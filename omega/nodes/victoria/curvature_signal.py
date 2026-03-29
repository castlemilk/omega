"""
omega.nodes.victoria.curvature_signal
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Geodesic curvature signal for Victoria.

Concept
-------
In differential geometry, geodesic curvature measures how much a curve
deviates from the "straight-line" (geodesic) path on a manifold surface.

In signal space, we embed each cycle's composite signal vector into the
unit hypersphere (all signal vectors are L2-normalised). The "geodesic" on
the hypersphere is the great-circle arc between two points. Geodesic
curvature then measures how much the signal trajectory is turning away from
that great-circle arc — i.e., is the market changing direction or continuing
on a consistent path?

Algorithm
---------
At each cycle we receive a vector of per-signal values s_t ∈ R^N.
We project onto the unit sphere: ŝ_t = s_t / ‖s_t‖.

With a rolling window of K unit vectors, we compute the sequence of
angular velocities and angular accelerations:

    θ_t       = arccos(clamp(ŝ_{t-1} · ŝ_t, -1, 1))   (turning angle)
    ω_t       = θ_t / Δt                                  (angular velocity)
    α_t       = ω_t - ω_{t-1}                             (angular acceleration)

Geodesic curvature κ_g is approximated as:

    κ_g ≈ |α| / max(ω, ε)

Interpretation
--------------
- Low κ_g  → trajectory is smooth / consistent → trend continuation signal
- High κ_g → trajectory is curving sharply → possible reversal / regime change

Trading signal
--------------
signal = -tanh(κ_g * scale)   if ω > ω_threshold   (directional change)
signal = +tanh(ω * trend_k)   otherwise             (smooth trend continuation)

This gives a positive signal when the path is smooth (trend continuation) and
a negative signal when curvature spikes (reversal warning).

References
----------
- do Carmo (1992) "Riemannian Geometry"
- Amari (1998) "Natural Gradient Works Efficiently in Learning"
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger("omega.nodes.victoria.curvature_signal")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WINDOW = 20  # rolling window length (cycles)
_MIN_SAMPLES = 5  # minimum cycles before signal is active
_EPS = 1e-8  # numerical floor to prevent divide-by-zero
_SCALE = 5.0  # geodesic curvature amplification for tanh mapping
_TREND_K = 3.0  # angular velocity amplification for trend signal
_OMEGA_THRESHOLD = 0.05  # min angular velocity to classify as "turning"
_ZSCORE_WINDOW = 30  # rolling window for z-score normalisation of κ_g


@dataclass
class SignalValue:
    """Mirrors the SignalValue contract used by the other advanced signal nodes."""

    value: float  # trading signal ∈ [-1, +1]
    confidence: float  # 0..1; grows with history length
    regime_tag: str  # "trend_continuation" | "curvature_spike" | "warmup" | "flat"
    raw: dict


class GeodesicCurvatureSignal:
    """
    Measures how much the composite signal trajectory is curving on the
    unit hypersphere.  High curvature → potential reversal.  Low curvature
    + high velocity → trend continuation.

    Parameters
    ----------
    window :     Rolling window for signal history (default 20).
    min_samples: Minimum cycles before returning a non-warmup signal.
    n_signals :  Number of signal dimensions (auto-detected on first call).
    """

    def __init__(
        self,
        window: int = _WINDOW,
        min_samples: int = _MIN_SAMPLES,
    ) -> None:
        self._window = window
        self._min_samples = min_samples
        self._n_signals: int | None = None

        # Unit-vector trajectory
        self._unit_vectors: deque[np.ndarray] = deque(maxlen=window)

        # Angular velocity history (for z-score normalisation)
        self._omega_history: deque[float] = deque(maxlen=_ZSCORE_WINDOW)
        # Geodesic curvature history (for z-score normalisation)
        self._kappa_history: deque[float] = deque(maxlen=_ZSCORE_WINDOW)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(self, signal_dict: dict[str, Any]) -> SignalValue:
        """
        Compute the geodesic curvature signal from the current cycle's
        per-signal dictionary.

        Parameters
        ----------
        signal_dict : dict mapping signal_name → {"value": float, ...}
        """
        vec = self._extract_vector(signal_dict)
        if vec is None or np.linalg.norm(vec) < _EPS:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="flat",
                raw={"reason": "zero_vector"},
            )

        # Normalise to unit sphere
        unit_vec = vec / (np.linalg.norm(vec) + _EPS)
        self._unit_vectors.append(unit_vec)

        n = len(self._unit_vectors)
        if n < self._min_samples:
            return SignalValue(
                value=0.0,
                confidence=float(n) / self._min_samples,
                regime_tag="warmup",
                raw={"n_samples": n, "min_samples": self._min_samples},
            )

        # Compute angular velocities from unit vector sequence
        vecs = list(self._unit_vectors)
        omegas = self._compute_angular_velocities(vecs)

        if len(omegas) < 2:
            return SignalValue(
                value=0.0,
                confidence=0.3,
                regime_tag="warmup",
                raw={"n_omegas": len(omegas)},
            )

        omega_cur = omegas[-1]
        omega_prev = omegas[-2]

        # Angular acceleration ≈ geodesic curvature
        angular_accel = abs(omega_cur - omega_prev)
        kappa_g = angular_accel / max(omega_cur, _EPS)

        # Update histories for z-score
        self._omega_history.append(omega_cur)
        self._kappa_history.append(kappa_g)

        # Derive the trading signal
        signal_val, regime_tag = self._compute_signal(omega_cur, kappa_g)

        confidence = min(1.0, float(n) / self._window)

        return SignalValue(
            value=signal_val,
            confidence=confidence,
            regime_tag=regime_tag,
            raw={
                "omega": float(omega_cur),
                "kappa_g": float(kappa_g),
                "angular_accel": float(angular_accel),
                "n_samples": n,
                "omega_zscore": self._zscore(omega_cur, self._omega_history),
                "kappa_zscore": self._zscore(kappa_g, self._kappa_history),
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_vector(self, signal_dict: dict[str, Any]) -> np.ndarray | None:
        """Extract a numeric vector from the signal dictionary."""
        values: list[float] = []
        for key, val in signal_dict.items():
            if key.startswith("_"):
                continue
            if isinstance(val, dict):
                v = val.get("value", 0.0)
            elif isinstance(val, (int, float)):
                v = float(val)
            else:
                continue
            try:
                fv = float(v)
                if math.isfinite(fv):
                    values.append(fv)
            except (TypeError, ValueError):
                continue

        if not values:
            return None

        if self._n_signals is None:
            self._n_signals = len(values)

        return np.array(values)

    @staticmethod
    def _compute_angular_velocities(vecs: list[np.ndarray]) -> list[float]:
        """Compute angular velocities (turning angles) between consecutive unit vectors."""
        omegas: list[float] = []
        for i in range(1, len(vecs)):
            dot = float(np.clip(np.dot(vecs[i - 1], vecs[i]), -1.0, 1.0))
            angle = math.acos(dot)  # ∈ [0, π]
            omegas.append(angle)
        return omegas

    def _compute_signal(self, omega: float, kappa_g: float) -> tuple[float, str]:
        """Map (angular velocity, geodesic curvature) → (signal, regime_tag)."""
        kappa_z = self._zscore(kappa_g, self._kappa_history)

        if omega < _OMEGA_THRESHOLD:
            # Flat / sideways market — signal near zero
            return 0.0, "flat"

        if kappa_g > 1.0 or kappa_z > 1.5:
            # High curvature → trajectory bending sharply → reversal warning
            signal = -math.tanh(kappa_g * _SCALE * 0.2)
            return float(signal), "curvature_spike"

        # Low curvature + meaningful velocity → trend continuation
        signal = math.tanh(omega * _TREND_K)
        return float(signal), "trend_continuation"

    @staticmethod
    def _zscore(value: float, history: deque) -> float:
        """Z-score of value relative to history. Returns 0.0 if insufficient data."""
        if len(history) < 3:
            return 0.0
        h = list(history)
        mean = sum(h) / len(h)
        var = sum((x - mean) ** 2 for x in h) / max(1, len(h) - 1)
        std = math.sqrt(var) if var > 0 else _EPS
        return (value - mean) / std
