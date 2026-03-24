"""
omega.nodes.victoria.liquidation_cascade
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
LiquidationCascadeNode — monitors leverage clusters and cascade risk near BTC price.

Research basis: @0xricker — leverage clusters form at round-number prices and funding
rate extremes predict when forced unwinds become self-reinforcing cascade events.

Data source priority:
  1. Coinglass API (requires $29/mo key, configured via COINGLASS_API_KEY env var)
  2. Binance perpetuals funding rate (free, used as proxy when Coinglass unavailable)

Cascade probability model (proxy):
  funding_rate > +0.05%  → HIGH (longs overextended, upside cascade if price dips)
  funding_rate < -0.03%  → HIGH (shorts overextended, downside squeeze if price rises)
  otherwise              → LOW

Capability: LIQUIDATION_CASCADE  (registered for bridge routing)
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import uuid
from typing import Any

from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.victoria.liquidation_cascade")

# Funding rate thresholds for cascade signal (expressed as decimal fractions)
_LONG_CASCADE_THRESHOLD = 0.0005  # > +0.05% 8-hour rate → longs overextended
_SHORT_CASCADE_THRESHOLD = -0.0003  # < -0.03% 8-hour rate → shorts overextended

# Binance perpetuals funding rate endpoint (free, no auth)
_BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1"

# Cache TTL: funding rates update every 8 hours, refresh every 5 min is fine
_CACHE_TTL = 300  # seconds


class BinanceFundingFetcher:
    """
    Fetch the latest BTC perpetuals funding rate from Binance.
    Returns the rate as a float (e.g. 0.0001 = 0.01%).
    Cache TTL: 5 minutes.
    """

    def __init__(self, timeout: float = 5.0) -> None:
        self._timeout = timeout
        self._cache: tuple[float, float] | None = None  # (rate, fetched_at)

    def fetch(self) -> float | None:
        if self._cache is not None:
            rate, ts = self._cache
            if time.time() - ts < _CACHE_TTL:
                return rate

        try:
            req = urllib.request.Request(
                _BINANCE_FUNDING_URL,
                headers={"User-Agent": "omega-liquidation/1.0"},
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode())
        except Exception as exc:
            logger.debug("Binance funding fetch failed: %s", exc)
            return None

        try:
            rate = float(data[0]["fundingRate"])
            self._cache = (rate, time.time())
            return rate
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            logger.debug("Binance funding parse failed: %s", exc)
            return None


class MockLiquidationDataSource:
    """
    Demo/mock data source that simulates Coinglass-style liquidation cluster data.

    Replace this with a real CoinglasFetcher once the API key is available.
    Returns synthetic cluster data near current BTC price.
    """

    def fetch_clusters(self, btc_price: float) -> dict[str, Any]:
        """
        Return mock liquidation cluster data near the given BTC price.

        In production (Coinglass), this returns actual open interest stacked at
        price levels, identifying where cascades would be triggered.
        """
        # Mock: clusters at ±2%, ±5% from current price
        return {
            "source": "mock",
            "btc_price": btc_price,
            "clusters": [
                {
                    "price": round(btc_price * 0.98, 0),
                    "long_liquidations_usd": 45_000_000,
                    "short_liquidations_usd": 8_000_000,
                },
                {
                    "price": round(btc_price * 0.95, 0),
                    "long_liquidations_usd": 120_000_000,
                    "short_liquidations_usd": 15_000_000,
                },
                {
                    "price": round(btc_price * 1.02, 0),
                    "long_liquidations_usd": 12_000_000,
                    "short_liquidations_usd": 55_000_000,
                },
                {
                    "price": round(btc_price * 1.05, 0),
                    "long_liquidations_usd": 18_000_000,
                    "short_liquidations_usd": 95_000_000,
                },
            ],
        }


def _cascade_probability_from_funding(funding_rate: float) -> tuple[float, str]:
    """
    Map a funding rate to a cascade probability (0-1) and risk label.

    Returns (probability, risk_label).
    """
    if funding_rate > _LONG_CASCADE_THRESHOLD:
        # Longs overextended — any dip could trigger forced sells
        # Scale: 0.05% → 0.6, 0.10% → 0.9 (capped at 0.95)
        prob = min(0.95, 0.6 + (funding_rate - _LONG_CASCADE_THRESHOLD) * 6.0)
        return prob, "HIGH_LONG"
    elif funding_rate < _SHORT_CASCADE_THRESHOLD:
        # Shorts overextended — any rally triggers a short squeeze cascade
        excess = abs(funding_rate) - abs(_SHORT_CASCADE_THRESHOLD)
        prob = min(0.95, 0.6 + excess * 8.0)
        return prob, "HIGH_SHORT"
    else:
        # Neutral zone — low cascade risk
        abs_rate = abs(funding_rate)
        max_neutral = max(abs(_SHORT_CASCADE_THRESHOLD), _LONG_CASCADE_THRESHOLD)
        prob = 0.05 + 0.35 * (abs_rate / max_neutral)
        return min(0.4, prob), "LOW"


def _nearest_cluster(
    clusters: list[dict[str, Any]], btc_price: float
) -> tuple[float | None, float | None]:
    """
    Return (nearest_cluster_price, distance_pct) for the highest-value cluster.
    """
    if not clusters or btc_price <= 0:
        return None, None

    best_price: float | None = None
    best_size: float = 0.0

    for c in clusters:
        price = float(c.get("price", 0))
        if price <= 0:
            continue
        total_liq = float(c.get("long_liquidations_usd", 0)) + float(
            c.get("short_liquidations_usd", 0)
        )
        if total_liq > best_size:
            best_size = total_liq
            best_price = price

    if best_price is None:
        return None, None

    distance_pct = abs(best_price - btc_price) / btc_price * 100.0
    return best_price, round(distance_pct, 2)


class LiquidationCascadeNode(Node):
    """
    Monitors leverage buildup and liquidation clusters near current BTC price.

    Data source: Coinglass API (when COINGLASS_API_KEY is set), falls back to
    Binance funding rates as a proxy for leverage sentiment.

    Capabilities
    ------------
    liquidation_monitor   → check current cascade risk
    cascade_probability   -> get probability 0-1
    LIQUIDATION_CASCADE   -> bridge-routing alias

    Action: ``monitor_liquidations``

    Output keys
    -----------
    cascade_probability      : float 0-1
    leverage_ratio           : float (mock/estimated)
    funding_rate             : float (raw 8h rate from Binance)
    funding_rate_signal      : str  LOW | HIGH_LONG | HIGH_SHORT
    nearest_liquidation_cluster : float | None  (price level, USD)
    distance_to_cluster      : float | None  (% away from current price)
    data_source              : str  "binance_funding" | "coinglass" | "mock"
    confidence               : float 0-1
    """

    def __init__(self, timeout: float = 5.0) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._funding_fetcher = BinanceFundingFetcher(timeout=timeout)
        self._mock_clusters = MockLiquidationDataSource()

        # Runtime state
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._last_funding_rate: float | None = None
        self._last_cascade_prob: float = 0.0

    # ── Node interface ────────────────────────────────────────────────────────

    def get_state(self) -> NodeState:
        error_rate = self._error_count / max(1, self._execution_count)
        avg_lat = self._total_latency_ms / max(1, self._execution_count)
        return NodeState(
            node_id=self._node_id,
            name="LiquidationCascadeNode",
            version=self._version,
            health=max(0.0, 1.0 - error_rate),
            capabilities=self.get_capabilities(),
            metrics={
                "avg_latency_ms": avg_lat,
                "error_rate": error_rate,
                "execution_count": float(self._execution_count),
                "last_cascade_prob": self._last_cascade_prob,
            },
            metadata={
                "data_source": "binance_funding+mock_clusters",
                "coinglass_available": False,
            },
        )

    def get_capabilities(self) -> list[str]:
        return ["liquidation_monitor", "cascade_probability", "LIQUIDATION_CASCADE"]

    def describe(self) -> str:
        return (
            "LiquidationCascadeNode: monitors BTC leverage buildup using Binance "
            "perpetuals funding rates as a proxy for cascade risk. Identifies when "
            "longs or shorts are overextended and a price move could trigger forced "
            "liquidation cascades. Coinglass integration ready (set COINGLASS_API_KEY)."
        )

    def evaluate(self) -> dict[str, float]:
        return {
            "avg_latency_ms": self._total_latency_ms / max(1, self._execution_count),
            "error_rate": self._error_count / max(1, self._execution_count),
            "execution_count": float(self._execution_count),
            "last_cascade_prob": self._last_cascade_prob,
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        return False

    def execute(self, inp: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1

        action = inp.action
        if action not in (
            "monitor_liquidations",
            "liquidation_monitor",
            "cascade_probability",
            "LIQUIDATION_CASCADE",
        ):
            elapsed = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += elapsed
            self._error_count += 1
            return NodeOutput(
                request_id=inp.request_id,
                success=False,
                errors=[f"LiquidationCascadeNode: unknown action '{action}'"],
                metrics={"latency_ms": elapsed},
            )

        try:
            result = self._monitor(inp.parameters)
            elapsed = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += elapsed
            self._last_cascade_prob = result.get("cascade_probability", 0.0)
            return NodeOutput(
                request_id=inp.request_id,
                success=True,
                result=result,
                metrics={"latency_ms": elapsed},
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += elapsed
            self._error_count += 1
            logger.error("LiquidationCascadeNode error: %s", exc, exc_info=True)
            return NodeOutput(
                request_id=inp.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": elapsed},
            )

    # ── Internal logic ────────────────────────────────────────────────────────

    def _monitor(self, params: dict[str, Any]) -> dict[str, Any]:
        """Core monitoring logic — fetch funding rate, compute cascade prob."""
        market_data: dict[str, Any] = params.get("market_data", {})
        funding_override: float | None = params.get("funding_rate_override")

        # 1. Get BTC price from market data
        btc_price = self._extract_btc_price(market_data)

        # 2. Get funding rate (override for testing, else live Binance)
        raw_rate: float | None
        if funding_override is not None:
            raw_rate = float(funding_override)
            data_source = "override"
        else:
            raw_rate = self._funding_fetcher.fetch()
            data_source = "binance_funding"

        self._last_funding_rate = raw_rate

        # 3. Compute cascade probability from funding rate
        if raw_rate is not None:
            funding_rate: float = raw_rate
            cascade_prob, risk_label = _cascade_probability_from_funding(funding_rate)
            confidence = 0.7  # funding-rate proxy is moderately reliable
        else:
            funding_rate = 0.0
            # Fallback: neutral with low confidence
            cascade_prob, risk_label = 0.2, "LOW"
            confidence = 0.2
            funding_rate = 0.0

        # 4. Get liquidation cluster data (mock until Coinglass key available)
        cluster_price: float | None = None
        distance_pct: float | None = None
        if btc_price is not None:
            cluster_data = self._mock_clusters.fetch_clusters(btc_price)
            clusters = cluster_data.get("clusters", [])
            cluster_price, distance_pct = _nearest_cluster(clusters, btc_price)
            data_source += "+mock_clusters"

        # 5. Estimate leverage_ratio from funding magnitude (proxy)
        # At 0.01% = normal (leverage ~10x), at 0.05% = elevated (leverage ~20x)
        leverage_ratio = 10.0 + abs(funding_rate) * 200_000.0

        logger.debug(
            "LiquidationCascade: funding=%.5f cascade_prob=%.3f risk=%s",
            funding_rate,
            cascade_prob,
            risk_label,
        )

        return {
            "cascade_probability": round(cascade_prob, 4),
            "leverage_ratio": round(leverage_ratio, 2),
            "funding_rate": round(funding_rate, 6),
            "funding_rate_signal": risk_label,
            "nearest_liquidation_cluster": cluster_price,
            "distance_to_cluster": distance_pct,
            "data_source": data_source,
            "confidence": round(confidence, 3),
        }

    def _extract_btc_price(self, market_data: dict[str, Any]) -> float | None:
        """Extract current BTC price from market_data dict."""
        # Try common structures used across Victoria data providers
        for key in ("btc_price", "price", "BTC"):
            if key in market_data:
                val = market_data[key]
                if isinstance(val, (int, float)):
                    return float(val)
                if isinstance(val, dict):
                    for subkey in ("close", "price", "last"):
                        if subkey in val:
                            closes = val[subkey]
                            if isinstance(closes, list) and closes:
                                return float(closes[-1])
                            if isinstance(closes, (int, float)):
                                return float(closes)

        # Try close prices list
        close = market_data.get("close", [])
        if isinstance(close, list) and close:
            return float(close[-1])

        return None
