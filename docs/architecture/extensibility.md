# Omega Platform Extensibility Guide

This guide explains how to add new projects and node types to Omega without
modifying platform code. All configuration is declarative YAML; the Go registry
is the canonical source of truth, and Python nodes are clients of that registry.

---

## Table of Contents

1. [Create a new project in 5 steps](#1-create-a-new-project-in-5-steps)
2. [Node type reference](#2-node-type-reference)
3. [Connection protocol](#3-connection-protocol)
4. [Attention router](#4-attention-router)
5. [Memory bus — cross-project intelligence](#5-memory-bus--cross-project-intelligence)
6. [Example: sentiment-only trading in 20 lines of YAML](#6-example-sentiment-only-trading-in-20-lines-of-yaml)
7. [Go registry as canonical source; Python as client](#7-go-registry-as-canonical-source-python-as-client)

---

## 1. Create a new project in 5 steps

### Step 1 — Write a project YAML

Create `projects/<your_project>.yaml`. The minimum viable project:

```yaml
name: my_project
description: What this project does

nodes:
  - type: data_provider
    name: feed
    config:
      provider: binance
      tickers: [BTCUSDT]

  - type: signal_generator
    name: signals
    inputs: [feed.market_data]
    config:
      signals: [basic]

  - type: executor
    name: paper_trader
    inputs: [signals.signal_value]
    config:
      mode: paper

routing:
  type: dag
  config: {}
```

### Step 2 — Register with the platform

Run the project once to register it in the node registry:

```bash
omega run --project projects/my_project.yaml
```

The orchestrator reads the YAML, instantiates each node type from the Go
registry, and wires the DAG. No code changes required for standard node types.

### Step 3 — Connect to the dashboard

Projects appear automatically in the React dashboard after first run. Navigate
to the **Projects** page; your project is listed with live health indicators.

### Step 4 — Configure evaluation

Add `eval_config` to your YAML to tell `omega eval` which metrics matter:

```yaml
eval_config:
  primary_metrics: [sharpe_ratio, win_rate]
  metric_targets:
    sharpe_ratio: 1.5
    win_rate: 0.45
  eval_frequency: per_cycle
```

### Step 5 — Enable self-improvement

Add `improvement_config` to activate Bayesian hyperparameter search and
adversarial stress-testing between cycles:

```yaml
improvement_config:
  tpe_enabled: true
  tpe_trials: 50
  adversarial_enabled: true
  adversarial_rounds: 3
  walk_forward_enabled: true
```

The TPE optimiser will tune any numeric config values you mark with `~tunable`
in the YAML. Results persist to `data/router_weights.json`.

---

## 2. Node type reference

Each node type corresponds to a Python base class in `omega/core/node.py` and a
Go capability registered in `internal/registry/`. The platform wires them using
the `inputs:` references in your YAML.

### `data_provider`

Fetches external data and emits structured frames into the pipeline.

**Config keys:**
| Key | Type | Description |
|-----|------|-------------|
| `provider` | string | One of: `binance`, `bybit`, `coingecko`, `coinbase`, `kraken`, `cryptocompare` |
| `tickers` | list[string] | Market symbols (e.g. `BTCUSDT`) |
| `feed_type` | string | `ohlcv` (default), `l2_depth`, `aggTrades`, `funding_rate` |
| `depth_levels` | int | L2 book depth (only when `feed_type: l2_depth`) |
| `snapshot_interval_ms` | int | Polling cadence in milliseconds |

**Outputs:** `market_data`, `order_book`, `trades` (depending on feed_type)

**Capability:** `data_ingestion`

**Fallback chain:** Binance → Bybit → CoinGecko → Coinbase → Kraken → CryptoCompare.
The platform retries on 4xx/5xx with exponential backoff; US-blocked exchanges
(Binance/Bybit return 451/403) are skipped transparently.

---

### `signal_generator`

Transforms raw market data into scored, directional signals.

**Config keys:**
| Key | Type | Description |
|-----|------|-------------|
| `signals` | list[string] | Signal families to activate (see below) |
| `min_confidence` | float | Signals below this score are dropped (default 0.0) |

**Signal families:**
| Family | Indicators |
|--------|-----------|
| `basic` | RSI, MACD, Bollinger Bands, Z-score, BTC-beta, volume delta |
| `spectral` | Spectral-graph adjacency, Riemannian curvature |
| `smart_money` | Whale flow, order-block detection |
| `sentiment` | FinBERT news NLP, Twitter sentiment |
| `vrp` | Variance Risk Premium (implied vs realised vol) |
| `spread` | Mid-price, quoted/effective spread, book imbalance |
| `inventory_risk` | A-S inventory penalty (−γqσ²) |
| `adverse_selection` | Lee-Ready trade direction + toxicity score |

**Outputs:** `signal_value`, `confidence`, `direction`

**Capability:** `signal_generation`

---

### `regime_detector`

Classifies the current market regime to gate signal weighting.

**Config keys:**
| Key | Type | Description |
|-----|------|-------------|
| `algorithm` | string | `wasserstein` (default), `hmm`, `pca` |

**Outputs:** `regime` (string label: `bull`, `bear`, `ranging`, `volatile`)

---

### `strategy`

Combines signals and regime into a trade decision with position weights.

**Config keys:**
| Key | Type | Description |
|-----|------|-------------|
| `min_conviction` | float | Minimum weighted signal score to open a position |
| `max_positions` | int | Maximum simultaneous open positions |

**Outputs:** `trade_decision`, `position_weights`

**Capability:** `portfolio_optimization`

---

### `risk_manager`

Enforces position limits, drawdown constraints, and sizing rules.

**Config keys:**
| Key | Type | Description |
|-----|------|-------------|
| `max_drawdown` | float | Maximum drawdown as a negative fraction (e.g. `-0.15`) |
| `max_position_pct` | float | Max allocation per position as fraction of NAV |
| `kelly_fraction` | float | Kelly criterion scaling factor (e.g. `0.25` = quarter-Kelly) |

**Outputs:** `approved_decision`

**Capability:** `risk_assessment`

---

### `executor`

Sends approved orders to an exchange or simulates fills in paper mode.

**Config keys:**
| Key | Type | Description |
|-----|------|-------------|
| `mode` | string | `paper` or `live` |
| `fill_model` | string | `probabilistic`, `queue_position`, `instant` (paper only) |
| `max_positions` | int | Hard limit enforced at execution time |

**Outputs:** `fill_events`, `pnl`

**Capability:** `execution`

---

### `intelligence`

Runs a brain adapter (LLM or classical optimizer) over node outputs to tune
parameters or generate insights.

**Config keys:**
| Key | Type | Description |
|-----|------|-------------|
| `optimize_params` | list[string] | Config keys to tune via TPE |
| `tpe_trials` | int | Bayesian optimisation trial budget |
| `target_metric` | string | Metric to maximise |
| `optimize_frequency` | string | `per_session`, `per_cycle`, `manual` |

**Capability:** `forecasting`

---

## 3. Connection protocol

Nodes communicate using protobuf messages over the Go↔Python bridge. All
schemas live in `proto/omega/v1/`.

### Key proto files

| File | Purpose |
|------|---------|
| `proto/omega/v1/pipeline_service.proto` | `RunCycle`, `StepResult`, cycle orchestration |
| `proto/omega/v1/node_service.proto` | `NodeStatus`, capability declarations |
| `proto/omega/v1/state_service.proto` | `StateTensor` — per-node 16-dim float vector |
| `proto/omega/v1/memory_service.proto` | `StoreEpisode`, `QuerySemantic` |
| `proto/omega/v1/coordination.proto` | `GoalSpec`, `RoutingPlan` — attention routing wire types |
| `proto/omega/v1/types.proto` | Shared enums: `GoalType`, `CapabilityType` |

### StateTensor

Every node emits a `StateTensor` each cycle — a 16-dimensional float32 vector
that summarises node health and recent performance. The attention router uses
these tensors to compute node keys and values.

```protobuf
// proto/omega/v1/state_tensor.proto
message StateTensor {
  bytes values = 1;          // little-endian float32[16]
  repeated string dim_names = 2;  // human-readable dimension labels
  int64 timestamp_ms = 3;
  string node_id = 4;
}
```

Reserved dimensions (by convention):

| Index | Name | Description |
|-------|------|-------------|
| 0 | `accuracy` | Rolling prediction accuracy [0,1] |
| 1 | `latency_ms` | p50 cycle latency |
| 2 | `error_rate` | Fraction of cycles with errors |
| 3 | `trust_score` | Platform trust score [0,1] (affects autonomy gating) |
| 4–7 | domain-specific | e.g. `sharpe`, `fill_rate`, `inventory_usd`, `toxicity` |
| 8–15 | free | Project-defined metrics |

### Transport

The bridge uses Connect-RPC (HTTP/2 + protobuf) over `localhost:9090`.

```
Go orchestrator (port 8080)
  │
  │  Connect-RPC (internal/bridge/pipeline_client.go)
  ▼
Python pipeline server (port 9090 — omega/bridge/pipeline_server.py)
  │
  │  Python node graph (omega/core/orchestrator.py)
  ▼
Individual nodes (omega/nodes/*)
```

W3C `traceparent` headers propagate across the bridge so spans from Go and
Python appear as a single trace in Grafana Tempo.

---

## 4. Attention router

The attention router decides which node handles a given `GoalSpec`. It uses
scaled dot-product attention — the same mechanism as a transformer attention
head — over the current node state tensors.

### Algorithm

```
Attention(Q, K, V) = softmax(Q·Kᵀ / √d_k) · V

Q  = LinearGoalEncoder.Encode(goal)          → ℝ³²
K  = NodeProjector.Key(tensor, capabilities) → ℝ^{N×32}
V  = NodeProjector.Value(tensor)             → ℝ^{N×32}
```

**Step by step:**

1. **Goal encoding** — The `GoalSpec` is projected into a 32-dim query vector.
   The encoder is a linear layer over a one-hot goal type (5 classes) and a
   16-dim context metric vector.

2. **Node key/value projection** — Each node's `StateTensor` + capability
   one-hot + trust scalar is projected to a 32-dim key and value.

3. **Scoring** — Dot products `Q·Kᵢ / √32` give raw compatibility scores.

4. **Trust masking** — Nodes with `trust_score < 0.7` receive a `−10.0`
   pre-softmax penalty when the goal requires autonomy. This effectively
   blocks untrusted nodes without a hard capability check.

5. **EMA prior** — An exponential moving average of historical routing
   outcomes adds a small additive bias to each score, nudging the router
   toward nodes that have historically performed well for similar goals.

6. **Softmax** — Normalised attention weights `α` over all nodes.

7. **Primary selection** — `argmax(α)` is the selected node. `max(α) < 0.6`
   signals low confidence — the orchestrator logs a warning and may fall back
   to a default node.

### Extending the router

To expose a new capability to the router, add it to `AllCapabilities` in
`internal/coordination/attention_router.go`. The capability one-hot expands
automatically. Then declare the capability in your node YAML:

```yaml
- type: signal_generator
  name: my_signal
  config:
    capabilities: [signal_generation, anomaly_detection]
```

---

## 5. Memory bus — cross-project intelligence

The memory bus allows nodes in different projects to share learned patterns
without tight coupling. It is the mechanism by which, for example, Victoria's
regime detector can inform Polymarket's bet-sizing strategy.

### Architecture

```
Project: victoria                 Project: polymarket
  ├── regime_detector               ├── market_selector
  │     writes →                    │     reads ←
  │                                  │
  └──────── omega/core/memory_bus.py ──────────────────
                  │
                  │  Shared namespace: "platform"
                  ▼
            data/omega_victoria_memory.db (SQLite WAL)
```

### Namespaces

| Namespace | Scope | Example keys |
|-----------|-------|-------------|
| `node:<node_id>` | Private to that node | `victoria.signals.last_sharpe` |
| `project:<project>` | Shared within project | `victoria.regime.current` |
| `platform` | Shared across all projects | `platform.btc.regime`, `platform.risk.alert` |

### Writing to the bus (Python)

```python
from omega.core.memory_bus import MemoryBus

bus = MemoryBus()

# Write a cross-project fact
bus.write(
    namespace="platform",
    key="btc.regime",
    value={"regime": "bull", "confidence": 0.82},
    ttl_seconds=300,    # evict after 5 minutes
)
```

### Reading from the bus (Python)

```python
result = bus.read(namespace="platform", key="btc.regime")
if result:
    regime = result["value"]["regime"]
```

### Memory tiers

Each node has access to three memory tiers via `omega/core/memory.py`:

| Tier | Class | Scope | Persistence |
|------|-------|-------|-------------|
| Working | `WorkingMemory` | Intra-cycle dict (TTL) | In-process only |
| Episodic | `EpisodicMemory` | Per-cycle observations | SQLite, indefinite |
| Semantic | `SemanticMemory` | Distilled learned facts | SQLite, updated by consolidation pass |

The **consolidation pass** (`omega/core/memory_consolidation.py`) runs
asynchronously, distilling recent episodic entries into semantic facts. This is
how long-term patterns (e.g. "ETHUSDT tends to lead BTC in bull regimes") are
extracted from raw history.

---

## 6. Example: sentiment-only trading in 20 lines of YAML

This complete project runs a sentiment signal from FinBERT + Twitter against
BTC, sizes positions with Kelly criterion, and paper-trades the result.

```yaml
name: sentiment_trader
description: Sentiment-only trading strategy using FinBERT + Twitter signals

nodes:
  - type: data_provider
    name: feed
    config:
      provider: binance
      tickers: [BTCUSDT, ETHUSDT]

  - type: signal_generator
    name: sentiment
    inputs: [feed.market_data]
    config:
      signals: [sentiment]

  - type: strategy
    name: conviction
    inputs: [sentiment.signal_value, sentiment.confidence]
    config:
      min_conviction: 0.65
      max_positions: 2

  - type: risk_manager
    name: risk
    inputs: [conviction.trade_decision, conviction.position_weights]
    config:
      max_drawdown: -0.10
      kelly_fraction: 0.25

  - type: executor
    name: paper
    inputs: [risk.approved_decision]
    config:
      mode: paper

routing:
  type: dag
  config: {}

eval_config:
  primary_metrics: [sharpe_ratio, win_rate]
  metric_targets:
    sharpe_ratio: 1.2
  eval_frequency: per_cycle
```

Run with:

```bash
omega run --project projects/sentiment_trader.yaml
```

The platform resolves the DAG, starts the data feed, generates sentiment
signals each cycle, and paper-trades approved decisions. Results appear in the
dashboard under the `sentiment_trader` project.

---

## 7. Go registry as canonical source; Python as client

The platform separates **registration** (Go) from **implementation** (Python).
This keeps the Go layer as the authoritative source of node type metadata while
allowing arbitrary Python logic in node bodies.

### Go registry (canonical)

`internal/registry/node_registry.go` — maps node type strings to capability
declarations and routing metadata.

```go
registry.Register(NodeTypeSpec{
    Type:         "signal_generator",
    Capabilities: []string{"signal_generation"},
    // StateTensor dimension names for this type
    TensorDims: []string{
        "accuracy", "latency_ms", "error_rate", "trust_score",
        "signal_strength", "regime_confidence",
    },
})
```

When `omega run` starts, the Go orchestrator reads the project YAML and
validates each node type against the registry. Unknown types fail fast with a
descriptive error before any Python process starts.

### Python nodes (client)

Python nodes extend `omega/core/node.py:BaseNode`. The node type string in YAML
is resolved to a Python class by `omega/core/node_registry.py`.

```python
# omega/core/node_registry.py
NODE_TYPES = {
    "data_provider":    DataProviderNode,
    "signal_generator": SignalGeneratorNode,
    "regime_detector":  RegimeDetectorNode,
    "strategy":         StrategyNode,
    "risk_manager":     RiskManagerNode,
    "executor":         ExecutorNode,
    "intelligence":     IntelligenceNode,
}
```

To register a **custom node type**:

1. Create `omega/nodes/my_domain/my_node.py` extending `BaseNode`.
2. Implement `execute(ctx) → NodeResult` and declare `CAPABILITIES`.
3. Add the entry to `NODE_TYPES` in `omega/core/node_registry.py`.
4. Register the Go metadata in `internal/registry/node_registry.go`.
5. Use the new type in project YAML.

### Proto as the contract

Neither Go nor Python owns the data contract — protobuf does. The schemas in
`proto/omega/v1/` are the single source of truth for all message types crossing
the bridge. When you add a new signal output field:

```bash
# Edit the relevant .proto file, then regenerate:
buf generate
```

This regenerates both `gen/go/omega/v1/` and `gen/python/omega/v1.py`
simultaneously, keeping Go and Python in sync.

---

## Summary

| Concept | Where it lives |
|---------|----------------|
| Project config | `projects/*.yaml` |
| Node type registry | `internal/registry/node_registry.go` (Go), `omega/core/node_registry.py` (Python) |
| Message schemas | `proto/omega/v1/*.proto` |
| Attention router | `internal/coordination/attention_router.go` |
| Memory bus | `omega/core/memory_bus.py` |
| Signal implementations | `omega/nodes/victoria/` |
| Bridge transport | `internal/bridge/pipeline_client.go` ↔ `omega/bridge/pipeline_server.py` |
