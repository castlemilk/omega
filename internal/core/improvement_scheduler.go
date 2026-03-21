package core

// improvement_scheduler.go — ImprovementScheduler
//
// Priority-queue-based scheduler for improvement trials.  Go owns scheduling
// and cooldown logic.  The actual TPE optimisation stays in Python and is
// called via the TPEOptimizer bridge interface.

import (
	"container/heap"
	"fmt"
	"log/slog"
	"math"
	"sync"
	"time"
)

// ---------------------------------------------------------------------------
// Bridge interface — Python implements TPE on the other side
// ---------------------------------------------------------------------------

// TPEOptimizer is called by the orchestrator to propose next hyperparameter
// trials for a node.  Python implements this via Connect-RPC or subprocess.
type TPEOptimizer interface {
	// ProposeTrialParams returns the next set of parameters to try for nodeID.
	ProposeTrialParams(nodeID string, history []TrialHistory) (map[string]any, error)
}

// TrialHistory records a past improvement trial for a node.
type TrialHistory struct {
	NodeID    string
	Params    map[string]any
	Score     float64
	Timestamp time.Time
	Success   bool
}

// ---------------------------------------------------------------------------
// NodeScheduleConfig
// ---------------------------------------------------------------------------

// NodeScheduleConfig holds per-node scheduling parameters.
type NodeScheduleConfig struct {
	NodeID                string
	Interval              time.Duration // how often to run improvement
	Cooldown              time.Duration // cooldown after failure
	MaxConsecutiveFailures int          // suspend after this many failures
	Priority              float64      // relative priority (higher = first)
	Enabled               bool
}

// DefaultNodeScheduleConfig returns a config with sensible defaults.
func DefaultNodeScheduleConfig(nodeID string) NodeScheduleConfig {
	return NodeScheduleConfig{
		NodeID:                nodeID,
		Interval:              time.Hour,
		Cooldown:              5 * time.Minute,
		MaxConsecutiveFailures: 5,
		Priority:              1.0,
		Enabled:               true,
	}
}

// ---------------------------------------------------------------------------
// scheduleEntry — heap element
// ---------------------------------------------------------------------------

type scheduleEntry struct {
	nextRunAt           time.Time
	nodeID              string
	priority            float64
	consecutiveFailures int
	lastRunAt           *time.Time
	lastScore           *float64
	// generation counter: entries are invalidated when a node is re-scheduled
	// by bumping its generation in the scheduler and checking on pop.
	generation uint64
}

// ---------------------------------------------------------------------------
// scheduleHeap — min-heap by nextRunAt
// ---------------------------------------------------------------------------

type scheduleHeap []*scheduleEntry

func (h scheduleHeap) Len() int           { return len(h) }
func (h scheduleHeap) Less(i, j int) bool { return h[i].nextRunAt.Before(h[j].nextRunAt) }
func (h scheduleHeap) Swap(i, j int)      { h[i], h[j] = h[j], h[i] }
func (h *scheduleHeap) Push(x any)        { *h = append(*h, x.(*scheduleEntry)) }
func (h *scheduleHeap) Pop() any {
	old := *h
	n := len(old)
	x := old[n-1]
	*h = old[:n-1]
	return x
}

// ---------------------------------------------------------------------------
// ImprovementScheduler
// ---------------------------------------------------------------------------

// ImprovementScheduler is a priority-queue-based scheduler for improvement
// trials.  It is safe for concurrent use.
type ImprovementScheduler struct {
	mu          sync.Mutex
	configs     map[string]NodeScheduleConfig
	generations map[string]uint64      // current generation per nodeID
	entries     map[string]*scheduleEntry // latest entry per nodeID
	h           scheduleHeap
	clock       func() time.Time
}

// NewImprovementScheduler creates a scheduler.  clock may be nil (uses time.Now).
func NewImprovementScheduler(clock func() time.Time) *ImprovementScheduler {
	if clock == nil {
		clock = time.Now
	}
	s := &ImprovementScheduler{
		configs:     make(map[string]NodeScheduleConfig),
		generations: make(map[string]uint64),
		entries:     make(map[string]*scheduleEntry),
		clock:       clock,
	}
	heap.Init(&s.h)
	return s
}

