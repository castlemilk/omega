# V255.C — VERDICT: **KEEP-FLAG-GATED** (alpha survives friction + maker fees + 7d hold)

**Date:** 2026-07-14 · **Author:** claude (Opus 4.8)
**Pre-registration:** [`V255_C.md`](V255_C.md) (committed `4af212e` before the scorer ran)
**Code:** `omega/nodes/funding_carry/{hold_scaled.py,v255c_scorer.py}` (zero edits to `omega/nodes/victoria/`)
**Artifacts:** `/Volumes/gamma-systems-2/omega-victoria-data/v255_C/{v255c_scorer.json,v255c_trades.csv}`
**Determinism:** byte-identical JSON + trades.csv across `PYTHONHASHSEED` 42 vs 1 (pure-python stats, `math.fsum`, canonical sort, fixed-seed bootstrap). trades.csv sha `309b7319…`, 1225 trades.

> Pre-registered gate (V255_C.md): PASS (⇒ the KEEP-FLAG-GATED ceiling) requires
> **ALL** of — pooled median net PnL > $0 · MWU p < 0.05 in ≥1 genuine regime ·
> annualized gross carry ≥ 15% · no Goodhart tuning — with the basis caveat
> hard-capping the verdict at KEEP-FLAG-GATED regardless. **Result: NO falsifier
> fired. All four clauses pass. Verdict = KEEP-FLAG-GATED.**

## Phase 3 numeric results

**Pooled (n=1225, net of 2-leg 20 bps maker fee):**

| metric | net PnL | gross carry (pre-fee) |
|---|---:|---:|
| total | **+$41,062.62** | +$52,972.16 |
| mean / trade | +$33.52 | +$43.24 |
| **median / trade** | **+$1.56** | +$7.63 |
| p25 / p75 | −$1.43 / +$34.20 | +$3.17 / +$49.14 |
| win rate | **63.92%** | 92.98% |
| profit factor | 18.92 | 60.99 |

**Bootstrap 95% CI on pooled median net PnL** (10,000 resamples, fixed seed
20250714): **[+$0.85, +$2.39]** — excludes zero, lower bound > 0. The positive
median is statistically robust, not a razor's-edge artifact of the point estimate.

**Per genuine regime (net PnL; `near_zero` excluded as pre-declared):**

| regime | trades | total | median | WR | PF | separator MWU (\|entry funding\|) |
|---|---:|---:|---:|---:|---:|---|
| negative_carry | 561 | +$1,543.85 | −$1.09 | 35.8% | 2.30 | **p≈0** |
| positive_carry | 324 | +$8,776.55 | +$10.67 | 87.6% | 21.20 | **p=3e-6** |
| high_vol | 340 | **+$30,742.22** | **+$44.45** | 87.6% | 46.83 | **p≈0** |

**Annualized carry:** GROSS **29.0%** · NET **18.6%** (mean carry 0.556%/7-day hold).

**Notional distribution (level-scaling diagnostic):** min $2,000 · median $3,266.67
· max $10,000 · 244 trades at the $10k cap. Level-scaling concentrates capital in
the high-\|funding\| trades that carry the profit (see high_vol total).

**Hedge cancellation:** spot+perp price PnL max residual = **$0.00** (exact —
single-series identity, unchanged from V255.B).

## Falsifier check (per pre-registered clause)

| # | falsifier | fired? | value |
|---|---|:--:|---|
| 1 | pooled median net PnL ≤ $0 | ❌ | **+$1.56** (CI95 [+$0.85, +$2.39] > 0) |
| 2 | MWU p ≥ 0.05 in EVERY genuine regime | ❌ | p≈0 in **all 3** regimes |
| 3 | annualized gross carry < 15% | ❌ | **29.0%** |
| 4 | basis-hedge fails empirically | ❌ (cannot fire) | residual $0.00; single-series ⇒ untestable |
| 5 | Goodhart tuning | ❌ | all params fixed in `V255_C.md` before run |

**Zero falsifiers fired ⇒ the strategy passes every testable clause.**

## Verdict: **KEEP-FLAG-GATED** — specific reasoning

V255.C confirms the V255.B recommendation was correct: the funding-carry loss was
**friction geometry, not absence of alpha**, and the two pre-registered levers fixed
it.

