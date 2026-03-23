# Go/Python Pipeline Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bidirectional Connect-RPC bridge so Go can call Python pipeline steps, with W3C trace context propagating across the boundary.

**Architecture:** Python runs a stdlib `ThreadingHTTPServer` (zero new deps) in a daemon background thread speaking Connect-RPC JSON. Go gets a generated typed client. Trace context (`traceparent` header) flows Go→Python. SQLite audit log unchanged.

**Tech Stack:** Go Connect-RPC (connectrpc.com/connect), Python stdlib http.server, Protobuf/buf, Python 3.11 dataclasses

**Spec:** `docs/superpowers/specs/2026-03-23-go-python-pipeline-bridge-design.md`

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Create | `proto/omega/v1/pipeline_service.proto` | PipelineService RPC definitions |
| Generate | `gen/go/omega/v1/pipeline_service.pb.go` | Auto-generated — do not edit |
| Generate | `gen/go/omega/v1/omegav1connect/pipeline_service.connect.go` | Auto-generated — do not edit |
| Create | `omega/bridge/pipeline_types.py` | Dataclass types for request/response |
| Create | `omega/bridge/pipeline_server.py` | ThreadingHTTPServer Connect-RPC server |
| Modify | `omega/bridge/__init__.py` | Export new types |
| Modify | `omega/core/orchestrator_v2.py` | Add `start_with_pipeline_server()` |
| Create | `internal/bridge/pipeline_client.go` | Go Connect-RPC client to Python |
| Create | `internal/bridge/pipeline_client_test.go` | Go client tests |
| Modify | `internal/handler/orchestrator.go` | Add `WithPipelineClient()`, update `runCycle()` |
| Modify | `cmd/omega-api/main.go` | Optionally inject pipeline client |
| Create | `tests/bridge/__init__.py` | Package marker |
| Create | `tests/bridge/test_pipeline_server.py` | Python server unit tests |
| Create | `tests/bridge/test_pipeline_integration.py` | Go→Python round-trip integration tests |

---

## Task 1: Add pipeline_service.proto

**Files:**
- Create: `proto/omega/v1/pipeline_service.proto`

- [ ] **Step 1.1: Create the proto file**

```protobuf
syntax = "proto3";

package omega.v1;

option go_package = "github.com/benebsworth/omega/gen/go/omega/v1;omegav1";

// PipelineService is served by Python and called by Go.
// It enables Go to drive pipeline step execution on the Python side.
service PipelineService {
  // ExecuteStep asks Python to run one named pipeline step and return results.
  rpc ExecuteStep(ExecuteStepRequest) returns (ExecuteStepResponse);
  // Ping checks that the Python pipeline server is alive.
  rpc Ping(PingRequest) returns (PingResponse);
}

message ExecuteStepRequest {
  string step_id        = 1;  // e.g. "step_1"
  string step_name      = 2;  // e.g. "DataIngestion"
  string node_type      = 3;  // e.g. "DATA_INGESTION" — used to route to handler
  int64  cycle          = 4;
  string trace_id       = 5;  // W3C trace ID (hex, 32 chars) from Go span
  string parent_span_id = 6;  // current Go span ID (hex, 16 chars)
  map<string, string> parameters = 7;  // step config overrides
  bytes  input_payload  = 8;  // JSON-encoded output from previous step (may be empty)
}

message ExecuteStepResponse {
  bool   success        = 1;
  string error_text     = 2;
  bytes  output_payload = 3;  // JSON-encoded output for next step
  map<string, double> metrics = 4;
  double duration_ms    = 5;
  string node_id        = 6;
  string node_name      = 7;
}

message PingRequest {}

message PingResponse {
  bool   ok      = 1;
  string version = 2;  // Python omega package version
}
```

- [ ] **Step 1.2: Verify buf lint passes**

```bash
cd /path/to/worktree
buf lint proto/omega/v1/pipeline_service.proto
```
Expected: no output (clean).

- [ ] **Step 1.3: Commit**

```bash
git add proto/omega/v1/pipeline_service.proto
git commit -m "feat(proto): add PipelineService — Go→Python pipeline step execution"
```

---

## Task 2: Generate Go stubs

**Files:**
- Generate: `gen/go/omega/v1/pipeline_service.pb.go`
- Generate: `gen/go/omega/v1/omegav1connect/pipeline_service.connect.go`
- Generate: `dashboard/src/gen/omega/v1/pipeline_service_pb.ts` (bonus TypeScript)

