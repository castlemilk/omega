# Omega Node Intelligence Audit
**Date:** 2026-03-27
**Scope:** Full platform health check + per-node autonomy assessment
**Branch:** crazy-mirzakhani

---

## Part 1: Platform Health Check

### 1.1 Go Build
```
go build ./...  →  EXIT 0 ✅
```
All Go packages compile cleanly with no errors or warnings.

### 1.2 Python Module Imports
All 16 core modules import successfully ✅

| Module | Status |
|--------|--------|
| `omega.core.brain` | ✅ |
| `omega.core.memory` | ✅ |
| `omega.core.memory_bus` | ✅ |
| `omega.core.signal_bus` | ✅ |
| `omega.core.registry` | ✅ |
| `omega.core.orchestrator` | ✅ |
| `omega.nodes.victoria.victoria_node` | ✅ |
| `omega.nodes.victoria.signal_generation` | ✅ |
| `omega.nodes.victoria.strategy` | ✅ |
| `omega.nodes.victoria.risk_management` | ✅ |
| `omega.nodes.victoria.dynamic_weights` | ✅ |
| `omega.nodes.shared.reasoning_node` | ✅ |
| `omega.nodes.shared.reflection_node` | ✅ |
| `omega.nodes.devils_advocate` | ✅ |
| `omega.adversarial.debate_gate` | ✅ |
| `omega.bridge.pipeline_server` | ✅ |

### 1.3 Database Health

All SQLite databases present and readable:

| Database | Tables | Key Counts |
|----------|--------|------------|
| `data/omega_victoria.db` | iterations, node_metrics, system_metrics | **8 iterations** logged |
| `data/omega_victoria_memory.db` | episodes, semantic_memories, memory_ratings | **44 episodes**, 0 semantic, 0 ratings |
| `data/omega_victoria_state.db` | nodes, node_executions, adversarial_results, challenges, improvement_log, brain_executions, traces, + 10 more | **91 nodes**, 8 adversarial results, 18 challenges open |
| `data/omega_challenge_registry.db` | (legacy) | present |

**Memory system concern:** 44 episodes exist but 0 semantic memories — consolidation has never run. Memory accumulates without distillation.

### 1.4 Signal Production Health

3-cycle test with mock OHLCV (100 bars, BTC/ETH/SOL):

| Signal | Cycle 0 | Cycle 1 | Cycle 2 | Status |
|--------|---------|---------|---------|--------|
| `sma_crossover` | -1.0 | -1.0 | -1.0 | ✅ Producing |
| `sma_short` | 44818.15 | 44818.15 | 44818.15 | ✅ Producing |
| `sma_long` | 45295.16 | 45295.16 | 45295.16 | ✅ Producing |
| `composite` | -1.0 | -1.0 | -1.0 | ✅ Producing |
| `price` | 44807.67 | 44807.67 | 44807.67 | ✅ Producing |
| `return_1d` | -0.0026 | -0.0026 | -0.0026 | ✅ Producing |
| `rsi` | N/A | N/A | N/A | ⚠️ Not available (v1.0 — needs improve()) |
| `macd` | N/A | N/A | N/A | ⚠️ Not available (v1.0 — needs improve()) |
| `bollinger_bands` | N/A | N/A | N/A | ⚠️ Not available (v1.0 — needs improve()) |

**Key finding:** SignalGenerationNode starts at v1.0 (SMA only). RSI/MACD/BB require calling `improve()` to unlock. The improvement loop is not calling `improve()` on signal nodes — they're stuck at v1.0.

### 1.5 Node Registry

**91 nodes registered in state DB** (7 copies of each node type from repeated runs):

Active node types: DataIngestionNode, SignalGenerationNode, StrategyNode, RiskManagementNode, ReportingNode, VerificationNode, PropertyTestNode, LintNode, InvariantDiscoveryNode, DataIntegrityNode, ConvergenceMonitorNode, SignalResearchNode, DashboardNode

In-memory registry (fresh startup): 5 nodes (VictoriaNode, ReasoningNode, ReflectionNode, CalculatorNode, TextAnalyzerNode)

VictoriaNode capabilities: `poll, fetch_market_data, compute_signals, construct_portfolio, backtest_strategy, rank_signals, data_ingestion, signal_research, strategy, risk_management, verification, memory, improvement, adversarial`

### 1.6 Attention Router

8 adversarial_results records in state DB. All `ring=1`, `flagged=0`, `max_disagreement=0.0`. The attention router is running but Ring 1 is passing clean with no disagreements. No Ring 2/3 activity detected.

