package core

// benchmark_test.go — benchmarks for the hot paths in Omega's orchestration core.
//
// Run with:
//
//	go test ./internal/core/... -bench=. -benchmem -count=1 -benchtime=3s
//
// Benchmarks establish baselines for:
//   - Working-memory lookups (MemoryKernel)
//   - Episodic memory queries (MemoryKernel)
//   - Safety envelope checks (SafetyEnvelope)
//   - NSGA-II Pareto ranking (ParetoEvaluator)
//   - Outcome-based scoring (OutcomeBasedScorer)
//   - Goal architecture step (GoalArchitecture)
//   - Ring 1 ensemble disagreement detection (EnsembleDisagreementDetector)
//   - Adversarial pressure run (AdversarialPressure)

import (
	"context"
	"database/sql"
	"fmt"
	"testing"

	_ "modernc.org/sqlite"
)

// ---------------------------------------------------------------------------
// Helpers shared by multiple benchmarks
// ---------------------------------------------------------------------------

// openInMemDB opens an ephemeral SQLite database for benchmarks.
func openInMemDB(b *testing.B) *sql.DB {
	b.Helper()
	db, err := sql.Open("sqlite", "file::memory:?cache=shared")
	if err != nil {
		b.Fatalf("openInMemDB: %v", err)
	}
	db.SetMaxOpenConns(1)
	b.Cleanup(func() { _ = db.Close() })
	return db
}

// newBenchKernel returns a MemoryKernel backed by an in-memory SQLite DB.
func newBenchKernel(b *testing.B) *MemoryKernel {
	b.Helper()
	db := openInMemDB(b)
	k, err := NewMemoryKernel(db)
	if err != nil {
		b.Fatalf("NewMemoryKernel: %v", err)
	}
	return k
}

// ---------------------------------------------------------------------------
// Working-memory benchmarks
// ---------------------------------------------------------------------------

func BenchmarkWorkingMemory_Set(b *testing.B) {
	k := newBenchKernel(b)
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		k.SetWorking(fmt.Sprintf("key-%d", i%100), i)
	}
}

func BenchmarkWorkingMemory_Get(b *testing.B) {
	k := newBenchKernel(b)
	for i := 0; i < 100; i++ {
		k.SetWorking(fmt.Sprintf("key-%d", i), i)
	}
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		k.GetWorking(fmt.Sprintf("key-%d", i%100))
	}
}

func BenchmarkWorkingMemory_Snapshot(b *testing.B) {
	k := newBenchKernel(b)
	for i := 0; i < 50; i++ {
		k.SetWorking(fmt.Sprintf("key-%d", i), i)
	}
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		_ = k.WorkingSnapshot()
	}
}

// ---------------------------------------------------------------------------
// Episodic memory benchmarks
// ---------------------------------------------------------------------------

func BenchmarkEpisodicMemory_Store(b *testing.B) {
	k := newBenchKernel(b)
	ctx := context.Background()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		ep := Episode{
			EventType:  "benchmark_event",
			Content:    map[string]any{"i": i, "score": float64(i) * 0.01},
			Tags:       []string{"bench"},
			Importance: 0.5,
			Cycle:      i,
			Namespace:  "bench",
		}
		_, err := k.StoreEpisode(ctx, ep)
		if err != nil {
			b.Fatal(err)
		}
	}
}

// BenchmarkEpisodicMemory_Query measures retrieval after seeding N episodes.
// Table-driven to show query cost at different corpus sizes.
func BenchmarkEpisodicMemory_Query(b *testing.B) {
	sizes := []int{10, 100, 500}
	for _, n := range sizes {
		n := n
		b.Run(fmt.Sprintf("n=%d", n), func(b *testing.B) {
			k := newBenchKernel(b)
			ctx := context.Background()
			for i := 0; i < n; i++ {
				ep := Episode{
					EventType:  "bench_event",
					Content:    map[string]any{"i": i},
					Tags:       []string{"bench"},
					Importance: 0.5,
					Cycle:      i,
					Namespace:  "bench",
				}
				if _, err := k.StoreEpisode(ctx, ep); err != nil {
					b.Fatal(err)
				}
			}
			f := EpisodeFilter{
				Namespace:     "bench",
				MinImportance: 0.3,
				Limit:         20,
			}
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				_, err := k.RetrieveEpisodes(ctx, f)
				if err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}

// ---------------------------------------------------------------------------
// Safety envelope benchmarks
// ---------------------------------------------------------------------------

func BenchmarkSafetyEnvelope_Check(b *testing.B) {
	se := NewSafetyEnvelope(0.3, 0.15, 0.8, 0.5)
	portfolio := map[string]float64{
		"BTC":  0.25,
		"ETH":  0.25,
		"SOL":  0.25,
		"USDC": 0.25,
	}
	corrMatrix := map[string]map[string]float64{
		"BTC":  {"ETH": 0.75, "SOL": 0.70, "USDC": 0.05},
		"ETH":  {"BTC": 0.75, "SOL": 0.68, "USDC": 0.04},
		"SOL":  {"BTC": 0.70, "ETH": 0.68, "USDC": 0.03},
		"USDC": {"BTC": 0.05, "ETH": 0.04, "SOL": 0.03},
	}
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		_, _ = se.Check(portfolio, 0.05, corrMatrix)
	}
}

func BenchmarkSafetyEnvelope_Clamp(b *testing.B) {
	se := NewSafetyEnvelope(0.25, 0.15, 0.8, 0.5)
	portfolio := map[string]float64{
		"BTC":  0.5, // over-concentrated → will be clamped
		"ETH":  0.3,
		"SOL":  0.15,
		"USDC": 0.05,
	}
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		_ = se.Clamp(portfolio)
	}
}

// ---------------------------------------------------------------------------
// Pareto evaluator benchmarks
// ---------------------------------------------------------------------------

func BenchmarkParetoEvaluator_AssignRanks(b *testing.B) {
	sizes := []int{5, 20, 100}
	for _, n := range sizes {
		n := n
		b.Run(fmt.Sprintf("n=%d", n), func(b *testing.B) {
			pe := &ParetoEvaluator{}
			population := make([]map[string]float64, n)
			for i := range population {
				population[i] = map[string]float64{
					"accuracy": 0.5 + float64(i)/float64(n)*0.5,
					"latency":  200 - float64(i)*1.5,
					"drawdown": 0.1 + float64(i%5)*0.02,
				}
			}
			objectives := []string{"accuracy", "latency", "drawdown"}
			directions := map[string]string{"accuracy": "max", "latency": "min", "drawdown": "min"}
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				_ = pe.AssignRanks(population, objectives, directions)
			}
		})
	}
}

