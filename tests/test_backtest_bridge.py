"""
Integration tests for omega.eval.backtest_bridge — OmegaBacktestBridge.

These tests run the actual OmegaOrchestrator against synthetic OHLCV data.
They are integration tests: they exercise the full pipeline (signals →
strategy → adversarial → position → PnL) without mocking inner components.
"""

import math
import random

import pytest

from omega.eval.backtest_bridge import BacktestMode, BacktestResult, OmegaBacktestBridge
from omega.eval.baselines import buy_and_hold
from omega.eval.metrics import EvalReport


def _make_ohlcv(
    n: int = 200,
    start: float = 100.0,
    trend: float = 0.001,
    volatility: float = 0.02,
    seed: int = 42,
) -> list[dict]:
    """Generate synthetic OHLCV data for testing."""
    rng = random.Random(seed)
    bars = []
    price = start
    for i in range(n):
        ret = rng.gauss(trend, volatility)
        open_ = price
        close = price * (1.0 + ret)
        high = max(open_, close) * (1.0 + abs(rng.gauss(0, 0.005)))
        low = min(open_, close) * (1.0 - abs(rng.gauss(0, 0.005)))
        vol = rng.uniform(1000, 10000)
        bars.append(
            {
                "timestamp": i,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": vol,
            }
        )
        price = close
    return bars


# Minimum data for tests (lookback=60, need at least 62+ bars with 1 bar lookahead)
MIN_BARS = 150


class TestOmegaBacktestBridgeBasic:
    def setup_method(self):
        self.ohlcv = _make_ohlcv(n=MIN_BARS)
        self.bridge = OmegaBacktestBridge(
            mode=BacktestMode.PICO,
            ticker="BTCUSDT",
            lookback_window=60,
        )

    def test_returns_backtest_result(self):
        result = self.bridge.run(self.ohlcv)
        assert isinstance(result, BacktestResult)

    def test_result_has_report(self):
        result = self.bridge.run(self.ohlcv)
        assert result.report is not None
        assert isinstance(result.report, EvalReport)

    def test_n_cycles_reasonable(self):
        result = self.bridge.run(self.ohlcv)
        # cycles = n - lookback - 1 (last bar used for fill)
        expected = MIN_BARS - 60 - 1
        assert result.n_cycles == expected

    def test_returns_length(self):
        result = self.bridge.run(self.ohlcv)
        assert len(result.returns) == result.n_cycles

    def test_baselines_present(self):
        result = self.bridge.run(self.ohlcv)
        assert "buy_and_hold" in result.baselines
        assert "sma_crossover" in result.baselines

    def test_mode_recorded(self):
        result = self.bridge.run(self.ohlcv)
        assert result.mode == BacktestMode.PICO.value

    def test_ticker_recorded(self):
        result = self.bridge.run(self.ohlcv)
        assert result.ticker == "BTCUSDT"

    def test_n_bars_recorded(self):
        result = self.bridge.run(self.ohlcv)
        assert result.n_bars == MIN_BARS

    def test_sharpe_finite(self):
        result = self.bridge.run(self.ohlcv)
        assert math.isfinite(result.report.sharpe)

    def test_max_drawdown_nonpositive(self):
        result = self.bridge.run(self.ohlcv)
        assert result.report.max_drawdown <= 0.0

    def test_too_few_bars_raises(self):
        bridge = OmegaBacktestBridge(lookback_window=60)
        with pytest.raises(ValueError, match="bars"):
            bridge.run(_make_ohlcv(n=50))


class TestWalkForwardSplit:
    def setup_method(self):
        self.ohlcv = _make_ohlcv(n=200)
        self.bridge = OmegaBacktestBridge(
            mode=BacktestMode.PICO,
            lookback_window=60,
        )

    def test_in_out_sample_returns_present(self):
        result = self.bridge.run(self.ohlcv)
        assert len(result.in_sample_returns) > 0
        assert len(result.out_of_sample_returns) > 0

    def test_in_plus_out_equals_total(self):
        result = self.bridge.run(self.ohlcv)
        total = len(result.in_sample_returns) + len(result.out_of_sample_returns)
        assert total == len(result.returns)

    def test_in_sample_sharpe_computed(self):
        result = self.bridge.run(self.ohlcv)
        from omega.eval.sharpe import compute_sharpe

        expected = compute_sharpe(result.in_sample_returns)
        assert abs(result.report.in_sample_sharpe - expected) < 1e-10

    def test_out_of_sample_sharpe_computed(self):
        result = self.bridge.run(self.ohlcv)
        from omega.eval.sharpe import compute_sharpe

        expected = compute_sharpe(result.out_of_sample_returns)
        assert abs(result.report.out_of_sample_sharpe - expected) < 1e-10

    def test_split_approximately_60_40(self):
        """In-sample should be ~60% of total returns."""
        result = self.bridge.run(self.ohlcv)
        n_total = len(result.returns)
        n_is = len(result.in_sample_returns)
        ratio = n_is / n_total
        # Allow ±10% slack due to lookback window alignment
        assert 0.40 <= ratio <= 0.80


