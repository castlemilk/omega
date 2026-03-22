package core

import (
	"context"
	"math"
	"testing"
)

// ---------------------------------------------------------------------------
// ConstitutionalConstraints
// ---------------------------------------------------------------------------

func TestConstitutionalConstraints_NoViolations(t *testing.T) {
	cc := &ConstitutionalConstraints{}
	cc.RegisterDefaults()
	metrics := map[string]float64{
		"max_drawdown_pct": 5.0,
		"max_position_pct": 10.0,
		"sharpe_ratio":     1.5,
		"error_rate":       0.1,
	}
	passed, violations := cc.Check(context.Background(), metrics)
	if !passed {
		t.Errorf("expected passed=true, got violations: %v", violations)
	}
	if len(violations) != 0 {
		t.Errorf("expected no violations, got %d", len(violations))
	}
}

func TestConstitutionalConstraints_HardViolation(t *testing.T) {
	cc := &ConstitutionalConstraints{}
	cc.RegisterDefaults()
	metrics := map[string]float64{
		"max_drawdown_pct": 20.0, // exceeds 15 hard limit
	}
	passed, violations := cc.Check(context.Background(), metrics)
	if passed {
		t.Error("expected passed=false for hard drawdown violation")
	}
	if len(violations) != 1 {
		t.Errorf("expected 1 violation, got %d", len(violations))
	}
	if violations[0].Severity != "hard" {
		t.Errorf("expected severity=hard, got %s", violations[0].Severity)
	}
}

func TestConstitutionalConstraints_SoftViolationPassesGate(t *testing.T) {
	cc := &ConstitutionalConstraints{}
	cc.RegisterDefaults()
	metrics := map[string]float64{
		"sharpe_ratio": -3.0, // below -2.0 soft limit
	}
	passed, violations := cc.Check(context.Background(), metrics)
	// Soft violations don't block the gate.
	if !passed {
		t.Error("expected passed=true for soft-only violations")
	}
	if len(violations) != 1 {
		t.Errorf("expected 1 violation, got %d", len(violations))
	}
	if violations[0].Severity != "soft" {
		t.Errorf("expected severity=soft, got %s", violations[0].Severity)
	}
}

func TestConstitutionalConstraints_MissingMetricSkipped(t *testing.T) {
	cc := &ConstitutionalConstraints{}
	cc.Register("test_constraint", "nonexistent_metric", 10.0, "max", "hard")
	passed, violations := cc.Check(context.Background(), map[string]float64{})
	if !passed || len(violations) != 0 {
		t.Error("missing metric should be skipped silently")
	}
}

// ---------------------------------------------------------------------------
// BalancedScorecard
// ---------------------------------------------------------------------------

func TestBalancedScorecard_EqualWeights(t *testing.T) {
	bs := NewBalancedScorecard(nil)
	bs.Update(map[string]float64{
		"sharpe_ratio":      1.0,
		"max_drawdown_pct":  10.0,
		"coverage_rate":     0.8,
		"information_ratio": 0.5,
	})
	composite := bs.CompositeScore()
	if composite < 0 || composite > 1 {
		t.Errorf("composite score %f out of [0,1]", composite)
	}
	scores := bs.Score()
	for _, d := range scorecardDimensions {
		if scores[d] < 0 || scores[d] > 1 {
			t.Errorf("dimension %s score %f out of [0,1]", d, scores[d])
		}
	}
}

func TestBalancedScorecard_Trend(t *testing.T) {
	bs := NewBalancedScorecard(nil)
	// Push scores up over 10 updates.
	for i := 0; i < 10; i++ {
		bs.Update(map[string]float64{"sharpe_ratio": float64(i) * 0.5})
	}
	trend := bs.Trend(5)
	// returns dimension should be positive since sharpe_ratio was rising.
	if trend["returns"] < 0 {
		t.Errorf("expected positive trend for returns, got %.4f", trend["returns"])
	}
}

func TestBalancedScorecard_TrendInsufficientHistory(t *testing.T) {
	bs := NewBalancedScorecard(nil)
	trend := bs.Trend(5)
	for _, d := range scorecardDimensions {
		if trend[d] != 0.0 {
			t.Errorf("expected 0 trend with no history for %s, got %f", d, trend[d])
		}
	}
}

// ---------------------------------------------------------------------------
// AdaptiveReferenceTracker
// ---------------------------------------------------------------------------

