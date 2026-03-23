"""Unit + integration tests for DevilsAdvocateNode."""

import os

import pytest

from omega.core.challenge_registry import ChallengeRegistry, ChallengeSeverity, ChallengeStatus
from omega.core.node import NodeInput
from omega.core.verification_gates import (
    PropertyGate,
    RegressionGate,
    VerificationGateSystem,
)
from omega.nodes.devils_advocate import DevilsAdvocateNode, ReviewMode

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres integration tests",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_node(seed=False):
    registry = ChallengeRegistry()
    gates = VerificationGateSystem()
    if seed:
        registry.seed_initial_challenges()
    return DevilsAdvocateNode(registry=registry, gate_system=gates), registry, gates


def exec_node(node, action, **params):
    inp = NodeInput(action=action, parameters=params)
    return node.execute(inp)


# ---------------------------------------------------------------------------
# Node interface
# ---------------------------------------------------------------------------


class TestDevilsAdvocateInterface:
    def test_get_state_structure(self):
        node, _, _ = make_node()
        state = node.get_state()
        assert state.name == "DevilsAdvocateNode"
        assert 0.0 <= state.health <= 1.0
        assert state.version == "1.0"

    def test_get_capabilities_complete(self):
        node, _, _ = make_node()
        caps = node.get_capabilities()
        for mode in ReviewMode:
            assert mode.value in caps

    def test_describe_mentions_adversarial(self):
        node, _, _ = make_node()
        desc = node.describe().lower()
        assert any(kw in desc for kw in ["challenge", "adversarial", "devil"])

    def test_evaluate_metrics_present(self):
        node, _, _ = make_node()
        metrics = node.evaluate()
        assert "open_challenges" in metrics
        assert "resolution_rate" in metrics
        assert "blocking_challenges" in metrics
        assert "critical_open" in metrics
        assert "veto_count" in metrics

    def test_improve_always_returns_false(self):
        node, _, _ = make_node()
        assert node.improve({}) is False
        assert node.improve({"anything": True}) is False

    def test_unknown_action_fails_gracefully(self):
        node, _, _ = make_node()
        out = exec_node(node, "nonexistent_action")
        assert out.success is False
        assert len(out.errors) > 0
        assert "nonexistent_action" in out.errors[0]

    def test_latency_in_output_metrics(self):
        node, _, _ = make_node()
        out = exec_node(node, "architectural_review")
        assert "latency_ms" in out.metrics
        assert out.metrics["latency_ms"] >= 0.0

    def test_execution_count_increments(self):
        node, _, _ = make_node()
        exec_node(node, "architectural_review")
        exec_node(node, "complexity_audit")
        state_after = node.get_state()
        assert state_after.metadata["execution_count"] == 2


# ---------------------------------------------------------------------------
# Operating modes
# ---------------------------------------------------------------------------


class TestArchitecturalReview:
    def test_returns_report(self):
        node, reg, _ = make_node()
        reg.add("orchestrator", ChallengeSeverity.HIGH, "Test challenge", "E")
        out = exec_node(node, "architectural_review", subsystem="orchestrator")
        assert out.success
        report = out.result
        assert report["mode"] == "architectural_review"
        assert "challenges" in report
        assert "gate_results" in report
        assert "veto" in report
        assert "verdict" in report

    def test_filters_by_subsystem(self):
        node, reg, _ = make_node()
        reg.add("orchestrator.routing", ChallengeSeverity.HIGH, "Routing issue", "E")
        reg.add("memory.decay", ChallengeSeverity.MEDIUM, "Memory issue", "E")
        out = exec_node(node, "architectural_review", subsystem="orchestrator")
        assert out.result["open_count"] == 1

    def test_no_veto_when_no_critical_open(self):
        node, reg, _ = make_node()
        reg.add("orchestrator", ChallengeSeverity.HIGH, "High but not critical", "E")
        out = exec_node(node, "architectural_review")
        assert out.result["veto"] is False
        assert out.result["verdict"] == "APPROVED"

    def test_veto_when_critical_open(self):
        node, reg, _ = make_node()
        reg.add("alignment", ChallengeSeverity.CRITICAL, "EWC failure mode", "E")
        out = exec_node(node, "architectural_review")
        assert out.result["veto"] is True
        assert out.result["verdict"] == "VETOED"

    def test_veto_increments_counter(self):
        node, reg, _ = make_node()
        reg.add("alignment", ChallengeSeverity.CRITICAL, "Blocker", "E")
        exec_node(node, "architectural_review")
        exec_node(node, "architectural_review")
        assert node.get_state().metadata["veto_count"] == 2


class TestImplementationAudit:
    def test_returns_report(self):
        node, _reg, _ = make_node()
        out = exec_node(node, "implementation_audit", subsystem="memory")
        assert out.success
        assert out.result["mode"] == "implementation_audit"
        assert "challenges" in out.result
        assert "open_count" in out.result

    def test_resolved_challenges_excluded(self):
        node, reg, _ = make_node()
        cid = reg.add("memory.decay", ChallengeSeverity.HIGH, "Decay issue", "E")
        reg.update_status(cid, ChallengeStatus.RESOLVED)
        out = exec_node(node, "implementation_audit", subsystem="memory")
        assert out.result["open_count"] == 0


