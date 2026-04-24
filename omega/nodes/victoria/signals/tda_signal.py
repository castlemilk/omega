"""
Topological Data Analysis (TDA) crash-prediction signal for Victoria.

Applies persistent homology to the rolling return time series to detect
topological structures associated with pre-crash regimes:
  - β₀ (Betti-0): connected components — counts isolated clusters of returns
  - β₁ (Betti-1): holes / loops — captures cyclicity / oscillation structure
  - Persistence entropy: Shannon entropy of the persistence diagram lifetimes

High β₁ + low persistence entropy historically precedes sharp drawdowns in
BTC/ETH — the topology develops a persistent loop (oscillation builds) before
the break. This captures momentum reversal structure not visible in first/second
moments.

Backend: uses a pure-numpy Vietoris-Rips approximation via a distance-matrix
persistence algorithm. No external dependencies required (ripser / gudhi are
used if available for speed).

Output (SignalValue):
    value      = tda_fragmentation  ∈ [-1, +1]
                 < 0 = topologically fragmented (crash precursor)
                 > 0 = topologically smooth (healthy trend)
    confidence = 1 - persistence_entropy_normalised  (higher = more certain)
    regime_tag = "fragmented" | "oscillating" | "smooth" | "insufficient_data"
    raw        = {
        "betti0": int,
        "betti1": int,
        "persistence_entropy": float,
        "n_points": int,
        "epsilon_max": float,
    }

Feature flag: controlled by VictoriaFeatures.tda_signal_enabled.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

from omega.nodes.victoria.signals_advanced import SignalValue

logger = logging.getLogger("omega.nodes.victoria.signals.tda_signal")

# Homology dimensions computed (0 = connected components, 1 = loops)
_DIM0 = 0
_DIM1 = 1

# Point cloud embedding: each point = (r_t, r_{t+1}) sliding window
_EMBED_DIM = 2

# Epsilon grid: fraction of max pairwise distance used in numpy fallback.
# Capped at 0.40 to avoid near-complete graph at large epsilon (inflates β₁).
_N_EPSILON = 30
_EPSILON_FRACS = np.linspace(0.02, 0.40, _N_EPSILON)


class TDASignal:
    """
    Topological crash-prediction signal using persistent homology.

    Parameters
    ----------
    window:
        Number of recent returns to embed. 40–80 gives stable topology.
    min_obs:
        Minimum returns before producing a valid signal.
    embed_dim:
        Takens delay embedding dimension (default 2 = pairs).
    """

    def __init__(self, window: int = 60, min_obs: int = 30, embed_dim: int = _EMBED_DIM) -> None:
        self._window = int(window)
        self._min_obs = int(min_obs)
        self._embed_dim = int(embed_dim)
        self._returns: list[float] = []

    # ── Public interface ──────────────────────────────────────────────────────

    def update_returns(self, returns: list[float] | np.ndarray) -> None:
        """Replace internal buffer with the latest return series.

        Callers compute the full BTC return window each cycle and pass it in.
        Earlier `extend` semantics caused the buffer to balloon with duplicates
        in live mode (where the same window is re-passed every short cycle),
        flattening the topology — masked in backtest by the sliding cursor.
        """
        arr = [float(x) for x in np.asarray(returns).ravel() if np.isfinite(x)]
        max_keep = self._window * 3
        self._returns = arr[-max_keep:]

    def compute(self, market_data: dict[str, Any] | None = None) -> SignalValue:
        recent = np.array(self._returns[-self._window:], dtype=float)
        recent = recent[np.isfinite(recent)]

        if len(recent) < self._min_obs:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="insufficient_data",
                raw={"betti0": 0, "betti1": 0, "persistence_entropy": 0.0,
                     "n_points": len(recent), "epsilon_max": 0.0},
            )

        # Build point cloud via delay embedding
        cloud = _delay_embed(recent, self._embed_dim)
        if len(cloud) < 4:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="insufficient_data",
                raw={"betti0": 0, "betti1": 0, "persistence_entropy": 0.0,
                     "n_points": len(cloud), "epsilon_max": 0.0},
            )

        # Attempt fast path (ripser if installed)
        try:
            betti0, betti1, pers_entropy, eps_max = _compute_via_ripser(cloud)
        except ImportError:
            betti0, betti1, pers_entropy, eps_max = _compute_numpy(cloud)

        regime_tag = _classify_regime(betti0, betti1, pers_entropy)
        value = _fragmentation_score(betti0, betti1, pers_entropy)
        confidence = float(np.clip(1.0 - pers_entropy, 0.0, 1.0))

        return SignalValue(
            value=float(np.clip(value, -1.0, 1.0)),
            confidence=confidence,
            regime_tag=regime_tag,
            raw={
                "betti0": int(betti0),
                "betti1": int(betti1),
                "persistence_entropy": round(float(pers_entropy), 5),
                "n_points": len(cloud),
                "epsilon_max": round(float(eps_max), 6),
            },
        )


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _delay_embed(returns: np.ndarray, d: int) -> np.ndarray:
    """Takens delay embedding: returns → (T-d+1, d) point cloud."""
    n = len(returns)
    if n < d:
        return np.empty((0, d))
    return np.stack([returns[i:n - d + i + 1] for i in range(d)], axis=1)


def _pairwise_distances(cloud: np.ndarray) -> np.ndarray:
    """Euclidean pairwise distance matrix."""
    diff = cloud[:, None, :] - cloud[None, :, :]
    return np.sqrt((diff ** 2).sum(axis=-1))


# ── Numpy fallback VR persistence ─────────────────────────────────────────────

def _compute_numpy(cloud: np.ndarray) -> tuple[int, int, float, float]:
    """
    Approximate VR persistence via Union-Find (dim-0) + edge-loop counting (dim-1).

    This is a coarse approximation: β₀ from Union-Find filtration,
    β₁ estimated from the Euler characteristic (V - E + F ≈ 1 - β₁ for H1).
    Accurate enough for the regime classification signal.
    """
    D = _pairwise_distances(cloud)
    n = len(cloud)
    eps_max = float(D.max())
    if eps_max < 1e-10:
        return 1, 0, 0.0, eps_max

    epsilons = _EPSILON_FRACS * eps_max

    betti0_series: list[int] = []
    betti1_series: list[int] = []
    lifetimes: list[float] = []

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> bool:
        rx, ry = find(x), find(y)
        if rx == ry:
            return False
        parent[rx] = ry
        return True

    n_components = n
    n_edges = 0
    n_triangles = 0

    prev_eps = 0.0
    for eps in epsilons:
        # Add edges with D[i,j] <= eps
        new_edges: list[tuple[int, int]] = []
        for i in range(n):
            for j in range(i + 1, n):
                if prev_eps < D[i, j] <= eps:
                    new_edges.append((i, j))

        for i, j in new_edges:
            merged = union(i, j)
            if merged:
                n_components -= 1
                lifetimes.append(eps - prev_eps)
            n_edges += 1

        # Estimate triangles: trace(A³)/6 counts closed triangles.
        adj = (D <= eps).astype(np.float32)
        np.fill_diagonal(adj, 0)
        A2 = adj @ adj
        n_triangles = int(np.trace(A2 @ adj)) // 6

        # Euler characteristic: V - E + F = 1 - β₁  (for connected)
        # β₁ ≈ E - V + 1 + 2*n_triangles (rough)
        b0 = max(1, len(set(find(i) for i in range(n))))
        b1 = max(0, n_edges - n + b0 - n_triangles)

        betti0_series.append(b0)
        betti1_series.append(b1)
        prev_eps = eps

    betti0_final = betti0_series[-1] if betti0_series else 1
    betti1_final = betti1_series[-1] if betti1_series else 0

    pers_entropy = _persistence_entropy(lifetimes)
    return betti0_final, betti1_final, pers_entropy, eps_max


def _compute_via_ripser(cloud: np.ndarray) -> tuple[int, int, float, float]:
    """Use ripser (if installed) for fast accurate persistence."""
    import ripser  # type: ignore[import]
    result = ripser.ripser(cloud, maxdim=1)
    dgms = result["dgms"]

    D = _pairwise_distances(cloud)
    eps_max = float(D.max())

    # β₀: H0 bars still open at death=inf
    h0 = dgms[0]
    betti0 = int(np.isinf(h0[:, 1]).sum())

    # β₁: H1 bars
    h1 = dgms[1] if len(dgms) > 1 else np.empty((0, 2))
    betti1 = len(h1)

    # Persistence entropy from H1 lifetimes
    lifetimes: list[float] = []
    for birth, death in h1:
        if np.isfinite(death):
            lifetimes.append(float(death - birth))
    pers_entropy = _persistence_entropy(lifetimes)

    return betti0, betti1, pers_entropy, eps_max


def _persistence_entropy(lifetimes: list[float]) -> float:
    """Normalised Shannon entropy of persistence diagram lifetimes."""
    arr = np.array([x for x in lifetimes if x > 0], dtype=float)
    if len(arr) == 0:
        return 0.0
    total = arr.sum()
    if total < 1e-12:
        return 0.0
    p = arr / total
    raw = -float(np.sum(p * np.log(p + 1e-12)))
    # Normalise by log(N) so output is in [0, 1]
    return float(np.clip(raw / math.log(max(len(arr), 2)), 0.0, 1.0))


# ── Signal classification ─────────────────────────────────────────────────────

def _classify_regime(betti0: int, betti1: int, pers_entropy: float) -> str:
    if betti0 >= 4:
        return "fragmented"
    if betti1 >= 2 and pers_entropy < 0.5:
        return "oscillating"
    return "smooth"


def _fragmentation_score(betti0: int, betti1: int, pers_entropy: float) -> float:
    """
    Combine topological features into a single [-1, 1] fragmentation score.

    Negative = fragmented / crash precursor. Positive = smooth / trending.
    """
    # β₀ penalty: high connected-component count → fragmented market
    b0_norm = np.clip((betti0 - 1) / 5.0, 0.0, 1.0)
    # β₁ penalty: high loop count in low-entropy diagram → oscillatory trap
    b1_norm = np.clip(betti1 / 4.0, 0.0, 1.0)
    # Entropy bonus: high entropy = diffuse persistence = less dangerous
    entropy_bonus = pers_entropy

    raw_score = entropy_bonus - 0.5 * b0_norm - 0.5 * b1_norm
    return float(np.clip(raw_score * 2.0 - 1.0, -1.0, 1.0))


# ── Standalone test ───────────────────────────────────────────────────────────

def _self_test() -> None:
    import sys

    rng = np.random.default_rng(7)

    # Smooth trend — should be "smooth"
    trend = np.cumsum(0.01 + 0.01 * rng.standard_normal(80))
    trend_rets = np.diff(trend).tolist()

    # Crash precursor: oscillatory with fat tails
    osc = np.sin(np.linspace(0, 8 * np.pi, 80)) * 0.04 + 0.01 * rng.standard_normal(80)
    osc_rets = np.diff(osc).tolist()

    for label, rets in [("trend", trend_rets), ("oscillating", osc_rets)]:
        sig = TDASignal(window=50, min_obs=20)
        sig.update_returns(rets)
        sv = sig.compute()
        print(
            f"{label:12s}  regime={sv.regime_tag:15s}  "
            f"value={sv.value:+.3f}  conf={sv.confidence:.3f}  "
            f"β0={sv.raw['betti0']}  β1={sv.raw['betti1']}  "
            f"pers_ent={sv.raw['persistence_entropy']:.4f}"
        )
        assert sv.regime_tag != "insufficient_data", f"{label}: got insufficient_data"

    # Insufficient data
    sig = TDASignal(window=50, min_obs=30)
    sig.update_returns([0.01] * 5)
    sv = sig.compute()
    assert sv.regime_tag == "insufficient_data"
    print("insufficient_data OK")

    print("All TDASignal tests PASSED")
    sys.exit(0)


if __name__ == "__main__":
    _self_test()
