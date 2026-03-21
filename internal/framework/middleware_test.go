package framework_test

import (
	"context"
	"errors"
	"sync/atomic"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/framework"
)

func TestChain_ExecutesInOrder(t *testing.T) {
	var order []string

	mw1 := func(next framework.HandlerFunc) framework.HandlerFunc {
		return func(ctx context.Context, req any) (any, error) {
			order = append(order, "mw1-before")
			resp, err := next(ctx, req)
			order = append(order, "mw1-after")
			return resp, err
		}
	}

	mw2 := func(next framework.HandlerFunc) framework.HandlerFunc {
		return func(ctx context.Context, req any) (any, error) {
			order = append(order, "mw2-before")
			resp, err := next(ctx, req)
			order = append(order, "mw2-after")
			return resp, err
		}
	}

	handler := func(_ context.Context, req any) (any, error) {
		order = append(order, "handler")
		return "ok", nil
	}

	chain := framework.NewChain(mw1, mw2)
	wrapped := chain.Then(handler)

	resp, err := wrapped(context.Background(), nil)
	if err != nil {
		t.Fatal(err)
	}
	if resp != "ok" {
		t.Fatalf("expected 'ok', got %v", resp)
	}

	expected := []string{"mw1-before", "mw2-before", "handler", "mw2-after", "mw1-after"}
	if len(order) != len(expected) {
		t.Fatalf("expected order %v, got %v", expected, order)
	}
	for i, v := range expected {
		if order[i] != v {
			t.Fatalf("at [%d] expected %q, got %q", i, v, order[i])
		}
	}
}

func TestChain_PropagatesError(t *testing.T) {
	sentinel := errors.New("handler error")

	mw := func(next framework.HandlerFunc) framework.HandlerFunc {
		return func(ctx context.Context, req any) (any, error) {
			return next(ctx, req)
		}
	}

	handler := func(_ context.Context, _ any) (any, error) {
		return nil, sentinel
	}

	chain := framework.NewChain(mw)
	wrapped := chain.Then(handler)

	_, err := wrapped(context.Background(), nil)
	if !errors.Is(err, sentinel) {
		t.Fatalf("expected sentinel error, got %v", err)
	}
}

func TestLoggingMiddleware_DoesNotAlterResponse(t *testing.T) {
	handler := func(_ context.Context, req any) (any, error) {
		return "result", nil
	}

	chain := framework.NewChain(framework.LoggingMiddleware("test-op"))
	wrapped := chain.Then(handler)

	resp, err := wrapped(context.Background(), "input")
	if err != nil {
		t.Fatal(err)
	}
	if resp != "result" {
		t.Fatalf("expected 'result', got %v", resp)
	}
}

func TestMetricsMiddleware_CountsSuccess(t *testing.T) {
	var successCount atomic.Int64

	counter := func(op string, success bool, _ time.Duration) {
		if success {
			successCount.Add(1)
		}
	}

	handler := func(_ context.Context, _ any) (any, error) {
		return "ok", nil
	}

	chain := framework.NewChain(framework.MetricsMiddleware("op", counter))
	wrapped := chain.Then(handler)

	_, _ = wrapped(context.Background(), nil)
	_, _ = wrapped(context.Background(), nil)

	if successCount.Load() != 2 {
		t.Fatalf("expected 2 successes, got %d", successCount.Load())
	}
}

func TestMetricsMiddleware_CountsError(t *testing.T) {
	var errCount atomic.Int64

	counter := func(_ string, success bool, _ time.Duration) {
		if !success {
			errCount.Add(1)
		}
	}

	handler := func(_ context.Context, _ any) (any, error) {
		return nil, errors.New("fail")
	}

	chain := framework.NewChain(framework.MetricsMiddleware("op", counter))
	wrapped := chain.Then(handler)

	_, _ = wrapped(context.Background(), nil)

	if errCount.Load() != 1 {
		t.Fatalf("expected 1 error, got %d", errCount.Load())
	}
}

func TestRateLimitMiddleware_AllowsUnderLimit(t *testing.T) {
	callCount := 0
	handler := func(_ context.Context, _ any) (any, error) {
		callCount++
		return "ok", nil
	}

	// Allow 5 per second
	chain := framework.NewChain(framework.RateLimitMiddleware(5, time.Second))
	wrapped := chain.Then(handler)

	for i := 0; i < 5; i++ {
		_, err := wrapped(context.Background(), nil)
		if err != nil {
			t.Fatalf("call %d failed unexpectedly: %v", i, err)
		}
	}
	if callCount != 5 {
		t.Fatalf("expected 5 calls, got %d", callCount)
	}
}

func TestRateLimitMiddleware_RejectsOverLimit(t *testing.T) {
	handler := func(_ context.Context, _ any) (any, error) {
		return "ok", nil
	}

	// Allow only 2 per minute (won't refill in test time)
	chain := framework.NewChain(framework.RateLimitMiddleware(2, time.Minute))
	wrapped := chain.Then(handler)

	_, _ = wrapped(context.Background(), nil)
	_, _ = wrapped(context.Background(), nil)
	_, err := wrapped(context.Background(), nil)
	if err == nil {
		t.Fatal("expected rate limit error on 3rd call")
	}
}

func TestTracingMiddleware_DoesNotAlterResponse(t *testing.T) {
	handler := func(ctx context.Context, req any) (any, error) {
		return "traced", nil
	}

	chain := framework.NewChain(framework.TracingMiddleware("test-svc", "op"))
	wrapped := chain.Then(handler)

	resp, err := wrapped(context.Background(), nil)
	if err != nil {
		t.Fatal(err)
	}
	if resp != "traced" {
		t.Fatalf("expected 'traced', got %v", resp)
	}
}

func TestCircuitBreakerMiddleware_OpensAfterThreshold(t *testing.T) {
	calls := 0
	handler := func(_ context.Context, _ any) (any, error) {
		calls++
		return nil, errors.New("fail")
	}

	// threshold = 3, half-open after 10ms
	chain := framework.NewChain(framework.CircuitBreakerMiddleware("op", 3, 10*time.Millisecond))
	wrapped := chain.Then(handler)

	for i := 0; i < 3; i++ {
		_, _ = wrapped(context.Background(), nil)
	}

	// Circuit should now be open — handler should NOT be called
	_, err := wrapped(context.Background(), nil)
	if err == nil {
		t.Fatal("expected circuit breaker error")
	}
	if calls != 3 {
		t.Fatalf("expected handler called 3 times (not 4), got %d", calls)
	}
}

func TestCircuitBreakerMiddleware_HalfOpenAfterTimeout(t *testing.T) {
	fail := true
	handler := func(_ context.Context, _ any) (any, error) {
		if fail {
			return nil, errors.New("fail")
		}
		return "ok", nil
	}

	chain := framework.NewChain(framework.CircuitBreakerMiddleware("op", 2, 20*time.Millisecond))
	wrapped := chain.Then(handler)

	// Trip the circuit
	_, _ = wrapped(context.Background(), nil)
	_, _ = wrapped(context.Background(), nil)

	// Wait for half-open timeout
	time.Sleep(30 * time.Millisecond)
	fail = false

	// Half-open probe: should succeed and close the circuit
	_, err := wrapped(context.Background(), nil)
	if err != nil {
		t.Fatalf("expected half-open probe to succeed, got %v", err)
	}

	// Subsequent calls should work normally
	_, err = wrapped(context.Background(), nil)
	if err != nil {
		t.Fatalf("expected closed circuit to work, got %v", err)
	}
}
