"""
omega.adversarial.risk_personas
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Three risk personas debate position sizing and produce a position_scale
multiplier in [0, 1] to apply against the Kelly-optimal fraction.

Inspired by TradingAgents' Aggressive / Conservative / Neutral risk debate
but implemented entirely with quantitative rule-based logic — zero LLM calls.

Personas
--------
AggressivePersona
    Argues for deploying close to full Kelly. Cites momentum, positive IC,
    and favourable regime. Concedes only on extreme error rates or deeply
    negative Sharpe.

ConservativePersona
    Argues for 1/4 Kelly. Cites tail-risk heuristics: high vol regime,
    drawdown history (via negative Sharpe), and node error rates.

NeutralPersona
    Mediates between the other two. Uses base-rate reasoning: expected IC
    translated to expected edge, scaled by regime confidence. Typically
    recommends half-Kelly.

RiskDebate.resolve(ctx)
    Runs all three personas, then computes a weighted-average position_scale
    using the persona credibility scores (derived from context). Returns a
    float in [0, 1].
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import ClassVar

logger = logging.getLogger("omega.adversarial.risk_personas")


# ---------------------------------------------------------------------------
# Input context (shared with DebateGate but re-imported to avoid circular)
# ---------------------------------------------------------------------------


@dataclass
class RiskContext:
    """
    Quantitative inputs for the risk persona debate.

    Fields
    ------
    composite_signal  : Composite signal value in [-1, 1].
    ic_short          : Information coefficient at short horizon.
    vol_regime        : Current volatility regime string.
    recent_sharpe     : Rolling Sharpe (30d). Negative = recent losses.
    node_error_rate   : NodeHealth error rate [0, 1].
    atl_distance      : Distance from ATL as fraction [0, 1].
    debate_confidence : Confidence from DebateGate verdict [0, 1]. Optional.
                        If provided, anchors the neutral persona's recommendation.
    max_drawdown      : Maximum drawdown observed recently [0, 1]. Optional.
    """

    composite_signal: float = 0.0
    ic_short: float = 0.0
    vol_regime: str = "normal_vol"
    recent_sharpe: float = 0.0
    node_error_rate: float = 0.0
    atl_distance: float = 0.5
    debate_confidence: float = 0.5
    max_drawdown: float = 0.0


# ---------------------------------------------------------------------------
# Persona verdict
# ---------------------------------------------------------------------------


@dataclass
class PersonaVerdict:
    """Output from a single persona's argument."""

    persona: str
    recommended_scale: float  # [0, 1]
    credibility: float  # [0, 1] — how credible this persona's argument is given context
    reasoning: str


# ---------------------------------------------------------------------------
# Persona implementations
# ---------------------------------------------------------------------------


class AggressivePersona:
    """
    Argues for deploying close to full Kelly.

    Credibility is HIGH when:
    - composite_signal is strongly positive
    - ic_short is above meaningful threshold (> 0.05)
    - vol_regime is low_vol (lower-risk environment)
    - recent_sharpe is positive

    Credibility is LOW when:
    - node_error_rate is high (signals unreliable)
    - recent_sharpe is deeply negative (momentum absent)
    - vol_regime is high_vol
    """

    # Scale recommendation: starts at full Kelly, reduced by risk factors
    _BASE_SCALE: float = 1.0

    def argue(self, ctx: RiskContext) -> PersonaVerdict:
        reasoning_parts = ["Aggressive: momentum and IC support full deployment."]
        scale = self._BASE_SCALE
        credibility = 0.5  # start neutral

        # Boost credibility on strong signal + IC
        if ctx.composite_signal > 0.3:
            credibility += 0.15
            reasoning_parts.append(f"Signal is strongly bullish ({ctx.composite_signal:.3f})")
        if ctx.ic_short > 0.05:
            credibility += 0.15
            reasoning_parts.append(f"IC short is above threshold ({ctx.ic_short:.4f})")
        if ctx.recent_sharpe > 0.5:
            credibility += 0.10
            reasoning_parts.append(f"Recent Sharpe is positive ({ctx.recent_sharpe:.2f})")
        if ctx.vol_regime == "low_vol":
            credibility += 0.10
            reasoning_parts.append("Low-vol regime supports larger positions")

        # Reduce scale and credibility on risk factors
        if ctx.node_error_rate > 0.10:
            scale *= 0.8
            credibility -= 0.15
            reasoning_parts.append(f"Conceding: node errors elevated ({ctx.node_error_rate:.1%})")
        if ctx.recent_sharpe < -0.5:
            scale *= 0.7
            credibility -= 0.15
            reasoning_parts.append(f"Conceding: recent Sharpe negative ({ctx.recent_sharpe:.2f})")
        if ctx.vol_regime == "high_vol":
            scale *= 0.85
            credibility -= 0.10
            reasoning_parts.append("Slight reduction for high-vol regime")
        if ctx.max_drawdown > 0.15:
            scale *= 0.9
            credibility -= 0.10
            reasoning_parts.append(f"Recent drawdown {ctx.max_drawdown:.1%} — mild concession")

        scale = float(min(1.0, max(0.0, scale)))
        credibility = float(min(1.0, max(0.0, credibility)))

        logger.debug("AggressivePersona: scale=%.3f credibility=%.3f", scale, credibility)
        return PersonaVerdict(
            persona="aggressive",
            recommended_scale=scale,
            credibility=credibility,
            reasoning=" ".join(reasoning_parts),
        )


