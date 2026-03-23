"""Integration tests for the Go→Python pipeline bridge.

These tests simulate exactly what the Go PipelineClient sends to the Python
pipeline server — the same Connect-RPC JSON HTTP calls with traceparent headers
and camelCase JSON bodies.  No Go binary is required; we exercise the full
Python server path with the same wire format Go uses.

Run these with:
    pytest tests/bridge/test_pipeline_integration.py -v -m integration

Or skip them in fast CI:
    pytest -m 'not integration'
"""

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


def _go_style_post(
    port: int,
    method: str,
    body: dict,
    trace_id: str = "",
    span_id: str = "",
) -> dict:
    """Make a Connect-RPC JSON call identical to what Go PipelineClient sends.

    Go sends:
      POST /omega.v1.PipelineService/<method>
      Content-Type: application/json
      Connect-Protocol-Version: 1
      traceparent: 00-{trace_id}-{span_id}-01   (when OTel span is active)
    """
    url = f"http://localhost:{port}/omega.v1.PipelineService/{method}"
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Connect-Protocol-Version": "1",
    }
    if trace_id and span_id:
        headers["traceparent"] = f"00-{trace_id}-{span_id}-01"
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return dict(json.loads(resp.read()))


# ── Module-scoped server with default handlers ─────────────────────────────────


@pytest.fixture(scope="module")
def integration_server():
    port = _free_port()
    registry = StepHandlerRegistry()

    def data_ingestion(req: ExecuteStepRequest) -> ExecuteStepResponse:
        return ExecuteStepResponse(
            success=True,
            node_id="node-data-ingest",
            node_name="DataIngestionNode",
            metrics={"records_fetched": 1000.0, "latency_ms": 45.0},
            output_payload=b'{"ohlcv": [1, 2, 3], "source": "binance"}',
        )

    def signal_research(req: ExecuteStepRequest) -> ExecuteStepResponse:
        import json as _json

        prev = _json.loads(req.input_payload) if req.input_payload else {}
        return ExecuteStepResponse(
            success=True,
            node_id="node-signals",
            node_name="SignalResearchNode",
            metrics={"signals_generated": 5.0},
            output_payload=_json.dumps({"signals": {"sma": 0.6}, "prev": prev}).encode(),
        )

    registry.register("DATA_INGESTION", data_ingestion)
    registry.register("SIGNAL_RESEARCH", signal_research)

    server, _ = start_pipeline_server(port=port, registry=registry)
    time.sleep(0.1)
    yield port
    server.shutdown()


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_go_style_ping(integration_server):
    resp = _go_style_post(integration_server, "Ping", {})
    assert resp["ok"] is True
    assert "version" in resp


@pytest.mark.integration
def test_go_style_execute_step_data_ingestion(integration_server):
    resp = _go_style_post(
        integration_server,
        "ExecuteStep",
        {
            "stepId": "step_1",
            "stepName": "DataIngestion",
            "nodeType": "DATA_INGESTION",
            "cycle": 42,
        },
    )
    assert resp["success"] is True
    assert resp["nodeId"] == "node-data-ingest"
    assert resp["metrics"]["records_fetched"] == pytest.approx(1000.0)
    assert "outputPayload" in resp  # base64-encoded JSON


@pytest.mark.integration
def test_go_style_step_chaining_via_input_payload(integration_server):
    """Simulate Go passing the output of step 1 as input to step 2."""
    import base64

    # Step 1: get data
    step1 = _go_style_post(
        integration_server,
        "ExecuteStep",
        {
            "stepId": "step_1",
            "stepName": "DataIngestion",
            "nodeType": "DATA_INGESTION",
            "cycle": 1,
        },
    )
    assert step1["success"] is True

    # Step 2: pass step 1 output as input
    step2 = _go_style_post(
        integration_server,
        "ExecuteStep",
        {
            "stepId": "step_2",
            "stepName": "SignalResearch",
            "nodeType": "SIGNAL_RESEARCH",
            "cycle": 1,
            "inputPayload": step1["outputPayload"],  # forward step 1 output
        },
    )
    assert step2["success"] is True
    output = json.loads(base64.b64decode(step2["outputPayload"]))
    assert "signals" in output
    # Prev data from step 1 should be present (forwarded correctly)
    assert "prev" in output


