package observability

import (
	"testing"
	"time"
)

// ---------------------------------------------------------------------------
// window
// ---------------------------------------------------------------------------

func TestWindow_PushAndValues(t *testing.T) {
	w := newWindow(3)
	// Empty window.
	if got := w.values(); len(got) != 0 {
		t.Fatalf("want empty values, got %v", got)
	}

	w.push(1)
	w.push(2)
	w.push(3)
	vals := w.values()
	if len(vals) != 3 {
		t.Fatalf("want 3 values, got %d", len(vals))
	}
	for i, want := range []float64{1, 2, 3} {
		if vals[i] != want {
			t.Errorf("vals[%d] = %v, want %v", i, vals[i], want)
		}
	}
}

func TestWindow_WrapAround(t *testing.T) {
	w := newWindow(3)
	w.push(1)
	w.push(2)
	w.push(3)
	w.push(4) // wraps: evicts 1
	vals := w.values()
	if len(vals) != 3 {
		t.Fatalf("want 3 values, got %d", len(vals))
	}
	for i, want := range []float64{2, 3, 4} {
		if vals[i] != want {
			t.Errorf("vals[%d] = %v, want %v", i, vals[i], want)
		}
	}
}

func TestWindow_LenBeforeFull(t *testing.T) {
	w := newWindow(5)
	w.push(1)
	w.push(2)
	if w.len() != 2 {
		t.Fatalf("want 2, got %d", w.len())
	}
}

// ---------------------------------------------------------------------------
// Statistical helpers
// ---------------------------------------------------------------------------

func TestMean(t *testing.T) {
	tests := []struct {
		xs   []float64
		want float64
	}{
		{nil, 0},
		{[]float64{}, 0},
		{[]float64{1, 2, 3}, 2},
		{[]float64{10, 20}, 15},
	}
	for _, tt := range tests {
		if got := mean(tt.xs); got != tt.want {
			t.Errorf("mean(%v) = %v, want %v", tt.xs, got, tt.want)
		}
	}
}

