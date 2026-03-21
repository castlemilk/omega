package adversarial

import (
	"math"
	"testing"
)

// ---------------------------------------------------------------------------
// bayesianUpdate
// ---------------------------------------------------------------------------

func TestBayesianUpdate_NeutralPrior_NeutralLR(t *testing.T) {
	// LR of 1.0 should leave posterior = prior
	posterior := bayesianUpdate(0.5, []float64{1.0})
	if math.Abs(posterior-0.5) > 1e-6 {
		t.Errorf("expected posterior ~0.5, got %.6f", posterior)
	}
}

func TestBayesianUpdate_StrongBullEvidence(t *testing.T) {
	posterior := bayesianUpdate(0.5, []float64{10.0}) // strong LR
	if posterior <= 0.5 {
		t.Errorf("expected posterior > 0.5 with strong bull LR, got %.4f", posterior)
	}
}

func TestBayesianUpdate_StrongBearEvidence(t *testing.T) {
	posterior := bayesianUpdate(0.5, []float64{0.1}) // weak LR → bearish
	if posterior >= 0.5 {
		t.Errorf("expected posterior < 0.5 with weak LR, got %.4f", posterior)
	}
}

func TestBayesianUpdate_StaysBounded(t *testing.T) {
	tests := []struct {
		prior float64
		lrs   []float64
	}{
		{0.5, []float64{1e10, 1e10}},
		{0.5, []float64{1e-10, 1e-10}},
		{0.01, []float64{1e10}},
		{0.99, []float64{1e-10}},
	}
	for _, tt := range tests {
		p := bayesianUpdate(tt.prior, tt.lrs)
		if p < 0 || p > 1 {
			t.Errorf("posterior %.6f out of [0,1] for prior=%.2f lrs=%v", p, tt.prior, tt.lrs)
		}
	}
}

// ---------------------------------------------------------------------------
// SignalContext
// ---------------------------------------------------------------------------

func TestSignalContext_CurrentRegimeIC_FallsBackToICShort(t *testing.T) {
	ctx := SignalContext{
		ICShort:   0.07,
		VolRegime: "unknown_regime",
		RegimeIC:  map[string]float64{"low_vol": 0.12},
	}
	if ctx.CurrentRegimeIC() != 0.07 {
		t.Errorf("expected fallback to ICShort=0.07, got %.4f", ctx.CurrentRegimeIC())
	}
}

func TestSignalContext_CurrentRegimeIC_UsesMapWhenPresent(t *testing.T) {
	ctx := SignalContext{
		ICShort:   0.07,
		VolRegime: "low_vol",
		RegimeIC:  map[string]float64{"low_vol": 0.12},
	}
	if ctx.CurrentRegimeIC() != 0.12 {
		t.Errorf("expected regime IC = 0.12, got %.4f", ctx.CurrentRegimeIC())
	}
}

// ---------------------------------------------------------------------------
// BullCaseBuilder
// ---------------------------------------------------------------------------

func TestBullCaseBuilder_StrongBullInputs(t *testing.T) {
	b := &BullCaseBuilder{}
	ctx := SignalContext{
		CompositeSignal: 0.8,
		ICShort:         0.12,
		ICLong:          0.12,
		VolRegime:       "low_vol",
		RegimeIC:        map[string]float64{"low_vol": 0.15},
		RecentSharpe:    1.5,
		NodeErrorRate:   0.0,
		ATLDistance:     0.3,
		RSI:             25.0,
	}
	bull := b.Build(ctx)
	if bull.Strength < 0.6 {
		t.Errorf("expected strong bull case > 0.6, got %.4f", bull.Strength)
	}
	if len(bull.Evidence) == 0 {
		t.Error("expected non-empty evidence")
	}
}

func TestBullCaseBuilder_BearInputs_WeakBull(t *testing.T) {
	b := &BullCaseBuilder{}
	ctx := SignalContext{
		CompositeSignal: -0.8,
		ICShort:         -0.02,
		VolRegime:       "high_vol",
		RecentSharpe:    -1.5,
		NodeErrorRate:   0.5,
		RSI:             80.0,
	}
	bull := b.Build(ctx)
	if bull.Strength > 0.3 {
		t.Errorf("expected weak bull case < 0.3 for bear inputs, got %.4f", bull.Strength)
	}
}

