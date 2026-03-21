// Package eval implements an automated eval-and-improve feedback loop.
package eval

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/benebsworth/omega/internal/core"
)

// EvalResult holds the outcome of a single harness run.
type EvalResult struct {
	Passed  int
	Failed  int
	Score   float64 // 0.0–1.0
	Details []string
}

// EvalHarness runs a named evaluation suite.
type EvalHarness interface {
	Name() string
	Run() EvalResult
}

// Orchestrator is the subset of core.Orchestrator used by FeedbackLoop.
type Orchestrator interface {
	RunCycle(ctx context.Context) (*core.CycleResult, error)
}

// ImprovementEngine is the subset of core.ImprovementEngine used by FeedbackLoop.
type ImprovementEngine interface {
	RunImprovementCycle(ctx context.Context) error
}

// MemoryStore is the subset of core.MemoryKernel used by FeedbackLoop.
type MemoryStore interface {
	StoreEpisode(ctx context.Context, ep core.Episode) (string, error)
}

// IterationResult captures scores and regressions for one feedback loop iteration.
type IterationResult struct {
	Iteration    int
	Scores       map[string]float64
	Regressions  []string // harness names that regressed vs previous iteration
	Improvements []string // actions taken in response to degradation
}

// FeedbackReport shows the complete improvement trajectory across all iterations.
type FeedbackReport struct {
	Iterations     []IterationResult
	Direction      string // "improving", "degrading", or "stable"
	BestSubsystem  string
	WorstSubsystem string
}

// FeedbackLoop orchestrates eval → analyze → improve cycles.
type FeedbackLoop struct {
	orch      Orchestrator
	engine    ImprovementEngine
	memory    MemoryStore
	harnesses []EvalHarness
	logger    *slog.Logger
}

// NewFeedbackLoop constructs a FeedbackLoop with the given dependencies.
func NewFeedbackLoop(
	orch Orchestrator,
	engine ImprovementEngine,
	memory MemoryStore,
	harnesses []EvalHarness,
	logger *slog.Logger,
) *FeedbackLoop {
	if logger == nil {
		logger = slog.Default()
	}
	return &FeedbackLoop{
		orch:      orch,
		engine:    engine,
		memory:    memory,
		harnesses: harnesses,
		logger:    logger,
	}
}

// RunLoop executes iterations feedback cycles and returns a FeedbackReport.
func (f *FeedbackLoop) RunLoop(ctx context.Context, iterations int) (FeedbackReport, error) {
	var report FeedbackReport
	prevScores := map[string]float64{}

	for i := 1; i <= iterations; i++ {
		// Run orchestration cycle before evaluating.
		if _, err := f.orch.RunCycle(ctx); err != nil {
			f.logger.Warn("orchestrator cycle error", "iteration", i, "error", err)
		}

		iter := IterationResult{
			Iteration: i,
			Scores:    make(map[string]float64),
		}

		var worstName string
		worstScore := 2.0 // sentinel above max

		// Run all harnesses, collect results.
		for _, h := range f.harnesses {
			result := h.Run()
			score := result.Score
			iter.Scores[h.Name()] = score

			// Detect regression vs previous iteration.
			if prev, ok := prevScores[h.Name()]; ok && score < prev {
				iter.Regressions = append(iter.Regressions, h.Name())
			}

			// Track worst-performing subsystem.
			if worstName == "" || score < worstScore {
				worstScore = score
				worstName = h.Name()
			}

			// Feed result into memory as an eval episode.
			ep := core.Episode{
				EpisodeID: fmt.Sprintf("eval-%s-iter%d-%d", h.Name(), i, time.Now().UnixNano()),
				Timestamp: time.Now(),
				EventType: "eval_result",
				Content: map[string]any{
					"harness": h.Name(),
					"passed":  result.Passed,
					"failed":  result.Failed,
					"score":   score,
					"details": result.Details,
					"regime":  "eval",
					"signal":  "feedback",
				},
				Tags:       []string{"eval", h.Name(), fmt.Sprintf("iteration-%d", i)},
				Importance: 1.0 - score, // lower score → higher importance
				Cycle:      i,
				Namespace:  "eval",
			}
			if _, err := f.memory.StoreEpisode(ctx, ep); err != nil {
				f.logger.Warn("failed to store eval episode", "harness", h.Name(), "error", err)
			}
		}

		// Trigger improvement when regressions detected or worst score is below threshold.
		const degradationThreshold = 0.7
		shouldImprove := len(iter.Regressions) > 0 || (worstName != "" && worstScore < degradationThreshold)
		if shouldImprove {
			if err := f.engine.RunImprovementCycle(ctx); err != nil {
				f.logger.Warn("improvement cycle error", "iteration", i, "error", err)
			} else {
				iter.Improvements = append(iter.Improvements,
					fmt.Sprintf("improvement cycle triggered (worst=%s score=%.3f regressions=%v)",
						worstName, worstScore, iter.Regressions))
			}
		}

		f.logger.Info("feedback loop iteration complete",
			"iteration", i,
			"scores", iter.Scores,
			"regressions", iter.Regressions,
			"improvements", iter.Improvements,
		)

		report.Iterations = append(report.Iterations, iter)
		prevScores = iter.Scores
	}

	report.Direction, report.BestSubsystem, report.WorstSubsystem = computeDirection(report.Iterations)
	return report, nil
}

