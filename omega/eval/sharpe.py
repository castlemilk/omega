"""Canonical Sharpe ratio implementation for the Omega project.

Formula:
  - Excess returns: r_i - (risk_free / periods_per_year)
  - Sample standard deviation (N-1 denominator)
  - Annualised: (mean_excess / sample_std) * sqrt(periods_per_year)
"""

from __future__ import annotations

import math


def sharpe_ratio(
    returns: list[float],
    risk_free: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """Annualised Sharpe ratio.

    Args:
        returns: Sequence of per-period returns (e.g. daily P&L fractions).
        risk_free: Annualised risk-free rate (e.g. 0.05 for 5%). Converted to
                   per-period by dividing by *periods_per_year*.
        periods_per_year: Trading periods in a year. 252 for daily, 52 for
                          weekly, 12 for monthly, etc.

    Returns:
        Annualised Sharpe ratio, or 0.0 when fewer than 2 observations or
        zero volatility.
    """
    if len(returns) < 2:
        return 0.0

    daily_rf = risk_free / periods_per_year
    excess = [r - daily_rf for r in returns]

    mean_e = sum(excess) / len(excess)
    # Sample variance (N-1)
    var = sum((x - mean_e) ** 2 for x in excess) / (len(excess) - 1)
    std = math.sqrt(var) if var > 0 else 0.0

    if std == 0.0:
        return 0.0

    return mean_e / std * math.sqrt(periods_per_year)