// Register adds a node to the scheduler.  If runImmediately is true the first
// trial is due immediately; otherwise it is scheduled cfg.Interval from now.
func (s *ImprovementScheduler) Register(nodeID string, cfg *NodeScheduleConfig, runImmediately bool) {
	s.mu.Lock()
	defer s.mu.Unlock()

	c := DefaultNodeScheduleConfig(nodeID)
	if cfg != nil {
		c = *cfg
	}
	c.NodeID = nodeID
	s.configs[nodeID] = c

	now := s.clock()
	nextRun := now.Add(c.Interval)
	if runImmediately {
		nextRun = now
	}

	gen := s.generations[nodeID] + 1
	s.generations[nodeID] = gen

	e := &scheduleEntry{
		nextRunAt:  nextRun,
		nodeID:     nodeID,
		priority:   c.Priority,
		generation: gen,
	}
	s.entries[nodeID] = e
	heap.Push(&s.h, e)
	slog.Debug("scheduler: registered node", "node_id", nodeID, "next_run_in", nextRun.Sub(now).Truncate(time.Second))
}

// Unregister removes a node from the scheduler.
func (s *ImprovementScheduler) Unregister(nodeID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.configs, nodeID)
	delete(s.entries, nodeID)
	s.generations[nodeID]++ // invalidate any stale heap entries
	s.rebuildHeap()
}

// UpdateConfig updates scheduling parameters for a registered node.
func (s *ImprovementScheduler) UpdateConfig(nodeID string, fn func(*NodeScheduleConfig)) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	cfg, ok := s.configs[nodeID]
	if !ok {
		return fmt.Errorf("node %q not registered", nodeID)
	}
	fn(&cfg)
	s.configs[nodeID] = cfg
	return nil
}

// DueNodes returns node IDs whose next run time is <= now, ordered by
// descending priority (most urgent first).  Suspended nodes are skipped.
func (s *ImprovementScheduler) DueNodes() []string {
	s.mu.Lock()
	defer s.mu.Unlock()

	now := s.clock()
	type item struct {
		priority float64
		nodeID   string
	}
	var due []item

	for s.h.Len() > 0 && !s.h[0].nextRunAt.After(now) {
		e := heap.Pop(&s.h).(*scheduleEntry)

		// Skip stale entries
		if s.generations[e.nodeID] != e.generation {
			continue
		}
		if s.entries[e.nodeID] != e {
			continue
		}

		cfg, ok := s.configs[e.nodeID]
		if !ok || !cfg.Enabled {
			continue
		}
		if e.consecutiveFailures >= cfg.MaxConsecutiveFailures {
			slog.Warn("scheduler: node suspended", "node_id", e.nodeID, "failures", e.consecutiveFailures)
			continue
		}
		due = append(due, item{priority: e.priority, nodeID: e.nodeID})
	}

	// Sort by descending priority
	for i := 1; i < len(due); i++ {
		for j := i; j > 0 && due[j].priority > due[j-1].priority; j-- {
			due[j], due[j-1] = due[j-1], due[j]
		}
	}

	out := make([]string, len(due))
	for i, d := range due {
		out[i] = d.nodeID
	}
	return out
}

// RecordOutcome records the result of an improvement trial and reschedules the
// node.  On failure, exponential back-off is applied.
func (s *ImprovementScheduler) RecordOutcome(nodeID string, success bool, score *float64) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	cfg, ok := s.configs[nodeID]
	if !ok {
		slog.Warn("scheduler: RecordOutcome for unregistered node", "node_id", nodeID)
		return fmt.Errorf("node %q not registered", nodeID)
	}

	now := s.clock()
	e := s.entries[nodeID]
	if e == nil {
		e = &scheduleEntry{nodeID: nodeID, priority: cfg.Priority}
	}
	e.lastRunAt = &now
	e.lastScore = score

	var delay time.Duration
	if success {
		e.consecutiveFailures = 0
		delay = cfg.Interval
		slog.Debug("scheduler: node succeeded", "node_id", nodeID, "next_run_in", delay.Truncate(time.Second))
	} else {
		e.consecutiveFailures++
		// Exponential back-off capped at 4× interval
		backoff := float64(cfg.Cooldown) * math.Pow(2, float64(min(e.consecutiveFailures-1, 5)))
		maxBackoff := float64(cfg.Interval) * 4
		if backoff > maxBackoff {
			backoff = maxBackoff
		}
		delay = time.Duration(backoff)
		slog.Info("scheduler: node failed", "node_id", nodeID, "attempt", e.consecutiveFailures, "cooldown", delay.Truncate(time.Second))
	}

	e.nextRunAt = now.Add(delay)
	gen := s.generations[nodeID] + 1
	s.generations[nodeID] = gen
	e.generation = gen
	s.entries[nodeID] = e
	heap.Push(&s.h, e)
	return nil
}

