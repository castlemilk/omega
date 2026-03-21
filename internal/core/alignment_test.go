package core

import (
	"math"
	"testing"
)

// ---------------------------------------------------------------------------
// SafetyEnvelope
// ---------------------------------------------------------------------------

func TestSafetyEnvelope_Check_Clean(t *testing.T) {
	se := NewSafetyEnvelope(0.25, 0.15, 0.85, 0.5)
	// 4 assets each at 25% — exactly at the limit (not exceeding).
	portfolio := map[string]float64{"BTC": 0.25, "ETH": 0.25, "SOL": 0.25, "ADA": 0.25}
	ok, violations := se.Check(portfolio, 0.05, nil)
	if !ok {
		t.Errorf("expected clean portfolio, got violations: %v", violations)
	}
}

func TestSafetyEnvelope_Check_PositionConcentration(t *testing.T) {
	se := NewSafetyEnvelope(0.25, 0.15, 0.85, 0.5)
	// BTC takes 80% — exceeds 25% limit.
	portfolio := map[string]float64{"BTC": 0.8, "ETH": 0.2}
	ok, violations := se.Check(portfolio, 0.0, nil)
	if ok {
		t.Error("expected violation for position concentration")
	}
	if len(violations) == 0 {
		t.Fatal("expected at least 1 violation")
	}
}

func TestSafetyEnvelope_Check_Drawdown(t *testing.T) {
	se := NewSafetyEnvelope(0.25, 0.15, 0.85, 0.5)
	portfolio := map[string]float64{"BTC": 0.5, "ETH": 0.5}
	ok, violations := se.Check(portfolio, 0.20, nil)
	if ok {
		t.Error("expected violation for drawdown")
	}
	found := false
	for _, v := range violations {
		if len(v) > 8 && v[:8] == "drawdown" {
			found = true
		}
	}
	if !found {
		t.Errorf("expected drawdown violation, got: %v", violations)
	}
}

func TestSafetyEnvelope_Check_Correlation(t *testing.T) {
	se := NewSafetyEnvelope(0.25, 0.15, 0.85, 0.5)
	portfolio := map[string]float64{"BTC": 0.5, "ETH": 0.5}
	corrMatrix := map[string]map[string]float64{
		"BTC": {"ETH": 0.95}, // exceeds 0.85
		"ETH": {"BTC": 0.95},
	}
	ok, violations := se.Check(portfolio, 0.0, corrMatrix)
	if ok {
		t.Error("expected violation for high correlation")
	}
	if len(violations) == 0 {
		t.Fatal("expected correlation violation")
	}
}

func TestSafetyEnvelope_CheckImprovementMagnitude_OK(t *testing.T) {
	se := NewSafetyEnvelope(0.25, 0.15, 0.85, 0.5)
	ok, reason := se.CheckImprovementMagnitude(0.3)
	if !ok {
		t.Errorf("expected OK for delta=0.3, got reason: %s", reason)
	}
}

func TestSafetyEnvelope_CheckImprovementMagnitude_Exceeded(t *testing.T) {
	se := NewSafetyEnvelope(0.25, 0.15, 0.85, 0.5)
	ok, reason := se.CheckImprovementMagnitude(0.6)
	if ok {
		t.Error("expected failure for delta=0.6 > 0.5 limit")
	}
	if reason == "" {
		t.Error("expected non-empty reason")
	}
}

func TestSafetyEnvelope_Clamp_ReducesConcentration(t *testing.T) {
	se := NewSafetyEnvelope(0.25, 0.15, 0.85, 0.5)
	// 4 assets where one is dominant — clamp should bring it down.
	portfolio := map[string]float64{"BTC": 0.7, "ETH": 0.1, "SOL": 0.1, "ADA": 0.1}
	clamped := se.Clamp(portfolio)
	totalWeight := 0.7 + 0.1 + 0.1 + 0.1
	for asset, w := range clamped {
		pct := math.Abs(w) / totalWeight
		if pct > se.MaxPositionPct+1e-9 {
			t.Errorf("asset %s still exceeds max after clamping: pct=%.4f", asset, pct)
		}
	}
}

func TestSafetyEnvelope_Clamp_EmptyPortfolio(t *testing.T) {
	se := NewSafetyEnvelope(0.25, 0.15, 0.85, 0.5)
	clamped := se.Clamp(map[string]float64{})
	if len(clamped) != 0 {
		t.Error("expected empty result for empty portfolio")
	}
}

