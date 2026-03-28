"""
omega.nodes.victoria.whale_signal
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Whale exchange flow signal for Victoria.

Tracks large BTC/ETH exchange inflows (bearish — selling pressure)
and outflows (bullish — accumulation) to generate a directional signal.

Sources (tried in order):
  1. Whale Alert API     — large on-chain transactions  (env: WHALE_ALERT_API_KEY)
  2. CoinGlass API       — aggregated exchange netflow   (env: COINGLASS_API_KEY)
  3. Binance public API  — taker-buy volume imbalance proxy (no key required)

Signal semantics:
  net_flow_usd = outflows_usd − inflows_usd
  whale_activity_score ∈ [−1.0, +1.0]
    +1.0 → strong net outflow from exchanges (accumulation / bullish)
    −1.0 → strong net inflow to exchanges   (distribution / bearish)

Cache TTL: 10 minutes (whale data is slow-moving).
Fallback: 0.0 with confidence=0.0 if all sources fail.
"""

from __future__ import annotations

import logging
import math
import os
import time
import urllib.request
import json as _json
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.whale_signal")

_CACHE_TTL = 600  # 10 minutes
_EPSILON = 1e-9

# Whale Alert: minimum USD value to treat as a "whale" transaction
_WHALE_MIN_VALUE_USD = 1_000_000  # $1M+
# Lookback window for Whale Alert transaction history (seconds)
_WHALE_ALERT_LOOKBACK = 3600  # 1 hour

# CoinGlass flow normalization cap (in USD) — flows larger than this are clipped to ±1.0
# Typical daily BTC exchange flow is in the $500M–$2B range
_COINGLASS_FLOW_CAP_USD = 1_000_000_000  # $1B

# Binance taker-buy ratio thresholds
_TAKER_BUY_BULL_THRESHOLD = 0.56  # > 56% taker buys → accumulation pressure
_TAKER_BUY_BEAR_THRESHOLD = 0.44  # < 44% taker buys → distribution pressure

# BTC/ETH tickers tracked (Binance symbol format)
_TRACKED_SYMBOLS = ["BTCUSDT", "ETHUSDT"]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 8) -> Any:
    """Minimal HTTP GET returning parsed JSON, or raises on error."""
    req = urllib.request.Request(url, headers=headers or {})
    req.add_header("User-Agent", "omega-victoria/1.0")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return _json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# _SignalValue (lightweight, avoids circular import with signals_advanced)
# ---------------------------------------------------------------------------


class _SignalValue:
    __slots__ = ("confidence", "raw", "regime_tag", "value")

    def __init__(
        self,
        value: float,
        confidence: float,
        regime_tag: str,
        raw: dict[str, float],
    ) -> None:
        self.value = value
        self.confidence = confidence
        self.regime_tag = regime_tag
        self.raw = raw


def _unavailable(reason: str) -> _SignalValue:
    return _SignalValue(value=0.0, confidence=0.0, regime_tag="unavailable", raw={"reason": 0.0, reason: 0.0})


# ---------------------------------------------------------------------------
# Source 1: Whale Alert
# ---------------------------------------------------------------------------


def _fetch_whale_alert(api_key: str) -> _SignalValue:
    """
    Fetch recent large transactions from Whale Alert.

    Transactions where to.owner_type == "exchange" count as inflows (bearish).
    Transactions where from.owner_type == "exchange" count as outflows (bullish).
    Transactions between unknown wallets are ignored.

    Only BTC and ETH transactions are considered.
    """
    start_ts = int(time.time()) - _WHALE_ALERT_LOOKBACK
    url = (
        f"https://api.whale-alert.io/v1/transactions"
        f"?api_key={api_key}"
        f"&min_value={_WHALE_MIN_VALUE_USD}"
        f"&start={start_ts}"
        f"&limit=100"
    )
    data = _http_get(url, timeout=10)

    transactions = data.get("transactions", [])
    if not transactions:
        return _unavailable("no_whale_txns")

    inflows_usd = 0.0
    outflows_usd = 0.0
    btc_net = 0.0
    eth_net = 0.0

    for tx in transactions:
        symbol = tx.get("symbol", "").upper()
        if symbol not in ("BTC", "ETH"):
            continue

        amount_usd = float(tx.get("amount_usd", 0))
        from_type = tx.get("from", {}).get("owner_type", "unknown")
        to_type = tx.get("to", {}).get("owner_type", "unknown")

        # Inflow: wallet → exchange (selling pressure)
        if to_type == "exchange" and from_type != "exchange":
            inflows_usd += amount_usd
            if symbol == "BTC":
                btc_net -= amount_usd
            else:
                eth_net -= amount_usd

        # Outflow: exchange → wallet (accumulation)
        elif from_type == "exchange" and to_type != "exchange":
            outflows_usd += amount_usd
            if symbol == "BTC":
                btc_net += amount_usd
            else:
                eth_net += amount_usd

    total = inflows_usd + outflows_usd
    if total < _EPSILON:
        return _unavailable("no_exchange_flows")

    net_flow_usd = outflows_usd - inflows_usd
    # Normalize against 1-hour flow cap (scaled down from daily cap)
    hourly_cap = _COINGLASS_FLOW_CAP_USD / 24.0
    raw_score = net_flow_usd / (hourly_cap + _EPSILON)
    # Use tanh to smoothly compress to [-1, 1]
    score = math.tanh(raw_score * 2.0)

    if score > 0.3:
        regime_tag = "accumulation"
    elif score < -0.3:
        regime_tag = "distribution"
    else:
        regime_tag = "neutral_flow"

    confidence = min(0.9, 0.4 + min(1.0, total / (hourly_cap * 0.5)) * 0.5)

    return _SignalValue(
        value=_clamp(score),
        confidence=confidence,
        regime_tag=regime_tag,
        raw={
            "inflows_usd": inflows_usd,
            "outflows_usd": outflows_usd,
            "net_flow_usd": net_flow_usd,
            "btc_net_usd": btc_net,
            "eth_net_usd": eth_net,
            "tx_count": float(len(transactions)),
            "source": 1.0,  # whale_alert
        },
    )


