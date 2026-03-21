"""omega.bridge.state_client — HTTP client for the Go StateService.

Uses Connect-RPC unary JSON protocol. Zero external dependencies (stdlib only).

The Connect unary protocol is:
  POST <base_url>/omega.v1.StateService/<MethodName>
  Content-Type: application/json
  Connect-Protocol-Version: 1
  Body: proto JSON (camelCase field names)

Usage:
    client = StateServiceClient("http://localhost:8080")
    exec_id = client.begin_execution("node-1", "TestNode", "run", cycle=1)
    client.end_execution(exec_id, success=True, metrics={"score": 0.9})
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_BASE_PATH = "/omega.v1.StateService/"


class StateServiceError(Exception):
    """Raised when the Go StateService returns an error response."""


class StateServiceClient:
    """HTTP client for the Go StateService Connect-RPC endpoint (JSON protocol)."""

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
            raise StateServiceError(f"{method} failed ({exc.code}): {msg}") from exc
        except Exception as exc:
            raise StateServiceError(f"{method} unavailable: {exc}") from exc

    @staticmethod
    def _encode_map(d: dict | None) -> dict:
        """Encode a dict to map<string,string> by JSON-encoding non-string values."""
        if not d:
            return {}
        return {k: json.dumps(v) if not isinstance(v, str) else v for k, v in d.items()}

    # ── Node registry ──────────────────────────────────────────────────────

    def upsert_node(
        self,
        node_id: str,
        name: str,
        version: str,
        capabilities: list[str],
        health: float,
        status: str = "active",
        brain_config: dict | None = None,
    ) -> None:
        self._call(
            "UpsertNode",
            {
                "nodeId": node_id,
                "name": name,
                "version": version,
                "capabilities": capabilities,
                "health": health,
                "status": status,
                "brainConfig": self._encode_map(brain_config),
            },
        )

    # ── Executions ─────────────────────────────────────────────────────────

    def begin_execution(
        self,
        node_id: str,
        node_name: str,
        action: str,
        trace_id: str | None = None,
        span_id: str | None = None,
        cycle: int = 0,
    ) -> str:
        resp = self._call(
            "BeginExecution",
            {
                "nodeId": node_id,
                "nodeName": node_name,
                "action": action,
                "traceId": trace_id or "",
                "spanId": span_id or "",
                "cycle": cycle,
            },
        )
        return str(resp["execId"])

    def end_execution(
        self,
        exec_id: str,
        success: bool,
        error_text: str | None = None,
        metrics: dict | None = None,
    ) -> None:
        self._call(
            "EndExecution",
            {
                "execId": exec_id,
                "success": success,
                "errorText": error_text or "",
                "metrics": metrics or {},
            },
        )

    # ── Traces ─────────────────────────────────────────────────────────────

    def begin_span(
        self,
        trace_id: str,
        node_id: str,
        node_name: str,
        operation: str,
        parent_span_id: str | None = None,
        cycle: int = 0,
    ) -> str:
        resp = self._call(
            "BeginSpan",
            {
                "traceId": trace_id,
                "nodeId": node_id,
                "nodeName": node_name,
                "operation": operation,
                "parentSpanId": parent_span_id or "",
                "cycle": cycle,
            },
        )
        return str(resp["spanId"])

    def end_span(
        self,
        span_id: str,
        status: str = "ok",
        metadata: dict | None = None,
    ) -> None:
        self._call(
            "EndSpan",
            {
                "spanId": span_id,
                "status": status,
                "metadata": self._encode_map(metadata),
            },
        )

    # ── Cost events ────────────────────────────────────────────────────────

    def record_cost(
        self,
        node_id: str,
        provider: str,
        call_type: str,
        duration_ms: float,
        exec_id: str | None = None,
        estimated_cost_usd: float = 0.0,
        metadata: dict | None = None,
        cycle: int = 0,
    ) -> None:
        self._call(
            "RecordCost",
            {
                "nodeId": node_id,
                "provider": provider,
                "callType": call_type,
                "durationMs": duration_ms,
                "execId": exec_id or "",
                "estimatedCostUsd": estimated_cost_usd,
                "metadata": self._encode_map(metadata),
                "cycle": cycle,
            },
        )

    # ── Issues ─────────────────────────────────────────────────────────────

    def open_issue(
        self,
        issue_id: str,
        detector: str,
        severity: str,
        description: str,
        context: dict | None = None,
        cycle: int = 0,
    ) -> bool:
        resp = self._call(
            "OpenIssue",
            {
                "issueId": issue_id,
                "detector": detector,
                "severity": severity,
                "description": description,
                "context": self._encode_map(context),
                "cycle": cycle,
            },
        )
        return bool(resp.get("created", False))

    def escalate_issue(self, issue_id: str) -> bool:
        resp = self._call("EscalateIssue", {"issueId": issue_id})
        return int(resp.get("rowsAffected", 0)) > 0

    def resolve_issue(self, issue_id: str, cycle: int | None = None) -> bool:
        resp = self._call(
            "ResolveIssue",
            {
                "issueId": issue_id,
                "cycle": cycle or 0,
            },
        )
        return bool(resp.get("resolved", False))

    # ── Activity log ───────────────────────────────────────────────────────

    def log_activity(
        self,
        action_type: str,
        entity_type: str,
        entity_id: str,
        data: dict | None = None,
        cycle: int = 0,
    ) -> None:
        self._call(
            "LogActivity",
            {
                "actionType": action_type,
                "entityType": entity_type,
                "entityId": entity_id,
                "data": self._encode_map(data),
                "cycle": cycle,
            },
        )

    # ── Improvement log ────────────────────────────────────────────────────

    def record_improvement(
        self,
        node_id: str,
        node_name: str,
        from_version: str,
        to_version: str,
        before_metrics: dict | None = None,
        after_metrics: dict | None = None,
        triggered_by: str = "metrics",
        cycle: int = 0,
    ) -> None:
        self._call(
            "RecordImprovement",
            {
                "nodeId": node_id,
                "nodeName": node_name,
                "fromVersion": from_version,
                "toVersion": to_version,
                "beforeMetrics": before_metrics or {},
                "afterMetrics": after_metrics or {},
                "triggeredBy": triggered_by,
                "cycle": cycle,
            },
        )

    # ── Config revisions ───────────────────────────────────────────────────

    def save_config_revision(self, node_id: str, version: str, config: dict) -> None:
        self._call(
            "SaveConfigRevision",
            {
                "nodeId": node_id,
                "version": version,
                "config": self._encode_map(config),
            },
        )

    # ── Brain executions ───────────────────────────────────────────────────

    def record_brain_execution(
        self,
        node_id: str,
        node_name: str,
        provider: str,
        model: str,
        operation: str,
        action_decided: str,
        parameters: dict | None = None,
        reasoning: str = "",
        confidence: float = 0.0,
        outcome: str = "pending",
        latency_ms: float = 0.0,
        trace_id: str = "",
        cycle: int = 0,
    ) -> str:
        resp = self._call(
            "RecordBrainExecution",
            {
                "nodeId": node_id,
                "nodeName": node_name,
                "provider": provider,
                "model": model,
                "operation": operation,
                "actionDecided": action_decided,
                "parameters": self._encode_map(parameters),
                "reasoning": reasoning,
                "confidence": confidence,
                "outcome": outcome,
                "latencyMs": latency_ms,
                "traceId": trace_id,
                "cycle": cycle,
            },
        )
        return str(resp["brainExecId"])

    def update_brain_outcome(self, brain_exec_id: str, outcome: str) -> None:
        self._call(
            "UpdateBrainOutcome",
            {
                "brainExecId": brain_exec_id,
                "outcome": outcome,
            },
        )

    # ── Alignment decisions ────────────────────────────────────────────────

    def record_alignment_decision(
        self,
        cycle: int,
        approved: bool,
        violations: list | None = None,
        pareto_ranks: dict | None = None,
        adjustments: dict | None = None,
        vcg_payments: dict | None = None,
        goodhart_warning: bool = False,
    ) -> str:
        resp = self._call(
            "RecordAlignmentDecision",
            {
                "cycle": cycle,
                "approved": approved,
                "violations": violations or [],
                "paretoRanks": self._encode_map(pareto_ranks),
                "adjustments": self._encode_map(adjustments),
                "vcgPayments": self._encode_map(vcg_payments),
                "goodhartWarning": goodhart_warning,
            },
        )
        return str(resp["decisionId"])

    # ── Adversarial results ────────────────────────────────────────────────

    def record_adversarial_result(
        self,
        cycle: int,
        ring: int,
        flagged: bool,
        max_disagreement: float = 0.0,
        scenario_count: int = 0,
        failure_cases: list | None = None,
        details: dict | None = None,
    ) -> str:
        resp = self._call(
            "RecordAdversarialResult",
            {
                "cycle": cycle,
                "ring": ring,
                "flagged": flagged,
                "maxDisagreement": max_disagreement,
                "scenarioCount": scenario_count,
                "failureCases": failure_cases or [],
                "details": self._encode_map(details),
            },
        )
        return str(resp["resultId"])

    # ── Goal tracking ──────────────────────────────────────────────────────

    def record_goal_tracking(
        self,
        cycle: int,
        approved: bool,
        composite_score: float,
        scorecard: dict | None = None,
        nash_weights: dict | None = None,
        tracking_error: float = 0.0,
        control_action: dict | None = None,
        subtasks: list | None = None,
        violations: list | None = None,
    ) -> str:
        resp = self._call(
            "RecordGoalTracking",
            {
                "cycle": cycle,
                "approved": approved,
                "compositeScore": composite_score,
                "scorecard": self._encode_map(scorecard),
                "nashWeights": self._encode_map(nash_weights),
                "trackingError": tracking_error,
                "controlAction": self._encode_map(control_action),
                "subtasks": subtasks or [],
                "violations": violations or [],
            },
        )
        return str(resp["trackingId"])
