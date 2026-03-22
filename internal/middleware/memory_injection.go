package middleware

import (
	"context"
	"log/slog"
)

const (
	MetaKeyMemoryContext   = "memory_context"
	MetaKeyMemoryLearnings = "memory_learnings"
)

// MemoryStore is the interface the MemoryInjectionMiddleware uses to interact
// with the memory subsystem. Implementations can be backed by a database,
// vector store, or any other persistence mechanism.
type MemoryStore interface {
	// QueryRelevant returns serialised memory context relevant to the given
	// node and action. An empty string is acceptable when no context is found.
	QueryRelevant(ctx context.Context, nodeID, action string) (string, error)

	// StoreLeaning persists a learning extracted from the execution response.
	// Implementations should be non-blocking where possible.
	StoreLearning(ctx context.Context, nodeID, action, learning string) error
}

// MemoryInjectionMiddleware injects relevant memories into request metadata
// before execution and extracts learnings from the response afterward.
//
// If either the query or storage call fails the middleware logs a warning
// but does not abort the chain — memory is advisory, not load-bearing.
type MemoryInjectionMiddleware struct {
	store MemoryStore
}

// NewMemoryInjectionMiddleware creates a MemoryInjectionMiddleware backed by
// the given MemoryStore. If store is nil the middleware is a no-op pass-through.
func NewMemoryInjectionMiddleware(store MemoryStore) *MemoryInjectionMiddleware {
	return &MemoryInjectionMiddleware{store: store}
}

// Process implements Middleware.
func (m *MemoryInjectionMiddleware) Process(ctx context.Context, req *ExecutionRequest, next NextFunc) (*ExecutionResponse, error) {
	if m.store == nil {
		return next(ctx, req)
	}

	// Pre-execution: inject relevant memories.
	memCtx, err := m.store.QueryRelevant(ctx, req.NodeID, req.Action)
	if err != nil {
		slog.WarnContext(ctx, "memory injection: failed to query relevant memories",
			"node_id", req.NodeID,
			"action", req.Action,
			"err", err,
		)
	} else if memCtx != "" {
		if req.Metadata == nil {
			req.Metadata = make(map[string]string)
		}
		req.Metadata[MetaKeyMemoryContext] = memCtx
	}

	resp, err := next(ctx, req)

	// Post-execution: extract learnings from response.
	if err == nil && resp != nil {
		if learning, ok := resp.Metadata[MetaKeyMemoryLearnings]; ok && learning != "" {
			if storeErr := m.store.StoreLearning(ctx, req.NodeID, req.Action, learning); storeErr != nil {
				slog.WarnContext(ctx, "memory injection: failed to store learning",
					"node_id", req.NodeID,
					"action", req.Action,
					"err", storeErr,
				)
			}
		}
	}

	return resp, err
}
