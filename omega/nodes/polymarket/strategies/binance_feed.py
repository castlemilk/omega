"""
omega.nodes.polymarket.strategies.binance_feed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Async Binance trade-stream feed with price-move detection.

The feed maintains a rolling window of recent prices and fires a callback
whenever the observed price change exceeds the configured threshold.

Usage::

    async def on_move(direction, magnitude, price, ts):
        print(f"BTC moved {direction} {magnitude:.3%} @ {price:.2f}")

    feed = BinancePriceFeed(
        ws_url="wss://stream.binance.com:9443/ws/btcusdt@trade",
        threshold=0.0011,
    )
    feed.on_move_detected = on_move
    await feed.run()          # blocks; cancel to stop
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from collections.abc import Awaitable, Callable

logger = logging.getLogger("omega.nodes.polymarket.strategies.binance_feed")

# Type alias for the move-detected callback.
# Signature: (direction: str, magnitude: float, price: float, timestamp_s: float) -> Awaitable | None
MoveCallback = Callable[[str, float, float, float], Awaitable[None] | None]


class BinancePriceFeed:
    """
    Async Binance WebSocket feed for BTC/USDT real-time trades.

    Responsibilities
    ----------------
    * Maintain a live ``last_price`` updated on every trade message.
    * Keep a rolling deque of (price, timestamp) samples for magnitude calc.
    * Compare each new trade price against the *reference price* — the most
      recent price at the start of the rolling window — and fire
      ``on_move_detected`` when the threshold is crossed.
    * Reconnect automatically on disconnect using exponential back-off.

    Parameters
    ----------
    ws_url
        Binance trade stream WebSocket URL.
    threshold
        Fractional price-move threshold (e.g. 0.0011 = 0.11 %).
    window_size
        Number of recent prices kept in the rolling window (default 60).
    on_move_detected
        Async or sync callable:
        ``(direction, magnitude, price, timestamp_s) -> None``
        where ``direction`` is ``"up"`` or ``"down"``.
    max_reconnect_delay_s
        Cap for exponential back-off between reconnection attempts.
    """

    def __init__(
        self,
        ws_url: str = "wss://stream.binance.com:9443/ws/btcusdt@trade",
        threshold: float = 0.0011,
        window_size: int = 60,
        on_move_detected: MoveCallback | None = None,
        max_reconnect_delay_s: float = 60.0,
    ) -> None:
        self.ws_url = ws_url
        self.threshold = threshold
        self.window_size = window_size
        self.on_move_detected: MoveCallback | None = on_move_detected
        self.max_reconnect_delay_s = max_reconnect_delay_s

        self.last_price: float | None = None
        self._price_window: deque[tuple[float, float]] = deque(maxlen=window_size)
        self._reference_price: float | None = None
        self._running = False
        self._reconnect_attempts = 0

        # Metrics
        self.messages_received: int = 0
        self.moves_detected: int = 0
        self.reconnects: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """
        Start the feed loop. Runs until cancelled.

        Reconnects automatically with exponential back-off on any
        connection error or unexpected disconnect.
        """
        self._running = True
        while self._running:
            try:
                await self._connect_and_stream()
                self._reconnect_attempts = 0  # clean exit resets counter
            except asyncio.CancelledError:
                logger.info("BinancePriceFeed cancelled — shutting down.")
                self._running = False
                return
            except Exception as exc:
                delay = self._backoff_delay()
                logger.warning(
                    "BinancePriceFeed connection error (%s). Reconnecting in %.1fs (attempt %d).",
                    exc,
                    delay,
                    self._reconnect_attempts,
                )
                self.reconnects += 1
                await asyncio.sleep(delay)

    def stop(self) -> None:
        """Signal the run loop to stop after the current reconnect cycle."""
        self._running = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _connect_and_stream(self) -> None:
        """Open a single WebSocket session and process messages until it closes."""
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("websockets package required: pip install websockets") from exc

        logger.info("BinancePriceFeed connecting to %s", self.ws_url)
        async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10) as ws:
            logger.info("BinancePriceFeed connected.")
            self._reconnect_attempts = 0
            async for raw in ws:
                if not self._running:
                    return
                await self._handle_message(raw)

    async def _handle_message(self, raw: str) -> None:
        """Parse one Binance trade message and update state."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("BinancePriceFeed: unparseable message, skipping.")
            return

        # Binance @trade stream: {"e":"trade","p":"<price>","T":<trade_time_ms>,...}
        price_str = msg.get("p")
        trade_time_ms = msg.get("T")
        if price_str is None or trade_time_ms is None:
            return

        try:
            price = float(price_str)
            ts = trade_time_ms / 1000.0  # convert ms → seconds
        except (ValueError, TypeError):
            return

        self.messages_received += 1
        await self._update_price(price, ts)

    async def _update_price(self, price: float, timestamp_s: float) -> None:
        """Update internal state and fire callback if a move is detected."""
        self.last_price = price
        self._price_window.append((price, timestamp_s))

        # Need at least 2 data points to detect a move.
        if len(self._price_window) < 2:
            self._reference_price = price
            return

        # Reference price is the oldest sample still in the window.
        ref_price = self._price_window[0][0]
        if ref_price == 0:
            return

        move = (price - ref_price) / ref_price
        magnitude = abs(move)

        if magnitude >= self.threshold:
            direction = "up" if move > 0 else "down"
            self.moves_detected += 1
            # Reset reference to current so subsequent ticks don't re-fire
            # until the window slides past the spike.
            self._price_window.clear()
            self._price_window.append((price, timestamp_s))

            logger.info(
                "BinancePriceFeed: move detected %s %.4f%% @ %.2f (ts=%.3f)",
                direction,
                magnitude * 100,
                price,
                timestamp_s,
            )

            if self.on_move_detected is not None:
                result = self.on_move_detected(direction, magnitude, price, timestamp_s)
                if asyncio.iscoroutine(result):
                    await result

    def _backoff_delay(self) -> float:
        """Exponential back-off: 1, 2, 4, 8 … capped at max_reconnect_delay_s."""
        self._reconnect_attempts += 1
        delay = min(2 ** (self._reconnect_attempts - 1), self.max_reconnect_delay_s)
        return float(delay)

    # ------------------------------------------------------------------
    # Introspection helpers (useful for tests / health checks)
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    def get_metrics(self) -> dict[str, float]:
        return {
            "messages_received": float(self.messages_received),
            "moves_detected": float(self.moves_detected),
            "reconnects": float(self.reconnects),
            "last_price": self.last_price or 0.0,
        }
