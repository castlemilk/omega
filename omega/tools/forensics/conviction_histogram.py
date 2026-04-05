"""Conviction band histogram — how many trades fall above/below a conviction threshold."""

from __future__ import annotations

from dataclasses import dataclass

from omega.tools.forensics.loader import RunArtifacts


@dataclass
class ConvictionHistogram:
    hold_threshold: float
    trade_band_count: int
    hold_band_count: int
    trade_band_pct: float
    hold_band_pct: float
    min_conviction: float
    max_conviction: float
    mean_conviction: float


def compute_histogram(run: RunArtifacts, hold_threshold: float) -> ConvictionHistogram:
    """Compute a conviction-band histogram for a run's trades.

    A trade is in the *trade band* if `abs(conviction) >= hold_threshold`.
    Otherwise it is in the *hold band* (would have been skipped under that threshold).
    """
    convictions = [abs(float(t.get("conviction", 0.0))) for t in run.trades]
    total = len(convictions)

    trade_band = sum(1 for c in convictions if c >= hold_threshold)
    hold_band = total - trade_band

    return ConvictionHistogram(
        hold_threshold=hold_threshold,
        trade_band_count=trade_band,
        hold_band_count=hold_band,
        trade_band_pct=(trade_band / total) if total > 0 else 0.0,
        hold_band_pct=(hold_band / total) if total > 0 else 0.0,
        min_conviction=min(convictions) if convictions else 0.0,
        max_conviction=max(convictions) if convictions else 0.0,
        mean_conviction=(sum(convictions) / total) if total > 0 else 0.0,
    )
