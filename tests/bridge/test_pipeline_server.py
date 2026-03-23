"""Unit tests for omega.bridge.pipeline_server and omega.bridge.pipeline_types."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

import pytest

from omega.bridge.pipeline_server import StepHandlerRegistry, start_pipeline_server
from omega.bridge.pipeline_types import ExecuteStepRequest, ExecuteStepResponse

# ── Helpers ────────────────────────────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])


def _post(port: int, method: str, body: dict, headers: dict | None = None) -> dict:
    url = f"http://localhost:{port}/omega.v1.PipelineService/{method}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
            **(headers or {}),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return dict(json.loads(resp.read()))


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def server_port():
    port = _free_port()
    registry = StepHandlerRegistry()
    server, _ = start_pipeline_server(port=port, registry=registry)
    time.sleep(0.05)  # allow the daemon thread to bind
    yield port, registry
    server.shutdown()


# ── Ping ───────────────────────────────────────────────────────────────────────


def test_ping_returns_ok(server_port):
    port, _ = server_port
    resp = _post(port, "Ping", {})
    assert resp["ok"] is True
    assert "version" in resp


# ── ExecuteStep — routing ──────────────────────────────────────────────────────


def test_execute_step_unknown_node_type_returns_failure(server_port):
    port, _ = server_port
    resp = _post(
        port,
        "ExecuteStep",
        {
            "stepId": "step_1",
            "stepName": "DataIngestion",
            "nodeType": "UNKNOWN_TYPE",
            "cycle": 1,
        },
    )
    assert resp["success"] is False
    assert "UNKNOWN_TYPE" in resp["errorText"]


def test_execute_step_registered_handler_succeeds(server_port):
    port, registry = server_port

    def my_handler(req: ExecuteStepRequest) -> ExecuteStepResponse:
        return ExecuteStepResponse(
            success=True,
            node_id="node-test",
            node_name="TestNode",
            metrics={"score": 0.9},
        )

    registry.register("DATA_INGESTION", my_handler)
    resp = _post(
        port,
        "ExecuteStep",
        {
            "nodeType": "DATA_INGESTION",
            "stepId": "step_1",
            "stepName": "DataIngestion",
            "cycle": 5,
        },
    )
    assert resp["success"] is True
    assert resp["nodeId"] == "node-test"
    assert resp["nodeName"] == "TestNode"
    assert resp["metrics"]["score"] == pytest.approx(0.9)


def test_execute_step_handler_exception_returns_error(server_port):
    port, registry = server_port

    def failing_handler(req: ExecuteStepRequest) -> ExecuteStepResponse:
        raise RuntimeError("simulated failure")

    registry.register("STRATEGY", failing_handler)
    resp = _post(port, "ExecuteStep", {"nodeType": "STRATEGY", "cycle": 1})
    assert resp["success"] is False
    assert "simulated failure" in resp["errorText"]


# ── Trace context propagation ─────────────────────────────────────────────────


def test_traceparent_header_extracted_into_request(server_port):
    port, registry = server_port
    captured: list[ExecuteStepRequest] = []

    def capture_handler(req: ExecuteStepRequest) -> ExecuteStepResponse:
        captured.append(req)
        return ExecuteStepResponse(success=True)

    registry.register("SIGNAL_RESEARCH", capture_handler)
    trace_id = "a" * 32
    span_id = "b" * 16
    _post(
        port,
        "ExecuteStep",
        {"nodeType": "SIGNAL_RESEARCH", "cycle": 1},
        headers={"traceparent": f"00-{trace_id}-{span_id}-01"},
    )
    assert len(captured) == 1
    assert captured[0].trace_id == trace_id
    assert captured[0].parent_span_id == span_id


def test_trace_fields_in_body_take_precedence_over_header(server_port):
    """When trace fields are in the JSON body AND the header, body wins."""
    port, registry = server_port
    captured: list[ExecuteStepRequest] = []

    def capture_handler(req: ExecuteStepRequest) -> ExecuteStepResponse:
        captured.append(req)
        return ExecuteStepResponse(success=True)

    registry.register("MEMORY", capture_handler)
    body_trace = "c" * 32
    header_trace = "d" * 32
    _post(
        port,
        "ExecuteStep",
        {"nodeType": "MEMORY", "cycle": 1, "traceId": body_trace, "parentSpanId": "e" * 16},
        headers={"traceparent": f"00-{header_trace}-{'f' * 16}-01"},
    )
    assert captured[0].trace_id == body_trace


# ── HTTP error cases ───────────────────────────────────────────────────────────


def test_unknown_method_returns_404(server_port):
    port, _ = server_port
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(port, "NonExistentMethod", {})
    assert exc_info.value.code == 404


def test_wrong_path_returns_404(server_port):
    port, _ = server_port
    url = f"http://localhost:{port}/wrong/path"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=5)
    assert exc_info.value.code == 404


# ── ExecuteStepRequest.from_json ───────────────────────────────────────────────


def test_from_json_parses_all_fields():
    import base64

    payload = b'{"data": 1}'
    body = {
        "stepId": "step_1",
        "stepName": "DataIngestion",
        "nodeType": "DATA_INGESTION",
        "cycle": 3,
        "traceId": "abc",
        "parentSpanId": "def",
        "parameters": {"key": "val"},
        "inputPayload": base64.b64encode(payload).decode(),
    }
    req = ExecuteStepRequest.from_json(body)
    assert req.step_id == "step_1"
    assert req.step_name == "DataIngestion"
    assert req.node_type == "DATA_INGESTION"
    assert req.cycle == 3
    assert req.trace_id == "abc"
    assert req.parent_span_id == "def"
    assert req.parameters == {"key": "val"}
    assert req.input_payload == payload


def test_from_json_defaults_for_missing_fields():
    req = ExecuteStepRequest.from_json({})
    assert req.step_id == ""
    assert req.step_name == ""
    assert req.node_type == ""
    assert req.cycle == 0
    assert req.trace_id == ""
    assert req.parent_span_id == ""
    assert req.parameters == {}
    assert req.input_payload == b""


# ── ExecuteStepResponse.to_json ───────────────────────────────────────────────


def test_to_json_excludes_empty_output_payload():
    resp = ExecuteStepResponse(success=True, node_id="n1")
    d = resp.to_json()
    assert "outputPayload" not in d
    assert d["success"] is True
    assert d["nodeId"] == "n1"


def test_to_json_includes_output_payload_when_set():
    import base64

    payload = b'{"result": 42}'
    resp = ExecuteStepResponse(success=True, output_payload=payload)
    d = resp.to_json()
    assert base64.b64decode(d["outputPayload"]) == payload


# ── Concurrent requests ────────────────────────────────────────────────────────


def test_server_handles_concurrent_requests(server_port):
    """ThreadingHTTPServer should handle multiple simultaneous requests."""
    import concurrent.futures

    port, registry = server_port

    def slow_handler(req: ExecuteStepRequest) -> ExecuteStepResponse:
        time.sleep(0.02)
        return ExecuteStepResponse(success=True, node_id="concurrent")

    registry.register("ADVERSARIAL", slow_handler)

    def call() -> dict:
        return _post(port, "ExecuteStep", {"nodeType": "ADVERSARIAL", "cycle": 1})

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(call) for _ in range(5)]
        results = [f.result() for f in futures]

    assert all(r["success"] for r in results)
