"""Tests for the Evaluator harness."""

import pytest
from omega.core.evaluator import Evaluator, GoalSpec, MetricSpec, _mean, _stddev, _pct_change
from omega.core.node import NodeState
from datetime import datetime


def _make_state(node_id="n1", metrics=None):
    return NodeState(
        node_id=node_id,
        name="TestNode",
        version="1.0",
        health=1.0,
        capabilities=["test"],
        metrics=metrics or {},
    )


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

class TestStats:
    def test_mean_empty(self):
        assert _mean([]) == 0.0

    def test_mean(self):
        assert _mean([1, 2, 3, 4]) == pytest.approx(2.5)

    def test_stddev_single(self):
        assert _stddev([5.0]) == 0.0

    def test_stddev(self):
        # sample stddev of [2,4,4,4,5,5,7,9] ≈ 2.138 (not 2.0 which is the population stddev)
        assert _stddev([2, 4, 4, 4, 5, 5, 7, 9]) == pytest.approx(2.138, rel=1e-3)

    def test_pct_change_zero_base(self):
        assert _pct_change(0, 10) == 0.0

    def test_pct_change_increase(self):
        assert _pct_change(100, 110) == pytest.approx(10.0)

    def test_pct_change_decrease(self):
        assert _pct_change(100, 90) == pytest.approx(-10.0)


# ---------------------------------------------------------------------------
# MetricSpec
# ---------------------------------------------------------------------------

class TestMetricSpec:
    def test_minimize_better(self):
        ms = MetricSpec("latency", direction="minimize")
        assert ms.is_better(0.5, 1.0)
        assert not ms.is_better(1.0, 0.5)

    def test_maximize_better(self):
        ms = MetricSpec("accuracy", direction="maximize")
        assert ms.is_better(0.9, 0.7)
        assert not ms.is_better(0.7, 0.9)

    def test_minimize_delta_positive_when_improved(self):
        ms = MetricSpec("latency", direction="minimize")
        assert ms.delta(new_val=1.0, old_val=2.0) == pytest.approx(1.0)

    def test_maximize_delta_positive_when_improved(self):
        ms = MetricSpec("accuracy", direction="maximize")
        assert ms.delta(new_val=0.9, old_val=0.7) == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# GoalSpec builder
# ---------------------------------------------------------------------------

class TestGoalSpec:
    def test_builder_chain(self):
        spec = (
            GoalSpec("fast_math")
            .add_metric("latency", "minimize", weight=2.0)
            .add_metric("accuracy", "maximize", weight=3.0)
        )
        assert len(spec.metrics) == 2
        assert spec.metrics[0].name == "latency"
        assert spec.metrics[1].weight == 3.0


# ---------------------------------------------------------------------------
# Evaluator — record & retrieve
# ---------------------------------------------------------------------------

class TestEvaluatorRecord:
    def setup_method(self):
        self.ev = Evaluator(db_path=":memory:")
        self.spec = GoalSpec("g").add_metric("accuracy", "maximize")
        self.ev.register_goal(self.spec)

    def test_record_iteration(self):
        states = [_make_state(metrics={"accuracy": 0.8})]
        iter_id = self.ev.record("g", 0, states, {"accuracy": 0.8})
        assert iter_id >= 1

    def test_record_multiple_iterations(self):
        for i, acc in enumerate([0.5, 0.7, 0.9]):
            self.ev.record("g", i, [], {"accuracy": acc})

        history = self.ev._store.get_system_metric_history("g", "accuracy")
        assert len(history) == 3
        assert [v for _, v in history] == pytest.approx([0.5, 0.7, 0.9])

    def test_has_improved_true(self):
        self.ev.record("g", 0, [], {"accuracy": 0.5})
        self.ev.record("g", 1, [], {"accuracy": 0.8})
        assert self.ev.has_improved("g", "accuracy", min_delta_pct=1.0)

    def test_has_improved_false_regression(self):
        self.ev.record("g", 0, [], {"accuracy": 0.9})
        self.ev.record("g", 1, [], {"accuracy": 0.8})
        assert not self.ev.has_improved("g", "accuracy", min_delta_pct=1.0)

    def test_has_improved_single_iteration(self):
        self.ev.record("g", 0, [], {"accuracy": 0.9})
        assert not self.ev.has_improved("g", "accuracy")

    def test_has_improved_minimize_direction(self):
        ev = Evaluator(":memory:")
        spec = GoalSpec("lat").add_metric("latency", "minimize")
        ev.register_goal(spec)
        ev.record("lat", 0, [], {"latency": 10.0})
        ev.record("lat", 1, [], {"latency": 5.0})
        assert ev.has_improved("lat", "latency", min_delta_pct=1.0)

    def test_score_higher_accuracy_better(self):
        s1 = self.ev.score("g", {"accuracy": 0.5})
        s2 = self.ev.score("g", {"accuracy": 0.9})
        assert s2 > s1

    def test_score_unknown_goal_returns_zero(self):
        assert self.ev.score("nonexistent_goal", {"accuracy": 0.9}) == 0.0


# ---------------------------------------------------------------------------
# Evaluator — reporting
# ---------------------------------------------------------------------------

class TestEvaluatorReport:
    def test_report_contains_goal(self):
        ev = Evaluator(":memory:")
        spec = GoalSpec("math").add_metric("accuracy", "maximize")
        ev.register_goal(spec)
        ev.record("math", 0, [], {"accuracy": 0.9})
        report = ev.report("math")
        assert "math" in report
        assert "accuracy" in report

    def test_report_shows_history(self):
        ev = Evaluator(":memory:")
        spec = GoalSpec("lat").add_metric("latency", "minimize")
        ev.register_goal(spec)
        for i, val in enumerate([10.0, 8.0, 5.0]):
            ev.record("lat", i, [], {"latency": val})
        report = ev.report("lat")
        assert "10.000" in report or "10" in report

    def test_report_without_registered_goal(self):
        ev = Evaluator(":memory:")
        report = ev.report("unknown")
        assert "unknown" in report


# ---------------------------------------------------------------------------
# Node metric history
# ---------------------------------------------------------------------------

class TestNodeMetricHistory:
    def test_node_metric_stored_and_retrieved(self):
        ev = Evaluator(":memory:")
        spec = GoalSpec("g").add_metric("accuracy", "maximize")
        ev.register_goal(spec)

        state = _make_state("node_abc", {"accuracy": 0.75})
        ev.record("g", 0, [state], {"accuracy": 0.75})

        history = ev._store.get_node_metric_history("g", "node_abc", "accuracy")
        assert len(history) == 1
        assert history[0][1] == pytest.approx(0.75)
