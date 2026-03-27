"""CoinGecko data source (supports demo API key via CG_API_KEY env var)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from omega.core.credentials import credentials
from omega.data.base import DataSource, MarketData

logger = logging.getLogger(__name__)

_COINGECKO_BASE = "https://api.coingecko.com/api/v3"
_FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"

# Free tier: ~10-30 calls/min  → conservative 3s between calls
_RATE_LIMIT_SECS = 3.0

# Map common trading symbols → CoinGecko coin IDs
SYMBOL_TO_ID: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "XRP": "ripple",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "LTC": "litecoin",
    "DOGE": "dogecoin",
    "SHIB": "shiba-inu",
}


class CoinGeckoSource(DataSource):
    """Free CoinGecko API — no authentication required.

    Rate limited to ~10-30 requests/minute on the free tier.
    Uses urllib to avoid extra dependencies.
    """

    def __init__(self, timeout_secs: int = 10) -> None:
        super().__init__(name="coingecko")
        self._timeout = timeout_secs
        self._last_request: float = 0.0
        self._session_headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "omega-victoria/1.0",
        }
        api_key = credentials.get("COINGECKO_API_KEY")
        if api_key:
            self._session_headers["x-cg-demo-api-key"] = api_key

    # ------------------------------------------------------------------
    # DataSource interface
    # ------------------------------------------------------------------

    def connect(self) -> None:
        self._connected = True
        logger.info("CoinGeckoSource ready (free tier, no auth)")

    def disconnect(self) -> None:
        self._connected = False

    def subscribe(self, symbol: str) -> None:
        pass  # REST polling; no persistent subscriptions

    def get_snapshot(self, symbol: str) -> MarketData | None:
        coin_id = self._resolve_id(symbol)
        results = self.get_market_data([coin_id])
        return results[0] if results else None

    # ------------------------------------------------------------------
    # Extended API
    # ------------------------------------------------------------------

    def get_market_data(self, coin_ids: list[str]) -> list[MarketData]:
        """Batch fetch market data for multiple coins.

        Args:
            coin_ids: CoinGecko coin IDs (e.g. ["bitcoin", "ethereum"]).
                      Use SYMBOL_TO_ID to map ticker symbols.
        """
        if not coin_ids:
            return []

        ids_param = ",".join(coin_ids)
        url = (
            f"{_COINGECKO_BASE}/coins/markets"
            f"?vs_currency=usd"
            f"&ids={ids_param}"
            f"&order=market_cap_desc"
            f"&per_page={min(len(coin_ids), 250)}"
            f"&page=1"
            f"&sparkline=false"
        )

        raw = self._fetch_json(url)
        if raw is None:
            return []

        results: list[MarketData] = []
        now = time.time()
        for item in raw:
            try:
                last = float(item.get("current_price") or 0)
                # CoinGecko doesn't expose bid/ask; approximate from price
                spread_est = last * 0.0005  # ~0.05% typical spread
                results.append(
                    MarketData(
                        timestamp=now,
                        symbol=item.get("symbol", "").upper(),
                        bid=last - spread_est / 2,
                        ask=last + spread_est / 2,
                        last_price=last,
                        volume_24h=float(item.get("total_volume") or 0),
                        market_cap=float(item.get("market_cap") or 0),
                    )
                )
            except (TypeError, ValueError) as exc:
                logger.warning("Failed to parse coin data: %s — %s", item.get("id"), exc)

        self._mark_fetch()
        return results

    def get_fear_greed_index(self) -> float:
        """Fetch the Crypto Fear & Greed Index from alternative.me (0-100).

        Returns:
            Float 0-100 where 0=extreme fear, 100=extreme greed.
            Returns 50.0 (neutral) on failure.
        """
        raw = self._fetch_json(_FEAR_GREED_URL)
        if raw is None:
            return 50.0
        try:
            value = float(raw["data"][0]["value"])
            self._mark_fetch()
            return value
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning("Failed to parse fear/greed index: %s", exc)
            return 50.0

    def get_trending_coins(self) -> list[str]:
        """Fetch currently trending coin IDs from CoinGecko."""
        url = f"{_COINGECKO_BASE}/search/trending"
        raw = self._fetch_json(url)
        if raw is None:
            return []
        try:
            self._mark_fetch()
            return [item["item"]["id"] for item in raw.get("coins", [])]
        except (KeyError, TypeError) as exc:
            logger.warning("Failed to parse trending coins: %s", exc)
            return []

    def get_global_market_data(self) -> Any:
        """Fetch global crypto market stats (total market cap, BTC dominance, etc.)."""
        url = f"{_COINGECKO_BASE}/global"
        raw = self._fetch_json(url)
        if raw is None:
            return {}
        self._mark_fetch()
        return raw.get("data", {})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_id(self, symbol: str) -> str:
        """Resolve a ticker symbol to a CoinGecko coin ID."""
        return SYMBOL_TO_ID.get(symbol.upper(), symbol.lower())

    def _fetch_json(self, url: str) -> Any:
        """HTTP GET with rate limiting and error handling."""
        self._wait_rate_limit()
        try:
            req = Request(url, headers=self._session_headers)
            with urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self._last_request = time.monotonic()
                return data
        except URLError as exc:
            self._mark_error()
            logger.warning("CoinGecko request failed [%s]: %s", url, exc)
            return None
        except json.JSONDecodeError as exc:
            self._mark_error()
            logger.warning("CoinGecko invalid JSON [%s]: %s", url, exc)
            return None

    def _wait_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < _RATE_LIMIT_SECS:
            time.sleep(_RATE_LIMIT_SECS - elapsed)
