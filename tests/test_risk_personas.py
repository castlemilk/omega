"""Tests for omega.adversarial.risk_personas."""

from __future__ import annotations

import pytest

from omega.adversarial.risk_personas import (
    AggressivePersona,
    ConservativePersona,
    NeutralPersona,
    RiskContext,
    RiskDebate,
    RiskDebateResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def high_confidence_ctx() -> RiskContext:
    """High-signal, low-risk context — should favour larger positions."""
    return RiskContext(
        composite_signal=0.70,
        ic_short=0.10,
        vol_regime="low_vol",
        recent_sharpe=1.5,
        node_error_rate=0.01,
        atl_distance=0.6,
        debate_confidence=0.75,
        max_drawdown=0.03,
    )


def risky_ctx() -> RiskContext:
    """High-vol, negative-Sharpe context — should favour smaller positions."""
    return RiskContext(
        composite_signal=-0.30,
        ic_short=0.01,
        vol_regime="high_vol",
        recent_sharpe=-1.0,
        node_error_rate=0.20,
        atl_distance=0.1,
        debate_confidence=0.25,
        max_drawdown=0.20,
    )


def neutral_ctx() -> RiskContext:
    """Neutral, balanced context."""
    return RiskContext(
        composite_signal=0.10,
        ic_short=0.05,
        vol_regime="normal_vol",
        recent_sharpe=0.3,
        node_error_rate=0.05,
        atl_distance=0.5,
        debate_confidence=0.50,
        max_drawdown=0.05,
    )


# ---------------------------------------------------------------------------
# AggressivePersona
# ---------------------------------------------------------------------------


class TestAggressivePersona:
    def test_high_confidence_ctx_produces_high_scale(self):
        persona = AggressivePersona()
        verdict = persona.argue(high_confidence_ctx())
        assert verdict.recommended_scale > 0.7

    def test_risky_ctx_reduces_scale_from_base(self):
        persona = AggressivePersona()
        verdict = persona.argue(risky_ctx())
        # Still > 0 but reduced from 1.0
        assert verdict.recommended_scale < 1.0

    def test_scale_bounded(self):
        persona = AggressivePersona()
        for ctx in [high_confidence_ctx(), risky_ctx(), neutral_ctx()]:
            v = persona.argue(ctx)
            assert 0.0 <= v.recommended_scale <= 1.0

    def test_credibility_bounded(self):
        persona = AggressivePersona()
        for ctx in [high_confidence_ctx(), risky_ctx(), neutral_ctx()]:
            v = persona.argue(ctx)
            assert 0.0 <= v.credibility <= 1.0

    def test_persona_label(self):
        persona = AggressivePersona()
        verdict = persona.argue(neutral_ctx())
        assert verdict.persona == "aggressive"

    def test_reasoning_non_empty(self):
        persona = AggressivePersona()
        verdict = persona.argue(neutral_ctx())
        assert len(verdict.reasoning) > 0

    def test_high_credibility_in_favourable_conditions(self):
        persona = AggressivePersona()
        verdict = persona.argue(high_confidence_ctx())
        # Strong signal, good IC, positive Sharpe, low_vol → credibility boosted
        assert verdict.credibility > 0.5

    def test_low_credibility_in_unfavourable_conditions(self):
        persona = AggressivePersona()
        verdict = persona.argue(risky_ctx())
        # High vol, negative Sharpe, high error rate → credibility penalised
        assert verdict.credibility <= 0.5


# ---------------------------------------------------------------------------
# ConservativePersona
# ---------------------------------------------------------------------------


class TestConservativePersona:
    def test_risky_ctx_produces_low_scale(self):
        persona = ConservativePersona()
        verdict = persona.argue(risky_ctx())
        assert verdict.recommended_scale <= 0.35

    def test_base_scale_is_quarter_kelly(self):
        persona = ConservativePersona()
        # Neutral context, no boosts
        verdict = persona.argue(neutral_ctx())
        assert verdict.recommended_scale == pytest.approx(0.25, abs=0.10)

    def test_scale_bounded(self):
        persona = ConservativePersona()
        for ctx in [high_confidence_ctx(), risky_ctx(), neutral_ctx()]:
            v = persona.argue(ctx)
            assert 0.0 <= v.recommended_scale <= 1.0

    def test_credibility_bounded(self):
        persona = ConservativePersona()
        for ctx in [high_confidence_ctx(), risky_ctx(), neutral_ctx()]:
            v = persona.argue(ctx)
            assert 0.0 <= v.credibility <= 1.0

    def test_persona_label(self):
        persona = ConservativePersona()
        assert persona.argue(neutral_ctx()).persona == "conservative"

    def test_high_credibility_in_risky_conditions(self):
        persona = ConservativePersona()
        verdict = persona.argue(risky_ctx())
        # High_vol + negative Sharpe + high drawdown → conservative is credible
        assert verdict.credibility > 0.5

    def test_strong_ic_nudges_scale_up_slightly(self):
        persona = ConservativePersona()
        base_ctx = RiskContext(
            composite_signal=0.5,
            ic_short=0.10,
            vol_regime="normal_vol",
            recent_sharpe=1.5,
        )
        neutral = RiskContext(composite_signal=0.1, ic_short=0.02)
        strong_verdict = persona.argue(base_ctx)
        weak_verdict = persona.argue(neutral)
        assert strong_verdict.recommended_scale >= weak_verdict.recommended_scale


# ---------------------------------------------------------------------------
# NeutralPersona
# ---------------------------------------------------------------------------


class TestNeutralPersona:
    def _persona_verdicts(self, ctx: RiskContext):
        a = AggressivePersona().argue(ctx)
        c = ConservativePersona().argue(ctx)
        return a, c

    def test_scale_bounded(self):
        persona = NeutralPersona()
        for ctx in [high_confidence_ctx(), risky_ctx(), neutral_ctx()]:
            a, c = self._persona_verdicts(ctx)
            v = persona.mediate(a, c, ctx)
            assert 0.0 <= v.recommended_scale <= 1.0

    def test_credibility_bounded(self):
        persona = NeutralPersona()
        for ctx in [high_confidence_ctx(), risky_ctx(), neutral_ctx()]:
            a, c = self._persona_verdicts(ctx)
            v = persona.mediate(a, c, ctx)
            assert 0.0 <= v.credibility <= 1.0

    def test_persona_label(self):
        persona = NeutralPersona()
        a, c = self._persona_verdicts(neutral_ctx())
        assert persona.mediate(a, c, neutral_ctx()).persona == "neutral"

    def test_scale_between_aggressive_and_conservative(self):
        """Neutral scale should be within [conservative, aggressive] bounds."""
        persona = NeutralPersona()
        for ctx in [high_confidence_ctx(), neutral_ctx()]:
            a, c = self._persona_verdicts(ctx)
            n = persona.mediate(a, c, ctx)
            # Allow a small tolerance for floating-point
            assert c.recommended_scale - 1e-9 <= n.recommended_scale <= a.recommended_scale + 1e-9

    def test_debate_confidence_anchors_scale(self):
        persona = NeutralPersona()
        ctx_high = RiskContext(
            ic_short=0.06,
            vol_regime="normal_vol",
            debate_confidence=0.90,
        )
        ctx_low = RiskContext(
            ic_short=0.06,
            vol_regime="normal_vol",
            debate_confidence=0.10,
        )
        a = AggressivePersona().argue(ctx_high)
        c = ConservativePersona().argue(ctx_high)
        v_high = persona.mediate(a, c, ctx_high)

        a2 = AggressivePersona().argue(ctx_low)
        c2 = ConservativePersona().argue(ctx_low)
        v_low = persona.mediate(a2, c2, ctx_low)

        assert v_high.recommended_scale >= v_low.recommended_scale


# ---------------------------------------------------------------------------
# RiskDebate
# ---------------------------------------------------------------------------


class TestRiskDebate:
    def test_returns_risk_debate_result(self):
        result = RiskDebate().resolve(neutral_ctx())
        assert isinstance(result, RiskDebateResult)

    def test_position_scale_bounded(self):
        for ctx in [high_confidence_ctx(), risky_ctx(), neutral_ctx()]:
            result = RiskDebate().resolve(ctx)
            assert 0.0 <= result.position_scale <= 1.0

    def test_high_confidence_ctx_larger_scale_than_risky(self):
        high = RiskDebate().resolve(high_confidence_ctx())
        risky = RiskDebate().resolve(risky_ctx())
        assert high.position_scale > risky.position_scale

    def test_all_verdicts_populated(self):
        result = RiskDebate().resolve(neutral_ctx())
        assert result.aggressive_verdict is not None
        assert result.conservative_verdict is not None
        assert result.neutral_verdict is not None

    def test_reasoning_non_empty(self):
        result = RiskDebate().resolve(neutral_ctx())
        assert len(result.reasoning) > 0

    def test_scale_is_credibility_weighted(self):
        """
        When all personas have equal credibility, scale = simple average.
        We can't test internal credibility directly but we can check the
        scale is somewhere in [conservative.scale, aggressive.scale].
        """
        result = RiskDebate().resolve(neutral_ctx())
        c_scale = result.conservative_verdict.recommended_scale
        a_scale = result.aggressive_verdict.recommended_scale
        assert c_scale <= result.position_scale <= a_scale

    def test_deterministic(self):
        ctx = neutral_ctx()
        r1 = RiskDebate().resolve(ctx)
        r2 = RiskDebate().resolve(ctx)
        assert r1.position_scale == pytest.approx(r2.position_scale)

    def test_zero_total_credibility_fallback(self):
        """If all credibility weights collapse to zero, should not raise."""
        # Create a context that might produce degenerate credibility
        ctx = RiskContext(
            composite_signal=0.0,
            ic_short=0.0,
            vol_regime="normal_vol",
            recent_sharpe=0.0,
            node_error_rate=0.0,
        )
        result = RiskDebate().resolve(ctx)
        assert 0.0 <= result.position_scale <= 1.0


# ---------------------------------------------------------------------------
# Integration: DebateGate + RiskDebate together
# ---------------------------------------------------------------------------


class TestDebateRiskIntegration:
    def test_debate_confidence_feeds_into_risk(self):
        """DebateGate verdict confidence should anchor risk debate scale."""
        from omega.adversarial.debate_gate import DebateGate, SignalContext

        gate = DebateGate()
        signal_ctx = SignalContext(
            composite_signal=0.70,
            ic_short=0.10,
            ic_long=0.08,
            vol_regime="low_vol",
            regime_ic={"low_vol": 0.12},
            recent_sharpe=1.4,
            node_error_rate=0.01,
            rsi=45.0,
        )
        verdict = gate.evaluate(signal_ctx)

        risk_ctx = RiskContext(
            composite_signal=signal_ctx.composite_signal,
            ic_short=signal_ctx.ic_short,
            vol_regime=signal_ctx.vol_regime,
            recent_sharpe=signal_ctx.recent_sharpe,
            node_error_rate=signal_ctx.node_error_rate,
            debate_confidence=verdict.confidence,
        )
        risk_result = RiskDebate().resolve(risk_ctx)

        # High debate confidence → risk debate should recommend meaningful scale
        assert risk_result.position_scale > 0.2

    def test_low_debate_confidence_reduces_risk_scale(self):
        """Low debate confidence should reduce risk debate scale."""
        risk_ctx = RiskContext(
            composite_signal=0.0,
            ic_short=0.02,
            vol_regime="high_vol",
            recent_sharpe=-0.5,
            node_error_rate=0.15,
            debate_confidence=0.10,
        )
        result = RiskDebate().resolve(risk_ctx)
        assert result.position_scale < 0.5
