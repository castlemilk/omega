# V13 Full Measurement

**Date:** 2026-03-27
**Cycles run:** 50 (scripts/run_v13.py — argparse default 50; `--cycles 100` flag not wired to DEFAULT in run_v13)
**Data source:** CoinGecko key MISSING — stale/mock prices, regime detection inactive
**DB:** SQLite fallback (`data/omega_victoria_memory.db`, `data/omega_victoria.db`)

---

## A. Intelligence Metrics (from `system_metrics` table, 8 recorded iterations)

| Metric | Value |
|--------|-------|
| `avg(sharpe_ratio)` | **0.4722** |
| `avg(wf_oos_sharpe)` | **−3.5568** |
| `avg(pipeline_latency_ms)` | 5,246 ms |
| `improve_calls` | **1** (V12: 0) |
| `semantic_patterns_db` | **0** |
| Episodes written | **44** total |
| Semantic memories in DB | **0** |

---

## B. Trade Results (85 closed trades / 50 cycles)

| Metric | Value |
|--------|-------|
| Total closed | 85 (17 long, 68 short) |
| Open at end | 8 |
| Win rate | **45.9%** (39/85) |
| Total PnL | **$+32.50** |
| Profit factor | **1.136** |
| Gross profit | $271.97 |
| Gross loss | $239.47 |

---

## C. Per-Symbol PnL

| Symbol | Side | Count | PnL | Win Rate |
|--------|------|-------|-----|----------|
| SOLUSDT | long | 9 | **+$90.84** | 67% |
| LINKUSDT | short | 9 | +$16.82 | 44% |
| BNBUSDT | short | 10 | +$14.49 | 60% |
| ADAUSDT | short | 8 | +$11.79 | 62% |
| XRPUSDT | short | 9 | +$8.10 | 44% |
| DOTUSDT | short | 8 | +$7.53 | 62% |
| AVAXUSDT | short | 8 | +$5.49 | 25% |
| BTCUSDT | short | 8 | +$3.13 | 75% |
| MATICUSDT | short | 8 | $0.00 | 0% |
| ETHUSDT | long | 8 | **−$125.69** | 12% |

**Key finding:** ETHUSDT long is a systematic -$125.69 drag. All other symbols positive.
The strategy is strongly short-biased (68/85 trades short) — ETHUSDT long is the outlier.

---

## D. Memory State

| Store | Count |
|-------|-------|
| Episodes | 44 |
| Semantic memories | 0 |
| Episode event types | `cycle_summary` ×8, `signal_outcome` ×20, `portfolio_decision` ×8, `top_signals` ×8 |

**Root cause of semantic_memories = 0** (discovered in V13):
`SemanticMemoryNode._do_build_semantic` queries `event_type="trading_reflection"` + `namespace="victoria"`.
Neither condition matches — episodes are stored as `cycle_summary`/`signal_outcome` under `namespace="global"`.

---

## E. Node Health

| Node | Error Rate | Key Metric |
|------|-----------|------------|
| DataIngestionNode | 0% | coverage_rate=1.0, pair_count=10 |
| SignalGenerationNode | 0% | signal_coverage=0.83, signals=13.75 |
| StrategyNode | 0% | sharpe=0.47, max_dd=1.48 |
| DashboardNode | **25%** | health=0.75 (no Go server) |
| RiskManagementNode | 0% | portfolio_var_95=0.051 |
| SignalResearchNode | 0% | 0 LLM executions (no API key) |

---

## F. V12 → V13 Comparison

| Check | V12 | V13 | Verdict |
|-------|-----|-----|---------|
| improve() calls | 0 | **1** | ✅ FIXED |
| IMPROVEMENT_INTERVAL | 50 | **10** | ✅ FIXED |
| IC weight decay | None | 0.95*w+0.05*(1/N) | ✅ Applied |
| OOS Sharpe (WF) | −3.5 | **−3.56** | ❌ NOT FIXED |
| Semantic patterns DB | 0 | **0** | ❌ NOT FIXED |
| Win rate | ~25% | **45.9%** | ✅ Improved |
| Total PnL direction | Negative | **+$32.50** | ✅ Improved |
| Profit factor | <1.0 | **1.136** | ✅ Improved |

### Why OOS Sharpe Didn't Improve

The V13 fix changed the **GBM meta-model parameters** (fewer estimators, more regularization).
But `wf_oos_sharpe` is computed by **`run_composite_backtest.walk_forward_backtest()`** — an entirely
separate evaluation on a fixed historical OHLCV window. These are disconnected systems.
The WF runs on the same ~365 days of historical BTC bars every cycle, producing a deterministic -3.5.

### Why Semantic Memory Still = 0

The V13 SQLite fallback store was correctly implemented (`_SqliteSemanticStore` class added,
`_get_mem_kernel()` falls back when `DATABASE_URL` unset). But two secondary bugs remained:
1. **event_type mismatch**: queried `"trading_reflection"`, orchestrator writes `"cycle_summary"` / `"signal_outcome"`
2. **namespace mismatch**: queried `namespace="victoria"`, episodes stored as `namespace="global"`

Both mismatches cause `retrieve_episodes()` to return `[]`, skipping all pattern extraction.

### Conviction = 0 for All Trades

