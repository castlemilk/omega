"""
omega.nodes.victoria.spectral_signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Spectral graph theory stress indicator.

The signal correlation network forms a graph. The Laplacian eigenvalues reveal
when signals are fragmenting (market stress) vs converging (consensus).

Fiedler value (λ₂, second-smallest eigenvalue of the graph Laplacian):
- High Fiedler → signals well-connected → consensus → safe to trade
- Low Fiedler  → signals fragmenting    → stress    → reduce exposure
- Fiedler == 0 → graph disconnected    → maximum disagreement

References
----------
- Fiedler, M. (1973) "Algebraic connectivity of graphs", Czechoslovak Math J.
- Onnela et al. (2004) "Clustering and information in correlation based financial networks"
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

import numpy as np

from omega.nodes.victoria.information_flow import SIGNAL_NAMES

logger = logging.getLogger("omega.nodes.victoria.spectral_signals")

_CORR_THRESHOLD = 0.3   # adjacency edge weight threshold
_MIN_SAMPLES = 15        # minimum history before eigenvalue analysis is reliable
_ZSCORE_WINDOW = 50      # rolling window for z-scoring the Fiedler value
_EPS = 1e-8


@dataclass
class SignalValue:
    """Mirrors the SignalValue contract used by the other advanced signal nodes."""

    value: float        # z-scored Fiedler; >0 = consensus, <0 = stress/fragmentation
    confidence: float   # 0..1; grows with history length
    regime_tag: str     # "consensus" | "stress" | "fragmented" | "warmup"
    raw: dict


class SpectralGraphSignal:
    """
    Computes the Fiedler value (second-smallest eigenvalue of graph Laplacian)
    of the signal correlation network.

    When the Fiedler value drops, signals are fragmenting — different parts of
    the market see different things.  When it rises, signals converge on a
    shared story.

    Parameters
    ----------
    window : int
        Rolling window length for the signal history matrix (T rows x N cols).
    """

    def __init__(self, window: int = 30) -> None:
        self._signal_history: deque[list[float]] = deque(maxlen=window)
        self._fiedler_history: deque[float] = deque(maxlen=_ZSCORE_WINDOW)

    # ------------------------------------------------------------------ public

    def compute(self, signal_vector: dict[str, float]) -> SignalValue:
        """
        Update state with a new signal vector and return the spectral indicator.

        Parameters
        ----------
        signal_vector : dict
            Maps signal name → float value (any scale; only direction matters
            for the correlation adjacency matrix).
        """
        vec = np.array([signal_vector.get(s, 0.0) for s in SIGNAL_NAMES], dtype=float)
        self._signal_history.append(vec.tolist())

        n_samples = len(self._signal_history)

        if n_samples < _MIN_SAMPLES:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="warmup",
                raw={
                    "fiedler": 0.0,
                    "spectral_gap": 0.0,
                    "n_components": 1,
                    "n_samples": n_samples,
                },
            )

        data = np.array(self._signal_history)  # shape (T, N)
        N = data.shape[1]

        # -- Correlation matrix → adjacency matrix (threshold |corr| > 0.3) ---
        # np.corrcoef can produce NaN if a column is constant; guard against it.
        with np.errstate(invalid="ignore"):
            C = np.corrcoef(data.T)
        C = np.nan_to_num(C, nan=0.0)

        A = (np.abs(C) > _CORR_THRESHOLD).astype(float)
        np.fill_diagonal(A, 0)

        # -- Graph Laplacian L = D - A ----------------------------------------
        degrees = A.sum(axis=1)
        D = np.diag(degrees)
        L = D - A

        # -- Eigenvalues (symmetric → eigvalsh is faster & more stable) --------
        eigenvalues = np.sort(np.linalg.eigvalsh(L))

        # Fiedler value = λ₂ (second-smallest eigenvalue)
        fiedler = float(eigenvalues[1]) if N > 1 else 0.0

        # Spectral gap = λ_max - λ₂ (how "clustered" the graph is)
        spectral_gap = float(eigenvalues[-1] - eigenvalues[1]) if N > 1 else 0.0

        # Number of connected components = number of zero eigenvalues
        n_components = int(np.sum(eigenvalues < _EPS))

        # -- Z-score Fiedler vs rolling history ---------------------------------
        self._fiedler_history.append(fiedler)

        fiedler_zscore = 0.0
        if len(self._fiedler_history) >= 3:
            arr = np.array(self._fiedler_history)
            mu = float(arr.mean())
            sigma = float(arr.std())
            if sigma > _EPS:
                fiedler_zscore = (fiedler - mu) / sigma
            # If sigma ≈ 0, all Fiedler values are the same → no signal

        # -- Confidence grows with history depth --------------------------------
        confidence = min(abs(fiedler_zscore) / 2.0, 1.0)
        # Scale confidence by warmup completeness
        warmup_factor = min(n_samples / _MIN_SAMPLES, 1.0)
        confidence *= warmup_factor

        # -- Regime tag ---------------------------------------------------------
        if n_components > 1:
            regime_tag = "fragmented"          # graph is disconnected
        elif fiedler_zscore < -1.0:
            regime_tag = "stress"              # Fiedler below average → fragmentation
        elif fiedler_zscore > 0.5:
            regime_tag = "consensus"           # Fiedler above average → connectivity
        else:
            regime_tag = "neutral"

        logger.debug(
            "spectral: fiedler=%.4f z=%.3f gap=%.4f components=%d regime=%s",
            fiedler,
            fiedler_zscore,
            spectral_gap,
            n_components,
            regime_tag,
        )

        return SignalValue(
            value=fiedler_zscore,
            confidence=confidence,
            regime_tag=regime_tag,
            raw={
                "fiedler": round(fiedler, 6),
                "spectral_gap": round(spectral_gap, 6),
                "n_components": n_components,
                "n_samples": n_samples,
                "mean_degree": round(float(degrees.mean()), 4),
                "n_edges": int(A.sum() / 2),
            },
        )
