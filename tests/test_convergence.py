"""Tests for omega.core.convergence."""

from __future__ import annotations

import math

import pytest

from omega.core.convergence import (
    ConvergenceDiagnostics,
    _regularised_incomplete_beta,
    beats_random,
    has_plateaued,
    improvement_rate,
    regret,
)

# ---------------------------------------------------------------------------
# improvement_rate
# ---------------------------------------------------------------------------


class TestImprovementRate:
    def test_empty_returns_zero(self):
        assert improvement_rate([]) == 0.0

    def test_single_returns_zero(self):
        assert improvement_rate([1.0]) == 0.0

    def test_two_increasing_returns_positive(self):
        assert improvement_rate([1.0, 2.0]) > 0.0

    def test_two_decreasing_returns_negative(self):
        assert improvement_rate([2.0, 1.0]) < 0.0

    def test_constant_returns_zero(self):
        scores = [3.0] * 10
        assert improvement_rate(scores) == pytest.approx(0.0)

    def test_windowed_ignores_early_scores(self):
        # First 10 declining, last 5 increasing steeply
        scores = [10.0 - i for i in range(10)] + [0.0, 1.0, 2.0, 3.0, 4.0]
        rate_full = improvement_rate(scores, window=len(scores))
        rate_window = improvement_rate(scores, window=5)
        assert rate_window > rate_full

    def test_arithmetic_correctness(self):
        # [0, 1, 2, 3] → diffs = [1, 1, 1] → mean = 1.0
        assert improvement_rate([0.0, 1.0, 2.0, 3.0]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# has_plateaued
# ---------------------------------------------------------------------------


class TestHasPlateaued:
    def test_insufficient_data_returns_false(self):
        assert has_plateaued([1.0, 2.0, 3.0], window=20) is False

    def test_constant_scores_plateau(self):
        scores = [5.0] * 25
        assert has_plateaued(scores, epsilon=0.01, window=20) is True

    def test_improving_scores_not_plateau(self):
        scores = [float(i) for i in range(30)]
        assert has_plateaued(scores, epsilon=0.01, window=20) is False

    def test_epsilon_boundary(self):
        # Improvement rate of 0.005 — below epsilon=0.01 → plateau
        scores = [i * 0.005 for i in range(25)]
        assert has_plateaued(scores, epsilon=0.01, window=20) is True

    def test_exactly_window_length(self):
        scores = [0.5] * 20
        assert has_plateaued(scores, window=20) is True

    def test_high_epsilon_easier_to_plateau(self):
        scores = [float(i) for i in range(25)]
        # rate ≈ 1.0
        assert has_plateaued(scores, epsilon=0.5, window=20) is False
        assert has_plateaued(scores, epsilon=2.0, window=20) is True


# ---------------------------------------------------------------------------
# regret
# ---------------------------------------------------------------------------


class TestRegret:
    def test_empty_returns_empty(self):
        assert regret([], oracle_score=1.0) == []

    def test_oracle_equals_score_zero_regret(self):
        r = regret([1.0, 1.0, 1.0], oracle_score=1.0)
        assert r == [pytest.approx(0.0)] * 3

    def test_monotone_increasing(self):
        r = regret([0.5, 0.5, 0.5], oracle_score=1.0)
        # Each step adds 0.5, so [0.5, 1.0, 1.5]
        assert r == pytest.approx([0.5, 1.0, 1.5])

    def test_perfect_optimiser_accumulates_no_regret(self):
        oracle = 2.0
        r = regret([oracle] * 10, oracle_score=oracle)
        assert all(abs(v) < 1e-9 for v in r)

    def test_length_matches_input(self):
        scores = [0.1, 0.2, 0.3, 0.4, 0.5]
        r = regret(scores, oracle_score=1.0)
        assert len(r) == len(scores)

    def test_scores_above_oracle_give_negative_regret(self):
        r = regret([2.0], oracle_score=1.0)
        assert r[0] < 0.0


# ---------------------------------------------------------------------------
# beats_random
# ---------------------------------------------------------------------------


class TestBeatsRandom:
    def test_too_few_samples_returns_false(self):
        sig, p = beats_random([1.0], [0.5])
        assert sig is False
        assert p == pytest.approx(1.0)

    def test_clearly_better_returns_significant(self):
        tpe = [1.0] * 50
        rand = [0.0] * 50
        sig, p = beats_random(tpe, rand)
        assert sig is True
        assert p < 0.05

    def test_clearly_worse_returns_not_significant(self):
        tpe = [0.0] * 50
        rand = [1.0] * 50
        sig, _p = beats_random(tpe, rand)
        assert sig is False

    def test_identical_distributions_not_significant(self):
        import random

        rng = random.Random(42)
        data = [rng.gauss(0, 1) for _ in range(40)]
        sig, _p = beats_random(data, data)
        assert sig is False

    def test_p_value_in_range(self):
        import random

        rng = random.Random(7)
        tpe = [rng.gauss(0.5, 1) for _ in range(30)]
        rand = [rng.gauss(0.0, 1) for _ in range(30)]
        _, p = beats_random(tpe, rand)
        assert 0.0 <= p <= 1.0

    def test_confidence_affects_significance(self):
        tpe = [0.6 + i * 0.01 for i in range(30)]
        rand = [0.5 + i * 0.005 for i in range(30)]
        _, _p = beats_random(tpe, rand)
        sig_95, _ = beats_random(tpe, rand, confidence=0.95)
        sig_50, _ = beats_random(tpe, rand, confidence=0.50)
        # Looser confidence should be easier to satisfy
        assert sig_50 >= sig_95

    def test_zero_variance_both_same_mean(self):
        tpe = [1.0] * 20
        rand = [1.0] * 20
        sig, _p = beats_random(tpe, rand)
        assert sig is False


# ---------------------------------------------------------------------------
# Incomplete beta (internal)
# ---------------------------------------------------------------------------


class TestRegularisedIncompleteBeta:
    def test_x_zero_returns_zero(self):
        assert _regularised_incomplete_beta(0.0, 1.0, 1.0) == pytest.approx(0.0)

    def test_x_one_returns_one(self):
        assert _regularised_incomplete_beta(1.0, 1.0, 1.0) == pytest.approx(1.0)

    def test_symmetry(self):
        # I_x(a, b) + I_{1-x}(b, a) == 1
        x, a, b = 0.3, 2.0, 5.0
        assert _regularised_incomplete_beta(x, a, b) + _regularised_incomplete_beta(
            1 - x, b, a
        ) == pytest.approx(1.0, abs=1e-5)

    def test_uniform_half(self):
        # I_{0.5}(1, 1) == 0.5  (beta(1,1) is uniform)
        assert _regularised_incomplete_beta(0.5, 1.0, 1.0) == pytest.approx(0.5, abs=1e-4)


# ---------------------------------------------------------------------------
# ConvergenceDiagnostics class
# ---------------------------------------------------------------------------


class TestConvergenceDiagnostics:
    def test_initial_state(self):
        d = ConvergenceDiagnostics()
        assert d.n_trials == 0
        assert d.scores == []
        assert d.best_score == -math.inf
        assert d.mean_score == 0.0

    def test_record_updates_state(self):
        d = ConvergenceDiagnostics()
        d.record(1.0)
        d.record(2.0)
        assert d.n_trials == 2
        assert d.best_score == pytest.approx(2.0)
        assert d.mean_score == pytest.approx(1.5)

    def test_has_converged_false_initially(self):
        d = ConvergenceDiagnostics(window=5)
        for s in [1.0, 2.0, 3.0]:
            d.record(s)
        assert d.has_converged() is False

    def test_has_converged_true_after_plateau(self):
        d = ConvergenceDiagnostics(epsilon=0.01, window=5)
        for _ in range(5):
            d.record(1.0)
        assert d.has_converged() is True

    def test_improvement_rate_delegated(self):
        d = ConvergenceDiagnostics()
        for i in range(5):
            d.record(float(i))
        assert d.improvement_rate() == pytest.approx(1.0)

    def test_regret_delegated(self):
        d = ConvergenceDiagnostics()
        d.record(0.5)
        d.record(0.5)
        r = d.regret(oracle_score=1.0)
        assert r == pytest.approx([0.5, 1.0])

    def test_beats_random_delegated(self):
        d = ConvergenceDiagnostics()
        for _ in range(20):
            d.record(1.0)
        rand = [0.0] * 20
        sig, p = d.beats_random(rand)
        assert sig is True
        assert p < 0.05

    def test_reset_clears_state(self):
        d = ConvergenceDiagnostics()
        d.record(1.0)
        d.record(2.0)
        d.reset()
        assert d.n_trials == 0
        assert d.scores == []

    def test_scores_returns_copy(self):
        d = ConvergenceDiagnostics()
        d.record(1.0)
        scores = d.scores
        scores.append(999.0)
        assert d.n_trials == 1  # Internal list unchanged