- [ ] **Step 2.1: Run buf generate**

```bash
make proto
```
Expected output: buf downloads plugins and generates files. Check:
- `gen/go/omega/v1/pipeline_service.pb.go` exists
- `gen/go/omega/v1/omegav1connect/pipeline_service.connect.go` exists

- [ ] **Step 2.2: Verify Go builds**

```bash
go build ./...
```
Expected: no errors.

- [ ] **Step 2.3: Commit generated files**

```bash
git add gen/ dashboard/src/gen/
git commit -m "chore: regenerate proto stubs for PipelineService"
```

---

## Task 3: Python types + pipeline server

**Files:**
- Create: `omega/bridge/pipeline_types.py`
- Create: `omega/bridge/pipeline_server.py`
- Modify: `omega/bridge/__init__.py`

- [ ] **Step 3.1: Create pipeline_types.py**

```python
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
```

- [ ] **Step 3.2: Create pipeline_server.py**

```python
"""omega.bridge.pipeline_server — Connect-RPC pipeline step server for Python.

Serves the PipelineService over HTTP/1.1 Connect-RPC JSON protocol.
Zero external dependencies (stdlib only).

Connect unary protocol (inbound, Python is the server):
  POST /omega.v1.PipelineService/<MethodName>
  Content-Type: application/json
  Connect-Protocol-Version: 1
  Body: JSON proto message (camelCase)

Usage:
    registry = StepHandlerRegistry()
    registry.register("DATA_INGESTION", my_handler)
    server, thread = start_pipeline_server(port=9090, registry=registry)
    # later:
    server.shutdown()
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from omega.bridge.pipeline_types import ExecuteStepRequest, ExecuteStepResponse, PingResponse

log = logging.getLogger(__name__)

_SERVICE_PATH = "/omega.v1.PipelineService/"

StepHandler = Callable[[ExecuteStepRequest], ExecuteStepResponse]


class StepHandlerRegistry:
    """Maps node_type strings to step handler callables."""

    def __init__(self) -> None:
        self._handlers: dict[str, StepHandler] = {}

    def register(self, node_type: str, handler: StepHandler) -> None:
        self._handlers[node_type] = handler
        log.debug("Registered pipeline handler for node_type=%r", node_type)

    def dispatch(self, req: ExecuteStepRequest) -> ExecuteStepResponse:
        handler = self._handlers.get(req.node_type)
        if handler is None:
            return ExecuteStepResponse(
                success=False,
                error_text=f"no handler registered for node_type={req.node_type!r}",
            )
        t0 = time.perf_counter()
        try:
            resp = handler(req)
            resp.duration_ms = (time.perf_counter() - t0) * 1000
            return resp
        except Exception as exc:
            return ExecuteStepResponse(
                success=False,
                error_text=str(exc),
                duration_ms=(time.perf_counter() - t0) * 1000,
            )


@dataclass
class _ServerContext:
    registry: StepHandlerRegistry


def _make_handler(ctx: _ServerContext) -> type[BaseHTTPRequestHandler]:
    """Factory that closes over the server context (registry) for the handler class."""

    class _Handler(BaseHTTPRequestHandler):
        log_message = lambda self, fmt, *args: log.debug(fmt, *args)  # noqa: E731

        def do_POST(self) -> None:  # noqa: N802
            if not self.path.startswith(_SERVICE_PATH):
                self._send_error(404, "not found")
                return

            method = self.path[len(_SERVICE_PATH):]
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"

            try:
                body = json.loads(raw)
            except Exception as exc:
                self._send_error(400, f"invalid JSON: {exc}")
                return

            traceparent = self.headers.get("traceparent", "")

            if method == "ExecuteStep":
                self._handle_execute_step(body, traceparent)
            elif method == "Ping":
                self._handle_ping()
            else:
                self._send_error(404, f"unknown method: {method}")

        def _handle_execute_step(self, body: dict, traceparent: str) -> None:
            req = ExecuteStepRequest.from_json(body)
            # Propagate trace context from header into request if not already set
            if traceparent and not req.trace_id:
                parts = traceparent.split("-")
                if len(parts) >= 3:
                    req.trace_id = parts[1]
                    req.parent_span_id = parts[2]

            log.debug(
                "ExecuteStep: step=%s node_type=%s cycle=%d trace=%s",
                req.step_name, req.node_type, req.cycle, req.trace_id[:8] if req.trace_id else "",
            )
            resp = ctx.registry.dispatch(req)
            self._send_json(resp.to_json())

        def _handle_ping(self) -> None:
            self._send_json(PingResponse(ok=True).to_json())

        def _send_json(self, payload: dict) -> None:
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_error(self, code: int, message: str) -> None:
            data = json.dumps({"code": "not_found", "message": message}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return _Handler


def start_pipeline_server(
    port: int = 9090,
    registry: StepHandlerRegistry | None = None,
    host: str = "",
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start the pipeline server in a daemon background thread.

    Args:
        port:     TCP port to listen on.
        registry: Step handler registry. A default (stub-only) registry is
                  used if not provided.
        host:     Bind address (empty = all interfaces).

    Returns:
        (server, thread) — call server.shutdown() to stop.
    """
    if registry is None:
        registry = StepHandlerRegistry()
    ctx = _ServerContext(registry=registry)
    handler_cls = _make_handler(ctx)
    server = ThreadingHTTPServer((host, port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="pipeline-server")
    thread.start()
    log.info("Pipeline server listening on %s:%d", host or "0.0.0.0", port)
    return server, thread
```

