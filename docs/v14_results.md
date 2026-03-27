# V14 Results

**Date:** 2026-03-27
**Cycles completed:** 70 of 100 (snapshot; training continues in background)
**Script:** `scripts/run_v14.py --cycles 100 --sleep 30`
**Data source:** CoinGecko API key present; DATABASE_URL not set → SQLite fallback
**Commit:** `251be80` (feat: V13 full measurement + V14 fixes)

---

## Summary

V14 stacks all V13 fixes plus the conviction_distribution patch. Trading performance
continues improving from V12→V13→V14. The DB-level intelligence score (0.51) has not
changed because `system_metrics` writes require the evaluation framework with DATABASE_URL —
a known gap documented below.

---

## A. Fixes Applied (V14 = V13 + Fix 4)

| Fix | Description | Status |
|-----|-------------|--------|
| Fix 1 | Meta-model regularization: `n_estimators=50`, `min_samples_leaf=10`, `max_features='sqrt'` | ✅ Applied |
| Fix 2 | IC weight decay: `0.95*w + 0.05*(1/N)` to prevent OOS Sharpe blowout | ✅ Applied |
| Fix 3 | Semantic memory SQLite fallback (`_SqliteSemanticStore`) | ✅ Applied (see note) |
| Fix 3b | `IMPROVEMENT_INTERVAL: 50 → 10` + scheduler auto-register | ✅ Applied |
| Fix 4 | `conviction_distribution` in all `_construct_portfolio` return paths | ✅ Applied |

---

## B. Intelligence Score: V12 → V13 → V14

| Metric | V12 | V13 | V14 |
|--------|-----|-----|-----|
| DB intelligence score | **0.510** | 0.510 (same DB, no new writes) | **0.510** (same) |
| In-sample Sharpe | 0.472 | 0.472 | 0.472 |
| OOS Walk-Forward Sharpe | −3.44 | −3.56 | −3.56 |
| Completeness score | 0.500 | 0.500 | 0.500 |
| Signal coverage | 0.833 | 0.833 | 0.833 |
| Coverage rate | 1.000 | 1.000 | 1.000 |
| improve() calls | 0 | **1** | **1** |
| Semantic patterns in DB | 0 | 0 | 0 |

**Why the DB score hasn't moved:** The intelligence score in `omega_victoria.db.system_metrics`
is written by the `eval/victoria_eval.py` evaluation framework, not by the training script.
The V14 run executes `orchestrator_v2.run_one_cycle()` which writes to the paper trading
engine but does not call `run_composite_backtest()` — the function that populates `system_metrics`.
The 8 recorded iterations are all from 2026-03-22 (V12 runs).

**What V14 did improve (measurably):**

| Check | V12 | V13 | V14 |
|-------|-----|-----|-----|
| improve() fires | ❌ 0 | ✅ 1 | ✅ 1 |
| Trading PnL direction | ❌ −$67 | ✅ +$33 | ✅ **+$247** |
| Profit factor | <1.0 | 1.136 | **1.564** |
| Win rate | 25% | 45.9% (50 cycles) | 33.0% (70 cycles) |
| Closed trades | 10 | 85 | **115** |

---

## C. Trade Performance (snapshot at cycle 70 / 115 closed trades)

| Metric | V12 | V13 (50c) | V14 (70c) |
|--------|-----|-----------|-----------|
| Total closed | 10 | 85 | **115** |
| Open positions | — | 8 | 7 |
| Win rate | 25.0% | 45.9% | 33.0% |
| Total PnL | −$67.49 | +$32.50 | **+$246.66** |
| Gross profit | — | $271.97 | $684.21 |
| Gross loss | — | $239.47 | $437.55 |
| Profit factor | <1.0 | **1.136** | **1.564** |
| Long trades | 2 | 17 (20%) | 16 (14%) |
| Short trades | 8 | 68 (80%) | 99 (86%) |

---

## D. Per-Symbol PnL (V14, 70 cycles)

| Symbol | Trades | PnL | Win Rate |
|--------|--------|-----|----------|
| SOLUSDT | 12 | **+$297.56** | 50% |
| AVAXUSDT | 12 | +$7.12 | 33% |
| DOTUSDT | 14 | +$5.98 | 29% |
| XRPUSDT | 13 | +$1.03 | 46% |
| MATICUSDT | 12 | $0.00 | 0% |
| ADAUSDT | 12 | −$9.17 | 25% |
| LINKUSDT | 12 | −$9.80 | 25% |
| BNBUSDT | 13 | −$10.90 | 38% |
| ETHUSDT | 15 | **−$35.15** | 47% |

