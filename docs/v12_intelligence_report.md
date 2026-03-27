# V12 Intelligence Report
**Run ID:** run_20260326_001
**Generated:** 2026-03-27
**Cycles Completed:** 247 / 1000
**Status:** Completed (snapshot at cycle 247)

---

## 1. Intelligence Score Trend

Queried from `episodes` (event_type=`cycle_summary`), ordered by timestamp:

| Cycle | Score      | Sharpe | OOS Sharpe | Pipeline ms |
|-------|------------|--------|------------|-------------|
| 0     | 0.5120     | 0.4823 | −3.44      | 6073        |
| 0     | 0.5116     | 0.4808 | −3.52      | 8016        |
| 0     | 0.5119     | 0.4843 | −3.49      | 5880        |
| 0     | 0.5102     | 0.4697 | −3.58      | 8655        |
| 0     | 0.5102     | 0.4697 | −3.58      | 546         |
| 1     | 0.5102     | 0.4697 | −3.58      | 546         |
| 2     | 0.5102     | 0.4697 | −3.58      | 546         |
| 0     | 0.5092     | 0.4608 | −3.63      | 4858        |
| 0     | 0.5092     | 0.4607 | −3.63      | 7399        |

**Summary (across all cycle_summary episodes):**
- Mean score: ~0.5103
- Min score: 0.5092
- Max score: 0.5120
- Δ range: 0.0028 — **effectively flat, no learning trend**

**Key observation:** Intelligence score is plateaued in the 0.509–0.512 band. The `improved_nodes` array is empty in every recorded cycle. No self-improvement events have triggered.

Training progress tracking (training_progress.json) shows a different view of cumulative PnL (per-cycle gain, not intelligence score), rising from $0 → $347.2 by cycle 247, with win rate improving from 50% → 78%. These are **trade performance** metrics not intelligence score metrics.

---

## 2. Intelligence Check Results (8 Checks)

Derived from `system_metrics` in the most recent cycle_summary episodes:

| # | Check | Threshold | Current | Status |
|---|-------|-----------|---------|--------|
| 1 | Coverage Rate | ≥ 0.95 | 1.000 | ✅ PASS |
| 2 | Signal Coverage | ≥ 0.75 | 0.833 | ✅ PASS |
| 3 | In-Sample Sharpe | > 0.0 | 0.461–0.482 | ✅ PASS |
| 4 | Completeness Score | ≥ 0.60 | 0.500 | ❌ FAIL |
| 5 | Error Rate | < 0.05 | 0.000 | ✅ PASS |
| 6 | Indicator Count (norm.) | ≥ 1.0 | 1.000 | ✅ PASS |
| 7 | Pipeline Latency | < 5000 ms | 4858–8655 ms | ⚠️ WARN (intermittent) |
| 8 | Walk-Forward OOS Sharpe | > 0.0 | −3.44 to −3.63 | ❌ FAIL |

**PASSED: 5/8** (checks 1, 2, 3, 5, 6)
**FAILED: 2/8** (checks 4, 8)
**WARNING: 1/8** (check 7)

### Failure Detail

**Check 4 — Completeness Score (0.50, below 0.60 threshold):**
The completeness score has been pinned at exactly 0.5 across all cycles. This suggests only one of two completeness sub-components is passing (e.g. data freshness passes but signal diversity fails). The signal conviction table shows OnChain (0.55) and MeanReversion (0.58) as the lowest-conviction signals — both below the 0.60 completeness floor.

**Check 8 — Walk-Forward OOS Sharpe (−3.4 to −3.6):**
This is the critical failure. In-sample Sharpe is positive (~0.47), but the walk-forward out-of-sample Sharpe is deeply negative, indicating severe overfitting. The model generalises poorly to new data. This has been consistent across all 9 observed cycles with no improvement.

---

## 3. Trade Results

**Source:** `data/v10_trades.csv` (most recent closed trade log; `paper_trades` table requires PostgreSQL — not active in this session)

**Summary (last session):**

| Metric | Value |
|--------|-------|
| Total trades | 10 |
| Closed with PnL | 8 |
| Wins | 2 (25%) |
| Total PnL | −$67.49 |
| Average PnL per trade | −$8.44 |

**Per-Symbol Breakdown (sorted by PnL):**