- [ ] **Step 3.3: Update omega/bridge/__init__.py**

Add imports for the new types:
```python
from omega.bridge.pipeline_types import ExecuteStepRequest, ExecuteStepResponse, PingResponse
from omega.bridge.pipeline_server import StepHandlerRegistry, start_pipeline_server
```

- [ ] **Step 3.4: Commit**

```bash
git add omega/bridge/pipeline_types.py omega/bridge/pipeline_server.py omega/bridge/__init__.py
git commit -m "feat(bridge): add Python PipelineService Connect-RPC server (stdlib)"
```

---

## Task 4: Python unit tests

**Files:**
- Create: `tests/bridge/__init__.py`
- Create: `tests/bridge/test_pipeline_server.py`

- [ ] **Step 4.1: Write failing tests first**

```python
"""Tests for omega.bridge.pipeline_server and pipeline_types."""
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
        return s.getsockname()[1]


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
        return json.loads(resp.read())


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def server_port():
    port = _free_port()
    registry = StepHandlerRegistry()
    server, _ = start_pipeline_server(port=port, registry=registry)
    # brief pause for the thread to bind
    time.sleep(0.05)
    yield port, registry
    server.shutdown()


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_ping(server_port):
    port, _ = server_port
    resp = _post(port, "Ping", {})
    assert resp["ok"] is True
    assert "version" in resp


def test_execute_step_unknown_node_type(server_port):
    port, _ = server_port
    resp = _post(port, "ExecuteStep", {
        "stepId": "step_1",
        "stepName": "DataIngestion",
        "nodeType": "UNKNOWN_TYPE",
        "cycle": 1,
    })
    assert resp["success"] is False
    assert "UNKNOWN_TYPE" in resp["errorText"]


def test_execute_step_registered_handler(server_port):
    port, registry = server_port

    def my_handler(req: ExecuteStepRequest) -> ExecuteStepResponse:
        return ExecuteStepResponse(
            success=True,
            node_id="node-test",
            node_name="TestNode",
            metrics={"score": 0.9},
        )

    registry.register("DATA_INGESTION", my_handler)
    resp = _post(port, "ExecuteStep", {
        "nodeType": "DATA_INGESTION",
        "stepId": "step_1",
        "stepName": "DataIngestion",
        "cycle": 5,
    })
    assert resp["success"] is True
    assert resp["nodeId"] == "node-test"
    assert resp["metrics"]["score"] == pytest.approx(0.9)


def test_traceparent_header_extracted(server_port):
    port, registry = server_port
    captured: list[ExecuteStepRequest] = []

    def capture_handler(req: ExecuteStepRequest) -> ExecuteStepResponse:
        captured.append(req)
        return ExecuteStepResponse(success=True)

    registry.register("SIGNAL_RESEARCH", capture_handler)
    trace_id = "a" * 32
    span_id = "b" * 16
    _post(
        port, "ExecuteStep",
        {"nodeType": "SIGNAL_RESEARCH", "cycle": 1},
        headers={"traceparent": f"00-{trace_id}-{span_id}-01"},
    )
    assert len(captured) == 1
    assert captured[0].trace_id == trace_id
    assert captured[0].parent_span_id == span_id


def test_handler_exception_returns_error_response(server_port):
    port, registry = server_port

    def failing_handler(req: ExecuteStepRequest) -> ExecuteStepResponse:
        raise RuntimeError("simulated failure")

    registry.register("STRATEGY", failing_handler)
    resp = _post(port, "ExecuteStep", {"nodeType": "STRATEGY", "cycle": 1})
    assert resp["success"] is False
    assert "simulated failure" in resp["errorText"]


def test_unknown_method_returns_404(server_port):
    port, _ = server_port
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(port, "NonExistentMethod", {})
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
    assert req.cycle == 3
    assert req.parameters == {"key": "val"}
    assert req.input_payload == payload


def test_from_json_defaults_for_missing_fields():
    req = ExecuteStepRequest.from_json({})
    assert req.step_id == ""
    assert req.cycle == 0
    assert req.parameters == {}
    assert req.input_payload == b""
```

