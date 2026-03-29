"""
omega.nodes.victoria.conformal_calibrator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Split-conformal prediction calibrator for Victoria signals.

Overview
--------
Conformal prediction is a distribution-free framework that wraps any
point predictor and produces prediction intervals with **guaranteed finite-
sample coverage**: for a calibration set of size n, the interval covers the
true outcome at least (1 - α) fraction of the time, no distributional
assumptions required.

Split-conformal algorithm
-------------------------
1. Split history into calibration set (last ``cal_size`` cycles) and
   remainder (training).
2. For each calibration cycle t, compute the nonconformity score:

       s_t = |forecast_t - realised_t|

3. Sort {s_1, ..., s_n}.  For coverage level (1 - α), the conformal
   quantile is:

       q̂ = s_{⌈(n+1)(1-α)⌉}     (or +∞ if index exceeds n)

4. For new forecast ŷ_{n+1}, the prediction interval is:

       [ŷ_{n+1} - q̂,  ŷ_{n+1} + q̂]

Adaptation for online trading
------------------------------
Because we receive one new observation per cycle (online setting), we use
a **sliding calibration window** of fixed size ``cal_size``.  This makes
the calibrator non-exchangeable (strictly speaking, exchangeability is
required for the coverage guarantee), but empirically a rolling window
performs well and degrades gracefully.

To maintain *approximate* coverage guarantees online we use the
EnbPI (Ensemble Prediction Intervals) trick: we track the running residual
and inflate/deflate the quantile if recent coverage is above or below target.

Usage
-----
    cal = ConformalCalibrator(alpha=0.1, cal_size=50)

    # Update with each realised return
    cal.update(forecast=0.42, realised=0.38)

    # Get an interval for a new forecast
    lo, mid, hi = cal.predict(forecast=0.50)

    # Check current coverage quality
    info = cal.coverage_info()

References
----------
- Vovk, Gammerman, Shafer (2005) "Algorithmic Learning in a Random World"
- Angelopoulos & Bates (2023) "A Gentle Introduction to Conformal Prediction"
- Xu & Xie (2023) "Conformal Prediction for Time Series"
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import NamedTuple

logger = logging.getLogger("omega.nodes.victoria.conformal_calibrator")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_ALPHA = 0.10      # 90 % nominal coverage
_DEFAULT_CAL_SIZE = 50     # calibration window (cycles)
_MIN_CAL_SAMPLES = 5       # minimum samples before intervals are non-trivial
_COVERAGE_ADAPT_RATE = 0.05  # adaptation step when coverage drifts


class PredictionInterval(NamedTuple):
    lower: float
    mid: float
    upper: float
    quantile: float    # the conformal quantile q̂ used
    coverage_target: float  # 1 - alpha


@dataclass
class _CalibrationPoint:
    forecast: float
    realised: float
    score: float  # |forecast - realised|


class ConformalCalibrator:
    """
    Online split-conformal calibrator with adaptive coverage correction.

    Parameters
    ----------
    alpha :    Miscoverage level.  Nominal coverage = 1 - alpha (default 0.10).
    cal_size : Rolling calibration window size (default 50).
    """

    def __init__(
        self,
        alpha: float = _DEFAULT_ALPHA,
        cal_size: int = _DEFAULT_CAL_SIZE,
    ) -> None:
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        self._alpha = alpha
        self._cal_size = cal_size
        self._target_coverage = 1.0 - alpha

        # Sliding calibration window
        self._cal: deque[_CalibrationPoint] = deque(maxlen=cal_size)

        # Adaptive correction to the raw conformal quantile
        self._alpha_adj = alpha  # tracks realised miscoverage

        # Rolling coverage tracking (last 20 intervals)
        self._covered_history: deque[bool] = deque(maxlen=20)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, forecast: float, realised: float) -> None:
        """
        Add a new (forecast, realised) pair to the calibration window.

        Call this once per cycle after the outcome is known.
        """
        if not (math.isfinite(forecast) and math.isfinite(realised)):
            return
        score = abs(forecast - realised)
        pt = _CalibrationPoint(forecast=forecast, realised=realised, score=score)
        self._cal.append(pt)

        # Track coverage for the *previous* interval (if we had predicted one)
        # We use the current point's score vs the previous quantile as a proxy.
        if len(self._cal) >= _MIN_CAL_SAMPLES:
            q = self._conformal_quantile(self._alpha_adj)
            covered = score <= q
            self._covered_history.append(covered)
            self._adapt_alpha()

    def predict(self, forecast: float) -> PredictionInterval:
        """
        Return a conformal prediction interval for ``forecast``.

        Returns a symmetric interval [forecast - q̂, forecast + q̂].
        Falls back to a wide interval when calibration data is insufficient.
        """
        if not math.isfinite(forecast):
            return PredictionInterval(
                lower=float("-inf"),
                mid=forecast,
                upper=float("inf"),
                quantile=float("inf"),
                coverage_target=self._target_coverage,
            )

        q = self._conformal_quantile(self._alpha_adj)
        return PredictionInterval(
            lower=forecast - q,
            mid=forecast,
            upper=forecast + q,
            quantile=q,
            coverage_target=self._target_coverage,
        )

    def coverage_info(self) -> dict:
        """Return a snapshot of the calibrator's current state."""
        n = len(self._cal)
        covered = list(self._covered_history)
        empirical_coverage = sum(covered) / len(covered) if covered else float("nan")
        q = self._conformal_quantile(self._alpha_adj)
        return {
            "cal_samples": n,
            "nominal_coverage": self._target_coverage,
            "empirical_coverage": empirical_coverage,
            "current_quantile": q,
            "alpha_raw": self._alpha,
            "alpha_adj": self._alpha_adj,
            "interval_width": 2 * q if math.isfinite(q) else float("inf"),
        }

    def uncertainty_score(self, forecast: float) -> float:
        """
        Map the current prediction interval width to a [0, 1] uncertainty score.

        score = 0.0 → narrow interval (high certainty)
        score = 1.0 → very wide interval (high uncertainty)
        """
        q = self._conformal_quantile(self._alpha_adj)
        if not math.isfinite(q) or q <= 0.0:
            return 1.0 if not math.isfinite(q) else 0.0
        # Normalise by |forecast| to make scale-invariant; floor at small value
        ref = max(abs(forecast), 0.01)
        relative_width = (2 * q) / ref
        return float(min(1.0, math.tanh(relative_width)))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _conformal_quantile(self, alpha: float) -> float:
        """
        Compute the (1 - alpha)(1 + 1/n) quantile of the calibration scores.

        Returns +inf when there are fewer than _MIN_CAL_SAMPLES observations.
        """
        n = len(self._cal)
        if n < _MIN_CAL_SAMPLES:
            return float("inf")

        scores = sorted(pt.score for pt in self._cal)
        # Conformal quantile index: ⌈(n+1)(1-α)⌉ − 1  (0-indexed)
        level = 1.0 - alpha
        idx = math.ceil((n + 1) * level) - 1
        if idx >= n:
            return float("inf")
        return float(scores[idx])

    def _adapt_alpha(self) -> None:
        """
        EnbPI-style adaptation: nudge alpha_adj if empirical coverage drifts.

        If empirical coverage is below target (miscovering) → decrease alpha_adj
        to widen intervals.  If above target → increase alpha_adj to narrow.
        """
        covered = list(self._covered_history)
        if len(covered) < 5:
            return
        empirical_cov = sum(covered) / len(covered)
        gap = empirical_cov - self._target_coverage
        # Nudge in proportion to the gap
        self._alpha_adj -= _COVERAGE_ADAPT_RATE * gap
        # Clamp to [alpha/4, 4*alpha] to prevent runaway
        self._alpha_adj = max(self._alpha / 4.0, min(4.0 * self._alpha, self._alpha_adj))
