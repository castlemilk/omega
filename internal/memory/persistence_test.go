package memory

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

// ---------------------------------------------------------------------------
// AtomicWriter + MtimeCache
// ---------------------------------------------------------------------------

func TestAtomicWriteRead(t *testing.T) {
	dir := t.TempDir()
	w, err := NewAtomicWriter(dir)
	if err != nil {
		t.Fatalf("NewAtomicWriter: %v", err)
	}

	data := []byte("hello omega")
	if err := w.Write("key1", data); err != nil {
		t.Fatalf("Write: %v", err)
	}

	got, err := w.Read("key1")
	if err != nil {
		t.Fatalf("Read: %v", err)
	}
	if string(got) != string(data) {
		t.Fatalf("got %q, want %q", got, data)
	}
}

func TestAtomicWriteOverwrite(t *testing.T) {
	dir := t.TempDir()
	w, _ := NewAtomicWriter(dir)

	_ = w.Write("k", []byte("v1"))
	_ = w.Write("k", []byte("v2"))

	got, err := w.Read("k")
	if err != nil {
		t.Fatalf("Read: %v", err)
	}
	if string(got) != "v2" {
		t.Fatalf("got %q, want %q", got, "v2")
	}
}

func TestAtomicDelete(t *testing.T) {
	dir := t.TempDir()
	w, _ := NewAtomicWriter(dir)

	_ = w.Write("del", []byte("data"))
	if err := w.Delete("del"); err != nil {
		t.Fatalf("Delete: %v", err)
	}

	if _, err := w.Read("del"); err == nil {
		t.Fatal("expected error reading deleted key, got nil")
	}
}

func TestMtimeCacheInvalidation(t *testing.T) {
	dir := t.TempDir()
	w, _ := NewAtomicWriter(dir)

	_ = w.Write("cached", []byte("first"))

	// Read to populate cache.
	d1, _ := w.Read("cached")
	if string(d1) != "first" {
		t.Fatalf("initial read: got %q", d1)
	}

	// Overwrite; Write() calls Invalidate internally.
	_ = w.Write("cached", []byte("second"))

	d2, _ := w.Read("cached")
	if string(d2) != "second" {
		t.Fatalf("after invalidation: got %q, want %q", d2, "second")
	}
}

func TestMtimeCacheNoReread(t *testing.T) {
	cache := NewMtimeCache()
	mtime := time.Now()

	cache.Set("k", []byte("data"), mtime)

	got, ok := cache.Get("k", mtime)
	if !ok {
		t.Fatal("expected cache hit")
	}
	if string(got) != "data" {
		t.Fatalf("got %q", got)
	}

	// Different mtime → miss.
	_, ok2 := cache.Get("k", mtime.Add(time.Second))
	if ok2 {
		t.Fatal("expected cache miss for different mtime")
	}
}

// ---------------------------------------------------------------------------
// WriteQueue debounce
// ---------------------------------------------------------------------------

func TestWriteQueueFlush(t *testing.T) {
	dir := t.TempDir()
	writer, _ := NewAtomicWriter(dir)

	q := NewWriteQueue(writer, time.Hour) // long debounce — rely on Flush()

	q.Enqueue("k", []byte("val1"))
	q.Enqueue("k", []byte("val2")) // should overwrite val1

	q.Flush()

	got, err := writer.Read("k")
	if err != nil {
		t.Fatalf("Read after flush: %v", err)
	}
	if string(got) != "val2" {
		t.Fatalf("got %q, want %q", got, "val2")
	}
}

func TestWriteQueueDebounce(t *testing.T) {
	dir := t.TempDir()
	writer, _ := NewAtomicWriter(dir)

	debounce := 50 * time.Millisecond
	q := NewWriteQueue(writer, debounce)

	q.Enqueue("k", []byte("a"))
	q.Enqueue("k", []byte("b"))
	q.Enqueue("k", []byte("c"))

	// Wait for debounce to fire naturally.
	time.Sleep(debounce + 100*time.Millisecond)

	got, err := writer.Read("k")
	if err != nil {
		t.Fatalf("Read after debounce: %v", err)
	}
	if string(got) != "c" {
		t.Fatalf("got %q, want final value %q", got, "c")
	}
}