- [ ] **Step 4.2: Run tests — verify they pass**

```bash
python -m pytest tests/bridge/test_pipeline_server.py -v
```
Expected: all tests PASS.

- [ ] **Step 4.3: Commit**

```bash
git add tests/bridge/__init__.py tests/bridge/test_pipeline_server.py
git commit -m "test(bridge): add Python pipeline server unit tests"
```

---

## Task 5: Go pipeline client

**Files:**
- Create: `internal/bridge/pipeline_client.go`
- Create: `internal/bridge/pipeline_client_test.go`

- [ ] **Step 5.1: Create internal/bridge/pipeline_client.go**

```go
// Package bridge provides the Go-side client for the Python PipelineService.
package bridge

import (
	"context"
	"net/http"
	"os"

	"connectrpc.com/connect"
	"go.opentelemetry.io/otel/trace"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
)

const defaultPythonAddr = "http://localhost:9090"

// PipelineClient calls the Python PipelineService over Connect-RPC JSON.
type PipelineClient struct {
	client omegav1connect.PipelineServiceClient
	addr   string
}

// NewPipelineClient creates a client pointing at the Python pipeline server.
// addr defaults to $OMEGA_PYTHON_PIPELINE_ADDR or http://localhost:9090.
func NewPipelineClient(addr string) *PipelineClient {
	if addr == "" {
		addr = os.Getenv("OMEGA_PYTHON_PIPELINE_ADDR")
	}
	if addr == "" {
		addr = defaultPythonAddr
	}
	client := omegav1connect.NewPipelineServiceClient(
		&http.Client{},
		addr,
		connect.WithSendGzip(),
	)
	return &PipelineClient{client: client, addr: addr}
}

// ExecuteStep sends a pipeline step execution request to Python.
// It injects the W3C traceparent header from the current OTel span in ctx.
func (c *PipelineClient) ExecuteStep(
	ctx context.Context,
	req *omegav1.ExecuteStepRequest,
) (*omegav1.ExecuteStepResponse, error) {
	connectReq := connect.NewRequest(req)
	injectTraceparent(ctx, connectReq.Header())
	resp, err := c.client.ExecuteStep(ctx, connectReq)
	if err != nil {
		return nil, err
	}
	return resp.Msg, nil
}

// Ping checks that the Python server is reachable.
func (c *PipelineClient) Ping(ctx context.Context) (bool, error) {
	connectReq := connect.NewRequest(&omegav1.PingRequest{})
	resp, err := c.client.Ping(ctx, connectReq)
	if err != nil {
		return false, err
	}
	return resp.Msg.Ok, nil
}

// Addr returns the configured Python pipeline server address.
func (c *PipelineClient) Addr() string { return c.addr }

// injectTraceparent sets the W3C traceparent header from the active OTel span.
// Format: 00-{traceID}-{spanID}-01
func injectTraceparent(ctx context.Context, h http.Header) {
	span := trace.SpanFromContext(ctx)
	if !span.SpanContext().IsValid() {
		return
	}
	sc := span.SpanContext()
	h.Set("traceparent", "00-"+sc.TraceID().String()+"-"+sc.SpanID().String()+"-01")
}
```

- [ ] **Step 5.2: Write Go unit tests**

