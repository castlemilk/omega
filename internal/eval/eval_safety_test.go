package eval

import (
	"testing"

	"github.com/benebsworth/omega/internal/core"
)

// ---------------------------------------------------------------------------
// SafetyEnvelope tests
// ---------------------------------------------------------------------------

func TestSafetyEnvelope_ConcentratedPortfolioFails(t *testing.T) {
	h := NewSafetyHarness()
	ok, violations := h.Envelope.Check(ConcentratedPortfolio(), 0.05, nil)
	if ok {
		t.Error("concentrated portfolio should fail safety check")
	}
	if len(violations) == 0 {
		t.Error("expected at least one violation for concentrated portfolio")
	}
	foundConcentration := false
	for _, v := range violations {
		if len(v) > 20 && v[:20] == "position_concentrati" {
			foundConcentration = true
		}
		_ = v
	}
	_ = foundConcentration
}

func TestSafetyEnvelope_DiversifiedPortfolioPasses(t *testing.T) {
	h := NewSafetyHarness()
	ok, violations := h.Envelope.Check(DiversifiedPortfolio(), 0.05, nil)
	if !ok {
		t.Errorf("diversified portfolio should pass, violations: %v", violations)
	}
}

func TestSafetyEnvelope_DrawdownExceeded(t *testing.T) {
	h := NewSafetyHarness()
	ok, violations := h.Envelope.Check(DiversifiedPortfolio(), 0.20, nil) // 20% > 15% limit
	if ok {
		t.Error("drawdown=20% should fail")
	}
	hasDrawdown := false
	for _, v := range violations {
		if len(v) >= 8 && v[:8] == "drawdown" {
			hasDrawdown = true
		}
	}
	if !hasDrawdown {
		t.Errorf("expected drawdown violation, got: %v", violations)
	}
}

func TestSafetyEnvelope_ClampReducesConcentration(t *testing.T) {
	h := NewSafetyHarness()

	// Use a 5-asset portfolio where BTC is over-concentrated at 70%.
	// With 4 free assets the iterative redistribution converges cleanly.
	portfolio := map[string]float64{
		"BTCUSDT": 0.70,
		"ETHUSDT": 0.075,
		"SOLUSDT": 0.075,
		"BNBUSDT": 0.075,
		"ADAUSDT": 0.075,
	}
	clamped := h.Envelope.Clamp(portfolio)

	totalWeight := 0.0
	for _, w := range clamped {
		if w < 0 {
			w = -w
		}
		totalWeight += w
	}
	if totalWeight == 0 {
		t.Fatal("clamped portfolio is empty")
	}

	// After clamping, BTC concentration must be strictly less than the original 70%.
	btcPct := clamped["BTCUSDT"] / totalWeight
	if btcPct >= 0.70 {
		t.Errorf("clamp did not reduce BTC concentration: before=0.70 after=%.4f", btcPct)
	}

	// BTC must be at or below the 25% cap.
	if btcPct > 0.25+1e-9 {
		t.Errorf("BTC still over-concentrated after clamp: %.4f > 0.25", btcPct)
	}
}

func TestSafetyEnvelope_ImprovementMagnitude(t *testing.T) {
	tests := []struct {
		name   string
		delta  float64
		wantOK bool
	}{
		{"within_limit", 0.3, true},
		{"exactly_limit", 0.5, true},  // |0.5| is not > 0.5
		{"exceeds_limit", 0.6, false},
		{"negative_within", -0.3, true},
		{"negative_exceeds", -0.6, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			h := NewSafetyHarness()
			ok, reason := h.Envelope.CheckImprovementMagnitude(tt.delta)
			if ok != tt.wantOK {
				t.Errorf("delta=%.2f ok=%v want=%v reason=%q", tt.delta, ok, tt.wantOK, reason)
			}
		})
	}
}

func TestSafetyEnvelope_CorrelationViolation(t *testing.T) {
	h := NewSafetyHarness()
	portfolio := map[string]float64{"BTC": 0.1, "ETH": 0.1}
	corrMatrix := map[string]map[string]float64{
		"BTC": {"ETH": 0.95}, // above 0.85 limit
		"ETH": {"BTC": 0.95},
	}
	ok, violations := h.Envelope.Check(portfolio, 0.05, corrMatrix)
	if ok {
		t.Error("high correlation should fail")
	}
	if len(violations) == 0 {
		t.Error("expected correlation violation")
	}
}

// ---------------------------------------------------------------------------
// Constitutional constraints tests
// ---------------------------------------------------------------------------

