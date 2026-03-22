package api

import (
	"context"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/observability"
)

func newTestBus() *observability.EventBus {
	return observability.NewEventBus(nil)
}

// publishAndWait publishes an event and waits long enough for the aggregator goroutine to ingest it.
func publishAndWait(bus *observability.EventBus, e observability.Event) {
	bus.Publish(e)
	time.Sleep(50 * time.Millisecond)
}

// waitUntil polls f until it returns true or the deadline is exceeded.
func waitUntil(t *testing.T, f func() bool, deadline time.Duration) {
	t.Helper()
	end := time.Now().Add(deadline)
	for time.Now().Before(end) {
		if f() {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Error("condition not satisfied within deadline")
}

func TestNewMetricsAggregator_initialState(t *testing.T) {
	bus := newTestBus()
	agg := NewMetricsAggregator(bus)

	m := agg.GetLiveMetrics()
	if m.CyclesPerMinute1m != 0 {
		t.Errorf("expected 0 cycles/min, got %f", m.CyclesPerMinute1m)
	}
	if m.NodesByAutonomyLevel == nil {
		t.Error("NodesByAutonomyLevel should not be nil")
	}
	if m.NodesByCircuitBreakerState == nil {
		t.Error("NodesByCircuitBreakerState should not be nil")
	}
}

func TestRollingWindowCappedAt100(t *testing.T) {
	bus := newTestBus()
	agg := NewMetricsAggregator(bus)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go agg.Run(ctx)

	for i := 0; i < 110; i++ {
		bus.Publish(observability.Event{
			Type:    observability.EventCycleStarted,
			Payload: observability.CycleStartedPayload{Cycle: int64(i)},
		})
	}

	waitUntil(t, func() bool {
		agg.mu.RLock()
		defer agg.mu.RUnlock()
		return len(agg.rollingWindow) == rollingWindowSize
	}, 500*time.Millisecond)

	agg.mu.RLock()
	wlen := len(agg.rollingWindow)
	agg.mu.RUnlock()

	if wlen > rollingWindowSize {
		t.Errorf("rolling window len %d exceeds cap %d", wlen, rollingWindowSize)
	}
}

func TestNodeRegistrationSetsInitialState(t *testing.T) {
	bus := newTestBus()
	agg := NewMetricsAggregator(bus)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go agg.Run(ctx)

	publishAndWait(bus, observability.Event{
		Type:    observability.EventNodeRegistered,
		Payload: observability.NodeRegisteredPayload{NodeID: "node-1"},
	})

	waitUntil(t, func() bool {
		agg.mu.RLock()
		defer agg.mu.RUnlock()
		_, ok := agg.nodeAutonomy["node-1"]
		return ok
	}, 300*time.Millisecond)

	agg.mu.RLock()
	level := agg.nodeAutonomy["node-1"]
	cbState := agg.nodeCBState["node-1"]
	agg.mu.RUnlock()

	if level != 1 {
		t.Errorf("expected initial autonomy level 1 (manual), got %d", level)
	}
	if cbState != "closed" {
		t.Errorf("expected initial CB state 'closed', got %q", cbState)
	}
}

func TestNodePromotionUpdatesAutonomyLevel(t *testing.T) {
	bus := newTestBus()
	agg := NewMetricsAggregator(bus)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go agg.Run(ctx)

	publishAndWait(bus, observability.Event{
		Type:    observability.EventNodePromoted,
		Payload: observability.NodePromotedPayload{NodeID: "node-1", FromLevel: 1, ToLevel: 3},
	})

	waitUntil(t, func() bool {
		agg.mu.RLock()
		defer agg.mu.RUnlock()
		return agg.nodeAutonomy["node-1"] == 3
	}, 300*time.Millisecond)

	agg.mu.RLock()
	level := agg.nodeAutonomy["node-1"]
	agg.mu.RUnlock()

	if level != 3 {
		t.Errorf("expected autonomy level 3, got %d", level)
	}
}

func TestNodeDemotionUpdatesAutonomyLevel(t *testing.T) {
	bus := newTestBus()
	agg := NewMetricsAggregator(bus)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go agg.Run(ctx)

	publishAndWait(bus, observability.Event{
		Type:    observability.EventNodeDemoted,
		Payload: observability.NodeDemotedPayload{NodeID: "node-2", FromLevel: 4, ToLevel: 2, Reason: "errors"},
	})

	waitUntil(t, func() bool {
		agg.mu.RLock()
		defer agg.mu.RUnlock()
		return agg.nodeAutonomy["node-2"] == 2
	}, 300*time.Millisecond)

	agg.mu.RLock()
	level := agg.nodeAutonomy["node-2"]
	agg.mu.RUnlock()

	if level != 2 {
		t.Errorf("expected autonomy level 2, got %d", level)
	}
}

func TestCircuitBreakerTrippedMarksNodeOpen(t *testing.T) {
	bus := newTestBus()
	agg := NewMetricsAggregator(bus)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go agg.Run(ctx)

	publishAndWait(bus, observability.Event{
		Type:    observability.EventNodeRegistered,
		Payload: observability.NodeRegisteredPayload{NodeID: "node-cb"},
	})
	publishAndWait(bus, observability.Event{
		Type:    observability.EventCircuitBreakerTripped,
		Payload: observability.CircuitBreakerTrippedPayload{NodeID: "node-cb", ConsecutiveFails: 5},
	})

	waitUntil(t, func() bool {
		agg.mu.RLock()
		defer agg.mu.RUnlock()
		return agg.nodeCBState["node-cb"] == "open"
	}, 300*time.Millisecond)

	agg.mu.RLock()
	state := agg.nodeCBState["node-cb"]
	agg.mu.RUnlock()

	if state != "open" {
		t.Errorf("expected CB state 'open', got %q", state)
	}
}

// ingestDirect calls ingest synchronously, bypassing the goroutine, for compute tests.
func ingestDirect(agg *MetricsAggregator, e observability.Event) {
	agg.ingest(e)
}

func TestComputeMetrics_cycleRates(t *testing.T) {
	bus := newTestBus()
	agg := NewMetricsAggregator(bus)

	// Ingest directly to avoid goroutine timing issues in compute tests.
	for i := 0; i < 3; i++ {
		ingestDirect(agg, observability.Event{
			Type:    observability.EventCycleCompleted,
			Payload: observability.CycleCompletedPayload{Cycle: int64(i), DurationSecs: 2.0, NodeCount: 1, Success: true},
		})
	}

	agg.compute()

	m := agg.GetLiveMetrics()
	if m.CyclesPerMinute1m != 3.0 {
		t.Errorf("expected 3.0 cycles/min (1m), got %f", m.CyclesPerMinute1m)
	}
	if m.AvgCycleDurationMs1m != 2000.0 {
		t.Errorf("expected avg duration 2000ms, got %f", m.AvgCycleDurationMs1m)
	}
}

func TestComputeMetrics_safetyViolationRate(t *testing.T) {
	bus := newTestBus()
	agg := NewMetricsAggregator(bus)

	// 4 cycles, 2 safety violations → rate 0.5.
	for i := 0; i < 4; i++ {
		ingestDirect(agg, observability.Event{
			Type:    observability.EventCycleCompleted,
			Payload: observability.CycleCompletedPayload{Cycle: int64(i), DurationSecs: 1.0, Success: true},
		})
	}
	for i := 0; i < 2; i++ {
		ingestDirect(agg, observability.Event{
			Type:    observability.EventSafetyViolation,
			Payload: observability.SafetyViolationPayload{NodeID: "n", Layer: 1, Constraint: "c", Value: 1, Limit: 0},
		})
	}

	agg.compute()
	m := agg.GetLiveMetrics()

	want := 2.0 / 4.0
	if m.SafetyViolationRate != want {
		t.Errorf("expected safety violation rate %f, got %f", want, m.SafetyViolationRate)
	}
}

func TestComputeMetrics_adversarialAlertRate(t *testing.T) {
	bus := newTestBus()
	agg := NewMetricsAggregator(bus)

	for i := 0; i < 10; i++ {
		ingestDirect(agg, observability.Event{
			Type:    observability.EventCycleCompleted,
			Payload: observability.CycleCompletedPayload{Cycle: int64(i), DurationSecs: 1.0, Success: true},
		})
	}
	for i := 0; i < 3; i++ {
		ingestDirect(agg, observability.Event{
			Type:    observability.EventAdversarialVeto,
			Payload: observability.AdversarialVetoPayload{NodeID: "n", Ring: 1, Reason: "r"},
		})
	}

	agg.compute()
	m := agg.GetLiveMetrics()

	want := 3.0 / 10.0
	if m.AdversarialAlertRate != want {
		t.Errorf("expected adversarial alert rate %f, got %f", want, m.AdversarialAlertRate)
	}
}

func TestComputeMetrics_improvementSuccessRate(t *testing.T) {
	bus := newTestBus()
	agg := NewMetricsAggregator(bus)

	// 1 successful (after > before) and 1 failed (after < before).
	ingestDirect(agg, observability.Event{
		Type: observability.EventImprovementApplied,
		Payload: observability.ImprovementAppliedPayload{
			NodeID: "n", StrategyName: "s",
			BeforeMetrics: map[string]float64{"score": 5.0},
			AfterMetrics:  map[string]float64{"score": 8.0},
		},
	})
	ingestDirect(agg, observability.Event{
		Type: observability.EventImprovementApplied,
		Payload: observability.ImprovementAppliedPayload{
			NodeID: "n", StrategyName: "s",
			BeforeMetrics: map[string]float64{"score": 8.0},
			AfterMetrics:  map[string]float64{"score": 3.0},
		},
	})

	agg.compute()
	m := agg.GetLiveMetrics()

	want := 0.5
	if m.ImprovementSuccessRate != want {
		t.Errorf("expected improvement success rate %f, got %f", want, m.ImprovementSuccessRate)
	}
}

func TestComputeMetrics_nodesByAutonomyLevel(t *testing.T) {
	bus := newTestBus()
	agg := NewMetricsAggregator(bus)

	ingestDirect(agg, observability.Event{
		Type:    observability.EventNodeRegistered,
		Payload: observability.NodeRegisteredPayload{NodeID: "n1"},
	})
	ingestDirect(agg, observability.Event{
		Type:    observability.EventNodePromoted,
		Payload: observability.NodePromotedPayload{NodeID: "n2", FromLevel: 1, ToLevel: 4},
	})
	ingestDirect(agg, observability.Event{
		Type:    observability.EventNodePromoted,
		Payload: observability.NodePromotedPayload{NodeID: "n3", FromLevel: 1, ToLevel: 4},
	})

	agg.compute()
	m := agg.GetLiveMetrics()

	if m.NodesByAutonomyLevel["manual"] != 1 {
		t.Errorf("expected 1 manual node, got %d", m.NodesByAutonomyLevel["manual"])
	}
	if m.NodesByAutonomyLevel["full"] != 2 {
		t.Errorf("expected 2 full nodes, got %d", m.NodesByAutonomyLevel["full"])
	}
}

func TestComputeMetrics_nodesByCircuitBreakerState(t *testing.T) {
	bus := newTestBus()
	agg := NewMetricsAggregator(bus)

	ingestDirect(agg, observability.Event{
		Type:    observability.EventNodeRegistered,
		Payload: observability.NodeRegisteredPayload{NodeID: "n-ok"},
	})
	ingestDirect(agg, observability.Event{
		Type:    observability.EventNodeRegistered,
		Payload: observability.NodeRegisteredPayload{NodeID: "n-tripped"},
	})
	ingestDirect(agg, observability.Event{
		Type:    observability.EventCircuitBreakerTripped,
		Payload: observability.CircuitBreakerTrippedPayload{NodeID: "n-tripped", ConsecutiveFails: 3},
	})

	agg.compute()
	m := agg.GetLiveMetrics()

	if m.NodesByCircuitBreakerState["closed"] != 1 {
		t.Errorf("expected 1 closed CB, got %d", m.NodesByCircuitBreakerState["closed"])
	}
	if m.NodesByCircuitBreakerState["open"] != 1 {
		t.Errorf("expected 1 open CB, got %d", m.NodesByCircuitBreakerState["open"])
	}
}

func TestGetLiveMetrics_threadSafe(t *testing.T) {
	bus := newTestBus()
	agg := NewMetricsAggregator(bus)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go agg.Run(ctx)

	done := make(chan struct{})
	for i := 0; i < 10; i++ {
		go func() {
			for j := 0; j < 100; j++ {
				agg.GetLiveMetrics()
			}
			done <- struct{}{}
		}()
	}

	go func() {
		for i := 0; i < 50; i++ {
			bus.Publish(observability.Event{
				Type:    observability.EventCycleCompleted,
				Payload: observability.CycleCompletedPayload{Cycle: int64(i), DurationSecs: 1.0},
			})
		}
	}()

	for i := 0; i < 10; i++ {
		<-done
	}
}

func TestImprovementSucceeded(t *testing.T) {
	tests := []struct {
		name   string
		before map[string]float64
		after  map[string]float64
		want   bool
	}{
		{
			name:   "improves",
			before: map[string]float64{"score": 5.0},
			after:  map[string]float64{"score": 8.0},
			want:   true,
		},
		{
			name:   "regresses",
			before: map[string]float64{"score": 8.0},
			after:  map[string]float64{"score": 3.0},
			want:   false,
		},
		{
			name:   "no before metrics",
			before: nil,
			after:  map[string]float64{"score": 8.0},
			want:   false,
		},
		{
			name:   "no after metrics",
			before: map[string]float64{"score": 5.0},
			after:  nil,
			want:   false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			p := observability.ImprovementAppliedPayload{
				BeforeMetrics: tt.before,
				AfterMetrics:  tt.after,
			}
			if got := improvementSucceeded(p); got != tt.want {
				t.Errorf("improvementSucceeded() = %v, want %v", got, tt.want)
			}
		})
	}
}
