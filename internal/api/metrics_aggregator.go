package api

import (
	"context"
	"sync"
	"time"

	"github.com/benebsworth/omega/internal/observability"
)

const rollingWindowSize = 100

// LiveMetrics holds the latest computed aggregated metrics.
type LiveMetrics struct {
	CyclesPerMinute1m          float64        `json:"cycles_per_minute_1m"`
	CyclesPerMinute5m          float64        `json:"cycles_per_minute_5m"`
	CyclesPerMinute15m         float64        `json:"cycles_per_minute_15m"`
	AvgCycleDurationMs1m       float64        `json:"avg_cycle_duration_ms_1m"`
	AvgCycleDurationMs5m       float64        `json:"avg_cycle_duration_ms_5m"`
	SafetyViolationRate        float64        `json:"safety_violation_rate"`
	AdversarialAlertRate       float64        `json:"adversarial_alert_rate"`
	ImprovementSuccessRate     float64        `json:"improvement_success_rate"`
	NodesByAutonomyLevel       map[string]int `json:"nodes_by_autonomy_level"`
	NodesByCircuitBreakerState map[string]int `json:"nodes_by_circuit_breaker_state"`
	UpdatedAt                  time.Time      `json:"updated_at"`
}

// timestampedEvent pairs an event with its reception time for windowed queries.
type timestampedEvent struct {
	event      observability.Event
	receivedAt time.Time
}

// MetricsAggregator subscribes to the EventBus, maintains a rolling window of
// the last 100 events, and computes LiveMetrics every second.
type MetricsAggregator struct {
	ch        <-chan observability.Event
	cancelSub func()

	mu            sync.RWMutex
	rollingWindow []timestampedEvent
	nodeAutonomy  map[string]int    // nodeID -> autonomy level (1–4)
	nodeCBState   map[string]string // nodeID -> "closed" | "open" | "half_open"
	liveMetrics   LiveMetrics
}

// NewMetricsAggregator creates a MetricsAggregator wired to the given EventBus.
// The subscription is registered immediately so no events are missed before Run is called.
func NewMetricsAggregator(bus *observability.EventBus) *MetricsAggregator {
	ch, cancel := bus.Subscribe(256) // all events
	return &MetricsAggregator{
		ch:            ch,
		cancelSub:     cancel,
		rollingWindow: make([]timestampedEvent, 0, rollingWindowSize),
		nodeAutonomy:  make(map[string]int),
		nodeCBState:   make(map[string]string),
		liveMetrics: LiveMetrics{
			NodesByAutonomyLevel:       map[string]int{"manual": 0, "supervised": 0, "semi": 0, "full": 0},
			NodesByCircuitBreakerState: map[string]int{"closed": 0, "open": 0, "half_open": 0},
		},
	}
}

// Run starts the aggregation loop. It blocks until ctx is cancelled.
func (a *MetricsAggregator) Run(ctx context.Context) {
	defer a.cancelSub()

	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case e, ok := <-a.ch:
			if !ok {
				return
			}
			a.ingest(e)
		case <-ticker.C:
			a.compute()
		}
	}
}

// GetLiveMetrics returns a snapshot of the most recently computed metrics.
func (a *MetricsAggregator) GetLiveMetrics() LiveMetrics {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.liveMetrics
}

// ingest adds the event to the rolling window and updates node state maps.
func (a *MetricsAggregator) ingest(e observability.Event) {
	a.mu.Lock()
	defer a.mu.Unlock()

	te := timestampedEvent{event: e, receivedAt: time.Now()}
	a.rollingWindow = append(a.rollingWindow, te)
	if len(a.rollingWindow) > rollingWindowSize {
		a.rollingWindow = a.rollingWindow[1:]
	}

	// Update per-node state from registration and state-change events.
	switch e.Type {
	case observability.EventNodeRegistered:
		if p, ok := e.Payload.(observability.NodeRegisteredPayload); ok {
			if _, exists := a.nodeAutonomy[p.NodeID]; !exists {
				a.nodeAutonomy[p.NodeID] = 1 // starts at manual
			}
			if _, exists := a.nodeCBState[p.NodeID]; !exists {
				a.nodeCBState[p.NodeID] = "closed"
			}
		}
	case observability.EventNodePromoted:
		if p, ok := e.Payload.(observability.NodePromotedPayload); ok {
			a.nodeAutonomy[p.NodeID] = int(p.ToLevel)
			if _, exists := a.nodeCBState[p.NodeID]; !exists {
				a.nodeCBState[p.NodeID] = "closed"
			}
		}
	case observability.EventNodeDemoted:
		if p, ok := e.Payload.(observability.NodeDemotedPayload); ok {
			a.nodeAutonomy[p.NodeID] = int(p.ToLevel)
			if _, exists := a.nodeCBState[p.NodeID]; !exists {
				a.nodeCBState[p.NodeID] = "closed"
			}
		}
	case observability.EventCircuitBreakerTripped:
		if p, ok := e.Payload.(observability.CircuitBreakerTrippedPayload); ok {
			a.nodeCBState[p.NodeID] = "open"
		}
	}
}

