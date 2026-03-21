"""Tests for omega.math.kelly — Fat-tail Kelly sizer."""

from __future__ import annotations

import numpy as np
import pytest

from omega.math.kelly import (
    kelly_fat_tail,
    kelly_fractional,
    kelly_multi_asset,
    kelly_standard,
    rolling_kurtosis,
)

# ---------------------------------------------------------------------------
# kelly_standard
# ---------------------------------------------------------------------------


class TestKellyStandard:
    def test_even_money_sixty_percent(self):
        """Classic example: 60/40 coin flip at even money → f* = 0.2."""
        assert kelly_standard(0.6, 1.0) == pytest.approx(0.2)

    def test_even_money_fifty_percent(self):
        """50/50 coin at even money → f* = 0 (break-even)."""
        assert kelly_standard(0.5, 1.0) == pytest.approx(0.0)

    def test_negative_edge(self):
        """Unfair bet: p=0.4, b=1 → f* = -0.2 (don't bet)."""
        assert kelly_standard(0.4, 1.0) == pytest.approx(-0.2)

    def test_asymmetric_payout(self):
        """p=0.3, b=3 → f* = (0.3*3 - 0.7)/3 = 0.2/3 ≈ 0.0667."""
        result = kelly_standard(0.3, 3.0)
        assert result == pytest.approx((0.3 * 3.0 - 0.7) / 3.0)

    def test_very_high_edge(self):
        """Certainty win (p→1) should give f*→1."""
        result = kelly_standard(0.9999, 1.0)
        assert result > 0.99

    def test_invalid_p_zero(self):
        with pytest.raises(ValueError, match="p must be in"):
            kelly_standard(0.0, 1.0)

    def test_invalid_p_one(self):
        with pytest.raises(ValueError, match="p must be in"):
            kelly_standard(1.0, 1.0)

    def test_invalid_p_negative(self):
        with pytest.raises(ValueError, match="p must be in"):
            kelly_standard(-0.1, 1.0)

    def test_invalid_b_zero(self):
        with pytest.raises(ValueError, match="b must be"):
            kelly_standard(0.6, 0.0)

    def test_invalid_b_negative(self):
        with pytest.raises(ValueError, match="b must be"):
            kelly_standard(0.6, -1.0)

    def test_large_b(self):
        """High payout ratio: p=0.1, b=20 → f* = (0.1*20-0.9)/20 = 1.1/20 = 0.055."""
        expected = (0.1 * 20 - 0.9) / 20
        assert kelly_standard(0.1, 20.0) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# kelly_fat_tail
# ---------------------------------------------------------------------------


class TestKellyFatTail:
    def test_normal_kurtosis_no_adjustment(self):
        """κ = 3 (normal distribution) → factor = √(3/3) = 1, no change."""
        standard = kelly_standard(0.6, 1.0)
        adjusted = kelly_fat_tail(0.6, 1.0, kurtosis=3.0)
        assert adjusted == pytest.approx(standard)

    def test_high_kurtosis_reduces_position(self):
        """κ > 3 → adjustment < 1 → smaller position."""
        standard = kelly_standard(0.6, 1.0)
        adjusted = kelly_fat_tail(0.6, 1.0, kurtosis=6.0)
        assert adjusted < standard

    def test_low_kurtosis_increases_position(self):
        """κ < 3 → adjustment > 1 → larger position (platykurtic returns)."""
        standard = kelly_standard(0.6, 1.0)
        adjusted = kelly_fat_tail(0.6, 1.0, kurtosis=1.5)
        assert adjusted > standard

    def test_adjustment_factor_formula(self):
        """Verify exact formula: f_adj = f* x sqrt(3/kappa)."""
        p, b, kappa = 0.65, 2.0, 5.0
        f_star = kelly_standard(p, b)
        expected = f_star * (3.0 / kappa) ** 0.5
        assert kelly_fat_tail(p, b, kurtosis=kappa) == pytest.approx(expected)

    def test_zero_kurtosis_clamped(self):
        """κ = 0 is clamped to 0.01 to avoid division by zero."""
        result = kelly_fat_tail(0.6, 1.0, kurtosis=0.0)
        expected = kelly_standard(0.6, 1.0) * (3.0 / 0.01) ** 0.5
        assert result == pytest.approx(expected)

    def test_negative_kurtosis_clamped(self):
        """κ < 0 is clamped to 0.01."""
        result_neg = kelly_fat_tail(0.6, 1.0, kurtosis=-1.0)
        result_zero = kelly_fat_tail(0.6, 1.0, kurtosis=0.0)
        assert result_neg == pytest.approx(result_zero)

    def test_invalid_params_propagated(self):
        with pytest.raises(ValueError):
            kelly_fat_tail(0.0, 1.0, kurtosis=3.0)


# ---------------------------------------------------------------------------
# kelly_multi_asset
# ---------------------------------------------------------------------------