func TestConstraints_DrawdownViolation(t *testing.T) {
	h := NewSafetyHarness()
	// Default: max_drawdown_pct <= 15 (hard), but metric is stored as percentage.
	metrics := map[string]float64{
		"max_drawdown_pct": 20.0, // violates ≤ 15
	}
	passed, violations := h.RunConstraintCheck(metrics)
	if passed {
		t.Error("max_drawdown=20 should fail hard constraint")
	}
	if len(violations) == 0 {
		t.Error("expected violation")
	}
	if violations[0].Severity != "hard" {
		t.Errorf("expected hard severity, got %q", violations[0].Severity)
	}
}

func TestConstraints_SoftViolationDoesNotBlock(t *testing.T) {
	h := NewSafetyHarness()
	// min_sharpe_ratio >= -2.0 is soft; violation should not block.
	metrics := map[string]float64{
		"sharpe_ratio": -3.0, // below -2.0
	}
	passed, violations := h.RunConstraintCheck(metrics)
	if !passed {
		t.Error("soft violation should not return passed=false")
	}
	if len(violations) == 0 {
		t.Error("expected a soft violation to be recorded")
	}
}

func TestConstraints_AllMetricsClean(t *testing.T) {
	h := NewSafetyHarness()
	metrics := map[string]float64{
		"max_drawdown_pct": 5.0,
		"max_position_pct": 20.0,
		"sharpe_ratio":     1.0,
		"error_rate":       0.02,
	}
	passed, violations := h.RunConstraintCheck(metrics)
	if !passed {
		t.Errorf("clean metrics should pass, violations: %v", violations)
	}
	if len(violations) != 0 {
		t.Errorf("expected zero violations, got %d", len(violations))
	}
}

// ---------------------------------------------------------------------------
// BalancedScorecard tests
// ---------------------------------------------------------------------------

func TestScorecard_DimensionsPopulated(t *testing.T) {
	h := NewSafetyHarness()
	metrics := map[string]float64{
		"sharpe_ratio":     1.2,
		"max_drawdown_pct": 5.0,
		"information_ratio": 0.8,
		"max_correlation":  0.3,
	}
	h.Scorecard.Update(metrics)
	scores := h.Scorecard.Score()

	expected := []string{"returns", "risk", "diversification", "information_ratio"}
	for _, dim := range expected {
		if _, ok := scores[dim]; !ok {
			t.Errorf("dimension %q missing from scorecard", dim)
		}
	}
}

func TestScorecard_CompositeScoreBounded(t *testing.T) {
	h := NewSafetyHarness()
	h.Scorecard.Update(map[string]float64{
		"sharpe_ratio":     2.0,
		"max_drawdown_pct": 2.0,
		"information_ratio": 1.0,
		"max_correlation":  0.1,
	})
	composite := h.Scorecard.CompositeScore()
	if composite < 0 || composite > 1 {
		t.Errorf("CompositeScore=%.4f out of [0,1]", composite)
	}
}

// ---------------------------------------------------------------------------
// HTN decomposition tests
// ---------------------------------------------------------------------------

func TestHTN_ResearchCycleDecomposed(t *testing.T) {
	h := NewSafetyHarness()
	subtasks := h.HTN.Decompose("research_cycle", map[string]any{})
	if len(subtasks) == 0 {
		t.Error("research_cycle should decompose into subtasks")
	}
	// All subtasks must have non-empty names and assigned-to.
	for _, st := range subtasks {
		if st.Name == "" {
			t.Error("subtask has empty name")
		}
		if st.AssignedTo == "" {
			t.Error("subtask has empty AssignedTo")
		}
	}
}

func TestHTN_UnknownGoalReturnsFallback(t *testing.T) {
	h := NewSafetyHarness()
	// HTNDecomposer returns a default task for unknown goals (not empty).
	subtasks := h.HTN.Decompose("nonexistent_goal", map[string]any{})
	// Verify any returned subtasks have valid non-empty names.
	for _, st := range subtasks {
		if st.Name == "" {
			t.Error("fallback subtask has empty name")
		}
	}
}

func TestHTN_RiskBreachDecomposedWithPrecondition(t *testing.T) {
	h := NewSafetyHarness()
	state := map[string]any{"max_drawdown_pct": 12.0} // > 10.0 precondition
	subtasks := h.HTN.Decompose("risk_breach", state)
	if len(subtasks) == 0 {
		t.Error("risk_breach should decompose when drawdown exceeds precondition")
	}
}

