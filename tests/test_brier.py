"""Tests for omega.math.brier — Brier score engine."""

from __future__ import annotations

import math

import numpy as np
import pytest

from omega.math.brier import (
    brier_score,
    brier_score_ew,
    calibration_curve,
    rank_sources,
)

# ---------------------------------------------------------------------------
# brier_score
# ---------------------------------------------------------------------------


class TestBrierScore:
    def test_perfect_forecasts(self):
        """Perfect predictions should yield BS = 0."""
        assert brier_score([1.0, 0.0, 1.0], [1, 0, 1]) == pytest.approx(0.0)

    def test_worst_forecasts(self):
        """Confidently wrong predictions yield BS = 1."""
        assert brier_score([0.0, 1.0, 0.0], [1, 0, 1]) == pytest.approx(1.0)

    def test_uninformative_forecasts(self):
        """Always predicting 0.5 yields BS = 0.25."""
        forecasts = [0.5, 0.5, 0.5, 0.5]
        outcomes = [1, 0, 1, 0]
        assert brier_score(forecasts, outcomes) == pytest.approx(0.25)

    def test_known_value(self):
        """Manual check: (0.9-1)² + (0.2-0)² + (0.8-1)² = 0.01+0.04+0.04 = 0.09/3 = 0.03."""
        forecasts = [0.9, 0.2, 0.8]
        outcomes = [1, 0, 1]
        assert brier_score(forecasts, outcomes) == pytest.approx((0.01 + 0.04 + 0.04) / 3)

    def test_empty_input(self):
        assert brier_score([], []) == 0.0

    def test_single_element_correct(self):
        assert brier_score([1.0], [1]) == pytest.approx(0.0)

    def test_single_element_wrong(self):
        assert brier_score([0.0], [1]) == pytest.approx(1.0)

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="same length"):
            brier_score([0.5, 0.5], [1])

    def test_forecast_out_of_range_raises(self):
        with pytest.raises(ValueError, match="\\[0, 1\\]"):
            brier_score([1.1], [1])

    def test_negative_forecast_raises(self):
        with pytest.raises(ValueError, match="\\[0, 1\\]"):
            brier_score([-0.1], [0])

    def test_outcome_out_of_range_raises(self):
        with pytest.raises(ValueError, match="\\[0, 1\\]"):
            brier_score([0.5], [2])

    def test_numpy_arrays_accepted(self):
        f = np.array([0.7, 0.3])
        o = np.array([1.0, 0.0])
        result = brier_score(f, o)
        assert result == pytest.approx((0.09 + 0.09) / 2)


# ---------------------------------------------------------------------------
# brier_score_ew
# ---------------------------------------------------------------------------


class TestBrierScoreEW:
    def test_lam_one_equals_standard(self):
        """λ=1 should reproduce standard Brier score."""
        forecasts = [0.8, 0.3, 0.9, 0.1]
        outcomes = [1, 0, 1, 0]
        assert brier_score_ew(forecasts, outcomes, lam=1.0) == pytest.approx(
            brier_score(forecasts, outcomes)
        )

    def test_recent_errors_penalised_more(self):
        """With λ < 1, an error at the end should dominate over one at the start."""
        # All correct except last; lower λ should increase score vs all correct except first
        early_error = [0.0, 1.0, 1.0, 1.0]  # error at index 0
        late_error = [1.0, 1.0, 1.0, 0.0]  # error at index 3
        outcomes = [1, 1, 1, 1]

        score_early = brier_score_ew(early_error, outcomes, lam=0.5)
        score_late = brier_score_ew(late_error, outcomes, lam=0.5)
        assert score_late > score_early

    def test_empty_returns_zero(self):
        assert brier_score_ew([], [], lam=0.97) == 0.0

    def test_invalid_lam_zero(self):
        with pytest.raises(ValueError, match="lam must be in"):
            brier_score_ew([0.5], [1], lam=0.0)

    def test_invalid_lam_negative(self):
        with pytest.raises(ValueError, match="lam must be in"):
            brier_score_ew([0.5], [1], lam=-0.1)

    def test_invalid_lam_greater_than_one(self):
        with pytest.raises(ValueError, match="lam must be in"):
            brier_score_ew([0.5], [1], lam=1.01)

    def test_perfect_predictions_zero(self):
        assert brier_score_ew([1.0, 0.0, 1.0], [1, 0, 1]) == pytest.approx(0.0)

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="same length"):
            brier_score_ew([0.5, 0.5], [1])

    def test_manual_calculation(self):
        """Two observations, λ=0.5: w=[0.5,1.0], errors=[0.0,1.0]."""
        # forecasts=[1,0], outcomes=[1,1] → errors=[0, 1]
        # weights=[0.5^1, 0.5^0] = [0.5, 1.0] sum=1.5
        # BS_ew = (0.5*0 + 1.0*1) / 1.5 = 1/1.5 ≈ 0.6667
        result = brier_score_ew([1.0, 0.0], [1, 1], lam=0.5)
        assert result == pytest.approx(1.0 / 1.5)


