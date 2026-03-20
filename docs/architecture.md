# Project Omega — Architecture

## Vision

> Build a framework where nodes can be defined by contract, composed via an orchestrator, collectively evaluated against a goal, and individually improved through a feedback loop — automatically, iteratively.

This document covers the MVP architecture: enough to validate the hypothesis.

---

## Core Hypothesis

Can we close the loop between **execution**, **evaluation**, and **improvement** without human intervention?

```
┌───────────┐     tasks      ┌────────────────────────────────┐
│           │ ─────────────▶ │           Orchestrator          │
│   Goal    │                │  ┌────────────────────────────┐ │
│           │                │  │        Node Registry        │ │
└───────────┘                │  │  ┌──────┐ ┌──────┐ ┌────┐  │ │
                             │  │  │  N1  │ │  N2  │ │ N3 │  │ │
                             │  │  └──────┘ └──────┘ └────┘  │ │
                             │  └────────────────────────────┘ │
                             │                                  │
                             │  ┌────────────────────────────┐ │
                             │  │         Evaluator           │ │
                             │  │    (SQLite metric store)    │ │
                             │  └────────────────────────────┘ │
                             └────────────────────────────────┘
                                           │
                                    improve feedback
                                           │
                                           ▼
                             ┌─────────────────────────┐
                             │   Node.improve(feedback) │
                             │   → version bump         │
                             │   → behaviour change     │
                             └─────────────────────────┘
```

---

## Components

### `Node` (contract)

The fundamental unit.  A node declares:
- **What it can do** (`get_capabilities`) — a list of action verbs.
- **How it's doing** (`get_state`, `evaluate`) — health, metrics, version.
- **How to improve** (`improve`) — accepts feedback dict, changes behaviour, returns bool.

Nodes are black boxes.  The orchestrator doesn't care how they work internally.

### `NodeRegistry`

In-memory capability index: `{capability_verb → [node_id, …]}`.  Supports health-filtered lookup.  O(1) registration; O(k) capability lookup where k = nodes with that capability.

### `Evaluator`

Persists iteration snapshots to SQLite.  Computes:
- **Metric history** — `[(iteration, value), …]` per metric per goal.
- **Composite score** — weighted average over all MetricSpecs (direction-normalised).
- **Convergence detection** — `has_improved(goal, metric, min_delta_pct)`.
- **Report** — human-readable summary with trend arrows.

Uses `:memory:` by default; pass a file path for persistence across runs.

### `Orchestrator`

The coordination layer.  One convergence loop iteration:

```
1.  execute_goal(goal, parameters, iteration)
    ├─ decompose parameters["tasks"] into sub-tasks (or infer from goal string)
    ├─ for each task: select_node(action) → healthiest node with that capability
    └─ call node.execute(NodeInput) → NodeOutput

2.  evaluate_performance(goal, outputs, iteration)
    ├─ aggregate latency, success_rate, accuracy from outputs
    ├─ call evaluator.record(…) → persisted to SQLite
    └─ return system_metrics dict

3.  improve_system(goal, system_metrics, iteration)
    ├─ for each node: build feedback dict from system_metrics + node_metrics
    └─ call node.improve(feedback) → bool (changed?)
```

### Example Nodes

| Node | Improvement | Trigger |
|------|------------|---------|
| `CalculatorNode` | Enable LRU result cache | `improve_latency=True` in feedback |
| `WebFetcherNode` | Add TTL response cache + retry | latency feedback / error rate |
| `TextAnalyzerNode` | Unlock new analysis capabilities | any improvement call |

---

## Data Flow

```
parameters["tasks"] = [
    {"action": "add", "parameters": {"a": 3, "b": 4}},
    {"action": "multiply", "parameters": {"a": 6, "b": 7}},
]

                           Orchestrator
                          ┌────────────┐
  tasks ────────────────▶ │  routing   │
                          │  loop      │──▶ NodeInput ──▶ CalculatorNode.execute()
                          │            │◀─ NodeOutput ◀──────────────────────────
                          └────────────┘
                               │ outputs
                               ▼
                          evaluate_performance()
                               │ system_metrics
                               ▼
                          evaluator.record()  (→ SQLite)
                               │
                               ▼
                          improve_system()
                               │ feedback
                               ▼
                          node.improve(feedback)  → changed=True/False
```

---

## Key Design Decisions

### Why no external dependencies?
The hypothesis is about the *loop*, not the libraries.  Stdlib SQLite is sufficient for metric storage.  Adding pandas, numpy, etc. would obscure the core mechanic.

### Why is `improve()` on the node, not the orchestrator?
Nodes know their own internals.  The orchestrator only knows metrics.  This separation means you can swap orchestration strategies without touching node implementations, and nodes can have domain-specific improvement heuristics.

### Why SQLite for metrics?
- Zero setup, zero deps.
- Persistent across runs when given a file path.
- Easy to inspect with any SQLite browser.
- Queryable by iteration, node, goal.

### Why capability-based routing?
Explicit capability declarations make the system introspectable and debuggable.  An LLM could generate a new node by reading `get_capabilities()` of existing nodes and choosing a gap to fill.

---

## Extension Points

1. **New node** — implement `Node`, register with `Orchestrator`.
2. **New routing strategy** — override `Orchestrator._select_node()`.
3. **New goal decomposition** — override `Orchestrator._infer_action()` or always pass explicit `tasks`.
4. **New improvement signal** — add a `MetricSpec` to the `GoalSpec` and handle it in `node.improve()`.
5. **Distributed nodes** — replace `NodeRegistry` with a remote-capable implementation; keep the `Node` interface unchanged.

---

## MVP Limitations (intentional)

- Single-process, single-thread.
- No persistence by default (`:memory:` SQLite).
- Goal decomposition is keyword-based, not semantic.
- Improvement is deterministic (not LLM-driven yet).
- No authentication, rate limiting, or quota tracking.

These are all good targets for the next iteration once the core loop is validated.
