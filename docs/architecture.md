# Project Omega — Architecture

Project Omega is a self-improving AI node orchestration framework. Nodes execute domain logic, observe their own performance, and iteratively improve themselves. A Go Connect-RPC API exposes live state to a React dashboard.

---

## 1. High-Level System Architecture

```mermaid
graph TD
    subgraph Python["Python Layer (omega-nodes)"]
        HB[Heartbeat Loop]
        NODES[Domain Nodes<br/>Ingest · Signals · Strategy · Risk · Report]
        VERIFY[Verification Nodes<br/>Property · Invariant · Convergence]
        INFRA[Infrastructure<br/>StateStore · MemoryKernel · Tracer · Metrics · Analyzer]
        BRAIN[Brain Adapters<br/>Anthropic · OpenAI · Ollama · NoBrain]
    end

    subgraph Storage["Shared SQLite Storage"]
        SDB[(state.db<br/>nodes · traces · issues · costs · improvements)]
        MDB[(memory.db<br/>episodic · semantic · working)]
    end

    subgraph Go["Go Layer (omega-api :8080)"]
        API[Connect-RPC Server]
        HANDLER[OrchestratorService Handler]
        DBG[DB Reader]
    end

    subgraph UI["React Dashboard (:5173)"]
        DASH[Vite + Connect-ES<br/>Nodes · Traces · Memory · Metrics · Issues]
    end

    HB --> NODES
    HB --> VERIFY
    NODES --> INFRA
    VERIFY --> INFRA
    INFRA --> SDB
    INFRA --> MDB
    BRAIN --> NODES

    DBG --> SDB
    DBG --> MDB
    API --> HANDLER
    HANDLER --> DBG

    DASH -->|Connect-RPC| API
```

---

## 2. Heartbeat Loop Flow

Each heartbeat cycle runs the full pipeline in sequence, then evaluates health and triggers self-improvement if needed.

```mermaid
sequenceDiagram
    participant ORC as Orchestrator (Heartbeat)
    participant MEM as MemoryKernel
    participant TRC as Tracer
    participant ING as DataIngestionNode
    participant SIG as SignalGenerationNode
    participant STR as StrategyNode
    participant RSK as RiskManagementNode
    participant RPT as ReportingNode
    participant VER as Verification Suite
    participant SS  as StateStore

    ORC->>MEM: begin_cycle(N) — decay + consolidate
    ORC->>TRC: start_trace(op="heartbeat", cycle=N)

    ORC->>ING: execute(fetch_market_data)
    ING-->>ORC: OHLCV + Fear/Greed + DeFi TVL
    ORC->>TRC: end_span(ingestion)
    ORC->>SS:  record_cost(binance, coingecko)

    ORC->>SIG: execute(generate_signals)
    SIG-->>ORC: SMA/RSI/MACD/BB/BTC-beta
    ORC->>TRC: end_span(signals)

    ORC->>STR: execute(construct_portfolio)
    STR-->>ORC: portfolio weights + backtest
    ORC->>TRC: end_span(strategy)

    ORC->>RSK: execute(risk_check)
    RSK-->>ORC: VaR/CVaR/correlations
    ORC->>TRC: end_span(risk)

    ORC->>RPT: execute(generate_report)
    RPT-->>ORC: human-readable report

    ORC->>VER: execute verification suite
    VER-->>ORC: property tests + invariants + convergence

    ORC->>SS:  open_issue() for any failures
    ORC->>MEM: store_episode(cycle_summary)

    Note over ORC: Evaluate node health
    ORC->>ORC: health < threshold → node.improve()

    ORC->>TRC: end_span(root)
    ORC->>SS:  record_improvement() if improved

    Note over ORC: Sleep → next cycle
```

---

## 3. Subsystem Interaction Map

The five core subsystems interact in a feedback loop. Each arrow represents a data dependency or control signal.