class ConservativePersona:
    """
    Argues for 1/4 Kelly to preserve capital.

    Credibility is HIGH when:
    - vol_regime is high_vol (tail risk elevated)
    - max_drawdown is significant
    - recent_sharpe is negative
    - node_error_rate is high

    Credibility is LOW when:
    - signal is very strong with positive IC and positive Sharpe
    """

    _BASE_SCALE: float = 0.25  # 1/4 Kelly

    def argue(self, ctx: RiskContext) -> PersonaVerdict:
        reasoning_parts = ["Conservative: tail risk requires capital preservation at 1/4 Kelly."]
        scale = self._BASE_SCALE
        credibility = 0.5

        # Boost credibility on risk factors
        if ctx.vol_regime == "high_vol":
            credibility += 0.20
            reasoning_parts.append("High-vol regime — fat-tail losses are more likely")
        if ctx.recent_sharpe < -0.3:
            credibility += 0.15
            reasoning_parts.append(
                f"Negative recent Sharpe ({ctx.recent_sharpe:.2f}) signals edge erosion"
            )
        if ctx.max_drawdown > 0.10:
            credibility += 0.15
            reasoning_parts.append(
                f"Recent drawdown {ctx.max_drawdown:.1%} — reduce to limit further loss"
            )
        if ctx.node_error_rate > 0.05:
            credibility += 0.10
            reasoning_parts.append(
                f"Elevated node error rate ({ctx.node_error_rate:.1%}) — signal quality degraded"
            )

        # Increase recommended scale slightly when evidence is strong
        if ctx.ic_short > 0.08 and ctx.composite_signal > 0.4:
            scale = min(0.35, scale + 0.10)
            credibility -= 0.10
            reasoning_parts.append("Conceding slightly: strong IC + signal (scale nudged to 0.35)")
        if ctx.recent_sharpe > 1.0:
            scale = min(0.40, scale + 0.10)
            credibility -= 0.10
            reasoning_parts.append("Conceding: strong positive Sharpe (scale nudged up)")

        scale = float(min(1.0, max(0.0, scale)))
        credibility = float(min(1.0, max(0.0, credibility)))

        logger.debug("ConservativePersona: scale=%.3f credibility=%.3f", scale, credibility)
        return PersonaVerdict(
            persona="conservative",
            recommended_scale=scale,
            credibility=credibility,
            reasoning=" ".join(reasoning_parts),
        )


class NeutralPersona:
    """
    Mediates between Aggressive and Conservative using base-rate reasoning.

    Algorithm
    ---------
    1. Translate ic_short to expected edge: E = IC * sqrt(252) (annualised info ratio).
    2. Compute a regime confidence multiplier: low_vol → 1.0, high_vol → 0.6.
    3. Base recommendation = clamp(E / max_E, 0, 1) * regime_conf * 0.5 (half-Kelly default).
    4. Anchor to debate_confidence if provided: scale = lerp(base, debate_conf, 0.4).
    5. Penalise for error rate.

    The neutral persona's credibility is always moderate (0.5) ± small adjustments.
    """

    _MAX_IC: float = 0.20  # IC at which full half-Kelly is recommended
    _REGIME_CONFIDENCE: ClassVar[dict[str, float]] = {
        "low_vol": 1.0,
        "normal_vol": 0.8,
        "high_vol": 0.6,
    }

    def mediate(
        self,
        aggressive: PersonaVerdict,
        conservative: PersonaVerdict,
        ctx: RiskContext,
    ) -> PersonaVerdict:
        reasoning_parts = ["Neutral: base-rate position sizing via IC and regime."]

        # Step 1: IC → annualised info ratio proxy
        annualised_ir = ctx.ic_short * math.sqrt(252)
        base_scale = min(1.0, max(0.0, annualised_ir / (self._MAX_IC * math.sqrt(252))))
        base_scale *= 0.5  # half-Kelly baseline

        # Step 2: regime confidence multiplier
        regime_conf = self._REGIME_CONFIDENCE.get(ctx.vol_regime, 0.8)
        base_scale *= regime_conf
        reasoning_parts.append(
            f"Base scale from IC ({ctx.ic_short:.4f}) and regime '{ctx.vol_regime}'"
            f" ({regime_conf:.1f}x): {base_scale:.3f}"
        )

        # Step 3: anchor to debate_confidence
        if ctx.debate_confidence > 0:
            base_scale = base_scale * 0.6 + ctx.debate_confidence * 0.5 * 0.4
            reasoning_parts.append(f"Anchored to debate confidence ({ctx.debate_confidence:.3f})")

        # Step 4: error penalty
        error_penalty = 1.0 - ctx.node_error_rate * 0.5
        base_scale *= error_penalty

        # Step 5: sanity-check against extreme personas
        #   The neutral persona shouldn't recommend more than the aggressive
        #   or less than the conservative
        base_scale = float(
            min(aggressive.recommended_scale, max(conservative.recommended_scale, base_scale))
        )

        credibility = 0.50  # neutral always moderate
        # Slight credibility boost when the two extremes are far apart
        spread = abs(aggressive.recommended_scale - conservative.recommended_scale)
        if spread > 0.3:
            credibility += 0.10
            reasoning_parts.append(
                f"High spread between personas ({spread:.2f}) — neutral acts as tiebreaker"
            )

        base_scale = float(min(1.0, max(0.0, base_scale)))
        credibility = float(min(1.0, max(0.0, credibility)))

        logger.debug("NeutralPersona: scale=%.3f credibility=%.3f", base_scale, credibility)
        return PersonaVerdict(
            persona="neutral",
            recommended_scale=base_scale,
            credibility=credibility,
            reasoning=" ".join(reasoning_parts),
        )


