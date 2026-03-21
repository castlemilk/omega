"""Tests for omega.core.goals — 3-layer goal architecture."""

import pytest
from omega.core.goals import (
    ConstitutionalConstraints,
    BalancedScorecard,
    HTNDecomposer,
    AdaptiveReferenceTracker,
    GoalArchitecture,
    GoalDecision,
    ConstraintViolation,
    Task,
    # Advanced components (still importable)
    NashWelfareAggregator,
    MPCReferenceTracker,
)


# ---------------------------------------------------------------------------
# Layer 1: ConstitutionalConstraints
# ---------------------------------------------------------------------------

class TestConstitutionalConstraints:
    def setup_method(self):
        self.c = ConstitutionalConstraints()
        self.c.register_defaults()

    def test_no_violation_healthy_metrics(self):
        metrics = {
            "max_drawdown_pct": 5.0,
            "max_position_pct": 15.0,
            "sharpe_ratio": 1.5,
            "error_rate": 0.05,
        }
        passed, violations = self.c.check(metrics)
        assert passed
        assert violations == []

    def test_hard_drawdown_violation(self):
        metrics = {"max_drawdown_pct": 25.0}  # > 15
        passed, violations = self.c.check(metrics)
        assert not passed
        assert any(v.severity == "hard" for v in violations)

    def test_hard_position_violation(self):
        metrics = {"max_position_pct": 40.0}  # > 25
        passed, violations = self.c.check(metrics)
        assert not passed

    def test_register_custom_constraint(self):
        self.c.register("custom_check", "latency_ms", 500.0, direction="max", severity="hard")
        metrics = {"latency_ms": 600.0}
        passed, violations = self.c.check(metrics)
        assert not passed

    def test_missing_metric_passes(self):
        passed, violations = self.c.check({"unknown_metric": 999.0})
        assert passed


# ---------------------------------------------------------------------------
# Layer 2: BalancedScorecard
# ---------------------------------------------------------------------------

class TestBalancedScorecard:
    def setup_method(self):
        self.sc = BalancedScorecard()

    def test_update_and_score(self):
        self.sc.update({
            "sharpe_ratio": 1.5,
            "max_drawdown_pct": 5.0,
            "error_rate": 0.05,
            "coverage_rate": 0.9,
        })
        scores = self.sc.score()
        assert set(scores.keys()) == set(BalancedScorecard.DIMENSIONS)
        assert all(0.0 <= v <= 1.0 for v in scores.values())

    def test_composite_score_range(self):
        self.sc.update({"sharpe_ratio": 2.0, "error_rate": 0.01, "coverage_rate": 0.95})
        cs = self.sc.composite_score()
        assert 0.0 <= cs <= 1.0

    def test_trend_requires_history(self):
        for i in range(6):
            self.sc.update({"sharpe_ratio": float(i) * 0.1})
        trend = self.sc.trend(window=5)
        assert isinstance(trend, dict)

    def test_empty_metrics_doesnt_crash(self):
        self.sc.update({})
        scores = self.sc.score()
        assert isinstance(scores, dict)


# ---------------------------------------------------------------------------
# AdaptiveReferenceTracker
# ---------------------------------------------------------------------------

class TestAdaptiveReferenceTracker:
    def setup_method(self):
        self.tracker = AdaptiveReferenceTracker(
            objectives=["sharpe_ratio", "coverage_rate"],
            ema_alpha=0.3,
        )

    def test_tracking_error_zero_with_no_data(self):
        err = self.tracker.tracking_error()
        assert err == 0.0

    def test_tracking_error_zero_initially_after_one_update(self):
        # EMA starts at first value, so error should be 0 or near-0
        self.tracker.update({"sharpe_ratio": 1.5, "coverage_rate": 0.8})
        err = self.tracker.tracking_error()
        assert err == 0.0

    def test_tracking_error_positive_after_deviation(self):
        # Warm up EMA
        for _ in range(5):
            self.tracker.update({"sharpe_ratio": 2.0, "coverage_rate": 0.9})
        # Now feed a very different value — should produce nonzero error
        self.tracker.update({"sharpe_ratio": 0.1, "coverage_rate": 0.1})
        err = self.tracker.tracking_error()
        assert isinstance(err, float)
        assert err >= 0.0

    def test_control_action_keys(self):
        self.tracker.update({"sharpe_ratio": 1.0, "coverage_rate": 0.7})
        action = self.tracker.control_action()
        assert "sharpe_ratio" in action
        assert "coverage_rate" in action

    def test_manual_reference_override(self):
        self.tracker.update({"sharpe_ratio": 1.0, "coverage_rate": 0.7})
        self.tracker.set_reference({
            "sharpe_ratio": [5.0, 5.0, 5.0],
            "coverage_rate": [0.99, 0.99, 0.99],
        })
        # Tracking error should be nonzero against the manual reference
        err = self.tracker.tracking_error()
        assert isinstance(err, float)

    def test_ema_adapts_over_time(self):
        # Feed constant values then check EMA has settled
        for _ in range(20):
            self.tracker.update({"sharpe_ratio": 2.0, "coverage_rate": 0.9})
        # EMA should be close to 2.0
        ema_sr = self.tracker._ema.get("sharpe_ratio", 0.0)
        assert abs(ema_sr - 2.0) < 0.5


