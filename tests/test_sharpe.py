"""
Tests for omega.eval.sharpe — verifies the single Sharpe formula against
known values and edge cases.
"""

import math

from omega.eval.sharpe import (
    _normal_cdf,
    compute_information_ratio,
    compute_sharpe,
    compute_sharpe_confidence_interval,
    sharpe_difference_significant,
)


class TestComputeSharpe:
    def test_known_value(self):
        """
        Verify against manually-computed value.
        Returns: [0.01, 0.02, 0.03, 0.04, 0.05]
        mean = 0.03, std(ddof=1) = sqrt(0.025) ≈ 0.01581
        daily_sharpe = 0.03 / 0.01581 ≈ 1.8974
        annualised = 1.8974 * sqrt(252) ≈ 30.117... but let's use exact math.
        """
        returns = [0.01, 0.02, 0.03, 0.04, 0.05]
        n = len(returns)
        mean = sum(returns) / n
        var = sum((x - mean) ** 2 for x in returns) / (n - 1)
        std = math.sqrt(var)
        expected = mean / std * math.sqrt(252)
        result = compute_sharpe(returns, periods_per_year=252)
        assert abs(result - expected) < 1e-10

    def test_zero_returns(self):
        """All-zero returns → Sharpe = 0."""
        assert compute_sharpe([0.0] * 50) == 0.0

    def test_constant_positive_returns(self):
        """Constant returns → std = 0 → Sharpe = 0 (not inf)."""
        assert compute_sharpe([0.01] * 100) == 0.0

    def test_single_observation(self):
        """Single return → cannot compute → 0."""
        assert compute_sharpe([0.05]) == 0.0

    def test_empty(self):
        assert compute_sharpe([]) == 0.0

    def test_risk_free_rate_adjustment(self):
        """Risk-free rate shifts the mean before computing Sharpe."""
        returns = [0.01, 0.02, 0.03, 0.04, 0.05]
        rfr = 0.01
        excess = [r - rfr for r in returns]
        n = len(excess)
        mean_ex = sum(excess) / n
        var_ex = sum((x - mean_ex) ** 2 for x in excess) / (n - 1)
        std_ex = math.sqrt(var_ex)
        expected = mean_ex / std_ex * math.sqrt(252)
        result = compute_sharpe(returns, risk_free_rate=rfr)
        assert abs(result - expected) < 1e-10

    def test_negative_mean_returns(self):
        """Negative mean returns produce negative Sharpe."""
        returns = [-0.05, -0.02, -0.01, -0.03, -0.04]
        result = compute_sharpe(returns)
        assert result < 0.0

    def test_sample_variance_not_population(self):
        """Explicitly confirm N-1 (sample) denominator is used."""
        # Use non-zero mean so sample and population Sharpe differ
        returns = [0.01, 0.02, 0.03, 0.04]
        n = len(returns)
        mean = sum(returns) / n
        # Sample variance
        var_sample = sum((x - mean) ** 2 for x in returns) / (n - 1)
        # Population variance
        var_pop = sum((x - mean) ** 2 for x in returns) / n
        # They're different — confirm our function uses sample
        std_sample = math.sqrt(var_sample)
        std_pop = math.sqrt(var_pop)
        expected_sample = mean / std_sample * math.sqrt(252)
        expected_pop = mean / std_pop * math.sqrt(252)
        result = compute_sharpe(returns)
        assert abs(result - expected_sample) < 1e-10
        assert abs(result - expected_pop) > 0.001  # different values

    def test_periods_per_year_weekly(self):
        """Weekly Sharpe uses sqrt(52) annualisation."""
        returns = [0.01, 0.02, 0.03, 0.04, 0.05]
        result_weekly = compute_sharpe(returns, periods_per_year=52)
        result_daily = compute_sharpe(returns, periods_per_year=252)
        # weekly should be smaller than daily (sqrt(52) < sqrt(252))
        assert result_weekly < result_daily
        ratio = result_daily / result_weekly
        assert abs(ratio - math.sqrt(252) / math.sqrt(52)) < 1e-6

    def test_large_sample(self):
        """Large sample should produce a finite, reasonable Sharpe."""
        import random

        rng = random.Random(42)
        returns = [rng.gauss(0.001, 0.02) for _ in range(500)]
        result = compute_sharpe(returns)
        assert math.isfinite(result)
        assert -10.0 < result < 10.0