class TestBaselineComparisons:
    def setup_method(self):
        self.ohlcv = _make_ohlcv(n=200, trend=0.001, seed=7)
        self.bridge = OmegaBacktestBridge(
            mode=BacktestMode.PICO,
            lookback_window=60,
        )

    def test_buy_and_hold_baseline_matches_standalone(self):
        """Baseline Sharpe from bridge matches standalone buy_and_hold call."""
        result = self.bridge.run(self.ohlcv)
        bridge_bnh = result.baselines["buy_and_hold"]
        closes = [float(b["close"]) for b in self.ohlcv][60:]
        standalone = buy_and_hold(closes)
        assert abs(bridge_bnh.sharpe - standalone.sharpe) < 1e-8

    def test_baselines_have_sharpe(self):
        result = self.bridge.run(self.ohlcv)
        for name, baseline in result.baselines.items():
            assert math.isfinite(baseline.sharpe), f"{name} has non-finite Sharpe"

    def test_baselines_have_max_drawdown(self):
        result = self.bridge.run(self.ohlcv)
        for name, baseline in result.baselines.items():
            assert baseline.max_drawdown <= 0.0, f"{name} drawdown > 0"


class TestModes:
    def test_pico_mode_runs(self):
        ohlcv = _make_ohlcv(n=MIN_BARS)
        bridge = OmegaBacktestBridge(mode=BacktestMode.PICO, lookback_window=60)
        result = bridge.run(ohlcv)
        assert result.mode == "pico"

    def test_supervised_mode_runs(self):
        ohlcv = _make_ohlcv(n=MIN_BARS)
        bridge = OmegaBacktestBridge(mode=BacktestMode.SUPERVISED, lookback_window=60)
        result = bridge.run(ohlcv)
        assert result.mode == "supervised"

    def test_autonomous_mode_runs(self):
        ohlcv = _make_ohlcv(n=MIN_BARS)
        bridge = OmegaBacktestBridge(mode=BacktestMode.AUTONOMOUS, lookback_window=60)
        result = bridge.run(ohlcv)
        assert result.mode == "autonomous"

    def test_pico_mode_report_name(self):
        ohlcv = _make_ohlcv(n=MIN_BARS)
        bridge = OmegaBacktestBridge(mode=BacktestMode.PICO, lookback_window=60)
        result = bridge.run(ohlcv)
        assert "pico" in result.report.strategy_name


class TestCycleRecords:
    def setup_method(self):
        self.ohlcv = _make_ohlcv(n=MIN_BARS)
        self.bridge = OmegaBacktestBridge(mode=BacktestMode.PICO, lookback_window=60)

    def test_cycles_match_n_cycles(self):
        result = self.bridge.run(self.ohlcv)
        assert len(result.cycles) == result.n_cycles

    def test_cycle_has_required_fields(self):
        result = self.bridge.run(self.ohlcv)
        cycle = result.cycles[0]
        assert hasattr(cycle, "bar_index")
        assert hasattr(cycle, "close_price")
        assert hasattr(cycle, "position")
        assert hasattr(cycle, "equity")
        assert hasattr(cycle, "autonomy_level")

    def test_cycle_equity_starts_near_initial(self):
        result = self.bridge.run(self.ohlcv)
        # First cycle equity should be near initial_capital (1.0 by default)
        assert 0.5 <= result.cycles[0].equity <= 2.0

    def test_cycle_position_in_range(self):
        result = self.bridge.run(self.ohlcv)
        for cycle in result.cycles:
            assert -1.0 <= cycle.position <= 1.0

    def test_cycle_close_prices_match_input(self):
        result = self.bridge.run(self.ohlcv)
        for cycle in result.cycles:
            bar = self.ohlcv[cycle.bar_index]
            assert abs(cycle.close_price - bar["close"]) < 1e-6


class TestEdgeCases:
    def test_flat_market(self):
        """Flat market → no signals, strategy stays flat."""
        ohlcv = [
            {
                "timestamp": i,
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1000.0,
            }
            for i in range(MIN_BARS)
        ]
        bridge = OmegaBacktestBridge(mode=BacktestMode.PICO, lookback_window=60)
        result = bridge.run(ohlcv)
        assert result is not None
        assert math.isfinite(result.report.total_return)

    def test_volatile_market(self):
        """High volatility market should not crash."""
        ohlcv = _make_ohlcv(n=MIN_BARS, volatility=0.10, seed=99)
        bridge = OmegaBacktestBridge(mode=BacktestMode.PICO, lookback_window=60)
        result = bridge.run(ohlcv)
        assert result is not None

    def test_custom_ticker(self):
        ohlcv = _make_ohlcv(n=MIN_BARS)
        bridge = OmegaBacktestBridge(
            mode=BacktestMode.PICO,
            ticker="ETHUSDT",
            lookback_window=60,
        )
        result = bridge.run(ohlcv)
        assert result.ticker == "ETHUSDT"

    def test_commission_reduces_returns(self):
        """Higher commission should reduce (or equal) total returns."""
        ohlcv = _make_ohlcv(n=MIN_BARS, trend=0.002, seed=13)
        bridge_no_cost = OmegaBacktestBridge(
            mode=BacktestMode.PICO, lookback_window=60, commission=0.0
        )
        bridge_with_cost = OmegaBacktestBridge(
            mode=BacktestMode.PICO, lookback_window=60, commission=0.01
        )
        result_nc = bridge_no_cost.run(ohlcv)
        result_wc = bridge_with_cost.run(ohlcv)
        # With commission, total return should be <= without commission
        assert result_wc.report.total_return <= result_nc.report.total_return + 0.01
