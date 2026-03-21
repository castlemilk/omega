package eval_test

import (
	"context"
	"fmt"
	"testing"

	"github.com/benebsworth/omega/internal/core"
	"github.com/benebsworth/omega/internal/eval"
)

// ---------------------------------------------------------------------------
// Test doubles
// ---------------------------------------------------------------------------

// improvingHarness returns scores that increase by delta on each call.
type improvingHarness struct {
	name  string
	score float64
	delta float64
}

func (h *improvingHarness) Name() string { return h.name }
func (h *improvingHarness) Run() eval.EvalResult {
	s := h.score
	h.score += h.delta
	if h.score > 1.0 {
		h.score = 1.0
	}
	passed := int(s * 10)
	return eval.EvalResult{
		Passed:  passed,
		Failed:  10 - passed,
		Score:   s,
		Details: []string{fmt.Sprintf("score=%.2f", s)},
	}
}

// fixedScoreHarness returns the same score every call.
type fixedScoreHarness struct {
	name   string
	scores []float64
	call   int
}

func (h *fixedScoreHarness) Name() string { return h.name }
func (h *fixedScoreHarness) Run() eval.EvalResult {
	idx := h.call
	if idx >= len(h.scores) {
		idx = len(h.scores) - 1
	}
	h.call++
	s := h.scores[idx]
	passed := int(s * 10)
	return eval.EvalResult{
		Passed:  passed,
		Failed:  10 - passed,
		Score:   s,
		Details: []string{fmt.Sprintf("call=%d score=%.2f", h.call, s)},
	}
}

// mockOrchestrator is a no-op orchestrator.
type mockOrchestrator struct{ cycles int }

func (m *mockOrchestrator) RunCycle(_ context.Context) (*core.CycleResult, error) {
	m.cycles++
	return &core.CycleResult{}, nil
}

// mockImprovementEngine counts improvement cycle invocations.
type mockImprovementEngine struct{ calls int }

func (m *mockImprovementEngine) RunImprovementCycle(_ context.Context) error {
	m.calls++
	return nil
}

// mockMemory collects stored episodes.
type mockMemory struct{ episodes []core.Episode }

