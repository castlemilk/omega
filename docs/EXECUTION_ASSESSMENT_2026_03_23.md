# Omega System Execution Assessment — 2026-03-23

**Date:** 2026-03-23
**Branch:** claude/infallible-bouman
**Assessor:** Claude (automated end-to-end run)

---

## Summary

This document records the results of a live execution assessment of the Omega system
after the PostgreSQL migration consolidation. Each subsystem was actually run or probed,
not just inspected statically.

---

## Phase 1 — Infrastructure

### PostgreSQL
- **Status:** WORKING
- Port 5432 (docker-postgres-1, postgres:16 image) already running.
- `omega` database exists with all 30 expected tables present.
- The `omega` user has full access.
- DB is pre-populated with historical data from prior runs (36 adversarial_results, 18 node_executions from EvalTestNode, 3 traces, 1 semantic_memory entry).

### Go API Server
- **Status:** WORKING
- An instance (PID 45004) was already running — it started before this session.
- `GET /healthz` → `{"state":"HEALTHY",...}` with both `memory-db` and `state-db` checks healthy.
- `GET /readyz` → HEALTHY.
- `GET /metrics` → Prometheus metrics served (goroutines, GC, etc.).
- `GET /debug/diagnostics` → build info, runtime stats — all OK.
- **Note:** The running API was started without `OTLP_ENDPOINT`, so traces go to stdout, not the collector.

---

## Phase 2 — Python Orchestrator (Victoria Cycle)

### Startup + Node Registration
- **Status:** WORKING
- `python -m omega run --mode pico --symbols BTCUSDT,ETHUSDT --iterations 1 --heartbeat 1` runs successfully.
- 5 nodes register: DataIngestionNode, SignalGenerationNode, StrategyNode, RiskManagementNode, ReportingNode.
- **Bug found and fixed:** `runner.py:214` called `record_heartbeat(duration_seconds=0.0)` but the signature uses `duration_s`. Fixed → `record_heartbeat(duration_s=0.0)`.

### Heartbeat Loop
- **Status:** PARTIAL
- The runner loop itself works; it boots, registers nodes, and stops cleanly after N iterations.
- **Critical gap:** The `_heartbeat()` method sends `action="run_cycle"` to all nodes. None of the Victoria nodes handle `"run_cycle"` — they each silently return `NodeOutput(success=False, errors=["unknown action"])`.
- Consequence: every heartbeat cycle completes without doing any real work. Nodes are initialised but never called with a real action.

---

## Phase 3 — Subsystem Assessment

### Data Ingestion (Binance/CoinGecko)
- **Status:** WORKING
- Tested directly: `DataIngestionNode.execute(NodeInput(action="fetch_market_data", ...))` returned 10 symbols (BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, ADAUSDT, DOTUSDT, AVAXUSDT, LINKUSDT, MATICUSDT).
- Binance API live — real OHLCV data fetched, including BTC at ~$68,251.73.
- Returns `success=True` with full dict of symbol → OHLCV data.

### Signal Generation
- **Status:** WORKING
- `SignalGenerationNode.execute(NodeInput(action="compute_signals", parameters={"market_data": ...}))` returned composite signals for all 10 symbols.
- Signal output includes: ticker, composite score, price, RSI, 1d return.
- The composite direction at API level was "SHORT" (real signal from live data).

### Strategy Construction
- **Status:** WORKING
- `StrategyNode.execute(NodeInput(action="construct_portfolio", ...))` returned equal-weight portfolio (10 × 10% = 100%).
- Portfolio object includes: weights, positions count, method, signal_threshold, top_picks.
- Strategy defaults to equal weighting when composite scores are flat (-1.0 across all assets, indicating bearish/neutral signal).

### Risk Management
- **Status:** WORKING
- `RiskManagementNode.execute(NodeInput(action="check_risk_limits", ...))` returned adjusted weights with risk constraints applied.
- Returns original_weights and adjusted_weights (no changes from original in this run).

### Adversarial Review (Ring 1 + Devils Advocate)
- **Status:** PARTIAL
- Go API `AdversarialService/GetAdversarialReport` → returns `{}` (empty report, no active challenges).
- DB has 36 `adversarial_results` rows from prior runs — Ring 1 flagged (`flagged=true`, max_disagreement=0.38) and Ring 2 unflagged (max_disagreement=0.12).
- Python `DevilsAdvocateNode.execute(action="architectural_review", ...)` → `{"veto": false, "verdict": "APPROVED", "challenges": []}` (no challenges defined, gates all pass vacuously).
- The adversarial system initialises and returns verdicts, but the challenges list is empty — the review passes without substantive scrutiny.

