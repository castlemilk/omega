package adversarial

// Three risk personas debate position sizing and produce a position_scale
// multiplier in [0, 1] to apply against the Kelly-optimal fraction.
//
// AggressivePersona — argues for deploying close to full Kelly.
// ConservativePersona — argues for 1/4 Kelly to preserve capital.
// NeutralPersona — mediates between the two using base-rate reasoning.
// RiskDebate.Resolve — runs all three, returns credibility-weighted average.

import (
	"fmt"
	"log/slog"
	"math"
)

// ---------------------------------------------------------------------------
// RiskContext
// ---------------------------------------------------------------------------

// RiskContext holds quantitative inputs for the risk persona debate.
type RiskContext struct {
	// CompositeSignal is the composite signal value in [-1, 1].
	CompositeSignal float64

	// ICShort is the information coefficient at short horizon.
	ICShort float64

	// VolRegime is the current volatility regime string.
	VolRegime string

	// RecentSharpe is the rolling Sharpe (30d). Negative = recent losses.
	RecentSharpe float64

	// NodeErrorRate is the NodeHealth error rate [0, 1].
	NodeErrorRate float64

	// ATLDistance is the distance from ATL as fraction [0, 1].
	ATLDistance float64

	// DebateConfidence is the confidence from DebateGate verdict [0, 1].
	// If provided, anchors the neutral persona's recommendation.
	DebateConfidence float64

	// MaxDrawdown is the maximum drawdown observed recently [0, 1].
	MaxDrawdown float64
}

// DefaultRiskContext returns a RiskContext with safe defaults.
func DefaultRiskContext() RiskContext {
	return RiskContext{
		VolRegime:        "normal_vol",
		ATLDistance:      0.5,
		DebateConfidence: 0.5,
	}
}

// ---------------------------------------------------------------------------
// PersonaVerdict
// ---------------------------------------------------------------------------

// PersonaVerdict is the output from a single persona's argument.
type PersonaVerdict struct {
	Persona          string
	RecommendedScale float64 // [0, 1]
	Credibility      float64 // [0, 1] — how credible this persona's argument is given context
	Reasoning        string
}

// ---------------------------------------------------------------------------
// AggressivePersona
// ---------------------------------------------------------------------------

// AggressivePersona argues for deploying close to full Kelly.
type AggressivePersona struct{}

// Argue evaluates the context and returns the aggressive persona's verdict.
func (p *AggressivePersona) Argue(ctx RiskContext) PersonaVerdict {
	var parts []string
	parts = append(parts, "Aggressive: momentum and IC support full deployment.")
	scale := 1.0
	credibility := 0.5

	// Boost on strong signal + IC
	if ctx.CompositeSignal > 0.3 {
		credibility += 0.15
		parts = append(parts, fmt.Sprintf("Signal is strongly bullish (%.3f)", ctx.CompositeSignal))
	}
	if ctx.ICShort > 0.05 {
		credibility += 0.15
		parts = append(parts, fmt.Sprintf("IC short is above threshold (%.4f)", ctx.ICShort))
	}
	if ctx.RecentSharpe > 0.5 {
		credibility += 0.10
		parts = append(parts, fmt.Sprintf("Recent Sharpe is positive (%.2f)", ctx.RecentSharpe))
	}
	if ctx.VolRegime == "low_vol" {
		credibility += 0.10
		parts = append(parts, "Low-vol regime supports larger positions")
	}

	// Reduce on risk factors
	if ctx.NodeErrorRate > 0.10 {
		scale *= 0.8
		credibility -= 0.15
		parts = append(parts, fmt.Sprintf("Conceding: node errors elevated (%.1f%%)", ctx.NodeErrorRate*100))
	}
	if ctx.RecentSharpe < -0.5 {
		scale *= 0.7
		credibility -= 0.15
		parts = append(parts, fmt.Sprintf("Conceding: recent Sharpe negative (%.2f)", ctx.RecentSharpe))
	}
	if ctx.VolRegime == "high_vol" {
		scale *= 0.85
		credibility -= 0.10
		parts = append(parts, "Slight reduction for high-vol regime")
	}
	if ctx.MaxDrawdown > 0.15 {
		scale *= 0.9
		credibility -= 0.10
		parts = append(parts, fmt.Sprintf("Recent drawdown %.1f%% — mild concession", ctx.MaxDrawdown*100))
	}

	scale = clamp01(scale)
	credibility = clamp01(credibility)

	reasoning := ""
	for i, p := range parts {
		if i > 0 {
			reasoning += " "
		}
		reasoning += p
	}

	slog.Debug("AggressivePersona", "scale", scale, "credibility", credibility)
	return PersonaVerdict{
		Persona:          "aggressive",
		RecommendedScale: scale,
		Credibility:      credibility,
		Reasoning:        reasoning,
	}
}

