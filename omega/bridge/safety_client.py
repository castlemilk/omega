"""omega.bridge.safety_client — HTTP client for the Go SafetyService.

Uses Connect-RPC unary JSON protocol. Zero external dependencies (stdlib only).

Connect unary protocol:
  POST <base_url>/omega.v1.SafetyService/<MethodName>
  Content-Type: application/json
  Connect-Protocol-Version: 1
  Body: proto JSON (camelCase field names)

Usage:
    client = SafetyServiceClient("http://localhost:8080")

    result = client.check_alignment(
        node_metrics=[{"nodeId": "n1", "metrics": {"sharpe": 1.4}}],
        portfolio={"position_pct": 0.05, "drawdown_pct": 0.02},
        cycle=5,
    )
    if not result["approved"]:
        raise RuntimeError(result["violations"])
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_BASE_PATH = "/omega.v1.SafetyService/"

# Gate phase constants matching proto enum
GATE_PHASE_PRE_CYCLE = "GATE_PHASE_PRE_CYCLE"
GATE_PHASE_POST_CYCLE = "GATE_PHASE_POST_CYCLE"
GATE_PHASE_PRE_IMPROVEMENT = "GATE_PHASE_PRE_IMPROVEMENT"

# Challenge severity constants
CHALLENGE_SEVERITY_CRITICAL = "CHALLENGE_SEVERITY_CRITICAL"
CHALLENGE_SEVERITY_HIGH = "CHALLENGE_SEVERITY_HIGH"
CHALLENGE_SEVERITY_MEDIUM = "CHALLENGE_SEVERITY_MEDIUM"
CHALLENGE_SEVERITY_LOW = "CHALLENGE_SEVERITY_LOW"

# Resolution constants
CHALLENGE_RESOLUTION_RESOLVED = "CHALLENGE_RESOLUTION_RESOLVED"
CHALLENGE_RESOLUTION_WONTFIX = "CHALLENGE_RESOLUTION_WONTFIX"
CHALLENGE_RESOLUTION_ACKNOWLEDGED = "CHALLENGE_RESOLUTION_ACKNOWLEDGED"


class SafetyServiceError(Exception):
    """Raised when the Go SafetyService returns an error response."""


class SafetyServiceClient:
    """HTTP client for the Go SafetyService Connect-RPC endpoint (JSON protocol)."""

    def __init__(self, base_url: str = "http://localhost:8080", timeout: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _call(self, method: str, body: dict) -> Any:
        url = self._base_url + _BASE_PATH + method
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Connect-Protocol-Version": "1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                err_body = json.loads(exc.read())
                msg = err_body.get("message", str(exc))
            except Exception:
                msg = str(exc)
            raise SafetyServiceError(f"{method} failed ({exc.code}): {msg}") from exc
        except Exception as exc:
            raise SafetyServiceError(f"{method} unavailable: {exc}") from exc

    # ── CheckAlignment ─────────────────────────────────────────────────────

    def check_alignment(
        self,
        node_metrics: list[dict[str, Any]],
        portfolio: dict[str, float] | None = None,
        system_metrics: dict[str, float] | None = None,
        cycle: int = 0,
    ) -> dict[str, Any]:
        """Run all three alignment layers and return a decision.

        Args:
            node_metrics: List of {nodeId, metrics: {name: value}} dicts.
            portfolio: Portfolio-level metrics for SafetyEnvelope:
                position_pct, drawdown_pct, max_correlation.
            system_metrics: System-wide metrics (passed through to all layers).
            cycle: Current cycle number.

        Returns:
            CheckAlignmentResponse dict: {approved, violations, paretoRanks,
            outcomeScores, goodhartWarning, reasons, checkedAt}
        """
        return self._call(
            "CheckAlignment",
            {
                "nodeMetrics": node_metrics,
                "systemMetrics": system_metrics or {},
                "portfolio": portfolio or {},
                "cycle": cycle,
            },
        )

    # ── VerifyGates ────────────────────────────────────────────────────────

    def verify_gates(
        self,
        checks: dict[str, str],
        phase: str = GATE_PHASE_PRE_CYCLE,
        cycle: int = 0,
    ) -> dict[str, Any]:
        """Run the full verification gate system.

        Args:
            checks: Context dict (JSON-encoded values) passed to each gate.
            phase: GATE_PHASE_PRE_CYCLE | GATE_PHASE_POST_CYCLE |
                   GATE_PHASE_PRE_IMPROVEMENT.
            cycle: Current cycle number.

        Returns:
            VerifyGatesResponse: {allPassed, results, passedCount, failedCount}
        """
        return self._call(
            "VerifyGates",
            {
                "phase": phase,
                "context": checks,
                "cycle": cycle,
            },
        )

    # ── EvaluateGoals ──────────────────────────────────────────────────────

    def evaluate_goals(
        self,
        node_id: str,
        metrics: dict[str, float] | None = None,
        system_state: dict[str, str] | None = None,
        cycle: int = 0,
    ) -> dict[str, Any]:
        """Run the HTN goal architecture for one cycle step.

        Args:
            node_id: Node being evaluated (used to key into system_state if needed).
            metrics: Composite metric values for goal scoring.
            system_state: JSON-encoded system state values.
            cycle: Current cycle number.

        Returns:
            EvaluateGoalsResponse: {approved, violations, scorecard,
            compositeScore, subtasks, trackingError, controlAction, evaluatedAt}
        """
        state = dict(system_state or {})
        state.setdefault("node_id", node_id)
        return self._call(
            "EvaluateGoals",
            {
                "metrics": metrics or {},
                "systemState": state,
                "cycle": cycle,
            },
        )

    # ── RecordOutcomeScore ─────────────────────────────────────────────────

    def record_outcome_score(
        self,
        node_id: str,
        predicted: float,
        actual: float,
        return_contribution: float = 0.0,
        cycle: int = 0,
    ) -> bool:
        """Store a post-hoc accuracy observation for a node."""
        resp = self._call(
            "RecordOutcomeScore",
            {
                "nodeId": node_id,
                "predicted": predicted,
                "actual": actual,
                "returnContribution": return_contribution,
                "cycle": cycle,
            },
        )
        return bool(resp.get("ok", False))

    # ── HasBlockingChallenges ──────────────────────────────────────────────

    def has_blocking_challenges(self) -> bool:
        """Check whether any open CRITICAL challenges block execution."""
        resp = self._call("HasBlockingChallenges", {})
        return bool(resp.get("hasBlocking", False))

    def blocking_challenge_counts(self) -> dict[str, int]:
        """Return {criticalCount, highCount} of open challenges."""
        resp = self._call("HasBlockingChallenges", {})
        return {
            "criticalCount": int(resp.get("criticalCount", 0)),
            "highCount": int(resp.get("highCount", 0)),
        }

    # ── OpenChallenge ──────────────────────────────────────────────────────

    def open_challenge(
        self,
        target_subsystem: str,
        description: str,
        evidence: str = "",
        severity: str = CHALLENGE_SEVERITY_MEDIUM,
        challenge_id: str = "",
    ) -> str:
        """Record a new Devil's Advocate challenge for a subsystem.

        Args:
            target_subsystem: Subsystem being challenged.
            description: What the challenge asserts.
            evidence: Supporting evidence text.
            severity: CHALLENGE_SEVERITY_* constant.
            challenge_id: Optional ID; generated by server if empty.

        Returns:
            The challenge ID (server-assigned or provided).
        """
        resp = self._call(
            "OpenChallenge",
            {
                "targetSubsystem": target_subsystem,
                "severity": severity,
                "description": description,
                "evidence": evidence,
                "challengeId": challenge_id,
            },
        )
        return str(resp.get("challengeId", ""))

    # ── ResolveChallenge ───────────────────────────────────────────────────

    def resolve_challenge(
        self,
        challenge_id: str,
        resolution: str = CHALLENGE_RESOLUTION_RESOLVED,
        notes: str = "",
    ) -> bool:
        """Mark an existing challenge as resolved or won't-fix.

        Args:
            challenge_id: The challenge to resolve.
            resolution: CHALLENGE_RESOLUTION_* constant.
            notes: Optional resolution notes.

        Returns:
            True if the server acknowledged the resolution.
        """
        resp = self._call(
            "ResolveChallenge",
            {
                "challengeId": challenge_id,
                "resolution": resolution,
                "notes": notes,
            },
        )
        return bool(resp.get("ok", False))

    # ── GetGoalDecision ────────────────────────────────────────────────────

    def get_goal_decision(self, cycle: int) -> dict[str, Any] | None:
        """Retrieve the stored goal decision for a cycle.

        Returns:
            EvaluateGoalsResponse dict, or None if not found.
        """
        resp = self._call("GetGoalDecision", {"cycle": cycle})
        if not resp.get("found", False):
            return None
        return resp.get("decision")
