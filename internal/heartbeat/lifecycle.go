// lifecycle.go — per-node lifecycle state-machine and event ring buffer.
package heartbeat

import (
	"sync"
	"time"
)

// lifecycleRingSize is the maximum number of lifecycle events kept per node.
const lifecycleRingSize = 1000

// LifecycleState represents the operational state of a node.
type LifecycleState int

const (
	StateUnknown   LifecycleState = iota // never seen
	StateStarting                        // process initialising
	StateWarmingUp                       // loading models / data
	StateRunning                         // operating normally
	StateDegraded                        // operating with errors
	StateStopped                         // cleanly shut down
)

// String returns the canonical uppercase name used in JSON responses.
func (s LifecycleState) String() string {
	switch s {
	case StateStarting:
		return "STARTING"
	case StateWarmingUp:
		return "WARMING_UP"
	case StateRunning:
		return "RUNNING"
	case StateDegraded:
		return "DEGRADED"
	case StateStopped:
		return "STOPPED"
	default:
		return "UNKNOWN"
	}
}

// LifecycleEvent records a single state transition.
type LifecycleEvent struct {
	NodeID    string
	FromState LifecycleState
	ToState   LifecycleState
	Reason    string
	Timestamp time.Time
}

// nodeLifecycleRing is the per-node ring buffer of lifecycle events.
type nodeLifecycleRing struct {
	events [lifecycleRingSize]LifecycleEvent
	head   int // next write position
	count  int // number of valid entries (≤ lifecycleRingSize)
}

// all returns events in chronological order (oldest first).
func (r *nodeLifecycleRing) all() []LifecycleEvent {
	if r.count == 0 {
		return []LifecycleEvent{}
	}
	out := make([]LifecycleEvent, r.count)
	start := (r.head - r.count + lifecycleRingSize) % lifecycleRingSize
	for i := range r.count {
		out[i] = r.events[(start+i)%lifecycleRingSize]
	}
	return out
}

// latest returns the most recently recorded event's ToState, or StateUnknown.
func (r *nodeLifecycleRing) latest() LifecycleState {
	if r.count == 0 {
		return StateUnknown
	}
	prev := (r.head - 1 + lifecycleRingSize) % lifecycleRingSize
	return r.events[prev].ToState
}

// LifecycleStore is a thread-safe, in-memory store for node lifecycle events.
type LifecycleStore struct {
	mu    sync.RWMutex
	rings map[string]*nodeLifecycleRing
}

// NewLifecycleStore returns a ready-to-use LifecycleStore.
func NewLifecycleStore() *LifecycleStore {
	return &LifecycleStore{rings: make(map[string]*nodeLifecycleRing)}
}

// RecordEvent appends a lifecycle event for the given node.
func (s *LifecycleStore) RecordEvent(ev LifecycleEvent) {
	s.mu.Lock()
	defer s.mu.Unlock()

	r, ok := s.rings[ev.NodeID]
	if !ok {
		r = &nodeLifecycleRing{}
		s.rings[ev.NodeID] = r
	}
	r.events[r.head] = ev
	r.head = (r.head + 1) % lifecycleRingSize
	if r.count < lifecycleRingSize {
		r.count++
	}
}

// GetEvents returns all recorded lifecycle events for a node, oldest first.
// Returns an empty (non-nil) slice if the node is unknown.
func (s *LifecycleStore) GetEvents(nodeID string) []LifecycleEvent {
	s.mu.RLock()
	defer s.mu.RUnlock()

	r, ok := s.rings[nodeID]
	if !ok {
		return []LifecycleEvent{}
	}
	return r.all()
}

// CurrentState returns the most recent ToState recorded for the node.
// Returns StateUnknown if no events have been recorded.
func (s *LifecycleStore) CurrentState(nodeID string) LifecycleState {
	s.mu.RLock()
	defer s.mu.RUnlock()

	r, ok := s.rings[nodeID]
	if !ok {
		return StateUnknown
	}
	return r.latest()
}
