# V236 separator analysis — basket trend-efficiency vs recent-trade outcomes

**Date:** 2026-07-04
**Author:** claude (Fable 5)
**Rule:** V234 pre-grid separator proof (mandatory since V235). Cost: $0 — no
runs, computed entirely from committed V235 walk-forward artifacts.
**Verdict:** **NO SEPARATOR. ER and VR both fail the pre-registered gate.
V236's chop-throttle mechanism is REFUTED at $0; no code, no grid.**

## Question

Does the momentum composite have negative conditional expectancy when basket
trend efficiency is low, on the honest recent distribution (V235 walk-forward,
mean −$516 / p25 −$2,551, n=10 windows)? If yes, a low-ER size throttle is
worth a 32-window grid (~6h). If no, the mechanism is refuted before any burn.

## Data

- **Trades:** the 10 recent-labeled main-arm cells of the V235 walk-forward
  grid, `$AUDIT/v235wf_<window>_main_recent_determinism/*_r1_trades.csv`
  (AUDIT = `/Volumes/gamma-systems-2/omega-victoria-data`). Pooled **n = 140**
  trades (42 winners / 98 losers; pooled PnL −$5,163, consistent with the
  published mean −$516 × 10).
- **Prices:** the frozen walk-forward snapshots
  `data/snapshots/walk_forward/snap_wf_*.json` (91 daily bars per window).
- **Effective universe (verified, per V235 universe finding):** the traded
  names are **ETHUSDT / ADAUSDT / NEARUSDT / ARBUSDT** (35 trades each) — not
  BTC/ETH/SOL/XRP. Basket statistics below use whichever of these 4 exist in a
  given snapshot (e.g. 2020-08-13 has only ETH+ADA; ARB lists 2023).

### Cycle→bar mapping (derived + validated)

`ReplayIngestionNode` starts its cursor at `window=30`; the trades CSV `cycle`
is the **exit** cycle. Exact-price matching against the frozen series gives:

- exit bar index = `cycle + 28` — **126/140 trades match the frozen close
  bit-exactly** (remainder differ by the slippage adjustment);
- entry bar index = `cycle − hold_cycles + 28` (entry offsets 27/26/25/24/23/18
  in the exact-match scan correspond 1:1 to `28 − hold_cycles`).

All conditioning variables below are computed at the **entry** bar using only
bars ≤ entry (no lookahead). Max cycle observed = 53 < 61 replay steps ⇒ no
wrap-seam contamination in any of the 140 trades.

## Primary test 1 — Kaufman ER (20d, basket)

Basket ER at entry = mean over available universe names of
`|close[i] − close[i−20]| / Σ_{j=i−19..i} |close[j] − close[j−1]|` (fsum).

| statistic | value |
|---|---|
| winners' median entry-ER (n=42) | **0.1581** |
| losers' median entry-ER (n=98) | **0.1613** |
| Mann-Whitney U (one-sided, winners > losers) | U=2114, z=0.255, **p = 0.40** |

Tercile pooled PnL (boundaries ER 0.127 / 0.224; bootstrap 95% CI, 5000 resamples, seed 42):

| tercile | n | ER range | pooled PnL | 95% CI | win rate |
|---|---|---|---|---|---|
| low-ER  | 46 | 0.056–0.126 | **−$1,182** | [−$8,270, +$7,597] | 0.30 |
| mid-ER  | 46 | 0.127–0.218 | −$1,660 | [−$11,267, +$10,804] | 0.26 |
| high-ER | 48 | 0.224–0.463 | −$2,320 | [−$12,053, +$7,681] | 0.33 |

**Gate: FAIL on both prongs.** Winners' median is *below* losers' (wrong
direction, p=0.40 ≫ 0.05). The low-ER tercile (−$1,182) is not distinguishable
from zero (CI spans ±$8k) and is the *least* negative tercile — high-ER trades
lose more. There is no low-ER loss concentration to throttle.

## Primary test 2 — Lo–MacKinlay variance ratio (q=5 over 20d, basket)

VR(5) on trailing-20d log returns at entry (overlapping 5d sums,
sample-variance form), basket-averaged over the same universe.

