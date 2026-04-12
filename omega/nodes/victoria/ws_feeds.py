"""
omega.nodes.victoria.ws_feeds
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Real-time WebSocket feed manager for Victoria's microstructure signals.

Connects to Binance public combined streams (aggTrade + depth20) in a
background daemon thread and maintains per-symbol ring buffers.  Six
microstructure signals are computed on demand and exposed via
``WSFeedManager.get_microstructure()``.

Graceful degradation: if ``websockets`` is unavailable, or while the WS
connection is not yet established, all signals return 0.0.

Binance public endpoint (no auth required):
  wss://stream.binance.com:9443/stream?streams=<sym>@aggTrade/<sym>@depth20@100ms

Usage::

    from omega.nodes.victoria.ws_feeds import WSFeedManager

    manager = WSFeedManager(["ETHUSDT", "BTCUSDT"])
    manager.start()                         # non-blocking
    # ... later ...
    signals = manager.get_microstructure("ETHUSDT")
    manager.stop()
"""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.ws_feeds")

# ---------------------------------------------------------------------------
# Optional import — degrade gracefully if websockets not installed
# ---------------------------------------------------------------------------
try:
    import websockets  # type: ignore[import]

    _WEBSOCKETS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _WEBSOCKETS_AVAILABLE = False
    logger.warning("ws_feeds: 'websockets' package not available — all microstructure signals will return 0.0")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"
_RECONNECT_DELAY = 5.0          # seconds between reconnect attempts
_RING_CAPACITY = 1_000          # ticks per symbol
_BOOK_DEPTH = 20                # top-N book levels
_TICK_MOMENTUM_WINDOW = 50      # last N ticks for momentum
_TRADE_FLOW_WINDOW_SEC = 60.0   # seconds for trade flow / volume profile
_SPREAD_HISTORY = 100           # ticks to keep for spread z-score
_VOL_PROFILE_WINDOWS = 10       # number of 60-s windows for avg volume


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Tick:
    """Single aggTrade record."""
    price: float
    size: float
    side: str   # "buy" | "sell"
    ts: float   # unix timestamp (seconds)


@dataclass
class BookLevel:
    """One price level in the L2 order book."""
    price: float
    size: float


class RingBuffer:
    """Fixed-size circular buffer of :class:`Tick` objects."""

    def __init__(self, capacity: int = _RING_CAPACITY) -> None:
        self._buf: deque[Tick] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def push(self, tick: Tick) -> None:
        with self._lock:
            self._buf.append(tick)

    def snapshot(self) -> list[Tick]:
        """Return a copy of the current contents (oldest → newest)."""
        with self._lock:
            return list(self._buf)


class OrderBook:
    """L2 order book snapshot (top-20 each side)."""

    def __init__(self) -> None:
        self.bids: list[BookLevel] = []  # best bid first (descending price)
        self.asks: list[BookLevel] = []  # best ask first (ascending price)
        self._lock = threading.Lock()

    def update(self, bids: list[list[str]], asks: list[list[str]]) -> None:
        """Accept raw Binance depth lists and store as :class:`BookLevel`."""
        new_bids = [BookLevel(float(p), float(s)) for p, s in bids]
        new_asks = [BookLevel(float(p), float(s)) for p, s in asks]
        # Binance sends them sorted already, but enforce just in case
        new_bids.sort(key=lambda lvl: lvl.price, reverse=True)
        new_asks.sort(key=lambda lvl: lvl.price)
        with self._lock:
            self.bids = new_bids
            self.asks = new_asks

    def snapshot(self) -> tuple[list[BookLevel], list[BookLevel]]:
        with self._lock:
            return list(self.bids), list(self.asks)


# ---------------------------------------------------------------------------
# Per-symbol state
# ---------------------------------------------------------------------------

@dataclass
class _SymbolState:
    ticks: RingBuffer = field(default_factory=RingBuffer)
    book: OrderBook = field(default_factory=OrderBook)
    # Rolling spread history for z-score
    spread_history: deque[float] = field(default_factory=lambda: deque(maxlen=_SPREAD_HISTORY))
    spread_lock: threading.Lock = field(default_factory=threading.Lock)
    # Has received at least one trade
    has_data: bool = False


