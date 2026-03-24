"""
omega.nodes.polymarket.pricing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
PolymarketPricingNode — fetches live weather/temperature market prices from
the Polymarket Gamma API.

The Gamma API is a public REST API for market metadata. We filter for markets
whose question text contains weather/temperature keywords to surface the
relevant prediction markets.

API base: https://gamma-api.polymarket.com

Usage::

    node = PolymarketPricingNode()
    out = node.execute(NodeInput(action="fetch_weather_markets"))
    # out.result = [{"market_id": "...", "question": "...", "yes_price": 0.62, ...}, ...]
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.polymarket.pricing")

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
WEATHER_KEYWORDS = [
    "temperature",
    "weather",
    "degrees",
    "fahrenheit",
    "celsius",
    "heat",
    "cold",
    "warm",
    "hot",
    "freeze",
    "frost",
    "high temp",
    "low temp",
    "above",
    "below",
    "°f",
    "°c",
    "° f",
    "° c",
]
USER_AGENT = "omega-polymarket-pricing/1.0"
CACHE_TTL_SECONDS = 120  # 2 minutes for market prices


@dataclass
class _CacheEntry:
    result: Any
    expires_at: float


class PolymarketPricingNode(Node):
    """
    Fetches Polymarket prediction-market prices for weather/temperature markets.

    Actions
    -------
    fetch_weather_markets   — Return list of active weather markets with prices
    fetch_market            — Fetch a single market by market_id
    """

    def __init__(self) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._execution_count = 0
        self._error_count = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._total_latency_ms = 0.0
        self._cache: dict[str, _CacheEntry] = {}

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._node_id,
            name="PolymarketPricingNode",
            version=self._version,
            health=max(0.0, 1.0 - self._error_count / max(1, self._execution_count)),
            capabilities=self.get_capabilities(),
            metrics=self.evaluate(),
        )

    def get_capabilities(self) -> list[str]:
        return ["fetch_weather_markets", "fetch_market", "polymarket_pricing"]

    def describe(self) -> str:
        return (
            "Fetches live weather and temperature market prices from the Polymarket "
            "Gamma API. Filters markets by weather/temperature keywords and returns "
            "market_id, question, yes_price, no_price, and volume."
        )

    def execute(self, inp: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1
        action = inp.action.lower()

        result: Any = None
        try:
            if action in ("fetch_weather_markets", "polymarket_pricing", "marketpricing"):
                result = self._fetch_weather_markets(inp.parameters)
            elif action == "fetch_market":
                market_id = inp.parameters.get("market_id", "")
                result = self._fetch_single_market(str(market_id))
            else:
                raise ValueError(
                    f"Unknown action '{action}'. Supported: {self.get_capabilities()}"
                )
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._error_count += 1
            self._total_latency_ms += elapsed
            logger.warning("PolymarketPricingNode error: %s", exc)
            return NodeOutput(
                request_id=inp.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": elapsed},
            )

        elapsed = (time.perf_counter() - t0) * 1000
        self._total_latency_ms += elapsed
        return NodeOutput(
            request_id=inp.request_id,
            success=True,
            result=result,
            metrics={"latency_ms": elapsed},
        )

    def evaluate(self) -> dict[str, float]:
        total_cache = self._cache_hits + self._cache_misses
        return {
            "error_rate": self._error_count / max(1, self._execution_count),
            "avg_latency_ms": self._total_latency_ms / max(1, self._execution_count),
            "cache_hit_rate": self._cache_hits / max(1, total_cache),
            "execution_count": float(self._execution_count),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_cached(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if time.time() > entry.expires_at:
            del self._cache[key]
            return None
        return entry.result

    def _set_cache(self, key: str, result: Any) -> None:
        self._cache[key] = _CacheEntry(
            result=result,
            expires_at=time.time() + CACHE_TTL_SECONDS,
        )

    def _get_json(self, url: str) -> Any:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    def _is_weather_market(self, question: str) -> bool:
        q_lower = question.lower()
        return any(kw in q_lower for kw in WEATHER_KEYWORDS)

    def _parse_market(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        """Extract relevant fields from a Gamma API market record."""
        question = raw.get("question", raw.get("title", ""))
        if not self._is_weather_market(question):
            return None

        # Yes price: try outcomes tokens array or direct fields
        yes_price = 0.5
        no_price = 0.5
        volume = 0.0

        tokens = raw.get("tokens", [])
        if len(tokens) >= 2:
            for tok in tokens:
                outcome = str(tok.get("outcome", "")).lower()
                price = float(tok.get("price", 0.5))
                if outcome == "yes":
                    yes_price = price
                elif outcome == "no":
                    no_price = price
        elif "outcomePrices" in raw:
            prices = raw["outcomePrices"]
            if isinstance(prices, list) and len(prices) >= 2:
                try:
                    yes_price = float(prices[0])
                    no_price = float(prices[1])
                except (TypeError, ValueError):
                    pass

        volume_str = raw.get("volume", raw.get("volumeNum", 0))
        try:
            volume = float(volume_str)
        except (TypeError, ValueError):
            volume = 0.0

        return {
            "market_id": str(raw.get("conditionId", raw.get("id", ""))),
            "question": question,
            "yes_price": round(yes_price, 4),
            "no_price": round(no_price, 4),
            "volume": round(volume, 2),
            "end_date": raw.get("endDate", raw.get("endDateIso", "")),
            "active": raw.get("active", True),
            "fetched_at": datetime.now().isoformat(),
        }

    def _fetch_weather_markets(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        cache_key = "weather_markets"
        cached = self._get_cached(cache_key)
        if cached is not None:
            self._cache_hits += 1
            return cached  # type: ignore[no-any-return]

        self._cache_misses += 1
        # Fetch active markets sorted by volume (descending) to surface recent markets
        markets: list[dict[str, Any]] = []
        limit = int(params.get("limit", 200))
        url = (
            f"{GAMMA_API_BASE}/markets?active=true&limit={limit}&closed=false"
            f"&order=volume&ascending=false"
        )

        data = self._get_json(url)
        raw_list = data if isinstance(data, list) else data.get("markets", [])

        for raw in raw_list:
            parsed = self._parse_market(raw)
            if parsed:
                markets.append(parsed)

        self._set_cache(cache_key, markets)
        return markets

    def _fetch_single_market(self, market_id: str) -> dict[str, Any]:
        cache_key = f"market:{market_id}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            self._cache_hits += 1
            return cached  # type: ignore[no-any-return]

        self._cache_misses += 1
        url = f"{GAMMA_API_BASE}/markets/{market_id}"
        raw = self._get_json(url)
        parsed = self._parse_market(raw)
        if parsed is None:
            raise ValueError(f"Market {market_id} does not appear to be a weather market")

        self._set_cache(cache_key, parsed)
        return parsed
