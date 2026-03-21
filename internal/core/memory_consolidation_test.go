package core

import (
	"testing"
	"time"
)

// ---------------------------------------------------------------------------
// MemoryIndex
// ---------------------------------------------------------------------------

func TestMemoryIndex_AddAndLookup(t *testing.T) {
	idx := NewMemoryIndex()
	r := NewMemoryRecord("volatile", "price_move", map[string]any{"val": 1.0}, []string{"btc"}, 0.8, false)
	idx.Add(r)

	byRegime := idx.ByRegime("volatile")
	if _, ok := byRegime[r.MemoryID]; !ok {
		t.Error("expected record in byRegime index")
	}

	bySignal := idx.BySignal("price_move")
	if _, ok := bySignal[r.MemoryID]; !ok {
		t.Error("expected record in bySignal index")
	}

	now := time.Now()
	byTime := idx.ByTimeRange(now.Add(-time.Hour), now.Add(time.Hour))
	if _, ok := byTime[r.MemoryID]; !ok {
		t.Error("expected record in byTime index")
	}
}

func TestMemoryIndex_Remove(t *testing.T) {
	idx := NewMemoryIndex()
	r := NewMemoryRecord("trending", "regime_shift", map[string]any{}, nil, 0.5, false)
	idx.Add(r)
	idx.Remove(r)

	if len(idx.ByRegime("trending")) != 0 {
		t.Error("expected empty byRegime after remove")
	}
}

func TestIntersect(t *testing.T) {
	a := map[string]struct{}{"x": {}, "y": {}}
	b := map[string]struct{}{"y": {}, "z": {}}
	result := Intersect(a, b)
	if len(result) != 1 {
		t.Fatalf("expected intersection of 1, got %d", len(result))
	}
	if _, ok := result["y"]; !ok {
		t.Fatal("expected 'y' in intersection")
	}
}

// ---------------------------------------------------------------------------
// DecayManager
// ---------------------------------------------------------------------------

func TestDecayManager_Decay(t *testing.T) {
	dm, err := NewDecayManager(7*24*time.Hour, 0, 0.3)
	if err != nil {
		t.Fatal(err)
	}
	r := NewMemoryRecord("r", "s", map[string]any{}, nil, 1.0, false)
	// Simulate 7 days elapsed (half-life)
	r.CreatedAt = time.Now().Add(-7 * 24 * time.Hour)
	dm.Decay(&r, time.Now())

	// After one half-life, importance should be ~0.5
	if r.Importance < 0.4 || r.Importance > 0.6 {
		t.Errorf("expected importance ~0.5 after one half-life, got %f", r.Importance)
	}
}

func TestDecayManager_LandmarkProtection(t *testing.T) {
	dm, err := NewDecayManager(1*time.Second, 0, 0.3)
	if err != nil {
		t.Fatal(err)
	}
	r := NewMemoryRecord("r", "s", map[string]any{}, nil, 0.9, true /* landmark */)
	r.CreatedAt = time.Now().Add(-365 * 24 * time.Hour) // 1 year ago
	dm.Decay(&r, time.Now())

	if r.Importance < 0.3 {
		t.Errorf("landmark importance should be >= 0.3 (floor), got %f", r.Importance)
	}
}

func TestDecayManager_ShouldPrune(t *testing.T) {
	dm, _ := NewDecayManager(time.Hour, 0, 0.3)
	r := NewMemoryRecord("r", "s", map[string]any{}, nil, 0.01, false)
	if !dm.ShouldPrune(&r, 0.05) {
		t.Error("expected ShouldPrune true for low-importance non-landmark")
	}
	r.IsLandmark = true
	if dm.ShouldPrune(&r, 0.05) {
		t.Error("landmark should never be pruned")
	}
}

func TestDecayManager_InvalidHalfLife(t *testing.T) {
	_, err := NewDecayManager(0, 0, 0.3)
	if err == nil {
		t.Fatal("expected error for zero half-life")
	}
}

// ---------------------------------------------------------------------------
// ImportanceScorer
// ---------------------------------------------------------------------------

func TestImportanceScorer_WeightsMustSumToOne(t *testing.T) {
	_, err := NewImportanceScorer(0.5, 0.5, 0.5, 0.5)
	if err == nil {
		t.Fatal("expected error when weights don't sum to 1.0")
	}
}

func TestImportanceScorer_RegimeBoost(t *testing.T) {
	s := DefaultImportanceScorer()
	now := time.Now()

	rSame := NewMemoryRecord("volatile", "move", map[string]any{}, nil, 0.5, false)
	rDiff := NewMemoryRecord("trending", "move", map[string]any{}, nil, 0.5, false)

	scoreSame := s.Score(&rSame, "volatile", now)
	scoreDiff := s.Score(&rDiff, "volatile", now)

	if scoreSame <= scoreDiff {
		t.Errorf("matching regime should score higher: same=%f diff=%f", scoreSame, scoreDiff)
	}
}

