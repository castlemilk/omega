"""tests.test_backtest — BacktestEngine and helper function unit tests."""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cfg(symbols=None):
    cfg = MagicMock()
    cfg.data.symbols = symbols or ["BTCUSDT", "ETHUSDT"]
    cfg.data.providers = ["binance"]
    cfg.data.fetch_interval_days = 90
    cfg.database.state_db_path = ":memory:"
    return cfg


def _ohlcv_list(sym: str, n: int = 60, start_price: float = 100.0):
    """Generate a simple trending OHLCV list."""
    from omega.backtest import OHLCV

    bars = []
    price = start_price
    for i in range(n):
        close = price * (1.0 + 0.005 * (1 if i % 7 < 4 else -1))
        bars.append(
            OHLCV(
                symbol=sym,
                date=f"2024-{(i // 30) + 1:02d}-{(i % 28) + 1:02d}",
                open=price,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=1_000_000.0,
            )
        )
        price = close
    return bars


# ---------------------------------------------------------------------------
# Unit tests — helpers
# ---------------------------------------------------------------------------


class TestSMA:
    def test_returns_none_for_early_bars(self):
        from omega.backtest import _sma

        prices = list(range(1, 11))  # 1..10
        result = _sma(prices, window=5)
        assert result[0] is None
        assert result[3] is None
        assert result[4] is not None

    def test_correct_value(self):
        from omega.backtest import _sma

        prices = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _sma(prices, window=3)
        assert result[2] == pytest.approx(2.0)
        assert result[4] == pytest.approx(4.0)

    def test_single_window(self):
        from omega.backtest import _sma

        prices = [10.0, 20.0, 30.0]
        result = _sma(prices, window=1)
        assert result == prices


class TestRSI:
    def test_length_matches_input(self):
        from omega.backtest import _rsi

        prices = [float(i) for i in range(1, 31)]
        result = _rsi(prices, window=14)
        assert len(result) == len(prices)

    def test_rsi_bounds(self):
        from omega.backtest import _rsi

        prices = [100.0 * (1.03**i) for i in range(30)]  # always rising
        result = _rsi(prices, window=14)
        valid = [r for r in result if r is not None]
        assert all(0.0 <= v <= 100.0 for v in valid)

    def test_rsi_high_on_rising_prices(self):
        from omega.backtest import _rsi

        prices = [100.0 * (1.02**i) for i in range(30)]
        result = _rsi(prices, window=14)
        final = [r for r in result if r is not None][-1]
        assert final > 70.0  # strongly rising → overbought


class TestSMACrossover:
    def test_produces_trades_and_returns(self):
        from omega.backtest import _sma_crossover_strategy

        bars = _ohlcv_list("BTCUSDT", n=100)
        trades, rets = _sma_crossover_strategy("BTCUSDT", bars, short=5, long=20)
        assert isinstance(trades, list)
        assert isinstance(rets, list)
        assert len(rets) == len(bars) - 1

    def test_returns_finite_values(self):
        from omega.backtest import _sma_crossover_strategy

        bars = _ohlcv_list("ETHUSDT", n=80)
        _trades, rets = _sma_crossover_strategy("ETHUSDT", bars, short=5, long=20)
        assert all(math.isfinite(r) for r in rets)

    def test_no_trades_for_flat_data(self):
        from omega.backtest import OHLCV, _sma_crossover_strategy

        # Perfectly flat prices → no crossovers
        bars = [OHLCV("BTC", f"2024-01-{i + 1:02d}", 100, 100, 100, 100, 1000) for i in range(50)]
        trades, _ = _sma_crossover_strategy("BTC", bars, short=5, long=20)
        assert trades == []


class TestMultiSignalStrategy:
    def test_produces_trades_and_returns(self):
        from omega.backtest import _multi_signal_strategy

        bars = _ohlcv_list("SOLUSDT", n=120)
        _trades, rets = _multi_signal_strategy("SOLUSDT", bars)
        assert len(rets) == len(bars) - 1


