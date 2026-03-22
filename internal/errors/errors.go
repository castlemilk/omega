// Package omegaerrs defines Omega-specific error types with Connect-RPC code mapping,
// error classification (retryable vs permanent), and structured context wrapping.
package omegaerrs

import (
	"errors"
	"fmt"
	"strings"

	"connectrpc.com/connect"
)

// ---------------------------------------------------------------------------
// Error classification
// ---------------------------------------------------------------------------

// ErrorClass enumerates the root cause categories for execution failures.
// Values match the ErrorClassification proto enum.
type ErrorClass int32

const (
	ErrorClassUnspecified        ErrorClass = 0
	ErrorClassTimeout            ErrorClass = 1
	ErrorClassDataQuality        ErrorClass = 2
	ErrorClassDependencyFailure  ErrorClass = 3
	ErrorClassResourceExhaustion ErrorClass = 4
	ErrorClassValidationError    ErrorClass = 5
	ErrorClassLLMError           ErrorClass = 6
	ErrorClassUnknown            ErrorClass = 7
)

// Classification holds the structured error classification for an execution failure.
type Classification struct {
	Class     ErrorClass
	Code      string // machine-readable sub-code, e.g. "circuit_open"
	Retryable bool
}

// Classify inspects err and returns a structured Classification.
// It checks sentinel types first, then falls back to string heuristics.
func Classify(err error) Classification {
	if err == nil {
		return Classification{Class: ErrorClassUnspecified}
	}

	// Structured OmegaError — use its code and retryability.
	var oe *OmegaError
	if errors.As(err, &oe) {
		return Classification{
			Class:     classFromConnectCode(oe.Code),
			Code:      codeFromOmegaError(oe),
			Retryable: oe.Retryable,
		}
	}

	// Connect-RPC error — classify by status code.
	var ce *connect.Error
	if errors.As(err, &ce) {
		return Classification{
			Class:     classFromConnectCode(ce.Code()),
			Code:      connectCodeName(ce.Code()),
			Retryable: isRetryableCode(ce.Code()),
		}
	}

	// Sentinel checks.
	switch {
	case errors.Is(err, ErrCircuitOpen):
		return Classification{Class: ErrorClassDependencyFailure, Code: "circuit_open", Retryable: true}
	case errors.Is(err, ErrCycleTimeout):
		return Classification{Class: ErrorClassTimeout, Code: "cycle_timeout", Retryable: true}
	case errors.Is(err, ErrSafetyViolation):
		return Classification{Class: ErrorClassValidationError, Code: "safety_violation", Retryable: false}
	case errors.Is(err, ErrConstitutionalBlock):
		return Classification{Class: ErrorClassValidationError, Code: "constitutional_block", Retryable: false}
	case errors.Is(err, ErrNodeNotFound):
		return Classification{Class: ErrorClassDependencyFailure, Code: "node_not_found", Retryable: false}
	case errors.Is(err, ErrMemoryCapacity):
		return Classification{Class: ErrorClassResourceExhaustion, Code: "memory_capacity", Retryable: true}
	}

	// String heuristics as last resort.
	msg := strings.ToLower(err.Error())
	switch {
	case strings.Contains(msg, "context deadline exceeded") || strings.Contains(msg, "deadline exceeded") || strings.Contains(msg, "timeout"):
		return Classification{Class: ErrorClassTimeout, Code: "deadline_exceeded", Retryable: true}
	case strings.Contains(msg, "connection refused") || strings.Contains(msg, "no such host") || strings.Contains(msg, "connection reset"):
		return Classification{Class: ErrorClassDependencyFailure, Code: "connection_refused", Retryable: true}
	case strings.Contains(msg, "circuit open"):
		return Classification{Class: ErrorClassDependencyFailure, Code: "circuit_open", Retryable: true}
	case strings.Contains(msg, "resource exhausted") || strings.Contains(msg, "out of memory") || strings.Contains(msg, "too many requests"):
		return Classification{Class: ErrorClassResourceExhaustion, Code: "resource_exhausted", Retryable: true}
	case strings.Contains(msg, "llm") || strings.Contains(msg, "model") || strings.Contains(msg, "token limit") || strings.Contains(msg, "rate limit"):
		return Classification{Class: ErrorClassLLMError, Code: "llm_error", Retryable: true}
	case strings.Contains(msg, "invalid") || strings.Contains(msg, "validation") || strings.Contains(msg, "malformed"):
		return Classification{Class: ErrorClassValidationError, Code: "validation_error", Retryable: false}
	case strings.Contains(msg, "data quality") || strings.Contains(msg, "stale data") || strings.Contains(msg, "missing data"):
		return Classification{Class: ErrorClassDataQuality, Code: "data_quality", Retryable: false}
	}

	return Classification{Class: ErrorClassUnknown, Code: "unknown", Retryable: false}
}

func classFromConnectCode(code connect.Code) ErrorClass {
	switch code {
	case connect.CodeDeadlineExceeded:
		return ErrorClassTimeout
	case connect.CodeUnavailable, connect.CodeNotFound:
		return ErrorClassDependencyFailure
	case connect.CodeResourceExhausted:
		return ErrorClassResourceExhaustion
	case connect.CodeFailedPrecondition, connect.CodeInvalidArgument, connect.CodePermissionDenied:
		return ErrorClassValidationError
	case connect.CodeAborted:
		return ErrorClassDependencyFailure
	default:
		return ErrorClassUnknown
	}
}

func codeFromOmegaError(oe *OmegaError) string {
	if oe.Op != "" {
		// Convert op like "circuit.mynode" → "circuit_open"
		if strings.HasPrefix(oe.Op, "circuit.") {
			return "circuit_open"
		}
		return strings.ReplaceAll(oe.Op, ".", "_")
	}
	return connectCodeName(oe.Code)
}

func connectCodeName(code connect.Code) string {
	switch code {
	case connect.CodeDeadlineExceeded:
		return "deadline_exceeded"
	case connect.CodeUnavailable:
		return "unavailable"
	case connect.CodeNotFound:
		return "not_found"
	case connect.CodeResourceExhausted:
		return "resource_exhausted"
	case connect.CodeFailedPrecondition:
		return "failed_precondition"
	case connect.CodeInvalidArgument:
		return "invalid_argument"
	case connect.CodeAborted:
		return "aborted"
	default:
		return "unknown"
	}
}

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
