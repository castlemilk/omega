"""omega.bridge.pipeline_types — typed dataclasses for PipelineService messages.

These mirror proto/omega/v1/pipeline_service.proto without requiring
the protobuf runtime library (stdlib only).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExecuteStepRequest:
    step_id: str
    step_name: str
    node_type: str
    cycle: int
    trace_id: str
    parent_span_id: str
    parameters: dict[str, str] = field(default_factory=dict)
    input_payload: bytes = b""
    project_id: str = ""

    @classmethod
    def from_json(cls, body: dict) -> ExecuteStepRequest:
        import base64

        raw = body.get("inputPayload", "")
        payload = base64.b64decode(raw) if raw else b""
        return cls(
            step_id=body.get("stepId", ""),
            step_name=body.get("stepName", ""),
            node_type=body.get("nodeType", ""),
            cycle=int(body.get("cycle", 0)),
            trace_id=body.get("traceId", ""),
            parent_span_id=body.get("parentSpanId", ""),
            parameters=dict(body.get("parameters", {})),
            input_payload=payload,
            project_id=body.get("projectId", ""),
        )


@dataclass
class ExecuteStepResponse:
    success: bool
    error_text: str = ""
    output_payload: bytes = b""
    metrics: dict[str, float] = field(default_factory=dict)
    duration_ms: float = 0.0
    node_id: str = ""
    node_name: str = ""

    def to_json(self) -> dict:
        import base64

        d: dict = {
            "success": self.success,
            "errorText": self.error_text,
            "metrics": self.metrics,
            "durationMs": self.duration_ms,
            "nodeId": self.node_id,
            "nodeName": self.node_name,
        }
        if self.output_payload:
            d["outputPayload"] = base64.b64encode(self.output_payload).decode()
        return d


@dataclass
class PingResponse:
    ok: bool
    version: str = "0.1.0"

    def to_json(self) -> dict:
        return {"ok": self.ok, "version": self.version}
