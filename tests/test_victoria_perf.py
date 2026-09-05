"""
tests/test_victoria_perf.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Performance benchmarks for the Victoria trading engine.

Benchmarks:
  - Heartbeat cycle time (end-to-end latency)
  - Data ingestion latency (mocked API calls)
  - Signal generation throughput (signals/second)
  - Memory usage: no unbounded growth across cycles

Marks:
  - Tests are marked as ``slow`` when they require timing precision.
  - Use ``pytest -m 'not slow'`` to skip during fast iteration.

All API calls are mocked — these are CPU/memory benchmarks only.

STANDING FINDING (2026-09-03), deliberately NOT worked around here:

Two budgets are still missed with the network removed, i.e. by computation alone:

    signal generation, 10 tickers x 90 bars   1370ms   budget   50ms
    full heartbeat cycle                       793ms   budget  200ms

Relaxing them would be a product decision — they may encode a live-loop SLA — so
they are left failing and visible rather than quietly widened. Either the signal
layer needs optimising or the budgets were never achievable; the numbers above say
which question to ask, and nothing here should be changed until that is answered.
"""

from __future__ import annotations

import gc
import math
import random
import sys
import time
import tracemalloc
import uuid
from typing import ClassVar
from unittest.mock import patch

import pytest

from omega.core.node import NodeInput
from omega.nodes.victoria.data_ingestion import DataIngestionNode
from omega.nodes.victoria.dynamic_weights import DynamicWeightAllocator
from omega.nodes.victoria.risk_management import RiskManagementNode
from omega.nodes.victoria.signal_generation import SignalGenerationNode
from omega.nodes.victoria.strategy import StrategyNode

# Marked slow: these run real multi-cycle Victoria simulations and take minutes.
# Unmarked, they made `pytest tests/` appear to hang, so the suite was not run —
# which is how a whole stale TestRegimeAdaptivity class sat failing unnoticed.
pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Thresholds (generous — CI machines vary widely)
# ---------------------------------------------------------------------------

# Signal generation for 10 tickers over 90 bars should complete in < 50ms
SIGNAL_GEN_LATENCY_MS = 50.0


@pytest.fixture(autouse=True)
def _no_network():
    """These measure COMPUTATION, so take the network out of the measurement.

    compute_signals reaches out to yfinance (via the macro cache) and to Deribit,
    so with a live connection this module was timing the internet: 2,988ms with
    network against 855ms without, on the same warm cache. A latency budget that
    moves with an exchange's response time is not a budget.

    NOTE: the budgets are still not met with the network removed — signal
    generation is ~855ms against the 50ms here. That gap is real and is NOT
    papered over by this fixture; see the module docstring.
    """
    import socket

    real = socket.socket

    class _Offline(socket.socket):
        def connect(self, *a, **k):
            raise OSError("network disabled: perf tests measure computation")

        def connect_ex(self, *a, **k):
            return 1

    socket.socket = _Offline
    try:
        yield
    finally:
        socket.socket = real

# Full portfolio construction (signals + strategy + risk) should be < 200ms
PIPELINE_LATENCY_MS = 200.0

# Single-node execution should never exceed 100ms (without network)
NODE_EXEC_LATENCY_MS = 100.0

# Throughput: should process at least 5 tickers/second
MIN_TICKERS_PER_SECOND = 5.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_input(action: str, **params) -> NodeInput:
    return NodeInput(request_id=str(uuid.uuid4()), action=action, parameters=params)


def _make_ohlcv(n: int = 90, seed: int = 42) -> dict:
    rng = random.Random(seed)
    prices = [50_000.0]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + rng.gauss(0.0002, 0.015)))
    return {
        "close": prices,
        "adjclose": prices,
        "open": [p * 0.999 for p in prices],
        "high": [p * 1.002 for p in prices],
        "low": [p * 0.998 for p in prices],
        "volume": [500_000.0 + rng.gauss(0, 10000) for _ in range(n)],
    }


def _make_market_data(n_tickers: int = 10, n_bars: int = 90) -> dict:
    tickers = [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "BNBUSDT",
        "XRPUSDT",
        "ADAUSDT",
        "DOTUSDT",
        "AVAXUSDT",
        "LINKUSDT",
        "MATICUSDT",
    ][:n_tickers]
    return {t: _make_ohlcv(n=n_bars, seed=i) for i, t in enumerate(tickers)}