// computeDirection summarises the overall trajectory and identifies best/worst subsystems.
func computeDirection(iters []IterationResult) (direction, best, worst string) {
	if len(iters) < 2 {
		return "stable", "", ""
	}

	first := iters[0].Scores
	last := iters[len(iters)-1].Scores

	avgFirst := avgScores(first)
	avgLast := avgScores(last)

	const epsilon = 0.01
	switch {
	case avgLast > avgFirst+epsilon:
		direction = "improving"
	case avgLast < avgFirst-epsilon:
		direction = "degrading"
	default:
		direction = "stable"
	}

	bestScore, worstScore := -1.0, 2.0
	for name, score := range last {
		if score > bestScore {
			bestScore = score
			best = name
		}
		if score < worstScore {
			worstScore = score
			worst = name
		}
	}
	return
}

func avgScores(scores map[string]float64) float64 {
	if len(scores) == 0 {
		return 0
	}
	var sum float64
	for _, v := range scores {
		sum += v
	}
	return sum / float64(len(scores))
}

// ---------------------------------------------------------------------------
// Adapters — wrap eval harness implementations into EvalHarness.
// ---------------------------------------------------------------------------

// AutonomyEvalAdapter wraps an autonomy evaluation function.
type AutonomyEvalAdapter struct{ runFn func() EvalResult }

func NewAutonomyEvalAdapter(runFn func() EvalResult) *AutonomyEvalAdapter {
	return &AutonomyEvalAdapter{runFn: runFn}
}
func (a *AutonomyEvalAdapter) Name() string    { return "autonomy" }
func (a *AutonomyEvalAdapter) Run() EvalResult { return a.runFn() }

// AdversarialEvalAdapter wraps an adversarial ring evaluation function.
type AdversarialEvalAdapter struct{ runFn func() EvalResult }

func NewAdversarialEvalAdapter(runFn func() EvalResult) *AdversarialEvalAdapter {
	return &AdversarialEvalAdapter{runFn: runFn}
}
func (a *AdversarialEvalAdapter) Name() string    { return "adversarial" }
func (a *AdversarialEvalAdapter) Run() EvalResult { return a.runFn() }

// SafetyEvalAdapter wraps a safety gate evaluation function.
type SafetyEvalAdapter struct{ runFn func() EvalResult }

func NewSafetyEvalAdapter(runFn func() EvalResult) *SafetyEvalAdapter {
	return &SafetyEvalAdapter{runFn: runFn}
}
func (a *SafetyEvalAdapter) Name() string    { return "safety" }
func (a *SafetyEvalAdapter) Run() EvalResult { return a.runFn() }

// MemoryEvalAdapter wraps a memory subsystem evaluation function.
type MemoryEvalAdapter struct{ runFn func() EvalResult }

func NewMemoryEvalAdapter(runFn func() EvalResult) *MemoryEvalAdapter {
	return &MemoryEvalAdapter{runFn: runFn}
}
func (a *MemoryEvalAdapter) Name() string    { return "memory" }
func (a *MemoryEvalAdapter) Run() EvalResult { return a.runFn() }

// ImprovementEvalAdapter wraps an improvement engine evaluation function.
type ImprovementEvalAdapter struct{ runFn func() EvalResult }

func NewImprovementEvalAdapter(runFn func() EvalResult) *ImprovementEvalAdapter {
	return &ImprovementEvalAdapter{runFn: runFn}
}
func (a *ImprovementEvalAdapter) Name() string    { return "improvement" }
func (a *ImprovementEvalAdapter) Run() EvalResult { return a.runFn() }
