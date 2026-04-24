# V161 Backtest vs Live Gap — Root Cause

**Date:** 2026-04-25
**Priority:** P0 (blocks interpretation of all prior training results vs live)
**Status:** Root cause identified; fix in design.

## Decision required (before Phase 2)

Phase 3 as originally planned ("re-run v163_live for 500 cycles in ~2 hours") is
**not feasible** once cadence is fixed: 500 bars on 1h resolution = ~21 days
wall-clock. Pick one before Phase 2 starts:

- **(a) Accept 2-3 day live runs** — sleep-until-next-bar on 1h, collect 48-72
  bars, compare to matched-length backtest slice. Statistically meaningful on
  both sides, but slow iteration.
- **(b) Lower bar resolution to 1min** — 500 cycles × 60s sleep ≈ 8h live run.
  Requires retraining the signal ensemble at 1min cadence; invalidates v161
  tuning.
- **(c) Tick-on-bar event-driven harness** — cycle only on new bar close; same
  as (a) for 1h, but flexible across timeframes.

Recommend **(a)** — preserves v161 calibration, acceptable iteration cost, and
unblocks a genuine apples-to-apples comparison in 2-3 days.

## TL;DR

The 22pp win-rate gap between v161_live backtest (+$8,623 / 45.5% WR on 500
cycles) and live paper (−$139 / 27.6% WR on 500 cycles) is **not** signal
drift, classifier drift, or data-source drift. It is a **cadence mismatch**
between training and live: the strategy is trained on 1h bars where 1
cycle = 1 bar advance, but the live harness cycles at 10s sleep against 1h
bars, so 500 live cycles traverse ~2-3 bars of real market time instead of
500.

Live did not evaluate the strategy on 500 independent market states. It
evaluated ~2-3 states, re-entered 127 times. The 27.6% WR is a stdev-2 draw
on ~2 underlying price movements, not a separate strategy.

## Evidence

### 1. Variance test rules out stochastic noise

Ran `v161_live` × 5 seeds × 500 cycles on `snap_20260414` (the snapshot the
live run was benchmarked against). Backtest is effectively deterministic:

| seed | PnL | trades | WR | PF |
|---|---|---|---|---|
| 1 | +$9,073 | 156 | 0.455 | 1.194 |
| 7 | +$9,073 | 156 | 0.455 | 1.194 |
| 13 | +$6,819 | 159 | 0.453 | 1.136 |
| 42 | +$9,073 | 156 | 0.455 | 1.194 |
| 99 | +$9,073 | 156 | 0.455 | 1.194 |
| **mean** | **+$8,623** | **156.6** | **0.455** | **1.182** |
| **stdev** | $1,008 | 1.3 | 0.001 | 0.026 |

**Live:** −$139 / 127t / 0.276 WR / 0.725 PF.

WR gap = 17.9pp vs backtest stdev of 0.1pp — 180× outside noise. Gap is
real and structural.

### 2. Live wall-time is 2-3 bars, not 500

`/tmp/v161_live_metrics.jsonl` first/last timestamps: 2026-04-24 09:22:55
→ 12:00:15 UTC = **2h37m wall time** for 500 cycles (sleep=10s × 500 +
per-cycle API latency). On 1h bars, that is 2–3 new closes over the entire
run.

Backtest `ReplayIngestionNode.execute()` ([providers/replay.py:140-166](../../omega/nodes/victoria/providers/replay.py))
advances cursor by **1 bar per cycle**. Backtest 500 cycles = 500 bars.

### 3. Signals that depend on BTC return distribution are frozen live

Signal-by-signal z-score of means, 500-cycle live vs 500-cycle bt (seed=42):

| signal | live σ | bt σ | interpretation |
|---|---|---|---|
| w2_trend | 6.9e-05 | 5.4e-03 | Wasserstein regime near-constant live |
| w2_crisis | 6.9e-05 | 4.3e-03 | same |
| w2_normal | 5.7e-05 | 4.2e-03 | same |
| tda_betti0 | 0 | 0.95 | TDA always returns 1 live |
| tda_fragmentation | 2.5e-04 | 0.19 | TDA near-constant live |
| tda_pers_entropy | 1.3e-04 | 4.5e-02 | TDA near-constant live |

These signals compute on the last 60 BTC log-returns. If the BTC price
series barely updates cycle-to-cycle (as it does at 10s sampling of 1h
bars), the return window is nearly identical → signals are nearly
constant. Backtest sees a sliding window → signals vary normally.

