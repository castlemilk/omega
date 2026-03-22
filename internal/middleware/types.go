// Package middleware provides a typed, interface-based middleware chain for
// Omega execution requests. It includes safety mechanisms (loop detection,
// autonomy gating, ring validation) and observability (metrics, memory injection).
package middleware

import "time"

// AutonomyLevel controls what actions a node is permitted to take.
type AutonomyLevel int

const (
	// AutonomyPICO permits only read-only actions.
	AutonomyPICO AutonomyLevel = iota
	// AutonomySupervisedLevel permits all actions but flags dangerous ones.
	AutonomySupervisedLevel
	// AutonomyAutonomous permits all actions without restrictions.
	AutonomyAutonomous
)

// ExecutionRequest is the input to a middleware chain execution.
type ExecutionRequest struct {
	// NodeID identifies the executing node.
	NodeID string
	// Action is the operation being requested.
	Action string
	// Payload carries the operation-specific data.
	Payload []byte
	// Metadata is an arbitrary key-value store for cross-cutting concerns.
	// Middleware may read from and write to this map.
	Metadata map[string]string
	// AutonomyLevel governs what the node is permitted to do.
	AutonomyLevel AutonomyLevel
	// Depth tracks the recursive execution depth.
	Depth int
}

// ExecutionResponse is the output from a middleware chain execution.
type ExecutionResponse struct {
	// Result holds the operation output.
	Result []byte
	// Metadata carries response-side annotations written by middleware.
	Metadata map[string]string
	// Duration is the total wall-clock time for the execution.
	Duration time.Duration
	// Error is a non-empty string when the execution failed.
	Error string
}
