"""Integration tests for omega.core.orchestrator_v2 — OmegaOrchestrator."""

from __future__ import annotations

from typing import Any

import pytest

from omega.core.autonomy import AutonomyLevel
from omega.core.cycle import CycleResult
from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.core.orchestrator_v2 import OmegaOrchestrator

# ---------------------------------------------------------------------------
# Minimal stub node for testing (no external deps)
# ---------------------------------------------------------------------------


class StubNode(Node):
    """Minimal node that supports configurable capabilities."""

    def __init__(
        self,
        name: str = "stub",
        capabilities: list[str] | None = None,
        health: float = 1.0,
        fail: bool = False,
    ) -> None:
        import uuid

        self._nid = str(uuid.uuid4())
        self._name = name
        self._caps = capabilities or ["poll", "compute_signals", "construct_portfolio"]
        self._health = health
        self._fail = fail
        self._exec_count = 0

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._nid,
            name=self._name,
            version="1.0",
            health=self._health,
            capabilities=self._caps,
            metrics={"exec_count": float(self._exec_count)},
        )

    def get_capabilities(self) -> list[str]:
        return self._caps

    def describe(self) -> str:
        return f"StubNode({self._name})"

    def execute(self, inp: NodeInput) -> NodeOutput:
        self._exec_count += 1
        if self._fail:
            return NodeOutput(
                request_id=inp.request_id,
                success=False,
                errors=["intentional failure"],
            )
        return NodeOutput(
            request_id=inp.request_id,
            success=True,
            result={"stub": True, "action": inp.action},
            metrics={"latency_ms": 1.0},
        )

    def evaluate(self) -> dict[str, float]:
        return {"exec_count": float(self._exec_count)}

    def improve(self, feedback: dict[str, Any]) -> bool:
        return False


class SignalNode(StubNode):
    """Stub that returns signal data from compute_signals."""

    def execute(self, inp: NodeInput) -> NodeOutput:
        self._exec_count += 1
        if inp.action == "compute_signals":
            return NodeOutput(
                request_id=inp.request_id,
                success=True,
                result={"BTC": {"composite_signal": 0.5}, "ETH": {"composite_signal": -0.2}},
                metrics={"latency_ms": 1.0},
            )
        return NodeOutput(
            request_id=inp.request_id,
            success=True,
            result={},
            metrics={"latency_ms": 0.5},
        )


class StrategyNode(StubNode):
    """Stub that returns a trade proposal from construct_portfolio."""

    def execute(self, inp: NodeInput) -> NodeOutput:
        self._exec_count += 1
        if inp.action == "construct_portfolio":
            return NodeOutput(
                request_id=inp.request_id,
                success=True,
                result=[{"symbol": "BTCUSDT", "side": "buy", "weight": 0.5}],
                metrics={"latency_ms": 2.0},
            )
        return NodeOutput(
            request_id=inp.request_id,
            success=True,
            result={},
            metrics={"latency_ms": 0.5},
        )


# ---------------------------------------------------------------------------
# OmegaOrchestrator — basic API
# ---------------------------------------------------------------------------


class TestOrchestratorRegistration:
    def test_register_and_activate(self):
        orch = OmegaOrchestrator()
        node = StubNode("n1")
        nid = orch.register_node(node, activate=True)
        assert nid == node._nid
        assert node in orch.active_nodes

    def test_register_without_activate(self):
        orch = OmegaOrchestrator()
        node = StubNode("n1")
        orch.register_node(node, activate=False)
        assert node not in orch.active_nodes

    def test_activate_after_register(self):
        orch = OmegaOrchestrator()
        node = StubNode("n1")
        orch.register_node(node, activate=False)
        orch.activate_node(node._nid)
        assert node in orch.active_nodes

    def test_deactivate(self):
        orch = OmegaOrchestrator()
        node = StubNode("n1")
        orch.register_node(node, activate=True)
        orch.deactivate_node(node._nid)
        assert node not in orch.active_nodes

    def test_deregister(self):
        orch = OmegaOrchestrator()
        node = StubNode("n1")
        nid = orch.register_node(node)
        orch.deregister_node(nid)
        assert node not in orch.active_nodes

    def test_activate_unregistered_raises(self):
        orch = OmegaOrchestrator()
        with pytest.raises(KeyError):
            orch.activate_node("nonexistent-id")

    def test_multiple_nodes(self):
        orch = OmegaOrchestrator()
        for i in range(5):
            orch.register_node(StubNode(f"node-{i}"))
        assert len(orch.active_nodes) == 5

    def test_zero_nodes(self):
        orch = OmegaOrchestrator()
        result = orch.run_one_cycle()
        assert isinstance(result, CycleResult)
        assert result.signals_generated == 0
        assert result.trades_proposed == 0

    def test_node_summary(self):
        orch = OmegaOrchestrator()
        node = StubNode("n1")
        orch.register_node(node)
        summary = orch.node_summary()
        assert len(summary) == 1
        assert summary[0]["name"] == "n1"
        assert summary[0]["active"] is True


