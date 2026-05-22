"""Spectral graph crash-duration detector.

During crashes, asset returns become highly correlated — the market moves
as a single block. This shows up as a wide spectral gap (λ1 ≫ λ2) on the
correlation-matrix eigendecomposition. Outside of crashes, the gap is
narrow (diverse drivers).

This module exposes three features per cycle:

    * `spectral_gap`         — λ1 - λ2 of the cross-asset return-correlation
                              matrix over a rolling window.
    * `spectral_gap_z`       — z-score vs rolling history of the gap. A
                              spike (z >= 2) marks crash ONSET. Sustained
                              elevation marks crash CONTINUATION.
    * `crash_duration`       — consecutive cycles with `spectral_gap_z`
                              above the threshold. Reset to 0 when z
                              drops below. The ensemble can use this to
                              size DOWN as duration grows (crash fatigue),
                              or to widen stops (volatility persisting).

Pure numpy-free implementation: power iteration for top 2 eigenvalues
of a 5×5-ish symmetric matrix is fast enough (~10 iterations to converge).
Works in both live and backtest (price-only, no WS dependency).

Companion to `dynamic_graph.py` — that module measures *which* assets
are central; this module measures *how cohesive* the market is overall.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Final, Sequence

logger = logging.getLogger("omega.nodes.victoria.signals.spectral_crash")

_DEFAULT_WINDOW: Final[int] = 30
_HISTORY: Final[int] = 100
_SPIKE_Z: Final[float] = 2.0
_POWER_ITERS: Final[int] = 30


@dataclass
class _SymPriceHistory:
    closes: deque[float] = field(default_factory=lambda: deque(maxlen=_DEFAULT_WINDOW))


@dataclass
class _SpectralHistory:
    gap_history: deque[float] = field(default_factory=lambda: deque(maxlen=_HISTORY))
    crash_duration: int = 0


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


def _top_two_eigvals(M: list[list[float]], iters: int = _POWER_ITERS) -> tuple[float, float]:
    """Power iteration for the top eigenvalue, deflation for the second.

    M is a symmetric n×n matrix. Returns (λ1, λ2) — both ≥ 0 for a
    correlation matrix (PSD).
    """
    n = len(M)
    if n == 0:
        return 0.0, 0.0

    def matvec(A: list[list[float]], v: list[float]) -> list[float]:
        return [sum(A[i][j] * v[j] for j in range(n)) for i in range(n)]

    def norm(v: list[float]) -> float:
        return sum(x * x for x in v) ** 0.5

    def rayleigh(A: list[list[float]], v: list[float]) -> float:
        Av = matvec(A, v)
        denom = sum(v[i] * v[i] for i in range(n)) or 1e-12
        return sum(v[i] * Av[i] for i in range(n)) / denom

    # Top eigenvalue (power iteration)
    v = [1.0 / (n ** 0.5)] * n
    for _ in range(iters):
        Av = matvec(M, v)
        nrm = norm(Av) or 1e-12
        v = [x / nrm for x in Av]
    lam1 = rayleigh(M, v)

    # Deflate: M' = M - λ1 v vᵀ
    M2 = [
        [M[i][j] - lam1 * v[i] * v[j] for j in range(n)]
        for i in range(n)
    ]
    # Top eigenvalue of M2 = λ2 of M
    u = [1.0 / (n ** 0.5)] * n
    for _ in range(iters):
        Mu = matvec(M2, u)
        # Orthogonalize against v each step to avoid re-discovering λ1
        proj = sum(u[i] * v[i] for i in range(n))
        u = [Mu[i] - proj * v[i] for i in range(n)]
        nrm = norm(u) or 1e-12
        u = [x / nrm for x in u]
    lam2 = rayleigh(M, u)

    return max(0.0, lam1), max(0.0, lam2)


class SpectralCrashSignal:
    """Computes the cross-asset correlation matrix each cycle, extracts the
    spectral gap (λ1 - λ2), and tracks z-scored crash duration."""

    def __init__(
        self,
        window: int = _DEFAULT_WINDOW,
        spike_z: float = _SPIKE_Z,
    ) -> None:
        self._window = window
        self._spike_z = spike_z
        self._prices: dict[str, _SymPriceHistory] = {}
        self._history = _SpectralHistory()

    def push_close(self, symbol: str, close: float) -> None:
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
        zero = {
            "spectral_gap": 0.0,
            "spectral_gap_z": 0.0,
            "crash_duration": 0.0,
        }
        symbols = [s for s, h in self._prices.items() if len(h.closes) >= max(5, self._window // 2)]
        if len(symbols) < 2:
            return zero

        # Build per-symbol return series, align length
        rets: dict[str, list[float]] = {s: _returns(list(self._prices[s].closes)) for s in symbols}
        min_len = min(len(r) for r in rets.values())
        if min_len < 5:
            return zero
        rets = {s: r[-min_len:] for s, r in rets.items()}

        # Correlation matrix (symbol × symbol)
        n = len(symbols)
        M = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i, n):
                if i == j:
                    M[i][j] = 1.0
                else:
                    rho = _pearson(rets[symbols[i]], rets[symbols[j]])
                    M[i][j] = M[j][i] = rho

        # Top two eigenvalues
        lam1, lam2 = _top_two_eigvals(M)
        gap = lam1 - lam2

        # Update history + crash-duration counter
        self._history.gap_history.append(gap)
        if len(self._history.gap_history) < 10:
            return {
                "spectral_gap": round(gap, 4),
                "spectral_gap_z": 0.0,
                "crash_duration": 0.0,
            }
        mu = mean(self._history.gap_history)
        sigma = pstdev(self._history.gap_history) or 1e-9
        z = (gap - mu) / sigma

        if z >= self._spike_z:
            self._history.crash_duration += 1
        else:
            self._history.crash_duration = 0

        return {
            "spectral_gap": round(gap, 4),
            "spectral_gap_z": round(z, 4),
            "crash_duration": float(self._history.crash_duration),
        }

    def reset(self) -> None:
        self._prices.clear()
        self._history = _SpectralHistory()