# ---------------------------------------------------------------------------
# calibration_curve
# ---------------------------------------------------------------------------


class TestCalibrationCurve:
    def test_output_keys(self):
        result = calibration_curve([0.1, 0.5, 0.9], [0, 1, 1])
        assert set(result.keys()) == {"bin_centers", "mean_forecast", "hit_rate", "counts"}

    def test_default_ten_bins(self):
        result = calibration_curve([0.1, 0.5, 0.9], [0, 1, 1])
        assert len(result["bin_centers"]) == 10

    def test_custom_bins(self):
        result = calibration_curve([0.1, 0.5, 0.9], [0, 1, 1], n_bins=5)
        assert len(result["bin_centers"]) == 5

    def test_empty_bins_are_nan(self):
        # Only forecasts in first bin (≈0.05)
        result = calibration_curve([0.05], [1], n_bins=10)
        assert result["counts"][0] == 1
        assert np.isnan(result["hit_rate"][1])  # second bin empty

    def test_total_count_equals_n(self):
        forecasts = [0.1, 0.2, 0.5, 0.8, 0.9]
        outcomes = [0, 0, 1, 1, 1]
        result = calibration_curve(forecasts, outcomes)
        assert result["counts"].sum() == len(forecasts)

    def test_perfect_calibration(self):
        """Each forecast probability equals the empirical hit rate in its bin."""
        # 10 obs at 0.05, 10 obs at 0.55 — hit rates ≈ forecasts
        forecasts = [0.05] * 10 + [0.55] * 10
        outcomes = [0] * 9 + [1] + [0] * 5 + [1] * 5
        result = calibration_curve(forecasts, outcomes)
        # bin 0 (0-0.1): 10 obs, hit_rate ≈ 0.1 ≈ mean_forecast 0.05 (approximately)
        assert result["counts"][0] == 10
        assert result["hit_rate"][0] == pytest.approx(0.1)

    def test_forecast_at_exactly_one(self):
        """Forecast of exactly 1.0 should fall in the last bin."""
        result = calibration_curve([1.0], [1], n_bins=10)
        assert result["counts"][-1] == 1
        assert result["counts"][:-1].sum() == 0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="same length"):
            calibration_curve([0.5, 0.5], [1])

    def test_out_of_range_forecast_raises(self):
        with pytest.raises(ValueError, match="\\[0, 1\\]"):
            calibration_curve([1.5], [1])


# ---------------------------------------------------------------------------
# rank_sources
# ---------------------------------------------------------------------------


class TestRankSources:
    def test_better_source_ranked_first(self):
        """Source with lower BS should rank first."""
        sources = {
            "model_A": ([0.9, 0.2, 0.8], [1, 0, 1]),  # accurate
            "model_B": ([0.5, 0.5, 0.5], [1, 0, 1]),  # uninformative
        }
        ranked = rank_sources(sources)
        assert ranked[0][0] == "model_A"
        assert ranked[1][0] == "model_B"
        assert ranked[0][1] < ranked[1][1]

    def test_scores_match_brier_score(self):
        sources = {
            "X": ([0.8, 0.3], [1, 0]),
        }
        ranked = rank_sources(sources)
        expected = brier_score([0.8, 0.3], [1, 0])
        assert ranked[0][1] == pytest.approx(expected)

    def test_empty_source_goes_last(self):
        sources = {
            "good": ([0.9, 0.1], [1, 0]),
            "empty": ([], []),
        }
        ranked = rank_sources(sources)
        assert ranked[-1][0] == "empty"
        assert math.isnan(ranked[-1][1])

    def test_weighted_variant(self):
        sources = {
            "A": ([0.8, 0.2, 0.9], [1, 0, 1]),
        }
        ranked_std = rank_sources(sources, weighted=False)
        ranked_ew = rank_sources(sources, weighted=True, lam=0.97)
        # Both should return the same source; scores may differ slightly
        assert ranked_std[0][0] == "A"
        assert ranked_ew[0][0] == "A"

    def test_empty_sources_dict(self):
        assert rank_sources({}) == []

    def test_three_sources_sorted(self):
        sources = {
            "worst": ([0.0, 1.0], [1, 0]),  # BS = 1.0
            "best": ([1.0, 0.0], [1, 0]),  # BS = 0.0
            "mid": ([0.5, 0.5], [1, 0]),  # BS = 0.25
        }
        ranked = rank_sources(sources)
        names = [r[0] for r in ranked]
        assert names == ["best", "mid", "worst"]
