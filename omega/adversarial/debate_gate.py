"""
omega.adversarial.debate_gate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Structured Bull/Bear debate for signal disagreement resolution.

Inspired by TradingAgents' Bull/Bear researcher architecture, but implemented
entirely with rule-based/quantitative case construction — zero LLM calls in
the critical path. Consistent with the PICO baseline: all logic is deterministic
and reproducible given the same inputs.

Architecture
------------
                    ┌──────────────────┐
  SignalContext ──▶ │  BullCaseBuilder │──▶ BullCase (strength, evidence)
                    └──────────────────┘         │
                                                  ▼
                    ┌──────────────────┐    ┌──────────┐    ┌────────────────┐
  SignalContext ──▶ │  BearCaseBuilder │──▶ │  Judge   │──▶ │ DebateVerdict  │
                    └──────────────────┘    └──────────┘    └────────────────┘
                                                  ▲
                    BearCase (strength, evidence) ─┘

Mathematical basis
------------------
Bull case strength = Σ w_i · indicator_i  (bullish indicators, weighted by IC)
Bear case strength = Σ w_j · indicator_j  (bearish indicators, weighted by IC)

Judge performs a Bayesian update starting from a 0.5 prior:
  LR_bull = bull_strength / (1 - bull_strength)
  LR_bear = (1 - bear_strength) / bear_strength
  posterior = Bayesian(prior=0.5, [LR_bull, LR_bear])

The posterior maps to:
  ≥ 0.60 → BUY   (confidence = 2·(posterior - 0.5))
  ≤ 0.40 → SELL
  else   → HOLD
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

from omega.math.bayesian import bayesian_update

logger = logging.getLogger("omega.adversarial.debate_gate")


# ---------------------------------------------------------------------------
# Direction enum
# ---------------------------------------------------------------------------


class Direction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


# ---------------------------------------------------------------------------
# Input context
# ---------------------------------------------------------------------------


@dataclass
class SignalContext:
    """
    All quantitative inputs the DebateGate uses to construct Bull/Bear cases.

    Fields
    ------
    composite_signal  : Composite signal value, typically in [-1, 1].
                        Positive = bullish, negative = bearish.
    ic_short          : Information coefficient at short horizon (e.g., 1-day).
    ic_long           : IC at longer horizon (e.g., 5-day). Decay indicates
                        signal fade — a bearish factor.
    vol_regime        : Current volatility regime string, e.g., "high_vol",
                        "low_vol", "normal_vol".
    regime_ic         : Per-regime IC map, e.g. {"high_vol": 0.04, "low_vol": 0.13}.
                        Used to check regime alignment.
    recent_sharpe     : Rolling Sharpe ratio over recent window (30d). Negative
                        Sharpe is a strong bearish signal.
    node_error_rate   : NodeHealth error rate [0, 1]. High error rate degrades
                        signal confidence.
    atl_distance      : Distance from all-time-low as fraction [0, 1]. Low
                        ATL distance → potential mean-reversion support (bull).
    rsi               : RSI value [0, 100]. Overbought (>70) is bearish;
                        oversold (<30) is bullish.
    extra             : Optional dict for additional indicator pass-through.
    """

    composite_signal: float = 0.0
    ic_short: float = 0.0
    ic_long: float = 0.0
    vol_regime: str = "normal_vol"
    regime_ic: dict[str, float] = field(default_factory=dict)
    recent_sharpe: float = 0.0
    node_error_rate: float = 0.0
    atl_distance: float = 0.5
    rsi: float = 50.0
    extra: dict[str, Any] = field(default_factory=dict)

    def current_regime_ic(self) -> float:
        """Return IC for the current vol regime, falling back to ic_short."""
        return self.regime_ic.get(self.vol_regime, self.ic_short)


# ---------------------------------------------------------------------------
# Case dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BullCase:
    """Arguments favouring a long/buy position."""

    strength: float  # [0, 1] — aggregate bull evidence strength
    evidence: list[str]  # human-readable evidence items
    indicator_contributions: dict[str, float]  # indicator_name → contribution


@dataclass
class BearCase:
    """Arguments favouring a short/neutral/sell position."""

    strength: float  # [0, 1] — aggregate bear evidence strength
    evidence: list[str]
    indicator_contributions: dict[str, float]


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


@dataclass
class DebateVerdict:
    """
    Output of the DebateGate judge.

    Fields
    ------
    direction        : BUY / SELL / HOLD based on posterior probability.
    confidence       : float [0, 1] — how decisive the verdict is.
                       0.0 = complete uncertainty, 1.0 = certainty.
    position_scale   : float [0, 1] — fraction of Kelly-optimal to deploy.
    reasoning        : Human-readable summary of the decisive arguments.
    dissent_strength : Strength of the losing side's case. High dissent means
                       the verdict was contested — useful for self-calibration.
    bull_strength    : Raw bull case strength before Bayesian synthesis.
    bear_strength    : Raw bear case strength.
    posterior        : Bayesian posterior probability (P(bullish | evidence)).
    """

    direction: Direction
    confidence: float
    position_scale: float
    reasoning: str
    dissent_strength: float
    bull_strength: float
    bear_strength: float
    posterior: float


# ---------------------------------------------------------------------------
# Bull case builder
# ---------------------------------------------------------------------------


class BullCaseBuilder:
    """
    Constructs the strongest quantitative case for going long.

    Each indicator is scored as a contribution in [0, 1] and weighted.
    Final strength is the weighted sum, clipped to [0, 1].

    Indicator weights are calibrated so that:
      - Composite signal direction is the primary factor (weight 0.35).
      - IC quality is the second factor (weight 0.25).
      - Regime alignment accounts for vol-adjusted IC (weight 0.20).
      - Sharpe and RSI are supporting factors (0.10 + 0.10).
    """

    # Indicator → weight (must sum to 1.0)
    _WEIGHTS: ClassVar[dict[str, float]] = {
        "composite_signal": 0.35,
        "ic_quality": 0.25,
        "regime_alignment": 0.20,
        "sharpe": 0.10,
        "rsi": 0.10,
    }

    def build(self, ctx: SignalContext) -> BullCase:
        contributions: dict[str, float] = {}
        evidence: list[str] = []

        # 1. Composite signal direction [0, 1]
        #    Normalise from [-1, 1] → [0, 1]
        sig_norm = (ctx.composite_signal + 1.0) / 2.0
        contributions["composite_signal"] = float(min(1.0, max(0.0, sig_norm)))
        if ctx.composite_signal > 0.3:
            evidence.append(f"Composite signal strongly bullish: {ctx.composite_signal:.3f}")
        elif ctx.composite_signal > 0:
            evidence.append(f"Composite signal mildly bullish: {ctx.composite_signal:.3f}")

        # 2. IC quality — higher short IC and low decay are bullish
        #    IC decay = max(0, ic_short - ic_long) as a fraction of ic_short
        ic_quality = min(1.0, max(0.0, ctx.ic_short * 5.0))  # scale: 0.20 IC → 1.0
        ic_decay = 0.0
        if ctx.ic_short > 0 and ctx.ic_long < ctx.ic_short:
            ic_decay = (ctx.ic_short - ctx.ic_long) / max(ctx.ic_short, 1e-9)
        ic_quality = ic_quality * (1.0 - 0.5 * ic_decay)  # decay penalises
        contributions["ic_quality"] = float(min(1.0, max(0.0, ic_quality)))
        if ctx.ic_short > 0.05:
            evidence.append(f"IC at short horizon is positive: {ctx.ic_short:.4f}")
        if ic_decay < 0.2 and ctx.ic_long > 0:
            evidence.append(f"IC decay is low ({ic_decay:.1%}), signal persists to long horizon")

        # 3. Regime alignment — is current regime IC favourable?
        regime_ic = ctx.current_regime_ic()
        regime_score = min(1.0, max(0.0, regime_ic * 10.0))  # scale: 0.10 IC → 1.0
        contributions["regime_alignment"] = float(regime_score)
        if regime_ic > 0.05:
            evidence.append(f"Regime '{ctx.vol_regime}' has positive IC: {regime_ic:.4f}")

        # 4. Sharpe — positive recent Sharpe is bullish
        #    Map [-2, +2] → [0, 1]
        sharpe_norm = (ctx.recent_sharpe + 2.0) / 4.0
        contributions["sharpe"] = float(min(1.0, max(0.0, sharpe_norm)))
        if ctx.recent_sharpe > 0.5:
            evidence.append(f"Recent Sharpe ratio is positive: {ctx.recent_sharpe:.2f}")

        # 5. RSI — oversold territory is bullish (mean reversion)
        #    < 30: strong bull signal; > 70: weak; 50 = neutral
        if ctx.rsi < 30:
            rsi_score = 1.0
            evidence.append(f"RSI oversold ({ctx.rsi:.1f}) — mean-reversion opportunity")
        elif ctx.rsi < 50:
            rsi_score = (50.0 - ctx.rsi) / 50.0 * 0.5 + 0.5  # [0.5, 1.0]
        elif ctx.rsi < 70:
            rsi_score = 1.0 - (ctx.rsi - 50.0) / 40.0  # [0.5, 0.0] range mapped to [0.5, 0]
        else:
            rsi_score = 0.0  # overbought — bull case weakened
        contributions["rsi"] = float(min(1.0, max(0.0, rsi_score)))

        # Penalise for high node error rate
        error_penalty = 1.0 - ctx.node_error_rate
        strength = sum(self._WEIGHTS[k] * v for k, v in contributions.items()) * error_penalty

        if ctx.node_error_rate > 0.1:
            evidence.append(
                f"WARNING: node error rate is elevated ({ctx.node_error_rate:.1%}), "
                "bull case confidence reduced"
            )

        strength = float(min(1.0, max(0.0, strength)))
        logger.debug(
            "BullCase: strength=%.3f contributions=%s",
            strength,
            {k: f"{v:.3f}" for k, v in contributions.items()},
        )
        return BullCase(
            strength=strength,
            evidence=evidence,
            indicator_contributions=contributions,
        )


# ---------------------------------------------------------------------------
# Bear case builder
# ---------------------------------------------------------------------------


class BearCaseBuilder:
    """
    Constructs the strongest quantitative case for going short / staying flat.

    Bearish indicators are the mirror-image of bullish ones, plus tail-risk
    factors: ATL proximity risk (fade support = bearish overhang) and IC decay.
    """

    _WEIGHTS: ClassVar[dict[str, float]] = {
        "composite_signal": 0.35,
        "ic_quality": 0.20,
        "regime_mismatch": 0.20,
        "sharpe": 0.15,
        "rsi": 0.10,
    }

    def build(self, ctx: SignalContext) -> BearCase:
        contributions: dict[str, float] = {}
        evidence: list[str] = []

        # 1. Composite signal direction — negative is bearish
        sig_norm_bear = 1.0 - (ctx.composite_signal + 1.0) / 2.0
        contributions["composite_signal"] = float(min(1.0, max(0.0, sig_norm_bear)))
        if ctx.composite_signal < -0.3:
            evidence.append(f"Composite signal strongly bearish: {ctx.composite_signal:.3f}")
        elif ctx.composite_signal < 0:
            evidence.append(f"Composite signal mildly bearish: {ctx.composite_signal:.3f}")

        # 2. IC quality — low or negative IC is bearish
        ic_bear = 1.0 - min(1.0, max(0.0, ctx.ic_short * 5.0))
        ic_decay = 0.0
        if ctx.ic_short > 0 and ctx.ic_long < ctx.ic_short:
            ic_decay = (ctx.ic_short - ctx.ic_long) / max(ctx.ic_short, 1e-9)
        ic_bear = min(1.0, ic_bear + 0.3 * ic_decay)  # IC decay strengthens bear
        contributions["ic_quality"] = float(min(1.0, max(0.0, ic_bear)))
        if ctx.ic_short < 0.02:
            evidence.append(f"IC at short horizon is near-zero or negative: {ctx.ic_short:.4f}")
        if ic_decay > 0.3:
            evidence.append(
                f"Significant IC decay ({ic_decay:.1%}) — signal fades at long horizon"
            )

        # 3. Regime mismatch — current regime IC is unfavourable
        regime_ic = ctx.current_regime_ic()
        regime_mismatch = 1.0 - min(1.0, max(0.0, regime_ic * 10.0))
        contributions["regime_mismatch"] = float(regime_mismatch)
        if regime_ic < 0.02:
            evidence.append(f"Regime '{ctx.vol_regime}' has near-zero IC: {regime_ic:.4f}")
        if ctx.vol_regime == "high_vol" and ctx.recent_sharpe < 0:
            evidence.append("High volatility regime + negative Sharpe — elevated drawdown risk")

        # 4. Sharpe — negative Sharpe is bearish
        sharpe_bear = 1.0 - (ctx.recent_sharpe + 2.0) / 4.0
        contributions["sharpe"] = float(min(1.0, max(0.0, sharpe_bear)))
        if ctx.recent_sharpe < -0.5:
            evidence.append(
                f"Recent Sharpe ratio is significantly negative: {ctx.recent_sharpe:.2f}"
            )

        # 5. RSI — overbought is bearish
        if ctx.rsi > 70:
            rsi_bear = 1.0
            evidence.append(f"RSI overbought ({ctx.rsi:.1f}) — reversion risk elevated")
        elif ctx.rsi > 50:
            rsi_bear = (ctx.rsi - 50.0) / 50.0 * 0.5 + 0.5
        elif ctx.rsi > 30:
            rsi_bear = 1.0 - (50.0 - ctx.rsi) / 50.0 * 0.5
        else:
            rsi_bear = 0.0  # oversold — bear case weakened for mean reversion
        contributions["rsi"] = float(min(1.0, max(0.0, rsi_bear)))

        # High node error rate strengthens bear case (signal unreliable)
        error_boost = 1.0 + ctx.node_error_rate * 0.3
        strength = sum(self._WEIGHTS[k] * v for k, v in contributions.items()) * error_boost

        if ctx.node_error_rate > 0.1:
            evidence.append(
                f"Elevated node error rate ({ctx.node_error_rate:.1%}) "
                "— signal reliability impaired"
            )

        strength = float(min(1.0, max(0.0, strength)))
        logger.debug(
            "BearCase: strength=%.3f contributions=%s",
            strength,
            {k: f"{v:.3f}" for k, v in contributions.items()},
        )
        return BearCase(
            strength=strength,
            evidence=evidence,
            indicator_contributions=contributions,
        )


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------


class Judge:
    """
    Weighs Bull and Bear cases using Bayesian inference and produces a verdict.

    Algorithm
    ---------
    1. Start with uninformative prior P(bull) = 0.5.
    2. Convert bull_strength to a likelihood ratio:
         LR_bull = bull_strength / (1 - bull_strength)  [evidence FOR buying]
    3. Convert bear_strength to a counter likelihood ratio:
         LR_bear = (1 - bear_strength) / bear_strength  [evidence AGAINST buying]
    4. Update: posterior = Bayesian(0.5, [LR_bull, LR_bear])
    5. Map posterior → direction + confidence + position_scale.

    Thresholds
    ----------
    posterior ≥ 0.60  → BUY
    posterior ≤ 0.40  → SELL
    else              → HOLD

    position_scale is proportional to confidence, capped at 1.0.
    """

    _BUY_THRESHOLD: float = 0.60
    _SELL_THRESHOLD: float = 0.40

    def weigh(self, bull: BullCase, bear: BearCase, ctx: SignalContext) -> DebateVerdict:
        # Guard against degenerate strengths to avoid log(0) in Bayesian update
        eps = 1e-6
        bull_s = float(min(1.0 - eps, max(eps, bull.strength)))
        bear_s = float(min(1.0 - eps, max(eps, bear.strength)))

        lr_bull = bull_s / (1.0 - bull_s)  # LR favouring bull
        lr_bear_inv = (1.0 - bear_s) / bear_s  # LR diminishing bear (=1/LR_bear)

        posterior = bayesian_update(prior=0.5, likelihood_ratios=[lr_bull, lr_bear_inv])

        # Direction
        if posterior >= self._BUY_THRESHOLD:
            direction = Direction.BUY
            confidence = (posterior - 0.5) * 2.0  # [0, 1]
            dissent_strength = bear.strength
            winning_evidence = bull.evidence
        elif posterior <= self._SELL_THRESHOLD:
            direction = Direction.SELL
            confidence = (0.5 - posterior) * 2.0  # [0, 1]
            dissent_strength = bull.strength
            winning_evidence = bear.evidence
        else:
            direction = Direction.HOLD
            confidence = 1.0 - abs(posterior - 0.5) * 4.0  # near-0 at extremes, 1.0 at 0.5
            confidence = float(max(0.0, confidence))
            # HOLD: dissent = max of both sides
            dissent_strength = max(bull.strength, bear.strength)
            winning_evidence = ["Bull and bear cases are roughly balanced — holding is prudent"]

        confidence = float(min(1.0, max(0.0, confidence)))
        position_scale = float(min(1.0, max(0.0, confidence)))

        # Build reasoning
        top_evidence = winning_evidence[:3]  # top 3 decisive points
        reasoning_parts = [f"Direction: {direction.value} (posterior={posterior:.3f})"]
        if top_evidence:
            reasoning_parts.append("Decisive evidence: " + "; ".join(top_evidence))
        reasoning_parts.append(f"Dissent strength (losing side): {dissent_strength:.3f}")
        reasoning = ". ".join(reasoning_parts)

        logger.info(
            "Judge: posterior=%.3f direction=%s confidence=%.3f position_scale=%.3f dissent=%.3f",
            posterior,
            direction.value,
            confidence,
            position_scale,
            dissent_strength,
        )

        return DebateVerdict(
            direction=direction,
            confidence=confidence,
            position_scale=position_scale,
            reasoning=reasoning,
            dissent_strength=dissent_strength,
            bull_strength=bull.strength,
            bear_strength=bear.strength,
            posterior=posterior,
        )


# ---------------------------------------------------------------------------
# DebateGate — public API
# ---------------------------------------------------------------------------


class DebateGate:
    """
    Routes signal disagreement through a structured Bull/Bear debate.

    When the adversarial layer detects signal disagreement or low composite
    confidence, call ``evaluate()`` instead of immediately vetoing.  The gate
    returns a ``DebateVerdict`` that the caller can use to:

    - Proceed at full Kelly   → confidence > 0.6
    - Proceed at half Kelly   → 0.4 ≤ confidence ≤ 0.6
    - Veto                    → confidence < 0.4

    Zero LLM calls. Fully deterministic given the same SignalContext.

    Usage::

        gate = DebateGate()
        verdict = gate.evaluate(SignalContext(
            composite_signal=0.6,
            ic_short=0.08,
            ic_long=0.12,
            vol_regime="low_vol",
            regime_ic={"low_vol": 0.13, "high_vol": 0.04},
            recent_sharpe=1.2,
            node_error_rate=0.02,
            rsi=45.0,
        ))
        if verdict.confidence > 0.6:
            deploy_full_kelly()
        elif verdict.confidence >= 0.4:
            deploy_half_kelly(verdict.position_scale * 0.5)
        else:
            veto()
    """

    def __init__(
        self,
        bull_builder: BullCaseBuilder | None = None,
        bear_builder: BearCaseBuilder | None = None,
        judge: Judge | None = None,
    ) -> None:
        self._bull = bull_builder or BullCaseBuilder()
        self._bear = bear_builder or BearCaseBuilder()
        self._judge = judge or Judge()

    def evaluate(self, ctx: SignalContext) -> DebateVerdict:
        """
        Run the full Bull/Bear debate and return a verdict.

        Parameters
        ----------
        ctx : SignalContext with all relevant quantitative signal data.

        Returns
        -------
        DebateVerdict with direction, confidence, position_scale, and reasoning.
        """
        bull = self._bull.build(ctx)
        bear = self._bear.build(ctx)
        verdict = self._judge.weigh(bull, bear, ctx)

        logger.info(
            "DebateGate: bull_strength=%.3f bear_strength=%.3f "
            "→ %s confidence=%.3f position_scale=%.3f",
            bull.strength,
            bear.strength,
            verdict.direction.value,
            verdict.confidence,
            verdict.position_scale,
        )
        return verdict

    @staticmethod
    def action_from_verdict(verdict: DebateVerdict) -> tuple[str, float]:
        """
        Map a DebateVerdict to a simple (action, position_scale) tuple.

        Returns
        -------
        ("proceed", position_scale)  if confidence > 0.6
        ("reduce", position_scale * 0.5)  if 0.4 <= confidence <= 0.6
        ("veto", 0.0)  if confidence < 0.4
        """
        if verdict.confidence > 0.6:
            return ("proceed", verdict.position_scale)
        elif verdict.confidence >= 0.4:
            return ("reduce", verdict.position_scale * 0.5)
        else:
            return ("veto", 0.0)


# ---------------------------------------------------------------------------
# Convenience: build SignalContext from a raw signal dict
# ---------------------------------------------------------------------------


def signal_context_from_dict(data: dict[str, Any]) -> SignalContext:
    """
    Build a ``SignalContext`` from a raw dict, ignoring unknown keys.

    Useful for quick construction from pipeline output dicts.
    """
    known = {f.name for f in SignalContext.__dataclass_fields__.values()}
    kwargs = {k: v for k, v in data.items() if k in known}
    return SignalContext(**kwargs)
