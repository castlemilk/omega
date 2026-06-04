# Omega Multi-Agent Trading Intelligence Architecture

> **Status:** Living document — last updated April 2026
> **Scope:** Architecture design for Omega's multi-agent trading intelligence system
> **First project node:** Victoria (crypto quantitative trading)

---

## 1. Vision

Omega emulates a full trading house of quants, where each desk is an intelligent agent with its own reasoning (LLM) and memory layers. Rather than a monolithic strategy, the system decomposes the trading problem into specialized agents — alpha research, signal evaluation, risk management, execution, portfolio construction, and surveillance — each capable of independent reasoning, learning from its own history, and coordinating with peers through a shared attention mechanism.

Victoria (crypto quantitative trading) is the first project node demonstrating this architecture. It currently operates as a tightly integrated node (`omega/nodes/victoria/victoria_node.py`, 113 KB) composed of sub-nodes for data ingestion, signal generation, strategy, and risk management. The multi-agent architecture described here is the target state: decomposing Victoria's monolithic logic into cooperating agents, each backed by an LLM brain and a structured memory system.

The core thesis is that markets are too complex for any single model. A team of specialized agents — each with deep expertise in its domain, its own episodic memory of what worked and failed, and the ability to reason about novel situations — will outperform a monolithic system. The attention router (`internal/coordination/attention_router.go`) already implements the coordination layer; the next step is wiring LLM reasoning into each agent via the brain provider (`omega/core/brain.py`).

---

## 2. Agent Layers

Every agent in Omega follows the same three-method contract defined in `omega/core/node.py`:

```
execute(NodeInput) → NodeOutput    # Act on the world
evaluate() → dict[str, float]     # Self-assess performance
improve(feedback) → bool          # Apply improvements
```

The multi-agent architecture layers LLM reasoning and structured memory on top of this contract. Each agent has:

- **Reasoning:** An LLM adapter (`omega/core/brain.py`) that receives the agent's current state, relevant memories, and market context, then returns a structured decision with confidence scores.
- **Memory:** A three-tier memory system (`omega/core/memory.py`) with working memory (current cycle), episodic memory (timestamped events), and semantic memory (learned patterns).

### 2.1 Alpha Research Agent

**Role:** Discovers and evaluates new alpha sources — the agent responsible for answering "where is the edge?"

**Reasoning layer:** The LLM analyzes market narratives, research papers, on-chain data patterns, and funding rate regimes to propose new signal hypotheses. It receives the current signal universe and their recent performance via the `BrainRequest` context, and returns proposed signals with expected information coefficients.

**Memory layer:** A pattern library that stores market conditions and observed outcomes. Examples:

- "Negative funding + rising OI preceded 8% BTC rally in March 2024"
- "RSI divergence on 4h timeframe had 0.12 IC during trending regimes, decayed to 0.02 in ranging"
- "On-chain whale accumulation signal led price by 6-12 hours in Q4 2024"

These are stored as `SemanticMemory` records in `omega/core/memory.py`, with `confidence` scores that strengthen or decay based on subsequent observations.

**Current state in codebase:**

| Component | File | Description |
|---|---|---|
| Basic signals | `omega/nodes/victoria/signal_generation.py` | RSI, MACD, SMA, Bollinger Bands |
| Advanced signals | `omega/nodes/victoria/signals_advanced.py` | Order flow, cross-asset, microstructure |
| Funding/sentiment | `omega/nodes/victoria/news_signals.py` | Funding rate, OI, sentiment signals |
| On-chain signals | `omega/nodes/victoria/victoria_node.py` | `OnChainSignal`, `SmartMoneySignal`, `WhaleFlowSignal` |
| Options signals | `omega/nodes/victoria/options_signals.py` | Derivatives-based signals |
| FinBERT sentiment | `omega/nodes/victoria/finbert_sentiment.py` | BERT-based news sentiment |
| Signal performance | `omega/core/signal_performance.py` | IC tracking and signal health |

**Next milestones:**

1. Wire `AnthropicBrain` (claude-opus-4-6) to evaluate signal hypotheses against the pattern library
2. Automated research paper ingestion — LLM summarizes quantitative papers and extracts testable signal definitions
3. Sentiment analysis pipeline — LLM interprets crypto Twitter narratives and maps them to tradeable signals
4. Signal proposal protocol — Alpha agent publishes proposed signals to the shared bus; Signal Research agent evaluates them

### 2.2 Signal Research Agent (Meta-Harness)

**Role:** Evaluates which signals are working and which have decayed — the agent responsible for answering "what should we trust right now?"