// ---------------------------------------------------------------------------
// ConservativePersona
// ---------------------------------------------------------------------------

// ConservativePersona argues for 1/4 Kelly to preserve capital.
type ConservativePersona struct{}

// Argue evaluates the context and returns the conservative persona's verdict.
func (p *ConservativePersona) Argue(ctx RiskContext) PersonaVerdict {
	var parts []string
	parts = append(parts, "Conservative: tail risk requires capital preservation at 1/4 Kelly.")
	scale := 0.25
	credibility := 0.5

	// Boost on risk factors
	if ctx.VolRegime == "high_vol" {
		credibility += 0.20
		parts = append(parts, "High-vol regime — fat-tail losses are more likely")
	}
	if ctx.RecentSharpe < -0.3 {
		credibility += 0.15
		parts = append(parts, fmt.Sprintf("Negative recent Sharpe (%.2f) signals edge erosion", ctx.RecentSharpe))
	}
	if ctx.MaxDrawdown > 0.10 {
		credibility += 0.15
		parts = append(parts, fmt.Sprintf("Recent drawdown %.1f%% — reduce to limit further loss", ctx.MaxDrawdown*100))
	}
	if ctx.NodeErrorRate > 0.05 {
		credibility += 0.10
		parts = append(parts, fmt.Sprintf("Elevated node error rate (%.1f%%) — signal quality degraded", ctx.NodeErrorRate*100))
	}

	// Increase scale when evidence is strong (concessions)
	if ctx.ICShort > 0.08 && ctx.CompositeSignal > 0.4 {
		scale = math.Min(0.35, scale+0.10)
		credibility -= 0.10
		parts = append(parts, "Conceding slightly: strong IC + signal (scale nudged to 0.35)")
	}
	if ctx.RecentSharpe > 1.0 {
		scale = math.Min(0.40, scale+0.10)
		credibility -= 0.10
		parts = append(parts, "Conceding: strong positive Sharpe (scale nudged up)")
	}

	scale = clamp01(scale)
	credibility = clamp01(credibility)

	reasoning := ""
	for i, p := range parts {
		if i > 0 {
			reasoning += " "
		}
		reasoning += p
	}

	slog.Debug("ConservativePersona", "scale", scale, "credibility", credibility)
	return PersonaVerdict{
		Persona:          "conservative",
		RecommendedScale: scale,
		Credibility:      credibility,
		Reasoning:        reasoning,
	}
}

// ---------------------------------------------------------------------------
// NeutralPersona
// ---------------------------------------------------------------------------

var regimeConfidence = map[string]float64{
	"low_vol":    1.0,
	"normal_vol": 0.8,
	"high_vol":   0.6,
}

const maxIC = 0.20 // IC at which full half-Kelly is recommended

// NeutralPersona mediates between Aggressive and Conservative using base-rate reasoning.
type NeutralPersona struct{}

// Mediate evaluates the context and the two extreme verdicts, returning a
// neutral verdict.
func (p *NeutralPersona) Mediate(aggressive, conservative PersonaVerdict, ctx RiskContext) PersonaVerdict {
	var parts []string
	parts = append(parts, "Neutral: base-rate position sizing via IC and regime.")

	// Step 1: IC → annualised info ratio proxy
	annualisedIR := ctx.ICShort * math.Sqrt(252)
	maxAnnualisedIR := maxIC * math.Sqrt(252)
	baseScale := clamp01(annualisedIR / maxAnnualisedIR)
	baseScale *= 0.5 // half-Kelly baseline

	// Step 2: regime confidence multiplier
	regConf, ok := regimeConfidence[ctx.VolRegime]
	if !ok {
		regConf = 0.8
	}
	baseScale *= regConf
	parts = append(parts, fmt.Sprintf("Base scale from IC (%.4f) and regime '%s' (%.1fx): %.3f",
		ctx.ICShort, ctx.VolRegime, regConf, baseScale))

	// Step 3: anchor to debate_confidence
	if ctx.DebateConfidence > 0 {
		baseScale = baseScale*0.6 + ctx.DebateConfidence*0.5*0.4
		parts = append(parts, fmt.Sprintf("Anchored to debate confidence (%.3f)", ctx.DebateConfidence))
	}

	// Step 4: error penalty
	errorPenalty := 1.0 - ctx.NodeErrorRate*0.5
	baseScale *= errorPenalty

	// Step 5: sanity-check against extreme personas
	baseScale = math.Max(conservative.RecommendedScale, math.Min(aggressive.RecommendedScale, baseScale))

	credibility := 0.50
	spread := math.Abs(aggressive.RecommendedScale - conservative.RecommendedScale)
	if spread > 0.3 {
		credibility += 0.10
		parts = append(parts, fmt.Sprintf("High spread between personas (%.2f) — neutral acts as tiebreaker", spread))
	}

	baseScale = clamp01(baseScale)
	credibility = clamp01(credibility)

	reasoning := ""
	for i, p := range parts {
		if i > 0 {
			reasoning += " "
		}
		reasoning += p
	}

	slog.Debug("NeutralPersona", "scale", baseScale, "credibility", credibility)
	return PersonaVerdict{
		Persona:          "neutral",
		RecommendedScale: baseScale,
		Credibility:      credibility,
		Reasoning:        reasoning,
	}
}

