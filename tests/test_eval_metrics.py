"""
Tests for omega.eval.metrics — comprehensive metric functions and EvalReport.
"""

import math

from omega.eval.metrics import (
    EvalReport,
    TradeRecord,
    build_equity_curve,
    build_eval_report,
    compute_annualised_return,
    compute_calmar_ratio,
    compute_max_drawdown,
    compute_profit_factor,
    compute_sortino_ratio,
    compute_win_rate,
)


class TestComputeMaxDrawdown:
    def test_monotone_increasing(self):
        """No drawdown in a steadily rising curve."""
        curve = [1.0, 1.1, 1.2, 1.3, 1.4]
        assert compute_max_drawdown(curve) == 0.0

    def test_monotone_decreasing(self):
        """Total return equals drawdown for monotone decline."""
        curve = [1.0, 0.9, 0.8, 0.7]
        expected = (0.7 - 1.0) / 1.0  # -0.3
        result = compute_max_drawdown(curve)
        assert abs(result - expected) < 1e-10

    def test_peak_then_recover(self):
        """Drawdown from peak, then recovery — finds peak correctly."""
        curve = [1.0, 1.5, 1.0, 1.5]
        # Peak = 1.5 at index 1, trough = 1.0 at index 2
        expected = (1.0 - 1.5) / 1.5
        result = compute_max_drawdown(curve)
        assert abs(result - expected) < 1e-10

    def test_multiple_drawdowns(self):
        """Returns the maximum (worst) drawdown."""
        # Small drawdown then large drawdown
        curve = [1.0, 1.2, 1.1, 1.4, 0.9]
        # Drawdown 1: (1.1 - 1.2) / 1.2 = -0.0833
        # Drawdown 2: (0.9 - 1.4) / 1.4 = -0.357
        result = compute_max_drawdown(curve)
        assert result < -0.30

    def test_single_element(self):
        """Single element → no drawdown."""
        assert compute_max_drawdown([1.0]) == 0.0

    def test_empty(self):
        assert compute_max_drawdown([]) == 0.0

    def test_returns_nonpositive(self):
        """Max drawdown is always <= 0."""
        import random

        rng = random.Random(42)
        curve = [1.0]
        for _ in range(100):
            curve.append(curve[-1] * (1 + rng.gauss(0, 0.02)))
        assert compute_max_drawdown(curve) <= 0.0

    def test_known_value(self):
        """50% drawdown from peak of 2.0 to trough of 1.0."""
        curve = [1.0, 2.0, 1.0]
        result = compute_max_drawdown(curve)
        assert abs(result - (-0.5)) < 1e-10


class TestComputeWinRate:
    def test_all_winners(self):
        trades = [TradeRecord(pnl=1.0) for _ in range(10)]
        assert compute_win_rate(trades) == 1.0

    def test_all_losers(self):
        trades = [TradeRecord(pnl=-1.0) for _ in range(10)]
        assert compute_win_rate(trades) == 0.0

    def test_half_and_half(self):
        trades = [TradeRecord(pnl=1.0)] * 5 + [TradeRecord(pnl=-1.0)] * 5
        assert compute_win_rate(trades) == 0.5

    def test_empty(self):
        assert compute_win_rate([]) == 0.0

    def test_zero_pnl_is_not_a_win(self):
        trades = [TradeRecord(pnl=0.0), TradeRecord(pnl=1.0)]
        assert compute_win_rate(trades) == 0.5


class TestComputeProfitFactor:
    def test_all_winners(self):
        trades = [TradeRecord(pnl=2.0) for _ in range(5)]
        result = compute_profit_factor(trades)
        assert result == float("inf")

    def test_all_losers(self):
        trades = [TradeRecord(pnl=-1.0) for _ in range(5)]
        assert compute_profit_factor(trades) == 0.0

    def test_equal_profit_loss(self):
        trades = [TradeRecord(pnl=1.0), TradeRecord(pnl=-1.0)]
        assert compute_profit_factor(trades) == 1.0

    def test_known_value(self):
        trades = [
            TradeRecord(pnl=3.0),
            TradeRecord(pnl=-1.0),
            TradeRecord(pnl=2.0),
            TradeRecord(pnl=-1.0),
        ]
        # gross_profit = 5, gross_loss = 2 → PF = 2.5
        assert compute_profit_factor(trades) == 2.5

    def test_empty(self):
        assert compute_profit_factor([]) == 0.0

    def test_zero_pnl_excluded(self):
        trades = [TradeRecord(pnl=2.0), TradeRecord(pnl=0.0), TradeRecord(pnl=-1.0)]
        assert compute_profit_factor(trades) == 2.0