func TestImportanceScorer_Rank(t *testing.T) {
	s := DefaultImportanceScorer()
	now := time.Now()

	high := NewMemoryRecord("r", "s", map[string]any{}, nil, 0.9, false)
	low := NewMemoryRecord("r", "s", map[string]any{}, nil, 0.1, false)
	records := []*MemoryRecord{&low, &high}

	ranked := s.Rank(records, "r", now, 0)
	if ranked[0].Record.Importance < ranked[1].Record.Importance {
		t.Error("Rank should return descending order")
	}
}

// ---------------------------------------------------------------------------
// ConsolidationPipeline
// ---------------------------------------------------------------------------

func TestConsolidationPipeline_AddAndGet(t *testing.T) {
	cfg := DefaultConsolidationConfig()
	p, err := NewConsolidationPipeline(cfg, nil)
	if err != nil {
		t.Fatal(err)
	}

	r := NewMemoryRecord("volatile", "price_move", map[string]any{"val": 1}, nil, 0.8, false)
	p.Add(r)

	got, ok := p.Get(r.MemoryID)
	if !ok || got == nil {
		t.Fatal("expected to find added record")
	}
	if got.AccessCount != 1 {
		t.Errorf("expected access count 1, got %d", got.AccessCount)
	}
}

func TestConsolidationPipeline_Consolidate_PromotesOldRecords(t *testing.T) {
	cfg := DefaultConsolidationConfig()
	cfg.MinAge = 0               // promote immediately
	cfg.PromotionThreshold = 0.3 // our importance is above this
	p, err := NewConsolidationPipeline(cfg, nil)
	if err != nil {
		t.Fatal(err)
	}

	r := NewMemoryRecord("r", "s", map[string]any{}, nil, 0.8, false)
	p.Add(r)

	result, err := p.Consolidate()
	if err != nil {
		t.Fatal(err)
	}
	if result.Consolidated != 1 {
		t.Errorf("expected 1 consolidated, got %d", result.Consolidated)
	}
	if p.LongTermSize() != 1 {
		t.Errorf("expected 1 in long-term, got %d", p.LongTermSize())
	}
	if p.ShortTermSize() != 0 {
		t.Errorf("expected 0 in short-term, got %d", p.ShortTermSize())
	}
}

func TestConsolidationPipeline_Consolidate_PrunesLowImportance(t *testing.T) {
	cfg := DefaultConsolidationConfig()
	cfg.MinAge = 365 * 24 * time.Hour // high min age so nothing is promoted
	cfg.PruneThreshold = 0.5          // prune everything below 0.5
	p, err := NewConsolidationPipeline(cfg, nil)
	if err != nil {
		t.Fatal(err)
	}

	r := NewMemoryRecord("r", "s", map[string]any{}, nil, 0.1, false) // below prune threshold
	p.Add(r)

	result, err := p.Consolidate()
	if err != nil {
		t.Fatal(err)
	}
	if result.Pruned != 1 {
		t.Errorf("expected 1 pruned, got %d", result.Pruned)
	}
}

func TestConsolidationPipeline_MaybeConsolidate_RespectsInterval(t *testing.T) {
	cfg := DefaultConsolidationConfig()
	cfg.Interval = time.Hour // very long interval
	p, err := NewConsolidationPipeline(cfg, nil)
	if err != nil {
		t.Fatal(err)
	}

	result, err := p.MaybeConsolidate()
	if err != nil {
		t.Fatal(err)
	}
	if result != nil {
		t.Fatal("expected MaybeConsolidate to skip because interval not elapsed")
	}
}

func TestConsolidationPipeline_Query(t *testing.T) {
	cfg := DefaultConsolidationConfig()
	p, err := NewConsolidationPipeline(cfg, nil)
	if err != nil {
		t.Fatal(err)
	}

	r1 := NewMemoryRecord("volatile", "price_move", map[string]any{}, nil, 0.9, false)
	r2 := NewMemoryRecord("trending", "regime_shift", map[string]any{}, nil, 0.5, false)
	p.Add(r1)
	p.Add(r2)

	results := p.Query("volatile", "", nil, nil, "volatile", 10)
	if len(results) == 0 {
		t.Fatal("expected at least one result from query")
	}
	if results[0].Record.MemoryID != r1.MemoryID {
		t.Error("expected volatile record ranked first")
	}
}

func TestConsolidationPipeline_Stats(t *testing.T) {
	cfg := DefaultConsolidationConfig()
	p, _ := NewConsolidationPipeline(cfg, nil)
	p.Add(NewMemoryRecord("r", "s", map[string]any{}, nil, 0.5, false))
	stats := p.Stats()
	if stats["short_term"].(int) != 1 {
		t.Errorf("expected short_term=1 in stats, got %v", stats["short_term"])
	}
}
