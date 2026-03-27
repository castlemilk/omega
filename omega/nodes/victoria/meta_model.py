"""
omega.nodes.victoria.meta_model
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Ensemble meta-learner — the "Medallion Fund" layer.

Stacks regime probabilities, PCA factor exposures, individual signal values,
and signal disagreement structure into a feature vector, then trains a
GradientBoostingClassifier (falls back to LogisticRegression) to predict
binary trade outcomes (win/loss) from the paper_trades history.

Rolling retrain every RETRAIN_INTERVAL cycles on the most recent 200 trades.

When the meta-model is fitted and confident, it replaces the simple IC-weighted
blend as the source of the final conviction score.  When insufficient data is
available it degrades gracefully to the weighted average fallback.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

import numpy as np

logger = logging.getLogger("omega.nodes.victoria.meta_model")

try:
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not installed — meta-model will use fallback blending")

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

RETRAIN_INTERVAL = 50  # retrain every N recorded outcomes
MIN_SAMPLES_META = 50  # minimum outcomes before meta-model activates
MAX_TRAIN_SAMPLES = 200  # rolling window for training
N_REGIME_PROBS = 3  # [p_bull, p_bear, p_sideways]
N_FACTORS = 3  # PCA factor exposures


class MetaModel:
    """
    Stacked ensemble meta-learner.

    Feature vector (per cycle):
      [p_bull, p_bear, p_sideways,          # 3 regime probabilities
       f1, f2, f3,                           # 3 PCA factor exposures
       sig_0, ..., sig_9,                    # 10 raw signal values
       signal_std, signal_range,             # 2 disagreement features
       n_bullish, n_bearish,                 # 2 conviction counts
       ic_w_0, ..., ic_w_9]                  # 10 IC weights

    Target: 1 = trade won, 0 = trade lost

    Usage::
        meta = MetaModel()
        result = meta.predict(regime_probs, factors, signal_values, ic_weights)
        meta.record_outcome(pnl=+500.0)
    """

    def __init__(self) -> None:
        self._model: Any = None
        self._scaler: Any = None
        self._is_fitted = False
        self._outcome_count = 0
        self._win_rate = 0.5

        # Ring buffer of (features, label) pairs
        self._features: deque[list[float]] = deque(maxlen=MAX_TRAIN_SAMPLES)
        self._labels: deque[int] = deque(maxlen=MAX_TRAIN_SAMPLES)

        # Buffer of pending feature vectors (awaiting their trade outcome)
        # Each entry: {"features": list[float], "cycle": int}
        self._pending: deque[dict[str, Any]] = deque(maxlen=20)

        self._cycle = 0
        self._last_conviction = 0.0
        self._last_confidence = 0.0
        self._last_win_prob = 0.5

    # ------------------------------------------------------------------ public

    def predict(
        self,
        regime_probs: list[float],
        factors: list[float],
        signal_values: dict[str, float],
        ic_weights: dict[str, float],
    ) -> dict[str, Any]:
        """
        Compute meta-model conviction for the current cycle.

        Parameters
        ----------
        regime_probs : [p_bull, p_bear, p_sideways]
        factors      : PCA factor exposures [f1, f2, f3]
        signal_values: {signal_name: value} for each signal
        ic_weights   : {signal_name: weight} from DynamicWeightAllocator

        Returns
        -------
        dict with: conviction [-1,1], confidence, win_probability, use_meta, source
        """
        features = self._build_features(regime_probs, factors, signal_values, ic_weights)
        self._pending.append({"features": features, "cycle": self._cycle})
        self._cycle += 1

        if not self._is_fitted or not _SKLEARN_AVAILABLE:
            conviction = self._fallback_blend(signal_values, ic_weights)
            return {
                "conviction": conviction,
                "confidence": 0.5,
                "win_probability": self._win_rate,
                "use_meta": False,
                "source": "fallback_ic_blend",
            }

        try:
            x = np.array(features, dtype=float).reshape(1, -1)
            x = np.nan_to_num(x, nan=0.0, posinf=1.0, neginf=-1.0)
            x_s = self._scaler.transform(x)

            proba = self._model.predict_proba(x_s)[0]
            win_prob = float(proba[1]) if len(proba) > 1 else float(proba[0])

            # Direction from raw signal consensus
            sig_vals = [signal_values.get(n, 0.0) for n in SIGNAL_NAMES]
            avg_signal = float(np.mean(sig_vals)) if sig_vals else 0.0

            # Magnitude from meta-model confidence; direction from signal consensus
            magnitude = abs(win_prob - 0.5) * 2.0  # ∈ [0, 1]
            direction = 1.0 if avg_signal >= 0 else -1.0
            conviction = direction * magnitude

            confidence = magnitude
            self._last_conviction = conviction
            self._last_confidence = confidence
            self._last_win_prob = win_prob

            return {
                "conviction": max(-1.0, min(1.0, conviction)),
                "confidence": round(confidence, 4),
                "win_probability": round(win_prob, 4),
                "use_meta": True,
                "source": "meta_model",
            }
        except Exception as exc:
            logger.debug("Meta-model inference failed: %s", exc)
            return {
                "conviction": self._fallback_blend(signal_values, ic_weights),
                "confidence": 0.5,
                "win_probability": self._win_rate,
                "use_meta": False,
                "source": "fallback_error",
            }

    def record_outcome(self, pnl: float) -> None:
        """
        Record a trade outcome.  Pops the oldest pending feature vector and
        pairs it with the win/loss label, then retrains every RETRAIN_INTERVAL.
        """
        if not self._pending:
            return

        entry = self._pending.popleft()
        label = 1 if pnl > 0 else 0
        self._features.append(entry["features"])
        self._labels.append(label)
        self._outcome_count += 1

        # Rolling win rate
        n = len(self._labels)
        if n > 0:
            self._win_rate = float(sum(self._labels) / n)

        # Retrain
        if n >= MIN_SAMPLES_META and self._outcome_count % RETRAIN_INTERVAL == 0:
            self._retrain()

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted

    @property
    def win_rate(self) -> float:
        return self._win_rate

    @property
    def outcome_count(self) -> int:
        return self._outcome_count

    # ------------------------------------------------------------------ private

    def _build_features(
        self,
        regime_probs: list[float],
        factors: list[float],
        signal_values: dict[str, float],
        ic_weights: dict[str, float],
    ) -> list[float]:
        """Build flat feature vector."""
        # Regime probs (pad to 3)
        rp = list(regime_probs)[:N_REGIME_PROBS]
        rp += [1 / 3] * max(0, N_REGIME_PROBS - len(rp))

        # Factor exposures (pad to 3)
        fv = list(factors)[:N_FACTORS]
        fv += [0.0] * max(0, N_FACTORS - len(fv))

        # Signal values
        svals = [float(signal_values.get(n, 0.0)) for n in SIGNAL_NAMES]

        # Disagreement structure
        arr = np.array(svals)
        sig_std = float(np.std(arr))
        sig_range = float(np.max(arr) - np.min(arr))
        n_bullish = float(np.sum(arr > 0.1))
        n_bearish = float(np.sum(arr < -0.1))

        # IC weights
        iw = [float(ic_weights.get(n, 1.0 / len(SIGNAL_NAMES))) for n in SIGNAL_NAMES]

        return rp + fv + svals + [sig_std, sig_range, n_bullish, n_bearish] + iw

    def _retrain(self) -> None:
        """Retrain classifier on buffered (features, label) pairs."""
        if not _SKLEARN_AVAILABLE:
            return

        n = len(self._labels)
        if n < MIN_SAMPLES_META:
            return

        x_mat = np.array(list(self._features), dtype=float)
        y = np.array(list(self._labels), dtype=int)

        x_mat = np.nan_to_num(x_mat, nan=0.0, posinf=1.0, neginf=-1.0)

        if len(np.unique(y)) < 2:
            logger.debug("Meta-model: only one class — skipping retrain")
            return

        try:
            scaler = StandardScaler()
            x_scaled = scaler.fit_transform(x_mat)

            try:
                model: Any = GradientBoostingClassifier(
                    n_estimators=50,
                    max_depth=3,
                    learning_rate=0.08,
                    subsample=0.8,
                    min_samples_leaf=10,
                    max_features="sqrt",
                    random_state=42,
                )
                model.fit(x_scaled, y)
            except Exception:
                # Fallback to logistic regression
                model = LogisticRegression(C=0.5, max_iter=500, random_state=42)
                model.fit(x_scaled, y)

            preds = model.predict(x_scaled)
            acc = float(np.mean(preds == y))

            self._scaler = scaler
            self._model = model
            self._is_fitted = True

            logger.info(
                "MetaModel retrained: n=%d train_acc=%.3f win_rate=%.3f",
                n,
                acc,
                self._win_rate,
            )
        except Exception as exc:
            logger.warning("Meta-model retrain failed: %s", exc)

    def _fallback_blend(
        self,
        signal_values: dict[str, float],
        ic_weights: dict[str, float],
    ) -> float:
        """IC-weighted blend used when meta-model is not yet fitted."""
        total_w = sum(ic_weights.values()) or 1.0
        composite = (
            sum(signal_values.get(n, 0.0) * ic_weights.get(n, 0.0) for n in SIGNAL_NAMES) / total_w
        )
        return max(-1.0, min(1.0, composite))
