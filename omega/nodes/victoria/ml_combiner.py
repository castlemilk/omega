"""
omega.nodes.victoria.ml_combiner
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Learned signal combiner that replaces the naive equal-weight composite in
signal_generation.py.

Uses Ridge regression (closed-form) to learn per-signal weights from realized
PnL.  Falls back to equal weights when fewer than 30 training samples are
available or when numpy is not installed.

Closed-form Ridge:
    w = (X^T X + alpha * I)^{-1} X^T y

where alpha=1.0 provides L2 regularisation that keeps weights from blowing
up on small sample sizes or near-collinear signal columns.
"""

from __future__ import annotations

import json
import logging
import os
from collections import deque
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.ml_combiner")

# Try importing numpy; if unavailable, fall back to pure-Python ridge.
try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:
    np = None
    _HAS_NUMPY = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fixed signal key order used to build the feature vector.
# All keys that _extract_features should look for in a signals dict.
SIGNAL_KEYS: list[str] = [
    "rsi_signal",
    "macd_crossover",
    "sma_crossover",
    "zscore_signal",
    "volume_signal",
    "bb_signal",
    "vol_regime_signal",
    "btc_beta_signal",
    # Cross-asset market-level signals (V64-V67)
    "funding_rate_signal",
    "fear_greed_signal",
    "dxy_signal",
    "vix_signal",
    "yield_curve_signal",
]

_ALPHA = 1.0  # Ridge regularisation strength
_MAX_BUFFER = 500  # Max number of (X, y) samples retained
_MIN_SAMPLES = 30  # Minimum samples before switching from equal-weight


# ---------------------------------------------------------------------------
# Pure-Python helpers (no numpy)
# ---------------------------------------------------------------------------


def _dot(v1: list[float], v2: list[float]) -> float:
    """Inner product of two equal-length lists."""
    return sum(a * b for a, b in zip(v1, v2, strict=False))


def _mat_vec_mul(M: list[list[float]], v: list[float]) -> list[float]:
    """Matrix-vector multiplication M @ v."""
    return [_dot(row, v) for row in M]


def _mat_mat_mul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    """Matrix-matrix multiplication A @ B."""
    n_rows = len(A)
    n_cols = len(B[0])
    n_inner = len(B)
    C = [[0.0] * n_cols for _ in range(n_rows)]
    for i in range(n_rows):
        for j in range(n_cols):
            C[i][j] = sum(A[i][k] * B[k][j] for k in range(n_inner))
    return C


def _transpose(M: list[list[float]]) -> list[list[float]]:
    if not M:
        return []
    rows, cols = len(M), len(M[0])
    return [[M[r][c] for r in range(rows)] for c in range(cols)]


def _mat_add_diag(M: list[list[float]], diag_val: float) -> list[list[float]]:
    """Add diag_val to every diagonal element of M (in-place copy)."""
    n = len(M)
    out = [row[:] for row in M]
    for i in range(n):
        out[i][i] += diag_val
    return out


def _gauss_jordan_inverse(M: list[list[float]]) -> list[list[float]] | None:
    """
    Invert square matrix M using Gauss-Jordan elimination.
    Returns None if M is singular.
    """
    n = len(M)
    # Augment [M | I]
    aug = [row[:] + ([1.0 if i == j else 0.0 for j in range(n)]) for i, row in enumerate(M)]
    for col in range(n):
        # Find pivot
        pivot_row = None
        max_val = 0.0
        for row in range(col, n):
            if abs(aug[row][col]) > max_val:
                max_val = abs(aug[row][col])
                pivot_row = row
        if pivot_row is None or max_val < 1e-12:
            return None  # singular
        aug[col], aug[pivot_row] = aug[pivot_row], aug[col]
        scale = aug[col][col]
        aug[col] = [x / scale for x in aug[col]]
        for row in range(n):
            if row != col:
                factor = aug[row][col]
                aug[row] = [aug[row][k] - factor * aug[col][k] for k in range(2 * n)]
    return [row[n:] for row in aug]


def _pure_python_ridge(X: list[list[float]], y: list[float], alpha: float) -> list[float] | None:
    """
    Closed-form Ridge regression without numpy.
    Returns weight vector w of length n_features, or None on failure.
    """
    try:
        Xt = _transpose(X)
        XtX = _mat_mat_mul(Xt, X)
        XtX_reg = _mat_add_diag(XtX, alpha)
        inv = _gauss_jordan_inverse(XtX_reg)
        if inv is None:
            return None
        Xty = _mat_vec_mul(Xt, y)
        w = _mat_vec_mul(inv, Xty)
        return w
    except Exception as exc:
        logger.debug("pure-python ridge failed: %s", exc)
        return None


