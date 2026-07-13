# V255.B — VERDICT: **REFUTED** (friction/hold, not absence of alpha)

**Date:** 2026-07-14 · **Author:** claude (Opus 4.8)
**Pre-registration:** [`V255_B.md`](V255_B.md) (committed `3fe7eaa` before the scorer ran)
**Code:** `omega/nodes/funding_carry/{basis_hedge.py,v255b_scorer.py}` (zero edits to `omega/nodes/victoria/`)
**Artifacts:** `/Volumes/gamma-systems-2/omega-victoria-data/v255_B/{v255b_scorer.json,v255b_trades.csv}`
**Determinism:** byte-identical across `PYTHONHASHSEED` 42 vs 1 (pure-python stats, `math.fsum`, canonical sort). trades.csv sha `65db62f0…`, 2369 trades.

> Pre-registered gate (V255_B.md): PASS requires **ALL** of — pooled median net
> PnL > $0 · MWU p < 0.05 in ≥1 genuine regime · annualized gross carry ≥ 5% ·
> hedge cancels price risk · no Goodhart tuning. **Result: REFUTED — falsifier #1
> fired (pooled median net PnL = −$5.95 ≤ $0).** The other three testable
> falsifiers did NOT fire.

## Phase 3 numeric results

**Pooled (n=2369, net of 2-leg 20 bps fee):**

| metric | net PnL | gross carry (pre-fee) |
|---|---:|---:|
| total | **+$23,583.79** | +$70,963.79 |
| mean / trade | +$9.96 | +$29.96 |
| **median / trade** | **−$5.95** | +$14.05 |
| p25 / p75 | −$11.00 / +$16.68 | +$9.00 / +$36.68 |
| win rate | 39.85% | 97.89% |
| profit factor | 2.516 | 134.2 |

**Per genuine regime (net PnL; `near_zero` excluded as pre-declared):**

| regime | trades | total | median | WR | PF | separator MWU (|entry funding|) |
|---|---:|---:|---:|---:|---:|---|
| negative_carry | 935 | **−$7,175.64** | −$11.00 | 11.9% | 0.259 | z=13.7, **p≈0** |
| positive_carry | 666 | +$3,877.86 | −$0.48 | 48.7% | 2.207 | z=19.8, **p≈0** |
| high_vol | 768 | **+$26,881.56** | **+$18.34** | 66.3% | 11.13 | z=20.1, **p≈0** |

**Annualized gross carry:** mean carry 0.2996%/3-day hold → **36.4% annualized gross**.

**Hedge cancellation:** spot+perp price PnL max residual = **$0.00** (exact — single-series identity).

## Falsifier check (per pre-registered clause)

| # | falsifier | fired? | value |
|---|---|:--:|---|
| 1 | pooled median net PnL ≤ $0 | ✅ **FIRED** | **−$5.95** |
| 2 | MWU p ≥ 0.05 in EVERY genuine regime | ❌ | p≈0 in **all 3** regimes |
| 3 | annualized gross carry < 5% | ❌ | **36.4%** |
| 4 | basis-hedge fails empirically | ❌ (cannot fire) | residual $0.00; single-series ⇒ untestable |
| 5 | Goodhart tuning | ❌ | all params fixed in `V255_B.md` before run |

**One falsifier fired ⇒ REFUTED**, per the pre-registered "ANY of" rule.

## Verdict: **REFUTED** — specific reason

The **carry alpha is real and large** — gross **36.4% annualized**, the |entry
funding| level separator is **p≈0 in every genuine regime** (Phase 0's two
findings confirmed), and total/mean PnL are net-positive (+$23.6k, +$9.96/trade,
PF 2.5). But the **pre-registered net-per-trade structure does not clear a
positive median**: at the pre-declared **3-day hold** the **median gross carry is
+$14.05, which loses to the 2-leg 20 bps ($20) round-trip fee → median net
−$5.95**. Most trades cluster near the entry threshold where 3-day carry ≈ fee;
only the high-|funding| tail (concentrated in `high_vol`) clears friction. This is
a **friction/hold refutation, not an absence-of-alpha refutation.**

**Honest friction sensitivity (disclosure, not re-tuning):** the refutation is
tight and fee-model-dependent. Median gross +$14.05 vs a $20 two-leg fee. Had I
pre-declared Phase 0's single-leg 10 bps fee, median net would be ≈ +$4.05
(pass). I pre-declared the **two-leg 20 bps** fee *before* seeing results because
a basis trade genuinely has two legs (4 fills); symmetric taker was chosen to
avoid optimism. Per the anti-Goodhart guardrail I am **not** revising it post-hoc
to flip the verdict.

**Basis-cleanliness caveat (from the Phase 2 mechanism check):** the frozen data
has one `close` series per symbol, so the hedge cancels price risk *by
construction, not by measurement*. Even had the median passed, the verdict would
have been **capped at KEEP-FLAG-GATED**, never ADOPT, until real perp/spot basis
execution is measured.

## Next step

Per the V255 plan's success frame, a clean refutation advances "profitable
reliably" by telling us where to aim. Two evidence-based, **pre-registerable**
(not retrofit) directions:

→ **V255.C — hold/level-scaled basis harvest (recommended if the funding lane
continues).** The alpha is confirmed; the loss is friction geometry. Pre-register
a longer hold (amortize the fixed 4-fill fee over more carry) and/or funding-level
position scaling (size ∝ |funding|, so capital concentrates where carry ≫ fee),
and/or maker-side execution. `high_vol` alone was net +$26.9k / median +$18.34 /
WR 66% — but restricting to it *now* would be post-hoc Goodhart; it must be a
pre-registered hypothesis with its own walk-forward falsifier. **Mandatory gate:**
V255.C cannot claim ADOPT without a real perp-mark + spot-index basis series to
retire the untested-hedge caveat.

→ **V254 Track C — on-chain flow as a primary universe (recommended if the funding
lane is judged closed).** If V255.C's realistic-friction net median is still ≤ $0,
the funding-carry ceiling (thin per-trade carry vs two-leg fees at daily
resolution) is structural, and on-chain flow is the next genuinely independent
universe. This is the pivot the V255 success frame names.

**Recommendation:** the confirmed gross alpha + confirmed separator + one robustly
profitable regime justify **one tight V255.C** (hold/scaling pre-registered, ~1
day, reuses everything here) before declaring the lane closed. If V255.C also
misses net, pivot to Track C.

## High-water table

**Unchanged.** V255.B is a parallel funding book with no Victoria high-water to
move; the spot baseline (crisis +$599 / trend +$2,997 / recent +$30) stands
untouched. This is a $0 offline refutation — the fast, cheap adjudication the
funding lane was chosen to provide.
