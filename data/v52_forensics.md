# V52 Training Run — Deep Forensics

## Executive Summary

V52 failed all critical gates with total PnL of **-$55.90** vs. V51 baseline +$5.76 (Δ -$61.66). The run was catastrophically damaged by **22 LONG trades placed in the crisis regime** totaling -$100.62 — despite the crisis regime being a bear/high-stress market context where longs should be suppressed. Conviction scores were robotically compressed into a 0.050–0.075 band with zero discriminative power (winner mean: 0.060, loser mean: 0.059), meaning the conviction filter passed bad trades as readily as good ones. A secondary failure was **DOTUSDT short-biased entries in the normal regime** generating -$21.51 across 13 trades (7% win rate). MATICUSDT produced 27 trades with PnL = exactly $0.00 (entry price = exit price), indicating a broken paper-trading execution path for that ticker.

---

## Gate Results

| Gate | Result | V52 | V51 Baseline | Delta |
|---|---|---|---|---|
| pnl_floor | FAIL | -$55.90 | +$5.76 | -$61.66 |
| regime_parity[crisis] | FAIL | -$89.53 | -$24.59 | -$64.94 |
| regime_parity[normal] | FAIL | -$4.71 | +$45.31 | -$50.02 |
| regime_parity[high_vol] | PASS | +$4.93 | -$14.97 | +$19.90 |
| drawdown_ceiling | PASS | 0.0 | 0.0 | — |
| trade_count_floor | PASS | 85 trades | 101 trades | — |
| signal_integrity | PASS | — | — | — |
| auto_apply_audit | PASS | — | — | — |

Note: Gate file labels "v48" but actually compares against v51 (the stored baseline at gate evaluation time).

---

## Per-Symbol PnL

| Symbol | Trades | Win Rate | Total PnL | Avg PnL |
|---|---|---|---|---|
| ETHUSDT | 37 | 43% | **-$54.65** | -$1.48 |
| AVAXUSDT | 3 | 0% | **-$23.36** | -$7.79 |
| DOTUSDT | 24 | 21% | **-$10.42** | -$0.43 |
| LINKUSDT | 22 | 27% | -$0.88 | -$0.04 |
| MATICUSDT | 27 | 0%* | **$0.00** | $0.00 |

*MATICUSDT: all 27 trades closed at exactly entry price ($0.00 PnL) — paper trading execution is broken for this symbol (entry_price == exit_price in all cases, indicating price lookup is returning the same stale value on open and close).

---

## Per-Regime Breakdown

| Regime | Trades | Win Rate | Total PnL | Avg PnL | Notes |
|---|---|---|---|---|---|
| crisis | 43 | 14% | **-$89.53** | -$2.08 | Primary failure driver |
| normal | 62 | 31% | -$4.71 | -$0.08 | Shorts crushing longs |
| high_vol | 8 | 25% | **+$4.93** | +$0.62 | Only profitable regime |

### Crisis regime sub-breakdown (by direction):
- Crisis LONGS: n=22, total **-$100.62** (catastrophic)
- Crisis SHORTS: n=21, total **+$11.09** (correct direction)

### Normal regime sub-breakdown (by direction):
- Normal LONGS: n=35, total **+$16.80**, WR=49% (working correctly)
- Normal SHORTS: n=27, total **-$21.51**, WR=7% (DOTUSDT short bias broken)

---

## Per-Regime per-Symbol Detail (sorted by PnL)

| Regime | Symbol | Trades | Win Rate | Total PnL |
|---|---|---|---|---|
| crisis | ETHUSDT | 14 | 14% | **-$68.77** |
| normal | DOTUSDT | 13 | 15% | **-$21.51** |
| crisis | AVAXUSDT | 1 | 0% | **-$18.08** |
| crisis | LINKUSDT | 7 | 14% | **-$13.77** |
| normal | AVAXUSDT | 2 | 0% | -$5.27 |
| crisis | MATICUSDT | 12 | 0%* | $0.00 |
| normal | MATICUSDT | 14 | 0%* | $0.00 |
| high_vol | LINKUSDT | 1 | 0%* | $0.00 |
| high_vol | DOTUSDT | 2 | 0%* | $0.00 |
| high_vol | MATICUSDT | 1 | 0%* | $0.00 |
| high_vol | ETHUSDT | 4 | 50% | **+$4.93** |
| crisis | DOTUSDT | 9 | 33% | **+$11.09** |
| normal | LINKUSDT | 14 | 36% | **+$12.89** |
| normal | ETHUSDT | 19 | 63% | **+$9.18** |

