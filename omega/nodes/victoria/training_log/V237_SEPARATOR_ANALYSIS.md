# V237 separator analysis — BTC-factor mis-demean contamination vs recent-trade outcomes

**Date:** 2026-07-04
**Author:** claude (Fable 5)
**Rule:** V234 pre-grid separator proof (mandatory since V235). Cost: $0 — no
runs, computed entirely from committed V235 walk-forward artifacts (the exact
V236 dataset, methodology and entry-bar mapping reused unchanged).
**Verdict:** **NO SEPARATOR. Prong 1 (rank test) fails at every β window;
V237's BTC-factor residualization is REFUTED at $0; no code, no grid.**

## Question

Does the β=1 cross-sectional demean (`_basket_mean`) inject BTC-factor
contamination that the strategy mistakes for idiosyncratic signal — i.e., are
losing entries systematically higher-contamination than winning entries? If
yes, replacing the demean with rolling-OLS BTC residualization is worth a
32-window grid (~6h). If no, the mechanism is refuted before any burn.

## Data (V236 dataset, reused verbatim)

- **Trades:** the 10 recent-labeled main-arm cells of the V235 walk-forward
  grid, `$AUDIT/v235wf_<window>_main_recent_determinism/*_r1_trades.csv`.
  Pooled **n = 140** (42 winners / 98 losers; pooled PnL −$5,163 — matches
  V236's table exactly, confirming identical trade extraction).
- **Prices:** frozen `data/snapshots/walk_forward/snap_wf_*.json` (91 daily
  bars; BTCUSDT present in every snapshot even though blacklisted from trading).
- **Universe:** ETHUSDT / ADAUSDT / NEARUSDT / ARBUSDT, 35 trades each.
- **Entry bar** = `cycle − hold_cycles + 28` (validated V236, bit-exact price
  match 126/140). All conditioning uses bars ≤ entry (no lookahead).

## Method

Per trade, at the entry bar:

- **β_t** = rolling OLS slope of the ticker's daily returns on BTC's daily
  returns over a trailing window ending at entry (`math.fsum`-fenced cov/var;
  window truncated to available history, min 15 returns — every one of the 140
  trades clears the floor, effective returns min/med/max = 29/41/60 at the
  primary 60d window; the 91-bar snapshots cap the deepest entries).
- **Contamination** `C = |β_t − 1| · |r_BTC,entry|` (pre-registered executing
  spec), where `r_BTC,entry` is BTC's daily return on the entry bar.
- Primary window 60d; sensitivity at 20/30/40/90d (pre-reg named 40/90 as
  color; 20/30 added for symmetry with V236's sensitivity table).

## The premise half-holds: betas do vary

β(60d) across the 140 entries: min 0.05 / p25 0.92 / median 1.15 / p75 1.53 /
max 3.01. Per name (median [range]): ETH 1.12 [0.76, 1.85], ADA 0.98
[0.41, 1.73], NEAR 1.27 [0.62, 2.28], ARB 1.15 [0.05, 3.01]. The β=1
assumption is indeed wrong in levels — but that alone is not the gate; the
gate is whether the resulting contamination *separates losers from winners*.

## Primary test — contamination C at 60d β window

| statistic | value |
|---|---|
| winners' median C (n=42) | **0.002355** |
| losers' median C (n=98) | **0.002674** |
| Mann-Whitney U (one-sided, losers > winners) | U=2021, z=−0.168, **p = 0.567** |

Tercile pooled PnL (bootstrap 95% CI, 5000 resamples, seed 42):

| tercile | n | C range | pooled PnL | 95% CI | win rate |
|---|---|---|---|---|---|
| low-C  | 46 | 0.00001–0.00109 | −$6,261 | [−$11,927, −$554] | 0.28 |
| mid-C  | 47 | 0.00111–0.00523 | **+$4,390** | [−$7,622, +$17,579] | 0.34 |
| high-C | 47 | 0.00535–0.03311 | −$3,292 | [−$11,386, +$6,119] | 0.28 |

**Gate: FAIL on prong 1.** The median gap is nominally in the right direction
but rank-mass is not (z is *negative*), p=0.567 ≫ 0.05. Prong 2 technically
passes (high-C tercile −$3,292 < −$500) but the required loss *gradient* is
absent: the pattern is U-shaped — the **low**-contamination tercile is the only
one whose loss CI excludes zero (−$6,261, CI [−$11,927, −$554]), and the middle
tercile is *positive*. Losses are emphatically not concentrated where the
mis-demean contamination lives.

## Sensitivity (diagnostic; strengthens the refutation)

| β window | winners med C | losers med C | one-sided p | terciles (low/mid/high) |
|---|---|---|---|---|
| 20d | 0.00420 | 0.00295 | 0.738 (**wrong direction**) | −$5,463 / +$1,450 / −$1,149 |
| 30d | 0.00353 | 0.00262 | 0.829 (**wrong direction**) | −$7,233 / +$2,372 / −$302 |
| 40d | 0.00295 | 0.00277 | 0.645 (**wrong direction**) | −$9,187 / +$7,051 / −$3,028 |
| 60d (primary) | 0.00236 | 0.00267 | 0.567 | −$6,261 / +$4,390 / −$3,292 |
| 90d | 0.00326 | 0.00239 | 0.583 (**wrong direction**) | −$3,473 / +$696 / −$2,386 |

At four of five windows the winners' median contamination is *higher* than the
losers' — the exact opposite of the hypothesis. The U-shape (low and high
terciles negative, middle positive) is stable across windows, which is the
signature of no monotone relationship plus noise, not of a throttleable defect.

**Robustness variant** (the original V237.md wording "aggregated over the
composite's lookback"): `C_agg = |β60 − 1| · Σ|r_BTC|` over the trailing 20
bars at entry — p=0.520, terciles −$2,594 / −$68 / −$2,501. Same verdict.

Per-window color: the two big positive recent windows sit at *opposite* ends
of the contamination scale (snap_wf_20250305 +$3,860 at median C=0.0061 —
high; snap_wf_20260228 +$6,551 at C=0.0011 — low), and the worst window
(snap_wf_20240723 −$5,356) is mid-pack (C=0.0024). As with V236's ER/VR, the
conditioning variable does not agree with where the money is made or lost.

## Decision (per the pre-registered gate)

- Prong 1 — losers' median C > winners' at p < 0.05: **NO** (p=0.567 primary;
  wrong direction at 4/5 sensitivity windows).
- Prong 2 — high-C tercile pooled < −$500: technically yes (−$3,292), but the
  gate requires BOTH prongs and "a loss gradient in the right direction"
  (V237.md); the gradient is U-shaped, not monotone.

**⇒ V237 BTC-factor residualization REFUTED AT $0.** No implementation, no
smoke test, no 32-window grid. Third consecutive $0/low-cost refutation
(V236 ER, V236 VR fallback, V237 contamination) on the recent distribution.

## What this refutes (and what it does not)

- **Refuted:** "recent's losses are the β=1 mis-demean trading BTC-factor
  noise as idio signal, so OLS residualization will lift the mean/tail."
  Betas do deviate from 1 (median 1.15, IQR 0.92–1.53), but the resulting
  contamination is uncorrelated with trade outcome — winners carry as much of
  it as losers. The demean's crudeness is real; its *cost* is not detectable
  in this book.
- **Not refuted:** recent being a hard regime (n=10 honest mean −$516 stands).
- **Consequence (per pre-reg):** the composite-side / OHLCV-native
  intervention space for recent is now exhausted — V236 (state-conditional
  throttle) and V237 (factor construction) both died at their separators.
  Per V237.md's refuted branch: the queue advances to **V238 (frozen-series
  feed build — new information classes)**, with the tail cap (V240 candidate)
  and the Section-4 conditional-expectancy surface as the remaining
  recent-adjacent items. See `REFLECTION_V237.md`.

## Reproduction

Stdlib-only Python (fsum-fenced OLS and rank sums; Mann-Whitney normal
approximation with tie correction; bootstrap seed 42), from the artifact paths
above. Per-trade table (window, symbol, entry bar, PnL, r_BTC, β60, C60)
regenerable in ~1 minute; script pattern identical to V236's.