func TestWriteQueueMultipleKeys(t *testing.T) {
	dir := t.TempDir()
	writer, _ := NewAtomicWriter(dir)
	q := NewWriteQueue(writer, time.Hour)

	q.Enqueue("a", []byte("aaa"))
	q.Enqueue("b", []byte("bbb"))
	q.Flush()

	for _, tc := range []struct{ key, want string }{{"a", "aaa"}, {"b", "bbb"}} {
		got, err := writer.Read(tc.key)
		if err != nil {
			t.Fatalf("Read %q: %v", tc.key, err)
		}
		if string(got) != tc.want {
			t.Fatalf("key %q: got %q, want %q", tc.key, got, tc.want)
		}
	}
}

// ---------------------------------------------------------------------------
// EpisodicMemory
// ---------------------------------------------------------------------------

func TestEpisodicRecord(t *testing.T) {
	w, _ := NewAtomicWriter(t.TempDir())
	em := NewEpisodicMemory(w)

	ep := Episode{
		NodeID: "node1",
		Action: "deploy",
		Result: "ok",
		Tags:   []string{"prod"},
	}
	if err := em.Record(ep); err != nil {
		t.Fatalf("Record: %v", err)
	}

	got, err := em.Query(EpisodicFilter{NodeID: "node1"})
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if len(got) != 1 {
		t.Fatalf("got %d episodes, want 1", len(got))
	}
	if got[0].Action != "deploy" {
		t.Fatalf("got action %q", got[0].Action)
	}
}

func TestEpisodicTemporalCategory(t *testing.T) {
	w, _ := NewAtomicWriter(t.TempDir())
	em := NewEpisodicMemory(w)

	recent := Episode{Action: "a", Result: "r", Timestamp: time.Now().Add(-30 * time.Minute)}
	medium := Episode{Action: "b", Result: "r", Timestamp: time.Now().Add(-12 * time.Hour)}
	distant := Episode{Action: "c", Result: "r", Timestamp: time.Now().Add(-48 * time.Hour)}

	for _, ep := range []Episode{recent, medium, distant} {
		_ = em.Record(ep)
	}

	all, _ := em.Query(EpisodicFilter{})
	cats := map[TemporalCategory]int{}
	for _, ep := range all {
		cats[ep.TemporalCategory]++
	}
	if cats[TemporalRecent] != 1 {
		t.Errorf("recent: got %d, want 1", cats[TemporalRecent])
	}
	if cats[TemporalMedium] != 1 {
		t.Errorf("medium: got %d, want 1", cats[TemporalMedium])
	}
	if cats[TemporalDistant] != 1 {
		t.Errorf("distant: got %d, want 1", cats[TemporalDistant])
	}
}

func TestEpisodicQueryTagFilter(t *testing.T) {
	w, _ := NewAtomicWriter(t.TempDir())
	em := NewEpisodicMemory(w)

	_ = em.Record(Episode{Action: "a", Result: "ok", Tags: []string{"prod"}})
	_ = em.Record(Episode{Action: "b", Result: "ok", Tags: []string{"staging"}})

	got, _ := em.Query(EpisodicFilter{Tags: []string{"prod"}})
	if len(got) != 1 || got[0].Action != "a" {
		t.Fatalf("unexpected results: %+v", got)
	}
}

func TestEpisodicQueryTimeRange(t *testing.T) {
	w, _ := NewAtomicWriter(t.TempDir())
	em := NewEpisodicMemory(w)

	now := time.Now()
	_ = em.Record(Episode{Action: "old", Result: "r", Timestamp: now.Add(-2 * time.Hour)})
	_ = em.Record(Episode{Action: "new", Result: "r", Timestamp: now})

	got, _ := em.Query(EpisodicFilter{After: now.Add(-30 * time.Minute)})
	if len(got) != 1 || got[0].Action != "new" {
		t.Fatalf("time filter unexpected: %+v", got)
	}
}

func TestEpisodicDetectContradictions(t *testing.T) {
	w, _ := NewAtomicWriter(t.TempDir())
	em := NewEpisodicMemory(w)

	_ = em.Record(Episode{Action: "deploy", Result: "ok"})
	_ = em.Record(Episode{Action: "deploy", Result: "ok"})

	// No contradiction when results match.
	cs, _ := em.DetectContradictions(Episode{Action: "deploy", Result: "ok"})
	if len(cs) != 0 {
		t.Fatalf("expected no contradictions, got %d", len(cs))
	}

	// Contradiction when result differs.
	cs2, _ := em.DetectContradictions(Episode{Action: "deploy", Result: "fail"})
	if len(cs2) != 2 {
		t.Fatalf("expected 2 contradictions (one per prior episode), got %d", len(cs2))
	}
}

