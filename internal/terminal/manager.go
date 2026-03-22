package terminal

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"

	"github.com/benebsworth/omega/internal/db"
	"github.com/benebsworth/omega/internal/telemetry"
)

// NewManager constructs a Manager with the given options.
func NewManager(opts ...Option) *Manager {
	m := &Manager{
		sessions: make(map[string]*Session),
		tracer:   otel.Tracer("omega.terminal"),
	}
	for _, o := range opts {
		o(m)
	}
	return m
}

// CreateSession creates and registers a new managed session.
func (m *Manager) CreateSession(ctx context.Context, cfg SessionConfig) (*Session, error) {
	if cfg.ID == "" {
		cfg.ID = uuid.NewString()
	}
	if cfg.AutonomyLevel == "" {
		cfg.AutonomyLevel = LevelPico
	}
	if cfg.MaxOutputSize <= 0 {
		cfg.MaxOutputSize = DefaultMaxOutputSize
	}
	if cfg.Timeout <= 0 {
		cfg.Timeout = DefaultSessionTimeout
	}
	if cfg.CmdTimeout <= 0 {
		cfg.CmdTimeout = DefaultCmdTimeout
	}

	sess := &Session{
		ID:        cfg.ID,
		Config:    cfg,
		CreatedAt: time.Now(),
		Status:    StatusActive,
	}

	m.mu.Lock()
	if _, exists := m.sessions[cfg.ID]; exists {
		m.mu.Unlock()
		return nil, fmt.Errorf("session %q already exists", cfg.ID)
	}
	m.sessions[cfg.ID] = sess
	m.mu.Unlock()

	// Session-level timeout — fires expireSession when it elapses.
	sess.timer = time.AfterFunc(cfg.Timeout, func() {
		_ = m.expireSession(context.Background(), cfg.ID) //nolint:errcheck
	})

	return sess, nil
}

// Execute runs a command in the named session and returns structured output.
func (m *Manager) Execute(ctx context.Context, req CommandRequest) (*CommandResult, error) {
	m.mu.RLock()
	sess, ok := m.sessions[req.SessionID]
	m.mu.RUnlock()
	if !ok {
		return nil, fmt.Errorf("session %q not found", req.SessionID)
	}

	sess.mu.Lock()
	status := sess.Status
	sess.mu.Unlock()
	if status != StatusActive {
		return nil, fmt.Errorf("session %q is %s", req.SessionID, status)
	}

	// Build the full command string used for safety checks.
	fullCmd := req.Command
	if len(req.Args) > 0 {
		fullCmd = req.Command + " " + strings.Join(req.Args, " ")
	}

	result := &CommandResult{
		SessionID: req.SessionID,
		Command:   req.Command,
	}

	// ── Safety checks ───────────────────────────────────────────────────────
	if isHardBlocked(fullCmd, sess.Config.BlockedCmds) {
		result.Error = fmt.Sprintf("command blocked (hard block): %q", fullCmd)
		return result, nil
	}
	if !isAllowedForLevel(fullCmd, sess.Config.AutonomyLevel, sess.Config.AllowedCmds) {
		result.Error = fmt.Sprintf("command not permitted at autonomy level %q: %q",
			sess.Config.AutonomyLevel, fullCmd)
		return result, nil
	}

	// ── OTel span ───────────────────────────────────────────────────────────
	ctx, span := m.tracer.Start(ctx, telemetry.SpanTerminalExec,
		trace.WithSpanKind(trace.SpanKindInternal))
	defer span.End()

	span.SetAttributes(
		telemetry.AttrTerminalSessionID.String(req.SessionID),
		telemetry.AttrTerminalCommand.String(fullCmd),
		telemetry.AttrTerminalAutonomyLevel.String(sess.Config.AutonomyLevel),
		telemetry.AttrTerminalCycleID.String(req.CycleID),
		telemetry.AttrTerminalBlocked.Bool(false),
	)

	traceID := span.SpanContext().TraceID().String()
	result.TraceID = traceID

	// ── Execution ───────────────────────────────────────────────────────────
	cmdCtx, cancel := context.WithTimeout(ctx, sess.Config.CmdTimeout)
	defer cancel()

	cmd := exec.CommandContext(cmdCtx, req.Command, req.Args...) //nolint:gosec
	cmd.Dir = sess.Config.WorkDir

	if len(sess.Config.Env) > 0 {
		env := make([]string, 0, len(sess.Config.Env))
		for k, v := range sess.Config.Env {
			env = append(env, k+"="+v)
		}
		cmd.Env = env
	}

	if req.Stdin != "" {
		cmd.Stdin = strings.NewReader(req.Stdin)
	}

	var stdoutBuf, stderrBuf bytes.Buffer
	cmd.Stdout = &stdoutBuf
	cmd.Stderr = &stderrBuf

	start := time.Now()
	runErr := cmd.Run()
	result.Duration = time.Since(start)

	result.Stdout = capOutput(stdoutBuf.String(), sess.Config.MaxOutputSize, &result.Truncated)
	result.Stderr = capOutput(stderrBuf.String(), sess.Config.MaxOutputSize, &result.Truncated)

	if cmd.ProcessState != nil {
		result.ExitCode = cmd.ProcessState.ExitCode()
	}
	if runErr != nil && result.ExitCode == 0 {
		result.ExitCode = 1
		result.Error = runErr.Error()
	}

	// ── Span outcome ────────────────────────────────────────────────────────
	span.SetAttributes(
		telemetry.AttrTerminalExitCode.Int(result.ExitCode),
		telemetry.AttrTerminalDurationMS.Int64(result.Duration.Milliseconds()),
	)
	if result.ExitCode != 0 {
		span.SetStatus(codes.Error, fmt.Sprintf("exit %d", result.ExitCode))
	} else {
		span.SetStatus(codes.Ok, "")
	}

	// ── Append to session command log ───────────────────────────────────────
	rec := commandRecord{
		id:         uuid.NewString(),
		command:    req.Command,
		args:       req.Args,
		exitCode:   result.ExitCode,
		stdout:     result.Stdout,
		stderr:     result.Stderr,
		duration:   result.Duration,
		truncated:  result.Truncated,
		executedAt: time.Now(),
		err:        result.Error,
		traceID:    traceID,
	}
	sess.mu.Lock()
	sess.commands = append(sess.commands, rec)
	sess.mu.Unlock()

	return result, nil
}