**Reasoning layer:** The LLM analyzes `DecisionTraceAnalyzer` output (from `omega/core/analyzer.py`) and the Meta-Harness evaluation results, generates hypotheses about signal decay (e.g., "RSI mean-reversion signal decayed because we entered a trending regime"), and proposes reweighting or signal additions/removals.

**Memory layer:** Rolling signal performance scorecards per regime, information coefficient histories, and signal correlation matrices. The `DynamicWeightAllocator` in `omega/nodes/victoria/dynamic_weights.py` already maintains IC-based weights; the memory layer extends this with regime-tagged histories so the agent can recall that "during high-volatility regimes, funding rate signal IC was 0.18 while RSI IC dropped to 0.01."

**Current state in codebase:**

| Component | File | Description |
|---|---|---|
| Meta-Harness | `omega/core/meta_harness.py` | Propose → Evaluate → Store loop |
| ML combiner | `omega/nodes/victoria/dynamic_weights.py` | IC-based signal weighting |
| Decision analyzer | `omega/core/analyzer.py` | Trade decision attribution |
| Regime detector | `omega/nodes/victoria/regime_detector.py` | Market regime classification |
| HMM regime | `omega/nodes/victoria/hmm_regime.py` | Hidden Markov Model regime detection |
| Feedback descent | `omega/core/feedback_descent.py` | Gradient-free parameter optimization |
| Improvement engine | `omega/core/improvement_engine.py` | Node improvement scheduling |

The Meta-Harness (`MetaProposer` → `MetaEvaluator` → `StrategyFileSystem`) already implements the core loop. The composite score weights signal quality across five dimensions: Sharpe (0.30), drawdown (0.20), hit rate (0.20), profit factor (0.15), and long ratio (0.15).

**Next milestones:**

1. LLM generates natural-language explanations for weight shifts — "Reduced funding rate weight from 0.25 to 0.10 because IC dropped from 0.15 to 0.03 over the last 50 cycles during the current ranging regime"
2. Automated signal removal proposals — agent identifies signals with sustained negative IC and proposes deprecation
3. Cross-signal interaction analysis — LLM reasons about why certain signal combinations work (or interfere) in specific regimes

### 2.3 Risk Agent

**Role:** Portfolio-level risk management — the agent responsible for answering "what could go wrong and how do we protect against it?"

**Reasoning layer:** The LLM reasons about tail scenarios, correlation regime shifts, upcoming macro events (FOMC, CPI releases, ETF decisions), and their implications for current positions. It receives the current portfolio state, historical drawdown episodes from memory, and market context, then outputs risk adjustments (position size reductions, hedges, or full exits).

**Memory layer:** Every risk event the system has lived through — which risk metrics predicted drawdowns versus which were noise. Stored as episodic memories tagged by event type (liquidation cascade, exchange outage, regulatory announcement, etc.) with linked semantic memories capturing the learned lessons (e.g., "BTC-ETH correlation spikes to 0.95+ during liquidation cascades — reduce cross-asset exposure when funding rates diverge sharply").

**Current state in codebase:**

| Component | File | Description |
|---|---|---|
| Risk manager | `omega/core/risk_manager.py` | 5-layer risk system |
| Position risk | `omega/nodes/victoria/risk_management.py` | Position-level VaR, sizing |
| Circuit breaker | `omega/core/circuit_breaker.py` | Emergency halt mechanism |
| Adversarial risk | `omega/adversarial/risk_personas.py` | Adversarial risk scenarios |
| Safety alignment | `omega/core/alignment.py` | Constitutional constraints |

The current `PositionRiskManager` implements five layers: max drawdown protection (-8% halt), correlation-based limits (RMT-denoised, 0.75 threshold), volatility-scaled sizing, time-based risk reduction (50% during high-risk UTC windows), and portfolio heat caps (6 concurrent positions, 30% capital deployed).

**Next milestones:**

1. Dynamic VaR/CVaR computation using regime-aware covariance matrices
2. Correlation-aware position sizing — when BTC-ETH correlation exceeds 0.9, automatically reduce the combined allocation
3. Event-driven risk overlay — LLM reads macro calendar and pre-positions risk limits before FOMC, CPI, and other events
4. Tail scenario simulation — agent proposes "what if" scenarios and stress-tests the portfolio

### 2.4 Execution Agent

**Role:** Optimal trade execution — the agent responsible for answering "how do we get the best fill?"

**Reasoning layer:** The LLM analyzes order book conditions (depth, spread, recent trades), recent fill quality metrics, and slippage patterns to determine optimal execution strategy for each trade. It considers whether to use market orders, limit orders, or algorithmic execution (TWAP/VWAP), and the optimal order size to minimize market impact.

