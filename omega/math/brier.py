"""
omega.math.brier
~~~~~~~~~~~~~~~~
Brier score engine for evaluating probabilistic forecast calibration.

All signal sources in the Victoria system are ranked by their rolling Brier score.
Use this module as the single source of truth for calibration metrics.

Mathematical Background
-----------------------
Standard Brier Score (lower is better, perfect = 0, worst = 1):

    BS = (1/N) Σ_{t=1}^{N} (f_t - o_t)²

where f_t ∈ [0,1] is the forecast probability and o_t ∈ {0,1} is the outcome.

Exponentially Weighted Brier Score (emphasises recent forecasts):

    BS_ew = Σ λ^(T-t)(f_t - o_t)² / Σ λ^(T-t)

where λ ∈ (0,1] is the decay factor and T is the current time index.

Calibration Curve:
    Bin forecasts into B equal-width buckets on [0,1].
    For each bucket b: mean forecast vs. empirical hit rate.
    A perfectly calibrated source lies on the diagonal.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np


def brier_score(
    forecasts: Sequence[float],
    outcomes: Sequence[float],
) -> float:
    """
    Compute the standard Brier score.

    Parameters
    ----------
    forecasts : Sequence of predicted probabilities in [0, 1].
    outcomes  : Sequence of binary outcomes in {0, 1}.

    Returns
    -------
    Brier score in [0, 1]. Returns 0.0 for empty inputs.

    Raises
    ------
    ValueError
        If lengths differ or values are outside expected ranges.
    """
    f = np.asarray(forecasts, dtype=float)
    o = np.asarray(outcomes, dtype=float)

    if f.shape != o.shape:
        raise ValueError(
            f"forecasts and outcomes must have the same length, got {len(f)} and {len(o)}"
        )
    if len(f) == 0:
        return 0.0
    if np.any((f < 0) | (f > 1)):
        raise ValueError("forecasts must be in [0, 1]")
    if np.any((o < 0) | (o > 1)):
        raise ValueError("outcomes must be in [0, 1]")

    return float(np.mean((f - o) ** 2))


def brier_score_ew(
    forecasts: Sequence[float],
    outcomes: Sequence[float],
    lam: float = 0.97,
) -> float:
    """
    Compute the exponentially weighted Brier score for recency bias.

    Weights decay geometrically from the most recent observation backward:
        w_t = λ^(T-t),  t = 1, ..., T

    Parameters
    ----------
    forecasts : Sequence of predicted probabilities in [0, 1], oldest first.
    outcomes  : Sequence of binary outcomes in {0, 1}, oldest first.
    lam       : Decay factor λ ∈ (0, 1]. Default 0.97 ≈ 30-day half-life.

    Returns
    -------
    Exponentially weighted Brier score. Returns 0.0 for empty inputs.

    Raises
    ------
    ValueError
        If lam not in (0, 1], lengths differ, or values out of range.
    """
    if not (0 < lam <= 1.0):
        raise ValueError(f"lam must be in (0, 1], got {lam}")

    f = np.asarray(forecasts, dtype=float)
    o = np.asarray(outcomes, dtype=float)

    if f.shape != o.shape:
        raise ValueError(
            f"forecasts and outcomes must have the same length, got {len(f)} and {len(o)}"
        )
    if len(f) == 0:
        return 0.0
    if np.any((f < 0) | (f > 1)):
        raise ValueError("forecasts must be in [0, 1]")
    if np.any((o < 0) | (o > 1)):
        raise ValueError("outcomes must be in [0, 1]")

    n = len(f)
    # weights[i] = λ^(n-1-i), so the last element has weight 1.0
    exponents = np.arange(n - 1, -1, -1, dtype=float)
    weights = lam**exponents
    squared_errors = (f - o) ** 2

    return float(np.sum(weights * squared_errors) / np.sum(weights))


def calibration_curve(
    forecasts: Sequence[float],
    outcomes: Sequence[float],
    n_bins: int = 10,
) -> dict[str, np.ndarray]:
    """
    Compute calibration curve data by binning forecasts into equal-width buckets.

    Each bin reports:
    - mean forecast probability for forecasts that fell in that bin
    - empirical hit rate (fraction of positive outcomes in that bin)
    - count of observations in that bin

    A perfectly calibrated source has mean_forecast ≈ hit_rate for every bin
    (the reliability diagram lies on the diagonal y = x).

    Parameters
    ----------
    forecasts : Sequence of predicted probabilities in [0, 1].
    outcomes  : Sequence of binary outcomes in {0, 1}.
    n_bins    : Number of equal-width bins on [0, 1]. Default 10 (deciles).

    Returns
    -------
    dict with keys:
        'bin_centers'    : ndarray shape (n_bins,) — midpoint of each bin
        'mean_forecast'  : ndarray shape (n_bins,) — mean forecast per bin (NaN if empty)
        'hit_rate'       : ndarray shape (n_bins,) — empirical frequency per bin (NaN if empty)
        'counts'         : ndarray shape (n_bins,) int — observations per bin

    Raises
    ------
    ValueError
        If lengths differ or values are outside expected ranges.
    """
    f = np.asarray(forecasts, dtype=float)
    o = np.asarray(outcomes, dtype=float)

    if f.shape != o.shape:
        raise ValueError(
            f"forecasts and outcomes must have the same length, got {len(f)} and {len(o)}"
        )
    if np.any((f < 0) | (f > 1)):
        raise ValueError("forecasts must be in [0, 1]")
    if np.any((o < 0) | (o > 1)):
        raise ValueError("outcomes must be in [0, 1]")

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

    mean_forecast = np.full(n_bins, np.nan)
    hit_rate = np.full(n_bins, np.nan)
    counts = np.zeros(n_bins, dtype=int)

    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        # include right edge in the last bin to catch exactly 1.0
        if i < n_bins - 1:
            mask = (f >= lo) & (f < hi)
        else:
            mask = (f >= lo) & (f <= hi)

        n = int(np.sum(mask))
        counts[i] = n
        if n > 0:
            mean_forecast[i] = float(np.mean(f[mask]))
            hit_rate[i] = float(np.mean(o[mask]))

    return {
        "bin_centers": bin_centers,
        "mean_forecast": mean_forecast,
        "hit_rate": hit_rate,
        "counts": counts,
    }


def rank_sources(
    source_data: dict[str, tuple[Sequence[float], Sequence[float]]],
    weighted: bool = False,
    lam: float = 0.97,
) -> list[tuple[str, float]]:
    """
    Rank signal sources by calibration quality (ascending Brier score).

    Parameters
    ----------
    source_data : Mapping of source_name → (forecasts, outcomes).
                  Each source may have a different number of observations.
    weighted    : If True, use exponentially weighted Brier score (recency bias).
                  Default False uses standard Brier score.
    lam         : Decay factor for weighted variant. Ignored if weighted=False.

    Returns
    -------
    List of (source_name, brier_score) tuples sorted ascending by score
    (best calibrated sources first). Sources with no data return score of NaN
    and are placed last.

    Examples
    --------
    >>> sources = {
    ...     "model_A": ([0.9, 0.2, 0.8], [1, 0, 1]),
    ...     "model_B": ([0.5, 0.5, 0.5], [1, 0, 1]),
    ... }
    >>> rank_sources(sources)
    [('model_A', 0.023...), ('model_B', 0.333...)]
    """
    scored: list[tuple[str, float]] = []

    for name, (forecasts, outcomes) in source_data.items():
        if len(forecasts) == 0:
            scored.append((name, math.nan))
            continue
        if weighted:
            score = brier_score_ew(forecasts, outcomes, lam=lam)
        else:
            score = brier_score(forecasts, outcomes)
        scored.append((name, score))

    # NaN sources go last; otherwise ascending by score
    return sorted(scored, key=lambda x: (math.isnan(x[1]), x[1]))
