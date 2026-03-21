// Package eval provides integration evaluation harnesses for the Omega framework.
// Each harness exercises a subsystem end-to-end with deterministic, fixed test data.
package eval

import (
	"context"

	"github.com/benebsworth/omega/internal/core"
)

// AutonomyHarness wraps AutonomyManager and provides deterministic scenario helpers.
type AutonomyHarness struct {
	Manager *core.AutonomyManager
}

// NewAutonomyHarness creates a harness backed by a fresh AutonomyManager.
func NewAutonomyHarness() *AutonomyHarness {
	return &AutonomyHarness{Manager: core.NewAutonomyManager()}
}

// GoodMetrics returns fixed performance metrics that satisfy all promotion thresholds.
func GoodMetrics() map[string]float64 {
	return map[string]float64{
		"sharpe":     1.2,
		"pnl":        0.08,
		"error_rate": 0.02,
	}
}

// PoorMetrics returns fixed performance metrics that should block promotion.
func PoorMetrics() map[string]float64 {
	return map[string]float64{
		"sharpe":     0.2,
		"pnl":        -0.05,
		"error_rate": 0.30,
	}
}

// FeedSuccessfulCycles records n successful cycles for nodeID starting at startCycle.
func (h *AutonomyHarness) FeedSuccessfulCycles(nodeID string, n int, startCycle int64, metrics map[string]float64) {
	for i := 0; i < n; i++ {
		h.Manager.RecordCycleMetrics(nodeID, startCycle+int64(i), metrics, true)
	}
}

// FeedFailedCycles records n failed cycles for nodeID starting at startCycle.
func (h *AutonomyHarness) FeedFailedCycles(nodeID string, n int, startCycle int64, metrics map[string]float64) {
	for i := 0; i < n; i++ {
		h.Manager.RecordCycleMetrics(nodeID, startCycle+int64(i), metrics, false)
	}
}

// AttemptPromotion requests a promotion to targetLevel. If approved, records it immediately.
func (h *AutonomyHarness) AttemptPromotion(
	ctx context.Context,
	nodeID string,
	targetLevel core.AutonomyLevel,
	metrics map[string]float64,
	cycle int64,
) core.PromotionResult {
	result := h.Manager.RequestPromotion(ctx, nodeID, targetLevel, metrics, cycle)
	if result.Approved {
		current := h.Manager.GetLevel(nodeID).Level
		h.Manager.RecordPromotion(nodeID, current, result.GrantedLevel, "eval_promotion", cycle)
	}
	return result
}

// PromoteThroughLevel feeds 10 successful cycles then requests promotion to nextLevel.
// Returns the PromotionResult and the next available cycle counter.
func (h *AutonomyHarness) PromoteThroughLevel(
	ctx context.Context,
	nodeID string,
	nextLevel core.AutonomyLevel,
	metrics map[string]float64,
	startCycle int64,
) (core.PromotionResult, int64) {
	h.FeedSuccessfulCycles(nodeID, 10, startCycle, metrics)
	promotionCycle := startCycle + 10
	result := h.AttemptPromotion(ctx, nodeID, nextLevel, metrics, promotionCycle)
	return result, promotionCycle + 1
}

// AutonomyLifecycleResult captures the outcome of a full lifecycle run.
type AutonomyLifecycleResult struct {
	// PromotionResults holds the result at each attempted promotion step.
	PromotionResults []core.PromotionResult
	// FinalLevel is the node's level after the scenario completes.
	FinalLevel core.AutonomyLevel
	// History is the full recorded promotion/demotion log.
	History []core.PromotionEvent
}

// RunFullLifecycle promotes nodeID from Manual → Supervised → Semi → Full using
// goodMetrics, then demotes it back to Manual, then verifies that re-promotion
// from zero cycles is correctly blocked.
func (h *AutonomyHarness) RunFullLifecycle(ctx context.Context, nodeID string) AutonomyLifecycleResult {
	good := GoodMetrics()
	var cycle int64 = 1
	promotionResults := make([]core.PromotionResult, 0, 4)

	// Promote: Manual → Supervised → Semi → Full
	for _, target := range []core.AutonomyLevel{
		core.AutonomyLevelSupervised,
		core.AutonomyLevelSemi,
		core.AutonomyLevelFull,
	} {
		r, nextCycle := h.PromoteThroughLevel(ctx, nodeID, target, good, cycle)
		promotionResults = append(promotionResults, r)
		cycle = nextCycle
	}

	// Demote: record a direct demotion back to Manual (simulates metric degradation).
	h.Manager.RecordPromotion(nodeID, core.AutonomyLevelFull, core.AutonomyLevelManual, "performance_degradation", cycle)
	cycle++

	// Immediately attempt re-promotion — should be blocked (zero cycles at current level).
	blockedResult := h.AttemptPromotion(ctx, nodeID, core.AutonomyLevelSupervised, good, cycle)
	promotionResults = append(promotionResults, blockedResult)

	return AutonomyLifecycleResult{
		PromotionResults: promotionResults,
		FinalLevel:       h.Manager.GetLevel(nodeID).Level,
		History:          h.Manager.GetHistory(nodeID, 0),
	}
}