**Key findings:**
- SOLUSDT is the primary alpha driver (+$297.56, 50% WR) — strongly directional
- ETHUSDT long continues as the main drag (−$35.15) despite high win rate (47%)
  → large loss trades outweigh wins; position sizing issue or stop placement
- MATICUSDT: 0 PnL across 12 trades → all trades exit at exactly $0 (round-trip pricing)
- Strategy is heavily short-biased (99/115 short = 86%) — regime unknown, no directional filter active

---

## E. Intelligence Layer Status

| Component | State | Note |
|-----------|-------|------|
| improve() calls | 1 | Fired once at cycle ~10; SyntheticEvaluator proposed new params for VictoriaNode |
| Semantic patterns DB | 0 | SQLite fallback wired but `event_type="trading_reflection"` never written |
| Semantic patterns node | ~0 | `retrieve_episodes()` returns [] (namespace/event_type mismatch from V13) |
| OOS Sharpe | −3.56 | Deterministic computation on fixed 365-day BTC window; disconnected from training |
| Regime detection | "unknown" | Wasserstein detector returns unknown without live price history |
| Conviction distribution | wired | `_construct_portfolio` now returns `conviction_distribution` in all paths |

---

## F. Remaining Known Gaps (for V15)

1. **OOS Sharpe still −3.56** — The meta-model regularization (Fix 1) affects in-sample fitting
   but `wf_oos_sharpe` runs `walk_forward_backtest()` on fixed historical OHLCV data every
   evaluation. These are disconnected. Fix: wire the regularized meta-model into the backtest
   evaluation path, OR run 200+ evaluation cycles with DATABASE_URL to get a live OOS estimate.

2. **Semantic memory = 0** — The SQLite fallback store is implemented correctly but the
   `SemanticMemoryNode` queries `event_type="trading_reflection"` which the orchestrator
   never writes. Fix: rename orchestrator episode writes from `cycle_summary` → add a
   `trading_reflection` event or update the semantic node query filter.

3. **ETHUSDT systematic drag** — 15 trades, high win rate (47%) but negative total PnL (−$35).
   Large individual losses dominate. Fix: per-symbol stop-loss tightening or position sizing
   cap on ETHUSDT.

4. **Intelligence score disconnected from training** — The 0.51 score is only updated by
   `eval/victoria_eval.py` which requires DATABASE_URL. Fix: run training with a Postgres
   DATABASE_URL, or call `run_composite_backtest()` from within the training script.

5. **MATICUSDT zero PnL** — Every trade closes at $0. Likely a price precision or minimum
   tick size issue in the paper trading engine for this pair.

---

## G. Progress Checkpoints

| Cycle | Closed | PnL | Win Rate | improve | sem_db |
|-------|--------|-----|----------|---------|--------|
| 1 | 0 | $0 | 0% | 0 | 0 |
| 10 | 10 | +$165 | 50% | 0 | 0 |
| 20 | 29 | +$143 | 28% | 1 | 0 |
| 30 | 42 | +$193 | 29% | 1 | 0 |
| 40 | 57 | +$209 | 30% | 1 | 0 |
| 50 | 77 | +$231 | 32% | 1 | 0 |
| 60 | 94 | +$221 | 35% | 1 | 0 |
| 70 | 114 | +$247 | 33% | 1 | 0 |

**Trend:** PnL consistently positive and growing. Win rate stabilizing at 30–35%.
improve() fired once at cycle ~10-20 and did not re-trigger (scheduler cooldown).

---

## H. Files Changed in V14

| File | Change |
|------|--------|
| `omega/nodes/victoria/strategy.py` | `conviction_distribution` in all `_construct_portfolio` return paths |
| `omega/nodes/victoria/meta_model.py` | `n_estimators=50`, `min_samples_leaf=10`, `max_features='sqrt'` |
| `omega/nodes/victoria/dynamic_weights.py` | IC weight decay after each update |
| `omega/nodes/shared/semantic_memory.py` | SQLite fallback + warning logging |
| `omega/core/orchestrator_v2.py` | `IMPROVEMENT_INTERVAL=10`, scheduler auto-register |
| `scripts/run_v14.py` | New V14 training script (all fixes, v14 output files) |

---

## I. Repo Consolidation (this session)

14 stale worktree branches deleted (all contained work already present on `main`):
`charming-babbage`, `confident-bhaskara`, `determined-hertz`, `dreamy-leavitt`,
`eager-mcnulty`, `frosty-blackburn`, `funny-dhawan`, `hardcore-yonath`,
`jolly-cartwright`, `laughing-hawking`, `recursing-chebyshev`, `relaxed-shaw`,
`sad-visvesvaraya`, `suspicious-northcutt` + 8 already-merged branches.

Remaining active worktrees: `confident-merkle`, `cranky-antonelli`, `upbeat-napier`.
