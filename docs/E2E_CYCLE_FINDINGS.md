# Omega E2E Cycle Assessment — Findings & Improvement Opportunities

**Date:** 2026-03-24
**Source:** Live E2E execution assessment of the Omega platform (branch: `claude/infallible-bouman`)
**Related:** `docs/EXECUTION_ASSESSMENT_2026_03_23.md`, `EVAL_GAP_ANALYSIS.md`

---

## Overview

This document captures the 15 improvement opportunities identified during the first live end-to-end execution assessment of the Omega platform. Each finding is categorised by type (Bug / Architecture / DX / Eval) and includes severity, affected component, and a recommended fix.

---

## Findings

### FINDING-001 — Heartbeat orchestration is a no-op
**Type:** Bug (Critical)
**Component:** `omega/runner.py` — `_heartbeat()`
**Status:** In Progress

The heartbeat loop broadcasts `action="run_cycle"` to every registered node. None of the Victoria nodes handle this action — each returns `NodeOutput(success=False, errors=["unknown action"])`. Every cycle completes without any real work being done.

**Fix:** Replace the `run_cycle` broadcast with a proper pipeline: DataIngestion → SignalGeneration → StrategyConstruction → RiskManagement in sequence, passing outputs as inputs to the next step.

---

### FINDING-002 — Paper trading not wired into runtime
**Type:** Bug (Critical)
**Component:** `omega/nodes/victoria/` — missing execution layer
**Status:** Open

The pipeline computes portfolio weights and signals but has no execution layer to:
1. Write signals to `victoria_signals`
2. Simulate order fills into `victoria_trades`
3. Track open positions in `victoria_portfolio`

`victoria_trades`, `victoria_portfolio`, and `victoria_signals` tables all have 0 rows.

**Fix:** Create `omega/nodes/victoria/paper_trading.py` with `PaperTradingEngine`. Wire it into the pipeline after the risk management step. This is Victoria-specific — it belongs in `omega/nodes/victoria/`, not in platform code.

---

### FINDING-003 — victoriaSteps() hardcoded in platform orchestrator
**Type:** Architecture (High)
**Component:** `internal/handler/orchestrator.go` — `victoriaSteps()`
**Status:** Open

The Go platform orchestrator has a hardcoded `victoriaSteps()` function with Victoria's 9 pipeline steps. This violates the platform/project separation rule: Omega is the platform, Victoria is a project running on it. Project-specific pipeline configs belong in the project registration, not in `internal/handler/orchestrator.go`.

**Fix:** `runCycle()` should read pipeline steps from the `ProjectHandler.AllProjects()` registry. Victoria's steps come from its `PipelineConfig` proto field (already seeded in `victoriaProject()` in `main.go`). Remove `victoriaSteps()`.

---

### FINDING-004 — Improvement engine never invoked from the heartbeat
**Type:** Bug (High)
**Component:** `omega/core/improvement_engine.py` — lifecycle integration
**Status:** Open

`ImprovementEngine` instantiates correctly with `make_state_backend()`. TPE proposes params and records outcomes in-memory. But the engine is never called from the runner heartbeat. `improvement_log` DB table: 0 rows.

**Fix:** Wire `ImprovementEngine` into `VictoriaNode` startup. After each cycle completes, if the project's `improvement_config.tpe_enabled=True`, call `evaluate_and_record()` with real cycle metrics. When TPE finds better params, call `apply_params()`.

---

### FINDING-005 — REST autonomy gate blocks /api/v1/nodes
**Type:** Bug (High)
**Component:** `internal/middleware/autonomy_gate.go`
**Status:** Open

`GET /api/v1/nodes` returns `autonomy gate: action "GET" is not permitted at PICO autonomy level`. The autonomy gate incorrectly matches the HTTP method string `"GET"` against its list of permitted action names. Dashboard REST paths are blocked.