def _make_mock_klines(*args, **kwargs):
    return _make_ohlcv(n=90)


# ---------------------------------------------------------------------------
# Signal generation throughput
# ---------------------------------------------------------------------------


class TestSignalGenerationPerf:
    def setup_method(self):
        self.node = SignalGenerationNode()
        # Enable all indicators for realistic benchmark
        self.node.improve({"iteration": 1})
        self.node.improve({"iteration": 2})

    def test_signal_generation_latency_10_tickers(self):
        """Signal generation for 10 tickers/90 bars should be < SIGNAL_GEN_LATENCY_MS."""
        md = _make_market_data(n_tickers=10, n_bars=90)

        t0 = time.perf_counter()
        out = self.node.execute(_make_input("compute_signals", market_data=md))
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert out.success
        assert elapsed_ms < SIGNAL_GEN_LATENCY_MS, (
            f"Signal generation took {elapsed_ms:.1f}ms, limit {SIGNAL_GEN_LATENCY_MS}ms"
        )

    @pytest.mark.slow
    def test_signal_generation_throughput(self):
        """Process ≥ MIN_TICKERS_PER_SECOND tickers per second."""
        n_tickers = 20
        md = _make_market_data(n_tickers=min(n_tickers, 10), n_bars=90)
        # Duplicate tickers for larger benchmark
        extra = {f"EXTRA{i}USDT": _make_ohlcv(seed=100 + i) for i in range(n_tickers - 10)}
        md.update(extra)

        t0 = time.perf_counter()
        out = self.node.execute(_make_input("compute_signals", market_data=md))
        elapsed_s = time.perf_counter() - t0

        signals_generated = len(out.result)
        throughput = signals_generated / elapsed_s
        assert throughput >= MIN_TICKERS_PER_SECOND, (
            f"Throughput {throughput:.1f} tickers/s below minimum {MIN_TICKERS_PER_SECOND}"
        )

    def test_signal_generation_scales_with_tickers(self):
        """Latency should scale roughly linearly — not super-linearly — with ticker count."""
        md_small = _make_market_data(n_tickers=2, n_bars=90)
        md_large = _make_market_data(n_tickers=10, n_bars=90)

        t0 = time.perf_counter()
        for _ in range(10):
            self.node.execute(_make_input("compute_signals", market_data=md_small))
        t_small = (time.perf_counter() - t0) / 10

        t0 = time.perf_counter()
        for _ in range(10):
            self.node.execute(_make_input("compute_signals", market_data=md_large))
        t_large = (time.perf_counter() - t0) / 10

        # Large (5x tickers) should not be more than 20x slower
        ratio = t_large / max(t_small, 1e-9)
        assert ratio < 20.0, (
            f"Scaling ratio {ratio:.1f}x is too high (expect < 20x for 5x tickers)"
        )

    def test_repeated_execution_no_latency_regression(self):
        """Later executions should not be significantly slower than early ones (no leak)."""
        md = _make_market_data(n_tickers=5, n_bars=90)

        times = []
        for _ in range(30):
            t0 = time.perf_counter()
            self.node.execute(_make_input("compute_signals", market_data=md))
            times.append((time.perf_counter() - t0) * 1000)

        # Median of last 10 vs first 10 — should not be more than 3x slower
        first_10_median = sorted(times[:10])[5]
        last_10_median = sorted(times[20:])[5]
        assert last_10_median < first_10_median * 3, (
            f"Latency regression detected: first={first_10_median:.2f}ms, last={last_10_median:.2f}ms"
        )


# ---------------------------------------------------------------------------
# Data ingestion latency (mocked)
# ---------------------------------------------------------------------------


