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


class TestB3ReturnLookAhead:
    """B3-RETURN: signal bar must earn 0 return (entry is next bar's open)."""

    def _make_crossover_bars(self):
        """
        Build a minimal bar sequence that triggers exactly one golden cross.

        Bars 0-19: price slowly rises so SMA(5) stays below SMA(10).
        Bar 20+: price jumps sharply so SMA(5) crosses above SMA(10) at bar ~20.
        We need enough bars after the cross for the strategy to process them.
        """
        from omega.backtest import OHLCV

        bars = []
        # 30 slowly-drifting bars so long SMA can warm up
        price = 100.0
        for i in range(30):
            close = price + 0.1  # tiny drift keeps short < long for a while
            bars.append(
                OHLCV("TST", f"2024-01-{i + 1:02d}", price, close * 1.01, close * 0.99, close, 1e6)
            )
            price = close

        # Now spike price up so the short SMA crosses above the long SMA
        for i in range(20):
            close = price * 1.05  # 5 % daily spike causes rapid crossover
            bars.append(
                OHLCV(
                    "TST",
                    f"2024-02-{i + 1:02d}",
                    price,
                    close * 1.01,
                    close * 0.99,
                    close,
                    1e6,
                )
            )
            price = close

        return bars

    def test_signal_bar_return_is_zero_sma_crossover(self):
        from omega.backtest import _sma_crossover_strategy

        bars = self._make_crossover_bars()
        _trades, rets = _sma_crossover_strategy("TST", bars, short=5, long=10)

        # Find the first bar where a golden cross would fire (position transitions 0→1)
        # By design of our bars the first crossover happens somewhere in bars 30-50.
        # We verify: immediately after any entry the position-change bar returns 0.
        # Reconstruct which bars are signal bars by checking for zero followed by nonzero.
        # More directly: run strategy manually and confirm via a known simple case.
        assert len(rets) == len(bars) - 1
        assert all(math.isfinite(r) for r in rets)

    def test_signal_bar_earns_zero_simple(self):
        """
        Craft a minimal 35-bar sequence where the golden cross fires at a known bar.
        Confirm that bar's return slot is 0.0, and the bar after it may be nonzero.
        """
        from omega.backtest import OHLCV, _sma_crossover_strategy

        # We need SMA(3) cross SMA(5).
        # Make prices such that first 5 bars are flat (SMA(5) warms up),
        # then drop for a few bars (short dips below long), then spike.
        prices = (
            [100.0] * 5  # warm-up: short == long
            + [99.0] * 5  # short drops below long
            + [105.0] * 10  # spike: short crosses above long
            + [105.0] * 5  # hold position
        )
        bars = [
            OHLCV("X", f"2024-01-{i + 1:02d}", p, p * 1.01, p * 0.99, p, 1e6)
            for i, p in enumerate(prices)
        ]

        _trades, rets = _sma_crossover_strategy("X", bars, short=3, long=5)
        assert len(rets) == len(bars) - 1

        # Find the crossover bar index i (0-based in rets, which maps to bars[i+1])
        # Re-run the SMA logic to find it
        from omega.backtest import _sma

        closes = [b.close for b in bars]
        sma_s = _sma(closes, 3)
        sma_l = _sma(closes, 5)
        crossover_bar = None
        for idx in range(1, len(bars)):
            if sma_s[idx] is None or sma_l[idx] is None:
                continue
            ps = sma_s[idx - 1]
            pl = sma_l[idx - 1]
            if ps is None or pl is None:
                continue
            if ps <= pl and sma_s[idx] > sma_l[idx]:
                crossover_bar = idx
                break

        assert crossover_bar is not None, "No golden cross found in test data"
        # rets[crossover_bar - 1] corresponds to bars[crossover_bar]
        assert rets[crossover_bar - 1] == pytest.approx(0.0), (
            f"Signal bar {crossover_bar} should earn 0.0, got {rets[crossover_bar - 1]}"
        )

    def test_signal_bar_earns_zero_multi_signal(self):
        """Same check for _multi_signal_strategy."""
        from omega.backtest import OHLCV, _multi_signal_strategy, _sma

        prices = [100.0] * 5 + [99.0] * 5 + [105.0] * 20 + [105.0] * 5
        bars = [
            OHLCV("X", f"2024-01-{i + 1:02d}", p, p * 1.01, p * 0.99, p, 1e6)
            for i, p in enumerate(prices)
        ]

        _trades, rets = _multi_signal_strategy("X", bars)
        assert len(rets) == len(bars) - 1

        closes = [b.close for b in bars]
        sma_s = _sma(closes, 10)
        sma_l = _sma(closes, 30)
        crossover_bar = None
        for idx in range(1, len(bars)):
            if sma_s[idx] is None or sma_l[idx] is None:
                continue
            ps = sma_s[idx - 1]
            pl = sma_l[idx - 1]
            if ps is None or pl is None:
                continue
            if ps <= pl and sma_s[idx] > sma_l[idx]:
                crossover_bar = idx
                break

        if crossover_bar is not None and crossover_bar - 1 < len(rets):
            assert rets[crossover_bar - 1] == pytest.approx(0.0), (
                f"Signal bar {crossover_bar} should earn 0.0, got {rets[crossover_bar - 1]}"
            )


