package middleware

import (
	"context"
	"log/slog"
)

// highRiskActions is the set of actions that trigger adversarial ring validation
// when executed at AutonomySupervisedLevel or above.
var highRiskActions = map[string]bool{
	"deploy":         true,
	"execute":        true,
	"override":       true,
	"delete":         true,
	"drop":           true,
	"shutdown":       true,
	"restart":        true,
	"promote":        true,
	"escalate":       true,
	"modify_config":  true,
}

const MetaKeyRingValidationRequired = "ring_validation_required"

// RingValidationMiddleware sets a metadata flag to trigger adversarial ring
// validation when the request autonomy level is at least SUPERVISED and the
// action is classified as high-risk.
type RingValidationMiddleware struct{}

// NewRingValidationMiddleware creates a RingValidationMiddleware.
func NewRingValidationMiddleware() *RingValidationMiddleware {
	return &RingValidationMiddleware{}
}

// Process implements Middleware.
func (m *RingValidationMiddleware) Process(ctx context.Context, req *ExecutionRequest, next NextFunc) (*ExecutionResponse, error) {
	if req.AutonomyLevel >= AutonomySupervisedLevel && highRiskActions[req.Action] {
		slog.InfoContext(ctx, "ring validation: high-risk action detected, flagging for adversarial validation",
			"node_id", req.NodeID,
			"action", req.Action,
			"autonomy_level", req.AutonomyLevel,
		)
		if req.Metadata == nil {
			req.Metadata = make(map[string]string)
		}
		req.Metadata[MetaKeyRingValidationRequired] = req.Action
	}
	return next(ctx, req)
}