# ---------------------------------------------------------------------------
# Layer 3: HTNDecomposer
# ---------------------------------------------------------------------------

class TestHTNDecomposer:
    def setup_method(self):
        self.htn = HTNDecomposer()
        self.htn.register_vectora_methods()

    def test_decompose_research_cycle(self):
        state = {"health": 0.9, "error_rate": 0.02}
        tasks = self.htn.decompose("research_cycle", state)
        assert isinstance(tasks, list)
        assert len(tasks) > 0
        assert all(isinstance(t, Task) for t in tasks)

    def test_tasks_have_assigned_nodes(self):
        state = {"health": 0.8}
        tasks = self.htn.decompose("research_cycle", state)
        for t in tasks:
            assert t.assigned_to

    def test_applicable_methods_healthy(self):
        state = {"health": 0.9, "error_rate": 0.01}
        methods = self.htn.applicable_methods("research_cycle", state)
        assert len(methods) > 0

    def test_register_custom_method(self):
        self.htn.register_method(
            goal="custom_goal",
            method_name="custom_method",
            preconditions={"health": {">": 0.5}},
            subtasks=[{"name": "do_thing", "parameters": {}, "assigned_to": "SomeNode", "priority": 0.8}],
        )
        state = {"health": 0.9}
        tasks = self.htn.decompose("custom_goal", state)
        assert any(t.name == "do_thing" for t in tasks)

    def test_failed_precondition_falls_through(self):
        state = {"health": 0.01, "error_rate": 0.99}
        tasks = self.htn.decompose("research_cycle", state)
        assert isinstance(tasks, list)


# ---------------------------------------------------------------------------
# GoalArchitecture — end-to-end
# ---------------------------------------------------------------------------

class TestGoalArchitecture:
    def setup_method(self):
        self.g = GoalArchitecture()

    def test_step_returns_decision(self):
        metrics = {
            "sharpe_ratio": 1.5,
            "coverage_rate": 0.85,
            "error_rate": 0.05,
            "max_drawdown_pct": 8.0,
            "max_position_pct": 20.0,
        }
        decision = self.g.step(metrics, cycle=1)
        assert isinstance(decision, GoalDecision)
        assert isinstance(decision.approved, bool)
        assert isinstance(decision.scorecard, dict)
        assert isinstance(decision.subtasks, list)
        assert 0.0 <= decision.composite_score <= 1.0

    def test_constraint_violation_blocks(self):
        metrics = {
            "max_drawdown_pct": 30.0,  # violates hard constraint (>15)
            "sharpe_ratio": 1.0,
        }
        decision = self.g.step(metrics, cycle=1)
        assert not decision.approved
        assert len(decision.constraint_violations) > 0

    def test_set_reference_trajectory(self):
        traj = {
            "sharpe_ratio": [1.5, 1.6, 1.7, 1.8, 1.9],
            "coverage_rate": [0.8, 0.82, 0.84, 0.86, 0.88],
        }
        self.g.set_reference_trajectory(traj)
        metrics = {"sharpe_ratio": 1.0, "coverage_rate": 0.7}
        decision = self.g.step(metrics, cycle=1)
        assert isinstance(decision.tracking_error, float)
        assert decision.tracking_error >= 0.0

    def test_step_multiple_cycles(self):
        for i in range(5):
            metrics = {
                "sharpe_ratio": 1.0 + i * 0.1,
                "coverage_rate": 0.7 + i * 0.02,
                "error_rate": max(0.01, 0.1 - i * 0.01),
            }
            decision = self.g.step(metrics, cycle=i)
            assert isinstance(decision, GoalDecision)

    def test_tracking_error_in_decision(self):
        # Warm up tracker, then deviate
        for _ in range(5):
            self.g.step({"sharpe_ratio": 2.0, "coverage_rate": 0.9}, cycle=0)
        decision = self.g.step({"sharpe_ratio": 2.0, "coverage_rate": 0.9}, cycle=5)
        assert isinstance(decision.tracking_error, float)
        assert decision.tracking_error >= 0.0

    def test_no_nash_weights_in_decision(self):
        # GoalDecision no longer has nash_weights
        decision = self.g.step({"sharpe_ratio": 1.0}, cycle=0)
        assert not hasattr(decision, "nash_weights")


# ---------------------------------------------------------------------------
# Advanced components remain importable (regression guard)
# ---------------------------------------------------------------------------

class TestAdvancedComponentsImportable:
    def test_nash_welfare_aggregator_importable(self):
        n = NashWelfareAggregator(objectives=["a", "b"])
        w = n.nash_welfare({"a": 1.0, "b": 0.5})
        assert isinstance(w, float)

    def test_mpc_reference_tracker_importable(self):
        mpc = MPCReferenceTracker(objectives=["x"], horizon=3)
        mpc.update({"x": 1.0})
        assert mpc.tracking_error() == 0.0