**Concern:** All results show empty failure_cases and 0 max_disagreement — either the adversarial scenarios are trivially passing, or the ring runner isn't generating meaningful test cases.

### 1.7 Memory System

```
episodes:          44   (type breakdown: cycle_summary, portfolio_decision, top_signals)
semantic_memories:  0   ← NEVER CONSOLIDATED
memory_ratings:     0   ← NO FEEDBACK WRITTEN BACK
```

Episodes were written at cycle=0 (all from a single run). Importance scores: 0.7–0.8. The consolidation batch job has never been triggered — no semantic memories exist despite 44 episodes.

### 1.8 Adversarial System

**18 open challenges** in challenge registry, severity breakdown:

| Severity | Count | Examples |
|----------|-------|---------|
| CRITICAL | 1 | IterDRAG hallucination → SemanticMemory propagation |
| HIGH | 3 | BOCPD OOM growth, VCG rational-agent assumption, constitutional enforcement gap |
| MEDIUM | 1 | Skill versioning/compatibility contracts |

**8 adversarial_results** — all Ring 1, all passing. No Ring 2 or Ring 3 runs recorded.

---

## Part 2 & 3: Node Intelligence Audit

### Per-Node Assessment Matrix

| Node | Has Memory | Brain/LLM | Autonomy Level | Signal Bus | Debate Gate | Gap |
|------|-----------|-----------|----------------|-----------|------------|-----|
| **CalculatorNode** | ❌ None | ❌ | **L1** — stateful (cache, counters) | ❌ | ❌ | No learning from calculation outcomes |
| **TextAnalyzerNode** | ❌ None | ❌ | **L1** — sequential feature unlock | ❌ | ❌ | No concept of text quality feedback |
| **WebFetcherNode** | ❌ None | ❌ | **L1** — learns retry/cache via feedback | ❌ | ❌ | No memory of which URLs are reliable |
| **DashboardNode** | ❌ None | ❌ | **L2** — self-evaluates, generates improvement reports | ❌ | ❌ | Monitoring only; can't act on findings |
| **SkillCreatorNode** | ❌ None | ⚠️ declares `research` tag | **L1** — pure factory | ❌ | ❌ | No memory of which skills work |
| **DevilsAdvocateNode** | ✅ ChallengeRegistry | ❌ rule-based | **L3** — system veto, challenge tracking | ❌ | ✅ implements | Challenges never LLM-generated; rule-based only |
| **VictoriaNode** | ✅ delegates to subsystems | ✅ optional (BrainConfig) | **L3** — IC-weighted signals, 3 autonomy modes | ✅ publishes | ✅ delegates to DebateGate | IC learning works; brain is optional/off by default |
| **SignalGenerationNode** | ❌ None | ❌ | **L1** — feature unlock (v1.0→v1.3) | ❌ | ❌ | **Stuck at v1.0 — improve() never called** |
| **DataIngestionNode** | ❌ None | ❌ | **L1** — caches, data source health | ❌ | ❌ | No memory of data source quality history |
| **StrategyNode** | ✅ stores trade history | ✅ optional | **L2-L3** — Kelly + regime + debate gate | ✅ reads peers | ✅ DebateGate | No episodic memory integration |
| **RiskManagementNode** | ❌ None | ❌ | **L1-L2** — rule-based structural validation | ❌ | ✅ receives checks | Thresholds static; don't adapt to regime |
| **DynamicWeightAllocator** | ✅ IC history | ❌ | **L2** — Bayesian online IC estimation | ❌ | ❌ | IC estimated per-signal but not per-regime |
| **ReasoningNode** | ✅ reads MemoryBus | ✅ QUICK tier | **L3** — LLM + memory context | ❌ | ❌ | Doesn't write back reasoning outcomes to memory |
| **ReflectionNode** | ✅ writes both (MemoryKernel + MemoryBus) | ✅ QUICK tier | **L3** — LLM reflection + episodic storage + cross-project sharing | ❌ | ❌ | Memory never consolidated; no semantic distillation |
| **EdgeDetectionNode** | ✅ persists to DB | ❌ | **L2** — Kelly fractions, threshold learning | ❌ | ❌ | Doesn't read Victoria's regime insights yet |
| **WeatherEnsembleNode** | ✅ model performance | ❌ | **L2** — ensemble weight learning, calibration | ❌ | ❌ | Isolated from Victoria's risk signals |
| **SignalResearchNode** | ✅ reads episodes | ✅ QUICK tier | **L3** — LLM hypothesis generation from history | ❌ | ❌ | Hypotheses not tested against live data automatically |
| **InvariantDiscoveryNode** | ❌ None | ✅ optional | **L3** — LLM invariant discovery | ❌ | ❌ | Discoveries not persisted to SemanticMemory |
| **LiquidationCascadeNode** | ✅ history | ❌ | **L2** — learns cascade patterns | ❌ | ❌ | Cascade learnings not cross-asset |
| **All Pure Signal Nodes** (14 nodes: MarketData, OrderFlow, CrossAsset, Micro, Sentiment, VRP, OnChain, LongShort, BTCDominance, AltData, Macro, News, Options, Derivatives) | ❌ None | ❌ | **L0-L1** — stateless computation | ❌ | ❌ | No regime awareness, no learning, no feedback |
| **CleanerNodes** (DataIntegrity, Lint, PropertyTest, Convergence, Verification) | ❌ None | ❌ | **L2** — validation + suggestions | ❌ | ❌ | Violations not stored for trend analysis |

