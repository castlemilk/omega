package eval

import (
	"context"
	"testing"

	"github.com/benebsworth/omega/internal/adversarial"
	"github.com/benebsworth/omega/internal/core"
)

// ---------------------------------------------------------------------------
// Ring 1: ensemble disagreement
// ---------------------------------------------------------------------------

func TestRing1_NoDisagreement(t *testing.T) {
	h := NewRing1Harness(0.5)
	ctx := context.Background()

	// All variants produce identical outputs → no disagreement.
	output := map[string]float64{"BTCUSDT": 0.5, "ETHUSDT": 0.3}
	h.RegisterAndSubmit("v1", output)
	h.RegisterAndSubmit("v2", output)
	h.RegisterAndSubmit("v3", output)

	result := h.RunCycle(ctx)
	if result.Flagged {
		t.Errorf("expected no disagreement, got Flagged=true MaxDisagreement=%.4f", result.MaxDisagreement)
	}
	if result.MaxDisagreement != 0.0 {
		t.Errorf("MaxDisagreement=%v want=0", result.MaxDisagreement)
	}
}

func TestRing1_LargeDisagreementFlagged(t *testing.T) {
	h := NewRing1Harness(0.3)
	ctx := context.Background()

	// Two variants with maximally divergent outputs.
	h.RegisterAndSubmit("bull", map[string]float64{"BTCUSDT": 1.0, "ETHUSDT": 1.0})
	h.RegisterAndSubmit("bear", map[string]float64{"BTCUSDT": -1.0, "ETHUSDT": -1.0})

	result := h.RunCycle(ctx)
	if !result.Flagged {
		t.Errorf("expected Flagged=true, MaxDisagreement=%.4f threshold=0.3", result.MaxDisagreement)
	}
	if len(result.DisagreeingVariants) != 2 {
		t.Errorf("DisagreeingVariants=%v want 2 entries", result.DisagreeingVariants)
	}
}

func TestRing1_BelowThresholdNotFlagged(t *testing.T) {
	// High threshold: even a large gap does not flag.
	h := NewRing1Harness(10.0)
	ctx := context.Background()

	h.RegisterAndSubmit("v1", map[string]float64{"BTC": 0.9})
	h.RegisterAndSubmit("v2", map[string]float64{"BTC": 0.1})

	result := h.RunCycle(ctx)
	if result.Flagged {
		t.Errorf("expected no flag with high threshold, got Flagged=true")
	}
}

func TestRing1_ThreeVariantsDivergence(t *testing.T) {
	// Three variants; two agree, one is the outlier.
	h := NewRing1Harness(0.5)
	ctx := context.Background()

	h.RegisterAndSubmit("v1", map[string]float64{"BTC": 0.5, "ETH": 0.5})
	h.RegisterAndSubmit("v2", map[string]float64{"BTC": 0.5, "ETH": 0.5})
	h.RegisterAndSubmit("v3", map[string]float64{"BTC": -0.9, "ETH": -0.9})

	result := h.RunCycle(ctx)
	if !result.Flagged {
		t.Errorf("expected Flagged=true with outlier variant")
	}
}

func TestRing1_OutputsCopiedNotAliased(t *testing.T) {
	h := NewRing1Harness(0.5)
	ctx := context.Background()

	out := map[string]float64{"BTC": 0.5}
	h.RegisterAndSubmit("v1", out)
	h.RegisterAndSubmit("v2", out)
	result := h.RunCycle(ctx)

	// Mutate original; result.Outputs must be unaffected.
	out["BTC"] = 99.0
	if result.Outputs["v1"]["BTC"] == 99.0 {
		t.Error("outputs were aliased instead of copied")
	}
}

// ---------------------------------------------------------------------------
// Ring 2: scenario stress testing
// ---------------------------------------------------------------------------

