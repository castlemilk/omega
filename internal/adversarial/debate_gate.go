// Package adversarial implements the structured Bull/Bear debate for signal
// disagreement resolution and the three-persona risk debate for position sizing.
//
// The DebateGate routes signal disagreement through a deterministic
// quantitative debate — zero LLM calls. Fully reproducible given the same
// SignalContext inputs.
package adversarial

import (
	"fmt"
	"log/slog"
	"math"
)

// ---------------------------------------------------------------------------
// Direction
// ---------------------------------------------------------------------------

// Direction is the trade direction verdict from the debate.
type Direction string

const (
	DirectionBuy  Direction = "BUY"
	DirectionSell Direction = "SELL"
	DirectionHold Direction = "HOLD"
)

// ---------------------------------------------------------------------------
// SignalContext — input to the debate
// ---------------------------------------------------------------------------

// SignalContext holds all quantitative inputs the DebateGate uses to construct
// Bull/Bear cases.
type SignalContext struct {
	// CompositeSignal is the composite signal value, typically in [-1, 1].
	// Positive = bullish, negative = bearish.
	CompositeSignal float64

	// ICShort is the information coefficient at short horizon (e.g., 1-day).
	ICShort float64

	// ICLong is the IC at longer horizon (e.g., 5-day). Decay indicates signal
	// fade — a bearish factor.
	ICLong float64

	// VolRegime is the current volatility regime string, e.g., "high_vol",
	// "low_vol", "normal_vol".
	VolRegime string

	// RegimeIC is a per-regime IC map, e.g. {"high_vol": 0.04, "low_vol": 0.13}.
	RegimeIC map[string]float64

	// RecentSharpe is the rolling Sharpe ratio over recent window (30d).
	RecentSharpe float64

	// NodeErrorRate is the NodeHealth error rate [0, 1].
	NodeErrorRate float64

	// ATLDistance is the distance from all-time-low as fraction [0, 1].
	ATLDistance float64

	// RSI value [0, 100]. Overbought (>70) is bearish; oversold (<30) is bullish.
	RSI float64

	// Extra is an optional map for additional indicator pass-through.
	Extra map[string]any
}

// CurrentRegimeIC returns IC for the current vol regime, falling back to ICShort.
func (s SignalContext) CurrentRegimeIC() float64 {
	if s.RegimeIC != nil {
		if ic, ok := s.RegimeIC[s.VolRegime]; ok {
			return ic
		}
	}
	return s.ICShort
}

// DefaultSignalContext returns a SignalContext with safe defaults.
func DefaultSignalContext() SignalContext {
	return SignalContext{
		VolRegime:   "normal_vol",
		ATLDistance: 0.5,
		RSI:         50.0,
		RegimeIC:    map[string]float64{},
		Extra:       map[string]any{},
	}
}

// ---------------------------------------------------------------------------
// Cases
// ---------------------------------------------------------------------------

// BullCase holds arguments favouring a long/buy position.
type BullCase struct {
	Strength               float64            // [0, 1] aggregate bull evidence strength
	Evidence               []string           // human-readable evidence items
	IndicatorContributions map[string]float64 // indicator_name → contribution
}

// BearCase holds arguments favouring a short/neutral/sell position.
type BearCase struct {
	Strength               float64
	Evidence               []string
	IndicatorContributions map[string]float64
}

// ---------------------------------------------------------------------------
// DebateVerdict
// ---------------------------------------------------------------------------

// DebateVerdict is the output of the DebateGate judge.
type DebateVerdict struct {
	Direction      Direction
	Confidence     float64 // [0, 1] — how decisive the verdict is
	PositionScale  float64 // [0, 1] — fraction of Kelly-optimal to deploy
	Reasoning      string
	DissentStrength float64 // losing side's case strength
	BullStrength   float64
	BearStrength   float64
	Posterior      float64 // Bayesian posterior P(bullish | evidence)
}

// ---------------------------------------------------------------------------
// Bayesian update (pure math, no external deps)
// ---------------------------------------------------------------------------

