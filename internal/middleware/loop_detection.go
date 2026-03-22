package middleware

import (
	"context"
	"crypto/sha256"
	"fmt"
	"log/slog"
	"sync"
)

const (
	loopWarnThreshold  = 3
	loopErrorThreshold = 5
	loopLRUCapacity    = 100
)

// callHash uniquely identifies a (node, action, payload) triple.
type callHash [32]byte

func hashCall(nodeID, action string, payload []byte) callHash {
	h := sha256.New()
	h.Write([]byte(nodeID))
	h.Write([]byte{0})
	h.Write([]byte(action))
	h.Write([]byte{0})
	h.Write(payload)
	var out callHash
	copy(out[:], h.Sum(nil))
	return out
}

// lruEntry is a node in a doubly-linked list used for LRU eviction.
type lruEntry struct {
	key   callHash
	count int
	prev  *lruEntry
	next  *lruEntry
}

// callTracker is a fixed-capacity LRU map from call hash → hit count.
type callTracker struct {
	mu       sync.Mutex
	capacity int
	counts   map[callHash]*lruEntry
	head     *lruEntry // most recently used
	tail     *lruEntry // least recently used
}

func newCallTracker(capacity int) *callTracker {
	return &callTracker{
		capacity: capacity,
		counts:   make(map[callHash]*lruEntry, capacity),
	}
}

// increment bumps the counter for key and returns the new count.
func (t *callTracker) increment(key callHash) int {
	t.mu.Lock()
	defer t.mu.Unlock()

	if e, ok := t.counts[key]; ok {
		e.count++
		t.moveToFront(e)
		return e.count
	}

	e := &lruEntry{key: key, count: 1}
	t.counts[key] = e
	t.pushFront(e)

	if len(t.counts) > t.capacity {
		t.evict()
	}
	return 1
}

func (t *callTracker) pushFront(e *lruEntry) {
	e.next = t.head
	e.prev = nil
	if t.head != nil {
		t.head.prev = e
	}
	t.head = e
	if t.tail == nil {
		t.tail = e
	}
}

func (t *callTracker) moveToFront(e *lruEntry) {
	if t.head == e {
		return
	}
	// detach
	if e.prev != nil {
		e.prev.next = e.next
	}
	if e.next != nil {
		e.next.prev = e.prev
	}
	if t.tail == e {
		t.tail = e.prev
	}
	// attach at front
	e.prev = nil
	e.next = t.head
	if t.head != nil {
		t.head.prev = e
	}
	t.head = e
}

func (t *callTracker) evict() {
	if t.tail == nil {
		return
	}
	e := t.tail
	if e.prev != nil {
		e.prev.next = nil
	}
	t.tail = e.prev
	if t.head == e {
		t.head = nil
	}
	delete(t.counts, e.key)
}

// LoopDetectionMiddleware tracks repeated (node, action, payload) calls.
// It logs a warning at loopWarnThreshold identical calls and returns an error
// at loopErrorThreshold.
type LoopDetectionMiddleware struct {
	tracker *callTracker
}

// NewLoopDetectionMiddleware creates a LoopDetectionMiddleware with an LRU
// capacity of loopLRUCapacity entries.
func NewLoopDetectionMiddleware() *LoopDetectionMiddleware {
	return &LoopDetectionMiddleware{tracker: newCallTracker(loopLRUCapacity)}
}

// Process implements Middleware.
func (m *LoopDetectionMiddleware) Process(ctx context.Context, req *ExecutionRequest, next NextFunc) (*ExecutionResponse, error) {
	key := hashCall(req.NodeID, req.Action, req.Payload)
	count := m.tracker.increment(key)

	switch {
	case count >= loopErrorThreshold:
		return nil, fmt.Errorf("loop detection: node %q action %q called %d times (limit %d); aborting",
			req.NodeID, req.Action, count, loopErrorThreshold)
	case count >= loopWarnThreshold:
		slog.WarnContext(ctx, "loop detection: repeated call detected",
			"node_id", req.NodeID,
			"action", req.Action,
			"count", count,
			"warn_threshold", loopWarnThreshold,
			"error_threshold", loopErrorThreshold,
		)
	}

	return next(ctx, req)
}
