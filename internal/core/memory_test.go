package core

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/db"
)

func newTestKernel(t *testing.T) *MemoryKernel {
	t.Helper()
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL not set — skipping Postgres integration tests")
	}
	t.Setenv("DATABASE_URL", dsn)
	database, err := db.New(context.Background())
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	k, err := NewMemoryKernel(database.StateDB())
	if err != nil {
		database.Close()
		t.Fatalf("NewMemoryKernel: %v", err)
	}
	t.Cleanup(func() { database.Close() })
	return k
}

// ---------------------------------------------------------------------------
// Working memory
// ---------------------------------------------------------------------------

func TestWorkingMemory_SetGet(t *testing.T) {
	k := newTestKernel(t)
	k.SetWorking("foo", 42)
	v, ok := k.GetWorking("foo")
	if !ok {
		t.Fatal("expected key to exist")
	}
	if v.(int) != 42 {
		t.Fatalf("got %v, want 42", v)
	}
}

func TestWorkingMemory_Clear(t *testing.T) {
	k := newTestKernel(t)
	k.SetWorking("a", 1)
	k.SetWorking("b", 2)
	k.ClearWorking()
	if _, ok := k.GetWorking("a"); ok {
		t.Fatal("expected working memory to be cleared")
	}
}

func TestWorkingMemory_Snapshot(t *testing.T) {
	k := newTestKernel(t)
	k.SetWorking("x", "hello")
	snap := k.WorkingSnapshot()
	if snap["x"] != "hello" {
		t.Fatalf("snapshot mismatch: %v", snap)
	}
}

// ---------------------------------------------------------------------------
// Episodic memory
// ---------------------------------------------------------------------------

func TestEpisodicStore_StoreAndRetrieve(t *testing.T) {
	ctx := context.Background()
	k := newTestKernel(t)

	id, err := k.StoreEpisode(ctx, Episode{
		EventType:  "signal_generated",
		Content:    map[string]any{"ticker": "BTCUSDT", "composite": 0.8},
		Tags:       []string{"btc", "buy_signal"},
		Importance: 0.9,
		Cycle:      1,
		Namespace:  "global",
	})
	if err != nil {
		t.Fatalf("StoreEpisode: %v", err)
	}
	if id == "" {
		t.Fatal("expected non-empty episode ID")
	}

	episodes, err := k.RetrieveEpisodes(ctx, EpisodeFilter{EventType: "signal_generated", Limit: 5})
	if err != nil {
		t.Fatalf("RetrieveEpisodes: %v", err)
	}
	if len(episodes) != 1 {
		t.Fatalf("expected 1 episode, got %d", len(episodes))
	}
	if episodes[0].EpisodeID != id {
		t.Errorf("episode ID mismatch: got %s, want %s", episodes[0].EpisodeID, id)
	}
}

func TestEpisodicStore_TagFilter(t *testing.T) {
	ctx := context.Background()
	k := newTestKernel(t)

	_, _ = k.StoreEpisode(ctx, Episode{EventType: "e1", Content: map[string]any{}, Tags: []string{"alpha"}, Importance: 0.8, Namespace: "global"})
	_, _ = k.StoreEpisode(ctx, Episode{EventType: "e2", Content: map[string]any{}, Tags: []string{"beta"}, Importance: 0.8, Namespace: "global"})

	eps, err := k.RetrieveEpisodes(ctx, EpisodeFilter{Tags: []string{"alpha"}, Limit: 10})
	if err != nil {
		t.Fatal(err)
	}
	if len(eps) != 1 {
		t.Fatalf("expected 1 episode with tag alpha, got %d", len(eps))
	}
}

func TestEpisodicStore_NamespaceIsolation(t *testing.T) {
	ctx := context.Background()
	k := newTestKernel(t)

	_, _ = k.StoreEpisode(ctx, Episode{EventType: "e", Content: map[string]any{}, Importance: 1.0, Namespace: "ns1"})
	_, _ = k.StoreEpisode(ctx, Episode{EventType: "e", Content: map[string]any{}, Importance: 1.0, Namespace: "ns2"})

	eps, _ := k.RetrieveEpisodes(ctx, EpisodeFilter{Namespace: "ns1", Limit: 10})
	if len(eps) != 1 {
		t.Fatalf("expected 1 episode in ns1, got %d", len(eps))
	}
}