*Zero-PnL rows include MATICUSDT execution bug; high_vol zero rows are likely also execution artifacts.

---

## Conviction Distribution

**Critical finding: All trade conviction scores fall within 0.050–0.075. The filter provides zero discriminative power.**

| Conviction Bucket | Trades | Win Rate | Total PnL | Avg PnL |
|---|---|---|---|---|
| 0.050–0.075 (all) | 113 | 24% | -$89.31 | -$0.79 |

All 113 trades fall in a single bucket. The conviction range is robotically compressed:
- Min: 0.050, Max: 0.075, Mean: 0.059, Median: 0.058

Winner conviction mean: **0.060** | Loser conviction mean: **0.059** (Δ = 0.001 — statistically meaningless)

This means the conviction threshold (somewhere around 0.05) is far too low — it is passing nearly all generated signals indiscriminately, and there is no relationship between conviction magnitude and trade outcome.

---

## Hold Duration Analysis

All trades hold between 3–7 cycles (mean: 5.0, median: 5). No flexibility in hold duration.

| Hold Duration | Trades | Win Rate | Total PnL | Avg PnL |
|---|---|---|---|---|
| 2-3 cycles | 23 | 17% | -$15.57 | -$0.68 |
| 4-5 cycles | 40 | 28% | -$20.37 | -$0.51 |
| 6-10 cycles | 50 | 24% | -$53.37 | -$1.07 |

Longer holds are worse (-$1.07/trade vs -$0.51/trade for 4-5 cycles). All hold durations are losing. The fixed exit-after-N-cycles strategy has no edge.

---

## Filter Hit Analysis

From 172 valid JSONL cycles:

### Trade Action Counts
| Action | Cycles | % |
|---|---|---|
| HOLD | 114 | 66% |
| TRADE | 58 | 34% |
| SIT_OUT | 0 | 0% |

### Regime Distribution (JSONL)
| Regime | Total Cycles | Cycles with New Trades | Trade Rate |
|---|---|---|---|
| crisis | 59 | 21 | 36% |
| high_vol | 15 | 5 | 33% |
| normal | 98 | 32 | 33% |

**Key finding**: Crisis cycles see 36% new trade rate — the system is trading into crisis nearly as often as normal regime. Crisis longs are being placed without suppression.

### Composite Score: Trade vs No-Trade Cycles
- When TRADE placed: composite mean = **+0.0348** (min -0.0964, max +0.1870)
- When NO TRADE placed: composite mean = **+0.0213** (min -0.1122, max +0.1950)

Composite score difference is tiny (0.013 spread) and both populations overlap heavily — the filter is barely discriminating on composite score either.

### Vol Rank
`vol_rank` is **null in 100% of cycles** (172/172). The volatility ranking signal is completely broken/disconnected.

### Active Signals
Always exactly 20 signals active — no signal dropout, but also no variation, suggesting signals may be returning stale values.

---

## Top 10 Worst Trades

| Cycle | Symbol | Side | PnL | Regime | Hold | Conviction |
|---|---|---|---|---|---|---|
| 16 | AVAXUSDT | long | -$18.08 | crisis | 5 | 0.057 |
| 106 | DOTUSDT | short | -$12.79 | normal | 5 | 0.055 |
| 16 | ETHUSDT | long | -$11.10 | crisis | 3 | 0.069 |
| 23 | ETHUSDT | long | -$10.34 | crisis | 6 | 0.058 |
| 31 | DOTUSDT | short | -$9.02 | crisis | 6 | 0.058 |
| 171 | DOTUSDT | short | -$8.66 | normal | 6 | 0.056 |
| 177 | DOTUSDT | short | -$8.63 | normal | 4 | 0.056 |
| 86 | ETHUSDT | long | -$8.54 | crisis | 7 | 0.059 |
| 8 | ETHUSDT | long | -$7.69 | crisis | 7 | 0.069 |
| 12 | ETHUSDT | long | -$6.65 | crisis | 3 | 0.069 |