class TestComputeCalmarRatio:
    def test_known_value(self):
        """Calmar = CAGR annualised_return / |max_drawdown|."""
        returns = [0.001] * 252  # 0.1% per day
        max_dd = -0.10  # 10% drawdown
        # CAGR: (1.001^252) - 1
        ann_return = compute_annualised_return(returns, 252)
        expected = ann_return / 0.10
        result = compute_calmar_ratio(returns, max_dd)
        assert abs(result - expected) < 1e-6

    def test_zero_drawdown(self):
        """Zero drawdown → calmar = 0 (avoid division by zero)."""
        returns = [0.01] * 100
        assert compute_calmar_ratio(returns, 0.0) == 0.0

    def test_positive_drawdown_returns_zero(self):
        """max_dd >= 0 (invalid input) → returns 0."""
        returns = [0.01] * 100
        assert compute_calmar_ratio(returns, 0.05) == 0.0

    def test_empty_returns(self):
        assert compute_calmar_ratio([], -0.1) == 0.0

    def test_negative_returns(self):
        """Negative compound returns → negative Calmar."""
        returns = [-0.001] * 100
        result = compute_calmar_ratio(returns, -0.1)
        assert result < 0.0


class TestComputeSortinoRatio:
    def test_no_downside(self):
        """All returns above target → infinite Sortino."""
        returns = [0.01] * 100
        result = compute_sortino_ratio(returns, target=0.0)
        assert result == float("inf")

    def test_known_value(self):
        """Verify Sortino against manual calculation."""
        returns = [0.02, -0.01, 0.03, -0.02, 0.01]
        target = 0.0
        n = len(returns)
        mean = sum(returns) / n
        downside = [min(0.0, r - target) for r in returns]
        # Sample variance of full series for downside
        ds_var = sum(d**2 for d in downside) / (n - 1)
        ds_std = math.sqrt(ds_var)
        expected = (mean - target) / ds_std * math.sqrt(252)
        result = compute_sortino_ratio(returns, target=target)
        assert abs(result - expected) < 1e-10

    def test_target_adjustment(self):
        """Higher target → lower Sortino (more bars below target)."""
        returns = [0.01, 0.02, -0.01, 0.03, -0.02] * 10
        s_low = compute_sortino_ratio(returns, target=0.0)
        s_high = compute_sortino_ratio(returns, target=0.015)
        assert s_low > s_high

    def test_short_returns(self):
        assert compute_sortino_ratio([0.01]) == 0.0
        assert compute_sortino_ratio([]) == 0.0

    def test_all_negative(self):
        returns = [-0.01] * 50
        result = compute_sortino_ratio(returns)
        assert result < 0.0


class TestBuildEquityCurve:
    def test_starting_value(self):
        curve = build_equity_curve([0.1, 0.2])
        assert curve[0] == 1.0

    def test_length(self):
        returns = [0.01] * 10
        curve = build_equity_curve(returns)
        assert len(curve) == 11  # initial + 10 returns

    def test_compounding(self):
        returns = [0.10, 0.10]  # two 10% gains
        curve = build_equity_curve(returns)
        assert abs(curve[-1] - 1.21) < 1e-10

    def test_custom_initial(self):
        curve = build_equity_curve([0.10], initial=100.0)
        assert abs(curve[-1] - 110.0) < 1e-10

    def test_zero_returns(self):
        curve = build_equity_curve([0.0] * 5)
        assert all(v == 1.0 for v in curve)