// bayesianUpdate performs a Bayesian update in log-odds space.
//
//	LO_posterior = log(prior/(1-prior)) + Σ log(LR_i)
//
// Returns the posterior probability.
func bayesianUpdate(prior float64, likelihoodRatios []float64) float64 {
	const eps = 1e-15
	p := math.Max(eps, math.Min(1-eps, prior))
	logOdds := math.Log(p / (1 - p))
	for _, lr := range likelihoodRatios {
		if lr > 0 {
			logOdds += math.Log(lr)
		}
	}
	return 1.0 / (1.0 + math.Exp(-logOdds))
}

func clamp01(v float64) float64 {
	return math.Max(0.0, math.Min(1.0, v))
}

// ---------------------------------------------------------------------------
// BullCaseBuilder
// ---------------------------------------------------------------------------

// bullWeights are the indicator weights for the bull case.
var bullWeights = map[string]float64{
	"composite_signal": 0.35,
	"ic_quality":       0.25,
	"regime_alignment": 0.20,
	"sharpe":           0.10,
	"rsi":              0.10,
}

// BullCaseBuilder constructs the strongest quantitative case for going long.
type BullCaseBuilder struct{}

// Build evaluates the SignalContext and returns a BullCase.
func (b *BullCaseBuilder) Build(ctx SignalContext) BullCase {
	contributions := make(map[string]float64, 5)
	var evidence []string

	// 1. Composite signal direction [0, 1] (normalise from [-1, 1])
	sigNorm := (ctx.CompositeSignal + 1.0) / 2.0
	contributions["composite_signal"] = clamp01(sigNorm)
	if ctx.CompositeSignal > 0.3 {
		evidence = append(evidence, fmt.Sprintf("Composite signal strongly bullish: %.3f", ctx.CompositeSignal))
	} else if ctx.CompositeSignal > 0 {
		evidence = append(evidence, fmt.Sprintf("Composite signal mildly bullish: %.3f", ctx.CompositeSignal))
	}

	// 2. IC quality — higher short IC and low decay are bullish
	icQuality := clamp01(ctx.ICShort * 5.0) // scale: 0.20 IC → 1.0
	icDecay := 0.0
	if ctx.ICShort > 0 && ctx.ICLong < ctx.ICShort {
		icDecay = (ctx.ICShort - ctx.ICLong) / math.Max(ctx.ICShort, 1e-9)
	}
	icQuality *= (1.0 - 0.5*icDecay)
	contributions["ic_quality"] = clamp01(icQuality)
	if ctx.ICShort > 0.05 {
		evidence = append(evidence, fmt.Sprintf("IC at short horizon is positive: %.4f", ctx.ICShort))
	}
	if icDecay < 0.2 && ctx.ICLong > 0 {
		evidence = append(evidence, fmt.Sprintf("IC decay is low (%.1f%%), signal persists to long horizon", icDecay*100))
	}

	// 3. Regime alignment
	regimeIC := ctx.CurrentRegimeIC()
	regimeScore := clamp01(regimeIC * 10.0) // scale: 0.10 IC → 1.0
	contributions["regime_alignment"] = regimeScore
	if regimeIC > 0.05 {
		evidence = append(evidence, fmt.Sprintf("Regime '%s' has positive IC: %.4f", ctx.VolRegime, regimeIC))
	}

	// 4. Sharpe — map [-2, +2] → [0, 1]
	sharpeNorm := (ctx.RecentSharpe + 2.0) / 4.0
	contributions["sharpe"] = clamp01(sharpeNorm)
	if ctx.RecentSharpe > 0.5 {
		evidence = append(evidence, fmt.Sprintf("Recent Sharpe ratio is positive: %.2f", ctx.RecentSharpe))
	}

	// 5. RSI — oversold territory is bullish
	var rsiScore float64
	switch {
	case ctx.RSI < 30:
		rsiScore = 1.0
		evidence = append(evidence, fmt.Sprintf("RSI oversold (%.1f) — mean-reversion opportunity", ctx.RSI))
	case ctx.RSI < 50:
		rsiScore = (50.0-ctx.RSI)/50.0*0.5 + 0.5
	case ctx.RSI < 70:
		rsiScore = 1.0 - (ctx.RSI-50.0)/40.0
	default:
		rsiScore = 0.0
	}
	contributions["rsi"] = clamp01(rsiScore)

	// Error penalty
	errorPenalty := 1.0 - ctx.NodeErrorRate
	var strength float64
	for k, w := range bullWeights {
		strength += w * contributions[k]
	}
	strength *= errorPenalty

	if ctx.NodeErrorRate > 0.1 {
		evidence = append(evidence, fmt.Sprintf("WARNING: node error rate is elevated (%.1f%%), bull case confidence reduced", ctx.NodeErrorRate*100))
	}

	strength = clamp01(strength)
	slog.Debug("BullCase built", "strength", strength, "contributions", contributions)
	return BullCase{
		Strength:               strength,
		Evidence:               evidence,
		IndicatorContributions: contributions,
	}
}

