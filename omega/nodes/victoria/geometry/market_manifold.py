"""
omega.nodes.victoria.geometry.market_manifold
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Information geometry: market as a statistical manifold.

Concept
-------
At each cycle, the return distribution of a basket of assets is modelled
as a member of an exponential family parameterised by

    θ = (μ, σ², γ)   — mean, variance, skewness

This family forms a Riemannian manifold equipped with the **Fisher Information
Metric** (FIM):

    g_ij(θ) = E[ ∂_i log p(x;θ) · ∂_j log p(x;θ) ]

The **Ricci scalar curvature** R(θ) summarises the manifold's local geometry:

    R > 0  →  positive curvature → market is mean-reverting
    R < 0  →  negative curvature → market is trending / momentum-driven
    R ≈ 0  →  flat geometry → transitional / uncertain

**Geodesic distance** between two states θ_a and θ_b is the length of the
shortest path on the manifold under the FIM metric.  We approximate it via
numerical integration of the arc length from θ_a to θ_b using the linear
path (straight line in parameter space is a first-order approximation; the
true geodesic requires solving a BVP, but the Rao distance is sufficient for
signal purposes).

Algorithm (per cycle)
---------------------
1. Extract rolling returns for each asset in the basket.
2. Estimate θ = (μ, σ², γ) using moment estimators on the pooled basket.
3. Build g_ij numerically via score function expectations (Monte Carlo).
4. Approximate Christoffel symbols Γ^k_ij via finite differences on g.
5. Compute Ricci scalar R from the Riemann tensor contraction.
6. Compare current θ to reference crash / rally / neutral states via geodesic
   distance.
7. Emit a trading signal in [-1, +1]:
      R < -0.3  →  signal towards momentum (follow trend)
      R >  0.3  →  signal towards mean-reversion (fade extremes)
      |R| ≤ 0.3 →  neutral / transitional

References
----------
- Amari & Nagaoka (2000) "Methods of Information Geometry"
- Rao (1945) "Information and the accuracy attainable in the estimation"
- Shun-ichi Amari (1998) "Natural Gradient Works Efficiently in Learning"
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger("omega.nodes.victoria.geometry.market_manifold")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WINDOW = 30  # rolling cycle window for return estimation
_MIN_SAMPLES = 10  # minimum returns before signal activates
_MC_SAMPLES = 500  # Monte Carlo samples for FIM estimation
_FD_EPS = 1e-4  # finite-difference step for Christoffel symbols
_CURVATURE_THRESHOLD = 0.3  # |R| threshold to emit directional signal
_SIGNAL_SCALE = 2.0  # tanh scale for signal magnitude

# Reference market states (θ = [μ, σ², γ]) — calibrated from crypto crash/rally history
# Crisis / crash: negative drift, high variance, negative skew (tail risk)
_REF_CRASH: np.ndarray = np.array([-0.02, 0.0025, -1.2])
# Strong rally: positive drift, moderate variance, positive skew
_REF_RALLY: np.ndarray = np.array([0.015, 0.0008, 0.8])
# Neutral / sideways: near-zero drift, low variance, symmetric
_REF_NEUTRAL: np.ndarray = np.array([0.0, 0.0003, 0.0])


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ManifoldState:
    """A single point on the market manifold (one cycle snapshot)."""

    theta: np.ndarray  # [μ, σ², γ] parameter vector
    fim: np.ndarray  # 3×3 Fisher Information Matrix
    ricci: float  # Ricci scalar curvature
    geo_dist_crash: float  # geodesic distance to crash reference
    geo_dist_rally: float  # geodesic distance to rally reference
    geo_dist_neutral: float  # geodesic distance to neutral reference
    regime: str  # "mean_reversion" | "trending" | "transitional"
    signal: float  # trading signal ∈ [-1, +1]
    confidence: float  # 0..1


@dataclass
class _History:
    """Rolling history for normalisation."""

    ricci: deque = field(default_factory=lambda: deque(maxlen=_WINDOW))
    theta: deque = field(default_factory=lambda: deque(maxlen=_WINDOW))


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------


class MarketManifold:
    """
    Models the market as a statistical manifold using information geometry.

    Usage
    -----
    manifold = MarketManifold()
    for cycle_market_data in training_loop:
        state = manifold.update(cycle_market_data)
        print(state.signal, state.regime)
    """

    def __init__(
        self,
        window: int = _WINDOW,
        min_samples: int = _MIN_SAMPLES,
        mc_samples: int = _MC_SAMPLES,
        rng_seed: int = 42,
    ) -> None:
        self._window = window
        self._min_samples = min_samples
        self._mc_samples = mc_samples
        self._rng = np.random.default_rng(rng_seed)

        # Per-ticker return history: ticker → deque of float returns
        self._returns: dict[str, deque] = {}
        self._history = _History()
        self._cycle = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, market_data: dict[str, Any]) -> ManifoldState | None:
        """
        Ingest one cycle of market data, update return histories, and compute
        the current manifold state.

        Parameters
        ----------
        market_data : dict keyed by ticker symbol.
            Each value must contain "close" or "adjclose" as a list of prices.

        Returns
        -------
        ManifoldState on success, None if insufficient data.
        """
        self._cycle += 1
        self._ingest(market_data)

        pooled = self._pooled_returns()
        if len(pooled) < self._min_samples:
            return None

        theta = self._estimate_theta(pooled)
        if theta is None:
            return None

        fim = self._fisher_information_matrix(theta)
        ricci = self._ricci_scalar(fim, theta)

        geo_crash = self._geodesic_distance(theta, _REF_CRASH, fim)
        geo_rally = self._geodesic_distance(theta, _REF_RALLY, fim)
        geo_neutral = self._geodesic_distance(theta, _REF_NEUTRAL, fim)

        regime = self._predict_regime(ricci)
        signal, confidence = self._compute_signal(ricci, geo_crash, geo_rally)

        self._history.ricci.append(ricci)
        self._history.theta.append(theta.copy())

        return ManifoldState(
            theta=theta,
            fim=fim,
            ricci=ricci,
            geo_dist_crash=geo_crash,
            geo_dist_rally=geo_rally,
            geo_dist_neutral=geo_neutral,
            regime=regime,
            signal=signal,
            confidence=confidence,
        )

    def predict_regime(self, ricci: float) -> str:
        """Classify market regime from Ricci scalar curvature."""
        return self._predict_regime(ricci)

    # ------------------------------------------------------------------
    # Data ingestion
    # ------------------------------------------------------------------

    def _ingest(self, market_data: dict[str, Any]) -> None:
        """Extract latest log-return for each ticker and append to history."""
        for ticker, data in market_data.items():
            if not data or not isinstance(data, dict):
                continue
            prices_raw = data.get("adjclose") or data.get("close") or []
            prices = [float(p) for p in prices_raw if p is not None]
            prices = [p for p in prices if p > 0 and math.isfinite(p)]
            if len(prices) < 2:
                continue

            # log return: most recent period
            ret = math.log(prices[-1] / prices[-2])
            if not math.isfinite(ret):
                continue

            if ticker not in self._returns:
                self._returns[ticker] = deque(maxlen=self._window)
            self._returns[ticker].append(ret)

    def _pooled_returns(self) -> np.ndarray:
        """Pool all per-ticker returns into one array (cross-sectional view)."""
        all_rets: list[float] = []
        for buf in self._returns.values():
            all_rets.extend(buf)
        return np.array(all_rets)

    # ------------------------------------------------------------------
    # Parameter estimation  θ = (μ, σ², γ)
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_theta(returns: np.ndarray) -> np.ndarray | None:
        """
        Estimate distribution parameters via method of moments.
        Returns θ = [μ, σ², γ] or None if numerically invalid.
        """
        n = len(returns)
        if n < 3:
            return None

        mu = float(np.mean(returns))
        variance = float(np.var(returns, ddof=1))
        if variance <= 0 or not math.isfinite(variance):
            return None

        std = math.sqrt(variance)
        # Sample skewness
        skewness = float(np.mean(((returns - mu) / std) ** 3)) if std > 0 else 0.0

        if not (math.isfinite(mu) and math.isfinite(variance) and math.isfinite(skewness)):
            return None

        return np.array([mu, variance, skewness])

    # ------------------------------------------------------------------
    # Fisher Information Matrix
    # ------------------------------------------------------------------

    def _fisher_information_matrix(self, theta: np.ndarray) -> np.ndarray:
        """
        Numerically estimate the 3×3 Fisher Information Matrix via Monte Carlo:

            g_ij ≈ (1/N) Σ_k [ ∂_i log p(x_k; θ) · ∂_j log p(x_k; θ) ]

        We model p(x; θ) as a Gaussian parameterised by (μ, σ²) and treat
        skewness as a perturbation.  The FIM for a Gaussian family has a
        known closed-form block-diagonal structure, which we use as the base:

            g = diag(1/σ², 1/(2σ⁴), 0)   (Gaussian FIM in (μ, σ²) coords)

        We extend with a finite-difference numerical estimate around the
        skewness dimension using a moment-generating function approximation.
        """
        mu, var, _gamma = float(theta[0]), float(theta[1]), float(theta[2])
        var = max(var, 1e-10)
        sigma = math.sqrt(var)

        # Closed-form Gaussian FIM block (2×2 in μ, σ²)
        g00 = 1.0 / var  # ∂μ score²
        g11 = 1.0 / (2.0 * var * var)  # ∂σ² score²
        g01 = 0.0  # Gaussian: off-diagonal = 0

        # Numerical FIM extension for skewness dimension via Monte Carlo
        # Draw samples from a skew-normal approximation
        samples = self._rng.normal(mu, sigma, self._mc_samples)
        # Apply skewness correction via Gram-Charlier approximation:
        # p(x) ∝ φ(z) [1 + (γ/6) H_3(z)]  where H_3(z) = z³ - 3z
        z = (samples - mu) / (sigma + 1e-10)
        h3 = z**3 - 3 * z
        dlog_dgamma = h3 / 6.0  # ∂ log p / ∂γ (Gram-Charlier)
        dlog_dmu = z / sigma
        dlog_dsig2 = (z**2 - 1.0) / (2.0 * var)

        g22 = float(np.mean(dlog_dgamma**2))  # FIM element for skewness
        g02 = float(np.mean(dlog_dmu * dlog_dgamma))
        g12 = float(np.mean(dlog_dsig2 * dlog_dgamma))

        fim = np.array(
            [
                [g00, g01, g02],
                [g01, g11, g12],
                [g02, g12, g22],
            ]
        )

        # Regularise for numerical stability
        fim += np.eye(3) * 1e-6
        return fim

    # ------------------------------------------------------------------
    # Christoffel symbols and Ricci curvature
    # ------------------------------------------------------------------

    def _christoffel(self, theta: np.ndarray) -> np.ndarray:
        """
        Compute Christoffel symbols Γ^k_ij via finite differences on the FIM.

            Γ^k_ij = (1/2) g^{km} (∂_i g_{mj} + ∂_j g_{mi} - ∂_m g_{ij})

        Returns shape (3, 3, 3) array: Γ[k, i, j].
        """
        dim = 3
        g = self._fisher_information_matrix(theta)

        try:
            g_inv = np.linalg.inv(g)
        except np.linalg.LinAlgError:
            return np.zeros((dim, dim, dim))

        # Partial derivatives of g via finite differences
        dg = np.zeros((dim, dim, dim))  # dg[m, i, j] = ∂_m g_{ij}
        for m in range(dim):
            theta_p = theta.copy()
            theta_p[m] += _FD_EPS
            theta_n = theta.copy()
            theta_n[m] -= _FD_EPS
            gp = self._fisher_information_matrix(theta_p)
            gn = self._fisher_information_matrix(theta_n)
            dg[m] = (gp - gn) / (2.0 * _FD_EPS)

        gamma = np.zeros((dim, dim, dim))
        for k in range(dim):
            for i in range(dim):
                for j in range(dim):
                    s = 0.0
                    for m in range(dim):
                        s += g_inv[k, m] * (dg[i, m, j] + dg[j, m, i] - dg[m, i, j])
                    gamma[k, i, j] = 0.5 * s

        return gamma

    def _ricci_scalar(self, fim: np.ndarray, theta: np.ndarray) -> float:
        """
        Approximate Ricci scalar curvature R via contraction of the Riemann tensor.

            R^i_jkl = ∂_k Γ^i_lj - ∂_l Γ^i_kj + Γ^i_km Γ^m_lj - Γ^i_lm Γ^m_kj
            Ric_jl  = R^i_jil  (Ricci tensor, contract first and third indices)
            R       = g^{jl} Ric_jl  (Ricci scalar)

        Uses finite differences on Christoffel symbols.
        """
        dim = 3

        gamma0 = self._christoffel(theta)

        # Partial derivatives of Christoffel symbols
        d_gamma = np.zeros((dim, dim, dim, dim))  # d_gamma[m, k, i, j] = ∂_m Γ^k_ij
        for m in range(dim):
            theta_p = theta.copy()
            theta_p[m] += _FD_EPS
            theta_n = theta.copy()
            theta_n[m] -= _FD_EPS
            gp = self._christoffel(theta_p)
            gn = self._christoffel(theta_n)
            d_gamma[m] = (gp - gn) / (2.0 * _FD_EPS)

        # Riemann tensor R^i_jkl
        riemann = np.zeros((dim, dim, dim, dim))
        for i in range(dim):
            for j in range(dim):
                for k in range(dim):
                    for l in range(dim):  # noqa: E741
                        term1 = d_gamma[k, i, l, j]
                        term2 = d_gamma[l, i, k, j]
                        term3 = sum(gamma0[i, k, m] * gamma0[m, l, j] for m in range(dim))
                        term4 = sum(gamma0[i, l, m] * gamma0[m, k, j] for m in range(dim))
                        riemann[i, j, k, l] = term1 - term2 + term3 - term4

        # Ricci tensor Ric_jl = R^i_jil
        ric = np.zeros((dim, dim))
        for j in range(dim):
            for l in range(dim):  # noqa: E741
                ric[j, l] = sum(riemann[i, j, i, l] for i in range(dim))

        # Ricci scalar R = g^{jl} Ric_jl
        try:
            g_inv = np.linalg.inv(fim)
        except np.linalg.LinAlgError:
            return 0.0

        r_scalar = float(np.einsum("jl,jl->", g_inv, ric))
        if not math.isfinite(r_scalar):
            return 0.0

        # Z-score normalise against rolling history to keep signal stable
        r_scalar = self._normalise_ricci(r_scalar)
        return float(np.clip(r_scalar, -5.0, 5.0))

    def _normalise_ricci(self, r_scalar: float) -> float:
        """Z-score normalise R against rolling history."""
        history = list(self._history.ricci)
        if len(history) < 5:
            return r_scalar
        mean = sum(history) / len(history)
        var = sum((x - mean) ** 2 for x in history) / max(1, len(history) - 1)
        std = math.sqrt(var) if var > 0 else 1e-8
        return (r_scalar - mean) / std

    # ------------------------------------------------------------------
    # Geodesic distance (Rao distance approximation)
    # ------------------------------------------------------------------

    def _geodesic_distance(
        self,
        theta_a: np.ndarray,
        theta_b: np.ndarray,
        fim: np.ndarray,
    ) -> float:
        """
        Approximate geodesic (Rao) distance between two parameter vectors:

            d(a, b) ≈ √[ (θ_b - θ_a)ᵀ g(θ_a) (θ_b - θ_a) ]

        This is the linearised arc length — a first-order approximation.
        The true Rao distance requires integrating along the geodesic, but
        the linearisation is sufficient for regime classification.
        """
        delta = theta_b - theta_a
        # Clip delta to prevent extreme distances from destabilising the signal
        delta = np.clip(delta, -10.0, 10.0)
        q = float(delta @ fim @ delta)
        return math.sqrt(max(q, 0.0))

    # ------------------------------------------------------------------
    # Regime classification and signal generation
    # ------------------------------------------------------------------

    @staticmethod
    def _predict_regime(ricci: float) -> str:
        """Classify market regime from Ricci scalar."""
        if ricci > _CURVATURE_THRESHOLD:
            return "mean_reversion"
        if ricci < -_CURVATURE_THRESHOLD:
            return "trending"
        return "transitional"

    def _compute_signal(
        self, ricci: float, geo_crash: float, geo_rally: float
    ) -> tuple[float, float]:
        """
        Map Ricci curvature and geodesic distances to a trading signal ∈ [-1, +1].

        Logic:
          - mean_reversion regime: fade extremes → positive signal if near crash
            (contrarian long), negative if near rally (contrarian short)
          - trending regime: follow momentum → negative signal if near crash
            (follow shorts), positive if near rally (follow longs)
          - transitional: signal proportional to Ricci, dampened
        """
        n_samples = len(self._history.ricci)
        confidence = min(1.0, float(n_samples) / self._window)

        if abs(ricci) <= _CURVATURE_THRESHOLD:
            # Transitional: small residual signal proportional to Ricci
            signal = math.tanh(ricci * 0.5)
            return float(signal), confidence * 0.5

        # Proximity indicators: how close to reference states?
        total_geo = geo_crash + geo_rally + 1e-8
        crash_proximity = 1.0 - (geo_crash / total_geo)  # 1 = at crash state
        rally_proximity = 1.0 - (geo_rally / total_geo)  # 1 = at rally state
        proximity_signal = rally_proximity - crash_proximity  # in [-1, +1]

        if ricci > _CURVATURE_THRESHOLD:
            # Mean-reverting: fade extremes
            signal = math.tanh(-proximity_signal * _SIGNAL_SCALE)
        else:
            # Trending: follow momentum
            signal = math.tanh(proximity_signal * _SIGNAL_SCALE)

        return float(np.clip(signal, -1.0, 1.0)), confidence

    # ------------------------------------------------------------------
    # Crash proximity scoring (V95 Enhancement C)
    # ------------------------------------------------------------------

    def crash_proximity_score(self, mu: float, sigma: float) -> float:
        """
        Compute the minimum Fisher-Rao geodesic distance from the current
        distribution parameters to a set of known crash reference states.

        Known crash states are defined as (mean_return, std_dev) pairs
        corresponding to observed crypto crash distributions.  The method
        constructs a minimal theta = [mu, sigma², 0] (zero skewness for
        simplicity) and computes the geodesic distance to each reference,
        returning the minimum.

        A low min_distance (< 0.5) indicates the current market state is
        geometrically close to a historical crash regime.

        Parameters
        ----------
        mu    : float — current mean log-return of the basket
        sigma : float — current return standard deviation (not variance)

        Returns
        -------
        min_distance : float — geodesic distance to nearest crash state
        """
        # Known crash reference states: (mean_return, std_dev) pairs
        # Calibrated from major crypto drawdowns (>-30% in 30-day windows).
        _CRASH_REFS: list[tuple[float, float]] = [
            (-0.05, 0.08),  # sharp panic sell-off (e.g. May 2021)
            (-0.04, 0.07),  # prolonged bear leg (e.g. Nov 2022)
            (-0.02, 0.05),  # slow bleed / high-vol sideways crash
        ]

        var = max(sigma * sigma, 1e-10)
        theta_current = np.array([mu, var, 0.0])
        fim = self._fisher_information_matrix(theta_current)

        distances: list[float] = []
        for ref_mu, ref_sigma in _CRASH_REFS:
            ref_var = max(ref_sigma * ref_sigma, 1e-10)
            theta_ref = np.array([ref_mu, ref_var, 0.0])
            d = self._geodesic_distance(theta_current, theta_ref, fim)
            distances.append(d)

        return min(distances) if distances else float("inf")

    # ------------------------------------------------------------------
    # Serialisation for dashboard
    # ------------------------------------------------------------------

    def history_for_dashboard(self, n: int = 60) -> list[dict]:
        """
        Return the last n cycles of manifold state as a list of dicts suitable
        for the GeometryView dashboard.  Falls back to empty list if history is thin.
        """
        ricci_hist = list(self._history.ricci)
        theta_hist = list(self._history.theta)
        out = []
        for i, (r, th) in enumerate(zip(ricci_hist[-n:], theta_hist[-n:], strict=False)):
            regime = self._predict_regime(r)
            out.append(
                {
                    "cycle": i + 1,
                    "ricci": round(r, 4),
                    "mu": round(float(th[0]), 6),
                    "variance": round(float(th[1]), 8),
                    "skewness": round(float(th[2]), 4),
                    "regime": regime,
                }
            )
        return out
