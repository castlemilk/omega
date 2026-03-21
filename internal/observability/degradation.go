package observability

import (
	"log/slog"
	"math"
	"sync"
	"time"
)

// ---------------------------------------------------------------------------
// Sliding window
// ---------------------------------------------------------------------------

// window is a fixed-capacity circular buffer of float64 samples.
type window struct {
	data []float64
	pos  int
	full bool
}

func newWindow(size int) *window {
	return &window{data: make([]float64, size)}
}

func (w *window) push(v float64) {
	w.data[w.pos] = v
	w.pos = (w.pos + 1) % len(w.data)
	if !w.full && w.pos == 0 {
		w.full = true
	}
}

// values returns the samples in chronological order (oldest first).
func (w *window) values() []float64 {
	if !w.full {
		return w.data[:w.pos]
	}
	out := make([]float64, len(w.data))
	copy(out, w.data[w.pos:])
	copy(out[len(w.data)-w.pos:], w.data[:w.pos])
	return out
}

func (w *window) len() int {
	if w.full {
		return len(w.data)
	}
	return w.pos
}

// ---------------------------------------------------------------------------
// Statistical helpers
// ---------------------------------------------------------------------------

// mean computes the arithmetic mean. Returns 0 for empty slices.
func mean(xs []float64) float64 {
	if len(xs) == 0 {
		return 0
	}
	sum := 0.0
	for _, x := range xs {
		sum += x
	}
	return sum / float64(len(xs))
}

// linearSlope estimates the slope of xs over time using ordinary least squares.
// Returns 0 for slices shorter than 2 elements.
func linearSlope(xs []float64) float64 {
	n := float64(len(xs))
	if n < 2 {
		return 0
	}
	// t = 0, 1, 2, … so mean_t = (n-1)/2
	meanT := (n - 1) / 2
	meanY := mean(xs)

	var num, den float64
	for i, y := range xs {
		t := float64(i)
		num += (t - meanT) * (y - meanY)
		den += (t - meanT) * (t - meanT)
	}
	if den == 0 {
		return 0
	}
	return num / den
}

// ---------------------------------------------------------------------------
// DegradationKind
// ---------------------------------------------------------------------------

// DegradationKind classifies the type of degradation detected.
type DegradationKind string

const (
	DegradationPerformance DegradationKind = "performance" // metric value declining
	DegradationErrorRate   DegradationKind = "error_rate"  // error rate spiking
)

// ---------------------------------------------------------------------------
// DegradationConfig
// ---------------------------------------------------------------------------

// DegradationConfig controls detection sensitivity.
type DegradationConfig struct {
	// WindowSize is the number of cycle observations kept per metric.
	WindowSize int

	// MinSamples is the minimum number of samples before detection fires.
	MinSamples int

	// PerformanceDropThreshold is the relative drop (0–1) from baseline mean
	// that triggers a performance-regression alert.
	// e.g. 0.15 = 15% decline.
	PerformanceDropThreshold float64

	// ErrorRateSpikeThreshold is the absolute error-rate increase that triggers
	// an error-rate-spike alert.
	// e.g. 0.10 = 10 percentage points above baseline.
	ErrorRateSpikeThreshold float64

	// NegativeSlopeThreshold: if the OLS slope of the metric window is more
	// negative than this value per cycle, it triggers a performance alert.
	// Set to 0 to disable slope-based detection.
	NegativeSlopeThreshold float64
}

// DefaultDegradationConfig returns sensible production defaults.
func DefaultDegradationConfig() DegradationConfig {
	return DegradationConfig{
		WindowSize:               20,
		MinSamples:               5,
		PerformanceDropThreshold: 0.15,
		ErrorRateSpikeThreshold:  0.10,
		NegativeSlopeThreshold:   0,
	}
}

// ---------------------------------------------------------------------------
// NodeDegradationTracker
// ---------------------------------------------------------------------------