// ---------------------------------------------------------------------------
// ParetoEvaluator
// ---------------------------------------------------------------------------

func TestParetoEvaluator_Dominates(t *testing.T) {
	pe := &ParetoEvaluator{}
	objs := []string{"accuracy", "latency"}
	dirs := map[string]string{"accuracy": "maximize", "latency": "minimize"}

	a := map[string]float64{"accuracy": 0.9, "latency": 10.0}
	b := map[string]float64{"accuracy": 0.8, "latency": 15.0}

	if !pe.Dominates(a, b, objs, dirs) {
		t.Error("a should dominate b (better accuracy, lower latency)")
	}
	if pe.Dominates(b, a, objs, dirs) {
		t.Error("b should not dominate a")
	}
}

func TestParetoEvaluator_Dominates_NoDominance(t *testing.T) {
	pe := &ParetoEvaluator{}
	objs := []string{"accuracy", "latency"}
	dirs := map[string]string{"accuracy": "maximize", "latency": "minimize"}

	// a better on accuracy, b better on latency — neither dominates.
	a := map[string]float64{"accuracy": 0.9, "latency": 20.0}
	b := map[string]float64{"accuracy": 0.7, "latency": 5.0}

	if pe.Dominates(a, b, objs, dirs) {
		t.Error("a should not dominate b")
	}
	if pe.Dominates(b, a, objs, dirs) {
		t.Error("b should not dominate a")
	}
}

func TestParetoEvaluator_AssignRanks_FrontZero(t *testing.T) {
	pe := &ParetoEvaluator{}
	objs := []string{"score"}
	dirs := map[string]string{"score": "maximize"}

	pop := []map[string]float64{
		{"score": 1.0}, // rank 0
		{"score": 0.5}, // rank 1
		{"score": 0.0}, // rank 2
	}
	ranks := pe.AssignRanks(pop, objs, dirs)
	if ranks[0] != 0 {
		t.Errorf("expected rank 0 for best solution, got %d", ranks[0])
	}
	if ranks[1] != 1 {
		t.Errorf("expected rank 1 for middle, got %d", ranks[1])
	}
	if ranks[2] != 2 {
		t.Errorf("expected rank 2 for worst, got %d", ranks[2])
	}
}

func TestParetoEvaluator_AssignRanks_Empty(t *testing.T) {
	pe := &ParetoEvaluator{}
	ranks := pe.AssignRanks(nil, nil, nil)
	if ranks != nil {
		t.Error("expected nil ranks for empty population")
	}
}

func TestParetoEvaluator_CrowdingDistance_Boundaries(t *testing.T) {
	pe := &ParetoEvaluator{}
	front := []map[string]float64{
		{"x": 0.0},
		{"x": 0.5},
		{"x": 1.0},
	}
	cd := pe.CrowdingDistance(front, []string{"x"})
	if !math.IsInf(cd[0], 1) || !math.IsInf(cd[2], 1) {
		t.Error("expected boundary solutions to have infinite crowding distance")
	}
	if cd[1] == 0 || math.IsInf(cd[1], 1) {
		t.Errorf("expected finite nonzero crowding distance for middle, got %f", cd[1])
	}
}

func TestParetoEvaluator_NSGA2Sort_OrderedBestFirst(t *testing.T) {
	pe := &ParetoEvaluator{}
	objs := []string{"f"}
	dirs := map[string]string{"f": "maximize"}

	pop := []map[string]float64{
		{"f": 0.2},
		{"f": 1.0},
		{"f": 0.5},
	}
	order := pe.NSGA2Sort(pop, objs, dirs)
	// Best (index 1, f=1.0) should appear first.
	if order[0] != 1 {
		t.Errorf("expected best solution (index 1) first, got index %d", order[0])
	}
}

// ---------------------------------------------------------------------------
// OutcomeBasedScorer
// ---------------------------------------------------------------------------

func TestOutcomeBasedScorer_EmptyNodeScore(t *testing.T) {
	s := NewOutcomeBasedScorer()
	score := s.Score("unknown_node")
	if score != 0.0 {
		t.Errorf("expected 0 score for unknown node, got %f", score)
	}
}

