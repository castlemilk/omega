# High-ROI Improvements — Strategic Assessment

**Date:** 2026-05-01
**Author:** session retrospective
**Purpose:** Step back from feature-experiment loop and rank what's actually
limiting performance.

## Where we are

- **V161 backtest:** +$41.85k composite (recent +$4.3k / crisis +$2.6k / trend +$34.9k).
- **v167c live (current):** +$308 across 28 trades, 32% WR, 27.5h elapsed,
  PF ~1.0. *Profitable but thin.*
- **15-min cadence beats 1h** (v167 +$154 / 14t vs. v164 −$201 / 3t same window).
- **V165–V172 IC-weighting variants all regress** (composite −$30k to −$60k).
  Six attempts, six losses on the same root pattern.

The thing we keep doing — modifying the composite weighting — has cost ~30
hours of session time and produced zero wins. The thing we did once that
worked — switching cadence — produced the only profitable live run.

## The six candidates, ranked by ROI

ROI = (expected PnL improvement) / (implementation effort), risk-adjusted.

### 1. **Fresh snapshot capture** — HIGHEST ROI

Snapshots in use:
- `snap_20260414.json` (recent): April 14, 2026
- `snap_trending_2023q4.json`: Q4 **2023** (2.5 years stale)
- `snap_crisis_2022h1.json`: H1 **2022** (3.5 years stale)

Crypto microstructure has changed massively since 2022 — the FTX collapse,
the ETF-flow regime, the funding-rate environment, the dominant market makers.
Optimizing v161 for crisis behaviour observed in 2022 H1 is **training on a
distribution that no longer exists**.

The 22pp live-vs-backtest WR gap (29% vs ~50%) almost certainly contains a
big stale-data component. Even the "recent" snapshot is 17 days old by now.

**Action:** capture three NEW snapshots:
- `snap_recent_live`: last 7 days at 15-min cadence (already have this:
  `snap_15min_live.json` from V167 launch).
- `snap_volatile_recent`: any 7-day stretch from the last 60 days that had
  >5% drawdowns (from Binance fapi).
- `snap_trending_recent`: 7 days of clean uptrend / downtrend from the last
  90 days (find via daily return std selection).

**Effort:** 1-2 hours (the snapshot capture script exists; just run it three
times with different date ranges).
**Expected improvement:** if snapshots are the right vintage, the backtest
optimization landscape may shift enough that auto_improve finds a config
materially different from v161. Could close 5-10 pp of the live WR gap.
**Risk of regression:** none — fresh snapshots are pure additive evidence.
**ROI:** ~20× the IC weighting attempts. Should have done this first.

### 2. **Signal pruning over weighting** — HIGH ROI

Our IC calibration gave clear answers about which top-level signals
*hurt*:

| Signal | Pooled IC | Verdict |
|---|---|---|
| sma_crossover | −0.273 | **drop** |
| return_1d (sub-signal) | −0.150 | drop |
| momentum_acceleration (sub-signal) | −0.119 | drop |
| spy_signal | −0.289 (n=5) | unreliable, drop |

The previous "weight by IC" attempts failed because they tried to invert
anti-predictive signals — but composite arithmetic over correlated, noisy
signals doesn't reliably benefit from sign-flipping. **Just removing them
entirely is simpler, more robust, and our data already says they hurt.**

**Action:** add a feature flag `excluded_signals: list[str]` that filters
named signals out of the per-ticker `ts` dict before composite computation.
Default `["sma_crossover"]` for V172_pruned variant. Ship if Phase A passes.

**Effort:** 30 minutes.
**Expected improvement:** +5-15% composite if sma_crossover really is a drag
(it has 11k pairs of evidence).
**Risk:** minor. We already know v161 PnL with sma_crossover IN; this just
removes one signal whose IC is clearly negative.
**ROI:** very high.

### 3. **Run V161 live for a full week** — HIGH ROI for evidence, zero implementation

We have v167c at cyc 116/192. After it finishes (cyc 192 = ~21 hours from
now), launch v167d_15min for ANOTHER 192 cycles (24 hours). That gives a 96
hour total live experiment in the same stable configuration. Around 50-100
trades is statistically meaningful.

