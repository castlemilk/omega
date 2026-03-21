package eval

import (
	"time"

	"github.com/benebsworth/omega/internal/core"
)

// ---------------------------------------------------------------------------
// Fixed-clock helper
// ---------------------------------------------------------------------------

// FixedClock returns a clock function whose time advances by step each call.
// This makes ImprovementScheduler tests fully deterministic.
type FixedClock struct {
	current time.Time
	step    time.Duration
}

// NewFixedClock creates a FixedClock starting at a fixed epoch.
// step is added each time Tick is called.
func NewFixedClock(step time.Duration) *FixedClock {
	// Fixed epoch: 2024-01-01 00:00:00 UTC — no time.Now().
	epoch := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	return &FixedClock{current: epoch, step: step}
}

// Now returns the current fixed time.
func (c *FixedClock) Now() time.Time { return c.current }

// Tick advances the clock by one step and returns the new time.
func (c *FixedClock) Tick() time.Time {
	c.current = c.current.Add(c.step)
	return c.current
}

// Advance moves the clock forward by d.
func (c *FixedClock) Advance(d time.Duration) time.Time {
	c.current = c.current.Add(d)
	return c.current
}

// ---------------------------------------------------------------------------
// ImprovementHarness
// ---------------------------------------------------------------------------

// ImprovementHarness wraps ImprovementScheduler with a FixedClock.
type ImprovementHarness struct {
	Scheduler *core.ImprovementScheduler
	Clock     *FixedClock
}

// NewImprovementHarness creates an ImprovementScheduler driven by a FixedClock.
// step is how much time passes per Tick (default 1 minute if zero).
func NewImprovementHarness(step time.Duration) *ImprovementHarness {
	if step == 0 {
		step = time.Minute
	}
	fc := NewFixedClock(step)
	s := core.NewImprovementScheduler(fc.Now)
	return &ImprovementHarness{Scheduler: s, Clock: fc}
}

// RegisterNode registers a node with default config, optionally run immediately.
func (h *ImprovementHarness) RegisterNode(nodeID string, runImmediately bool) {
	cfg := core.DefaultNodeScheduleConfig(nodeID)
	h.Scheduler.Register(nodeID, &cfg, runImmediately)
}

// RegisterNodeWithConfig registers a node with an explicit config.
func (h *ImprovementHarness) RegisterNodeWithConfig(cfg core.NodeScheduleConfig) {
	h.Scheduler.Register(cfg.NodeID, &cfg, false)
}

// TickAndDue advances the clock by one step and returns the nodes now due.
func (h *ImprovementHarness) TickAndDue() []string {
	h.Clock.Tick()
	return h.Scheduler.DueNodes()
}

// SimulateFailures records n consecutive failures for nodeID, each separated by
// one clock tick. Returns the failure counts at each step.
func (h *ImprovementHarness) SimulateFailures(nodeID string, n int) []bool {
	suspended := make([]bool, n)
	for i := 0; i < n; i++ {
		_ = h.Scheduler.RecordOutcome(nodeID, false, nil)
		h.Clock.Tick()
		suspended[i] = h.Scheduler.IsSuspended(nodeID)
	}
	return suspended
}

// SimulateSuccess records a success with the given score.
func (h *ImprovementHarness) SimulateSuccess(nodeID string, score float64) error {
	return h.Scheduler.RecordOutcome(nodeID, true, &score)
}

// ScorePtr returns a *float64 for convenience.
func ScorePtr(v float64) *float64 { return &v }
