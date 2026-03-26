"""
omega.nodes.victoria.factor_model
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
PCA-based factor model for signal decomposition.

Extracts N orthogonal factors from the 11 signal time series, tests for
cointegration between signal pairs (Engle-Granger), and builds a factor
loading matrix used to produce a statistically robust composite score.

Rolling 50-cycle windows are used for coefficient estimation so the model
tracks evolving signal relationships rather than fitting a static structure.

Typical factor interpretation (crypto context):
  F1 — broad market momentum (loads on most signals positively)
  F2 — risk-on / risk-off divergence
  F3 — mean-reversion vs momentum divergence
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

import numpy as np

logger = logging.getLogger("omega.nodes.victoria.factor_model")

try:
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not installed — using numpy SVD for PCA")

try:
    from statsmodels.tsa.stattools import coint

    _STATSMODELS_AVAILABLE = True
except ImportError:
    _STATSMODELS_AVAILABLE = False

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

N_COMPONENTS = 3  # number of principal factors to extract
ROLLING_WINDOW = 100  # max history to keep
MIN_SAMPLES = 20  # minimum observations before fitting
REFIT_EVERY = 10  # refit every N new observations
COINT_TEST_EVERY = 50  # run cointegration tests every N observations


class SignalFactorModel:
    """
    PCA factor model on signal time series.

    Usage::
        model = SignalFactorModel()
        result = model.update({"basic_signals": 0.3, "order_flow": 0.5, ...})
        # {"factors": [0.7, -0.2, 0.1], "composite": 0.45, "is_fitted": True, ...}
    """

    def __init__(self, n_components: int = N_COMPONENTS) -> None:
        self._n_components = n_components
        self._history: deque[list[float]] = deque(maxlen=ROLLING_WINDOW)
        self._obs_count = 0

        # Fitted model state
        self._pca: Any = None
        self._scaler: Any = None
        self._is_fitted = False
        self._explained_variance: list[float] = []
        self._factor_loadings: np.ndarray | None = None  # (n_signals, n_components)

        # Numpy-fallback PCA params
        self._np_mean: np.ndarray | None = None
        self._np_std: np.ndarray | None = None
        self._np_components: np.ndarray | None = None  # (n_components, n_signals)

        # Cointegration
        self._cointegrated_pairs: list[tuple[str, str, float]] = []

        self._last_factors: list[float] = [0.0] * n_components
        self._last_composite: float = 0.0

    # ------------------------------------------------------------------ public

    def update(self, signal_values: dict[str, float]) -> dict[str, Any]:
        """
        Record a new signal observation and compute factor decomposition.

        Parameters
        ----------
        signal_values : {signal_name: float} for each of the 11 signals

        Returns
        -------
        dict with: factors, composite, factor_loadings, explained_variance, is_fitted
        """
        row = [signal_values.get(name, 0.0) for name in SIGNAL_NAMES]
        self._history.append(row)
        self._obs_count += 1

        n = len(self._history)
        if n < MIN_SAMPLES:
            return self._fallback(signal_values)

        # Refit periodically
        if not self._is_fitted or self._obs_count % REFIT_EVERY == 0:
            self._fit()

        if _STATSMODELS_AVAILABLE and n >= MIN_SAMPLES and self._obs_count % COINT_TEST_EVERY == 0:
            self._test_cointegration()

        if not self._is_fitted:
            return self._fallback(signal_values)

        return self._project(row)

    @property
    def last_factors(self) -> list[float]:
        return self._last_factors

    @property
    def cointegrated_pairs(self) -> list[tuple[str, str, float]]:
        return self._cointegrated_pairs

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted

    # ------------------------------------------------------------------ private

    def _get_matrix(self) -> np.ndarray | None:
        if not self._history:
            return None
        mat: np.ndarray = np.array(list(self._history), dtype=float)
        # Replace NaN/Inf
        mat = np.nan_to_num(mat, nan=0.0, posinf=1.0, neginf=-1.0)
        return mat

    def _fit(self) -> None:
        """Fit PCA on current signal history."""
        mat = self._get_matrix()
        if mat is None or mat.shape[0] < MIN_SAMPLES:
            return

        n_comp = min(self._n_components, mat.shape[1], mat.shape[0])

        if _SKLEARN_AVAILABLE:
            try:
                scaler = StandardScaler()
                mat_scaled = scaler.fit_transform(mat)
                pca = PCA(n_components=n_comp)
                pca.fit(mat_scaled)
                self._scaler = scaler
                self._pca = pca
                self._factor_loadings = pca.components_.T  # (n_signals, n_comp)
                self._explained_variance = pca.explained_variance_ratio_.tolist()
                self._is_fitted = True
                logger.debug(
                    "PCA fitted: %d factors explain %.1f%% variance",
                    n_comp,
                    sum(self._explained_variance) * 100,
                )
                return
            except Exception as exc:
                logger.debug("sklearn PCA failed: %s", exc)

        # Numpy SVD fallback
        try:
            mean = np.mean(mat, axis=0)
            std = np.std(mat, axis=0)
            std[std < 1e-8] = 1.0
            mat_scaled = (mat - mean) / std
            _u, s_vals, vt = np.linalg.svd(mat_scaled, full_matrices=False)
            total_var = np.sum(s_vals**2)
            self._np_mean = mean
            self._np_std = std
            self._np_components = vt[:n_comp]
            self._explained_variance = (s_vals[:n_comp] ** 2 / total_var).tolist()
            self._factor_loadings = self._np_components.T  # (n_signals, n_comp)
            self._is_fitted = True
            logger.debug("NumPy SVD PCA fitted: %d components", n_comp)
        except Exception as exc:
            logger.debug("NumPy PCA failed: %s", exc)

    def _project(self, row: list[float]) -> dict[str, Any]:
        """Project latest signal observation onto principal factors."""
        x = np.array(row, dtype=float)
        x = np.nan_to_num(x, nan=0.0, posinf=1.0, neginf=-1.0)

        try:
            if _SKLEARN_AVAILABLE and self._pca is not None:
                x_s = self._scaler.transform(x.reshape(1, -1))[0]
                factors = self._pca.transform(x_s.reshape(1, -1))[0].tolist()
            elif self._np_components is not None:
                x_s = (x - self._np_mean) / self._np_std
                factors = (self._np_components @ x_s).tolist()
            else:
                return self._fallback(dict(zip(SIGNAL_NAMES, row, strict=False)))

            self._last_factors = factors

            # Composite: variance-weighted sum of factors, scaled to [-1, 1]
            ev = np.array(self._explained_variance)
            if ev.sum() > 0 and len(factors) >= len(ev):
                ev_w = ev / ev.sum()
                raw = float(np.dot(ev_w, np.array(factors[: len(ev)])))
                # Soft-clip: typical factor score range is ±3
                composite = float(np.tanh(raw / 2.0))
            else:
                composite = 0.0

            self._last_composite = composite

            # Factor loading summary (signal → F1 loading for quick inspection)
            fl_summary: dict[str, float] = {}
            if self._factor_loadings is not None:
                for i, name in enumerate(SIGNAL_NAMES):
                    if i < self._factor_loadings.shape[0]:
                        fl_summary[name] = float(self._factor_loadings[i, 0])

            return {
                "factors": factors,
                "composite": composite,
                "factor_loadings_f1": fl_summary,
                "explained_variance": self._explained_variance,
                "is_fitted": True,
                "cointegrated_pairs": [
                    (a, b, round(p, 4)) for a, b, p in self._cointegrated_pairs[:5]
                ],
            }
        except Exception as exc:
            logger.debug("Factor projection failed: %s", exc)
            return self._fallback(dict(zip(SIGNAL_NAMES, row, strict=False)))

    def _test_cointegration(self) -> None:
        """Run Engle-Granger cointegration tests on all signal pairs."""
        mat = self._get_matrix()
        if mat is None or mat.shape[0] < 50:
            return
        pairs: list[tuple[str, str, float]] = []
        for i, ni in enumerate(SIGNAL_NAMES):
            for j, nj in enumerate(SIGNAL_NAMES[i + 1 :], start=i + 1):
                s1, s2 = mat[:, i], mat[:, j]
                if np.std(s1) < 1e-6 or np.std(s2) < 1e-6:
                    continue
                try:
                    _, p_val, _ = coint(s1, s2)
                    if p_val < 0.05:
                        pairs.append((ni, nj, float(p_val)))
                except Exception:
                    pass
        self._cointegrated_pairs = sorted(pairs, key=lambda t: t[2])
        if pairs:
            logger.info(
                "Cointegration: %d pairs (p<0.05). Top: %s",
                len(pairs),
                [(a, b) for a, b, _ in pairs[:3]],
            )

    def _fallback(self, signal_values: dict[str, float]) -> dict[str, Any]:
        """Equal-weight composite fallback when model not yet fitted."""
        vals = [float(signal_values.get(n, 0.0)) for n in SIGNAL_NAMES]
        composite = float(np.mean(vals)) if vals else 0.0
        composite = max(-1.0, min(1.0, composite))
        return {
            "factors": [0.0] * self._n_components,
            "composite": composite,
            "factor_loadings_f1": {},
            "explained_variance": [],
            "is_fitted": False,
            "cointegrated_pairs": [],
        }
