package eval

import (
	"context"
	"os"
	"testing"

	"github.com/benebsworth/omega/internal/core"
	"github.com/benebsworth/omega/internal/db"
)

// MemoryHarness wraps MemoryKernel backed by a Postgres database.
type MemoryHarness struct {
	Kernel *core.MemoryKernel
	database *db.DB
}

// NewMemoryHarness opens a Postgres DB (via TEST_DATABASE_URL) and returns a ready MemoryHarness.
// Test is skipped if TEST_DATABASE_URL is not set.
func NewMemoryHarness(t *testing.T) *MemoryHarness {
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

	kernel, err := core.NewMemoryKernel(database.StateDB())
	if err != nil {
		database.Close()
		t.Fatalf("NewMemoryKernel: %v", err)
	}

	t.Cleanup(func() { database.Close() })
	return &MemoryHarness{Kernel: kernel, database: database}
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
