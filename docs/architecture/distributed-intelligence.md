# Omega Distributed Cluster Intelligence Architecture

**Version:** 0.1.0-draft
**Date:** 2026-03-26
**Author:** Architecture Review
**Status:** Proposal

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current State Architecture](#current-state-architecture)
3. [Target State Architecture](#target-state-architecture)
4. [Node Autonomy](#1-node-autonomy)
5. [Distributed Memory Architecture](#2-distributed-memory-architecture)
6. [Communication Protocols](#3-communication-protocols)
7. [Distributed Attention Router](#4-distributed-attention-router)
8. [Context Windows per Node](#5-context-windows-per-node)
9. [Cluster Topology](#6-cluster-topology)
10. [Framework Evaluation](#7-framework-evaluation)
11. [Specific Changes to Omega Core](#8-specific-changes-to-omega-core)
12. [Trading-Specific Distributed Patterns](#9-trading-specific-distributed-patterns)
13. [Migration Path](#10-migration-path)
14. [Risk Assessment](#11-risk-assessment)

---

## Executive Summary

Omega currently operates as a single-machine orchestrator: a Go process drives Python nodes sequentially through a pipeline, memory is centralized in PostgreSQL, and the attention router runs in-process. This architecture works for a single project with 9 pipeline steps, but it cannot scale to multiple machines, tolerate node failures, or exploit parallelism across independent signal sources.

This document proposes evolving Omega into a **distributed cluster intelligence** system where each node is a self-contained agent with its own memory, context, and reasoning capability. The evolution is designed as a series of incremental migrations that preserve the current working system while unlocking distributed operation over 3-6 months.

The core insight driving this design: **Omega's existing abstractions (node registry, capability-based routing, attention-weighted scheduling, triple-tier memory) already model a distributed system conceptually. The work is to make the deployment reality match the conceptual model.**

### Key Design Decisions

- **Hierarchical hybrid topology** with project-level coordinators under a platform supervisor
- **NATS** for inter-node messaging (sub-millisecond latency, Go-native)
- **Hybrid Logical Clocks** for distributed event ordering (constant space, physical-time aligned)
- **Three-tier memory hierarchy**: L1 node-local, L2 project-shared (Redis), L3 platform-global (Postgres)
- **Raft consensus** only for critical shared state (risk parameters, position aggregates)
- **Temporal** for durable workflow orchestration of multi-step pipelines
- **Gossip protocol** (hashicorp/memberlist) for node discovery and health propagation

---

## Current State Architecture

### System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Single Machine                            │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Go Server (Port 8080)                    │   │
│  │                                                       │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │   │
│  │  │ Orchestrator │  │ Attention    │  │ Node       │  │   │
│  │  │ (runCycle)   │──│ Router       │  │ Registry   │  │   │
│  │  │              │  │ (32-dim QKV) │  │ (in-memory)│  │   │
│  │  └──────┬───────┘  └──────────────┘  └────────────┘  │   │
│  │         │                                              │   │
│  │         │ Connect-RPC + W3C Traceparent                │   │
│  │         ▼                                              │   │
│  │  ┌──────────────────────────────────────────────────┐  │   │
│  │  │         Python Pipeline Server (Port 9090)        │  │   │
│  │  │                                                    │  │   │
│  │  │  step_1 → step_2 → step_3 → ... → step_9         │  │   │
│  │  │  DataIng  SigRes   PortOpt       Ring3Adv         │  │   │
│  │  │                                                    │  │   │
│  │  │  ┌──────────────┐  ┌──────────┐                   │  │   │
│  │  │  │ BrainAdapter │  │ Memory   │                   │  │   │
│  │  │  │ (centralized)│  │ Kernel   │                   │  │   │
│  │  │  └──────────────┘  └────┬─────┘                   │  │   │
│  │  └──────────────────────────┼────────────────────────┘  │   │
│  └──────────────────────────────┼────────────────────────┘   │
│                                  │                            │
│  ┌───────────────────────────────▼──────────────────────┐   │
│  │              PostgreSQL (Single Instance)              │   │
│  │                                                        │   │
│  │  episodes │ semantic_memories │ nodes │ node_executions│   │
│  │  traces   │ improvement_log   │ issues│ brain_exec_log │   │
│  └────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### What Works Well (Preserve These)

1. **Connect-RPC bridge** with W3C traceparent injection across Go/Python boundary
2. **Attention router** with learnable QKV projections, trust masking, and EMA priors
3. **Triple-tier memory** (working -> episodic -> semantic with consolidation)
4. **Capability-based node registration** with health tracking
5. **StateTensor abstraction** for node state representation
6. **Circuit breaker per node** with error classification
7. **Postgres LISTEN/NOTIFY** channels already provide primitive pub/sub

### What Limits Scaling

1. **Sequential pipeline execution**: step_1 must finish before step_2 starts. Independent signals cannot run in parallel.
2. **Single-machine memory**: all nodes share one MemoryKernel instance. No local caching, no partial replication.
3. **Synchronous orchestration**: `runCycle` blocks on each `ExecuteStep` call. A slow node blocks the entire pipeline.
4. **Centralized brain**: all LLM calls route through one BrainAdapter. No node-local reasoning.
5. **No failure isolation**: a panicking node is caught by `defer recover()`, but the cycle still runs serially.
6. **No horizontal scaling**: adding a second machine requires manually running a separate process and coordinating state externally.

### Key Metrics (Current)

| Metric | Current | Target |
|--------|---------|--------|
| Nodes per machine | 9 (sequential) | 10-50 (distributed) |
| Cycle latency | Sum of all steps | Max of parallel paths |
| Memory access | ~1ms (local Postgres) | L1: <0.1ms, L2: <5ms, L3: <20ms |
| Failure blast radius | Entire pipeline | Single node |
| Brain calls | Centralized, queued | Node-local, parallel |
| Node communication | Synchronous RPC | Async pub/sub |

---

## Target State Architecture

### System Diagram (3-6 Month Vision)

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Omega Cluster                                  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                   Platform Coordinator                          │  │
│  │  ┌───────────┐  ┌──────────────┐  ┌─────────────────────────┐ │  │
│  │  │ Raft      │  │ Global       │  │ Distributed Attention   │ │  │
│  │  │ Consensus │  │ Risk Mgr     │  │ Router (federated)      │ │  │
│  │  │ (etcd)    │  │ (veto power) │  │                         │ │  │
│  │  └───────────┘  └──────────────┘  └─────────────────────────┘ │  │
│  │  ┌───────────┐  ┌──────────────┐                               │  │
│  │  │ Memberlist│  │ Temporal     │                               │  │
│  │  │ (gossip)  │  │ Server       │                               │  │
│  │  └───────────┘  └──────────────┘                               │  │
│  └──────────────────────────┬─────────────────────────────────────┘  │
│                              │ NATS                                    │
│         ┌────────────────────┼────────────────────┐                   │
│         │                    │                    │                    │
│  ┌──────▼──────┐     ┌──────▼──────┐     ┌──────▼──────┐            │
│  │ Project     │     │ Project     │     │ Shared       │            │
│  │ Coordinator │     │ Coordinator │     │ Services     │            │
│  │ (Victoria)  │     │ (Polymarket)│     │              │            │
│  │             │     │             │     │ Memory       │            │
│  │ ┌─────────┐│     │ ┌─────────┐ │     │ Consolidator │            │
│  │ │Local    ││     │ │Local    │ │     │              │            │
│  │ │Router   ││     │ │Router   │ │     │ Research     │            │
│  │ │(QKV)    ││     │ │(QKV)    │ │     │ Pool         │            │
│  │ └─────────┘│     │ └─────────┘ │     └──────────────┘            │
│  │             │     │             │                                  │
│  │  ┌───┐┌───┐│     │ ┌───┐┌───┐ │                                  │
│  │  │N1 ││N2 ││     │ │N5 ││N6 │ │                                  │
│  │  └───┘└───┘│     │ └───┘└───┘ │                                  │
│  │  ┌───┐┌───┐│     │ ┌───┐┌───┐ │                                  │
│  │  │N3 ││N4 ││     │ │N7 ││N8 │ │                                  │
│  │  └───┘└───┘│     │ └───┘└───┘ │                                  │
│  └─────────────┘     └─────────────┘                                  │
│         │                    │                                         │
│  ┌──────▼────────────────────▼──────────────────────────────────────┐│
│  │                    Shared Infrastructure                          ││
│  │  ┌────────┐  ┌─────────┐  ┌──────────┐  ┌────────────────────┐  ││
│  │  │ NATS   │  │ Redis   │  │ Postgres │  │ Kafka              │  ││
│  │  │ (ctrl) │  │ (L2     │  │ (L3      │  │ (audit trail)      │  ││
│  │  │        │  │  cache)  │  │  memory) │  │                    │  ││
│  │  └────────┘  └─────────┘  └──────────┘  └────────────────────┘  ││
│  └──────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────┘
```

### Autonomous Node Architecture

Each node in the target state is a self-contained agent:

```
┌─────────────────────────────────────────────────┐
│                  Autonomous Node                  │
│                                                   │
│  ┌─────────────┐  ┌──────────────────────────┐  │
│  │ Local Brain │  │ Context Window            │  │
│  │ (LLM tier)  │  │ ┌────────────────────┐   │  │
│  │ quick/deep  │  │ │ Recent observations │   │  │
│  └─────────────┘  │ │ Recent decisions    │   │  │
│                    │ │ Compressed history  │   │  │
│  ┌─────────────┐  │ └────────────────────┘   │  │
│  │ L1 Memory   │  └──────────────────────────┘  │
│  │ (local)     │                                  │
│  │ episodic    │  ┌──────────────────────────┐   │
│  │ semantic    │  │ Capabilities             │   │
│  │ working     │  │ signal_generation        │   │
│  └─────────────┘  │ risk_assessment          │   │
│                    │ ...                      │   │
│  ┌─────────────┐  └──────────────────────────┘   │
│  │ State       │                                  │
│  │ Tensor      │  ┌──────────────────────────┐   │
│  │ (16-dim)    │  │ NATS Client              │   │
│  └─────────────┘  │ pub: observations        │   │
│                    │ sub: relevant topics     │   │
│  ┌─────────────┐  └──────────────────────────┘   │
│  │ Health &    │                                  │
│  │ Circuit     │  ┌──────────────────────────┐   │
│  │ Breaker     │  │ Connect-RPC Server       │   │
│  └─────────────┘  │ (Execute, Evaluate, etc) │   │
│                    └──────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

---

## 1. Node Autonomy

### Current State

Nodes are passive executors. The Go orchestrator calls `PipelineService.ExecuteStep()` synchronously, passing input from the previous step. Nodes have no independent decision-making capability and no persistent local state between cycles.

### Target State

Each node becomes a self-contained agent that can:

- **Run independently** on any machine in the cluster
- **Maintain local memory** (L1 episodic + semantic cache)
- **Own a context window** tracking recent observations and decisions
- **Make local decisions** without waiting for the orchestrator
- **Communicate asynchronously** by publishing observations and subscribing to relevant topics

### Design: Node Autonomy Levels

Building on Omega's existing `autonomy_level` concept from project configuration:

```
Level 0 - Passive:     Current behavior. Orchestrator drives all execution.
Level 1 - Reactive:    Node can respond to events without orchestrator trigger.
Level 2 - Proactive:   Node can initiate actions based on local observations.
Level 3 - Autonomous:  Node can make and execute decisions independently.
                        (Gated by trust_score >= 0.7, existing mechanism)
```

### Granularity Decision

**One node per capability, not per signal or per project.**

Rationale: Omega's existing capability system (8 capabilities: signal_generation, risk_assessment, backtesting, data_ingestion, portfolio_optimization, anomaly_detection, forecasting, execution) provides the right granularity. Each capability maps to a logical agent type. Multiple instances of the same capability can run across machines for horizontal scaling.

For signal generation specifically, the node internally manages multiple signal sources. This avoids the overhead of inter-node coordination for closely related signals while allowing independent scaling of the signal generation capability.

### Coordination Without Central Bottleneck

Three mechanisms, chosen by urgency:

1. **Event-driven (async, <10ms)**: Nodes publish observations to NATS topics. Interested nodes subscribe. No coordination needed. Example: a DataIngestion node publishes a new market regime detection; SignalResearch nodes pick it up asynchronously.

2. **Gossip-propagated (eventual, <1s)**: Node state changes (health, capabilities, load) propagate via memberlist gossip. All nodes eventually converge on cluster state. No central registry needed for discovery.

3. **Consensus-gated (strong, <200ms)**: Critical decisions (risk limits, position changes) go through Raft consensus. Used sparingly, only where eventual consistency is unacceptable.

### Proto Evolution

```protobuf
// New: node_autonomy.proto
message NodeAutonomyConfig {
  AutonomyLevel level = 1;
  float trust_threshold = 2;        // min trust for autonomous operation
  repeated string allowed_actions = 3; // what the node can do autonomously
  repeated string veto_topics = 4;   // NATS topics that can veto this node
  Duration max_autonomous_duration = 5; // time limit for unsupervised runs
}

enum AutonomyLevel {
  AUTONOMY_LEVEL_PASSIVE = 0;
  AUTONOMY_LEVEL_REACTIVE = 1;
  AUTONOMY_LEVEL_PROACTIVE = 2;
  AUTONOMY_LEVEL_AUTONOMOUS = 3;
}

// Evolution of existing RegisterNodeRequest
message RegisterNodeRequest {
  string node_id = 1;
  string name = 2;
  string version = 3;
  string address = 4;               // Connect-RPC endpoint
  repeated string capabilities = 5;
  string language = 6;
  NodeAutonomyConfig autonomy = 7;  // NEW
  string nats_subject_prefix = 8;   // NEW: node's NATS topic namespace
  string machine_id = 9;            // NEW: which machine this node runs on
}
```

---

## 2. Distributed Memory Architecture

### Current State

All memory lives in a single PostgreSQL instance:

- **Working memory**: in-process Python dict, cleared each cycle
- **Episodic memory**: `episodes` table with namespace, importance, decay
- **Semantic memory**: `semantic_memories` table with concept, confidence, evidence_count
- Consolidation runs every 5 cycles, promoting high-importance episodes to semantic concepts

### Target State: Three-Tier Memory Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│                    Memory Hierarchy                           │
│                                                               │
│  L1: Node-Local (< 0.1ms)                                   │
│  ┌───────────────────────────────────────────────────────┐   │
│  │ In-process working memory (current cycle)              │   │
│  │ Local episodic cache (last N episodes, LRU)           │   │
│  │ Local semantic cache (relevant concepts, read-through) │   │
│  │ Context window (bounded recent state)                  │   │
│  └───────────────────────────────────────────────────────┘   │
│                          │ cache miss                         │
│                          ▼                                    │
│  L2: Project-Shared (< 5ms)                                  │
│  ┌───────────────────────────────────────────────────────┐   │
│  │ Redis cluster (per-project keyspace)                   │   │
│  │ Shared episodes (project-scoped, replicated)          │   │
│  │ Shared semantic concepts (project-scoped)             │   │
│  │ Real-time signal state (pub/sub channels)             │   │
│  └───────────────────────────────────────────────────────┘   │
│                          │ cache miss / consolidation         │
│                          ▼                                    │
│  L3: Platform-Global (< 20ms)                                │
│  ┌───────────────────────────────────────────────────────┐   │
│  │ PostgreSQL (existing schema, authoritative)            │   │
│  │ All episodes (full history)                            │   │
│  │ All semantic memories (ground truth)                   │   │
│  │ Cross-project patterns (platform-level learning)       │   │
│  │ Audit trail (immutable)                                │   │
│  └───────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Memory Consistency Model

Different tiers use different consistency guarantees:

| Tier | Consistency | Mechanism | Rationale |
|------|-------------|-----------|-----------|
| L1 | Strong (local) | In-process | Single-threaded access per node |
| L2 | Eventual (< 100ms) | Redis replication + NATS invalidation | Speed over precision for shared observations |
| L3 | Strong (ACID) | PostgreSQL transactions | Authoritative record, audit compliance |

### Handling Memory Conflicts

When two nodes store contradictory lessons (e.g., Node A learns "momentum works in current regime" while Node B learns "momentum fails in current regime"):

**Resolution strategy (domain-specific merge):**

1. **Both persist**: Store both memories with their source node_id and evidence_count
2. **Confidence-weighted**: During retrieval, weight by `confidence * evidence_count * recency`
3. **Consolidation resolves**: The periodic consolidation process (existing mechanism) evaluates contradictions using the BrainAdapter and resolves them into a unified semantic concept with caveats
4. **Escalation**: If contradiction persists across 3+ consolidation cycles, flag for human review via the existing `issues` table

```protobuf
// Evolution of existing MemoryService
message StoreEpisodeRequest {
  // ... existing fields ...
  string source_node_id = 10;       // NEW: which node created this
  string machine_id = 11;           // NEW: which machine
  bytes hlc_timestamp = 12;         // NEW: hybrid logical clock
  MemoryTier target_tier = 13;      // NEW: L1, L2, or L3
}

enum MemoryTier {
  MEMORY_TIER_LOCAL = 0;    // L1: stays on this node
  MEMORY_TIER_PROJECT = 1;  // L2: shared within project
  MEMORY_TIER_GLOBAL = 2;   // L3: platform-wide
}
```

### Event Ordering: Hybrid Logical Clocks

**Why HLC over vector clocks**: Omega targets 10-50 nodes. Vector clocks grow linearly with cluster size (50-element vectors on every message). HLC provides causality with constant space overhead and aligns with physical timestamps from market data feeds.

**Go implementation**: Use `github.com/cockroachdb/hlc` (battle-tested in CockroachDB) or implement a lightweight version:

```go
// internal/clock/hlc.go
type HLC struct {
    mu       sync.Mutex
    physical func() int64  // wall clock (milliseconds)
    logical  uint32
    lastPT   int64
}

func (c *HLC) Now() Timestamp {
    c.mu.Lock()
    defer c.mu.Unlock()
    pt := c.physical()
    if pt > c.lastPT {
        c.lastPT = pt
        c.logical = 0
    } else {
        c.logical++
    }
    return Timestamp{Physical: c.lastPT, Logical: c.logical}
}

func (c *HLC) Update(received Timestamp) Timestamp {
    c.mu.Lock()
    defer c.mu.Unlock()
    pt := c.physical()
    if pt > c.lastPT && pt > received.Physical {
        c.lastPT = pt
        c.logical = 0
    } else if received.Physical > c.lastPT {
        c.lastPT = received.Physical
        c.logical = received.Logical + 1
    } else {
        c.logical++
    }
    return Timestamp{Physical: c.lastPT, Logical: c.logical}
}
```

### Memory Sync Protocol

```
Node writes episode locally (L1)
  │
  ├─ importance >= 0.5 → publish to NATS topic "memory.{project_id}.episodes"
  │                       → other nodes in project update L1 cache
  │                       → project coordinator writes to Redis (L2)
  │
  ├─ importance >= 0.8 → additionally write to Postgres (L3)
  │
  └─ importance < 0.5  → stays in L1 only, subject to local decay
```

---

## 3. Communication Protocols

### Current State

Synchronous Connect-RPC calls in pipeline order. The Go orchestrator calls `ExecuteStep()` and blocks until the Python node responds. Postgres LISTEN/NOTIFY provides primitive pub/sub for 4 channels (node_state_changed, cycle_completed, improvement_triggered, issue_detected).

### Target State: Layered Communication

```
┌─────────────────────────────────────────────────────────────┐
│                  Communication Layers                         │
│                                                               │
│  Layer 1: Control Plane (NATS)                               │
│  ├─ Agent-to-agent signals                    < 1ms          │
│  ├─ Risk notifications / vetoes               < 1ms          │
│  ├─ Memory invalidation events                < 5ms          │
│  └─ Node lifecycle (join/leave/health)        < 10ms         │
│                                                               │
│  Layer 2: Workflow Orchestration (Temporal)                   │
│  ├─ Multi-step pipeline execution             10-100ms       │
│  ├─ Improvement cycles                        seconds        │
│  ├─ Backtesting workflows                     minutes        │
│  └─ Durable execution with replay             guaranteed     │
│                                                               │
│  Layer 3: State Synchronization (Gossip + Redis)             │
│  ├─ Node state tensor propagation             < 100ms        │
│  ├─ Capability announcements                  < 1s           │
│  ├─ Cluster membership changes                < 5s           │
│  └─ L2 memory cache sync                     < 100ms        │
│                                                               │
│  Layer 4: Consensus (Raft via etcd)                          │
│  ├─ Risk parameter updates                    < 200ms        │
│  ├─ Position aggregate changes                < 200ms        │
│  └─ Circuit breaker state (critical nodes)    < 200ms        │
│                                                               │
│  Layer 5: Audit Trail (Kafka)                                │
│  ├─ All execution records                     eventual       │
│  ├─ All memory mutations                      eventual       │
│  └─ All routing decisions                     eventual       │
└─────────────────────────────────────────────────────────────┘
```

### Why NATS (Not Kafka or Redis Streams) for Control Plane

| Criterion | NATS | Kafka | Redis Streams |
|-----------|------|-------|---------------|
| Latency (p99) | < 1ms | 50-200ms | < 2ms |
| Go SDK maturity | Native (written in Go) | Good | Good |
| Operational simplicity | Single binary, zero config | ZooKeeper/KRaft, partitions | Redis cluster, persistence tuning |
| Memory footprint | < 50MB | > 500MB | Depends on data volume |
| Pub/sub semantics | Native | Consumer groups (heavier) | XREAD groups |
| Trading suitability | Control + signals | Audit trail | State cache |

**Decision**: NATS for control plane (Layers 1+3), Kafka for audit trail (Layer 5), Redis for L2 memory cache. This matches each technology's strength.

### NATS Topic Design

```
omega.{cluster_id}.                          # cluster namespace
  nodes.                                     # node lifecycle
    {node_id}.heartbeat                      # periodic health
    {node_id}.state                          # state tensor updates
    joined                                   # new node announcements
    left                                     # node departures
  projects.                                  # project-scoped
    {project_id}.                            #
      pipeline.step.{step_id}               # step execution events
      memory.episodes                        # episode publications
      memory.semantic                        # semantic updates
      signals.{signal_type}                 # signal publications
      decisions.{decision_type}             # routing decisions
  risk.                                      # risk management
    alerts                                   # risk threshold breaches
    vetoes                                   # risk vetoes (high priority)
    limits.updated                           # parameter changes
  coordination.                              # router events
    route.requests                           # routing requests
    route.results                            # routing outcomes
```

### Gossip Integration

```go
// internal/cluster/membership.go
import "github.com/hashicorp/memberlist"

type ClusterMembership struct {
    list     *memberlist.Memberlist
    delegate *OmegaDelegate  // handles NotifyJoin, NotifyLeave, NotifyUpdate
}

// OmegaDelegate implements memberlist.Delegate
type OmegaDelegate struct {
    registry *NodeRegistry
    nats     *nats.Conn
}

func (d *OmegaDelegate) NotifyJoin(node *memberlist.Node) {
    // Update local registry
    // Publish to omega.nodes.joined
}

func (d *OmegaDelegate) NotifyLeave(node *memberlist.Node) {
    // Mark node offline in registry
    // Publish to omega.nodes.left
    // Trigger circuit breaker if needed
}

// NodeMeta carries capability and state tensor info in gossip
func (d *OmegaDelegate) NodeMeta(limit int) []byte {
    // Serialize: capabilities, health_score, load, trust_score
    // Compact binary encoding, fits in gossip payload
}
```

---

## 4. Distributed Attention Router

### Current State

The attention router is a centralized Go component that computes `softmax(Q*K^T / sqrt(32)) * V` to route goals to nodes. It uses:

- `LinearGoalEncoder`: 32-dim query from goal type (5 one-hot) + context metrics (16 dims)
- `NodeProjector`: key from state(16) + capabilities(8) + trust(1), value from state(16) + trust(1)
- EMA prior adaptation from outcome records
- Trust masking for autonomous goals

### Target State: Federated Routing

The router evolves from a single centralized instance to a **federated model** where each project coordinator runs a local router, and the platform coordinator aggregates cross-project routing.

```
┌─────────────────────────────────────────────────┐
│           Platform Router (Global)               │
│                                                   │
│  Handles:                                         │
│  - Cross-project goal routing                    │
│  - New project assignment                        │
│  - Resource contention resolution                │
│  - Global trust score aggregation                │
│                                                   │
│  Inputs: project-level state summaries           │
│  Frequency: per-cycle or on-demand               │
└───────────────────┬─────────────────────────────┘
                    │
        ┌───────────┼───────────┐
        │           │           │
┌───────▼───┐ ┌────▼────┐ ┌────▼────┐
│ Victoria  │ │Polymarket│ │ Future  │
│ Router    │ │ Router   │ │ Project │
│           │ │          │ │ Router  │
│ Local QKV │ │ Local QKV│ │         │
│ Local EMA │ │ Local EMA│ │         │
│ Local     │ │ Local    │ │         │
│ tensors   │ │ tensors  │ │         │
└───────────┘ └──────────┘ └─────────┘
```

### Routing as Distributed Scheduler

The attention router becomes a distributed scheduler with work-stealing capabilities:

```go
// internal/coordination/distributed_router.go

type DistributedRouter struct {
    localRouter    *AttentionRouter       // existing 32-dim QKV
    memberlist     *ClusterMembership     // gossip for node discovery
    nats           *nats.Conn             // for routing requests/results
    projectID      string                 // scoped to one project
    stealThreshold float32                // load threshold for work stealing
}

func (r *DistributedRouter) Route(ctx context.Context, goal *GoalSpec) (*RoutingResult, error) {
    // 1. Gather local node tensors (from gossip-propagated state)
    tensors := r.memberlist.GetNodeTensors(r.projectID)

    // 2. Run local attention routing (existing algorithm, unchanged)
    result := r.localRouter.Route(goal, tensors)

    // 3. If primary node is overloaded (from gossip health), try work stealing
    if r.isOverloaded(result.PrimaryNode) {
        stolen := r.tryStealWork(ctx, result)
        if stolen != nil {
            return stolen, nil
        }
    }

    // 4. Publish routing decision to NATS for observability
    r.nats.Publish("omega.coordination.route.results", result)

    return result, nil
}

func (r *DistributedRouter) tryStealWork(ctx context.Context, original *RoutingResult) *RoutingResult {
    // Find least-loaded node with matching capability
    // Use gossip-propagated load metrics
    // Only steal if load difference exceeds stealThreshold
}
```

### Trust Propagation

Trust scores propagate across the cluster using a reputation network:

1. **Local trust**: Each project coordinator maintains trust scores for its nodes (existing EMA mechanism)
2. **Cross-project trust**: When a node serves multiple projects, trust scores are weighted-averaged across projects
3. **Trust decay**: Nodes that haven't been evaluated recently decay toward a neutral trust (0.5)
4. **Trust propagation**: Trust updates published to NATS `omega.nodes.{node_id}.state`, picked up by all coordinators via gossip

### Failure Handling Evolution

```
Node Failure Detected (via gossip NotifyLeave or heartbeat timeout)
  │
  ├─ Circuit breaker opens (existing mechanism)
  │
  ├─ In-flight requests fail fast (existing)
  │
  ├─ NEW: Routing table updated immediately (remove node from attention)
  │
  ├─ NEW: NATS publish to omega.risk.alerts
  │
  ├─ NEW: Work redistribution
  │   ├─ Pending work for failed node queried from Temporal
  │   ├─ Re-routed via attention router (without failed node)
  │   └─ Temporal handles retry with new node assignment
  │
  └─ NEW: Fallback chain
      ├─ Try next-highest attention weight node
      ├─ Try any healthy node with matching capability
      └─ If no capable node: pause project, alert human
```

---

## 5. Context Windows per Node

### Design

Each node maintains a bounded **context window** - a sliding view of recent observations and decisions that informs its next action. This mirrors transformer self-attention but applied to agent state.

```
┌─────────────────────────────────────────────────┐
│              Node Context Window                  │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │ Compressed History (summary of cycles 1-N)  │ │
│  │ "BTC momentum positive since cycle 45,      │ │
│  │  drawdown event at cycle 52 recovered by    │ │
│  │  cycle 58, current regime: trending"        │ │
│  └─────────────────────────────────────────────┘ │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │ Recent Observations (last K cycles)          │ │
│  │ cycle_97: {price: 67200, volume: high, ...} │ │
│  │ cycle_98: {price: 67450, signal: buy, ...}  │ │
│  │ cycle_99: {price: 67100, signal: hold, ...} │ │
│  └─────────────────────────────────────────────┘ │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │ Recent Decisions (last K decisions)          │ │
│  │ decision_45: {action: increase_exposure,     │ │
│  │   confidence: 0.72, outcome: pending}        │ │
│  │ decision_46: {action: hold, confidence: 0.8} │ │
│  └─────────────────────────────────────────────┘ │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │ Relevant Semantic Memories (top M by score)  │ │
│  │ "BTC momentum signals have 62% hit rate     │ │
│  │  in trending regimes" (conf: 0.85)           │ │
│  └─────────────────────────────────────────────┘ │
│                                                   │
│  Window Size: configurable per node type         │
│  Compaction: every 50 cycles, summarize oldest   │
│  Sharing: on request via NATS topic              │
└─────────────────────────────────────────────────┘
```

### Context Compression

When the context window fills, the oldest entries are compressed into a summary:

```python
# omega/core/context_window.py

class ContextWindow:
    def __init__(self, max_observations=50, max_decisions=20,
                 max_semantic=10, compaction_overlap=10):
        self.observations = deque(maxlen=max_observations)
        self.decisions = deque(maxlen=max_decisions)
        self.semantic_cache = []  # top-M by relevance score
        self.compressed_history = ""  # LLM-generated summary
        self.compaction_count = 0

    def add_observation(self, obs):
        self.observations.append(obs)
        if len(self.observations) >= self.observations.maxlen:
            self._compact()

    def _compact(self):
        # Keep last `compaction_overlap` observations intact
        to_compress = list(self.observations)[:-self.compaction_overlap]

        # Use local BrainAdapter (quick tier) to summarize
        summary = self.brain.decide(BrainRequest(
            operation="summarize_context",
            current_state={"observations": to_compress,
                          "existing_summary": self.compressed_history},
        ))
        self.compressed_history = summary.parameters["summary"]
        self.compaction_count += 1

        # Remove compressed observations
        for _ in range(len(to_compress)):
            self.observations.popleft()

    def to_brain_context(self) -> dict:
        """Package context window for BrainRequest."""
        return {
            "compressed_history": self.compressed_history,
            "recent_observations": list(self.observations),
            "recent_decisions": list(self.decisions),
            "relevant_memories": self.semantic_cache,
            "window_stats": {
                "compactions": self.compaction_count,
                "observation_count": len(self.observations),
                "decision_count": len(self.decisions),
            }
        }
```

### Context Sharing Protocol

Nodes share context in two ways:

1. **On-demand pull**: A node requests another node's context via NATS request-reply:
   ```
   Request:  omega.projects.{pid}.context.request.{target_node_id}
   Response: compressed context window (JSON)
   ```

2. **Periodic broadcast**: Every N cycles, each node publishes a context summary to its project topic. Other nodes can use this to inform their own decisions without explicit coordination.

### When to Share Context

| Trigger | Mechanism | Latency Budget |
|---------|-----------|----------------|
| Regime change detected | Broadcast to project topic | < 10ms |
| Contradictory signal from peer | Request peer's context | < 50ms |
| Pre-consolidation | All nodes broadcast context | < 1s |
| New node joins project | Pull context from coordinator | < 5s |

---

## 6. Cluster Topology

### Recommended: Hierarchical Hybrid

After evaluating star, mesh, ring, and hierarchical topologies against Omega's requirements (10-50 nodes, mixed latency requirements, risk governance), the recommended topology is **hierarchical hybrid**:

```
                    Platform Coordinator
                    (Raft cluster: 3 nodes)
                    ┌──────────────────┐
                    │ Global Risk Mgr  │
                    │ Platform Router  │
                    │ Gossip Seed      │
                    │ Temporal Server  │
                    └────────┬─────────┘
                             │
              NATS (control plane)
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
    ┌────▼────┐         ┌───▼────┐         ┌────▼────┐
    │Victoria │         │Polymar.│         │Research │
    │Coord.   │         │Coord.  │         │Pool     │
    │         │         │        │         │         │
    │ Router  │         │ Router │         │ Router  │
    │ L2 Redis│         │L2 Redis│         │L2 Redis │
    └────┬────┘         └───┬────┘         └────┬────┘
         │                  │                    │
    Mesh within project     Mesh                 Mesh
    ┌──┬──┬──┐         ┌──┬──┬──┐          ┌──┬──┐
    │N1│N2│N3│         │N5│N6│N7│          │N9│N10│
    └──┘──┘──┘         └──┘──┘──┘          └──┘──┘
    │N4│                │N8│
    └──┘                └──┘
```

### Why This Topology

| Requirement | How Topology Addresses It |
|-------------|--------------------------|
| Low-latency signals | Mesh within project: nodes communicate directly via NATS, < 1ms |
| Risk governance | Platform coordinator: single authority for risk vetoes |
| Failure isolation | Project-scoped: Victoria failure doesn't affect Polymarket |
| Horizontal scaling | Add nodes to project mesh, or add new projects |
| Node discovery | Gossip propagation: no central registry bottleneck |
| Cross-project learning | Platform coordinator aggregates and distributes insights |

### Node Allocation (10-50 Nodes)

| Role | Count | Description |
|------|-------|-------------|
| Platform coordinator | 3 | Raft consensus cluster, risk management, Temporal server |
| Victoria project | 4-9 | DataIngestion, SignalResearch, PortOpt, RiskAssessment, Backtest, Adversarial |
| Polymarket project | 4-9 | Similar but for prediction markets |
| Research pool | 2-5 | On-demand nodes for deep analysis, improvement cycles |
| Shared services | 2-3 | Memory consolidation, monitoring, data feeds |
| **Total** | **15-29** | Typical deployment |

---

## 7. Framework Evaluation

### Decision Matrix

| Framework | Polyglot (Go+Python) | Latency | Agent Autonomy | Production Maturity | Fit for Omega |
|-----------|---------------------|---------|----------------|--------------------|----|
| **Temporal** | Native Go + Python SDKs | 50-200ms/step | Workflow-level | Battle-tested | **Primary orchestration** |
| **Ray** | Python-native, Go via cgo | Sub-ms compute | Computation-level | ML workloads | Signal computation |
| **NATS** | Go-native | Sub-ms messaging | N/A (transport) | Production | **Control plane** |
| **memberlist** | Go-native | Gossip convergence | N/A (discovery) | HashiCorp proven | **Node discovery** |
| **etcd** | Go-native | Raft: <200ms | N/A (consensus) | Kubernetes backbone | **Critical state** |
| **LangGraph** | Python-only | LLM-bound | Graph-based | Growing | Agent reasoning chains |
| **CrewAI** | Python-only | LLM-bound | Role-based | Growing | Role-based agent design |
| **Akka** | JVM-only | Low | Actor-based | Mature | Not polyglot enough |
| **Orleans** | .NET-only | Low | Virtual actors | Mature | Not polyglot enough |

### Recommended Stack

**Core infrastructure (build on)**:
- **Temporal** for durable pipeline orchestration (replaces synchronous `runCycle`)
- **NATS** for inter-node messaging (replaces Postgres LISTEN/NOTIFY for real-time)
- **hashicorp/memberlist** for gossip-based node discovery (replaces centralized registry)
- **etcd** for consensus on critical shared state (new capability)

**Keep existing**:
- **Connect-RPC** for node-to-node RPC (already works well)
- **PostgreSQL** for L3 persistent memory and audit (proven)
- **OpenTelemetry** for distributed tracing (already integrated)

**Add for specific capabilities**:
- **Redis** for L2 project-shared memory cache
- **Kafka** for immutable audit trail (if regulatory requirements demand it; otherwise Postgres is sufficient for now)

### Go Packages to Adopt

```go
// go.mod additions

require (
    // Cluster membership and gossip
    github.com/hashicorp/memberlist v0.5.x

    // Messaging
    github.com/nats-io/nats.go v1.x

    // Workflow orchestration
    go.temporal.io/sdk v1.x

    // Consensus (if not using external etcd)
    go.etcd.io/etcd/client/v3 v3.5.x

    // Hybrid logical clocks
    // (implement in-house, ~100 lines, or use cockroachdb/hlc)

    // Redis for L2 cache
    github.com/redis/go-redis/v9 v9.x
)
```

---

## 8. Specific Changes to Omega Core

### Phase 1: Async Node Communication (Weeks 1-4)

**Goal**: Break the synchronous pipeline dependency without changing node logic.

#### 8.1 Add NATS to the Go server

```go
// internal/messaging/nats.go

type NATSBus struct {
    conn     *nats.Conn
    js       nats.JetStreamContext  // for durable subscriptions
    hlc      *clock.HLC
    nodeID   string
}

func NewNATSBus(url string, nodeID string) (*NATSBus, error) {
    nc, err := nats.Connect(url,
        nats.Name("omega-"+nodeID),
        nats.ReconnectWait(time.Second),
        nats.MaxReconnects(-1),
    )
    if err != nil {
        return nil, err
    }
    js, _ := nc.JetStream()
    return &NATSBus{conn: nc, js: js, nodeID: nodeID}, nil
}

func (b *NATSBus) Publish(topic string, payload []byte) error {
    msg := &nats.Msg{
        Subject: topic,
        Data:    payload,
        Header:  nats.Header{},
    }
    msg.Header.Set("X-Omega-Node-ID", b.nodeID)
    msg.Header.Set("X-Omega-HLC", b.hlc.Now().String())
    return b.conn.PublishMsg(msg)
}

func (b *NATSBus) Subscribe(topic string, handler func(*nats.Msg)) (*nats.Subscription, error) {
    return b.conn.Subscribe(topic, handler)
}
```

#### 8.2 Evolve the Orchestrator from Synchronous to Event-Driven

```go
// internal/handler/orchestrator_v2.go

// Phase 1: Parallel independent steps within a cycle

func (o *OrchestratorHandler) runCycleParallel(ctx context.Context, project *Project) (*CycleResult, error) {
    steps := project.PipelineSteps()

    // Build dependency graph from step configuration
    dag := buildDAG(steps)

    // Execute steps respecting dependencies, parallelize independent steps
    var wg sync.WaitGroup
    results := make(map[string]*ExecuteStepResponse)
    var mu sync.Mutex

    for _, layer := range dag.TopologicalLayers() {
        // All steps in the same layer can run in parallel
        for _, step := range layer {
            wg.Add(1)
            go func(s *PipelineStep) {
                defer wg.Done()

                // Gather inputs from completed dependencies
                mu.Lock()
                input := gatherInputs(s, results)
                mu.Unlock()

                resp, err := o.pipelineClient.ExecuteStep(ctx, &ExecuteStepRequest{
                    StepId:       s.StepID,
                    StepName:     s.Name,
                    NodeType:     s.NodeType,
                    Cycle:        o.cycleN.Load(),
                    ProjectId:    project.ID,
                    InputPayload: input,
                })

                mu.Lock()
                results[s.StepID] = resp
                mu.Unlock()

                // Publish step completion event
                o.nats.Publish(
                    fmt.Sprintf("omega.projects.%s.pipeline.step.%s", project.ID, s.StepID),
                    resp,
                )
            }(step)
        }
        wg.Wait() // Wait for current layer before starting next
    }

    return aggregateResults(results), nil
}
```

#### 8.3 Add DAG-Based Pipeline Configuration

```yaml
# projects/victoria.yaml (evolved)
pipeline_config:
  - step_id: step_1
    name: DataIngestion
    node_type: DATA_INGESTION
    order: 1
    depends_on: []                   # NEW: explicit dependencies

  - step_id: step_2
    name: SignalResearch
    node_type: SIGNAL_RESEARCH
    order: 2
    depends_on: [step_1]

  - step_id: step_2b
    name: AnomalyDetection           # NEW: runs parallel to SignalResearch
    node_type: ANOMALY_DETECTION
    order: 2
    depends_on: [step_1]

  - step_id: step_3
    name: PortfolioOptimization
    node_type: PORTFOLIO_OPTIMIZATION
    order: 3
    depends_on: [step_2, step_2b]    # waits for both
```

### Phase 2: Gossip-Based Discovery (Weeks 5-8)

**Goal**: Replace centralized NodeRegistry with gossip-based discovery.

#### 8.4 Integrate memberlist

```go
// internal/cluster/cluster.go

type Cluster struct {
    memberlist *memberlist.Memberlist
    registry   *NodeRegistry            // existing, becomes local cache
    nats       *NATSBus
    localNode  *NodeEntry
}

func NewCluster(config ClusterConfig) (*Cluster, error) {
    mlConfig := memberlist.DefaultLANConfig()
    mlConfig.Name = config.NodeID
    mlConfig.BindPort = config.GossipPort
    mlConfig.Delegate = &OmegaDelegate{...}
    mlConfig.Events = &OmegaEventDelegate{...}

    list, err := memberlist.Create(mlConfig)
    if err != nil {
        return nil, err
    }

    // Join existing cluster if seeds provided
    if len(config.SeedNodes) > 0 {
        _, err = list.Join(config.SeedNodes)
    }

    return &Cluster{memberlist: list, ...}, nil
}

// OmegaDelegate carries node metadata in gossip
type OmegaDelegate struct {
    localMeta []byte  // capabilities, health, load, trust
}

func (d *OmegaDelegate) NodeMeta(limit int) []byte {
    return d.localMeta  // must be < limit bytes (typically 512)
}

func (d *OmegaDelegate) GetBroadcasts(overhead, limit int) [][]byte {
    // Piggyback state tensor updates on gossip messages
    return nil
}

func (d *OmegaDelegate) LocalState(join bool) []byte {
    // Full node state for new joiners
    return d.localMeta
}

func (d *OmegaDelegate) MergeRemoteState(buf []byte, join bool) {
    // Update local registry with remote node state
}
```

### Phase 3: Distributed Memory (Weeks 9-12)

**Goal**: Implement L1/L2/L3 memory hierarchy.

#### 8.5 L1 Local Memory Cache

```go
// internal/memory/local_cache.go

type LocalMemoryCache struct {
    episodes  *lru.Cache[string, *Episode]     // LRU, max 1000 entries
    semantic  *lru.Cache[string, *SemanticMemory]
    working   sync.Map                           // current cycle
    nats      *NATSBus
    projectID string
}

func (c *LocalMemoryCache) StoreEpisode(ep *Episode) error {
    // Always store locally (L1)
    c.episodes.Add(ep.EpisodeID, ep)

    // If important enough, propagate to L2
    if ep.Importance >= 0.5 {
        c.nats.Publish(
            fmt.Sprintf("omega.projects.%s.memory.episodes", c.projectID),
            ep,
        )
    }

    return nil
}

func (c *LocalMemoryCache) QueryEpisodes(query *EpisodeQuery) ([]*Episode, error) {
    // Try L1 first
    results := c.searchLocal(query)
    if len(results) >= query.Limit {
        return results, nil
    }

    // Fall through to L2 (Redis) then L3 (Postgres)
    // ... cache results locally on return
}
```

#### 8.6 L2 Redis Project Cache

```go
// internal/memory/redis_cache.go

type RedisProjectCache struct {
    client    *redis.Client
    projectID string
    ttl       time.Duration  // default 1 hour
}

func (c *RedisProjectCache) StoreEpisode(ep *Episode) error {
    key := fmt.Sprintf("omega:%s:episodes:%s", c.projectID, ep.EpisodeID)
    data, _ := json.Marshal(ep)
    return c.client.Set(ctx, key, data, c.ttl).Err()
}

func (c *RedisProjectCache) QueryByTags(tags []string, limit int) ([]*Episode, error) {
    // Use Redis sorted sets for importance-weighted retrieval
    // Key: omega:{project_id}:episodes:by_importance
    // Score: importance * recency_factor
}
```

### Phase 4: Temporal Integration (Weeks 13-16)

**Goal**: Replace the Go orchestrator loop with Temporal workflows for durable, distributed pipeline execution.

#### 8.7 Pipeline as Temporal Workflow

```go
// internal/workflow/pipeline_workflow.go

func PipelineWorkflow(ctx workflow.Context, params PipelineParams) (*CycleResult, error) {
    dag := buildDAG(params.Steps)

    results := make(map[string]*ExecuteStepResponse)

    for _, layer := range dag.TopologicalLayers() {
        // Execute all steps in this layer as parallel activities
        var futures []workflow.Future
        for _, step := range layer {
            input := gatherInputs(step, results)

            ao := workflow.ActivityOptions{
                TaskQueue:           step.NodeType + "-queue",  // route to capable node
                StartToCloseTimeout: 5 * time.Minute,
                RetryPolicy: &temporal.RetryPolicy{
                    InitialInterval:    time.Second,
                    MaximumAttempts:    3,
                    BackoffCoefficient: 2.0,
                },
            }
            ctx := workflow.WithActivityOptions(ctx, ao)

            future := workflow.ExecuteActivity(ctx, ExecuteStepActivity, step, input)
            futures = append(futures, future)
        }

        // Wait for all parallel activities in this layer
        for i, future := range futures {
            var resp ExecuteStepResponse
            if err := future.Get(ctx, &resp); err != nil {
                // Temporal handles retries automatically
                return nil, fmt.Errorf("step %s failed: %w", layer[i].StepID, err)
            }
            results[layer[i].StepID] = &resp
        }
    }

    return aggregateResults(results), nil
}

// Activity: runs on any worker with matching capability
func ExecuteStepActivity(ctx context.Context, step *PipelineStep, input []byte) (*ExecuteStepResponse, error) {
    // This runs on the node's Temporal worker
    // Uses existing Connect-RPC pipeline client
    client := getPipelineClient(step.NodeType)
    return client.ExecuteStep(ctx, &ExecuteStepRequest{
        StepId:       step.StepID,
        StepName:     step.Name,
        NodeType:     step.NodeType,
        InputPayload: input,
    })
}
```

### Phase 5: Full Autonomy (Weeks 17-24)

**Goal**: Nodes can operate independently, making local decisions and coordinating asynchronously.

This phase adds:
- Node-local BrainAdapter instances (not centralized)
- Context window implementation per node
- Autonomous decision loops with risk guardian veto
- Cross-node context sharing via NATS

---

## 9. Trading-Specific Distributed Patterns

### Signal Nodes on Different Machines

```
Machine A (Low-latency, colocated)     Machine B (GPU, compute)
┌───────────────────────────┐          ┌───────────────────────────┐
│ Market Data Feed Handler  │          │ Deep Signal Research      │
│ (sub-second latency)      │   NATS   │ (GPU-accelerated)        │
│                           │ ◄──────► │                           │
│ Price Signal Generator    │          │ Pattern Recognition       │
│ Volume Signal Generator   │          │ Sentiment Analysis        │
│ Order Flow Analyzer       │          │ Alternative Data          │
└───────────────────────────┘          └───────────────────────────┘

Machine C (Risk + Execution)
┌───────────────────────────┐
│ Risk Management Node      │
│ (always-on supervisor)    │
│                           │
│ Portfolio Optimizer       │
│ Execution Engine          │
└───────────────────────────┘
```

### Risk Management as Distributed Supervisor

The risk node operates as an always-on supervisor with **veto power** over all trading decisions:

```go
// internal/risk/supervisor.go

type RiskSupervisor struct {
    nats          *NATSBus
    positionStore *etcd.Client      // Raft-backed position aggregate
    limits        *RiskLimits        // from etcd consensus
}

func (s *RiskSupervisor) Start() {
    // Subscribe to all trading decisions across all projects
    s.nats.Subscribe("omega.projects.*.decisions.trade", s.evaluateTradeDecision)
    s.nats.Subscribe("omega.projects.*.decisions.exposure", s.evaluateExposureChange)
}

func (s *RiskSupervisor) evaluateTradeDecision(msg *nats.Msg) {
    var decision TradeDecision
    json.Unmarshal(msg.Data, &decision)

    // Check against risk limits (from etcd)
    violations := s.checkLimits(decision)

    if len(violations) > 0 {
        // VETO: publish to high-priority veto topic
        s.nats.Publish(
            fmt.Sprintf("omega.risk.vetoes"),
            &RiskVeto{
                DecisionID: decision.ID,
                NodeID:     decision.SourceNodeID,
                Violations: violations,
                Timestamp:  s.hlc.Now(),
            },
        )
    } else {
        // APPROVE: publish approval
        s.nats.Publish(
            fmt.Sprintf("omega.risk.approvals"),
            &RiskApproval{DecisionID: decision.ID},
        )
    }
}
```

### Market Data Nodes with Sub-Second Requirements

```
Exchange WebSocket → Feed Handler (Machine A, colocated)
                        │
                        ├─ NATS publish: omega.data.{exchange}.{symbol}.tick
                        │   (latency budget: < 100μs from receipt)
                        │
                        ├─ Local L1 cache: last 1000 ticks per symbol
                        │
                        └─ Redis L2 write: OHLCV aggregates per interval
                            (latency budget: < 5ms)

Signal Nodes subscribe to relevant NATS topics:
  - Price signals: omega.data.*.btc.tick
  - Volume signals: omega.data.*.*.volume_spike
  - Order flow: omega.data.*.*.orderbook_update
```

### Memory Consolidation Node

A dedicated node that runs periodically to extract cross-project patterns:

```python
# omega/nodes/consolidation_node.py

class ConsolidationNode:
    """
    Runs every N cycles (configurable).
    Reads from L2/L3, writes to L3.
    Detects cross-project patterns.
    """

    def consolidate(self):
        # 1. Query high-importance episodes across all projects (L3)
        episodes = self.memory_l3.query_episodes(
            min_importance=0.7,
            since_cycle=self.last_consolidation_cycle,
        )

        # 2. Cluster similar episodes
        clusters = self.cluster_episodes(episodes)

        # 3. For each cluster, extract semantic concept
        for cluster in clusters:
            concept = self.brain.decide(BrainRequest(
                operation="extract_concept",
                current_state={"episodes": cluster},
            ))

            # 4. Store as semantic memory (L3)
            self.memory_l3.store_semantic(
                concept=concept.parameters["name"],
                content=concept.parameters["description"],
                confidence=concept.confidence,
                evidence_count=len(cluster),
                tags=concept.parameters.get("tags", []),
                namespace="platform",  # cross-project
            )

        # 5. Detect contradictions
        contradictions = self.detect_contradictions(episodes)
        for c in contradictions:
            self.issues.create(
                detector="consolidation_node",
                severity="warning",
                description=f"Contradictory memories: {c.concept_a} vs {c.concept_b}",
            )
```

### Research Nodes (On-Demand)

Research nodes spin up dynamically to analyze new data or run deep improvement cycles:

```yaml
# Temporal workflow: research_workflow.yaml
# Triggered by: new data source discovered, improvement cycle due, human request

research_workflow:
  steps:
    - name: SpinUpResearchNode
      activity: cluster.spawn_node
      params:
        node_type: RESEARCH
        capabilities: [signal_research, backtesting, improvement]
        autonomy_level: AUTONOMOUS
        ttl: 1h  # auto-terminate after 1 hour

    - name: RunResearch
      activity: research.execute
      params:
        task: "Analyze {data_source} for trading signals"
        brain_tier: DEEP  # use Claude Opus for deep analysis

    - name: ValidateFindings
      activity: adversarial.challenge
      params:
        findings: ${RunResearch.output}

    - name: IntegrateResults
      activity: memory.store_semantic
      params:
        concepts: ${ValidateFindings.validated_findings}
        namespace: ${project_id}

    - name: TearDown
      activity: cluster.remove_node
```

---

## 10. Migration Path

### Guiding Principles

1. **Don't break what works**: Each phase must leave the system fully functional
2. **Feature flags**: New distributed features behind flags, old path as fallback
3. **Incremental adoption**: Projects can opt into distributed features individually
4. **Backward compatible protos**: Only additive changes to existing protobuf definitions

### Phase Timeline

```
Week  1-4:  Phase 1 - Async Node Communication
             ├─ Add NATS dependency
             ├─ Parallel step execution within cycles (DAG-based)
             ├─ Step completion events published to NATS
             └─ Feature flag: OMEGA_PARALLEL_PIPELINE=true

Week  5-8:  Phase 2 - Gossip-Based Discovery
             ├─ Add memberlist dependency
             ├─ Nodes register via gossip (memberlist) + RPC (backward compat)
             ├─ Node health propagated via gossip
             └─ Feature flag: OMEGA_GOSSIP_DISCOVERY=true

Week  9-12: Phase 3 - Distributed Memory
             ├─ Add Redis for L2 cache
             ├─ Implement L1 local LRU cache per node
             ├─ Memory write-through: L1 → L2 → L3 based on importance
             ├─ HLC timestamps on all memory operations
             └─ Feature flag: OMEGA_DISTRIBUTED_MEMORY=true

Week 13-16: Phase 4 - Temporal Orchestration
             ├─ Deploy Temporal server alongside Go server
             ├─ Pipeline execution as Temporal workflows
             ├─ Retry, timeout, and failure handling via Temporal
             ├─ Old orchestrator loop as fallback
             └─ Feature flag: OMEGA_TEMPORAL_ORCHESTRATION=true

Week 17-20: Phase 5a - Node Autonomy
             ├─ Node-local BrainAdapter instances
             ├─ Context window implementation
             ├─ Autonomous decision loops (gated by trust)
             └─ Feature flag: OMEGA_NODE_AUTONOMY=true

Week 21-24: Phase 5b - Full Distribution
             ├─ Multi-machine deployment
             ├─ Risk supervisor as always-on guardian
             ├─ Cross-project coordination
             ├─ Research node pool
             └─ Feature flag: OMEGA_FULL_DISTRIBUTED=true
```

### MVP: Phase 1 (Parallel Pipeline)

The minimum viable distributed feature is **parallel step execution within the existing pipeline**. This requires:

1. Adding `depends_on` to pipeline step configuration
2. Building a DAG from step dependencies
3. Executing independent steps concurrently
4. Publishing step results to NATS for observability

**Estimated impact**: Cycle latency drops from `sum(all_steps)` to `max(critical_path)`. For Victoria's 9 steps, if 3 can run in parallel, expect ~30-40% latency reduction.

**Risk**: Low. The DAG executor is a straightforward replacement for the sequential loop. Fallback to sequential is trivial.

### What To Build First (Recommended Order)

1. **NATS integration** (foundation for everything else)
2. **DAG-based parallel pipeline** (immediate performance win)
3. **memberlist gossip** (prepares for multi-machine)
4. **L1 memory cache** (performance win, no new infrastructure)
5. **Redis L2 cache** (enables distributed memory)
6. **Temporal workflows** (durable orchestration)
7. **Context windows** (enables node autonomy)
8. **Node-local brain** (enables autonomous decisions)
9. **Risk supervisor** (safety net for autonomy)
10. **Multi-machine deployment** (the actual distribution)

---

## 11. Risk Assessment

### Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| NATS becomes single point of failure | Medium | High | NATS cluster mode (3 nodes), graceful degradation to direct RPC |
| Memory consistency bugs | High | Medium | Extensive integration testing, L3 as source of truth, reconciliation jobs |
| Temporal adds operational complexity | Medium | Medium | Start with embedded mode, graduate to cluster |
| Gossip convergence too slow for trading | Low | High | Use NATS for latency-critical, gossip only for non-critical state |
| Node autonomy makes bad decisions | Medium | High | Trust gating (existing), risk supervisor veto, gradual autonomy rollout |

### Performance Tradeoffs

| Dimension | Current | Phase 1-2 | Phase 3-4 | Phase 5 |
|-----------|---------|-----------|-----------|---------|
| Cycle latency | Sum of steps | Max of parallel path | Same + cache hits | Async, no fixed cycle |
| Memory read | ~1ms (local PG) | ~1ms | L1: <0.1ms, L2: <5ms | Same |
| Node failure impact | Entire pipeline | Parallel group | Single step (Temporal retry) | Single node |
| Operational complexity | Single process | +NATS, +memberlist | +Redis, +Temporal | +etcd, +Kafka |
| Data consistency | Strong (single PG) | Strong | Tiered (L1 eventual, L3 strong) | Tiered |

### What NOT to Do

1. **Don't replace PostgreSQL**: It works well as L3 storage. Add Redis and NATS alongside, don't replace.
2. **Don't build a custom consensus protocol**: Use etcd or embedded Raft. Consensus is notoriously hard to get right.
3. **Don't distribute everything at once**: The sequential pipeline works. Distribute incrementally, prove each phase.
4. **Don't over-engineer the topology**: Start with star (current) + async messaging. Evolve to hierarchical as the number of projects and nodes grows.
5. **Don't abandon Connect-RPC**: It provides excellent Go/Python interop with tracing. Layer NATS on top, don't replace it.

---

## Appendix A: Technology Comparison Detail

### NATS vs Redis Streams vs Kafka

| Feature | NATS | Redis Streams | Kafka |
|---------|------|---------------|-------|
| P99 latency (<1KB) | < 1ms | < 2ms | 50-200ms |
| Durability | JetStream optional | Built-in | Gold standard |
| Go SDK | Native (NATS is written in Go) | go-redis/v9 | confluent-kafka-go |
| Operational overhead | Single binary | Redis cluster | ZooKeeper/KRaft + brokers |
| Message ordering | Per-subject | Per-stream | Per-partition |
| Consumer groups | Queue groups | XREADGROUP | Native |
| Backpressure | Flow control | XREAD blocking | Consumer lag |
| Best for Omega | Control plane, signals | L2 memory cache | Audit trail |

### Temporal vs Custom Orchestrator

| Feature | Current (custom Go) | Temporal |
|---------|--------------------|---------|
| Retry logic | Manual defer/recover | Declarative retry policy |
| Timeout handling | Context deadline | Per-activity timeout |
| Failure visibility | Log parsing | Temporal UI + queries |
| Workflow versioning | Git + manual | Built-in deterministic replay |
| Distributed execution | No | Native (task queues per capability) |
| Audit trail | activity_log table | Built-in event history |
| Operational cost | Zero (in-process) | Temporal server (can start embedded) |

---

## Appendix B: Proto Evolution Summary

All changes are **additive** (new fields, new services). No existing field semantics change.

```
types.proto
  + machine_id on Node
  + hlc_timestamp on ExecutionRecord
  + memory_tier on Episode and SemanticMemory

node_service.proto
  + NodeAutonomyConfig on RegisterNodeRequest
  + nats_subject_prefix on RegisterNodeRequest
  + machine_id on RegisterNodeRequest

memory_service.proto
  + source_node_id on StoreEpisodeRequest
  + hlc_timestamp on StoreEpisodeRequest
  + MemoryTier enum
  + target_tier on StoreEpisodeRequest
  + QueryEpisodesRequest: add min_importance, since_hlc filters

coordination.proto
  + machine_affinity on CoordinationRequest (prefer local nodes)
  + load_metrics on CoordinationResponse

pipeline_service.proto
  + depends_on on PipelineStep (for DAG execution)
  + parallel_group on ExecuteStepRequest (for grouping)

NEW: cluster.proto
  + ClusterService: JoinCluster, LeaveCluster, GetClusterState
  + NodeDiscoveryEvent: joined, left, updated
  + ClusterTopology message

NEW: context_window.proto
  + ContextWindow message
  + ContextShareRequest / ContextShareResponse
  + ContextCompactionEvent
```

---

## Appendix C: Deployment Architecture

### Development (Single Machine)

```bash
# All-in-one: everything runs locally
docker compose -f docker-compose.dev.yml up

# Services:
# - omega-go: Go server (port 8080)
# - omega-python: Python pipeline (port 9090)
# - postgres: L3 storage (port 5432)
# - nats: messaging (port 4222)
# - redis: L2 cache (port 6379)
# - temporal: workflow engine (port 7233, embedded mode)
```

### Production (Multi-Machine)

```
Machine Group A: Platform Coordination (3 machines)
  - etcd cluster (Raft consensus)
  - NATS cluster (3-node)
  - Temporal server cluster
  - Risk supervisor (primary + standby)
  - PostgreSQL primary + replica

Machine Group B: Victoria Project (3-5 machines)
  - Victoria project coordinator
  - Data ingestion nodes (colocated with data feeds)
  - Signal research nodes
  - Portfolio optimization node
  - Redis (L2 cache, project-scoped)

Machine Group C: Polymarket Project (3-5 machines)
  - Similar to Group B, project-specific

Machine Group D: Shared Services (2-3 machines)
  - Memory consolidation node
  - Research pool (auto-scaling)
  - Monitoring (Grafana, Prometheus, Jaeger)
  - Kafka (if audit trail needed)
```

---

*This document is a living architecture proposal. Each phase should be reviewed and refined based on learnings from the previous phase. The migration path is designed to be reversible at each stage.*
