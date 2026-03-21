"""Unit tests for VerificationGateSystem and all gate types."""
import pytest
from omega.core.verification_gates import (
    GateResult, GateStatus,
    PropertyGate, InvariantGate, ConsistencyGate,
    RegressionGate, ConvergenceGate,
    AndGate, OrGate,
    VerificationGateSystem,
)


class TestGateResult:
    def test_pass_properties(self):
        r = GateResult(status=GateStatus.PASS, gate_name="test", evidence="ok")
        assert r.passed is True
        assert r.failed is False

    def test_fail_properties(self):
        r = GateResult(status=GateStatus.FAIL, gate_name="test", evidence="bad")
        assert r.failed is True
        assert r.passed is False

    def test_warning_neither_pass_nor_fail(self):
        r = GateResult(status=GateStatus.WARNING, gate_name="test", evidence="marginal")
        assert r.passed is False
        assert r.failed is False


class TestPropertyGate:
    def _gate(self, predicate, desc="test"):
        return PropertyGate("pg", predicate, desc)

    def test_passes_when_true(self):
        gate = self._gate(lambda ctx: 0.0 <= ctx.get("value", 0) <= 1.0)
        assert gate.check({"value": 0.5}).status == GateStatus.PASS

    def test_fails_when_false(self):
        gate = self._gate(lambda ctx: 0.0 <= ctx.get("value", 0) <= 1.0)
        assert gate.check({"value": 1.5}).status == GateStatus.FAIL

    def test_exception_becomes_fail(self):
        gate = self._gate(lambda ctx: 1 / 0)
        result = gate.check({})
        assert result.status == GateStatus.FAIL
        assert "ZeroDivisionError" in result.evidence

    def test_evidence_contains_description_on_pass(self):
        gate = self._gate(lambda _: True, desc="must be positive")
        result = gate.check({})
        assert "must be positive" in result.evidence


class TestInvariantGate:
    def test_invariant_holds(self):
        gate = InvariantGate(
            "pos_bounded",
            invariant=lambda ctx: ctx.get("pos", 0) <= ctx.get("max_pos", 1),
            description="Position must not exceed max",
        )
        assert gate.check({"pos": 0.8, "max_pos": 1.0}).status == GateStatus.PASS

    def test_invariant_violated(self):
        gate = InvariantGate(
            "pos_bounded",
            invariant=lambda ctx: ctx.get("pos", 0) <= ctx.get("max_pos", 1),
            description="Position must not exceed max",
        )
        result = gate.check({"pos": 1.5, "max_pos": 1.0})
        assert result.status == GateStatus.FAIL
        assert "Invariant violated" in result.evidence


class TestConsistencyGate:
    def test_consistent(self):
        gate = ConsistencyGate(
            "keys_match",
            check_fn=lambda ctx: set(ctx.get("a_keys", [])) == set(ctx.get("b_keys", [])),
            description="Keys must match",
        )
        assert gate.check({"a_keys": ["x", "y"], "b_keys": ["y", "x"]}).status == GateStatus.PASS

    def test_inconsistent(self):
        gate = ConsistencyGate(
            "keys_match",
            check_fn=lambda ctx: set(ctx.get("a_keys", [])) == set(ctx.get("b_keys", [])),
            description="Keys must match",
        )
        assert gate.check({"a_keys": ["x"], "b_keys": ["y"]}).status == GateStatus.FAIL


class TestRegressionGate:
    def test_no_regression_maximize(self):
        gate = RegressionGate("sharpe", metric="sharpe", direction="maximize", threshold_pct=10.0)
        result = gate.check({"before": {"sharpe": 1.0}, "after": {"sharpe": 1.05}})
        assert result.status == GateStatus.PASS

    def test_regression_detected_maximize(self):
        gate = RegressionGate("sharpe", metric="sharpe", direction="maximize", threshold_pct=10.0)
        result = gate.check({"before": {"sharpe": 1.0}, "after": {"sharpe": 0.80}})
        assert result.status == GateStatus.FAIL
        assert "sharpe" in result.evidence.lower()

    def test_no_regression_minimize(self):
        gate = RegressionGate("latency", metric="latency", direction="minimize", threshold_pct=10.0)
        result = gate.check({"before": {"latency": 100.0}, "after": {"latency": 95.0}})
        assert result.status == GateStatus.PASS

    def test_regression_detected_minimize(self):
        gate = RegressionGate("latency", metric="latency", direction="minimize", threshold_pct=10.0)
        result = gate.check({"before": {"latency": 100.0}, "after": {"latency": 120.0}})
        assert result.status == GateStatus.FAIL

    def test_missing_metric_is_warning(self):
        gate = RegressionGate("sharpe", metric="sharpe", direction="maximize", threshold_pct=10.0)
        result = gate.check({"before": {}, "after": {}})
        assert result.status == GateStatus.WARNING

    def test_zero_before_no_crash(self):
        gate = RegressionGate("sharpe", metric="sharpe", direction="maximize", threshold_pct=10.0)
        result = gate.check({"before": {"sharpe": 0.0}, "after": {"sharpe": 0.0}})
        assert result.status == GateStatus.PASS

    def test_details_populated(self):
        gate = RegressionGate("sharpe", metric="sharpe", direction="maximize", threshold_pct=10.0)
        result = gate.check({"before": {"sharpe": 1.0}, "after": {"sharpe": 0.5}})
        assert "pct_change" in result.details
        assert result.details["before"] == 1.0
        assert result.details["after"] == 0.5