class TestBuildEvalReport:
    def _make_returns(self, n: int = 200) -> list[float]:
        import random

        rng = random.Random(42)
        return [rng.gauss(0.001, 0.02) for _ in range(n)]

    def test_returns_eval_report(self):
        r = self._make_returns()
        report = build_eval_report("test", "pico", r)
        assert isinstance(report, EvalReport)

    def test_strategy_name(self):
        r = self._make_returns()
        report = build_eval_report("my_strategy", "pico", r)
        assert report.strategy_name == "my_strategy"

    def test_sharpe_consistent(self):
        from omega.eval.sharpe import compute_sharpe

        r = self._make_returns()
        report = build_eval_report("test", "pico", r)
        expected = compute_sharpe(r)
        assert abs(report.sharpe - expected) < 1e-10

    def test_max_drawdown_nonpositive(self):
        r = self._make_returns()
        report = build_eval_report("test", "pico", r)
        assert report.max_drawdown <= 0.0

    def test_total_return(self):
        """Total return matches equity curve."""
        r = [0.01] * 10
        report = build_eval_report("test", "pico", r)
        # (1.01)^10 - 1
        expected = 1.01**10 - 1
        assert abs(report.total_return - expected) < 1e-6

    def test_walk_forward_sharpes(self):
        r = self._make_returns(200)
        is_r = r[:120]
        oos_r = r[120:]
        from omega.eval.sharpe import compute_sharpe

        report = build_eval_report(
            "test",
            "pico",
            r,
            in_sample_returns=is_r,
            out_of_sample_returns=oos_r,
        )
        assert abs(report.in_sample_sharpe - compute_sharpe(is_r)) < 1e-10
        assert abs(report.out_of_sample_sharpe - compute_sharpe(oos_r)) < 1e-10

    def test_empty_trades(self):
        r = self._make_returns()
        report = build_eval_report("test", "pico", r, trades=[])
        assert report.n_trades == 0
        assert report.win_rate == 0.0

    def test_trades_metrics(self):
        r = self._make_returns()
        trades = [
            TradeRecord(pnl=0.05),
            TradeRecord(pnl=-0.02),
            TradeRecord(pnl=0.03),
        ]
        report = build_eval_report("test", "pico", r, trades=trades)
        assert report.n_trades == 3
        assert abs(report.win_rate - 2 / 3) < 1e-10

    def test_summary_keys(self):
        r = self._make_returns()
        report = build_eval_report("test", "pico", r)
        summary = report.summary()
        for key in (
            "sharpe",
            "sortino",
            "calmar",
            "max_drawdown",
            "total_return",
            "win_rate",
            "profit_factor",
            "n_trades",
        ):
            assert key in summary

    def test_information_ratio_with_benchmark(self):
        import random

        rng = random.Random(1)
        r = [rng.gauss(0.001, 0.02) for _ in range(100)]
        bm = [rng.gauss(0.0008, 0.018) for _ in range(100)]
        report = build_eval_report("test", "pico", r, benchmark_returns=bm)
        assert math.isfinite(report.information_ratio)


class TestCAGRAnnualisedReturn:
    def test_constant_positive_returns(self):
        """For constant 1% daily returns over 252 days, CAGR ≈ 1.01^252 - 1."""
        returns = [0.01] * 252
        result = compute_annualised_return(returns, 252)
        expected = 1.01**252 - 1  # ≈ 12.1687, NOT 2.52
        assert abs(result - expected) < 1e-6
        # Confirm it is NOT the arithmetic mean result
        arithmetic_mean_result = 0.01 * 252  # 2.52
        assert abs(result - arithmetic_mean_result) > 1.0

    def test_zero_returns(self):
        """All-zero returns → 0.0 (equity stays at 1.0)."""
        assert compute_annualised_return([0.0] * 100, 252) == 0.0

    def test_empty_returns(self):
        """Empty sequence → 0.0."""
        assert compute_annualised_return([], 252) == 0.0

    def test_cagr_less_than_arithmetic_mean_for_volatile_returns(self):
        """For alternating +10%/-10% returns, CAGR < arithmetic mean."""
        # Alternating +10% / -10%: arithmetic mean is 0, but compounding loses value
        returns = [0.10, -0.10] * 50  # 100 periods
        cagr = compute_annualised_return(returns, 252)
        arithmetic_mean = sum(returns) / len(returns) * 252  # 0.0
        # CAGR must be strictly less than arithmetic mean (volatility drag)
        assert cagr < arithmetic_mean

    def test_cagr_vs_arithmetic_for_known_volatile_series(self):
        """Verify exact CAGR value for a simple alternating series."""
        # One up +10%, one down -10%: equity goes 1.0 -> 1.1 -> 0.99
        returns = [0.10, -0.10]
        result = compute_annualised_return(returns, 252)
        # equity[-1] = 0.99, n=2
        expected = 0.99 ** (252 / 2) - 1.0
        assert abs(result - expected) < 1e-10

    def test_calmar_uses_cagr(self):
        """compute_calmar_ratio result differs from old arithmetic formula for volatile series."""
        returns = [0.10, -0.10] * 50  # 100 periods alternating
        max_dd = compute_max_drawdown(build_equity_curve(returns))

        cagr_calmar = compute_calmar_ratio(returns, max_dd, 252)

        # Old arithmetic formula: ann_return = mean(returns) * 252 = 0.0 → calmar = 0
        arithmetic_ann_return = sum(returns) / len(returns) * 252  # 0.0
        # CAGR-based calmar is negative (compounding drag), arithmetic was 0
        assert cagr_calmar != arithmetic_ann_return / abs(max_dd)
        # CAGR for this series is negative (compounding loss), so calmar is also negative
        assert cagr_calmar < 0.0