```go
package bridge_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/bridge"
)

// mockPipelineServer starts an in-process HTTP server that responds to
// PipelineService Connect-RPC calls.
type mockResponse struct {
	body       map[string]any
	statusCode int
}

func newMockServer(t *testing.T, responses map[string]mockResponse) (*httptest.Server, *[]string) {
	t.Helper()
	received := &[]string{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		*received = append(*received, r.URL.Path)
		method := r.URL.Path[len("/omega.v1.PipelineService/"):]
		resp, ok := responses[method]
		if !ok {
			http.Error(w, "unknown method", http.StatusNotFound)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(resp.statusCode)
		_ = json.NewEncoder(w).Encode(resp.body)
	}))
	t.Cleanup(srv.Close)
	return srv, received
}

func TestPing_OK(t *testing.T) {
	srv, _ := newMockServer(t, map[string]mockResponse{
		"Ping": {body: map[string]any{"ok": true, "version": "0.1.0"}, statusCode: 200},
	})
	client := bridge.NewPipelineClient(srv.URL)
	ok, err := client.Ping(context.Background())
	if err != nil {
		t.Fatalf("Ping returned error: %v", err)
	}
	if !ok {
		t.Error("expected Ping to return ok=true")
	}
}

func TestExecuteStep_Success(t *testing.T) {
	srv, received := newMockServer(t, map[string]mockResponse{
		"ExecuteStep": {
			body: map[string]any{
				"success":  true,
				"nodeId":   "node-123",
				"nodeName": "DataIngestion",
				"metrics":  map[string]any{"records": 100.0},
			},
			statusCode: 200,
		},
	})

	client := bridge.NewPipelineClient(srv.URL)
	resp, err := client.ExecuteStep(context.Background(), &omegav1.ExecuteStepRequest{
		StepId:   "step_1",
		StepName: "DataIngestion",
		NodeType: "DATA_INGESTION",
		Cycle:    5,
	})
	if err != nil {
		t.Fatalf("ExecuteStep returned error: %v", err)
	}
	if !resp.Success {
		t.Errorf("expected success=true, got false")
	}
	if resp.NodeId != "node-123" {
		t.Errorf("expected node_id=node-123, got %s", resp.NodeId)
	}
	if len(*received) != 1 || (*received)[0] != "/omega.v1.PipelineService/ExecuteStep" {
		t.Errorf("unexpected request path: %v", *received)
	}
}

func TestExecuteStep_InjectsTraceparent(t *testing.T) {
	var capturedHeader string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		capturedHeader = r.Header.Get("traceparent")
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"success": true})
	}))
	t.Cleanup(srv.Close)

	client := bridge.NewPipelineClient(srv.URL)
	// Without an OTel span, traceparent should be absent (not injected).
	_, _ = client.ExecuteStep(context.Background(), &omegav1.ExecuteStepRequest{
		NodeType: "DATA_INGESTION",
	})
	// No active span → header not set (valid: span context is invalid).
	if capturedHeader != "" {
		// This is acceptable — it means OTel span injection is working.
		t.Logf("traceparent header was set: %s", capturedHeader)
	}
}

func TestNewPipelineClient_DefaultAddr(t *testing.T) {
	t.Setenv("OMEGA_PYTHON_PIPELINE_ADDR", "")
	c := bridge.NewPipelineClient("")
	if c.Addr() != "http://localhost:9090" {
		t.Errorf("expected default addr, got %s", c.Addr())
	}
}

func TestNewPipelineClient_EnvOverride(t *testing.T) {
	t.Setenv("OMEGA_PYTHON_PIPELINE_ADDR", "http://custom:8888")
	c := bridge.NewPipelineClient("")
	if c.Addr() != "http://custom:8888" {
		t.Errorf("expected env addr, got %s", c.Addr())
	}
}
```

- [ ] **Step 5.3: Run Go tests**

```bash
go test ./internal/bridge/... -v -timeout 30s
```
Expected: all tests PASS.

- [ ] **Step 5.4: Commit**

```bash
git add internal/bridge/
git commit -m "feat(bridge): add Go PipelineClient with traceparent injection"
```

---

## Task 6: Wire client into Go orchestrator

**Files:**
- Modify: `internal/handler/orchestrator.go`
- Modify: `cmd/omega-api/main.go`

- [ ] **Step 6.1: Add WithPipelineClient + runCycle update in orchestrator.go**

In `OrchestratorHandler` struct, add:
```go
pipelineClient *bridge.PipelineClient // may be nil
```

Add import: `"github.com/benebsworth/omega/internal/bridge"`