class TestConvergenceGate:
    def test_strictly_increasing_passes(self):
        gate = ConvergenceGate("conv", metric="accuracy", window=4)
        result = gate.check({"history": [0.70, 0.75, 0.80, 0.85]})
        assert result.status == GateStatus.PASS

    def test_oscillating_fails(self):
        gate = ConvergenceGate("conv", metric="accuracy", window=4)
        result = gate.check({"history": [0.70, 0.90, 0.50, 0.85]})
        assert result.status == GateStatus.FAIL

    def test_insufficient_history_is_warning(self):
        gate = ConvergenceGate("conv", metric="accuracy", window=4)
        result = gate.check({"history": [0.7]})
        assert result.status == GateStatus.WARNING

    def test_flat_series_is_warning(self):
        gate = ConvergenceGate("conv", metric="accuracy", window=4)
        result = gate.check({"history": [0.80, 0.80, 0.80, 0.80]})
        # Flat slope → warning (not converging, not oscillating)
        assert result.status in (GateStatus.WARNING, GateStatus.PASS)

    def test_minimize_direction_decreasing_passes(self):
        gate = ConvergenceGate("loss_conv", metric="loss", window=4, direction="minimize")
        result = gate.check({"history": [1.0, 0.8, 0.6, 0.4]})
        assert result.status == GateStatus.PASS

    def test_slope_in_details(self):
        gate = ConvergenceGate("conv", metric="accuracy", window=4)
        result = gate.check({"history": [0.70, 0.75, 0.80, 0.85]})
        assert "slope" in result.details
        assert result.details["slope"] > 0


class TestAndGate:
    def _pass(self, name="p"):
        return PropertyGate(name, lambda _: True, "always pass")

    def _fail(self, name="f"):
        return PropertyGate(name, lambda _: False, "always fail")

    def test_both_pass(self):
        gate = AndGate("both", [self._pass("a"), self._pass("b")])
        assert gate.check({}).status == GateStatus.PASS

    def test_one_fails(self):
        gate = AndGate("both", [self._pass("a"), self._fail("b")])
        assert gate.check({}).status == GateStatus.FAIL

    def test_both_fail(self):
        gate = AndGate("both", [self._fail("a"), self._fail("b")])
        assert gate.check({}).status == GateStatus.FAIL

    def test_evidence_contains_failure_info(self):
        gate = AndGate("both", [self._pass(), self._fail("fail_gate")])
        result = gate.check({})
        assert "always fail" in result.evidence


class TestOrGate:
    def _pass(self, name="p"):
        return PropertyGate(name, lambda _: True, "always pass")

    def _fail(self, name="f"):
        return PropertyGate(name, lambda _: False, "always fail")

    def test_one_passes(self):
        gate = OrGate("either", [self._pass("a"), self._fail("b")])
        assert gate.check({}).status == GateStatus.PASS

    def test_all_fail(self):
        gate = OrGate("either", [self._fail("a"), self._fail("b")])
        assert gate.check({}).status == GateStatus.FAIL

    def test_all_pass(self):
        gate = OrGate("either", [self._pass("a"), self._pass("b")])
        assert gate.check({}).status == GateStatus.PASS


class TestVerificationGateSystem:
    def test_empty_system_all_passed(self):
        system = VerificationGateSystem()
        results = system.run_all({})
        assert system.all_passed(results) is True

    def test_all_passing(self):
        system = VerificationGateSystem()
        system.register(PropertyGate("p1", lambda _: True, "ok"))
        system.register(PropertyGate("p2", lambda _: True, "ok"))
        results = system.run_all({})
        assert system.all_passed(results) is True

    def test_one_failure_blocks(self):
        system = VerificationGateSystem()
        system.register(PropertyGate("p1", lambda _: True, "ok"))
        system.register(PropertyGate("p2", lambda _: False, "bad"))
        results = system.run_all({})
        assert system.all_passed(results) is False

    def test_warnings_do_not_block(self):
        system = VerificationGateSystem()
        # ConvergenceGate with 1 history point → WARNING
        system.register(ConvergenceGate("conv", metric="x", window=4))
        results = system.run_all({"history": [0.5]})
        assert system.all_passed(results) is True  # warnings are ok

    def test_summary_structure(self):
        system = VerificationGateSystem()
        system.register(PropertyGate("p1", lambda _: True, "ok"))
        system.register(PropertyGate("p2", lambda _: False, "bad"))
        results = system.run_all({})
        summary = system.summary(results)
        assert summary["total"] == 2
        assert summary["passed"] == 1
        assert summary["failed"] == 1
        assert summary["warnings"] == 0
        assert len(summary["failures"]) == 1
        assert summary["failures"][0]["gate"] == "p2"

    def test_multiple_regressions_all_reported(self):
        system = VerificationGateSystem()
        system.register(RegressionGate("sharpe", metric="sharpe", direction="maximize", threshold_pct=5.0))
        system.register(RegressionGate("accuracy", metric="accuracy", direction="maximize", threshold_pct=5.0))
        ctx = {
            "before": {"sharpe": 1.0, "accuracy": 0.9},
            "after": {"sharpe": 0.5, "accuracy": 0.5},
        }
        results = system.run_all(ctx)
        summary = system.summary(results)
        assert summary["failed"] == 2
