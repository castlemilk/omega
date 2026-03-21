"""CCXT-based data source for exchange-agnostic market data."""

from __future__ import annotations

import logging
import time
from typing import Any

from omega.data.base import (
    OHLCV,
    DataSource,
    MarketData,
    OrderBookLevel,
    OrderBookSnapshot,
)

logger = logging.getLogger(__name__)

SUPPORTED_EXCHANGES = ("binance", "bybit", "okx")

# Minimum seconds between requests per exchange to respect rate limits
_RATE_LIMIT_SECS: dict[str, float] = {
    "binance": 0.05,  # 1200 req/min public
    "bybit": 0.1,  # 600 req/min public
    "okx": 0.1,  # 600 req/min public
}


class CCXTDataSource(DataSource):
    """Exchange-agnostic data source via the CCXT library.

    Uses only public endpoints — no API keys required for market data.
    """

    def __init__(
        self,
        exchange_id: str = "binance",
        timeout_ms: int = 10_000,
    ) -> None:
        if exchange_id not in SUPPORTED_EXCHANGES:
            raise ValueError(
                f"Unsupported exchange '{exchange_id}'. Choose from: {SUPPORTED_EXCHANGES}"
            )
        super().__init__(name=f"ccxt:{exchange_id}")
        self._exchange_id = exchange_id
        self._timeout_ms = timeout_ms
        self._exchange: Any = None
        self._last_request: float = 0.0
        self._rate_limit = _RATE_LIMIT_SECS.get(exchange_id, 0.1)
        self._subscriptions: set[str] = set()

    # ------------------------------------------------------------------
    # DataSource interface
    # ------------------------------------------------------------------

    def connect(self) -> None:
        try:
            import ccxt
        except ImportError as exc:
            raise RuntimeError("ccxt not installed. Run: pip install ccxt") from exc

        exchange_cls = getattr(ccxt, self._exchange_id)
        self._exchange = exchange_cls(
            {
                "timeout": self._timeout_ms,
                "enableRateLimit": True,
            }
        )
        self._connected = True
        logger.info("Connected to %s via CCXT", self._exchange_id)

    def disconnect(self) -> None:
        self._exchange = None
        self._connected = False
        logger.info("Disconnected from %s", self._exchange_id)

    def subscribe(self, symbol: str) -> None:
        self._subscriptions.add(symbol)

    def get_snapshot(self, symbol: str) -> MarketData | None:
        return self.get_ticker(symbol)

    # ------------------------------------------------------------------
    # Extended API
    # ------------------------------------------------------------------

    def get_ticker(self, symbol: str) -> MarketData | None:
        """Fetch latest ticker data for a symbol."""
        self._wait_rate_limit()
        try:
            ticker = self._exchange.fetch_ticker(symbol)
            self._mark_fetch()
            return MarketData(
                timestamp=ticker.get("timestamp", time.time() * 1000) / 1000.0,
                symbol=symbol,
                bid=float(ticker.get("bid") or ticker.get("last") or 0),
                ask=float(ticker.get("ask") or ticker.get("last") or 0),
                last_price=float(ticker.get("last") or 0),
                volume_24h=float(ticker.get("baseVolume") or 0),
            )
        except Exception as exc:
            self._mark_error()
            logger.warning("Failed to fetch ticker for %s: %s", symbol, exc)
            return None

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> list[OHLCV]:
        """Fetch OHLCV candles."""
        self._wait_rate_limit()
        try:
            raw = self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            self._mark_fetch()
            return [
                OHLCV(
                    timestamp=row[0] / 1000.0,
                    symbol=symbol,
                    timeframe=timeframe,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
                for row in raw
            ]
        except Exception as exc:
            self._mark_error()
            logger.warning("Failed to fetch OHLCV for %s: %s", symbol, exc)
            return []

    def get_orderbook(
        self,
        symbol: str,
        depth: int = 20,
    ) -> OrderBookSnapshot | None:
        """Fetch order book snapshot."""
        self._wait_rate_limit()
        try:
            raw = self._exchange.fetch_order_book(symbol, limit=depth)
            self._mark_fetch()
            return OrderBookSnapshot(
                symbol=symbol,
                timestamp=raw.get("timestamp", time.time() * 1000) / 1000.0
                if raw.get("timestamp")
                else time.time(),
                bids=[
                    OrderBookLevel(price=float(p), size=float(s)) for p, s in raw.get("bids", [])
                ],
                asks=[
                    OrderBookLevel(price=float(p), size=float(s)) for p, s in raw.get("asks", [])
                ],
            )
        except Exception as exc:
            self._mark_error()
            logger.warning("Failed to fetch orderbook for %s: %s", symbol, exc)
            return None

    def get_funding_rate(self, symbol: str) -> float:
        """Fetch current perpetual funding rate. Returns 0.0 if unavailable."""
        self._wait_rate_limit()
        try:
            data = self._exchange.fetch_funding_rate(symbol)
            self._mark_fetch()
            return float(data.get("fundingRate") or 0.0)
        except Exception as exc:
            self._mark_error()
            logger.debug("Funding rate unavailable for %s: %s", symbol, exc)
            return 0.0

    def get_open_interest(self, symbol: str) -> float:
        """Fetch open interest for a perpetual contract. Returns 0.0 if unavailable."""
        self._wait_rate_limit()
        try:
            data = self._exchange.fetch_open_interest(symbol)
            self._mark_fetch()
            return float(data.get("openInterestAmount") or data.get("openInterest") or 0.0)
        except Exception as exc:
            self._mark_error()
            logger.debug("Open interest unavailable for %s: %s", symbol, exc)
            return 0.0

    def get_full_snapshot(self, symbol: str) -> MarketData | None:
        """Ticker + funding rate + open interest in one call."""
        md = self.get_ticker(symbol)
        if md is None:
            return None
        md.funding_rate = self.get_funding_rate(symbol)
        md.open_interest = self.get_open_interest(symbol)
        return md

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _wait_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._rate_limit:
            time.sleep(self._rate_limit - elapsed)
        self._last_request = time.monotonic()