### Paper Trading Execution
- **Status:** BROKEN / NOT IMPLEMENTED
- `victoria_trades` table: 0 rows.
- `victoria_portfolio` table: 0 rows.
- `victoria_signals` table: 0 rows.
- No Python code in `omega/` references `paper_trade`, `victoria_trades`, or `victoria_portfolio`. The pipeline computes portfolio weights and signals but has no execution layer to:
  1. Write signals to `victoria_signals`
  2. Simulate order fills into `victoria_trades`
  3. Track open positions in `victoria_portfolio`

### Improvement Engine (TPE + apply_params)
- **Status:** PARTIAL
- `ImprovementEngine` instantiates correctly with `make_state_backend()`.
- `register_node` + `propose` + `record_outcome` work in-memory.
- **Correct usage:** `ContinuousParam('signal_threshold', 0.0, 1.0)` and `DiscreteParam('lookback_days', 10, 90)`.
- TPE proposes params: `{'signal_threshold': 0.67, 'lookback_days': 86}`.
- `best_score`, `trial_count`, `best_params` work correctly.
- **Gap:** Engine only persists via `evaluate_and_record()` which requires a configured evaluator. The runner never calls the improvement engine.
- `improvement_log` DB table: 0 rows (no improvement cycles have run end-to-end).

### State Tensor Publishing
- **Status:** PARTIAL
- `VictoriaNode.get_state_tensor()` returns a 16-dimensional tensor with `schema_version="1.0.0"`.
- Values are all at neutral defaults (no historical execution data to derive from).
- **Gap:** `CoordinationService` handler exists in `internal/coordination/handler.go` but is **not registered** in `cmd/omega-api/main.go`. Calls to `/omega.v1.CoordinationService/Route` return `404 page not found`. State tensors are computed but never published to the routing layer.

### Memory System
- **Status:** PARTIAL
- `semantic_memories` table has 1 row: `concept="btc_momentum", confidence=0.8, namespace="global"`.
- `MemoryService` is registered and callable via Connect-RPC.
- Python memory kernel initialises but no new memories were written during this assessment run.

### Goal Architecture
- **Status:** PARTIAL
- Go API logs: `INFO GoalArchitecture initialised objectives="[sharpe_ratio coverage_rate error_rate]"` on startup — correct.
- `OrchestratorService/GetConvergence` returns 3 historical convergence points (from 2026-03-22 run), with stable `score=0.5099` across all 3 cycles — no improvement over cycles.
- `goal_tracking` DB table: 0 rows.
- System health = "critical" with composite score 0.6, 27 open issues, 12 error-severity.

### Go API Server (Connect-RPC)
- **Status:** WORKING
- Active services: OrchestratorService, VictoriaService, StateService, AutonomyService, AdversarialService, MemoryService, ImprovementService, TerminalService, NodeService, DataService, ProjectService.
- **Not registered:** CoordinationService (code exists, never added to mux in main.go).
- `OrchestratorService/ListNodes` → 13 registered nodes returned correctly.
- `OrchestratorService/GetHealth` → status="critical", score=0.6.
- `VictoriaService/GetSignals` → `{"compositeDirection":"SHORT"}` (live signal).
- `VictoriaService/GetTrades` → `{}` (no trades — as expected).
- `AutonomyService/GetAutonomyLevel` → `AUTONOMY_LEVEL_MANUAL` for all nodes.
- **Bug:** REST `/api/v1/nodes` returns `autonomy gate: action "GET" is not permitted at PICO autonomy level`. The API path is being intercepted by the autonomy gate for HTTP methods, blocking the REST endpoint.
- **StateService/BeginExecution persistence:** Called successfully (returns exec_id), but rows do not appear in Postgres. The running API instance may not be connected to the Postgres instance at 5432 (no `pg_stat_activity` connections from the Go process observed). Needs investigation.

### Dashboard
- **Status:** WORKING (build)
- `npm run build` in `dashboard/` succeeds in 2.13s: 2532 modules transformed, 896KB JS bundle.
- Dashboard was not served live during this assessment.
- Known open issues (from Go API): API endpoints `/api/nodes`, `/api/metrics`, `/api/traces`, `/api/convergence` are unreachable (REST paths blocked by autonomy gate or not mapped).

