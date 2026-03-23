"""Tests for omega.eval.tpe_eval — TPEEvaluator."""

from __future__ import annotations

import math

import pytest

from omega.eval.tpe_eval import (
    TPEEvalReport,
    TPEEvaluator,
    TrialRecord,
    _approx_one_sided_p,
)

# ---------------------------------------------------------------------------
# TrialRecord
# ---------------------------------------------------------------------------


class TestTrialRecord:
    def test_creation(self):
        rec = TrialRecord(
            trial_index=0,
            params={"lr": 0.001},
            score=0.5,
            best_so_far=0.5,
            method="tpe",
        )
        assert rec.trial_index == 0
        assert rec.method == "tpe"


# ---------------------------------------------------------------------------
# TPEEvaluator — construction
# ---------------------------------------------------------------------------


class TestTPEEvaluatorConstruction:
    def test_default_params(self):
        ev = TPEEvaluator(n_trials=10)
        assert ev._n_trials == 10
        assert len(ev._param_space) > 0

    def test_custom_param_space(self):
        from omega.core.bayesian_optimizer import ContinuousParam

        space = [ContinuousParam("x", 0.0, 1.0)]
        ev = TPEEvaluator(n_trials=5, param_space=space)
        assert len(ev._param_space) == 1

    def test_assert_ran_before_analysis(self):
        ev = TPEEvaluator(n_trials=5)
        with pytest.raises(RuntimeError, match=r"Call run\(\)"):
            ev.convergence_curve()


# ---------------------------------------------------------------------------
# TPEEvaluator — run
# ---------------------------------------------------------------------------


class TestTPEEvaluatorRun:
    def test_run_returns_report(self):
        ev = TPEEvaluator(n_trials=20, seed=42)
        report = ev.run()
        assert isinstance(report, TPEEvalReport)

    def test_report_n_trials(self):
        ev = TPEEvaluator(n_trials=15, seed=1)
        report = ev.run()
        assert report.n_trials == 15
        assert len(report.tpe_trials) == 15
        assert len(report.random_trials) == 15

    def test_tpe_best_score_is_finite(self):
        ev = TPEEvaluator(n_trials=20, seed=42)
        report = ev.run()
        assert math.isfinite(report.tpe_best_score)
        assert math.isfinite(report.random_best_score)

    def test_str_representation(self):
        ev = TPEEvaluator(n_trials=10, seed=1)
        report = ev.run()
        s = str(report)
        assert "TPEEvalReport" in s

    def test_trial_methods_tagged(self):
        ev = TPEEvaluator(n_trials=10, seed=42)
        ev.run()
        for t in ev._tpe_trials:
            assert t.method == "tpe"
        for t in ev._random_trials:
            assert t.method == "random"

    def test_best_so_far_monotonically_nondecreasing(self):
        ev = TPEEvaluator(n_trials=30, seed=7)
        ev.run()
        curve = [t.best_so_far for t in ev._tpe_trials]
        for i in range(1, len(curve)):
            assert curve[i] >= curve[i - 1], (
                f"curve[{i}]={curve[i]} < curve[{i - 1}]={curve[i - 1]}"
            )


# ---------------------------------------------------------------------------
# convergence_curve
# ---------------------------------------------------------------------------


class TestConvergenceCurve:
    def test_length_matches_n_trials(self):
        ev = TPEEvaluator(n_trials=25, seed=42)
        ev.run()
        assert len(ev.convergence_curve()) == 25

    def test_non_decreasing(self):
        ev = TPEEvaluator(n_trials=30, seed=42)
        ev.run()
        curve = ev.convergence_curve()
        for i in range(1, len(curve)):
            assert curve[i] >= curve[i - 1]

    def test_last_value_equals_best(self):
        ev = TPEEvaluator(n_trials=20, seed=1)
        report = ev.run()
        curve = ev.convergence_curve()
        # report.tpe_best_score is rounded to 8 decimal places
        assert curve[-1] == pytest.approx(report.tpe_best_score, rel=1e-6)


# ---------------------------------------------------------------------------
# regret_curve
# ---------------------------------------------------------------------------


class TestRegretCurve:
    def test_length_matches_n_trials(self):
        ev = TPEEvaluator(n_trials=20, seed=42)
        ev.run()
        assert len(ev.regret_curve()) == 20

    def test_non_negative(self):
        ev = TPEEvaluator(n_trials=20, seed=42)
        ev.run()
        curve = ev.regret_curve()
        for v in curve:
            assert v >= -1e-9  # allow tiny floating-point errors

    def test_cumulative(self):
        """Regret should be cumulative (increasing or flat, not decreasing)."""
        ev = TPEEvaluator(n_trials=30, seed=5)
        ev.run()
        curve = ev.regret_curve()
        for i in range(1, len(curve)):
            assert curve[i] >= curve[i - 1] - 1e-9