**Memory layer:** Per-venue, per-symbol execution quality history — average slippage by order size bucket, optimal execution times, fill rate by order type. This builds over time into a practical knowledge base like "BTCUSDT market orders on Binance Futures have 0.02% average slippage for orders under $50K, but slippage jumps to 0.08% above $100K."

**Current state in codebase:**

| Component | File | Description |
|---|---|---|
| Paper trading | `omega/core/paper_trading.py` | Simulated execution engine |
| Strategy execution | `omega/nodes/victoria/strategy.py` | Trade construction and submission |
| Data providers | `omega/nodes/victoria/data_providers.py` | Exchange API integration |
| Overnight runner | `omega/core/overnight_runner.py` | Continuous execution loop |

Currently, execution uses simple market orders in paper trading mode. The `paper_trading.py` engine (38.9 KB) simulates fills with configurable slippage models.

**Next milestones:**

1. TWAP/VWAP simulation in paper trading — split large orders across time windows
2. Slippage modeling — build empirical slippage curves from paper trading fills
3. Adaptive order sizing — LLM recommends order sizes based on current book depth and historical slippage data
4. Multi-venue routing — when live, route orders to the venue with best expected execution quality

### 2.5 Portfolio Construction Agent

**Role:** Optimizes the portfolio as a whole — the agent responsible for answering "given our signals and risk budget, what should the portfolio look like?"

**Reasoning layer:** The LLM evaluates portfolio concentration, correlation exposure, regime suitability, and capital efficiency. It considers whether the current portfolio is appropriately diversified, whether positions are sized according to their conviction and correlation structure, and whether the regime calls for more aggressive or defensive positioning.

**Memory layer:** Historical correlation regimes and strategy rotation patterns. The agent remembers that "in Q1 2024 trending regime, momentum signals drove 80% of PnL while mean-reversion was flat" and uses this to adjust portfolio construction during similar regimes.

**Current state in codebase:**

| Component | File | Description |
|---|---|---|
| Strategy node | `omega/nodes/victoria/strategy.py` | Portfolio construction logic |
| Victoria node | `omega/nodes/victoria/victoria_node.py` | Position decisions, blacklists |
| Regime detector | `omega/nodes/victoria/regime_detector.py` | Regime classification |
| Goals system | `omega/core/goals.py` | HTN goal decomposition, balanced scorecard |
| Evaluator | `omega/core/evaluator.py` | Portfolio metric aggregation |

The current `StrategyNode` in `strategy.py` (71.8 KB) handles portfolio construction with conviction filtering, position sizing, and blacklist management. The `goals.py` system (31.9 KB) already defines hierarchical task networks for goal decomposition.

**Next milestones:**

1. Mean-variance optimization with regime-aware covariance estimation
2. Risk budgeting — allocate a total risk budget across positions based on signal conviction and correlation
3. Regime-conditional portfolio templates — pre-defined allocation templates for trending, ranging, and crisis regimes that the LLM can select and customize
4. Rebalancing optimization — LLM reasons about when to rebalance vs. hold, considering transaction costs

### 2.6 Surveillance Agent

**Role:** Monitors system health and behavior anomalies — the agent responsible for answering "is the system behaving as expected?"

**Reasoning layer:** The LLM detects when the system is behaving differently than expected — unusual signal patterns, execution anomalies, unexplained PnL, or degraded data quality. It generates alerts with natural-language explanations and recommended actions.

**Memory layer:** Baseline behavior profiles and known failure patterns. The agent builds a model of "normal" behavior and flags deviations. It remembers past incidents: "On 2024-03-15, CoinGecko API returned stale data for 4 hours, causing false signals — implemented staleness check after that."

**Current state in codebase:**

| Component | File | Description |
|---|---|---|
| Verification | `omega/nodes/victoria/verification.py` | Property/invariant testing |
| Observability | `internal/observability/` | Metrics, tracing, health |
| Circuit breaker | `omega/core/circuit_breaker.py` | Emergency halt |
| Data resilience | `omega/core/data_resilience.py` | Data fault tolerance |
| Startup validator | `omega/core/startup_validator.py` | Pre-flight checks |
| Heartbeat | `internal/heartbeat/` | Node health monitoring |
| Intelligence metrics | `omega/core/intelligence_metrics.py` | System intelligence tracking |
| Tracing | `omega/core/tracing.py` | Span/trace recording |

The `verification.py` module (40.7 KB) already implements property-based and invariant testing. The Go heartbeat system (`internal/heartbeat/`, `proto/omega/v1/heartbeat_service.proto`) monitors node health with `HEALTHY`, `DEGRADED`, `STALE`, and `DEAD` states. The `TrainingDiagnostics` message captures cycle-level health: regime, data freshness, active signals, sit-out decisions, blockers, and PnL.