// ---------------------------------------------------------------------------
// SemanticStore
// ---------------------------------------------------------------------------

func TestSemanticStoreAndRetrieve(t *testing.T) {
	w, _ := NewAtomicWriter(t.TempDir())
	ss := NewSemanticStore(w)

	f := Fact{
		Key:        "btc_trend",
		Value:      "upward",
		Confidence: 0.9,
		Source:     "test",
		DecayRate:  0.01,
	}
	if err := ss.Store(f); err != nil {
		t.Fatalf("Store: %v", err)
	}

	got, err := ss.Retrieve("btc_trend")
	if err != nil {
		t.Fatalf("Retrieve: %v", err)
	}
	if got.Value != "upward" {
		t.Fatalf("got value %q", got.Value)
	}
	if got.Confidence > 0.9+0.001 {
		t.Fatalf("confidence should not increase; got %f", got.Confidence)
	}
}

func TestSemanticDecay(t *testing.T) {
	w, _ := NewAtomicWriter(t.TempDir())
	ss := NewSemanticStore(w)

	// Store a fact with LastAccessed set 2 hours ago.
	f := Fact{
		Key:          "old_fact",
		Value:        "v",
		Confidence:   1.0,
		DecayRate:    0.5, // aggressive decay for testing
		LastAccessed: time.Now().Add(-2 * time.Hour),
	}
	// Write directly into the JSON store to bypass the auto-set of LastAccessed.
	// We achieve this by storing normally and then patching the file.
	_ = ss.Store(f)

	// Manually write the file with backdated LastAccessed.
	import_data := filepath.Join(t.TempDir(), "semantic.json") // just for path; we use the real writer
	_ = import_data

	// Retrieve should apply decay: C' = 1.0 * exp(-0.5 * 2) ≈ 0.368.
	// Because Store sets LastAccessed = now, we can't trivially backdate it
	// through the public API. Instead, test that the decay formula is applied
	// by writing a JSON file manually into the temp dir.
	dir2 := t.TempDir()
	w2, _ := NewAtomicWriter(dir2)
	ss2 := NewSemanticStore(w2)

	backdated := time.Now().Add(-2 * time.Hour)
	raw := `[{"key":"k","value":"v","confidence":1.0,"source":"","created_at":"` +
		backdated.Format(time.RFC3339) + `","last_accessed":"` +
		backdated.Format(time.RFC3339) + `","decay_rate":0.5}]`
	if err := os.WriteFile(filepath.Join(dir2, semanticKey), []byte(raw), 0o600); err != nil { //nolint:gosec
		t.Fatalf("write raw: %v", err)
	}

	got, err := ss2.Retrieve("k")
	if err != nil {
		t.Fatalf("Retrieve: %v", err)
	}
	// exp(-0.5 * 2) ≈ 0.368; allow ±0.05 tolerance.
	if got.Confidence > 0.42 || got.Confidence < 0.32 {
		t.Fatalf("unexpected decayed confidence: %f (want ≈0.368)", got.Confidence)
	}
}

func TestSemanticPrune(t *testing.T) {
	w, _ := NewAtomicWriter(t.TempDir())
	ss := NewSemanticStore(w)

	_ = ss.Store(Fact{Key: "high", Value: "v", Confidence: 0.9, DecayRate: 0.0})
	_ = ss.Store(Fact{Key: "low", Value: "v", Confidence: 0.1, DecayRate: 0.0})

	removed, err := ss.Prune(0.5)
	if err != nil {
		t.Fatalf("Prune: %v", err)
	}
	if removed != 1 {
		t.Fatalf("got removed=%d, want 1", removed)
	}

	if _, err := ss.Retrieve("low"); err == nil {
		t.Fatal("expected low-confidence fact to be pruned")
	}
	if _, err := ss.Retrieve("high"); err != nil {
		t.Fatalf("high-confidence fact should survive prune: %v", err)
	}
}

func TestSemanticRetrieveNotFound(t *testing.T) {
	w, _ := NewAtomicWriter(t.TempDir())
	ss := NewSemanticStore(w)

	_, err := ss.Retrieve("missing")
	if err == nil {
		t.Fatal("expected error for missing key")
	}
}
