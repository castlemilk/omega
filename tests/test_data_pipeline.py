"""Tests for DataPipeline orchestrator."""

from __future__ import annotations

import threading
import time

import pytest

from omega.data.base import DataBuffer, DataSource, MarketData
from omega.data.data_pipeline import DataPipeline, SourceConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_market_data(symbol: str = "BTC/USDT", price: float = 50_000.0) -> MarketData:
    return MarketData(
        timestamp=time.time(),
        symbol=symbol,
        bid=price - 1,
        ask=price + 1,
        last_price=price,
        volume_24h=1_000_000.0,
    )


class FakeSource(DataSource):
    """In-process DataSource that returns pre-canned MarketData."""

    def __init__(
        self,
        name: str = "fake",
        data: MarketData | None = None,
        fail_times: int = 0,
    ) -> None:
        super().__init__(name=name)
        self._data = data
        self._fail_times = fail_times
        self._call_count = 0

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def subscribe(self, symbol: str) -> None:
        pass

    def get_snapshot(self, symbol: str) -> MarketData | None:
        self._call_count += 1
        if self._call_count <= self._fail_times:
            raise RuntimeError(f"Simulated failure #{self._call_count}")
        md = self._data or _make_market_data(symbol)
        self._mark_fetch()
        return md


# ---------------------------------------------------------------------------
# DataBuffer tests
# ---------------------------------------------------------------------------


class TestDataBuffer:
    def test_push_and_peek(self):
        buf: DataBuffer[int] = DataBuffer(maxlen=10)
        buf.push(1)
        buf.push(2)
        buf.push(3)
        assert buf.peek(2) == [2, 3]

    def test_maxlen_evicts_oldest(self):
        buf: DataBuffer[int] = DataBuffer(maxlen=3)
        for i in range(5):
            buf.push(i)
        assert len(buf) == 3
        assert buf.snapshot() == [2, 3, 4]

    def test_pop_returns_oldest(self):
        buf: DataBuffer[int] = DataBuffer(maxlen=10)
        buf.push(10)
        buf.push(20)
        assert buf.pop(timeout=0.1) == 10
        assert buf.pop(timeout=0.1) == 20

    def test_pop_blocks_until_data(self):
        buf: DataBuffer[int] = DataBuffer(maxlen=10)
        results: list[int | None] = []

        def reader():
            results.append(buf.pop(timeout=1.0))

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        time.sleep(0.05)
        buf.push(42)
        t.join(timeout=2.0)
        assert results == [42]

    def test_pop_returns_none_on_timeout(self):
        buf: DataBuffer[int] = DataBuffer(maxlen=10)
        result = buf.pop(timeout=0.05)
        assert result is None

    def test_thread_safety_concurrent_pushes(self):
        buf: DataBuffer[int] = DataBuffer(maxlen=10_000)
        errors: list[Exception] = []
        n = 500
        threads_per_side = 4

        def pusher(start: int):
            try:
                for i in range(start, start + n):
                    buf.push(i)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=pusher, args=(i * n,), daemon=True)
            for i in range(threads_per_side)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors
        assert len(buf) == threads_per_side * n

    def test_iter_drain_clears_buffer(self):
        buf: DataBuffer[int] = DataBuffer(maxlen=100)
        for i in range(5):
            buf.push(i)
        drained = list(buf.iter_drain())
        assert drained == [0, 1, 2, 3, 4]
        assert len(buf) == 0

    def test_clear(self):
        buf: DataBuffer[int] = DataBuffer(maxlen=10)
        buf.push(1)
        buf.push(2)
        buf.clear()
        assert len(buf) == 0

    def test_snapshot_does_not_drain(self):
        buf: DataBuffer[int] = DataBuffer(maxlen=10)
        buf.push(1)
        buf.push(2)
        snap = buf.snapshot()
        assert snap == [1, 2]
        assert len(buf) == 2  # unchanged


# ---------------------------------------------------------------------------
# Pipeline source management tests
# ---------------------------------------------------------------------------


