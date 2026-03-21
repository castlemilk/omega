package observability

import (
	"context"
	"errors"
	"testing"
	"time"
)

func testCfg(threshold int, resetTimeout time.Duration) CircuitBreakerConfig {
	return CircuitBreakerConfig{
		FailureThreshold: threshold,
		ResetTimeout:     resetTimeout,
		HalfOpenMaxCalls: 1,
	}
}

// ---------------------------------------------------------------------------
// CircuitBreaker state machine
// ---------------------------------------------------------------------------

func TestCircuitBreaker_InitiallyClosed(t *testing.T) {
	cb := NewCircuitBreaker("node-1", testCfg(3, time.Minute), nil)
	if cb.State() != CircuitClosed {
		t.Fatalf("want CLOSED, got %v", cb.State())
	}
	if !cb.Allow() {
		t.Fatal("Allow() should return true when CLOSED")
	}
}

func TestCircuitBreaker_OpensAfterThreshold(t *testing.T) {
	cb := NewCircuitBreaker("node-1", testCfg(3, time.Minute), nil)
	for i := 0; i < 3; i++ {
		cb.RecordFailure()
	}
	if cb.State() != CircuitOpen {
		t.Fatalf("want OPEN after 3 failures, got %v", cb.State())
	}
	if cb.Allow() {
		t.Fatal("Allow() should return false when OPEN")
	}
}

func TestCircuitBreaker_DoesNotOpenBeforeThreshold(t *testing.T) {
	cb := NewCircuitBreaker("node-1", testCfg(3, time.Minute), nil)
	cb.RecordFailure()
	cb.RecordFailure()
	if cb.State() != CircuitClosed {
		t.Fatalf("want CLOSED after 2 of 3 failures, got %v", cb.State())
	}
}

func TestCircuitBreaker_SuccessResetFailureCount(t *testing.T) {
	cb := NewCircuitBreaker("node-1", testCfg(3, time.Minute), nil)
	cb.RecordFailure()
	cb.RecordFailure()
	cb.RecordSuccess()
	cb.RecordFailure()
	cb.RecordFailure()
	// Only 2 consecutive failures after success reset → still CLOSED.
	if cb.State() != CircuitClosed {
		t.Fatalf("want CLOSED, got %v", cb.State())
	}
}

func TestCircuitBreaker_TransitionsToHalfOpen(t *testing.T) {
	cb := NewCircuitBreaker("node-1", testCfg(1, 10*time.Millisecond), nil)
	cb.RecordFailure() // trips
	if cb.State() != CircuitOpen {
		t.Fatalf("want OPEN, got %v", cb.State())
	}
	time.Sleep(20 * time.Millisecond)
	if cb.State() != CircuitHalfOpen {
		t.Fatalf("want HALF_OPEN after reset timeout, got %v", cb.State())
	}
}

func TestCircuitBreaker_HalfOpen_SuccessCloses(t *testing.T) {
	cb := NewCircuitBreaker("node-1", testCfg(1, 5*time.Millisecond), nil)
	cb.RecordFailure()
	time.Sleep(10 * time.Millisecond)
	_ = cb.State() // trigger HALF_OPEN transition
	cb.RecordSuccess()
	if cb.State() != CircuitClosed {
		t.Fatalf("want CLOSED after probe success, got %v", cb.State())
	}
}

func TestCircuitBreaker_HalfOpen_FailureReopens(t *testing.T) {
	cb := NewCircuitBreaker("node-1", testCfg(1, 5*time.Millisecond), nil)
	cb.RecordFailure()
	time.Sleep(10 * time.Millisecond)
	_ = cb.State() // trigger HALF_OPEN
	cb.RecordFailure()
	if cb.State() != CircuitOpen {
		t.Fatalf("want OPEN after probe failure, got %v", cb.State())
	}
}

func TestCircuitBreaker_Do_RejectsWhenOpen(t *testing.T) {
	cb := NewCircuitBreaker("node-1", testCfg(1, time.Minute), nil)
	cb.RecordFailure()

	err := cb.Do(context.Background(), func(_ context.Context) error {
		t.Fatal("fn should not be called when circuit is open")
		return nil
	})
	if !errors.Is(err, ErrCircuitOpen) {
		t.Fatalf("want ErrCircuitOpen, got %v", err)
	}
}

func TestCircuitBreaker_Do_RecordsFailure(t *testing.T) {
	cb := NewCircuitBreaker("node-1", testCfg(3, time.Minute), nil)
	for i := 0; i < 2; i++ {
		_ = cb.Do(context.Background(), func(_ context.Context) error {
			return errors.New("boom")
		})
	}
	if cb.State() != CircuitClosed {
		t.Fatalf("want CLOSED, got %v", cb.State())
	}
	_ = cb.Do(context.Background(), func(_ context.Context) error {
		return errors.New("boom")
	})
	if cb.State() != CircuitOpen {
		t.Fatalf("want OPEN after threshold, got %v", cb.State())
	}
}

// ---------------------------------------------------------------------------
// CircuitBreakerRegistry
// ---------------------------------------------------------------------------

func TestCircuitBreakerRegistry_LazyCreation(t *testing.T) {
	reg := NewCircuitBreakerRegistry(DefaultCircuitBreakerConfig(), nil, nil)
	cb := reg.Get("alpha")
	if cb == nil {
		t.Fatal("Get() returned nil")
	}
	// Same call returns same instance.
	cb2 := reg.Get("alpha")
	if cb != cb2 {
		t.Fatal("Get() should return same instance for same nodeID")
	}
}

func TestCircuitBreakerRegistry_Remove(t *testing.T) {
	reg := NewCircuitBreakerRegistry(DefaultCircuitBreakerConfig(), nil, nil)
	_ = reg.Get("beta")
	reg.Remove("beta")
	snap := reg.Snapshot()
	if _, ok := snap["beta"]; ok {
		t.Fatal("Remove() should delete from snapshot")
	}
}

func TestCircuitBreakerRegistry_Snapshot(t *testing.T) {
	reg := NewCircuitBreakerRegistry(testCfg(1, time.Minute), nil, nil)
	reg.Get("n1").RecordFailure() // trips
	reg.Get("n2") // stays CLOSED

	snap := reg.Snapshot()
	if snap["n1"] != CircuitOpen {
		t.Fatalf("n1 should be OPEN, got %v", snap["n1"])
	}
	if snap["n2"] != CircuitClosed {
		t.Fatalf("n2 should be CLOSED, got %v", snap["n2"])
	}
}

func TestCircuitBreakerRegistry_MetricsHook(t *testing.T) {
	m := NewMetrics()
	reg := NewCircuitBreakerRegistry(testCfg(1, time.Minute), nil, m)
	cb := reg.Get("node-x")
	cb.RecordFailure() // should call onStateChange → OPEN

	// The test just verifies no panic. Prometheus gauge is updated.
	snap := reg.Snapshot()
	if snap["node-x"] != CircuitOpen {
		t.Fatalf("want OPEN, got %v", snap["node-x"])
	}
}

// ---------------------------------------------------------------------------
// String representations
// ---------------------------------------------------------------------------

func TestCircuitStateString(t *testing.T) {
	tests := []struct {
		state CircuitState
		want  string
	}{
		{CircuitClosed, "CLOSED"},
		{CircuitOpen, "OPEN"},
		{CircuitHalfOpen, "HALF_OPEN"},
		{CircuitState(99), "UNKNOWN"},
	}
	for _, tt := range tests {
		if got := tt.state.String(); got != tt.want {
			t.Errorf("CircuitState(%d).String() = %q, want %q", tt.state, got, tt.want)
		}
	}
}
