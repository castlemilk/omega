package framework

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
)

// ── Metric ────────────────────────────────────────────────────────────────────

// Metric is a single data point reported via MetricCollectionHook.
type Metric struct {
	Name   string
	Value  float64
	Labels map[string]string
}

// ── Hook interfaces ───────────────────────────────────────────────────────────

// PreCycleHook runs before each orchestration cycle.
// An error aborts the cycle (remaining hooks are not called).
type PreCycleHook interface {
	PreCycle(ctx context.Context, cycle int64) error
}

// PostCycleHook runs after each orchestration cycle, receiving the cycle error (nil on success).
type PostCycleHook interface {
	PostCycle(ctx context.Context, cycle int64, err error) error
}

// NodeRegistrationHook runs when a new node registers with the orchestrator.
type NodeRegistrationHook interface {
	OnNodeRegistered(ctx context.Context, nodeID string) error
}

// MetricCollectionHook runs when any subsystem reports a metric.
// Implementations should be fast; use channels for heavy processing.
type MetricCollectionHook interface {
	OnMetricCollected(ctx context.Context, m Metric)
}

// ── orderedHooks ──────────────────────────────────────────────────────────────

// orderedHooks keeps hooks in registration order for deterministic execution.
type orderedHooks[H any] struct {
	ids   []string
	hooks map[string]H
}

func newOrderedHooks[H any]() orderedHooks[H] {
	return orderedHooks[H]{hooks: make(map[string]H)}
}

func (o *orderedHooks[H]) add(id string, h H) {
	o.ids = append(o.ids, id)
	o.hooks[id] = h
}

func (o *orderedHooks[H]) remove(id string) {
	delete(o.hooks, id)
	for i, v := range o.ids {
		if v == id {
			o.ids = append(o.ids[:i], o.ids[i+1:]...)
			return
		}
	}
}

// snapshot returns hooks in registration order without holding the lock.
func (o *orderedHooks[H]) snapshot() []H {
	out := make([]H, 0, len(o.ids))
	for _, id := range o.ids {
		if h, ok := o.hooks[id]; ok {
			out = append(out, h)
		}
	}
	return out
}

// ── ExtensionRegistry ─────────────────────────────────────────────────────────

// ExtensionRegistry manages all hook registrations.
// The adversarial layer, safety layer, and memory layer plug into the
// orchestration cycle via these extension points without the orchestrator
// importing them directly.
type ExtensionRegistry struct {
	mu sync.RWMutex

	preCycle   orderedHooks[PreCycleHook]
	postCycle  orderedHooks[PostCycleHook]
	nodeReg    orderedHooks[NodeRegistrationHook]
	metricColl orderedHooks[MetricCollectionHook]

	counter atomic.Uint64
}

// NewExtensionRegistry returns an empty ExtensionRegistry.
func NewExtensionRegistry() *ExtensionRegistry {
	return &ExtensionRegistry{
		preCycle:   newOrderedHooks[PreCycleHook](),
		postCycle:  newOrderedHooks[PostCycleHook](),
		nodeReg:    newOrderedHooks[NodeRegistrationHook](),
		metricColl: newOrderedHooks[MetricCollectionHook](),
	}
}

// ── Registration helpers ──────────────────────────────────────────────────────

func (r *ExtensionRegistry) nextID() string {
	return fmt.Sprintf("hook-%d", r.counter.Add(1))
}

// AddPreCycleHook registers h and returns its ID for later removal.
func (r *ExtensionRegistry) AddPreCycleHook(h PreCycleHook) string {
	r.mu.Lock()
	defer r.mu.Unlock()
	id := r.nextID()
	r.preCycle.add(id, h)
	return id
}

// RemovePreCycleHook removes the hook with the given ID.
func (r *ExtensionRegistry) RemovePreCycleHook(id string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.preCycle.remove(id)
}

// AddPostCycleHook registers h and returns its ID.
func (r *ExtensionRegistry) AddPostCycleHook(h PostCycleHook) string {
	r.mu.Lock()
	defer r.mu.Unlock()
	id := r.nextID()
	r.postCycle.add(id, h)
	return id
}

// RemovePostCycleHook removes the hook with the given ID.
func (r *ExtensionRegistry) RemovePostCycleHook(id string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.postCycle.remove(id)
}

// AddNodeRegistrationHook registers h and returns its ID.
func (r *ExtensionRegistry) AddNodeRegistrationHook(h NodeRegistrationHook) string {
	r.mu.Lock()
	defer r.mu.Unlock()
	id := r.nextID()
	r.nodeReg.add(id, h)
	return id
}

// RemoveNodeRegistrationHook removes the hook with the given ID.
func (r *ExtensionRegistry) RemoveNodeRegistrationHook(id string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.nodeReg.remove(id)
}

// AddMetricCollectionHook registers h and returns its ID.
func (r *ExtensionRegistry) AddMetricCollectionHook(h MetricCollectionHook) string {
	r.mu.Lock()
	defer r.mu.Unlock()
	id := r.nextID()
	r.metricColl.add(id, h)
	return id
}

// RemoveMetricCollectionHook removes the hook with the given ID.
func (r *ExtensionRegistry) RemoveMetricCollectionHook(id string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.metricColl.remove(id)
}

// ── Execution helpers ─────────────────────────────────────────────────────────

// RunPreCycle calls all registered PreCycleHooks in registration order.
// The first error aborts the run (remaining hooks are not called).
func (r *ExtensionRegistry) RunPreCycle(ctx context.Context, cycle int64) error {
	r.mu.RLock()
	hooks := r.preCycle.snapshot()
	r.mu.RUnlock()

	for _, h := range hooks {
		if err := h.PreCycle(ctx, cycle); err != nil {
			return fmt.Errorf("PreCycleHook: %w", err)
		}
	}
	return nil
}

// RunPostCycle calls all registered PostCycleHooks in registration order.
// All hooks run regardless of errors; the first error is returned.
func (r *ExtensionRegistry) RunPostCycle(ctx context.Context, cycle int64, cycleErr error) error {
	r.mu.RLock()
	hooks := r.postCycle.snapshot()
	r.mu.RUnlock()

	var firstErr error
	for _, h := range hooks {
		if err := h.PostCycle(ctx, cycle, cycleErr); err != nil && firstErr == nil {
			firstErr = err
		}
	}
	return firstErr
}

// RunNodeRegistered calls all registered NodeRegistrationHooks.
// All hooks run; the first error is returned.
func (r *ExtensionRegistry) RunNodeRegistered(ctx context.Context, nodeID string) error {
	r.mu.RLock()
	hooks := r.nodeReg.snapshot()
	r.mu.RUnlock()

	var firstErr error
	for _, h := range hooks {
		if err := h.OnNodeRegistered(ctx, nodeID); err != nil && firstErr == nil {
			firstErr = err
		}
	}
	return firstErr
}

// RunMetricCollected calls all registered MetricCollectionHooks synchronously.
func (r *ExtensionRegistry) RunMetricCollected(ctx context.Context, m Metric) {
	r.mu.RLock()
	hooks := r.metricColl.snapshot()
	r.mu.RUnlock()

	for _, h := range hooks {
		h.OnMetricCollected(ctx, m)
	}
}
