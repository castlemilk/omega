package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/types/known/timestamppb"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/db"
	"github.com/benebsworth/omega/internal/terminal"
)

// Ensure interface satisfaction at compile time.
var _ omegav1connect.TerminalServiceHandler = (*TerminalHandler)(nil)

// TerminalHandler implements TerminalService — sandboxed LLM terminal sessions
// with autonomy-gated command execution and hybrid SQLite persistence.
type TerminalHandler struct {
	manager *terminal.Manager
	db      *db.DB
}

// NewTerminal creates a TerminalHandler backed by the given Manager.
func NewTerminal(m *terminal.Manager, database *db.DB) *TerminalHandler {
	return &TerminalHandler{manager: m, db: database}
}

// ── CreateSession ─────────────────────────────────────────────────────────────

func (h *TerminalHandler) CreateSession(
	ctx context.Context,
	req *connect.Request[omegav1.CreateSessionRequest],
) (*connect.Response[omegav1.CreateSessionResponse], error) {
	cfg := protoToSessionConfig(req.Msg.Config)
	sess, err := h.manager.CreateSession(ctx, cfg)
	if err != nil {
		return nil, connect.NewError(connect.CodeAlreadyExists, err)
	}
	return connect.NewResponse(&omegav1.CreateSessionResponse{
		Session: sessionToProto(sess),
	}), nil
}

// ── ExecuteCommand ────────────────────────────────────────────────────────────

func (h *TerminalHandler) ExecuteCommand(
	ctx context.Context,
	req *connect.Request[omegav1.ExecuteCommandRequest],
) (*connect.Response[omegav1.ExecuteCommandResponse], error) {
	cmdReq := terminal.CommandRequest{
		SessionID: req.Msg.SessionId,
		Command:   req.Msg.Command,
		Args:      req.Msg.Args,
		Stdin:     req.Msg.Stdin,
		Reason:    req.Msg.Reason,
		CycleID:   req.Msg.CycleId,
	}
	result, err := h.manager.Execute(ctx, cmdReq)
	if err != nil {
		return nil, connect.NewError(connect.CodeNotFound, err)
	}
	return connect.NewResponse(&omegav1.ExecuteCommandResponse{
		SessionId:  result.SessionID,
		Command:    result.Command,
		ExitCode:   int32(result.ExitCode), //nolint:gosec
		Stdout:     result.Stdout,
		Stderr:     result.Stderr,
		DurationMs: result.Duration.Milliseconds(),
		Truncated:  result.Truncated,
		Error:      result.Error,
		TraceId:    result.TraceID,
	}), nil
}

// ── CloseSession ──────────────────────────────────────────────────────────────

func (h *TerminalHandler) CloseSession(
	ctx context.Context,
	req *connect.Request[omegav1.CloseSessionRequest],
) (*connect.Response[omegav1.CloseSessionResponse], error) {
	if err := h.manager.CloseSession(ctx, req.Msg.SessionId); err != nil {
		return nil, connect.NewError(connect.CodeNotFound, err)
	}
	return connect.NewResponse(&omegav1.CloseSessionResponse{Ok: true}), nil
}

// ── ListSessions ──────────────────────────────────────────────────────────────

func (h *TerminalHandler) ListSessions(
	ctx context.Context,
	_ *connect.Request[omegav1.ListSessionsRequest],
) (*connect.Response[omegav1.ListSessionsResponse], error) {
	sessions := h.manager.ListSessions(ctx)
	proto := make([]*omegav1.TerminalSession, 0, len(sessions))
	for _, s := range sessions {
		proto = append(proto, sessionToProto(s))
	}
	return connect.NewResponse(&omegav1.ListSessionsResponse{Sessions: proto}), nil
}

// ── GetSessionHistory ─────────────────────────────────────────────────────────

