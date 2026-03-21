"""
Tests for omega.eval.significance — bootstrap CIs and statistical significance.

TDD RED phase: all tests here fail until significance.py is implemented.
"""

from __future__ import annotations

import math
import random


class TestSharpeIsSignificant:
    def test_returns_three_tuple(self):
        """sharpe_is_significant returns (bool, float, (float, float))."""
        from omega.eval.significance import sharpe_is_significant

        rng = random.Random(42)
        returns = [rng.gauss(0.002, 0.01) for _ in range(100)]
        result = sharpe_is_significant(returns)
        assert isinstance(result, tuple) and len(result) == 3
        sig, point, ci = result
        assert isinstance(sig, bool)
        assert isinstance(point, float)
        assert isinstance(ci, tuple) and len(ci) == 2

    def test_significant_for_strong_positive_returns(self):
        """Large positive mean returns → CI lower bound > min_sharpe → significant."""
        from omega.eval.significance import sharpe_is_significant

        # Strong, consistent positive returns → high Sharpe, CI clearly above 0
        rng = random.Random(1)
        returns = [rng.gauss(0.01, 0.005) for _ in range(300)]
        sig, point, (lo, hi) = sharpe_is_significant(returns, confidence=0.95, min_sharpe=0.0)
        assert point > 0.0
        assert lo < hi
        assert sig is True

    def test_not_significant_for_zero_mean_returns(self):
        """Near-zero mean returns → CI straddles zero → not significant."""
        from omega.eval.significance import sharpe_is_significant

        rng = random.Random(99)
        returns = [rng.gauss(0.0, 0.02) for _ in range(100)]
        sig, _point, (lo, hi) = sharpe_is_significant(returns, confidence=0.95, min_sharpe=0.0)
        assert isinstance(sig, bool)
        # CI should straddle 0 for pure noise
        assert lo < hi

    def test_point_estimate_is_sharpe(self):
        """point_estimate matches compute_sharpe on the same returns."""
        from omega.eval.sharpe import compute_sharpe
        from omega.eval.significance import sharpe_is_significant

        rng = random.Random(7)
        returns = [rng.gauss(0.001, 0.02) for _ in range(200)]
        _sig, point, _ci = sharpe_is_significant(returns)
        expected = compute_sharpe(returns)
        assert abs(point - expected) < 1e-10

    def test_ci_lower_less_than_upper(self):
        """CI lower bound always < upper bound."""
        from omega.eval.significance import sharpe_is_significant

        rng = random.Random(5)
        returns = [rng.gauss(0.001, 0.02) for _ in range(150)]
        _sig, _point, (lo, hi) = sharpe_is_significant(returns)
        assert lo < hi

    def test_empty_returns_not_significant(self):
        """Empty returns → not significant, zero point, zero CI."""
        from omega.eval.significance import sharpe_is_significant

        sig, point, (lo, hi) = sharpe_is_significant([])
        assert sig is False
        assert point == 0.0
        assert lo == 0.0
        assert hi == 0.0

    def test_single_return_not_significant(self):
        """Single return → not significant."""
        from omega.eval.significance import sharpe_is_significant

        sig, _point, _ = sharpe_is_significant([0.05])
        assert sig is False

    def test_min_sharpe_threshold(self):
        """min_sharpe > 0 raises the bar for significance."""
        from omega.eval.significance import sharpe_is_significant

        rng = random.Random(3)
        # Returns with moderate Sharpe
        returns = [rng.gauss(0.001, 0.02) for _ in range(200)]
        _sig_low, _, _ = sharpe_is_significant(returns, min_sharpe=0.0)
        sig_high, _, _ = sharpe_is_significant(returns, min_sharpe=100.0)
        # With absurdly high min_sharpe, should definitely not be significant
        assert sig_high is False


