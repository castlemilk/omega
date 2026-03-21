package core

import (
	"context"
	"math"
	"testing"
)

// ---------------------------------------------------------------------------
// EnsembleDisagreementDetector
// ---------------------------------------------------------------------------

func TestNormalisedDistance(t *testing.T) {
	tests := []struct {
		name string
		a    map[string]float64
		b    map[string]float64
		want float64 // approximately
	}{
		{
			name: "identical outputs",
			a:    map[string]float64{"BTC": 0.8, "ETH": 0.6},
			b:    map[string]float64{"BTC": 0.8, "ETH": 0.6},
			want: 0.0,
		},
		{
			name: "no shared keys",
			a:    map[string]float64{"BTC": 0.8},
			b:    map[string]float64{"SOL": 0.4},
			want: 0.0,
		},
		{
			name: "single shared key full disagreement",
			a:    map[string]float64{"BTC": 1.0},
			b:    map[string]float64{"BTC": 0.0},
			want: 1.0,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := normalisedDistance(tt.a, tt.b)
			if math.Abs(got-tt.want) > 1e-9 {
				t.Errorf("normalisedDistance() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestEnsembleDisagreementDetector_NoOutputs(t *testing.T) {
	d := NewEnsembleDisagreementDetector(0.2)
	result := d.Detect(context.Background())
	if result.Flagged {
		t.Error("expected no flag with empty outputs")
	}
	if result.MaxDisagreement != 0.0 {
		t.Errorf("expected max_disagreement=0, got %v", result.MaxDisagreement)
	}
}

func TestEnsembleDisagreementDetector_AgreementBelowThreshold(t *testing.T) {
	d := NewEnsembleDisagreementDetector(0.5)
	d.RegisterVariant("v_a", "aggressive")
	d.RegisterVariant("v_b", "conservative")
	d.SubmitOutput("v_a", map[string]float64{"BTC": 0.8, "ETH": 0.6})
	d.SubmitOutput("v_b", map[string]float64{"BTC": 0.75, "ETH": 0.58}) // close
	result := d.Detect(context.Background())
	if result.Flagged {
		t.Errorf("expected no flag, got flagged with max_disagreement=%.4f", result.MaxDisagreement)
	}
}

func TestEnsembleDisagreementDetector_DisagreementAboveThreshold(t *testing.T) {
	d := NewEnsembleDisagreementDetector(0.2)
	d.SubmitOutput("v_a", map[string]float64{"BTC": 0.9, "ETH": 0.8})
	d.SubmitOutput("v_b", map[string]float64{"BTC": 0.1, "ETH": 0.1})
	result := d.Detect(context.Background())
	if !result.Flagged {
		t.Errorf("expected flagged, got max_disagreement=%.4f", result.MaxDisagreement)
	}
	if len(result.DisagreeingVariants) == 0 {
		t.Error("expected non-empty disagreeing_variants")
	}
}

func TestEnsembleDisagreementDetector_Clear(t *testing.T) {
	d := NewEnsembleDisagreementDetector(0.2)
	d.SubmitOutput("v_a", map[string]float64{"BTC": 0.9})
	d.SubmitOutput("v_b", map[string]float64{"BTC": 0.1})
	d.Clear()
	result := d.Detect(context.Background())
	if result.Flagged {
		t.Error("expected no flag after clear")
	}
}

func TestEnsembleDisagreementDetector_AutoRegister(t *testing.T) {
	d := NewEnsembleDisagreementDetector(0.2)
	// Submit without prior register — should auto-register
	d.SubmitOutput("v_new", map[string]float64{"BTC": 0.5})
	result := d.Detect(context.Background())
	if _, ok := result.Outputs["v_new"]; !ok {
		t.Error("expected v_new in outputs")
	}
}

// ---------------------------------------------------------------------------
// ScenarioGenerator
// ---------------------------------------------------------------------------

func TestScenarioGenerator_BaseScenarios(t *testing.T) {
	g := NewScenarioGenerator(42, true)
	scenarios := g.baseStressScenarios()
	if len(scenarios) != 6 {
		t.Errorf("expected 6 base scenarios, got %d", len(scenarios))
	}
	for _, s := range scenarios {
		if s.Severity < 0 || s.Severity > 1 {
			t.Errorf("scenario %s has out-of-range severity %v", s.ScenarioID, s.Severity)
		}
		if s.VolMultiplier <= 0 {
			t.Errorf("scenario %s has non-positive vol_multiplier %v", s.ScenarioID, s.VolMultiplier)
		}
	}
}

func TestScenarioGenerator_GenerateAdversarial(t *testing.T) {
	g := NewScenarioGenerator(42, true)
	signals := map[string]float64{"BTCUSDT": 0.9, "ETHUSDT": 0.7, "SOLUSDT": 0.3}
	scenarios := g.GenerateAdversarial(context.Background(), signals, nil, 5)
	if len(scenarios) > 5 {
		t.Errorf("expected at most 5 scenarios, got %d", len(scenarios))
	}
	// Check sorted by severity descending
	for i := 1; i < len(scenarios); i++ {
		if scenarios[i].Severity > scenarios[i-1].Severity {
			t.Errorf("scenarios not sorted by severity descending at index %d", i)
		}
	}
}

func TestScenarioGenerator_GenerateAdversarial_EmptySignals(t *testing.T) {
	g := NewScenarioGenerator(42, true)
	// With empty signals, only base scenarios are returned
	scenarios := g.GenerateAdversarial(context.Background(), nil, nil, 5)
	if len(scenarios) == 0 {
		t.Error("expected at least base scenarios with empty signals")
	}
}

func TestScenarioGenerator_StressTest(t *testing.T) {
	g := NewScenarioGenerator(42, true)
	signals := map[string]float64{"BTC": 0.8, "ETH": 0.6}
	scenario := Scenario{
		ScenarioID:           "test",
		Name:                 "Test",
		MarketShocks:         map[string]float64{"BTC": -0.30},
		VolMultiplier:        2.0,
		CorrelationBreakdown: false,
		Severity:             0.7,
	}
	stressed := g.StressTest(signals, scenario)
	if len(stressed) != len(signals) {
		t.Errorf("expected %d tickers in stressed output, got %d", len(signals), len(stressed))
	}
	for _, v := range stressed {
		if v < -1.0 || v > 1.0 {
			t.Errorf("stressed signal %v out of [-1, 1] range", v)
		}
	}
}

// ---------------------------------------------------------------------------
// EvolutionaryTournament
// ---------------------------------------------------------------------------

func TestEvolutionaryTournament_InitialisePopulation(t *testing.T) {
	et := NewEvolutionaryTournament(5, 0.1)
	baseParams := map[string]any{"threshold": 0.5, "window": 20, "use_momentum": true}
	et.InitialisePopulation(baseParams)
	if et.CurrentPopulationSize() != 5 {
		t.Errorf("expected population size 5, got %d", et.CurrentPopulationSize())
	}
}

func TestEvolutionaryTournament_MutateParams_Types(t *testing.T) {
	et := NewEvolutionaryTournament(5, 0.1)
	params := map[string]any{
		"float_val": 1.0,
		"int_val":   10,
		"bool_val":  false,
		"str_val":   "unchanged",
	}
	mutated := et.mutateParams(params)
	// String values should be unchanged
	if mutated["str_val"] != "unchanged" {
		t.Errorf("string value should be unchanged, got %v", mutated["str_val"])
	}
	// Int values should remain >= 1
	if v, ok := mutated["int_val"].(int); ok {
		if v < 1 {
			t.Errorf("int_val should be >= 1 after mutation, got %d", v)
		}
	}
}

func TestEvolutionaryTournament_RunTournament(t *testing.T) {
	et := NewEvolutionaryTournament(6, 0.1)
	baseParams := map[string]any{"threshold": 0.5, "window": 20}
	et.InitialisePopulation(baseParams)

	// Deterministic fitness: higher threshold → higher fitness
	fitnessFn := func(params map[string]any) float64 {
		if t, ok := params["threshold"].(float64); ok {
			return t
		}
		return 0.0
	}

	result, err := et.RunTournament(context.Background(), fitnessFn)
	if err != nil {
		t.Fatalf("RunTournament failed: %v", err)
	}
	if result.ChampionID == "" {
		t.Error("expected non-empty champion_id")
	}
	if result.Generation != 1 {
		t.Errorf("expected generation=1, got %d", result.Generation)
	}
	if len(result.FitnessScores) == 0 {
		t.Error("expected non-empty fitness scores")
	}
}

func TestEvolutionaryTournament_RunTournament_EmptyPopulation(t *testing.T) {
	et := NewEvolutionaryTournament(5, 0.1)
	_, err := et.RunTournament(context.Background(), func(p map[string]any) float64 { return 0.0 })
	if err == nil {
		t.Error("expected error for empty population")
	}
}

func TestEvolutionaryTournament_GetChampionParams_NilOnEmpty(t *testing.T) {
	et := NewEvolutionaryTournament(5, 0.1)
	if et.GetChampionParams() != nil {
		t.Error("expected nil champion params for empty population")
	}
}

// ---------------------------------------------------------------------------
// AdversarialPressure
// ---------------------------------------------------------------------------

func TestAdversarialPressure_Run_Ring1Only(t *testing.T) {
	ap := NewAdversarialPressure(0.2, 5, []int{1})

	variantOutputs := map[string]map[string]float64{
		"v_a": {"BTC": 0.9, "ETH": 0.8},
		"v_b": {"BTC": 0.1, "ETH": 0.1},
	}
	report := ap.Run(context.Background(), 1, variantOutputs, nil, nil, nil)
	if report.Ring1Result == nil {
		t.Error("expected Ring1Result to be set")
	}
	if !report.Ring1Result.Flagged {
		t.Error("expected Ring1 to flag disagreement")
	}
	if len(report.Ring2Scenarios) != 0 {
		t.Error("expected no Ring2 scenarios (Ring 2 not active)")
	}
}

func TestAdversarialPressure_Run_Ring2_OnInterval(t *testing.T) {
	ap := NewAdversarialPressure(0.5, 5, []int{1, 2})
	signals := map[string]float64{"BTCUSDT": 0.9, "ETHUSDT": 0.7}

	// Cycle divisible by Ring2Interval (10)
	report := ap.Run(context.Background(), 10, nil, signals, nil, nil)
	if len(report.Ring2Scenarios) == 0 {
		t.Error("expected Ring2 scenarios on cycle 10")
	}

	// Cycle not divisible by Ring2Interval
	report2 := ap.Run(context.Background(), 11, nil, signals, nil, nil)
	if len(report2.Ring2Scenarios) != 0 {
		t.Error("expected no Ring2 scenarios on cycle 11")
	}
}

func TestAdversarialPressure_ValidateRing1(t *testing.T) {
	ap := NewAdversarialPressure(0.2, 5, []int{1})

	// Not enough cycles yet
	if ap.ValidateRing1(10, 0.05) {
		t.Error("should not validate with 0 cycles run")
	}

	// Run cycles with disagreement
	for i := 0; i < 12; i++ {
		var outputs map[string]map[string]float64
		if i%3 == 0 {
			// Flagged
			outputs = map[string]map[string]float64{
				"v_a": {"BTC": 0.9},
				"v_b": {"BTC": 0.1},
			}
		} else {
			// Not flagged
			outputs = map[string]map[string]float64{
				"v_a": {"BTC": 0.5},
				"v_b": {"BTC": 0.5},
			}
		}
		ap.Run(context.Background(), i, outputs, nil, nil, nil)
	}

	// Should now validate (flagged 4/12 = 33% > 5%)
	if !ap.ValidateRing1(10, 0.05) {
		t.Error("expected Ring1 to validate after sufficient flagging cycles")
	}
}

func TestAdversarialPressure_CollectAndClearFailureCases(t *testing.T) {
	ap := NewAdversarialPressure(0.2, 5, []int{1})

	// Generate a failure case
	variantOutputs := map[string]map[string]float64{
		"v_a": {"BTC": 0.9},
		"v_b": {"BTC": 0.1},
	}
	ap.Run(context.Background(), 1, variantOutputs, nil, nil, nil)

	failures := ap.CollectFailureCases()
	if len(failures) == 0 {
		t.Error("expected at least one failure case after Ring1 flag")
	}

	ap.ClearFailureCases()
	if len(ap.CollectFailureCases()) != 0 {
		t.Error("expected empty failure cases after clear")
	}
}
