package memory

import (
	"context"
	"sync"
	"time"
)

const defaultDebounceDuration = 30 * time.Second

// ---------------------------------------------------------------------------
// WriteQueue
// ---------------------------------------------------------------------------

// WriteQueue debounces writes to an AtomicWriter.  When the same key is
// enqueued multiple times within the debounce window only the most recent
// value is flushed, preventing thundering-herd on rapid updates.
type WriteQueue struct {
	writer   *AtomicWriter
	debounce time.Duration

	mu      sync.Mutex
	pending map[string][]byte    // key → latest data
	timers  map[string]*time.Timer

	flushCh chan struct{} // closed by Flush to trigger immediate write
}

// NewWriteQueue creates a WriteQueue backed by writer.
// If debounce is ≤ 0 the default 30 s is used.
func NewWriteQueue(writer *AtomicWriter, debounce time.Duration) *WriteQueue {
	if debounce <= 0 {
		debounce = defaultDebounceDuration
	}
	return &WriteQueue{
		writer:   writer,
		debounce: debounce,
		pending:  make(map[string][]byte),
		timers:   make(map[string]*time.Timer),
		flushCh:  make(chan struct{}),
	}
}

// Enqueue queues a write for key, resetting the debounce timer if one is
// already running for that key.
func (q *WriteQueue) Enqueue(key string, data []byte) {
	cp := make([]byte, len(data))
	copy(cp, data)

	q.mu.Lock()
	defer q.mu.Unlock()

	q.pending[key] = cp

	// Reset existing timer.
	if t, ok := q.timers[key]; ok {
		t.Stop()
	}
	q.timers[key] = time.AfterFunc(q.debounce, func() {
		q.flushKey(key)
	})
}

// flushKey writes a single key and removes it from the pending map.
func (q *WriteQueue) flushKey(key string) {
	q.mu.Lock()
	data, ok := q.pending[key]
	if ok {
		delete(q.pending, key)
		delete(q.timers, key)
	}
	q.mu.Unlock()

	if ok {
		_ = q.writer.Write(key, data)
	}
}

// Flush immediately writes all pending keys, cancelling their debounce timers.
func (q *WriteQueue) Flush() {
	q.mu.Lock()
	keys := make([]string, 0, len(q.pending))
	for k := range q.pending {
		keys = append(keys, k)
	}
	// Stop timers before releasing the lock.
	for _, k := range keys {
		if t, ok := q.timers[k]; ok {
			t.Stop()
			delete(q.timers, k)
		}
	}
	// Snapshot and clear pending.
	snapshot := make(map[string][]byte, len(keys))
	for _, k := range keys {
		snapshot[k] = q.pending[k]
		delete(q.pending, k)
	}
	q.mu.Unlock()

	for k, data := range snapshot {
		_ = q.writer.Write(k, data)
	}
}

// Start launches the background goroutine that responds to flush signals.
// It returns when ctx is cancelled, first calling Flush to drain pending writes.
func (q *WriteQueue) Start(ctx context.Context) {
	go func() {
		<-ctx.Done()
		q.Flush()
	}()
}
