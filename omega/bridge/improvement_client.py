"""omega.bridge.improvement_client — HTTP client for the Go ImprovementService.

Uses Connect-RPC unary JSON protocol. Zero external dependencies (stdlib only).

Connect unary protocol:
  POST <base_url>/omega.v1.ImprovementService/<MethodName>
  Content-Type: application/json
  Connect-Protocol-Version: 1
  Body: proto JSON (camelCase field names)

The ImprovementService manages the improvement scheduling pipeline, the TPE
Bayesian optimizer bridge, and deterministic strategy compilation.

Usage:
    client = ImprovementServiceClient("http://localhost:8080")

    due = client.due_nodes(cycle=5)
    for node_id in due:
        params = client.propose_trial_params(node_id, history=[...])
        # ... run trial with params ...
        client.record_outcome(node_id, success=True, score=1.4, cycle=5)

    strategy = client.compile_strategy("node-1", version="v2", parameters=params)
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_BASE_PATH = "/omega.v1.ImprovementService/"

# Trial status constants
TRIAL_STATUS_PENDING = "TRIAL_STATUS_PENDING"
TRIAL_STATUS_RUNNING = "TRIAL_STATUS_RUNNING"
TRIAL_STATUS_SUCCEEDED = "TRIAL_STATUS_SUCCEEDED"
TRIAL_STATUS_FAILED = "TRIAL_STATUS_FAILED"
TRIAL_STATUS_SKIPPED = "TRIAL_STATUS_SKIPPED"


class ImprovementServiceError(Exception):
    """Raised when the Go ImprovementService returns an error response."""


class ImprovementServiceClient:
    """HTTP client for the Go ImprovementService Connect-RPC endpoint (JSON protocol)."""

    def __init__(self, base_url: str = "http://localhost:8080", timeout: float = 10.0) -> None:
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
            raise ImprovementServiceError(f"{method} failed ({exc.code}): {msg}") from exc
        except Exception as exc:
            raise ImprovementServiceError(f"{method} unavailable: {exc}") from exc

    # ── DueNodes ───────────────────────────────────────────────────────────

    def due_nodes(self, cycle: int = 0) -> list[str]:
        """Return node IDs whose improvement trials are due in the current cycle.

        Returns:
            List of node IDs, ordered by descending priority.
        """
        resp = self._call("DueNodes", {"cycle": cycle})
        return list(resp.get("nodeIds", []))

    # ── ScheduleImprovement ────────────────────────────────────────────────

    def schedule_improvement(
        self,
        node_id: str,
        priority: float = 1.0,
        interval_seconds: int = 3600,
        first_run_delay_seconds: int = 0,
    ) -> dict[str, Any]:
        """Set or update the improvement schedule for a node.

        Returns:
            ScheduleEntry dict.
        """
        return self._call(
            "ScheduleImprovement",
            {
                "nodeId": node_id,
                "priority": priority,
                "interval": {"seconds": interval_seconds, "nanos": 0},
                "firstRunAt": {} if first_run_delay_seconds == 0 else {
                    "seconds": first_run_delay_seconds,
                    "nanos": 0,
                },
            },
        )

    # ── RecordOutcome ──────────────────────────────────────────────────────

    def record_outcome(
        self,
        node_id: str,
        outcome: dict[str, Any] | None = None,
        success: bool = True,
        score: float = 0.0,
        cycle: int = 0,
        before_metrics: dict[str, float] | None = None,
        after_metrics: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Store the result of an improvement trial and reschedule the node.

        Args:
            node_id: The node whose trial completed.
            outcome: Optional unstructured outcome dict (unused by proto; use
                success/score instead).
            success: Whether the trial succeeded.
            score: Composite metric improvement delta (e.g. Sharpe delta).
            cycle: Orchestrator cycle number.
            before_metrics: Metrics before the trial.
            after_metrics: Metrics after the trial.

        Returns:
            {nextRunAt, updatedEntry: ScheduleEntry}
        """
        _ = outcome  # available for callers but not sent to proto
        return self._call(
            "RecordOutcome",
            {
                "nodeId": node_id,
                "success": success,
                "score": score,
                "cycle": cycle,
                "beforeMetrics": before_metrics or {},
                "afterMetrics": after_metrics or {},
            },
        )

    # ── ProposeTrialParams ─────────────────────────────────────────────────

    def propose_trial_params(
        self,
        node_id: str,
        history: list[dict[str, Any]] | None = None,
        param_space: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ask the TPE optimizer to propose the next hyperparameter trial.

        Args:
            node_id: Node being optimised.
            history: Past trials [{params, score, success, cycle}, ...].
                The `params` field should be dict[str, float].
            param_space: JSON-serialisable param space definition.
                Values are JSON-encoded strings sent as map<string,string>.

        Returns:
            {params: dict[str, float], expectedImprovement: float, strategy: str}
        """
        encoded_history = []
        for entry in (history or []):
            encoded_history.append({
                "params": entry.get("params", {}),
                "score": float(entry.get("score", 0.0)),
                "success": bool(entry.get("success", True)),
                "cycle": int(entry.get("cycle", 0)),
            })

        encoded_space: dict[str, str] = {}
        for k, v in (param_space or {}).items():
            encoded_space[k] = v if isinstance(v, str) else json.dumps(v)

        return self._call(
            "ProposeTrialParams",
            {
                "nodeId": node_id,
                "history": encoded_history,
                "paramSpace": encoded_space,
            },
        )

    # ── CompileStrategy ────────────────────────────────────────────────────

    def compile_strategy(
        self,
        node_id: str,
        version: str = "",
        parameters: dict[str, float] | None = None,
        rules: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Freeze a node's current state into a versioned deterministic strategy.

        Args:
            node_id: The node to compile.
            version: Node version string.
            parameters: Hyperparameter values to freeze.
            rules: List of StrategyRule dicts:
                [{name, conditions: [{fieldPath, operator, threshold}], confidence}]

        Returns:
            {strategyId, checksum, nodeVersion, compiledAt}
        """
        return self._call(
            "CompileStrategy",
            {
                "nodeId": node_id,
                "nodeVersion": version,
                "parameters": parameters or {},
                "rules": rules or [],
            },
        )

    # ── RollbackStrategy ───────────────────────────────────────────────────

    def rollback_strategy(self, node_id: str, version: int) -> bool:
        """Revert a node to a previously compiled strategy version.

        Args:
            node_id: The node to roll back.
            version: Strategy registry version number to restore.

        Returns:
            True if rollback was successful.
        """
        resp = self._call(
            "RollbackStrategy",
            {
                "nodeId": node_id,
                "targetVersion": version,
            },
        )
        return bool(resp.get("ok", False))

    # ── GetImprovementSchedule ─────────────────────────────────────────────

    def get_improvement_schedule(self, node_id: str) -> dict[str, Any] | None:
        """Return the current schedule entry for a node.

        Returns:
            ScheduleEntry dict, or None if not found.
        """
        resp = self._call("GetImprovementSchedule", {"nodeId": node_id})
        if not resp.get("found", False):
            return None
        return resp.get("entry")

    # ── ListImprovedNodes ──────────────────────────────────────────────────

    def list_improved_nodes(self) -> list[dict[str, Any]]:
        """Return all nodes currently in the improvement queue.

        Returns:
            List of ScheduleEntry dicts.
        """
        resp = self._call("ListImprovedNodes", {})
        return resp.get("entries", [])
