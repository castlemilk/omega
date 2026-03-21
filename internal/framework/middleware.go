package framework

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"
)

// ── Core types ────────────────────────────────────────────────────────────────

// HandlerFunc is the unit of work threaded through a middleware chain.
type HandlerFunc func(ctx context.Context, req any) (any, error)

// Middleware wraps a HandlerFunc to add cross-cutting concerns.
type Middleware func(next HandlerFunc) HandlerFunc

// ── Chain ─────────────────────────────────────────────────────────────────────

// Chain composes an ordered slice of Middleware into a single decorator.
// The first middleware in the slice is the outermost wrapper (runs first on
// the way in, last on the way out).
type Chain struct {
	middlewares []Middleware
}

// NewChain creates a Chain from the given middlewares in left-to-right wrapping order.
func NewChain(mws ...Middleware) Chain {
	return Chain{middlewares: append([]Middleware{}, mws...)}
}

// Then wraps handler with all middlewares in the chain.
func (c Chain) Then(handler HandlerFunc) HandlerFunc {
	// Apply in reverse so that the first middleware is the outer-most layer.
	h := handler
	for i := len(c.middlewares) - 1; i >= 0; i-- {
		h = c.middlewares[i](h)
	}
	return h
}

// ── Pre-built middleware ───────────────────────────────────────────────────────

// LoggingMiddleware logs operation name, duration, and outcome via slog.
func LoggingMiddleware(operation string) Middleware {
	return func(next HandlerFunc) HandlerFunc {
		return func(ctx context.Context, req any) (any, error) {
			start := time.Now()
			resp, err := next(ctx, req)
			dur := time.Since(start)
			if err != nil {
				slog.InfoContext(ctx, "operation completed",
					"op", operation, "duration", dur, "ok", false, "err", err)
			} else {
				slog.InfoContext(ctx, "operation completed",
					"op", operation, "duration", dur, "ok", true)
			}
			return resp, err
		}
	}
}

// MetricsRecordFunc is called by MetricsMiddleware after each invocation.
// op is the operation name, success indicates no error, dur is the wall time.
type MetricsRecordFunc func(op string, success bool, dur time.Duration)

// MetricsMiddleware calls record after each invocation.
func MetricsMiddleware(operation string, record MetricsRecordFunc) Middleware {
	return func(next HandlerFunc) HandlerFunc {
		return func(ctx context.Context, req any) (any, error) {
			start := time.Now()
			resp, err := next(ctx, req)
			record(operation, err == nil, time.Since(start))
			return resp, err
		}
	}
}

// TracingMiddleware injects a simple trace-id into the context and logs spans.
// In production you would replace this with an OpenTelemetry exporter.
func TracingMiddleware(service, operation string) Middleware {
	return func(next HandlerFunc) HandlerFunc {
		return func(ctx context.Context, req any) (any, error) {
			start := time.Now()
			resp, err := next(ctx, req)
			dur := time.Since(start)
			slog.InfoContext(ctx, "trace span",
				"service", service, "op", operation, "duration_ms", dur.Milliseconds(), "ok", err == nil)
			return resp, err
		}
	}
}

// ── Rate limiter ──────────────────────────────────────────────────────────────

// ErrRateLimited is returned when a request exceeds the configured rate.
var ErrRateLimited = errors.New("framework: rate limit exceeded")

// tokenBucket is a minimal token-bucket rate limiter.
type tokenBucket struct {
	mu       sync.Mutex
	tokens   int
	capacity int
	refill   time.Duration
	last     time.Time
}

func newTokenBucket(capacity int, refill time.Duration) *tokenBucket {
	return &tokenBucket{
		tokens:   capacity,
		capacity: capacity,
		refill:   refill,
		last:     time.Now(),
	}
}

func (b *tokenBucket) allow() bool {
	b.mu.Lock()
	defer b.mu.Unlock()

	now := time.Now()
	elapsed := now.Sub(b.last)
	// Refill tokens proportional to elapsed time.
	added := int(float64(elapsed) / float64(b.refill) * float64(b.capacity))
	if added > 0 {
		b.tokens += added
		if b.tokens > b.capacity {
			b.tokens = b.capacity
		}
		b.last = now
	}

	if b.tokens <= 0 {
		return false
	}
	b.tokens--
	return true
}

// RateLimitMiddleware limits to capacity calls per window. Excess calls
// receive ErrRateLimited without invoking the handler.
func RateLimitMiddleware(capacity int, window time.Duration) Middleware {
	bucket := newTokenBucket(capacity, window)
	return func(next HandlerFunc) HandlerFunc {
		return func(ctx context.Context, req any) (any, error) {
			if !bucket.allow() {
				return nil, ErrRateLimited
			}
			return next(ctx, req)
		}
	}
}

// ── Circuit breaker ───────────────────────────────────────────────────────────

// ErrCircuitOpen is returned when the circuit breaker is open.
var ErrCircuitOpen = errors.New("framework: circuit breaker open")

type circuitState int

const (
	circuitClosed   circuitState = iota // normal — requests pass through
	circuitOpen                         // failing — requests blocked
	circuitHalfOpen                     // probe — one request allowed to test recovery
)

type circuitBreaker struct {
	mu           sync.Mutex
	operation    string
	threshold    int
	halfOpenAfter time.Duration
	failures     int
	state        circuitState
	openedAt     time.Time
}

// CircuitBreakerMiddleware opens the circuit after threshold consecutive
// failures and allows one probe after halfOpenAfter elapses.
func CircuitBreakerMiddleware(operation string, threshold int, halfOpenAfter time.Duration) Middleware {
	cb := &circuitBreaker{
		operation:    operation,
		threshold:    threshold,
		halfOpenAfter: halfOpenAfter,
	}
	return func(next HandlerFunc) HandlerFunc {
		return func(ctx context.Context, req any) (any, error) {
			if err := cb.allow(); err != nil {
				return nil, err
			}
			resp, err := next(ctx, req)
			cb.record(err)
			return resp, err
		}
	}
}

func (cb *circuitBreaker) allow() error {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	switch cb.state {
	case circuitClosed:
		return nil
	case circuitOpen:
		if time.Since(cb.openedAt) >= cb.halfOpenAfter {
			cb.state = circuitHalfOpen
			return nil // let the probe through
		}
		return fmt.Errorf("%w: operation %q", ErrCircuitOpen, cb.operation)
	case circuitHalfOpen:
		// Allow only one probe at a time; subsequent calls are blocked.
		return fmt.Errorf("%w: operation %q (half-open probe in progress)", ErrCircuitOpen, cb.operation)
	}
	return nil
}

func (cb *circuitBreaker) record(err error) {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	if err != nil {
		cb.failures++
		if cb.state == circuitHalfOpen || cb.failures >= cb.threshold {
			cb.state = circuitOpen
			cb.openedAt = time.Now()
		}
	} else {
		// Success closes the circuit.
		cb.failures = 0
		cb.state = circuitClosed
	}
}
