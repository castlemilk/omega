"""Tests for omega.core.improvement_engine and improvement_scheduler."""

from __future__ import annotations

import math

import pytest

from omega.core.bayesian_optimizer import CategoricalParam, ContinuousParam, DiscreteParam
from omega.core.improvement_engine import (
    ImprovementEngine,
    SyntheticEvaluator,
    _max_drawdown,
    _sharpe_ratio,
    composite_score,
)
from omega.core.improvement_scheduler import (
    ImprovementScheduler,
    NodeScheduleConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _basic_space():
    return [
        ContinuousParam("alpha", low=0.0, high=1.0),
        DiscreteParam("depth", low=1, high=5),
        CategoricalParam("mode", choices=["fast", "slow"]),
    ]


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------


class TestMetricHelpers:
    def test_sharpe_empty(self):
        assert _sharpe_ratio([]) == 0.0
        assert _sharpe_ratio([0.01]) == 0.0

    def test_sharpe_positive_returns(self):
        # Vary returns slightly so std > 0
        returns = [0.001 + i * 0.00001 for i in range(252)]
        s = _sharpe_ratio(returns)
        assert s > 0

    def test_sharpe_negative_returns(self):
        returns = [-0.001 - i * 0.00001 for i in range(252)]
        s = _sharpe_ratio(returns)
        assert s < 0

    def test_max_drawdown_flat(self):
        assert _max_drawdown([1.0, 1.0, 1.0]) == pytest.approx(0.0, abs=1e-10)

    def test_max_drawdown_always_rising(self):
        assert _max_drawdown([1.0, 1.1, 1.2, 1.3]) == pytest.approx(0.0, abs=1e-10)

    def test_max_drawdown_50_percent(self):
        curve = [1.0, 1.2, 0.6, 0.7]
        mdd = _max_drawdown(curve)
        # peak=1.2, trough=0.6 → dd = 0.5 → returned as -0.5
        assert mdd == pytest.approx(-0.5, abs=0.01)

    def test_composite_score_blends(self):
        cs = composite_score(sharpe=2.0, max_drawdown_negative=-0.1)
        # 0.7*2 + 0.3*(-0.1) = 1.4 - 0.03 = 1.37
        assert cs == pytest.approx(1.37, abs=1e-9)


# ---------------------------------------------------------------------------
# SyntheticEvaluator
# ---------------------------------------------------------------------------


class TestSyntheticEvaluator:
    def test_score_higher_near_target(self):
        ev = SyntheticEvaluator(target_params={"alpha": 0.5}, noise=0.0, seed=0)
        _, _ = ev.evaluate("n1", {"alpha": 0.5})
        score_near, _ = ev.evaluate("n1", {"alpha": 0.5})
        score_far, _ = ev.evaluate("n1", {"alpha": 0.99})
        assert score_near > score_far

    def test_returns_metrics_dict(self):
        ev = SyntheticEvaluator(seed=0)
        _, metrics = ev.evaluate("n1", {"alpha": 0.5})
        assert "sharpe" in metrics
        assert "max_drawdown" in metrics
        assert "composite" in metrics


# ---------------------------------------------------------------------------
# ImprovementEngine
# ---------------------------------------------------------------------------


class TestImprovementEngineRegistration:
    def test_register_and_is_registered(self):
        engine = ImprovementEngine()
        assert not engine.is_registered("n1")
        engine.register_node("n1", _basic_space())
        assert engine.is_registered("n1")

    def test_register_with_prior_trials(self):
        space = [ContinuousParam("x", 0.0, 1.0)]
        # scores: float(i) for i in range(15) → max = 14.0
        trials = [({"x": float(i) / 10}, float(i)) for i in range(15)]
        engine = ImprovementEngine()
        engine.register_node("n1", space, prior_trials=trials)
        assert engine.trial_count("n1") == 15
        assert engine.best_score("n1") == pytest.approx(14.0)

    def test_propose_returns_valid_params(self):
        engine = ImprovementEngine()
        engine.register_node("n1", _basic_space())
        params = engine.propose("n1")
        assert "alpha" in params
        assert "depth" in params
        assert "mode" in params
        assert 0.0 <= params["alpha"] <= 1.0
        assert 1 <= params["depth"] <= 5
        assert params["mode"] in ["fast", "slow"]

    def test_propose_raises_for_unregistered(self):
        engine = ImprovementEngine()
        with pytest.raises(KeyError):
            engine.propose("no-such-node")


class TestImprovementEngineOutcomes:
    def test_record_outcome_increments_trial_count(self):
        engine = ImprovementEngine()
        engine.register_node("n1", _basic_space())
        params = engine.propose("n1")
        engine.record_outcome("n1", params, score=0.5)
        assert engine.trial_count("n1") == 1

    def test_best_score_updates(self):
        engine = ImprovementEngine()
        engine.register_node("n1", _basic_space())
        p1 = engine.propose("n1")
        engine.record_outcome("n1", p1, score=0.1)
        p2 = engine.propose("n1")
        engine.record_outcome("n1", p2, score=0.9)
        assert engine.best_score("n1") == pytest.approx(0.9)
        assert engine.best_params("n1") == p2

    def test_best_score_is_max_not_last(self):
        engine = ImprovementEngine()
        engine.register_node("n1", _basic_space())
        for score in [0.5, 0.9, 0.3]:
            p = engine.propose("n1")
            engine.record_outcome("n1", p, score=score)
        assert engine.best_score("n1") == pytest.approx(0.9)

    def test_recent_trials_returns_n(self):
        engine = ImprovementEngine()
        engine.register_node("n1", _basic_space())
        for i in range(15):
            p = engine.propose("n1")
            engine.record_outcome("n1", p, score=float(i))
        trials = engine.recent_trials("n1", n=5)
        assert len(trials) == 5

    def test_evaluate_and_record_uses_evaluator(self):
        ev = SyntheticEvaluator(target_params={"alpha": 0.5}, noise=0.0, seed=0)
        engine = ImprovementEngine(evaluator=ev)
        engine.register_node("n1", _basic_space())
        trial = engine.evaluate_and_record("n1", {"alpha": 0.5, "depth": 3, "mode": "fast"})
        assert trial.score is not None
        assert "sharpe" in trial.metrics


class TestImprovementEngineLearning:
    def test_engine_improves_over_trials(self):
        """Best score should increase as TPE focuses on better regions."""
        space = [ContinuousParam("x", 0.0, 1.0)]
        ev = SyntheticEvaluator(target_params={"x": 0.7}, noise=0.0, seed=42)
        engine = ImprovementEngine(evaluator=ev, n_startup_trials=5, seed=42)
        engine.register_node("n1", space)

        initial_score = -math.inf
        final_score = -math.inf

        for i in range(50):
            engine.evaluate_and_record("n1", engine.propose("n1"))
            if i == 9:
                initial_score = engine.best_score("n1")
            final_score = engine.best_score("n1")

        assert final_score >= initial_score

    def test_sharpe_trend_stable_initially(self):
        engine = ImprovementEngine()
        engine.register_node("n1", _basic_space())
        assert engine.sharpe_trend("n1") == "stable"

    def test_all_node_ids(self):
        engine = ImprovementEngine()
        engine.register_node("a", _basic_space())
        engine.register_node("b", _basic_space())
        ids = engine.all_node_ids()
        assert "a" in ids
        assert "b" in ids


# ---------------------------------------------------------------------------
# ImprovementScheduler
# ---------------------------------------------------------------------------


class _FakeClock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class TestImprovementScheduler:
    def test_register_and_not_due_immediately_by_default(self):
        clock = _FakeClock(0.0)
        sched = ImprovementScheduler(clock=clock)
        sched.register("n1", NodeScheduleConfig("n1", interval_seconds=100.0))
        due = sched.due_nodes()
        assert "n1" not in due

    def test_register_run_immediately(self):
        clock = _FakeClock(0.0)
        sched = ImprovementScheduler(clock=clock)
        sched.register(
            "n1", NodeScheduleConfig("n1", interval_seconds=100.0), run_immediately=True
        )
        due = sched.due_nodes()
        assert "n1" in due

    def test_due_after_interval(self):
        clock = _FakeClock(0.0)
        sched = ImprovementScheduler(clock=clock)
        sched.register("n1", NodeScheduleConfig("n1", interval_seconds=60.0))
        clock.advance(61.0)
        due = sched.due_nodes()
        assert "n1" in due

    def test_not_due_before_interval(self):
        clock = _FakeClock(0.0)
        sched = ImprovementScheduler(clock=clock)
        sched.register("n1", NodeScheduleConfig("n1", interval_seconds=60.0))
        clock.advance(30.0)
        assert "n1" not in sched.due_nodes()

    def test_record_success_reschedules(self):
        clock = _FakeClock(0.0)
        sched = ImprovementScheduler(clock=clock)
        sched.register("n1", NodeScheduleConfig("n1", interval_seconds=60.0), run_immediately=True)
        sched.due_nodes()  # consume the immediate run
        sched.record_outcome("n1", success=True)
        # Should not be due immediately after success
        assert "n1" not in sched.due_nodes()
        # Should be due after interval
        clock.advance(65.0)
        assert "n1" in sched.due_nodes()

    def test_failure_triggers_cooldown(self):
        clock = _FakeClock(0.0)
        sched = ImprovementScheduler(clock=clock)
        sched.register(
            "n1",
            NodeScheduleConfig("n1", interval_seconds=60.0, cooldown_seconds=30.0),
            run_immediately=True,
        )
        sched.due_nodes()
        sched.record_outcome("n1", success=False)
        # Not due after 10s (within cooldown)
        clock.advance(10.0)
        assert "n1" not in sched.due_nodes()
        # Due after cooldown
        clock.advance(25.0)
        assert "n1" in sched.due_nodes()

    def test_exponential_backoff_on_repeated_failures(self):
        clock = _FakeClock(0.0)
        sched = ImprovementScheduler(clock=clock)
        sched.register(
            "n1",
            NodeScheduleConfig("n1", interval_seconds=3600.0, cooldown_seconds=60.0),
            run_immediately=True,
        )
        sched.due_nodes()

        # First failure: cooldown = 60
        sched.record_outcome("n1", success=False)
        clock.advance(65.0)
        assert "n1" in sched.due_nodes()

        # Second failure: cooldown = 120
        sched.record_outcome("n1", success=False)
        clock.advance(65.0)
        assert "n1" not in sched.due_nodes()
        clock.advance(60.0)
        assert "n1" in sched.due_nodes()

    def test_suspension_after_max_failures(self):
        clock = _FakeClock(0.0)
        sched = ImprovementScheduler(clock=clock)
        cfg = NodeScheduleConfig(
            "n1", interval_seconds=10.0, cooldown_seconds=1.0, max_consecutive_failures=3
        )
        sched.register("n1", cfg, run_immediately=True)

        for _ in range(3):
            sched.due_nodes()
            sched.record_outcome("n1", success=False)
            clock.advance(5.0)

        assert sched.is_suspended("n1")
        clock.advance(1000.0)
        # Even after a long wait, suspended node should not appear in due_nodes
        assert "n1" not in sched.due_nodes()

    def test_reset_failures_clears_suspension(self):
        clock = _FakeClock(0.0)
        sched = ImprovementScheduler(clock=clock)
        cfg = NodeScheduleConfig(
            "n1", interval_seconds=10.0, cooldown_seconds=1.0, max_consecutive_failures=2
        )
        sched.register("n1", cfg, run_immediately=True)
        sched.due_nodes()
        sched.record_outcome("n1", success=False)
        clock.advance(2.0)
        sched.due_nodes()
        sched.record_outcome("n1", success=False)
        assert sched.is_suspended("n1")

        sched.reset_failures("n1")
        assert not sched.is_suspended("n1")
        assert "n1" in sched.due_nodes()

    def test_priority_ordering(self):
        clock = _FakeClock(0.0)
        sched = ImprovementScheduler(clock=clock)
        sched.register("low", NodeScheduleConfig("low", priority=1.0), run_immediately=True)
        sched.register("high", NodeScheduleConfig("high", priority=5.0), run_immediately=True)
        due = sched.due_nodes()
        assert due.index("high") < due.index("low")

    def test_schedule_status_returns_all_nodes(self):
        clock = _FakeClock(0.0)
        sched = ImprovementScheduler(clock=clock)
        sched.register("a", NodeScheduleConfig("a"))
        sched.register("b", NodeScheduleConfig("b"))
        status = sched.schedule_status()
        node_ids = {s["node_id"] for s in status}
        assert {"a", "b"} == node_ids

    def test_next_due_returns_soonest(self):
        clock = _FakeClock(0.0)
        sched = ImprovementScheduler(clock=clock)
        sched.register("slow", NodeScheduleConfig("slow", interval_seconds=100.0))
        sched.register("fast", NodeScheduleConfig("fast", interval_seconds=30.0))
        node_id, _ = sched.next_due()
        # Both scheduled for the future; fast should come first
        assert node_id == "fast"

    def test_disabled_node_not_due(self):
        clock = _FakeClock(0.0)
        sched = ImprovementScheduler(clock=clock)
        cfg = NodeScheduleConfig("n1", interval_seconds=10.0, enabled=False)
        sched.register("n1", cfg, run_immediately=True)
        clock.advance(20.0)
        assert "n1" not in sched.due_nodes()

    def test_unregister_removes_node(self):
        clock = _FakeClock(0.0)
        sched = ImprovementScheduler(clock=clock)
        sched.register("n1", NodeScheduleConfig("n1", interval_seconds=10.0), run_immediately=True)
        sched.unregister("n1")
        assert "n1" not in sched.registered_nodes()
        clock.advance(20.0)
        assert "n1" not in sched.due_nodes()
