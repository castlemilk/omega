// Package omegaerrs defines Omega-specific error types with Connect-RPC code mapping,
// error classification (retryable vs permanent), and structured context wrapping.
package omegaerrs

import (
	"errors"
	"fmt"

	"connectrpc.com/connect"
)

// ---------------------------------------------------------------------------
// Sentinel errors
// ---------------------------------------------------------------------------

// ErrNodeNotFound is returned when a node ID cannot be found in the registry.
var ErrNodeNotFound = errors.New("node not found")

// ErrCycleTimeout is returned when an orchestration cycle exceeds its deadline.
var ErrCycleTimeout = errors.New("cycle timeout")

// ErrSafetyViolation is returned when a hard safety constraint is breached.
var ErrSafetyViolation = errors.New("safety violation")

// ErrCircuitOpen is returned when a circuit breaker is open and rejects the call.
var ErrCircuitOpen = errors.New("circuit open")

// ErrConstitutionalBlock is returned when constitutional constraints block an action.
var ErrConstitutionalBlock = errors.New("constitutional block")

// ErrMemoryCapacity is returned when a memory store is at capacity.
var ErrMemoryCapacity = errors.New("memory capacity exceeded")

// ErrImprovementInProgress is returned when a second improvement is started for a node already being improved.
var ErrImprovementInProgress = errors.New("improvement already in progress")

// ---------------------------------------------------------------------------
// OmegaError — structured error with context
// ---------------------------------------------------------------------------

// OmegaError wraps an error with structured context for logging and classification.
type OmegaError struct {
	Code      connect.Code
	Retryable bool
	Cause     error
	NodeID    string
	Op        string // short description of the failing operation
	Detail    string // additional human-readable context
}

func (e *OmegaError) Error() string {
	if e.NodeID != "" {
		return fmt.Sprintf("[%s] %s: %v (node=%s)", e.Op, e.Detail, e.Cause, e.NodeID)
	}
	return fmt.Sprintf("[%s] %s: %v", e.Op, e.Detail, e.Cause)
}

func (e *OmegaError) Unwrap() error { return e.Cause }

// ToConnect converts the OmegaError to a Connect-RPC error.
func (e *OmegaError) ToConnect() error {
	return connect.NewError(e.Code, e)
}

// ---------------------------------------------------------------------------
// Constructor helpers
// ---------------------------------------------------------------------------

// NodeNotFound wraps ErrNodeNotFound with the given node ID.
func NodeNotFound(nodeID string) *OmegaError {
	return &OmegaError{
		Code:      connect.CodeNotFound,
		Retryable: false,
		Cause:     ErrNodeNotFound,
		NodeID:    nodeID,
		Op:        "registry.lookup",
		Detail:    "node not found",
	}
}

// CycleTimeout wraps ErrCycleTimeout for the given operation.
func CycleTimeout(op string) *OmegaError {
	return &OmegaError{
		Code:      connect.CodeDeadlineExceeded,
		Retryable: true,
		Cause:     ErrCycleTimeout,
		Op:        op,
		Detail:    "cycle exceeded deadline",
	}
}

// SafetyViolation wraps ErrSafetyViolation with the violated constraint name.
func SafetyViolation(constraint string) *OmegaError {
	return &OmegaError{
		Code:      connect.CodeFailedPrecondition,
		Retryable: false,
		Cause:     ErrSafetyViolation,
		Op:        "alignment.check",
		Detail:    fmt.Sprintf("safety constraint violated: %s", constraint),
	}
}

// CircuitOpen wraps ErrCircuitOpen for the named circuit.
func CircuitOpen(circuit string) *OmegaError {
	return &OmegaError{
		Code:      connect.CodeUnavailable,
		Retryable: true,
		Cause:     ErrCircuitOpen,
		Op:        "circuit." + circuit,
		Detail:    "circuit breaker is open",
	}
}

// ConstitutionalBlock wraps ErrConstitutionalBlock for the given reason.
func ConstitutionalBlock(nodeID, reason string) *OmegaError {
	return &OmegaError{
		Code:      connect.CodeFailedPrecondition,
		Retryable: false,
		Cause:     ErrConstitutionalBlock,
		NodeID:    nodeID,
		Op:        "goals.constitutional",
		Detail:    reason,
	}
}

// Wrap attaches a Connect code and operation context to any error.
func Wrap(code connect.Code, op, detail string, cause error) *OmegaError {
	return &OmegaError{
		Code:      code,
		Retryable: isRetryableCode(code),
		Cause:     cause,
		Op:        op,
		Detail:    detail,
	}
}

// ---------------------------------------------------------------------------
// Classification helpers
// ---------------------------------------------------------------------------

// IsRetryable reports whether err represents a transient, retryable condition.
func IsRetryable(err error) bool {
	var oe *OmegaError
	if errors.As(err, &oe) {
		return oe.Retryable
	}
	// Classify Connect errors by code.
	var ce *connect.Error
	if errors.As(err, &ce) {
		return isRetryableCode(ce.Code())
	}
	return false
}

// IsSafetyViolation reports whether err (or any wrapped error) is ErrSafetyViolation.
func IsSafetyViolation(err error) bool {
	return errors.Is(err, ErrSafetyViolation)
}

// IsNodeNotFound reports whether err (or any wrapped error) is ErrNodeNotFound.
func IsNodeNotFound(err error) bool {
	return errors.Is(err, ErrNodeNotFound)
}

// IsCircuitOpen reports whether err (or any wrapped error) is ErrCircuitOpen.
func IsCircuitOpen(err error) bool {
	return errors.Is(err, ErrCircuitOpen)
}

// ConnectCode extracts the Connect error code from err, or CodeUnknown if none.
func ConnectCode(err error) connect.Code {
	var oe *OmegaError
	if errors.As(err, &oe) {
		return oe.Code
	}
	var ce *connect.Error
	if errors.As(err, &ce) {
		return ce.Code()
	}
	return connect.CodeUnknown
}

func isRetryableCode(code connect.Code) bool {
	switch code {
	case connect.CodeUnavailable,
		connect.CodeDeadlineExceeded,
		connect.CodeResourceExhausted,
		connect.CodeAborted:
		return true
	default:
		return false
	}
}