func TestAdaptiveReferenceTracker_TrackingError_ZeroWithNoData(t *testing.T) {
	tracker := NewAdaptiveReferenceTracker([]string{"sharpe_ratio"}, 0.2, 1.5)
	if err := tracker.TrackingError(); err != 0.0 {
		t.Errorf("expected 0 tracking error with no data, got %f", err)
	}
}

func TestAdaptiveReferenceTracker_ControlAction_Proportional(t *testing.T) {
	tracker := NewAdaptiveReferenceTracker([]string{"sharpe_ratio"}, 0.5, 1.5)
	// Seed some data so EMA is set.
	tracker.Update(map[string]float64{"sharpe_ratio": 2.0})
	tracker.Update(map[string]float64{"sharpe_ratio": 2.0})
	tracker.Update(map[string]float64{"sharpe_ratio": 0.0}) // last is below EMA
	ctrl := tracker.ControlAction()
	// Control action should push toward EMA (positive correction expected).
	if ctrl["sharpe_ratio"] == 0.0 {
		t.Error("expected nonzero control action when last value differs from EMA")
	}
}

func TestAdaptiveReferenceTracker_ManualReference(t *testing.T) {
	tracker := NewAdaptiveReferenceTracker([]string{"x"}, 0.2, 1.5)
	tracker.SetReference(map[string][]float64{"x": {10.0, 11.0, 12.0}})
	tracker.Update(map[string]float64{"x": 9.0})
	ctrl := tracker.ControlAction()
	// K_p * (ref - cur) / uncertainty = 0.1 * (10 - 9) / ~1 ≈ 0.1
	if ctrl["x"] <= 0 {
		t.Errorf("expected positive control action toward manual reference, got %f", ctrl["x"])
	}
}

// ---------------------------------------------------------------------------
// HTNDecomposer
// ---------------------------------------------------------------------------

func TestHTNDecomposer_VictoriaMethods_ResearchCycle(t *testing.T) {
	htn := NewHTNDecomposer()
	htn.RegisterVictoriaMethods()
	tasks := htn.Decompose("research_cycle", map[string]any{})
	if len(tasks) == 0 {
		t.Fatal("expected subtasks for research_cycle, got none")
	}
	// First task should be ingest_data.
	if tasks[0].Name != "ingest_data" {
		t.Errorf("expected first task=ingest_data, got %s", tasks[0].Name)
	}
	// Each task must have a valid UUID-style ID.
	for _, task := range tasks {
		if task.TaskID == "" {
			t.Error("task missing TaskID")
		}
	}
}

func TestHTNDecomposer_RiskBreach_Precondition(t *testing.T) {
	htn := NewHTNDecomposer()
	htn.RegisterVictoriaMethods()
	// Precondition: max_drawdown_pct > 10.
	tasks := htn.Decompose("risk_breach", map[string]any{"max_drawdown_pct": 15.0})
	if len(tasks) == 0 {
		t.Fatal("expected tasks for risk_breach with high drawdown")
	}
	if tasks[0].Name != "run_risk_management" {
		t.Errorf("expected run_risk_management first, got %s", tasks[0].Name)
	}
}

func TestHTNDecomposer_RiskBreach_PreconditionNotMet(t *testing.T) {
	htn := NewHTNDecomposer()
	htn.RegisterVictoriaMethods()
	// Drawdown below threshold — precondition not met, fallback task.
	tasks := htn.Decompose("risk_breach", map[string]any{"max_drawdown_pct": 5.0})
	if len(tasks) != 1 {
		t.Fatalf("expected 1 fallback task, got %d", len(tasks))
	}
	if tasks[0].Name != "risk_breach" {
		t.Errorf("expected fallback task name=risk_breach, got %s", tasks[0].Name)
	}
}

func TestHTNDecomposer_UnknownGoal_Fallback(t *testing.T) {
	htn := NewHTNDecomposer()
	tasks := htn.Decompose("nonexistent_goal", map[string]any{})
	if len(tasks) != 1 || tasks[0].Name != "nonexistent_goal" {
		t.Errorf("expected single fallback task with goal name, got %v", tasks)
	}
}

// ---------------------------------------------------------------------------
// GoalArchitecture
// ---------------------------------------------------------------------------

