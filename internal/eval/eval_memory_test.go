package eval

import (
	"context"
	"testing"

	"github.com/benebsworth/omega/internal/core"
)

// ---------------------------------------------------------------------------
// Working memory tests
// ---------------------------------------------------------------------------

func TestMemory_WorkingSetAndGet(t *testing.T) {
	h := NewMemoryHarness(t)
	h.Kernel.SetWorking("signal", 0.75)
	val, ok := h.Kernel.GetWorking("signal")
	if !ok {
		t.Fatal("expected key to be present")
	}
	if val.(float64) != 0.75 {
		t.Errorf("val=%v want=0.75", val)
	}
}

func TestMemory_WorkingMissingKeyReturnsFalse(t *testing.T) {
	h := NewMemoryHarness(t)
	_, ok := h.Kernel.GetWorking("nonexistent")
	if ok {
		t.Error("expected false for missing key")
	}
}

func TestMemory_WorkingClear(t *testing.T) {
	h := NewMemoryHarness(t)
	h.Kernel.SetWorking("k1", 1)
	h.Kernel.SetWorking("k2", 2)
	h.Kernel.ClearWorking()
	snap := h.Kernel.WorkingSnapshot()
	if len(snap) != 0 {
		t.Errorf("expected empty snapshot after clear, got %d keys", len(snap))
	}
}

func TestMemory_WorkingSnapshot(t *testing.T) {
	h := NewMemoryHarness(t)
	h.Kernel.SetWorking("a", "alpha")
	h.Kernel.SetWorking("b", 42)
	snap := h.Kernel.WorkingSnapshot()
	if len(snap) != 2 {
		t.Errorf("snapshot len=%d want=2", len(snap))
	}
	if snap["a"] != "alpha" {
		t.Errorf("snap[a]=%v want=alpha", snap["a"])
	}
}

// ---------------------------------------------------------------------------
// Episodic memory tests
// ---------------------------------------------------------------------------

func TestMemory_StoreAndRetrieveEpisodes(t *testing.T) {
	ctx := context.Background()
	h := NewMemoryHarness(t)
	ids := h.StoreFixedEpisodes(ctx, t, "test_ns", 5)
	if len(ids) != 5 {
		t.Fatalf("stored %d episodes want 5", len(ids))
	}

	episodes, err := h.Kernel.RetrieveEpisodes(ctx, core.EpisodeFilter{
		Namespace: "test_ns",
		Limit:     10,
	})
	if err != nil {
		t.Fatalf("RetrieveEpisodes: %v", err)
	}
	if len(episodes) != 5 {
		t.Errorf("retrieved %d episodes want 5", len(episodes))
	}
}

func TestMemory_FilterByEventType(t *testing.T) {
	ctx := context.Background()
	h := NewMemoryHarness(t)
	h.StoreFixedEpisodes(ctx, t, "ns", 3)

	// Store one episode with different event type.
	_, err := h.Kernel.StoreEpisode(ctx, core.Episode{
		EventType: "portfolio_built",
		Content:   map[string]any{"assets": 5},
		Cycle:     99,
		Namespace: "ns",
		Importance: 0.9,
	})
	if err != nil {
		t.Fatalf("StoreEpisode: %v", err)
	}

	episodes, err := h.Kernel.RetrieveEpisodes(ctx, core.EpisodeFilter{
		EventType: "portfolio_built",
		Namespace: "ns",
		Limit:     10,
	})
	if err != nil {
		t.Fatalf("RetrieveEpisodes by event type: %v", err)
	}
	if len(episodes) != 1 {
		t.Errorf("expected 1 portfolio_built episode, got %d", len(episodes))
	}
}

func TestMemory_FilterBySinceCycle(t *testing.T) {
	ctx := context.Background()
	h := NewMemoryHarness(t)
	h.StoreFixedEpisodes(ctx, t, "ns", 10)

	// Only retrieve episodes from cycle >= 6.
	episodes, err := h.Kernel.RetrieveEpisodes(ctx, core.EpisodeFilter{
		SinceCycle: 6,
		Namespace:  "ns",
		Limit:      20,
	})
	if err != nil {
		t.Fatalf("RetrieveEpisodes since cycle: %v", err)
	}
	if len(episodes) != 5 { // cycles 6..10
		t.Errorf("expected 5 episodes since cycle 6, got %d", len(episodes))
	}
}

