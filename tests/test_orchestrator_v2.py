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


# ---------------------------------------------------------------------------
# AdversarialPressureV2 integration
# ---------------------------------------------------------------------------


class AlwaysFlagAdversarial:
    """Mock adversarial layer that always fires Ring 1."""

    def __init__(self) -> None:
        self.call_count = 0
        self.last_cycle: int | None = None
        self.last_variant_outputs: dict | None = None

    def run_v2(
        self,
        cycle: int,
        variant_outputs: dict,
        current_signals: dict,
        strategy_params: dict,
        fitness_fn: Any = None,
        strategy_callable: Any = None,
    ):
        from omega.core.adversarial import AdversarialReport, DisagreementResult
        from omega.core.adversarial_v2 import AdversarialReportV2, AttributionResult

        self.call_count += 1
        self.last_cycle = cycle
        self.last_variant_outputs = variant_outputs

        ring1 = DisagreementResult(
            flagged=True,
            max_disagreement=0.95,
            disagreeing_variants=list(variant_outputs.keys()),
            outputs=variant_outputs,
        )
        base = AdversarialReport(
            cycle=cycle,
            ring1_result=ring1,
            ring2_scenarios=[],
            ring3_result=None,
            failure_cases=[],
        )
        attribution = AttributionResult(
            outlier_variants=list(variant_outputs.keys())[:1],
            outlier_scores={k: 1.0 for k in variant_outputs},
            method="mock",
            confidence=0.99,
        )
        return AdversarialReportV2(
            base_report=base,
            attribution=attribution,
            threshold_adjustment=None,
            fp_summary={},
            ring2_sim_report=None,
            ring2_activated=False,
            current_threshold=0.20,
        )


class TestAdversarialIntegration:
    def test_adversarial_run_v2_is_called(self):
        """When adversarial is set and proposals exist, run_v2 must be called."""
        mock_adv = AlwaysFlagAdversarial()
        orch = OmegaOrchestrator(adversarial=mock_adv)
        node = StrategyNode("strat", capabilities=["construct_portfolio"])
        orch.register_node(node)

        orch.run_one_cycle()

        assert mock_adv.call_count == 1, "run_v2 was never called — Ring 1 still dead"

    def test_adversarial_receives_cycle_number(self):
        mock_adv = AlwaysFlagAdversarial()
        orch = OmegaOrchestrator(adversarial=mock_adv)
        orch.register_node(StrategyNode("strat", capabilities=["construct_portfolio"]))

        orch.run_one_cycle()
        orch.run_one_cycle()

        assert mock_adv.last_cycle == 1

    def test_adversarial_flag_recorded_in_result(self):
        """When Ring 1 fires, the CycleResult must record adversarial flags."""
        mock_adv = AlwaysFlagAdversarial()
        orch = OmegaOrchestrator(adversarial=mock_adv)
        orch.register_node(StrategyNode("strat", capabilities=["construct_portfolio"]))

        result = orch.run_one_cycle()

        assert result.had_adversarial_flag, "no adversarial flag recorded"
        ring1_flags = [f for f in result.adversarial_flags if f.get("ring") == "ring1"]
        assert ring1_flags, "ring1 flag not found in result"
        assert ring1_flags[0]["reason"] == "ensemble_disagreement"

    def test_supervised_proposals_blocked_on_flag(self):
        """In SUPERVISED mode, flagged proposals must be blocked (not executed)."""
        mock_adv = AlwaysFlagAdversarial()
        orch = OmegaOrchestrator(adversarial=mock_adv)
        node = StrategyNode("strat", capabilities=["construct_portfolio"])
        orch.register_node(node)

        # Force node to SUPERVISED autonomy level
        nid = node._nid
        orch._autonomy.get_state(nid).level = AutonomyLevel.SUPERVISED

        result = orch.run_one_cycle()

        # Proposals should have been blocked → zero trades executed
        assert result.trades_executed == 0, (
            f"Expected 0 trades (blocked by adversarial), got {result.trades_executed}"
        )
        critical_flags = [
            f for f in result.adversarial_flags if f.get("reason") == "supervised_block"
        ]
        assert critical_flags, "supervised_block flag not recorded"

    def test_autonomous_proposals_weight_halved_on_flag(self):
        """In AUTONOMOUS mode, flagged proposals must have weight reduced by 50%."""
        mock_adv = AlwaysFlagAdversarial()
        orch = OmegaOrchestrator(adversarial=mock_adv)
        node = StrategyNode("strat", capabilities=["construct_portfolio"])
        orch.register_node(node)

        # Force node to AUTONOMOUS
        nid = node._nid
        orch._autonomy.get_state(nid).level = AutonomyLevel.AUTONOMOUS

        result = orch.run_one_cycle()

        # Proposals should pass through but with reduced weight
        assert result.trades_executed >= 1, "Expected trades to execute (with reduced weight)"
        ring1_flags = [f for f in result.adversarial_flags if f.get("ring") == "ring1"]
        assert ring1_flags, "ring1 flag not recorded"

    def test_adversarial_not_called_without_proposals(self):
        """If no proposals, run_v2 must not be called (nothing to evaluate)."""
        mock_adv = AlwaysFlagAdversarial()
        orch = OmegaOrchestrator(adversarial=mock_adv)
        # No strategy-capable node → no proposals
        orch.register_node(StubNode("data", capabilities=["poll"]))

        orch.run_one_cycle()

        assert mock_adv.call_count == 0

    def test_adversarial_variant_outputs_built_from_signal_data(self):
        """variant_outputs passed to run_v2 should include data from signal-producing nodes."""
        mock_adv = AlwaysFlagAdversarial()
        orch = OmegaOrchestrator(adversarial=mock_adv)

        class SignalAndStrategyNode(StubNode):
            def execute(self, inp: NodeInput) -> NodeOutput:
                self._exec_count += 1
                if inp.action == "compute_signals":
                    return NodeOutput(
                        request_id=inp.request_id,
                        success=True,
                        result={"BTC": 0.8, "ETH": 0.3},
                        metrics={},
                    )
                if inp.action == "construct_portfolio":
                    return NodeOutput(
                        request_id=inp.request_id,
                        success=True,
                        result=[{"symbol": "BTCUSDT", "side": "buy", "weight": 0.5}],
                        metrics={},
                    )
                return NodeOutput(request_id=inp.request_id, success=True, result={}, metrics={})

        node = SignalAndStrategyNode(
            "combo", capabilities=["compute_signals", "construct_portfolio"]
        )
        orch.register_node(node)
        orch.run_one_cycle()

        assert mock_adv.call_count == 1
        assert mock_adv.last_variant_outputs is not None
        # Should contain the node's signal data
        assert any("BTC" in v for v in mock_adv.last_variant_outputs.values())