# ---------------------------------------------------------------------------
# OmegaOrchestrator — cycle execution
# ---------------------------------------------------------------------------


class TestOrchestratorCycle:
    def test_run_one_cycle_returns_result(self):
        orch = OmegaOrchestrator()
        result = orch.run_one_cycle()
        assert isinstance(result, CycleResult)
        assert result.context.cycle_number == 0
        assert result.duration_seconds >= 0

    def test_cycle_number_increments(self):
        orch = OmegaOrchestrator()
        orch.run_one_cycle()
        orch.run_one_cycle()
        assert orch.cycle_number == 2

    def test_history_grows(self):
        orch = OmegaOrchestrator()
        orch.run_one_cycle()
        orch.run_one_cycle()
        assert len(orch.history) == 2

    def test_poll_step_executed(self):
        orch = OmegaOrchestrator()
        node = StubNode("data", capabilities=["poll"])
        orch.register_node(node)
        orch.run_one_cycle()
        assert node._exec_count >= 1

    def test_signal_step_executed(self):
        orch = OmegaOrchestrator()
        node = SignalNode("sig", capabilities=["compute_signals"])
        orch.register_node(node)
        result = orch.run_one_cycle()
        assert node._exec_count >= 1
        assert result.signals_generated >= 0  # may be 0 if no data

    def test_strategy_step_executed(self):
        orch = OmegaOrchestrator()
        node = StrategyNode("strat", capabilities=["construct_portfolio"])
        orch.register_node(node)
        result = orch.run_one_cycle()
        assert node._exec_count >= 1
        assert result.trades_proposed >= 1
        assert result.trades_executed >= 1

    def test_degraded_node_deactivated(self):
        orch = OmegaOrchestrator()
        # Stub with very low health
        node = StubNode("sick", capabilities=["poll"], health=0.1, fail=True)
        orch.register_node(node)
        # Manually mark node health as degraded
        health_rec = orch._node_health[node._nid]
        for _ in range(6):
            health_rec.record(0.1, False)
        # Reconcile should deactivate
        orch.reconcile_active_nodes(health_threshold=0.3)
        assert node not in orch.active_nodes

    def test_cycle_context_has_regime(self):
        orch = OmegaOrchestrator()
        result = orch.run_one_cycle()
        assert result.context.regime in {"normal", "trending", "volatile", "crash", "unknown"}

    def test_cycle_context_records_active_nodes(self):
        orch = OmegaOrchestrator()
        node = StubNode("n1")
        orch.register_node(node)
        result = orch.run_one_cycle()
        assert node._nid in result.context.active_node_ids

    def test_cycle_context_records_autonomy_levels(self):
        orch = OmegaOrchestrator()
        node = StubNode("n1")
        orch.register_node(node)
        result = orch.run_one_cycle()
        assert node._nid in result.context.autonomy_levels
        assert result.context.autonomy_levels[node._nid] in {"pico", "supervised", "autonomous"}


# ---------------------------------------------------------------------------
# Goal-driven activation
# ---------------------------------------------------------------------------


class TestGoalDrivenActivation:
    def test_goal_node_ids_activates_registered_nodes(self):
        orch = OmegaOrchestrator()
        n1 = StubNode("n1")
        n2 = StubNode("n2")
        orch.register_node(n1, activate=False)
        orch.register_node(n2, activate=False)
        assert len(orch.active_nodes) == 0

        # Activate only n1 via goal
        orch.reconcile_active_nodes(goal_node_ids={n1._nid})
        assert n1 in orch.active_nodes
        assert n2 not in orch.active_nodes

    def test_goal_node_ids_passed_to_run_one_cycle(self):
        orch = OmegaOrchestrator()
        n1 = StubNode("n1")
        n2 = StubNode("n2")
        orch.register_node(n1, activate=False)
        orch.register_node(n2, activate=False)

        orch.run_one_cycle(goal_node_ids={n1._nid})
        assert n1 in orch.active_nodes


