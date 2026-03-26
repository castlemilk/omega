"""
omega.nodes.victoria.regime_detector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
3-state Hidden Markov Model for market regime detection.

States:
  - bull     (0): trending up, momentum regime
  - bear     (1): trending down, fear regime
  - sideways (2): ranging, mean-reversion regime

Features: [price_return, log_volatility, volume_ratio]

Signal weights are regime-dependent — momentum signals get higher weight in
trending regimes; mean-reversion signals get higher weight in sideways regimes.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

import numpy as np

logger = logging.getLogger("omega.nodes.victoria.regime_detector")

try:
    from hmmlearn import hmm as _hmm_lib

    _HMM_AVAILABLE = True
except ImportError:
    _HMM_AVAILABLE = False
    logger.warning("hmmlearn not installed — using rule-based regime fallback")

# Regime state indices
REGIME_BULL = "bull"
REGIME_BEAR = "bear"
REGIME_SIDEWAYS = "sideways"
REGIMES = [REGIME_BULL, REGIME_BEAR, REGIME_SIDEWAYS]

# Per-regime signal weight multipliers.
# Values > 1.0 boost the signal; < 1.0 attenuate it.
# These are applied multiplicatively to the IC-based weights before renormalization.
REGIME_SIGNAL_MULTIPLIERS: dict[str, dict[str, float]] = {
    REGIME_BULL: {
        "basic_signals": 1.4,  # momentum signals excel in trending up
        "cross_asset": 1.2,
        "market_data": 1.1,
        "order_flow": 1.3,  # order flow confirms breakouts
        "sentiment": 0.8,  # sentiment less predictive in full bull
        "microstructure": 0.7,  # mean-reversion signals misleading in trending
        "vrp": 1.0,
        "onchain": 1.1,
        "long_short_ratio": 1.2,
        "btc_dominance": 0.9,
    },
    REGIME_BEAR: {
        "basic_signals": 1.2,
        "cross_asset": 1.2,
        "market_data": 1.1,
        "order_flow": 1.0,
        "sentiment": 1.3,  # sentiment leads in fear regimes
        "microstructure": 0.9,
        "vrp": 1.4,  # vol regime signal most predictive in bear
        "onchain": 1.2,  # on-chain selling patterns matter
        "long_short_ratio": 1.3,
        "btc_dominance": 1.0,
    },
    REGIME_SIDEWAYS: {
        "basic_signals": 0.7,  # momentum useless in ranging
        "cross_asset": 0.9,
        "market_data": 0.9,
        "order_flow": 1.4,  # order flow / microstructure lead in ranging
        "sentiment": 1.1,
        "microstructure": 1.5,  # mean-reversion signals most relevant
        "vrp": 0.9,
        "onchain": 1.0,
        "long_short_ratio": 1.0,
        "btc_dominance": 1.1,
    },
}


class HMMRegimeDetector:
    """
    3-state HMM regime detector.

    Trains on rolling window of (return, volatility, volume_ratio) features.
    Retrains every 20 observations. Falls back to rule-based detection when
    hmmlearn is unavailable or insufficient data.

    Usage::
        detector = HMMRegimeDetector()
        result = detector.update(market_data)
        # {"regime": "bull", "probs": [0.7, 0.1, 0.2], "signal_multipliers": {...}}
    """

    MIN_TRAIN_SAMPLES = 30
    FEATURE_WINDOW = 120  # rolling history for training
    RETRAIN_EVERY = 20  # retrain every N new observations

    def __init__(self) -> None:
        self._model: Any = None
        self._hmm_state_to_regime: dict[int, str] = {}
        self._is_trained = False

        self._returns: deque[float] = deque(maxlen=self.FEATURE_WINDOW)
        self._vols: deque[float] = deque(maxlen=self.FEATURE_WINDOW)
        self._vol_ratios: deque[float] = deque(maxlen=self.FEATURE_WINDOW)

        self._regime_probs: list[float] = [1 / 3, 1 / 3, 1 / 3]
        self._current_regime: str = REGIME_SIDEWAYS
        self._obs_count = 0

    # ------------------------------------------------------------------ public

    def update(self, market_data: dict[str, Any]) -> dict[str, Any]:
        """
        Ingest new market data, update HMM, return regime result.

        Returns
        -------
        dict with keys: regime, probs, signal_multipliers, confidence
        """
        features = self._extract_features(market_data)
        if features is None:
            return self._fallback_result()

        ret, vol, vol_ratio = features
        self._returns.append(ret)
        self._vols.append(vol)
        self._vol_ratios.append(vol_ratio)
        self._obs_count += 1

        n = len(self._returns)
        if n < self.MIN_TRAIN_SAMPLES:
            return self._fallback_result()

        # Retrain periodically
        if _HMM_AVAILABLE and (not self._is_trained or self._obs_count % self.RETRAIN_EVERY == 0):
            self._train_hmm()

        if self._is_trained and _HMM_AVAILABLE:
            result = self._predict_hmm()
        else:
            result = self._rule_based(ret, vol)

        self._current_regime = result["regime"]
        self._regime_probs = result["probs"]
        return result

    @property
    def current_regime(self) -> str:
        return self._current_regime

    @property
    def regime_probs(self) -> list[float]:
        return self._regime_probs

    # ------------------------------------------------------------------ private

    def _extract_features(self, market_data: dict[str, Any]) -> tuple[float, float, float] | None:
        """Extract (return, annualised_vol, volume_ratio) from market_data."""
        # Prefer BTC as representative asset
        btc_data: dict[str, Any] | None = None
        for key in ("BTCUSDT", "BTC-USDT", "btcusdt", "BTC/USDT", "BTCUSD"):
            if key in market_data:
                btc_data = market_data[key]
                break
        if btc_data is None and market_data:
            btc_data = next(iter(market_data.values()))
        if btc_data is None or not isinstance(btc_data, dict):
            return None

        try:
            close = btc_data.get("close", [])
            volume = btc_data.get("volume", [])

            # 1-bar return
            if isinstance(close, list) and len(close) >= 2:
                c1, c0 = float(close[-1]), float(close[-2])
                ret = (c1 - c0) / c0 if c0 != 0 else 0.0
            else:
                ret = 0.0

            # Rolling 20-bar annualised vol
            if isinstance(close, list) and len(close) >= 10:
                prices = np.array(close[-20:], dtype=float)
                prices = prices[prices > 0]
                if len(prices) >= 2:
                    rets = np.diff(np.log(prices))
                    vol = float(np.std(rets)) * np.sqrt(252 * 24)  # hourly bars
                    vol = max(0.01, min(vol, 10.0))
                else:
                    vol = float(self._vols[-1]) if self._vols else 0.5
            else:
                vol = float(self._vols[-1]) if self._vols else 0.5

            # Volume ratio: latest vs 20-bar average
            if isinstance(volume, list) and len(volume) >= 5:
                arr = np.array(volume[-20:], dtype=float)
                arr = arr[arr > 0]
                vol_ratio = float(arr[-1] / np.mean(arr[:-1])) if len(arr) >= 2 else 1.0
                vol_ratio = max(0.1, min(vol_ratio, 10.0))
            else:
                vol_ratio = 1.0

            return float(ret), float(vol), float(vol_ratio)
        except Exception as exc:
            logger.debug("Feature extraction failed: %s", exc)
            return None

    def _train_hmm(self) -> None:
        """Fit GaussianHMM on collected feature history."""
        n = len(self._returns)
        if n < self.MIN_TRAIN_SAMPLES:
            return
        try:
            feat_mat = np.column_stack(
                [list(self._returns), list(self._vols), list(self._vol_ratios)]
            )
            model = _hmm_lib.GaussianHMM(
                n_components=3,
                covariance_type="diag",
                n_iter=100,
                random_state=42,
                min_covar=1e-4,
            )
            model.fit(feat_mat)

            # Map HMM state indices to regime labels by return mean
            means = model.means_  # shape (3, 3); col 0 = return
            ret_order = np.argsort(means[:, 0])  # ascending by return
            self._hmm_state_to_regime = {
                int(ret_order[0]): REGIME_BEAR,  # lowest return
                int(ret_order[1]): REGIME_SIDEWAYS,  # middle return
                int(ret_order[2]): REGIME_BULL,  # highest return
            }
            self._model = model
            self._is_trained = True
            logger.debug("HMM trained on %d samples", n)
        except Exception as exc:
            logger.debug("HMM training failed: %s", exc)

    def _predict_hmm(self) -> dict[str, Any]:
        """Predict regime using trained HMM."""
        try:
            feat_mat = np.column_stack(
                [list(self._returns), list(self._vols), list(self._vol_ratios)]
            )
            proba = self._model.predict_proba(feat_mat)  # (n, 3)
            current_probs = proba[-1]

            regime_probs: dict[str, float] = {r: 0.0 for r in REGIMES}
            for state_idx, p in enumerate(current_probs):
                regime_name = self._hmm_state_to_regime.get(state_idx, REGIME_SIDEWAYS)
                regime_probs[regime_name] = float(p)

            best = max(regime_probs, key=lambda k: regime_probs[k])
            probs_list = [
                regime_probs[REGIME_BULL],
                regime_probs[REGIME_BEAR],
                regime_probs[REGIME_SIDEWAYS],
            ]

            return {
                "regime": best,
                "probs": probs_list,
                "signal_multipliers": REGIME_SIGNAL_MULTIPLIERS.get(best, {}),
                "confidence": regime_probs[best],
                "source": "hmm",
            }
        except Exception as exc:
            logger.debug("HMM prediction failed: %s", exc)
            ret = float(self._returns[-1]) if self._returns else 0.0
            vol = float(self._vols[-1]) if self._vols else 0.5
            return self._rule_based(ret, vol)

    def _rule_based(self, ret: float, vol: float) -> dict[str, Any]:
        """Simple rule-based regime classification as fallback."""
        if len(self._returns) >= 10:
            recent_rets = list(self._returns)[-10:]
            avg_ret = float(np.mean(recent_rets))
            avg_vol = float(np.mean(list(self._vols)[-10:])) if len(self._vols) >= 10 else vol
        else:
            avg_ret, avg_vol = ret, vol

        if avg_ret > 0.003 and avg_vol < 0.8:
            regime, probs = REGIME_BULL, [0.7, 0.1, 0.2]
        elif avg_ret < -0.003 or avg_vol > 1.2:
            regime, probs = REGIME_BEAR, [0.1, 0.7, 0.2]
        else:
            regime, probs = REGIME_SIDEWAYS, [0.2, 0.2, 0.6]

        return {
            "regime": regime,
            "probs": probs,
            "signal_multipliers": REGIME_SIGNAL_MULTIPLIERS.get(regime, {}),
            "confidence": max(probs),
            "source": "rule_based",
        }

    def _fallback_result(self) -> dict[str, Any]:
        return {
            "regime": REGIME_SIDEWAYS,
            "probs": [1 / 3, 1 / 3, 1 / 3],
            "signal_multipliers": {},
            "confidence": 0.33,
            "source": "insufficient_data",
        }