func (h *TerminalHandler) GetSessionHistory(
	ctx context.Context,
	req *connect.Request[omegav1.GetSessionHistoryRequest],
) (*connect.Response[omegav1.GetSessionHistoryResponse], error) {
	// Check in-memory first (active session).
	if sess, err := h.manager.GetSession(ctx, req.Msg.SessionId); err == nil {
		cmds, _ := h.manager.GetCommands(ctx, req.Msg.SessionId) //nolint:errcheck
		protoCmds := make([]*omegav1.ExecuteCommandResponse, 0, len(cmds))
		for _, c := range cmds {
			protoCmds = append(protoCmds, &omegav1.ExecuteCommandResponse{
				SessionId:  sess.ID,
				Command:    c.Command,
				ExitCode:   int32(c.ExitCode), //nolint:gosec
				Stdout:     c.Stdout,
				Stderr:     c.Stderr,
				DurationMs: c.Duration.Milliseconds(),
				Truncated:  c.Truncated,
				Error:      c.Error,
				TraceId:    c.TraceID,
			})
		}
		return connect.NewResponse(&omegav1.GetSessionHistoryResponse{
			Session:  sessionToProto(sess),
			Commands: protoCmds,
		}), nil
	}

	// Fall back to DB (closed/timed-out session).
	if h.db == nil {
		return nil, connect.NewError(connect.CodeNotFound,
			fmt.Errorf("session %q not found", req.Msg.SessionId))
	}
	dbSess, err := h.db.GetTerminalSession(req.Msg.SessionId)
	if err != nil || dbSess == nil {
		return nil, connect.NewError(connect.CodeNotFound,
			fmt.Errorf("session %q not found", req.Msg.SessionId))
	}
	cmds, err := h.db.GetTerminalCommands(req.Msg.SessionId)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	protoCmds := make([]*omegav1.ExecuteCommandResponse, 0, len(cmds))
	for _, c := range cmds {
		var args []string
		_ = json.Unmarshal([]byte(c.Args), &args) //nolint:errcheck
		protoCmds = append(protoCmds, &omegav1.ExecuteCommandResponse{
			SessionId:  c.SessionID,
			Command:    c.Command,
			ExitCode:   int32(c.ExitCode), //nolint:gosec
			Stdout:     c.Stdout,
			Stderr:     c.Stderr,
			DurationMs: c.DurationMS,
			Truncated:  c.Truncated,
		})
	}

	protoSess := &omegav1.TerminalSession{
		Id:     dbSess.ID,
		Status: dbSess.Status,
		Config: &omegav1.SessionConfig{
			SessionId:     dbSess.ID,
			WorkDir:       dbSess.WorkDir,
			AutonomyLevel: dbSess.AutonomyLevel,
		},
		CreatedAt: timestamppb.New(time.Unix(int64(dbSess.CreatedAt), 0)), //nolint:gosec
	}

	return connect.NewResponse(&omegav1.GetSessionHistoryResponse{
		Session:  protoSess,
		Commands: protoCmds,
	}), nil
}

// ── helpers ───────────────────────────────────────────────────────────────────

func protoToSessionConfig(p *omegav1.SessionConfig) terminal.SessionConfig {
	if p == nil {
		return terminal.SessionConfig{}
	}
	env := make(map[string]string, len(p.Env))
	for k, v := range p.Env {
		env[k] = v
	}
	return terminal.SessionConfig{
		ID:            p.SessionId,
		WorkDir:       p.WorkDir,
		Env:           env,
		AllowedCmds:   p.AllowedCmds,
		BlockedCmds:   p.BlockedCmds,
		Timeout:       time.Duration(p.TimeoutSeconds) * time.Second,
		CmdTimeout:    time.Duration(p.CmdTimeoutSeconds) * time.Second,
		AutonomyLevel: p.AutonomyLevel,
		MaxOutputSize: int(p.MaxOutputBytes), //nolint:gosec
	}
}

func sessionToProto(s *terminal.Session) *omegav1.TerminalSession {
	return &omegav1.TerminalSession{
		Id:        s.ID,
		Status:    s.Status,
		CreatedAt: timestamppb.New(s.CreatedAt),
		Config: &omegav1.SessionConfig{
			SessionId:     s.Config.ID,
			WorkDir:       s.Config.WorkDir,
			AllowedCmds:   s.Config.AllowedCmds,
			BlockedCmds:   s.Config.BlockedCmds,
			AutonomyLevel: s.Config.AutonomyLevel,
		},
	}
}