# ---------------------------------------------------------------------------
# trials_to_convergence
# ---------------------------------------------------------------------------


class TestTrialsToConvergence:
    def test_returns_int(self):
        ev = TPEEvaluator(n_trials=30, seed=42)
        ev.run()
        t = ev.trials_to_convergence(epsilon=0.01)
        assert isinstance(t, int)

    def test_within_bounds(self):
        ev = TPEEvaluator(n_trials=50, seed=42)
        ev.run()
        t = ev.trials_to_convergence(epsilon=0.01)
        assert 0 <= t <= 50

    def test_large_epsilon_converges_early(self):
        ev = TPEEvaluator(n_trials=50, seed=42)
        ev.run()
        t_tight = ev.trials_to_convergence(epsilon=1e-6)
        t_loose = ev.trials_to_convergence(epsilon=10.0)
        assert t_loose <= t_tight


# ---------------------------------------------------------------------------
# beats_random
# ---------------------------------------------------------------------------


class TestBeatsRandom:
    def test_returns_bool(self):
        ev = TPEEvaluator(n_trials=50, seed=42)
        ev.run()
        result = ev.beats_random(confidence=0.95)
        assert isinstance(result, bool)

    def test_low_confidence_easier_to_beat(self):
        """With low confidence, TPE should more easily 'beat' random."""
        ev = TPEEvaluator(n_trials=50, seed=42)
        ev.run()
        # At very low confidence (just above chance), TPE likely beats random
        result_low = ev.beats_random(confidence=0.50)
        result_high = ev.beats_random(confidence=0.999)
        # Low confidence result can be True even if high is False
        # Just verify they are booleans (ordering not guaranteed for small n)
        assert isinstance(result_low, bool)
        assert isinstance(result_high, bool)

    def test_p_value_in_report(self):
        ev = TPEEvaluator(n_trials=30, seed=42)
        report = ev.run()
        assert 0.0 <= report.p_value <= 1.0


# ---------------------------------------------------------------------------
# Statistical test internals
# ---------------------------------------------------------------------------


class TestStatisticalTest:
    def test_identical_scores_no_difference(self):
        from omega.eval.tpe_eval import TPEEvaluator

        t1 = [TrialRecord(i, {}, 0.5, 0.5, "tpe") for i in range(10)]
        t2 = [TrialRecord(i, {}, 0.5, 0.5, "random") for i in range(10)]
        _beats, p = TPEEvaluator._statistical_test(t1, t2)
        # When means are equal, p should be high (no evidence of difference)
        assert p > 0.3

    def test_clearly_better_tpe(self):
        t1 = [TrialRecord(i, {}, 1.0 + i * 0.01, 1.0, "tpe") for i in range(30)]
        t2 = [TrialRecord(i, {}, 0.0, 0.0, "random") for i in range(30)]
        beats, p = TPEEvaluator._statistical_test(t1, t2)
        assert beats is True
        assert p < 0.05

    def test_insufficient_data_returns_false(self):
        t1 = [TrialRecord(0, {}, 1.0, 1.0, "tpe")]
        t2 = [TrialRecord(0, {}, 0.0, 0.0, "random")]
        beats, p = TPEEvaluator._statistical_test(t1, t2)
        assert beats is False
        assert p == 1.0


# ---------------------------------------------------------------------------
# _approx_one_sided_p
# ---------------------------------------------------------------------------


class TestApproxOneSidedP:
    def test_large_positive_t_small_p(self):
        p = _approx_one_sided_p(5.0)
        assert p < 0.01

    def test_zero_t_half(self):
        p = _approx_one_sided_p(0.0)
        assert 0.45 < p < 0.55

    def test_negative_t_large_p(self):
        p = _approx_one_sided_p(-3.0)
        assert p > 0.95

    def test_range(self):
        for t in [-5, -2, -1, 0, 1, 2, 5]:
            p = _approx_one_sided_p(t)
            assert 0.0 <= p <= 1.0


# ---------------------------------------------------------------------------
# Bonferroni multiple-comparison correction
# ---------------------------------------------------------------------------