**Next milestones:**

1. Automated anomaly detection — LLM establishes behavior baselines and flags statistical outliers
2. Signal decay monitoring — continuous IC tracking with LLM-generated decay explanations
3. A/B testing framework — agent proposes and manages controlled experiments for signal and strategy changes
4. Incident postmortem automation — after drawdown events, agent compiles a postmortem with root cause analysis

---

## 3. Omega Platform Integration

The agent layer builds on Omega's three-tier platform: a Go orchestration framework, a Python domain logic layer, and a React dashboard. Each agent is a node in this framework, inheriting the platform's coordination, memory, observability, and communication infrastructure.

### 3.1 Node Contract

Every agent implements the `Node` base class from `omega/core/node.py`:

```python
class Node(ABC):
    def get_state(self) -> NodeState           # Health, capabilities, metrics
    def get_capabilities(self) -> list[str]    # Declared actions
    def describe(self) -> str                  # Human-readable description
    def execute(self, input: NodeInput) -> NodeOutput   # Run action
    def evaluate(self) -> dict[str, float]     # Self-assess
    def improve(self, feedback: dict) -> bool  # Apply improvements
```

`NodeState` carries the node's identity (`node_id`, `name`, `version`), health score (0.0–1.0), declared capabilities, and current metrics. The Go orchestrator (`internal/core/orchestrator.go`) wraps each node as a `NodeExecutor` with per-node circuit breakers and Prometheus histograms (`omega_cycle_duration_seconds`).

### 3.2 Attention Router (Q × K × V, 32-dim)

The Go attention router (`internal/coordination/attention_router.go`) implements scaled dot-product attention to route goals to the most appropriate agents:

```
Query  = LinearGoalEncoder(goal_type ∈ ℝ⁵, context_metrics ∈ ℝ¹⁶)  →  ℝ³²
Key    = NodeProjector(state_tensor ∈ ℝ¹⁶, capabilities ∈ ℝ⁸, trust ∈ ℝ¹)  →  ℝ³²
Value  = NodeProjector(state_tensor ∈ ℝ¹⁶, trust ∈ ℝ¹)  →  ℝ³²

Attention(Q, K, V) = softmax(Q·Kᵀ / √32) · V
```

**Dimension budget:** `DimModel=32`, `DimGoalType=5` (one-hot goal type), `DimContextVec=16` (fixed-width market metrics), `DimStateTensor=16` (Victoria state tensor), `DimCapability=8` (one-hot capability encoding).

**Trust masking:** Nodes with `trust_score < 0.7` receive a `−10.0` pre-softmax penalty when considered for autonomous goals, effectively requiring human approval for low-trust agents.

The Python-side `AttentionRouter` in `omega/core/orchestrator_v2.py` implements a complementary learnable-weight attention mechanism that boosts signal weights on winning trades.

### 3.3 Memory System (3-Tier)

The memory system (`omega/core/memory.py`, 33.6 KB) mirrors human cognitive architecture:

**Working Memory** (`WorkingMemory`): Ephemeral key-value store for the current cycle. Holds the active context — current market state, pending signals, in-flight orders. Cleared each cycle.

**Episodic Memory** (`EpisodicStore`): Timestamped event records with importance scoring and temporal decay. Every significant event is recorded as an `Episode` with tags, importance (0.0–1.0), and the cycle number. Importance decays over time unless reinforced by subsequent events.

**Semantic Memory** (`SemanticStore`): Learned patterns extracted from episodic memory. The `Consolidator` runs every N cycles, identifying recurring patterns in episodic events and promoting them to `SemanticMemory` records with confidence scores and evidence counts. Example: after observing "negative funding → rally" three times, a semantic memory is created with `confidence=0.6` and `evidence_count=3`.

**Cross-node memory** (`omega/core/cross_node_memory.py`) enables agents to share learned patterns. The `MemoryBus` (`omega/core/memory_bus.py`) provides thread-safe signal broadcasting with 16-dim state tensors consumed by the Go attention router.

The enhanced memory system in `omega/core/memory_v2.py` (44.7 KB) adds richer consolidation and retrieval. Memory quality is tracked by `omega/core/memory_quality.py`.

Storage is backed by Postgres via psycopg3, with schema managed by the Go database layer (`internal/db/`).

### 3.4 Brain Provider

The brain provider (`omega/core/brain.py`, 31 KB) connects LLM reasoning to each agent through a pluggable adapter system:

```python
class BrainAdapter(ABC):
    def consult(self, request: BrainRequest) -> BrainResponse: ...

class BrainRequest:
    node_state: NodeState       # Agent's current state
    metrics: dict               # Performance metrics
    memories: list[Memory]      # Relevant memories from retrieval
    context: dict               # Market context, cycle info

class BrainResponse:
    action: str                 # Recommended action
    parameters: dict            # Action parameters
    reasoning: str              # Natural-language explanation
    confidence: float           # 0.0–1.0
```

**Model tiers:** Each agent can use QUICK (claude-haiku-4-5, gpt-4o-mini) for routine decisions or DEEP (claude-opus-4-6, gpt-4o) for complex reasoning. The `ModelTier` enum and per-provider defaults are defined in `brain.py`.

**Provider implementations:** `AnthropicBrain`, `OpenAIBrain`, `OllamaBrain`, `DeepSeekBrain`, plus `NoBrain` for pure rule-based fallback. The Go-side brain providers live in `internal/brain/` (including `openrouter.go` for OpenRouter.ai access).

**Fallback behavior:** If no brain is configured or the LLM call fails, agents fall back to rule-based logic — the system never stops trading because of an LLM outage.

### 3.5 Observability

Decision traces flow through OpenTelemetry instrumentation (`omega/core/tracing.py`). The Go observability layer (`internal/observability/`) provides Prometheus metrics, circuit breakers, and a health gate that blocks cycles when `CompositeHealth` drops below threshold.

The `metrics_exporter.py` (21.9 KB) publishes counters and histograms for system health monitoring. The `intelligence_metrics.py` module tracks system-level intelligence scores and per-node contributions.

### 3.6 Heartbeat Service

The heartbeat system (`internal/heartbeat/`, `proto/omega/v1/heartbeat_service.proto`) monitors agent health with structured diagnostics:

```protobuf
message Heartbeat {
    string node_id = 1;
    string node_type = 2;
    google.protobuf.Timestamp timestamp = 3;
    NodeHealth health = 4;        // HEALTHY, DEGRADED, STALE, DEAD
    map<string, double> metrics = 5;
    repeated string blockers = 6;
}
```

The Python heartbeat client (`omega/core/heartbeat_client.py`) publishes node health to the Go service, which aggregates and exposes it to the dashboard and orchestrator.

### 3.7 Communication (Proto/Connect-RPC)

Agent-to-agent and agent-to-platform communication uses Protocol Buffers with Connect-RPC, defined across 18 proto files in `proto/omega/v1/`:

| Service | Proto file | Purpose |
|---|---|---|
| `OrchestratorService` | `omega_service.proto` | Core orchestration |
| `NodeService` | `node_service.proto` | Node lifecycle & execution |
| `MemoryService` | `memory_service.proto` | Memory operations |
| `HeartbeatService` | `heartbeat_service.proto` | Health monitoring |
| `CoordinationService` | `coordination.proto` | Goal routing & attention |
| `AdversarialService` | `adversarial_service.proto` | Challenge & debate |
| `SafetyService` | `safety_service.proto` | Safety constraints |
| `AutonomyService` | `autonomy_service.proto` | Autonomy gates |
| `VictoriaService` | `victoria_service.proto` | Victoria-specific ops |
| `ImprovementService` | `improvement_service.proto` | Self-improvement |

Generated Go bindings live in `gen/`. The Python-Go bridge (`omega/bridge/`) exposes a pipeline server on port 9090 that the Go orchestrator calls via HTTP.

### 3.8 Adversarial Layer

The adversarial pressure system (`omega/core/adversarial_v2.py`, 30.8 KB) validates agent proposals before execution. Challenge rings stress-test trade proposals, and a veto mechanism allows the risk agent (or adversarial personas from `omega/adversarial/risk_personas.py`) to block dangerous trades. The alignment system (`omega/core/alignment.py`, 26 KB) enforces constitutional constraints.

---

## 4. Orchestration Cycle

The main execution loop (`omega/core/orchestrator_v2.py`, 86.7 KB) runs each cycle through seven stages:

```
┌─────────────────────────────────────────────────────────┐
│                    One Cycle                             │
│                                                         │
│  1. Reconcile    → Health-check nodes, activate goals   │
│  2. Data Poll    → All nodes poll for fresh data        │
│  3. Signals      → Signal nodes compute indicators      │
│  4. Strategy     → Strategy nodes propose trades        │
│  5. Adversarial  → Validate proposals, debate gate      │
│  6. Execute      → Execute clean, block flagged         │
│  7. Post-cycle   → Memory consolidation, improvement    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

In the multi-agent architecture, each stage involves the relevant agents reasoning about their domain and publishing decisions to the shared bus. The attention router determines which agents participate in each stage based on goal routing scores.

---

## 5. Technical Design

### 5.1 Agent Interface (Go)

The Go-side agent interface extends the existing `NodeExecutor` with reasoning and memory methods:

```go
// internal/core/orchestrator.go — current interface
type NodeExecutor interface {
    Execute(ctx context.Context, input *NodeInput) (*NodeOutput, error)
}

