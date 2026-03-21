"""
Tests for omega.eval.baselines — verifies baseline strategy implementations.
"""

from omega.eval.baselines import BaselineResult, buy_and_hold, random_strategy, sma_crossover
from omega.eval.sharpe import compute_sharpe


def _linear_prices(start: float = 100.0, end: float = 200.0, n: int = 100) -> list[float]:
    """Linearly increasing prices from start to end."""
    return [start + (end - start) * i / (n - 1) for i in range(n)]


def _flat_prices(price: float = 100.0, n: int = 100) -> list[float]:
    return [price] * n


def _declining_prices(start: float = 200.0, end: float = 100.0, n: int = 100) -> list[float]:
    return [start + (end - start) * i / (n - 1) for i in range(n)]


class TestBuyAndHold:
    def test_returns_baseline_result(self):
        prices = _linear_prices(n=50)
        result = buy_and_hold(prices)
        assert isinstance(result, BaselineResult)
        assert result.name == "buy_and_hold"

    def test_single_trade(self):
        """Buy-and-hold has exactly one trade."""
        prices = _linear_prices(n=50)
        result = buy_and_hold(prices)
        assert result.n_trades == 1
        assert len(result.trades) == 1

    def test_total_return_correct(self):
        """Total return matches price appreciation."""
        prices = [100.0, 110.0, 120.0, 130.0, 140.0]
        result = buy_and_hold(prices)
        expected_return = (140.0 - 100.0) / 100.0  # 40%
        assert abs(result.total_return - expected_return) < 1e-6

    def test_returns_length(self):
        """Returns series has length n-1 (one per bar transition)."""
        prices = _linear_prices(n=50)
        result = buy_and_hold(prices)
        assert len(result.returns) == 49

    def test_equity_curve_length(self):
        prices = _linear_prices(n=50)
        result = buy_and_hold(prices)
        assert len(result.equity_curve) == 50  # initial + one per return

    def test_declining_market(self):
        """Declining prices → negative total return."""
        prices = _declining_prices(n=50)
        result = buy_and_hold(prices)
        assert result.total_return < 0.0
        assert result.win_rate == 0.0

    def test_flat_market(self):
        """Flat prices → zero total return, zero sharpe."""
        prices = _flat_prices(n=50)
        result = buy_and_hold(prices)
        assert abs(result.total_return) < 1e-6
        assert result.sharpe == 0.0  # zero std

    def test_too_few_prices(self):
        """Single price → graceful empty result."""
        result = buy_and_hold([100.0])
        assert result.returns == []
        assert result.n_trades == 0

    def test_sharpe_matches_compute_sharpe(self):
        """Sharpe in result matches standalone compute_sharpe on same returns."""
        prices = _linear_prices(n=100)
        result = buy_and_hold(prices)
        expected = compute_sharpe(result.returns)
        assert abs(result.sharpe - expected) < 1e-10

    def test_positive_market_win_rate(self):
        prices = _linear_prices(start=100.0, end=200.0, n=50)
        result = buy_and_hold(prices)
        assert result.win_rate == 1.0

    def test_summary_keys(self):
        prices = _linear_prices(n=50)
        result = buy_and_hold(prices)
        summary = result.summary()
        for key in ("sharpe", "max_drawdown", "total_return", "win_rate", "n_trades"):
            assert key in summary


