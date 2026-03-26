# Paper Trading Results — V3 1000-Cycle Training Run

**Date:** 2026-03-26
**Run location:** `.claude/worktrees/bold-mccarthy`
**Script:** `scripts/run_v3_training.py`
**Log:** `/private/tmp/v3_training.log`

---

## Run Status

| Field | Value |
|-------|-------|
| Status | **COMPLETED** ✓ (1000/1000 cycles) |
| Total elapsed | 2522.0 seconds (~42 minutes) |
| Process PID | 22863 (exited) |
| Started | 2026-03-26 12:37 AEST |
| Finished | 2026-03-26 13:19 AEST |

---

## In-Memory Metrics (from training script)

> ⚠️ These metrics are **unreliable** — see bugs section below.

| Metric | Value |
|--------|-------|
| Cycles completed | 1000 / 1000 |
| Total trades (closed_trades list) | 8,730 |
| Realised PnL | $0.00 |
| Win rate | 0.0% |
| Memories | 0 |

---

## Postgres Database Results

### `paper_trades` table (V1 baseline — unchanged)

| Metric | Value |
|--------|-------|
| Total trades | 172 |
| Closed trades | 118 |
| Open trades | 54 |
| **Total PnL** | **$27,679.57** |
| Winners | 98 |
| Losers | 20 |
| **Win rate** | **83.1%** |

#### Per-symbol breakdown (paper_trades):

| Symbol | Closed | Open | PnL | Wins | Losses | Win% |
|--------|--------|------|-----|------|--------|------|
| SOLUSDT | 59 | 27 | $18,092.03 | 49 | 10 | 83.1% |
| ETHUSDT | 59 | 27 | $9,587.54 | 49 | 10 | 83.1% |

### `victoria_trades` table (V3 run output)

| Metric | Value |
|--------|-------|
| Total trade records | 13,870 (final) |
| Winners | 0 |
| Losers | 0 |
| Break-even | 13,870 (100%) |
| **Total PnL** | **$0.00** |

#### Per-symbol directional bias (victoria_trades):

| Symbol | Primary Direction | Trade Count |
|--------|------------------|-------------|
| SOLUSDT | LONG (100%) | 1,367 |
| ETHUSDT | LONG (100%) | 1,367 |
| BTCUSDT | SHORT (100%) | 1,281 |
| BNBUSDT | SHORT (100%) | 1,281 |
| XRPUSDT | SHORT (100%) | 1,281 |
| MATICUSDT | SHORT (100%) | 1,281 |
| ADAUSDT | SHORT (100%) | 1,281 |
| AVAXUSDT | SHORT (100%) | 1,281 |
| DOTUSDT | SHORT (100%) | 1,281 |
| LINKUSDT | LONG (77%), SHORT (23%) | 1,282 |

### `episodes` table

| Metric | Value |
|--------|-------|
| Victoria signal_cycle episodes | 56 |
| Cycle range | 945–1000 |

### Other memory tables

| Table | Count |
|-------|-------|
| shared_memory | 1,113 |
| semantic_memories | (not queried) |

---

## Comparison vs Baselines

| Metric | V1 Baseline | V2 | V3 (this run) |
|--------|-------------|-----|---------------|
| Total trades | 172 | 1,810 | 13,870 (in DB) |
| Closed trades | 118 | ~952 (52.6% of 1810) | 0 with real PnL |
| Win rate | **83.1%** | 52.6% | 0.0% (broken) |
| Total PnL | **$27,679** | N/A | $0.00 (broken) |
| Memories | — | — | 0 (broken) |
| Symbols | SOL, ETH | — | 10 symbols |

---

## Critical Issues Found

### 1. Zero PnL — Directional Lock (No Position Flips)
The V3 signal stack consistently proposes the **same direction** for most symbols every cycle (e.g. SOLUSDT always LONG, BTCUSDT always SHORT). Because the `PaperTradingEngine` only realises PnL when a position **flips direction**, and most positions never flip, `realised_pnl` stays at $0.00 throughout the entire 1000-cycle run.

- LINKUSDT is the only symbol that flips (77% long / 23% short) but those direction flips produce zero PnL in the DB, suggesting the entry prices at flip time are identical (stale market data issue).

### 2. `closed_trades` List Contains Open Trades (Naming Bug)
In `PaperTradingEngine.execute_proposals()`, every **newly opened** position is appended to `self._closed_trades`:

```python
self._closed_trades.append(trade)  # BUG: this is an OPEN trade
```

The actual closed trades (from direction flips) go into `closed_from_flip` and are persisted to DB but never added to `_closed_trades`. This causes the training script's win-rate calculation to be permanently 0%:

```python
wins = sum(1 for t in pt.closed_trades if float(t.get("pnl", 0)) > 0)
# Always 0 because "closed_trades" only contains open trades with pnl=0
```

### 3. Memory Count Always 0
`_get_memory_count()` queries a table that doesn't exist:

```sql
SELECT COUNT(*) FROM episodic_memory WHERE project_id='victoria'
-- Table doesn't exist! Actual table is: episodes (with namespace column)
```

Correct query should be:
```sql
SELECT COUNT(*) FROM episodes WHERE namespace='victoria'
-- Returns 57 entries
```

### 4. Ring 1 Supervisor Blocking VictoriaNode
Ring 1 fired continuously throughout the run, blocking proposals from node `f1f9a3db-3c9c-42ad-b16c-fe9042174f9c` (VictoriaNode) due to disagreement threshold violations:

```
Ring 1 fired [cycle=733]: max_disagreement=0.598 outliers=['f1f9a3db:disagreement', 'f1f9a3db:order_flow'] threshold=0.200 learned=0.700
```

This means VictoriaNode proposals were **blocked by the supervisor** for much of the run. Trades that did execute were from unblocked cycles where disagreement fell below 0.700 learned threshold.

---

## Active Victoria Signals

| Signal | Weight | Conviction |
|--------|--------|------------|
| adv_basic_signals | 0.500 | 0.500 |
| vrp | 0.346 | 1.000 |
| SOLUSDT | 0.273 | 0.273 |
| ETHUSDT | 0.273 | 0.273 |
| adv_cross_asset | 0.273 | 0.273 |
| adv_onchain | 0.182 | 0.182 |
| on_chain | 0.134 | 0.800 |
| news | 0.091 | 0.800 |
| derivatives | 0.091 | 0.400 |
| options_microstructure | 0.065 | 1.000 |

---

## Recommendations for V4

1. **Fix `_closed_trades` bug**: Only append to `_closed_trades` when a trade is actually closed (direction flip or explicit close). Add closed trades from `closed_from_flip` to the list.

2. **Fix memory count query**: Change `episodic_memory WHERE project_id='victoria'` → `episodes WHERE namespace='victoria'`.

3. **Diagnose zero PnL on flips**: Even LINKUSDT flips show pnl=0. Investigate whether market data prices are being refreshed between cycles or if stale prices are reused.

4. **Ring 1 threshold tuning**: The 0.700 learned threshold is too aggressive — it's blocking the primary trading node nearly every cycle. Consider raising the blocking threshold or adjusting the disagreement calculation.

5. **Add more diverse signal generation**: 9 out of 10 symbols have a fixed directional bias throughout 1000 cycles. The model needs exposure to more varied market conditions to learn proper position management.

6. **Market data freshness**: Ensure each cycle fetches fresh price data to enable realistic PnL simulation. If the same prices are used every cycle, no meaningful PnL can be realized.