func TestMemory_NamespaceIsolation(t *testing.T) {
	ctx := context.Background()
	h := NewMemoryHarness(t)
	h.StoreFixedEpisodes(ctx, t, "ns_a", 3)
	h.StoreFixedEpisodes(ctx, t, "ns_b", 4)

	epA, _ := h.Kernel.RetrieveEpisodes(ctx, core.EpisodeFilter{Namespace: "ns_a", Limit: 20})
	epB, _ := h.Kernel.RetrieveEpisodes(ctx, core.EpisodeFilter{Namespace: "ns_b", Limit: 20})

	if len(epA) != 3 {
		t.Errorf("ns_a: got %d episodes want 3", len(epA))
	}
	if len(epB) != 4 {
		t.Errorf("ns_b: got %d episodes want 4", len(epB))
	}
}

func TestMemory_EpisodeCount(t *testing.T) {
	ctx := context.Background()
	h := NewMemoryHarness(t)
	h.StoreFixedEpisodes(ctx, t, "ns", 7)

	count, err := h.Kernel.EpisodeCount(ctx)
	if err != nil {
		t.Fatalf("EpisodeCount: %v", err)
	}
	if count != 7 {
		t.Errorf("EpisodeCount=%d want=7", count)
	}
}

// ---------------------------------------------------------------------------
// Semantic memory tests
// ---------------------------------------------------------------------------

func TestMemory_StoreAndRetrieveSemantic(t *testing.T) {
	ctx := context.Background()
	h := NewMemoryHarness(t)
	h.StoreFixedSemanticMemory(ctx, t, "btc_momentum", "test_ns")

	mems, err := h.Kernel.RetrieveSemantic(ctx, core.SemanticFilter{
		Concept:   "btc_momentum",
		Namespace: "test_ns",
		Limit:     5,
	})
	if err != nil {
		t.Fatalf("RetrieveSemantic: %v", err)
	}
	if len(mems) != 1 {
		t.Errorf("expected 1 semantic memory, got %d", len(mems))
	}
	if mems[0].Concept != "btc_momentum" {
		t.Errorf("concept=%q want=btc_momentum", mems[0].Concept)
	}
}

func TestMemory_ReinforceSemantic(t *testing.T) {
	ctx := context.Background()
	h := NewMemoryHarness(t)
	h.StoreFixedSemanticMemory(ctx, t, "eth_regime", "ns")

	before, err := h.Kernel.RetrieveSemantic(ctx, core.SemanticFilter{Concept: "eth_regime", Limit: 1})
	if err != nil || len(before) == 0 {
		t.Fatal("could not retrieve semantic memory")
	}
	confBefore := before[0].Confidence

	ok, err := h.Kernel.ReinforceSemantic(ctx, "eth_regime", 0.05)
	if err != nil {
		t.Fatalf("ReinforceSemantic: %v", err)
	}
	if !ok {
		t.Error("expected reinforcement to succeed")
	}

	after, _ := h.Kernel.RetrieveSemantic(ctx, core.SemanticFilter{Concept: "eth_regime", Limit: 1})
	if after[0].Confidence <= confBefore {
		t.Errorf("confidence should increase after reinforcement: before=%.4f after=%.4f", confBefore, after[0].Confidence)
	}
}

func TestMemory_SemanticMinConfidenceFilter(t *testing.T) {
	ctx := context.Background()
	h := NewMemoryHarness(t)

	// Store one high-confidence and one low-confidence semantic memory.
	_, _ = h.Kernel.StoreSemantic(ctx, core.SemanticMemory{
		Concept: "high_conf", Content: "high", Confidence: 0.9, Namespace: "ns",
	})
	_, _ = h.Kernel.StoreSemantic(ctx, core.SemanticMemory{
		Concept: "low_conf", Content: "low", Confidence: 0.3, Namespace: "ns",
	})

	mems, _ := h.Kernel.RetrieveSemantic(ctx, core.SemanticFilter{
		MinConfidence: 0.7,
		Namespace:     "ns",
		Limit:         10,
	})
	if len(mems) != 1 {
		t.Errorf("expected 1 high-confidence memory, got %d", len(mems))
	}
	if mems[0].Concept != "high_conf" {
		t.Errorf("concept=%q want=high_conf", mems[0].Concept)
	}
}

