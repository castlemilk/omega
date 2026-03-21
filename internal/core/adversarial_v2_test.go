package core

import (
	"context"
	"testing"
)

// ---------------------------------------------------------------------------
// AdaptiveThresholdManager
// ---------------------------------------------------------------------------

func TestAdaptiveThresholdManager_NoAdjustmentWithinCooldown(t *testing.T) {
	cfg := DefaultAdaptiveThresholdConfig(0.20)
	cfg.AdjustmentInterval = 10
	mgr := NewAdaptiveThresholdManager(cfg)

	// First adjustment at cycle 10 (interval has elapsed since init at -10)
	adj := mgr.Update(10, 0.50, 0.40)
	if adj == nil {
		t.Fatal("expected first adjustment at cycle 10")
	}
	thresholdAfterFirst := mgr.CurrentThreshold

	// Second call at cycle 15 — only 5 cycles after last adjustment (< 10)
	adj2 := mgr.Update(15, 0.50, 0.40)
	if adj2 != nil {
		t.Error("expected no adjustment within cooldown period")
	}
	if mgr.CurrentThreshold != thresholdAfterFirst {
		t.Errorf("expected threshold unchanged at %.4f, got %.4f", thresholdAfterFirst, mgr.CurrentThreshold)
	}
}

func TestAdaptiveThresholdManager_RaiseThresholdOnHighFPRate(t *testing.T) {
	cfg := DefaultAdaptiveThresholdConfig(0.20)
	cfg.AdjustmentInterval = 0 // no delay
	mgr := NewAdaptiveThresholdManager(cfg)
	mgr.lastAdjustmentCycle = -100

	adj := mgr.Update(10, 0.50, 0.40) // FP rate 0.50 > watermark 0.30
	if adj == nil {
		t.Fatal("expected adjustment when FP rate is high")
	}
	if adj.NewThreshold <= adj.OldThreshold {
		t.Errorf("expected threshold to increase: old=%.4f new=%.4f", adj.OldThreshold, adj.NewThreshold)
	}
}

func TestAdaptiveThresholdManager_LowerThresholdOnLowFPLowFlag(t *testing.T) {
	cfg := DefaultAdaptiveThresholdConfig(0.20)
	cfg.AdjustmentInterval = 0
	mgr := NewAdaptiveThresholdManager(cfg)
	mgr.lastAdjustmentCycle = -100

	// FP rate < 0.05 and flag_rate < 0.05 → lower threshold
	adj := mgr.Update(10, 0.01, 0.01)
	if adj == nil {
		t.Fatal("expected adjustment when FP rate and flag rate are very low")
	}
	if adj.NewThreshold >= adj.OldThreshold {
		t.Errorf("expected threshold to decrease: old=%.4f new=%.4f", adj.OldThreshold, adj.NewThreshold)
	}
}

func TestAdaptiveThresholdManager_NoAdjustmentInNormalRange(t *testing.T) {
	cfg := DefaultAdaptiveThresholdConfig(0.20)
	cfg.AdjustmentInterval = 0
	mgr := NewAdaptiveThresholdManager(cfg)
	mgr.lastAdjustmentCycle = -100

	adj := mgr.Update(10, 0.15, 0.10) // normal range
	if adj != nil {
		t.Error("expected no adjustment for normal FP rate and flag rate")
	}
}

func TestAdaptiveThresholdManager_ClampedAtMinMax(t *testing.T) {
	cfg := DefaultAdaptiveThresholdConfig(0.05)
	cfg.MinThreshold = 0.05
	cfg.AdjustmentInterval = 0
	mgr := NewAdaptiveThresholdManager(cfg)
	mgr.lastAdjustmentCycle = -100

	// Already at min, low flag rate — should not go below min
	mgr.Update(10, 0.01, 0.01)
	if mgr.CurrentThreshold < cfg.MinThreshold {
		t.Errorf("threshold %.4f went below min %.4f", mgr.CurrentThreshold, cfg.MinThreshold)
	}
}

// ---------------------------------------------------------------------------
// DisagreementAttributor
// ---------------------------------------------------------------------------

func TestDisagreementAttributor_NoVariants(t *testing.T) {
	da := NewDisagreementAttributor(1.5)
	result := da.Attribute(DisagreementResult{
		Flagged: true,
		Outputs: map[string]map[string]float64{},
	})
	if result.Confidence != 0 {
		t.Errorf("expected confidence=0 with no variants, got %.2f", result.Confidence)
	}
}