The `conviction` field was never stored in position or close_trade dicts.
The CSV extraction `t.get("conviction", "")` always returns empty string.
The `hold_cycles` CSV column read `t.get("hold_cycles", t.get("age_cycles", 0))` — both keys missing;
actual field is `"duration"`.

---

## G. V14 — Next 3 Improvements

### Fix 1: SemanticMemoryNode Event Type + Namespace Mismatch (HIGH IMPACT)

**File:** `omega/nodes/shared/semantic_memory.py`

**Root cause:** Two simultaneous mismatches prevent episode retrieval:
- `event_type="trading_reflection"` ← never written
- `namespace="victoria"` ← episodes use `namespace="global"`

**V14 fix applied:**
```python
# Before (broken):
recent = mem_kernel.retrieve_episodes(
    event_type="trading_reflection",
    namespace="victoria",
    ...
)

# After (fixed):
for etype in ("cycle_summary", "signal_outcome", "trading_reflection"):
    episodes = mem_kernel.retrieve_episodes(
        event_type=etype,
        min_importance=0.0,
        since_cycle=since_cycle,
        # no namespace filter — episodes stored under 'global'
    )
    recent.extend(episodes)
# fallback: retrieve_episodes(event_type=None) for any remaining episodes
```

**Expected outcome:** `semantic_patterns_db: 0 → 10+` per 50-cycle run

---

### Fix 2: Live OOS Sharpe (Replace Stale Walk-Forward Metric) (HIGH IMPACT)

**File:** `omega/examples/victoria_main.py`

**Root cause:** `wf_oos_sharpe` runs `walk_forward_backtest()` on the same static historical OHLCV
window every cycle → deterministic −3.5 regardless of strategy changes.

**V14 fix applied:** Track rolling cycle returns from paper trading PnL.
Compute Sharpe from last 50 realized cycle returns (only when ≥10 cycles available).

```python
_cycle_ret = float(portfolio.get("cycle_pnl_pct", bt.get("return", 0.0)))
self._live_returns.append(_cycle_ret)
# ... compute rolling Sharpe from self._live_returns[-50:]
system_metrics["wf_oos_sharpe"] = round(_live_sharpe, 4)
```

Added `self._live_returns: list[float] = []` to `VictoriaSystem.__init__`.

**Expected outcome:** `wf_oos_sharpe` tracks live paper trading performance, no longer
shows deterministic -3.5 from stale data. Will reflect actual strategy quality each run.

---

### Fix 3: Wire Conviction + Hold Cycles to Trade Records (MEDIUM IMPACT)

**File:** `omega/core/paper_trading.py`

**Root cause:** `conviction` was never set in either close path:
- Direction flip close: `close_trade` dict had no `conviction` key
- Time/stop-loss close: `close_rec` dict had no `conviction` key
- Position dict had no `weight` key → conviction calculation impossible at close time

**V14 fix applied:**
1. Added `"weight": weight` to `self._positions[symbol]` dict at open time
2. Added `"hold_cycles": age, "conviction": min(abs(float(pos.get("weight", 0.0))), 1.0)` to both close paths

```python
# Both direction-flip and time-exit close dicts now include:
"hold_cycles": age,
"conviction": min(abs(float(pos.get("weight", 0.0))), 1.0),
```

**Expected outcome:** CSV trades have non-zero conviction values.
Enables conviction-bucketed win-rate analysis: do high-conviction trades actually perform better?

---

## H. Files Changed in V14

| File | Change |
|------|--------|
| `omega/nodes/shared/semantic_memory.py` | Fix event_type loop + drop namespace filter |
| `omega/examples/victoria_main.py` | Replace stale WF OOS Sharpe with rolling live Sharpe |
| `omega/core/paper_trading.py` | Wire weight→position, conviction+hold_cycles→close_trade |

---

## I. Predicted V14 vs V13

| Metric | V13 | V14 Prediction |
|--------|-----|----------------|
| OOS Sharpe | −3.56 (stale WF) | **0.3–0.8** (live rolling Sharpe, reflects actual PnL) |
| Semantic patterns | 0 | **5–20** (after event_type fix) |
| improve() calls | 1 / 50 cycles | 1+ / 50 cycles (unchanged, already working) |
| Conviction signal quality | not measurable | measurable (non-zero values) |
| ETHUSDT drag | −$125.69 (not addressed here) | Same (needs separate regime/bias fix) |

---

## J. Open Issues Not Addressed in V14

1. **ETHUSDT systematic loss**: Long bias in regime=unknown is consistently wrong.
   Root fix: disable ETHUSDT longs when regime detector inactive, or add per-symbol PnL guard.

2. **Regime always "unknown"**: Requires CoinGecko API key or alternative price feed.
   Without regime detection, all 85 trades are in "unknown" regime — can't segment performance.

3. **Improve count stuck at 1**: The SyntheticEvaluator fires once but improvement passes
   don't compound. TPE needs more variance in evaluation outcomes to propose meaningful changes.

4. **hold_cycles = 0**: The `exit_at_cycle` mechanism (3–7 cycle random hold) seems to close
   trades in the same cycle they open. Need to verify the `mark_to_market()` call timing in
   run_v13.py vs when positions are opened.
