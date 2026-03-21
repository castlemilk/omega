"""
omega.math
~~~~~~~~~~
Pure mathematical primitives for probabilistic signal evaluation and position sizing.

Modules
-------
brier     : Brier score, calibration curves, signal source ranking
kelly     : Kelly criterion (standard, fat-tail adjusted, multi-asset)
bayesian  : Bayesian signal aggregation with log-odds representation
"""

from omega.math.bayesian import (
    aggregate_signals,
    bayesian_update,
    entropy,
    log_odds,
    log_odds_to_prob,
    posterior_summary,
)
from omega.math.brier import (
    brier_score,
    brier_score_ew,
    calibration_curve,
    rank_sources,
)
from omega.math.kelly import (
    kelly_fat_tail,
    kelly_fractional,
    kelly_multi_asset,
    kelly_standard,
    rolling_kurtosis,
)

__all__ = [
    "aggregate_signals",
    "bayesian_update",
    "brier_score",
    "brier_score_ew",
    "calibration_curve",
    "entropy",
    "kelly_fat_tail",
    "kelly_fractional",
    "kelly_multi_asset",
    "kelly_standard",
    "log_odds",
    "log_odds_to_prob",
    "posterior_summary",
    "rank_sources",
    "rolling_kurtosis",
]
