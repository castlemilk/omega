"""Tests for omega.core.autonomy — GraduatedAutonomyController."""

from __future__ import annotations

import os

import pytest

from omega.core.autonomy import (
    AutonomyLevel,
    AutonomyThresholds,
    GraduatedAutonomyController,
    NodeAutonomyState,
    PerformanceMetric,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres integration tests",
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def thresholds() -> AutonomyThresholds:
    return AutonomyThresholds(
        min_cycles=3,
        metrics=[
            PerformanceMetric("sharpe", "higher_is_better", 0.5, 0.0),
            PerformanceMetric("max_drawdown", "lower_is_better", 0.15, 0.20),
        ],
    )


@pytest.fixture
def controller(thresholds: AutonomyThresholds) -> GraduatedAutonomyController:
    return GraduatedAutonomyController(store=None, thresholds=thresholds)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_node_starts_at_pico(controller: GraduatedAutonomyController) -> None:
    state = controller.register_node("node-1")
    assert state.level == AutonomyLevel.PICO
    assert state.cycles_at_level == 0
    assert state.total_cycles == 0


def test_register_idempotent(controller: GraduatedAutonomyController) -> None:
    controller.register_node("node-x")
    controller.record_cycle("node-x", sharpe=1.0, drawdown=0.05)
    state = controller.register_node("node-x")  # re-register
    assert state.cycles_at_level == 1  # existing state preserved


# ---------------------------------------------------------------------------
# Cycle recording
# ---------------------------------------------------------------------------


def test_record_cycle_increments_counters(controller: GraduatedAutonomyController) -> None:
    controller.register_node("node-2")
    controller.record_cycle("node-2", sharpe=1.0, drawdown=0.05)
    state = controller.get_state("node-2")
    assert state.total_cycles == 1
    assert state.cycles_at_level == 1


def test_record_cycle_tracks_max_drawdown(controller: GraduatedAutonomyController) -> None:
    controller.register_node("node-3")
    controller.record_cycle("node-3", sharpe=1.0, drawdown=0.05)
    controller.record_cycle("node-3", sharpe=1.0, drawdown=0.12)
    controller.record_cycle("node-3", sharpe=1.0, drawdown=0.03)
    state = controller.get_state("node-3")
    assert state.max_drawdown_observed == pytest.approx(0.12)


def test_record_cycle_ema_sharpe(controller: GraduatedAutonomyController) -> None:
    controller.register_node("node-ema")
    # After many cycles with sharpe=1.0, rolling_sharpe should converge toward 1.0
    for _ in range(50):
        controller.record_cycle("node-ema", sharpe=1.0, drawdown=0.01)
    state = controller.get_state("node-ema")
    assert state.rolling_sharpe > 0.8


# ---------------------------------------------------------------------------
# Promotion — success path
# ---------------------------------------------------------------------------


def _qualify_node(
    controller: GraduatedAutonomyController,
    node_id: str,
    cycles: int = 5,
    sharpe: float = 1.5,
    drawdown: float = 0.05,
) -> None:
    controller.register_node(node_id)
    for _ in range(cycles):
        controller.record_cycle(node_id, sharpe=sharpe, drawdown=drawdown)


def test_promote_pico_to_supervised(controller: GraduatedAutonomyController) -> None:
    _qualify_node(controller, "node-p2s")
    result = controller.promote_node("node-p2s")
    assert result.success
    assert result.changed
    assert result.previous_level == AutonomyLevel.PICO
    assert result.new_level == AutonomyLevel.SUPERVISED


def test_promote_supervised_to_autonomous(controller: GraduatedAutonomyController) -> None:
    _qualify_node(controller, "node-s2a")
    controller.promote_node("node-s2a")  # → SUPERVISED
    # Reset cycles_at_level by recording more cycles at supervised level
    for _ in range(5):
        controller.record_cycle("node-s2a", sharpe=1.5, drawdown=0.05)
    result = controller.promote_node("node-s2a")
    assert result.success
    assert result.new_level == AutonomyLevel.AUTONOMOUS


def test_promote_records_history(controller: GraduatedAutonomyController) -> None:
    _qualify_node(controller, "node-hist")
    controller.promote_node("node-hist")
    state = controller.get_state("node-hist")
    assert len(state.promotion_history) == 1
    assert state.promotion_history[0]["from"] == "pico"
    assert state.promotion_history[0]["to"] == "supervised"


def test_promote_resets_cycles_at_level(controller: GraduatedAutonomyController) -> None:
    _qualify_node(controller, "node-reset")
    controller.promote_node("node-reset")
    state = controller.get_state("node-reset")
    assert state.cycles_at_level == 0


# ---------------------------------------------------------------------------
# Promotion — failure paths
# ---------------------------------------------------------------------------


def test_promote_fails_insufficient_cycles(controller: GraduatedAutonomyController) -> None:
    controller.register_node("node-few")
    controller.record_cycle("node-few", sharpe=2.0, drawdown=0.01)  # only 1 cycle
    result = controller.promote_node("node-few")
    assert not result.success
    assert "insufficient_cycles" in result.reason


def test_promote_fails_low_sharpe(controller: GraduatedAutonomyController) -> None:
    _qualify_node(controller, "node-lowsharpe", sharpe=0.1)
    result = controller.promote_node("node-lowsharpe")
    assert not result.success
    assert "sharpe_too_low" in result.reason


def test_promote_fails_high_drawdown(controller: GraduatedAutonomyController) -> None:
    _qualify_node(controller, "node-hidd", drawdown=0.25)
    result = controller.promote_node("node-hidd")
    assert not result.success
    assert "drawdown_too_high" in result.reason


def test_promote_at_max_level_fails(controller: GraduatedAutonomyController) -> None:
    _qualify_node(controller, "node-max")
    controller.promote_node("node-max")  # → SUPERVISED
    for _ in range(5):
        controller.record_cycle("node-max", sharpe=1.5, drawdown=0.05)
    controller.promote_node("node-max")  # → AUTONOMOUS
    result = controller.promote_node("node-max")  # already at top
    assert not result.success
    assert result.reason == "already_at_max_level"


# ---------------------------------------------------------------------------
# Demotion
# ---------------------------------------------------------------------------


def test_demote_supervised_to_pico(controller: GraduatedAutonomyController) -> None:
    _qualify_node(controller, "node-d1")
    controller.promote_node("node-d1")  # → SUPERVISED
    result = controller.demote_node("node-d1", reason="manual")
    assert result.success
    assert result.new_level == AutonomyLevel.PICO


def test_demote_autonomous_to_supervised(controller: GraduatedAutonomyController) -> None:
    _qualify_node(controller, "node-d2")
    controller.promote_node("node-d2")  # → SUPERVISED
    for _ in range(5):
        controller.record_cycle("node-d2", sharpe=1.5, drawdown=0.05)
    controller.promote_node("node-d2")  # → AUTONOMOUS
    result = controller.demote_node("node-d2", reason="drawdown_exceeded")
    assert result.success
    assert result.new_level == AutonomyLevel.SUPERVISED


def test_demote_at_pico_fails(controller: GraduatedAutonomyController) -> None:
    controller.register_node("node-pico-floor")
    result = controller.demote_node("node-pico-floor", reason="test")
    assert not result.success
    assert result.reason == "already_at_min_level"


def test_demote_records_history(controller: GraduatedAutonomyController) -> None:
    _qualify_node(controller, "node-dhist")
    controller.promote_node("node-dhist")
    controller.demote_node("node-dhist", reason="sharpe_below_threshold")
    state = controller.get_state("node-dhist")
    assert len(state.demotion_history) == 1
    assert state.demotion_history[0]["reason"] == "sharpe_below_threshold"


# ---------------------------------------------------------------------------
# check_and_demote
# ---------------------------------------------------------------------------


def test_check_and_demote_on_low_sharpe(controller: GraduatedAutonomyController) -> None:
    _qualify_node(controller, "node-cad1")
    controller.promote_node("node-cad1")
    transition = controller.check_and_demote("node-cad1", current_sharpe=-0.5)
    assert transition is not None
    assert transition.reason == "sharpe_below_threshold"


def test_check_and_demote_on_da_critical(controller: GraduatedAutonomyController) -> None:
    _qualify_node(controller, "node-cad2")
    controller.promote_node("node-cad2")
    transition = controller.check_and_demote("node-cad2", da_critical=True)
    assert transition is not None
    assert transition.reason == "da_critical_challenge"


def test_check_and_demote_no_trigger(controller: GraduatedAutonomyController) -> None:
    _qualify_node(controller, "node-cad3")
    controller.promote_node("node-cad3")
    transition = controller.check_and_demote(
        "node-cad3", current_sharpe=1.5, current_drawdown=0.05
    )
    assert transition is None


# ---------------------------------------------------------------------------
# Brain application
# ---------------------------------------------------------------------------


class _FakeNode:
    def __init__(self) -> None:
        from omega.core.brain import AnthropicBrain, BrainConfig

        self.brain = AnthropicBrain(BrainConfig(provider="anthropic", model="claude-sonnet-4-6"))


def test_apply_brain_pico_forces_nobrain(controller: GraduatedAutonomyController) -> None:
    from omega.core.brain import NoBrain

    node = _FakeNode()
    controller.register_node("node-brain-pico")
    controller.apply_brain_for_level(node, "node-brain-pico")
    assert isinstance(node.brain, NoBrain)


def test_apply_brain_supervised_keeps_existing(controller: GraduatedAutonomyController) -> None:
    node = _FakeNode()
    _qualify_node(controller, "node-brain-sup")
    controller.promote_node("node-brain-sup")  # → SUPERVISED
    original_brain = node.brain
    controller.apply_brain_for_level(node, "node-brain-sup")
    assert node.brain is original_brain  # unchanged


# ---------------------------------------------------------------------------
# Convenience predicates
# ---------------------------------------------------------------------------


def test_is_pico(controller: GraduatedAutonomyController) -> None:
    controller.register_node("node-pred")
    assert controller.is_pico("node-pred")
    assert not controller.is_supervised("node-pred")
    assert not controller.is_autonomous("node-pred")


# ---------------------------------------------------------------------------
# NodeAutonomyState serialisation
# ---------------------------------------------------------------------------


def test_node_autonomy_state_roundtrip() -> None:
    state = NodeAutonomyState(
        node_id="n1",
        level=AutonomyLevel.SUPERVISED,
        cycles_at_level=5,
        total_cycles=15,
        metric_values={"sharpe": 0.8, "max_drawdown": 0.07},
        promotion_history=[{"from": "pico", "to": "supervised"}],
    )
    recovered = NodeAutonomyState.from_dict(state.to_dict())
    assert recovered.node_id == state.node_id
    assert recovered.level == state.level
    assert recovered.rolling_sharpe == pytest.approx(state.rolling_sharpe)
    assert len(recovered.promotion_history) == 1


# ---------------------------------------------------------------------------
# StateStore integration (in-memory SQLite)
# ---------------------------------------------------------------------------


def test_persist_and_reload_via_store() -> None:
    from omega.core.state_store import SQLiteBackend

    store = SQLiteBackend(db_path=":memory:")
    ctrl = GraduatedAutonomyController(store=store, thresholds=AutonomyThresholds(min_cycles=2))
    ctrl.register_node("node-persist")
    ctrl.record_cycle("node-persist", sharpe=1.5, drawdown=0.05)
    ctrl.record_cycle("node-persist", sharpe=1.5, drawdown=0.05)

    # Create a fresh controller pointing at the same store — cache is empty
    ctrl2 = GraduatedAutonomyController(store=store, thresholds=AutonomyThresholds(min_cycles=2))
    state = ctrl2.get_state("node-persist")
    assert state.total_cycles == 2