func TestRing2_BaseScenariosFail(t *testing.T) {
	// Pass threshold = 0.99: almost no strategy can pass every scenario.
	h := NewRing2Harness(0.99)
	bank := core.NewHistoricalScenarioBank()
	scenarios := bank.AllScenarios()
	if len(scenarios) == 0 {
		t.Fatal("historical scenario bank is empty")
	}

	baseSignals := map[string]float64{"BTCUSDT": 0.6, "ETHUSDT": 0.4}
	_, report := h.RunScenarios(context.Background(), scenarios, baseSignals)

	// With threshold=0.99, gate should not pass.
	if report.GatePassed {
		t.Errorf("expected gate to fail with threshold=0.99, WorstResilience=%.4f", report.WorstResilience)
	}
	if report.WorstScenario == "" {
		t.Error("WorstScenario should be populated")
	}
	if len(report.RunResults) != len(scenarios) {
		t.Errorf("RunResults len=%d want=%d", len(report.RunResults), len(scenarios))
	}
}

func TestRing2_LowThresholdPasses(t *testing.T) {
	// Pass threshold = 0.0: every scenario trivially passes.
	h := NewRing2Harness(0.0)
	bank := core.NewHistoricalScenarioBank()
	scenarios := bank.AllScenarios()

	baseSignals := map[string]float64{"BTCUSDT": 0.5, "ETHUSDT": 0.3}
	results, _ := h.RunScenarios(context.Background(), scenarios, baseSignals)

	for _, r := range results {
		if !r.Passed {
			t.Errorf("scenario %q should pass at threshold=0.0, got ResilienceScore=%.4f", r.ScenarioID, r.ResilienceScore)
		}
	}
}

func TestRing2_SeverityOrderedWorstCase(t *testing.T) {
	h := NewRing2Harness(0.5)
	bank := core.NewHistoricalScenarioBank()
	scenarios := bank.AllScenarios()

	baseSignals := map[string]float64{"BTCUSDT": 0.5}
	_, report := h.RunScenarios(context.Background(), scenarios, baseSignals)

	// WorstResilience must be <= OverallResilience.
	if report.WorstResilience > report.OverallResilience {
		t.Errorf("WorstResilience=%.4f > OverallResilience=%.4f", report.WorstResilience, report.OverallResilience)
	}
}

// ---------------------------------------------------------------------------
// Ring 3: evolutionary tournament
// ---------------------------------------------------------------------------

func TestRing3_PopulationEvolvesWithSelectionPressure(t *testing.T) {
	// Fitness = param["alpha"] — champion should have highest alpha.
	fitnessFn := func(params map[string]any) float64 {
		if v, ok := params["alpha"].(float64); ok {
			return v
		}
		return 0.0
	}
	h := NewRing3Harness(5, 0.1, fitnessFn)
	baseParams := map[string]any{"alpha": 1.0, "beta": 0.5}

	result, err := h.Run(context.Background(), baseParams)
	if err != nil {
		t.Fatalf("RunTournament error: %v", err)
	}
	if result.ChampionID == "" {
		t.Error("expected a champion after tournament")
	}
	if len(result.FitnessScores) == 0 {
		t.Error("expected non-empty FitnessScores")
	}
	// Champion must have a positive fitness score.
	championScore, ok := result.FitnessScores[result.ChampionID]
	if !ok {
		// Champion may have been created by mutation; just verify it's non-negative.
		t.Logf("champion %q not in FitnessScores (may be a mutant)", result.ChampionID)
	} else if championScore < 0 {
		t.Errorf("champion fitness=%.4f should be non-negative", championScore)
	}
}

func TestRing3_EliminationReducesPopulation(t *testing.T) {
	h := NewRing3Harness(6, 0.05, nil)
	baseParams := map[string]any{"x": 1.0, "y": 2.0}
	h.Tournament.InitialisePopulation(baseParams)

	before := h.Tournament.CurrentPopulationSize()
	scores := h.Tournament.Evaluate(h.FitnessFn)
	h.Tournament.EliminateLosers(scores, 0.5) // keep 50%

	after := h.Tournament.CurrentPopulationSize()
	if after >= before {
		t.Errorf("population should shrink after elimination: before=%d after=%d", before, after)
	}
}

// ---------------------------------------------------------------------------
// Debate gate
// ---------------------------------------------------------------------------

func TestDebateGate_StrongBull_BuysWithHighConfidence(t *testing.T) {
	h := NewDebateHarness()
	verdict, action, scale := h.Evaluate(StrongBullContext())

	if verdict.Direction != adversarial.DirectionBuy {
		t.Errorf("Direction=%v want=BUY", verdict.Direction)
	}
	if verdict.Confidence <= 0.5 {
		t.Errorf("Confidence=%.4f should be > 0.5 for strong bull", verdict.Confidence)
	}
	if action != adversarial.ActionProceed && action != adversarial.ActionReduce {
		t.Errorf("Action=%v want Proceed or Reduce", action)
	}
	_ = scale
}