**Fix:** The autonomy gate should only apply to semantic action names (e.g. `"run_cycle"`, `"improve"`) — not HTTP verbs. In `withExecChain`, REST paths under `/api/v1/` should pass through without hitting the gate, or the gate should skip HTTP method strings.

---

### FINDING-006 — Tracer.end_span() type confusion
**Type:** Bug (Medium)
**Component:** `omega/core/tracing.py` — `Tracer.end_span()`
**Status:** Open

`Tracer.end_span()` expects a `str` span_id but callers may pass a `TraceContext` object directly, producing `psycopg.ProgrammingError: cannot adapt type 'TraceContext'`. The correct call is `end_span(ctx.span_id)`.

**Fix:** Add runtime type coercion in `end_span()`: if the argument is a `TraceContext`, extract `.span_id`. Add a docstring clarifying the expected type.

---

### FINDING-007 — OTLP_ENDPOINT not set in default startup
**Type:** DX (Medium)
**Component:** `cmd/omega-api/main.go`, `Makefile`
**Status:** Open

Traces go to stdout only because `OTLP_ENDPOINT` is not set when running `make api`. The OTel collector stack is running at `localhost:4318` but the API doesn't know about it.

**Fix:** Add `OTLP_ENDPOINT=http://localhost:4318` to `make dev` and document it. When `OTLP_ENDPOINT` is unset, log a warning at startup.

---

### FINDING-008 — StateService BeginExecution writes not confirmed in Postgres
**Type:** Bug (Medium)
**Component:** `internal/handler/state.go` → Postgres connection
**Status:** Open

`StateService/BeginExecution` returns a successful exec_id but rows do not appear in Postgres. The running API instance may not be connected to the Postgres instance at port 5432. No `pg_stat_activity` connections from the Go process were observed.

**Fix:** Verify `DATABASE_URL` env var is set at startup. Log the resolved DB connection string (without password) at startup. Add a startup check that confirms `BeginExecution` roundtrips correctly.

---

### FINDING-009 — Adversarial review passes vacuously
**Type:** Bug (Medium)
**Component:** `omega/nodes/victoria/` — `DevilsAdvocateNode`
**Status:** Open

`DevilsAdvocateNode.execute(action="architectural_review")` returns `{"veto": false, "verdict": "APPROVED", "challenges": []}`. The challenges list is empty — the review passes without substantive scrutiny. `AdversarialPressureV2` constructor argument is set but never called in `_step_adversarial()`.

**Fix:** Wire `AdversarialPressureV2.run_v2()` in `_step_adversarial()`. Populate at least 3 default structural challenges (concentration risk, data staleness, signal correlation).

---

### FINDING-010 — Goal tracking table empty; GoalArchitecture disconnected
**Type:** Architecture (Medium)
**Component:** `omega/core/goals.py` — lifecycle integration
**Status:** Open

`GoalArchitecture` is initialised at startup (`INFO GoalArchitecture initialised objectives=[...]`) but is never called from the orchestrator. The HTN decomposition and balanced scorecard are dead code relative to the runtime. `goal_tracking` DB table: 0 rows.

**Fix:** After each cycle, call `GoalArchitecture.evaluate_cycle(cycle_metrics)` and write the result to `goal_tracking`. This is Victoria-specific and belongs in `omega/nodes/victoria/`, not platform code.

---

### FINDING-011 — Python trace IDs not W3C-compliant
**Type:** Architecture (Medium)
**Component:** `omega/core/tracing.py` — `TraceContext`
**Status:** Open

Python-generated trace IDs are not in W3C `traceparent` format (`version-trace_id-parent_id-flags`). Python and Go spans cannot be joined in Grafana/Tempo. Traces from a single Victoria cycle appear as two disconnected trees.

**Fix:** Generate W3C-compliant trace IDs in `TraceContext`. Propagate `traceparent` header when calling Go services. Register the Python trace ID as the parent when creating Go spans.

---