class TestComputeMetrics:
    def test_basic_metrics(self):
        from omega.backtest import Trade, _compute_metrics

        rets = [0.01, -0.005, 0.008, 0.003, -0.002] * 10
        trades = [
            Trade("BTC", "2024-01-01", "long", 100.0, 110.0, 0.10),
            Trade("BTC", "2024-02-01", "long", 110.0, 105.0, -0.045),
        ]
        result = _compute_metrics(
            mode="pico",
            symbols=["BTC"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            trades=trades,
            daily_returns=rets,
        )
        assert result.mode == "pico"
        assert result.total_trades == 2
        assert result.win_rate == pytest.approx(0.5)
        assert isinstance(result.sharpe_ratio, float)
        assert result.max_drawdown_pct >= 0.0

    def test_no_trades(self):
        from omega.backtest import _compute_metrics

        result = _compute_metrics(
            mode="omega",
            symbols=[],
            start_date="2024-01-01",
            end_date="2024-12-31",
            trades=[],
            daily_returns=[],
        )
        assert result.win_rate == 0.0
        assert result.total_trades == 0

    def test_to_dict(self):
        from omega.backtest import _compute_metrics

        result = _compute_metrics(
            mode="pico",
            symbols=["BTC"],
            start_date="2024-01-01",
            end_date="2024-06-30",
            trades=[],
            daily_returns=[0.01] * 30,
        )
        d = result.to_dict()
        assert "total_return_pct" in d
        assert "sharpe_ratio" in d
        assert "max_drawdown_pct" in d
        assert "win_rate" in d


class TestCompare:
    def test_compare_returns_winner(self):
        from omega.backtest import BacktestResult, _compare

        pico = BacktestResult(
            mode="pico",
            symbols=["BTC"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            total_return_pct=5.0,
            annualised_return_pct=5.0,
            sharpe_ratio=0.8,
            max_drawdown_pct=10.0,
            win_rate=0.5,
            total_trades=10,
        )
        omega = BacktestResult(
            mode="omega",
            symbols=["BTC"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            total_return_pct=12.0,
            annualised_return_pct=12.0,
            sharpe_ratio=1.4,
            max_drawdown_pct=8.0,
            win_rate=0.6,
            total_trades=8,
        )
        cmp = _compare(pico, omega)
        assert cmp["winner"] == "omega"
        assert cmp["return_delta_pct"] == pytest.approx(7.0)
        assert cmp["sharpe_delta"] == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# BacktestEngine integration tests (synthetic data, no network)
# ---------------------------------------------------------------------------


class TestBacktestEngineSyntheticData:
    def _engine(self, symbols=None):
        from omega.backtest import BacktestEngine

        cfg = _make_cfg(symbols=symbols or ["BTCUSDT"])
        return BacktestEngine(config=cfg, symbols=cfg.data.symbols)

    def test_run_pico_only(self):
        engine = self._engine()
        report = engine.run("2024-01-01", "2024-12-31")
        assert "pico" in report
        assert "meta" in report
        assert report["meta"]["symbols"] == ["BTCUSDT"]

    def test_run_with_omega(self):
        engine = self._engine()
        report = engine.run("2024-01-01", "2024-12-31")
        assert "omega" in report

    def test_run_compare(self):
        engine = self._engine()
        report = engine.run("2024-01-01", "2024-12-31", compare_pico=True)
        assert "comparison" in report
        assert "winner" in report["comparison"]

    def test_run_pico_only_flag(self):
        engine = self._engine()
        report = engine.run("2024-01-01", "2024-06-30", pico_only=True)
        assert "pico" in report
        assert "omega" not in report

    def test_multiple_symbols(self):
        engine = self._engine(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        report = engine.run("2024-01-01", "2024-06-30")
        assert report["meta"]["symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    def test_fallback_to_synthetic_on_load_failure(self):
        from omega.backtest import BacktestEngine

        cfg = _make_cfg()
        engine = BacktestEngine(config=cfg, symbols=["BTCUSDT"])

        with patch.object(engine, "_load_real_data", side_effect=RuntimeError("no network")):
            data = engine._load_data("2024-01-01", "2024-06-30")

        assert "BTCUSDT" in data
        assert len(data["BTCUSDT"]) > 0

    def test_synthetic_data_is_deterministic(self):
        from omega.backtest import BacktestEngine

        cfg = _make_cfg()
        e1 = BacktestEngine(config=cfg, symbols=["BTCUSDT"])
        e2 = BacktestEngine(config=cfg, symbols=["BTCUSDT"])

        d1 = e1._generate_synthetic_data("2024-01-01", "2024-03-31")
        d2 = e2._generate_synthetic_data("2024-01-01", "2024-03-31")

        assert len(d1["BTCUSDT"]) == len(d2["BTCUSDT"])
        assert d1["BTCUSDT"][0].close == d2["BTCUSDT"][0].close