```mermaid
graph LR
    subgraph Goals["Goal System"]
        GS[GoalSpec<br/>metrics + weights]
        EVAL[Evaluator<br/>score computation]
    end

    subgraph Alignment["Alignment"]
        HEALTH[Health Tracker<br/>per-node scores]
        IMPROVE[Improvement Engine<br/>node.improve()]
    end

    subgraph Adversarial["Adversarial"]
        RINGS[Challenge Rings<br/>veto / stress-test]
    end

    subgraph Memory["Memory"]
        EP[Episodic Memory<br/>cycle summaries]
        SEM[Semantic Memory<br/>learned patterns]
        WM[Working Memory<br/>intra-cycle context]
    end

    subgraph Observability["Observability"]
        SS2[StateStore<br/>SQLite]
        TRC2[Tracer<br/>spans to SQLite]
        MET[MetricsCollector<br/>rolling aggregates]
        ANA[SystemAnalyzer<br/>recommendations]
    end

    GS --> EVAL
    EVAL --> HEALTH
    HEALTH --> IMPROVE
    IMPROVE --> RINGS
    RINGS -->|veto/approve| IMPROVE

    IMPROVE --> EP
    EP --> SEM
    SEM --> IMPROVE

    HEALTH --> SS2
    TRC2 --> SS2
    MET --> SS2
    ANA --> MET
    ANA --> SS2

    WM -->|intra-cycle state| EVAL
```

---

## 4. Data Flow Diagram

External market data flows through the Python pipeline, is persisted to SQLite, and served to the browser via the Go API.

```mermaid
flowchart LR
    subgraph External["External APIs (no auth)"]
        BIN[Binance<br/>OHLCV klines]
        CGK[CoinGecko<br/>market caps]
        ALT[Alternative.me<br/>Fear and Greed]
        LFI[llama.fi<br/>DeFi TVL]
    end

    subgraph Providers["Data Providers (Python)"]
        DP[DataIngestionNode<br/>BinanceProvider<br/>CoinGeckoProvider]
    end

    subgraph Pipeline["Analysis Pipeline (Python)"]
        SIG2[SignalGenerationNode<br/>SMA/RSI/MACD/BB]
        STR2[StrategyNode<br/>Portfolio Construction]
        RSK2[RiskManagementNode<br/>VaR / CVaR]
        RPT2[ReportingNode]
    end

    subgraph DB2["SQLite Shared Volume"]
        SD2[(state.db)]
        MD2[(memory.db)]
    end

    subgraph GoAPI["Go API port 8080"]
        CONN[Connect-RPC<br/>OrchestratorService]
    end

    subgraph Browser["React Dashboard port 5173"]
        PAGES[Nodes · Traces · Memory<br/>Metrics · Issues · Convergence]
    end

    BIN --> DP
    CGK --> DP
    ALT --> DP
    LFI --> DP

    DP --> SIG2 --> STR2 --> RSK2 --> RPT2

    SIG2 --> SD2
    STR2 --> SD2
    RSK2 --> SD2
    RPT2 --> MD2

    SD2 --> CONN
    MD2 --> CONN

    CONN -->|Connect-RPC HTTP2| PAGES
```

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| SQLite shared volume | Zero network overhead; Python writes, Go reads; WAL mode enables concurrent readers |
| stdlib-only Python deps | No external packages needed — `sqlite3`, `urllib`, `dataclasses`, `logging` cover everything |
| Connect-RPC over REST | Type-safe, proto-defined API shared between Go server and TypeScript client via code generation |
| OpenTelemetry-inspired tracing | Spans persist to SQLite so the dashboard can render waterfalls without a separate trace backend |
| 12-factor JSON logging | Structured logs are machine-parseable; pipe to any log aggregator (Loki, CloudWatch, Datadog) |
| Config from env vars + optional YAML | Twelve-factor compliance; YAML for local dev, env vars for Docker / CI |