| statistic | value |
|---|---|
| winners' median VR | 0.8145 |
| losers' median VR | 0.7551 |
| Mann-Whitney U (one-sided, winners > losers) | U=1942, z=−0.528, **p = 0.70** |

| tercile | n | VR range | pooled PnL | 95% CI | win rate |
|---|---|---|---|---|---|
| low-VR  | 46 | 0.267–0.625 | −$2,099 | [−$8,748, +$4,757] | 0.39 |
| mid-VR  | 46 | 0.625–0.945 | −$10,380 | [−$17,991, −$2,720] | 0.17 |
| high-VR | 48 | 0.962–1.692 | +$7,316 | [−$4,214, +$21,320] | 0.33 |

**Gate: FAIL.** The rank test is nowhere near significance (the median gap is
in the "right" direction but rank-mass is not — z is negative). The tercile
pattern is **non-monotone**: the *middle* tercile carries the losses while the
low tercile is mild. A threshold throttle keyed on "VR below X" does not
describe this shape.

*Diagnostic color (post-hoc, NOT actionable):* the mid-VR −$10,380 (CI
excluding 0) / high-VR +$7,316 split was not pre-registered, is one carving of
140 correlated trades, and non-monotone patterns of exactly this kind are what
multiple-comparison noise produces. Recorded only as a hypothesis seed for the
§4 conditional-expectancy surface (DEEP_REVIEW §2), where LOWO validation can
adjudicate it properly.

## Sensitivity (diagnostic, strengthens the refutation)

No horizon or aggregation choice rescues the separator:

| variant | winners med | losers med | one-sided p | low-tercile PnL |
|---|---|---|---|---|
| basket ER 10d | 0.327 | 0.247 | 0.35 | −$463 |
| basket ER 20d (primary) | 0.158 | 0.161 | 0.40 | −$1,182 |
| basket ER 30d (n=118) | 0.133 | 0.141 | 0.79 | **+$5,121** (sign flips) |
| own-ticker ER 20d | 0.166 | 0.167 | 0.69 | −$4,879 |

Per-window means show the same story at the window level: the two big positive
recent windows (snap_wf_20250305 +$3,860, snap_wf_20260228 +$6,551) sit at
mid-pack ER (0.230, 0.177), and the worst window (snap_wf_20240723 −$5,356)
has BOTH low ER (0.147) and VR ≈ 1.0 — the conditioning variables do not agree
on where the losses live.

## Decision (per the pre-registered gate)

- ER: winners > losers at p<0.05 → **NO** (wrong sign). Low-ER tercile < −$500
  → technically −$1,182, but the first prong already fails and the tercile
  gradient points the wrong way.
- VR fallback: p<0.05 → **NO** (p=0.70).

**⇒ V236 chop-regime exposure throttle REFUTED AT $0.** No implementation, no
smoke test, no 32-window grid. The ~6h grid burn and ~40 lines of runtime risk
are avoided entirely — this is the V234 separator rule doing exactly its job.

## What this refutes (and what it does not)

- **Refuted:** "recent's losses are concentrated in low-trend-efficiency
  states, so a state-conditional size throttle can lift the mean/tail." The
  losses are spread across the ER/VR spectrum; if anything high-ER entries
  lose slightly more.
- **Not refuted:** recent being a hard regime for the momentum book (the n=10
  distribution stands at mean −$516). The *mechanism* failed, not the problem
  statement. Per the DEEP_REVIEW fallback slot and the V236 brief, the next
  recent-targeted lever is **BTC-factor residualization** (fix a possible real
  defect — factor noise mis-demeaned by the crude `_basket_mean` and traded as
  idio signal — rather than gate a symptom). It promotes to **V237**, with its
  own separator proof required before any grid.

## Reproduction

All statistics computed from the artifact paths above with stdlib-only Python
(fsum-fenced sums; Mann-Whitney normal approximation with tie correction;
bootstrap seed 42). Entry-bar mapping validated by bit-exact price matching as
described. Raw per-trade table (window, symbol, entry bar, PnL, ER20, VR)
regenerable in ~1 minute from the committed snapshots + gamma trades CSVs.