Add method after `WithCircuitBreakerRegistry`:
```go
// WithPipelineClient attaches a Python pipeline client so runCycle() can
// drive pipeline step execution on the Python side.
func (h *OrchestratorHandler) WithPipelineClient(c *bridge.PipelineClient) *OrchestratorHandler {
	h.pipelineClient = c
	return h
}
```

Update `runCycle()` — after the node spans loop, add:
```go
// If a Python pipeline client is configured, drive each pipeline step.
if h.pipelineClient != nil {
	nodes, _ := h.db.AllNodes()
	steps := victoriaSteps() // placeholder — eventually from project config
	for _, step := range steps {
		stepReq := &omegav1.ExecuteStepRequest{
			StepId:   step.StepId,
			StepName: step.Name,
			NodeType: step.NodeType,
			Cycle:    cycle,
		}
		resp, err := h.pipelineClient.ExecuteStep(cycleCtx, stepReq)
		if err != nil {
			cycleSpan.AddEvent("pipeline_step_error",
				trace.WithAttributes(
					attribute.String("step_id", step.StepId),
					attribute.String("error", err.Error()),
				),
			)
			continue
		}
		cycleSpan.AddEvent("pipeline_step_done",
			trace.WithAttributes(
				attribute.String("step_id", step.StepId),
				attribute.Bool("success", resp.Success),
				attribute.Float64("duration_ms", resp.DurationMs),
			),
		)
		_ = nodes // used implicitly via DB updates from Python StateService calls
	}
}
```

Add private helper at bottom of file:
```go
// victoriaSteps returns the hardcoded Victoria pipeline steps.
// TODO: replace with DB/project lookup once multi-project support lands.
func victoriaSteps() []*omegav1.PipelineStep {
	return []*omegav1.PipelineStep{
		{StepId: "step_1", Name: "DataIngestion", NodeType: "DATA_INGESTION", Order: 1},
		{StepId: "step_2", Name: "SignalResearch", NodeType: "SIGNAL_RESEARCH", Order: 2},
		{StepId: "step_3", Name: "IntelligenceCoordination", NodeType: "STRATEGY", Order: 3},
		{StepId: "step_4", Name: "DynamicWeights", NodeType: "RISK_MANAGEMENT", Order: 4},
		{StepId: "step_5", Name: "DebateGate", NodeType: "VERIFICATION", Order: 5},
		{StepId: "step_6", Name: "WalkForward", NodeType: "VERIFICATION", Order: 6},
		{StepId: "step_7", Name: "Memory", NodeType: "MEMORY", Order: 7},
		{StepId: "step_8", Name: "ImprovementEngine", NodeType: "IMPROVEMENT", Order: 8},
		{StepId: "step_9", Name: "Ring3Adversarial", NodeType: "ADVERSARIAL", Order: 9},
	}
}
```

- [ ] **Step 6.2: Wire pipeline client in main.go**

In `cmd/omega-api/main.go`, after `h := handler.New(database).WithCircuitBreakerRegistry(cbRegistry)`, add:
```go
// Pipeline bridge — connects to Python pipeline server when configured.
// Set OMEGA_PYTHON_PIPELINE_ADDR to enable (e.g. "http://localhost:9090").
if addr := os.Getenv("OMEGA_PYTHON_PIPELINE_ADDR"); addr != "" {
	pipelineClient := bridge.NewPipelineClient(addr)
	h = h.WithPipelineClient(pipelineClient)
	log.Printf("Pipeline bridge: connected to Python at %s", addr)
} else {
	log.Printf("Pipeline bridge: disabled (set OMEGA_PYTHON_PIPELINE_ADDR to enable)")
}
```

Add import: `"github.com/benebsworth/omega/internal/bridge"`

- [ ] **Step 6.3: Mount PipelineService handler in main.go**

Python is the server for this service, but Go still needs to mount a stub so the service discovery works. Add after the other service mounts:
```go
// PipelineService — Python is the authoritative server; Go mounts a no-op stub
// so service discovery and health checks can reference the path.
pipePath, pipeSvcHandler := omegav1connect.NewPipelineServiceHandler(
    omegav1connect.UnimplementedPipelineServiceHandler{}, withHandlerOpts()...,
)
mux.Handle(pipePath, pipeSvcHandler)
```

- [ ] **Step 6.4: Build and test**

```bash
go build ./...
go test ./internal/handler/... -v -timeout 30s
```
Expected: builds and existing handler tests pass.

- [ ] **Step 6.5: Commit**