class TestDataIngestionPerf:
    def setup_method(self):
        self.node = DataIngestionNode()

    @patch(
        "omega.nodes.victoria.data_ingestion.BinanceProvider.fetch_klines",
        side_effect=_make_mock_klines,
    )
    @patch("omega.nodes.victoria.data_ingestion.FearGreedProvider.fetch", return_value={})
    @patch("omega.nodes.victoria.data_ingestion.DefiLlamaProvider.fetch", return_value={})
    def test_fetch_market_data_latency(self, mock_defi, mock_fg, mock_klines):
        """Mocked data ingestion (no network) should be fast."""
        # Override sleep in _fetch_all_pairs to avoid 0.05s * 10 = 500ms
        with patch("time.sleep"):
            t0 = time.perf_counter()
            out = self.node.execute(_make_input("fetch_market_data"))
            elapsed_ms = (time.perf_counter() - t0) * 1000

        assert out.success
        assert elapsed_ms < NODE_EXEC_LATENCY_MS, (
            f"Data ingestion took {elapsed_ms:.1f}ms (mocked), limit {NODE_EXEC_LATENCY_MS}ms"
        )

    @patch(
        "omega.nodes.victoria.data_ingestion.BinanceProvider.fetch_klines",
        side_effect=_make_mock_klines,
    )
    @patch("omega.nodes.victoria.data_ingestion.FearGreedProvider.fetch", return_value={})
    @patch("omega.nodes.victoria.data_ingestion.DefiLlamaProvider.fetch", return_value={})
    def test_data_node_metrics_track_latency(self, mock_defi, mock_fg, mock_klines):
        with patch("time.sleep"):
            self.node.execute(_make_input("fetch_market_data"))

        state = self.node.get_state()
        assert state.metrics["avg_latency_ms"] >= 0.0
        assert state.metrics["avg_latency_ms"] < NODE_EXEC_LATENCY_MS


# ---------------------------------------------------------------------------
# Risk management performance
# ---------------------------------------------------------------------------


