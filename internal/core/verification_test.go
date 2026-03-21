package core

import (
	"testing"
)

// ---------------------------------------------------------------------------
// PropertyGate
// ---------------------------------------------------------------------------

func TestPropertyGate_Pass(t *testing.T) {
	g := NewPropertyGate("test", func(ctx map[string]any) bool {
		v, _ := ctx["value"].(float64)
		return v > 0
	}, "value must be positive")
	result := g.Check(map[string]any{"value": 1.0})
	if !result.Passed() {
		t.Errorf("expected PASS, got %s: %s", result.Status, result.Evidence)
	}
}

func TestPropertyGate_Fail(t *testing.T) {
	g := NewPropertyGate("test", func(ctx map[string]any) bool {
		return false
	}, "always false")
	result := g.Check(map[string]any{})
	if !result.Failed() {
		t.Errorf("expected FAIL, got %s", result.Status)
	}
}

func TestPropertyGate_PanicRecovery(t *testing.T) {
	g := NewPropertyGate("panic_gate", func(ctx map[string]any) bool {
		panic("test panic")
	}, "panicking gate")
	result := g.Check(map[string]any{})
	if !result.Failed() {
		t.Error("expected FAIL on panic")
	}
	if result.Evidence == "" {
		t.Error("expected non-empty evidence on panic")
	}
}

// ---------------------------------------------------------------------------
// InvariantGate
// ---------------------------------------------------------------------------

func TestInvariantGate_Pass(t *testing.T) {
	g := NewInvariantGate("total_weight", func(ctx map[string]any) bool {
		w, _ := ctx["weight"].(float64)
		return w <= 1.0
	}, "total weight <= 1")
	result := g.Check(map[string]any{"weight": 0.9})
	if !result.Passed() {
		t.Errorf("expected PASS, got %s", result.Status)
	}
}

func TestInvariantGate_Fail(t *testing.T) {
	g := NewInvariantGate("total_weight", func(ctx map[string]any) bool {
		w, _ := ctx["weight"].(float64)
		return w <= 1.0
	}, "total weight <= 1")
	result := g.Check(map[string]any{"weight": 1.5})
	if !result.Failed() {
		t.Errorf("expected FAIL, got %s", result.Status)
	}
}

// ---------------------------------------------------------------------------
// ConsistencyGate
// ---------------------------------------------------------------------------

func TestConsistencyGate_Pass(t *testing.T) {
	g := NewConsistencyGate("signal_count", func(ctx map[string]any) bool {
		n, _ := ctx["n"].(int)
		return n > 0
	}, "at least one signal")
	result := g.Check(map[string]any{"n": 3})
	if !result.Passed() {
		t.Errorf("expected PASS, got %s", result.Status)
	}
}

// ---------------------------------------------------------------------------
// RegressionGate
// ---------------------------------------------------------------------------

func TestRegressionGate_Pass_NoRegression(t *testing.T) {
	g := NewRegressionGate("sharpe_reg", "sharpe_ratio", "maximize", 10.0)
	result := g.Check(map[string]any{
		"before": map[string]float64{"sharpe_ratio": 1.0},
		"after":  map[string]float64{"sharpe_ratio": 1.05},
	})
	if !result.Passed() {
		t.Errorf("expected PASS for improvement, got %s: %s", result.Status, result.Evidence)
	}
}

func TestRegressionGate_Fail_Regression(t *testing.T) {
	g := NewRegressionGate("sharpe_reg", "sharpe_ratio", "maximize", 10.0)
	result := g.Check(map[string]any{
		"before": map[string]float64{"sharpe_ratio": 1.0},
		"after":  map[string]float64{"sharpe_ratio": 0.8}, // -20% > threshold
	})
	if !result.Failed() {
		t.Errorf("expected FAIL for 20%% regression, got %s", result.Status)
	}
}

func TestRegressionGate_Warning_MissingMetric(t *testing.T) {
	g := NewRegressionGate("sharpe_reg", "sharpe_ratio", "maximize", 10.0)
	result := g.Check(map[string]any{
		"before": map[string]float64{},
		"after":  map[string]float64{},
	})
	if result.Status != GateWarning {
		t.Errorf("expected WARNING for missing metric, got %s", result.Status)
	}
}

func TestRegressionGate_Minimize_Direction(t *testing.T) {
	g := NewRegressionGate("latency_reg", "latency", "minimize", 10.0)
	// latency increased 20% — regression for minimize.
	result := g.Check(map[string]any{
		"before": map[string]float64{"latency": 100.0},
		"after":  map[string]float64{"latency": 125.0},
	})
	if !result.Failed() {
		t.Errorf("expected FAIL for latency increase, got %s", result.Status)
	}
}

func TestRegressionGate_Details_Present(t *testing.T) {
	g := NewRegressionGate("test", "metric", "maximize", 5.0)
	result := g.Check(map[string]any{
		"before": map[string]float64{"metric": 1.0},
		"after":  map[string]float64{"metric": 1.0},
	})
	if result.Details == nil {
		t.Error("expected Details map in result")
	}
	if _, ok := result.Details["pct_change"]; !ok {
		t.Error("expected pct_change in Details")
	}
}

// ---------------------------------------------------------------------------
// ConvergenceGate
// ---------------------------------------------------------------------------

func TestConvergenceGate_Pass_Converging(t *testing.T) {
	g := NewConvergenceGate("conv", "sharpe", 5, "maximize")
	history := []float64{0.5, 0.6, 0.7, 0.8, 0.9}
	result := g.Check(map[string]any{"history": history})
	if !result.Passed() {
		t.Errorf("expected PASS for monotonically increasing series, got %s: %s", result.Status, result.Evidence)
	}
}

