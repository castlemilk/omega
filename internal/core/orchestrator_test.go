package core

import (
	"context"
	"errors"
	"log/slog"
	"sync/atomic"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/observability"
)

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

// stubNode is a NodeExecutor that counts calls and optionally returns an error.
type stubNode struct {
	id      string
	calls   atomic.Int64
	failFor int // fail the first N calls
}

func (n *stubNode) NodeID() string { return n.id }
func (n *stubNode) Execute(_ context.Context) error {
	c := int(n.calls.Add(1))
	if c <= n.failFor {
		return errors.New("stub failure")
	}
	return nil
}

func newOrch(t *testing.T) (*Orchestrator, *observability.EventBus) {
	t.Helper()
	logger := slog.Default()
	bus := observability.NewEventBus(logger)
	metrics := observability.NewMetrics()
	cfg := DefaultOrchestratorConfig()
	cfg.CircuitBreaker = observability.CircuitBreakerConfig{
		FailureThreshold: 3,
		ResetTimeout:     100 * time.Millisecond,
		HalfOpenMaxCalls: 1,
	}
	orch := NewOrchestrator(cfg, bus, metrics, nil, logger)
	return orch, bus
}

// collectEvents drains ch until timeout and returns all collected events.
func collectEvents(ch <-chan observability.Event, count int, timeout time.Duration) []observability.Event {
	var events []observability.Event
	deadline := time.After(timeout)
	for {
		select {
		case e := <-ch:
			events = append(events, e)
			if len(events) >= count {
				return events
			}
		case <-deadline:
			return events
		}
	}
}

// ---------------------------------------------------------------------------
// Orchestrator lifecycle
// ---------------------------------------------------------------------------

func TestOrchestrator_RegisterAndRunCycle(t *testing.T) {
	orch, bus := newOrch(t)

	// Subscribe to all events.
	ch, cancel := bus.Subscribe(32)
	defer cancel()

	node := &stubNode{id: "node-a"}
	orch.Register(node)

	ctx := context.Background()
	result, err := orch.RunCycle(ctx)
	if err != nil {
		t.Fatalf("RunCycle returned error: %v", err)
	}
	if result.CycleID != 1 {
		t.Errorf("expected cycle ID 1, got %d", result.CycleID)
	}
	if !result.Results["node-a"] {
		t.Errorf("expected node-a to succeed")
	}
	if node.calls.Load() != 1 {
		t.Errorf("expected node-a Execute to be called once, got %d", node.calls.Load())
	}

	// We expect at least CycleStarted and CycleCompleted on the bus.
	events := collectEvents(ch, 3, 200*time.Millisecond)
	types := make(map[observability.EventType]int)
	for _, e := range events {
		types[e.Type]++
	}
	if types[observability.EventCycleStarted] == 0 {
		t.Error("expected CycleStarted event")
	}
	if types[observability.EventCycleCompleted] == 0 {
		t.Error("expected CycleCompleted event")
	}
}

func TestOrchestrator_NodeRegisteredEvent(t *testing.T) {
	orch, bus := newOrch(t)
	ch, cancel := bus.Subscribe(16, observability.EventNodeRegistered)
	defer cancel()

	orch.Register(&stubNode{id: "node-b"})

	events := collectEvents(ch, 1, 100*time.Millisecond)
	if len(events) == 0 {
		t.Fatal("expected NodeRegistered event")
	}
	p, ok := events[0].Payload.(observability.NodeRegisteredPayload)
	if !ok {
		t.Fatalf("expected NodeRegisteredPayload, got %T", events[0].Payload)
	}
	if p.NodeID != "node-b" {
		t.Errorf("expected node-b, got %s", p.NodeID)
	}
}

