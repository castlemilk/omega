"""Base abstractions for the Omega data ingestion layer."""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class MarketData:
    """Snapshot of market data for a symbol."""

    timestamp: float
    symbol: str
    bid: float
    ask: float
    last_price: float
    volume_24h: float
    funding_rate: float = 0.0
    open_interest: float = 0.0
    market_cap: float = 0.0

    @property
    def mid_price(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_bps(self) -> float:
        mid = self.mid_price
        if mid == 0:
            return 0.0
        return (self.spread / mid) * 10_000


@dataclass
class OrderBookLevel:
    price: float
    size: float


@dataclass
class OrderBookSnapshot:
    """Snapshot of order book state."""

    symbol: str
    timestamp: float
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]

    @property
    def mid_price(self) -> float:
        if not self.bids or not self.asks:
            return 0.0
        return (self.bids[0].price + self.asks[0].price) / 2.0

    @property
    def spread(self) -> float:
        if not self.bids or not self.asks:
            return 0.0
        return self.asks[0].price - self.bids[0].price

    @property
    def imbalance(self) -> float:
        """Order book imbalance: >0 means more bids (buying pressure)."""
        bid_vol = sum(lvl.size for lvl in self.bids)
        ask_vol = sum(lvl.size for lvl in self.asks)
        total = bid_vol + ask_vol
        if total == 0:
            return 0.0
        return (bid_vol - ask_vol) / total

    @property
    def bid_depth(self) -> float:
        return sum(lvl.price * lvl.size for lvl in self.bids)

    @property
    def ask_depth(self) -> float:
        return sum(lvl.price * lvl.size for lvl in self.asks)


@dataclass
class OHLCV:
    """OHLCV candle."""

    timestamp: float
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    @property
    def range(self) -> float:
        return self.high - self.low


class DataBuffer(Generic[T]):
    """Thread-safe ring buffer for streaming data."""

    def __init__(self, maxlen: int = 1000) -> None:
        self._buf: deque[T] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)

    def push(self, item: T) -> None:
        with self._not_empty:
            self._buf.append(item)
            self._not_empty.notify_all()

    def pop(self, timeout: float | None = None) -> T | None:
        with self._not_empty:
            if not self._buf:
                self._not_empty.wait(timeout=timeout)
            if self._buf:
                return self._buf.popleft()
            return None

    def peek(self, n: int = 1) -> list[T]:
        with self._lock:
            items = list(self._buf)
            return items[-n:]

    def snapshot(self) -> list[T]:
        with self._lock:
            return list(self._buf)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    def iter_drain(self) -> Iterator[T]:
        """Drain all current items without blocking."""
        with self._lock:
            items = list(self._buf)
            self._buf.clear()
        yield from items


class DataSource(ABC):
    """Abstract base for market data sources."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._connected = False
        self._last_fetch: float = 0.0
        self._error_count: int = 0

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def last_fetch_age(self) -> float:
        """Seconds since last successful fetch."""
        if self._last_fetch == 0:
            return float("inf")
        return time.monotonic() - self._last_fetch

    def _mark_fetch(self) -> None:
        self._last_fetch = time.monotonic()
        self._error_count = 0

    def _mark_error(self) -> None:
        self._error_count += 1

    @abstractmethod
    def connect(self) -> None:
        """Establish connection / session."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Clean up resources."""
        ...

    @abstractmethod
    def subscribe(self, symbol: str) -> None:
        """Subscribe to updates for a symbol."""
        ...

    @abstractmethod
    def get_snapshot(self, symbol: str) -> MarketData | None:
        """Get latest market data snapshot for a symbol."""
        ...

    def __enter__(self) -> DataSource:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.disconnect()
