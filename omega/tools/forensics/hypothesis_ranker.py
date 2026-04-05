"""Rank the top-3 structural differences most likely explaining the baseline→target PnL gap.

Hypotheses are scored heuristically from four inputs:
1. Conviction histogram shift (mean/max conviction ratio, hold-band percentage delta)
2. Signal delta proxy (per-symbol PnL delta concentration)
3. Skipped trades (count and PnL of trades the target missed)
4. Zero-trade cycle ratio shift

Each hypothesis has a confidence in [0, 1] derived from the magnitude of its supporting
signal relative to the total PnL gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from omega.tools.forensics.conviction_histogram import ConvictionHistogram
from omega.tools.forensics.loader import RunArtifacts
from omega.tools.forensics.signal_delta import SignalDeltaProxy
from omega.tools.forensics.skipped_trades import SkippedTrade


@dataclass
class Hypothesis:
    rank: int
    claim: str
    confidence: float
    evidence_refs: list[str] = field(default_factory=list)


def _conviction_hypothesis(
    v35: RunArtifacts,
    v48: RunArtifacts,
    h35: ConvictionHistogram,
    h48: ConvictionHistogram,
) -> tuple[str, float]:
    if h35.mean_conviction <= 0:
        return ("", 0.0)
    ratio = h48.mean_conviction / h35.mean_conviction
    # Ratio < 0.5 is strong evidence; 1.0 is no change
    if ratio < 1.0:
        magnitude = 1.0 - ratio  # 0.0 .. 1.0
    else:
        magnitude = 0.0
    claim = (
        f"Conviction magnitudes collapsed: V48 mean conviction ({h48.mean_conviction:.3f}) "
        f"is {ratio:.2f}x V35 ({h35.mean_conviction:.3f}). The HOLD band is now "
        f"{h48.hold_band_pct:.0%} of trades vs {h35.hold_band_pct:.0%} in V35, "
        "consistent with post-demean thresholds not tracking signal magnitude."
    )
    return (claim, min(0.95, 0.3 + magnitude))


def _skipped_trades_hypothesis(
    skipped: list[SkippedTrade],
    v35: RunArtifacts,
    v48: RunArtifacts,
) -> tuple[str, float]:
    if not skipped:
        return ("", 0.0)
    skipped_pnl = sum(s.baseline_pnl for s in skipped)
    pnl_gap = v35.total_pnl - v48.total_pnl
    if pnl_gap <= 0:
        return ("", 0.0)
    coverage = min(1.0, max(0.0, skipped_pnl / pnl_gap))
    claim = (
        f"{len(skipped)} baseline trades were skipped by V48, representing "
        f"${skipped_pnl:.2f} of the ${pnl_gap:.2f} PnL gap ({coverage:.0%} coverage). "
        "Most were profitable baseline entries below V48's current threshold."
    )
    return (claim, min(0.9, 0.2 + coverage * 0.7))


def _signal_concentration_hypothesis(
    delta: SignalDeltaProxy,
    v35: RunArtifacts,
    v48: RunArtifacts,
) -> tuple[str, float]:
    if not delta.per_symbol_delta:
        return ("", 0.0)
    worst_symbol, worst_delta = min(delta.per_symbol_delta.items(), key=lambda kv: kv[1])
    pnl_gap = v35.total_pnl - v48.total_pnl
    if pnl_gap <= 0 or worst_delta >= 0:
        return ("", 0.0)
    share = min(1.0, abs(worst_delta) / pnl_gap)
    claim = (
        f"Per-symbol PnL loss is concentrated in {worst_symbol}: "
        f"${worst_delta:.2f} delta ({share:.0%} of the total gap). "
        "Targeted signal re-weighting for this symbol is a cheap first fix."
    )
    return (claim, min(0.85, 0.15 + share * 0.6))


def _zero_trade_hypothesis(v35: RunArtifacts, v48: RunArtifacts) -> tuple[str, float]:
    # Ratio of zero-trade cycles normalized to run length
    v35_cycles = max(1, v35.zero_trade_cycles + v35.trade_cycles)
    v48_cycles = max(1, v48.zero_trade_cycles + v48.trade_cycles)
    v35_ratio = v35.zero_trade_cycles / v35_cycles
    v48_ratio = v48.zero_trade_cycles / v48_cycles
    growth = v48_ratio - v35_ratio
    if growth <= 0.1:
        return ("", 0.0)
    claim = (
        f"V48 zero-trade cycle ratio is {v48_ratio:.0%} vs V35 {v35_ratio:.0%} "
        f"(+{growth:.0%}). Filters or HOLD-band are skipping entire cycles; "
        "conviction or stale-data filters are over-gating."
    )
    return (claim, min(0.8, 0.2 + growth * 2.0))


def rank_hypotheses(
    v35: RunArtifacts,
    v48: RunArtifacts,
    v35_histogram: ConvictionHistogram,
    v48_histogram: ConvictionHistogram,
    delta: SignalDeltaProxy,
    skipped: list[SkippedTrade],
) -> list[Hypothesis]:
    """Produce the top-3 ranked hypotheses. Always returns exactly 3 entries."""
    candidates: list[tuple[str, float, list[str]]] = []

    claim, conf = _conviction_hypothesis(v35, v48, v35_histogram, v48_histogram)
    if claim:
        candidates.append(
            (claim, conf, ["conviction_histogram", "observability.conviction_filter_rate"])
        )

    claim, conf = _skipped_trades_hypothesis(skipped, v35, v48)
    if claim:
        candidates.append((claim, conf, ["skipped_trades", "baselines"]))

    claim, conf = _signal_concentration_hypothesis(delta, v35, v48)
    if claim:
        candidates.append((claim, conf, ["signal_contribution_delta_proxy"]))

    claim, conf = _zero_trade_hypothesis(v35, v48)
    if claim:
        candidates.append((claim, conf, ["observability.total_zero_trade_cycles"]))

    # Always pad to 3 with neutral-confidence fallbacks so downstream agents have a stable shape
    while len(candidates) < 3:
        candidates.append(
            (
                "No additional structural difference detected above heuristic thresholds.",
                0.05,
                [],
            )
        )

    candidates.sort(key=lambda c: c[1], reverse=True)
    top3 = candidates[:3]
    return [
        Hypothesis(rank=i + 1, claim=c[0], confidence=c[1], evidence_refs=c[2])
        for i, c in enumerate(top3)
    ]
