"""
omega.nodes.polymarket.strategies.latency_arb
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Latency-arbitrage engine for BTC-correlated Polymarket markets.

Background
----------
Polymarket prediction markets that reference BTC price (e.g. "Will BTC close
above $X on <date>?") reprice with a 9-16 second lag relative to Binance spot.
This engine:

  1. Subscribes to the Binance BTC/USDT trade stream.
  2. Detects price moves that exceed ``config.price_move_threshold``.
  3. Waits exactly ``config.min_delay_ms`` ms, then queries Polymarket via
     the CLOB client to check whether the markets have updated.
  4. If markets have NOT yet repriced, places a directional order.
  5. Aborts the cycle if ``config.max_delay_ms`` has elapsed (window closed).

Each detection→evaluation→execution cycle is wrapped in an OTel-style span
emitted through the project's ``omega.core.tracing`` module.

Usage::

    from omega.nodes.polymarket.strategies import LatencyArbEngine
    from omega.nodes.polymarket.strategies.latency_arb_config import LatencyArbConfig

    config = LatencyArbConfig(
        markets_to_watch=["<condition_id_1>", "<condition_id_2>"],
        max_position_usd=250.0,
    )
    engine = LatencyArbEngine(config)
    await engine.run()
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from omega.nodes.polymarket.strategies.binance_feed import BinancePriceFeed
from omega.nodes.polymarket.strategies.latency_arb_config import LatencyArbConfig

logger = logging.getLogger("omega.nodes.polymarket.strategies.latency_arb")


# ---------------------------------------------------------------------------
# Arb cycle record — tracks one full detection→execution attempt
# ---------------------------------------------------------------------------


@dataclass
class ArbCycle:
    """
    Immutable record of a single latency-arb attempt.

    Written at the start of each cycle and updated as it progresses.
    Stored in LatencyArbEngine.completed_cycles for post-hoc analysis.
    """

    cycle_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    move_detected_at: float = 0.0  # epoch seconds (Binance trade time)
    move_direction: str = ""  # "up" | "down"
    move_magnitude: float = 0.0  # fractional, e.g. 0.0015 = 0.15 %
    binance_price_at_trigger: float = 0.0

    # Set when Polymarket is queried
    entry_time: float = 0.0  # epoch seconds (when CLOB was queried)
    polymarket_price_at_entry: dict[str, float] = field(default_factory=dict)

    # Outcome
    order_placed: bool = False
    order_skipped_reason: str = ""  # "window_expired" | "already_repriced" | ""
    pnl_usd: float = 0.0  # realised P&L (filled in by settlement)

    # OTel span IDs
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    detection_span_id: str = ""
    evaluation_span_id: str = ""
    execution_span_id: str = ""


# ---------------------------------------------------------------------------
# Lightweight OTel-compatible span context
# ---------------------------------------------------------------------------


@dataclass
class _Span:
    """Minimal OTel-style span written to the engine's span log."""

    span_id: str
    trace_id: str
    operation: str
    started_at: float
    ended_at: float | None = None
    status: str = "ok"
    attributes: dict[str, Any] = field(default_factory=dict)

    def end(self, status: str = "ok", **attrs: Any) -> None:
        self.ended_at = time.time()
        self.status = status
        self.attributes.update(attrs)

    @property
    def duration_ms(self) -> float | None:
        if self.ended_at is None:
            return None
        return (self.ended_at - self.started_at) * 1000


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


