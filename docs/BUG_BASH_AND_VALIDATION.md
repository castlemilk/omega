# Omega — Bug Bash & System Validation

**Last updated:** 2026-03-25
**Purpose:** Living document. Captures every tracked bug, provides a runnable validation checklist, and defines regression baselines. Run the checklist after every major merge.

---

## Table of Contents

1. [Known Bugs (Tracked)](#1-known-bugs-tracked)
2. [Validation Checklist](#2-validation-checklist)
3. [Regression Test Commands](#3-regression-test-commands)
4. [Performance Baselines](#4-performance-baselines)
5. [Known Limitations (Not Bugs)](#5-known-limitations-not-bugs)

---

## 1. Known Bugs (Tracked)

| ID | Severity | Subsystem | Description | Status | Found | Fixed | Root Cause | Verification |
|---|---|---|---|---|---|---|---|---|
| BUG-001 | High | Orchestrator | `runner.py:214` called `record_heartbeat(duration_seconds=0.0)` but the function signature uses `duration_s` — causes `TypeError` on every heartbeat | Fixed | 2026-03-23 | 2026-03-23 | Wrong kwarg name passed; signature mismatch not caught at test time | Run `python -m omega run --mode pico --symbols BTCUSDT --iterations 1 --heartbeat 1` — no `TypeError` in output |
| BUG-002 | Critical | Orchestrator | `_heartbeat()` broadcasts `action="run_cycle"` to all nodes. None of the Victoria nodes handle this action — every node returns `NodeOutput(success=False, errors=["unknown action"])`. The entire heartbeat loop is a no-op. | In Progress | 2026-03-23 | — | `_heartbeat()` not updated to call the correct pipeline actions (`fetch_market_data` → `compute_signals` → `construct_portfolio` → `check_risk_limits`) in sequence | Run one iteration; inspect cycle result — at least one node must return `success=True` with non-empty output |
| BUG-003 | High | Coordination | `CoordinationService` handler exists in `internal/coordination/handler.go` but is never registered in `cmd/omega-api/main.go`. All calls to `/omega.v1.CoordinationService/Route` return `404` | In Progress | 2026-03-23 | — | Handler implemented but not wired into the Connect-RPC mux | `curl http://localhost:8080/omega.v1.CoordinationService/Route` must not return 404 |
| BUG-004 | Critical | Execution | Paper trading not wired into runtime. `victoria_trades`, `victoria_portfolio`, and `victoria_signals` tables all have 0 rows. Pipeline produces signals and weights but no code writes them to the DB or simulates fills. | In Progress | 2026-03-23 | — | Execution step (`_step_execute()`) is a stub — it counts and logs proposals but takes no action | After running one cycle, `victoria_signals` must have ≥1 row; `victoria_portfolio` must reflect current weights |
| BUG-005 | High | API / Autonomy | REST endpoint `/api/v1/nodes` returns `autonomy gate: action "GET" is not permitted at PICO autonomy level`. The autonomy gate incorrectly matches HTTP verb "GET" against action names — blocking the dashboard and all REST consumers. | Open | 2026-03-23 | — | Autonomy gate checks action string against `"GET"` literally; REST GET requests not excluded from gate evaluation | `curl http://localhost:8080/api/v1/nodes` must return node list JSON, not an autonomy gate error |
| BUG-006 | Medium | Observability | `Tracer.end_span()` expects a `str` span_id but callers may pass a `TraceContext` object directly, producing `psycopg.ProgrammingError: cannot adapt type 'TraceContext'` | Open | 2026-03-23 | — | API accepts `str` but callers assumed they could pass the full context object; missing runtime type validation | Call `end_span(ctx)` with a `TraceContext` object — must not raise; call `end_span(ctx.span_id)` — must succeed |
| BUG-007 | High | Coordination | `PostgresTensorPublisher.Subscribe()` opens a LISTEN connection but enters a busy-poll loop (sleep 50ms, check `pg_notification_queue_usage()`) — never calls `WaitForNotification()`. The returned channel never receives a tensor. Real-time state propagation is silently dead. | Fixed | 2026-03-23 | 2026-03-23 | Comment in code acknowledged the bug: *"production use should use WaitForNotification"* but fix was not applied | Publish a tensor; subscriber channel must receive it within 200ms |
| BUG-008 | Critical | Self-Improvement | `ImprovementEngine.evaluate_and_record()` stores `best_params` per node but never calls `node.apply_params(best_params)`. Approved improvements sit in a dict and are never applied to the running node. | Fixed | 2026-03-21 | 2026-03-23 | `apply_params()` method on `Node` existed but was not wired; improvement engine missing the call-through step | After a TPE trial is accepted, node's `get_params()` must return the new values; node version must increment |
| BUG-009 | High | Adversarial | Ring 1 adversarial cannot fire in single-node topology. `AdversarialPressureV2` triggers on ensemble disagreement (`variant_outputs` ≥ 2 differing results) — with only one Victoria node, there is only one variant and disagreement is always 0. | Fixed | 2026-03-23 | 2026-03-23 | Ring 1 was designed for multi-node ensemble; perturbation variants added so single-node can self-disagree | Run 10 cycles — at least 1 cycle must show `ring1_flagged=True` in `adversarial_results` |
| BUG-010 | High | Data Pipeline | Silent fallback to synthetic (LCG) data when `DataIngestionNode` is unavailable, with no warning. All Sharpe numbers produced in dev/CI are LCG artifacts, not market signal. | Partially Fixed | 2026-03-21 | 2026-03-23 | `_load_data()` and `_load_prices()` silently swallow all ingestion errors and substitute LCG data | `EvalReport` must include `is_synthetic: true` flag when fallback used; a `WARNING` log must appear at ingestion failure time |
| BUG-011 | High | Eval Framework | Look-ahead bias: `backtest.py:_sma_crossover_strategy()` enters a long at `bars[i].close` when the crossover triggers at bar `i` and computes bar `i` return immediately. Signal-bar return is captured before the trade can be placed. | Fixed | 2026-03-21 | 2026-03-23 | Entry priced at same-bar close rather than next-bar open; `backtest_bridge.py` was correct but the standalone engine was not | Backtest with a delayed-by-1 random signal must produce ~0 Sharpe; old code produced positive Sharpe from look-ahead |
| BUG-012 | Medium | Eval Framework | Equity curve in `backtest.py:_compute_metrics()` computed as additive sum (`cumulative = sum(daily_returns)`). Drawdown calculated on additive P&L understates losses after winning periods. | Fixed | 2026-03-21 | 2026-03-23 | Used simple sum instead of cumulative product; `metrics.py:build_equity_curve()` had the correct formula but was not used | `_compute_metrics()` must use `np.cumprod(1 + daily_returns)` for drawdown calculation |
| BUG-013 | Medium | Eval Framework | `compute_annualised_return()` used arithmetic mean (`sum(r)/len(r) * periods_per_year`) instead of CAGR. Arithmetic mean overstates compound growth when variance is nonzero. | Fixed | 2026-03-21 | 2026-03-23 | Textbook error — arithmetic vs geometric mean; inflates headline return numbers shown in `EvalReport` | `compute_annualised_return()` on a 50% up / 50% down sequence must return near zero, not positive |
| BUG-014 | Medium | Self-Improvement | TPE in `tpe_eval.py` runs Welch t-test per trial with no correction for multiple comparisons. 100 trials at p < 0.05 expects ~5 false discoveries. | Fixed | 2026-03-21 | 2026-03-23 | Single t-test applied per configuration without Bonferroni/Holm/BH adjustment; each trial treated as independent | `_statistical_test()` must apply Bonferroni correction: `alpha_corrected = alpha / n_trials`; accepted trial rate on random search must drop |
| BUG-015 | High | Security | `docker-compose.yml` hardcodes `POSTGRES_PASSWORD: omega`. Port 5432 exposed on `0.0.0.0`. Any process on the Docker network can read/write all Omega state. | Open | 2026-03-23 | — | Default development credentials committed to version control without rotation mechanism | DB credentials must be in `.env` (gitignored); `docker-compose.yml` must reference env vars, not literals |
| BUG-016 | High | Security | Connect-RPC handlers in `internal/handler/` implement no auth middleware. `StartOrchestrator`, `StopOrchestrator`, and `RunImprovement` are callable by any HTTP client. | Fixed | 2026-03-23 | 2026-03-23 | No auth interceptor registered on the Connect mux; development oversight | Unauthenticated `curl` to `StartOrchestrator` must return 401; authenticated call with valid API key must succeed |
| BUG-017 | High | Self-Improvement | `ConsolidationPipeline.consolidate()` moves records from short-term to long-term memory. Consolidated memories are never read back by strategy or signal generation layers. `VictoriaNode` has no interface to retrieve consolidated patterns. | Fixed | 2026-03-21 | 2026-03-23 | Memory module developed in isolation from signal layer; no `get_memories()` call added to `SignalGenerationNode` or `StrategyNode` | After 30 cycles, `StrategyNode` must show memory-derived weight adjustments visible in cycle output |
| BUG-018 | Critical | Architecture | `victoriaSteps()` hardcoded in `internal/handler/orchestrator.go` — Victoria pipeline steps embedded in platform code, violating platform/project separation. Omega should not know about Victoria's step names. | Fixed | 2026-03-24 | 2026-03-24 | `runCycle()` lacked a project registry; steps were defined inline as a convenience. Fixed by wiring `ProjectHandler` to `OrchestratorHandler` and reading steps from `project.PipelineConfig`. | `orchestrator.go` must contain no Victoria-specific step names; adding a new project must require zero changes to platform code |
| BUG-019 | Critical | Execution | Paper trading execution layer absent. `victoria_trades`, `victoria_portfolio`, and `victoria_signals` tables remain at 0 rows after any number of cycles. The pipeline computes weights but does not execute. | Fixed | 2026-03-24 | 2026-03-24 | No `PaperTradingEngine` existed in `omega/nodes/victoria/`; pipeline had no post-risk step to simulate fills. Added `paper_trading.py` to Victoria nodes and wired it into the pipeline server dispatch. | After one cycle, `victoria_signals` ≥ 1 row; `victoria_trades` ≥ 1 row; `victoria_portfolio` reflects current weights |
| BUG-020 | High | Self-Improvement | `ImprovementEngine.evaluate_and_record()` is called successfully in isolation tests but the runner never invokes it. `improvement_log` DB table: 0 rows after any number of cycles. Node params are never updated at runtime. | Fixed | 2026-03-24 | 2026-03-24 | `VictoriaNode` was not registered with `ImprovementEngine` at startup; no post-cycle hook existed to call the engine with real metrics. Added startup wiring and post-cycle `evaluate_and_record()` call. | `improvement_log` gains ≥ 1 row after 5 cycles; `apply_params()` called when TPE finds better params |
| BUG-021 | High | DX | No `make dev` target exists. Starting the dev environment requires 3 manual steps in the correct order (`docker compose up -d postgres`, Python pipeline server background, Go API foreground). Developers frequently start services in the wrong order or forget the pipeline server. | Fixed | 2026-03-24 | 2026-03-24 | Makefile grew organically; no integrated dev target was defined. Added `make dev` and `make dev-down` targets. | `make dev` brings up all required services; `make dev-down` tears them all down |
| BUG-022 | High | DX | `omega run` shows only a one-line health summary per cycle. Per-step success/failure and latency are invisible. Developers cannot tell which step is failing or slow without reading OTel spans in Grafana. | Fixed | 2026-03-24 | 2026-03-24 | CLI was designed for monitoring mode (background orchestrator + poll); no cycle-execution mode existed. Added `--cycles N` flag with per-step output format. | `omega run --cycles 1` shows `step_name: success (123ms)` or `step_name: FAILED (error)` for each pipeline step |
| BUG-023 | Medium | Architecture | `runCycle()` in the Go orchestrator was the only caller of `victoriaSteps()` — a private function with no test coverage. Changes to Victoria's pipeline could silently break orchestration without any compile-time or runtime error. | Fixed | 2026-03-24 | 2026-03-24 | Steps were maintained in two places: `victoriaProject()` (correct, project-driven) and `victoriaSteps()` (wrong, platform-coupled). By making `runCycle()` read from `ProjectHandler`, the single source of truth is the project registration. | `victoriaSteps()` removed; Go build must succeed; no Victoria step names remain in `orchestrator.go` |

---

## 2. Validation Checklist

Run this checklist after every major merge. Each section can be run independently.

### 2.1 Infrastructure

- [ ] Docker Compose starts cleanly: `docker compose up -d`
- [ ] PostgreSQL accessible: `psql -h localhost -U omega -d omega -c '\dt'` returns ≥ 30 tables
- [ ] Go API starts and `/healthz` returns `"state":"HEALTHY"` with both `memory-db` and `state-db` checks passing
- [ ] Go API `/readyz` returns healthy
- [ ] Go API `/metrics` returns Prometheus text format (goroutines, GC, etc.)
- [ ] Dashboard builds without error: `cd dashboard && npm run build` (or `web/dashboard`)
- [ ] OTLP collector is receiving traces: check `http://localhost:8889/metrics` for `otelcol_exporter_sent_spans > 0` (requires `OTLP_ENDPOINT` set)
- [ ] No `ERROR` or `PANIC` lines in `docker compose logs` at startup

### 2.2 Data Pipeline

- [ ] `DataIngestionNode.execute(action="fetch_market_data")` returns `success=True` with OHLCV data for configured symbols
- [ ] Response includes real prices (BTC > $1000) — not the LCG fallback values
- [ ] If Binance is unreachable, a `WARNING` log appears and `is_synthetic: true` is set on output — **no silent fallback**
- [ ] Data freshness guard: mock a 2-hour-old timestamp — system logs `WARNING: data stale (2h)`
- [ ] Data freshness guard: mock a 7-hour-old timestamp — system logs `ERROR: data degraded (7h)` and degrades signal confidence
- [ ] `SignalGenerationNode.execute(action="compute_signals", parameters={"market_data": ...})` returns composite signals
- [ ] Signal output includes: `ticker`, `composite_score`, `rsi`, `sma_fast`, `sma_slow`, `macd`, `bollinger_upper`, `bollinger_lower`
- [ ] `StrategyNode.execute(action="construct_portfolio", ...)` returns portfolio with weights summing to ~1.0
- [ ] `RiskManagementNode.execute(action="check_risk_limits", ...)` returns `adjusted_weights` without crashing

### 2.3 Heartbeat Loop (End-to-End Cycle)

- [ ] `python -m omega run --mode pico --symbols BTCUSDT,ETHUSDT --iterations 1 --heartbeat 1` exits 0
- [ ] At least one node returns `success=True` in the cycle result (BUG-002 regression check)
- [ ] Cycle output includes results from DataIngestionNode → SignalGenerationNode → StrategyNode → RiskManagementNode in correct order
- [ ] No `unknown action` errors in cycle output
- [ ] `record_heartbeat()` is called with `duration_s=` (not `duration_seconds=`) — BUG-001 regression check

### 2.4 Paper Trading Execution

- [ ] After one full cycle, `victoria_signals` table has ≥ 1 row
- [ ] After one full cycle, `victoria_portfolio` table reflects current weights
- [ ] After one full cycle, `victoria_trades` table has ≥ 1 row (simulated fill)
- [ ] Cycle metrics include `pt_portfolio_value`, `pt_total_pnl`, `pt_win_rate`
- [ ] Paper trades are persisted with `symbol`, `side`, `quantity`, `fill_price`, `timestamp`

### 2.5 Self-Improvement

- [ ] `ImprovementEngine` instantiates with `make_state_backend()`
- [ ] `register_node` + `propose` + `record_outcome` work without error
- [ ] When a TPE trial is accepted (`trial.accepted = True`), `node.apply_params(best_params)` is called — BUG-008 regression check
- [ ] After `apply_params()` is called, `node.get_params()` returns the new values
- [ ] Node version increments after params are applied
- [ ] `improvement_log` DB table gains ≥ 1 row after running the improvement engine end-to-end
- [ ] Rolling 30-cycle Sharpe trend is computed and accessible in `CycleResult` or `ImprovementEngine.get_trend()`

### 2.6 Coordination Layer

- [ ] `VictoriaNode.get_state_tensor()` returns a 16-dimensional tensor with `schema_version="1.0.0"`
- [ ] State tensor values are non-default after a real cycle (not all zeros)
- [ ] `CoordinationService` is registered in `main.go` — BUG-003 regression check
- [ ] `curl http://localhost:8080/omega.v1.CoordinationService/Route` does NOT return `404`
- [ ] `CoordinationService/Route` returns a routing plan with `selected_nodes` and `confidence_scores`
- [ ] `coordination_outcomes` table receives a row after a routing call
- [ ] Attention router weights are not all identical (Xavier init confirmed)

### 2.7 Adversarial Layer

- [ ] `DevilsAdvocateNode.execute(action="architectural_review")` returns a `verdict` field
- [ ] Over 10 cycles, at least 1 cycle shows `ring1_flagged=True` in `adversarial_results` — BUG-009 regression check
- [ ] `adversarial_results` table records new rows each run
- [ ] Veto decisions (`veto=True`) appear in cycle output when adversarial threshold is crossed
- [ ] Adversarial flags appear in `CycleResult.adversarial_flags` list

### 2.8 Observability

- [ ] `GET /metrics` returns Prometheus metrics including at least `go_goroutines`, `process_cpu_seconds_total`
- [ ] With `OTLP_ENDPOINT=http://localhost:4318` set, traces appear in Tempo (check Grafana → Explore → Tempo)
- [ ] Grafana dashboards render without `No data` on the `omega-api` datasource
- [ ] `postgres_exporter` metrics appear at port 9187 (if configured in compose)
- [ ] Python tracer calls `end_span(ctx.span_id)` (not `end_span(ctx)`) — BUG-006 regression check
- [ ] `traces` table in Postgres gains rows during a cycle run
- [ ] W3C `traceparent` headers used for Python → Go trace propagation (no orphaned span trees)

### 2.9 Security

- [ ] `docker-compose.yml` contains no literal password values — uses env var references
- [ ] Unauthenticated call to `StartOrchestrator` returns `401` — BUG-016 regression check
- [ ] Authenticated call with valid API key to `StartOrchestrator` succeeds
- [ ] `.env` file is listed in `.gitignore`
- [ ] `git log --all --full-history -- '*.env'` shows no committed secrets

### 2.10 API & REST Layer

- [ ] `GET /api/v1/nodes` returns node list JSON — BUG-005 regression check (must NOT be blocked by autonomy gate)
- [ ] `GET /api/v1/metrics` returns metrics JSON
- [ ] `GET /api/v1/convergence` returns convergence history
- [ ] `GET /api/v1/traces` returns trace list
- [ ] `OrchestratorService/ListNodes` → returns ≥ 5 registered nodes
- [ ] `VictoriaService/GetSignals` → returns `compositeDirection` field
- [ ] `AutonomyService/GetAutonomyLevel` → returns a valid `AUTONOMY_LEVEL_*` value

### 2.11 Eval Framework

- [ ] Backtests use CAGR: `compute_annualised_return()` on a 50%↑/50%↓ sequence returns ~0 — BUG-013 regression check
- [ ] No look-ahead bias: a 1-bar-lagged random signal produces ~0 Sharpe — BUG-011 regression check
- [ ] Equity curve is multiplicative: `backtest.py:_compute_metrics()` uses `np.cumprod(1 + returns)` — BUG-012 regression check
- [ ] Every `EvalReport` includes `sharpe_ci_lower` and `sharpe_ci_upper` bootstrap confidence intervals
- [ ] `_statistical_test()` in `tpe_eval.py` applies Bonferroni correction — BUG-014 regression check
- [ ] `EvalReport.is_synthetic` is `True` when fallback data was used — BUG-010 regression check
- [ ] `EvalReport.is_synthetic` is `False` when real Binance data was used

---

## 3. Regression Test Commands

Run these commands in order for a full regression. All must pass before merging to `main`.

```bash
# ── Go ──────────────────────────────────────────────────────────────────────
# Build all packages (catches compile errors across the full Go module)
go build ./...

# Run all Go unit tests
go test ./...

# Run Go tests with race detector (catches data races in concurrent code)
go test -race ./...


# ── Python ──────────────────────────────────────────────────────────────────
# Run full Python test suite
python -m pytest tests/ --timeout=120

# Run with verbose output to see individual test names
python -m pytest tests/ -v --timeout=120

# Run only unit tests (fast, no network)
python -m pytest tests/unit/ --timeout=30

# Run only integration tests (requires Postgres + Go API running)
DATABASE_URL=postgresql://omega:omega@localhost:5432/omega \
  python -m pytest tests/integration/ -k "integration" --timeout=120

# Run eval framework tests specifically
python -m pytest tests/ -k "eval or backtest or sharpe" --timeout=120


# ── Frontend ────────────────────────────────────────────────────────────────
# Primary dashboard location
cd dashboard && npm run build

# Alternate location if above fails
cd web/dashboard && npm run build


# ── Protos ──────────────────────────────────────────────────────────────────
# Regenerate protos after any .proto change
cd proto && buf generate


# ── E2E Smoke Test (requires Postgres + Go API running) ─────────────────────
# Single pico cycle — validates data → signals → strategy → risk pipeline
python -m omega run \
  --mode pico \
  --symbols BTCUSDT,ETHUSDT \
  --iterations 1 \
  --heartbeat 1

# 5-cycle run — validates heartbeat continuity and improvement engine invocation
python -m omega run \
  --mode pico \
  --symbols BTCUSDT,ETHUSDT \
  --iterations 5 \
  --heartbeat 5


# ── Infrastructure Health ────────────────────────────────────────────────────
# Confirm Go API is healthy
curl -s http://localhost:8080/healthz | jq '.state'
# Expected: "HEALTHY"

# Confirm all DB tables exist
psql -h localhost -U omega -d omega -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
# Expected: >= 30

# Confirm CoordinationService is registered (BUG-003 regression)
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8080/omega.v1.CoordinationService/Route \
  -H "Content-Type: application/json" -d '{}'
# Expected: 400 or 401 (not 404)

# Confirm REST node list is accessible (BUG-005 regression)
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/api/v1/nodes
# Expected: 200 (not 403)
```

---

## 4. Performance Baselines

Document current performance to catch regressions. Update this section when a baseline changes intentionally.

| Metric | Baseline | Measured | Threshold |
|---|---|---|---|
| Python test suite (full) | ~1800 tests, ~3 min | TBD | Fail if > 5 min |
| Python test suite (unit only) | ~1200 tests, ~60s | TBD | Fail if > 90s |
| Go test suite | ~20 packages, ~10s | TBD | Fail if > 30s |
| Frontend build (`dashboard/`) | ~2.1s, ~896KB bundle | 2.13s / 896KB (2026-03-23) | Fail if > 10s or > 1.5MB |
| Go API startup to `/healthz` ready | < 2s | TBD | Fail if > 5s |
| Single Victoria cycle latency | TBD | TBD (measure after BUG-002 fix) | TBD |
| Data ingestion (10 symbols, Binance) | < 3s | TBD | Fail if > 10s |
| Signal generation (10 symbols) | < 1s | TBD | Fail if > 3s |
| Full pipeline (data → risk) | < 5s | TBD | Fail if > 15s |

> **Note:** Cycle latency baseline is TBD — measure after BUG-002 (heartbeat no-op) is fixed and a real end-to-end cycle completes.

---

## 5. Known Limitations (Not Bugs)

These are architectural gaps and unimplemented features. They are tracked here to prevent confusion during validation — a "failing" check in this list is expected behaviour, not a regression.

### Platform Completeness

- **Only Victoria domain node exists.** Telesis, Flaggr, and Cuttlefish nodes are architectural stubs only. Cross-node composition cannot be demonstrated until at least two domain nodes are live.
- **No real execution engine.** Paper trading is the highest fidelity available. There is no broker adapter, no OMS, and no live order placement. `actions_executed` counts proposals that passed the adversarial gate — not real fills.
- **Attention router weights are Xavier-random.** The `OutcomeStore` accumulates routing outcomes but no training pipeline reads them. The router will not improve until `RoutingWeightAdapter` is implemented (backlog: Q3 2026). `TrainingEligible: true` appears in stats after 1000 outcomes, but nothing acts on it.
- **OTLP only works when explicitly configured.** If `OTLP_ENDPOINT` is not set, all Python and Go telemetry is silently dropped (or written to stdout). The OTel collector stack (`deploy/docker-compose.otel.yaml`) must be started separately from the main compose stack.
- **No horizontal scaling.** The Python orchestrator is single-threaded. Node execution is sequential within a cycle. No NATS bus, no worker pool, no k8s deployment. Planned for Q3 2026.
- **Goal system is disconnected.** `GoalArchitecture` in `goals.py` is never called from the orchestrator. The HTN decomposition and balanced scorecard exist as dead code relative to the runtime until EPIC-004 is implemented.

### Eval Framework

- **OOS window is contaminated by TPE.** All TPE trials in `BacktestEvaluator` score against the same fixed calendar window. A true held-out test set (third split) does not exist. Sharpe numbers from TPE optimisation are upper-bounded estimates.
- **Ablation harness uses synthetic Gaussian noise.** `AblationHarness` with default config uses `_AblationNode`, not `VictoriaNode`. Ablation results measure RNG behaviour, not real signal attribution.
- **Normal approximation used for small samples.** `sharpe_difference_significant()` warns at n < 30. Backtests on 60–100 bars produce materially incorrect p-values.
- **No survivorship bias handling.** Asset universe (BTC, ETH, SOL) excludes failed assets (LUNA, FTT). Cross-asset signals trained on this universe are survivorship-biased.
- **No Monte Carlo simulation.** Single realised equity curve reported. No bootstrap path distribution, no uncertainty envelope around the equity curve.
- **No CVaR / Expected Shortfall.** Tail risk is not measured. Sortino ratio is computed but CVaR at 5th percentile is not.
- **No historical crash stress tests.** All stress testing uses synthetic Gaussian data. March 2020, May 2021, June/November 2022 events are not in the test suite.

### Security (Accepted for Dev, Must Fix Before Any Shared Environment)

- **No sandbox for node execution.** PICO mode does not enforce process isolation. Nodes can make network requests and write files freely.
- **No mTLS between Go and Python services.** Internal service communication is plaintext HTTP.
- **No secret rotation.** Credentials in `.env` have no TTL or rotation mechanism.
- **No immutable audit log.** Adversarial flags, autonomy transitions, and improvement decisions exist only in application logs — not in an append-only database table.

### Observability

- **Dashboard metrics may be cosmetic.** Until BUG-002 (heartbeat no-op) and BUG-004 (paper trading) are fixed, health scores reflect cycle completion without real work, not actual strategy performance.
- **Python trace IDs are not W3C-compliant.** Python and Go spans cannot be joined in a distributed trace viewer. Traces from a single Victoria cycle appear as two disconnected trees.
- **No alerting integration.** `EPIC-001` specifies Slack/PagerDuty alerts at error rate > 5%. Circuit breaker registry exists but no notification path is wired.