func (m *mockMemory) StoreEpisode(_ context.Context, ep core.Episode) (string, error) {
	m.episodes = append(m.episodes, ep)
	return ep.EpisodeID, nil
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

// TestFeedbackLoop_ScoresTrendUp verifies that 3 iterations with improving
// harnesses produce an "improving" direction in the report.
func TestFeedbackLoop_ScoresTrendUp(t *testing.T) {
	orch := &mockOrchestrator{}
	engine := &mockImprovementEngine{}
	mem := &mockMemory{}

	harnesses := []eval.EvalHarness{
		&improvingHarness{name: "autonomy", score: 0.5, delta: 0.1},
		&improvingHarness{name: "safety", score: 0.6, delta: 0.1},
		&improvingHarness{name: "memory", score: 0.55, delta: 0.1},
	}

	fl := eval.NewFeedbackLoop(orch, engine, mem, harnesses, nil)
	report, err := fl.RunLoop(context.Background(), 3)
	if err != nil {
		t.Fatalf("RunLoop error: %v", err)
	}

	if len(report.Iterations) != 3 {
		t.Fatalf("expected 3 iterations, got %d", len(report.Iterations))
	}

	// Verify scores increase across iterations for each harness.
	for _, name := range []string{"autonomy", "safety", "memory"} {
		s1 := report.Iterations[0].Scores[name]
		s3 := report.Iterations[2].Scores[name]
		if s3 <= s1 {
			t.Errorf("harness %q: expected score to trend up, got iter1=%.2f iter3=%.2f", name, s1, s3)
		}
	}

	if report.Direction != "improving" {
		t.Errorf("expected direction=improving, got %q", report.Direction)
	}

	// Orchestrator should have been called once per iteration.
	if orch.cycles != 3 {
		t.Errorf("expected 3 orchestrator cycles, got %d", orch.cycles)
	}

	// Memory should have received 3 harnesses × 3 iterations = 9 episodes.
	if len(mem.episodes) != 9 {
		t.Errorf("expected 9 stored episodes, got %d", len(mem.episodes))
	}
}

// TestFeedbackLoop_RegressionDetection verifies that a score drop is flagged
// as a regression in the iteration result.
func TestFeedbackLoop_RegressionDetection(t *testing.T) {
	orch := &mockOrchestrator{}
	engine := &mockImprovementEngine{}
	mem := &mockMemory{}

	// "good" harness starts high; "bad" harness drops in iteration 2.
	harnesses := []eval.EvalHarness{
		&fixedScoreHarness{name: "good", scores: []float64{0.9, 0.9, 0.9}},
		&fixedScoreHarness{name: "bad", scores: []float64{0.8, 0.4, 0.4}},
	}

	fl := eval.NewFeedbackLoop(orch, engine, mem, harnesses, nil)
	report, err := fl.RunLoop(context.Background(), 3)
	if err != nil {
		t.Fatalf("RunLoop error: %v", err)
	}

	// Iteration 1 has no previous scores, so no regressions.
	if len(report.Iterations[0].Regressions) != 0 {
		t.Errorf("iter 1: expected no regressions, got %v", report.Iterations[0].Regressions)
	}

	// Iteration 2: "bad" drops from 0.8 → 0.4 → regression.
	iter2Regressions := report.Iterations[1].Regressions
	if len(iter2Regressions) != 1 || iter2Regressions[0] != "bad" {
		t.Errorf("iter 2: expected regression [bad], got %v", iter2Regressions)
	}

	// Iteration 3: "bad" stays at 0.4 (no change) → no new regression.
	if len(report.Iterations[2].Regressions) != 0 {
		t.Errorf("iter 3: expected no regressions, got %v", report.Iterations[2].Regressions)
	}
}

// TestFeedbackLoop_ImprovementEngineTriggered verifies that the improvement
// engine is called when a harness score drops (regression) or falls below
// the degradation threshold.
func TestFeedbackLoop_ImprovementEngineTriggered(t *testing.T) {
	orch := &mockOrchestrator{}
	engine := &mockImprovementEngine{}
	mem := &mockMemory{}

	// Harness starts high, drops below threshold in iteration 2, recovers in 3.
	harnesses := []eval.EvalHarness{
		&fixedScoreHarness{name: "subsystem", scores: []float64{0.9, 0.5, 0.9}},
	}

	fl := eval.NewFeedbackLoop(orch, engine, mem, harnesses, nil)
	report, err := fl.RunLoop(context.Background(), 3)
	if err != nil {
		t.Fatalf("RunLoop error: %v", err)
	}

	// Iter 1: score=0.9, above threshold, no regression → no improvement cycle.
	if len(report.Iterations[0].Improvements) != 0 {
		t.Errorf("iter 1: expected no improvements triggered, got %v", report.Iterations[0].Improvements)
	}

	// Iter 2: score drops to 0.5 (below 0.7 threshold) AND regression detected
	// → improvement engine must be called.
	if len(report.Iterations[1].Improvements) == 0 {
		t.Error("iter 2: expected improvement cycle to be triggered, got none")
	}

	// Engine should have been called at least once (for iter 2).
	if engine.calls < 1 {
		t.Errorf("expected improvement engine called ≥1 time, got %d", engine.calls)
	}

	// Iter 3: score recovers to 0.9, no regression → improvement engine not called again.
	callsAfterIter2 := engine.calls
	_ = callsAfterIter2 // captured; iter 3 should not add more calls
	if len(report.Iterations[2].Improvements) != 0 {
		t.Errorf("iter 3: expected no improvements triggered, got %v", report.Iterations[2].Improvements)
	}
}

// TestFeedbackLoop_Adapters verifies that the named adapters implement
// EvalHarness with the expected names.
func TestFeedbackLoop_Adapters(t *testing.T) {
	noop := func() eval.EvalResult { return eval.EvalResult{Score: 1.0} }

	cases := []struct {
		harness eval.EvalHarness
		want    string
	}{
		{eval.NewAutonomyEvalAdapter(noop), "autonomy"},
		{eval.NewAdversarialEvalAdapter(noop), "adversarial"},
		{eval.NewSafetyEvalAdapter(noop), "safety"},
		{eval.NewMemoryEvalAdapter(noop), "memory"},
		{eval.NewImprovementEvalAdapter(noop), "improvement"},
	}

	for _, tc := range cases {
		t.Run(tc.want, func(t *testing.T) {
			if tc.harness.Name() != tc.want {
				t.Errorf("Name() = %q, want %q", tc.harness.Name(), tc.want)
			}
			res := tc.harness.Run()
			if res.Score != 1.0 {
				t.Errorf("Run().Score = %.2f, want 1.0", res.Score)
			}
		})
	}
}

// TestFeedbackReport_Direction verifies direction computation for various trajectories.
func TestFeedbackReport_Direction(t *testing.T) {
	orch := &mockOrchestrator{}
	engine := &mockImprovementEngine{}
	mem := &mockMemory{}

	t.Run("degrading", func(t *testing.T) {
		harnesses := []eval.EvalHarness{
			&fixedScoreHarness{name: "h", scores: []float64{0.9, 0.7, 0.5}},
		}
		fl := eval.NewFeedbackLoop(orch, engine, mem, harnesses, nil)
		report, _ := fl.RunLoop(context.Background(), 3)
		if report.Direction != "degrading" {
			t.Errorf("expected degrading, got %q", report.Direction)
		}
	})

	t.Run("stable", func(t *testing.T) {
		harnesses := []eval.EvalHarness{
			&fixedScoreHarness{name: "h", scores: []float64{0.7, 0.7, 0.7}},
		}
		fl := eval.NewFeedbackLoop(orch, engine, mem, harnesses, nil)
		report, _ := fl.RunLoop(context.Background(), 3)
		if report.Direction != "stable" {
			t.Errorf("expected stable, got %q", report.Direction)
		}
	})
}