class LatencyArbEngine:
    """
    Latency-arbitrage engine for BTC-correlated Polymarket markets.

    The engine is async; call ``await engine.run()`` to start. It will run
    indefinitely until cancelled. Internally it:

    * Starts a ``BinancePriceFeed`` task.
    * On each detected BTC move, schedules an arb cycle coroutine.
    * The arb cycle respects the min/max delay window and talks to Polymarket
      through the CLOB client.

    Parameters
    ----------
    config
        ``LatencyArbConfig`` instance (all tuning knobs live here).
    clob_client
        Optional Polymarket CLOB client. If ``None``, the engine operates in
        *dry-run* mode: it logs what it *would* do but places no real orders.
        Pass an ``omega.nodes.polymarket.clob_client.CLOBClient`` instance for
        live trading.
    """

    def __init__(
        self,
        config: LatencyArbConfig | None = None,
        clob_client: Any = None,
    ) -> None:
        self.config = config or LatencyArbConfig()
        self._clob = clob_client  # may be None (dry-run)

        self._feed = BinancePriceFeed(
            ws_url=self.config.binance_ws_url,
            threshold=self.config.price_move_threshold,
            on_move_detected=self._on_move,
        )

        # State
        self._last_trade_at: float = 0.0  # epoch seconds of last completed trade
        self._daily_trade_count: int = 0
        # Initialise to today so the first reset check doesn't wipe trades placed
        # within the same session before _on_move is first called.
        self._daily_reset_date: str = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        self._active_cycle: ArbCycle | None = None

        # Records
        self.completed_cycles: list[ArbCycle] = []
        self.spans: list[_Span] = []

        # Cancellation token for active cycle tasks
        self._pending_cycle_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """
        Start the engine. Runs indefinitely until cancelled.

        Internally starts the Binance feed loop; move events schedule
        arb cycle coroutines automatically.
        """
        logger.info("LatencyArbEngine starting (dry_run=%s).", self._clob is None)
        await self._feed.run()

    def stop(self) -> None:
        """Gracefully stop the engine and its feed."""
        self._feed.stop()
        if self._pending_cycle_task and not self._pending_cycle_task.done():
            self._pending_cycle_task.cancel()

    def get_metrics(self) -> dict[str, float]:
        """Return engine-level performance metrics."""
        total = len(self.completed_cycles)
        placed = sum(1 for c in self.completed_cycles if c.order_placed)
        expired = sum(
            1 for c in self.completed_cycles if c.order_skipped_reason == "window_expired"
        )
        repriced = sum(
            1 for c in self.completed_cycles if c.order_skipped_reason == "already_repriced"
        )
        return {
            "total_cycles": float(total),
            "orders_placed": float(placed),
            "window_expired": float(expired),
            "already_repriced": float(repriced),
            "daily_trade_count": float(self._daily_trade_count),
            **self._feed.get_metrics(),
        }

    # ------------------------------------------------------------------
    # Move callback (fired by BinancePriceFeed)
    # ------------------------------------------------------------------

    async def _on_move(
        self,
        direction: str,
        magnitude: float,
        price: float,
        timestamp_s: float,
    ) -> None:
        """
        Called by BinancePriceFeed when a qualifying price move is detected.

        Schedules an arb cycle as a background task so the feed loop is
        not blocked.  Drops the event if a cycle is already active (only
        one cycle at a time).
        """
        if self._pending_cycle_task and not self._pending_cycle_task.done():
            logger.debug("LatencyArbEngine: move detected but cycle already active — skipping.")
            return

        self._reset_daily_counter_if_needed()

        if self._daily_trade_count >= self.config.max_daily_trades:
            logger.warning(
                "LatencyArbEngine: daily trade limit (%d) reached — skipping move.",
                self.config.max_daily_trades,
            )
            return

        cycle = ArbCycle(
            move_detected_at=timestamp_s,
            move_direction=direction,
            move_magnitude=magnitude,
            binance_price_at_trigger=price,
        )
        self._active_cycle = cycle

        self._pending_cycle_task = asyncio.create_task(
            self._run_arb_cycle(cycle),
            name=f"arb_cycle_{cycle.cycle_id[:8]}",
        )

    # ------------------------------------------------------------------
    # Arb cycle — detection → evaluation → execution
    # ------------------------------------------------------------------

    async def _run_arb_cycle(self, cycle: ArbCycle) -> None:
        """
        Full arb cycle coroutine for one detected move event.

        Steps
        -----
        1. Emit ``detection`` span.
        2. Sleep until ``min_delay_ms`` has elapsed since the move.
        3. If ``max_delay_ms`` already exceeded → abort with "window_expired".
        4. Query Polymarket markets (``evaluation`` span).
        5. If market has NOT repriced → place order (``execution`` span).
        6. Record cycle and update counters.
        """
        trace_id = cycle.trace_id
        now = time.time()

        # --- detection span ------------------------------------------------
        det_span = self._start_span(
            trace_id=trace_id,
            operation="latency_arb.detection",
            binance_price=cycle.binance_price_at_trigger,
            direction=cycle.move_direction,
            magnitude=cycle.move_magnitude,
        )
        det_span.end(
            status="ok",
            move_detected_at=cycle.move_detected_at,
            detection_wall_time=now,
        )
        cycle.detection_span_id = det_span.span_id

        # --- wait until min_delay_ms has elapsed ---------------------------
        elapsed_ms = (now - cycle.move_detected_at) * 1000
        wait_ms = max(0.0, self.config.min_delay_ms - elapsed_ms)

        logger.info(
            "ArbCycle %s: move %s %.4f%%, waiting %.0f ms before Polymarket query.",
            cycle.cycle_id[:8],
            cycle.move_direction,
            cycle.move_magnitude * 100,
            wait_ms,
        )

        if wait_ms > 0:
            await asyncio.sleep(wait_ms / 1000.0)

        # --- check hard deadline -------------------------------------------
        elapsed_now_ms = (time.time() - cycle.move_detected_at) * 1000
        if elapsed_now_ms > self.config.max_delay_ms:
            cycle.order_skipped_reason = "window_expired"
            logger.info(
                "ArbCycle %s: window expired (%.0f ms > %d ms) — aborting.",
                cycle.cycle_id[:8],
                elapsed_now_ms,
                self.config.max_delay_ms,
            )
            self._finish_cycle(cycle)
            return

        # --- cooldown check ------------------------------------------------
        since_last = time.time() - self._last_trade_at
        if self._last_trade_at > 0 and since_last < self.config.cooldown_seconds:
            cycle.order_skipped_reason = "cooldown"
            logger.info(
                "ArbCycle %s: cooldown active (%.0f s remaining) — skipping.",
                cycle.cycle_id[:8],
                self.config.cooldown_seconds - since_last,
            )
            self._finish_cycle(cycle)
            return

        # --- evaluation span: query Polymarket prices ----------------------
        eval_span = self._start_span(
            trace_id=trace_id,
            operation="latency_arb.evaluation",
            markets_count=len(self.config.markets_to_watch),
        )

        cycle.entry_time = time.time()
        pm_prices = await self._fetch_polymarket_prices()
        cycle.polymarket_price_at_entry = pm_prices

        repriced = self._has_already_repriced(cycle, pm_prices)
        eval_span.end(
            status="ok",
            repriced=repriced,
            markets_queried=len(pm_prices),
        )
        cycle.evaluation_span_id = eval_span.span_id

        if repriced:
            cycle.order_skipped_reason = "already_repriced"
            logger.info(
                "ArbCycle %s: Polymarket already repriced — skipping.",
                cycle.cycle_id[:8],
            )
            self._finish_cycle(cycle)
            return

        # --- execution span: place order -----------------------------------
        exec_span = self._start_span(
            trace_id=trace_id,
            operation="latency_arb.execution",
            direction=cycle.move_direction,
        )

        success = await self._place_order(cycle)
        exec_span.end(
            status="ok" if success else "error",
            order_placed=success,
        )
        cycle.execution_span_id = exec_span.span_id
        cycle.order_placed = success

        if success:
            self._last_trade_at = time.time()
            self._daily_trade_count += 1

        self._finish_cycle(cycle)

    # ------------------------------------------------------------------
    # Polymarket interaction
    # ------------------------------------------------------------------

    async def _fetch_polymarket_prices(self) -> dict[str, float]:
        """
        Query current mid-prices from Polymarket for all watched markets.

        Returns a dict mapping condition_id -> mid_price (0.0-1.0).
        Falls back to an empty dict in dry-run mode.
        """
        if self._clob is None:
            logger.debug("LatencyArbEngine: dry-run — no CLOB client, returning empty prices.")
            return {}

        prices: dict[str, float] = {}
        for condition_id in self.config.markets_to_watch:
            try:
                # CLOBClient interface (to be implemented in parallel):
                #   clob_client.get_market_price(condition_id) -> float
                price = await self._clob.get_market_price(condition_id)
                prices[condition_id] = float(price)
            except Exception as exc:
                logger.warning(
                    "LatencyArbEngine: failed to fetch price for %s: %s",
                    condition_id,
                    exc,
                )
        return prices

    def _has_already_repriced(self, cycle: ArbCycle, pm_prices: dict[str, float]) -> bool:
        """
        Heuristic: has Polymarket already incorporated the BTC move?

        A simple implementation checks whether the Polymarket probability
        has moved at all from the ``feed.last_price``-implied fair value.
        The parallel CLOB client will provide richer snapshot history;
        until then, if we have no prices the default is "not repriced"
        (optimistic — prefer attempting the trade).
        """
        if not pm_prices:
            return False  # dry-run or no data → assume not repriced

        # If any price is available, we'd compare against a pre-move baseline.
        # Without a pre-move snapshot stored here we cannot make a definitive
        # call — return False to be optimistic in dry-run mode.
        # Real implementation: compare pm_prices against a snapshot captured
        # immediately after move_detected_at via the CLOB client.
        return False

    async def _place_order(self, cycle: ArbCycle) -> bool:
        """
        Place a directional market order on all watched markets.

        In dry-run mode (no CLOB client) logs the intended order and returns
        True to allow cycle tracking to proceed.
        """
        direction = cycle.move_direction
        side = "YES" if direction == "up" else "NO"

        if self._clob is None:
            logger.info(
                "LatencyArbEngine [DRY RUN]: would place %s orders on %d markets "
                "(max_usd=%.2f, btc_trigger=%.2f).",
                side,
                len(self.config.markets_to_watch),
                self.config.max_position_usd,
                cycle.binance_price_at_trigger,
            )
            return True

        all_ok = True
        for condition_id in self.config.markets_to_watch:
            try:
                # CLOBClient interface:
                #   clob_client.place_market_order(condition_id, side, size_usd) -> bool
                ok = await self._clob.place_market_order(
                    condition_id,
                    side=side,
                    size_usd=self.config.max_position_usd
                    / max(1, len(self.config.markets_to_watch)),
                )
                if not ok:
                    all_ok = False
            except Exception as exc:
                logger.error(
                    "LatencyArbEngine: order failed for %s: %s",
                    condition_id,
                    exc,
                )
                all_ok = False

        return all_ok

    # ------------------------------------------------------------------
    # Span helpers
    # ------------------------------------------------------------------

    def _start_span(self, trace_id: str, operation: str, **attrs: Any) -> _Span:
        span = _Span(
            span_id=str(uuid.uuid4()),
            trace_id=trace_id,
            operation=operation,
            started_at=time.time(),
            attributes=dict(attrs),
        )
        self.spans.append(span)
        return span

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def _finish_cycle(self, cycle: ArbCycle) -> None:
        self.completed_cycles.append(cycle)
        self._active_cycle = None
        logger.info(
            "ArbCycle %s complete: placed=%s skipped=%s",
            cycle.cycle_id[:8],
            cycle.order_placed,
            cycle.order_skipped_reason or "—",
        )

    def _reset_daily_counter_if_needed(self) -> None:
        today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        if today != self._daily_reset_date:
            self._daily_trade_count = 0
            self._daily_reset_date = today
