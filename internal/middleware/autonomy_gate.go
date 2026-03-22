package middleware

import (
	"context"
	"fmt"
	"log/slog"
)

// readOnlyActions is the set of actions permitted under AutonomyPICO.
var readOnlyActions = map[string]bool{
	"read":   true,
	"list":   true,
	"get":    true,
	"query":  true,
	"fetch":  true,
	"status": true,
	"ping":   true,
	"health": true,
}

// dangerousActions are flagged (but not blocked) under AutonomySupervisedLevel.
var dangerousActions = map[string]bool{
	"delete":   true,
	"drop":     true,
	"truncate": true,
	"execute":  true,
	"deploy":   true,
	"shutdown": true,
	"restart":  true,
	"override": true,
}

const MetaKeyDangerousFlagged = "autonomy_dangerous_flagged"

// AutonomyGateMiddleware enforces action permissions based on the request's
// AutonomyLevel.
//
//   - PICO:       only read-only actions are allowed; all others are rejected.
//   - SUPERVISED: all actions proceed, but dangerous ones are flagged in metadata.
//   - AUTONOMOUS: all actions proceed without restriction.
type AutonomyGateMiddleware struct{}

// NewAutonomyGateMiddleware creates an AutonomyGateMiddleware.
func NewAutonomyGateMiddleware() *AutonomyGateMiddleware {
	return &AutonomyGateMiddleware{}
}

// Process implements Middleware.
func (m *AutonomyGateMiddleware) Process(ctx context.Context, req *ExecutionRequest, next NextFunc) (*ExecutionResponse, error) {
	switch req.AutonomyLevel {
	case AutonomyPICO:
		if !readOnlyActions[req.Action] {
			return nil, fmt.Errorf("autonomy gate: action %q is not permitted at PICO autonomy level (node %q)",
				req.Action, req.NodeID)
		}

	case AutonomySupervisedLevel:
		if dangerousActions[req.Action] {
			slog.WarnContext(ctx, "autonomy gate: dangerous action flagged under SUPERVISED level",
				"node_id", req.NodeID,
				"action", req.Action,
			)
			if req.Metadata == nil {
				req.Metadata = make(map[string]string)
			}
			req.Metadata[MetaKeyDangerousFlagged] = req.Action
		}

	case AutonomyAutonomous:
		// No restrictions.
	}

	return next(ctx, req)
}