1. **The 7-day hold flipped the median positive.** V255.B's failing clause was the
   median (−$5.95 at 3-day hold, pooled WR 39.9%). Amortizing the fixed 4-fill fee
   over 2.3× more carry accrual lifted pooled **WR to 63.92%** — past 50%, which is
   precisely the mechanical condition for a positive median (fee and every PnL
   component scale linearly with notional, so median sign is governed by WR>50%, as
   pre-registered in V255_C.md). Median net = **+$1.56**, CI95 **[+$0.85, +$2.39]**
   excludes zero.
2. **The level separator survived the parameter change** — MWU p≈0 in every genuine
   regime, exactly as Phase 0 and V255.B found. The mechanism, not a window artifact.
3. **The alpha was amortized, not destroyed** — annualized gross **29.0%** ≥ 15%
   bar (net **18.6%**). The 7-day hold cost ~7pts of annualized gross vs V255.B's
   36.4% (different non-overlapping trade set) but stayed well clear of the floor.
4. **Level-scaled sizing improved total/mean** ($23.6k→$41.1k total, +$9.96→+$33.52
   mean) by concentrating capital where carry ≫ fee — the Kelly-lite intent.

### Why NOT ADOPT — the mandatory pre-cap (basis caveat, carried from V255.B)

The frozen data has **one `close` series per symbol** (no separate perp mark / spot
index). The spot and perp price legs cancel to **exactly $0 by construction, not by
measurement** — the hedge is validated algebraically, never empirically. The
basis-cleanliness assumption (zero basis slippage) is **UNTESTED on this data**.
This was pre-declared in both V255_B.md and V255_C.md as a **hard cap**: no positive
verdict may exceed KEEP-FLAG-GATED, and **ADOPT to production is impossible** without
real perp-mark + spot-index basis execution data. That data acquisition needs
live-host provisioning and is **out of scope for this task**.

### Honest sensitivity / limits (disclosure, not re-tuning)

- **The median is thin (+$1.56).** It is robust in sign (CI excludes zero) but small
  in magnitude — the pooled median is dominated by near-threshold trades that
  level-scaling deliberately sizes small ($2k). The *profit* lives in the
  high-\|funding\| tail (high_vol median +$44.45, total +$30.7k) — which is where
  level-scaling puts the capital, so mean/total (+$41k) is the economically
  meaningful figure, not the median. The median clause is the honest go/no-go; it
  passed, barely, on sign.
- **`negative_carry` is still marginal** (median −$1.09, WR 35.8%) but total-positive
  (+$1.5k) and its separator is p≈0. It is not individually gated; the pooled median
  and ≥1-regime separator are the pre-registered tests.
- **Real basis frictions are unmodeled** (the cap above): basis slippage, funding
  on the spot-margin leg, and borrow on the short-spot leg would all erode the thin
  median. This is exactly why the verdict is capped at FLAG-GATED pending real data.

## Next step

**Funding-carry earns KEEP-FLAG-GATED status.** The lane is **not** closed — the
confirmed 36% (now 29% at 7d) gross carry + p≈0 separator + a net-positive pooled
median under realistic maker fees is a real, if thin, edge on this data. But it is
**flag-gated OFF and cannot advance to production on frozen data**.

→ **V255.D (gated, out of scope for this task): basis-data acquisition + live
re-verify.** The single mandatory unlock is a **real perp-mark + spot-index basis
series** (Binance perp mark price + spot index, or equivalent) to (a) measure the
hedge residual empirically and (b) charge realistic basis-execution frictions on the
thin median. Only after that measurement can funding-carry be considered for ADOPT.
Until then the strategy stays a flag-gated parallel book.

→ **Meanwhile, V254 Track C (on-chain flow) remains the recommended primary lane**
for the next *offline* alpha search — funding-carry is now proven-but-blocked on
data provisioning, so the marginal offline effort is better spent on a genuinely
independent universe that isn't gated on live-host data. (This is a prioritization,
not a closure: funding-carry is validated, just parked pending basis data.)

## High-water table

**Unchanged.** V255.C is a parallel funding book with no Victoria high-water to
move; the spot baseline (crisis +$599 / trend +$2,997 / recent +$30) stands
untouched. This is a $0 offline adjudication — the cheap, fast verdict the funding
lane was chosen to provide.