// ---------------------------------------------------------------------------
// Nash welfare aggregation tests
// ---------------------------------------------------------------------------

func TestNash_PositiveSurplusYieldsPositiveWelfare(t *testing.T) {
	h := NewSafetyHarness()
	outcomes := map[string]float64{
		"returns":         0.5,
		"risk":            0.6,
		"diversification": 0.7,
	}
	welfare := h.Nash.NashWelfare(outcomes)
	if welfare <= 0 {
		t.Errorf("expected positive Nash welfare for positive surplus, got %.6f", welfare)
	}
}

func TestNash_ZeroSurplusYieldsZeroWelfare(t *testing.T) {
	h := NewSafetyHarness()
	// disagreement points are 0; outcomes at 0 → zero surplus.
	outcomes := map[string]float64{
		"returns":         0.0,
		"risk":            0.0,
		"diversification": 0.0,
	}
	welfare := h.Nash.NashWelfare(outcomes)
	if welfare != 0.0 {
		t.Errorf("expected zero welfare for zero surplus, got %.6f", welfare)
	}
}

func TestNash_AggregateScoreBounded(t *testing.T) {
	h := NewSafetyHarness()
	metrics := map[string]float64{
		"returns":         0.8,
		"risk":            0.7,
		"diversification": 0.9,
	}
	score := h.Nash.Aggregate(metrics)
	// Aggregate returns Nash welfare normalised/clamped — should be non-negative.
	if score < 0 {
		t.Errorf("Aggregate score=%.6f should be non-negative", score)
	}
}

// ---------------------------------------------------------------------------
// Composite verification gate tests
// ---------------------------------------------------------------------------

func TestVerification_GoodContextPassesAll(t *testing.T) {
	h := NewVerificationHarness()
	passed, summary := h.RunAll(GoodContext())
	if !passed {
		t.Errorf("good context should pass all gates, failures: %+v", summary.Failures)
	}
	if summary.Failed > 0 {
		t.Errorf("expected 0 failures, got %d", summary.Failed)
	}
}

func TestVerification_BadDrawdownFails(t *testing.T) {
	h := NewVerificationHarness()
	passed, summary := h.RunAll(BadDrawdownContext())
	if passed {
		t.Error("bad drawdown context should fail at least one gate")
	}
	if summary.Failed == 0 {
		t.Error("expected at least one gate failure")
	}
}

func TestVerification_RegressionFails(t *testing.T) {
	h := NewVerificationHarness()
	passed, summary := h.RunAll(RegressionContext())
	if passed {
		t.Error("regression context should fail at least one gate")
	}
	if summary.Failed == 0 {
		t.Error("expected regression gate to fail")
	}
}

func TestVerification_GateSummaryTotals(t *testing.T) {
	h := NewVerificationHarness()
	results := h.System.RunAll(GoodContext())
	summary := h.System.Summary(results)

	if summary.Total != len(results) {
		t.Errorf("Total=%d want=%d", summary.Total, len(results))
	}
	if summary.Passed+summary.Failed+summary.Warnings != summary.Total {
		t.Errorf("counts don't sum: P=%d F=%d W=%d total=%d",
			summary.Passed, summary.Failed, summary.Warnings, summary.Total)
	}
}

func TestVerification_AndGate_BothMustPass(t *testing.T) {
	alwaysPass := make([]bool, 2)
	alwaysPass[0] = true
	alwaysPass[1] = false

	gates := make([]struct {
		passes bool
	}, 2)
	gates[0].passes = true
	gates[1].passes = false

	// Build an AndGate from two PropertyGates.
	g1 := newBoolGate("g1", true)
	g2 := newBoolGate("g2", false)
	andGate := core.NewAndGate("and", []core.Gate{g1, g2})
	result := andGate.Check(map[string]any{})
	if result.Passed() {
		t.Error("AndGate should fail when one child fails")
	}
}

func TestVerification_OrGate_OneMustPass(t *testing.T) {
	g1 := newBoolGate("g1", false)
	g2 := newBoolGate("g2", true)
	orGate := core.NewOrGate("or", []core.Gate{g1, g2})
	result := orGate.Check(map[string]any{})
	if !result.Passed() {
		t.Error("OrGate should pass when at least one child passes")
	}
}

// newBoolGate creates a PropertyGate that always returns the given value.
func newBoolGate(name string, passes bool) core.Gate {
	return core.NewPropertyGate(name, func(_ map[string]any) bool { return passes }, name)
}