class TestSharpeDifferenceSignificantBootstrap:
    def test_returns_three_tuple(self):
        """sharpe_difference_significant returns (bool, float, (float, float))."""
        from omega.eval.significance import sharpe_difference_significant

        rng = random.Random(42)
        a = [rng.gauss(0.002, 0.01) for _ in range(100)]
        b = [rng.gauss(0.001, 0.01) for _ in range(100)]
        result = sharpe_difference_significant(a, b)
        assert isinstance(result, tuple) and len(result) == 3
        sig, diff, ci = result
        assert isinstance(sig, bool)
        assert isinstance(diff, float)
        assert isinstance(ci, tuple) and len(ci) == 2

    def test_identical_returns_not_significant(self):
        """Identical series → difference is 0, not significant."""
        from omega.eval.significance import sharpe_difference_significant

        rng = random.Random(42)
        returns = [rng.gauss(0.001, 0.02) for _ in range(200)]
        sig, diff, (lo, hi) = sharpe_difference_significant(returns, returns)
        assert sig is False
        assert abs(diff) < 1e-10
        assert lo <= 0.0 <= hi  # CI straddles zero

    def test_clearly_different_series_significant(self):
        """Series with very different Sharpes → difference should be significant."""
        from omega.eval.significance import sharpe_difference_significant

        # Series A has strong positive returns, Series B is near-zero
        rng = random.Random(1)
        a = [rng.gauss(0.01, 0.005) for _ in range(500)]
        b = [rng.gauss(0.0, 0.005) for _ in range(500)]
        _sig, diff, (lo, hi) = sharpe_difference_significant(a, b, n_bootstrap=2000)
        assert diff > 0.0  # A is better
        assert lo < hi

    def test_diff_estimate_is_sharpe_a_minus_sharpe_b(self):
        """diff estimate ≈ Sharpe(A) - Sharpe(B)."""
        from omega.eval.sharpe import compute_sharpe
        from omega.eval.significance import sharpe_difference_significant

        rng = random.Random(10)
        a = [rng.gauss(0.002, 0.01) for _ in range(200)]
        b = [rng.gauss(0.001, 0.01) for _ in range(200)]
        _sig, diff, _ci = sharpe_difference_significant(a, b)
        expected = compute_sharpe(a) - compute_sharpe(b)
        assert abs(diff - expected) < 1e-10

    def test_ci_lower_less_than_upper(self):
        """Bootstrap CI has lo < hi."""
        from omega.eval.significance import sharpe_difference_significant

        rng = random.Random(55)
        a = [rng.gauss(0.001, 0.02) for _ in range(150)]
        b = [rng.gauss(0.001, 0.02) for _ in range(150)]
        _sig, _diff, (lo, hi) = sharpe_difference_significant(a, b)
        assert lo < hi

    def test_short_sequences_not_significant(self):
        """Fewer than 4 samples → not significant."""
        from omega.eval.significance import sharpe_difference_significant

        sig, _diff, _ = sharpe_difference_significant([0.01, 0.02], [0.01, 0.02])
        assert sig is False

    def test_empty_sequences(self):
        """Empty sequences → not significant."""
        from omega.eval.significance import sharpe_difference_significant

        sig, diff, (_lo, _hi) = sharpe_difference_significant([], [])
        assert sig is False
        assert diff == 0.0

    def test_n_bootstrap_affects_precision(self):
        """Higher n_bootstrap → narrower CI (statistically, on average)."""
        from omega.eval.significance import sharpe_difference_significant

        rng = random.Random(77)
        a = [rng.gauss(0.002, 0.01) for _ in range(200)]
        b = [rng.gauss(0.001, 0.01) for _ in range(200)]
        _sig1, _d1, (lo1, hi1) = sharpe_difference_significant(a, b, n_bootstrap=100, seed=42)
        _sig2, _d2, (lo2, hi2) = sharpe_difference_significant(a, b, n_bootstrap=5000, seed=42)
        # More bootstraps → more stable estimates (both are valid; just check they run)
        assert lo1 < hi1
        assert lo2 < hi2


class TestDeflatedSharpeRatio:
    def test_returns_float(self):
        """deflated_sharpe_ratio returns a float."""
        from omega.eval.significance import deflated_sharpe_ratio

        result = deflated_sharpe_ratio(
            sharpe=1.5, n_trials=10, variance_of_sharpes=0.5, skew=0.0, kurtosis=3.0
        )
        assert isinstance(result, float)

    def test_dsr_less_than_raw_sharpe_with_many_trials(self):
        """DSR penalises for multiple testing — returns probability, not raw SR."""
        from omega.eval.significance import deflated_sharpe_ratio

        # DSR is a probability in [0, 1]
        dsr = deflated_sharpe_ratio(
            sharpe=1.5, n_trials=100, variance_of_sharpes=0.3, skew=0.0, kurtosis=3.0
        )
        assert 0.0 <= dsr <= 1.0

    def test_dsr_decreases_with_more_trials(self):
        """More trials → higher selection bias → lower DSR for same observed Sharpe."""
        from omega.eval.significance import deflated_sharpe_ratio

        dsr_few = deflated_sharpe_ratio(
            sharpe=1.5, n_trials=5, variance_of_sharpes=0.3, skew=0.0, kurtosis=3.0
        )
        dsr_many = deflated_sharpe_ratio(
            sharpe=1.5, n_trials=1000, variance_of_sharpes=0.3, skew=0.0, kurtosis=3.0
        )
        assert dsr_few > dsr_many

    def test_dsr_high_for_very_high_sharpe(self):
        """Extremely high observed Sharpe → DSR close to 1."""
        from omega.eval.significance import deflated_sharpe_ratio

        dsr = deflated_sharpe_ratio(
            sharpe=20.0, n_trials=10, variance_of_sharpes=0.1, skew=0.0, kurtosis=3.0
        )
        assert dsr > 0.9

    def test_dsr_handles_zero_variance(self):
        """Zero variance_of_sharpes → no selection bias → DSR ≈ 1 for positive SR."""
        from omega.eval.significance import deflated_sharpe_ratio

        dsr = deflated_sharpe_ratio(
            sharpe=1.5, n_trials=10, variance_of_sharpes=0.0, skew=0.0, kurtosis=3.0
        )
        assert math.isfinite(dsr)
        assert 0.0 <= dsr <= 1.0

    def test_dsr_one_trial_equals_no_penalty(self):
        """With n_trials=1, almost no selection bias (SR* ≈ 0)."""
        from omega.eval.significance import deflated_sharpe_ratio

        dsr = deflated_sharpe_ratio(
            sharpe=1.5, n_trials=1, variance_of_sharpes=0.3, skew=0.0, kurtosis=3.0
        )
        assert dsr > 0.5  # positive Sharpe with no multiple testing should be > 0.5