### Detailed Analysis

#### Memory Architecture (Current State)
```
MemoryKernel (episodic):
  - 44 episodes written, never consolidated
  - Consolidation batch: UNSCHEDULED
  - Importance decay: NOT IMPLEMENTED
  - SemanticMemory: EMPTY

MemoryBus (cross-project):
  - ReflectionNode writes regime insights (conviction > 0.5)
  - EdgeDetectionNode does NOT yet read from it
  - TTL set (7 days) but no cleanup job runs

SignalBus (inter-node):
  - VictoriaNode publishes after each compute_signals()
  - StrategyNode reads peer signals
  - In-memory only: lost on restart
```

#### Reasoning Architecture (Current State)
```
Brain integration:
  - brain_executions table: 0 records (LLM never called in a live cycle)
  - ReasoningNode: optional brain, NoBrain by default
  - ReflectionNode: optional brain, NoBrain by default
  - System runs in NoBrain mode — all "LLM reasoning" is actually rule-based fallback

Improvement engine:
  - improvement_log: 0 records (improve() never called on nodes)
  - SignalGenerationNode: stuck at v1.0, RSI/MACD/BB never unlocked
  - Orchestrator: not wiring improve() calls into the cycle
```

#### Critical Infrastructure Gaps
```
1. Consolidation not scheduled → episodic memory accumulates endlessly
2. improve() not called from orchestrator → no node ever self-improves at runtime
3. Brain defaults to NoBrain → all LLM features are silently disabled
4. Ring 2/3 adversarial never runs → only Ring 1 structural checks active
5. MemoryBus TTL not enforced → no cross-project memory cleanup
```

---

## Part 4: Top 3 Quick Win Opportunities

### Quick Win #1: Wire the Memory Consolidation Loop

**Node:** ReflectionNode → MemoryConsolidationNode
**Problem:** 44 episodes written, 0 semantic memories. Every cycle writes but nothing is ever learned.
**Impact:** HIGH — enables actual learning from trading outcomes; prevents unbounded DB growth.

**Proposed change in `omega/core/orchestrator.py`:**
```python
# After every N cycles (e.g., 10), trigger consolidation
if self._cycle_count % 10 == 0:
    consolidator = MemoryConsolidationNode()
    await consolidator.consolidate(self._memory_kernel)
    logger.info(f"Memory consolidated at cycle {self._cycle_count}")
```

**Why this matters:** Without consolidation, the system can't learn. ReasoningNode reads MemoryBus insights, but those insights come from ReflectionNode which can only produce shallow per-trade reflections — it can't synthesize "across 50 trades, the pattern is X" without semantic memory.

---

### Quick Win #2: Enable `improve()` in the Orchestrator Loop

**Node:** SignalGenerationNode (and all other improveable nodes)
**Problem:** SignalGenerationNode is permanently at v1.0 — only SMA signals. RSI, MACD, Bollinger Bands are implemented but locked behind `improve()`.
**Impact:** HIGH — immediate signal diversity increase from 1 indicator to 4+.

**Proposed change in `omega/core/orchestrator.py`:**
```python
# After each improvement cycle (e.g., every 5 cycles or when feedback metric drops)
IMPROVEMENT_INTERVAL = 5
if self._cycle_count % IMPROVEMENT_INTERVAL == 0:
    for node in self._registry.all_nodes():
        if hasattr(node, 'improve') and node.health >= 0.8:
            improved = node.improve(self._last_cycle_metrics)
            if improved:
                logger.info(f"Node {node.node_id} self-improved to {node.get_state().version}")
```

**Why this matters:** The entire improvement engine architecture exists but is dormant. SignalGenerationNode has a clear v1.0 → v1.3 upgrade path that just needs to be triggered. The IC-based DynamicWeightAllocator can immediately start learning IC values for RSI/MACD signals once they're unlocked.