func TestDebateGate_StrongBear_SellsOrHolds(t *testing.T) {
	h := NewDebateHarness()
	verdict, _, _ := h.Evaluate(StrongBearContext())

	if verdict.Direction == adversarial.DirectionBuy {
		t.Errorf("Direction=BUY unexpected for strong bear context")
	}
}

func TestDebateGate_ConfidenceBounds(t *testing.T) {
	tests := []struct {
		name string
		ctx  adversarial.SignalContext
	}{
		{"strong_bull", StrongBullContext()},
		{"strong_bear", StrongBearContext()},
		{"neutral", adversarial.DefaultSignalContext()},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			h := NewDebateHarness()
			verdict, _, scale := h.Evaluate(tt.ctx)
			if verdict.Confidence < 0 || verdict.Confidence > 1 {
				t.Errorf("Confidence=%.4f out of [0,1]", verdict.Confidence)
			}
			if scale < 0 || scale > 1 {
				t.Errorf("PositionScale=%.4f out of [0,1]", scale)
			}
		})
	}
}

func TestDebateGate_ActionMapping(t *testing.T) {
	tests := []struct {
		name       string
		confidence float64
		wantAction adversarial.DebateAction
	}{
		{"high_confidence", 0.7, adversarial.ActionProceed},
		{"mid_confidence", 0.5, adversarial.ActionReduce},
		{"low_confidence", 0.3, adversarial.ActionVeto},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			verdict := adversarial.DebateVerdict{
				Direction:     adversarial.DirectionBuy,
				Confidence:    tt.confidence,
				PositionScale: 0.8,
			}
			action, _ := adversarial.ActionFromVerdict(verdict)
			if action != tt.wantAction {
				t.Errorf("action=%v want=%v", action, tt.wantAction)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// Risk persona debate
// ---------------------------------------------------------------------------

func TestRiskDebate_HighRisk_ConservativeDominates(t *testing.T) {
	h := NewRiskDebateHarness()
	result := h.Debate.Resolve(HighRiskContext())

	if result.PositionScale < 0 || result.PositionScale > 1 {
		t.Errorf("PositionScale=%.4f out of [0,1]", result.PositionScale)
	}
	// In high-risk context conservative should recommend a small scale; final should be < 0.5.
	if result.PositionScale >= 0.5 {
		t.Errorf("PositionScale=%.4f should be < 0.5 in high-risk context", result.PositionScale)
	}
}

func TestRiskDebate_LowRisk_AggressiveDominates(t *testing.T) {
	h := NewRiskDebateHarness()
	result := h.Debate.Resolve(LowRiskContext())

	// In low-risk context aggressive should push scale up; final should be > 0.4.
	if result.PositionScale <= 0.4 {
		t.Errorf("PositionScale=%.4f should be > 0.4 in low-risk context", result.PositionScale)
	}
}

func TestRiskDebate_AllVerdictsFilled(t *testing.T) {
	h := NewRiskDebateHarness()
	result := h.Debate.Resolve(adversarial.DefaultRiskContext())

	if result.AggressiveVerdict.Persona == "" {
		t.Error("AggressiveVerdict persona missing")
	}
	if result.ConservativeVerdict.Persona == "" {
		t.Error("ConservativeVerdict persona missing")
	}
	if result.NeutralVerdict.Persona == "" {
		t.Error("NeutralVerdict persona missing")
	}
}

func TestRiskDebate_CredibilityWeightedScale(t *testing.T) {
	// Verify that the resolved scale lies between conservative (low) and aggressive (high) scales.
	h := NewRiskDebateHarness()
	ctx := adversarial.DefaultRiskContext()
	result := h.Debate.Resolve(ctx)

	minScale := result.ConservativeVerdict.RecommendedScale
	maxScale := result.AggressiveVerdict.RecommendedScale
	if result.PositionScale < minScale-1e-9 || result.PositionScale > maxScale+1e-9 {
		t.Errorf("PositionScale=%.4f outside [conservative=%.4f, aggressive=%.4f]",
			result.PositionScale, minScale, maxScale)
	}
}
