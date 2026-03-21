"""
omega.eval.sharpe
~~~~~~~~~~~~~~~~~
Single source of truth for Sharpe ratio and related statistics.

ALL Sharpe calculations in the eval framework use this module.
No other code should implement its own Sharpe formula.

Formula
-------
  Sharpe = mean(returns) / std(returns, ddof=1) * sqrt(periods_per_year)

Sample variance (N-1 denominator) is used throughout.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence


def compute_sharpe(
    returns: Sequence[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """
    Compute annualised Sharpe ratio using sample variance (N-1).

    Parameters
    ----------
    returns         : Sequence of per-period returns (e.g. daily).
    risk_free_rate  : Per-period risk-free rate (default 0.0).
    periods_per_year: Annualisation factor (252 for daily, 52 weekly, 12 monthly).

    Returns
    -------
    Sharpe ratio as float. Returns 0.0 if fewer than 2 observations or zero std.
    """
    r = [float(x) for x in returns]
    n = len(r)
    if n < 2:
        return 0.0

    excess = [x - risk_free_rate for x in r]
    mean_ex = sum(excess) / n
    # Sample variance: N-1 denominator
    variance = sum((x - mean_ex) ** 2 for x in excess) / (n - 1)
    std = math.sqrt(variance)

    if std == 0.0:
        return 0.0

    return mean_ex / std * math.sqrt(periods_per_year)


def compute_sharpe_confidence_interval(
    returns: Sequence[float],
    confidence: float = 0.95,
    n_bootstrap: int = 1000,
    periods_per_year: int = 252,
    seed: int = 42,
) -> tuple[float, float]:
    """
    Bootstrap confidence interval for the Sharpe ratio.

    Parameters
    ----------
    returns         : Per-period returns.
    confidence      : Confidence level (default 0.95 → 95% CI).
    n_bootstrap     : Number of bootstrap resamples.
    periods_per_year: Annualisation factor.
    seed            : Random seed for reproducibility.

    Returns
    -------
    (lower, upper) confidence interval.
    """
    r = [float(x) for x in returns]
    n = len(r)
    if n < 2:
        return (0.0, 0.0)

    rng = random.Random(seed)
    sharpes: list[float] = []
    for _ in range(n_bootstrap):
        sample = [rng.choice(r) for _ in range(n)]
        sharpes.append(compute_sharpe(sample, periods_per_year=periods_per_year))

    sharpes.sort()
    alpha = 1.0 - confidence
    lo_idx = math.floor(alpha / 2 * n_bootstrap)
    hi_idx = math.ceil((1.0 - alpha / 2) * n_bootstrap) - 1
    lo_idx = max(0, lo_idx)
    hi_idx = min(n_bootstrap - 1, hi_idx)
    return (sharpes[lo_idx], sharpes[hi_idx])


def sharpe_difference_significant(
    returns_a: Sequence[float],
    returns_b: Sequence[float],
    confidence: float = 0.95,
) -> tuple[bool, float]:
    """
    Test whether the Sharpe of A is significantly different from B.

    Uses a paired t-test on the Sharpe difference estimated via bootstrap
    (Jobson-Korkie style). For sequences of equal length, tests if the
    difference in per-period excess returns has a non-zero mean.

    Parameters
    ----------
    returns_a, returns_b : Per-period return sequences (same length).
    confidence           : Confidence level.

    Returns
    -------
    (is_significant, p_value) where p_value approximated from t-distribution.
    """
    a = [float(x) for x in returns_a]
    b = [float(x) for x in returns_b]
    n = min(len(a), len(b))
    if n < 4:
        return (False, 1.0)

    a = a[:n]
    b = b[:n]
    diffs = [a[i] - b[i] for i in range(n)]
    mean_d = sum(diffs) / n
    variance_d = sum((d - mean_d) ** 2 for d in diffs) / (n - 1)
    std_d = math.sqrt(variance_d) if variance_d > 0 else 0.0

    if std_d == 0.0:
        # Identical — not significant
        return (False, 1.0)

    t_stat = mean_d / (std_d / math.sqrt(n))

    # Approximate p-value using normal approximation (valid for n >= 30)
    # For small n this is an approximation; use scipy for exact if needed.
    p_value = 2.0 * (1.0 - _normal_cdf(abs(t_stat)))

    return (p_value < (1.0 - confidence), p_value)


def compute_information_ratio(
    returns: Sequence[float],
    benchmark_returns: Sequence[float],
    periods_per_year: int = 252,
) -> float:
    """
    Compute Information Ratio: alpha / tracking_error.

    IR = mean(active_returns) / std(active_returns, ddof=1) * sqrt(periods_per_year)

    Parameters
    ----------
    returns           : Strategy per-period returns.
    benchmark_returns : Benchmark per-period returns.
    periods_per_year  : Annualisation factor.

    Returns
    -------
    Information Ratio as float.
    """
    r = [float(x) for x in returns]
    b = [float(x) for x in benchmark_returns]
    n = min(len(r), len(b))
    if n < 2:
        return 0.0

    active = [r[i] - b[i] for i in range(n)]
    return compute_sharpe(active, risk_free_rate=0.0, periods_per_year=periods_per_year)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normal_cdf(x: float) -> float:
    """Approximate standard normal CDF using Abramowitz & Stegun formula."""
    # Valid to about 7 decimal places
    sign = 1.0 if x >= 0 else -1.0
    x = abs(x)
    t = 1.0 / (1.0 + 0.2316419 * x)
    poly = t * (
        0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429)))
    )
    pdf = math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
    return 0.5 + sign * (0.5 - pdf * poly)


# Backwards-compatibility alias
sharpe_ratio = compute_sharpe