# ---------------------------------------------------------------------------
# RiskDebate — orchestrator
# ---------------------------------------------------------------------------


@dataclass
class RiskDebateResult:
    """Full output from a RiskDebate session."""

    position_scale: float  # Final [0, 1] position scale multiplier
    aggressive_verdict: PersonaVerdict
    conservative_verdict: PersonaVerdict
    neutral_verdict: PersonaVerdict
    reasoning: str


class RiskDebate:
    """
    Runs the three-persona risk debate and resolves to a position_scale.

    Resolution is a credibility-weighted average of the three persona verdicts.
    Credibility acts as the voting weight — personas that are more credible
    given the current context get more influence over the final scale.

    Usage::

        ctx = RiskContext(
            composite_signal=0.5,
            ic_short=0.07,
            vol_regime="normal_vol",
            recent_sharpe=0.8,
            node_error_rate=0.03,
            debate_confidence=0.65,
        )
        result = RiskDebate().resolve(ctx)
        print(result.position_scale)  # e.g., 0.62
    """

    def __init__(
        self,
        aggressive: AggressivePersona | None = None,
        conservative: ConservativePersona | None = None,
        neutral: NeutralPersona | None = None,
    ) -> None:
        self._aggressive = aggressive or AggressivePersona()
        self._conservative = conservative or ConservativePersona()
        self._neutral = neutral or NeutralPersona()

    def resolve(self, ctx: RiskContext) -> RiskDebateResult:
        """
        Run debate and compute credibility-weighted position scale.

        Returns
        -------
        RiskDebateResult with final position_scale and all persona verdicts.
        """
        a_verdict = self._aggressive.argue(ctx)
        c_verdict = self._conservative.argue(ctx)
        n_verdict = self._neutral.mediate(a_verdict, c_verdict, ctx)

        # Credibility-weighted average
        verdicts = [a_verdict, c_verdict, n_verdict]
        total_credibility = sum(v.credibility for v in verdicts)

        if total_credibility < 1e-9:
            # Fallback: equal weights
            position_scale = sum(v.recommended_scale for v in verdicts) / 3.0
        else:
            position_scale = (
                sum(v.recommended_scale * v.credibility for v in verdicts) / total_credibility
            )

        position_scale = float(min(1.0, max(0.0, position_scale)))

        reasoning = (
            f"RiskDebate resolved: scale={position_scale:.3f} "
            f"(aggressive={a_verdict.recommended_scale:.2f}x{a_verdict.credibility:.2f}, "
            f"conservative={c_verdict.recommended_scale:.2f}x{c_verdict.credibility:.2f}, "
            f"neutral={n_verdict.recommended_scale:.2f}x{n_verdict.credibility:.2f})"
        )

        logger.info(
            "RiskDebate: position_scale=%.3f "
            "aggressive=(scale=%.2f, cred=%.2f) "
            "conservative=(scale=%.2f, cred=%.2f) "
            "neutral=(scale=%.2f, cred=%.2f)",
            position_scale,
            a_verdict.recommended_scale,
            a_verdict.credibility,
            c_verdict.recommended_scale,
            c_verdict.credibility,
            n_verdict.recommended_scale,
            n_verdict.credibility,
        )

        return RiskDebateResult(
            position_scale=position_scale,
            aggressive_verdict=a_verdict,
            conservative_verdict=c_verdict,
            neutral_verdict=n_verdict,
            reasoning=reasoning,
        )