class TestKellyMultiAsset:
    def test_single_asset_matches_standard(self):
        """Single asset: f* = mu/sigma^2 matches kelly_standard for binary payoff."""
        mu = np.array([0.1])
        cov = np.array([[0.04]])  # sigma = 0.2
        result = kelly_multi_asset(mu, cov)
        assert result.shape == (1,)
        assert result[0] == pytest.approx(0.1 / 0.04)

    def test_two_uncorrelated_assets(self):
        """Uncorrelated assets: each allocation = mu_i / sigma_i^2."""
        mu = np.array([0.1, 0.2])
        cov = np.array([[0.04, 0.0], [0.0, 0.09]])
        result = kelly_multi_asset(mu, cov)
        assert result[0] == pytest.approx(0.1 / 0.04)
        assert result[1] == pytest.approx(0.2 / 0.09)

    def test_correlated_assets(self):
        """With correlation, solution should differ from uncorrelated case."""
        mu = np.array([0.1, 0.1])
        cov_uncorr = np.array([[0.04, 0.0], [0.0, 0.04]])
        cov_corr = np.array([[0.04, 0.03], [0.03, 0.04]])
        r_uncorr = kelly_multi_asset(mu, cov_uncorr)
        r_corr = kelly_multi_asset(mu, cov_corr)
        # Results should differ due to correlation
        assert not np.allclose(r_uncorr, r_corr)

    def test_shape_preserved(self):
        mu = np.array([0.1, 0.15, 0.05])
        cov = np.eye(3) * 0.04
        result = kelly_multi_asset(mu, cov)
        assert result.shape == (3,)

    def test_dimension_mismatch_raises(self):
        with pytest.raises(ValueError, match="shape"):
            kelly_multi_asset([0.1, 0.2], [[0.04]])

    def test_singular_matrix_raises(self):
        """Singular (rank-deficient) covariance should raise ValueError."""
        mu = np.array([0.1, 0.2])
        cov = np.array([[1.0, 1.0], [1.0, 1.0]])  # rank 1
        with pytest.raises(ValueError, match="rank-deficient"):
            kelly_multi_asset(mu, cov)


# ---------------------------------------------------------------------------
# rolling_kurtosis
# ---------------------------------------------------------------------------


class TestRollingKurtosis:
    def test_output_length(self):
        returns = list(range(20))
        result = rolling_kurtosis(returns, window=5)
        assert len(result) == 20

    def test_first_window_minus_one_are_nan(self):
        returns = list(range(10))
        result = rolling_kurtosis(returns, window=4)
        assert all(np.isnan(result[:3]))

    def test_valid_values_start_at_window_index(self):
        returns = np.random.default_rng(42).standard_normal(20)
        result = rolling_kurtosis(returns, window=5)
        # Index 4 should be the first non-NaN
        assert not np.isnan(result[4])
        assert np.isnan(result[3])

    def test_normal_distribution_kurtosis_near_three(self):
        """Large sample from normal distribution → kurtosis ≈ 3."""
        rng = np.random.default_rng(0)
        returns = rng.standard_normal(1000)
        result = rolling_kurtosis(returns, window=500)
        # Last value should be approximately 3 (normal distribution)
        assert result[-1] == pytest.approx(3.0, abs=0.5)

    def test_constant_series_returns_three(self):
        """Constant series: sigma=0, treated as normal → kurtosis = 3."""
        result = rolling_kurtosis([1.0] * 10, window=4)
        assert result[3] == pytest.approx(3.0)

    def test_window_too_small_raises(self):
        with pytest.raises(ValueError, match="window must be"):
            rolling_kurtosis([1, 2, 3, 4], window=3)

    def test_fat_tailed_distribution_high_kurtosis(self):
        """Student-t with low df has high kurtosis."""
        rng = np.random.default_rng(42)
        # t with df=3 has excess kurtosis = 6, so raw kurtosis = 9
        returns = rng.standard_t(df=3, size=2000)
        result = rolling_kurtosis(returns, window=500)
        # Last window kurtosis should be substantially > 3
        assert result[-1] > 4.0


# ---------------------------------------------------------------------------
# kelly_fractional
# ---------------------------------------------------------------------------


class TestKellyFractional:
    def test_half_kelly(self):
        """Half-Kelly should be exactly half of standard Kelly."""
        standard = kelly_standard(0.6, 1.0)
        half = kelly_fractional(0.6, 1.0, fraction=0.5)
        assert half == pytest.approx(standard * 0.5)

    def test_full_kelly_no_cap(self):
        """fraction=1, no kurtosis, max_position=1 → standard Kelly."""
        standard = kelly_standard(0.6, 1.0)
        result = kelly_fractional(0.6, 1.0, fraction=1.0, max_position=1.0)
        assert result == pytest.approx(standard)

    def test_max_position_cap_applied(self):
        """Very high Kelly fraction should be capped at max_position."""
        result = kelly_fractional(0.999, 100.0, fraction=1.0, max_position=0.25)
        assert result == pytest.approx(0.25)

    def test_negative_kelly_returns_zero(self):
        """Negative edge bet → 0.0 (don't trade)."""
        result = kelly_fractional(0.3, 1.0, fraction=0.5)
        assert result == pytest.approx(0.0)

    def test_fat_tail_integration(self):
        """Providing kurtosis should reduce position vs. no kurtosis."""
        no_adj = kelly_fractional(0.6, 1.0, fraction=0.5, kurtosis=None)
        fat_adj = kelly_fractional(0.6, 1.0, fraction=0.5, kurtosis=6.0)
        assert fat_adj < no_adj

    def test_invalid_fraction_zero(self):
        with pytest.raises(ValueError, match="fraction"):
            kelly_fractional(0.6, 1.0, fraction=0.0)

    def test_invalid_fraction_above_one(self):
        with pytest.raises(ValueError, match="fraction"):
            kelly_fractional(0.6, 1.0, fraction=1.1)

    def test_invalid_max_position_zero(self):
        with pytest.raises(ValueError, match="max_position"):
            kelly_fractional(0.6, 1.0, max_position=0.0)

    def test_result_always_in_bounds(self):
        """Result must always be in [0, max_position]."""
        for p in [0.3, 0.5, 0.6, 0.8, 0.99]:
            for b in [0.5, 1.0, 2.0, 5.0]:
                result = kelly_fractional(p, b, fraction=0.5, max_position=0.2)
                assert 0.0 <= result <= 0.2
