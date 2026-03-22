// Package terminal provides an LLM-mediated CLI terminal management system
// for Omega. Instead of raw exec.Command calls, handlers create managed
// sessions. The safety layer enforces autonomy-level command allowlists and
// a hard-blocked list. All executions emit OTel spans and are flushed to the
// state DB on session close or timeout.
package terminal

import (
	"sync"
	"time"

	"github.com/benebsworth/omega/internal/db"
	"go.opentelemetry.io/otel/trace"
)

const (
	StatusActive   = "active"
	StatusClosed   = "closed"
	StatusTimedOut = "timed_out"

	LevelPico       = "pico"
	LevelSupervised = "supervised"
	LevelAutonomous = "autonomous"

	DefaultMaxOutputSize  = 1 << 20 // 1 MiB
	DefaultSessionTimeout = 10 * time.Minute
	DefaultCmdTimeout     = 30 * time.Second
	TruncationMarker      = "\n[TRUNCATED]"
)

// SessionConfig configures a new terminal session.
type SessionConfig struct {
	ID            string
	WorkDir       string
	Env           map[string]string
	AllowedCmds   []string      // command prefix whitelist (empty = level default)
	BlockedCmds   []string      // extra blacklist entries (merged with defaults)
	Timeout       time.Duration // max session lifetime
	CmdTimeout    time.Duration // max per-command timeout
	AutonomyLevel string        // "pico" | "supervised" | "autonomous"
	MaxOutputSize int           // max bytes of output captured per command
}

// Session represents a managed terminal session.
type Session struct {
	ID        string
	Config    SessionConfig
	CreatedAt time.Time
	Status    string

	commands []commandRecord
	mu       sync.Mutex // guards commands and Status
	timer    *time.Timer
}

// commandRecord is an internal log entry for a single execution.
type commandRecord struct {
	id         string
	command    string
	args       []string
	exitCode   int
	stdout     string
	stderr     string
	duration   time.Duration
	truncated  bool
	executedAt time.Time
	err        string
	traceID    string
}

// CommandRequest is a structured request to execute a command.
type CommandRequest struct {
	SessionID string
	Command   string
	Args      []string
	Stdin     string
	Reason    string // LLM's reasoning for why this command is needed
	CycleID   string // omega cycle ID for traceability
}

// CommandResult is the structured output of a command execution.
type CommandResult struct {
	SessionID string
	Command   string
	ExitCode  int
	Stdout    string
	Stderr    string
	Duration  time.Duration
	Truncated bool
	Error     string // non-empty if command was blocked or failed to start
	TraceID   string // OTel trace ID for this execution
}

// Option is a functional option for Manager.
type Option func(*Manager)

// Manager manages terminal sessions.
type Manager struct {
	sessions map[string]*Session
	mu       sync.RWMutex
	tracer   trace.Tracer
	db       *db.DB // nil = no persistence
}

// WithDB enables hybrid persistence via the given StateDB.
func WithDB(database *db.DB) Option {
	return func(m *Manager) { m.db = database }
}

// WithTracer injects a custom OTel tracer (useful in tests).
func WithTracer(t trace.Tracer) Option {
	return func(m *Manager) { m.tracer = t }
}