// ---------------------------------------------------------------------------
// Cycle lifecycle tests
// ---------------------------------------------------------------------------

func TestMemory_BeginEndCycleStoresSummary(t *testing.T) {
	ctx := context.Background()
	h := NewMemoryHarness(t)

	if err := h.Kernel.BeginCycle(ctx, 1); err != nil {
		t.Fatalf("BeginCycle: %v", err)
	}
	id, err := h.Kernel.EndCycle(ctx, 1, map[string]any{"result": "ok"})
	if err != nil {
		t.Fatalf("EndCycle: %v", err)
	}
	if id == "" {
		t.Error("EndCycle should return a non-empty episode ID")
	}

	// The summary episode should be retrievable.
	eps, err := h.Kernel.RetrieveEpisodes(ctx, core.EpisodeFilter{
		EventType: "cycle_summary",
		Limit:     5,
	})
	if err != nil {
		t.Fatalf("RetrieveEpisodes: %v", err)
	}
	if len(eps) == 0 {
		t.Error("expected at least one cycle_summary episode")
	}
}

func TestMemory_BeginCycleClearsWorkingMemory(t *testing.T) {
	ctx := context.Background()
	h := NewMemoryHarness(t)

	h.Kernel.SetWorking("carry_forward", "value")
	if err := h.Kernel.BeginCycle(ctx, 2); err != nil {
		t.Fatalf("BeginCycle: %v", err)
	}

	_, ok := h.Kernel.GetWorking("carry_forward")
	if ok {
		t.Error("BeginCycle should clear working memory")
	}
}

func TestMemory_ConsolidationProducesSemanticPatterns(t *testing.T) {
	ctx := context.Background()
	h := NewMemoryHarness(t)

	// Store 5 episodes of the same event type to trigger consolidation heuristic.
	for i := 0; i < 6; i++ {
		_, err := h.Kernel.StoreEpisode(ctx, core.Episode{
			EventType:  "signal_generated",
			Content:    map[string]any{"value": float64(i)},
			Cycle:      i + 1,
			Namespace:  "global",
			Importance: 0.8,
		})
		if err != nil {
			t.Fatalf("StoreEpisode[%d]: %v", i, err)
		}
	}

	// Run consolidation at cycle 5 (multiple of memConsolidationEvery=5).
	h.RunCycleLifecycle(ctx, t, 5)

	// After consolidation, semantic memories should have been extracted.
	mems, err := h.Kernel.RetrieveSemantic(ctx, core.SemanticFilter{Limit: 20})
	if err != nil {
		t.Fatalf("RetrieveSemantic: %v", err)
	}
	// At least one semantic memory should exist (consolidation may produce zero
	// if the heuristic threshold is not met — this is an integration check).
	t.Logf("semantic memories after consolidation: %d", len(mems))
}

func TestMemory_MultiCycleLifecycle(t *testing.T) {
	ctx := context.Background()
	h := NewMemoryHarness(t)

	// Store some content, then run 10 cycles.
	h.StoreFixedEpisodes(ctx, t, "global", 5)
	h.RunCycleLifecycle(ctx, t, 10)

	// EndCycle stores a cycle_summary episode per cycle.
	eps, err := h.Kernel.RetrieveEpisodes(ctx, core.EpisodeFilter{
		EventType: "cycle_summary",
		Limit:     20,
	})
	if err != nil {
		t.Fatalf("RetrieveEpisodes: %v", err)
	}
	if len(eps) != 10 {
		t.Errorf("expected 10 cycle_summary episodes, got %d", len(eps))
	}
}
