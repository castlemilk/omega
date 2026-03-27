# Intelligence Instrumentation — Design Spec
_Date: 2026-03-27_

## Goal

Instrument the intelligence layer so we can measure and improve it. Without measurement we can't tell if the brain, memory, self-improvement, or adversarial layer are doing anything useful.

## Components

### 1. Postgres Table — `intelligence_metrics`

Added to `internal/db/db.go` bootstrap (consistent with all other tables). One row per cycle. Tracks:

- **Node improvement**: improve_calls, improve_accepted/rejected, signal_version, new_signals_unlocked
- **Brain/LLM**: brain_calls, brain_provider, brain_latency_ms, brain_tokens_used
- **Memory**: episodes_created/total, semantic_patterns extracted/total, shared_memory reads/writes, cross-project count
- **Reasoning**: reflection_calls, debate_gate_invocations/blocks, adversarial ring counts
- **Signal quality**: signals_active/nonzero/errored, rmt_info_ratio, wasserstein_confidence, geometric_curvature
- **Attention router**: routing_decisions, trust_score_avg
- **Composite**: intelligence_score (0–1, 8-check composite)

### 2. Python — `omega/core/intelligence_metrics.py`

`IntelligenceMetricsCollector`:
- `record(metric, value)` — set a metric for current cycle
- `increment(metric, amount=1)` — increment a counter
- `flush(cycle)` — compute `intelligence_score`, INSERT into postgres, reset state
- `_compute_intelligence_score()` — 8 boolean checks (brain active, improve active, episodes created, semantic extracted, shared memory reads, signals nonzero > 10, rmt_info_ratio > 0.3, debate gate invoked) averaged to float

Uses psycopg directly (same pattern as `MemoryBus`). No-ops gracefully if `DATABASE_URL` not set.

### 3. Python — `omega/core/memory_quality.py`

`MemoryQualityAssessor`:
- Queries existing tables: `episodes`, `semantic_memories`, `shared_memory`, `memory_ratings`, `paper_trades`
- Returns dict with: episode_count, semantic_count, shared_memory_count, memory_ratings_count, avg_episode_rating, episode_diversity, memory_utilization, stale_memory_pct, cross_project_ratio, memory_influenced_trades, memory_win_rate
- `memory_win_rate`: JOIN paper_trades WHERE memory_consulted=true vs false (requires memory_consulted flag or falls back to 0.0 if not tracked)
- `episode_diversity`: count distinct signal names mentioned in episode content
- `memory_utilization`: fraction of memories read at least once (requires read_count column — falls back to approximation from shared_memory access patterns)

### 4. Orchestrator Wiring (`orchestrator_v2.py`)

`OmegaOrchestrator.__init__` accepts optional `metrics_collector: IntelligenceMetricsCollector | None`.

Instrumentation hooks:
- **Brain calls**: after every `node.execute()` where `out.metrics` has `brain_calls` / `brain_latency_ms` / `brain_tokens_used` / `brain_provider` — aggregate into collector
- **Improve**: after `_improvement_scheduler.maybe_improve()` — increment `improve_calls`, `improve_accepted` or `improve_rejected` based on result
- **Memory**: after `_consolidation.run()` — record `episodes_created`, `semantic_patterns_extracted`; after `MemoryBus` reads/writes in nodes — increment via collector passed down
- **Debate gate**: after adversarial check — increment `debate_gate_invocations`, `debate_gate_blocks`
- **Signal quality**: from node output metrics — `signals_active`, `signals_nonzero`, `rmt_info_ratio`, etc.
- **Cycle end** (`post_cycle`): call `collector.flush(cycle_number)`

### 5. Protobuf — extend `omega_service.proto`

Add to `OrchestratorService`:

```proto
rpc GetIntelligenceMetrics(GetIntelligenceMetricsRequest) returns (GetIntelligenceMetricsResponse);
```

`GetIntelligenceMetricsRequest`: `last_n_cycles` (int32, default 100)

`GetIntelligenceMetricsResponse` fields (aggregated over last N cycles):
- brain_provider, brain_calls_total, brain_calls_per_cycle (float)
- improve_calls_total, improve_accepted_total
- signal_version_latest, new_signals_unlocked (repeated string)
- episodes_total, semantic_patterns_total, shared_memory_total
- memory_utilization_pct, cross_project_ratio
- intelligence_score_avg (float), intelligence_score_latest (float)
- checks_passing (repeated IntelligenceCheck — name + passing bool)

Run `buf generate` after proto change.

### 6. Go Handler

New method `GetIntelligenceMetrics` on `OrchestratorHandler` (or equivalent handler struct in `internal/handler/`). Queries `intelligence_metrics` with `ORDER BY cycle DESC LIMIT $1`, aggregates, returns proto response.

### 7. Go CLI — `status --intelligence`

Add `--intelligence` bool flag to `statusCmd`. When true, calls `client.GetIntelligenceMetrics(...)` and renders formatted output matching the spec:

```
Intelligence Layer Status (last 100 cycles):
  Brain provider: anthropic (haiku)
  ...
  Intelligence score: 0.625 (5/8 checks passing)
    ✅ Self-improvement active
    ❌ LLM reasoning (NoBrain — no API key)
    ...
```

### 8. Verification

Run `omega run` for 20 cycles (NoBrain mode, short interval) then `omega status --intelligence` to verify rows appear and score is computed.

## Data Flow

```
OrchestratorV2 (Python)
  → IntelligenceMetricsCollector.increment/record (per-cycle)
  → flush(cycle) → INSERT intelligence_metrics (Postgres)

Go API Handler
  → SELECT intelligence_metrics ORDER BY cycle DESC LIMIT N
  → Aggregate → GetIntelligenceMetricsResponse (proto)

Go CLI (omega status --intelligence)
  → Connect-RPC → GetIntelligenceMetrics → formatted output
```

## Constraints

- Python collector must no-op gracefully without `DATABASE_URL`
- Go handler must not break if table is empty (return zeroed response)
- Proto field names must follow existing `omega_service.proto` conventions
- All table creation in `internal/db/db.go` bootstrap (not a separate migration file)