func TestLinearSlope(t *testing.T) {
	tests := []struct {
		name string
		xs   []float64
		sign int // -1=negative, 0=zero, 1=positive
	}{
		{"empty", nil, 0},
		{"single", []float64{5}, 0},
		{"flat", []float64{3, 3, 3}, 0},
		{"ascending", []float64{1, 2, 3, 4}, 1},
		{"descending", []float64{4, 3, 2, 1}, -1},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := linearSlope(tt.xs)
			var gotSign int
			switch {
			case s > 0:
				gotSign = 1
			case s < 0:
				gotSign = -1
			}
			if gotSign != tt.sign {
				t.Errorf("slope sign = %d, want %d (slope=%v)", gotSign, tt.sign, s)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// NodeDegradationTracker
// ---------------------------------------------------------------------------

func testDegCfg() DegradationConfig {
	return DegradationConfig{
		WindowSize:               10,
		MinSamples:               4,
		PerformanceDropThreshold: 0.20,
		ErrorRateSpikeThreshold:  0.15,
		NegativeSlopeThreshold:   0, // disabled
	}
}

func TestNodeDegradationTracker_NoEventBelowThreshold(t *testing.T) {
	tr := NewNodeDegradationTracker("n1", testDegCfg(), nil)
	for i := 0; i < 8; i++ {
		tr.RecordMetric("sharpe", 1.5+float64(i)*0.01) // gently improving
	}
	events := tr.Check()
	if len(events) != 0 {
		t.Fatalf("want no events, got %d", len(events))
	}
}

func TestNodeDegradationTracker_DetectsPerformanceDrop(t *testing.T) {
	tr := NewNodeDegradationTracker("n1", testDegCfg(), nil)
	// First half: baseline ~2.0
	for i := 0; i < 5; i++ {
		tr.RecordMetric("sharpe", 2.0)
	}
	// Second half: current ~1.0 (50% drop → above 20% threshold)
	for i := 0; i < 5; i++ {
		tr.RecordMetric("sharpe", 1.0)
	}

	events := tr.Check()
	if len(events) == 0 {
		t.Fatal("want at least 1 degradation event for 50% sharpe drop")
	}
	ev := events[0]
	if ev.Kind != DegradationPerformance {
		t.Fatalf("want DegradationPerformance, got %v", ev.Kind)
	}
	if ev.NodeID != "n1" {
		t.Fatalf("want node n1, got %q", ev.NodeID)
	}
	if ev.DropPct <= 0 {
		t.Fatalf("want positive DropPct, got %v", ev.DropPct)
	}
}

func TestNodeDegradationTracker_DetectsErrorRateSpike(t *testing.T) {
	tr := NewNodeDegradationTracker("n1", testDegCfg(), nil)
	// Baseline: 5% error rate
	for i := 0; i < 5; i++ {
		tr.RecordErrorRate(0.05)
	}
	// Current: 25% error rate (20pp spike → above 15% threshold)
	for i := 0; i < 5; i++ {
		tr.RecordErrorRate(0.25)
	}

	events := tr.Check()
	if len(events) == 0 {
		t.Fatal("want at least 1 error-rate event")
	}
	found := false
	for _, ev := range events {
		if ev.Kind == DegradationErrorRate {
			found = true
		}
	}
	if !found {
		t.Fatal("want DegradationErrorRate event")
	}
}

func TestNodeDegradationTracker_CooldownPreventsFlood(t *testing.T) {
	tr := NewNodeDegradationTracker("n1", testDegCfg(), nil)
	tr.cooldown = 10 * time.Second // long cooldown

	// Push enough samples to trigger.
	for i := 0; i < 5; i++ {
		tr.RecordMetric("sharpe", 2.0)
	}
	for i := 0; i < 5; i++ {
		tr.RecordMetric("sharpe", 0.5)
	}

	first := tr.Check()
	if len(first) == 0 {
		t.Fatal("want event on first check")
	}

	// Immediately add more bad samples and check again.
	for i := 0; i < 3; i++ {
		tr.RecordMetric("sharpe", 0.5)
	}
	second := tr.Check()
	for _, ev := range second {
		if ev.Metric == "sharpe" {
			t.Fatal("want no sharpe event during cooldown")
		}
	}
}

func TestNodeDegradationTracker_InsufficientSamples(t *testing.T) {
	tr := NewNodeDegradationTracker("n1", testDegCfg(), nil)
	tr.RecordMetric("sharpe", 2.0) // only 1 sample (< MinSamples=4)
	events := tr.Check()
	if len(events) != 0 {
		t.Fatalf("want no events with insufficient samples, got %d", len(events))
	}
}

// ---------------------------------------------------------------------------
// DegradationMonitor
// ---------------------------------------------------------------------------

func TestDegradationMonitor_CheckAll_EmitsEvents(t *testing.T) {
	bus := NewEventBus(nil)
	m := NewMetrics()
	mon := NewDegradationMonitor(testDegCfg(), bus, m, nil)

	ch, cancel := bus.Subscribe(8, EventDegradationDetected)
	defer cancel()

	tr := mon.Tracker("node-alpha")
	// Trigger a degradation.
	for i := 0; i < 5; i++ {
		tr.RecordMetric("sharpe", 2.0)
	}
	for i := 0; i < 5; i++ {
		tr.RecordMetric("sharpe", 0.5)
	}

	mon.CheckAll()

	select {
	case ev := <-ch:
		if ev.Type != EventDegradationDetected {
			t.Fatalf("want DegradationDetected, got %v", ev.Type)
		}
		p := ev.Payload.(DegradationDetectedPayload)
		if p.NodeID != "node-alpha" {
			t.Fatalf("want node-alpha, got %q", p.NodeID)
		}
	case <-time.After(time.Second):
		t.Fatal("timeout waiting for DegradationDetected event")
	}
}

func TestDegradationMonitor_Remove(t *testing.T) {
	mon := NewDegradationMonitor(testDegCfg(), nil, nil, nil)
	_ = mon.Tracker("n1")
	mon.Remove("n1")
	// After remove, Tracker creates a fresh one — no panic.
	tr := mon.Tracker("n1")
	if tr == nil {
		t.Fatal("Tracker after Remove should not be nil")
	}
}

func TestDegradationMonitor_MultipleNodes(t *testing.T) {
	bus := NewEventBus(nil)
	mon := NewDegradationMonitor(testDegCfg(), bus, nil, nil)

	ch, cancel := bus.Subscribe(16, EventDegradationDetected)
	defer cancel()

	for _, nodeID := range []string{"n1", "n2"} {
		tr := mon.Tracker(nodeID)
		for i := 0; i < 5; i++ {
			tr.RecordMetric("accuracy", 0.9)
		}
		for i := 0; i < 5; i++ {
			tr.RecordMetric("accuracy", 0.5) // 44% drop
		}
	}

	mon.CheckAll()

	received := make(map[string]bool)
	deadline := time.After(time.Second)
	for len(received) < 2 {
		select {
		case ev := <-ch:
			p := ev.Payload.(DegradationDetectedPayload)
			received[p.NodeID] = true
		case <-deadline:
			t.Fatalf("only received events for nodes: %v", received)
		}
	}
}