// ---------------------------------------------------------------------------
// BearCaseBuilder
// ---------------------------------------------------------------------------

var bearWeights = map[string]float64{
	"composite_signal": 0.35,
	"ic_quality":       0.20,
	"regime_mismatch":  0.20,
	"sharpe":           0.15,
	"rsi":              0.10,
}

// BearCaseBuilder constructs the strongest quantitative case for going short / staying flat.
type BearCaseBuilder struct{}

// Build evaluates the SignalContext and returns a BearCase.
func (b *BearCaseBuilder) Build(ctx SignalContext) BearCase {
	contributions := make(map[string]float64, 5)
	var evidence []string

	// 1. Composite signal — negative is bearish
	sigNormBear := 1.0 - (ctx.CompositeSignal+1.0)/2.0
	contributions["composite_signal"] = clamp01(sigNormBear)
	if ctx.CompositeSignal < -0.3 {
		evidence = append(evidence, fmt.Sprintf("Composite signal strongly bearish: %.3f", ctx.CompositeSignal))
	} else if ctx.CompositeSignal < 0 {
		evidence = append(evidence, fmt.Sprintf("Composite signal mildly bearish: %.3f", ctx.CompositeSignal))
	}

	// 2. IC quality — low or negative IC is bearish
	icBear := 1.0 - clamp01(ctx.ICShort*5.0)
	icDecay := 0.0
	if ctx.ICShort > 0 && ctx.ICLong < ctx.ICShort {
		icDecay = (ctx.ICShort - ctx.ICLong) / math.Max(ctx.ICShort, 1e-9)
	}
	icBear = math.Min(1.0, icBear+0.3*icDecay)
	contributions["ic_quality"] = clamp01(icBear)
	if ctx.ICShort < 0.02 {
		evidence = append(evidence, fmt.Sprintf("IC at short horizon is near-zero or negative: %.4f", ctx.ICShort))
	}
	if icDecay > 0.3 {
		evidence = append(evidence, fmt.Sprintf("Significant IC decay (%.1f%%) — signal fades at long horizon", icDecay*100))
	}

	// 3. Regime mismatch
	regimeIC := ctx.CurrentRegimeIC()
	regimeMismatch := 1.0 - clamp01(regimeIC*10.0)
	contributions["regime_mismatch"] = regimeMismatch
	if regimeIC < 0.02 {
		evidence = append(evidence, fmt.Sprintf("Regime '%s' has near-zero IC: %.4f", ctx.VolRegime, regimeIC))
	}
	if ctx.VolRegime == "high_vol" && ctx.RecentSharpe < 0 {
		evidence = append(evidence, "High volatility regime + negative Sharpe — elevated drawdown risk")
	}

	// 4. Sharpe — negative Sharpe is bearish
	sharpeBear := 1.0 - (ctx.RecentSharpe+2.0)/4.0
	contributions["sharpe"] = clamp01(sharpeBear)
	if ctx.RecentSharpe < -0.5 {
		evidence = append(evidence, fmt.Sprintf("Recent Sharpe ratio is significantly negative: %.2f", ctx.RecentSharpe))
	}

	// 5. RSI — overbought is bearish
	var rsiBear float64
	switch {
	case ctx.RSI > 70:
		rsiBear = 1.0
		evidence = append(evidence, fmt.Sprintf("RSI overbought (%.1f) — reversion risk elevated", ctx.RSI))
	case ctx.RSI > 50:
		rsiBear = (ctx.RSI-50.0)/50.0*0.5 + 0.5
	case ctx.RSI > 30:
		rsiBear = 1.0 - (50.0-ctx.RSI)/50.0*0.5
	default:
		rsiBear = 0.0
	}
	contributions["rsi"] = clamp01(rsiBear)

	// High node error strengthens bear case
	errorBoost := 1.0 + ctx.NodeErrorRate*0.3
	var strength float64
	for k, w := range bearWeights {
		strength += w * contributions[k]
	}
	strength *= errorBoost

	if ctx.NodeErrorRate > 0.1 {
		evidence = append(evidence, fmt.Sprintf("Elevated node error rate (%.1f%%) — signal reliability impaired", ctx.NodeErrorRate*100))
	}

	strength = clamp01(strength)
	slog.Debug("BearCase built", "strength", strength, "contributions", contributions)
	return BearCase{
		Strength:               strength,
		Evidence:               evidence,
		IndicatorContributions: contributions,
	}
}

