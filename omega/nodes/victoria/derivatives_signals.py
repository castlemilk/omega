"""
omega.nodes.victoria.derivatives_signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
DerivativesSignal — funding rate + open interest signals from
Binance Futures public API (no authentication required).

Endpoints used:
  /fapi/v1/fundingRate         — 8h funding rate history (last 10)
  /futures/data/openInterestHist — hourly OI history (last 10)

Interpretation:
  Funding rate (contrarian):
    Positive funding > threshold → longs paying shorts → crowded long → bearish fade
    Negative funding < -threshold → shorts paying longs → crowded short → bullish fade
    Extreme funding (>3x threshold) → high conviction contrarian

  Open interest + price direction (trend confirmation):
    Rising OI + rising price → confirmed uptrend → bullish
    Rising OI + falling price → confirmed downtrend → bearish
    Falling OI → position unwinding → reduced conviction

Cache TTL: 15 minutes (Binance updates every 8h for funding, 1h for OI).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any

from omega.nodes.victoria.signals_advanced import SignalValue

logger = logging.getLogger("omega.nodes.victoria.derivatives_signals")

_BINANCE_FUTURES_BASE = "https://fapi.binance.com"
_CACHE_TTL = 900  # 15 minutes

# Funding rate thresholds (per 8-hour period)
_FUNDING_EXTREME = 0.001  # 0.10% per 8h ≈ 109% APR — extreme crowding
_FUNDING_HIGH = 0.0003  # 0.03% per 8h ≈ 33% APR  — elevated crowding
_FUNDING_THRESHOLD = 0.0001  # 0.01% per 8h ≈ 11% APR  — baseline noise level


class DerivativesSignal:
    """
    Derivatives market signal from Binance Futures public API.

    Sub-signals:
      funding_rate : Contrarian signal based on 8h funding rate (avg of last 8 periods)
      open_interest: Trend confirmation from OI vs price direction alignment

    Composite: funding_rate (60%) + open_interest (40%).
    Both sub-signals self-fetch with 15-minute caching.
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def compute(self, market_data: dict[str, Any] | None = None) -> SignalValue:
        """Fetch derivatives data and return composite SignalValue."""
        raw: dict[str, float] = {}
        sub_signals: dict[str, float] = {}
        sub_confidences: dict[str, float] = {}

        # A. Funding rate signal
        fr_score, fr_conf, fr_raw = self._funding_rate_signal()
        raw.update(fr_raw)
        if fr_score is not None:
            sub_signals["funding"] = fr_score
            sub_confidences["funding"] = fr_conf

        # B. Open interest signal
        oi_score, oi_conf, oi_raw = self._open_interest_signal(market_data)
        raw.update(oi_raw)
        if oi_score is not None:
            sub_signals["open_interest"] = oi_score
            sub_confidences["open_interest"] = oi_conf

        if not sub_signals:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="no_data",
                raw=raw,
            )

        # Weighted composite: funding 60%, OI 40%
        _weights = {"funding": 0.6, "open_interest": 0.4}
        total_w = sum(_weights[k] for k in sub_signals)
        composite = sum(sub_signals[k] * _weights[k] for k in sub_signals) / total_w
        composite = max(-1.0, min(1.0, composite))

        # Confidence: weighted average of sub-signal confidences
        conf_total = sum(sub_confidences[k] * _weights[k] for k in sub_signals)
        confidence = min(1.0, conf_total / total_w)

        # Regime tagging
        funding_label = raw.get("funding_regime_label", 0.0)
        if composite < -0.5:
            regime_tag = "overextended_long"
        elif composite > 0.5:
            regime_tag = "overextended_short"
        elif abs(funding_label) >= 1.5:
            regime_tag = "extreme_funding"
        else:
            regime_tag = "derivatives_neutral"

        raw["composite"] = composite
        raw["sub_signal_count"] = float(len(sub_signals))

        logger.debug(
            "derivatives_signal: composite=%.3f confidence=%.3f regime=%s sub=%s",
            composite,
            confidence,
            regime_tag,
            list(sub_signals.keys()),
        )

        return SignalValue(
            value=composite,
            confidence=confidence,
            regime_tag=regime_tag,
            raw=raw,
        )

    # ------------------------------------------------------------------
    # Sub-signal computations
    # ------------------------------------------------------------------

    def _funding_rate_signal(self) -> tuple[float | None, float, dict[str, float]]:
        """
        Fetch 8h funding rate history from Binance and compute contrarian signal.

        Returns (score [-1,+1] or None, confidence [0,1], raw_metrics).
        """
        data = self._fetch(
            "/fapi/v1/fundingRate",
            {"symbol": "BTCUSDT", "limit": "10"},
        )
        raw: dict[str, float] = {}

        if not data or not isinstance(data, list) or not data:
            return None, 0.0, raw

        rates = []
        for item in data:
            try:
                rates.append(float(item.get("fundingRate", 0)))
            except (TypeError, ValueError):
                continue

        if not rates:
            return None, 0.0, raw

        latest_rate = rates[-1]
        n = min(len(rates), 8)
        avg_rate = sum(rates[-n:]) / n

        raw["funding_rate_latest"] = latest_rate
        raw["funding_rate_avg_8p"] = avg_rate
        raw["funding_rate_count"] = float(len(rates))

        # Contrarian scoring: extreme positioning → mean reversion
        if avg_rate > _FUNDING_EXTREME:
            score = -1.0
            confidence = 0.85
            raw["funding_regime_label"] = 2.0  # extreme crowded long
        elif avg_rate > _FUNDING_HIGH:
            score = -0.7
            confidence = 0.70
            raw["funding_regime_label"] = 1.5
        elif avg_rate > _FUNDING_THRESHOLD:
            score = -0.35
            confidence = 0.55
            raw["funding_regime_label"] = 1.0
        elif avg_rate < -_FUNDING_EXTREME:
            score = 1.0
            confidence = 0.85
            raw["funding_regime_label"] = -2.0  # extreme crowded short
        elif avg_rate < -_FUNDING_HIGH:
            score = 0.7
            confidence = 0.70
            raw["funding_regime_label"] = -1.5
        elif avg_rate < -_FUNDING_THRESHOLD:
            score = 0.35
            confidence = 0.55
            raw["funding_regime_label"] = -1.0
        else:
            # Near-zero funding: longs/shorts in equilibrium
            # Slight directional tilt based on latest vs avg
            score = 0.0
            confidence = 0.40
            raw["funding_regime_label"] = 0.0
            # Small directional bias from trend of funding
            if len(rates) >= 3:
                recent_trend = rates[-1] - rates[-3]
                if abs(recent_trend) > _FUNDING_THRESHOLD / 2:
                    score = -min(0.2, abs(recent_trend) / _FUNDING_THRESHOLD) * (
                        1 if recent_trend > 0 else -1
                    )

        return score, confidence, raw

    def _open_interest_signal(
        self,
        market_data: dict[str, Any] | None = None,
    ) -> tuple[float | None, float, dict[str, float]]:
        """
        Fetch hourly OI history and compute trend confirmation signal.

        Returns (score [-1,+1] or None, confidence [0,1], raw_metrics).
        """
        data = self._fetch(
            "/futures/data/openInterestHist",
            {"symbol": "BTCUSDT", "period": "1h", "limit": "10"},
        )
        raw: dict[str, float] = {}

        if not data or not isinstance(data, list) or len(data) < 2:
            return None, 0.0, raw

        oi_values: list[float] = []
        for item in data:
            try:
                oi_values.append(float(item.get("sumOpenInterest", 0)))
            except (TypeError, ValueError):
                continue

        if len(oi_values) < 2:
            return None, 0.0, raw

        latest_oi = oi_values[-1]
        prev_oi = oi_values[-2]
        oi_change_1h = (latest_oi - prev_oi) / max(abs(prev_oi), 1.0)

        # 5-hour trend for more stable signal
        oi_trend_5h = 0.0
        if len(oi_values) >= 5:
            oi_trend_5h = (oi_values[-1] - oi_values[-5]) / max(abs(oi_values[-5]), 1.0)

        raw["oi_latest"] = latest_oi
        raw["oi_change_1h_pct"] = oi_change_1h
        raw["oi_trend_5h_pct"] = oi_trend_5h

        # Get price context for OI/price alignment
        price_change = 0.0
        if market_data:
            btc = market_data.get("BTCUSDT") or {}
            prices: list[float] = btc.get("close") or market_data.get("close", [])
            if prices and len(prices) > 1 and prices[-2] != 0:
                price_change = (prices[-1] - prices[-2]) / prices[-2]
                raw["price_change_1p"] = price_change

        # Trend confirmation: OI + price direction alignment
        if oi_change_1h > 0.02 and price_change > 0.001:
            # OI rising + price rising = uptrend confirmed
            score = min(0.80, 0.5 + abs(oi_change_1h) * 5)
            confidence = 0.65
        elif oi_change_1h > 0.02 and price_change < -0.001:
            # OI rising + price falling = downtrend confirmed
            score = max(-0.80, -(0.5 + abs(oi_change_1h) * 5))
            confidence = 0.65
        elif oi_change_1h < -0.03:
            # Sharp OI decline: position unwinding — uncertain direction
            score = 0.0
            confidence = 0.25
        elif abs(oi_trend_5h) > 0.05 and price_change != 0.0:
            # Sustained 5h trend with price alignment
            direction = 1.0 if price_change > 0 else -1.0
            score = direction * min(0.5, abs(oi_trend_5h) * 3)
            confidence = 0.50
        else:
            score = 0.0
            confidence = 0.35

        return score, confidence, raw

    # ------------------------------------------------------------------
    # Fetch + cache helpers
    # ------------------------------------------------------------------

    def _fetch(self, endpoint: str, params: dict[str, str]) -> Any:
        """Fetch from Binance Futures API with 15-minute caching."""
        cache_key = endpoint + "?" + urllib.parse.urlencode(sorted(params.items()))
        now = time.time()

        if cache_key in self._cache:
            cached_ts, cached_data = self._cache[cache_key]
            if now - cached_ts < _CACHE_TTL:
                return cached_data

        url = _BINANCE_FUTURES_BASE + endpoint + "?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "omega-signal/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
                self._cache[cache_key] = (now, data)
                return data
        except Exception as exc:
            logger.debug("DerivativesSignal fetch failed %s: %s", endpoint, exc)
            # Return stale cache if available
            if cache_key in self._cache:
                _, stale = self._cache[cache_key]
                return stale
            return None