// Target agent interface (extends NodeExecutor)
type AgentNode interface {
    NodeExecutor
    Reason(ctx context.Context, state *AgentState, memories []*Memory) (*Decision, error)
    Remember(ctx context.Context, episode *Episode) error
    Act(ctx context.Context, decision *Decision) (*ActionResult, error)
}
```

`Reason()` sends the agent's state and relevant memories to the brain provider and receives a structured decision. `Remember()` stores an episode in the memory system. `Act()` translates a decision into concrete actions (order placement, risk adjustment, etc.).

### 5.2 Memory Schema (Protobuf)

The memory schema extends the existing `memory_service.proto`:

```protobuf
message AgentMemory {
    // Working memory — current cycle context
    map<string, google.protobuf.Value> working = 1;

    // Episodic memory — timestamped events with decay
    repeated Episode episodes = 2;

    // Semantic memory — learned patterns
    repeated SemanticRecord patterns = 3;
}

message Episode {
    string episode_id = 1;
    google.protobuf.Timestamp timestamp = 2;
    string event_type = 3;           // "trade_outcome", "risk_event", "signal_decay"
    google.protobuf.Struct content = 4;
    repeated string tags = 5;
    double importance = 6;           // 0.0–1.0, decays over time
    int64 cycle = 7;
}

message SemanticRecord {
    string memory_id = 1;
    string concept = 2;             // "negative_funding_rally_pattern"
    string content = 3;             // Natural-language description
    double confidence = 4;          // Strengthened or decayed by evidence
    int32 evidence_count = 5;
    repeated string tags = 6;
    google.protobuf.Timestamp last_accessed = 7;
}
```

This mirrors the Python-side `Episode` and `SemanticMemory` classes in `omega/core/memory.py`, enabling the Go orchestrator to query and route based on memory state.

### 5.3 Reasoning Protocol

When an agent needs to reason, it follows a structured protocol:

```
Agent                       Brain Provider                  Memory
  │                              │                            │
  │  1. Retrieve memories        │                            │
  │─────────────────────────────────────────────────────────>│
  │  (tag-based + keyword recall)│                            │
  │<─────────────────────────────────────────────────────────│
  │  relevant_memories           │                            │
  │                              │                            │
  │  2. Build BrainRequest       │                            │
  │  (state + metrics + memories + context)                   │
  │─────────────────────────────>│                            │
  │                              │  3. LLM inference          │
  │                              │  (structured output)       │
  │<─────────────────────────────│                            │
  │  BrainResponse               │                            │
  │  (action, params, reasoning, confidence)                  │
  │                              │                            │
  │  4. Store episode            │                            │
  │─────────────────────────────────────────────────────────>│
  │  (decision + outcome)        │                            │
```

The `Retriever` class in `omega/core/memory.py` handles tag-based and keyword-based recall. The brain provider returns structured JSON via the `BrainResponse` schema. Confidence scores below a configurable threshold trigger fallback to rule-based logic.

### 5.4 Coordination Protocol

Agents coordinate through a shared decision bus. Each agent publishes its decisions, and other agents can veto or modify them:

```
Alpha Agent ──publishes──> "BUY ETHUSDT, conviction=0.8"
                                │
Signal Agent ──confirms──> "ETH momentum IC=0.15, funding signal IC=0.12"
                                │
Risk Agent ──modifies───> "Reduce size to 0.5x — portfolio heat at 25%"
                                │
Portfolio Agent ──approves──> "Position fits within risk budget, no correlation conflict"
                                │
Execution Agent ──executes──> "TWAP over 5 minutes, expected slippage 0.03%"
                                │
Surveillance Agent ──monitors──> "Execution within normal parameters"
```

The `SharedSignalState` in `omega/core/memory_bus.py` provides the thread-safe broadcasting mechanism. Each node publishes signals and a 16-dim state tensor; peers read via `read_peers()`. The Go attention router consumes these tensors for routing decisions.

The adversarial layer (`omega/core/adversarial_v2.py`) enforces the veto mechanism: the risk agent or adversarial personas can block trades that fail stress tests. Blocked trades are logged as episodic memories for the proposing agent to learn from.

### 5.5 State Tensor Protocol

Each agent encodes its current state as a 16-dimensional tensor (`omega/core/state_tensor.py`), published to the signal bus alongside raw signals. The Go attention router consumes these tensors as node state inputs:

```
Victoria State Tensor (16 dims):
[market_volatility, trend_strength, momentum, mean_reversion,
 funding_rate, open_interest_change, volume_ratio, spread,
 portfolio_heat, drawdown, win_rate, sharpe_rolling,
 signal_agreement, regime_confidence, data_freshness, health]