def _numpy_ridge(X: list[list[float]], y: list[float], alpha: float) -> list[float] | None:
    """Closed-form Ridge using numpy for speed and numerical stability."""
    try:
        Xnp = np.array(X, dtype=float)
        ynp = np.array(y, dtype=float)
        XtX = Xnp.T @ Xnp
        XtX_reg = XtX + alpha * np.eye(XtX.shape[0])
        w = np.linalg.solve(XtX_reg, Xnp.T @ ynp)
        weights: list[float] = w.tolist()
        return weights
    except Exception as exc:
        logger.debug("numpy ridge failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# SignalCombiner
# ---------------------------------------------------------------------------


class SignalCombiner:
    """
    Learned signal combiner using online-updated Ridge regression.

    Usage
    -----
    combiner = SignalCombiner()
    combiner.load("data/signal_weights.json")          # optional warm-start
    score = combiner.predict(signals_dict)             # [-1, 1] or None
    combiner.update(signals_dict, realized_pnl)        # after trade closes
    combiner.persist("data/signal_weights.json")       # save updated weights
    """

    def __init__(self) -> None:
        self._min_samples: int = _MIN_SAMPLES
        self._alpha: float = _ALPHA
        self._max_buffer: int = _MAX_BUFFER

        # Rolling buffer of (feature_vector, label) pairs
        self._buffer: deque[tuple[list[float], float]] = deque(maxlen=_MAX_BUFFER)

        # Learned weight vector (one per SIGNAL_KEYS entry).
        # None means "not yet trained" → fall back to equal weights.
        self._weights: list[float] | None = None

        # Intercept term
        self._intercept: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(self, X: list[dict[str, Any]], y: list[float]) -> None:
        """
        Batch fit from a list of signal dicts and forward returns.

        Parameters
        ----------
        X : list[dict]
            Each dict contains sub-signal keys (see SIGNAL_KEYS).
        y : list[float]
            Corresponding realised forward returns (or PnL values).
        """
        if len(X) != len(y):
            raise ValueError(f"X and y must be same length: {len(X)} vs {len(y)}")
        if not X:
            return

        # Replace buffer with the new batch (but respect max size)
        self._buffer.clear()
        for signals_dict, label in zip(X, y, strict=False):
            feats = self._extract_features(signals_dict)
            self._buffer.append((feats, label))

        self._refit()

    def predict(self, signals_dict: dict[str, Any]) -> float | None:
        """
        Return a combined score in [-1, 1].

        Returns None if fewer than _min_samples are available (caller
        should fall back to _balanced_composite).
        """
        if len(self._buffer) < self._min_samples or self._weights is None:
            return None

        feats = self._extract_features(signals_dict)
        raw = _dot(feats, self._weights) + self._intercept
        # Clip to [-1, 1]
        return max(-1.0, min(1.0, raw))

    def update(self, signals_dict: dict[str, Any], realized_pnl: float) -> None:
        """
        Online update: incorporate one new (signals, pnl) observation and
        refit with the full rolling buffer.
        """
        feats = self._extract_features(signals_dict)
        self._buffer.append((feats, realized_pnl))

        if len(self._buffer) >= self._min_samples:
            self._refit()

    def persist(self, path: str) -> None:
        """Serialize weights and buffer to a JSON file."""
        try:
            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
            payload: dict[str, Any] = {
                "signal_keys": SIGNAL_KEYS,
                "weights": self._weights,
                "intercept": self._intercept,
                "n_samples": len(self._buffer),
                "buffer": [{"x": list(x), "y": y} for x, y in self._buffer],
            }
            with open(path, "w") as fh:
                json.dump(payload, fh, indent=2)
            logger.debug("SignalCombiner: persisted %d samples to %s", len(self._buffer), path)
        except Exception as exc:
            logger.warning("SignalCombiner: persist failed: %s", exc)

    def load(self, path: str) -> None:
        """Load weights and buffer from a JSON file (silent no-op if missing)."""
        if not os.path.exists(path):
            return
        try:
            with open(path) as fh:
                payload = json.load(fh)
            stored_keys = payload.get("signal_keys", [])
            weights_raw = payload.get("weights")
            self._intercept = float(payload.get("intercept", 0.0))

            # Restore buffer
            self._buffer.clear()
            for entry in payload.get("buffer", []):
                x = entry.get("x", [])
                y = entry.get("y", 0.0)
                if len(x) == len(SIGNAL_KEYS):
                    self._buffer.append((x, float(y)))

            # Restore weights only if the key layout matches
            if stored_keys == SIGNAL_KEYS and weights_raw and len(weights_raw) == len(SIGNAL_KEYS):
                self._weights = [float(w) for w in weights_raw]
                logger.info(
                    "SignalCombiner: loaded %d samples, weights=%s",
                    len(self._buffer),
                    [round(w, 4) for w in self._weights],
                )
            else:
                # Key layout changed — refit from buffer if we have enough samples
                logger.info(
                    "SignalCombiner: key layout mismatch (stored=%s, current=%s) — refitting",
                    stored_keys,
                    SIGNAL_KEYS,
                )
                self._weights = None
                if len(self._buffer) >= self._min_samples:
                    self._refit()
        except Exception as exc:
            logger.warning("SignalCombiner: load failed (%s) — starting fresh", exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_features(self, signals_dict: dict[str, Any]) -> list[float]:
        """
        Extract a fixed-length feature vector from a signals dict.
        Missing keys are filled with 0.0.
        """
        return [float(signals_dict.get(key, 0.0)) for key in SIGNAL_KEYS]

    def _refit(self) -> None:
        """Refit Ridge regression from the current buffer."""
        if len(self._buffer) < self._min_samples:
            return

        X_list = [list(x) for x, _ in self._buffer]
        y_list = [y for _, y in self._buffer]

        # Demean y to get a clean intercept
        y_mean = sum(y_list) / len(y_list)
        y_centered = [yi - y_mean for yi in y_list]

        if _HAS_NUMPY:
            w = _numpy_ridge(X_list, y_centered, self._alpha)
        else:
            w = _pure_python_ridge(X_list, y_centered, self._alpha)

        if w is None:
            logger.debug("SignalCombiner: ridge solve failed — retaining previous weights")
            return

        self._weights = w
        self._intercept = y_mean
        logger.debug(
            "SignalCombiner: refitted on %d samples; weights=%s",
            len(self._buffer),
            [round(wi, 4) for wi in w],
        )