func TestOrchestrator_DuplicateRegister(t *testing.T) {
	orch, _ := newOrch(t)
	orch.Register(&stubNode{id: "dup"})
	orch.Register(&stubNode{id: "dup"}) // should not panic or crash

	result, err := orch.RunCycle(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	// Only one node; should execute once.
	if len(result.Results) != 1 {
		t.Errorf("expected 1 node in results, got %d", len(result.Results))
	}
}

func TestOrchestrator_Deregister(t *testing.T) {
	orch, _ := newOrch(t)
	orch.Register(&stubNode{id: "node-c"})
	orch.Deregister("node-c")

	result, err := orch.RunCycle(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Results) != 0 {
		t.Errorf("expected empty results after deregister, got %d", len(result.Results))
	}
}

func TestOrchestrator_CycleIDMonotonicallyIncreasing(t *testing.T) {
	orch, _ := newOrch(t)
	ctx := context.Background()

	var prev int64
	for i := 0; i < 5; i++ {
		r, err := orch.RunCycle(ctx)
		if err != nil {
			t.Fatal(err)
		}
		if r.CycleID <= prev {
			t.Errorf("cycle ID %d not greater than previous %d", r.CycleID, prev)
		}
		prev = r.CycleID
	}
}

// ---------------------------------------------------------------------------
// Circuit breaker integration
// ---------------------------------------------------------------------------

func TestOrchestrator_CircuitBreakerOpensAfterFailures(t *testing.T) {
	orch, bus := newOrch(t)

	// Subscribe to circuit-breaker-tripped events.
	cbCh, cancel := bus.Subscribe(16, observability.EventCircuitBreakerTripped)
	defer cancel()

	// Node fails indefinitely.
	node := &stubNode{id: "flaky", failFor: 999}
	orch.Register(node)

	ctx := context.Background()

	// Threshold is 3; run 3 cycles to trip the circuit.
	for i := 0; i < 3; i++ {
		r, err := orch.RunCycle(ctx)
		if err != nil {
			t.Fatalf("cycle %d: unexpected orchestrator error: %v", i, err)
		}
		if r.Results["flaky"] != false {
			t.Errorf("cycle %d: expected flaky to fail", i)
		}
	}

	// 4th cycle: circuit should be open, node should be skipped.
	r, err := orch.RunCycle(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if r.Results["flaky"] != false {
		t.Errorf("expected flaky to be skipped (circuit open)")
	}
	// Node should NOT have been called in cycle 4.
	// Total Execute calls should be exactly 3 (threshold).
	if node.calls.Load() != 3 {
		t.Errorf("expected exactly 3 Execute calls before circuit opened, got %d", node.calls.Load())
	}

	// We should have received at least one CircuitBreakerTripped event.
	events := collectEvents(cbCh, 1, 200*time.Millisecond)
	if len(events) == 0 {
		t.Error("expected CircuitBreakerTripped event")
	}
}

func TestOrchestrator_CircuitBreakerHalfOpenProbe(t *testing.T) {
	orch, _ := newOrch(t)
	cfg := orch.cfg
	cfg.CircuitBreaker.ResetTimeout = 50 * time.Millisecond

	logger := slog.Default()
	bus := observability.NewEventBus(logger)
	metrics := observability.NewMetrics()
	orch = NewOrchestrator(cfg, bus, metrics, nil, logger)

	// Node fails first 3, then succeeds.
	node := &stubNode{id: "recovering", failFor: 3}
	orch.Register(node)

	ctx := context.Background()

	// Trip the circuit (3 failures).
	for i := 0; i < 3; i++ {
		if _, err := orch.RunCycle(ctx); err != nil {
			t.Fatalf("unexpected error during trip cycle %d: %v", i, err)
		}
	}
	if orch.circuit.State("recovering") != observability.CircuitOpen {
		t.Fatalf("expected circuit to be OPEN after 3 failures")
	}

	// Wait for reset timeout → HALF_OPEN.
	time.Sleep(80 * time.Millisecond)

	// Run one cycle: should probe in HALF_OPEN state.
	r, err := orch.RunCycle(ctx)
	if err != nil {
		t.Fatal(err)
	}
	// The node should now succeed (calls = 4, which is > failFor=3).
	if !r.Results["recovering"] {
		t.Errorf("expected recovering node to succeed in half-open probe")
	}

	// After a successful half-open probe, circuit should close.
	if orch.circuit.State("recovering") != observability.CircuitClosed {
		t.Errorf("expected circuit to be CLOSED after successful probe, got %s",
			orch.circuit.State("recovering").String())
	}
}

// ---------------------------------------------------------------------------
// Health gate
// ---------------------------------------------------------------------------

func TestOrchestrator_UnhealthySystemAbortsCycle(t *testing.T) {
	logger := slog.Default()
	bus := observability.NewEventBus(logger)
	metrics := observability.NewMetrics()
	cfg := DefaultOrchestratorConfig()
	cfg.HealthCheckTimeout = 50 * time.Millisecond

	health := observability.NewCompositeHealth(logger)
	// Register a checker that always returns UNHEALTHY.
	health.Register(observability.NewHealthCheckerFunc("always-sick",
		func(_ context.Context) observability.HealthStatus {
			return observability.HealthStatus{
				State:     observability.HealthStateUnhealthy,
				Message:   "simulated failure",
				CheckedAt: time.Now(),
			}
		},
	))

	orch := NewOrchestrator(cfg, bus, metrics, health, logger)
	orch.Register(&stubNode{id: "node-d"})

	_, err := orch.RunCycle(context.Background())
	if err == nil {
		t.Fatal("expected error when system is unhealthy, got nil")
	}
}

func TestOrchestrator_HealthySystemProceedsCycle(t *testing.T) {
	logger := slog.Default()
	bus := observability.NewEventBus(logger)
	metrics := observability.NewMetrics()
	cfg := DefaultOrchestratorConfig()

	health := observability.NewCompositeHealth(logger)
	health.Register(observability.NewHealthCheckerFunc("always-healthy",
		func(_ context.Context) observability.HealthStatus {
			return observability.HealthStatus{
				State:     observability.HealthStateHealthy,
				CheckedAt: time.Now(),
			}
		},
	))

	orch := NewOrchestrator(cfg, bus, metrics, health, logger)
	orch.Register(&stubNode{id: "node-e"})

	r, err := orch.RunCycle(context.Background())
	if err != nil {
		t.Fatalf("expected no error with healthy system: %v", err)
	}
	if !r.Results["node-e"] {
		t.Error("expected node-e to succeed")
	}
}

// ---------------------------------------------------------------------------
// Promotion / demotion / safety events
// ---------------------------------------------------------------------------

func TestOrchestrator_PromoteNodeEmitsEvent(t *testing.T) {
	orch, bus := newOrch(t)
	ch, cancel := bus.Subscribe(16, observability.EventNodePromoted)
	defer cancel()

	orch.Register(&stubNode{id: "n1"})
	orch.PromoteNode("n1", 0.5, 0.8)

	events := collectEvents(ch, 1, 100*time.Millisecond)
	if len(events) == 0 {
		t.Fatal("expected NodePromoted event")
	}
	p := events[0].Payload.(observability.NodePromotedPayload)
	if p.NodeID != "n1" || p.FromLevel != 0.5 || p.ToLevel != 0.8 {
		t.Errorf("unexpected payload: %+v", p)
	}
}

func TestOrchestrator_DemoteNodeEmitsEvent(t *testing.T) {
	orch, bus := newOrch(t)
	ch, cancel := bus.Subscribe(16, observability.EventNodeDemoted)
	defer cancel()

	orch.Register(&stubNode{id: "n2"})
	orch.DemoteNode("n2", "safety violation", 0.8, 0.3)

	events := collectEvents(ch, 1, 100*time.Millisecond)
	if len(events) == 0 {
		t.Fatal("expected NodeDemoted event")
	}
	p := events[0].Payload.(observability.NodeDemotedPayload)
	if p.NodeID != "n2" || p.Reason != "safety violation" {
		t.Errorf("unexpected payload: %+v", p)
	}
}

func TestOrchestrator_SafetyViolationEmitsEvent(t *testing.T) {
	orch, bus := newOrch(t)
	ch, cancel := bus.Subscribe(16, observability.EventSafetyViolation)
	defer cancel()

	orch.EmitSafetyViolation("n3", "drawdown", "hard", "exceeded 0.15")

	events := collectEvents(ch, 1, 100*time.Millisecond)
	if len(events) == 0 {
		t.Fatal("expected SafetyViolation event")
	}
}

func TestOrchestrator_AdversarialAlertEmitsEvent(t *testing.T) {
	orch, bus := newOrch(t)
	ch, cancel := bus.Subscribe(16, observability.EventAdversarialVeto)
	defer cancel()

	orch.EmitAdversarialAlert(2, "n4", 0.9, 0.75)

	events := collectEvents(ch, 1, 100*time.Millisecond)
	if len(events) == 0 {
		t.Fatal("expected AdversarialVeto event")
	}
	p := events[0].Payload.(observability.AdversarialVetoPayload)
	if p.Ring != 2 || p.NodeID != "n4" {
		t.Errorf("unexpected payload: %+v", p)
	}
}

// ---------------------------------------------------------------------------
// CycleCompletedEvent payload
// ---------------------------------------------------------------------------

func TestOrchestrator_CycleCompletedPayload(t *testing.T) {
	orch, bus := newOrch(t)
	ch, cancel := bus.Subscribe(16, observability.EventCycleCompleted)
	defer cancel()

	orch.Register(&stubNode{id: "n5"})
	r, err := orch.RunCycle(context.Background())
	if err != nil {
		t.Fatal(err)
	}

	events := collectEvents(ch, 1, 200*time.Millisecond)
	if len(events) == 0 {
		t.Fatal("expected CycleCompleted event")
	}
	p := events[0].Payload.(observability.CycleCompletedPayload)
	if p.Cycle != r.CycleID {
		t.Errorf("cycle ID mismatch: event=%d result=%d", p.Cycle, r.CycleID)
	}
	if !p.Success {
		t.Error("expected success=true")
	}
}
