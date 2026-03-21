package eval

import (
	"context"
	"database/sql"
	"testing"

	"github.com/benebsworth/omega/internal/core"
	_ "modernc.org/sqlite"
)

// MemoryHarness wraps MemoryKernel backed by an in-memory SQLite database.
type MemoryHarness struct {
	Kernel *core.MemoryKernel
	db     *sql.DB
}

// NewMemoryHarness opens an in-memory SQLite DB and returns a ready MemoryHarness.
// t.Cleanup automatically closes the DB when the test ends.
func NewMemoryHarness(t *testing.T) *MemoryHarness {
	t.Helper()
	db, err := sql.Open("sqlite", ":memory:")
	if err != nil {
		t.Fatalf("open in-memory sqlite: %v", err)
	}
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)

	kernel, err := core.NewMemoryKernel(db)
	if err != nil {
		_ = db.Close()
		t.Fatalf("NewMemoryKernel: %v", err)
	}

	t.Cleanup(func() { _ = db.Close() })
	return &MemoryHarness{Kernel: kernel, db: db}
}

// StoreFixedEpisodes stores n episodes with fixed content under the given namespace.
func (h *MemoryHarness) StoreFixedEpisodes(ctx context.Context, t *testing.T, namespace string, n int) []string {
	t.Helper()
	ids := make([]string, 0, n)
	for i := 0; i < n; i++ {
		ep := core.Episode{
			EventType:  "signal_generated",
			Content:    map[string]any{"index": i, "value": float64(i) * 0.1},
			Tags:       []string{"eval", "test"},
			Importance: 0.6 + float64(i)*0.01,
			Cycle:      i + 1,
			Namespace:  namespace,
		}
		id, err := h.Kernel.StoreEpisode(ctx, ep)
		if err != nil {
			t.Fatalf("StoreEpisode[%d]: %v", i, err)
		}
		ids = append(ids, id)
	}
	return ids
}

// StoreFixedSemanticMemory stores a SemanticMemory and returns its ID.
func (h *MemoryHarness) StoreFixedSemanticMemory(ctx context.Context, t *testing.T, concept, namespace string) string {
	t.Helper()
	sm := core.SemanticMemory{
		Concept:       concept,
		Content:       "learned pattern for " + concept,
		Confidence:    0.8,
		EvidenceCount: 3,
		Tags:          []string{"eval", concept},
		Namespace:     namespace,
	}
	id, err := h.Kernel.StoreSemantic(ctx, sm)
	if err != nil {
		t.Fatalf("StoreSemantic: %v", err)
	}
	return id
}

// RunCycleLifecycle runs BeginCycle/EndCycle for cycles 1..n.
func (h *MemoryHarness) RunCycleLifecycle(ctx context.Context, t *testing.T, n int) {
	t.Helper()
	for cycle := 1; cycle <= n; cycle++ {
		if err := h.Kernel.BeginCycle(ctx, cycle); err != nil {
			t.Fatalf("BeginCycle(%d): %v", cycle, err)
		}
		summary := map[string]any{
			"cycle":   cycle,
			"signals": float64(cycle) * 0.5,
		}
		if _, err := h.Kernel.EndCycle(ctx, cycle, summary); err != nil {
			t.Fatalf("EndCycle(%d): %v", cycle, err)
		}
	}
}
