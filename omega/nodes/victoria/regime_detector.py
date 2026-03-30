"""
omega.nodes.victoria.regime_detector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Regime-aware signal weight multipliers derived from backtest IC analysis.

Three market regimes are supported:
  - BULL     : trending upward  (e.g. Oct 2023 - Mar 2024)
  - BEAR     : sustained decline (e.g. May 2022 - Nov 2022)
  - SIDEWAYS : range-bound / mean-reverting (e.g. Jul 2024 - Oct 2024)

Design
------
IC findings from historical backtest (signal Information Coefficients by regime):
  BULL     : momentum works when trending; vol_regime harmful
  BEAR     : rsi strongest (+0.144); momentum harmful
  SIDEWAYS : vol_regime strongest (-0.389, high-vol = bearish); rsi works (+0.140)

The multiplier table is applied ON TOP of base IC weights from DynamicWeightAllocator.
After multiplier application:
  1. BULL regime enforces a momentum floor (min weight 0.3) to prevent the
     meta-model from fading momentum in up-trends.
  2. Trend strength is assessed to decide whether momentum signal is trusted.
  3. Per-regime conviction thresholds gate trade entry.

Signal name mapping (used throughout this file)
-----------------------------------------------
  "momentum"   - SMA crossover signal (trend-following)
  "rsi"        - RSI mean-reversion signal
  "vol_regime" - Volatility regime signal (low-vol bullish, high-vol bearish)
  "bb"         - Bollinger Band mean-reversion signal
  "macd"       - MACD histogram crossover signal
  "vwm"        - Volume-weighted momentum signal
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger("omega.nodes.victoria.regime_detector")

try:
    import hmmlearn.hmm as _hmm_lib

    _HMM_AVAILABLE = True
except ImportError:
    _HMM_AVAILABLE = False

# ---------------------------------------------------------------------------
# Regime labels
# ---------------------------------------------------------------------------

BULL = "bull"
BEAR = "bear"
SIDEWAYS = "sideways"

KNOWN_REGIMES: frozenset[str] = frozenset({BULL, BEAR, SIDEWAYS})

# ---------------------------------------------------------------------------
# Signal multiplier lookup table (regime -> signal_name -> multiplier)
# Applied on top of base IC weights.  Signals not listed default to 1.0.
# ---------------------------------------------------------------------------

REGIME_SIGNAL_MULTIPLIERS: dict[str, dict[str, float]] = {
    BULL: {
        "momentum": 1.5,  # Trend-following works well in up-trends
        "rsi": 0.5,  # Mean-reversion unreliable during sustained rally
        "vol_regime": 0.3,  # Vol regime signal hurts in bull (mostly low-vol, ignore)
        "bb": 1.0,
        "macd": 1.2,  # MACD confirms momentum in bull
        "vwm": 1.1,
    },
    BEAR: {
        "momentum": 0.3,  # Momentum fades in bear; dangerous to chase
        "rsi": 1.5,  # RSI oversold bounces are the primary trade
        "vol_regime": 0.8,  # Elevated vol is a warning signal, moderate weight
        "bb": 1.3,  # BB oversold signals work well in bear bounces
        "macd": 0.8,
        "vwm": 0.9,
    },
    SIDEWAYS: {
        "momentum": 0.2,  # Momentum is actively harmful in range-bound markets
        "rsi": 1.4,  # RSI extremes reliably mean-revert
        "vol_regime": 1.5,  # Vol regime is the strongest predictor (IC -0.389)
        "bb": 1.2,  # BB extremes mean-revert in sideways
        "macd": 0.7,  # MACD whipsaws in sideways
        "vwm": 0.8,
    },
}

# ---------------------------------------------------------------------------
# Per-regime conviction thresholds
# ---------------------------------------------------------------------------

# agreement_ratio: fraction of signals that agree on direction (bullish or bearish)
# min_weighted_conviction: |composite_prob - 0.5| * 2, only used in SIDEWAYS
REGIME_CONVICTION_THRESHOLDS: dict[str, dict[str, float]] = {
    BULL: {"agreement_ratio": 0.5, "min_weighted_conviction": 0.0},
    BEAR: {"agreement_ratio": 0.7, "min_weighted_conviction": 0.0},
    SIDEWAYS: {"agreement_ratio": 0.6, "min_weighted_conviction": 0.4},
}

# BULL momentum floor: after multiplier scaling, momentum weight must be >= this
# fraction of the total weight allocated to any single signal.  Prevents the
# meta-model from assigning negative (fade) weight to momentum in up-trends.
BULL_MOMENTUM_MIN_WEIGHT = 0.3


# ---------------------------------------------------------------------------
# RegimeAwareSignalModifier
# ---------------------------------------------------------------------------


class RegimeAwareSignalModifier:
    """
    Applies regime-specific multipliers to raw signal weights and enforces
    conviction filters before allowing a trade signal to pass.

    Usage::

        modifier = RegimeAwareSignalModifier()

        # Adjust base weights for regime
        adjusted = modifier.apply_regime_weights(
            base_weights={"momentum": 0.25, "rsi": 0.25, "vol_regime": 0.25, "bb": 0.25},
            regime="bull",
            closes=price_array,
        )

        # Check whether conviction is sufficient to trade
        allowed = modifier.check_conviction_threshold(
            agreement_ratio=0.6,
            weighted_conviction=0.5,
            regime="bull",
        )
    """

    def __init__(
        self,
        multiplier_overrides: dict[str, dict[str, float]] | None = None,
        threshold_overrides: dict[str, dict[str, float]] | None = None,
    ) -> None:
        self._multipliers = {k: dict(v) for k, v in REGIME_SIGNAL_MULTIPLIERS.items()}
        if multiplier_overrides:
            for regime, overrides in multiplier_overrides.items():
                if regime not in self._multipliers:
                    self._multipliers[regime] = {}
                self._multipliers[regime].update(overrides)

        self._thresholds = {k: dict(v) for k, v in REGIME_CONVICTION_THRESHOLDS.items()}
        if threshold_overrides:
            for regime, overrides in threshold_overrides.items():
                if regime not in self._thresholds:
                    self._thresholds[regime] = {}
                self._thresholds[regime].update(overrides)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_regime_weights(
        self,
        base_weights: dict[str, float],
        regime: str,
        closes: list[float] | None = None,
    ) -> dict[str, float]:
        """
        Scale base signal weights by regime-specific multipliers.

        Parameters
        ----------
        base_weights:
            {signal_name: weight} — e.g. Brier-score or IC-derived weights.
            Need not sum to 1; the result is normalised.
        regime:
            One of "bull", "bear", "sideways".  Unknown regimes return
            base_weights unchanged.
        closes:
            Optional price series used for the BULL trend-strength check.
            If provided and regime is "bull", the trend strength gate decides
            whether to trust momentum or fall back to the floor.

        Returns
        -------
        Normalised weight dict with regime multipliers applied and, for BULL,
        the momentum floor enforced.
        """
        regime = regime.lower()
        if regime not in self._multipliers:
            return dict(base_weights)

        table = self._multipliers[regime]
        scaled: dict[str, float] = {}
        for name, w in base_weights.items():
            mult = table.get(name, 1.0)
            scaled[name] = max(0.0, w * mult)

        # BULL regime: enforce momentum floor and apply trend-strength gate
        if regime == BULL:
            scaled = self._apply_bull_momentum_floor(scaled, closes)

        return self._normalise(scaled)

    def check_conviction_threshold(
        self,
        agreement_ratio: float,
        weighted_conviction: float,
        regime: str,
    ) -> bool:
        """
        Return True if the signal meets the regime's conviction requirements.

        Parameters
        ----------
        agreement_ratio:
            Fraction of active signals pointing in the same direction [0, 1].
        weighted_conviction:
            |composite_probability - 0.5| * 2, representing signal strength [0, 1].
        regime:
            "bull", "bear", or "sideways".
        """
        regime = regime.lower()
        thresholds = self._thresholds.get(regime, {})
        min_agreement = thresholds.get("agreement_ratio", 0.5)
        min_conviction = thresholds.get("min_weighted_conviction", 0.0)

        if agreement_ratio < min_agreement:
            return False
        return not (min_conviction > 0.0 and weighted_conviction < min_conviction)

    def trend_strength(self, closes: list[float]) -> dict[str, Any]:
        """
        Compute trend-strength metrics from a closing price series.

        Returns
        -------
        {
            "momentum_20d": float,      # 20-day return
            "momentum_60d": float,      # 60-day return
            "above_sma50":  bool,       # price > 50-day SMA
            "trend_strong": bool,       # 20d & 60d positive AND price > SMA50
            "momentum_agreement": bool, # 20d and 60d agree in direction
        }
        """
        result: dict[str, Any] = {
            "momentum_20d": 0.0,
            "momentum_60d": 0.0,
            "above_sma50": False,
            "trend_strong": False,
            "momentum_agreement": False,
        }
        if len(closes) < 61:
            return result

        price = closes[-1]
        result["momentum_20d"] = (price - closes[-21]) / closes[-21] if closes[-21] != 0 else 0.0
        result["momentum_60d"] = (price - closes[-61]) / closes[-61] if closes[-61] != 0 else 0.0

        sma50 = sum(closes[-50:]) / 50
        result["above_sma50"] = price > sma50

        m20 = result["momentum_20d"]
        m60 = result["momentum_60d"]
        result["momentum_agreement"] = (m20 > 0) == (m60 > 0)
        result["trend_strong"] = (m20 > 0) and (m60 > 0) and result["above_sma50"]

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_bull_momentum_floor(
        self,
        weights: dict[str, float],
        closes: list[float] | None,
    ) -> dict[str, float]:
        """
        Enforce minimum momentum weight in BULL regime.

        If trend strength metrics are available and trend is NOT strong
        (20d and 60d momentum disagree), we still apply the floor but
        at half strength to reflect reduced confidence.
        """
        weights = dict(weights)

        # Determine effective floor based on trend strength
        floor = BULL_MOMENTUM_MIN_WEIGHT
        if closes is not None:
            ts = self.trend_strength(closes)
            if not ts["momentum_agreement"]:
                # Disagreement: use a softer floor (still positive, but smaller)
                floor = BULL_MOMENTUM_MIN_WEIGHT * 0.5
            # If trend_strong is True, use the full floor as-is

        total = sum(weights.values())
        if total == 0:
            return weights

        # Current normalised momentum weight
        mom_raw = weights.get("momentum", 0.0)
        mom_norm = mom_raw / total if total > 0 else 0.0

        if mom_norm < floor:
            # Lift momentum to floor, deduct proportionally from others
            deficit = (floor - mom_norm) * total
            others = {k: v for k, v in weights.items() if k != "momentum"}
            others_total = sum(others.values())

            if others_total > deficit:
                # Scale others down proportionally
                scale = (others_total - deficit) / others_total
                for k in others:
                    weights[k] = max(0.0, others[k] * scale)
            else:
                # Zero out others to meet floor
                for k in others:
                    weights[k] = 0.0

            weights["momentum"] = floor * total

        return weights

    @staticmethod
    def _normalise(weights: dict[str, float]) -> dict[str, float]:
        total = sum(weights.values())
        if total <= 0:
            n = len(weights)
            return {k: 1.0 / n for k in weights} if n > 0 else {}
        return {k: v / total for k, v in weights.items()}


# ---------------------------------------------------------------------------
# Module-level default instance
# ---------------------------------------------------------------------------

default_modifier = RegimeAwareSignalModifier()


# ---------------------------------------------------------------------------
# BottomSignalDetector — Glassnode-proxy macro bottom signals
# ---------------------------------------------------------------------------


@dataclass
class MacroBias:
    """Result of bottom-signal analysis.

    score:                 float in [-1, +1].  Positive = macro bullish (bottom
                           signals active); negative = macro bearish.
    bottom_signals_active: True when at least 2 of 3 individual bottom signals
                           are firing.  Used to bias the regime away from bear.
    mvrv_proxy:           price / MA(365d).  < 1.0 ≈ MVRV Z-Score low (cheap).
    asopr_proxy:          7d return.  < 0 ≈ aSOPR < 1 (sellers underwater).
    exchange_reserve_proxy: stablecoin-dominance proxy.  < 0 = stablecoins
                           shrinking as % of total (capital rotating into crypto).
    """

    score: float = 0.0
    bottom_signals_active: bool = False
    mvrv_proxy: float = 1.0
    asopr_proxy: float = 0.0
    exchange_reserve_proxy: float = 0.0


class BottomSignalDetector:
    """
    Approximates Glassnode on-chain bottom signals using free OHLCV data.

    Signals approximated
    --------------------
    1. **MVRV Z-Score proxy** — price / MA(365d).
       Real MVRV = market_cap / realised_cap (i.e. coins valued at purchase
       price).  Realised cap ≈ long-term average price × supply, so
       price / MA(365d) is a valid proxy.
       * proxy < 1.0  → price below long-term average → MVRV Z-Score likely
                         in bottom range (< 1.5)           → +1 bottom signal
       * proxy < 0.85 → deep discount (strong signal)      → +1 extra weight

    2. **aSOPR proxy** — 7d return vs 30d baseline.
       aSOPR < 1.0 means coins are being moved at a loss.  If the 7-day
       price change is negative (−%) the cohort of recent buyers is selling
       at a loss, approximating aSOPR < 1.0.
       * 7d_return < 0 AND 30d_return < 0  → aSOPR < 1 signal  → +1 bottom

    3. **Exchange reserve proxy** — stablecoin dominance delta.
       When stablecoins decline as a fraction of crypto market cap, capital
       is rotating *back into* BTC/ETH — exchange reserves are effectively
       declining.  Without real stablecoin data we use the ratio of BTC's
       14-day return vs 30-day return.
       * 14d_return > 30d_return (recent acceleration) → +1 bottom signal

    Composite score
    ---------------
    score = tanh(sum_of_weighted_signals / normaliser)

    Usage::

        detector = BottomSignalDetector()
        closes = [95000.0, 96000.0, ...]  # BTC hourly closes, most recent last
        bias = detector.compute(closes)
        # bias.score ∈ [-1, +1];  bias.bottom_signals_active = True if bottoming
    """

    # Minimum history length before we emit a non-neutral result
    MIN_CANDLES = 30

    def compute(self, closes: list[float]) -> MacroBias:
        """Compute macro bias from a closing price series (ascending order)."""
        if not closes or len(closes) < self.MIN_CANDLES:
            return MacroBias()

        arr = np.array(closes, dtype=float)
        arr = arr[arr > 0]  # strip zeros
        n = len(arr)
        if n < self.MIN_CANDLES:
            return MacroBias()

        price = float(arr[-1])
        signals_fired: list[float] = []

        # ── Signal 1: MVRV Z-Score proxy ────────────────────────────────────
        mvrv_proxy = 1.0
        window_365 = min(365, n)
        ma365 = float(np.mean(arr[-window_365:]))
        if ma365 > 0:
            mvrv_proxy = price / ma365
        s1 = 0.0
        if mvrv_proxy < 1.0:
            # Price is below long-term average — strong bottom territory
            s1 = min(1.0, (1.0 - mvrv_proxy) * 3.0)  # scale: 0.33 below → 1.0
        elif mvrv_proxy < 1.2:
            # Slightly above realized value — mild bullish bias
            s1 = 0.2
        signals_fired.append(s1)

        # ── Signal 2: aSOPR proxy ────────────────────────────────────────────
        asopr_proxy = 0.0
        s2 = 0.0
        if n >= 30:
            p7_ago = float(arr[-min(7, n)])
            p30_ago = float(arr[-min(30, n)])
            ret7 = (price - p7_ago) / p7_ago if p7_ago > 0 else 0.0
            ret30 = (price - p30_ago) / p30_ago if p30_ago > 0 else 0.0
            asopr_proxy = ret7
            if ret7 < 0 and ret30 < 0:
                # Both 7d and 30d negative → sellers underwater → aSOPR < 1
                s2 = min(1.0, abs(ret7) * 5.0)
            elif ret7 < 0:
                s2 = min(0.5, abs(ret7) * 3.0)
        signals_fired.append(s2)

        # ── Signal 3: Exchange reserve proxy (momentum acceleration) ────────
        exch_reserve_proxy = 0.0
        s3 = 0.0
        if n >= 30:
            p14_ago = float(arr[-min(14, n)])
            ret14 = (price - p14_ago) / p14_ago if p14_ago > 0 else 0.0
            p30_ago = float(arr[-min(30, n)])
            ret30 = (price - p30_ago) / p30_ago if p30_ago > 0 else 0.0
            exch_reserve_proxy = ret14 - ret30
            if ret14 > ret30:
                # 14d outpacing 30d → short-term recovery signal
                s3 = min(1.0, (ret14 - ret30) * 4.0)
        signals_fired.append(s3)

        # ── Composite score ──────────────────────────────────────────────────
        # Weights: MVRV (0.45) is most reliable proxy, aSOPR (0.35), exch (0.20)
        weights = [0.45, 0.35, 0.20]
        raw = sum(w * s for w, s in zip(weights, signals_fired, strict=False))
        score = float(np.tanh(raw * 2.0))  # amplify and squash to [-1, 1]

        # bottom_signals_active: two of three individual signals > 0.15
        n_active = sum(1 for s in signals_fired if s > 0.15)
        bottom_active = n_active >= 2

        return MacroBias(
            score=round(score, 4),
            bottom_signals_active=bottom_active,
            mvrv_proxy=round(mvrv_proxy, 4),
            asopr_proxy=round(asopr_proxy, 4),
            exchange_reserve_proxy=round(exch_reserve_proxy, 4),
        )


# ---------------------------------------------------------------------------
# HMMRegimeDetector — 3-state HMM regime detector
# ---------------------------------------------------------------------------


class HMMRegimeDetector:
    """
    3-state HMM regime detector.

    Trains on rolling window of (return, volatility, volume_ratio) features.
    Retrains every 20 observations. Falls back to rule-based detection when
    hmmlearn is unavailable or insufficient data.
    """

    MIN_TRAIN_SAMPLES = 30
    FEATURE_WINDOW = 120
    RETRAIN_EVERY = 20

    def __init__(self) -> None:
        self._model: Any = None
        self._hmm_state_to_regime: dict[int, str] = {}
        self._is_trained = False
        self._returns: deque[float] = deque(maxlen=self.FEATURE_WINDOW)
        self._vols: deque[float] = deque(maxlen=self.FEATURE_WINDOW)
        self._vol_ratios: deque[float] = deque(maxlen=self.FEATURE_WINDOW)
        self._regime_probs: list[float] = [1 / 3, 1 / 3, 1 / 3]
        self._current_regime: str = SIDEWAYS
        self._obs_count = 0

    @property
    def current_regime(self) -> str:
        return self._current_regime

    @property
    def regime_probs(self) -> list[float]:
        return self._regime_probs

    def update(
        self,
        market_data: dict[str, Any],
        macro_bias: MacroBias | None = None,
    ) -> dict[str, Any]:
        """Update the regime estimate from market data.

        Parameters
        ----------
        market_data:
            Dict keyed by ticker symbol (e.g. "BTCUSDT") containing
            "close" and "volume" lists (ascending order).
        macro_bias:
            Optional result from :class:`BottomSignalDetector`.  When
            provided and ``bottom_signals_active`` is True, the bear
            probability is reduced to prevent false bear calls during
            macro-bottom conditions (e.g. MVRV Z-Score < 1.2, aSOPR < 1).
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
        if _HMM_AVAILABLE and (not self._is_trained or self._obs_count % self.RETRAIN_EVERY == 0):
            self._train_hmm()
        if self._is_trained and _HMM_AVAILABLE:
            result = self._predict_hmm()
        else:
            result = self._rule_based(ret, vol)

        # Apply macro bias post-processing when bottom signals are active.
        if macro_bias is not None and macro_bias.bottom_signals_active:
            result = self._apply_macro_bias(result, macro_bias)

        self._current_regime = result["regime"]
        self._regime_probs = result["probs"]
        return result

    def _apply_macro_bias(
        self,
        result: dict[str, Any],
        bias: MacroBias,
    ) -> dict[str, Any]:
        """
        Reduce bear probability when macro bottom signals are active.

        Logic
        -----
        * The bias score ∈ [0, 1] (only called when bottom_signals_active).
        * We attenuate the bear component by ``bear_reduction`` and
          redistribute the freed probability to sideways (not bull) so that
          we don't over-commit in the absence of positive price momentum.
        * The regime label is re-derived from the adjusted probabilities.
        """
        probs = list(result.get("probs", [1 / 3, 1 / 3, 1 / 3]))
        if len(probs) < 3:
            return result

        bear_reduction = min(0.5, bias.score * 0.5)  # max 50% bear attenuation
        bull_p, bear_p, side_p = probs[0], probs[1], probs[2]

        freed = bear_p * bear_reduction
        bear_p_new = bear_p - freed
        side_p_new = side_p + freed  # redistribute to sideways (cautious, not aggressive)

        new_probs = [bull_p, bear_p_new, side_p_new]
        total = sum(new_probs)
        if total > 0:
            new_probs = [p / total for p in new_probs]

        # Re-derive regime label
        regime_map = {0: BULL, 1: BEAR, 2: SIDEWAYS}
        best_idx = int(np.argmax(new_probs))
        new_regime = regime_map[best_idx]

        updated = dict(result)
        updated["probs"] = new_probs
        updated["regime"] = new_regime
        updated["confidence"] = float(new_probs[best_idx])
        updated["macro_bias_score"] = bias.score
        updated["macro_bottom_active"] = True

        if new_regime != result.get("regime"):
            logger.debug(
                "MacroBias regime correction: %s → %s (score=%.3f, mvrv=%.3f)",
                result.get("regime"),
                new_regime,
                bias.score,
                bias.mvrv_proxy,
            )

        return updated

    def _extract_features(self, market_data: dict[str, Any]) -> tuple[float, float, float] | None:
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
            if isinstance(close, list) and len(close) >= 2:
                c1, c0 = float(close[-1]), float(close[-2])
                ret = (c1 - c0) / c0 if c0 != 0 else 0.0
            else:
                ret = 0.0
            if isinstance(close, list) and len(close) >= 10:
                prices = np.array(close[-20:], dtype=float)
                prices = prices[prices > 0]
                if len(prices) >= 2:
                    rets = np.diff(np.log(prices))
                    vol = float(np.std(rets)) * np.sqrt(252 * 24)
                    vol = max(0.01, min(vol, 10.0))
                else:
                    vol = float(self._vols[-1]) if self._vols else 0.5
            else:
                vol = float(self._vols[-1]) if self._vols else 0.5
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
        n = len(self._returns)
        if n < self.MIN_TRAIN_SAMPLES:
            return
        try:
            feat_mat = np.column_stack(
                [list(self._returns), list(self._vols), list(self._vol_ratios)]
            )
            model = _hmm_lib.GaussianHMM(
                n_components=3, covariance_type="diag", n_iter=100, random_state=42, min_covar=1e-4
            )
            model.fit(feat_mat)
            means = model.means_
            ret_order = np.argsort(means[:, 0])
            self._hmm_state_to_regime = {
                int(ret_order[0]): BEAR,
                int(ret_order[1]): SIDEWAYS,
                int(ret_order[2]): BULL,
            }
            self._model = model
            self._is_trained = True
        except Exception as exc:
            logger.debug("HMM training failed: %s", exc)

    def _predict_hmm(self) -> dict[str, Any]:
        try:
            feat_mat = np.column_stack(
                [list(self._returns), list(self._vols), list(self._vol_ratios)]
            )
            proba = self._model.predict_proba(feat_mat)
            current_probs = proba[-1]
            regime_probs: dict[str, float] = {BULL: 0.0, BEAR: 0.0, SIDEWAYS: 0.0}
            for state_idx, p in enumerate(current_probs):
                regime_name = self._hmm_state_to_regime.get(state_idx, SIDEWAYS)
                regime_probs[regime_name] = float(p)
            best = max(regime_probs, key=lambda k: regime_probs[k])
            probs_list = [regime_probs[BULL], regime_probs[BEAR], regime_probs[SIDEWAYS]]
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
        if len(self._returns) >= 10:
            recent_rets = list(self._returns)[-10:]
            avg_ret = float(np.mean(recent_rets))
        else:
            avg_ret = ret
        if avg_ret > 0.001 and vol < 1.0:
            regime = BULL
            probs = [0.7, 0.1, 0.2]
        elif avg_ret < -0.001 or vol > 1.5:
            regime = BEAR
            probs = [0.1, 0.7, 0.2]
        else:
            regime = SIDEWAYS
            probs = [0.2, 0.2, 0.6]
        return {
            "regime": regime,
            "probs": probs,
            "signal_multipliers": REGIME_SIGNAL_MULTIPLIERS.get(regime, {}),
            "confidence": probs[0] if regime == BULL else probs[1] if regime == BEAR else probs[2],
            "source": "rule_based",
        }

    def _fallback_result(self) -> dict[str, Any]:
        return {
            "regime": self._current_regime,
            "probs": self._regime_probs,
            "signal_multipliers": REGIME_SIGNAL_MULTIPLIERS.get(self._current_regime, {}),
            "confidence": 0.33,
            "source": "fallback",
        }