// ---------------------------------------------------------------------------
// Judge
// ---------------------------------------------------------------------------

const (
	buyThreshold  = 0.60
	sellThreshold = 0.40
)

// Judge weighs Bull and Bear cases using Bayesian inference and produces a verdict.
type Judge struct{}

// Weigh runs the Bayesian synthesis and returns a DebateVerdict.
func (j *Judge) Weigh(bull BullCase, bear BearCase, _ SignalContext) DebateVerdict {
	const eps = 1e-6
	bullS := math.Max(eps, math.Min(1.0-eps, bull.Strength))
	bearS := math.Max(eps, math.Min(1.0-eps, bear.Strength))

	lrBull := bullS / (1.0 - bullS)       // LR favouring bull
	lrBearInv := (1.0 - bearS) / bearS    // LR diminishing bear

	posterior := bayesianUpdate(0.5, []float64{lrBull, lrBearInv})

	var direction Direction
	var confidence float64
	var dissentStrength float64
	var winningEvidence []string

	switch {
	case posterior >= buyThreshold:
		direction = DirectionBuy
		confidence = (posterior - 0.5) * 2.0
		dissentStrength = bear.Strength
		winningEvidence = bull.Evidence
	case posterior <= sellThreshold:
		direction = DirectionSell
		confidence = (0.5 - posterior) * 2.0
		dissentStrength = bull.Strength
		winningEvidence = bear.Evidence
	default:
		direction = DirectionHold
		confidence = math.Max(0.0, 1.0-math.Abs(posterior-0.5)*4.0)
		if bull.Strength > bear.Strength {
			dissentStrength = bull.Strength
		} else {
			dissentStrength = bear.Strength
		}
		winningEvidence = []string{"Bull and bear cases are roughly balanced — holding is prudent"}
	}

	confidence = clamp01(confidence)
	positionScale := clamp01(confidence)

	// Build reasoning
	n := 3
	if len(winningEvidence) < n {
		n = len(winningEvidence)
	}
	topEvidence := winningEvidence[:n]
	reasoning := fmt.Sprintf("Direction: %s (posterior=%.3f)", direction, posterior)
	if len(topEvidence) > 0 {
		reasoning += ". Decisive evidence: "
		for i, e := range topEvidence {
			if i > 0 {
				reasoning += "; "
			}
			reasoning += e
		}
	}
	reasoning += fmt.Sprintf(". Dissent strength (losing side): %.3f", dissentStrength)

	slog.Info("Judge verdict",
		"posterior", posterior,
		"direction", direction,
		"confidence", confidence,
		"position_scale", positionScale,
		"dissent", dissentStrength,
	)

	return DebateVerdict{
		Direction:       direction,
		Confidence:      confidence,
		PositionScale:   positionScale,
		Reasoning:       reasoning,
		DissentStrength: dissentStrength,
		BullStrength:    bull.Strength,
		BearStrength:    bear.Strength,
		Posterior:       posterior,
	}
}