# ---------------------------------------------------------------------------
# No-op manager (used when websockets unavailable)
# ---------------------------------------------------------------------------

_ZERO_SIGNALS: dict[str, float] = {
    "order_book_imbalance": 0.0,
    "trade_flow_direction": 0.0,
    "spread_zscore": 0.0,
    "volume_profile": 0.0,
    "tick_momentum": 0.0,
    "liquidation_proximity": 0.0,
}


class _NoOpWSFeedManager:
    """Returned when ``websockets`` is not importable."""

    def start(self) -> None:  # noqa: D401
        pass

    def stop(self) -> None:
        pass

    def is_ready(self) -> bool:
        return False

    def get_microstructure(self, symbol: str) -> dict[str, float]:
        return dict(_ZERO_SIGNALS)


# ---------------------------------------------------------------------------
# Main feed manager
# ---------------------------------------------------------------------------

class WSFeedManager:
    """
    Background-thread WebSocket feed manager.

    Parameters
    ----------
    symbols:
        List of Binance-format ticker symbols, e.g. ``["ETHUSDT", "BTCUSDT"]``.
    """

    def __init__(self, symbols: list[str]) -> None:
        self._symbols = [s.upper() for s in symbols]
        self._state: dict[str, _SymbolState] = {s: _SymbolState() for s in self._symbols}
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event = threading.Event()
        self._started = False
        self._warned_no_data: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background WS thread. Safe to call multiple times."""
        if self._started:
            return
        if not _WEBSOCKETS_AVAILABLE:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._thread_main,
            name="ws-feed-manager",
            daemon=True,
        )
        self._thread.start()
        self._started = True
        logger.debug("ws_feeds: background thread started for %s", self._symbols)

    def stop(self) -> None:
        """Signal the background thread to stop and wait for it."""
        if not self._started:
            return
        self._stop_event.set()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=10.0)
        self._started = False
        logger.debug("ws_feeds: background thread stopped")

    def is_ready(self) -> bool:
        """Return True when at least one symbol has received trade data."""
        return any(s.has_data for s in self._state.values())

    def get_microstructure(self, symbol: str) -> dict[str, float]:
        """
        Return the 6 microstructure signals for *symbol*.

        All values are in [-1, +1] except ``liquidation_proximity`` which is
        in [0, +1].  Returns all-zeros dict if no data is available.
        """
        sym = symbol.upper()
        state = self._state.get(sym)
        if state is None or not state.has_data:
            if sym not in self._warned_no_data:
                logger.warning("ws_feeds: no data for %s — returning zero signals", sym)
                self._warned_no_data.add(sym)
            return dict(_ZERO_SIGNALS)

        bids, asks = state.book.snapshot()
        ticks = state.ticks.snapshot()

        obi = self._order_book_imbalance(bids, asks)
        tfd = self._trade_flow_direction(ticks)
        ssz = self._spread_zscore(bids, asks, state)
        vp  = self._volume_profile(ticks)
        tm  = self._tick_momentum(ticks)
        lp  = self._liquidation_proximity(obi, tfd)

        return {
            "order_book_imbalance": obi,
            "trade_flow_direction": tfd,
            "spread_zscore": ssz,
            "volume_profile": vp,
            "tick_momentum": tm,
            "liquidation_proximity": lp,
        }

    # ------------------------------------------------------------------
    # Signal computations
    # ------------------------------------------------------------------

    @staticmethod
    def _order_book_imbalance(bids: list[BookLevel], asks: list[BookLevel]) -> float:
        """
        (bid_vol5 - ask_vol5) / (bid_vol5 + ask_vol5) over top-5 levels.
        Returns 0.0 if no book data.
        """
        if not bids or not asks:
            return 0.0
        bid_vol = sum(lvl.size for lvl in bids[:5])
        ask_vol = sum(lvl.size for lvl in asks[:5])
        total = bid_vol + ask_vol
        if total == 0.0:
            return 0.0
        return (bid_vol - ask_vol) / total

    @staticmethod
    def _trade_flow_direction(ticks: list[Tick]) -> float:
        """
        Net buy size / total size over the last 60 seconds.
        (buy - sell) / (buy + sell).  Returns 0.0 if no trades.
        """
        cutoff = time.time() - _TRADE_FLOW_WINDOW_SEC
        recent = [t for t in ticks if t.ts >= cutoff]
        if not recent:
            return 0.0
        buy_vol  = sum(t.size for t in recent if t.side == "buy")
        sell_vol = sum(t.size for t in recent if t.side == "sell")
        total = buy_vol + sell_vol
        if total == 0.0:
            return 0.0
        return (buy_vol - sell_vol) / total

    @staticmethod
    def _spread_zscore(
        bids: list[BookLevel],
        asks: list[BookLevel],
        state: _SymbolState,
    ) -> float:
        """
        (spread - mean_spread) / std_spread over last 100 ticks.
        Clamped to [-3, 3].  Returns 0.0 if fewer than 2 samples.
        """
        if not bids or not asks:
            return 0.0

        spread = asks[0].price - bids[0].price

        with state.spread_lock:
            state.spread_history.append(spread)
            history = list(state.spread_history)

        if len(history) < 2:
            return 0.0

        mean = statistics.mean(history)
        try:
            std = statistics.stdev(history)
        except statistics.StatisticsError:
            return 0.0

        if std == 0.0:
            return 0.0

        z = (spread - mean) / std
        return max(-3.0, min(3.0, z))

    @staticmethod
    def _volume_profile(ticks: list[Tick]) -> float:
        """
        current_60s_vol / avg_60s_vol - 1.0, clamped to [-1, 1].
        avg uses last 10 × 60-second windows.
        Returns 0.0 if not enough history.
        """
        if not ticks:
            return 0.0

        now = time.time()
        window_sec = _TRADE_FLOW_WINDOW_SEC   # 60s

        # Current window volume
        cutoff_current = now - window_sec
        current_vol = sum(t.size for t in ticks if t.ts >= cutoff_current)

        # Historical windows (windows 1..10 back in time)
        window_vols: list[float] = []
        for w in range(1, _VOL_PROFILE_WINDOWS + 1):
            w_start = now - (w + 1) * window_sec
            w_end   = now - w * window_sec
            vol = sum(t.size for t in ticks if w_start <= t.ts < w_end)
            window_vols.append(vol)

        # Filter out empty windows to avoid diluting the average
        nonempty = [v for v in window_vols if v > 0.0]
        if not nonempty:
            return 0.0

        avg_vol = statistics.mean(nonempty)
        if avg_vol == 0.0:
            return 0.0

        ratio = current_vol / avg_vol - 1.0
        return max(-1.0, min(1.0, ratio))

    @staticmethod
    def _tick_momentum(ticks: list[Tick]) -> float:
        """
        Linearly weighted average of last 50 tick directions.
        buy=+1, sell=-1.  Result in [-1, 1].
        """
        if not ticks:
            return 0.0

        recent = ticks[-_TICK_MOMENTUM_WINDOW:]
        n = len(recent)
        if n == 0:
            return 0.0

        # Weight: index 0 is oldest (weight=1), index n-1 is newest (weight=n)
        total_weight = 0.0
        weighted_sum = 0.0
        for i, tick in enumerate(recent):
            weight = float(i + 1)
            direction = 1.0 if tick.side == "buy" else -1.0
            weighted_sum += weight * direction
            total_weight += weight

        if total_weight == 0.0:
            return 0.0

        result = weighted_sum / total_weight
        return max(-1.0, min(1.0, result))

    @staticmethod
    def _liquidation_proximity(obi: float, tfd: float) -> float:
        """
        Proxy for over-leveraged directional crowding.
        When |OBI| + |TFD| > 1.0 (both signals strong same direction),
        proximity = (|OBI| + |TFD| - 1.0).  Clamped to [0, 1].
        """
        combined = abs(obi) + abs(tfd)
        return max(0.0, min(1.0, combined - 1.0))

    # ------------------------------------------------------------------
    # Threading / asyncio internals
    # ------------------------------------------------------------------

    def _thread_main(self) -> None:
        """Entry point for the background daemon thread."""
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            loop.run_until_complete(self._async_main())
        except Exception:
            logger.debug("ws_feeds: event loop exited with exception", exc_info=True)
        finally:
            loop.close()

    async def _async_main(self) -> None:
        """Reconnect loop — re-connects on any error or clean close."""
        while not self._stop_event.is_set():
            try:
                await self._connect_and_consume()
            except Exception as exc:
                logger.debug("ws_feeds: connection error (%s), reconnecting in %ss", exc, _RECONNECT_DELAY)
            if not self._stop_event.is_set():
                await asyncio.sleep(_RECONNECT_DELAY)

    async def _connect_and_consume(self) -> None:
        """Open combined stream and consume messages until closed."""
        stream_parts: list[str] = []
        for sym in self._symbols:
            low = sym.lower()
            stream_parts.append(f"{low}@aggTrade")
            stream_parts.append(f"{low}@depth20@100ms")

        url = f"{_BINANCE_WS_BASE}?streams={'/'.join(stream_parts)}"
        logger.debug("ws_feeds: connecting to %s", url)

        async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
            logger.debug("ws_feeds: connected")
            async for raw in ws:
                if self._stop_event.is_set():
                    break
                self._handle_message(raw)

    def _handle_message(self, raw: str) -> None:
        """Parse a combined-stream message and update state."""
        try:
            import json as _json
            msg: dict[str, Any] = _json.loads(raw)
        except Exception:
            return

        stream: str = msg.get("stream", "")
        data: dict[str, Any] = msg.get("data", {})
        if not stream or not data:
            return

        # Extract symbol from stream name  e.g. "ethusdt@aggTrade"
        sym_lower = stream.split("@")[0]
        sym = sym_lower.upper()
        state = self._state.get(sym)
        if state is None:
            return

        event_type: str = data.get("e", "")

        if event_type == "aggTrade":
            self._process_agg_trade(state, data)
        elif event_type == "depthUpdate":
            # depth20@100ms uses depthUpdate event
            bids = data.get("b", [])
            asks = data.get("a", [])
            state.book.update(bids, asks)
        else:
            # depth20 snapshot (no "e" key in initial snapshot)
            bids = data.get("bids") or data.get("b")
            asks = data.get("asks") or data.get("a")
            if bids is not None and asks is not None:
                state.book.update(bids, asks)

    @staticmethod
    def _process_agg_trade(state: _SymbolState, data: dict[str, Any]) -> None:
        """Push a new Tick onto the ring buffer and mark state as ready."""
        try:
            price = float(data["p"])
            size  = float(data["q"])
            # m=True → buyer is market maker → seller is aggressor → "sell"
            # m=False → seller is market maker → buyer is aggressor → "buy"
            side  = "sell" if data.get("m", False) else "buy"
            ts    = data.get("T", time.time() * 1000) / 1000.0  # ms → s
        except (KeyError, ValueError, TypeError):
            return

        tick = Tick(price=price, size=size, side=side, ts=ts)
        state.ticks.push(tick)
        state.has_data = True


# ---------------------------------------------------------------------------
# Module-level factory — returns NoOp if websockets unavailable
# ---------------------------------------------------------------------------

def create_feed_manager(symbols: list[str]) -> "WSFeedManager | _NoOpWSFeedManager":
    """
    Return a :class:`WSFeedManager` if ``websockets`` is available, otherwise
    a :class:`_NoOpWSFeedManager` that always returns zero signals.
    """
    if not _WEBSOCKETS_AVAILABLE:
        return _NoOpWSFeedManager()
    return WSFeedManager(symbols)


# ---------------------------------------------------------------------------
# Default basket (matches Victoria's active tickers + BTC market indicator)
# ---------------------------------------------------------------------------

VICTORIA_SYMBOLS = ["ETHUSDT", "NEARUSDT", "ARBUSDT", "ADAUSDT", "BTCUSDT"]