class TestAssumptionStressTest:
    def test_returns_report(self):
        node, _, _ = make_node()
        out = exec_node(node, "assumption_stress_test")
        assert out.success
        assert out.result["mode"] == "assumption_stress_test"
        assert "critical_violations" in out.result
        assert "high_violations" in out.result
        assert "assumptions_broken" in out.result

    def test_broken_verdict_when_critical_open(self):
        node, reg, _ = make_node()
        reg.add("alignment", ChallengeSeverity.CRITICAL, "EWC", "E")
        out = exec_node(node, "assumption_stress_test")
        assert out.result["verdict"] == "BROKEN"
        assert len(out.result["critical_violations"]) == 1

    def test_holding_verdict_when_all_resolved(self):
        node, reg, _ = make_node()
        cid = reg.add("alignment", ChallengeSeverity.CRITICAL, "EWC", "E")
        reg.update_status(cid, ChallengeStatus.RESOLVED)
        out = exec_node(node, "assumption_stress_test")
        assert out.result["verdict"] == "HOLDING"

    def test_seeded_challenges_are_broken(self):
        node, _reg, _ = make_node(seed=True)
        out = exec_node(node, "assumption_stress_test")
        # With seeded challenges including CRITICAL ones, verdict must be BROKEN
        assert out.result["verdict"] == "BROKEN"
        assert out.result["assumptions_broken"] > 0


class TestRegressionHunt:
    def test_clean_when_no_regression(self):
        node, _reg, gates = make_node()
        gates.register(
            RegressionGate("sharpe", metric="sharpe", direction="maximize", threshold_pct=10.0)
        )
        out = exec_node(node, "regression_hunt", before={"sharpe": 1.0}, after={"sharpe": 1.1})
        assert out.success
        assert out.result["verdict"] == "CLEAN"
        assert out.result["regressions_found"] == 0

    def test_regression_detected_and_challenge_raised(self):
        node, reg, gates = make_node()
        gates.register(
            RegressionGate("sharpe", metric="sharpe", direction="maximize", threshold_pct=10.0)
        )
        out = exec_node(node, "regression_hunt", before={"sharpe": 1.0}, after={"sharpe": 0.5})
        assert out.success
        assert out.result["verdict"] == "REGRESSION_DETECTED"
        assert out.result["regressions_found"] >= 1
        # Challenge auto-raised
        regression_chs = reg.all_challenges(subsystem="regression")
        assert len(regression_chs) >= 1

    def test_multiple_regressions_all_raise_challenges(self):
        node, _reg, gates = make_node()
        gates.register(
            RegressionGate("sharpe", metric="sharpe", direction="maximize", threshold_pct=5.0)
        )
        gates.register(
            RegressionGate("accuracy", metric="accuracy", direction="maximize", threshold_pct=5.0)
        )
        out = exec_node(
            node,
            "regression_hunt",
            before={"sharpe": 1.0, "accuracy": 0.9},
            after={"sharpe": 0.5, "accuracy": 0.5},
        )
        assert out.result["regressions_found"] == 2
        assert len(out.result["new_challenges_raised"]) == 2


class TestComplexityAudit:
    def test_returns_report(self):
        node, _, _ = make_node()
        out = exec_node(node, "complexity_audit")
        assert out.success
        assert out.result["mode"] == "complexity_audit"
        assert "complexity_challenge_count" in out.result
        assert "recommendation" in out.result

    def test_seeded_challenges_flag_complexity(self):
        node, _reg, _ = make_node(seed=True)
        out = exec_node(node, "complexity_audit")
        # Seeded challenges include ones about O(5n) overhead, layers, etc.
        assert out.result["complexity_challenge_count"] >= 1


# ---------------------------------------------------------------------------
# Integration test: DA catches a real regression
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_catches_sharpe_regression_end_to_end(self):
        """Full flow: gate registered → regression occurs → challenge raised → report shows failure."""
        registry = ChallengeRegistry()
        gates = VerificationGateSystem()
        gates.register(
            RegressionGate(
                "sharpe_regression",
                metric="sharpe_ratio",
                direction="maximize",
                threshold_pct=15.0,
            )
        )
        node = DevilsAdvocateNode(registry=registry, gate_system=gates)

        # Simulate improvement that regresses Sharpe by 33%
        out = node.execute(
            NodeInput(
                action="regression_hunt",
                parameters={
                    "before": {"sharpe_ratio": 1.5},
                    "after": {"sharpe_ratio": 1.0},
                },
            )
        )

        assert out.success
        assert out.result["gate_results"]["failed"] >= 1
        assert "sharpe" in out.result["gate_results"]["failures"][0]["evidence"].lower()
        assert out.result["regressions_found"] >= 1

        # Verify challenge was persisted
        regression_chs = registry.all_challenges(subsystem="regression")
        assert len(regression_chs) >= 1
        assert "sharpe" in regression_chs[0].description.lower()

    def test_no_veto_when_gates_pass_and_no_critical(self):
        registry = ChallengeRegistry()
        gates = VerificationGateSystem()
        gates.register(PropertyGate("health_ok", lambda ctx: True, "health is fine"))
        node = DevilsAdvocateNode(registry=registry, gate_system=gates)

        out = node.execute(NodeInput(action="architectural_review", parameters={}))
        assert out.success
        assert out.result["veto"] is False

    def test_evaluate_metrics_reflect_registry_state(self):
        registry = ChallengeRegistry()
        registry.seed_initial_challenges()
        node = DevilsAdvocateNode(registry=registry)

        metrics = node.evaluate()
        assert metrics["open_challenges"] >= 16
        assert metrics["resolution_rate"] == 0.0
        assert metrics["blocking_challenges"] == 1.0  # CRITICAL challenges present