func TestDisagreementAttributor_ClearOutlier(t *testing.T) {
	da := NewDisagreementAttributor(1.5)
	result := da.Attribute(DisagreementResult{
		Flagged: true,
		Outputs: map[string]map[string]float64{
			"v_a": {"BTC": 0.8, "ETH": 0.7},
			"v_b": {"BTC": 0.75, "ETH": 0.72}, // close to v_a
			"v_c": {"BTC": 0.05, "ETH": 0.04}, // clear outlier
		},
	})
	if len(result.OutlierVariants) == 0 {
		t.Error("expected at least one outlier variant")
	}
	found := false
	for _, id := range result.OutlierVariants {
		if id == "v_c" {
			found = true
		}
	}
	if !found {
		t.Errorf("expected v_c to be identified as outlier, got %v", result.OutlierVariants)
	}
}

func TestDisagreementAttributor_FallbackForFlaggedWithNoZscore(t *testing.T) {
	// When flagged but no variant exceeds z-score threshold, return highest-z variant
	da := NewDisagreementAttributor(10.0) // very high threshold
	result := da.Attribute(DisagreementResult{
		Flagged: true,
		Outputs: map[string]map[string]float64{
			"v_a": {"BTC": 0.5},
			"v_b": {"BTC": 0.3},
		},
	})
	if len(result.OutlierVariants) == 0 {
		t.Error("expected fallback outlier variant even with high z-score threshold")
	}
}

// ---------------------------------------------------------------------------
// FalsePositiveTracker
// ---------------------------------------------------------------------------

func TestFalsePositiveTracker_RateBeforeAnyOutcomes(t *testing.T) {
	tracker := NewFalsePositiveTracker(100)
	if tracker.FalsePositiveRate() != 0.0 {
		t.Error("expected FP rate = 0 before any outcomes")
	}
}

func TestFalsePositiveTracker_RecordAndRetrieve(t *testing.T) {
	tracker := NewFalsePositiveTracker(100)
	tracker.RecordFlag(1, true)
	tracker.RecordOutcome(1, true) // false positive

	rate := tracker.FalsePositiveRate()
	if rate != 1.0 {
		t.Errorf("expected FP rate = 1.0 after 1 FP, got %.2f", rate)
	}
}

func TestFalsePositiveTracker_MixedOutcomes(t *testing.T) {
	tracker := NewFalsePositiveTracker(100)
	for i := 0; i < 10; i++ {
		tracker.RecordFlag(i, true)
		tracker.RecordOutcome(i, i < 3) // 3 FPs, 7 TPs
	}
	rate := tracker.FalsePositiveRate()
	if rate < 0.28 || rate > 0.32 {
		t.Errorf("expected FP rate ~0.30, got %.2f", rate)
	}
}

func TestFalsePositiveTracker_PendingOutcomes(t *testing.T) {
	tracker := NewFalsePositiveTracker(100)
	tracker.RecordFlag(1, true)
	tracker.RecordFlag(2, true)
	tracker.RecordOutcome(1, false)

	pending := tracker.PendingOutcomes()
	if len(pending) != 1 || pending[0] != 2 {
		t.Errorf("expected pending=[2], got %v", pending)
	}
}

func TestFalsePositiveTracker_FlagRate(t *testing.T) {
	tracker := NewFalsePositiveTracker(100)
	for i := 0; i < 10; i++ {
		tracker.RecordFlag(i, i%2 == 0) // 5 flagged, 5 not
	}
	rate := tracker.FlagRate(0)
	if rate < 0.48 || rate > 0.52 {
		t.Errorf("expected flag rate ~0.5, got %.2f", rate)
	}
}

func TestFalsePositiveTracker_OutcomeForNonFlagged(t *testing.T) {
	tracker := NewFalsePositiveTracker(100)
	tracker.RecordFlag(5, false) // not flagged
	tracker.RecordOutcome(5, true)
	// Should not change resolved window
	if tracker.FalsePositiveRate() != 0.0 {
		t.Error("outcome for non-flagged should not affect FP rate")
	}
}

func TestFalsePositiveTracker_Summary(t *testing.T) {
	tracker := NewFalsePositiveTracker(100)
	tracker.RecordFlag(1, true)
	tracker.RecordOutcome(1, false)
	s := tracker.Summary()
	if s["total_cycles_observed"].(int) != 1 {
		t.Error("expected 1 cycle observed")
	}
	if s["total_flagged"].(int) != 1 {
		t.Error("expected 1 flagged")
	}
}