@pytest.mark.integration
def test_trace_context_roundtrip(integration_server):
    """Verify that a Go-style traceparent propagates into the Python request."""
    trace_id = "deadbeef" * 4  # 32 hex chars — valid W3C trace ID
    span_id = "cafebabe" * 2  # 16 hex chars — valid W3C span ID

    # Capture via a fresh server with a dedicated handler
    port2 = _free_port()
    registry2 = StepHandlerRegistry()
    captured: list[tuple[str, str]] = []

    def capturing_handler(req: ExecuteStepRequest) -> ExecuteStepResponse:
        captured.append((req.trace_id, req.parent_span_id))
        return ExecuteStepResponse(success=True)

    registry2.register("MEMORY", capturing_handler)
    server2, _ = start_pipeline_server(port=port2, registry=registry2)
    time.sleep(0.05)
    try:
        _go_style_post(
            port2,
            "ExecuteStep",
            {"nodeType": "MEMORY", "cycle": 1},
            trace_id=trace_id,
            span_id=span_id,
        )
        assert len(captured) == 1
        assert captured[0][0] == trace_id, (
            f"trace_id: expected {trace_id!r}, got {captured[0][0]!r}"
        )
        assert captured[0][1] == span_id, f"span_id: expected {span_id!r}, got {captured[0][1]!r}"
    finally:
        server2.shutdown()


@pytest.mark.integration
def test_unregistered_node_type_graceful_error(integration_server):
    resp = _go_style_post(
        integration_server,
        "ExecuteStep",
        {"nodeType": "NONEXISTENT_NODE", "cycle": 1},
    )
    assert resp["success"] is False
    assert "NONEXISTENT_NODE" in resp["errorText"]


@pytest.mark.integration
def test_full_victoria_pipeline_sequence(integration_server):
    """Simulate Go calling all 9 Victoria pipeline steps in order.

    Steps without registered handlers should return graceful failure —
    not crash the server. The server must remain alive for all 9 calls.
    """
    victoria_steps = [
        ("step_1", "DataIngestion", "DATA_INGESTION"),
        ("step_2", "SignalResearch", "SIGNAL_RESEARCH"),
        ("step_3", "IntelligenceCoordination", "STRATEGY"),
        ("step_4", "DynamicWeights", "RISK_MANAGEMENT"),
        ("step_5", "DebateGate", "VERIFICATION"),
        ("step_6", "WalkForward", "VERIFICATION"),
        ("step_7", "Memory", "MEMORY"),
        ("step_8", "ImprovementEngine", "IMPROVEMENT"),
        ("step_9", "Ring3Adversarial", "ADVERSARIAL"),
    ]

    results = []
    for step_id, step_name, node_type in victoria_steps:
        resp = _go_style_post(
            integration_server,
            "ExecuteStep",
            {
                "stepId": step_id,
                "stepName": step_name,
                "nodeType": node_type,
                "cycle": 99,
            },
        )
        results.append((step_name, resp.get("success"), resp.get("errorText", "")))

    # Steps with registered handlers must succeed
    registered = {r[0] for r in results if r[1]}
    assert "DataIngestion" in registered
    assert "SignalResearch" in registered

    # Unregistered steps must fail gracefully (not 500, not crash)
    for step_name, success, error_text in results:
        if not success:
            assert error_text, f"{step_name} failed with empty errorText"

    # Server must still be alive after 9 calls
    ping = _go_style_post(integration_server, "Ping", {})
    assert ping["ok"] is True