# ---------------------------------------------------------------------------
# Source 2: CoinGlass exchange netflow
# ---------------------------------------------------------------------------


def _fetch_coinglass(api_key: str) -> _SignalValue:
    """
    Fetch exchange netflow from CoinGlass API.

    Uses the /public/v2/indicator/exchange_flow endpoint which returns
    aggregated inflow/outflow data across all major exchanges.
    """
    headers = {"coinglassSecret": api_key}
    inflows_usd = 0.0
    outflows_usd = 0.0
    raw: dict[str, float] = {"source": 2.0}  # coinglass

    for symbol in ("BTC", "ETH"):
        try:
            # type=0 → inflow, type=1 → outflow (last 24h aggregated)
            inflow_url = (
                f"https://open-api.coinglass.com/public/v2/indicator/exchange_flow_chart"
                f"?symbol={symbol}&type=0&interval=h4"
            )
            outflow_url = (
                f"https://open-api.coinglass.com/public/v2/indicator/exchange_flow_chart"
                f"?symbol={symbol}&type=1&interval=h4"
            )

            inflow_data = _http_get(inflow_url, headers=headers)
            outflow_data = _http_get(outflow_url, headers=headers)

            # Expect {"code": "0", "data": {"list": [{"time":..., "value":...}, ...]}}
            inflow_list = inflow_data.get("data", {}).get("list", [])
            outflow_list = outflow_data.get("data", {}).get("list", [])

            # Use the most recent data point (last item)
            if inflow_list:
                sym_inflow = float(inflow_list[-1].get("value", 0))
                inflows_usd += sym_inflow
                raw[f"{symbol.lower()}_inflow_usd"] = sym_inflow

            if outflow_list:
                sym_outflow = float(outflow_list[-1].get("value", 0))
                outflows_usd += sym_outflow
                raw[f"{symbol.lower()}_outflow_usd"] = sym_outflow

        except Exception as exc:
            logger.debug("CoinGlass %s flow fetch failed: %s", symbol, exc)

    total = inflows_usd + outflows_usd
    if total < _EPSILON:
        return _unavailable("coinglass_no_data")

    net_flow_usd = outflows_usd - inflows_usd
    raw["net_flow_usd"] = net_flow_usd
    raw["inflows_usd"] = inflows_usd
    raw["outflows_usd"] = outflows_usd

    raw_score = net_flow_usd / (_COINGLASS_FLOW_CAP_USD + _EPSILON)
    score = math.tanh(raw_score * 3.0)

    if score > 0.3:
        regime_tag = "accumulation"
    elif score < -0.3:
        regime_tag = "distribution"
    else:
        regime_tag = "neutral_flow"

    confidence = min(0.85, 0.4 + min(1.0, total / (_COINGLASS_FLOW_CAP_USD * 0.2)) * 0.45)

    return _SignalValue(
        value=_clamp(score),
        confidence=confidence,
        regime_tag=regime_tag,
        raw=raw,
    )


# ---------------------------------------------------------------------------
# Source 3: Binance public API — taker-buy volume proxy
# ---------------------------------------------------------------------------