func TestBullCaseBuilder_StrengthBounded(t *testing.T) {
	b := &BullCaseBuilder{}
	for _, rsival := range []float64{10.0, 50.0, 90.0} {
		ctx := DefaultSignalContext()
		ctx.RSI = rsival
		bull := b.Build(ctx)
		if bull.Strength < 0 || bull.Strength > 1 {
			t.Errorf("bull strength %.4f out of [0,1] for RSI=%.0f", bull.Strength, rsival)
		}
	}
}

// ---------------------------------------------------------------------------
// BearCaseBuilder
// ---------------------------------------------------------------------------

func TestBearCaseBuilder_StrongBearInputs(t *testing.T) {
	b := &BearCaseBuilder{}
	ctx := SignalContext{
		CompositeSignal: -0.8,
		ICShort:         0.0,
		VolRegime:       "high_vol",
		RecentSharpe:    -1.5,
		NodeErrorRate:   0.4,
		RSI:             78.0,
	}
	bear := b.Build(ctx)
	if bear.Strength < 0.6 {
		t.Errorf("expected strong bear case > 0.6, got %.4f", bear.Strength)
	}
}

func TestBearCaseBuilder_BullInputs_WeakBear(t *testing.T) {
	b := &BearCaseBuilder{}
	ctx := SignalContext{
		CompositeSignal: 0.9,
		ICShort:         0.15,
		VolRegime:       "low_vol",
		RecentSharpe:    2.0,
		NodeErrorRate:   0.0,
		RSI:             25.0,
	}
	bear := b.Build(ctx)
	if bear.Strength > 0.4 {
		t.Errorf("expected weak bear case < 0.4 for bull inputs, got %.4f", bear.Strength)
	}
}

// ---------------------------------------------------------------------------
// Judge
// ---------------------------------------------------------------------------

func TestJudge_BuyVerdict(t *testing.T) {
	j := &Judge{}
	bull := BullCase{Strength: 0.90, Evidence: []string{"Strong signal"}, IndicatorContributions: map[string]float64{}}
	bear := BearCase{Strength: 0.10, Evidence: []string{}, IndicatorContributions: map[string]float64{}}
	ctx := DefaultSignalContext()
	verdict := j.Weigh(bull, bear, ctx)
	if verdict.Direction != DirectionBuy {
		t.Errorf("expected BUY, got %s (posterior=%.4f)", verdict.Direction, verdict.Posterior)
	}
	if verdict.Confidence <= 0 {
		t.Error("expected positive confidence for BUY")
	}
}

func TestJudge_SellVerdict(t *testing.T) {
	j := &Judge{}
	bull := BullCase{Strength: 0.10, Evidence: []string{}, IndicatorContributions: map[string]float64{}}
	bear := BearCase{Strength: 0.90, Evidence: []string{"Strong bear"}, IndicatorContributions: map[string]float64{}}
	ctx := DefaultSignalContext()
	verdict := j.Weigh(bull, bear, ctx)
	if verdict.Direction != DirectionSell {
		t.Errorf("expected SELL, got %s (posterior=%.4f)", verdict.Direction, verdict.Posterior)
	}
}

func TestJudge_HoldVerdict(t *testing.T) {
	j := &Judge{}
	bull := BullCase{Strength: 0.50, Evidence: []string{}, IndicatorContributions: map[string]float64{}}
	bear := BearCase{Strength: 0.50, Evidence: []string{}, IndicatorContributions: map[string]float64{}}
	ctx := DefaultSignalContext()
	verdict := j.Weigh(bull, bear, ctx)
	if verdict.Direction != DirectionHold {
		t.Errorf("expected HOLD, got %s (posterior=%.4f)", verdict.Direction, verdict.Posterior)
	}
}

func TestJudge_ConfidenceBounded(t *testing.T) {
	j := &Judge{}
	tests := []struct{ bull, bear float64 }{
		{0.99, 0.01},
		{0.01, 0.99},
		{0.50, 0.50},
	}
	for _, tt := range tests {
		bull := BullCase{Strength: tt.bull, IndicatorContributions: map[string]float64{}}
		bear := BearCase{Strength: tt.bear, IndicatorContributions: map[string]float64{}}
		verdict := j.Weigh(bull, bear, DefaultSignalContext())
		if verdict.Confidence < 0 || verdict.Confidence > 1 {
			t.Errorf("confidence %.4f out of [0,1] for bull=%.2f bear=%.2f", verdict.Confidence, tt.bull, tt.bear)
		}
		if verdict.PositionScale < 0 || verdict.PositionScale > 1 {
			t.Errorf("position_scale %.4f out of [0,1]", verdict.PositionScale)
		}
	}
}