// ---------------------------------------------------------------------------
// RiskDebateResult
// ---------------------------------------------------------------------------

// RiskDebateResult is the full output from a RiskDebate session.
type RiskDebateResult struct {
	PositionScale       float64 // Final [0, 1] position scale multiplier
	AggressiveVerdict   PersonaVerdict
	ConservativeVerdict PersonaVerdict
	NeutralVerdict      PersonaVerdict
	Reasoning           string
}

// ---------------------------------------------------------------------------
// RiskDebate — orchestrator
// ---------------------------------------------------------------------------

// RiskDebate runs the three-persona risk debate and resolves to a position_scale.
type RiskDebate struct {
	aggressive   *AggressivePersona
	conservative *ConservativePersona
	neutral      *NeutralPersona
}

// NewRiskDebate creates a RiskDebate with optional custom personas.
func NewRiskDebate(aggressive *AggressivePersona, conservative *ConservativePersona, neutral *NeutralPersona) *RiskDebate {
	if aggressive == nil {
		aggressive = &AggressivePersona{}
	}
	if conservative == nil {
		conservative = &ConservativePersona{}
	}
	if neutral == nil {
		neutral = &NeutralPersona{}
	}
	return &RiskDebate{
		aggressive:   aggressive,
		conservative: conservative,
		neutral:      neutral,
	}
}

// Resolve runs the debate and computes a credibility-weighted position scale.
func (rd *RiskDebate) Resolve(ctx RiskContext) RiskDebateResult {
	aVerdict := rd.aggressive.Argue(ctx)
	cVerdict := rd.conservative.Argue(ctx)
	nVerdict := rd.neutral.Mediate(aVerdict, cVerdict, ctx)

	verdicts := []PersonaVerdict{aVerdict, cVerdict, nVerdict}
	var totalCredibility float64
	for _, v := range verdicts {
		totalCredibility += v.Credibility
	}

	var positionScale float64
	if totalCredibility < 1e-9 {
		// Fallback: equal weights
		for _, v := range verdicts {
			positionScale += v.RecommendedScale
		}
		positionScale /= float64(len(verdicts))
	} else {
		for _, v := range verdicts {
			positionScale += v.RecommendedScale * v.Credibility
		}
		positionScale /= totalCredibility
	}

	positionScale = clamp01(positionScale)

	reasoning := fmt.Sprintf(
		"RiskDebate resolved: scale=%.3f (aggressive=%.2fx%.2f, conservative=%.2fx%.2f, neutral=%.2fx%.2f)",
		positionScale,
		aVerdict.RecommendedScale, aVerdict.Credibility,
		cVerdict.RecommendedScale, cVerdict.Credibility,
		nVerdict.RecommendedScale, nVerdict.Credibility,
	)

	slog.Info("RiskDebate",
		"position_scale", positionScale,
		"aggressive_scale", aVerdict.RecommendedScale,
		"aggressive_cred", aVerdict.Credibility,
		"conservative_scale", cVerdict.RecommendedScale,
		"conservative_cred", cVerdict.Credibility,
		"neutral_scale", nVerdict.RecommendedScale,
		"neutral_cred", nVerdict.Credibility,
	)

	return RiskDebateResult{
		PositionScale:       positionScale,
		AggressiveVerdict:   aVerdict,
		ConservativeVerdict: cVerdict,
		NeutralVerdict:      nVerdict,
		Reasoning:           reasoning,
	}
}
