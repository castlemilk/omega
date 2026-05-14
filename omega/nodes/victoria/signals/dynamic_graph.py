"""Dynamic correlation-graph signal — EMGNN-lite without PyTorch.

Captures the EMGNN insight (dynamic correlation graphs evolve across
regime transitions and carry information that fixed-window correlation
estimates miss) without the neural network overhead.

Approach:
    1. Maintain a rolling close-price window per symbol.
    2. Each cycle, compute the cross-asset Pearson correlation matrix.
    3. Threshold |corr| >= edge_threshold to build a graph adjacency.
    4. Emit three graph-level features:
        * `graph_centrality_btc` — BTC's degree centrality in the
          thresholded graph. High = BTC drives everything (trend
          regime). Low = decoupled (mean-reversion regime).
        * `graph_clustering` — global clustering coefficient. High =
          pack movement (systemic risk on).
        * `graph_density` — fraction of possible edges actually present.

The signal is computed from OHLCV close prices already collected by the
ingestion node, so it works in **both** live and backtest snapshot
modes — unlike VPIN / Kyle / LOB which are WS-only.

Feature flag: `dynamic_graph_signal=True`.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Final, Sequence

logger = logging.getLogger("omega.nodes.victoria.signals.dynamic_graph")

_DEFAULT_WINDOW: Final[int] = 30
_DEFAULT_EDGE_THRESHOLD: Final[float] = 0.4
_HISTORY: Final[int] = 100  # for z-scores of graph metrics


@dataclass
class _SymPriceHistory:
    closes: deque[float] = field(default_factory=lambda: deque(maxlen=_DEFAULT_WINDOW))


@dataclass
class _MetricHistory:
    centrality: deque[float] = field(default_factory=lambda: deque(maxlen=_HISTORY))
    clustering: deque[float] = field(default_factory=lambda: deque(maxlen=_HISTORY))
    density: deque[float] = field(default_factory=lambda: deque(maxlen=_HISTORY))


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 5:
        return 0.0
    mx = sum(xs[:n]) / n
    my = sum(ys[:n]) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    sx2 = sum((xs[i] - mx) ** 2 for i in range(n))
    sy2 = sum((ys[i] - my) ** 2 for i in range(n))
    if sx2 <= 0.0 or sy2 <= 0.0:
        return 0.0
    return num / (sx2 ** 0.5 * sy2 ** 0.5)


def _returns(closes: Sequence[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            out.append((closes[i] - closes[i - 1]) / closes[i - 1])
    return out


class DynamicGraphSignal:
    """Rolling correlation-graph features across the symbol basket."""

    def __init__(
        self,
        window: int = _DEFAULT_WINDOW,
        edge_threshold: float = _DEFAULT_EDGE_THRESHOLD,
        anchor_symbol: str = "BTCUSDT",
    ) -> None:
        self._window = window
        self._edge_threshold = edge_threshold
        self._anchor = anchor_symbol.upper()
        self._prices: dict[str, _SymPriceHistory] = {}
        self._history = _MetricHistory()

    def push_close(self, symbol: str, close: float) -> None:
        """Record the latest close for `symbol`."""
        sym = symbol.upper()
        h = self._prices.get(sym)
        if h is None:
            h = _SymPriceHistory(closes=deque(maxlen=self._window))
            self._prices[sym] = h
        try:
            h.closes.append(float(close))
        except (TypeError, ValueError):
            return

    def compute(self) -> dict[str, float]:
        """Return graph-level features after pushing this cycle's closes.

        Caller should `push_close()` for every symbol BEFORE calling this.
        """
        zero = {
            "graph_centrality_btc": 0.0,
            "graph_clustering": 0.0,
            "graph_density": 0.0,
            "graph_centrality_btc_z": 0.0,
            "graph_clustering_z": 0.0,
        }
        # Need at least window prices for each of >= 2 symbols
        symbols = [s for s, h in self._prices.items() if len(h.closes) >= max(5, self._window // 2)]
        if len(symbols) < 2:
            return zero

        # Compute return series, then pairwise correlation
        rets: dict[str, list[float]] = {s: _returns(list(self._prices[s].closes)) for s in symbols}
        # All return series must have the same length for matrix ops
        min_len = min(len(r) for r in rets.values())
        if min_len < 5:
            return zero
        rets = {s: r[-min_len:] for s, r in rets.items()}

        # Adjacency matrix
        n = len(symbols)
        adj: list[list[int]] = [[0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                rho = _pearson(rets[symbols[i]], rets[symbols[j]])
                if abs(rho) >= self._edge_threshold:
                    adj[i][j] = 1
                    adj[j][i] = 1

        # Graph metrics
        degrees = [sum(row) for row in adj]
        max_deg = n - 1
        # BTC centrality (degree / max_possible_degree)
        anchor_idx = symbols.index(self._anchor) if self._anchor in symbols else None
        anchor_centrality = (degrees[anchor_idx] / max_deg) if anchor_idx is not None and max_deg > 0 else 0.0

        # Clustering coefficient (global, average of local)
        local_clusterings: list[float] = []
        for i in range(n):
            neighbors = [k for k in range(n) if adj[i][k]]
            if len(neighbors) < 2:
                continue
            possible = len(neighbors) * (len(neighbors) - 1) / 2
            actual = 0
            for a in range(len(neighbors)):
                for b in range(a + 1, len(neighbors)):
                    if adj[neighbors[a]][neighbors[b]]:
                        actual += 1
            local_clusterings.append(actual / possible if possible > 0 else 0.0)
        clustering = sum(local_clusterings) / len(local_clusterings) if local_clusterings else 0.0

        # Density
        total_possible = n * (n - 1) / 2
        edges = sum(degrees) / 2
        density = edges / total_possible if total_possible > 0 else 0.0

        # Update history + z-scores
        self._history.centrality.append(anchor_centrality)
        self._history.clustering.append(clustering)
        self._history.density.append(density)

        cent_z = self._zscore(self._history.centrality, anchor_centrality)
        clust_z = self._zscore(self._history.clustering, clustering)

        return {
            "graph_centrality_btc": round(anchor_centrality, 4),
            "graph_clustering": round(clustering, 4),
            "graph_density": round(density, 4),
            "graph_centrality_btc_z": round(cent_z, 4),
            "graph_clustering_z": round(clust_z, 4),
        }

    @staticmethod
    def _zscore(history: deque[float], current: float) -> float:
        if len(history) < 10:
            return 0.0
        mu = mean(history)
        sigma = pstdev(history) or 1e-9
        return (current - mu) / sigma

    def reset(self) -> None:
        self._prices.clear()
        self._history = _MetricHistory()