// ---------------------------------------------------------------------------
// DebateGate
// ---------------------------------------------------------------------------

func TestDebateGate_Evaluate_BullishContext(t *testing.T) {
	gate := NewDebateGate(nil, nil, nil)
	ctx := SignalContext{
		CompositeSignal: 0.8,
		ICShort:         0.12,
		ICLong:          0.12,
		VolRegime:       "low_vol",
		RegimeIC:        map[string]float64{"low_vol": 0.15},
		RecentSharpe:    1.5,
		NodeErrorRate:   0.0,
		ATLDistance:     0.3,
		RSI:             25.0,
	}
	verdict := gate.Evaluate(ctx)
	if verdict.Direction != DirectionBuy {
		t.Errorf("expected BUY for strong bull context, got %s", verdict.Direction)
	}
}

func TestDebateGate_Evaluate_BearishContext(t *testing.T) {
	gate := NewDebateGate(nil, nil, nil)
	ctx := SignalContext{
		CompositeSignal: -0.8,
		ICShort:         0.0,
		VolRegime:       "high_vol",
		RecentSharpe:    -1.5,
		NodeErrorRate:   0.3,
		RSI:             78.0,
	}
	verdict := gate.Evaluate(ctx)
	if verdict.Direction != DirectionSell {
		t.Errorf("expected SELL for strong bear context, got %s (posterior=%.4f)", verdict.Direction, verdict.Posterior)
	}
}

// ---------------------------------------------------------------------------
// ActionFromVerdict
// ---------------------------------------------------------------------------

func TestActionFromVerdict_Proceed(t *testing.T) {
	verdict := DebateVerdict{Confidence: 0.8, PositionScale: 0.7}
	action, scale := ActionFromVerdict(verdict)
	if action != ActionProceed {
		t.Errorf("expected 'proceed', got '%s'", action)
	}
	if scale != 0.7 {
		t.Errorf("expected scale=0.7, got %.2f", scale)
	}
}

func TestActionFromVerdict_Reduce(t *testing.T) {
	verdict := DebateVerdict{Confidence: 0.5, PositionScale: 0.6}
	action, scale := ActionFromVerdict(verdict)
	if action != ActionReduce {
		t.Errorf("expected 'reduce', got '%s'", action)
	}
	if math.Abs(scale-0.3) > 1e-9 {
		t.Errorf("expected scale=0.3 (0.6*0.5), got %.4f", scale)
	}
}

func TestActionFromVerdict_Veto(t *testing.T) {
	verdict := DebateVerdict{Confidence: 0.2, PositionScale: 0.5}
	action, scale := ActionFromVerdict(verdict)
	if action != ActionVeto {
		t.Errorf("expected 'veto', got '%s'", action)
	}
	if scale != 0.0 {
		t.Errorf("expected scale=0, got %.2f", scale)
	}
}

// ---------------------------------------------------------------------------
// SignalContextFromMap
// ---------------------------------------------------------------------------

func TestSignalContextFromMap_BasicMapping(t *testing.T) {
	data := map[string]any{
		"composite_signal": 0.6,
		"ic_short":         0.08,
		"vol_regime":       "high_vol",
		"rsi":              65.0,
	}
	ctx := SignalContextFromMap(data)
	if ctx.CompositeSignal != 0.6 {
		t.Errorf("expected composite_signal=0.6, got %.2f", ctx.CompositeSignal)
	}
	if ctx.ICShort != 0.08 {
		t.Errorf("expected ic_short=0.08, got %.4f", ctx.ICShort)
	}
	if ctx.VolRegime != "high_vol" {
		t.Errorf("expected vol_regime='high_vol', got '%s'", ctx.VolRegime)
	}
	if ctx.RSI != 65.0 {
		t.Errorf("expected rsi=65.0, got %.1f", ctx.RSI)
	}
}

func TestSignalContextFromMap_UnknownKeysIgnored(t *testing.T) {
	data := map[string]any{
		"unknown_key": "ignored",
		"rsi":         42.0,
	}
	ctx := SignalContextFromMap(data)
	if ctx.RSI != 42.0 {
		t.Errorf("expected rsi=42.0, got %.1f", ctx.RSI)
	}
}