class TestDataPipelineSourceManagement:
    def test_add_source_creates_buffers(self):
        pipe = DataPipeline()
        src = FakeSource()
        pipe.add_source(SourceConfig(source=src, symbols=["BTC/USDT", "ETH/USDT"]))
        assert pipe.get_buffer("BTC/USDT") is not None
        assert pipe.get_buffer("ETH/USDT") is not None
        assert pipe.get_buffer("DOGE/USDT") is None

    def test_start_connects_sources(self):
        pipe = DataPipeline()
        src = FakeSource()
        pipe.add_source(
            SourceConfig(
                source=src,
                symbols=["BTC/USDT"],
                poll_interval_secs=100,  # long interval so we control timing
            )
        )
        pipe.start()
        assert src.connected
        pipe.stop()

    def test_stop_disconnects_sources(self):
        pipe = DataPipeline()
        src = FakeSource()
        pipe.add_source(SourceConfig(source=src, symbols=["BTC/USDT"], poll_interval_secs=100))
        pipe.start()
        pipe.stop()
        assert not src.connected

    def test_context_manager(self):
        src = FakeSource()
        pipe = DataPipeline()
        pipe.add_source(SourceConfig(source=src, symbols=["BTC/USDT"], poll_interval_secs=100))
        with pipe:
            assert src.connected
        assert not src.connected

    def test_data_arrives_in_buffer(self):
        expected = _make_market_data("BTC/USDT", price=45_000)
        src = FakeSource(data=expected)
        pipe = DataPipeline()
        pipe.add_source(
            SourceConfig(
                source=src,
                symbols=["BTC/USDT"],
                poll_interval_secs=0.05,
            )
        )
        pipe.start()
        time.sleep(0.3)
        pipe.stop()
        buf = pipe.get_buffer("BTC/USDT")
        assert buf is not None
        assert len(buf) > 0
        latest = pipe.latest("BTC/USDT")
        assert latest is not None
        assert latest.last_price == pytest.approx(45_000)

    def test_callback_invoked(self):
        received: list[MarketData] = []
        src = FakeSource()
        pipe = DataPipeline()
        pipe.on_data(received.append)
        pipe.add_source(SourceConfig(source=src, symbols=["BTC/USDT"], poll_interval_secs=0.05))
        pipe.start()
        time.sleep(0.3)
        pipe.stop()
        assert len(received) > 0

    def test_health_report(self):
        src = FakeSource()
        pipe = DataPipeline()
        pipe.add_source(SourceConfig(source=src, symbols=["BTC/USDT"], poll_interval_secs=100))
        pipe.start()
        pipe.stop()
        h = pipe.health()
        assert h["running"] is False
        assert len(h["sources"]) == 1
        assert "BTC/USDT" in h["buffers"]


# ---------------------------------------------------------------------------
# Failure / retry logic tests
# ---------------------------------------------------------------------------


class TestPipelineRetryLogic:
    def test_retries_on_failure(self):
        """Source fails N times then succeeds; data should still arrive."""
        src = FakeSource(fail_times=2)
        pipe = DataPipeline()
        pipe.add_source(
            SourceConfig(
                source=src,
                symbols=["ETH/USDT"],
                poll_interval_secs=0.1,
                max_retries=3,
                backoff_base_secs=0.01,
            )
        )
        pipe.start()
        time.sleep(0.5)
        pipe.stop()
        assert src._call_count >= 3
        latest = pipe.latest("ETH/USDT")
        assert latest is not None

    def test_fallback_source_used_on_exhausted_retries(self):
        """Primary source always fails; fallback should deliver data."""
        primary = FakeSource(name="primary", fail_times=999)
        fallback_md = _make_market_data("SOL/USDT", price=100)
        fallback = FakeSource(name="fallback", data=fallback_md)

        pipe = DataPipeline()
        pipe.add_source(
            SourceConfig(
                source=primary,
                symbols=["SOL/USDT"],
                poll_interval_secs=0.1,
                max_retries=1,
                backoff_base_secs=0.01,
                fallback_source=fallback,
            )
        )
        pipe.start()
        time.sleep(0.5)
        pipe.stop()

        latest = pipe.latest("SOL/USDT")
        assert latest is not None
        assert latest.last_price == pytest.approx(100)

    def test_no_crash_when_callback_raises(self):
        """A misbehaving callback must not crash the pipeline thread."""

        def bad_cb(md: MarketData) -> None:
            raise RuntimeError("callback error")

        src = FakeSource()
        pipe = DataPipeline()
        pipe.on_data(bad_cb)
        pipe.add_source(SourceConfig(source=src, symbols=["BTC/USDT"], poll_interval_secs=0.05))
        pipe.start()
        time.sleep(0.3)
        # Pipeline thread must still be alive
        assert pipe.is_running
        pipe.stop()


# ---------------------------------------------------------------------------
# Data format / conversion tests
# ---------------------------------------------------------------------------


class TestMarketData:
    def test_mid_price(self):
        md = MarketData(timestamp=0, symbol="X", bid=100, ask=102, last_price=101, volume_24h=0)
        assert md.mid_price == pytest.approx(101)

    def test_spread(self):
        md = MarketData(timestamp=0, symbol="X", bid=100, ask=102, last_price=101, volume_24h=0)
        assert md.spread == pytest.approx(2)

    def test_spread_bps(self):
        md = MarketData(timestamp=0, symbol="X", bid=999, ask=1001, last_price=1000, volume_24h=0)
        assert md.spread_bps == pytest.approx(20)  # 2/1000 * 10000

    def test_zero_mid_price_spread_bps(self):
        md = MarketData(timestamp=0, symbol="X", bid=0, ask=0, last_price=0, volume_24h=0)
        assert md.spread_bps == 0.0
