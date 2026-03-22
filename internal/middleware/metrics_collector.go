package middleware

import (
	"context"
	"sync/atomic"
	"time"
)

// Counters holds atomic execution counters for the MetricsCollectorMiddleware.
type Counters struct {
	Total   atomic.Int64
	Success atomic.Int64
	Errors  atomic.Int64
}

// MetricsCollectorMiddleware records wall-clock duration and increments
// counters for total, successful, and failed executions.
// The measured Duration is written to the ExecutionResponse.
type MetricsCollectorMiddleware struct {
	counters *Counters
}

// NewMetricsCollectorMiddleware creates a MetricsCollectorMiddleware backed
// by the provided Counters. Pass a new(Counters) if you don't need to share
// counters across multiple chains.
func NewMetricsCollectorMiddleware(c *Counters) *MetricsCollectorMiddleware {
	if c == nil {
		c = new(Counters)
	}
	return &MetricsCollectorMiddleware{counters: c}
}

// GetCounters returns the underlying Counters so callers can read metrics.
func (m *MetricsCollectorMiddleware) GetCounters() *Counters {
	return m.counters
}

// Process implements Middleware.
func (m *MetricsCollectorMiddleware) Process(ctx context.Context, req *ExecutionRequest, next NextFunc) (*ExecutionResponse, error) {
	start := time.Now()
	m.counters.Total.Add(1)

	resp, err := next(ctx, req)

	dur := time.Since(start)

	if err != nil {
		m.counters.Errors.Add(1)
	} else {
		m.counters.Success.Add(1)
		if resp != nil {
			resp.Duration = dur
		}
	}

	return resp, err
}