def _fetch_binance_proxy() -> _SignalValue:
    """
    Proxy whale flow signal from Binance 24h taker-buy statistics.

    High taker-buy ratio indicates aggressive buying (price-taker demand) which
    correlates with accumulation. This is a weaker signal than actual exchange
    flows but requires no API key.

    Confidence is capped at 0.45 to reflect its proxy nature.
    """
    scores: list[float] = []
    raw: dict[str, float] = {"source": 3.0}  # binance_proxy

    for symbol in _TRACKED_SYMBOLS:
        try:
            url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
            data = _http_get(url)

            volume = float(data.get("volume", 0))
            taker_buy_vol = float(data.get("takerBuyBaseAssetVolume", 0))

            if volume < _EPSILON:
                continue

            ratio = taker_buy_vol / volume  # fraction of volume that was taker buys
            raw[f"{symbol.lower()}_taker_buy_ratio"] = ratio
            raw[f"{symbol.lower()}_volume"] = volume

            # Map ratio to [-1, 1]: 0.5 neutral, 0.56+ bullish, 0.44- bearish
            deviation = (ratio - 0.5) / 0.1  # ±1 per 10pp deviation
            scores.append(_clamp(deviation))

        except Exception as exc:
            logger.debug("Binance proxy fetch for %s failed: %s", symbol, exc)

    if not scores:
        return _unavailable("binance_proxy_failed")

    avg_score = sum(scores) / len(scores)

    if avg_score > 0.25:
        regime_tag = "buy_pressure"
    elif avg_score < -0.25:
        regime_tag = "sell_pressure"
    else:
        regime_tag = "balanced"

    raw["composite_score"] = avg_score

    return _SignalValue(
        value=_clamp(avg_score),
        confidence=0.35,  # low confidence — indirect proxy
        regime_tag=regime_tag,
        raw=raw,
    )


# ---------------------------------------------------------------------------
# WhaleFlowSignal — public interface
# ---------------------------------------------------------------------------


class WhaleFlowSignal:
    """
    Whale exchange flow signal.

    Tries Whale Alert → CoinGlass → Binance proxy in order.
    Results are cached for 10 minutes. Falls back to 0.0 / confidence=0.0
    if all sources are unavailable.

    Usage:
        signal = WhaleFlowSignal()
        sv = signal.compute()
        print(sv.value, sv.confidence, sv.regime_tag)
    """

    def __init__(self) -> None:
        self._cached: _SignalValue | None = None
        self._cache_ts: float = 0.0

    def compute(self, market_data: dict[str, Any] | None = None) -> _SignalValue:
        """
        Compute whale flow signal. market_data is accepted for API compatibility
        but not required (this signal fetches its own external data).
        """
        now = time.time()
        if self._cached is not None and (now - self._cache_ts) < _CACHE_TTL:
            return self._cached

        result = self._fetch()
        self._cached = result
        self._cache_ts = now
        return result

    def _fetch(self) -> _SignalValue:
        # Source 1: Whale Alert
        whale_key = os.environ.get("WHALE_ALERT_API_KEY", "").strip()
        if whale_key:
            try:
                sv = _fetch_whale_alert(whale_key)
                if sv.confidence > 0.0:
                    logger.debug(
                        "WhaleFlowSignal [whale-alert]: value=%.3f confidence=%.2f regime=%s",
                        sv.value, sv.confidence, sv.regime_tag,
                    )
                    return sv
            except Exception as exc:
                logger.debug("WhaleFlowSignal whale-alert failed: %s", exc)

        # Source 2: CoinGlass
        coinglass_key = os.environ.get("COINGLASS_API_KEY", "").strip()
        if coinglass_key:
            try:
                sv = _fetch_coinglass(coinglass_key)
                if sv.confidence > 0.0:
                    logger.debug(
                        "WhaleFlowSignal [coinglass]: value=%.3f confidence=%.2f regime=%s",
                        sv.value, sv.confidence, sv.regime_tag,
                    )
                    return sv
            except Exception as exc:
                logger.debug("WhaleFlowSignal coinglass failed: %s", exc)

        # Source 3: Binance taker-buy proxy (no key required)
        try:
            sv = _fetch_binance_proxy()
            if sv.confidence > 0.0:
                logger.debug(
                    "WhaleFlowSignal [binance-proxy]: value=%.3f confidence=%.2f regime=%s",
                    sv.value, sv.confidence, sv.regime_tag,
                )
                return sv
        except Exception as exc:
            logger.debug("WhaleFlowSignal binance-proxy failed: %s", exc)

        # All sources failed — graceful fallback
        logger.debug("WhaleFlowSignal: all sources failed, returning 0.0")
        return _SignalValue(
            value=0.0,
            confidence=0.0,
            regime_tag="unavailable",
            raw={"fallback": 1.0},
        )
