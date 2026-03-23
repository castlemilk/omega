# Omega Strategic Backlog: Neural Distributed System Architecture
## March 2026 → March 2027

---

## 1. Vision Statement

### Where Omega Is Today

Omega is a platform with a working proof of concept. Victoria — the first project node — runs a 9-step Python pipeline producing real signals, a React dashboard serves real data through Connect-RPC, and OTel tracing now instruments the full cycle. The multi-project architecture exists in code. The graduated autonomy model (PICO → Supervised → Autonomous) is designed but mostly manual. The vision is articulated but not yet structural.

What we have is a sophisticated research system that happens to be architected like a platform. What we need is a platform that happens to be doing research.

### Where Omega Needs to Be in 12 Months

In March 2027, Omega operates as a **neural distributed system**: a meta-architecture where individual software capabilities are nodes that compose through coordination layers to produce goal-directed intelligence. The analogy to neural networks is precise, not metaphorical:

- **Nodes** are like neurons — discrete computational units with defined input/output interfaces
- **Coordination Layer** is like the connectivity matrix — routes signals between nodes based on relevance and attention
- **State Tensors** are like activation values — structured representations of each node's current state exposed to the coordination layer
- **Self-Improvement Loop** is like backpropagation — error signals from outcomes flow back through the system, updating node weights and configurations
- **Trust Boundaries** are like inhibitory neurons — dampening nodes that are misbehaving, routing around failures

This is not theoretical. In 12 months:

1. **Victoria runs autonomously** — the quant research loop runs without human intervention: hypothesis → experiment → evaluation → improvement → next hypothesis. LLM analysts propose new vectors, the system validates them, promotes them to production, and the improvement engine learns from outcomes.

