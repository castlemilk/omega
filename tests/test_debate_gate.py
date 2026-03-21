"""Tests for omega.adversarial.debate_gate."""

from __future__ import annotations

import pytest

from omega.adversarial.debate_gate import (
    BearCaseBuilder,
    BullCaseBuilder,
    DebateGate,
    DebateVerdict,
    Direction,
    Judge,
    SignalContext,
    signal_context_from_dict,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def bullish_ctx() -> SignalContext:
    """Strong bullish signal context."""
    return SignalContext(
        composite_signal=0.75,
        ic_short=0.12,
        ic_long=0.10,
        vol_regime="low_vol",
        regime_ic={"low_vol": 0.13, "high_vol": 0.04},
        recent_sharpe=1.8,
        node_error_rate=0.01,
        atl_distance=0.6,
        rsi=45.0,
    )


def bearish_ctx() -> SignalContext:
    """Strong bearish signal context."""
    return SignalContext(
        composite_signal=-0.65,
        ic_short=-0.02,
        ic_long=0.05,
        vol_regime="high_vol",
        regime_ic={"low_vol": 0.08, "high_vol": -0.01},
        recent_sharpe=-1.2,
        node_error_rate=0.15,
        atl_distance=0.1,
        rsi=78.0,
    )


def neutral_ctx() -> SignalContext:
    """Near-neutral signal context that should produce HOLD."""
    return SignalContext(
        composite_signal=0.05,
        ic_short=0.03,
        ic_long=0.03,
        vol_regime="normal_vol",
        regime_ic={"normal_vol": 0.03},
        recent_sharpe=0.1,
        node_error_rate=0.05,
        atl_distance=0.5,
        rsi=50.0,
    )


# ---------------------------------------------------------------------------
# SignalContext
# ---------------------------------------------------------------------------


class TestSignalContext:
    def test_current_regime_ic_uses_regime(self):
        ctx = SignalContext(
            vol_regime="high_vol",
            regime_ic={"low_vol": 0.13, "high_vol": 0.04},
            ic_short=0.08,
        )
        assert ctx.current_regime_ic() == pytest.approx(0.04)

    def test_current_regime_ic_fallback_to_ic_short(self):
        ctx = SignalContext(
            vol_regime="rare_regime",
            regime_ic={"low_vol": 0.13},
            ic_short=0.07,
        )
        assert ctx.current_regime_ic() == pytest.approx(0.07)

    def test_current_regime_ic_empty_map(self):
        ctx = SignalContext(vol_regime="low_vol", ic_short=0.06)
        assert ctx.current_regime_ic() == pytest.approx(0.06)


# ---------------------------------------------------------------------------
# BullCaseBuilder
# ---------------------------------------------------------------------------


class TestBullCaseBuilder:
    def test_strong_bull_signal_produces_high_strength(self):
        builder = BullCaseBuilder()
        case = builder.build(bullish_ctx())
        assert case.strength > 0.6, f"Expected high strength, got {case.strength}"

    def test_bear_signal_produces_low_bull_strength(self):
        builder = BullCaseBuilder()
        case = builder.build(bearish_ctx())
        assert case.strength < 0.4, f"Expected low strength for bearish ctx, got {case.strength}"

    def test_strength_bounded(self):
        builder = BullCaseBuilder()
        for ctx in [bullish_ctx(), bearish_ctx(), neutral_ctx()]:
            case = builder.build(ctx)
            assert 0.0 <= case.strength <= 1.0

    def test_evidence_populated_for_bullish(self):
        builder = BullCaseBuilder()
        case = builder.build(bullish_ctx())
        assert len(case.evidence) > 0

    def test_indicator_contributions_sum_weighted_correctly(self):
        builder = BullCaseBuilder()
        case = builder.build(bullish_ctx())
        # Each contribution must be in [0, 1]
        for k, v in case.indicator_contributions.items():
            assert 0.0 <= v <= 1.0, f"Contribution {k}={v} out of bounds"

    def test_oversold_rsi_boosts_bull_case(self):
        builder = BullCaseBuilder()
        ctx_oversold = SignalContext(
            composite_signal=0.3,
            ic_short=0.05,
            rsi=25.0,
        )
        ctx_neutral = SignalContext(
            composite_signal=0.3,
            ic_short=0.05,
            rsi=50.0,
        )
        oversold_case = builder.build(ctx_oversold)
        neutral_case = builder.build(ctx_neutral)
        assert oversold_case.strength >= neutral_case.strength

    def test_high_error_rate_penalises_bull_case(self):
        builder = BullCaseBuilder()
        ctx_clean = bullish_ctx()
        ctx_errored = SignalContext(
            composite_signal=ctx_clean.composite_signal,
            ic_short=ctx_clean.ic_short,
            node_error_rate=0.30,
        )
        clean_case = builder.build(ctx_clean)
        errored_case = builder.build(ctx_errored)
        assert errored_case.strength < clean_case.strength


# ---------------------------------------------------------------------------
# BearCaseBuilder
# ---------------------------------------------------------------------------


class TestBearCaseBuilder:
    def test_strong_bear_signal_produces_high_strength(self):
        builder = BearCaseBuilder()
        case = builder.build(bearish_ctx())
        assert case.strength > 0.6, f"Expected high bear strength, got {case.strength}"

    def test_bull_signal_produces_low_bear_strength(self):
        builder = BearCaseBuilder()
        case = builder.build(bullish_ctx())
        assert case.strength < 0.4, (
            f"Expected low bear strength for bullish ctx, got {case.strength}"
        )

    def test_strength_bounded(self):
        builder = BearCaseBuilder()
        for ctx in [bullish_ctx(), bearish_ctx(), neutral_ctx()]:
            case = builder.build(ctx)
            assert 0.0 <= case.strength <= 1.0

    def test_overbought_rsi_boosts_bear_case(self):
        builder = BearCaseBuilder()
        ctx_overbought = SignalContext(
            composite_signal=-0.2,
            ic_short=0.02,
            rsi=80.0,
        )
        ctx_neutral = SignalContext(
            composite_signal=-0.2,
            ic_short=0.02,
            rsi=50.0,
        )
        overbought_case = builder.build(ctx_overbought)
        neutral_case = builder.build(ctx_neutral)
        assert overbought_case.strength >= neutral_case.strength

    def test_high_error_rate_boosts_bear_case(self):
        builder = BearCaseBuilder()
        ctx_clean = SignalContext(
            composite_signal=0.0,
            ic_short=0.05,
            node_error_rate=0.01,
        )
        ctx_errored = SignalContext(
            composite_signal=0.0,
            ic_short=0.05,
            node_error_rate=0.30,
        )
        clean_case = builder.build(ctx_clean)
        errored_case = builder.build(ctx_errored)
        assert errored_case.strength >= clean_case.strength


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------


class TestJudge:
    def _make_cases(self, bull_s: float, bear_s: float):
        from omega.adversarial.debate_gate import BearCase, BullCase

        bull = BullCase(strength=bull_s, evidence=[], indicator_contributions={})
        bear = BearCase(strength=bear_s, evidence=[], indicator_contributions={})
        return bull, bear

    def test_strong_bull_case_produces_buy(self):
        judge = Judge()
        bull, bear = self._make_cases(0.85, 0.15)
        verdict = judge.weigh(bull, bear, neutral_ctx())
        assert verdict.direction == Direction.BUY

    def test_strong_bear_case_produces_sell(self):
        judge = Judge()
        bull, bear = self._make_cases(0.10, 0.90)
        verdict = judge.weigh(bull, bear, neutral_ctx())
        assert verdict.direction == Direction.SELL

    def test_balanced_cases_produce_hold(self):
        judge = Judge()
        bull, bear = self._make_cases(0.50, 0.50)
        verdict = judge.weigh(bull, bear, neutral_ctx())
        assert verdict.direction == Direction.HOLD

    def test_confidence_bounded(self):
        judge = Judge()
        for bs, br in [(0.9, 0.1), (0.1, 0.9), (0.5, 0.5), (0.7, 0.3)]:
            bull, bear = self._make_cases(bs, br)
            verdict = judge.weigh(bull, bear, neutral_ctx())
            assert 0.0 <= verdict.confidence <= 1.0

    def test_position_scale_bounded(self):
        judge = Judge()
        bull, bear = self._make_cases(0.9, 0.1)
        verdict = judge.weigh(bull, bear, neutral_ctx())
        assert 0.0 <= verdict.position_scale <= 1.0

    def test_dissent_strength_is_losing_side(self):
        judge = Judge()
        bull, bear = self._make_cases(0.85, 0.20)
        verdict = judge.weigh(bull, bear, neutral_ctx())
        # Strong bull wins → bear is dissent
        assert verdict.dissent_strength == pytest.approx(bear.strength)

    def test_sell_dissent_is_bull_strength(self):
        judge = Judge()
        bull, bear = self._make_cases(0.15, 0.85)
        verdict = judge.weigh(bull, bear, neutral_ctx())
        assert verdict.direction == Direction.SELL
        assert verdict.dissent_strength == pytest.approx(bull.strength)

    def test_reasoning_non_empty(self):
        judge = Judge()
        bull, bear = self._make_cases(0.7, 0.3)
        verdict = judge.weigh(bull, bear, neutral_ctx())
        assert len(verdict.reasoning) > 0

    def test_posterior_in_range(self):
        judge = Judge()
        bull, bear = self._make_cases(0.7, 0.3)
        verdict = judge.weigh(bull, bear, neutral_ctx())
        assert 0.0 < verdict.posterior < 1.0


# ---------------------------------------------------------------------------
# DebateGate (end-to-end)
# ---------------------------------------------------------------------------


class TestDebateGate:
    def test_bullish_context_returns_buy(self):
        gate = DebateGate()
        verdict = gate.evaluate(bullish_ctx())
        assert verdict.direction == Direction.BUY

    def test_bearish_context_returns_sell(self):
        gate = DebateGate()
        verdict = gate.evaluate(bearish_ctx())
        assert verdict.direction == Direction.SELL

    def test_verdict_fields_populated(self):
        gate = DebateGate()
        verdict = gate.evaluate(bullish_ctx())
        assert isinstance(verdict, DebateVerdict)
        assert verdict.reasoning
        assert 0.0 <= verdict.confidence <= 1.0
        assert 0.0 <= verdict.position_scale <= 1.0
        assert 0.0 <= verdict.dissent_strength <= 1.0

    def test_action_from_verdict_proceed(self):
        # Artificially high confidence verdict
        verdict = DebateVerdict(
            direction=Direction.BUY,
            confidence=0.75,
            position_scale=0.75,
            reasoning="test",
            dissent_strength=0.20,
            bull_strength=0.80,
            bear_strength=0.20,
            posterior=0.85,
        )
        action, scale = DebateGate.action_from_verdict(verdict)
        assert action == "proceed"
        assert scale == pytest.approx(0.75)

    def test_action_from_verdict_reduce(self):
        verdict = DebateVerdict(
            direction=Direction.HOLD,
            confidence=0.50,
            position_scale=0.50,
            reasoning="test",
            dissent_strength=0.45,
            bull_strength=0.52,
            bear_strength=0.48,
            posterior=0.52,
        )
        action, scale = DebateGate.action_from_verdict(verdict)
        assert action == "reduce"
        assert scale == pytest.approx(0.25)  # 0.50 * 0.5

    def test_action_from_verdict_veto(self):
        verdict = DebateVerdict(
            direction=Direction.HOLD,
            confidence=0.20,
            position_scale=0.20,
            reasoning="test",
            dissent_strength=0.50,
            bull_strength=0.45,
            bear_strength=0.55,
            posterior=0.48,
        )
        action, scale = DebateGate.action_from_verdict(verdict)
        assert action == "veto"
        assert scale == pytest.approx(0.0)

    def test_deterministic_output(self):
        """Same inputs always produce the same verdict."""
        gate = DebateGate()
        ctx = bullish_ctx()
        v1 = gate.evaluate(ctx)
        v2 = gate.evaluate(ctx)
        assert v1.direction == v2.direction
        assert v1.confidence == pytest.approx(v2.confidence)
        assert v1.position_scale == pytest.approx(v2.position_scale)


# ---------------------------------------------------------------------------
# signal_context_from_dict
# ---------------------------------------------------------------------------


class TestSignalContextFromDict:
    def test_basic_construction(self):
        data = {
            "composite_signal": 0.5,
            "ic_short": 0.07,
            "vol_regime": "low_vol",
            "unknown_key": "ignored",
        }
        ctx = signal_context_from_dict(data)
        assert ctx.composite_signal == pytest.approx(0.5)
        assert ctx.ic_short == pytest.approx(0.07)
        assert ctx.vol_regime == "low_vol"

    def test_defaults_for_missing_keys(self):
        ctx = signal_context_from_dict({})
        assert ctx.composite_signal == pytest.approx(0.0)
        assert ctx.rsi == pytest.approx(50.0)