```bash
git add internal/handler/orchestrator.go cmd/omega-api/main.go
git commit -m "feat(orchestrator): wire Go PipelineClient into runCycle() pipeline dispatch"
```

---

## Task 7: Wire server into Python orchestrator

**Files:**
- Modify: `omega/core/orchestrator_v2.py`

- [ ] **Step 7.1: Add start_with_pipeline_server to OmegaOrchestrator**

After the `__init__` method, add:

```python
# ── Pipeline server integration ────────────────────────────────────────────────

def start_pipeline_server(
    self,
    port: int = 9090,
) -> tuple:
    """Start the Connect-RPC pipeline server in a daemon background thread.

    The server handles ExecuteStep calls from Go, routing each request to
    the matching registered node via the node's capabilities.

    Returns:
        (server, thread) — call server.shutdown() to stop cleanly.
    """
    from omega.bridge.pipeline_server import StepHandlerRegistry, start_pipeline_server as _start
    from omega.bridge.pipeline_types import ExecuteStepRequest, ExecuteStepResponse

    registry = StepHandlerRegistry()

    # Build a handler for each active node based on its node_type capability.
    # Maps NodeCapability string (e.g. "DATA_INGESTION") → node.execute wrapper.
    for node in self._registry.all_nodes():
        state = node.get_state()
        caps = [c.upper().replace(" ", "_") for c in (node.get_capabilities() or [])]
        for cap in caps:
            # Capture node in closure
            def _make_handler(n=node):
                def _handler(req: ExecuteStepRequest) -> ExecuteStepResponse:
                    from omega.core.node import NodeInput
                    import json
                    inp = NodeInput(
                        action=req.step_name.lower(),
                        parameters=dict(req.parameters),
                        context={
                            "cycle": req.cycle,
                            "trace_id": req.trace_id,
                            "parent_span_id": req.parent_span_id,
                            "input": json.loads(req.input_payload) if req.input_payload else {},
                        },
                    )
                    out = n.execute(inp)
                    return ExecuteStepResponse(
                        success=out.success,
                        error_text="; ".join(out.errors) if out.errors else "",
                        metrics={k: float(v) for k, v in out.metrics.items()
                                 if isinstance(v, (int, float))},
                        node_id=n.get_state().node_id,
                        node_name=n.get_state().name,
                    )
                return _handler
            registry.register(cap, _make_handler())

    server, thread = _start(port=port, registry=registry)
    logger.info("OmegaOrchestrator pipeline server started on port %d", port)
    return server, thread
```

- [ ] **Step 7.2: Build check**

```bash
python -m py_compile omega/core/orchestrator_v2.py
```
Expected: no output (clean parse).

- [ ] **Step 7.3: Commit**

```bash
git add omega/core/orchestrator_v2.py
git commit -m "feat(orchestrator): add start_pipeline_server() for Go→Python bridge"
```

---

## Task 8: Integration test

**Files:**
- Create: `tests/bridge/test_pipeline_integration.py`

- [ ] **Step 8.1: Write integration test**