| Symbol | Side | Trades | PnL |
|--------|------|--------|-----|
| ETHUSDT | long | 1 | +$8.80 |
| SOLUSDT | long | 1 | +$4.61 |
| BNBUSDT | short | 1 | −$1.00 |
| BTCUSDT | short | 1 | −$2.25 |
| XRPUSDT | short | 1 | −$5.03 |
| LINKUSDT | short | 1 | −$5.59 |
| LINKUSDT | long | 2 | −$67.04 |

**Key observation:** LINKUSDT long is the dominant loss driver (−$67.04 across 2 trades). ETH and SOL longs are the only profitable positions. The 25% win rate in the raw session contrasts with the 78% win rate reported in training_progress — the latter likely reflects a longer historical window with post-processing (e.g. sit-out filter removing zero-PnL trades from the denominator).

**Training progress view (training_progress.json, cycle 247):**
- Cumulative PnL: +$347.2
- Win rate: 78% (up from 50% at cycle 10)
- Current regime: BULL (74% confidence)
- Dominant signal: Funding (conviction 0.81)

---

## 4. Memory Quality

**Source:** `data/omega_victoria_memory.db`

| Store | Count |
|-------|-------|
| `episodes` | 44 |
| `semantic_memories` | 0 |
| `shared_memory` | N/A (table not created) |
| `node_reflections` | N/A (table not created) |

Training progress reports 224 episodic + 29 semantic patterns at cycle 247 — this is the **in-memory** state, not yet flushed to the DB (memory persistence/consolidation is lagging behind the training loop). The live DB reflects only partial persistence.

Semantic pattern extraction is working (training log shows patterns like "High funding rates predicted reversals in 7/10 cases" at cycle 244, "BTC dominance dips correlated with ALT rallies in 6/8 cases" at cycle 220) but the `semantic_memories` table count is 0, indicating the consolidation writer is not flushing to SQLite.

---

## 5. Node Reflection Summary

`node_reflections` table does not exist in the current schema. ReflectionNode writes to `episodes` (namespace=`victoria`) and `shared_memory` (MemoryBus). No episodic entries with event_type `reflection` were found in the DB — ReflectionNode is not being called in the V12 training loop.

**No node improvement events** were recorded in `improved_nodes` across any cycle_summary episode. The improvement engine is not firing.

---

## 6. Top 3 Actionable Improvements

### 1. Fix Walk-Forward OOS Sharpe (Critical — Check 8 FAIL)

The WF OOS Sharpe of −3.4 to −3.6 is the single largest problem. With in-sample Sharpe of +0.47 and OOS Sharpe of −3.5, the system is heavily overfit.

**Action:** Implement walk-forward window expansion — increase the training/test split ratio from its current setting and add feature regularisation. In `omega/nodes/victoria/factor_model.py`, check that the walk-forward test windows use strictly out-of-sample periods. Add a dropout rate or L2 penalty to the signal weighting in `dynamic_weights.py`. Target OOS Sharpe > 0.2 before continuing the training run.

### 2. Flush Semantic Memory to DB (Memory Consolidation Bug)

224 episodic + 29 semantic patterns are in memory (per training_progress.json) but `semantic_memories` count is 0 in the DB. Memory is being lost between runs.

**Action:** In `omega/core/memory_consolidation.py` or `omega/core/memory_bus.py`, verify the `flush()` / `consolidate()` method is being called at cycle checkpoints and that it writes to the `omega_victoria_memory.db` SQLite path. Likely the DB URL is not being passed to the MemoryBus or the consolidation interval is set too high. Add a forced flush on run completion.

### 3. Wire ReflectionNode + Enable Improvement Engine

`improved_nodes` is empty every cycle and ReflectionNode is not being invoked. The self-improvement loop is inert.

**Action:** In `omega/core/orchestrator_v2.py`, ensure `ReflectionNode.execute()` is called after each trade cycle with `trade_result`, `signals`, and `regime` context. Also audit the improvement eligibility check — the `N cycles since last improvement` guard (seen in `cycle.py:203`) may be set too conservatively (e.g. `min_cycles_between_improvements = 50`), preventing the improvement engine from ever triggering within the 247 cycles observed. Reduce to 10 cycles and observe if improvement events start appearing.