// compute recalculates LiveMetrics from the current rolling window and node maps.
func (a *MetricsAggregator) compute() {
	a.mu.Lock()
	defer a.mu.Unlock()

	now := time.Now()
	cutoff1m := now.Add(-1 * time.Minute)
	cutoff5m := now.Add(-5 * time.Minute)
	cutoff15m := now.Add(-15 * time.Minute)

	var (
		cycles1m, cycles5m, cycles15m   int
		cycleDurMs1m, cycleDurMs5m      float64
		cycleDurCount1m, cycleDurCount5m int
		totalCycles                     int
		safetyViolations                int
		adversarialAlerts               int
		improvements, improveSucceeded  int
	)

	for _, te := range a.rollingWindow {
		switch te.event.Type {
		case observability.EventCycleCompleted:
			totalCycles++
			p, ok := te.event.Payload.(observability.CycleCompletedPayload)
			if !ok {
				continue
			}
			durMs := p.DurationSecs * 1000
			if te.receivedAt.After(cutoff1m) {
				cycles1m++
				cycleDurMs1m += durMs
				cycleDurCount1m++
			}
			if te.receivedAt.After(cutoff5m) {
				cycles5m++
				cycleDurMs5m += durMs
				cycleDurCount5m++
			}
			if te.receivedAt.After(cutoff15m) {
				cycles15m++
			}
		case observability.EventSafetyViolation:
			safetyViolations++
		case observability.EventAdversarialVeto:
			adversarialAlerts++
		case observability.EventImprovementApplied:
			improvements++
			if p, ok := te.event.Payload.(observability.ImprovementAppliedPayload); ok {
				if improvementSucceeded(p) {
					improveSucceeded++
				}
			}
		}
	}

	var safetyViolationRate, adversarialAlertRate, improvementSuccessRate float64
	if totalCycles > 0 {
		safetyViolationRate = float64(safetyViolations) / float64(totalCycles)
		adversarialAlertRate = float64(adversarialAlerts) / float64(totalCycles)
	}
	if improvements > 0 {
		improvementSuccessRate = float64(improveSucceeded) / float64(improvements)
	}

	var avgDurMs1m, avgDurMs5m float64
	if cycleDurCount1m > 0 {
		avgDurMs1m = cycleDurMs1m / float64(cycleDurCount1m)
	}
	if cycleDurCount5m > 0 {
		avgDurMs5m = cycleDurMs5m / float64(cycleDurCount5m)
	}

	// Nodes by autonomy level.
	autonomyMap := map[string]int{"manual": 0, "supervised": 0, "semi": 0, "full": 0}
	for _, level := range a.nodeAutonomy {
		switch level {
		case 1:
			autonomyMap["manual"]++
		case 2:
			autonomyMap["supervised"]++
		case 3:
			autonomyMap["semi"]++
		case 4:
			autonomyMap["full"]++
		}
	}

	// Nodes by circuit breaker state.
	cbMap := map[string]int{"closed": 0, "open": 0, "half_open": 0}
	for _, state := range a.nodeCBState {
		cbMap[state]++
	}

	a.liveMetrics = LiveMetrics{
		CyclesPerMinute1m:          cyclesPerMinute(cycles1m, 1),
		CyclesPerMinute5m:          cyclesPerMinute(cycles5m, 5),
		CyclesPerMinute15m:         cyclesPerMinute(cycles15m, 15),
		AvgCycleDurationMs1m:       avgDurMs1m,
		AvgCycleDurationMs5m:       avgDurMs5m,
		SafetyViolationRate:        safetyViolationRate,
		AdversarialAlertRate:       adversarialAlertRate,
		ImprovementSuccessRate:     improvementSuccessRate,
		NodesByAutonomyLevel:       autonomyMap,
		NodesByCircuitBreakerState: cbMap,
		UpdatedAt:                  now,
	}
}

// cyclesPerMinute converts a raw count in a window of windowMinutes to a rate.
func cyclesPerMinute(count int, windowMinutes float64) float64 {
	return float64(count) / windowMinutes
}

// improvementSucceeded reports whether the avg of afterMetrics exceeds the avg
// of beforeMetrics, serving as a simple proxy for improvement success.
func improvementSucceeded(p observability.ImprovementAppliedPayload) bool {
	if len(p.BeforeMetrics) == 0 || len(p.AfterMetrics) == 0 {
		return false
	}
	var beforeSum, afterSum float64
	for _, v := range p.BeforeMetrics {
		beforeSum += v
	}
	for _, v := range p.AfterMetrics {
		afterSum += v
	}
	return afterSum > beforeSum
}