```

This compact representation enables the attention router to make fast routing decisions without parsing full agent state.

---

## 6. Implementation Roadmap

### Phase 1: Mechanical Foundations (Current)

The system operates with rule-based logic across all agents. Signals are generated mechanically, risk rules are static thresholds, and execution uses simple market orders.

**Key deliverables completed:**

- Signal generation pipeline (basic + advanced signals)
- 5-layer risk management system
- Meta-Harness strategy optimization loop
- Paper trading engine with configurable slippage
- Go orchestrator with heartbeat monitoring
- Attention router (Q×K×V, 32-dim)
- 3-tier memory system (working, episodic, semantic)
- Proto/Connect-RPC service definitions (18 services)
- Adversarial pressure and debate gate
- Observability (OTel tracing, Prometheus metrics)
- React dashboard

### Phase 2: ML Learning Loop

The system learns from its own trading history. Signals are weighted by IC, strategies are evaluated by the Meta-Harness, and parameters are tuned by feedback descent.

**Key deliverables:**

- IC-based signal weighting via `DynamicWeightAllocator` — **done** (`omega/nodes/victoria/dynamic_weights.py`)
- Meta-Harness evaluation loop — **done** (`omega/core/meta_harness.py`)
- Feedback descent optimization — **done** (`omega/core/feedback_descent.py`)
- Performance attribution per signal and regime — **in progress**
- Regime-conditional strategy selection — **in progress** (`omega/nodes/victoria/regime_detector.py`)
- HMM-based regime detection — **done** (`omega/nodes/victoria/hmm_regime.py`)

### Phase 3: LLM Reasoning Integration

The brain provider is wired to each agent for hypothesis generation, explanation, and novel situation handling.

**Key deliverables:**

- Brain adapter wired to Alpha Research agent — hypothesis generation for new signals
- Brain adapter wired to Signal Research agent — natural-language explanations for weight changes
- Brain adapter wired to Risk agent — tail scenario reasoning, macro event interpretation
- Brain adapter wired to Surveillance agent — anomaly explanation and recommended actions
- Model tier routing — QUICK for routine decisions, DEEP for complex reasoning
- Fallback protocol — graceful degradation to rule-based when LLM unavailable

### Phase 4: Multi-Agent Coordination

Agents communicate and negotiate. The risk agent can veto the alpha agent's position. The portfolio construction agent coordinates sizing across agents.

**Key deliverables:**

- Decision bus — agents publish structured decisions to shared state
- Veto protocol — risk and adversarial agents can block or modify proposals
- Negotiation rounds — agents iterate on proposals (e.g., risk agent requests smaller size, alpha agent accepts or argues)
- Attention routing for agent selection — goal router determines which agents participate in each decision
- Cross-agent memory sharing — agents share relevant semantic memories

### Phase 5: Self-Improvement

Agents propose and test their own improvements autonomously, subject to safety constraints and human approval gates.

**Key deliverables:**

- Agent-proposed experiments — alpha agent proposes new signal, Meta-Harness evaluates it in sandbox
- Automated A/B testing — surveillance agent manages controlled rollouts
- Self-modifying parameters — agents adjust their own configuration within bounded ranges
- Improvement scheduling — `omega/core/improvement_scheduler.py` coordinates improvement cycles
- Autonomy gates — `omega/core/autonomy.py` enforces approval requirements based on trust scores
- Constitutional constraints — `omega/core/alignment.py` defines hard limits that self-improvement cannot violate

---

## 7. File Reference Index

Quick reference mapping architecture concepts to codebase locations:

### Platform Layer (Go)

| Concept | File |
|---|---|
| Orchestrator | `internal/core/orchestrator.go` |
| Attention router | `internal/coordination/attention_router.go` |
| RPC handlers | `internal/handler/orchestrator.go` (47.5 KB) |
| Node handler | `internal/handler/node_handler.go` |
| Victoria handler | `internal/handler/victoria.go` |
| Memory handler | `internal/handler/memory_handler.go` |
| Training handler | `internal/handler/training_handler.go` |
| Brain providers | `internal/brain/openrouter.go` |
| Heartbeat processing | `internal/heartbeat/` |
| Database layer | `internal/db/` |
| Observability | `internal/observability/` |
| Proto definitions | `proto/omega/v1/*.proto` (18 files) |
| Generated bindings | `gen/` |
| CLI entry point | `cmd/omega/` |
| API server | `cmd/omega-api/` |

### Domain Layer (Python)

| Concept | File |
|---|---|
| Node base class | `omega/core/node.py` |
| Brain provider | `omega/core/brain.py` |
| Memory system | `omega/core/memory.py` |
| Enhanced memory | `omega/core/memory_v2.py` |
| Memory bus | `omega/core/memory_bus.py` |
| Cross-node memory | `omega/core/cross_node_memory.py` |
| Memory consolidation | `omega/core/memory_consolidation.py` |
| Orchestrator v2 | `omega/core/orchestrator_v2.py` |
| Meta-Harness | `omega/core/meta_harness.py` |
| Risk manager | `omega/core/risk_manager.py` |
| State store | `omega/core/state_store.py` |
| State tensor | `omega/core/state_tensor.py` |
| Signal bus | `omega/core/signal_bus.py` |
| Signal performance | `omega/core/signal_performance.py` |
| Adversarial v2 | `omega/core/adversarial_v2.py` |
| Alignment | `omega/core/alignment.py` |
| Goals | `omega/core/goals.py` |
| Evaluator | `omega/core/evaluator.py` |
| Improvement engine | `omega/core/improvement_engine.py` |
| Improvement scheduler | `omega/core/improvement_scheduler.py` |
| Autonomy | `omega/core/autonomy.py` |
| Feedback descent | `omega/core/feedback_descent.py` |
| Actions enum | `omega/core/actions.py` |
| Paper trading | `omega/core/paper_trading.py` |
| Tracing | `omega/core/tracing.py` |
| Metrics exporter | `omega/core/metrics_exporter.py` |
| Circuit breaker | `omega/core/circuit_breaker.py` |
| Bridge server | `omega/bridge/pipeline_server.py` |

### Victoria Node (Python)

| Concept | File |
|---|---|
| Victoria node | `omega/nodes/victoria/victoria_node.py` (113.7 KB) |
| Signal generation | `omega/nodes/victoria/signal_generation.py` |
| Advanced signals | `omega/nodes/victoria/signals_advanced.py` |
| Strategy | `omega/nodes/victoria/strategy.py` (71.8 KB) |
| Risk management | `omega/nodes/victoria/risk_management.py` |
| Dynamic weights | `omega/nodes/victoria/dynamic_weights.py` |
| Regime detector | `omega/nodes/victoria/regime_detector.py` |
| HMM regime | `omega/nodes/victoria/hmm_regime.py` |
| News signals | `omega/nodes/victoria/news_signals.py` |
| FinBERT sentiment | `omega/nodes/victoria/finbert_sentiment.py` |
| Options signals | `omega/nodes/victoria/options_signals.py` |
| Whale flow | `omega/nodes/victoria/unusual_whales_node.py` |
| Verification | `omega/nodes/victoria/verification.py` |
| Data ingestion | `omega/nodes/victoria/data_ingestion.py` |
| Data providers | `omega/nodes/victoria/data_providers.py` |
| Data cleaners | `omega/nodes/victoria/cleaners.py` |
| Reporting | `omega/nodes/victoria/reporting.py` |

---

## 8. Design Principles

**Graceful degradation.** Every agent works without an LLM. The brain provider is an enhancement layer, not a dependency. If the LLM is unavailable, agents fall back to rule-based logic. This means the system never stops trading because of an API outage.

**Memory as competitive advantage.** The memory system is not just logging — it's the agents' accumulated experience. Semantic memories encode hard-won lessons that compound over time. A system that has traded through a liquidation cascade once will handle the next one better.

**Trust-gated autonomy.** Agents earn autonomy through demonstrated competence. The trust score in the attention router controls how much latitude each agent has. New agents or agents after a reset start with low trust and require human approval for significant decisions.

**Adversarial validation.** Every trade proposal passes through the adversarial layer before execution. Risk personas stress-test proposals, and the debate gate requires consensus. This prevents any single agent's error from becoming a realized loss.

**Observable reasoning.** Every agent decision is traced through OTel spans, with natural-language reasoning stored in episodic memory. When a trade goes wrong, the system can reconstruct exactly what each agent was thinking and why.

---

*This document describes the target architecture. The codebase is in active development — see the roadmap (Section 6) for current status. For platform-level architecture, see `docs/architecture.md`. For the coordination layer specification, see `docs/specs/COORDINATION_V2_ARCHITECTURE.md`.*