**Action:** when v167c finishes, auto-launch v167d, then v167e, etc.
**Effort:** 1 hour to write a sequencer script.
**Expected improvement:** none directly — but converts "is the strategy
actually profitable in live?" from anecdote (+$300 in 24h, n=24) to
evidence (+/-$X over 100+ trades). That answer is the prerequisite for any
other improvement decision.
**Risk:** none.
**ROI:** high — investment in *knowing* what we have.

### 4. **Forward-return IC + Ridge regression** — TRACK 1, RUNNING NOW

V172 attempts this. Filters to v161-era trades only, uses Ridge regression
on the joint signal matrix. If V172 fails (likely, given the pattern), this
research line closes.

Already underway; not duplicating effort here.

### 5. **Ensemble of simple sub-strategies** — MEDIUM ROI

Three independent sub-strategies vote:
- Momentum (breakout + timeframe + adx_plus_di)
- Mean-reversion (donchian + sma_short)
- Microstructure (when WS feeds available)

Each emits {long, short, hold} per ticker. Majority wins; ties → hold.

This is more *robust* than weighted composites because each sub-strategy
makes a categorical decision and they don't have to agree on numerical
magnitudes.

**Effort:** 1-2 days. Significant refactor of the entry-decision path.
**Expected improvement:** 5-10% PnL, substantially less variance.
**Risk:** medium — this is a bigger change than feature-flag tweaks.
**ROI:** medium. Worth doing after items 1-3.

### 6. **Bull/Bear LLM debate architecture** — LOWEST ROI for now

Adding adversarial LLM analysts costs 3× per-decision compute. Our LLM
analyst is currently slightly negative (DeepSeek 100-cyc test: −$447 / 18
trades). Spending more LLM budget when the existing one is net-negative is
the wrong direction. **Defer until the LLM modifier is empirically positive.**

**Action:** none until LLM signal is shown to be net-positive.

---

## Ranked action list

| # | Action | Effort | Expected | Risk | ROI |
|---|---|---|---|---|---|
| 1 | Fresh snapshot capture (recent + volatile + trending) | 1-2h | 5-10pp WR closing | none | 20× |
| 2 | Drop sma_crossover (and others with IC<−0.05) | 30m | +5-15% composite | low | 15× |
| 3 | v167d/e/f sequencer for 96h+ live | 1h | evidence/n→100 | none | 10× |
| 4 | Ridge weights (V172 — running) | 0 (sunk) | unknown | regression | ? |
| 5 | Sub-strategy ensemble | 1-2d | +5-10% | medium | 4× |
| 6 | LLM debate | 1d | uncertain | high cost | 1× |

## What I'm doing now (this session)

1. **V172 Ridge weights — Track 1.** Phase A running. If passes, ship; if
   fails, close IC research line for good.
2. **This document — Track 2 strategic ranking.**
3. **Implementing items 1 + 2 from the table** while V172 runs.

## What I'm not doing yet

- Item 5 (sub-strategy ensemble). Requires a real refactor and more design.
- Item 6 (LLM debate). Premature; LLM modifier isn't even net-positive yet.

## Update — V172 results (2026-05-01 evening)

**Both variants regressed.** V172 Ridge composite −$15,394 vs V161 +$41,850
(−$57k). V172_pruned (just `del ts["sma_crossover"]`) composite −$24,249
(−$66k). The *pruning* result is more informative than the Ridge result —
it proves that even dropping a clearly-anti-predictive signal regresses, so
the IC of an isolated signal isn't a reliable guide to its system-level
contribution. sma_crossover (IC −0.273) is load-bearing in the integrated
strategy despite negative correlation with PnL in isolation.

This empirically validates the closing hypothesis below. **Closing the IC
research line for good.** Pivoting to items 1, 3, 5 from the action list.

## Closing the IC research line (if V172 fails)

After V165, V166, V168_micro, V169, V169b, V170, V171, V172 — if V172 also
regresses, that's 8 attempts at IC weighting in this session, all failing.
The pattern is unambiguous: **modifying the composite weighting in this
codebase regresses, regardless of methodology.** The signal stack works
empirically with uniform weights and the regime-adaptive thresholds; trying
to optimise per-signal weights breaks something we don't fully understand.

The right interpretation is probably: the *strategy* (regime gates,
sit-out, crisis_long_block, basket-mean demeaning) is what produces alpha,
not the weighting. The IC of an individual signal in isolation says little
about its contribution to a system that already filters and gates heavily.

If that interpretation holds, the right next moves are 1, 2, 3, 5 from the
table. Not more weighting experiments.