class TestSmaKrossover:
    def test_returns_baseline_result(self):
        prices = _linear_prices(n=100)
        result = sma_crossover(prices)
        assert isinstance(result, BaselineResult)
        assert "sma_crossover" in result.name

    def test_not_enough_data(self):
        """Fewer bars than slow window → empty result."""
        result = sma_crossover([100.0] * 10, fast=5, slow=20)
        assert result.returns == []
        assert result.n_trades == 0

    def test_trending_market_long_bias(self):
        """Linearly rising market → should be mostly long → positive return."""
        prices = _linear_prices(start=100.0, end=200.0, n=200)
        result = sma_crossover(prices, fast=10, slow=30)
        # In a clean uptrend, SMA crossover should capture most of the upside
        assert result.total_return > 0.0

    def test_declining_market_flat_bias(self):
        """Declining market (no shorting) → strategy should be mostly flat → less loss."""
        prices = _declining_prices(start=200.0, end=100.0, n=200)
        result_sma = sma_crossover(prices, fast=10, slow=30)
        result_bnh = buy_and_hold(prices)
        # SMA should lose less than buy-and-hold in declining market
        assert result_sma.total_return > result_bnh.total_return

    def test_returns_length(self):
        prices = _linear_prices(n=100)
        result = sma_crossover(prices, fast=5, slow=20)
        # Should have n-1 returns (one per bar from bar 1 onwards)
        assert len(result.returns) == 99

    def test_sharpe_matches_returns(self):
        prices = _linear_prices(n=100)
        result = sma_crossover(prices, fast=5, slow=20)
        expected = compute_sharpe(result.returns)
        assert abs(result.sharpe - expected) < 1e-10

    def test_flat_market_no_trades(self):
        """Flat market: fast SMA == slow SMA always → 0 or minimal trades."""
        prices = _flat_prices(n=100)
        result = sma_crossover(prices, fast=10, slow=30)
        # Flat market: crossover never triggers
        assert result.total_return == 0.0  # always flat or trivially so

    def test_custom_fast_slow(self):
        prices = _linear_prices(n=200)
        result_default = sma_crossover(prices)
        result_custom = sma_crossover(prices, fast=5, slow=50)
        # Different params → different result
        assert result_default.name != result_custom.name


class TestRandomStrategy:
    def test_returns_baseline_result(self):
        prices = _linear_prices(n=100)
        result = random_strategy(prices)
        assert isinstance(result, BaselineResult)
        assert result.name == "random_strategy"

    def test_reproducible_with_seed(self):
        prices = _linear_prices(n=100)
        r1 = random_strategy(prices, seed=42)
        r2 = random_strategy(prices, seed=42)
        assert r1.returns == r2.returns
        assert r1.total_return == r2.total_return

    def test_different_seeds_different_results(self):
        prices = _linear_prices(n=100)
        r1 = random_strategy(prices, seed=42)
        r2 = random_strategy(prices, seed=99)
        # Very unlikely to be identical
        assert r1.returns != r2.returns

    def test_returns_length(self):
        prices = _linear_prices(n=100)
        result = random_strategy(prices)
        assert len(result.returns) == 99

    def test_too_few_prices(self):
        result = random_strategy([100.0])
        assert result.returns == []

    def test_sharpe_matches_returns(self):
        prices = _linear_prices(n=100)
        result = random_strategy(prices)
        expected = compute_sharpe(result.returns)
        assert abs(result.sharpe - expected) < 1e-10

    def test_equity_curve_starts_at_one(self):
        prices = _linear_prices(n=100)
        result = random_strategy(prices)
        assert result.equity_curve[0] == 1.0

    def test_finite_results(self):
        """Random strategy should produce finite numeric results."""
        import math

        prices = _linear_prices(start=10.0, end=100.0, n=200)
        result = random_strategy(prices)
        assert math.isfinite(result.total_return)
        assert math.isfinite(result.sharpe)
        assert math.isfinite(result.max_drawdown)


class TestBaselineComparisons:
    def test_baselines_have_common_interface(self):
        """All baselines return BaselineResult with same summary keys."""
        prices = _linear_prices(n=100)
        for fn in (buy_and_hold, sma_crossover, random_strategy):
            result = fn(prices)
            summary = result.summary()
            for key in ("sharpe", "max_drawdown", "total_return", "win_rate", "n_trades"):
                assert key in summary, f"{fn.__name__} missing {key}"

    def test_max_drawdown_nonpositive(self):
        """Max drawdown is always <= 0."""
        prices = _linear_prices(n=100)
        for fn in (buy_and_hold, sma_crossover, random_strategy):
            result = fn(prices)
            assert result.max_drawdown <= 0.0

    def test_win_rate_in_range(self):
        prices = _linear_prices(n=100)
        for fn in (buy_and_hold, sma_crossover, random_strategy):
            result = fn(prices)
            assert 0.0 <= result.win_rate <= 1.0