// CloseSession closes the session and flushes it to DB.
func (m *Manager) CloseSession(ctx context.Context, sessionID string) error {
	return m.closeSessionWithStatus(ctx, sessionID, StatusClosed)
}

// Shutdown closes all active sessions, flushing them to DB.
// Call from the HTTP server shutdown hook to avoid leaking session data.
func (m *Manager) Shutdown(ctx context.Context) error {
	m.mu.Lock()
	ids := make([]string, 0, len(m.sessions))
	for id := range m.sessions {
		ids = append(ids, id)
	}
	m.mu.Unlock()
	var firstErr error
	for _, id := range ids {
		if err := m.closeSessionWithStatus(ctx, id, StatusTimedOut); err != nil && firstErr == nil {
			firstErr = err
		}
	}
	return firstErr
}

// GetCommands returns a snapshot of all command results logged in an active session.
func (m *Manager) GetCommands(ctx context.Context, sessionID string) ([]CommandResult, error) {
	m.mu.RLock()
	sess, ok := m.sessions[sessionID]
	m.mu.RUnlock()
	if !ok {
		return nil, fmt.Errorf("session %q not found", sessionID)
	}
	sess.mu.Lock()
	recs := make([]commandRecord, len(sess.commands))
	copy(recs, sess.commands)
	sess.mu.Unlock()

	out := make([]CommandResult, 0, len(recs))
	for _, r := range recs {
		out = append(out, CommandResult{
			SessionID: sessionID,
			Command:   r.command,
			ExitCode:  r.exitCode,
			Stdout:    r.stdout,
			Stderr:    r.stderr,
			Duration:  r.duration,
			Truncated: r.truncated,
			Error:     r.err,
			TraceID:   r.traceID,
		})
	}
	return out, nil
}

// ListSessions returns all active sessions.
func (m *Manager) ListSessions(_ context.Context) []*Session {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := make([]*Session, 0, len(m.sessions))
	for _, s := range m.sessions {
		out = append(out, s)
	}
	return out
}

// GetSession retrieves an active session by ID.
func (m *Manager) GetSession(_ context.Context, id string) (*Session, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	if s, ok := m.sessions[id]; ok {
		return s, nil
	}
	return nil, fmt.Errorf("session %q not found", id)
}

// expireSession is called by the timeout timer.
func (m *Manager) expireSession(ctx context.Context, sessionID string) error {
	return m.closeSessionWithStatus(ctx, sessionID, StatusTimedOut)
}

func (m *Manager) closeSessionWithStatus(ctx context.Context, sessionID, status string) error {
	m.mu.Lock()
	sess, ok := m.sessions[sessionID]
	if ok {
		delete(m.sessions, sessionID)
	}
	m.mu.Unlock()
	if !ok {
		return fmt.Errorf("session %q not found", sessionID)
	}

	if sess.timer != nil {
		sess.timer.Stop()
	}

	sess.mu.Lock()
	sess.Status = status
	cmds := make([]commandRecord, len(sess.commands))
	copy(cmds, sess.commands)
	sess.mu.Unlock()

	if m.db == nil {
		return nil
	}

	rec := &db.TerminalSessionRecord{
		ID:            sess.ID,
		WorkDir:       sess.Config.WorkDir,
		AutonomyLevel: sess.Config.AutonomyLevel,
		Status:        status,
		CreatedAt:     float64(sess.CreatedAt.Unix()),
		ClosedAt:      float64(time.Now().Unix()),
	}
	if err := m.db.SaveTerminalSession(rec); err != nil {
		return fmt.Errorf("flush session to db: %w", err)
	}
	for _, c := range cmds {
		argsJSON, _ := json.Marshal(c.args) //nolint:errcheck
		cmdRec := &db.TerminalCommandRecord{
			ID:         c.id,
			SessionID:  sess.ID,
			Command:    c.command,
			Args:       string(argsJSON),
			ExitCode:   c.exitCode,
			Stdout:     c.stdout,
			Stderr:     c.stderr,
			DurationMS: c.duration.Milliseconds(),
			Truncated:  c.truncated,
			ExecutedAt: float64(c.executedAt.Unix()),
		}
		if err := m.db.SaveTerminalCommand(cmdRec); err != nil {
			return fmt.Errorf("flush command to db: %w", err)
		}
	}
	return nil
}

// capOutput truncates s to maxBytes and appends TruncationMarker.
func capOutput(s string, maxBytes int, truncated *bool) string {
	if len(s) <= maxBytes {
		return s
	}
	*truncated = true
	return s[:maxBytes] + TruncationMarker
}

// compile-time assertion: Manager methods use sync primitives correctly.
var _ sync.Locker = (*sync.Mutex)(nil)