func TestGoalArchitecture_Step_ApprovedCycle(t *testing.T) {
	ga := NewGoalArchitecture(nil)
	metrics := map[string]float64{
		"sharpe_ratio":      1.0,
		"max_drawdown_pct":  5.0,
		"max_position_pct":  10.0,
		"coverage_rate":     0.8,
		"error_rate":        0.1,
	}
	decision := ga.Step(context.Background(), metrics, nil, 1)
	if !decision.Approved {
		t.Errorf("expected approved=true, got violations: %v", decision.ConstraintViolations)
	}
	if decision.Cycle != 1 {
		t.Errorf("expected cycle=1, got %d", decision.Cycle)
	}
	if len(decision.Subtasks) == 0 {
		t.Error("expected subtasks in decision")
	}
}

func TestGoalArchitecture_Step_HardViolationBlocks(t *testing.T) {
	ga := NewGoalArchitecture(nil)
	metrics := map[string]float64{
		"max_drawdown_pct": 20.0, // exceeds 15 hard limit
	}
	decision := ga.Step(context.Background(), metrics, nil, 2)
	if decision.Approved {
		t.Error("expected approved=false for hard drawdown violation")
	}
}

func TestGoalArchitecture_InferGoal_RiskBreach(t *testing.T) {
	ga := NewGoalArchitecture(nil)
	metrics := map[string]float64{"max_drawdown_pct": 12.0}
	decision := ga.Step(context.Background(), metrics, nil, 0)
	// Even if not approved, the subtasks should be risk_breach tasks.
	if len(decision.Subtasks) == 0 {
		t.Error("expected subtasks for risk_breach goal")
	}
}

func TestGoalArchitecture_InferGoal_DataStale(t *testing.T) {
	ga := NewGoalArchitecture(nil)
	metrics := map[string]float64{}
	systemState := map[string]any{"data_stale": true}
	decision := ga.Step(context.Background(), metrics, systemState, 0)
	if len(decision.Subtasks) == 0 {
		t.Error("expected subtasks for data_stale goal")
	}
	// data_stale methods produce ingest_data as first task.
	if decision.Subtasks[0].Name != "ingest_data" {
		t.Errorf("expected ingest_data first for data_stale, got %s", decision.Subtasks[0].Name)
	}
}

func TestGoalArchitecture_SetReferenceTrajectory(t *testing.T) {
	ga := NewGoalArchitecture(nil)
	ga.SetReferenceTrajectory(map[string][]float64{
		"sharpe_ratio": {1.0, 1.2, 1.4},
	})
	// After setting a reference, tracking error should be computed from it.
	ga.Step(context.Background(), map[string]float64{"sharpe_ratio": 0.5}, nil, 0)
	// Just verify no panic.
}

// ---------------------------------------------------------------------------
// NashWelfareAggregator
// ---------------------------------------------------------------------------

func TestNashWelfareAggregator_Welfare_PositiveSurplus(t *testing.T) {
	n := NewNashWelfareAggregator([]string{"a", "b"}, nil)
	welfare := n.NashWelfare(map[string]float64{"a": 2.0, "b": 3.0})
	if welfare <= 0 {
		t.Errorf("expected positive Nash welfare, got %f", welfare)
	}
}

func TestNashWelfareAggregator_Welfare_ZeroSurplus(t *testing.T) {
	n := NewNashWelfareAggregator([]string{"a", "b"}, map[string]float64{"a": 2.0, "b": 3.0})
	// outcomes == disagreement_points → surplus = 0
	welfare := n.NashWelfare(map[string]float64{"a": 2.0, "b": 3.0})
	if welfare != 0 {
		t.Errorf("expected 0 welfare when surplus=0, got %f", welfare)
	}
}

func TestNashWelfareAggregator_OptimalWeights_ReturnsSimplex(t *testing.T) {
	n := NewNashWelfareAggregator([]string{"a", "b"}, nil)
	history := []map[string]float64{{"a": 1.0, "b": 2.0}, {"a": 1.5, "b": 1.5}}
	weights := n.OptimalWeights(history, 20)
	sum := 0.0
	for _, w := range weights {
		sum += w
	}
	if math.Abs(sum-1.0) > 1e-9 {
		t.Errorf("expected weights to sum to 1, got %f", sum)
	}
}

// ---------------------------------------------------------------------------
// sigmoid helper
// ---------------------------------------------------------------------------

func TestSigmoid_Bounds(t *testing.T) {
	cases := []struct {
		x    float64
		want float64
	}{
		{0, 0.5},
		{1000, 1.0},
		{-1000, 0.0},
	}
	for _, tc := range cases {
		got := sigmoid(tc.x)
		if math.Abs(got-tc.want) > 1e-6 {
			t.Errorf("sigmoid(%f) = %f, want %f", tc.x, got, tc.want)
		}
	}
}