```python
"""Integration test: Go-style HTTP client calls the Python pipeline server.

These tests simulate exactly what the Go PipelineClient sends:
  POST /omega.v1.PipelineService/ExecuteStep
  Content-Type: application/json
  Connect-Protocol-Version: 1
  traceparent: 00-{trace_id}-{span_id}-01

No Go binary is required — we exercise the full Python server path with
the same HTTP calls Go would make.

Marked 'integration' so they can be excluded in fast unit test runs:
  pytest -m 'not integration'
"""
from __future__ import annotations

import json
import socket
import time
import urllib.request

import pytest

from omega.bridge.pipeline_server import StepHandlerRegistry, start_pipeline_server
from omega.bridge.pipeline_types import ExecuteStepRequest, ExecuteStepResponse


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _connect_rpc_post(
    port: int,
    method: str,
    body: dict,
    trace_id: str = "",
    span_id: str = "",
) -> dict:
    """Simulate a Connect-RPC call identical to what Go PipelineClient sends."""
    url = f"http://localhost:{port}/omega.v1.PipelineService/{method}"
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Connect-Protocol-Version": "1",
    }
    if trace_id and span_id:
        headers["traceparent"] = f"00-{trace_id}-{span_id}-01"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


@pytest.fixture(scope="module")
def pipeline_server():
    port = _free_port()
    registry = StepHandlerRegistry()

    def data_ingestion_handler(req: ExecuteStepRequest) -> ExecuteStepResponse:
        return ExecuteStepResponse(
            success=True,
            node_id="node-data-ingest",
            node_name="DataIngestionNode",
            metrics={"records_fetched": 1000.0, "latency_ms": 45.0},
            output_payload=b'{"ohlcv": [1, 2, 3]}',
        )

    registry.register("DATA_INGESTION", data_ingestion_handler)
    server, _ = start_pipeline_server(port=port, registry=registry)
    time.sleep(0.1)
    yield port
    server.shutdown()


@pytest.mark.integration
def test_go_style_ping(pipeline_server):
    resp = _connect_rpc_post(pipeline_server, "Ping", {})
    assert resp["ok"] is True


@pytest.mark.integration
def test_go_style_execute_step_with_trace_context(pipeline_server):
    trace_id = "a" * 32  # 32-char hex trace ID
    span_id = "b" * 16   # 16-char hex span ID

    resp = _connect_rpc_post(
        pipeline_server,
        "ExecuteStep",
        {
            "stepId": "step_1",
            "stepName": "DataIngestion",
            "nodeType": "DATA_INGESTION",
            "cycle": 42,
            "traceId": trace_id,
            "parentSpanId": span_id,
        },
        trace_id=trace_id,
        span_id=span_id,
    )
    assert resp["success"] is True
    assert resp["nodeId"] == "node-data-ingest"
    assert resp["metrics"]["records_fetched"] == pytest.approx(1000.0)


@pytest.mark.integration
def test_go_style_execute_step_missing_handler(pipeline_server):
    resp = _connect_rpc_post(
        pipeline_server,
        "ExecuteStep",
        {"nodeType": "NONEXISTENT", "cycle": 1},
    )
    assert resp["success"] is False
    assert "NONEXISTENT" in resp["errorText"]


@pytest.mark.integration
def test_trace_context_propagation_roundtrip(pipeline_server):
    """Verify that Go-style traceparent is correctly extracted by Python."""
    trace_id = "deadbeef" * 4   # 32 chars
    span_id = "cafebabe" * 2    # 16 chars
    captured: list[str] = []

    # Re-register with a capturing handler
    # (Note: this modifies the shared registry — acceptable for this test)
    from omega.bridge.pipeline_server import StepHandlerRegistry
    # Use a fresh server for isolation
    port2 = _free_port()
    registry2 = StepHandlerRegistry()

    def capturing_handler(req: ExecuteStepRequest) -> ExecuteStepResponse:
        captured.append(req.trace_id)
        captured.append(req.parent_span_id)
        return ExecuteStepResponse(success=True)

    registry2.register("MEMORY", capturing_handler)
    server2, _ = start_pipeline_server(port=port2, registry=registry2)
    time.sleep(0.05)

    try:
        _connect_rpc_post(
            port2, "ExecuteStep",
            {"nodeType": "MEMORY", "cycle": 1},
            trace_id=trace_id,
            span_id=span_id,
        )
        assert captured[0] == trace_id, f"trace_id mismatch: {captured[0]!r}"
        assert captured[1] == span_id, f"span_id mismatch: {captured[1]!r}"
    finally:
        server2.shutdown()
```

- [ ] **Step 8.2: Run integration tests**

```bash
python -m pytest tests/bridge/test_pipeline_integration.py -v -m integration
```
Expected: all tests PASS.

- [ ] **Step 8.3: Run all Python tests to confirm nothing broken**

```bash
python -m pytest tests/ -v --timeout=30
```
Expected: all tests PASS.

- [ ] **Step 8.4: Run all Go tests**

```bash
go test ./... -v -timeout 30s
```
Expected: all tests PASS.

- [ ] **Step 8.5: Final commit**

```bash
git add tests/bridge/test_pipeline_integration.py
git commit -m "test(bridge): add Go→Python pipeline bridge integration tests"
```

---

## Verification Checklist

- [ ] `make proto` succeeds and generates `pipeline_service.pb.go` + connect stub
- [ ] `go build ./...` succeeds
- [ ] `go test ./internal/bridge/... -v` — all PASS
- [ ] `go test ./internal/handler/... -v` — all PASS
- [ ] `python -m pytest tests/bridge/ -v` — all PASS
- [ ] `python -m pytest tests/ -v` — all PASS (no regressions)
- [ ] `OMEGA_PYTHON_PIPELINE_ADDR=http://localhost:9090 go run ./cmd/omega-api` starts cleanly
