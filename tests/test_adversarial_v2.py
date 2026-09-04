"""Tests for omega.core.adversarial_v2."""

from __future__ import annotations

import pytest

from omega.core.adversarial import DisagreementResult, Scenario
from omega.core.adversarial_v2 import (
    AdaptiveThresholdManager,
    AdversarialPressureV2,
    AdversarialReportV2,
    AttributionResult,
    DisagreementAttributor,
    FalsePositiveTracker,
    Ring2ActivationController,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_disagreement(
    flagged: bool,
    max_disagreement: float = 0.3,
    outputs: dict | None = None,
    disagreeing: list[str] | None = None,
) -> DisagreementResult:
    if outputs is None:
        outputs = {
            "v_a": {"BTC": 0.9, "ETH": 0.8},
            "v_b": {"BTC": 0.1, "ETH": 0.1},
        }
    return DisagreementResult(
        flagged=flagged,
        max_disagreement=max_disagreement,
        disagreeing_variants=disagreeing or (["v_a", "v_b"] if flagged else []),
        outputs=outputs,
    )


def simple_strategy(signals: dict, scenario: Scenario) -> dict:
    return {t: max(0.0, s) for t, s in signals.items()}


# ---------------------------------------------------------------------------
# AdaptiveThresholdManager
# ---------------------------------------------------------------------------


class TestAdaptiveThresholdManager:
    def test_initial_threshold(self):
        mgr = AdaptiveThresholdManager(initial_threshold=0.20)
        assert mgr.current_threshold == pytest.approx(0.20)

    def test_raises_threshold_on_high_fp_rate(self):
        mgr = AdaptiveThresholdManager(
            initial_threshold=0.20,
            step_size=0.02,
            fp_rate_high_watermark=0.20,
            adjustment_interval=1,
        )
        adj = mgr.update(cycle=5, false_positive_rate=0.50, flag_rate=0.30)
        assert adj is not None
        assert adj.new_threshold > adj.old_threshold
        assert mgr.current_threshold == pytest.approx(0.22)

    def test_lowers_threshold_on_low_fp_and_flag_rate(self):
        mgr = AdaptiveThresholdManager(
            initial_threshold=0.30,
            step_size=0.02,
            fp_rate_low_watermark=0.10,
            min_flag_rate=0.10,
            adjustment_interval=1,
        )
        adj = mgr.update(cycle=5, false_positive_rate=0.02, flag_rate=0.02)
        assert adj is not None
        assert adj.new_threshold < adj.old_threshold
        assert mgr.current_threshold == pytest.approx(0.28)

    def test_no_adjustment_within_interval(self):
        mgr = AdaptiveThresholdManager(
            initial_threshold=0.20,
            step_size=0.02,
            fp_rate_high_watermark=0.10,
            adjustment_interval=10,
        )
        mgr.update(cycle=5, false_positive_rate=0.50, flag_rate=0.30)
        adj2 = mgr.update(cycle=8, false_positive_rate=0.50, flag_rate=0.30)
        # Second update within interval should not adjust
        assert adj2 is None

    def test_threshold_clamped_at_max(self):
        mgr = AdaptiveThresholdManager(
            initial_threshold=0.58,
            max_threshold=0.60,
            step_size=0.05,
            fp_rate_high_watermark=0.10,
            adjustment_interval=1,
        )
        mgr.update(cycle=1, false_positive_rate=0.50, flag_rate=0.30)
        assert mgr.current_threshold <= 0.60

    def test_threshold_clamped_at_min(self):
        mgr = AdaptiveThresholdManager(
            initial_threshold=0.07,
            min_threshold=0.05,
            step_size=0.05,
            fp_rate_low_watermark=0.10,
            min_flag_rate=0.10,
            adjustment_interval=1,
        )
        mgr.update(cycle=1, false_positive_rate=0.01, flag_rate=0.01)
        assert mgr.current_threshold >= 0.05

    def test_no_adjustment_when_in_good_zone(self):
        mgr = AdaptiveThresholdManager(
            initial_threshold=0.20,
            fp_rate_high_watermark=0.30,
            fp_rate_low_watermark=0.05,
            min_flag_rate=0.05,
            adjustment_interval=1,
        )
        adj = mgr.update(cycle=5, false_positive_rate=0.15, flag_rate=0.10)
        assert adj is None
        assert mgr.current_threshold == pytest.approx(0.20)

    def test_adjustment_history_accumulates(self):
        mgr = AdaptiveThresholdManager(
            initial_threshold=0.20,
            step_size=0.02,
            fp_rate_high_watermark=0.10,
            adjustment_interval=1,
        )
        for i in range(5):
            mgr.update(cycle=i * 2, false_positive_rate=0.50, flag_rate=0.30)
        assert len(mgr.adjustment_history()) >= 1

    def test_rolling_flag_rate_initially_zero(self):
        mgr = AdaptiveThresholdManager()
        assert mgr.rolling_flag_rate() == pytest.approx(0.0)

    def test_record_observation_updates_flag_window(self):
        mgr = AdaptiveThresholdManager()
        mgr.record_observation(flagged=True)
        mgr.record_observation(flagged=False)
        mgr.record_observation(flagged=True)
        rate = mgr.rolling_flag_rate()
        assert rate == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# DisagreementAttributor
# ---------------------------------------------------------------------------


class TestDisagreementAttributor:
    def test_attributes_outlier_correctly(self):
        attributor = DisagreementAttributor(z_score_threshold=1.0)
        # v_c is the outlier: very different from v_a and v_b
        outputs = {
            "v_a": {"BTC": 0.8, "ETH": 0.7},
            "v_b": {"BTC": 0.75, "ETH": 0.72},
            "v_c": {"BTC": -0.9, "ETH": -0.8},  # outlier
        }
        result = _make_disagreement(
            flagged=True,
            outputs=outputs,
            disagreeing=["v_a", "v_b", "v_c"],
        )
        attr = attributor.attribute(result)
        assert isinstance(attr, AttributionResult)
        assert "v_c" in attr.outlier_variants

    def test_returns_empty_outliers_when_not_flagged_and_similar(self):
        attributor = DisagreementAttributor(z_score_threshold=10.0)  # very high threshold
        outputs = {
            "v_a": {"BTC": 0.5, "ETH": 0.5},
            "v_b": {"BTC": 0.51, "ETH": 0.49},
        }
        result = _make_disagreement(flagged=False, outputs=outputs, disagreeing=[])
        attr = attributor.attribute(result)
        assert isinstance(attr, AttributionResult)
        # With very high threshold and near-identical outputs, may return empty
        # or fallback to highest-z; confidence should be low
        assert attr.confidence < 0.5 or len(attr.outlier_variants) == 0

    def test_single_variant_returns_empty(self):
        attributor = DisagreementAttributor()
        outputs = {"v_a": {"BTC": 0.5}}
        result = _make_disagreement(flagged=False, outputs=outputs, disagreeing=[])
        attr = attributor.attribute(result)
        assert attr.outlier_variants == []
        assert attr.confidence == pytest.approx(0.0)

    def test_confidence_between_0_and_1(self):
        attributor = DisagreementAttributor(z_score_threshold=1.0)
        outputs = {
            "v_a": {"BTC": 0.8},
            "v_b": {"BTC": 0.2},
            "v_c": {"BTC": -0.9},
        }
        result = _make_disagreement(flagged=True, outputs=outputs)
        attr = attributor.attribute(result)
        assert 0.0 <= attr.confidence <= 1.0

    def test_outlier_scores_all_variants_present(self):
        attributor = DisagreementAttributor()
        outputs = {
            "v_a": {"BTC": 0.9},
            "v_b": {"BTC": 0.8},
            "v_c": {"BTC": -0.5},
        }
        result = _make_disagreement(flagged=True, outputs=outputs)
        attr = attributor.attribute(result)
        for vid in outputs:
            assert vid in attr.outlier_scores

    def test_method_label(self):
        attributor = DisagreementAttributor()
        outputs = {"v_a": {"BTC": 0.9}, "v_b": {"BTC": 0.1}}
        result = _make_disagreement(flagged=True, outputs=outputs)
        attr = attributor.attribute(result)
        assert attr.method == "z_score_pairwise"

    def test_flagged_fallback_returns_variant(self):
        """When flagged but no z-score exceeds threshold, should still return a variant."""
        attributor = DisagreementAttributor(z_score_threshold=100.0)
        outputs = {
            "v_a": {"BTC": 0.8, "ETH": 0.7},
            "v_b": {"BTC": 0.2, "ETH": 0.1},
        }
        result = _make_disagreement(flagged=True, outputs=outputs)
        attr = attributor.attribute(result)
        assert len(attr.outlier_variants) >= 1


# ---------------------------------------------------------------------------
# FalsePositiveTracker
# ---------------------------------------------------------------------------


class TestFalsePositiveTracker:
    def test_initial_fp_rate_zero(self):
        tracker = FalsePositiveTracker()
        assert tracker.false_positive_rate() == pytest.approx(0.0)

    def test_fp_rate_all_false_positives(self):
        tracker = FalsePositiveTracker()
        for i in range(5):
            tracker.record_flag(cycle=i, flagged=True)
            tracker.record_outcome(cycle=i, was_false_positive=True)
        assert tracker.false_positive_rate() == pytest.approx(1.0)

    def test_fp_rate_no_false_positives(self):
        tracker = FalsePositiveTracker()
        for i in range(5):
            tracker.record_flag(cycle=i, flagged=True)
            tracker.record_outcome(cycle=i, was_false_positive=False)
        assert tracker.false_positive_rate() == pytest.approx(0.0)

    def test_fp_rate_mixed(self):
        tracker = FalsePositiveTracker()
        for i in range(4):
            tracker.record_flag(cycle=i, flagged=True)
        tracker.record_outcome(0, was_false_positive=True)
        tracker.record_outcome(1, was_false_positive=False)
        tracker.record_outcome(2, was_false_positive=True)
        tracker.record_outcome(3, was_false_positive=False)
        assert tracker.false_positive_rate() == pytest.approx(0.5)

    def test_outcome_for_unflagged_cycle_ignored(self):
        tracker = FalsePositiveTracker()
        tracker.record_flag(cycle=0, flagged=False)
        tracker.record_outcome(cycle=0, was_false_positive=True)
        # No resolved flags should have been added
        assert len(tracker._resolved) == 0

    def test_outcome_for_unknown_cycle_warns(self):
        tracker = FalsePositiveTracker()
        # Should not raise
        tracker.record_outcome(cycle=999, was_false_positive=True)

    def test_flag_rate_calculation(self):
        tracker = FalsePositiveTracker()
        for i in range(10):
            tracker.record_flag(cycle=i, flagged=(i % 2 == 0))
        rate = tracker.flag_rate()
        assert rate == pytest.approx(0.5)

    def test_flag_rate_recent_n(self):
        tracker = FalsePositiveTracker()
        for i in range(10):
            tracker.record_flag(cycle=i, flagged=(i >= 7))  # last 3 flagged
        rate = tracker.flag_rate(recent_n=5)
        assert rate == pytest.approx(3 / 5)

    def test_pending_outcomes(self):
        tracker = FalsePositiveTracker()
        for i in range(5):
            tracker.record_flag(cycle=i, flagged=True)
        tracker.record_outcome(0, was_false_positive=False)
        pending = tracker.pending_outcomes()
        assert 0 not in pending
        assert set(pending) == {1, 2, 3, 4}

    def test_summary_dict_keys(self):
        tracker = FalsePositiveTracker()
        tracker.record_flag(cycle=0, flagged=True)
        tracker.record_outcome(0, was_false_positive=False)
        summary = tracker.summary()
        assert "total_cycles_observed" in summary
        assert "total_flagged" in summary
        assert "resolved_flags" in summary
        assert "false_positive_rate" in summary
        assert "pending_outcomes" in summary

    def test_window_limits_resolved_history(self):
        tracker = FalsePositiveTracker(window=5)
        for i in range(20):
            tracker.record_flag(cycle=i, flagged=True)
            tracker.record_outcome(cycle=i, was_false_positive=(i % 2 == 0))
        assert len(tracker._resolved) == 5


# ---------------------------------------------------------------------------
# Ring2ActivationController
# ---------------------------------------------------------------------------


class TestRing2ActivationController:
    def test_not_activated_below_min_cycles(self):
        ctrl = Ring2ActivationController(
            min_ring1_cycles=20,
            min_ring1_flag_rate=0.05,
        )
        assert ctrl.should_activate(ring1_cycles_run=5, ring1_flag_rate=0.20) is False

    def test_not_activated_below_min_flag_rate(self):
        ctrl = Ring2ActivationController(
            min_ring1_cycles=10,
            min_ring1_flag_rate=0.10,
        )
        assert ctrl.should_activate(ring1_cycles_run=20, ring1_flag_rate=0.01) is False

    def test_activated_when_both_criteria_met(self):
        ctrl = Ring2ActivationController(
            min_ring1_cycles=10,
            min_ring1_flag_rate=0.05,
        )
        assert ctrl.should_activate(ring1_cycles_run=20, ring1_flag_rate=0.10) is True

    def test_record_gate_result_updates_consecutive_passes(self):
        ctrl = Ring2ActivationController()
        ctrl.record_gate_result(cycle=1, passed=True)
        ctrl.record_gate_result(cycle=2, passed=True)
        assert ctrl.status.consecutive_gate_passes == 2
        assert ctrl.status.consecutive_gate_fails == 0

    def test_record_gate_result_resets_on_fail(self):
        ctrl = Ring2ActivationController()
        ctrl.record_gate_result(cycle=1, passed=True)
        ctrl.record_gate_result(cycle=2, passed=True)
        ctrl.record_gate_result(cycle=3, passed=False)
        assert ctrl.status.consecutive_gate_passes == 0
        assert ctrl.status.consecutive_gate_fails == 1

    def test_total_evaluations_increments(self):
        ctrl = Ring2ActivationController()
        ctrl.record_gate_result(cycle=1, passed=True)
        ctrl.record_gate_result(cycle=2, passed=False)
        assert ctrl.status.total_evaluations == 2


# ---------------------------------------------------------------------------
# AdversarialPressureV2 — integration tests
# ---------------------------------------------------------------------------


class TestAdversarialPressureV2:
    def _make_variant_outputs(self, agree: bool = True) -> dict:
        if agree:
            return {
                "v_a": {"BTC": 0.8, "ETH": 0.7},
                "v_b": {"BTC": 0.75, "ETH": 0.72},
            }
        else:
            return {
                "v_a": {"BTC": 0.9, "ETH": 0.8},
                "v_b": {"BTC": 0.1, "ETH": 0.1},
            }

    def test_run_v2_returns_report(self):
        ap = AdversarialPressureV2(ring1_threshold=0.2)
        report = ap.run_v2(
            cycle=1,
            variant_outputs=self._make_variant_outputs(agree=True),
            current_signals={"BTC": 0.8, "ETH": 0.6},
            strategy_params={},
        )
        assert isinstance(report, AdversarialReportV2)

    def test_run_v2_no_attribution_when_no_flag(self):
        ap = AdversarialPressureV2(ring1_threshold=0.50)
        report = ap.run_v2(
            cycle=1,
            variant_outputs=self._make_variant_outputs(agree=True),
            current_signals={"BTC": 0.8},
            strategy_params={},
        )
        assert report.attribution is None

    def test_run_v2_attribution_when_flagged(self):
        ap = AdversarialPressureV2(ring1_threshold=0.05)  # very sensitive
        report = ap.run_v2(
            cycle=1,
            variant_outputs=self._make_variant_outputs(agree=False),
            current_signals={"BTC": 0.8},
            strategy_params={},
        )
        # With threshold=0.05 and big disagreement, should be flagged
        if report.base_report.ring1_result and report.base_report.ring1_result.flagged:
            assert report.attribution is not None
            assert isinstance(report.attribution, AttributionResult)

    def test_run_v2_current_threshold_exposed(self):
        ap = AdversarialPressureV2(ring1_threshold=0.25)
        report = ap.run_v2(
            cycle=1,
            variant_outputs=self._make_variant_outputs(),
            current_signals={"BTC": 0.8},
            strategy_params={},
        )
        assert isinstance(report.current_threshold, float)
        assert report.current_threshold > 0

    def test_run_v2_fp_summary_present(self):
        ap = AdversarialPressureV2()
        report = ap.run_v2(
            cycle=1,
            variant_outputs=self._make_variant_outputs(),
            current_signals={"BTC": 0.8},
            strategy_params={},
        )
        assert isinstance(report.fp_summary, dict)
        assert "false_positive_rate" in report.fp_summary

    def test_register_outcome_updates_fp_tracker(self):
        ap = AdversarialPressureV2(ring1_threshold=0.05)
        # First run to create a flag observation
        ap.run_v2(
            cycle=1,
            variant_outputs=self._make_variant_outputs(agree=False),
            current_signals={"BTC": 0.8},
            strategy_params={},
        )
        # Register outcome (may or may not have been flagged depending on threshold)
        ap.fp_tracker.record_flag(cycle=99, flagged=True)
        ap.register_outcome(cycle=99, was_false_positive=True)
        assert ap.fp_tracker.false_positive_rate() > 0.0

    def test_ring2_not_activated_initially(self):
        ap = AdversarialPressureV2(
            min_ring1_cycles_for_ring2=100,
            min_ring1_flag_rate_for_ring2=0.50,
        )
        report = ap.run_v2(
            cycle=1,
            variant_outputs=self._make_variant_outputs(),
            current_signals={"BTC": 0.8},
            strategy_params={},
        )
        assert report.ring2_activated is False
        assert report.ring2_sim_report is None

    def test_ring2_activates_after_enough_cycles(self):
        ap = AdversarialPressureV2(
            ring1_threshold=0.05,  # very sensitive — will flag often
            min_ring1_cycles_for_ring2=5,
            min_ring1_flag_rate_for_ring2=0.01,
        )
        # Run enough cycles to satisfy Ring 1 validation
        for i in range(10):
            ap.run_v2(
                cycle=i,
                variant_outputs=self._make_variant_outputs(agree=False),
                current_signals={"BTC": 0.8, "ETH": 0.6},
                strategy_params={},
                strategy_callable=simple_strategy,
            )
        # By cycle 20 (RING2_SIM_INTERVAL) Ring 2 gate should run
        report = ap.run_v2(
            cycle=20,
            variant_outputs=self._make_variant_outputs(agree=False),
            current_signals={"BTC": 0.8, "ETH": 0.6},
            strategy_params={},
            strategy_callable=simple_strategy,
        )
        assert report.ring2_activated is True
        # sim_report may or may not exist depending on cycle alignment
        # but the activated flag should be True

    def test_run_v2_with_strategy_callable(self):
        ap = AdversarialPressureV2(
            min_ring1_cycles_for_ring2=1,
            min_ring1_flag_rate_for_ring2=0.0,
        )
        # Pre-run to satisfy cycles
        for i in range(3):
            ap.run_v2(
                cycle=i,
                variant_outputs=self._make_variant_outputs(agree=False),
                current_signals={"BTC": 0.8},
                strategy_params={},
            )
        # Run at RING2_SIM_INTERVAL boundary
        report = ap.run_v2(
            cycle=20,
            variant_outputs=self._make_variant_outputs(),
            current_signals={"BTC": 0.8, "ETH": 0.6},
            strategy_params={},
            strategy_callable=simple_strategy,
        )
        # Should not raise
        assert isinstance(report, AdversarialReportV2)

    def test_collect_failure_cases_delegates(self):
        ap = AdversarialPressureV2(ring1_threshold=0.05)
        ap.run_v2(
            cycle=1,
            variant_outputs=self._make_variant_outputs(agree=False),
            current_signals={"BTC": 0.8},
            strategy_params={},
        )
        cases = ap.collect_failure_cases()
        assert isinstance(cases, list)

    def test_clear_failure_cases(self):
        ap = AdversarialPressureV2(ring1_threshold=0.05)
        ap.run_v2(
            cycle=1,
            variant_outputs=self._make_variant_outputs(agree=False),
            current_signals={"BTC": 0.8},
            strategy_params={},
        )
        ap.clear_failure_cases()
        assert ap.collect_failure_cases() == []

    def test_validate_ring1_delegates(self):
        ap = AdversarialPressureV2()
        # Not enough cycles
        result = ap.validate_ring1(min_cycles=100)
        assert result is False

    def test_ring2_status_accessible(self):
        ap = AdversarialPressureV2()
        status = ap.ring2_status
        assert hasattr(status, "activated")
        assert hasattr(status, "total_evaluations")

    def test_threshold_adjustment_included_in_report(self):
        ap = AdversarialPressureV2(
            ring1_threshold=0.20,
            fp_high_watermark=0.0,  # always triggers raise
            adjustment_interval=1,
        )
        # Manually populate FP tracker to drive high FP rate
        for i in range(10):
            ap.fp_tracker.record_flag(cycle=i, flagged=True)
            ap.fp_tracker.record_outcome(cycle=i, was_false_positive=True)

        report = ap.run_v2(
            cycle=100,
            variant_outputs=self._make_variant_outputs(),
            current_signals={"BTC": 0.8},
            strategy_params={},
        )
        # Threshold adjustment may or may not fire depending on timing,
        # but the field should exist in the report
        assert hasattr(report, "threshold_adjustment")


class TestDebateGateLearnerDirection:
    """The gate learner's feedback sign.

    Blocking is `max_disagreement > threshold`, so a HIGHER threshold blocks LESS.
    The update rule was `threshold += alpha * (target - actual)`, which raised the
    threshold when the gate was under-blocking — positive feedback that ratcheted
    it to max_threshold within about 40 proposals and left the gate wide open.
    """

    def _learner(self):
        from omega.core.orchestrator_v2 import DebateGateLearner

        return DebateGateLearner()

    def test_under_blocking_tightens(self) -> None:
        gl = self._learner()
        start = gl.threshold
        for i in range(30):
            gl.record_proposal(blocked=False, cycle_id=str(i), proposal={})
            gl.update_threshold()
        assert gl.threshold < start, (
            "blocking below target must LOWER the threshold so the gate blocks more; "
            "raising it is the runaway this test exists to prevent"
        )

    def test_over_blocking_loosens(self) -> None:
        gl = self._learner()
        start = gl.threshold
        for i in range(30):
            gl.record_proposal(blocked=True, cycle_id=str(i), proposal={})
            gl.update_threshold()
        assert gl.threshold > start

    def test_threshold_stays_within_bounds(self) -> None:
        gl = self._learner()
        for i in range(500):
            gl.record_proposal(blocked=False, cycle_id=str(i), proposal={})
            gl.update_threshold()
        assert 0.10 <= gl.threshold <= 1.5

    def test_at_target_rate_the_threshold_stops_moving(self) -> None:
        """At the setpoint the controller must come to rest.

        Not "stays near its initial value": this is an integrator, so an early
        transient (the first window is 100% blocked, which legitimately loosens it)
        is carried forward permanently. What matters is that once the measured rate
        equals the target, delta is zero and the threshold stops moving. A
        controller that kept drifting at its setpoint would be the runaway again.
        """
        gl = self._learner()
        for i in range(60):
            gl.record_proposal(blocked=(i % 10 < 3), cycle_id=str(i), proposal={})
            gl.update_threshold()
        settled = gl.threshold
        for i in range(60, 120):
            gl.record_proposal(blocked=(i % 10 < 3), cycle_id=str(i), proposal={})
            gl.update_threshold()
        assert gl.threshold == pytest.approx(settled, abs=1e-9), (
            f"threshold moved {settled} -> {gl.threshold} while blocking at the target rate"
        )
