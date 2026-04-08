"""
omega.nodes.victoria.geometry.ollivier_ricci
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Ollivier-Ricci curvature on the asset correlation network.

Concept
-------
Ollivier-Ricci curvature (ORC) generalises Riemannian curvature to metric
measure spaces (Villani 2009).  For a weighted graph G = (V, E, d), the ORC
of an edge (i, j) is:

    κ(i, j) = 1 - W₁(μᵢ, μⱼ) / d(i, j)

where:
  - d(i, j)  is the edge distance (1 - |corr(i,j)| for a correlation graph)
  - μᵢ       is a probability measure "around" node i
  - W₁(·,·)  is the Wasserstein-1 (Earth Mover's) distance

We define μᵢ as the empirical distribution of ticker i's recent log-returns
(normalised to [0,1]).  ORC then measures how similar the return distributions
of two correlated assets are, penalised by how far apart they are in the
correlation metric.

Interpretation
--------------
κ > 0  (positive curvature):
    Correlated assets share similar return distributions → information
    spreads uniformly like a sphere.  High co-movement = STRESS / contagion.
    Signal < 0 (bearish).

κ < 0  (negative curvature):
    Correlated assets have different return shapes → hyperbolic geometry.
    Healthy diversification — co-movement without return shape collapse.
    Signal > 0 (bullish / reduced risk).

κ ≈ 0  (flat):
    Euclidean-like network.  Neutral.

Trading signal
--------------
    mean_κ = average ORC across all edges above correlation threshold
    signal  = -tanh(mean_κ * SIGNAL_SCALE)

    Positive mean curvature (stress) → negative signal (reduce exposure).
    Negative mean curvature (healthy) → positive signal (normal sizing).

References
----------
- Ollivier (2009) "Ricci curvature of Markov chains on metric spaces"
- Lin, Lu & Yau (2011) "Ricci curvature of graphs"
- Sandhu et al. (2016) "Graph curvature for differentiating cancer networks"
- Samal et al. (2018) "Comparative analysis of two discretizations of Ricci
  curvature for complex networks"
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.stats import wasserstein_distance

logger = logging.getLogger("omega.nodes.victoria.geometry.ollivier_ricci")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WINDOW: int = 30           # rolling window for return history
_MIN_TICKERS: int = 3       # minimum tickers to build a meaningful network
_CORR_THRESHOLD: float = 0.4  # minimum |correlation| to create an edge
_SIGNAL_SCALE: float = 3.0  # tanh scaling for curvature → signal
_N_BINS: int = 20           # histogram bins for Wasserstein approximation
_MIN_SAMPLES: int = 10      # minimum returns before signal activates


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class OrcState:
    """Result of one ORC computation cycle."""

    mean_curvature: float       # mean ORC across all edges
    n_edges: int                # number of edges in the network
    n_nodes: int                # number of tickers in the network
    signal: float               # trading signal ∈ [-1, +1]
    confidence: float           # 0..1; grows with history length
    regime: str                 # "stress" | "healthy" | "neutral"
    edge_curvatures: dict[str, float]  # {"{t1}-{t2}": κ} for top/bottom edges


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class OllivierRicciCurvature:
    """
    Computes Ollivier-Ricci curvature on the dynamic asset correlation network.

    At each cycle:
      1. Ingest latest log-returns for each ticker.
      2. Build a correlation matrix from the rolling return history.
      3. Create edges where |corr| ≥ threshold; distance = 1 - |corr|.
      4. For each edge (i, j), compute W₁(μᵢ, μⱼ) via scipy's
         wasserstein_distance on discretised return distributions.
      5. κ(i,j) = 1 - W₁ / d(i,j).
      6. Mean κ → trading signal via -tanh(mean_κ * scale).
    """

    def __init__(
        self,
        window: int = _WINDOW,
        min_tickers: int = _MIN_TICKERS,
        corr_threshold: float = _CORR_THRESHOLD,
        signal_scale: float = _SIGNAL_SCALE,
        n_bins: int = _N_BINS,
    ) -> None:
        self._window = window
        self._min_tickers = min_tickers
        self._corr_threshold = corr_threshold
        self._signal_scale = signal_scale
        self._n_bins = n_bins

        # Rolling return buffers per ticker
        self._returns: dict[str, deque[float]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, market_data: dict[str, Any]) -> OrcState | None:
        """
        Ingest one cycle of market data and return the current ORC state.

        Parameters
        ----------
        market_data : dict keyed by ticker.
            Each value must contain "close" or "adjclose" as a list of prices.

        Returns
        -------
        OrcState on success, None if insufficient data.
        """
        self._ingest(market_data)

        tickers = [t for t, buf in self._returns.items() if len(buf) >= _MIN_SAMPLES]
        if len(tickers) < self._min_tickers:
            return None

        returns_matrix = self._build_returns_matrix(tickers)
        corr_matrix = self._correlation_matrix(returns_matrix)
        edges = self._build_edges(tickers, corr_matrix)

        if not edges:
            return None

        edge_curvatures = self._compute_edge_curvatures(tickers, returns_matrix, edges)

        if not edge_curvatures:
            return None

        mean_kappa = sum(edge_curvatures.values()) / len(edge_curvatures)
        n_samples = min(len(buf) for buf in self._returns.values() if len(buf) >= _MIN_SAMPLES)
        confidence = min(1.0, float(n_samples) / self._window)

        signal = float(np.clip(-math.tanh(mean_kappa * self._signal_scale), -1.0, 1.0))

        if mean_kappa > 0.1:
            regime = "stress"
        elif mean_kappa < -0.1:
            regime = "healthy"
        else:
            regime = "neutral"

        # Keep only the top/bottom 5 edges by curvature for observability
        sorted_edges = sorted(edge_curvatures.items(), key=lambda kv: kv[1])
        top_edges = dict(
            sorted_edges[:3] + sorted_edges[-3:]
        )

        logger.debug(
            "ORC: mean_κ=%.3f n_edges=%d n_nodes=%d regime=%s signal=%.3f conf=%.2f",
            mean_kappa, len(edge_curvatures), len(tickers), regime, signal, confidence,
        )

        return OrcState(
            mean_curvature=mean_kappa,
            n_edges=len(edge_curvatures),
            n_nodes=len(tickers),
            signal=signal,
            confidence=confidence,
            regime=regime,
            edge_curvatures=top_edges,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ingest(self, market_data: dict[str, Any]) -> None:
        """Extract latest log-return for each ticker."""
        for ticker, data in market_data.items():
            if not data or not isinstance(data, dict):
                continue
            prices_raw = data.get("adjclose") or data.get("close") or []
            prices = [float(p) for p in prices_raw if p is not None]
            prices = [p for p in prices if p > 0 and math.isfinite(p)]
            if len(prices) < 2:
                continue
            ret = math.log(prices[-1] / prices[-2])
            if not math.isfinite(ret):
                continue
            if ticker not in self._returns:
                self._returns[ticker] = deque(maxlen=self._window)
            self._returns[ticker].append(ret)

    def _build_returns_matrix(self, tickers: list[str]) -> np.ndarray:
        """Build (n_tickers × window) matrix of recent returns."""
        rows = []
        min_len = min(len(self._returns[t]) for t in tickers)
        for t in tickers:
            buf = list(self._returns[t])[-min_len:]
            rows.append(buf)
        return np.array(rows, dtype=float)

    @staticmethod
    def _correlation_matrix(mat: np.ndarray) -> np.ndarray:
        """Compute pairwise correlation matrix.  Returns identity if degenerate."""
        n = mat.shape[0]
        if mat.shape[1] < 3:
            return np.eye(n)
        try:
            c = np.corrcoef(mat)
            # Replace NaN (zero-variance rows) with 0
            c = np.where(np.isfinite(c), c, 0.0)
            return c
        except Exception:
            return np.eye(n)

    def _build_edges(
        self, tickers: list[str], corr: np.ndarray
    ) -> list[tuple[int, int, float]]:
        """Return list of (i, j, distance) edges where |corr| ≥ threshold."""
        edges: list[tuple[int, int, float]] = []
        n = len(tickers)
        for i in range(n):
            for j in range(i + 1, n):
                c = float(corr[i, j])
                if abs(c) >= self._corr_threshold:
                    dist = max(1e-6, 1.0 - abs(c))  # correlation distance ∈ (0, 1]
                    edges.append((i, j, dist))
        return edges

    def _compute_edge_curvatures(
        self,
        tickers: list[str],
        returns_matrix: np.ndarray,
        edges: list[tuple[int, int, float]],
    ) -> dict[str, float]:
        """Compute ORC κ(i,j) = 1 - W₁(μᵢ, μⱼ) / d(i,j) for each edge."""
        edge_curvatures: dict[str, float] = {}

        # Pre-normalise each ticker's returns to [0, 1] for Wasserstein
        normalised: list[np.ndarray] = []
        for i in range(len(tickers)):
            r = returns_matrix[i]
            r_min, r_max = r.min(), r.max()
            span = r_max - r_min
            if span < 1e-10:
                normalised.append(np.zeros_like(r))
            else:
                normalised.append((r - r_min) / span)

        for i, j, dist in edges:
            try:
                w1 = wasserstein_distance(normalised[i], normalised[j])
                kappa = 1.0 - w1 / dist
                key = f"{tickers[i]}-{tickers[j]}"
                edge_curvatures[key] = float(kappa)
            except Exception:
                continue

        return edge_curvatures