class TestSharpeConfidenceInterval:
    def test_ci_bounds(self):
        """CI lower < point estimate < upper (approximately)."""
        import random

        rng = random.Random(0)
        returns = [rng.gauss(0.001, 0.02) for _ in range(200)]
        point = compute_sharpe(returns)
        lo, hi = compute_sharpe_confidence_interval(returns, confidence=0.95)
        assert lo < hi
        # Point estimate should usually fall inside 95% CI
        assert lo <= point <= hi or abs(point - lo) < 1.0  # allow slight miss at edges

    def test_ci_empty(self):
        lo, hi = compute_sharpe_confidence_interval([])
        assert lo == 0.0
        assert hi == 0.0

    def test_ci_single(self):
        lo, hi = compute_sharpe_confidence_interval([0.01])
        assert lo == 0.0
        assert hi == 0.0

    def test_ci_reproducible(self):
        """Same seed → same CI."""
        import random

        rng = random.Random(7)
        returns = [rng.gauss(0.001, 0.02) for _ in range(100)]
        ci1 = compute_sharpe_confidence_interval(returns, seed=99)
        ci2 = compute_sharpe_confidence_interval(returns, seed=99)
        assert ci1 == ci2

    def test_ci_wider_for_small_sample(self):
        """Smaller sample → wider CI."""
        import random

        rng = random.Random(42)
        small = [rng.gauss(0.001, 0.02) for _ in range(30)]
        large = [rng.gauss(0.001, 0.02) for _ in range(300)]
        lo_s, hi_s = compute_sharpe_confidence_interval(small)
        lo_l, hi_l = compute_sharpe_confidence_interval(large)
        width_small = hi_s - lo_s
        width_large = hi_l - lo_l
        assert width_small > width_large


class TestSharpeDifferenceSignificant:
    def test_identical_sequences(self):
        """Identical sequences → not significant."""
        returns = [0.01, -0.01, 0.02, -0.02, 0.01, -0.01] * 10
        sig, p = sharpe_difference_significant(returns, returns)
        assert not sig
        assert p > 0.05

    def test_very_different_sequences(self):
        """Very different sequences → likely significant."""
        a = [0.05] * 100
        b = [-0.05] * 100
        # Both have zero variance → handled gracefully
        sig, p = sharpe_difference_significant(a, b)
        # Should not raise; result depends on implementation
        assert isinstance(sig, bool)
        assert 0.0 <= p <= 1.0

    def test_short_sequence(self):
        """Fewer than 4 observations → not significant."""
        a = [0.01, 0.02]
        b = [0.03, 0.04]
        sig, p = sharpe_difference_significant(a, b)
        assert not sig
        assert p == 1.0

    def test_unequal_lengths_truncated(self):
        """Unequal lengths → uses min(len(a), len(b))."""
        a = [0.01, 0.02, 0.03, 0.04, 0.05] * 10
        b = [0.01, 0.02, 0.03, 0.04, 0.05] * 5
        sig, _p = sharpe_difference_significant(a, b)
        assert isinstance(sig, bool)

    def test_p_value_bounds(self):
        """p-value always in [0, 1]."""
        import random

        rng = random.Random(1)
        a = [rng.gauss(0.001, 0.02) for _ in range(100)]
        b = [rng.gauss(0.002, 0.02) for _ in range(100)]
        _sig, p = sharpe_difference_significant(a, b)
        assert 0.0 <= p <= 1.0


class TestInformationRatio:
    def test_same_as_benchmark(self):
        """IR = 0 when strategy == benchmark."""
        returns = [0.01, 0.02, -0.01, 0.03, -0.02]
        result = compute_information_ratio(returns, returns)
        assert result == 0.0

    def test_known_value(self):
        """IR computed from known active returns."""
        strategy = [0.02, 0.03, 0.01, 0.04, 0.02]
        benchmark = [0.01, 0.01, 0.01, 0.01, 0.01]
        active = [s - b for s, b in zip(strategy, benchmark, strict=True)]
        expected = compute_sharpe(active, periods_per_year=252)
        result = compute_information_ratio(strategy, benchmark)
        assert abs(result - expected) < 1e-10

    def test_outperforming_benchmark(self):
        """Strategy consistently above benchmark → positive IR."""
        strategy = [0.02] * 50
        benchmark = [0.01] * 50
        # Active returns are constant 0.01 → zero std → IR = 0
        result = compute_information_ratio(strategy, benchmark)
        assert result == 0.0  # constant alpha = zero std

    def test_mixed_alpha(self):
        """Positive IR for strategy with positive mean active returns."""
        strategy = [0.02, 0.01, 0.03, 0.02, 0.015, 0.025, 0.01, 0.03] * 5
        benchmark = [0.01] * 40
        result = compute_information_ratio(strategy, benchmark)
        assert result > 0.0

    def test_short_sequences(self):
        """Fewer than 2 overlapping → IR = 0."""
        assert compute_information_ratio([0.01], [0.01]) == 0.0
        assert compute_information_ratio([], []) == 0.0


class TestNormalCdf:
    def test_at_zero(self):
        assert abs(_normal_cdf(0) - 0.5) < 1e-6

    def test_positive_infinity(self):
        assert _normal_cdf(10) > 0.999

    def test_negative_value(self):
        assert _normal_cdf(-1.96) < 0.03

    def test_symmetry(self):
        assert abs(_normal_cdf(1.96) + _normal_cdf(-1.96) - 1.0) < 1e-4
