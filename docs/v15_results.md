# V15 Training — Status & Intelligence Score Trend

**Date:** 2026-03-27
**Status:** IN PROGRESS — started 21:09 local, currently at cycle ~5/100
**Script:** `scripts/run_training.py --cycles 100 --sleep 30` (PID 44266)
**Log:** `/tmp/v10_training.log`
**Label in log:** "V12 Training Run" — base script, does NOT include V13/V14 fixes
**Data source:** CoinGecko key MISSING, Database URL: postgres://omega (set but may fail)

---

## Current Progress (as of ~21:13)

| Metric | Value |
|--------|-------|
| Cycles complete | ~5 / 100 |
| Open positions | 9 |
| Closed trades | 4 |
| PnL | −$8 |
| Win rate | 25% |
| Avg cycle time | ~31s |
| ETA remaining | ~49 min |

> **Note:** V15 is using the base `run_training.py` script (V12 label), NOT `run_v14.py`.
> The V13/V14 fixes (meta-model regularization, IC weight decay, conviction_distribution)
> are NOT applied in this run. This is effectively a V12 replay, not a new iteration.

---

## Intelligence Score Trend: V12 → V14

The DB intelligence score (`system_metrics` table, written by eval framework) has not
moved across any of these runs — the training scripts don't call `run_composite_backtest()`.

| Run | DB Intel Score | improve() | sem_db | PnL | PF | WR | Cycles |
|-----|---------------|-----------|--------|-----|----|----|--------|
| V12 | **0.510** | 0 | 0 | −$67 | <1.0 | 25% | ~100 |
| V13 | 0.510 | **1** | 0 | +$33 | 1.14 | 46% | 50 |
| V14 | 0.510 | **1** | 0 | **+$299** | **1.51** | 38% | 100 |
| V15 | — | — | — | IN PROG | — | — | 100 |

**Is it trending up?**
- DB intelligence score: **FLAT at 0.510** — stuck because eval framework not integrated
- Trading performance: **YES — clear upward trend** V12→V13→V14
  - PnL: −$67 → +$33 → +$299 (+$366 net swing over 3 runs)
  - Profit factor: <1.0 → 1.14 → **1.51**
  - improve() firing: 0 → 1 → 1 (at least triggered)

**User-cited scores (from docs/v12_intelligence_report.md):**
- V12: 0.51 ✅ confirmed (5/8 checks: coverage, signal_coverage, sharpe, error_rate, indicator_count)
- V13: 0.51 (no change — eval framework not run, same 8 rows from 2026-03-22)
- V14: 0.51 (no change — same root cause)
- V15: N/A (run in progress)

---

## Intelligence Check Scores (static — from V12 DB rows, last written 2026-03-22)

| # | Check | Status |
|---|-------|--------|
| 1 | Coverage Rate ≥ 0.95 | ✅ PASS (1.00) |
| 2 | Signal Coverage ≥ 0.75 | ✅ PASS (0.83) |
| 3 | In-sample Sharpe > 0.0 | ✅ PASS (0.472) |
| 4 | Completeness Score ≥ 0.60 | ❌ FAIL (0.500) |
| 5 | Error Rate < 0.05 | ✅ PASS (0.000) |
| 6 | Indicator Count ≥ 1.0 | ✅ PASS (1.000) |
| 7 | Pipeline Latency < 5000ms | ⚠️ WARN (intermittent, 4858–8655ms) |
| 8 | Walk-Forward OOS Sharpe > 0.0 | ❌ FAIL (−3.44 to −3.63) |

**Score: 5/8 = 0.625 (unchanged across all runs)**

---

## New Signals (carry, pairs): Not Present

- `signal_ics.json` contains only: `volume_signal: 0.030`
- Memory episode `top_signals` shows discrete ±1.0 values only (5 symbols)
- No carry trade signal, no pairs trading signal detected in any run
- Signal names in V14 node: `momentum`, `volume`, `mean_reversion`, `regime_filter`, `vrp`

---

## Memory State (omega_victoria_memory.db)

| Store | Count |
|-------|-------|
| Episodes | 44 (all from V12/V13 runs 2026-03-22) |
| Semantic memories | **0** (root cause: namespace/event_type mismatch) |

Memory is NOT being written by V14/V15 training runs — new runs use in-process state,
episodes in the persistent DB are all from earlier eval framework runs.

---

## Key Gaps to Address

1. **DB intel score stuck at 0.510**: Wire `run_composite_backtest()` into training loop,
   or add `eval_intelligence()` call every N cycles
2. **OOS Sharpe = −3.5**: Critical failure. IC weight decay (Fix 2) was applied but hasn't
   moved the needle. Requires shorter lookback or walk-forward rewrite
3. **Semantic memory = 0**: Fix namespace ("victoria" not "global") and event_type filter
4. **V15 script is V12**: Should use `run_v14.py` or create `run_v15.py` with new features
5. **Ring 1 adversarial gate fires every cycle**: VRP disagreement ~0.50 vs threshold 0.20
   blocks autonomy — investigate VRP signal calibration
