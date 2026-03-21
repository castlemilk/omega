package core

import (
	"log/slog"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/observability"
)

func newManager(t *testing.T, threshold int, resetTimeout time.Duration) (*NodeCircuitManager, *observability.EventBus) {
	t.Helper()
	bus := observability.NewEventBus(slog.Default())
	cfg := observability.CircuitBreakerConfig{
		FailureThreshold: threshold,
		ResetTimeout:     resetTimeout,
		HalfOpenMaxCalls: 1,
	}
	m := NewNodeCircuitManager(cfg, observability.NewMetrics(), bus, slog.Default())
	return m, bus
}

func TestNodeCircuitManager_AllowsWhenClosed(t *testing.T) {
	m, _ := newManager(t, 3, time.Second)
	if !m.AllowExecution("node-x") {
		t.Error("expected AllowExecution to return true for fresh node")
	}
}

func TestNodeCircuitManager_OpensAfterThreshold(t *testing.T) {
	m, bus := newManager(t, 3, time.Second)
	ch, cancel := bus.Subscribe(16, observability.EventCircuitBreakerTripped)
	defer cancel()

	for i := 0; i < 3; i++ {
		m.AllowExecution("node-y")
		m.RecordFailure("node-y")
	}

	if m.State("node-y") != observability.CircuitOpen {
		t.Errorf("expected OPEN after 3 failures, got %s", m.State("node-y"))
	}
	if m.AllowExecution("node-y") {
		t.Error("expected AllowExecution to return false when circuit is OPEN")
	}

	events := collectEvents(ch, 1, 100*time.Millisecond)
	if len(events) == 0 {
		t.Error("expected CircuitBreakerTripped event when circuit opened")
	}
}

func TestNodeCircuitManager_HalfOpenAfterTimeout(t *testing.T) {
	m, _ := newManager(t, 2, 50*time.Millisecond)

	// Trip the circuit.
	for i := 0; i < 2; i++ {
		m.AllowExecution("node-z")
		m.RecordFailure("node-z")
	}
	if m.State("node-z") != observability.CircuitOpen {
		t.Fatal("expected OPEN")
	}

	// Wait for reset timeout.
	time.Sleep(80 * time.Millisecond)

	// AllowExecution triggers the OPEN→HALF_OPEN transition inside CircuitBreaker.Allow().
	if !m.AllowExecution("node-z") {
		t.Error("expected AllowExecution to allow probe in HALF_OPEN state")
	}
}

func TestNodeCircuitManager_ClosesAfterSuccessfulProbe(t *testing.T) {
	m, _ := newManager(t, 2, 30*time.Millisecond)

	// Trip.
	for i := 0; i < 2; i++ {
		m.AllowExecution("probe-node")
		m.RecordFailure("probe-node")
	}

	// Wait → HALF_OPEN.
	time.Sleep(50 * time.Millisecond)
	m.AllowExecution("probe-node") // probe allowed

	// Successful probe closes the circuit.
	m.RecordSuccess("probe-node")
	if m.State("probe-node") != observability.CircuitClosed {
		t.Errorf("expected CLOSED after successful probe, got %s", m.State("probe-node").String())
	}
}

func TestNodeCircuitManager_SnapshotReflectsAllNodes(t *testing.T) {
	m, _ := newManager(t, 5, time.Second)

	m.AllowExecution("a")
	m.AllowExecution("b")
	m.AllowExecution("c")

	snap := m.Snapshot()
	for _, id := range []string{"a", "b", "c"} {
		if _, ok := snap[id]; !ok {
			t.Errorf("expected node %s in snapshot", id)
		}
	}
}

func TestNodeCircuitManager_RemoveCleansUp(t *testing.T) {
	m, _ := newManager(t, 5, time.Second)
	m.AllowExecution("rm-node")
	m.Remove("rm-node")

	snap := m.Snapshot()
	if _, ok := snap["rm-node"]; ok {
		t.Error("expected rm-node to be removed from snapshot")
	}
}

func TestNodeCircuitManager_SuccessResetsFailureCount(t *testing.T) {
	m, _ := newManager(t, 3, time.Second)

	// Two failures, then a success — should NOT open the circuit.
	m.AllowExecution("resilient")
	m.RecordFailure("resilient")
	m.AllowExecution("resilient")
	m.RecordFailure("resilient")
	m.AllowExecution("resilient")
	m.RecordSuccess("resilient") // resets counter

	// One more failure should not trip (counter was reset).
	m.AllowExecution("resilient")
	m.RecordFailure("resilient")

	if m.State("resilient") != observability.CircuitClosed {
		t.Errorf("expected CLOSED, got %s (success should reset failure count)", m.State("resilient"))
	}
}