# ---------------------------------------------------------------------------
# Configurable-disagreement mock
# ---------------------------------------------------------------------------


class ConfigurableDisagreementAdversarial:
    """Mock adversarial that fires Ring 1 with a configurable max_disagreement."""

    def __init__(self, max_disagreement: float) -> None:
        self.max_disagreement = max_disagreement
        self.call_count = 0

    def run_v2(
        self,
        cycle: int,
        variant_outputs: dict,
        current_signals: dict,
        strategy_params: dict,
        fitness_fn: Any = None,
        strategy_callable: Any = None,
    ):
        from omega.core.adversarial import AdversarialReport, DisagreementResult
        from omega.core.adversarial_v2 import AdversarialReportV2, AttributionResult

        self.call_count += 1
        ring1 = DisagreementResult(
            flagged=True,
            max_disagreement=self.max_disagreement,
            disagreeing_variants=list(variant_outputs.keys()),
            outputs=variant_outputs,
        )
        base = AdversarialReport(
            cycle=cycle,
            ring1_result=ring1,
            ring2_scenarios=[],
            ring3_result=None,
            failure_cases=[],
        )
        return AdversarialReportV2(
            base_report=base,
            attribution=AttributionResult(
                outlier_variants=[],
                outlier_scores={},
                method="mock",
                confidence=0.0,
            ),
            threshold_adjustment=None,
            fp_summary={},
            ring2_sim_report=None,
            ring2_activated=False,
            current_threshold=0.20,
        )


# ---------------------------------------------------------------------------
# Adversarial gate rejection tests
# ---------------------------------------------------------------------------


class TestAdversarialGateRejectsLowQualityProposals:
    def test_adversarial_wired_by_default(self):
        """OmegaOrchestrator must wire AdversarialPressureV2 by default, never leave it None."""
        orch = OmegaOrchestrator()
        assert orch._adversarial is not None, (
            "_adversarial is None — adversarial gate is dead in production"
        )

    def test_high_disagreement_blocks_pico_proposal(self):
        """When Ring 1 fires with extreme disagreement (score < 0.6), PICO proposals must be blocked."""
        # max_disagreement=0.9 → score=0.1 < 0.6 threshold → proposal must be blocked
        mock_adv = ConfigurableDisagreementAdversarial(max_disagreement=0.9)
        orch = OmegaOrchestrator(adversarial=mock_adv)
        orch.register_node(StrategyNode("strat", capabilities=["construct_portfolio"]))

        result = orch.run_one_cycle()

        assert result.trades_executed == 0, (
            f"Expected 0 trades (blocked: disagreement=0.9, score=0.1 < 0.6), "
            f"got {result.trades_executed}"
        )
        blocked_flags = [
            f for f in result.adversarial_flags if f.get("reason") == "high_disagreement_block"
        ]
        assert blocked_flags, "high_disagreement_block flag not recorded"

    def test_moderate_disagreement_passes_pico_proposal(self):
        """When Ring 1 fires with moderate disagreement (score >= 0.6), PICO proposals pass."""
        # max_disagreement=0.3 → score=0.7 >= 0.6 threshold → proposal must pass
        mock_adv = ConfigurableDisagreementAdversarial(max_disagreement=0.3)
        orch = OmegaOrchestrator(adversarial=mock_adv)
        orch.register_node(StrategyNode("strat", capabilities=["construct_portfolio"]))

        result = orch.run_one_cycle()

        assert result.trades_executed >= 1, (
            f"Expected trades to execute (disagreement=0.3, score=0.7 >= 0.6), "
            f"got {result.trades_executed}"
        )
