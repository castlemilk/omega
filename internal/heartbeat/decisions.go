// decisions.go — per-node bounded queue for decision trace snapshots.
package heartbeat

import (
	"sync"
	"time"
)

// decisionQueueSize is the maximum number of decision snapshots kept per node.
const decisionQueueSize = 100

// DecisionEntry holds one per-cycle decision snapshot received from a Python node.
type DecisionEntry struct {
	NodeID       string
	Cycle        int32
	ReceivedAt   time.Time
	SnapshotJSON string // raw JSON blob from the Python node
}

// nodeDecisionRing is a per-node circular buffer of decision entries.
type nodeDecisionRing struct {
	entries [decisionQueueSize]DecisionEntry
	head    int // next write position
	count   int // number of valid entries (≤ decisionQueueSize)
}

// all returns entries in chronological order (oldest first).
func (r *nodeDecisionRing) all() []DecisionEntry {
	if r.count == 0 {
		return []DecisionEntry{}
	}
	out := make([]DecisionEntry, r.count)
	start := (r.head - r.count + decisionQueueSize) % decisionQueueSize
	for i := range r.count {
		out[i] = r.entries[(start+i)%decisionQueueSize]
	}
	return out
}

// DecisionStore is a thread-safe, in-memory store for decision snapshots.
type DecisionStore struct {
	mu     sync.RWMutex
	queues map[string]*nodeDecisionRing
}

// NewDecisionStore returns a ready-to-use DecisionStore.
func NewDecisionStore() *DecisionStore {
	return &DecisionStore{queues: make(map[string]*nodeDecisionRing)}
}

// RecordDecision stores a decision snapshot for a node. Oldest entry is
// evicted when the queue reaches decisionQueueSize.
func (s *DecisionStore) RecordDecision(entry DecisionEntry) {
	s.mu.Lock()
	defer s.mu.Unlock()

	q, ok := s.queues[entry.NodeID]
	if !ok {
		q = &nodeDecisionRing{}
		s.queues[entry.NodeID] = q
	}
	q.entries[q.head] = entry
	q.head = (q.head + 1) % decisionQueueSize
	if q.count < decisionQueueSize {
		q.count++
	}
}

// GetDecisions returns all stored decision snapshots for a node, oldest first.
// Returns an empty (non-nil) slice if the node is unknown.
func (s *DecisionStore) GetDecisions(nodeID string) []DecisionEntry {
	s.mu.RLock()
	defer s.mu.RUnlock()

	q, ok := s.queues[nodeID]
	if !ok {
		return []DecisionEntry{}
	}
	return q.all()
}

// GetDecisionByCycle returns the decision snapshot for a specific cycle number.
// Returns false if the cycle is not in the queue (evicted or never received).
func (s *DecisionStore) GetDecisionByCycle(nodeID string, cycle int32) (*DecisionEntry, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	q, ok := s.queues[nodeID]
	if !ok {
		return nil, false
	}
	for _, e := range q.all() {
		if e.Cycle == cycle {
			cp := e
			return &cp, true
		}
	}
	return nil, false
}