func TestOutcomeBasedScorer_PerfectAccuracy(t *testing.T) {
	s := NewOutcomeBasedScorer()
	// Record 10 perfect predictions.
	for i := 0; i < 10; i++ {
		s.RecordOutcome("node1", 1.0, 1.0, 0.01)
	}
	score := s.Score("node1")
	// accuracy=1.0, sharpe is positive → score close to 1.
	if score < 0.5 {
		t.Errorf("expected high score for perfect accuracy, got %f", score)
	}
}

func TestOutcomeBasedScorer_RollingWindowCap(t *testing.T) {
	s := NewOutcomeBasedScorer()
	for i := 0; i < 100; i++ {
		s.RecordOutcome("node1", 1.0, 1.0, 0.01)
	}
	s.mu.RLock()
	n := len(s.history["node1"])
	s.mu.RUnlock()
	if n > maxOutcomeHistory {
		t.Errorf("expected history capped at %d, got %d", maxOutcomeHistory, n)
	}
}

func TestOutcomeBasedScorer_GetScores_AllTracked(t *testing.T) {
	s := NewOutcomeBasedScorer()
	s.RecordOutcome("n1", 1.0, 1.0, 0.01)
	s.RecordOutcome("n2", 0.5, 1.0, -0.01)
	scores := s.GetScores()
	if _, ok := scores["n1"]; !ok {
		t.Error("n1 missing from GetScores")
	}
	if _, ok := scores["n2"]; !ok {
		t.Error("n2 missing from GetScores")
	}
}

// ---------------------------------------------------------------------------
// AlignmentLayer
// ---------------------------------------------------------------------------

func TestAlignmentLayer_CheckImprovementCycle_Safe(t *testing.T) {
	al := NewAlignmentLayer(nil)
	portfolio := map[string]float64{"BTC": 0.25, "ETH": 0.25, "SOL": 0.25, "ADA": 0.25}
	nodeMetrics := map[string]map[string]float64{
		"node1": {"accuracy": 0.9, "latency": 10.0},
		"node2": {"accuracy": 0.7, "latency": 5.0},
	}
	decision := al.CheckImprovementCycle(nodeMetrics, map[string]float64{"drawdown": 0.1}, portfolio, 0)
	if !decision.Approved {
		t.Errorf("expected approved=true, violations: %v", decision.Violations)
	}
	if _, ok := decision.ParetoRanks["node1"]; !ok {
		t.Error("node1 missing from ParetoRanks")
	}
}

func TestAlignmentLayer_CheckImprovementCycle_Unsafe(t *testing.T) {
	al := NewAlignmentLayer(nil)
	portfolio := map[string]float64{"BTC": 1.0} // 100% concentration
	decision := al.CheckImprovementCycle(nil, map[string]float64{}, portfolio, 1)
	if decision.Approved {
		t.Error("expected approved=false for 100% concentration")
	}
}

func TestAlignmentLayer_RecordImprovementAttempt_WithinBudget(t *testing.T) {
	al := NewAlignmentLayer(nil)
	ok, reason := al.RecordImprovementAttempt("node1",
		map[string]float64{"a": 1.0, "b": 2.0},
		map[string]float64{"a": 1.1, "b": 2.1},
	)
	if !ok {
		t.Errorf("expected ok for small delta, got reason: %s", reason)
	}
}

func TestAlignmentLayer_RecordImprovementAttempt_ExceedsBudget(t *testing.T) {
	al := NewAlignmentLayer(nil)
	ok, _ := al.RecordImprovementAttempt("node1",
		map[string]float64{"a": 0.0},
		map[string]float64{"a": 2.0}, // delta=2.0 > 0.5 limit
	)
	if ok {
		t.Error("expected failure for large improvement delta")
	}
}

func TestAlignmentLayer_MagnitudeWarning_PropagatedToDecision(t *testing.T) {
	al := NewAlignmentLayer(nil)
	// Trigger a magnitude warning.
	al.RecordImprovementAttempt("node1",
		map[string]float64{"a": 0.0},
		map[string]float64{"a": 2.0},
	)
	portfolio := map[string]float64{"BTC": 0.25, "ETH": 0.25, "SOL": 0.25, "ADA": 0.25}
	decision := al.CheckImprovementCycle(nil, map[string]float64{}, portfolio, 0)
	if !decision.MagnitudeWarning {
		t.Error("expected MagnitudeWarning=true after exceeding magnitude budget")
	}
	if decision.ImprovementMagnitudeOK {
		t.Error("expected ImprovementMagnitudeOK=false after warning")
	}
}
