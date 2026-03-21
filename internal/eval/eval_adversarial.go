package eval

import (
	"context"

	"github.com/benebsworth/omega/internal/adversarial"
	"github.com/benebsworth/omega/internal/core"
)

// ---------------------------------------------------------------------------
// Ring 1: Ensemble disagreement
// ---------------------------------------------------------------------------

// Ring1Harness wraps EnsembleDisagreementDetector for deterministic eval.
type Ring1Harness struct {
	Detector *core.EnsembleDisagreementDetector
}

// NewRing1Harness creates a detector with the given disagreement threshold.
func NewRing1Harness(threshold float64) *Ring1Harness {
	return &Ring1Harness{Detector: core.NewEnsembleDisagreementDetector(threshold)}
}

// RegisterAndSubmit registers variantID and submits its output in one call.
func (h *Ring1Harness) RegisterAndSubmit(variantID string, output map[string]float64) {
	h.Detector.RegisterVariant(variantID, variantID+"_desc")
	h.Detector.SubmitOutput(variantID, output)
}

// RunCycle calls Detect and returns the DisagreementResult, then clears outputs.
func (h *Ring1Harness) RunCycle(ctx context.Context) core.DisagreementResult {
	result := h.Detector.Detect(ctx)
	h.Detector.Clear()
	return result
}

// ---------------------------------------------------------------------------
// Ring 2: Scenario stress testing
// ---------------------------------------------------------------------------

// Ring2Harness wraps ScenarioRunner and SimulationGate for deterministic eval.
type Ring2Harness struct {
	Runner *core.ScenarioRunner
	Gate   *core.SimulationGate
}

// NewRing2Harness creates a runner and gate with fixed seed=42 for reproducibility.
func NewRing2Harness(passThreshold float64) *Ring2Harness {
	// Deterministic strategy: pass signals through unchanged (scale by 0.5).
	strategy := core.StrategyCallable(func(signals map[string]float64, _ core.Scenario) map[string]float64 {
		out := make(map[string]float64, len(signals))
		for k, v := range signals {
			out[k] = v * 0.5
		}
		return out
	})
	runner := core.NewScenarioRunner(strategy, nil, passThreshold, 42, true)
	gate := core.NewSimulationGate(core.DefaultSimulationGateConfig())
	return &Ring2Harness{Runner: runner, Gate: gate}
}

// RunScenarios runs all provided scenarios against fixed base signals, returning
// both the RunResults and the SimulationReport.
func (h *Ring2Harness) RunScenarios(ctx context.Context, scenarios []core.Scenario, baseSignals map[string]float64) ([]core.RunResult, core.SimulationReport) {
	results := h.Runner.Run(ctx, scenarios, baseSignals)
	report := h.Gate.Evaluate("eval_strategy", results)
	return results, report
}

// ---------------------------------------------------------------------------
// Ring 3: Evolutionary tournament
// ---------------------------------------------------------------------------

// Ring3Harness wraps EvolutionaryTournament with a deterministic fitness function.
type Ring3Harness struct {
	Tournament *core.EvolutionaryTournament
	FitnessFn  core.FitnessFunc
}

// NewRing3Harness creates a tournament with fixed population and mutation rate.
// fitnessFn must be deterministic (e.g., based only on parameter values).
func NewRing3Harness(populationSize int, mutationRate float64, fitnessFn core.FitnessFunc) *Ring3Harness {
	t := core.NewEvolutionaryTournament(populationSize, mutationRate)
	if fitnessFn == nil {
		// Default: fitness = sum of all float64 params (deterministic).
		fitnessFn = func(params map[string]any) float64 {
			var score float64
			for _, v := range params {
				if f, ok := v.(float64); ok {
					score += f
				}
			}
			return score
		}
	}
	return &Ring3Harness{Tournament: t, FitnessFn: fitnessFn}
}

// Run initialises the population, runs the tournament, and returns the result.
func (h *Ring3Harness) Run(ctx context.Context, baseParams map[string]any) (core.TournamentResult, error) {
	h.Tournament.InitialisePopulation(baseParams)
	return h.Tournament.RunTournament(ctx, h.FitnessFn)
}

// ---------------------------------------------------------------------------
// Debate gate
// ---------------------------------------------------------------------------

// DebateHarness wraps DebateGate for eval.
type DebateHarness struct {
	Gate *adversarial.DebateGate
}

// NewDebateHarness creates a DebateGate with default bull/bear/judge.
func NewDebateHarness() *DebateHarness {
	return &DebateHarness{Gate: adversarial.NewDebateGate(nil, nil, nil)}
}

// Evaluate runs the debate and returns verdict and action.
func (h *DebateHarness) Evaluate(ctx adversarial.SignalContext) (adversarial.DebateVerdict, adversarial.DebateAction, float64) {
	verdict := h.Gate.Evaluate(ctx)
	action, scale := adversarial.ActionFromVerdict(verdict)
	return verdict, action, scale
}

// StrongBullContext returns a SignalContext with strongly bullish indicators.
func StrongBullContext() adversarial.SignalContext {
	ctx := adversarial.DefaultSignalContext()
	ctx.CompositeSignal = 0.8
	ctx.ICShort = 0.12
	ctx.ICLong = 0.10
	ctx.VolRegime = "low_vol"
	ctx.RecentSharpe = 1.5
	ctx.NodeErrorRate = 0.01
	ctx.RSI = 25.0 // oversold → bullish
	ctx.RegimeIC = map[string]float64{"low_vol": 0.12}
	return ctx
}

// StrongBearContext returns a SignalContext with strongly bearish indicators.
func StrongBearContext() adversarial.SignalContext {
	ctx := adversarial.DefaultSignalContext()
	ctx.CompositeSignal = -0.8
	ctx.ICShort = -0.05
	ctx.ICLong = -0.08
	ctx.VolRegime = "high_vol"
	ctx.RecentSharpe = -1.5
	ctx.NodeErrorRate = 0.25
	ctx.RSI = 80.0 // overbought → bearish
	ctx.RegimeIC = map[string]float64{"high_vol": -0.05}
	return ctx
}

// ---------------------------------------------------------------------------
// Risk persona debate
// ---------------------------------------------------------------------------

// RiskDebateHarness wraps RiskDebate for eval.
type RiskDebateHarness struct {
	Debate *adversarial.RiskDebate
}

// NewRiskDebateHarness creates a RiskDebate with default personas.
func NewRiskDebateHarness() *RiskDebateHarness {
	return &RiskDebateHarness{Debate: adversarial.NewRiskDebate(nil, nil, nil)}
}

// HighRiskContext returns a RiskContext favouring the conservative persona.
func HighRiskContext() adversarial.RiskContext {
	ctx := adversarial.DefaultRiskContext()
	ctx.VolRegime = "high_vol"
	ctx.RecentSharpe = -0.8
	ctx.NodeErrorRate = 0.20
	ctx.MaxDrawdown = 0.18
	ctx.CompositeSignal = -0.3
	ctx.DebateConfidence = 0.3
	return ctx
}

// LowRiskContext returns a RiskContext favouring the aggressive persona.
func LowRiskContext() adversarial.RiskContext {
	ctx := adversarial.DefaultRiskContext()
	ctx.VolRegime = "low_vol"
	ctx.RecentSharpe = 1.5
	ctx.NodeErrorRate = 0.01
	ctx.MaxDrawdown = 0.03
	ctx.CompositeSignal = 0.6
	ctx.ICShort = 0.10
	ctx.DebateConfidence = 0.8
	return ctx
}
