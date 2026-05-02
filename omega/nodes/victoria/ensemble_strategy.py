"""V173: ensemble strategy — three independent sub-strategies vote.

Background: V165–V172 (9 weight-tuning attempts) all regressed because the
composite is a SUM of correlated signals — adjusting individual weights has
unpredictable system effects. Per-regime IC weighting failed even at correct
granularity. The pruning result (delete sma_crossover) regressing $66k proved
that individual signal IC isn't a reliable guide to system contribution.

Different approach: instead of one weighted composite, run three INDEPENDENT
sub-strategies each with their own signal subset and decision logic. They
emit categorical {LONG, SHORT, ABSTAIN} votes, NOT numerical weights.
Aggregate by majority vote. This is more robust because each sub-strategy is
self-contained — it doesn't have to agree on numerical magnitudes with others.

Sub-strategies:

  Momentum  (alpha-carriers from IC analysis)
            breakout_signal (+0.42), timeframe_signal (+0.32),
            adx_signal (+0.21), momentum_persistence (+0.11)

  MeanRev   (regime-gated; mean-reversion is suicide in crash)
            ABSTAIN during crisis regime entirely.
            Otherwise: ollivier_ricci_signal (+0.10 normal/-0.44 crisis),
            breakout_signal sign (faded vs followed), and price-vs-mean.

  Macro     (regime-confidence + directional bias)
            fear_greed_signal (+0.44 in crisis!), vix_signal,
            funding_rate_signal, w2_crisis distance.
            Outputs (regime_confidence, directional_bias) — informs sizing
            and acts as a tie-breaker, not a primary vote.

Aggregation:
  - 3 agree → full size
  - 2 agree, 1 abstain → 0.75x size
  - 2 agree, 1 disagree → 0.50x size, take majority vote
  - All disagree or all abstain → SIT OUT
  - Final size also multiplied by macro.regime_confidence (0–1)

Feature flag: ensemble_strategy=True (in features.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger("omega.nodes.victoria.ensemble_strategy")

Vote = Literal["long", "short", "abstain"]


@dataclass
class SubVote:
    direction: Vote
    conviction: float  # 0..1
    name: str          # for debugging/logs


@dataclass
class EnsembleDecision:
    direction: Vote                # final vote
    size_mult: float               # 0..1
    sub_votes: list[SubVote]
    macro_regime_confidence: float
    macro_bias: float              # -1 (bear) .. +1 (bull)


def _safe_float(d: dict, key: str, default: float = 0.0) -> float:
    v = d.get(key)
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def momentum_vote(signals: dict[str, Any]) -> SubVote:
    """Momentum sub-strategy: 4 alpha-carrier signals; majority sign decides.

    Conviction = (agreement_ratio - 0.5) × 2 × max(|signal|), clipped to [0, 1].
    """
    sig_names = ["breakout_signal", "timeframe_signal", "adx_signal", "momentum_persistence"]
    vals = [(_safe_float(signals, n, 0.0), n) for n in sig_names if n in signals]
    if not vals or all(v == 0 for v, _ in vals):
        return SubVote("abstain", 0.0, "momentum")
    pos = sum(1 for v, _ in vals if v > 0)
    neg = sum(1 for v, _ in vals if v < 0)
    total = pos + neg
    if total == 0 or pos == neg:
        return SubVote("abstain", 0.0, "momentum")
    direction: Vote = "long" if pos > neg else "short"
    agree_ratio = max(pos, neg) / total
    max_strength = max(abs(v) for v, _ in vals)
    conviction = max(0.0, min(1.0, (agree_ratio - 0.5) * 2.0 * max_strength))
    return SubVote(direction, round(conviction, 4), "momentum")


def mean_reversion_vote(signals: dict[str, Any], regime: str) -> SubVote:
    """Mean-reversion sub-strategy: regime-gated.

    ABSTAIN in crisis (mean-reversion against a crash bleeds money).
    In normal/trend: fade extreme breakout_signal when ORC confirms.
    """
    if regime == "crisis":
        return SubVote("abstain", 0.0, "mean_reversion")
    breakout = _safe_float(signals, "breakout_signal", 0.0)
    orc = _safe_float(signals, "ollivier_ricci_signal", 0.0)
    # Fade strong breakouts confirmed by negative ORC (overextension).
    if abs(breakout) < 0.3 or abs(orc) < 0.05:
        return SubVote("abstain", 0.0, "mean_reversion")
    # ORC sign should oppose breakout for a fade signal.
    if breakout > 0 and orc < 0:
        return SubVote("short", round(min(1.0, abs(breakout) * 0.7), 4), "mean_reversion")
    if breakout < 0 and orc > 0:
        return SubVote("long", round(min(1.0, abs(breakout) * 0.7), 4), "mean_reversion")
    return SubVote("abstain", 0.0, "mean_reversion")


def macro_signals(signals: dict[str, Any], regime: str) -> tuple[float, float, SubVote]:
    """Macro sub-strategy: regime confidence + directional bias.

    Returns (regime_confidence ∈ [0,1], bias ∈ [-1,+1], directional vote).
    The vote uses fear_greed (contrarian: fear → long, greed → short) plus
    funding rate (positive funding → overbought → short).
    """
    fg = _safe_float(signals, "fear_greed_signal", 0.0)        # [-1, +1] contrarian
    funding = _safe_float(signals, "funding_rate_signal", 0.0) # [-1, +1] z-score, sign-flipped
    vix = _safe_float(signals, "vix_signal", 0.0)              # higher = bearish
    # Composite bias: fear_greed and funding both contrarian.
    bias = (fg + funding - 0.5 * vix) / 2.5  # rough scale into [-1, +1]
    bias = max(-1.0, min(1.0, bias))

    # Regime confidence: high when signals agree on direction; low when split.
    components = [fg, funding, -vix]  # -vix because high vix = bearish
    same_sign = sum(1 for c in components if c * bias > 0.05)
    regime_confidence = same_sign / max(1, len(components))

    if abs(bias) < 0.1:
        vote = SubVote("abstain", 0.0, "macro")
    else:
        direction: Vote = "long" if bias > 0 else "short"
        vote = SubVote(direction, round(min(1.0, abs(bias)), 4), "macro")
    return round(regime_confidence, 4), round(bias, 4), vote


def aggregate(
    votes: list[SubVote],
    macro_confidence: float,
    sub_weights: dict[str, float] | None = None,
) -> EnsembleDecision:
    """Combine sub-votes into a final decision and size multiplier.

    V174 sub_weights: optional {sub_name: weight in [0,1]}. Multiplied into
    each vote's conviction. When a sub-strategy has been performing poorly
    recently (recent_hit_rate < 0.5), `adaptive_ensemble_decay` lowers its
    weight, fading its influence on the ensemble decision.
    """
    sub_weights = sub_weights or {}

    def _eff(v: SubVote) -> float:
        return v.conviction * sub_weights.get(v.name, 1.0)

    actives = [v for v in votes if v.direction != "abstain" and _eff(v) > 0.05]
    if not actives:
        return EnsembleDecision("abstain", 0.0, votes, macro_confidence, 0.0)
    longs = [v for v in actives if v.direction == "long"]
    shorts = [v for v in actives if v.direction == "short"]
    if len(longs) > len(shorts):
        majority: Vote = "long"
        agreeing = longs
    elif len(shorts) > len(longs):
        majority = "short"
        agreeing = shorts
    else:
        return EnsembleDecision("abstain", 0.0, votes, macro_confidence, 0.0)

    # Size mult: depends on agreement structure
    n_total = len(votes)
    n_agree = len(agreeing)
    n_abstain = sum(1 for v in votes if v.direction == "abstain")
    if n_agree == n_total:
        size_mult = 1.0
    elif n_agree == 2 and n_abstain == 1:
        size_mult = 0.75
    elif n_agree == 2 and n_abstain == 0:
        size_mult = 0.50
    else:
        size_mult = 0.0

    # Apply min-effective-conviction across agreeing votes and macro regime confidence
    min_conv = min(_eff(v) for v in agreeing) if agreeing else 0.0
    size_mult = size_mult * max(0.1, min_conv) * max(0.5, macro_confidence)
    size_mult = max(0.0, min(1.0, size_mult))

    # Aggregate macro_bias for the decision record
    macro_vote = next((v for v in votes if v.name == "macro"), None)
    macro_bias = macro_vote.conviction if macro_vote and macro_vote.direction != "abstain" else 0.0
    if macro_vote and macro_vote.direction == "short":
        macro_bias = -macro_bias

    return EnsembleDecision(
        direction=majority,
        size_mult=round(size_mult, 4),
        sub_votes=votes,
        macro_regime_confidence=macro_confidence,
        macro_bias=macro_bias,
    )


def decide(
    signals: dict[str, Any],
    regime: str,
    sub_weights: dict[str, float] | None = None,
    adversarial_check: bool = False,
) -> EnsembleDecision:
    """Main entry: compute all sub-votes and aggregate.

    `sub_weights` (V174 #1): per-sub-strategy multiplier reflecting recent
    hit rate. {momentum: 0.8, mean_reversion: 1.0, macro: 0.5} dampens
    sub-strategies that have recently underperformed.

    `adversarial_check` (V174 #4): when True, also computes the decision
    with all signal values negated. If the negated decision is also
    high-conviction in the OPPOSITE direction, it confirms the call. If it
    matches our direction or the gap is small, the underlying signals are
    ambiguous → SIT OUT.
    """
    mom = momentum_vote(signals)
    mr = mean_reversion_vote(signals, regime)
    macro_conf, _macro_bias, macro = macro_signals(signals, regime)
    decision = aggregate([mom, mr, macro], macro_conf, sub_weights)
    if not adversarial_check or decision.direction == "abstain":
        return decision

    # V174 #4: re-evaluate with negated signal values
    neg_signals = {
        k: (-v if isinstance(v, (int, float)) and not k.startswith("_regime") else v)
        for k, v in signals.items()
    }
    neg_mom = momentum_vote(neg_signals)
    neg_mr = mean_reversion_vote(neg_signals, regime)
    _neg_conf, _neg_bias, neg_macro = macro_signals(neg_signals, regime)
    neg_decision = aggregate([neg_mom, neg_mr, neg_macro], _neg_conf, sub_weights)

    if neg_decision.direction == decision.direction:
        # Same direction even with negated inputs → ambiguous, sit out
        logger.debug("adversarial: SAME-direction conflict → sit out (orig=%s neg=%s)",
                     decision.direction, neg_decision.direction)
        return EnsembleDecision("abstain", 0.0, decision.sub_votes,
                                decision.macro_regime_confidence, decision.macro_bias)

    if neg_decision.direction != "abstain":
        # Opposite-direction high-conviction → CONFIRMED. Boost size 1.2x (cap 1.0).
        boosted = min(1.0, decision.size_mult * 1.2)
        return EnsembleDecision(decision.direction, round(boosted, 4),
                                decision.sub_votes,
                                decision.macro_regime_confidence,
                                decision.macro_bias)
    # Negated → abstain → standard, keep decision unchanged
    return decision


def _self_test() -> None:
    """Smoke test."""
    # All bullish momentum, normal regime → LONG full size
    s = {
        "breakout_signal": 0.6,
        "timeframe_signal": 0.4,
        "adx_signal": 0.3,
        "momentum_persistence": 0.5,
        "fear_greed_signal": 0.8,
        "funding_rate_signal": 0.5,
        "ollivier_ricci_signal": 0.0,
        "vix_signal": -0.2,
    }
    d = decide(s, "normal")
    assert d.direction == "long", f"expected long, got {d}"
    print(f"all bullish: {d.direction} size×{d.size_mult}")

    # Crisis regime → mean_reversion abstains
    s2 = {**s, "ollivier_ricci_signal": -0.5}
    d2 = decide(s2, "crisis")
    print(f"crisis: {d2.direction} size×{d2.size_mult} votes={[v.direction for v in d2.sub_votes]}")

    # All abstain
    d3 = decide({}, "normal")
    assert d3.direction == "abstain"
    print(f"empty: {d3.direction} size×{d3.size_mult}")
    print("ensemble_strategy: OK")


if __name__ == "__main__":
    _self_test()
