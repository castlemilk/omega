"""
omega.nodes.victoria.wasserstein_regime
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Wasserstein-distance-based regime detector.

Replaces / augments the HMM regime detector which suffers from low confidence
(< 50%) because HMM assumes Gaussian distributions and struggles when the
signal distributions don't overlap cleanly.

Wasserstein distance (Earth Mover's Distance) is more robust because:
  - No hidden state assumption — directly measures distance to known regimes
  - Works with any distribution shape (HMM assumes Gaussian)
  - Continuous confidence (not binary state assignment)
  - Can incorporate labeled data to learn regime centroids over time

Algorithm
---------
1. Maintain a rolling window of composite signal vectors (one per cycle).
2. For each candidate regime (bull, bear, sideways), compute the average
   per-dimension W_1 distance between the recent empirical distribution
   and the regime centroid.
3. Convert distances to probabilities via softmax (closer = higher prob).
4. Regime = argmax; confidence = max prob.

Signal vector uses the 11 composite SIGNAL_NAMES from victoria_node.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger("omega.nodes.victoria.wasserstein_regime")

try:
    from scipy.stats import wasserstein_distance as _scipy_wasserstein

    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False
    logger.warning("scipy not available — falling back to simple mean-distance approximation")

# ---------------------------------------------------------------------------
# Signal names (must match victoria_node.SIGNAL_NAMES)
# ---------------------------------------------------------------------------

SIGNAL_NAMES = [
    "basic_signals",
    "order_flow",
    "cross_asset",
    "microstructure",
    "sentiment",
    "vrp",
    "market_data",
    "onchain",
    "long_short_ratio",
    "btc_dominance",
    "alt_data",
]

N_SIGNALS = len(SIGNAL_NAMES)

# Regime labels
BULL = "bull"
BEAR = "bear"
SIDEWAYS = "sideways"
REGIMES = [BULL, BEAR, SIDEWAYS]

# Bootstrap centroids: prior belief about what each regime looks like.
# Values are per-signal priors in [-1, +1] space.
# These are overwritten once enough labeled data accumulates.
_BULL_PRIOR = np.full(N_SIGNALS, 0.30)
_BEAR_PRIOR = np.full(N_SIGNALS, -0.30)
_SIDEWAYS_PRIOR = np.zeros(N_SIGNALS)

# Softmax temperature: higher = softer probabilities
_SOFTMAX_TEMP = 1.0


# ---------------------------------------------------------------------------
# WassersteinRegimeDetector
# ---------------------------------------------------------------------------


@dataclass
class RegimeResult:
    regime: str
    confidence: float
    bull_prob: float
    bear_prob: float
    sideways_prob: float
    d_bull: float
    d_bear: float
    d_sideways: float
    source: str = "wasserstein"


class WassersteinRegimeDetector:
    """
    Wasserstein-distance regime detector.

    Parameters
    ----------
    window : int
        Rolling window of signal vectors to maintain.
    min_samples : int
        Minimum observations before producing non-fallback estimates.
    """

    def __init__(self, window: int = 50, min_samples: int = 20) -> None:
        self._window = window
        self._min_samples = min_samples
        self._signal_history: deque[np.ndarray] = deque(maxlen=window)
        self._regime_history: deque[str] = deque(maxlen=100)

        # Regime centroids: updated via update_centroids()
        self._centroids: dict[str, np.ndarray] = {
            BULL: _BULL_PRIOR.copy(),
            BEAR: _BEAR_PRIOR.copy(),
            SIDEWAYS: _SIDEWAYS_PRIOR.copy(),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, signal_values: dict[str, float]) -> RegimeResult:
        """
        Ingest one cycle's signal values and return regime estimate.

        Parameters
        ----------
        signal_values : dict
            {signal_name: float_value} — values in [-1, +1].
            Missing signals default to 0.0.
        """
        vec = np.array([signal_values.get(s, 0.0) for s in SIGNAL_NAMES], dtype=float)
        self._signal_history.append(vec)

        if len(self._signal_history) < self._min_samples:
            return self._fallback(len(self._signal_history))

        recent = np.array(list(self._signal_history)[-self._min_samples :])

        d_bull = self._wasserstein_to_regime(recent, BULL)
        d_bear = self._wasserstein_to_regime(recent, BEAR)
        d_sideways = self._wasserstein_to_regime(recent, SIDEWAYS)

        distances = np.array([d_bull, d_bear, d_sideways])
        probs = self._softmax(-distances / _SOFTMAX_TEMP)

        regime = REGIMES[int(np.argmax(probs))]
        confidence = float(np.max(probs))

        self._regime_history.append(regime)

        result = RegimeResult(
            regime=regime,
            confidence=confidence,
            bull_prob=float(probs[0]),
            bear_prob=float(probs[1]),
            sideways_prob=float(probs[2]),
            d_bull=float(d_bull),
            d_bear=float(d_bear),
            d_sideways=float(d_sideways),
        )
        logger.debug(
            "wasserstein regime=%s conf=%.3f bull=%.3f bear=%.3f sideways=%.3f "
            "d_bull=%.4f d_bear=%.4f d_side=%.4f",
            regime,
            confidence,
            probs[0],
            probs[1],
            probs[2],
            d_bull,
            d_bear,
            d_sideways,
        )
        return result

    def update_centroids(self, labeled_data: dict[str, list[list[float]]]) -> None:
        """
        Update regime centroids from labeled historical data.

        Parameters
        ----------
        labeled_data : dict
            {regime_name: [[signal_vec], ...]} — list of signal vectors per regime.
        """
        for regime, vectors in labeled_data.items():
            if regime not in self._centroids:
                continue
            if len(vectors) >= 10:
                mat = np.array(vectors, dtype=float)
                self._centroids[regime] = np.mean(mat, axis=0)
                logger.info("Updated %s centroid from %d samples", regime, len(vectors))

    @property
    def regime_history(self) -> list[str]:
        return list(self._regime_history)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _wasserstein_to_regime(self, recent_data: np.ndarray, regime: str) -> float:
        """
        Compute average per-dimension W_1 distance between recent signal
        distribution and the regime centroid.

        recent_data : shape (n_samples, n_signals)
        """
        centroid = self._centroids[regime]
        n_dims = recent_data.shape[1]
        w_total = 0.0

        for dim in range(n_dims):
            col = recent_data[:, dim]
            if _SCIPY_AVAILABLE:
                # Full W_1 between empirical distribution and point mass at centroid
                ref = np.full(len(col), centroid[dim])
                w_total += float(_scipy_wasserstein(col, ref))
            else:
                # Fallback: mean absolute deviation from centroid
                w_total += float(np.mean(np.abs(col - centroid[dim])))

        return w_total / n_dims

    @staticmethod
    def _softmax(x: np.ndarray) -> np.ndarray:
        x = x - np.max(x)  # numerical stability
        e = np.exp(x)
        return e / e.sum()

    def _fallback(self, n_obs: int) -> RegimeResult:
        return RegimeResult(
            regime=SIDEWAYS,
            confidence=0.0,
            bull_prob=1 / 3,
            bear_prob=1 / 3,
            sideways_prob=1 / 3,
            d_bull=0.0,
            d_bear=0.0,
            d_sideways=0.0,
            source=f"warmup({n_obs}/{self._min_samples})",
        )