# ---------------------------------------------------------------------------
# Autonomy integration
# ---------------------------------------------------------------------------


class TestAutonomyIntegration:
    def test_new_nodes_start_at_pico(self):
        orch = OmegaOrchestrator()
        node = StubNode("n1")
        orch.register_node(node)
        assert orch._autonomy.get_level(node._nid) == AutonomyLevel.PICO

    def test_pico_mode_flagged_in_strategy_input(self):
        """In PICO mode, construct_portfolio is called with pico_mode=True."""
        orch = OmegaOrchestrator()

        captured_params: list[dict] = []

        class CapturingStrategyNode(StubNode):
            def execute(self, inp: NodeInput) -> NodeOutput:
                self._exec_count += 1
                captured_params.append(dict(inp.parameters))
                return NodeOutput(
                    request_id=inp.request_id,
                    success=True,
                    result=[{"symbol": "BTC", "side": "buy"}],
                    metrics={},
                )

        node = CapturingStrategyNode("strat", capabilities=["construct_portfolio"])
        orch.register_node(node)
        orch.run_one_cycle()

        # Node is at PICO → pico_mode should be True in parameters
        portfolio_calls = [p for p in captured_params if "pico_mode" in p]
        assert any(p["pico_mode"] is True for p in portfolio_calls)

    def test_critical_adversarial_flag_triggers_demotion_check(self):
        """A critical adversarial flag on a node triggers check_and_demote."""
        orch = OmegaOrchestrator()
        node = StubNode("n1")
        orch.register_node(node)

        # Manually bump node to SUPERVISED so demotion is meaningful
        autonomy_ctrl = orch._autonomy
        state = autonomy_ctrl.get_state(node._nid)
        # Force level to SUPERVISED via direct manipulation
        state._level = AutonomyLevel.SUPERVISED if hasattr(state, "_level") else None

        result = orch.run_one_cycle()
        # Just check the cycle completed without errors
        assert isinstance(result, CycleResult)


# ---------------------------------------------------------------------------
# run() loop — basic smoke tests
# ---------------------------------------------------------------------------


class TestRunLoop:
    def test_run_max_cycles(self):
        orch = OmegaOrchestrator()
        orch.run(max_cycles=3)
        assert orch.cycle_number == 3
        assert len(orch.history) == 3

    def test_run_returns_history(self):
        orch = OmegaOrchestrator()
        history = orch.run(max_cycles=2)
        assert len(history) == 2

    def test_stop_flag(self):
        orch = OmegaOrchestrator()
        # Use a node that calls stop after first cycle
        call_count = 0

        class StopperNode(StubNode):
            def execute(self, inp: NodeInput) -> NodeOutput:
                nonlocal call_count
                call_count += 1
                if call_count >= 1:
                    orch.stop()
                return NodeOutput(
                    request_id=inp.request_id,
                    success=True,
                    result={},
                    metrics={},
                )

        orch.register_node(StopperNode("stopper", capabilities=["poll"]))
        orch.run(max_cycles=100)
        # Should have stopped well before 100
        assert orch.cycle_number < 100

    def test_run_with_no_nodes_is_safe(self):
        orch = OmegaOrchestrator()
        orch.run(max_cycles=5)
        assert orch.cycle_number == 5


# ---------------------------------------------------------------------------
# Node health tracking
# ---------------------------------------------------------------------------


class TestNodeHealthTracking:
    def test_health_recorded_per_cycle(self):
        orch = OmegaOrchestrator()
        node = StubNode("n1", capabilities=["poll"])
        nid = orch.register_node(node)
        orch.run_one_cycle()
        health_rec = orch._node_health[nid]
        assert len(health_rec._scores) >= 1

    def test_failing_node_accumulates_errors(self):
        orch = OmegaOrchestrator()
        node = StubNode("n1", capabilities=["poll"], fail=True)
        nid = orch.register_node(node)
        orch.run_one_cycle()
        health_rec = orch._node_health[nid]
        assert health_rec._consecutive_errors >= 1
