package eval

import (
	"context"
	"math"

	"github.com/benebsworth/omega/internal/core"
)

// ---------------------------------------------------------------------------
// Safety envelope harness
// ---------------------------------------------------------------------------

// SafetyHarness wraps SafetyEnvelope, ConstitutionalConstraints, BalancedScorecard,
// HTNDecomposer, and NashWelfareAggregator for deterministic integration tests.
type SafetyHarness struct {
	Envelope    *core.SafetyEnvelope
	Constraints *core.ConstitutionalConstraints
	Scorecard   *core.BalancedScorecard
	HTN         *core.HTNDecomposer
	Nash        *core.NashWelfareAggregator
}

// NewSafetyHarness creates a SafetyHarness with default configuration.
func NewSafetyHarness() *SafetyHarness {
	cc := &core.ConstitutionalConstraints{}
	cc.RegisterDefaults()

	nashObjectives := []string{"returns", "risk", "diversification"}
	disagreement := map[string]float64{
		"returns":        0.0,
		"risk":           0.0,
		"diversification": 0.0,
	}

	htn := core.NewHTNDecomposer()
	htn.RegisterVictoriaMethods()

	return &SafetyHarness{
		Envelope:    core.NewSafetyEnvelope(0.25, 0.15, 0.85, 0.5),
		Constraints: cc,
		Scorecard:   core.NewBalancedScorecard(nil),
		HTN:         htn,
		Nash:        core.NewNashWelfareAggregator(nashObjectives, disagreement),
	}
}

// ConcentratedPortfolio returns a portfolio where one asset dominates (>25%).
func ConcentratedPortfolio() map[string]float64 {
	return map[string]float64{
		"BTCUSDT": 0.70, // far above 25% limit
		"ETHUSDT": 0.15,
		"SOLUSDT": 0.15,
	}
}

// DiversifiedPortfolio returns a portfolio within all concentration limits.
func DiversifiedPortfolio() map[string]float64 {
	return map[string]float64{
		"BTCUSDT": 0.20,
		"ETHUSDT": 0.20,
		"SOLUSDT": 0.20,
		"BNBUSDT": 0.20,
		"ADAUSDT": 0.20,
	}
}

// ClampedPortfolio runs Clamp on the concentrated portfolio and returns the result.
func (h *SafetyHarness) ClampedPortfolio() map[string]float64 {
	return h.Envelope.Clamp(ConcentratedPortfolio())
}

// RunConstraintCheck evaluates the given metrics against constitutional constraints.
func (h *SafetyHarness) RunConstraintCheck(metrics map[string]float64) (bool, []core.ConstraintViolation) {
	return h.Constraints.Check(context.Background(), metrics)
}

// ---------------------------------------------------------------------------
// Verification gate harness
// ---------------------------------------------------------------------------

// VerificationHarness wraps VerificationGateSystem for integration tests.
type VerificationHarness struct {
	System *core.VerificationGateSystem
}

// NewVerificationHarness creates a harness pre-loaded with all 5 gate types.
func NewVerificationHarness() *VerificationHarness {
	vgs := core.NewVerificationGateSystem()

	// 1. PropertyGate — drawdown must be <= 0.15
	vgs.Register(core.NewPropertyGate(
		"drawdown_property",
		func(ctx map[string]any) bool {
			dd, _ := ctx["drawdown"].(float64)
			return dd <= 0.15
		},
		"drawdown <= 15%",
	))

	// 2. InvariantGate — position weights must sum to ≤ 1.0
	vgs.Register(core.NewInvariantGate(
		"weight_invariant",
		func(ctx map[string]any) bool {
			weights, ok := ctx["weights"].(map[string]float64)
			if !ok {
				return true // no weights → trivially holds
			}
			total := 0.0
			for _, w := range weights {
				total += math.Abs(w)
			}
			return total <= 1.001 // small epsilon for float rounding
		},
		"total position weight <= 1.0",
	))

	// 3. ConsistencyGate — sharpe and pnl must have consistent sign
	vgs.Register(core.NewConsistencyGate(
		"sharpe_pnl_consistency",
		func(ctx map[string]any) bool {
			sharpe, hasSharpe := ctx["sharpe"].(float64)
			pnl, hasPnl := ctx["pnl"].(float64)
			if !hasSharpe || !hasPnl {
				return true
			}
			// Both positive or both non-positive
			return (sharpe >= 0 && pnl >= 0) || (sharpe < 0 && pnl < 0)
		},
		"sharpe and pnl must have consistent sign",
	))

	// 4. RegressionGate — sharpe must not drop > 20%
	vgs.Register(core.NewRegressionGate(
		"sharpe_regression",
		"sharpe",
		"maximize",
		20.0,
	))

	// 5. ConvergenceGate — loss series must be converging (decreasing)
	vgs.Register(core.NewConvergenceGate(
		"loss_convergence",
		"loss",
		5,
		"minimize",
	))

	return &VerificationHarness{System: vgs}
}

// RunAll executes all gates against ctx and returns (passed, summary).
func (h *VerificationHarness) RunAll(ctx map[string]any) (bool, core.GateSummary) {
	results := h.System.RunAll(ctx)
	return h.System.AllPassed(results), h.System.Summary(results)
}

// GoodContext returns a context that should pass all 5 gates.
func GoodContext() map[string]any {
	return map[string]any{
		"drawdown": 0.05,
		"weights":  map[string]float64{"BTC": 0.3, "ETH": 0.3, "SOL": 0.3},
		"sharpe":   1.0,
		"pnl":      0.05,
		"before":   map[string]float64{"sharpe": 1.0},
		"after":    map[string]float64{"sharpe": 0.9}, // 10% drop < 20% threshold
		"history":  []float64{0.5, 0.4, 0.35, 0.3, 0.25},
	}
}

// BadDrawdownContext returns a context that violates the drawdown property gate.
func BadDrawdownContext() map[string]any {
	ctx := GoodContext()
	ctx["drawdown"] = 0.20 // exceeds 15%
	return ctx
}

// RegressionContext returns a context that fails the sharpe regression gate.
func RegressionContext() map[string]any {
	ctx := GoodContext()
	ctx["before"] = map[string]float64{"sharpe": 1.0}
	ctx["after"] = map[string]float64{"sharpe": 0.5} // 50% drop > 20% threshold
	return ctx
}
