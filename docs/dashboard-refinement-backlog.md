# Dashboard Refinement Backlog

Status as of 2026-03-23. P0 observability items and initial frontend cleanup are complete on master.

## UI Refinements (from visual review against frontend-design skill)

### R1: Dashboard Recent Activity grouping
The activity feed on Dashboard.tsx shows every individual issue as a separate row (e.g. 5 separate "dashboard_api__api_*" entries at the same timestamp). Group identical events by timestamp+action, showing "Issue opened × 5 · dashboard_api (convergence, traces, metrics, nodes, health)" as a single row.

### R2: Issues page — group by detector+field-prefix
LintNode errors for `_defi_tvl` missing fields (volume, close, low, high, open, timestamps) appear as 6 separate rows. Same for `_fear_greed`. Group these under a collapsible parent like "LintNode: _defi_tvl missing 6 required fields" with expand to see details.

### R3: Pipeline stepper label overflow
"ImprovementEngine" and "Ring3Adversarial" still get clipped in the pipeline stepper cards. Consider using `text-xs` or abbreviating only when necessary with a tooltip for full name.

### R4: Traces list — add timestamp and status
The traces list only shows trace ID, span count, duration, and cycle number. Add a timestamp column and color-code by status (success/error).

### R5: Empty states for pages with no data
Several pages (Memory, Convergence, Alignment, Goals, Challenges, Improvements) likely show empty or placeholder content. Add proper empty state messaging with guidance.

### R6: Metrics page — verify real data rendering
Metrics.tsx is 13KB — verify it renders real Prometheus/OTel metrics and not just placeholder charts.

## P1 Observability (from observability-roadmap.md)

### P1-1: Node execution history in detail view
Clicking a node in Nodes.tsx should show recent execution history — timestamps, durations, success/fail counts, error messages. Currently the node table has no drill-down.

### P1-2: Trace filtering by node
Traces page needs a filter/dropdown to show traces for a specific node. Currently shows all traces with no filtering capability.

### P1-3: Safety and adversarial event persistence
Safety gate decisions and adversarial challenge results need to be persisted to the state store and surfaced in the Adversarial page. Currently these events may be fire-and-forget.

### P1-4: Prometheus scrape endpoint
Add a /metrics endpoint to the Go API server exposing key counters (cycles_total, node_executions_total, errors_total, latency histograms) in Prometheus format. Wire into docker-compose for scraping.

### P1-5: Cycle summary page
Add a dedicated cycle detail page showing: which nodes ran, per-node duration breakdown, issues detected during the cycle, signals generated, and a mini trace waterfall.

## P2+ (deferred — from roadmap)

- P2-1: Log aggregation (Loki or similar)
- P2-2: Cycle replay from trace data
- P2-3: Span detail overlay in trace waterfall
- P2-4: Cross-cycle metric comparison
- P2-5: Trace context propagation in slog
- P3-1: SLO dashboard
- P3-2: Alerting rules
- P3-3: Anomaly detection on metrics
- P3-4: Live/backtest reconciliation view