**Secondary bug (independent, masked in backtest):** `TDASignal.update_returns`
([signals/tda_signal.py:83-89](../../omega/nodes/victoria/signals/tda_signal.py))
and the analogous Wasserstein signal update both *extend* the internal buffer
with the full BTC return series every cycle, then rolling-cap at `window*3`.
In backtest this is harmless because the cursor slides 1 bar per cycle. In
live, re-appending the same (barely-changed) 60-return series every 10s
floods the buffer with near-duplicates, further flattening the signal even if
cadence were fixed. Should be changed to append only the newest return(s).

**Note on direct BTC-price verification:** `/tmp/v161_live_signal_contribs.jsonl`
was not persisted for this live run, so per-cycle BTC close values aren't
directly inspectable. The cadence conclusion rests on three independent
indirect lines: (1) wall-clock timestamps (2h37m for 500 cycles), (2)
`regime_transition=0` across all 500 rows, (3) the signal-freeze pattern
matching exactly what a static 60-return window would produce. Trade log
`mean hold_cycles = 6.35` (~63s) further confirms the strategy is trading
sub-bar noise.

Macro ingestion signals are also zero in live (`funding_rate_btc`,
`fear_greed_signal`, `dxy_signal`: 0 non-null values in 500 rows) — a
separate but independent ingestion issue.

### 4. Zero regime transitions in 500 live cycles

`regime_transition` = 0 across all 500 rows. Regime distribution was
normal 49.5% / crisis 38.6% / high_vol 11.9% — but with no transitions, the
classifier is labelling the same 2-3 underlying bars as different regimes
on a per-cycle basis, which is near-deterministic classification noise, not
genuine regime evolution.

## What this invalidates

- **v161_live_metrics.jsonl per-cycle rows are not independent.** 500 rows
  ≈ 2-3 genuine market evaluations. Any per-cycle statistics (WR, PF, PnL
  per trade) are implicitly a 2-3-sample study, not a 500-sample one.
- **The `live_vs_backtest_v161.md` ranking of root causes (classifier
  drift, signal IC drift, LLM off, data freshness) is wrong.** Classifier
  and signal behaviour appear drifted *because the input distribution
  collapses* in the 10s-vs-1h-bar regime.
- **The V162 resilience report's "normal regime was dominant in recent
  snapshot" is fine, but the live confirmation of that hypothesis is
  invalid.** Live had essentially one market state; regime breakdown on it
  is a label assigned to the same data 500 times.
- **Phase 4 (resume auto_improve using live as objective) is unsafe.** A
  500-cycle live window only represents 2-3 bars of genuine information.
  Optimizing against it would overfit to whatever 2-hour window we ran.

## What this does NOT invalidate

- The backtest itself (snapshot replay against 500 distinct bars) remains
  a valid evaluation of the strategy on the snapshot's market regime.
- The `auto_improve` optimizer results that ranked v161_live as optimal
  were computed against backtest — that ranking is still meaningful
  *within the backtest regime*.
- The max-DD 0.23% and position-sizing figures in the live report are
  arithmetically correct (size column verified as notional dollars: ~12%
  of $100k per position, not leveraged).

## Recommended fix (before v163_live)

Two paths, not mutually exclusive:

**Path A — Cycle-per-bar alignment (preferred).** Change live sleep from
10s to 1h (or to the native bar size of the signal ensemble). One cycle =
one bar of market evolution. 500 cycles = 500 bars = ~21 days for 1h bars.
This is the apples-to-apples comparison with backtest. Implementation:
make the live loop sleep until the next bar boundary on the dominant
timeframe, not a fixed 10 seconds.

**Path B — Event-driven cycle trigger.** Cycle only when any watched
ticker has a new bar close. For 1h bars on crypto (always closed on the
hour) this is equivalent to Path A. For mixed timeframes it's more
flexible.

Either path re-frames "cycle" from a wall-clock tick to a market-event
tick. The strategy's signals were designed for the latter; the live
harness gave them the former.

A secondary fix (independent): **macro signals (funding, fear-greed, DXY)
are silently zero in live.** This is a separate ingestion bug and should
be addressed alongside the cadence fix, since it also contributes to
degraded signal quality — but it is much smaller than the cadence
mismatch. Per-signal forensics were blocked by the cadence issue (no
signal comparison is meaningful when live is measuring 2-3 bars), so this
ingestion audit should happen after the cadence fix.

## Next step

Fix the cadence (Path A), re-run live as v163_live for 500 bars worth of
wall time (≈21 days on 1h bars — not feasible for a manual run in one
sitting). Pragmatic alternative: re-run for 48-72 live bars (2-3 days
wall-clock) and compare per-bar PnL/WR against a matched-length backtest
slice. That is a statistically meaningful sample on both sides.

**Do not promote v161→v162 live until cadence is fixed.** Do not resume
auto_improve against live objective until at least 50+ genuine bars of
live data are in hand.
