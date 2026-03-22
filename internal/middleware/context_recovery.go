package middleware

import (
	"context"
	"log/slog"
)

const (
	defaultDepthThreshold      = 10
	MetaKeyContextRecovery     = "context_recovery"
	metaValueRecoverySignal    = "true"
)

// ContextRecoveryMiddleware injects a recovery signal when execution depth
// exceeds a configurable threshold, indicating potential context loss.
type ContextRecoveryMiddleware struct {
	depthThreshold int
}

// NewContextRecoveryMiddleware creates a ContextRecoveryMiddleware.
// If threshold is ≤ 0 the default (10) is used.
func NewContextRecoveryMiddleware(threshold int) *ContextRecoveryMiddleware {
	if threshold <= 0 {
		threshold = defaultDepthThreshold
	}
	return &ContextRecoveryMiddleware{depthThreshold: threshold}
}

// Process implements Middleware.
func (m *ContextRecoveryMiddleware) Process(ctx context.Context, req *ExecutionRequest, next NextFunc) (*ExecutionResponse, error) {
	if req.Depth >= m.depthThreshold {
		slog.WarnContext(ctx, "context recovery: depth threshold exceeded, injecting recovery signal",
			"depth", req.Depth,
			"threshold", m.depthThreshold,
			"node_id", req.NodeID,
		)
		if req.Metadata == nil {
			req.Metadata = make(map[string]string)
		}
		req.Metadata[MetaKeyContextRecovery] = metaValueRecoverySignal
	}
	return next(ctx, req)
}