// NodeDegradationTracker maintains sliding windows for a single node and
// detects degradation patterns.
type NodeDegradationTracker struct {
	mu       sync.Mutex
	nodeID   string
	cfg      DegradationConfig
	logger   *slog.Logger

	// metric name → sliding window of observed values
	metricWindows map[string]*window

	// error rate window
	errorRateWindow *window

	// baseline: first-half mean of the window (recomputed on each check)
	baselines map[string]float64

	// When was the last degradation event fired per metric (to avoid flooding).
	lastFired map[string]time.Time
	cooldown  time.Duration
}

// NewNodeDegradationTracker creates a tracker for a single node.
func NewNodeDegradationTracker(nodeID string, cfg DegradationConfig, logger *slog.Logger) *NodeDegradationTracker {
	if logger == nil {
		logger = slog.Default()
	}
	return &NodeDegradationTracker{
		nodeID:          nodeID,
		cfg:             cfg,
		logger:          logger,
		metricWindows:   make(map[string]*window),
		baselines:       make(map[string]float64),
		lastFired:       make(map[string]time.Time),
		errorRateWindow: newWindow(cfg.WindowSize),
		cooldown:        5 * time.Minute,
	}
}

// RecordMetric appends a new observation for a named performance metric.
// Call once per cycle per metric (e.g. "sharpe", "accuracy", "pnl").
func (t *NodeDegradationTracker) RecordMetric(name string, value float64) {
	t.mu.Lock()
	defer t.mu.Unlock()

	w, ok := t.metricWindows[name]
	if !ok {
		w = newWindow(t.cfg.WindowSize)
		t.metricWindows[name] = w
	}
	w.push(value)
}

// RecordErrorRate appends a new error-rate observation (0.0–1.0).
func (t *NodeDegradationTracker) RecordErrorRate(rate float64) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.errorRateWindow.push(rate)
}

// DegradationEvent describes a single detected degradation.
type DegradationEvent struct {
	NodeID   string
	Kind     DegradationKind
	Metric   string
	Current  float64
	Baseline float64
	DropPct  float64
	Slope    float64
	At       time.Time
}

// Check analyses the windows and returns any newly detected degradation events.
// Returns nil if no degradation is detected or cooldown is active.
func (t *NodeDegradationTracker) Check() []DegradationEvent {
	t.mu.Lock()
	defer t.mu.Unlock()

	now := time.Now()
	var events []DegradationEvent

	// --- Performance metrics ---
	for name, w := range t.metricWindows {
		vals := w.values()
		if len(vals) < t.cfg.MinSamples {
			continue
		}
		if t.inCooldown(name, now) {
			continue
		}

		// Baseline = mean of the first half of the window.
		half := len(vals) / 2
		baseline := mean(vals[:half])
		current := mean(vals[half:])

		var fired bool

		// Drop from baseline.
		if baseline != 0 {
			drop := (baseline - current) / math.Abs(baseline)
			if drop >= t.cfg.PerformanceDropThreshold {
				events = append(events, DegradationEvent{
					NodeID:   t.nodeID,
					Kind:     DegradationPerformance,
					Metric:   name,
					Current:  current,
					Baseline: baseline,
					DropPct:  drop * 100,
					At:       now,
				})
				fired = true
			}
		}

		// Negative slope (trend detection).
		if !fired && t.cfg.NegativeSlopeThreshold < 0 {
			slope := linearSlope(vals)
			if slope <= t.cfg.NegativeSlopeThreshold {
				events = append(events, DegradationEvent{
					NodeID:   t.nodeID,
					Kind:     DegradationPerformance,
					Metric:   name,
					Current:  current,
					Baseline: baseline,
					Slope:    slope,
					At:       now,
				})
				fired = true
			}
		}

		if fired {
			t.lastFired[name] = now
			t.logger.Warn("performance degradation detected",
				"node_id", t.nodeID,
				"metric", name,
				"baseline", baseline,
				"current", current,
			)
		}
	}

	// --- Error rate ---
	erVals := t.errorRateWindow.values()
	erKey := "_error_rate"
	if len(erVals) >= t.cfg.MinSamples && !t.inCooldown(erKey, now) {
		half := len(erVals) / 2
		baseline := mean(erVals[:half])
		current := mean(erVals[half:])
		spike := current - baseline
		if spike >= t.cfg.ErrorRateSpikeThreshold {
			events = append(events, DegradationEvent{
				NodeID:   t.nodeID,
				Kind:     DegradationErrorRate,
				Metric:   "error_rate",
				Current:  current,
				Baseline: baseline,
				DropPct:  spike * 100,
				At:       now,
			})
			t.lastFired[erKey] = now
			t.logger.Warn("error rate spike detected",
				"node_id", t.nodeID,
				"baseline_rate", baseline,
				"current_rate", current,
			)
		}
	}

	return events
}

