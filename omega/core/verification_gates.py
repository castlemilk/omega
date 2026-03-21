"""
omega.core.verification_gates
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Composable gate objects that verify system properties before committing improvements.

Gate types:
  PropertyGate    — arbitrary predicate on a context dict
  InvariantGate   — system invariant that must hold across all states
  ConsistencyGate — cross-subsystem consistency check
  RegressionGate  — before/after metric regression detection
  ConvergenceGate — statistical test that a metric series is converging

Composition:
  AndGate — all children must pass
  OrGate  — at least one child must pass

Each gate has a check(context) method returning GateResult(PASS/FAIL/WARNING).
Gates can be registered with VerificationGateSystem and run collectively.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List


class GateStatus(str, Enum):
    PASS    = "pass"
    FAIL    = "fail"
    WARNING = "warning"


@dataclass
class GateResult:
    status: GateStatus
    gate_name: str
    evidence: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == GateStatus.PASS

    @property
    def failed(self) -> bool:
        return self.status == GateStatus.FAIL


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class Gate(ABC):
    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def check(self, context: Dict[str, Any]) -> GateResult:
        """Run the gate check and return a GateResult."""


# ---------------------------------------------------------------------------
# Concrete gates
# ---------------------------------------------------------------------------

class PropertyGate(Gate):
    """Passes when predicate(context) is True."""

    def __init__(self, name: str, predicate: Callable[[Dict], bool], description: str) -> None:
        super().__init__(name)
        self._predicate = predicate
        self._description = description

    def check(self, context: Dict[str, Any]) -> GateResult:
        try:
            ok = bool(self._predicate(context))
        except Exception as exc:
            return GateResult(
                status=GateStatus.FAIL,
                gate_name=self.name,
                evidence=f"{type(exc).__name__}: {exc}",
            )
        return GateResult(
            status=GateStatus.PASS if ok else GateStatus.FAIL,
            gate_name=self.name,
            evidence=self._description if ok else f"Property violated: {self._description}",
        )


class InvariantGate(Gate):
    """System invariant — must hold at all times."""

    def __init__(self, name: str, invariant: Callable[[Dict], bool], description: str) -> None:
        super().__init__(name)
        self._invariant = invariant
        self._description = description

    def check(self, context: Dict[str, Any]) -> GateResult:
        try:
            ok = bool(self._invariant(context))
        except Exception as exc:
            return GateResult(
                status=GateStatus.FAIL,
                gate_name=self.name,
                evidence=f"Invariant check raised: {type(exc).__name__}: {exc}",
            )
        return GateResult(
            status=GateStatus.PASS if ok else GateStatus.FAIL,
            gate_name=self.name,
            evidence=self._description if ok else f"Invariant violated: {self._description}",
        )


class ConsistencyGate(Gate):
    """Cross-subsystem consistency check."""

    def __init__(self, name: str, check_fn: Callable[[Dict], bool], description: str) -> None:
        super().__init__(name)
        self._check_fn = check_fn
        self._description = description

    def check(self, context: Dict[str, Any]) -> GateResult:
        try:
            ok = bool(self._check_fn(context))
        except Exception as exc:
            return GateResult(
                status=GateStatus.FAIL,
                gate_name=self.name,
                evidence=f"Consistency check raised: {exc}",
            )
        return GateResult(
            status=GateStatus.PASS if ok else GateStatus.FAIL,
            gate_name=self.name,
            evidence=self._description if ok else f"Consistency violated: {self._description}",
        )


class RegressionGate(Gate):
    """
    Detects metric regressions between before/after snapshots.

    Context keys: ``before`` and ``after`` — both dicts of metric_name → float.
    direction: "maximize" (regression = drop) or "minimize" (regression = rise).
    threshold_pct: percentage change that constitutes a regression.
    """

    def __init__(
        self,
        name: str,
        metric: str,
        direction: str = "maximize",
        threshold_pct: float = 10.0,
    ) -> None:
        super().__init__(name)
        self._metric = metric
        self._direction = direction
        self._threshold_pct = threshold_pct

    def check(self, context: Dict[str, Any]) -> GateResult:
        before = context.get("before", {})
        after = context.get("after", {})
        bval = before.get(self._metric)
        aval = after.get(self._metric)

        if bval is None or aval is None:
            return GateResult(
                status=GateStatus.WARNING,
                gate_name=self.name,
                evidence=f"Metric '{self._metric}' missing from before/after context",
            )

        pct_change = (aval - bval) / abs(bval) * 100.0 if bval != 0 else 0.0

        regressed = (
            pct_change < -self._threshold_pct
            if self._direction == "maximize"
            else pct_change > self._threshold_pct
        )

        if regressed:
            return GateResult(
                status=GateStatus.FAIL,
                gate_name=self.name,
                evidence=(
                    f"Regression: {self._metric} changed {pct_change:.1f}% "
                    f"(before={bval:.4f}, after={aval:.4f}, threshold={self._threshold_pct}%)"
                ),
                details={"metric": self._metric, "before": bval, "after": aval, "pct_change": pct_change},
            )
        return GateResult(
            status=GateStatus.PASS,
            gate_name=self.name,
            evidence=f"{self._metric} change={pct_change:+.1f}% within threshold",
            details={"metric": self._metric, "before": bval, "after": aval, "pct_change": pct_change},
        )


class ConvergenceGate(Gate):
    """
    Tests that a metric history is converging (positive linear slope for maximize).

    Context key: ``history`` — List[float] in iteration order.
    Requires at least ``window`` data points; returns WARNING if insufficient.
    FAIL if the series is oscillating (high mean abs diff relative to range).
    """

    def __init__(
        self,
        name: str,
        metric: str,
        window: int = 5,
        direction: str = "maximize",
    ) -> None:
        super().__init__(name)
        self._metric = metric
        self._window = window
        self._direction = direction

    def check(self, context: Dict[str, Any]) -> GateResult:
        history = context.get("history", [])
        if len(history) < self._window:
            return GateResult(
                status=GateStatus.WARNING,
                gate_name=self.name,
                evidence=f"Insufficient history: {len(history)} < {self._window} required",
            )

        recent = list(history[-self._window:])
        n = len(recent)
        mean_x = (n - 1) / 2.0
        mean_y = sum(recent) / n
        slope_num = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(recent))
        slope_den = sum((i - mean_x) ** 2 for i in range(n))
        slope = slope_num / slope_den if slope_den != 0 else 0.0

        converging = slope > 0 if self._direction == "maximize" else slope < 0

        rng = max(recent) - min(recent)
        mean_abs_diff = sum(abs(recent[i] - recent[i - 1]) for i in range(1, n)) / (n - 1)
        oscillating = rng > 0 and mean_abs_diff > rng * 0.5

        # Oscillation trumps positive slope — a series that swings wildly
        # cannot be trusted to be converging, even if the linear trend is up.
        if oscillating:
            return GateResult(
                status=GateStatus.FAIL,
                gate_name=self.name,
                evidence=f"{self._metric} oscillating (slope={slope:.4f}, mean_abs_diff={mean_abs_diff:.4f})",
                details={"slope": slope, "oscillating": True, "history_tail": recent},
            )
        if not converging:
            return GateResult(
                status=GateStatus.WARNING,
                gate_name=self.name,
                evidence=f"{self._metric} trend flat or diverging (slope={slope:.4f})",
                details={"slope": slope, "history_tail": recent},
            )
        return GateResult(
            status=GateStatus.PASS,
            gate_name=self.name,
            evidence=f"{self._metric} converging (slope={slope:+.4f})",
            details={"slope": slope, "history_tail": recent},
        )


# ---------------------------------------------------------------------------
# Composite gates
# ---------------------------------------------------------------------------

class AndGate(Gate):
    """All children must pass (warnings propagate if no failures)."""

    def __init__(self, name: str, children: List[Gate]) -> None:
        super().__init__(name)
        self._children = children

    def check(self, context: Dict[str, Any]) -> GateResult:
        results = [g.check(context) for g in self._children]
        failures = [r for r in results if r.failed]
        if failures:
            return GateResult(
                status=GateStatus.FAIL,
                gate_name=self.name,
                evidence="; ".join(r.evidence for r in failures),
            )
        warnings = [r for r in results if r.status == GateStatus.WARNING]
        if warnings:
            return GateResult(
                status=GateStatus.WARNING,
                gate_name=self.name,
                evidence="; ".join(r.evidence for r in warnings),
            )
        return GateResult(status=GateStatus.PASS, gate_name=self.name, evidence="All children passed")


class OrGate(Gate):
    """At least one child must pass."""

    def __init__(self, name: str, children: List[Gate]) -> None:
        super().__init__(name)
        self._children = children

    def check(self, context: Dict[str, Any]) -> GateResult:
        results = [g.check(context) for g in self._children]
        if any(r.passed for r in results):
            return GateResult(status=GateStatus.PASS, gate_name=self.name, evidence="At least one child passed")
        if any(r.status == GateStatus.WARNING for r in results):
            return GateResult(status=GateStatus.WARNING, gate_name=self.name, evidence="No child passed; some warnings")
        return GateResult(
            status=GateStatus.FAIL,
            gate_name=self.name,
            evidence="; ".join(r.evidence for r in results),
        )


# ---------------------------------------------------------------------------
# VerificationGateSystem
# ---------------------------------------------------------------------------

class VerificationGateSystem:
    """
    Registry of gates run collectively as a CI check or heartbeat step.

    Usage::
        system = VerificationGateSystem()
        system.register(PropertyGate(...))
        system.register(RegressionGate(...))
        results = system.run_all(context)
        if not system.all_passed(results):
            # veto the improvement
            ...
    """

    def __init__(self) -> None:
        self._gates: List[Gate] = []

    def register(self, gate: Gate) -> None:
        self._gates.append(gate)

    def run_all(self, context: Dict[str, Any]) -> List[GateResult]:
        return [g.check(context) for g in self._gates]

    def all_passed(self, results: List[GateResult]) -> bool:
        """Returns True if no gate failed (warnings are acceptable)."""
        return all(not r.failed for r in results)

    def summary(self, results: List[GateResult]) -> Dict[str, Any]:
        return {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if r.failed),
            "warnings": sum(1 for r in results if r.status == GateStatus.WARNING),
            "failures": [{"gate": r.gate_name, "evidence": r.evidence} for r in results if r.failed],
        }