// ---------------------------------------------------------------------------
// DebateGate — public API
// ---------------------------------------------------------------------------

// DebateGate routes signal disagreement through a structured Bull/Bear debate.
type DebateGate struct {
	bull  *BullCaseBuilder
	bear  *BearCaseBuilder
	judge *Judge
}

// NewDebateGate creates a DebateGate with optional custom builders and judge.
func NewDebateGate(bull *BullCaseBuilder, bear *BearCaseBuilder, judge *Judge) *DebateGate {
	if bull == nil {
		bull = &BullCaseBuilder{}
	}
	if bear == nil {
		bear = &BearCaseBuilder{}
	}
	if judge == nil {
		judge = &Judge{}
	}
	return &DebateGate{bull: bull, bear: bear, judge: judge}
}

// Evaluate runs the full Bull/Bear debate and returns a verdict.
func (dg *DebateGate) Evaluate(ctx SignalContext) DebateVerdict {
	bull := dg.bull.Build(ctx)
	bear := dg.bear.Build(ctx)
	verdict := dg.judge.Weigh(bull, bear, ctx)

	slog.Info("DebateGate",
		"bull_strength", bull.Strength,
		"bear_strength", bear.Strength,
		"direction", verdict.Direction,
		"confidence", verdict.Confidence,
		"position_scale", verdict.PositionScale,
	)
	return verdict
}

// DebateAction represents the recommended action from a verdict.
type DebateAction string

const (
	ActionProceed DebateAction = "proceed"
	ActionReduce  DebateAction = "reduce"
	ActionVeto    DebateAction = "veto"
)

// ActionFromVerdict maps a DebateVerdict to a simple (action, position_scale) pair.
//
//   - confidence > 0.6  → ("proceed", position_scale)
//   - 0.4 ≤ confidence ≤ 0.6  → ("reduce", position_scale * 0.5)
//   - confidence < 0.4  → ("veto", 0.0)
func ActionFromVerdict(verdict DebateVerdict) (DebateAction, float64) {
	switch {
	case verdict.Confidence > 0.6:
		return ActionProceed, verdict.PositionScale
	case verdict.Confidence >= 0.4:
		return ActionReduce, verdict.PositionScale * 0.5
	default:
		return ActionVeto, 0.0
	}
}

// SignalContextFromMap builds a SignalContext from a raw map, ignoring unknown keys.
func SignalContextFromMap(data map[string]any) SignalContext {
	ctx := DefaultSignalContext()
	if v, ok := data["composite_signal"]; ok {
		if f, ok := v.(float64); ok {
			ctx.CompositeSignal = f
		}
	}
	if v, ok := data["ic_short"]; ok {
		if f, ok := v.(float64); ok {
			ctx.ICShort = f
		}
	}
	if v, ok := data["ic_long"]; ok {
		if f, ok := v.(float64); ok {
			ctx.ICLong = f
		}
	}
	if v, ok := data["vol_regime"]; ok {
		if s, ok := v.(string); ok {
			ctx.VolRegime = s
		}
	}
	if v, ok := data["regime_ic"]; ok {
		if m, ok := v.(map[string]float64); ok {
			ctx.RegimeIC = m
		}
	}
	if v, ok := data["recent_sharpe"]; ok {
		if f, ok := v.(float64); ok {
			ctx.RecentSharpe = f
		}
	}
	if v, ok := data["node_error_rate"]; ok {
		if f, ok := v.(float64); ok {
			ctx.NodeErrorRate = f
		}
	}
	if v, ok := data["atl_distance"]; ok {
		if f, ok := v.(float64); ok {
			ctx.ATLDistance = f
		}
	}
	if v, ok := data["rsi"]; ok {
		if f, ok := v.(float64); ok {
			ctx.RSI = f
		}
	}
	return ctx
}