func TestEpisodicStore_ImportanceClamped(t *testing.T) {
	ctx := context.Background()
	k := newTestKernel(t)
	_, _ = k.StoreEpisode(ctx, Episode{EventType: "e", Content: map[string]any{}, Importance: 5.0, Namespace: "global"})
	eps, _ := k.RetrieveEpisodes(ctx, EpisodeFilter{Limit: 1})
	if eps[0].Importance > 1.0 {
		t.Fatalf("importance should be clamped to 1.0, got %f", eps[0].Importance)
	}
}

// ---------------------------------------------------------------------------
// Semantic memory
// ---------------------------------------------------------------------------

func TestSemanticStore_StoreAndRetrieve(t *testing.T) {
	ctx := context.Background()
	k := newTestKernel(t)

	id, err := k.StoreSemantic(ctx, SemanticMemory{
		Concept:    "btc_momentum",
		Content:    "BTC momentum signals tend to persist 3-5 days",
		Confidence: 0.7,
		Tags:       []string{"btc", "momentum"},
		Namespace:  "global",
	})
	if err != nil {
		t.Fatalf("StoreSemantic: %v", err)
	}
	if id == "" {
		t.Fatal("expected non-empty memory ID")
	}

	results, err := k.RetrieveSemantic(ctx, SemanticFilter{Concept: "btc_momentum", Limit: 5})
	if err != nil {
		t.Fatalf("RetrieveSemantic: %v", err)
	}
	if len(results) != 1 {
		t.Fatalf("expected 1 semantic memory, got %d", len(results))
	}
	if results[0].Concept != "btc_momentum" {
		t.Errorf("concept mismatch: %s", results[0].Concept)
	}
}

func TestSemanticStore_Reinforce(t *testing.T) {
	ctx := context.Background()
	k := newTestKernel(t)

	_, _ = k.StoreSemantic(ctx, SemanticMemory{Concept: "vol_regime", Content: "High vol", Confidence: 0.5, Namespace: "global"})

	// Storing the same concept again should reinforce, not insert a duplicate.
	_, _ = k.StoreSemantic(ctx, SemanticMemory{Concept: "vol_regime", Content: "High vol updated", Confidence: 0.5, Namespace: "global"})

	results, _ := k.RetrieveSemantic(ctx, SemanticFilter{Concept: "vol_regime", Limit: 10})
	if len(results) != 1 {
		t.Fatalf("expected 1 semantic memory after reinforce, got %d", len(results))
	}
	if results[0].EvidenceCount < 2 {
		t.Errorf("evidence_count should be >= 2 after reinforce, got %d", results[0].EvidenceCount)
	}
}

func TestSemanticStore_QueryText(t *testing.T) {
	ctx := context.Background()
	k := newTestKernel(t)

	_, _ = k.StoreSemantic(ctx, SemanticMemory{Concept: "eth_pattern", Content: "Ethereum shows weekend dips", Confidence: 0.6, Namespace: "global"})
	_, _ = k.StoreSemantic(ctx, SemanticMemory{Concept: "btc_pattern", Content: "Bitcoin stable on Mondays", Confidence: 0.6, Namespace: "global"})

	results, _ := k.RetrieveSemantic(ctx, SemanticFilter{QueryText: "ethereum", Limit: 5})
	if len(results) != 1 || results[0].Concept != "eth_pattern" {
		t.Fatalf("query_text filter failed: %v", results)
	}
}

// ---------------------------------------------------------------------------
// Ratings
// ---------------------------------------------------------------------------