func (t *NodeDegradationTracker) inCooldown(key string, now time.Time) bool {
	last, ok := t.lastFired[key]
	if !ok {
		return false
	}
	return now.Sub(last) < t.cooldown
}

// ---------------------------------------------------------------------------
// DegradationMonitor — aggregates trackers for all nodes
// ---------------------------------------------------------------------------

// DegradationMonitor manages per-node degradation trackers and wires detections
// into the event bus and metrics.
type DegradationMonitor struct {
	mu       sync.RWMutex
	trackers map[string]*NodeDegradationTracker
	cfg      DegradationConfig
	bus      *EventBus // may be nil
	metrics  *Metrics  // may be nil
	logger   *slog.Logger
}

// NewDegradationMonitor creates a monitor. bus and metrics may be nil.
func NewDegradationMonitor(cfg DegradationConfig, bus *EventBus, m *Metrics, logger *slog.Logger) *DegradationMonitor {
	if logger == nil {
		logger = slog.Default()
	}
	return &DegradationMonitor{
		trackers: make(map[string]*NodeDegradationTracker),
		cfg:      cfg,
		bus:      bus,
		metrics:  m,
		logger:   logger,
	}
}

// Tracker returns the degradation tracker for a node, creating it lazily.
func (dm *DegradationMonitor) Tracker(nodeID string) *NodeDegradationTracker {
	dm.mu.RLock()
	t, ok := dm.trackers[nodeID]
	dm.mu.RUnlock()
	if ok {
		return t
	}

	dm.mu.Lock()
	defer dm.mu.Unlock()
	if t, ok = dm.trackers[nodeID]; ok {
		return t
	}
	t = NewNodeDegradationTracker(nodeID, dm.cfg, dm.logger)
	dm.trackers[nodeID] = t
	return t
}

// CheckAll runs degradation checks on all tracked nodes and emits events for
// any degradation found. Call this once per cycle (or on a ticker).
func (dm *DegradationMonitor) CheckAll() {
	dm.mu.RLock()
	nodes := make([]string, 0, len(dm.trackers))
	for id := range dm.trackers {
		nodes = append(nodes, id)
	}
	dm.mu.RUnlock()

	for _, nodeID := range nodes {
		t := dm.Tracker(nodeID)
		events := t.Check()
		for _, ev := range events {
			if dm.metrics != nil {
				dm.metrics.RecordDegradation(ev.NodeID, string(ev.Kind))
			}
			if dm.bus != nil {
				dm.bus.PublishDegradationDetected(DegradationDetectedPayload{
					NodeID:   ev.NodeID,
					Kind:     string(ev.Kind),
					Metric:   ev.Metric,
					Current:  ev.Current,
					Baseline: ev.Baseline,
					DropPct:  ev.DropPct,
				})
			}
		}
	}
}

// Remove deletes the tracker for a node.
func (dm *DegradationMonitor) Remove(nodeID string) {
	dm.mu.Lock()
	defer dm.mu.Unlock()
	delete(dm.trackers, nodeID)
}
