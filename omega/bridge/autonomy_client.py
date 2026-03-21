"""omega.bridge.autonomy_client — HTTP client for the Go AutonomyService.

Uses Connect-RPC unary JSON protocol. Zero external dependencies (stdlib only).

Connect unary protocol:
  POST <base_url>/omega.v1.AutonomyService/<MethodName>
  Content-Type: application/json
  Connect-Protocol-Version: 1
  Body: proto JSON (camelCase field names)

Streaming methods (StreamNodeMetrics) use a polling loop over the Connect
server-streaming wire format: each chunk is a length-prefixed JSON envelope.
Since stdlib does not support chunked streaming natively, this client polls
the server for batches of events via a dedicated poll endpoint. If the Go side
only exposes the real gRPC stream, callers should use stream_node_metrics() and
treat the Iterator as a long-poll that yields one event per HTTP round-trip.

Usage:
    client = AutonomyServiceClient("http://localhost:8080")
    client.record_cycle_metrics("node-1", cycle=5, metrics={"sharpe": 1.4})
    level = client.get_autonomy_level("node-1")
    approved = client.request_promotion("node-1", justification="12 clean cycles")
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

log = logging.getLogger(__name__)

_BASE_PATH = "/omega.v1.AutonomyService/"

# Canonical autonomy level names (proto enum string representation)
AutonomyLevel = str  # "AUTONOMY_LEVEL_MANUAL" | "AUTONOMY_LEVEL_SUPERVISED" | ...

AUTONOMY_LEVEL_UNSPECIFIED = "AUTONOMY_LEVEL_UNSPECIFIED"
AUTONOMY_LEVEL_MANUAL = "AUTONOMY_LEVEL_MANUAL"
AUTONOMY_LEVEL_SUPERVISED = "AUTONOMY_LEVEL_SUPERVISED"
AUTONOMY_LEVEL_SEMI = "AUTONOMY_LEVEL_SEMI"
AUTONOMY_LEVEL_FULL = "AUTONOMY_LEVEL_FULL"


class AutonomyServiceError(Exception):
    """Raised when the Go AutonomyService returns an error response."""


class AutonomyServiceClient:
    """HTTP client for the Go AutonomyService Connect-RPC endpoint (JSON protocol)."""

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
            raise AutonomyServiceError(f"{method} failed ({exc.code}): {msg}") from exc
        except Exception as exc:
            raise AutonomyServiceError(f"{method} unavailable: {exc}") from exc

    # ── RecordCycleMetrics ─────────────────────────────────────────────────

    def record_cycle_metrics(
        self,
        node_id: str,
        cycle: int,
        metrics: dict[str, float],
        success: bool = True,
    ) -> bool:
        """Store per-node performance metrics after a cycle.

        Args:
            node_id: The node whose metrics to record.
            cycle: Cycle number.
            metrics: Metric name → float value (e.g. {"sharpe": 1.4, "win_rate": 0.6}).
            success: Whether the cycle completed without error.

        Returns:
            True if the server acknowledged the write.
        """
        resp = self._call(
            "RecordCycleMetrics",
            {
                "nodeId": node_id,
                "cycle": cycle,
                "metrics": metrics,
                "success": success,
            },
        )
        return bool(resp.get("ok", False))

    # ── GetAutonomyLevel ───────────────────────────────────────────────────

    def get_autonomy_level(self, node_id: str) -> dict[str, Any]:
        """Return the current autonomy level for a node.

        Returns:
            dict with keys: nodeId, level (AutonomyLevel str), confidence,
            cyclesAtLevel, since (ISO timestamp).
        """
        return self._call("GetAutonomyLevel", {"nodeId": node_id})

    # ── RequestPromotion ───────────────────────────────────────────────────

    def request_promotion(
        self,
        node_id: str,
        justification: str,
        requested_level: AutonomyLevel = AUTONOMY_LEVEL_SUPERVISED,
        supporting_metrics: dict[str, float] | None = None,
        cycle: int = 0,
    ) -> bool:
        """Ask the autonomy system to promote a node to a higher tier.

        Args:
            node_id: The node requesting promotion.
            justification: Human-readable reason for the request.
            requested_level: The desired autonomy level enum string.
            supporting_metrics: Metrics that support the promotion case.
            cycle: Current orchestrator cycle.

        Returns:
            True if the promotion was approved.
        """
        resp = self._call(
            "RequestPromotion",
            {
                "nodeId": node_id,
                "requestedLevel": requested_level,
                "reason": justification,
                "supportingMetrics": supporting_metrics or {},
                "cycle": cycle,
            },
        )
        return bool(resp.get("approved", False))

    # ── RecordPromotion ────────────────────────────────────────────────────

    def record_promotion(
        self,
        node_id: str,
        from_level: AutonomyLevel,
        to_level: AutonomyLevel,
        trigger: str = "promotion",
        cycle: int = 0,
    ) -> bool:
        """Persist a confirmed promotion or demotion event.

        Args:
            trigger: "promotion" | "demotion" | "reset"
        """
        resp = self._call(
            "RecordPromotion",
            {
                "nodeId": node_id,
                "fromLevel": from_level,
                "toLevel": to_level,
                "trigger": trigger,
                "cycle": cycle,
            },
        )
        return bool(resp.get("ok", False))

    # ── GetAutonomyHistory ─────────────────────────────────────────────────

    def get_autonomy_history(self, node_id: str, limit: int = 20) -> list[dict]:
        """Return the promotion/demotion history for a node.

        Returns:
            List of event dicts: {nodeId, fromLevel, toLevel, trigger, cycle, recordedAt}
        """
        resp = self._call(
            "GetAutonomyHistory",
            {"nodeId": node_id, "limit": limit},
        )
        return resp.get("events", [])

    # ── StreamNodeMetrics ──────────────────────────────────────────────────

    def stream_node_metrics(
        self,
        node_id: str = "",
        poll_interval_ms: int = 1000,
        max_events: int | None = None,
        idle_timeout: float = 30.0,
    ) -> Iterator[dict]:
        """Stream live per-node metrics events.

        Because stdlib does not support chunked HTTP streaming, this method
        issues repeated unary POST calls to the StreamNodeMetrics RPC endpoint
        and yields each NodeMetricsEvent dict as it arrives. The server may
        return one event per request if it exposes a poll-compatible adapter,
        or this can be wired to a dedicated non-streaming polling endpoint.

        Args:
            node_id: Node to stream; empty string = all nodes.
            poll_interval_ms: Milliseconds between polls (also sent to server).
            max_events: Stop after this many events (None = run forever).
            idle_timeout: Seconds without a new event before StopIteration.

        Yields:
            NodeMetricsEvent dicts: {nodeId, cycle, metrics, currentLevel, emittedAt}
        """
        count = 0
        last_event_time = time.monotonic()
        while True:
            try:
                resp = self._call(
                    "StreamNodeMetrics",
                    {"nodeId": node_id, "pollIntervalMs": poll_interval_ms},
                )
                events: list[dict] = []
                # Server may return a single event or a list under "events"
                if isinstance(resp, list):
                    events = resp
                elif "events" in resp:
                    events = resp["events"]
                elif resp:
                    events = [resp]

                for event in events:
                    yield event
                    count += 1
                    last_event_time = time.monotonic()
                    if max_events is not None and count >= max_events:
                        return

                if events:
                    last_event_time = time.monotonic()
                elif time.monotonic() - last_event_time > idle_timeout:
                    return

            except AutonomyServiceError as exc:
                log.warning("stream_node_metrics poll error: %s", exc)

            time.sleep(poll_interval_ms / 1000.0)
