"""
omega.nodes.devils_advocate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The Devil's Advocate meta-node.

Purpose: challenge, stress-test, and poke holes in every architectural
decision, principle, and primitive in the system.

Operating modes (capabilities):
  architectural_review     — challenge high-level design decisions
  implementation_audit     — review code for gaps between spec and implementation
  assumption_stress_test   — enumerate implicit assumptions and try to break them
  regression_hunt          — detect regressions introduced by improvements
  complexity_audit         — flag over-engineering; suggest simpler alternatives

The node:
  - Runs VerificationGates against the provided before/after context
  - Queries ChallengeRegistry for open challenges against the target subsystem
  - Produces structured Challenge Reports with severity ratings
  - Vetoes improvements when CRITICAL open challenges exist or gates fail
  - Never self-improves — improve() always returns False
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from omega.core.challenge_registry import (
    Challenge,
    ChallengeRegistry,
    ChallengeSeverity,
    ChallengeStatus,
)
from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.core.verification_gates import VerificationGateSystem


class ReviewMode(str, Enum):
    ARCHITECTURAL_REVIEW   = "architectural_review"
    IMPLEMENTATION_AUDIT   = "implementation_audit"
    ASSUMPTION_STRESS_TEST = "assumption_stress_test"
    REGRESSION_HUNT        = "regression_hunt"
    COMPLEXITY_AUDIT       = "complexity_audit"


_CAPABILITIES = [m.value for m in ReviewMode]

# Keywords that flag complexity-related challenges
_COMPLEXITY_KEYWORDS = ["complex", "overhead", "o(", "yagni", "layer", "abstraction"]


class DevilsAdvocateNode(Node):
    """
    Meta-node whose entire purpose is adversarial: challenge every
    assumption, gate every improvement, and surface blind spots.

    The DA node does NOT self-improve. Its job is to make every other
    node prove it deserves to exist and improve.
    """

    def __init__(
        self,
        registry: ChallengeRegistry | None = None,
        gate_system: VerificationGateSystem | None = None,
        db_path: str = ":memory:",
    ) -> None:
        # Skip super().__init__() — no Brain for the devil's advocate
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._registry = registry or ChallengeRegistry(db_path=db_path)
        self._gates = gate_system or VerificationGateSystem()
        self._execution_count = 0
        self._veto_count = 0

    # ------------------------------------------------------------------
    # Node interface
    # ------------------------------------------------------------------

    def get_state(self) -> NodeState:
        metrics = self.evaluate()
        health = self._registry.resolution_rate()
        return NodeState(
            node_id=self._node_id,
            name="DevilsAdvocateNode",
            version=self._version,
            health=health,
            capabilities=_CAPABILITIES,
            metrics=metrics,
            metadata={
                "veto_count": self._veto_count,
                "execution_count": self._execution_count,
            },
        )

    def get_capabilities(self) -> list[str]:
        return _CAPABILITIES

    def describe(self) -> str:
        return (
            "The Devil's Advocate meta-node. Challenges every architectural decision, "
            "stress-tests assumptions, hunts for regressions, and vetoes improvements "
            "that fail verification gates or have unresolved CRITICAL challenges. "
            "It never self-improves — it challenges others."
        )

    def evaluate(self) -> dict[str, float]:
        open_chs = self._registry.open_challenges()
        critical_open = sum(1 for c in open_chs if c.severity == ChallengeSeverity.CRITICAL)
        return {
            "open_challenges": float(len(open_chs)),
            "critical_open": float(critical_open),
            "resolution_rate": self._registry.resolution_rate(),
            "blocking_challenges": float(self._registry.has_blocking_challenges()),
            "veto_count": float(self._veto_count),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        """Devil's advocate does not self-improve. It challenges others."""
        return False

    def execute(self, input: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1
        action = input.action
        params = input.parameters

        try:
            if action == ReviewMode.ARCHITECTURAL_REVIEW:
                result = self._architectural_review(params)
            elif action == ReviewMode.IMPLEMENTATION_AUDIT:
                result = self._implementation_audit(params)
            elif action == ReviewMode.ASSUMPTION_STRESS_TEST:
                result = self._assumption_stress_test(params)
            elif action == ReviewMode.REGRESSION_HUNT:
                result = self._regression_hunt(params)
            elif action == ReviewMode.COMPLEXITY_AUDIT:
                result = self._complexity_audit(params)
            else:
                return NodeOutput(
                    request_id=input.request_id,
                    success=False,
                    errors=[f"Unknown action '{action}'. Valid: {_CAPABILITIES}"],
                    metrics={"latency_ms": (time.perf_counter() - t0) * 1000},
                )
        except Exception as exc:
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[f"DevilsAdvocateNode.{action} raised: {type(exc).__name__}: {exc}"],
                metrics={"latency_ms": (time.perf_counter() - t0) * 1000},
            )

        return NodeOutput(
            request_id=input.request_id,
            success=True,
            result=result,
            metrics={"latency_ms": (time.perf_counter() - t0) * 1000, **self.evaluate()},
        )

    # ------------------------------------------------------------------
    # Operating modes
    # ------------------------------------------------------------------

    def _architectural_review(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Challenge high-level design decisions for a given subsystem.
        Returns open challenges + gate results + veto decision.
        """
        subsystem = params.get("subsystem", "")
        open_chs = self._registry.open_challenges()
        relevant = (
            [c for c in open_chs if subsystem.lower() in c.target_subsystem.lower()]
            if subsystem else open_chs
        )

        gate_results = self._gates.run_all(params)
        gate_summary = self._gates.summary(gate_results)

        veto = self._registry.has_blocking_challenges() or gate_summary["failed"] > 0
        if veto:
            self._veto_count += 1

        return {
            "mode": "architectural_review",
            "subsystem": subsystem,
            "challenges": [_ch_dict(c) for c in relevant],
            "open_count": len(relevant),
            "critical_count": sum(1 for c in relevant if c.severity == ChallengeSeverity.CRITICAL),
            "gate_results": gate_summary,
            "veto": veto,
            "verdict": "VETOED" if veto else "APPROVED",
        }

    def _implementation_audit(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Review code for gaps between spec and implementation.
        Queries challenges tagged to the subsystem.
        """
        subsystem = params.get("subsystem", "")
        all_chs = self._registry.all_challenges(subsystem=subsystem)
        open_chs = [c for c in all_chs if c.status == ChallengeStatus.OPEN]

        gate_results = self._gates.run_all(params)
        gate_summary = self._gates.summary(gate_results)

        return {
            "mode": "implementation_audit",
            "subsystem": subsystem,
            "challenges": [_ch_dict(c) for c in open_chs],
            "total_challenges": len(all_chs),
            "open_count": len(open_chs),
            "gate_results": gate_summary,
        }

    def _assumption_stress_test(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Enumerate implicit assumptions across the system and flag those
        with open critical/high challenges.
        """
        all_chs = self._registry.all_challenges()
        critical = [
            c for c in all_chs
            if c.severity == ChallengeSeverity.CRITICAL and c.status == ChallengeStatus.OPEN
        ]
        high = [
            c for c in all_chs
            if c.severity == ChallengeSeverity.HIGH and c.status == ChallengeStatus.OPEN
        ]

        gate_results = self._gates.run_all(params)
        gate_summary = self._gates.summary(gate_results)

        assumptions_broken = len(critical) + len(high)
        return {
            "mode": "assumption_stress_test",
            "critical_violations": [_ch_dict(c) for c in critical],
            "high_violations": [_ch_dict(c) for c in high],
            "assumptions_broken": assumptions_broken,
            "gate_results": gate_summary,
            "verdict": "BROKEN" if assumptions_broken > 0 else "HOLDING",
        }

    def _regression_hunt(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Run all registered RegressionGates against before/after snapshots.
        Auto-raises new challenges for any regressions found.
        """
        gate_results = self._gates.run_all(params)
        gate_summary = self._gates.summary(gate_results)

        new_challenge_ids: list[str] = []
        for gr in gate_results:
            if gr.failed:
                cid = self._registry.add(
                    target_subsystem="regression",
                    severity=ChallengeSeverity.HIGH,
                    description=f"Regression detected by gate '{gr.gate_name}': {gr.evidence}",
                    evidence=str(gr.details),
                )
                new_challenge_ids.append(cid)

        return {
            "mode": "regression_hunt",
            "gate_results": gate_summary,
            "new_challenges_raised": new_challenge_ids,
            "regressions_found": len(new_challenge_ids),
            "verdict": "REGRESSION_DETECTED" if new_challenge_ids else "CLEAN",
        }

    def _complexity_audit(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Flag over-engineering by surfacing challenges that reference
        complexity, overhead, or layering keywords.
        """
        all_open = self._registry.open_challenges()
        complexity_chs = [
            c for c in all_open
            if any(kw in c.description.lower() for kw in _COMPLEXITY_KEYWORDS)
        ]

        gate_results = self._gates.run_all(params)
        gate_summary = self._gates.summary(gate_results)

        return {
            "mode": "complexity_audit",
            "complexity_challenges": [_ch_dict(c) for c in complexity_chs],
            "complexity_challenge_count": len(complexity_chs),
            "gate_results": gate_summary,
            "recommendation": (
                "Review and simplify — multiple complexity challenges open"
                if len(complexity_chs) > 2
                else "Complexity within acceptable bounds"
            ),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ch_dict(c: Challenge) -> dict[str, Any]:
    return {
        "id": c.challenge_id,
        "subsystem": c.target_subsystem,
        "severity": c.severity.value,
        "description": c.description,
        "evidence": c.evidence,
        "status": c.status.value,
    }