### FINDING-012 — Memory kernel writes no new memories during live runs
**Type:** Architecture (Low)
**Component:** `omega/nodes/victoria/` — memory integration
**Status:** Open

The Python memory kernel (`MemoryKernel`) initialises correctly but no new memories are written during cycle runs. The `semantic_memories` table has 1 seed row (from a prior session) but nothing accumulates. `ConsolidationPipeline` is tested in isolation but never triggered by live cycles.

**Fix:** After a cycle completes, extract key facts (e.g., signal directions, top/bottom performers, unusual volatility) and write them as episodic memories. Schedule consolidation every N cycles.

---

### FINDING-013 — No `make dev` target — startup requires multiple manual steps
**Type:** DX (Low)
**Component:** `Makefile`
**Status:** Open

Starting the dev environment requires:
1. `docker compose up -d postgres`
2. `python -m omega.bridge.pipeline_server` (background)
3. `go run ./cmd/omega-api` (foreground)

There is no single command to bring up the full stack.

**Fix:** Add `make dev` that starts Postgres, backgrounds the Python pipeline server, and runs the Go API in the foreground. Add `make dev-down` to clean up.

---

### FINDING-014 — No per-step visibility in CLI output
**Type:** DX (Low)
**Component:** `cmd/omega/run.go`
**Status:** Open

`omega run` polls health and shows a one-line summary per cycle (`status=HEALTHY score=0.600 nodes=13 cycles=1`). There is no visibility into which pipeline steps succeeded or failed, what latency each step took, or which step caused a cycle failure.

**Fix:** When running `omega run --cycles N`, show per-step success/failure and latency. Format: `step_name: success (123ms)` or `step_name: FAILED (error message)`. Show cycle summary at the end.

---

### FINDING-015 — CoordinationService not registered in main.go
**Type:** Bug (High)
**Component:** `cmd/omega-api/main.go` — service registration
**Status:** Fixed (2026-03-24)

`CoordinationService` handler exists in `internal/coordination/handler.go` but was not registered in `cmd/omega-api/main.go`. All calls to `/omega.v1.CoordinationService/Route` returned `404`.

The handler is now registered. `curl -X POST http://localhost:8080/omega.v1.CoordinationService/Route` returns 400/401 (not 404).

---

## Priority Matrix

| Finding | Type | Severity | Impact | Status |
|---|---|---|---|---|
| FINDING-001 | Bug | Critical | Every cycle is a no-op | In Progress |
| FINDING-002 | Bug | Critical | No trade execution or persistence | Open |
| FINDING-003 | Architecture | High | Platform/project coupling violation | Open |
| FINDING-004 | Bug | High | Self-improvement loop never runs | Open |
| FINDING-005 | Bug | High | Dashboard REST paths blocked | Open |
| FINDING-015 | Bug | High | State tensor routing dead | Fixed |
| FINDING-006 | Bug | Medium | Traces fail with type error | Open |
| FINDING-007 | DX | Medium | No observability without manual config | Open |
| FINDING-008 | Bug | Medium | Persistence writes unconfirmed | Open |
| FINDING-009 | Bug | Medium | Adversarial review is no-op | Open |
| FINDING-010 | Architecture | Medium | Goal system is dead code | Open |
| FINDING-011 | Architecture | Medium | Distributed tracing broken | Open |
| FINDING-012 | Architecture | Low | Memory never accumulates | Open |
| FINDING-013 | DX | Low | Dev startup is tedious | Open |
| FINDING-014 | DX | Low | CLI output is opaque | Open |

---

## Top 5 Fixes (Priority Order)

1. **FINDING-003** — Make `runCycle()` project-driven (removes Victoria coupling from platform)
2. **FINDING-002** — Wire paper trading persistence (first end-to-end execution)
3. **FINDING-004** — Wire `ImprovementEngine` to `VictoriaNode` in heartbeat
4. **FINDING-013** — Create `make dev` target (developer experience)
5. **FINDING-014** — Surface per-step results in CLI output (developer experience)