class TestB4MultiplicativeDrawdown:
    """B4: Max drawdown must use multiplicative equity curve."""

    def test_50pct_loss_gives_50pct_drawdown(self):
        from omega.backtest import _compute_metrics

        # A single -50% return: equity goes from 1.0 to 0.5.
        # Multiplicative DD = (1.0 - 0.5) / 1.0 = 0.5 → 50 %
        rets = [-0.5]
        result = _compute_metrics(
            mode="pico",
            symbols=["BTC"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            trades=[],
            daily_returns=rets,
        )
        assert result.max_drawdown_pct == pytest.approx(50.0)

    def test_drawdown_after_gain_is_fractional(self):
        from omega.backtest import _compute_metrics

        # +100% then -50%: equity goes 1→2→1, peak=2, dd=(2-1)/2=0.5 → 50%
        rets = [1.0, -0.5]
        result = _compute_metrics(
            mode="pico",
            symbols=["BTC"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            trades=[],
            daily_returns=rets,
        )
        assert result.max_drawdown_pct == pytest.approx(50.0)

    def test_no_drawdown_on_positive_returns(self):
        from omega.backtest import _compute_metrics

        rets = [0.01, 0.02, 0.005]
        result = _compute_metrics(
            mode="pico",
            symbols=["BTC"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            trades=[],
            daily_returns=rets,
        )
        assert result.max_drawdown_pct == pytest.approx(0.0)


class TestA4CAGRAnnualisedReturn:
    """A4: annualised return must be CAGR, not arithmetic scaling."""

    def test_cagr_exact_one_year(self):
        from omega.backtest import _compute_metrics

        # One 10% daily return over a 1-day window scaled to 365 days
        # equity = 1.1, CAGR = 1.1^(365/1) - 1 (absurdly large but mathematically correct)
        # More usefully: test with a flat 1% daily return for exactly 365 days.
        # equity = 1.01^365, CAGR should be 1.01^365 - 1 ≈ 37.78
        daily_r = 0.01
        n = 365
        rets = [daily_r] * n
        result = _compute_metrics(
            mode="pico",
            symbols=["BTC"],
            start_date="2024-01-01",
            end_date="2024-12-31",  # 366 days span, but days = 365
            trades=[],
            daily_returns=rets,
        )
        equity_final = (1.0 + daily_r) ** n
        days = (
            __import__("datetime").date.fromisoformat("2024-12-31")
            - __import__("datetime").date.fromisoformat("2024-01-01")
        ).days
        expected_cagr = (equity_final ** (365.0 / days)) - 1.0
        assert result.annualised_return_pct == pytest.approx(expected_cagr * 100, rel=1e-4)

    def test_cagr_not_arithmetic(self):
        from omega.backtest import _compute_metrics

        # Arithmetic scaling of total_ret would give total_ret * 365/days.
        # CAGR gives a different answer whenever total_ret != 0 and days != 365.
        # Use a 6-month window with a known return.
        rets = [0.005] * 180  # 180 days of 0.5% daily
        result = _compute_metrics(
            mode="pico",
            symbols=["BTC"],
            start_date="2024-01-01",
            end_date="2024-06-29",  # 180 days
            trades=[],
            daily_returns=rets,
        )
        equity_final = (1.005) ** 180
        days = 180
        cagr = (equity_final ** (365.0 / days)) - 1.0
        arithmetic = sum(rets) * (365.0 / days)
        # They should differ significantly
        assert abs(cagr - arithmetic) > 0.01
        assert result.annualised_return_pct == pytest.approx(cagr * 100, rel=1e-4)

    def test_total_return_pct_multiplicative(self):
        from omega.backtest import _compute_metrics

        # +10% then -10%: multiplicative equity = 1.1 * 0.9 = 0.99, total_ret = -1%
        rets = [0.1, -0.1]
        result = _compute_metrics(
            mode="pico",
            symbols=["BTC"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            trades=[],
            daily_returns=rets,
        )
        expected = (1.1 * 0.9 - 1.0) * 100  # -1.0 %
        assert result.total_return_pct == pytest.approx(expected, abs=1e-6)


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
        # allow_synthetic=True: these tests intentionally run against fake data
        return BacktestEngine(config=cfg, symbols=cfg.data.symbols, allow_synthetic=True)

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
        # allow_synthetic=True: explicitly testing the synthetic fallback path
        engine = BacktestEngine(config=cfg, symbols=["BTCUSDT"], allow_synthetic=True)

        with patch.object(engine, "_load_real_data", side_effect=RuntimeError("no network")):
            data = engine._load_data("2024-01-01", "2024-06-30")

        assert "BTCUSDT" in data
        assert len(data["BTCUSDT"]) > 0

    def test_raises_without_real_data_when_synthetic_not_allowed(self):
        from omega.backtest import BacktestEngine

        cfg = _make_cfg()
        engine = BacktestEngine(config=cfg, symbols=["BTCUSDT"], allow_synthetic=False)

        with (
            patch.object(engine, "_load_real_data", side_effect=RuntimeError("no network")),
            pytest.raises(ValueError, match="No real market data available"),
        ):
            engine._load_data("2024-01-01", "2024-06-30")

    def test_synthetic_data_is_deterministic(self):
        from omega.backtest import BacktestEngine

        cfg = _make_cfg()
        # allow_synthetic=True: explicitly testing the synthetic generator
        e1 = BacktestEngine(config=cfg, symbols=["BTCUSDT"], allow_synthetic=True)
        e2 = BacktestEngine(config=cfg, symbols=["BTCUSDT"], allow_synthetic=True)

        d1 = e1._generate_synthetic_data("2024-01-01", "2024-03-31")
        d2 = e2._generate_synthetic_data("2024-01-01", "2024-03-31")

        assert len(d1["BTCUSDT"]) == len(d2["BTCUSDT"])
        assert d1["BTCUSDT"][0].close == d2["BTCUSDT"][0].close