**Pattern**: 7 of 10 worst trades are either (a) crisis-regime longs on ETHUSDT/AVAXUSDT, or (b) normal-regime DOTUSDT shorts. These two patterns account for -$82.99 of the top-10 worst loss total.

---

## Top 10 Best Trades

| Cycle | Symbol | Side | PnL | Regime | Hold | Conviction |
|---|---|---|---|---|---|---|
| 53 | DOTUSDT | short | +$13.19 | normal | 4 | 0.056 |
| 157 | LINKUSDT | long | +$12.96 | normal | 4 | 0.059 |
| 18 | DOTUSDT | short | +$10.81 | crisis | 5 | 0.069 |
| 184 | DOTUSDT | short | +$8.58 | normal | 3 | 0.055 |
| 41 | ETHUSDT | long | +$6.59 | normal | 4 | 0.063 |
| 177 | LINKUSDT | long | +$6.51 | normal | 6 | 0.059 |
| 60 | LINKUSDT | long | +$6.46 | normal | 5 | 0.059 |
| 35 | LINKUSDT | long | +$6.39 | normal | 6 | 0.058 |
| 41 | LINKUSDT | long | +$6.37 | normal | 6 | 0.058 |
| 7 | LINKUSDT | long | +$5.48 | crisis | 6 | 0.050 |

**Pattern**: Best trades are normal-regime LINKUSDT longs and DOTUSDT shorts (when the direction is right). LINKUSDT long in normal regime is the cleanest edge in the book.

---

## PnL Trajectory

| Cycle Range | Period PnL | Cumulative PnL |
|---|---|---|
| 1–20 | -$29.98 | -$29.98 |
| 21–40 | -$30.22 | -$60.21 |
| 41–60 | +$22.19 | -$38.01 |
| 61–80 | -$17.31 | -$55.32 |
| 81–100 | -$13.02 | -$68.34 |
| 101–120 | -$16.20 | -$84.54 |
| 121–140 | -$0.71 | -$85.25 |
| 141–160 | -$0.40 | -$85.65 |
| 161–180 | -$15.32 | -$100.97 |
| 181–200 | +$11.66 | -$89.31 |

**Pattern**: The run was destroyed in the first 40 cycles (-$60.21), primarily from crisis-regime long trades. Cycles 41-60 showed a rare recovery (+$22.19) when the system caught the correct direction. The mid-run (80-140) bled slowly from DOTUSDT shorts. Late losses (161-180) from another DOTUSDT shorting streak.

Crisis regime cycles span: 6-8, 11-28, 56, 68-70, 73-87, 119-137 — heavily concentrated in the early run, explaining the early crash.

---

## Root Cause Hypotheses

### Hypothesis 1 — Crisis regime long suppression is ABSENT (confidence: VERY HIGH)
**Evidence**: 22 long trades placed in crisis regime totaling -$100.62. Crisis shorts totaled +$11.09 — the system correctly identifies bearish direction for some signals, but fails to suppress longs. The V50 ETHUSDT long momentum gate (the last attempted fix) was reverted in V52 (commit `d9ae8904`). The revert removed the only protection against crisis-regime longs.
**Impact**: -$100.62 directly attributable.

### Hypothesis 2 — Conviction threshold too low, no discriminative power (confidence: VERY HIGH)
**Evidence**: All 113 trades have conviction 0.050–0.075. The threshold appears to be set near 0.05 (the minimum observed). Winner mean conviction (0.060) vs. loser mean (0.059) is a 0.001 difference — noise level. The conviction filter is letting through essentially all signals that pass the composite score check.
**Impact**: No trades are being blocked on quality grounds; every signal that passes regime/agreement filters gets executed.

