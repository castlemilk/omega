"""
tests.test_latency_arb
~~~~~~~~~~~~~~~~~~~~~~
Unit tests for the Polymarket latency-arbitrage engine.

Tests
-----
* LatencyArbConfig validation
* BinancePriceFeed price-move detection logic
* Timing window enforcement (9-16 s hard window)
* ArbCycle signal generation and cycle recording
* Mock WebSocket feed driving the engine end-to-end

Note: tests use asyncio.run() directly — no pytest-asyncio required.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from omega.nodes.polymarket.strategies.binance_feed import BinancePriceFeed
from omega.nodes.polymarket.strategies.latency_arb import ArbCycle, LatencyArbEngine
from omega.nodes.polymarket.strategies.latency_arb_config import LatencyArbConfig

# ===========================================================================
# LatencyArbConfig
# ===========================================================================


class TestLatencyArbConfig:
    def test_defaults(self):
        cfg = LatencyArbConfig()
        assert cfg.price_move_threshold == pytest.approx(0.0011)
        assert cfg.min_delay_ms == 9_000
        assert cfg.max_delay_ms == 16_000
        assert cfg.cooldown_seconds == 60
        assert cfg.max_daily_trades == 20
        assert cfg.markets_to_watch == []

    def test_window_ms(self):
        cfg = LatencyArbConfig(min_delay_ms=9_000, max_delay_ms=16_000)
        assert cfg.window_ms == 7_000

    def test_invalid_delay_order_raises(self):
        with pytest.raises(ValueError, match="min_delay_ms"):
            LatencyArbConfig(min_delay_ms=16_000, max_delay_ms=9_000)

    def test_invalid_threshold_raises(self):
        with pytest.raises(ValueError, match="price_move_threshold"):
            LatencyArbConfig(price_move_threshold=0.0)

    def test_invalid_position_size_raises(self):
        with pytest.raises(ValueError, match="max_position_usd"):
            LatencyArbConfig(max_position_usd=-10.0)

    def test_custom_markets(self):
        markets = ["cond_abc", "cond_def"]
        cfg = LatencyArbConfig(markets_to_watch=markets)
        assert cfg.markets_to_watch == markets


# ===========================================================================
# BinancePriceFeed — price move detection
# ===========================================================================


class TestBinancePriceFeedMoveDetection:
    def _make_feed(self, threshold: float = 0.0011) -> BinancePriceFeed:
        return BinancePriceFeed(threshold=threshold)

    def test_no_move_below_threshold(self):
        detected: list = []
        feed = self._make_feed(threshold=0.0011)
        feed.on_move_detected = lambda d, m, p, t: detected.append((d, m))

        base = 50_000.0
        asyncio.run(feed._update_price(base, 0.0))
        asyncio.run(feed._update_price(base * 1.0010, 1.0))  # 0.10% — below threshold

        assert detected == [], "No callback expected below threshold"

    def test_upward_move_detected(self):
        detected: list = []
        feed = self._make_feed(threshold=0.0011)
        feed.on_move_detected = lambda d, m, p, t: detected.append((d, m, p, t))

        base = 50_000.0
        ts0 = time.time()
        asyncio.run(feed._update_price(base, ts0))
        new_price = base * 1.0015  # 0.15% — above threshold
        asyncio.run(feed._update_price(new_price, ts0 + 1.0))

        assert len(detected) == 1
        direction, magnitude, price, _ = detected[0]
        assert direction == "up"
        assert magnitude == pytest.approx(0.0015, rel=1e-3)
        assert price == pytest.approx(new_price, rel=1e-6)

    def test_downward_move_detected(self):
        detected: list = []
        feed = self._make_feed(threshold=0.0011)
        feed.on_move_detected = lambda d, m, p, t: detected.append((d, m))

        base = 50_000.0
        ts0 = time.time()
        asyncio.run(feed._update_price(base, ts0))
        asyncio.run(feed._update_price(base * 0.9984, ts0 + 1.0))  # -0.16%

        assert len(detected) == 1
        assert detected[0][0] == "down"
        assert detected[0][1] == pytest.approx(0.0016, rel=1e-3)

    def test_window_resets_after_detection(self):
        """After a move fires, window clears — next tick needs a fresh spike."""
        detected: list = []
        feed = self._make_feed(threshold=0.0011)
        feed.on_move_detected = lambda d, m, p, t: detected.append((d, m))

        base = 50_000.0
        ts = time.time()
        asyncio.run(feed._update_price(base, ts))
        asyncio.run(feed._update_price(base * 1.0015, ts + 1))  # triggers, resets ref
        # Tiny move from the new reference → should NOT trigger
        asyncio.run(feed._update_price(base * 1.0016, ts + 2))

        assert len(detected) == 1

    def test_async_callback_is_awaited(self):
        results: list = []

        async def async_cb(d: str, m: float, p: float, t: float) -> None:
            results.append(d)

        feed = self._make_feed(threshold=0.0011)
        feed.on_move_detected = async_cb

        base = 50_000.0
        ts = time.time()

        async def _run() -> None:
            await feed._update_price(base, ts)
            await feed._update_price(base * 1.002, ts + 1)

        asyncio.run(_run())
        assert results == ["up"]

    def test_move_count_increments(self):
        feed = self._make_feed(threshold=0.0011)
        base = 50_000.0
        ts = time.time()

        async def _run() -> None:
            await feed._update_price(base, ts)
            await feed._update_price(base * 1.002, ts + 1)  # triggers
            await feed._update_price(base * 0.9970, ts + 2)  # triggers again from new ref

        asyncio.run(_run())
        assert feed.moves_detected == 2


# ===========================================================================
# BinancePriceFeed — WebSocket message parsing
# ===========================================================================


class TestBinanceFeedMessageParsing:
    def test_valid_trade_message_updates_price(self):
        feed = BinancePriceFeed(threshold=0.0011)
        raw = '{"e":"trade","p":"50123.45","T":1711000000000,"q":"0.01"}'
        asyncio.run(feed._handle_message(raw))
        assert feed.last_price == pytest.approx(50123.45)
        assert feed.messages_received == 1

    def test_malformed_json_is_silently_skipped(self):
        feed = BinancePriceFeed(threshold=0.0011)
        asyncio.run(feed._handle_message("{not valid json}"))
        assert feed.messages_received == 0

    def test_missing_price_field_is_skipped(self):
        feed = BinancePriceFeed(threshold=0.0011)
        raw = '{"e":"trade","T":1711000000000}'
        asyncio.run(feed._handle_message(raw))
        assert feed.messages_received == 0

    def test_backoff_delay_sequence(self):
        feed = BinancePriceFeed(max_reconnect_delay_s=30.0)
        delays = [feed._backoff_delay() for _ in range(6)]
        assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]


# ===========================================================================
# BinancePriceFeed — exponential backoff
# ===========================================================================


class TestBinanceFeedBackoff:
    def test_backoff_caps_at_max(self):
        feed = BinancePriceFeed(max_reconnect_delay_s=10.0)
        delays = [feed._backoff_delay() for _ in range(10)]
        assert all(d <= 10.0 for d in delays)
        assert delays[-1] == 10.0


# ===========================================================================
# Timing window enforcement (9-16 s)
# ===========================================================================


class TestArbCycleTimingWindow:
    def _make_engine(self, **config_kwargs) -> LatencyArbEngine:
        cfg = LatencyArbConfig(
            min_delay_ms=100,  # short delays for test speed
            max_delay_ms=500,
            markets_to_watch=["cond_test"],
            **config_kwargs,
        )
        return LatencyArbEngine(config=cfg, clob_client=None)

    def test_cycle_waits_min_delay(self):
        """Engine waits at least min_delay_ms before querying Polymarket."""
        engine = self._make_engine()
        cycle = ArbCycle(
            move_detected_at=time.time(),
            move_direction="up",
            move_magnitude=0.002,
            binance_price_at_trigger=50_000.0,
        )

        t_start = time.time()
        asyncio.run(engine._run_arb_cycle(cycle))
        elapsed_ms = (time.time() - t_start) * 1000

        assert elapsed_ms >= engine.config.min_delay_ms * 0.9, (
            f"Expected ≥{engine.config.min_delay_ms}ms, got {elapsed_ms:.0f}ms"
        )

    def test_cycle_aborts_if_window_already_expired(self):
        """If max_delay_ms already elapsed when run starts, abort immediately."""
        engine = self._make_engine()
        # Move happened 10 s ago; test max is 0.5 s
        stale_move_time = time.time() - 10.0

        cycle = ArbCycle(
            move_detected_at=stale_move_time,
            move_direction="up",
            move_magnitude=0.002,
            binance_price_at_trigger=50_000.0,
        )
        asyncio.run(engine._run_arb_cycle(cycle))

        assert cycle.order_skipped_reason == "window_expired"
        assert not cycle.order_placed

    def test_cycle_within_window_does_not_abort(self):
        """A fresh move (within window) does not abort due to window expiry."""
        engine = self._make_engine()
        cycle = ArbCycle(
            move_detected_at=time.time(),
            move_direction="down",
            move_magnitude=0.0015,
            binance_price_at_trigger=49_000.0,
        )
        asyncio.run(engine._run_arb_cycle(cycle))
        assert cycle.order_skipped_reason != "window_expired"


# ===========================================================================
# Signal generation and cycle recording
# ===========================================================================


class TestArbSignalGeneration:
    def _make_engine(self) -> LatencyArbEngine:
        cfg = LatencyArbConfig(
            min_delay_ms=50,
            max_delay_ms=500,
            markets_to_watch=["cond_a", "cond_b"],
        )
        return LatencyArbEngine(config=cfg)

    def test_completed_cycles_recorded(self):
        engine = self._make_engine()
        cycle = ArbCycle(
            move_detected_at=time.time(),
            move_direction="up",
            move_magnitude=0.002,
            binance_price_at_trigger=50_000.0,
        )
        asyncio.run(engine._run_arb_cycle(cycle))
        assert len(engine.completed_cycles) == 1
        assert engine.completed_cycles[0].cycle_id == cycle.cycle_id

    def test_otel_spans_emitted(self):
        engine = self._make_engine()
        cycle = ArbCycle(
            move_detected_at=time.time(),
            move_direction="up",
            move_magnitude=0.002,
            binance_price_at_trigger=50_000.0,
        )
        asyncio.run(engine._run_arb_cycle(cycle))

        ops = [s.operation for s in engine.spans]
        assert "latency_arb.detection" in ops
        assert "latency_arb.evaluation" in ops
        assert "latency_arb.execution" in ops

    def test_span_trace_ids_match_cycle(self):
        engine = self._make_engine()
        cycle = ArbCycle(
            move_detected_at=time.time(),
            move_direction="up",
            move_magnitude=0.002,
            binance_price_at_trigger=50_000.0,
        )
        asyncio.run(engine._run_arb_cycle(cycle))

        span_ids = {cycle.detection_span_id, cycle.evaluation_span_id, cycle.execution_span_id}
        for span in engine.spans:
            if span.span_id in span_ids:
                assert span.trace_id == cycle.trace_id

    def test_dry_run_places_order(self):
        """In dry-run mode (no CLOB), order_placed should be True."""
        engine = self._make_engine()
        cycle = ArbCycle(
            move_detected_at=time.time(),
            move_direction="up",
            move_magnitude=0.002,
            binance_price_at_trigger=50_000.0,
        )
        asyncio.run(engine._run_arb_cycle(cycle))
        assert cycle.order_placed is True

    def test_cycle_direction_up_preserved(self):
        engine = self._make_engine()
        cycle = ArbCycle(
            move_detected_at=time.time(),
            move_direction="up",
            move_magnitude=0.002,
            binance_price_at_trigger=50_000.0,
        )
        asyncio.run(engine._run_arb_cycle(cycle))
        assert cycle.move_direction == "up"

    def test_cycle_direction_down_preserved(self):
        engine = self._make_engine()
        cycle = ArbCycle(
            move_detected_at=time.time(),
            move_direction="down",
            move_magnitude=0.0014,
            binance_price_at_trigger=49_000.0,
        )
        asyncio.run(engine._run_arb_cycle(cycle))
        assert cycle.move_direction == "down"


# ===========================================================================
# Daily trade limit
# ===========================================================================


class TestDailyTradeLimit:
    def test_daily_limit_blocks_new_cycles(self):
        cfg = LatencyArbConfig(
            min_delay_ms=50,
            max_delay_ms=500,
            markets_to_watch=["cond_x"],
            max_daily_trades=1,
        )
        engine = LatencyArbEngine(config=cfg)

        # First cycle completes successfully
        c1 = ArbCycle(
            move_detected_at=time.time(),
            move_direction="up",
            move_magnitude=0.002,
            binance_price_at_trigger=50_000.0,
        )
        asyncio.run(engine._run_arb_cycle(c1))
        assert c1.order_placed

        # Second cycle should be dropped because daily limit is reached
        dispatched: list[ArbCycle] = []
        original_run = engine._run_arb_cycle

        async def capture(cycle: ArbCycle) -> None:
            dispatched.append(cycle)
            await original_run(cycle)

        engine._run_arb_cycle = capture

        async def _trigger() -> None:
            await engine._on_move("up", 0.002, 51_000.0, time.time())
            await asyncio.sleep(0.01)

        asyncio.run(_trigger())
        assert len(dispatched) == 0, "Second cycle should be blocked by daily limit"


# ===========================================================================
# Mock WebSocket integration test
# ===========================================================================


class TestMockWebSocketFeed:
    def test_engine_detects_move_from_ws(self):
        """Feed processes mock WS messages and triggers an arb cycle."""
        import json

        completed: list[ArbCycle] = []

        cfg = LatencyArbConfig(
            min_delay_ms=50,
            max_delay_ms=500,
            markets_to_watch=["cond_ws_test"],
        )
        engine = LatencyArbEngine(config=cfg)

        original_finish = engine._finish_cycle

        def capture_finish(cycle: ArbCycle) -> None:
            completed.append(cycle)
            original_finish(cycle)

        engine._finish_cycle = capture_finish
        base_price = 60_000.0
        spike_price = base_price * 1.005  # 0.5% — well above 0.11%
        now_ms = int(time.time() * 1000)

        msgs = [
            json.dumps({"e": "trade", "p": str(base_price), "T": now_ms}),
            json.dumps({"e": "trade", "p": str(spike_price), "T": now_ms + 100}),
        ]

        async def _run() -> None:
            for raw in msgs:
                await engine._feed._handle_message(raw)
            if engine._pending_cycle_task:
                await asyncio.wait_for(engine._pending_cycle_task, timeout=2.0)

        asyncio.run(_run())

        assert len(completed) == 1, "Expected exactly one arb cycle to complete"
        assert completed[0].move_direction == "up"
        assert completed[0].binance_price_at_trigger == pytest.approx(spike_price, rel=1e-6)