2. **Multiple projects are live nodes** — Telesis (observability), Shorted/Victoria (market intelligence), Flaggr (feature management), and Cuttlefish (deployment) all expose the Node Protocol. Cross-node composition produces capabilities none of them have alone (e.g., Telesis detects anomalies in Victoria's signal quality, automatically triggering Cuttlefish to roll back a bad model deployment).

3. **The coordination layer routes intelligence** — a central coordinator runs an attention-like mechanism over node state tensors, deciding which nodes to activate for a given goal, how to compose their outputs, and how to route feedback from outcomes back to relevant nodes.

4. **Full observability is production-grade** — OTLP backend running, Grafana dashboards with SLOs, alerting on safety violations, metric regression detection, and a live/backtest reconciliation layer that surfaces when the model is drifting from its historical performance.

5. **Trust and safety are structural** — every autonomous action passes through a trust layer with escalation paths. PICO mode is enforced cryptographically (sandbox boundary), Supervised mode requires human-in-the-loop for irreversible actions, Autonomous mode requires sustained performance above defined thresholds.

The prior art for this vision: Minsky's Society of Mind (nodes with specialized competencies composing into general intelligence), Wiener's Cybernetics (feedback loops as the fundamental mechanism), and the autopoietic systems literature (systems that maintain and reproduce their own organization). Omega is an engineering implementation of these ideas on top of real software infrastructure.

The 12-month goal: **Omega is a self-improving, multi-domain intelligence platform where each capability is a composable node, the coordination layer learns which nodes to trust and when, and the system converges on high-level goals through iterative cycles without per-task human intervention.**

---

## 2. Architecture Evolution Roadmap

### Q2 2026 (Months 1–3): Foundation

**Theme: Make the existing system trustworthy and instrumented.**

Current state is a working prototype with significant observability gaps (P0–P2 issues identified). Before scaling intelligence, we need reliable infrastructure. This quarter closes the observation gap, standardizes the node protocol, and builds the Go/Python bridge that everything else depends on.

**Core deliverables:**
- OTLP backend deployed (Grafana Cloud or self-hosted), zero silent metric drops
- W3C-compliant trace IDs propagated Python → Go
- Node Protocol v1: standardized interface all nodes must implement
- Go/Python bridge: bidirectional Connect-RPC, Python nodes callable from Go
- Full observability of one complete Victoria cycle end-to-end
- Safety violations persisted and queryable

### Q3 2026 (Months 4–6): Scale

**Theme: Build the message bus, node registry, and real distributed execution.**

With reliable instrumentation, scale the architecture. NATS or equivalent message bus replaces synchronous calls where appropriate. Nodes register capabilities. State tensors are defined. The coordination layer prototype exists.

**Core deliverables:**
- NATS message bus deployed, core node communication async
- Node Capability Registry: discovery, health, capability advertisement
- State Tensor Protocol v1: nodes expose structured state snapshots
- Coordination Layer v1: routing table, no learning yet
- Shorted/Victoria promoted to full Node Protocol implementation
- Distributed execution prototype (k8s or Docker Compose cluster)
- Multi-project isolation: resource quotas, namespace separation

### Q4 2026 (Months 7–9): Intelligence

**Theme: Close the self-improvement loop and begin cross-node composition.**

The system becomes genuinely self-improving. LLM analysts are integrated. The geometric math library is production-quality. Victoria's quant pipeline runs with less human intervention each week.

**Core deliverables:**
- LLM-as-analyst integrated: Claude/GPT reviews experiments, proposes vectors
- Self-improvement loop fully automated (no human needed per experiment)
- Cross-node composition: Telesis + Victoria producing anomaly-detected signals
- Geometric math library: manifold learning, TDA, spectral methods stable
- Coordination Layer v2: learning-based routing, attention mechanism
- Multi-market data layer: unified adapter for ASX, crypto, forex
- Trust scoring: nodes earn and lose trust based on outcome history

### Q1 2027 (Months 10–12): Autonomy

**Theme: Full neural distributed system, self-organizing, production-ready.**

The system operates autonomously within defined trust boundaries. New nodes can be onboarded through the protocol without manual integration work. The coordination layer self-organizes. Omega is ready for external projects to join as nodes.

**Core deliverables:**
- Autonomous node onboarding: new capability registered and integrated by protocol
- Coordination Layer v3: self-organizing, persistent learning across cycles
- Full autonomy for Victoria's quant research within Supervised mode
- External node integration path documented and tested
- Production SLOs met: uptime, latency, improvement cycle cadence
- Omega CLI: interact with the coordination layer from the terminal

---

## 3. Detailed Backlog

---

### Q2 2026 (Months 1–3): Foundation Epics

---

#### EPIC-001: Observability Infrastructure (P0 Closure)
**Effort:** L
**Dependencies:** None
**Status (2026-03-23):** Not started. D1 confirms OTLP backend not deployed; `deploy/docker-compose.otel.yaml` exists but is not wired into the main stack. D2 confirms Python trace IDs remain non-W3C-compliant. Additionally: `state_tensor.go:Subscribe()` busy-polls at 50ms and never delivers notifications (A2) — fix belongs here as I3.

**Description:**
The current OTel setup silently discards metrics when no OTLP backend is configured. Python trace IDs are not W3C-compliant, breaking distributed tracing across the Go/Python boundary. Error classification is absent. This epic makes the telemetry system trustworthy.

**Deliverables:**
- Deploy OTLP backend: either Grafana Cloud (recommended for speed) or self-hosted Grafana + Mimir + Tempo stack
- Configure Go and Python SDKs to export to the same OTLP endpoint
- Python TraceContext propagation fixed to W3C `traceparent` format
- Error classification taxonomy: `system_error`, `validation_error`, `timeout`, `safety_violation`, `data_quality`
- Grafana dashboards: per-node trace count, error rate, cycle duration (P50/P95/P99)
- Alerting: error rate > 5% on any node triggers Slack/PagerDuty notification
- Health check endpoint on every service verifying OTLP connectivity

**Success Criteria:**
- Zero silent metric drops (verified by comparing emitted vs received counts)
- A complete Victoria cycle (DataIngestion → Ring3Adversarial) produces a single trace visible in Tempo with all spans from both Go and Python
- Error rate dashboard shows real values, not zeros

---

#### EPIC-002: Go/Python Bridge Protocol
**Effort:** L
**Dependencies:** EPIC-001 (tracing must propagate across boundary)
**Status (2026-03-23):** Partial. `pipeline_server.py` exists and handles `ExecuteStep` calls from Go. `bridge.PipelineClient` can call Python. However, A6 confirms `OrchestratorHandler.WithPipelineClient()` is optional — the handler runs `runCycle()` without the pipeline client by default. The bidirectional wiring is partially built but not exercised in the default Docker Compose stack.

**Description:**
Victoria's Python pipeline currently connects to the Go API via SQLite and informal conventions. This is fragile, untyped, and impossible to observe. The bridge should use the same Connect-RPC + Protobuf stack that Go uses, making Python a first-class API participant.

**Deliverables:**
- Protobuf definitions for the Bridge API: `PipelineRequest`, `PipelineResult`, `StepState`, `ArtifactRef`
- Python Connect-RPC client (using `connectrpc` Python library or buf-generated stubs)
- Go Connect-RPC server handlers for Python pipeline invocations
- Bidirectional: Go can call Python pipeline steps; Python can call Go services
- SQLite dependency removed from the communication path (may retain as persistence)
- W3C trace context propagated in all bridge calls
- Integration test: Go calls Python `SignalResearch` step and receives typed result

**Success Criteria:**
- Victoria pipeline steps callable from Go with typed request/response
- All bridge calls appear as spans in distributed traces
- No SQLite read/write in the hot communication path

---

#### EPIC-003: Node Protocol v1
**Effort:** M
**Dependencies:** EPIC-002

**Description:**
Define the standard interface every Omega node must implement. This is the most important architectural decision of the year — get it right here or pay the refactoring cost later. The protocol should be minimal but extensible.

**Deliverables:**
- `node.proto`: defines `NodeInfo`, `CapabilityDescriptor`, `StateSnapshot`, `HealthStatus`, `InvokeRequest`, `InvokeResponse`
- Node lifecycle: `Register`, `Heartbeat`, `Invoke`, `Shutdown`
- State snapshot: structured representation of current node state (not arbitrary JSON — typed fields with versioning)
- Capability declaration: what the node can do, input/output types, latency SLOs
- Victoria refactored to implement Node Protocol v1 as the reference implementation
- Node SDK (Go + Python): helpers for implementing the protocol without boilerplate
- Protocol documentation: "How to write a new Omega node" (1-2 pages)

**Protocol Design (key decisions):**
```protobuf
message NodeInfo {
  string node_id = 1;
  string node_type = 2;       // e.g., "market_intelligence", "observability"
  string version = 3;
  repeated CapabilityDescriptor capabilities = 4;
  TrustLevel current_trust = 5;
}

message StateSnapshot {
  string node_id = 1;
  google.protobuf.Timestamp captured_at = 2;
  bytes state_tensor = 3;     // serialized tensor (float32 array, shape defined by schema)
  map<string, string> metadata = 4;
  HealthStatus health = 5;
}
```

**Success Criteria:**
- Victoria implements Node Protocol v1 and passes protocol conformance tests
- A new stub node can be created using the SDK in under 2 hours
- Protocol has at least one versioning mechanism (capability negotiation)

---

#### EPIC-004: Safety Violation Persistence
**Effort:** S
**Dependencies:** EPIC-001
**Status (2026-03-23):** Not started. E4 confirms adversarial pressure fix is ✅ complete (`AdversarialPressureV2.run_v2()` now called in `_step_adversarial()`), but Ring 1 still cannot fire with a single-node topology (needs ≥2 variants for ensemble disagreement). Safety violations are still not persisted. E5 confirms PICO sandbox has no enforcement — Python nodes in PICO mode can call any system API.

**Description:**
Currently, safety violations are detected but not persisted. This means the system has no memory of past violations, making trust scoring and graduated autonomy impossible. Violations must be stored, queryable, and surfaced in the dashboard.

**Deliverables:**
- `safety_violations` table (or collection) with: node_id, timestamp, violation_type, severity, context, resolved_at
- Go service endpoint: `LogViolation`, `QueryViolations`, `ResolveViolation`
- Dashboard: Safety violations list on Issues page with filter by severity
- Alerting: Critical violations trigger immediate notification
- Violation history used in trust score computation (EPIC-012)

**Success Criteria:**
- Every safety violation from the last 30 days queryable by node and type
- Dashboard Issues page shows real violation data

---

#### EPIC-005: Traces Page Node Filter + Span Detail Overlay
**Effort:** S
**Dependencies:** EPIC-001

**Description:**
The Traces dashboard page is missing a `node_id` filter, making it difficult to debug specific node behavior. Span detail overlay (clicking a span to see attributes) is also missing.

**Deliverables:**
- Traces page: `node_id` dropdown filter (populated from live trace data)
- Traces page: time range filter
- Span detail overlay: click any span row to see all span attributes, events, and links
- Cycle replay: select a historical cycle ID and replay its trace timeline

**Success Criteria:**
- Can filter traces to a single node and see only that node's spans
- Clicking a span shows full attribute set including custom Omega attributes

---

#### EPIC-006: Metric Regression Detection
**Effort:** M
**Dependencies:** EPIC-001

**Description:**
The system collects metrics but has no automated way to detect when a metric has regressed. This is a prerequisite for autonomous operation — the system needs to know when something got worse.

**Deliverables:**
- Baseline computation: for each tracked metric, compute rolling 7-day baseline with P10/P50/P90
- Regression detection: flag when current value deviates > 2σ from baseline
- Regression events surfaced on Issues page as `metric_regression` issue type
- Grafana alerting rules for key metrics: cycle duration, signal quality, adversarial ensemble score

**Success Criteria:**
- Artificially degrading a metric triggers an issue within one cycle
- Dashboard shows metric regression history per node

---

#### EPIC-023: Data Pipeline Integrity Fixes
**Effort:** M
**Dependencies:** None (independent of infrastructure)
**Priority:** P0 — must complete before any evaluation results are trusted

**Description:**
The 2026-03-23 system evaluation identified critical data integrity issues that produce misleading evaluation metrics. The system silently falls back to synthetic data, uses an additive (not multiplicative) equity curve, has look-ahead bias in entry pricing, and loses all cycle history on restart. Every metric produced by the current system is suspect until these are fixed.

**Specific Findings (from SYSTEM_EVALUATION_2026_03_23.md):**
- B1/C1: Silent synthetic data fallback — no loud failure, no `INVALID` marker in results
- B4/C4: Look-ahead bias in `backtest.py:_sma_crossover_strategy()` — entry pricing uses bar close instead of next-bar open
- I6: Additive equity curve in `_compute_metrics()` — must be multiplicative (`np.cumprod(1 + daily_returns)`)
- I7: Bootstrap CIs never included in `EvalReport` — `compute_sharpe_confidence_interval()` is implemented but never called from `build_eval_report()`
- F5: `CycleHistory` bounded at 500 in-memory entries with no Postgres persistence — all history lost on restart
- B9: No data freshness/staleness guard — system can operate on hours-old market data without any indication
- F1/I10: Tight orchestration loop (`sleep_seconds=0.0` default) — will hammer Binance/CoinGecko in production

**Deliverables:**
- `_load_data()` raises `DataQualityError` (not silent fallback) when real data unavailable; all synthetic results marked `data_source: "synthetic"` in `EvalReport`
- `backtest.py` entry pricing fixed: use next-bar open price, not current-bar close
- Equity curve computation changed to multiplicative: `cumulative = np.cumprod(1 + daily_returns)`, CAGR formula corrected
- `build_eval_report()` calls `compute_sharpe_confidence_interval()` — every report includes 95% CI
- `cycle_history` Postgres table: write each `CycleResult` on completion; `CycleHistory` reads from DB on startup
- Data freshness guard: `DataIngestionNode.poll()` stamps `last_successful_fetch`; orchestrator checks freshness before proceeding; signal quality penalty when data age exceeds threshold
- Configurable orchestrator sleep: `sleep_until="next_candle"` mode to align with market close
- Fat-tail synthetic fallback (bonus): replace LCG with Student-t (ν=4) + GARCH(1,1) to approximate real crypto return statistics when fallback is unavoidable

**Success Criteria:**
- Every `EvalReport` on synthetic data shows `data_source: "synthetic"` prominently
- Running Victoria on real Binance data: equity curve is multiplicative, Sharpe includes 95% CI
- After restart, last 500 cycle results restored from Postgres
- Introducing a stale data condition (mock failed poll) triggers a data freshness warning within one cycle

---

#### EPIC-024: Security Hardening
**Effort:** M
**Dependencies:** None

**Description:**
The 2026-03-23 evaluation found multiple security issues that create real risk in any non-local deployment. Default credentials are hardcoded, RPC control endpoints have no auth, and Python nodes have no sandbox despite PICO mode being defined. These must be resolved before any cloud or shared deployment.

**Specific Findings:**
- C7/E1: `docker-compose.yml` hardcodes `POSTGRES_PASSWORD: omega`; port 5432 exposed on `0.0.0.0`
- C8/E2: `StartOrchestrator`, `StopOrchestrator`, `RunImprovement` RPC endpoints callable by any HTTP client with port 8080 access — no auth middleware
- E3: API keys loaded from `.env` with no secret rotation, auditing, or least-privilege
- D3: No immutable audit trail — safety-critical events (autonomy transitions, adversarial flags, improvement decisions) exist only in ephemeral logs
- A7: Python data ingestion path has no circuit breaker — Binance/CoinGecko failures fall through silently

**Deliverables:**
- `docker-compose.yml`: all credentials moved to `.env` with `${VAR}` references; `.env.example` provided; 5432 not exposed on `0.0.0.0` in non-dev configs
- API key auth middleware on Connect-RPC handlers: `StartOrchestrator`, `StopOrchestrator`, `RunImprovement` require `Authorization: Bearer <api_key>` header
- `omega_audit_log` Postgres table: append-only log for safety-critical events (schema: `event_type`, `node_id`, `timestamp`, `actor`, `payload`, `previous_state`, `new_state`)
- Python circuit breaker on `DataIngestionNode`: retry with exponential backoff on rate limits; circuit opens after 3 consecutive failures; logged with full context
- Secret rotation documentation: how to rotate API keys without downtime

**Success Criteria:**
- `docker-compose up` with no `.env` fails loudly (not silently uses defaults)
- RPC control endpoints return 401 without valid API key
- Every adversarial flag, autonomy transition, and improvement decision writes to `omega_audit_log`
- Binance rate limit triggers circuit breaker within 3 failures, not a silent synthetic fallback

---

---

### E2E Cycle Assessment Action Items (2026-03-24)

The following items were identified from a live end-to-end execution assessment and a gap analysis of the evaluation framework. They are sourced from `docs/E2E_CYCLE_FINDINGS.md`. Items are ordered by priority within each quarter.

---

#### ACTION-001: Project-Driven runCycle (FINDING-003)
**Effort:** S
**Priority:** P0 — Platform/project decoupling
**Quarter:** Q2 2026
**Status:** Implemented 2026-03-24

`victoriaSteps()` in `internal/handler/orchestrator.go` hardcoded Victoria pipeline steps into platform code — a direct violation of the platform/project separation rule. `runCycle()` now reads `PipelineConfig` from the `ProjectHandler` registry. When no projects are registered, the cycle logs a warning and skips pipeline dispatch. Victoria's steps come from its `omegav1.Project` registration in `main.go`.

---

#### ACTION-002: Paper Trading Persistence (FINDING-002)
**Effort:** M
**Priority:** P0 — Zero trading data in DB
**Quarter:** Q2 2026
**Status:** Implemented 2026-03-24

`victoria_trades`, `victoria_portfolio`, and `victoria_signals` tables had 0 rows. `PaperTradingEngine` added to `omega/nodes/victoria/paper_trading.py`. After risk management completes, the engine writes signals to `victoria_signals`, simulates fills into `victoria_trades`, and tracks portfolio state in `victoria_portfolio`. Victoria-specific — triggered by Victoria project config, not hardcoded in platform.

---

#### ACTION-003: ImprovementEngine Wired to VictoriaNode (FINDING-004)
**Effort:** M
**Priority:** P1 — Self-improvement loop silent
**Quarter:** Q2 2026
**Status:** Implemented 2026-03-24

`ImprovementEngine.evaluate_and_record()` stored `best_params` in memory but never called `apply_params()`. `VictoriaNode` is now registered with `ImprovementEngine` at startup. After each cycle with `improvement_config.tpe_enabled=True`, the engine runs with real cycle metrics (Sharpe, error rate). When TPE finds better params, `apply_params()` is called and the node version increments.

---

#### ACTION-004: `make dev` Target (FINDING-013)
**Effort:** XS
**Priority:** P1 — Developer experience
**Quarter:** Q2 2026
**Status:** Implemented 2026-03-24

Starting the dev environment required 3 manual steps in the correct order. `make dev` now brings up Postgres via Docker Compose, backgrounds the Python pipeline server, and runs the Go API in the foreground with `OTLP_ENDPOINT` set. `make dev-down` tears down the stack.

---

#### ACTION-005: CLI Per-Step Results (FINDING-014)
**Effort:** S
**Priority:** P1 — Developer experience
**Quarter:** Q2 2026
**Status:** Implemented 2026-03-24

`omega run` showed only a one-line health summary per cycle with no per-step visibility. Added `--cycles N` flag. When set, the CLI runs N cycles synchronously and displays per-step success/failure and latency: `step_name: success (123ms)` or `step_name: FAILED (error)`. Shows cycle summary (total duration, steps completed, error count) at the end.

---

#### ACTION-006: Fix REST Autonomy Gate (FINDING-005)
**Effort:** S
**Priority:** P0 — Dashboard broken
**Quarter:** Q2 2026
**Status:** Open

`GET /api/v1/nodes` returns `autonomy gate: action "GET" is not permitted at PICO autonomy level`. The gate is matching HTTP method strings against action names. REST paths under `/api/v1/` must bypass the autonomy gate — only semantic action names should be gated.

**Fix:** In `withExecChain`, skip gate evaluation for paths starting with `/api/v1/`. Or filter HTTP verb strings in `NewAutonomyGateMiddleware`.

---

#### ACTION-007: Fix Tracer.end_span() Type Confusion (FINDING-006)
**Effort:** XS
**Priority:** P2
**Quarter:** Q2 2026
**Status:** Open

`Tracer.end_span()` crashes when passed a `TraceContext` object instead of a `str` span_id. Add runtime type coercion: `if isinstance(span_id, TraceContext): span_id = span_id.span_id`. Add docstring.

---

#### ACTION-008: Set OTLP_ENDPOINT in Default Startup (FINDING-007)
**Effort:** XS
**Priority:** P2 — Observability gap
**Quarter:** Q2 2026
**Status:** Implemented as part of `make dev`

Resolved by `make dev` setting `OTLP_ENDPOINT=http://localhost:4318`. Remaining: add a startup warning when `OTLP_ENDPOINT` is unset so operators know traces are going to stdout only.

---

#### ACTION-009: Confirm StateService→Postgres Connection (FINDING-008)
**Effort:** S
**Priority:** P1
**Quarter:** Q2 2026
**Status:** Open

`StateService/BeginExecution` returns success but rows don't appear in Postgres. Verify `DATABASE_URL` is set. Add a startup validation that confirms a test write lands in Postgres. Log the DB host (not password) at startup.

---

#### ACTION-010: Wire AdversarialPressureV2 in _step_adversarial() (FINDING-009)
**Effort:** S
**Priority:** P1 — Adversarial layer is no-op
**Quarter:** Q2 2026
**Status:** Open

`_step_adversarial()` checks `not isinstance(proposal, dict)` — a condition that can never be True given `_step_strategy()` already filters for dicts. `AdversarialPressureV2` is constructed but never called. Wire `self._adversarial.run_v2(proposals)` in `_step_adversarial()`. Populate 3 default structural challenges.

---

#### ACTION-011: Wire GoalArchitecture into Cycle (FINDING-010)
**Effort:** M
**Priority:** P2
**Quarter:** Q3 2026
**Status:** Open

`GoalArchitecture` is initialised but never called from any cycle. `goal_tracking` table: 0 rows. Wire `GoalArchitecture.evaluate_cycle(cycle_metrics)` into VictoriaNode's post-cycle hook. Write result to `goal_tracking`. Victoria-specific — belongs in `omega/nodes/victoria/`, not platform.

---

#### ACTION-012: Fix Python Trace IDs to W3C-compliant Format (FINDING-011)
**Effort:** M
**Priority:** P2 — Distributed tracing broken
**Quarter:** Q3 2026 (part of EPIC-001)
**Status:** Open

Python trace IDs are not W3C `traceparent`-compliant. Python/Go spans appear as disconnected trees in Grafana/Tempo. Generate W3C-compliant trace IDs. Propagate `traceparent` header in all Python → Go calls. This is part of EPIC-001 but called out separately due to severity.

---

#### ACTION-013: Wire Memory Kernel to Cycle Output (FINDING-012)
**Effort:** M
**Priority:** P3
**Quarter:** Q3 2026
**Status:** Open

`MemoryKernel` initialises but no new memories are written during live runs. After each cycle, extract key facts (signal directions, top/bottom performers) and write episodic memories. Schedule consolidation every N cycles. Victoria-specific.

---

#### ACTION-014: Adversarial Review Substantive Challenges (FINDING-009 continued)
**Effort:** M
**Priority:** P2
**Quarter:** Q3 2026
**Status:** Open

Even after wiring `AdversarialPressureV2`, the challenges list is empty. Populate default structural challenges:
1. Concentration risk check (max position weight > 40% → challenge)
2. Data staleness check (market data > 30min old → challenge)
3. Signal correlation check (all signals agree by > 90% → correlated signal warning)

---

#### ACTION-015: OOS Contamination and TPE Third Split (EVAL_GAP_ANALYSIS A3)
**Effort:** L
**Priority:** P2 — Eval framework integrity
**Quarter:** Q3 2026
**Status:** Open

All TPE trials in `BacktestEvaluator` score against the same fixed calendar OOS window, which is no longer out-of-sample after the first trial. A proper design requires a held-out test set that TPE never sees. Add a mandatory third split: train/validate(OOS for TPE)/test(never seen by TPE). Until this is fixed, all Sharpe numbers from TPE optimisation are upper-bounded estimates.

---

### Q3 2026 (Months 4–6): Scale Epics

---

#### EPIC-007: NATS Message Bus
**Effort:** L
**Dependencies:** EPIC-003 (Node Protocol must be stable)

**Description:**
Synchronous Connect-RPC calls create tight coupling and make the system brittle under partial failure. NATS provides async pub/sub, request-reply, and JetStream persistence that fits the Omega node communication pattern naturally. NATS is chosen over Kafka (too heavy) and Redis pub/sub (no durability) for this scale.

**Architecture Decision:**
NATS with JetStream for:
- Node state broadcasts (`omega.nodes.{node_id}.state`)
- Coordination commands (`omega.coordination.commands`)
- Improvement proposals (`omega.improvements.proposals`)
- Safety events (`omega.safety.violations`)

Connect-RPC retained for:
- Synchronous typed API calls (dashboard → backend)
- Go/Python bridge for pipeline steps requiring request-reply semantics

**Deliverables:**
- NATS server deployed (docker-compose for local, k8s for production)
- Go NATS client library with Omega-specific helpers
- Python NATS client library (nats.py) with matching helpers
- Node state broadcasts: every node publishes `StateSnapshot` on heartbeat
- Coordination command consumer: nodes subscribe to commands from coordinator
- JetStream streams: `OMEGA_IMPROVEMENTS`, `OMEGA_SAFETY`, `OMEGA_STATES` with retention policies
- Dashboard: NATS cluster health on Metrics page
- Dead letter queue handling for failed message processing

**Success Criteria:**
- Victoria publishes state snapshots to NATS on every heartbeat
- Coordinator receives state updates without polling
- A node failure does not block other nodes (async decoupling verified)

---

#### EPIC-008: Node Capability Registry
**Effort:** M
**Dependencies:** EPIC-003, EPIC-007

**Description:**
The coordination layer needs to know what nodes exist, what they can do, and whether they're healthy. A capability registry is the service discovery layer for Omega's neural architecture.

**Design (inspired by Consul, but purpose-built):**
- Nodes register on startup with capabilities and SLO declarations
- Registry publishes `NodeRegistered`, `NodeDeregistered`, `NodeHealthChanged` events to NATS
- Registry persists to SQLite (simple, reliable, queryable)
- Coordination layer subscribes to registry events for real-time node topology

**Deliverables:**
- `NodeRegistry` Go service with `Register`, `Deregister`, `List`, `GetCapabilities` endpoints
- Capability matching: given a goal description, return nodes that can contribute
- Health-weighted routing: prefer healthy nodes with high trust scores
- Dashboard: Nodes page enhanced with live registry data (capabilities, trust, uptime)
- Registry API used by coordination layer in EPIC-010

**Success Criteria:**
- All live nodes visible in registry within 5 seconds of startup
- Node failure detected within 2 heartbeat intervals (configurable, default 30s)
- Capability query returns correct node set for given goal type

---

#### EPIC-009: State Tensor Protocol
**Effort:** L
**Dependencies:** EPIC-003, EPIC-007
**Status (2026-03-23):** Partial — blocked by subscriber bug. `state_tensor.go` is implemented with `StateTensorSchema` and serialisation. However, A2 confirms `Subscribe()` enters a busy-poll loop calling `pg_notification_queue_usage()` every 50ms and never calls `pgxpool.WaitForNotification()` — the channel returned by Subscribe() will never receive a tensor. `StartListening()` wires this broken subscriber into the aggregator. The real-time state propagation described in the spec is silently dead. Fix tracked as I3 in EPIC-001.

**Description:**
The most novel architectural element. Nodes expose their internal state as a typed tensor — a structured numeric representation that the coordination layer can use for routing decisions. This is the mechanism through which nodes become "neurons" in the network analogy.

**Design:**
Each node defines a `StateTensorSchema` declaring the dimensions and semantics of its state tensor. The tensor is a float32 array where each dimension has a defined meaning:

- Victoria's state tensor might include: `[signal_quality, cycle_health, last_improvement_score, data_freshness, adversarial_ensemble_score, active_experiment_count, ...]`
- Telesis state tensor: `[error_rate_5m, p99_latency_ms, active_alerts, ingestion_lag_s, ...]`

The coordination layer learns to interpret these tensors to make routing decisions (Q4 2026).

**Deliverables:**
- `StateTensorSchema` protobuf definition: dimension names, types, ranges, semantics
- Tensor serialization: float32 little-endian bytes, schema versioned separately
- Victoria implements state tensor with 12–20 dimensions
- State tensor published to NATS on every heartbeat
- Tensor history stored (ring buffer, last 1000 snapshots per node)
- Dashboard: Convergence page shows state tensor heatmap over time
- Schema registry: coordination layer can fetch schema for any node

**Success Criteria:**
- Victoria's state tensor captures the essential health of the quant pipeline in a 16-dimensional vector
- Tensor values tracked in Grafana (each dimension as a metric)
- Tensor schema versioned with backward compatibility

---

#### EPIC-010: Coordination Layer v1
**Effort:** XL
**Dependencies:** EPIC-007, EPIC-008, EPIC-009

**Description:**
The coordination layer is the nervous system of Omega. v1 is a routing table with hand-specified rules — not learned yet, but structurally correct. This establishes the interface that v2 (learned routing) will replace.

**Design:**
The coordinator runs as a standalone Go service:
1. Receives goals from external input (user command, scheduled trigger, improvement engine)
2. Queries node registry for relevant capabilities
3. Reads current state tensors from subscribed nodes
4. Routes the goal to a plan: ordered sequence of node invocations
5. Dispatches invocations via NATS, collects results
6. Evaluates outcome, emits feedback signal
7. Persists the plan→outcome tuple for learning (used in v2)

**Deliverables:**
- `Coordinator` Go service: goal intake, plan generation, execution, outcome evaluation
- Routing rules DSL: `IF goal.type == "quant_research" AND victoria.health > 0.7 THEN route to victoria`
- Plan representation: `CoordinationPlan` protobuf (steps, dependencies, estimated duration)
- Execution engine: dispatches plan steps, handles partial failures
- Outcome store: persists (goal, plan, result, feedback_signal) for every coordination cycle
- Dashboard: new Coordination page showing active/recent plans, routing decisions
- Feedback signal definition: scalar value in [-1, 1] representing outcome quality

**Success Criteria:**
- Coordinator successfully routes a quant research goal through Victoria end-to-end
- Plans visible in dashboard with step-by-step execution status
- Outcome history queryable (will be training data for v2)

---

#### EPIC-011: Distributed Execution (k8s)
**Effort:** XL
**Dependencies:** EPIC-007, EPIC-008

**Description:**
Currently everything runs on a single machine. To scale and to enforce isolation between projects, deploy on k8s. Each node runs as a separate deployment with resource quotas.

**Design:**
Kubernetes (local: k3s or minikube; production: GKE given existing GCP projects):
- Each Omega node = one k8s Deployment
- NATS = StatefulSet
- Go API + Coordinator = Deployment
- Resource quotas enforce multi-project isolation
- ConfigMaps/Secrets for per-project configuration

**Deliverables:**
- Helm chart for Omega platform (NATS, Go API, Coordinator, Node Registry)
- Per-project Helm chart (parameterized for Victoria, future projects)
- CI/CD pipeline: push to main → build images → deploy to k8s
- Resource quotas: CPU/memory limits per project namespace
- Network policies: nodes in project A cannot call nodes in project B directly (must route through coordinator)
- Monitoring: k8s metrics integrated into Grafana
- Local dev experience: `docker-compose up` still works for single-machine development

**Success Criteria:**
- Victoria runs on k8s with the same behavior as local
- A crash-loop in Victoria does not affect the Go API pod
- Deployment takes < 5 minutes from merged PR

---

#### EPIC-025: Self-Improvement Loop Completion
**Effort:** L
**Dependencies:** EPIC-002, EPIC-003, EPIC-009, EPIC-010

**Description:**
The 2026-03-23 evaluation confirmed that the self-improvement loop has multiple broken links: the improvement engine accepts better parameters but never applies them, the goal architecture is never called from the orchestrator, the attention router weights are random and never updated from outcomes, memory consolidation output is never read by the signal layer, and Ring 1 adversarial cannot fire with a single-node topology. This epic closes all five broken links.

**Specific Findings:**
- C5/I5: `ImprovementEngine` stores best params but never calls `node.apply_params()` — no `apply_params()` interface exists on `Node`
- A4/I2: `GoalArchitecture` in `goals.py` is fully implemented (HTN + balanced scorecard) but never instantiated or called from `orchestrator_v2.py`
- A3/I8: `NewAttentionRouter()` initialises `RoutingWeightAdapter` as `nil`; EMA prior path never exercised; weights are random forever despite `OutcomeStore` accumulating the right data
- C10: `ConsolidationPipeline.consolidate()` moves records from short to long-term memory, but consolidated memories are never read by `VictoriaNode` or signal layer
- C6/E4: Ring 1 adversarial fires on ensemble disagreement between `variant_outputs`, but a single-node system only has one variant — Ring 1 can never fire
- A5: Capability vocabulary mismatch — orchestrator uses `"compute_signals"` while Go registry uses `"signal_generation"` — nodes advertising capabilities via registry never match Python orchestrator checks
- P2.8: No rolling system quality metric — no way to know if the system is getting better week-over-week

**Deliverables:**
- `Node` ABC gains `apply_params(params: dict) -> None` interface; `VictoriaNode` implements it
- `ImprovementEngine.evaluate_and_record()` calls `node.apply_params(best_params)` when `trial.accepted = True`
- `orchestrator_v2.run()` accepts a `Goal` object; `GoalArchitecture` decomposes it into `goal_node_ids` and strategy params
- `RoutingWeightAdapter` implemented with EMA priors; wired into `NewAttentionRouter()`; updates after each outcome record
- `VictoriaNode` gains interface to retrieve consolidated patterns from memory; `SignalResearchNode` reads distilled patterns as parameterised feature weights
- Ring 1 adversarial redesigned for single-node: use temporal variants (compare current signal proposal against last N proposals) instead of requiring multiple node variants
- Canonical capability vocabulary established in `node.proto`: Go registry and Python orchestrator use identical strings
- Rolling 30-cycle Sharpe trend metric added to `CycleResult` and dashboard Metrics page

**Success Criteria:**
- After a successful TPE trial, VictoriaNode's parameters are observably different in the next cycle
- Goal object passed to `orchestrator_v2.run()` changes which signals are weighted in the pipeline
- Attention router EMA weights shift measurably after 100 cycles (not identical to Xavier init)
- Consolidated memory patterns appear as active feature weights in signal research output
- Ring 1 fires during a cycle where the current proposal diverges significantly from recent history
- `omega nodes list` and Python orchestrator report the same capability strings for Victoria

---

#### EPIC-026: Paper Trading Mode
**Effort:** L
**Dependencies:** EPIC-002
**Note:** Promoted from Nice-to-Have (N1) based on evaluation finding C2: execution is a no-op, making the "actions_executed" metric misleading. Paper trading provides the feedback loop that makes self-improvement meaningful.

**Description:**
Victoria's execution step is a confirmed no-op. Every metric saying "actions_executed" is counting "proposals that passed adversarial review," not actual trades. Paper trading creates a virtual order book against real market prices, providing:
1. A non-misleading execution metric
2. Real outcome quality for the `OutcomeStore` (actual simulated PnL, not synthetic)
3. The feedback loop needed for attention router training and trust scoring

**Design:**
```
PaperTradingEngine:
- Maintains virtual portfolio (positions, cash, PnL)
- On proposal approval: executes against real-time or OHLCV prices (no slippage model initially)
- Tracks open positions, marks to market each cycle
- Produces PnL record per trade → feeds OutcomeStore as outcome_quality signal
- Paper trade history persisted to Postgres
```

**Deliverables:**
- `PaperTradingEngine` Python class: virtual portfolio state, execute/close position methods
- Trade execution against next-bar OHLCV prices (no look-ahead — entry at open of bar after signal)
- Position tracking: open positions, unrealised PnL, realised PnL per trade
- Trade history persisted to `paper_trades` Postgres table
- `OutcomeStore` updated with paper trade PnL as the `outcome_quality` signal
- Dashboard Portfolio page: live paper portfolio positions, PnL waterfall, drawdown chart
- Live vs backtest reconciliation: compare paper trade Sharpe against backtest Sharpe for same period

**Success Criteria:**
- Victoria paper trades for 30 days; `OutcomeStore` contains real PnL-based outcome quality records
- Paper Sharpe and backtest Sharpe visible side-by-side in dashboard (reconciliation gap quantified)
- Attention router EMA weights shift based on real paper trade outcomes

---

#### EPIC-012: Trust Scoring System
**Effort:** M
**Dependencies:** EPIC-004, EPIC-010

**Description:**
Trust is the mechanism through which graduated autonomy becomes real. Nodes earn trust through consistent good outcomes and lose trust through failures, safety violations, and poor outcomes. Trust score gates what actions a node is permitted to take autonomously.

**Design:**
```
TrustScore ∈ [0.0, 1.0]
- 0.0–0.3: PICO (sandbox only, no external calls)
- 0.3–0.7: Supervised (human approval for irreversible actions)
- 0.7–1.0: Autonomous (acts within pre-approved capability envelope)
```

Trust decay: without activity, trust decays toward 0.5 (center). Trust is not sticky — it must be earned continuously.

**Deliverables:**
- `TrustScore` computed per node from: outcome history, safety violations, metric regression events, uptime
- Trust score exposed in `NodeInfo` and state tensor
- PICO sandbox: hard enforcement — Python subprocesses cannot make external network calls when trust < 0.3
- Supervised gate: coordinator requires human approval for actions on nodes with trust 0.3–0.7
- Trust history dashboard: node trust score over time with event annotations
- Trust score configuration: adjustable weights per factor

**Success Criteria:**
- A node that produces 10 consecutive good outcomes advances from Supervised → Autonomous
- A safety violation drops trust by measurable amount immediately
- PICO sandbox enforcement tested and verified

---

### Q4 2026 (Months 7–9): Intelligence Epics

---

#### EPIC-013: LLM-as-Analyst Integration
**Effort:** L
**Dependencies:** EPIC-002, EPIC-010

**Description:**
The self-improvement engine currently proposes new parameter combinations via TPE. LLM analysts can propose new *vector types* — entirely new signal sources that TPE cannot imagine. Claude (or GPT-4o) reviews experiment results, reads the current signal library, and proposes new hypotheses.

**Design:**
```
Improvement Cycle:
1. Run N experiments
2. LLM Analyst receives: experiment results, current vector library, market context
3. Analyst proposes: new vectors, modified hyperparameter search space, new pipeline steps
4. Proposals queued in `OMEGA_IMPROVEMENTS` JetStream stream
5. Human reviews proposals (Supervised mode) or auto-approved (Autonomous mode)
6. Approved proposals become experiments in next cycle
```

**Deliverables:**
- `LLMAnalyst` Go service: wraps Claude API, manages context window for experiment results
- Prompt engineering: system prompt establishing analyst role, output format (structured JSON proposals)
- Proposal types: `NewVectorProposal`, `HyperparameterProposal`, `PipelineModificationProposal`
- Proposal queue: persisted in JetStream, reviewable in dashboard
- Approval workflow: dashboard UI for reviewing/approving/rejecting proposals
- Auto-approval rules: low-risk proposals (new vectors with cost < 1 experiment) approved automatically
- Feedback loop: approved proposals' outcomes fed back to analyst as context in next cycle

**Success Criteria:**
- LLM analyst produces at least 3 novel vector proposals per week
- At least 1 LLM-proposed vector outperforms baseline within first month
- Analyst context includes last 50 experiments with outcomes (no context overflow)

---

#### EPIC-014: Geometric Math Library Maturation
**Effort:** L
**Dependencies:** None (parallel workstream)

**Description:**
Victoria's quant architecture includes geometric market modelling: differential geometry, manifold learning, TDA (topological data analysis), information geometry, and spectral methods. These are partially implemented. This epic makes them production-quality.

**Deliverables:**
- Manifold learning: Riemannian metric estimation on price/volume manifolds, stable implementation
- TDA: persistent homology for detecting regime changes, tuned for financial time series
- Information geometry: Fisher information metric for comparing distributions (useful for detecting distribution shift in signals)
- Spectral methods: graph Laplacian on correlation matrices, eigenvalue decomposition stable at scale
- Benchmarks: each method benchmarked on 3.7M price rows, performance envelope documented
- Unit tests: mathematical correctness verified against known properties (e.g., geodesic distances satisfy triangle inequality)
- Integration with signal research step: geometry-derived features available as vectors

**Success Criteria:**
- TDA regime change detection achieves recall > 0.7 on labeled historical regime transitions
- All geometric methods run within latency budget (< 500ms per signal research cycle)
- Library has 90%+ unit test coverage

---

#### EPIC-015: Multi-Market Data Layer
**Effort:** L
**Dependencies:** EPIC-002

**Description:**
Victoria currently processes crypto (Binance/CoinGecko) and ASIC short data. A unified data adapter pattern allows adding ASX equities, NASDAQ, forex, and derivatives without restructuring the pipeline.

**Design:**
```
MarketDataAdapter interface:
- GetOHLCV(symbol, timeframe, start, end) → []OHLCV
- GetOrderBook(symbol, depth) → OrderBook
- GetFundamentals(symbol) → Fundamentals (equities only)
- StreamTrades(symbol) → chan Trade
- GetReferenceData(symbol) → ReferenceData
```

Adapters: Binance (existing), CoinGecko (existing), ASX (new), NASDAQ via Polygon.io (new), Forex via OANDA (new)

**Deliverables:**
- `MarketDataAdapter` protobuf interface + Go implementation
- ASX adapter: scraping/API integration for Australian equities
- NASDAQ adapter: Polygon.io integration
- Forex adapter: OANDA or equivalent
- Data normalization layer: unified OHLCV schema across all markets
- Backfill tooling: populate historical data for new symbols
- Dashboard: multi-market symbol search on Portfolio page
- Data quality monitoring: per-source freshness, gap detection

**Success Criteria:**
- Victoria pipeline runs on ASX data with same steps as crypto
- Data quality dashboard shows freshness for all active sources
- Adding a new market takes < 1 day (adapter pattern is truly pluggable)

---

#### EPIC-016: Coordination Layer v2 (Learning-Based Routing)
**Effort:** XL
**Dependencies:** EPIC-010, EPIC-009, EPIC-013
**Status (2026-03-23):** Structurally present, not learning. A3 confirms `NewAttentionRouter()` initialises `RoutingWeightAdapter` as `nil` — the EMA prior path in `Route()` is never exercised. Weights are Xavier-random at startup and remain constant. `OutcomeStore` correctly persists `(goal, routing, outcome)` tuples and the `TrainingEligible: outcomes >= 1000` gate exists, but nothing reads from the store to update router weights. The attention mechanism computes correct scores over random projections — equivalent to random routing. Fix tracked in EPIC-025 (RoutingWeightAdapter EMA wiring) and the offline training pipeline remains a Q4 deliverable.

**Description:**
The v1 coordination layer uses hand-written routing rules. v2 replaces this with a learned routing function trained on the (goal, state_tensor, plan, outcome) tuples accumulated since v1 launch. The attention mechanism reads current node state tensors and produces a routing distribution over available nodes.

**Architecture:**
A small transformer-like attention layer (implementable in Go with a simple matrix library, no PyTorch needed at this scale):
- Query: goal embedding (encoded from goal type + context)
- Keys: node state tensors (from EPIC-009)
- Values: node capability vectors (from registry)
- Output: routing weights → plan generation

**Deliverables:**
- Outcome dataset: at least 1000 (goal, plan, outcome) tuples from v1 operation
- Attention routing model: trained offline, exported as ONNX or equivalent
- Go inference: load ONNX model, run attention at coordination time
- A/B testing: run v1 and v2 in parallel, compare outcome quality
- Model update cadence: retrain weekly on new outcome data
- Dashboard: routing visualization showing attention weights per node

**Success Criteria:**
- v2 routing achieves better outcomes than v1 on 70% of coordination cycles (verified by A/B)
- Routing decisions explainable: dashboard shows why each node was selected
- Model update works without downtime (hot-swap)

---

#### EPIC-017: Cross-Node Composition
**Effort:** L
**Dependencies:** EPIC-010, EPIC-008

**Description:**
Emergent capabilities arise when nodes compose. The first composition: Telesis (observability) + Victoria (market intelligence). Telesis detects signal quality anomalies in Victoria's outputs; Victoria uses Telesis health metrics as features in its own models.

**Deliverables:**
- Telesis node implements Node Protocol v1
- Telesis state tensor: error rates, latency percentiles, active alerts
- Coordinator routes composition goal: "improve signal quality" → activates both Telesis and Victoria
- Victoria can consume Telesis state tensor as an input feature (system health as a signal)
- Anomaly composition: Telesis spike + Victoria degradation → automatic escalation
- Dashboard: Composition page showing cross-node activation patterns

**Success Criteria:**
- A Telesis anomaly in Victoria's pipeline triggers Victoria to run self-diagnostic automatically
- At least one composition-derived feature improves Victoria's signal quality metrics

---

#### EPIC-027: Concept Drift Detection
**Effort:** L
**Dependencies:** EPIC-007, EPIC-008
**Source:** Novel Idea 12.4 (SYSTEM_EVALUATION_2026_03_23.md) + Phase 4 item P4.6

**Description:**
The current system has no mechanism to detect when its signals have stopped working because the market regime has changed. IC EMA decay is slow and reactive. A dedicated `DriftDetector` node monitors signal quality proactively by computing Jensen-Shannon divergence between current and training-window distributions, triggering coordinated system response when drift is detected.

**Design:**
The `DriftDetector` registers as an Omega node with `"drift_detection"` capability. It runs on every cycle alongside Victoria:
```
For each active signal:
  1. Compute IC over rolling 20-cycle window
  2. Compute JS divergence: JSD(signal_dist_current ‖ signal_dist_training)
  3. If JSD > threshold OR IC drops below min_ic:
     → Publish ConceptDrift event to NATS omega.drift.events
     → Orchestrator: demote signal weight in DynamicWeightAllocator
     → Orchestrator: trigger expedited TPE improvement run
     → Adversarial layer: increase scrutiny threshold for drifting signal
```

**Deliverables:**
- `DriftDetector` Python node implementing Node Protocol v1
- Jensen-Shannon divergence computation between rolling and training-window signal distributions
- `ConceptDrift` protobuf event: `signal_id`, `drift_score`, `ic_current`, `ic_training`, `triggered_at`
- NATS event publication on drift detection
- Orchestrator handles `ConceptDrift` event: weight demotion + expedited TPE trigger
- Dashboard: Drift Monitor panel showing per-signal drift score over time, threshold crossings
- Configurable thresholds per signal type (crypto signals may drift faster than macro signals)

**Success Criteria:**
- Artificially injecting a regime change in test data triggers `ConceptDrift` event within 5 cycles
- Drifting signal's weight is demonstrably reduced within 1 cycle of `ConceptDrift` event
- Drift detection does not produce false positives (< 5% false positive rate on 90-day backtest)

---

### Q1 2027 (Months 10–12): Autonomy Epics

---

#### EPIC-018: Autonomous Node Onboarding
**Effort:** L
**Dependencies:** EPIC-003, EPIC-008, EPIC-010, EPIC-012

**Description:**
Currently, adding a new node requires manual integration work. This epic defines and implements the protocol for a new project to join Omega as a node without bespoke integration code.

**Process:**
1. Project implements Node Protocol v1 SDK
2. Project calls `Registry.Register` with capabilities and state tensor schema
3. Coordinator automatically discovers the new node and adds it to routing table
4. Trust score starts at 0.1 (PICO mode, sandboxed)
5. Human reviews the capability declaration and approves or rejects
6. Approved node begins receiving routing requests

**Deliverables:**
- Onboarding checklist: automated protocol conformance tests a new node must pass
- Capability declaration UI: dashboard form for defining node capabilities
- Trust bootstrap: manual override to set initial trust score with justification
- Onboarding documentation: "Add your project to Omega" guide (target: 1 day for a new project)
- Flaggr node onboarded as second production node using this process
- Cuttlefish node onboarded as third production node

**Success Criteria:**
- Flaggr onboarded in < 1 day using documented process
- Automated conformance tests pass for both new nodes
- Both nodes appearing in coordination routing within first week

---

#### EPIC-019: Victoria Full Autonomy
**Effort:** L
**Dependencies:** EPIC-012, EPIC-013, EPIC-016

**Description:**
Victoria's quant research loop runs without human intervention within the Supervised trust level. The improvement engine proposes, the LLM analyst proposes, experiments run, results are evaluated, and the best configurations are promoted to production — all automatically.

**Deliverables:**
- Improvement proposals auto-approved for low-risk changes (vector parameter tweaks)
- Experiment queue management: coordinator schedules experiments without manual trigger
- Production promotion: configurations meeting performance threshold auto-promoted
- Rollback automation: performance regression triggers automatic rollback within 1 cycle
- Weekly summary report: auto-generated markdown report of improvements made, experiments run, performance delta
- Human escalation: changes classified as "high-risk" still require approval (structural pipeline changes, new data sources)

**Success Criteria:**
- Victoria runs for 2 consecutive weeks without human-initiated improvement cycles
- At least 1 auto-promoted configuration beats previous baseline
- Rollback automation tested and verified

---

#### EPIC-020: Production SLOs and Alerting
**Effort:** M
**Dependencies:** EPIC-001, EPIC-011

**Description:**
Define and enforce Service Level Objectives for the Omega platform. This is a prerequisite for claiming "production-ready."

**SLOs:**
- Platform availability: 99.5% uptime (measured monthly)
- Coordination cycle completion: 95% of cycles complete within SLA
- Victoria cycle duration: P95 < 10 minutes
- Signal quality: ensemble score > 0.30 (current baseline: 34.2%)
- Safety: zero unhandled critical violations

**Deliverables:**
- SLO definitions in code (Prometheus recording rules or Grafana alerts)
- SLO dashboard: burn rate, error budget remaining, historical compliance
- Alerting: SLO breach within 1 hour triggers PagerDuty
- Runbooks: one-page response guide for each alert type
- Quarterly SLO review: automated report comparing actual vs targets

**Success Criteria:**
- Platform meets all SLOs for 30 consecutive days
- Every alert has a corresponding runbook
- Error budget visualization showing remaining budget per SLO

---

#### EPIC-021: Coordination Layer v3 (Self-Organizing)
**Effort:** XL
**Dependencies:** EPIC-016, EPIC-017, EPIC-018

**Description:**
The coordination layer develops persistent memory of node relationships and emergent composition patterns. v3 adds: long-term node relationship learning, capability composition discovery, and automatic addition of new composition patterns to the routing table.

**Key advancement over v2:**
v2 learns to route individual goals. v3 learns that *combinations* of nodes produce better outcomes than either alone, and actively seeks those combinations for new goals.

**Deliverables:**
- Node relationship graph: persistent graph of (node_A, node_B, composition_outcome) tuples
- Composition discovery: automatically identifies node pairs/triplets that produce superadditive outcomes
- Emergent routing rules: discovered compositions added to routing table automatically
- Coordination memory: coordinator maintains rolling context of last 100 cycles
- Self-organization dashboard: visualize node relationship graph and composition strength

**Success Criteria:**
- At least 3 emergent node compositions discovered without manual specification
- v3 routing outperforms v2 on 80% of coordination cycles
- Node relationship graph stable and interpretable

---

#### EPIC-028: Constitutional Memory Distillation
**Effort:** XL
**Dependencies:** EPIC-013, EPIC-019
**Source:** Novel Idea 12.6 (SYSTEM_EVALUATION_2026_03_23.md) + Phase 4 item P4.7

**Description:**
The current memory consolidation pipeline moves records from short-term to long-term memory (archival). The evaluation found that consolidated memories are never read back by the signal pipeline (C10). This epic transforms consolidation from archival into *distillation*: rather than copying or summarising records, the consolidation LLM extracts abstract strategy principles that become active parameterised constraints in the signal layer.

**Design:**
```
Consolidation as Distillation:
Input:  50-100 cycle records about profitable/losing conditions
Output: StrategyPrinciple protobuf:
  - condition: "CrossAssetCorrelation drops during high-VIX regimes"
  - action: "reduce cross-asset position size by 30%"
  - trigger: {metric: "vpin", operator: ">", threshold: 0.8}
  - confidence: 0.82
  - source_record_ids: [...]
  - created_at: timestamp

These principles are stored in `strategy_principles` table.
SignalResearchNode reads active principles on each cycle as parameterised rules.
```

**Deliverables:**
- `DistillationPipeline` replacing/extending `ConsolidationPipeline` with LLM-powered principle extraction
- `StrategyPrinciple` protobuf: condition, action trigger, confidence score, source records
- `strategy_principles` Postgres table with versioning (principles can be superseded)
- `SignalResearchNode` reads active high-confidence principles (confidence > 0.7) as parameterised feature weights
- LLM distillation prompt engineering: structured output for machine-readable principle format
- Principle confidence decay: principles that contradict recent outcomes get confidence reduced
- Dashboard: Constitutional Memory page showing active principles, confidence scores, source cycle records
- Human review gate: new principles require approval before activation (consistent with Supervised mode)

**Success Criteria:**
- After 200 profitable cross-asset cycles, system distills at least 1 principle about cross-asset behavior
- Distilled principle is observably active in signal research: the parameterised rule changes position sizing
- Principle confidence decay: a principle that causes 5 consecutive losing cycles loses > 20% confidence

---

#### EPIC-022: Omega CLI
**Effort:** M
**Dependencies:** EPIC-010, EPIC-008

**Description:**
A terminal-native interface to the Omega coordination layer. Consistent with Cloud Guardian's aesthetic — terminal intimacy, not cosplay.

**Commands:**
```
omega nodes list                    # all nodes, health, trust
omega nodes inspect victoria        # node detail, state tensor
omega goals submit "improve alpha"  # submit a goal to the coordinator
omega goals status <goal_id>        # plan execution status
omega improvements list             # pending LLM analyst proposals
omega improvements approve <id>     # approve a proposal
omega trust history victoria        # trust score timeline
omega traces tail victoria          # live trace stream
```

**Deliverables:**
- Go CLI binary (`omega`) using Cobra
- `omega nodes`, `omega goals`, `omega improvements`, `omega trust`, `omega traces` command groups
- Output: terminal-native tables, JSON output flag for scripting
- Auth: API key or JWT for remote connections
- Shell completion: zsh/bash completion scripts
- Binary distribution: `brew install omega` or direct download

**Success Criteria:**
- All dashboard operations accessible via CLI
- `omega goals submit` to `omega goals status` workflow verified end-to-end
- CLI usable for remote Omega instances (not just localhost)

---

## 4. Research-Backed Architecture Decisions

---

### Node Communication: NATS vs gRPC vs Custom

**Decision: NATS + JetStream for async; Connect-RPC retained for sync**

NATS is chosen for async inter-node communication over the alternatives:

- **Kafka** (Apache/Confluent): Excellent durability, but operational complexity (ZooKeeper/KRaft, consumer groups, partition management) is disproportionate for a system of this scale. Kafka shines at millions of messages/second with strict ordering guarantees — Omega's inter-node communication is more like hundreds of messages/minute.
- **Redis pub/sub**: Zero durability. A crashed consumer misses messages. Unacceptable for improvement proposals and safety events.
- **Custom message bus**: Not invented here. NATS is trivially deployable (single binary, 35MB), has excellent Go support, and JetStream provides exactly the durability semantics needed.
- **Temporal/Cadence**: Excellent for durable workflow orchestration, but the workflow model is too prescriptive. Omega's coordination logic is custom and needs to own its execution model. Temporal is worth revisiting if the coordinator becomes complex enough to need durable workflows (Q4 2026).

NATS JetStream reference: https://docs.nats.io/nats-concepts/jetstream

Connect-RPC is retained for synchronous typed calls (dashboard, Go/Python bridge) because the type safety and schema-first approach (Protobuf) provides the interface contract needed for the node protocol.

---

### State Synchronization: CRDTs vs Event Sourcing vs Shared State

**Decision: Event sourcing for state changes; state tensors as materialized views**

State in Omega has two distinct needs:
1. **Node internal state** — each node owns its state, others observe it
2. **Coordination state** — the coordinator needs a current snapshot of all nodes

For node-internal state, event sourcing (append-only log of state transitions) provides the auditability needed for debugging and the ability to replay cycles. Each node publishes events (`ExperimentStarted`, `SignalGenerated`, `ImprovementApplied`) to JetStream. These events are the source of truth.

State tensors are materialized views of this event log — a compact numeric summary computed on demand from recent events. This keeps the coordination layer fast (reading tensors, not replaying event logs) while maintaining full auditability.

CRDTs (Automerge, Yjs) are appropriate for collaborative editing scenarios where multiple writers need to merge concurrent changes. Omega's state is single-writer-per-node; CRDTs add complexity without benefit.

Reference: Martin Kleppmann, "Designing Data-Intensive Applications" (Chapter 11, Event-Driven Systems). Automerge project for CRDT reference: https://automerge.org

---

### Consensus: Raft vs Gossip vs Central Coordinator

**Decision: Central coordinator with no distributed consensus required at this scale**

Distributed consensus (Raft, implemented by etcd; gossip, implemented by Serf/Consul) solves the problem of multiple nodes needing to agree on a single value without a central authority. Omega's architecture has a deliberate central coordinator — this is a design choice, not a limitation.

Arguments for central coordinator:
- Omega is not a peer-to-peer system. There is a deliberate hierarchy: coordination layer routes intelligence; nodes execute.
- At the scale of 5–20 nodes, the complexity of distributed consensus is not worth the availability gain.
- A central coordinator that crashes is recoverable in < 30s (k8s restarts). The window of unavailability during a coordinator crash is acceptable; the complexity of a leaderless system is not.

When to revisit: if Omega scales to 100+ nodes across multiple data centers, or if the coordinator becomes a write-intensive hot path, consider etcd for coordinator leader election and configuration storage.

Reference: Diego Ongaro & John Ousterhout, "In Search of an Understandable Consensus Algorithm (Raft)", USENIX ATC 2014. etcd documentation for production Raft deployment patterns.

---

### Self-Improvement: NAS, AutoML, Meta-Learning

**Decision: Hierarchical self-improvement (parameter → architecture → meta)**

Victoria's current TPE-based hyperparameter optimization is Level 1 self-improvement: search over a fixed parameter space. The roadmap adds two higher levels:

**Level 2: Architecture search (Q3–Q4 2026)**
LLM-as-analyst proposes new pipeline steps and vector types — effectively Neural Architecture Search (NAS) applied to the quant pipeline. The search space is discrete (which nodes/steps to include) and compositional (which features to combine). Reference: Elsken et al., "Neural Architecture Search: A Survey" (JMLR 2019).

**Level 3: Meta-learning (Q1 2027)**
The coordination layer learns to adapt routing strategy based on market regime — different node compositions work better in trending vs mean-reverting vs volatile markets. This is meta-learning: learning to learn differently based on context. Reference: Chelsea Finn et al., "Model-Agnostic Meta-Learning for Fast Adaptation of Deep Networks" (ICML 2017). More applicable to Omega: Schmidhuber's "Evolutionary Principles in Self-Referential Learning" (1987) — the original framing of self-improving systems.

AutoML reference (for TPE context): Bergstra & Bengio, "Random Search for Hyper-Parameter Optimization" (JMLR 2012). TPE specifically: Bergstra et al., "Algorithms for Hyper-Parameter Optimization" (NeurIPS 2011).

---

### Trust Boundaries: Capability-Based Security

**Decision: Capability-based trust model with cryptographic sandbox enforcement**

The graduated autonomy model (PICO → Supervised → Autonomous) maps cleanly to capability-based security theory: a node's permissions are the capabilities it currently holds, not a fixed identity. Trust score determines what capabilities are granted.

Reference: Dennis & Van Horn, "Programming Semantics for Multiprogrammed Computations" (JACM 1966) — original capability paper. More practical: OCAP (Object Capabilities) design patterns, implemented in languages like E and Caja.

For Omega's implementation:
- PICO nodes: given a "sandbox capability" — can read data, write to local state, but cannot make external network calls or modify shared state
- Supervised nodes: given "external-read capability" but not "external-write capability"
- Autonomous nodes: hold the full capability set declared at registration

Cryptographic enforcement: sandbox boundary implemented as a Linux network namespace (via k8s NetworkPolicy) — not just software trust but OS-level enforcement.

---

### Observability at Scale: OpenTelemetry + Grafana Stack

**Decision: Full OTLP stack with Grafana for visualization**

The OTel ecosystem has become the de-facto standard for cloud-native observability. The specific stack for Omega:

- **Traces**: Tempo (Grafana Labs, compatible with Jaeger format, scales horizontally)
- **Metrics**: Mimir (Grafana Labs, Prometheus-compatible, long-term storage)
- **Logs**: Loki (Grafana Labs, label-based, structured log queries)
- **Frontend**: Grafana (unified query across all three signals)

This is the "LGTM stack" (Loki, Grafana, Tempo, Mimir) — fully open source, well-integrated, and the natural evolution of the Prometheus + Jaeger tooling many engineers already know.

Alternative considered: Datadog (fully managed, excellent UX, high cost at scale). Honeycomb (excellent for distributed traces, but less integrated with metrics/logs). Given that Omega will generate high-cardinality traces at scale, self-hosting is more cost-effective.

Reference: OpenTelemetry specification (https://opentelemetry.io/docs/). Grafana LGTM stack documentation. Charity Majors, "Observability Engineering" (O'Reilly 2022) — chapter on high-cardinality telemetry.

---

## 5. Risk Register

---

### RISK-001: Go/Python Bridge Latency Makes Synchronous Pipeline Untenable
**Probability:** Medium
**Impact:** High
**Description:** If network-serialized Connect-RPC calls between Go and Python add > 50ms per step, the 9-step Victoria pipeline will be significantly slower than the current in-process approach.

**Mitigation:**
- Benchmark bridge latency before committing to the architecture
- Design pipeline steps to batch requests (reduce call count, not call latency)
- Async pipeline execution via NATS (steps publish results, next step subscribes) eliminates synchronous wait
- Fallback: retain SQLite handoff for latency-sensitive steps, use bridge only for high-level coordination

**Trigger:** Bridge round-trip > 20ms under load → escalate to async-first design

---

### RISK-002: LLM Analyst Produces Low-Quality Proposals
**Probability:** Medium
**Impact:** Medium
**Description:** If Claude/GPT-4o proposals are consistently rejected or produce negative outcomes, the self-improvement loop stalls and the human becomes the bottleneck again.

**Mitigation:**
- Start with strictly constrained proposal types (parameter tweaks only, no structural changes)
- Maintain proposal acceptance rate metric; if < 50% over 30 days, review prompt engineering
- Human-in-the-loop review in early weeks to calibrate prompt quality before enabling auto-approval
- Log all proposals with rationale and outcomes — use this as few-shot examples in the system prompt
- Fallback: LLM used for analysis reports only (not actionable proposals) if quality is insufficient

**Trigger:** Proposal acceptance rate < 30% over 2 weeks → full prompt engineering review

---

### RISK-003: NATS Becomes a Single Point of Failure
**Probability:** Low
**Impact:** High
**Description:** If all inter-node communication routes through NATS and NATS goes down, the entire Omega platform becomes unresponsive.

**Mitigation:**
- NATS JetStream with replication factor 3 in production (k8s StatefulSet with 3 pods)
- Connect-RPC fallback for critical synchronous calls — don't route everything through NATS
- Circuit breaker on NATS client: fall back to direct HTTP calls for health-critical operations
- Recovery time objective: NATS cluster restart < 30s in k8s
- Chaos testing: deliberately kill NATS pod and verify graceful degradation

**Trigger:** NATS unavailability > 60s in production → incident response

---

### RISK-004: State Tensor Schema Proliferation
**Probability:** High
**Impact:** Medium
**Description:** Each node defines its own state tensor schema. As the node count grows, schemas diverge, making the coordination layer harder to train and the system harder to debug.

**Mitigation:**
- Define a "common dimensions" set that all nodes must include (health, error_rate, last_cycle_age)
- Schema versioning from day one (EPIC-009 requirement)
- Schema registry with human-readable descriptions — makes debugging tractable
- Coordination layer trained only on common dimensions initially; node-specific dimensions added incrementally
- Quarterly schema review: remove unused dimensions, consolidate similar ones

**Trigger:** Schema review flag > 20 dimensions per node on average → forced consolidation

---

### RISK-005: Geometric Math Library Performance at Scale
**Probability:** Medium
**Impact:** Medium
**Description:** TDA (topological data analysis) and manifold learning algorithms have superlinear time complexity. At 3.7M rows with high-frequency updates, these may not fit within the signal research cycle budget.

**Mitigation:**
- Benchmark each method on production data volume before integrating (EPIC-014 requirement)
- Streaming/incremental algorithms where available (incremental PH for TDA)
- Precompute geometry on downsampled data, full computation on regime change detection
- Python-native implementations first (scikit-tda, giotto-tda), then optimize hot paths in Go/C++

**Trigger:** Geometric feature computation > 20% of total cycle time → profile and optimize

---

### RISK-006: Multi-Market Data Quality Heterogeneity
**Probability:** High
**Impact:** Medium
**Description:** Different market data sources have wildly different quality characteristics. ASX data has gaps on public holidays; crypto has wash trading artifacts; forex has weekend spreads. A unified adapter that doesn't account for source-specific quirks will propagate garbage into signals.

**Mitigation:**
- Data quality framework in EPIC-015: per-source quality profiles with known artifacts
- Source-specific normalization pipeline stages (not just schema normalization)
- Quality score as a metadata field on all OHLCV records
- Signal research step checks data quality score before using source in feature computation
- Integration tests with known-bad data samples for each source

**Trigger:** Signal quality metric drops > 10% after adding new data source → investigate data quality pipeline

---

### RISK-007: Coordination Layer v2 Training Data Contamination
**Probability:** Medium
**Impact:** High
**Description:** If v1 routing rules systematically bias toward certain nodes, the training data for v2 will be unrepresentative. v2 will learn to replicate v1's biases rather than improving on them.

**Mitigation:**
- Epsilon-greedy exploration in v1: with probability ε (initially 0.1), route to a random eligible node instead of following the rule
- Log counterfactual outcomes: when v1 routes to node A, also estimate what would have happened with node B
- Dataset diversity check before v2 training: verify all nodes appear in training data
- v2 training includes explicit de-biasing: re-weight training examples to correct for v1's routing frequency

**Trigger:** Any node appears in < 10% of training examples → increase ε for that node class

---

### RISK-008: Trust Score Gaming
**Probability:** Low
**Impact:** High
**Description:** A node that learns the trust scoring function could optimize for trust score rather than actual outcomes — appearing to perform well while degrading real performance.

**Mitigation:**
- Trust score computation is opaque to nodes (not exposed via Node Protocol)
- Multiple trust signals, not a single gameable metric (safety violations, metric regression, outcome history, uptime — hard to simultaneously game all)
- Humans retain override authority at all trust levels — Autonomous mode is not "humans can't intervene"
- Anomaly detection on trust score velocity: trust increasing faster than outcome improvement is suspicious

**Trigger:** Trust score increases > 0.2 in 1 week without commensurate outcome improvement → manual audit

---

## 7. Novel Research Ideas

These are speculative but architecturally grounded ideas identified during the 2026-03-23 system evaluation. They are not yet EPICs — they represent potential directions for H1 2027 and beyond. Each has a corresponding EPIC or Phase 4 item where implementation has been scoped.

---

### 7.1 Outcome-Weighted Attention Training as Implicit Reinforcement

The `coordination_outcomes` table stores `(goal, routing, state_snapshot, outcome_quality)` tuples — exactly the data needed for offline RL. Rather than hand-crafted EMA weight updates (EPIC-025), the longer-term training approach treats this as a cross-entropy loss problem: given the state tensor and goal at routing time, which routing decision led to the best outcome? A simple cross-entropy loss on routing decisions weighted by outcome quality — no PyTorch required, just Go matrix operations. After 1000+ records, a weekend training run could produce weights that do meaningfully better than random. The infrastructure is already built; only the training loop is missing.

**Status:** Infrastructure complete (OutcomeStore). Training loop tracked in EPIC-016 (offline training pipeline).
**When to pursue:** After 1000 outcome records accumulate from EPIC-026 (paper trading provides real outcomes).

---

### 7.2 Adversarial Generator Node as a First-Class Capability

Instead of a fixed `AdversarialPressureV2`, create an `AdversarialNode` that registers with the orchestrator as a node with `"adversarial_review"` capability. This node receives current proposals + signal data and uses an LLM to generate adversarial arguments against each proposal. The orchestrator treats adversarial review as just another node output — weighted, replaceable, upgradeable, and evaluatable like any other capability. This makes adversarial pressure composable and improvable rather than hardcoded.

**Status:** Current adversarial pressure is fixed-logic (✅ v2 fix merged). Composable node architecture is a Q4 2026 direction.
**When to pursue:** After EPIC-017 (cross-node composition) establishes the composition patterns.

---

### 7.3 Goal-Conditioned Node Activation for Cross-Project Intelligence

The current orchestrator activates nodes by ID. A more powerful model: nodes advertise capabilities and cost (latency, resource), and the goal system decomposes a high-level goal into a capability requirement vector. The attention router finds the cheapest node portfolio satisfying the requirement. This enables "Solve goal X" without specifying which nodes — the coordination layer figures it out. This is the proper AGI-layer primitive: goal-directed, capability-driven orchestration.

**Status:** Partially scoped as Phase 3 item P3.9. Goal decomposition infrastructure exists in `GoalArchitecture` (never wired). Node capability registry planned in EPIC-008.
**When to pursue:** After EPIC-010 (Coordination Layer v1) + EPIC-025 (GoalArchitecture wiring) are complete.

---

### 7.4 Concept Drift as a First-Class Signal

Full description scoped as **EPIC-027**. The key insight beyond the EPIC: concept drift detection itself becomes a signal input to the strategy layer. When the DriftDetector reports that signal X is drifting, other signals that historically *anticorrelate* with X's drift become temporarily upweighted. Drift is information, not just a failure mode.

**Status:** Scoped as EPIC-027 (Q4 2026). The anticorrelation-as-signal direction is post-EPIC-027 research.

---

### 7.5 Compositional Node Discovery

When the system has 4+ nodes, the coordination layer could discover emergent compositions that outperform any single node. For example: "Telesis anomaly score × Victoria signal quality → gating function that reduces position size when Telesis detects infrastructure stress." These compositions are not hand-coded — the outcome store reveals them statistically as routing vectors that co-activate multiple nodes and achieve better outcomes. A periodic "composition search" job identifies these patterns and registers them as meta-nodes.

**Status:** Partially scoped as Phase 3 item P3.10 and in EPIC-021 (Coordination Layer v3 self-organizing). Prerequisite is EPIC-017 (cross-node composition) generating enough outcome data.
**When to pursue:** Q1 2027, after the node relationship graph in EPIC-021 has accumulated 90 days of data.

---

### 7.6 Constitutional Memory: Compression as Distillation

Full description scoped as **EPIC-028**. The deeper research question: can the distillation LLM discover principles the human designers didn't anticipate? Over 6–12 months of live trading, the memory system may distill regime-conditional rules that outperform hand-crafted factor models. The "constitutional" framing matters: distilled principles are constraints, not just weights — they override the base signal layer when triggered.

**Status:** Scoped as EPIC-028 (Q1 2027). The constitutional override mechanism (principles as hard constraints) is a post-EPIC-028 research direction.

---

## 6. Key Milestones

---

### Month 1 (April 2026)
**Theme: Observability foundation**

- OTLP backend deployed and receiving telemetry
- Victoria produces a complete distributed trace (Go + Python spans in single trace)
- Python trace IDs fixed to W3C format
- Safety violations persisted and visible in dashboard
- EPIC-001 complete, EPIC-004 complete

**Measurable outcome:** Zero silent metric drops. Full Victoria cycle visible in one Tempo trace.

---

### Month 2 (May 2026)
**Theme: Bridge + Protocol**

- Go/Python bridge operational (Connect-RPC, bidirectional)
- Node Protocol v1 defined and documented
- Victoria refactored to implement Node Protocol v1 (reference implementation)
- Metric regression detection running

**Measurable outcome:** Go can invoke Victoria's `SignalResearch` step via Connect-RPC. Regression on any metric triggers a dashboard issue within one cycle.

---

### Month 3 (June 2026)
**Theme: Foundation complete**

- Traces page node filter and span detail overlay complete
- EPIC-005 complete, EPIC-006 complete
- Q2 retrospective: all P0/P1 observability issues closed
- Architecture review: Node Protocol v1 signed off, no breaking changes planned for Q3

**Measurable outcome:** Every P0/P1 observability issue from the initial audit is resolved. Q3 work can begin on stable foundation.

---

### Month 4 (July 2026)
**Theme: Message bus**

- NATS deployed locally and in CI
- Core node communication async via NATS
- Node Capability Registry v1 operational
- All live nodes visible in registry

**Measurable outcome:** Victoria's state snapshots visible in NATS topic. Registry reports all nodes healthy within 5s of startup.

---

### Month 5 (August 2026)
**Theme: State tensors + distribution**

- State Tensor Protocol v1 implemented in Victoria
- Victoria's 16-dimensional state tensor tracked in Grafana
- k8s deployment working locally (k3s or minikube)
- Victoria running in a k8s pod with the same behavior as local

**Measurable outcome:** Victoria state tensor dimensions visible as Grafana metrics. k8s deployment passes all integration tests.

---

### Month 6 (September 2026)
**Theme: Coordination v1 + Trust**

- Coordination Layer v1 operational: routes a quant research goal through Victoria
- Trust scoring live: Victoria has a trust score that moves based on outcomes
- Trust history visible in dashboard
- Q3 retrospective: distributed architecture in place

**Measurable outcome:** Coordination dashboard shows live plans. Victoria's trust score changes based on cycle outcomes.

---

### Month 7 (October 2026)
**Theme: LLM analyst**

- LLM-as-analyst integration complete
- First LLM-proposed vector in production
- Proposal approval workflow functional in dashboard
- Improvement cycle runs without manual trigger

**Measurable outcome:** At least 1 LLM-proposed vector in Victoria's signal library. Improvement cycle runs automatically on schedule.

---

### Month 8 (November 2026)
**Theme: Geometry + multi-market**

- Geometric math library: all 5 methods stable and benchmarked
- Multi-market adapter: at least 1 new market (ASX or NASDAQ) producing signals
- Geometry-derived features available in signal research

**Measurable outcome:** TDA regime change detection achieves > 0.7 recall on test set. Victoria pipeline runs on ASX data.

---

### Month 9 (December 2026)
**Theme: Cross-node composition**

- Telesis implements Node Protocol v1
- First cross-node composition: Telesis anomaly → Victoria self-diagnostic
- Coordination Layer v2 training data collected (> 500 outcome tuples)
- Q4 retrospective: intelligence layer operational

**Measurable outcome:** Telesis anomaly triggers Victoria diagnostic automatically. 500+ coordination outcomes logged for v2 training.

---

### Month 10 (January 2027)
**Theme: Coordination v2 + new nodes**

- Coordination Layer v2 deployed (A/B with v1)
- v2 routing matches or beats v1 on initial validation set
- Flaggr node onboarded via autonomous onboarding process

**Measurable outcome:** v2 routing on par with v1. Flaggr appears in coordination routing.

---

### Month 11 (February 2027)
**Theme: Victoria full autonomy**

- Victoria improvement loop runs for 2 weeks without human-initiated cycles
- At least 1 auto-promoted configuration in production
- Rollback automation verified
- SLOs defined and measured for first time

**Measurable outcome:** Two consecutive weeks of autonomous Victoria improvement cycles. All SLOs measured (not necessarily met yet).

---

### Month 12 (March 2027)
**Theme: Production-ready neural distributed system**

- Platform meets all SLOs for 30 consecutive days
- Omega CLI v1 shipped
- Coordination Layer v3 prototype (self-organizing, node relationship graph)
- Architecture review: Omega is a neural distributed system ✓

**Measurable outcome:** 30-day SLO compliance report. CLI `omega nodes list` works against production. Node relationship graph shows at least 3 emergent compositions.

---

## Appendix A: Epic Summary Table

| Epic | Name | Quarter | Effort | Dependencies |
|------|------|---------|--------|--------------|
| EPIC-001 | Observability Infrastructure | Q2 2026 | L | None |
| EPIC-002 | Go/Python Bridge Protocol | Q2 2026 | L | EPIC-001 |
| EPIC-003 | Node Protocol v1 | Q2 2026 | M | EPIC-002 |
| EPIC-004 | Safety Violation Persistence | Q2 2026 | S | EPIC-001 |
| EPIC-005 | Traces Page Node Filter | Q2 2026 | S | EPIC-001 |
| EPIC-006 | Metric Regression Detection | Q2 2026 | M | EPIC-001 |
| EPIC-007 | NATS Message Bus | Q3 2026 | L | EPIC-003 |
| EPIC-008 | Node Capability Registry | Q3 2026 | M | EPIC-003, EPIC-007 |
| EPIC-009 | State Tensor Protocol | Q3 2026 | L | EPIC-003, EPIC-007 |
| EPIC-010 | Coordination Layer v1 | Q3 2026 | XL | EPIC-007, EPIC-008, EPIC-009 |
| EPIC-011 | Distributed Execution (k8s) | Q3 2026 | XL | EPIC-007, EPIC-008 |
| EPIC-012 | Trust Scoring System | Q3 2026 | M | EPIC-004, EPIC-010 |
| EPIC-013 | LLM-as-Analyst Integration | Q4 2026 | L | EPIC-002, EPIC-010 |
| EPIC-014 | Geometric Math Library | Q4 2026 | L | None |
| EPIC-015 | Multi-Market Data Layer | Q4 2026 | L | EPIC-002 |
| EPIC-016 | Coordination Layer v2 | Q4 2026 | XL | EPIC-010, EPIC-009, EPIC-013 |
| EPIC-017 | Cross-Node Composition | Q4 2026 | L | EPIC-010, EPIC-008 |
| EPIC-018 | Autonomous Node Onboarding | Q1 2027 | L | EPIC-003, EPIC-008, EPIC-010, EPIC-012 |
| EPIC-019 | Victoria Full Autonomy | Q1 2027 | L | EPIC-012, EPIC-013, EPIC-016 |
| EPIC-020 | Production SLOs and Alerting | Q1 2027 | M | EPIC-001, EPIC-011 |
| EPIC-021 | Coordination Layer v3 | Q1 2027 | XL | EPIC-016, EPIC-017, EPIC-018 |
| EPIC-022 | Omega CLI | Q1 2027 | M | EPIC-010, EPIC-008 |
| EPIC-023 | Data Pipeline Integrity Fixes | Q2 2026 | M | None — P0 |
| EPIC-024 | Security Hardening | Q2 2026 | M | None |
| EPIC-025 | Self-Improvement Loop Completion | Q3 2026 | L | EPIC-002, EPIC-003, EPIC-009, EPIC-010 |
| EPIC-026 | Paper Trading Mode | Q3 2026 | L | EPIC-002 |
| EPIC-027 | Concept Drift Detection | Q4 2026 | L | EPIC-007, EPIC-008 |
| EPIC-028 | Constitutional Memory Distillation | Q1 2027 | XL | EPIC-013, EPIC-019 |

---

## Appendix B: Architecture Diagram (Text)

```
                           ┌─────────────────────────────────────────┐
                           │             OMEGA PLATFORM              │
                           │                                         │
  ┌──────────────┐         │  ┌─────────────┐    ┌───────────────┐  │
  │   React      │◄────────┼──│  Go API     │    │  Coordinator  │  │
  │   Dashboard  │         │  │ Connect-RPC │◄───│   (v1→v3)     │  │
  └──────────────┘         │  └─────────────┘    └───────┬───────┘  │
                           │         ▲                    │          │
                           │         │                    ▼          │
                           │  ┌──────┴──────┐    ┌───────────────┐  │
                           │  │ Node        │    │ NATS          │  │
                           │  │ Registry    │    │ JetStream     │  │
                           │  └─────────────┘    └───────┬───────┘  │
                           │                             │           │
                           └─────────────────────────────┼───────────┘
                                                         │
                    ┌────────────────┬──────────────────┬┴─────────────┐
                    ▼                ▼                  ▼              ▼
           ┌──────────────┐ ┌──────────────┐  ┌──────────────┐ ┌──────────────┐
           │  VICTORIA    │ │  TELESIS     │  │  FLAGGR      │ │ CUTTLEFISH   │
           │  (Market     │ │  (Observ-    │  │  (Feature    │ │ (Deployment  │
           │  Intel Node) │ │  ability     │  │  Mgmt Node)  │ │  Node)       │
           │              │ │  Node)       │  │              │ │              │
           │ State Tensor │ │ State Tensor │  │ State Tensor │ │ State Tensor │
           │ Trust Score  │ │ Trust Score  │  │ Trust Score  │ │ Trust Score  │
           └──────┬───────┘ └──────────────┘  └──────────────┘ └──────────────┘
                  │
                  ▼
         ┌─────────────────┐
         │ Python Pipeline │
         │ 9-step quant    │
         │ research        │
         │ (Connect-RPC    │
         │  bridge)        │
         └─────────────────┘
```

---

*Document authored: March 2026. Next review: June 2026 (Q2 retrospective).*
*Owner: Ben Ebsworth. Classification: Internal.*
