"""Tests for omega.eval.overfitting_gate — check_overfitting."""

from __future__ import annotations

import pytest

from omega.eval.overfitting_gate import OverfittingResult, check_overfitting


class TestOverfittingGateTypes:
    def test_returns_overfitting_result(self):
        result = check_overfitting(1.0, 0.5, 1.5, 0.9)
        assert isinstance(result, OverfittingResult)

    def test_has_required_fields(self):
        result = check_overfitting(1.0, 0.5, 1.5, 0.9)
        assert hasattr(result, "passed")
        assert hasattr(result, "reason")
        assert hasattr(result, "threshold")
        assert hasattr(result, "gap")

    def test_is_immutable(self) -> None:
        result = check_overfitting(1.0, 0.5, 1.5, 0.9)
        with pytest.raises((AttributeError, TypeError)):
            result.passed = False  # type: ignore[misc]


class TestOverfittingGateLogic:
    def test_passes_when_test_near_validate(self):
        # σ = (1.3 - 0.7) / (2 * 1.96) ≈ 0.153; threshold ≈ 0.847
        # test_sharpe=0.90 > 0.847 → pass
        result = check_overfitting(
            validate_sharpe=1.0,
            validate_ci_lower=0.7,
            validate_ci_upper=1.3,
            test_sharpe=0.90,
        )
        assert result.passed is True

    def test_fails_when_test_far_below_validate(self):
        # same CI → threshold ≈ 0.847; test_sharpe=0.2 < 0.847 → fail
        result = check_overfitting(
            validate_sharpe=1.0,
            validate_ci_lower=0.7,
            validate_ci_upper=1.3,
            test_sharpe=0.2,
        )
        assert result.passed is False

    def test_fails_with_overfitting_in_reason(self):
        result = check_overfitting(1.0, 0.7, 1.3, 0.2)
        assert "overfitting" in result.reason.lower()

    def test_passes_when_test_equals_validate(self):
        result = check_overfitting(1.0, 0.8, 1.2, 1.0)
        assert result.passed is True

    def test_passes_when_test_exceeds_validate(self):
        result = check_overfitting(1.0, 0.8, 1.2, 1.5)
        assert result.passed is True

    def test_threshold_is_validate_minus_one_sigma(self):
        # σ = (1.2 - 0.8) / (2 * 1.96) ≈ 0.1020
        result = check_overfitting(1.0, 0.8, 1.2, 0.5)
        expected_sigma = (1.2 - 0.8) / (2 * 1.96)
        expected_threshold = 1.0 - expected_sigma
        assert abs(result.threshold - expected_threshold) < 1e-6

    def test_gap_is_validate_minus_test(self):
        result = check_overfitting(1.0, 0.7, 1.3, 0.7)
        assert abs(result.gap - 0.3) < 1e-9

    def test_tight_ci_tight_threshold(self):
        # σ = (1.01 - 0.99) / (2*1.96) ≈ 0.0051; threshold ≈ 0.9949
        # test=0.98 < 0.9949 → fail
        result = check_overfitting(1.0, 0.99, 1.01, 0.98)
        assert result.passed is False

    def test_wide_ci_wide_threshold(self):
        # σ = (3.0 - (-1.0)) / (2*1.96) ≈ 1.02; threshold ≈ -0.02
        # test=0.0 > -0.02 → pass
        result = check_overfitting(1.0, -1.0, 3.0, 0.0)
        assert result.passed is True

    def test_reason_contains_numeric_values(self):
        result = check_overfitting(1.0, 0.7, 1.3, 0.5)
        assert "1.0" in result.reason or "1.0000" in result.reason
        assert "0.5" in result.reason or "0.5000" in result.reason


class TestOverfittingGateEdgeCases:
    def test_negative_sharpes(self):
        # Both sharpes negative — still a meaningful comparison
        result = check_overfitting(-0.5, -1.0, 0.0, -0.8)
        assert isinstance(result.passed, bool)

    def test_zero_validate_sharpe(self):
        result = check_overfitting(0.0, -0.5, 0.5, -0.1)
        assert isinstance(result.passed, bool)

    def test_equal_ci_bounds(self):
        # Zero-width CI → σ = 0 → threshold = validate_sharpe
        result = check_overfitting(1.0, 1.0, 1.0, 0.99)
        assert result.passed is False  # 0.99 < 1.0

    def test_equal_ci_bounds_equal_test(self):
        result = check_overfitting(1.0, 1.0, 1.0, 1.0)
        assert result.passed is True