func TestRateMemory(t *testing.T) {
	ctx := context.Background()
	k := newTestKernel(t)
	id, _ := k.StoreSemantic(ctx, SemanticMemory{Concept: "x", Content: "y", Confidence: 0.5, Namespace: "global"})
	if err := k.RateMemory(ctx, id, 0.9, "global"); err != nil {
		t.Fatalf("RateMemory: %v", err)
	}
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

func TestBeginCycle_ClearsWorking(t *testing.T) {
	ctx := context.Background()
	k := newTestKernel(t)
	k.SetWorking("stale_key", "should_be_gone")
	_ = k.BeginCycle(ctx, 1)
	if _, ok := k.GetWorking("stale_key"); ok {
		t.Fatal("BeginCycle should have cleared working memory")
	}
}

func TestEndCycle_StoresEpisode(t *testing.T) {
	ctx := context.Background()
	k := newTestKernel(t)
	id, err := k.EndCycle(ctx, 3, map[string]any{"status": "ok"})
	if err != nil {
		t.Fatalf("EndCycle: %v", err)
	}
	eps, _ := k.RetrieveEpisodes(ctx, EpisodeFilter{EventType: "cycle_summary", Limit: 1})
	if len(eps) == 0 || eps[0].EpisodeID != id {
		t.Fatal("EndCycle episode not stored")
	}
}

func TestConsolidate_EmptyIsNoop(t *testing.T) {
	ctx := context.Background()
	k := newTestKernel(t)
	concepts, err := k.Consolidate(ctx, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(concepts) != 0 {
		t.Fatalf("expected no concepts from empty store, got %d", len(concepts))
	}
}

func TestConsolidate_PatternExtraction(t *testing.T) {
	ctx := context.Background()
	k := newTestKernel(t)

	// Store enough signal_outcome episodes so the consolidator fires
	for i := 0; i < 4; i++ {
		outcome := 0.05 // positive
		_, _ = k.StoreEpisode(ctx, Episode{
			EventType:  "signal_outcome",
			Content:    map[string]any{"ticker": "BTCUSDT", "signal_type": "momentum", "outcome": outcome},
			Tags:       []string{"btc"},
			Importance: 0.8,
			Namespace:  "",
		})
	}

	concepts, err := k.Consolidate(ctx, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(concepts) == 0 {
		t.Fatal("expected at least one concept from signal_outcome episodes")
	}
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

func TestSummary(t *testing.T) {
	ctx := context.Background()
	k := newTestKernel(t)
	_, _ = k.StoreEpisode(ctx, Episode{EventType: "e", Content: map[string]any{}, Importance: 0.9, Namespace: "global"})
	s := k.Summary(ctx)
	if s.EpisodicCount != 1 {
		t.Errorf("expected 1 episode in summary, got %d", s.EpisodicCount)
	}
}

// ---------------------------------------------------------------------------
// NodeMemory
// ---------------------------------------------------------------------------

func TestNodeMemory_Remember_Recall(t *testing.T) {
	k := newTestKernel(t)
	nm := k.GetNodeMemory("test-node")

	nm.Remember("key1", "value1", 10*time.Second)
	v, ok := nm.Recall("key1")
	if !ok || v.(string) != "value1" {
		t.Fatalf("Recall failed: ok=%v v=%v", ok, v)
	}
}

func TestNodeMemory_TTLExpiry(t *testing.T) {
	k := newTestKernel(t)
	nm := k.GetNodeMemory("test-node")

	nm.Remember("ttl_key", "val", 1*time.Millisecond)
	time.Sleep(5 * time.Millisecond)
	if _, ok := nm.Recall("ttl_key"); ok {
		t.Fatal("expected TTL-expired entry to be missing")
	}
}

func TestNodeMemory_NamespaceIsolation(t *testing.T) {
	ctx := context.Background()
	k := newTestKernel(t)

	nm1 := k.GetNodeMemory("node-a")
	nm2 := k.GetNodeMemory("node-b")

	_, _ = nm1.StoreEpisode(ctx, "e", map[string]any{"data": 1}, nil, 0.9, 0)
	eps, _ := nm2.RetrieveEpisodes(ctx, EpisodeFilter{Limit: 10})
	if len(eps) != 0 {
		t.Fatal("node-b should not see node-a's episodes")
	}
}
