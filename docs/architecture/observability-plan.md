# Observability Architecture Plan

**Status:** Audit complete (2026-04-15). Implementation pending.  
**Audit scope:** `dashboard/`, `web/dashboard/`, `internal/handler/`, proto definitions, telemetry storage.

---

## Audit Findings Summary

### What Works

| Layer | What exists | Detail |
|-------|------------|--------|
| **Activation traces** | `data/activation_traces/*.jsonl` | Per-trade, per-signal data: `{trade_id, ticker, cycle, activations[{name, raw_value, reinforcement_weight, ic_weight, final_weight, weighted_value, direction_alignment}], composite{raw, demeaned, basket_mean, basket_std, weighted_conviction}, regime{label, bear_prob, bull_prob}}` |
| **Cycle metrics** | `/tmp/{version}_metrics.jsonl` | Per-cycle JSONL aggregates (not committed) |
| **SSE infrastructure** | `web/dashboard/src/hooks/useSSE.ts` | SSE subscription hook + `useFetch.ts` (5 s polling) |
| **Streaming RPC** | `MemoryService.StreamMemoryEvents` | Confirmed in proto; coarse `OrchestratorService.StreamEvents` exists (node_update, cycle_complete only) |
| **Postgres schema** | 13 tables | nodes, node_executions, traces, cost_events, issues, activity_log, improvement_log, config_revisions, brain_executions, alignment_decisions, adversarial_results, goal_tracking |
| **VictoriaSignal proto** | Fields present | `name, avg_ic, weight, half_life, current_value, trend` |

### What Is Broken / Missing

| Gap | Severity | Detail |
|-----|----------|--------|
| **Activation data not queryable via RPC** | HIGH | `activation_traces/*.jsonl` exists on disk but zero proto/handler coverage. No `GetSignalActivations` RPC. |
| **Geometry metrics absent everywhere** | CRITICAL | Ricci curvature, ORC, Fiedler eigenvalue, Fisher-Rao — not computed in Python, not in any proto message, no Postgres table, no Go handler, no dashboard page. |
| **No node-graph view** | HIGH | `NodesPage` in web/dashboard exists but shows static list — no graph topology, no execution flow, no edge weights. |
| **No signal Sankey / attribution view** | HIGH | Activation data captured; no DAG visualisation or per-signal weight breakdown UI. |
| **GeometryView is mock-only** | MEDIUM | `dashboard/src/components/GeometryView.tsx` renders hardcoded data. No RPC wired. |
| **reinforcement_multiplier missing from VictoriaSignal proto** | MEDIUM | Field captured in JSONL but not in proto, so dashboard can't surface it. |
| **Cycle-level streaming not wired to Victoria** | MEDIUM | `OrchestratorService.StreamEvents` exists but only emits coarse lifecycle events — no per-signal, per-cycle data. |

---

## Target Views

### View 1 — Node Execution Graph

**Goal:** Live directed graph of which nodes ran, in what order, with edge weights showing information flow.

**Data source:** `node_executions` Postgres table (already populated).  
**Current coverage:** `NodesPage` renders a flat list. No graph topology rendered.

**Work required:**
1. **Extend proto** — add `NodeGraph` message (nodes: list of `{id, type, status}`, edges: list of `{from, to, weight}`) to `OrchestratorService`.
2. **Go handler** — `GetNodeGraph(request)` → query `node_executions` JOIN `nodes`, return adjacency list.
3. **React page** — extend `NodesPage` or new `NodeGraphPage`. Use `react-flow` or `d3-force` to render DAG. Wire to `useFetch`.

**Effort:** Medium (3–5 days). Data exists; proto + handler + UI needed.

---

### View 2 — Signal Geometry Dashboard

**Goal:** Surface Ricci curvature, ORC (Ollivier–Ricci Curvature), Fiedler eigenvalue, Fisher-Rao metric — indicators of signal correlation geometry and market fragility.

**Data source:** Nothing. Geometry is not computed anywhere in the stack.

**Work required:**
1. **Python computation** — add `omega/nodes/victoria/geometry.py` computing ORC, Fiedler eigenvalue from signal correlation matrix, Fisher-Rao metric from regime probability distributions. Write output to `activation_traces/` or a new `geometry_traces/` JSONL per cycle.
2. **Postgres table** — `geometry_snapshots(id, version, cycle, timestamp, orc FLOAT, fiedler FLOAT, fisher_rao FLOAT, ricci_json JSONB)`.
3. **Proto** — add `GeometrySnapshot` message to `VictoriaService`.
4. **Go handler** — `GetGeometryHistory(version, from_cycle, to_cycle)` → Postgres.
5. **React page** — new `GeometryPage`. Time-series charts for ORC/Fiedler/Fisher-Rao.

**Effort:** Very High (10–15 days). Nothing exists; full stack from computation to UI.

---