### Hypothesis 3 — DOTUSDT short signal is structurally broken in normal regime (confidence: HIGH)
**Evidence**: 13 DOTUSDT short trades in normal regime: WR=15%, total -$21.51. The signal consistently picks the wrong direction — shorting during a period when DOTUSDT is trending up. The best DOTUSDT trade (cycle 53, +$13.19) was a short during a brief downturn, but the majority of subsequent DOT shorts lost heavily. A short-bias signal for DOT is not edge in a normal/bull environment.
**Impact**: -$21.51 directly attributable.

### Hypothesis 4 — MATICUSDT paper trading execution is broken (confidence: HIGH)
**Evidence**: 27 MATICUSDT trades all closed at exactly entry_price, producing $0.00 PnL. The price at entry and exit is always identical (0.3794 in the sample). This indicates the paper trading engine is either: (a) looking up price at a stale timestamp for both entry and exit, or (b) MATICUSDT's price feed is returning a single cached value throughout. These trades consume 27 trade slots (24% of all trades) and signal budget, producing zero alpha.
**Impact**: 27 wasted trade slots; potential signal budget distortion.

### Hypothesis 5 — vol_rank is completely disconnected (confidence: HIGH)
**Evidence**: vol_rank is null in 100% of 172 cycles. The volatility ranking filter that was designed to gate low-vol environments never fires because the metric is never computed. This means the `vol_low_threshold` (0.2) has no effect.
**Impact**: Low-conviction cycles in low-vol environments are not filtered out; noise trades pass through.

### Hypothesis 6 — Composite score has no signal in crisis (confidence: MEDIUM)
**Evidence**: Crisis regime composite score mean = -0.019 (37% positive cycles) but the system still places trades in 36% of crisis cycles including longs. The composite score going negative in crisis should suppress longs, but the per-symbol conviction translation is not regime-aware.
**Impact**: Negative composite score cycles generate long trades, compounding the crisis long problem.

### Hypothesis 7 — AVAXUSDT has zero win rate and outsized losses (confidence: MEDIUM)
**Evidence**: 3 AVAXUSDT trades, 0% WR, -$23.36 total. Worst single trade is AVAXUSDT long in crisis (-$18.08). Small sample but the symbol may have high-volatility without any working signal.
**Impact**: -$23.36 from 3 trades = -$7.79/trade average — worst per-trade loss ratio of all symbols.

---

## V53 Fix Proposals

### Fix 1 — Hard-block longs in crisis regime (PRIORITY: CRITICAL)
**Target**: `omega/nodes/victoria/strategy.py` — `_passes_conviction_filters`
**Action**: Reinstate and strengthen the crisis long block. In crisis regime (bear_prob >= 0.55 OR regime == 'crisis'), set `long_threshold = 999.0` (impossible to pass) OR add an explicit `if regime == 'crisis' and side == 'long': return False` gate before any threshold check.
**Rationale**: Crisis longs cost -$100.62 in V52. The V50 gate was correct and should never have been reverted without a regression test ensuring it stays in.
**Expected impact**: +$80-100 recovery. Crisis shorts (+$11.09) should be preserved.

### Fix 2 — Raise conviction threshold to create actual discrimination (PRIORITY: CRITICAL)
**Target**: `omega/nodes/victoria/strategy.py` — regime-adaptive thresholds
**Action**: Raise the minimum conviction threshold from ~0.05 to at least 0.15 in normal regime and 0.20 in high-vol. Current range 0.050–0.075 shows zero predictive power. The threshold needs to be in the range where discrimination exists. Alternatively, normalize conviction to 0-1 scale using historical distribution so that 0.05 is not near the 90th percentile.
**Rationale**: Winner/loser conviction is identical at current thresholds. Filter is passing all signals.
**Expected impact**: 40-60% reduction in trade count; higher quality trades only.

### Fix 3 — Disable or gate DOTUSDT short entries in normal regime (PRIORITY: HIGH)
**Target**: `omega/nodes/victoria/strategy.py` or DOTUSDT-specific signal weighting
**Action**: Add a `normal/DOTUSDT/short` block: if regime == 'normal' and symbol == 'DOTUSDT' and side == 'short', require conviction >= 0.25 (vs. the standard threshold). Alternatively, audit the signal that is generating short signals for DOT in bull/normal conditions and fix the signal direction logic.
**Rationale**: 13 normal-regime DOT shorts: WR=15%, total -$21.51. The signal is consistently wrong in direction.
**Expected impact**: +$15-20 recovery.