func BenchmarkParetoEvaluator_NSGA2Sort(b *testing.B) {
	sizes := []int{10, 50}
	for _, n := range sizes {
		n := n
		b.Run(fmt.Sprintf("n=%d", n), func(b *testing.B) {
			pe := &ParetoEvaluator{}
			population := make([]map[string]float64, n)
			for i := range population {
				population[i] = map[string]float64{
					"accuracy": 0.5 + float64(i)/float64(n)*0.4,
					"latency":  300 - float64(i)*2.0,
				}
			}
			objectives := []string{"accuracy", "latency"}
			directions := map[string]string{"accuracy": "max", "latency": "min"}
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				_ = pe.NSGA2Sort(population, objectives, directions)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// Outcome-based scorer benchmarks
// ---------------------------------------------------------------------------

func BenchmarkOutcomeBasedScorer_RecordAndScore(b *testing.B) {
	sizes := []int{5, 20, 100}
	for _, n := range sizes {
		n := n
		b.Run(fmt.Sprintf("nodes=%d", n), func(b *testing.B) {
			s := NewOutcomeBasedScorer()
			// Pre-populate history for each node.
			for i := 0; i < n; i++ {
				nodeID := fmt.Sprintf("node-%d", i)
				for j := 0; j < 30; j++ {
					predicted := 0.5 + float64(j%5)*0.1
					actual := predicted + float64(j%3)*0.05 - 0.05
					s.RecordOutcome(nodeID, predicted, actual, 0.02)
				}
			}
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				nodeID := fmt.Sprintf("node-%d", i%n)
				s.RecordOutcome(nodeID, 0.7, 0.72, 0.015)
				_ = s.Score(nodeID)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// Goal architecture benchmarks
// ---------------------------------------------------------------------------

func BenchmarkGoalArchitecture_Step(b *testing.B) {
	ga := NewGoalArchitecture(nil)
	ctx := context.Background()
	metrics := map[string]float64{
		"accuracy":        0.85,
		"sharpe_ratio":    1.8,
		"max_drawdown_pct": 5.0,
		"error_rate":      0.02,
	}
	systemState := map[string]any{
		"data_stale": false,
	}
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		_ = ga.Step(ctx, metrics, systemState, i)
	}
}

// ---------------------------------------------------------------------------
// Ring 1 ensemble disagreement benchmarks
// ---------------------------------------------------------------------------

func BenchmarkRing1_Detect(b *testing.B) {
	variantCounts := []int{3, 10, 50}
	for _, nv := range variantCounts {
		nv := nv
		b.Run(fmt.Sprintf("variants=%d", nv), func(b *testing.B) {
			d := NewEnsembleDisagreementDetector(0.2)
			ctx := context.Background()
			for v := 0; v < nv; v++ {
				vid := fmt.Sprintf("v%d", v)
				d.RegisterVariant(vid, "bench variant")
				d.SubmitOutput(vid, map[string]float64{
					"BTC": 0.5 + float64(v)*0.01,
					"ETH": 0.3 - float64(v)*0.005,
					"SOL": 0.2,
				})
			}
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				_ = d.Detect(ctx)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// AdversarialPressure.Run benchmark (Ring 1 only for predictable timing)
// ---------------------------------------------------------------------------

func BenchmarkAdversarialPressure_Run_Ring1(b *testing.B) {
	ap := NewAdversarialPressure(0.2, 5, []int{1})
	ctx := context.Background()

	variantOutputs := map[string]map[string]float64{
		"v0": {"BTC": 0.50, "ETH": 0.30},
		"v1": {"BTC": 0.52, "ETH": 0.29},
		"v2": {"BTC": 0.48, "ETH": 0.31},
	}
	currentSignals := map[string]float64{"BTC": 0.5, "ETH": 0.3}
	fitnessFn := func(params map[string]any) float64 { return 0.8 }

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		_ = ap.Run(ctx, i, variantOutputs, currentSignals, nil, fitnessFn)
	}
}