### View 3 — Signal Attribution Sankey ⭐ Highest Value

**Goal:** For a given trade or cycle, show each signal's contribution as a Sankey flow: signal name → weight → direction contribution → composite conviction.

**Data source:** `data/activation_traces/*.jsonl` (already written per-trade).  
**Current coverage:** No RPC, no UI.

**Work required:**
1. **New proto message** — add `SignalActivation` and `TradeActivations` messages to `VictoriaService` proto:
   ```protobuf
   message SignalActivation {
     string name = 1;
     float raw_value = 2;
     float reinforcement_weight = 3;
     float ic_weight = 4;
     float final_weight = 5;
     float weighted_value = 6;
     bool direction_alignment = 7;
   }
   message TradeActivations {
     string trade_id = 1;
     string ticker = 2;
     int32 cycle = 3;
     repeated SignalActivation activations = 4;
     float composite_conviction = 5;
     string regime_label = 6;
   }
   ```
2. **Go handler** — `GetSignalActivations(version string, cycle_from int, cycle_to int)` → reads `data/activation_traces/{version}_*.jsonl`, returns list of `TradeActivations`. (Index by version+cycle range; no DB write needed for Phase 1.)
3. **React page** — new `SignalAttributionPage`. Components:
   - Cycle selector / trade-id picker
   - Sankey diagram (use `d3-sankey` or `recharts`): Source = signal names, Target = direction (long/short), flow width = `final_weight × weighted_value`
   - Table below showing all 18 signals with raw/weighted values

**Effort:** Medium (4–6 days). Data exists; needs proto + Go JSONL reader + React Sankey page.

---

## Recommended Build Order

1. **View 3 (Sankey)** first — data already captured in JSONL, needs only proto + Go file reader + React component. Highest ROI: immediately makes signal attribution legible during training runs.
2. **View 1 (Node Graph)** second — data in Postgres, needs proto extension + handler + React DAG component. Enables live debugging of orchestrator flow.
3. **View 2 (Geometry)** last — requires new Python computation layer before anything else can be built. Deferred until V131+ training is stable.

---

## Proto Changes Required (Views 1 + 3)

**`proto/omega/v1/victoria.proto`** — add to `VictoriaService`:
```protobuf
rpc GetSignalActivations(GetSignalActivationsRequest) returns (GetSignalActivationsResponse);

message SignalActivation { ... }   // see spec above
message TradeActivations { ... }
message GetSignalActivationsRequest {
  string version = 1;
  int32 cycle_from = 2;
  int32 cycle_to = 3;
}
message GetSignalActivationsResponse {
  repeated TradeActivations trades = 1;
}
```

**`proto/omega/v1/orchestrator.proto`** — add to `OrchestratorService`:
```protobuf
rpc GetNodeGraph(GetNodeGraphRequest) returns (GetNodeGraphResponse);

message NodeGraphNode { string id = 1; string type = 2; string status = 3; }
message NodeGraphEdge { string from_id = 1; string to_id = 2; float weight = 3; }
message GetNodeGraphResponse { repeated NodeGraphNode nodes = 1; repeated NodeGraphEdge edges = 2; }
```

---

## Streaming vs Polling

| View | Recommended transport | Rationale |
|------|----------------------|-----------|
| Sankey (View 3) | `useFetch` 5 s polling | Activation data written per-trade; polling per cycle is sufficient |
| Node Graph (View 1) | `StreamEvents` (SSE) | Node execution events already emit via `OrchestratorService.StreamEvents` |
| Geometry (View 2) | `useFetch` 30 s polling | Geometry is expensive to compute; per-30-cycle refresh acceptable |

---

## File Inventory

### New files to create
| File | Purpose |
|------|---------|
| `internal/handler/victoria_activations.go` | Handler: reads activation_traces JSONL, serves `GetSignalActivations` |
| `web/dashboard/src/pages/SignalAttributionPage.tsx` | Sankey view (View 3) |
| `web/dashboard/src/pages/NodeGraphPage.tsx` | Node execution DAG (View 1) |
| `omega/nodes/victoria/geometry.py` | ORC/Fiedler/Fisher-Rao computation (View 2, deferred) |
| `internal/db/geometry.go` | Postgres geometry_snapshots queries (View 2, deferred) |

### Files to extend
| File | Change |
|------|--------|
| `proto/omega/v1/victoria.proto` | Add `SignalActivation`, `TradeActivations`, `GetSignalActivations` RPC |
| `proto/omega/v1/orchestrator.proto` | Add `NodeGraph`, `GetNodeGraph` RPC |
| `internal/handler/victoria.go` | Register `GetSignalActivations` handler |
| `internal/handler/orchestrator.go` | Register `GetNodeGraph` handler |
| `web/dashboard/src/App.tsx` | Add routes for new pages |
| `web/dashboard/src/components/Navigation.tsx` | Add nav links |
