# Go/Python Pipeline Bridge — Design Spec

**Date:** 2026-03-23
**Status:** Approved
**Worktree:** `claude/nice-galileo`

---

## 1. Problem Statement

The Go `OrchestratorService` and the Python `OmegaOrchestrator` currently run as independent systems:

- Python's `orchestrator_v2.py` runs the full pipeline loop internally (data_poll → signals → strategy → adversarial → execute → post_cycle), calling its own node objects directly.
- Go's `runCycle()` only logs activity — it never invokes Python pipeline steps.
- Communication is one-directional: Python → Go (Python calls Go's StateService, AdversarialService, etc. via `omega/bridge/`).

There is no mechanism for Go to call Python, and Python has no RPC server endpoint.

**Goal:** Add bidirectional RPC so Go can drive pipeline step execution on the Python side, with W3C trace context flowing across the boundary.

---

## 2. Current Architecture (SQLite-IPC)

```
Python orchestrator_v2.py
  └── _step_data_poll()  ─┐
  └── _step_signals()     │  Direct Python function calls
  └── _step_strategy()    │  (no inter-process boundary)
  └── _step_adversarial() ┘
  └── omega/bridge/*_client.py  →  POST /omega.v1.*Service/*  →  Go API (:8080)

Go API (:8080)
  └── OrchestratorService.runCycle()  →  logs + spans only
  └── StateService, AdversarialService, etc.  →  SQLite writes
```

**Limitations of current approach:**
- Go cannot trigger Python pipeline steps — Go is an observer, not an orchestrator.
- No typed contract between Go and Python for pipeline execution.
- Trace context only flows Python→Go (via `traceparent` header in bridge calls), not Go→Python.
- Cannot run Go-driven orchestration experiments without forking the Python loop.

---

## 3. Proposed Architecture

Add a `PipelineService` — Python serves it, Go calls it.

```
Go API (:8080)
  └── OrchestratorHandler.runCycle()
        └── PipelineClient.ExecuteStep(ctx, stepReq)
              │  POST /omega.v1.PipelineService/ExecuteStep
              │  Header: traceparent: 00-{trace_id}-{span_id}-01
              ▼
Python Pipeline Server (:9090)  [background thread in orchestrator process]
  └── PipelineServiceHandler.handle_execute_step()
        └── step_registry[node_type].execute(inp)
              └── Returns ExecuteStepResponse with metrics + output
              │
              └── Reports back to Go StateService (existing bridge)
```

**Key properties:**
- Python server: stdlib `http.server.ThreadingHTTPServer`, zero new dependencies
- Protocol: Connect-RPC unary JSON (same as existing Go→Python and Python→Go calls)
- Go client: generated `connectrpc.com/connect` typed client from `PipelineService` proto
- Trace context: Go injects `traceparent` header; Python extracts it and propagates to node execution
- SQLite retained as audit log (Go StateService writes remain unchanged)

---

## 4. Protocol Definition

### 4.1 PipelineService Proto

File: `proto/omega/v1/pipeline_service.proto`

```protobuf
syntax = "proto3";
package omega.v1;
option go_package = "github.com/benebsworth/omega/gen/go/omega/v1;omegav1";

service PipelineService {
  // ExecuteStep asks the Python pipeline server to run one named step.
  rpc ExecuteStep(ExecuteStepRequest) returns (ExecuteStepResponse);
  // Ping checks that the Python server is alive.
  rpc Ping(PingRequest) returns (PingResponse);
}

message ExecuteStepRequest {
  string step_id          = 1;  // e.g. "step_1"
  string step_name        = 2;  // e.g. "DataIngestion"
  string node_type        = 3;  // e.g. "DATA_INGESTION"
  int64  cycle            = 4;
  string trace_id         = 5;  // W3C trace ID (hex, 32 chars)
  string parent_span_id   = 6;  // current Go span ID (hex, 16 chars)
  map<string, string> parameters = 7;  // step config overrides
  bytes  input_payload    = 8;  // JSON-encoded output from previous step
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
  string version = 2;  // Python omega version string
}
```

### 4.2 Trace Context Propagation

The W3C `traceparent` header is constructed by Go from the active OTel span and forwarded to Python:

```
traceparent: 00-{trace_id}-{parent_span_id}-01
```

Python extracts this from the HTTP request headers and includes `trace_id` / `parent_span_id` in its StateService calls (`begin_execution`, `begin_span`), closing the distributed trace.

---

## 5. Component Designs

### 5.1 Python Pipeline Types (`omega/bridge/pipeline_types.py`)

Stdlib `dataclasses` — no protobuf dependency at runtime.

```python
@dataclass
class ExecuteStepRequest:
    step_id: str
    step_name: str
    node_type: str
    cycle: int
    trace_id: str
    parent_span_id: str
    parameters: dict[str, str]
    input_payload: bytes  # JSON

@dataclass
class ExecuteStepResponse:
    success: bool
    error_text: str
    output_payload: bytes  # JSON
    metrics: dict[str, float]
    duration_ms: float
    node_id: str
    node_name: str
```

### 5.2 Python Pipeline Server (`omega/bridge/pipeline_server.py`)

- `ThreadingHTTPServer` on configurable port (default 9090)
- Handles `POST /omega.v1.PipelineService/ExecuteStep`
- Handles `POST /omega.v1.PipelineService/Ping`
- Extracts `traceparent` header
- Dispatches to `StepHandlerRegistry` (maps `node_type` → callable)
- Returns Connect-RPC JSON response
- Started by `start_pipeline_server(port, registry)` → returns `(server, thread)`
- Server is a daemon thread — exits with the parent process

### 5.3 Step Handler Registry (`omega/bridge/pipeline_server.py`)

```python
class StepHandlerRegistry:
    def register(self, node_type: str, handler: Callable[[ExecuteStepRequest], ExecuteStepResponse])
    def dispatch(self, req: ExecuteStepRequest) -> ExecuteStepResponse
```

Default handlers registered for each of the 9 Victoria pipeline steps (DATA_INGESTION, SIGNAL_RESEARCH, STRATEGY, RISK_MANAGEMENT, VERIFICATION, MEMORY, IMPROVEMENT, ADVERSARIAL) — initially return a stub "not implemented" response so the server starts cleanly.

### 5.4 Go Pipeline Client (`internal/bridge/pipeline_client.go`)

```go
type PipelineClient struct {
    client omegav1connect.PipelineServiceClient
    addr   string
}

func NewPipelineClient(addr string) *PipelineClient
func (c *PipelineClient) ExecuteStep(ctx context.Context, req *omegav1.ExecuteStepRequest) (*omegav1.ExecuteStepResponse, error)
func (c *PipelineClient) Ping(ctx context.Context) (bool, error)
```

- `addr` defaults to `$OMEGA_PYTHON_PIPELINE_ADDR` or `http://localhost:9090`
- `ExecuteStep` injects `traceparent` from the current `ctx` OTel span before calling

### 5.5 Go Orchestrator Integration

`OrchestratorHandler` gains:
```go
func (h *OrchestratorHandler) WithPipelineClient(c *bridge.PipelineClient) *OrchestratorHandler
```

When `h.pipelineClient != nil`, `runCycle()` iterates the project's `PipelineConfig` steps in order and calls `pipelineClient.ExecuteStep()` for each, recording results via the existing StateService DB writes.

---

## 6. Migration Path

| Phase | What | SQLite role |
|-------|------|-------------|
| Current | Python writes SQLite directly + via Go StateService | Write authority (partial) |
| Phase 1 (complete) | Go is sole SQLite write authority; Python calls Go StateService | Audit log |
| **This spec** | Go can call Python pipeline steps via RPC | Audit log (unchanged) |
| Future | Go drives full pipeline orchestration; Python is execution engine only | Audit log |

SQLite is **retained as audit log** throughout. The `StateService` writes are unchanged. This spec adds a new communication direction without modifying any existing service.

---

## 7. Acceptance Criteria

- [ ] `proto/omega/v1/pipeline_service.proto` compiles and `make proto` succeeds
- [ ] Go `PipelineClient.Ping()` returns `ok=true` when Python server is running
- [ ] Go `PipelineClient.ExecuteStep()` sends a request and receives a valid response
- [ ] `traceparent` header is present in requests from Go and extracted by Python
- [ ] Python server starts cleanly in a background daemon thread
- [ ] Python server handles unknown `node_type` with a graceful error response
- [ ] Go unit tests for `PipelineClient` pass with a mock HTTP server
- [ ] Python unit tests for `pipeline_server` pass without any external services
- [ ] Integration test: Go client → Python server round-trip with trace context verification

---

## 8. Non-Goals

- Does not replace the existing Python orchestrator loop — Python can still self-orchestrate
- Does not change any existing proto service definitions
- Does not add any Python runtime dependencies beyond stdlib
- Does not implement actual pipeline step logic (step handlers return stubs initially)
- Does not change SQLite schema