func TestConvergenceGate_Warning_InsufficientHistory(t *testing.T) {
	g := NewConvergenceGate("conv", "sharpe", 5, "maximize")
	result := g.Check(map[string]any{"history": []float64{1.0, 2.0}})
	if result.Status != GateWarning {
		t.Errorf("expected WARNING for insufficient history, got %s", result.Status)
	}
}

func TestConvergenceGate_Fail_Oscillating(t *testing.T) {
	g := NewConvergenceGate("conv", "sharpe", 5, "maximize")
	// Wildly oscillating series.
	history := []float64{1.0, 10.0, 1.0, 10.0, 1.0}
	result := g.Check(map[string]any{"history": history})
	if !result.Failed() {
		t.Errorf("expected FAIL for oscillating series, got %s", result.Status)
	}
}

func TestConvergenceGate_Warning_FlatTrend(t *testing.T) {
	g := NewConvergenceGate("conv", "sharpe", 5, "maximize")
	// Slightly decreasing.
	history := []float64{1.0, 0.99, 0.98, 0.97, 0.96}
	result := g.Check(map[string]any{"history": history})
	if result.Status != GateWarning {
		t.Errorf("expected WARNING for diverging series, got %s: %s", result.Status, result.Evidence)
	}
}

// ---------------------------------------------------------------------------
// AndGate
// ---------------------------------------------------------------------------

func TestAndGate_AllPass(t *testing.T) {
	g := NewAndGate("and", []Gate{
		NewPropertyGate("p1", func(_ map[string]any) bool { return true }, "ok1"),
		NewPropertyGate("p2", func(_ map[string]any) bool { return true }, "ok2"),
	})
	result := g.Check(map[string]any{})
	if !result.Passed() {
		t.Errorf("expected PASS when all children pass, got %s", result.Status)
	}
}

func TestAndGate_OneFails(t *testing.T) {
	g := NewAndGate("and", []Gate{
		NewPropertyGate("p1", func(_ map[string]any) bool { return true }, "ok"),
		NewPropertyGate("p2", func(_ map[string]any) bool { return false }, "fail"),
	})
	result := g.Check(map[string]any{})
	if !result.Failed() {
		t.Errorf("expected FAIL when one child fails, got %s", result.Status)
	}
}

func TestAndGate_WarningPropagates(t *testing.T) {
	// A gate that returns WARNING.
	warningGate := NewRegressionGate("w", "missing_metric", "maximize", 10.0)
	passGate := NewPropertyGate("p", func(_ map[string]any) bool { return true }, "ok")
	g := NewAndGate("and", []Gate{passGate, warningGate})
	result := g.Check(map[string]any{
		"before": map[string]float64{},
		"after":  map[string]float64{},
	})
	if result.Status != GateWarning {
		t.Errorf("expected WARNING to propagate, got %s", result.Status)
	}
}

// ---------------------------------------------------------------------------
// OrGate
// ---------------------------------------------------------------------------

func TestOrGate_OnePass(t *testing.T) {
	g := NewOrGate("or", []Gate{
		NewPropertyGate("p1", func(_ map[string]any) bool { return false }, "fail"),
		NewPropertyGate("p2", func(_ map[string]any) bool { return true }, "ok"),
	})
	result := g.Check(map[string]any{})
	if !result.Passed() {
		t.Errorf("expected PASS when one child passes, got %s", result.Status)
	}
}

func TestOrGate_AllFail(t *testing.T) {
	g := NewOrGate("or", []Gate{
		NewPropertyGate("p1", func(_ map[string]any) bool { return false }, "f1"),
		NewPropertyGate("p2", func(_ map[string]any) bool { return false }, "f2"),
	})
	result := g.Check(map[string]any{})
	if !result.Failed() {
		t.Errorf("expected FAIL when all children fail, got %s", result.Status)
	}
}

// ---------------------------------------------------------------------------
// VerificationGateSystem
// ---------------------------------------------------------------------------

func TestVerificationGateSystem_AllPassed(t *testing.T) {
	vgs := NewVerificationGateSystem()
	vgs.Register(NewPropertyGate("p1", func(_ map[string]any) bool { return true }, "ok"))
	vgs.Register(NewPropertyGate("p2", func(_ map[string]any) bool { return true }, "ok"))
	results := vgs.RunAll(map[string]any{})
	if !vgs.AllPassed(results) {
		t.Error("expected all gates to pass")
	}
}

func TestVerificationGateSystem_Summary(t *testing.T) {
	vgs := NewVerificationGateSystem()
	vgs.Register(NewPropertyGate("pass_gate", func(_ map[string]any) bool { return true }, "ok"))
	vgs.Register(NewPropertyGate("fail_gate", func(_ map[string]any) bool { return false }, "nope"))
	vgs.Register(NewRegressionGate("warn_gate", "missing", "maximize", 10.0))

	results := vgs.RunAll(map[string]any{
		"before": map[string]float64{},
		"after":  map[string]float64{},
	})
	summary := vgs.Summary(results)

	if summary.Total != 3 {
		t.Errorf("expected total=3, got %d", summary.Total)
	}
	if summary.Passed != 1 {
		t.Errorf("expected passed=1, got %d", summary.Passed)
	}
	if summary.Failed != 1 {
		t.Errorf("expected failed=1, got %d", summary.Failed)
	}
	if summary.Warnings != 1 {
		t.Errorf("expected warnings=1, got %d", summary.Warnings)
	}
	if len(summary.Failures) != 1 {
		t.Errorf("expected 1 failure detail, got %d", len(summary.Failures))
	}
}
