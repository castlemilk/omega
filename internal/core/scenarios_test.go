package core

import (
	"context"
	"testing"
)

// ---------------------------------------------------------------------------
// HistoricalScenarioBank
// ---------------------------------------------------------------------------

func TestHistoricalScenarioBank_LoadsCanonical(t *testing.T) {
	bank := NewHistoricalScenarioBank()
	if bank.Len() < 7 {
		t.Errorf("expected at least 7 canonical scenarios, got %d", bank.Len())
	}
}

func TestHistoricalScenarioBank_GetByTag(t *testing.T) {
	bank := NewHistoricalScenarioBank()
	crashes := bank.GetByTag("crash")
	if len(crashes) == 0 {
		t.Error("expected at least one scenario with tag 'crash'")
	}
	for _, r := range crashes {
		found := false
		for _, tag := range r.Tags {
			if tag == "crash" {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("scenario %s returned by GetByTag('crash') but doesn't have tag 'crash'", r.Scenario.ScenarioID)
		}
	}
}

func TestHistoricalScenarioBank_GetBySeverity(t *testing.T) {
	bank := NewHistoricalScenarioBank()
	highSeverity := bank.GetBySeverity(0.90, 1.0)
	for _, r := range highSeverity {
		if r.Scenario.Severity < 0.90 || r.Scenario.Severity > 1.0 {
			t.Errorf("scenario %s has severity %.2f outside [0.90, 1.0]", r.Scenario.ScenarioID, r.Scenario.Severity)
		}
	}
}

func TestHistoricalScenarioBank_Add(t *testing.T) {
	bank := NewHistoricalScenarioBank()
	before := bank.Len()
	bank.Add(ScenarioRecord{
		Scenario: Scenario{
			ScenarioID: "test_custom",
			Name:       "Custom Test",
			Severity:   0.5,
		},
		Tags:   []string{"test"},
		Source: "user",
	})
	if bank.Len() != before+1 {
		t.Errorf("expected %d scenarios after add, got %d", before+1, bank.Len())
	}
	if r, ok := bank.Get("test_custom"); !ok {
		t.Error("expected to retrieve added scenario by ID")
	} else if r.Scenario.Name != "Custom Test" {
		t.Errorf("expected name 'Custom Test', got '%s'", r.Scenario.Name)
	}
}

func TestHistoricalScenarioBank_AllScenarios(t *testing.T) {
	bank := NewHistoricalScenarioBank()
	all := bank.AllScenarios()
	if len(all) != bank.Len() {
		t.Errorf("AllScenarios length %d != bank.Len() %d", len(all), bank.Len())
	}
}

// ---------------------------------------------------------------------------
// SyntheticScenarioGenerator
// ---------------------------------------------------------------------------

func TestSyntheticScenarioGenerator_Generate(t *testing.T) {
	gen := NewSyntheticScenarioGenerator(42, true)
	baseSignals := map[string]float64{"BTC": 0.8, "ETH": 0.6, "SOL": 0.4}
	scenarios := gen.Generate(baseSignals, 10, nil)
	if len(scenarios) != 10 {
		t.Errorf("expected 10 scenarios, got %d", len(scenarios))
	}
	// Should be sorted by severity descending
	for i := 1; i < len(scenarios); i++ {
		if scenarios[i].Severity > scenarios[i-1].Severity {
			t.Errorf("scenarios not sorted by severity at index %d", i)
		}
	}
}

func TestSyntheticScenarioGenerator_Generate_EmptySignals(t *testing.T) {
	gen := NewSyntheticScenarioGenerator(42, true)
	scenarios := gen.Generate(nil, 5, nil)
	if len(scenarios) != 0 {
		t.Error("expected empty scenarios for empty base_signals")
	}
}

func TestSyntheticScenarioGenerator_AllModes(t *testing.T) {
	gen := NewSyntheticScenarioGenerator(42, true)
	baseSignals := map[string]float64{"BTC": 0.5, "ETH": 0.3}

	modes := []SyntheticMode{
		ModeAmplitudeScaling,
		ModeTailShock,
		ModeCorrelationNuke,
		ModeRegimeFlip,
		ModeVolExplosion,
	}
	for _, mode := range modes {
		t.Run(string(mode), func(t *testing.T) {
			s := gen.Perturb(baseSignals, mode, 0.5)
			if s.ScenarioID == "" {
				t.Error("expected non-empty scenario_id")
			}
			if s.Severity < 0 || s.Severity > 1 {
				t.Errorf("severity %.2f out of [0,1]", s.Severity)
			}
			if s.VolMultiplier <= 0 {
				t.Errorf("vol_multiplier %.2f must be positive", s.VolMultiplier)
			}
		})
	}
}

func TestSyntheticScenarioGenerator_UnknownMode(t *testing.T) {
	gen := NewSyntheticScenarioGenerator(42, true)
	baseSignals := map[string]float64{"BTC": 0.5}
	s := gen.Perturb(baseSignals, "unknown_mode", 0.5)
	if s.Severity != 0.0 {
		t.Errorf("expected severity=0 for unknown mode, got %.2f", s.Severity)
	}
}

// ---------------------------------------------------------------------------
// ScenarioRunner
// ---------------------------------------------------------------------------

func TestScenarioRunner_Run_DefaultScorer(t *testing.T) {
	strategy := func(signals map[string]float64, _ Scenario) map[string]float64 {
		// Passthrough strategy
		return signals
	}
	runner := NewScenarioRunner(strategy, nil, 0.30, 42, true)

	baseSignals := map[string]float64{"BTC": 0.8, "ETH": 0.6}
	scenarios := []Scenario{
		{
			ScenarioID:    "test_1",
			Name:          "Test Scenario",
			MarketShocks:  map[string]float64{"BTC": -0.10},
			VolMultiplier: 1.5,
			Severity:      0.5,
		},
	}

	results := runner.Run(context.Background(), scenarios, baseSignals)
	if len(results) != 1 {
		t.Fatalf("expected 1 result, got %d", len(results))
	}
	if results[0].ResilienceScore < 0 || results[0].ResilienceScore > 1 {
		t.Errorf("resilience score %.4f out of [0,1]", results[0].ResilienceScore)
	}
}

func TestScenarioRunner_Run_PanicRecovery(t *testing.T) {
	panicStrategy := func(signals map[string]float64, _ Scenario) map[string]float64 {
		panic("deliberate test panic")
	}
	runner := NewScenarioRunner(panicStrategy, nil, 0.30, 42, true)
	scenarios := []Scenario{{ScenarioID: "x", Name: "X", Severity: 0.5, VolMultiplier: 1.0, MarketShocks: map[string]float64{}}}
	results := runner.Run(context.Background(), scenarios, map[string]float64{"BTC": 0.5})
	if len(results) != 1 {
		t.Fatal("expected 1 result even after panic")
	}
}

// ---------------------------------------------------------------------------
// SimulationGate
// ---------------------------------------------------------------------------

func TestSimulationGate_Evaluate_EmptyResults(t *testing.T) {
	gate := NewSimulationGate(DefaultSimulationGateConfig())
	report := gate.Evaluate("test_strategy", nil)
	if report.GatePassed {
		t.Error("expected gate to fail with no run results")
	}
}

func TestSimulationGate_Evaluate_AllPassing(t *testing.T) {
	gate := NewSimulationGate(DefaultSimulationGateConfig())
	results := []RunResult{
		{ScenarioID: "s1", ResilienceScore: 0.8, Passed: true, Severity: 0.5},
		{ScenarioID: "s2", ResilienceScore: 0.7, Passed: true, Severity: 0.5},
		{ScenarioID: "s3", ResilienceScore: 0.6, Passed: true, Severity: 0.5},
	}
	report := gate.Evaluate("test_strategy", results)
	if !report.GatePassed {
		t.Errorf("expected gate to pass: %s", report.GateReason)
	}
	if report.OverallResilience < 0.5 {
		t.Errorf("expected high overall resilience, got %.3f", report.OverallResilience)
	}
}

func TestSimulationGate_Evaluate_LowOverallResilience(t *testing.T) {
	gate := NewSimulationGate(DefaultSimulationGateConfig())
	results := []RunResult{
		{ScenarioID: "s1", ResilienceScore: 0.10, Passed: false, Severity: 0.5},
		{ScenarioID: "s2", ResilienceScore: 0.10, Passed: false, Severity: 0.5},
	}
	report := gate.Evaluate("test_strategy", results)
	if report.GatePassed {
		t.Error("expected gate to fail with low overall resilience")
	}
}

func TestSimulationGate_Evaluate_WorstScenarioTracked(t *testing.T) {
	gate := NewSimulationGate(DefaultSimulationGateConfig())
	results := []RunResult{
		{ScenarioID: "s1", ScenarioName: "Easy", ResilienceScore: 0.9, Passed: true, Severity: 0.3},
		{ScenarioID: "s2", ScenarioName: "Hard", ResilienceScore: 0.05, Passed: false, Severity: 0.9},
	}
	report := gate.Evaluate("test_strategy", results)
	if report.WorstScenario != "s2" {
		t.Errorf("expected worst scenario 's2', got '%s'", report.WorstScenario)
	}
}

func TestSimulationGate_RunAndEvaluate(t *testing.T) {
	gate := NewSimulationGate(DefaultSimulationGateConfig())
	strategy := func(signals map[string]float64, _ Scenario) map[string]float64 { return signals }
	baseSignals := map[string]float64{"BTC": 0.8, "ETH": 0.6}
	scenarios := []Scenario{
		{ScenarioID: "t1", Name: "T1", Severity: 0.5, VolMultiplier: 1.5, MarketShocks: map[string]float64{"BTC": -0.05}},
	}
	report := gate.RunAndEvaluate(context.Background(), "strategy_v1", strategy, scenarios, baseSignals, 0.30, nil)
	if report.StrategyID != "strategy_v1" {
		t.Errorf("expected strategy_id 'strategy_v1', got '%s'", report.StrategyID)
	}
}