class TestRiskManagementPerf:
    def setup_method(self):
        self.node = RiskManagementNode()
        self.node.improve({"iteration": 1})
        self.node.improve({"iteration": 2})

    def test_var_computation_latency(self):
        """VaR + CVaR + correlation for 5 assets should be fast."""
        md = _make_market_data(n_tickers=5)
        portfolio = {"weights": {t: 0.2 for t in list(md.keys())}}

        t0 = time.perf_counter()
        out = self.node.execute(
            _make_input("check_risk_limits", portfolio=portfolio, market_data=md)
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert out.success
        assert elapsed_ms < NODE_EXEC_LATENCY_MS, (
            f"Risk check took {elapsed_ms:.1f}ms, limit {NODE_EXEC_LATENCY_MS}ms"
        )

    def test_correlation_matrix_latency(self):
        md = _make_market_data(n_tickers=10)

        t0 = time.perf_counter()
        out = self.node.execute(_make_input("compute_correlation", market_data=md))
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert out.success
        assert elapsed_ms < NODE_EXEC_LATENCY_MS


# ---------------------------------------------------------------------------
# Strategy node performance
# ---------------------------------------------------------------------------


class TestStrategyNodePerf:
    def setup_method(self):
        self.node = StrategyNode()

    def _make_signals(self, tickers: list[str]) -> dict:
        rng = random.Random(42)
        return {
            t: {"composite": rng.uniform(-1, 1), "price": 50000.0, "return_1d": 0.001}
            for t in tickers
        }

    def test_portfolio_construction_latency(self):
        tickers = list(_make_market_data(n_tickers=10).keys())
        signals = self._make_signals(tickers)
        md = _make_market_data(n_tickers=10)

        t0 = time.perf_counter()
        out = self.node.execute(
            _make_input("construct_portfolio", signals=signals, market_data=md)
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert out.success
        assert elapsed_ms < PIPELINE_LATENCY_MS, (
            f"Portfolio construction took {elapsed_ms:.1f}ms, limit {PIPELINE_LATENCY_MS}ms"
        )

    def test_backtest_latency(self):
        """Backtest on 10 tickers x 90 bars should complete quickly."""
        md = _make_market_data(n_tickers=5, n_bars=90)
        signals = self._make_signals(list(md.keys()))

        t0 = time.perf_counter()
        out = self.node.execute(_make_input("backtest_strategy", signals=signals, market_data=md))
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert out.success
        assert elapsed_ms < PIPELINE_LATENCY_MS, (
            f"Backtest took {elapsed_ms:.1f}ms, limit {PIPELINE_LATENCY_MS}ms"
        )

    @pytest.mark.slow
    def test_backtest_latency_scales_acceptably_with_bars(self):
        """Backtest on 500 bars should still be < 2s."""
        md = _make_market_data(n_tickers=3, n_bars=500)
        signals = self._make_signals(list(md.keys()))

        t0 = time.perf_counter()
        out = self.node.execute(_make_input("backtest_strategy", signals=signals, market_data=md))
        elapsed_s = time.perf_counter() - t0

        assert out.success
        assert elapsed_s < 2.0, f"Long backtest took {elapsed_s:.2f}s, limit 2s"


# ---------------------------------------------------------------------------
# Full pipeline cycle latency
# ---------------------------------------------------------------------------


class TestHeartbeatCyclePerf:
    """Benchmark a full in-process heartbeat cycle (no I/O)."""

    def setup_method(self):
        self.signal_node = SignalGenerationNode()
        self.strategy_node = StrategyNode()
        self.risk_node = RiskManagementNode()
        self.signal_node.improve({"iteration": 1})
        self.signal_node.improve({"iteration": 2})
        self.risk_node.improve({"iteration": 1})

    def _run_cycle(self, md: dict) -> float:
        """Run one full in-process cycle and return elapsed ms."""
        t0 = time.perf_counter()

        # Stage 1: signals
        signal_out = self.signal_node.execute(_make_input("compute_signals", market_data=md))
        if not signal_out.success:
            return (time.perf_counter() - t0) * 1000

        # Stage 2: portfolio
        portfolio_out = self.strategy_node.execute(
            _make_input("construct_portfolio", signals=signal_out.result, market_data=md)
        )
        if not portfolio_out.success:
            return (time.perf_counter() - t0) * 1000

        # Stage 3: risk
        weights = portfolio_out.result.get("weights", {})
        if weights:
            self.risk_node.execute(
                _make_input(
                    "check_risk_limits",
                    portfolio={"weights": weights},
                    market_data=md,
                )
            )

        return (time.perf_counter() - t0) * 1000

    def test_single_cycle_latency(self):
        """A full in-process pipeline cycle should be < PIPELINE_LATENCY_MS."""
        md = _make_market_data(n_tickers=10, n_bars=90)
        elapsed_ms = self._run_cycle(md)
        assert elapsed_ms < PIPELINE_LATENCY_MS, (
            f"Full cycle took {elapsed_ms:.1f}ms, limit {PIPELINE_LATENCY_MS}ms"
        )

    @pytest.mark.slow
    def test_100_cycles_no_degradation(self):
        """Run 100 cycles and verify no significant latency growth."""
        md = _make_market_data(n_tickers=5, n_bars=90)
        times = [self._run_cycle(md) for _ in range(100)]

        first_10_avg = sum(times[:10]) / 10
        last_10_avg = sum(times[90:]) / 10

        # Last 10 cycles should not be more than 5x slower than first 10
        assert last_10_avg < first_10_avg * 5, (
            f"Cycle latency degraded: first={first_10_avg:.1f}ms, last={last_10_avg:.1f}ms"
        )

    @pytest.mark.slow
    def test_cycle_p99_latency(self):
        """99th percentile cycle latency should be < 2 * PIPELINE_LATENCY_MS."""
        md = _make_market_data(n_tickers=5, n_bars=90)
        times = sorted(self._run_cycle(md) for _ in range(50))
        p99 = times[int(0.99 * len(times))]
        assert p99 < PIPELINE_LATENCY_MS * 2, (
            f"P99 latency {p99:.1f}ms exceeds limit {PIPELINE_LATENCY_MS * 2}ms"
        )


# ---------------------------------------------------------------------------
# Memory usage profiling
# ---------------------------------------------------------------------------


class TestMemoryUsage:
    """Verify no unbounded memory growth across repeated cycles."""

    def test_signal_node_no_memory_leak(self):
        """Memory after 100 executions should not be > 10 MB above baseline."""
        node = SignalGenerationNode()
        node.improve({"iteration": 1})
        node.improve({"iteration": 2})
        md = _make_market_data(n_tickers=5, n_bars=90)

        # Warm up
        for _ in range(5):
            node.execute(_make_input("compute_signals", market_data=md))

        gc.collect()
        tracemalloc.start()
        snapshot1 = tracemalloc.take_snapshot()

        for _ in range(100):
            node.execute(_make_input("compute_signals", market_data=md))

        gc.collect()
        snapshot2 = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snapshot2.compare_to(snapshot1, "lineno")
        total_diff_bytes = sum(s.size_diff for s in stats if s.size_diff > 0)
        total_diff_mb = total_diff_bytes / (1024 * 1024)

        # Allow up to 10 MB growth for 100 cycles
        assert total_diff_mb < 10.0, f"Memory grew by {total_diff_mb:.1f} MB over 100 cycles"

    def test_dynamic_weight_allocator_no_memory_leak(self):
        """DynamicWeightAllocator should not accumulate unbounded IC history."""
        signals = ["sma_crossover", "rsi_signal", "macd_crossover", "bb_signal"]
        alloc = DynamicWeightAllocator(signals)

        gc.collect()
        tracemalloc.start()
        snapshot1 = tracemalloc.take_snapshot()

        for i in range(1000):
            for s in signals:
                alloc.update_ic(s, 0.1 + 0.01 * (i % 10))
            alloc.allocate()

        gc.collect()
        snapshot2 = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snapshot2.compare_to(snapshot1, "lineno")
        total_diff_bytes = sum(s.size_diff for s in stats if s.size_diff > 0)
        total_diff_mb = total_diff_bytes / (1024 * 1024)

        assert total_diff_mb < 5.0, (
            f"DynamicWeightAllocator memory grew by {total_diff_mb:.1f} MB over 1000 updates"
        )

    def test_risk_node_portfolio_returns_bounded(self):
        """Risk node should not cache unbounded portfolio return history."""
        node = RiskManagementNode()
        node.improve({"iteration": 1})

        md = _make_market_data(n_tickers=5, n_bars=90)

        gc.collect()
        size_before = sys.getsizeof(node.__dict__)

        for _ in range(50):
            portfolio = {"weights": {t: 0.2 for t in list(md.keys())}}
            node.execute(_make_input("compute_var", portfolio=portfolio, market_data=md))

        gc.collect()
        size_after = sys.getsizeof(node.__dict__)

        # Node state dict should not grow significantly (< 10x)
        assert size_after < size_before * 10, (
            f"Risk node state size grew from {size_before} to {size_after} bytes"
        )


# ---------------------------------------------------------------------------
# Dynamic weight allocator performance
# ---------------------------------------------------------------------------


class TestDynamicWeightAllocatorPerf:
    SIGNALS: ClassVar[list[str]] = [
        "sma_crossover",
        "rsi_signal",
        "macd_crossover",
        "bb_signal",
        "zscore_signal",
        "volume_signal",
    ]

    def setup_method(self):
        self.alloc = DynamicWeightAllocator(self.SIGNALS)

    def test_allocation_latency_cold(self):
        """Allocation without IC data should be immediate."""
        t0 = time.perf_counter()
        for _ in range(1000):
            self.alloc.allocate()
        elapsed_ms = time.perf_counter() - t0
        # 1000 allocations should take < 100ms
        assert elapsed_ms < 0.1, f"1000 cold allocations took {elapsed_ms * 1000:.1f}ms"

    def test_allocation_latency_with_ic_history(self):
        """Allocation with IC history should still be fast."""
        for _ in range(50):
            for s in self.SIGNALS:
                self.alloc.update_ic(s, random.gauss(0.1, 0.05))

        t0 = time.perf_counter()
        for _ in range(1000):
            self.alloc.allocate()
        elapsed_ms = time.perf_counter() - t0
        # 1000 warm allocations should take < 100ms
        assert elapsed_ms < 0.1, f"1000 warm allocations took {elapsed_ms * 1000:.1f}ms"

    def test_ic_update_throughput(self):
        """IC updates should handle high-frequency updates without slowdown."""
        t0 = time.perf_counter()
        for i in range(10_000):
            s = self.SIGNALS[i % len(self.SIGNALS)]
            self.alloc.update_ic(s, 0.1 + 0.05 * math.sin(i))
        elapsed_ms = (time.perf_counter() - t0) * 1000
        # 10k updates should complete in < 500ms
        assert elapsed_ms < 500.0, f"10k IC updates took {elapsed_ms:.1f}ms"
