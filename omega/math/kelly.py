"""
omega.math.kelly
~~~~~~~~~~~~~~~~
Kelly criterion position sizer with fat-tail and multi-asset extensions.

All position sizing in the Vectora system flows through this module.
Use fractional Kelly by default to account for model uncertainty.

Mathematical Background
-----------------------
Standard Kelly (single asset, binary outcome):

    f* = (p·b - q) / b

where p = win probability, q = 1-p, b = net win/loss ratio (e.g. 2.0 means
you win $2 for every $1 risked).

Fat-Tail Adjustment (Fernholz-style kurtosis penalty):

    f_adjusted = f* x sqrt(3/kappa)

where κ = excess kurtosis of recent returns. For a normal distribution κ = 3,
so √(3/3) = 1 (no adjustment). Leptokurtic returns (κ > 3) shrink the position.
Returns with κ ≤ 0 are clamped to a small positive value to avoid division by zero.

Multi-Asset Kelly (continuous-time, log-optimal portfolio):

    f⃗* = Σ⁻¹ · μ⃗

where μ⃗ is the vector of expected excess returns and Σ is the covariance matrix
of returns. Assumes returns are jointly normally distributed.

Fractional Kelly:
    Apply a fraction alpha in (0, 1] to reduce variance at the cost of lower growth:

    f_frac = alpha * f*

    alpha = 0.5 (half-Kelly) is common in practice.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def kelly_standard(
    p: float,
    b: float,
) -> float:
    """
    Compute the standard Kelly fraction for a single binary bet.

    Parameters
    ----------
    p : Win probability in (0, 1).
    b : Net win/loss ratio > 0.  A bet that pays $b per $1 risked.

    Returns
    -------
    Optimal fraction f* ∈ [-1, 1].  Negative means the bet should not be taken
    (negative expected log-growth). Caller is responsible for clamping to [0, 1].

    Raises
    ------
    ValueError
        If p not in (0, 1) or b ≤ 0.

    Examples
    --------
    >>> kelly_standard(0.6, 1.0)  # 60/40 coin flip, even payout
    0.2
    """
    if not (0 < p < 1):
        raise ValueError(f"p must be in (0, 1), got {p}")
    if b <= 0:
        raise ValueError(f"b must be > 0, got {b}")

    q = 1.0 - p
    return (p * b - q) / b


def kelly_fat_tail(
    p: float,
    b: float,
    kurtosis: float,
) -> float:
    """
    Kelly fraction adjusted for fat tails via excess kurtosis.

    Uses the correction factor √(3/κ) where κ is the excess kurtosis of returns.
    For normally distributed returns (κ = 3) the factor is 1 (no adjustment).
    Heavier tails (κ > 3) reduce the fraction proportionally.

    Parameters
    ----------
    p        : Win probability in (0, 1).
    b        : Net win/loss ratio > 0.
    kurtosis : Excess kurtosis of recent returns (κ). Values ≤ 0 are clamped
               to 0.01 to prevent division by zero.

    Returns
    -------
    Adjusted Kelly fraction. Always ≤ kelly_standard(p, b).

    Raises
    ------
    ValueError
        If p not in (0, 1) or b ≤ 0.
    """
    f_star = kelly_standard(p, b)
    kappa = max(kurtosis, 0.01)
    adjustment = np.sqrt(3.0 / kappa)
    return float(f_star * adjustment)


def kelly_multi_asset(
    mu: Sequence[float],
    cov: Sequence[Sequence[float]],
) -> np.ndarray:
    """
    Compute the log-optimal Kelly allocation for a multi-asset portfolio.

    Solves the continuous-time Kelly problem:

        f⃗* = Σ⁻¹ · μ⃗

    Parameters
    ----------
    mu  : Vector of expected excess returns, shape (n,).
    cov : Covariance matrix of returns, shape (n, n). Must be positive definite.

    Returns
    -------
    ndarray of shape (n,) — optimal fractional allocations per asset.
    Values may exceed 1 or be negative (long/short); caller should apply caps.

    Raises
    ------
    ValueError
        If dimensions are inconsistent or the covariance matrix is singular.

    Notes
    -----
    For numerical stability, we use np.linalg.lstsq rather than np.linalg.inv.
    """
    mu_arr = np.asarray(mu, dtype=float)
    cov_arr = np.asarray(cov, dtype=float)

    n = len(mu_arr)
    if cov_arr.shape != (n, n):
        raise ValueError(
            f"cov must be shape ({n}, {n}) to match mu of length {n}, got {cov_arr.shape}"
        )

    # Use lstsq for numerical robustness vs. explicit inversion
    result, _, rank, _ = np.linalg.lstsq(cov_arr, mu_arr, rcond=None)
    if rank < n:
        raise ValueError(
            f"Covariance matrix is rank-deficient (rank={rank}, n={n}). "
            "Cannot compute Kelly allocation."
        )
    return np.asarray(result)


def rolling_kurtosis(
    returns: Sequence[float],
    window: int,
) -> np.ndarray:
    """
    Compute rolling excess kurtosis over a fixed window.

    Excess kurtosis = kurtosis - 3, so a normal distribution gives 0.
    However for fat-tail adjustment we use the raw kurtosis (not excess),
    so we return raw kurtosis = excess + 3 for compatibility with kelly_fat_tail.

    Parameters
    ----------
    returns : Sequence of per-period returns, oldest first.
    window  : Rolling window length in periods. Must be ≥ 4.

    Returns
    -------
    ndarray of shape (len(returns),) with NaN for the first (window-1) positions.

    Raises
    ------
    ValueError
        If window < 4 (need at least 4 observations for kurtosis).
    """
    if window < 4:
        raise ValueError(f"window must be ≥ 4 for kurtosis, got {window}")

    r = np.asarray(returns, dtype=float)
    n = len(r)
    result = np.full(n, np.nan)

    for i in range(window - 1, n):
        window_data = r[i - window + 1 : i + 1]
        mu = np.mean(window_data)
        sigma = np.std(window_data, ddof=1)
        if sigma == 0:
            result[i] = 3.0  # treat constant series as normal
            continue
        # Fisher's definition: excess kurtosis = m4/sigma^4 - 3
        m4 = np.mean((window_data - mu) ** 4)
        excess_kurtosis = m4 / sigma**4 - 3.0
        # Return raw kurtosis for the fat-tail formula (κ = excess + 3)
        result[i] = excess_kurtosis + 3.0

    return result


def kelly_fractional(
    p: float,
    b: float,
    fraction: float = 0.5,
    kurtosis: float | None = None,
    max_position: float = 0.25,
) -> float:
    """
    Compute a risk-managed Kelly fraction combining all constraints.

    Applies in order:
    1. Standard Kelly: f* = (p·b - q) / b
    2. Fat-tail adjustment if kurtosis is provided: f* x sqrt(3/kappa)
    3. Fractional scaling: f* x fraction
    4. Cap at max_position

    Parameters
    ----------
    p            : Win probability in (0, 1).
    b            : Net win/loss ratio > 0.
    fraction     : Fractional Kelly multiplier in (0, 1]. Default 0.5 (half-Kelly).
    kurtosis     : Excess kurtosis for fat-tail adjustment. None skips adjustment.
    max_position : Maximum allowed position as a fraction of capital. Default 0.25.

    Returns
    -------
    Final position size in [0, max_position]. Returns 0.0 if standard Kelly is
    non-positive (bet has negative expected log-growth).

    Raises
    ------
    ValueError
        If fraction not in (0, 1], max_position not in (0, 1], or other
        parameter constraints are violated.
    """
    if not (0 < fraction <= 1.0):
        raise ValueError(f"fraction must be in (0, 1], got {fraction}")
    if not (0 < max_position <= 1.0):
        raise ValueError(f"max_position must be in (0, 1], got {max_position}")

    if kurtosis is not None:
        f = kelly_fat_tail(p, b, kurtosis)
    else:
        f = kelly_standard(p, b)

    if f <= 0:
        return 0.0

    f = f * fraction
    return float(min(f, max_position))