// ResetFailures clears the failure counter and schedules the node immediately.
func (s *ImprovementScheduler) ResetFailures(nodeID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	e := s.entries[nodeID]
	if e == nil {
		return
	}
	e.consecutiveFailures = 0
	e.nextRunAt = s.clock()
	gen := s.generations[nodeID] + 1
	s.generations[nodeID] = gen
	e.generation = gen
	heap.Push(&s.h, e)
}

// ---------------------------------------------------------------------------
// Introspection
// ---------------------------------------------------------------------------

// NodeScheduleStatus is a snapshot of a node's current schedule state.
type NodeScheduleStatus struct {
	NodeID              string
	NextRunIn           time.Duration
	ConsecutiveFailures int
	LastRunAt           *time.Time
	LastScore           *float64
	Enabled             bool
	Suspended           bool
	Priority            float64
}

// ScheduleStatus returns a snapshot of all registered nodes, sorted by
// next-run-in ascending.
func (s *ImprovementScheduler) ScheduleStatus() []NodeScheduleStatus {
	s.mu.Lock()
	defer s.mu.Unlock()

	now := s.clock()
	out := make([]NodeScheduleStatus, 0, len(s.entries))
	for nodeID, e := range s.entries {
		cfg := s.configs[nodeID]
		suspended := e.consecutiveFailures >= cfg.MaxConsecutiveFailures
		out = append(out, NodeScheduleStatus{
			NodeID:              nodeID,
			NextRunIn:           max0(e.nextRunAt.Sub(now)),
			ConsecutiveFailures: e.consecutiveFailures,
			LastRunAt:           e.lastRunAt,
			LastScore:           e.lastScore,
			Enabled:             cfg.Enabled,
			Suspended:           suspended,
			Priority:            e.priority,
		})
	}
	// sort by NextRunIn ascending
	for i := 1; i < len(out); i++ {
		for j := i; j > 0 && out[j].NextRunIn < out[j-1].NextRunIn; j-- {
			out[j], out[j-1] = out[j-1], out[j]
		}
	}
	return out
}

// NextDue returns the node ID and time-until-due for the next scheduled node.
// Returns "", 0, false if the scheduler is empty.
func (s *ImprovementScheduler) NextDue() (nodeID string, in time.Duration, ok bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.h.Len() == 0 {
		return "", 0, false
	}
	e := s.h[0]
	return e.nodeID, max0(e.nextRunAt.Sub(s.clock())), true
}

// RegisteredNodes returns all registered node IDs.
func (s *ImprovementScheduler) RegisteredNodes() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]string, 0, len(s.configs))
	for id := range s.configs {
		out = append(out, id)
	}
	return out
}

// IsSuspended returns true if the node has exceeded its failure limit.
func (s *ImprovementScheduler) IsSuspended(nodeID string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	e := s.entries[nodeID]
	cfg := s.configs[nodeID]
	if e == nil {
		return false
	}
	return e.consecutiveFailures >= cfg.MaxConsecutiveFailures
}

// ---------------------------------------------------------------------------
// Internal
// ---------------------------------------------------------------------------

func (s *ImprovementScheduler) rebuildHeap() {
	s.h = s.h[:0]
	for nodeID, e := range s.entries {
		if _, ok := s.configs[nodeID]; ok {
			s.h = append(s.h, e)
		}
	}
	heap.Init(&s.h)
}

func max0(d time.Duration) time.Duration {
	if d < 0 {
		return 0
	}
	return d
}
