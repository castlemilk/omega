"""
omega.nodes.victoria.information_flow
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Transfer entropy analysis to measure directional information flow between signals.

Transfer entropy:  TE(X→Y) = H(Y_t | Y_{t-1}) - H(Y_t | Y_{t-1}, X_{t-lag})

This measures how much knowing X_past helps predict Y_future beyond what
Y_past alone tells us — i.e. the "causal" influence of X on Y.

High TE(X→Y) → X is a leading indicator for Y.
Low TE(X→Y) → knowing X doesn't help predict Y.

Practical use:
- Build a causality graph: which signals predict which others
- Identify leading signals at each lag (1..MAX_LAG cycles ahead)
- Use outgoing TE as an additional weight dimension on top of IC weights
- Replace correlation-based blending with causal blending
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

import numpy as np

logger = logging.getLogger("omega.nodes.victoria.information_flow")

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
]

N_SIGNALS = len(SIGNAL_NAMES)
MIN_SAMPLES_TE = 50  # need enough history for reliable TE
MAX_LAG = 5  # cycles to check for leading relationships
N_BINS = 4  # discretisation bins for entropy computation
RECOMPUTE_EVERY = 25  # recompute full TE matrix every N cycles


class TransferEntropyAnalyzer:
    """
    Computes transfer entropy between all signal pairs.

    Usage::
        analyzer = TransferEntropyAnalyzer()
        result = analyzer.update({"basic_signals": 0.3, "order_flow": 0.5, ...})
        causal_weights = result["causal_weights"]  # signal → relative influence
    """

    def __init__(self) -> None:
        self._history: deque[list[float]] = deque(maxlen=200)
        self._update_counter = 0

        # TE[i][j] = TE(signal_i → signal_j)
        self._te_matrix: np.ndarray = np.zeros((N_SIGNALS, N_SIGNALS))
        # Causal weight: normalised outgoing TE for each signal
        self._causal_weights: dict[str, float] = {n: 1.0 for n in SIGNAL_NAMES}
        # Optimal lead lag for each signal relative to basic_signals (proxy for price)
        self._lead_lags: dict[str, int] = {n: 1 for n in SIGNAL_NAMES}
        self._is_computed = False

    # ------------------------------------------------------------------ public

    def update(self, signal_values: dict[str, float]) -> dict[str, Any]:
        """
        Record a new observation and (periodically) recompute TE matrix.

        Returns
        -------
        dict with: causal_weights, te_matrix_summary, top_causal, lead_lags
        """
        row = [signal_values.get(n, 0.0) for n in SIGNAL_NAMES]
        self._history.append(row)
        self._update_counter += 1

        n = len(self._history)
        if n >= MIN_SAMPLES_TE and self._update_counter % RECOMPUTE_EVERY == 0:
            self._recompute()

        return {
            "causal_weights": dict(self._causal_weights),
            "top_causal": self._top_n(3),
            "lead_lags": dict(self._lead_lags),
            "is_computed": self._is_computed,
        }

    def apply_causal_weights(self, base_weights: dict[str, float]) -> dict[str, float]:
        """
        Blend base signal weights with causal influence weights.

        The returned weights are renormalised to sum to 1.

        Parameters
        ----------
        base_weights : existing IC-based or equal weights {signal_name: weight}
        """
        adjusted: dict[str, float] = {}
        for name, w in base_weights.items():
            causal = self._causal_weights.get(name, 1.0)
            adjusted[name] = w * causal

        total = sum(adjusted.values())
        if total > 0:
            return {k: v / total for k, v in adjusted.items()}
        return dict(base_weights)

    # ------------------------------------------------------------------ private

    def _recompute(self) -> None:
        """Full TE matrix recomputation."""
        try:
            mat = np.array(list(self._history), dtype=float)
            mat = np.nan_to_num(mat, nan=0.0)

            n_time, n_sigs = mat.shape
            te = np.zeros((n_sigs, n_sigs))

            for i in range(n_sigs):
                for j in range(n_sigs):
                    if i != j:
                        te[i, j] = self._te_pair(mat[:, i], mat[:, j], lag=1)

            self._te_matrix = te

            # Causal weight = normalised total outgoing TE
            outgoing = te.sum(axis=1)  # shape (n_sigs,)
            total = outgoing.sum()
            if total > 1e-8:
                # Normalise to have mean ≈ 1 (multiplicative adjustment)
                normed = (outgoing / total) * n_sigs
                self._causal_weights = {
                    SIGNAL_NAMES[i]: max(0.1, float(normed[i])) for i in range(n_sigs)
                }
            else:
                self._causal_weights = {n: 1.0 for n in SIGNAL_NAMES}

            # Lead lag analysis: which lag gives max TE(signal → basic_signals)
            price_idx = SIGNAL_NAMES.index("basic_signals")
            for i, name in enumerate(SIGNAL_NAMES):
                if name == "basic_signals":
                    self._lead_lags[name] = 0
                    continue
                best_lag, best_te = 1, 0.0
                for lag in range(1, min(MAX_LAG + 1, n_time // 5)):
                    te_val = self._te_pair(mat[:, i], mat[:, price_idx], lag=lag)
                    if te_val > best_te:
                        best_te = te_val
                        best_lag = lag
                self._lead_lags[name] = best_lag

            self._is_computed = True
            logger.info("TE matrix recomputed. Top causal signals: %s", self._top_n(3))
        except Exception as exc:
            logger.debug("TE recomputation failed: %s", exc)

    def _te_pair(self, x: np.ndarray, y: np.ndarray, lag: int) -> float:
        """
        Compute TE(X→Y) = H(Y_t|Y_{t-lag}) - H(Y_t|Y_{t-lag}, X_{t-lag}).

        Uses discretisation into N_BINS bins for entropy estimation.
        """
        n = len(x)
        if n <= lag + 5:
            return 0.0
        try:
            y_future = y[lag:]
            y_past = y[:-lag]
            x_past = x[:-lag]

            n_len = min(len(y_future), len(y_past), len(x_past))
            y_f = y_future[:n_len]
            y_p = y_past[:n_len]
            x_p = x_past[:n_len]

            yf_d = self._discretize(y_f)
            yp_d = self._discretize(y_p)
            xp_d = self._discretize(x_p)

            # H(Y_future | Y_past)
            h1 = self._cond_entropy(yf_d, yp_d)

            # H(Y_future | Y_past, X_past) — joint conditioning via composite key
            joint = yp_d * (N_BINS + 1) + xp_d
            h2 = self._cond_entropy(yf_d, joint)

            return max(0.0, float(h1 - h2))
        except Exception:
            return 0.0

    def _discretize(self, x: np.ndarray) -> np.ndarray:
        """Rank-based discretisation into N_BINS equal-frequency bins."""
        pct = np.linspace(0, 100, N_BINS + 1)
        edges = np.percentile(x, pct)
        edges = np.unique(edges)
        bins: list[float] = edges[1:-1].tolist()
        result: np.ndarray = np.array(np.digitize(x, bins), dtype=np.intp)
        return result

    def _entropy(self, x: np.ndarray) -> float:
        """Shannon entropy H(X) in bits."""
        _, counts = np.unique(x, return_counts=True)
        p = counts / counts.sum()
        return float(-np.sum(p * np.log2(p + 1e-12)))

    def _cond_entropy(self, x: np.ndarray, y: np.ndarray) -> float:
        """Conditional entropy H(X|Y) = H(X,Y) - H(Y)."""
        # Joint
        joint = x * (np.max(x) + 1) + y
        return self._entropy(joint) - self._entropy(y)

    def _top_n(self, n: int) -> list[str]:
        return sorted(self._causal_weights, key=lambda k: self._causal_weights[k], reverse=True)[
            :n
        ]