---

### Quick Win #3: Connect EdgeDetectionNode to Victoria's MemoryBus

**Nodes:** ReflectionNode (Victoria) ↔ EdgeDetectionNode (Polymarket)
**Problem:** The cross-project memory bus architecture exists but the connection is one-sided. Victoria writes regime insights; Polymarket doesn't read them.
**Impact:** MEDIUM-HIGH — Polymarket edge sizing could immediately benefit from Victoria's regime awareness.

**Proposed change in `omega/nodes/polymarket/edge_detection.py`:**
```python
# In EdgeDetectionNode.detect() or _calculate_kelly_fraction()
from omega.core.memory_bus import MemoryBus, MemoryType

def _get_regime_adjusted_kelly(self, base_kelly: float) -> float:
    """Adjust Kelly fraction based on Victoria's regime insights."""
    bus = MemoryBus()
    insights = bus.read(
        types=[MemoryType.REGIME_INSIGHT, MemoryType.RISK_WARNING],
        min_relevance=0.4,
        limit=3
    )

    if not insights:
        return base_kelly

    # High vol / risk warning → reduce sizing
    has_risk_warning = any(i.memory_type == MemoryType.RISK_WARNING for i in insights)
    avg_relevance = sum(i.relevance_score for i in insights) / len(insights)

    # Victoria's conviction in its regime insight modulates our sizing
    adjustment = 1.0 - (avg_relevance * 0.3 if has_risk_warning else 0.0)
    return min(base_kelly * adjustment, 0.25)  # cap at 25%
```

**Why this matters:** Victoria already writes regime insights after every high-conviction trade. Polymarket is making binary prediction bets with no awareness of macro risk conditions. A simple read of the MemoryBus would let Polymarket reduce sizing during high-volatility crypto regimes — exactly the kind of cross-domain learning the architecture was designed for.

---

## Summary: Where We Are vs. Where We Need to Be

### Autonomy Distribution
```
L0 (Pure function):       14 nodes  (all individual signal type nodes)
L1 (Stateful):             6 nodes  (Calculator, Text, Web, DataIngestion, SkillCreator, SignalGen)
L2 (Memory):               8 nodes  (Dashboard, Victoria, Strategy, Dynamic, Edge, Weather, Liquidation, Signal types)
L3 (Reasoning):            6 nodes  (Reasoning, Reflection, DevilsAdvocate, SignalResearch, Invariant, Victoria w/brain)
L4 (Autonomous):           0 nodes  ← none yet
```

### Biggest Architectural Gaps

| Gap | Severity | Fix Complexity |
|-----|----------|---------------|
| Memory consolidation never runs | CRITICAL | Low — 10 lines in orchestrator |
| `improve()` never called → all nodes stuck at v1.0 | HIGH | Low — 10 lines in orchestrator |
| Brain defaults to NoBrain → LLM features silently disabled | HIGH | Medium — needs API key config + orchestrator wiring |
| Ring 2/3 adversarial never triggered | HIGH | Medium — needs scenario bank + scheduled trigger |
| MemoryBus is one-directional (Victoria writes, Polymarket doesn't read) | MEDIUM | Low — 20 lines in edge_detection.py |
| No L4 (truly autonomous) nodes | MEDIUM | High — requires goal-setting + action initiation architecture |
| SignalResearchNode hypotheses not auto-tested | MEDIUM | High — needs backtest integration loop |

### System Current Reality Check
- **Intelligence exists in design but not in execution.** The architecture for L3-L4 autonomy is fully specified: brain tiers, memory bus, episodic/semantic storage, debate gate, improvement engine. But the orchestrator loop doesn't call any of it.
- **The nodes are sophisticated but dormant.** ReflectionNode can write meaningful regime insights but needs a live brain. SignalGenerationNode can self-improve to RSI+MACD+BB but needs `improve()` called. MemoryBus enables cross-project learning but needs the reader wired up.
- **Brain = NoBrain by default.** `brain_executions` table has 0 records. No LLM has ever been called in a production Victoria cycle. All "reasoning" is rule-based fallback.

### Recommended Implementation Order
1. **Immediate (1 day):** Add memory consolidation trigger + `improve()` calls to orchestrator loop
2. **Short-term (2-3 days):** Wire EdgeDetectionNode to read Victoria's MemoryBus insights
3. **Medium-term (1 week):** Configure a real BrainConfig (claude-haiku-4-5 for QUICK tier) and enable it for ReasoningNode + ReflectionNode
4. **Longer-term (2+ weeks):** Trigger Ring 2/3 adversarial scenarios; build L4 autonomous initiation for VictoriaNode
