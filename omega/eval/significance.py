"""
omega.eval.significance
~~~~~~~~~~~~~~~~~~~~~~~
Statistical significance testing for Sharpe ratios.

Functions
---------
sharpe_is_significant       -- Bootstrap CI test: is a strategy's Sharpe > min_sharpe?
sharpe_difference_significant -- Paired bootstrap: does Sharpe(A) differ from Sharpe(B)?
deflated_sharpe_ratio       -- Bailey & Lopez de Prado DSR for multiple-testing correction.

All Sharpe calculations delegate to omega.eval.sharpe — never reimplement.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence

from omega.eval.sharpe import (
    _normal_cdf,
    compute_sharpe,
    compute_sharpe_confidence_interval,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sharpe_is_significant(
    returns: Sequence[float],
    confidence: float = 0.95,
    min_sharpe: float = 0.0,
    n_bootstrap: int = 1000,
    periods_per_year: int = 252,
    seed: int = 42,
) -> tuple[bool, float, tuple[float, float]]:
    """
    Test whether a strategy's Sharpe ratio is significantly above min_sharpe.

    Uses a bootstrap confidence interval: if the CI lower bound exceeds
    min_sharpe, the Sharpe is considered statistically significant.

    Parameters
    ----------
    returns         : Per-period returns.
    confidence      : Confidence level (default 0.95 → 95% CI).
    min_sharpe      : Minimum Sharpe to be considered significant (default 0.0).
    n_bootstrap     : Number of bootstrap resamples.
    periods_per_year: Annualisation factor.
    seed            : RNG seed for reproducibility.

    Returns
    -------
    (is_significant, point_estimate, (ci_lower, ci_upper))
    """
    r = list(returns)
    if len(r) < 2:
        return (False, 0.0, (0.0, 0.0))

    point = compute_sharpe(r, periods_per_year=periods_per_year)
    ci = compute_sharpe_confidence_interval(
        r,
        confidence=confidence,
        n_bootstrap=n_bootstrap,
        periods_per_year=periods_per_year,
        seed=seed,
    )
    lo, hi = ci
    is_significant = lo > min_sharpe
    return (is_significant, point, (lo, hi))


def sharpe_difference_significant(
    returns_a: Sequence[float],
    returns_b: Sequence[float],
    confidence: float = 0.95,
    n_bootstrap: int = 10000,
    periods_per_year: int = 252,
    seed: int = 42,
) -> tuple[bool, float, tuple[float, float]]:
    """
    Paired bootstrap test: is Sharpe(A) significantly different from Sharpe(B)?

    The point estimate is Sharpe(A) - Sharpe(B) on the original series.
    The CI is built by resampling paired (a_i, b_i) observations and computing
    the Sharpe difference on each bootstrap sample.

    Parameters
    ----------
    returns_a, returns_b : Per-period returns (same length).
    confidence           : Confidence level (default 0.95).
    n_bootstrap          : Number of bootstrap resamples (default 10000).
    periods_per_year     : Annualisation factor.
    seed                 : RNG seed for reproducibility.

    Returns
    -------
    (is_significant, sharpe_difference, (ci_lower, ci_upper))
    """
    a = [float(x) for x in returns_a]
    b = [float(x) for x in returns_b]
    n = min(len(a), len(b))

    if n < 4:
        return (False, 0.0, (0.0, 0.0))

    a = a[:n]
    b = b[:n]

    sharpe_a = compute_sharpe(a, periods_per_year=periods_per_year)
    sharpe_b = compute_sharpe(b, periods_per_year=periods_per_year)
    diff_estimate = sharpe_a - sharpe_b

    # Paired bootstrap: resample indices, compute Sharpe difference on each sample
    rng = random.Random(seed)
    indices = list(range(n))
    bootstrap_diffs: list[float] = []
    for _ in range(n_bootstrap):
        sample_idx = [rng.choice(indices) for _ in range(n)]
        sample_a = [a[i] for i in sample_idx]
        sample_b = [b[i] for i in sample_idx]
        sr_a = compute_sharpe(sample_a, periods_per_year=periods_per_year)
        sr_b = compute_sharpe(sample_b, periods_per_year=periods_per_year)
        bootstrap_diffs.append(sr_a - sr_b)

    bootstrap_diffs.sort()
    alpha = 1.0 - confidence
    lo_idx = max(0, math.floor(alpha / 2 * n_bootstrap))
    hi_idx = min(n_bootstrap - 1, math.ceil((1.0 - alpha / 2) * n_bootstrap) - 1)
    ci_lo = bootstrap_diffs[lo_idx]
    ci_hi = bootstrap_diffs[hi_idx]

    # Significant if CI doesn't straddle zero
    is_significant = ci_lo > 0.0 or ci_hi < 0.0

    return (is_significant, diff_estimate, (ci_lo, ci_hi))


def deflated_sharpe_ratio(
    sharpe: float,
    n_trials: int,
    variance_of_sharpes: float,
    skew: float,
    kurtosis: float,
) -> float:
    """
    Deflated Sharpe Ratio (DSR) — Bailey & Lopez de Prado 2014.

    Corrects an observed Sharpe ratio for selection bias introduced by
    trying n_trials different parameter configurations or strategies.

    The DSR is the probability that the strategy's Sharpe is genuinely
    positive after accounting for multiple testing.

    Parameters
    ----------
    sharpe             : Observed (best) Sharpe ratio.
    n_trials           : Number of strategy configurations / backtests tried.
    variance_of_sharpes: Variance of the SR estimates across the n_trials.
    skew               : Skewness of the strategy's return distribution.
    kurtosis           : Excess kurtosis of the strategy's return distribution.

    Returns
    -------
    DSR in [0, 1] — probability that SR is genuinely positive.
    """
    n_trials = max(1, int(n_trials))
    sr_std = math.sqrt(max(0.0, variance_of_sharpes))

    # Expected maximum SR under the null (all strategies have SR=0)
    # Using the Euler-Mascheroni approximation for E[max of n standard normals]
    # from Bailey & Lopez de Prado 2014, eq. (9)
    euler_gamma = 0.5772156649015328
    if n_trials == 1:
        # No selection bias with a single trial
        sr_benchmark = 0.0
    else:
        # E[SR*] = sr_std * E[max_n], where E[max_n] uses the extreme value approx
        inv_cdf_1 = _normal_ppf(1.0 - 1.0 / n_trials)
        inv_cdf_2 = _normal_ppf(1.0 - 1.0 / (n_trials * math.e))
        e_max = (1.0 - euler_gamma) * inv_cdf_1 + euler_gamma * inv_cdf_2
        sr_benchmark = sr_std * e_max

    # Non-normality correction: SE adjustment for return skewness and kurtosis
    # Denominator = sqrt(1 - skew*SR + (kurtosis-1)/4 * SR^2)
    # (kurtosis here is excess kurtosis; for normal distribution = 0)
    excess_kurt = kurtosis - 3.0 if kurtosis >= 3.0 else 0.0
    denom_sq = 1.0 - skew * sharpe + (excess_kurt + 2.0) / 4.0 * sharpe**2
    denom_sq = max(1e-12, denom_sq)
    correction = math.sqrt(denom_sq)

    z = (sharpe - sr_benchmark) / correction
    return _normal_cdf(z)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normal_ppf(p: float) -> float:
    """
    Approximate normal quantile (inverse CDF) using rational approximation.

    Accurate to ~4 decimal places for p in (0.0001, 0.9999).
    Uses Peter Acklam's algorithm.
    """
    p = max(1e-12, min(1.0 - 1e-12, p))

    # Rational approximation coefficients (Acklam)
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]

    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        x = (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
        )
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )

    return x