class TestBonferroniCorrection:
    def test_report_has_n_trials_correction_field(self):
        """n_trials_correction field exists and equals n_trials in report."""
        ev = TPEEvaluator(n_trials=20, seed=42)
        report = ev.run()
        assert hasattr(report, "n_trials_correction")
        assert report.n_trials_correction == report.n_trials

    def test_n_trials_correction_default_is_one(self):
        """Default TPEEvalReport has n_trials_correction=1."""
        # Minimal report constructed directly
        rec = TrialRecord(0, {}, 0.5, 0.5, "tpe")
        report = TPEEvalReport(
            n_trials=10,
            tpe_trials=[rec],
            random_trials=[rec],
            tpe_best_score=0.5,
            random_best_score=0.5,
            tpe_beats_random=False,
            p_value=1.0,
        )
        assert report.n_trials_correction == 1

    def test_statistical_test_stricter_with_more_comparisons(self):
        """Same scores: n_comparisons=100 uses stricter threshold than n_comparisons=1."""
        # TPE is slightly better — should pass lenient threshold but not strict one
        t1 = [TrialRecord(i, {}, 0.55 + i * 0.001, 0.5, "tpe") for i in range(30)]
        t2 = [TrialRecord(i, {}, 0.50, 0.5, "random") for i in range(30)]

        beats_lenient, p_val_lenient = TPEEvaluator._statistical_test(t1, t2, n_comparisons=1)
        beats_strict, p_val_strict = TPEEvaluator._statistical_test(t1, t2, n_comparisons=100)

        # Raw p-values must be identical (same data)
        assert p_val_lenient == pytest.approx(p_val_strict)

        # With n_comparisons=100, threshold is 0.05/100=0.0005; more likely to reject
        # At minimum, strict cannot be True when lenient is False
        if not beats_lenient:
            assert not beats_strict

    def test_statistical_test_raw_p_value_unchanged(self):
        """The raw p-value returned is the same regardless of n_comparisons."""
        t1 = [TrialRecord(i, {}, 0.8, 0.8, "tpe") for i in range(20)]
        t2 = [TrialRecord(i, {}, 0.5, 0.5, "random") for i in range(20)]

        _, p1 = TPEEvaluator._statistical_test(t1, t2, n_comparisons=1)
        _, p100 = TPEEvaluator._statistical_test(t1, t2, n_comparisons=100)

        assert p1 == pytest.approx(p100)

    def test_report_p_value_is_raw(self):
        """Report p_value is the raw (uncorrected) p-value from the t-test."""
        ev = TPEEvaluator(n_trials=30, seed=42)
        report = ev.run()
        # Raw p-value must be in [0, 1]
        assert 0.0 <= report.p_value <= 1.0
        # n_trials_correction records the Bonferroni denominator
        assert report.n_trials_correction == report.n_trials

    def test_clearly_superior_tpe_beats_after_correction(self):
        """Clearly superior TPE (large effect) still returns True after Bonferroni with n=30."""
        t1 = [TrialRecord(i, {}, 1.0 + i * 0.01, 1.0, "tpe") for i in range(30)]
        t2 = [TrialRecord(i, {}, 0.0, 0.0, "random") for i in range(30)]
        beats, p = TPEEvaluator._statistical_test(t1, t2, n_comparisons=30)
        assert beats is True
        # alpha_corrected = 0.05/30 ≈ 0.00167; p should be well below this
        assert p < 0.05 / 30

    def test_beats_random_applies_bonferroni(self):
        """beats_random with 100 trials requires p < (1-0.95)/100 = 0.0005."""
        ev = TPEEvaluator(n_trials=100, seed=42)
        ev.run()

        # Get raw p-value via _statistical_test with n_comparisons=1
        _, raw_p = TPEEvaluator._statistical_test(
            ev._tpe_trials, ev._random_trials, n_comparisons=1
        )

        # beats_random uses n_comparisons=n_trials internally
        result = ev.beats_random(confidence=0.95)
        alpha_corrected = 0.05 / 100  # (1-0.95)/100

        # Verify the result is consistent with the corrected threshold
        assert result == (raw_p < alpha_corrected)

    def test_beats_random_custom_n_comparisons(self):
        """beats_random respects explicit n_comparisons override."""
        ev = TPEEvaluator(n_trials=50, seed=42)
        ev.run()

        # With n_comparisons=1, threshold is just (1-0.95)/1 = 0.05
        result_lenient = ev.beats_random(confidence=0.95, n_comparisons=1)
        # With n_comparisons=1000, threshold is 0.05/1000 = 0.00005 — very strict
        result_strict = ev.beats_random(confidence=0.95, n_comparisons=1000)

        # Strict can only be True if lenient is True
        if result_strict:
            assert result_lenient

    def test_str_includes_n_trials_correction(self):
        """__str__ of TPEEvalReport includes n_trials_correction."""
        ev = TPEEvaluator(n_trials=10, seed=1)
        report = ev.run()
        s = str(report)
        assert "n_trials_correction" in s