// ---------------------------------------------------------------------------
// Ring2ActivationController
// ---------------------------------------------------------------------------

func TestRing2ActivationController_NotActivatedBeforeMinCycles(t *testing.T) {
	ctrl := NewRing2ActivationController(20, 0.05, nil)
	if ctrl.ShouldActivate(5, 0.10) {
		t.Error("should not activate before min cycles")
	}
}

func TestRing2ActivationController_ActivatedAfterMinCycles(t *testing.T) {
	ctrl := NewRing2ActivationController(20, 0.05, nil)
	if !ctrl.ShouldActivate(20, 0.10) {
		t.Error("should activate after min cycles with sufficient flag rate")
	}
}

func TestRing2ActivationController_RecordGateResult(t *testing.T) {
	ctrl := NewRing2ActivationController(1, 0.01, nil)
	ctrl.ShouldActivate(5, 0.10)
	ctrl.RecordGateResult(5, true)
	ctrl.RecordGateResult(6, true)
	ctrl.RecordGateResult(7, false)

	status := ctrl.Status()
	if status.ConsecutiveGatePasses != 0 {
		t.Errorf("expected 0 consecutive passes after a fail, got %d", status.ConsecutiveGatePasses)
	}
	if status.ConsecutiveGateFails != 1 {
		t.Errorf("expected 1 consecutive fail, got %d", status.ConsecutiveGateFails)
	}
	if status.TotalEvaluations != 3 {
		t.Errorf("expected 3 total evaluations, got %d", status.TotalEvaluations)
	}
}

// ---------------------------------------------------------------------------
// AdversarialPressureV2 integration
// ---------------------------------------------------------------------------

func TestAdversarialPressureV2_RunV2_Basic(t *testing.T) {
	cfg := DefaultAdversarialPressureV2Config()
	cfg.Ring1Threshold = 0.2
	ap := NewAdversarialPressureV2(cfg)

	variantOutputs := map[string]map[string]float64{
		"v_a": {"BTC": 0.9, "ETH": 0.8},
		"v_b": {"BTC": 0.1, "ETH": 0.1},
	}
	signals := map[string]float64{"BTC": 0.7}
	report := ap.RunV2(context.Background(), 1, variantOutputs, signals, nil, nil, nil)

	if report.BaseReport.Ring1Result == nil {
		t.Error("expected Ring1Result")
	}
	if !report.BaseReport.Ring1Result.Flagged {
		t.Error("expected Ring1 to flag disagreement")
	}
	if report.Attribution == nil {
		t.Error("expected attribution on flagged Ring1")
	}
	if report.CurrentThreshold <= 0 {
		t.Error("expected positive current_threshold")
	}
}

func TestAdversarialPressureV2_RegisterOutcome_AffectsFPRate(t *testing.T) {
	cfg := DefaultAdversarialPressureV2Config()
	ap := NewAdversarialPressureV2(cfg)

	// Run cycle that flags
	variantOutputs := map[string]map[string]float64{
		"v_a": {"BTC": 0.9},
		"v_b": {"BTC": 0.1},
	}
	ap.RunV2(context.Background(), 1, variantOutputs, nil, nil, nil, nil)
	ap.RegisterOutcome(1, true) // it was a false positive

	rate := ap.fpTracker.FalsePositiveRate()
	if rate != 1.0 {
		t.Errorf("expected FP rate = 1.0 after recording one FP, got %.2f", rate)
	}
}

func TestAdversarialPressureV2_NilStrategyCallable_NoRing2Gate(t *testing.T) {
	cfg := DefaultAdversarialPressureV2Config()
	cfg.MinRing1CyclesForRing2 = 1
	cfg.MinRing1FlagRateForRing2 = 0.01
	ap := NewAdversarialPressureV2(cfg)

	// Run enough cycles to activate Ring2
	for i := 0; i < 5; i++ {
		variantOutputs := map[string]map[string]float64{
			"v_a": {"BTC": 0.9},
			"v_b": {"BTC": 0.1},
		}
		ap.RunV2(context.Background(), i, variantOutputs, nil, nil, nil, nil)
	}

	// On the sim interval but no strategy callable → no Ring2 sim report
	report := ap.RunV2(context.Background(), ring2SimInterval, nil, nil, nil, nil, nil)
	if report.Ring2SimReport != nil {
		t.Error("expected no Ring2 sim report without strategy callable")
	}
}