### Fix 4 — Fix MATICUSDT paper trading execution (PRIORITY: HIGH)
**Target**: `omega/core/paper_trading.py` or `omega/nodes/victoria/victoria_node.py`
**Action**: Investigate why MATICUSDT `exit_price == entry_price` in all 27 trades. The paper trading engine likely fetches price at close using the same cached/stale value as the open. Add a test that asserts `abs(exit_price - entry_price) > 0` for any trade held > 1 cycle.
**Rationale**: 27 zero-PnL trades (24% of all trades) waste capacity and signal budget.
**Expected impact**: Either correct MATIC trades generate real PnL signal, or MATIC is dropped and budget redirected.

### Fix 5 — Reconnect vol_rank computation (PRIORITY: HIGH)
**Target**: `omega/nodes/victoria/victoria_node.py` or `omega/nodes/victoria/market_data_signals.py`
**Action**: vol_rank is null in 100% of cycles. Find where vol_rank is computed, trace why it returns None, and fix the computation pipeline. Add an assertion/warning in the metrics emitter when vol_rank is None.
**Rationale**: The vol_low_threshold filter (0.2) is a dead no-op when vol_rank is never populated. Low-vol noise trades pass through unfiltered.
**Expected impact**: Removes estimated 10-20% of low-quality trades in low-volatility environments.

### Fix 6 — Add regression tests for crisis long suppression (PRIORITY: HIGH)
**Target**: `tests/` — new test file or extend existing strategy tests
**Action**: Add a parameterized test: `assert strategy._passes_conviction_filters(symbol='ETHUSDT', side='long', regime='crisis', ...) == False`. This test should have prevented the V50 gate from being reverted.
**Rationale**: The V50 fix was reverted in commit `d9ae8904` with no regression protection. Without a test, any future revert will repeat this failure.
**Expected impact**: Prevents regression recurrence.

### Fix 7 — Suppress AVAXUSDT until signal validated (PRIORITY: MEDIUM)
**Target**: `omega/nodes/victoria/domain_config.py` or symbol whitelist
**Action**: Remove AVAXUSDT from the active symbol list until a signal with positive expected value is validated in backtesting. With 3 trades at -$7.79/trade average and 0% WR, there is no edge.
**Rationale**: AVAXUSDT is consuming capital with no return. V51 may not have traded it; worth checking.
**Expected impact**: +$15-23 recovery.

### Fix 8 — Add composite score regime gate (PRIORITY: MEDIUM)
**Target**: `omega/nodes/victoria/strategy.py`
**Action**: When composite_score < -0.05 (net bearish consensus), suppress all long entries regardless of individual symbol conviction. When composite_score > +0.05, suppress all short entries. This creates a market-direction override layer above per-symbol signals.
**Rationale**: Crisis composite mean = -0.019; the market signal is bearish but longs still get placed. A stronger composite gate would prevent the regime/direction mismatch.
**Expected impact**: Blocks 5-10 additional wrong-direction trades per run.

---

## Summary Priority Order for V53

1. **[CRITICAL]** Hard-block crisis-regime longs — accounts for -$100.62 loss
2. **[CRITICAL]** Raise conviction threshold (0.05 → 0.15+) — current filter is noise
3. **[HIGH]** Fix MATICUSDT paper trading execution (zero-PnL bug)
4. **[HIGH]** Reconnect vol_rank (currently 100% null)
5. **[HIGH]** Block/gate DOTUSDT short in normal regime (-$21.51)
6. **[HIGH]** Add regression test for crisis long suppression gate
7. **[MEDIUM]** Suppress AVAXUSDT until signal is validated
8. **[MEDIUM]** Add composite score direction gate

Implementing fixes 1-3 alone should recover approximately +$80-120 in PnL, bringing V53 back above the V51 baseline (+$5.76 gate threshold).
