"""
Wasserstein regime distance signal for Victoria.

Computes the 1-Wasserstein distance (Earth Mover's Distance) between the
current rolling return distribution and pre-stored regime archetypes. Replaces
bear_prob thresholds with a continuous, geometry-aware regime classifier that
is robust to distributional shifts not captured by a single scalar.

Archetypes (fitted once from labelled historical data, or bootstrap defaults):
    "crisis"   — fat left tail, negative mean, elevated std (2022 H1 style)
    "normal"   — near-zero mean, moderate std
    "trending" — fat right tail, positive mean, moderate std

Output per compute() call:
    SignalValue with:
        value      = w2_normal_distance normalised to [-1, 1] (negative = close
                     to normal, positive = far from normal / crisis-like)
        confidence = 1 - (w2_crisis / (w2_crisis + w2_normal + ε))
        regime_tag = closest archetype label
        raw        = {
            "w2_crisis":   float,
            "w2_normal":   float,
            "w2_trend":    float,
            "closest":     str,
            "n_returns":   int,
        }

Usage:
    sig = WassersteinRegimeSignal(window=60)
    sig.update_returns(recent_returns)   # list[float] or np.ndarray, len >= 20
    sv = sig.compute()

Feature flag: controlled by VictoriaFeatures.wasserstein_regime_enabled.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from omega.nodes.victoria.signals_advanced import SignalValue

logger = logging.getLogger("omega.nodes.victoria.signals.wasserstein_regime")

# Bootstrap archetype parameters (mean, std).
# Intentionally coarse defaults — update_archetypes() lets callers supply
# historically-fitted quantile arrays from labelled data.
# Crisis: negative mean, fat tails (high std)
# Normal: near-zero mean, tight std
# Trending: positive mean, moderate std
_DEFAULT_ARCHETYPES: dict[str, dict[str, float]] = {
    "crisis":   {"mean": -0.030, "std": 0.050},
    "normal":   {"mean":  0.001, "std": 0.014},
    "trending": {"mean":  0.022, "std": 0.020},
}

# Quantile grid used for EMD approximation (CDF inversion method).
_N_QUANTILES = 200
_Q = np.linspace(0.0, 1.0, _N_QUANTILES + 2)[1:-1]  # avoid 0/1 for ppf


class WassersteinRegimeSignal:
    """
    Wasserstein-1 distance to crisis / normal / trending return archetypes.

    Parameters
    ----------
    window:
        Number of recent returns to use per compute(). 60 = ~2 months of daily.
    min_obs:
        Minimum observations before returning a valid signal.
    """

    def __init__(self, window: int = 60, min_obs: int = 20) -> None:
        self._window = int(window)
        self._min_obs = int(min_obs)
        self._returns: list[float] = []
        self._archetypes: dict[str, np.ndarray] = {}
        self._build_default_archetypes()

    # ── Public interface ──────────────────────────────────────────────────────

    def update_returns(self, returns: list[float] | np.ndarray) -> None:
        """Replace internal buffer with the latest return series.

        Callers pass the full BTC return window each cycle; earlier `extend`
        semantics caused buffer-bloat with duplicates in live mode where the
        same series is re-passed every short cycle. See backtest-live-gap-v161.md.
        """
        arr = list(float(x) for x in np.asarray(returns).ravel() if np.isfinite(x))
        self._returns = arr[-self._window * 3:]

    def update_archetypes(self, crisis: np.ndarray, normal: np.ndarray, trending: np.ndarray) -> None:
        """
        Supply historically-fitted quantile arrays (length = _N_QUANTILES each).
        Call once during initialisation from labelled historical data.
        """
        assert len(crisis) == len(normal) == len(trending) == _N_QUANTILES
        self._archetypes = {
            "crisis":   np.asarray(crisis, dtype=float),
            "normal":   np.asarray(normal, dtype=float),
            "trending": np.asarray(trending, dtype=float),
        }

    def compute(self, market_data: dict[str, Any] | None = None) -> SignalValue:
        """Compute Wasserstein distances and return a SignalValue."""
        recent = np.array(self._returns[-self._window:], dtype=float)
        recent = recent[np.isfinite(recent)]

        if len(recent) < self._min_obs:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="insufficient_data",
                raw={"n_returns": len(recent), "w2_crisis": 0.0, "w2_normal": 0.0, "w2_trend": 0.0, "closest": "unknown"},
            )

        current_q = np.quantile(recent, _Q)

        distances: dict[str, float] = {}
        for label, archetype_q in self._archetypes.items():
            distances[label] = float(np.mean(np.abs(current_q - archetype_q)))

        closest = min(distances, key=distances.get)  # type: ignore[arg-type]

        w2_crisis = distances.get("crisis", 0.0)
        w2_normal = distances.get("normal", 0.0)
        w2_trend  = distances.get("trending", 0.0)
        total = w2_crisis + w2_normal + w2_trend + 1e-9

        # value: how far from "normal" we are, normalised to [-1, 1]
        # negative = normal-like, positive = crisis-like
        normalised_dist = (w2_normal - w2_crisis) / (w2_normal + w2_crisis + 1e-9)
        value = float(np.clip(normalised_dist, -1.0, 1.0))

        # confidence: inversely proportional to distance from closest archetype
        conf_raw = 1.0 - (distances[closest] / (total / 3.0 + 1e-9))
        confidence = float(np.clip(conf_raw, 0.0, 1.0))

        return SignalValue(
            value=value,
            confidence=confidence,
            regime_tag=closest,
            raw={
                "w2_crisis": round(w2_crisis, 6),
                "w2_normal": round(w2_normal, 6),
                "w2_trend":  round(w2_trend, 6),
                "closest":   closest,
                "n_returns": len(recent),
            },
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_default_archetypes(self) -> None:
        """Generate archetype quantile arrays from Gaussian default parameters."""
        from scipy.stats import norm  # type: ignore[import]

        archetypes: dict[str, np.ndarray] = {}
        for label, p in _DEFAULT_ARCHETYPES.items():
            archetypes[label] = norm.ppf(_Q, loc=p["mean"], scale=p["std"])
        self._archetypes = archetypes

    @classmethod
    def fit_archetypes_from_data(
        cls,
        labelled_returns: dict[str, list[float]],
    ) -> dict[str, np.ndarray]:
        """
        Fit quantile-based archetypes from labelled historical returns.

        Parameters
        ----------
        labelled_returns:
            e.g. {"crisis": [...], "normal": [...], "trending": [...]}

        Returns
        -------
        dict mapping label → quantile array (length _N_QUANTILES).
        """
        result: dict[str, np.ndarray] = {}
        for label, rets in labelled_returns.items():
            arr = np.array(rets, dtype=float)
            arr = arr[np.isfinite(arr)]
            if len(arr) < 30:
                logger.warning("fit_archetypes: too few samples for '%s' (%d)", label, len(arr))
                continue
            result[label] = np.quantile(arr, _Q)
        return result


# ── Standalone test ───────────────────────────────────────────────────────────

def _self_test() -> None:
    import sys

    rng = np.random.default_rng(0)

    # Simulate crisis returns: strongly negative with fat tails
    crisis_rets = rng.normal(-0.03, 0.05, 80).tolist()
    normal_rets = rng.normal(0.001, 0.018, 80).tolist()
    trend_rets  = rng.normal(0.02, 0.02, 80).tolist()

    sig = WassersteinRegimeSignal(window=60, min_obs=20)

    def check(label: str, returns: list[float], expected_closest: str) -> None:
        sig2 = WassersteinRegimeSignal(window=60, min_obs=20)
        sig2.update_returns(returns)
        sv = sig2.compute()
        print(
            f"{label:10s}  closest={sv.regime_tag:10s}  "
            f"value={sv.value:+.3f}  conf={sv.confidence:.3f}  "
            f"w2_crisis={sv.raw['w2_crisis']:.5f}  w2_normal={sv.raw['w2_normal']:.5f}"
        )
        assert sv.regime_tag == expected_closest, (
            f"{label}: expected {expected_closest}, got {sv.regime_tag}"
        )

    check("crisis",  crisis_rets, "crisis")
    check("normal",  normal_rets, "normal")
    check("trending", trend_rets, "trending")

    # Insufficient data
    sig.update_returns([0.01] * 5)
    sv = sig.compute()
    assert sv.confidence == 0.0
    print("insufficient_data OK")

    print("All WassersteinRegimeSignal tests PASSED")
    sys.exit(0)


if __name__ == "__main__":
    _self_test()