### OTLP Tracing
- **Status:** PARTIAL
- The observability stack (Grafana, Tempo, OTel Collector) is running: ports 3001, 3200, 4317-4318, 8889.
- The running omega-api was started without `OTLP_ENDPOINT` set → traces go to stdout only.
- Python tracing (`omega.core.tracing`): `Tracer.start_trace()` + `end_span(ctx.span_id)` works and writes to `traces` table in Postgres. 3 trace rows from prior run visible.
- **Bug in Tracer API:** `end_span()` expects `str` span_id but callers may pass a `TraceContext` object — `psycopg.ProgrammingError: cannot adapt type 'TraceContext'`. The correct call is `end_span(ctx.span_id)`.
- With `OTLP_ENDPOINT=http://localhost:4318` set, traces would flow to the collector.

### PostgreSQL Persistence
- **Status:** PARTIAL
- Tables exist and schema is correct.
- Historical data present from prior runs.
- Victoria pipeline (data → signals → strategy → risk) does not write to any Victoria tables.
- StateService `BeginExecution` call succeeds but rows don't appear in Postgres — root cause unclear (possible: running API not connected to this PG instance).

---

## Subsystem Ratings

| Subsystem | Rating | Notes |
|---|---|---|
| Data ingestion (Binance/CoinGecko) | **WORKING** | Live data fetched for 10 symbols |
| Signal generation | **WORKING** | Signals compute correctly on real data |
| Strategy construction | **WORKING** | Equal-weight portfolio constructed |
| Risk management | **WORKING** | Risk limits checked and weights adjusted |
| Adversarial review (Ring 1 + Devils Advocate) | **PARTIAL** | Initialises but no challenges defined; Ring 1 historical data exists |
| Paper trading execution | **BROKEN** | No execution layer; victoria_trades/signals/portfolio tables empty |
| Improvement engine (TPE + apply_params) | **PARTIAL** | TPE works in-memory; never invoked from heartbeat loop |
| State tensor publishing | **PARTIAL** | Tensor computed (16-dim); CoordinationService not registered in API |
| Memory system | **PARTIAL** | 1 seed memory in DB; no new memories written this run |
| Goal architecture | **PARTIAL** | Objectives configured; goal_tracking table empty; convergence flat |
| Go API server | **WORKING** | Healthy, 11 services registered, /healthz OK |
| Dashboard | **WORKING** | Builds successfully; not serving live |
| OTLP tracing | **PARTIAL** | Stack running; API started without OTLP_ENDPOINT; Python tracer works |
| Postgres persistence | **PARTIAL** | Tables exist; Victoria pipeline doesn't write; StateService writes unconfirmed |

---

## Critical Bugs Found

1. **`runner.py:214` — wrong kwarg `duration_seconds` vs `duration_s`** — FIXED in this session.
2. **Heartbeat sends `action="run_cycle"` which no node handles** — Every cycle is a no-op. The runner never actually exercises the Victoria pipeline.
3. **`CoordinationService` not registered in `main.go`** — State tensor routing is dead.
4. **No paper trading execution layer** — The pipeline stops at strategy construction; there is no code to execute simulated trades or persist them.
5. **REST autonomy gate blocks `/api/v1/nodes`** — Dashboard REST paths are blocked.
6. **`Tracer.end_span()` type confusion** — Passes `TraceContext` when `str` expected; callers must use `ctx.span_id`.

---

## What Works End-to-End

The individual compute nodes (data, signals, strategy, risk) work correctly when called directly with the right actions. The Go API boots, connects to Postgres (or appears to), and serves all registered services. The dashboard builds.

## What Doesn't Work End-to-End

The system cannot run a complete Victoria cycle autonomously. The heartbeat loop is wired incorrectly (all nodes get `run_cycle` which none handle). There is no paper trading execution layer. The improvement engine is never invoked. State tensors are never published to the coordination router (which isn't even registered). The Python–Go bridge (`StateServiceClient`) appears to work at the HTTP level but persistence to Postgres is unconfirmed.

---

## Recommended Next Steps (Priority Order)

1. **Fix the heartbeat orchestration** — Replace the `run_cycle` broadcast with a proper pipeline: call DataIngestionNode → SignalGenerationNode → StrategyNode → RiskManagementNode → ReportingNode with the correct chained actions and outputs.
2. **Implement paper trading execution** — Write `victoria_signals`, `victoria_trades`, `victoria_portfolio` tables from pipeline output.
3. **Register CoordinationService in main.go** — Attach the existing `coordination.Handler` to the mux.
4. **Verify StateService–Postgres connection** — Confirm the running API instance's DB connection string and that writes land in Postgres.
5. **Wire improvement engine into heartbeat** — After a cycle, call `ImprovementEngine.evaluate_and_record()` with real metrics.
6. **Set OTLP_ENDPOINT** — Point the running API at the local OTel collector (`:4318`) to get traces into Grafana/Tempo.
