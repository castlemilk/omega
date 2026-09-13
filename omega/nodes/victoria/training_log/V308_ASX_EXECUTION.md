# V308 — V304's capacity table was an execution schedule in disguise

**Date:** 2026-09-13
**Status:** PRE-REGISTERED — re-computation on frozen data; no new alpha claimed; results blank below until the run is done.
**Parent:** V307 (the intraday map) / V304 (the verdict being re-priced)

---

## 1. The bet, in one sentence

V304's "positive at $5M, quarterly" rests on charging square-root impact against
**full-day** ADV, which is an unstated assumption that every rebalance is worked
across the whole session. V307 measured where ASX liquidity actually is — 36% of the
day in the closing auction, 47% in the last hour plus auction — so the same trade
executed in one of those windows meets **0.36×** or **0.47×** the volume, and impact
rises by the square root of that. **The bet is that the quarterly book stays net
positive at $5M under every schedule, and that breakeven AUM shrinks in proportion
to the volume share.**

## 2. Why this is worth a version

Two reasons, and the second is the real one:

1. It is the only thing the V307 map feeds directly, and V304 §4(2) named "a
   cheaper way to hold the exposure" as one of two things that could move its
   verdict. Making the schedule explicit is the first step to pricing one.
2. **The V299/V301/V304 capacity numbers were never committed as code.** They were
   produced in-session and exist only as tables in three journal entries. That is
   the failure V305 warned about — new code written fast — in its purest form: a
   result nobody can re-run. This version writes the computation down, and gates
   itself on reproducing V304's row before it changes anything.

## 3. Method (pre-declared)

- **Substrate:** the frozen v3 point-in-time panel (1,941 codes, 1,005 priced,
  2015-10 → 2026-09), `ApiPriceSource` over `v3/prices` (despiked, #582), short
  series from `v3/shorts`, publication lag 7 days (`panel.knowable_short`).
- **Book:** the V304 configuration. Quarterly rebalance (every 63rd session of
  BHP's calendar from 2016-01), long-only, least-shorted **20%** of the eligible
  universe with `max_names` lifted (selectivity is a fraction of the drawn
  universe, V304 §1), 8% concentration cap, screens `min_adv_aud=500k` and
  `min_price_aud=0.20`. Gaps excluded, delistings charged 0% (V303).
- **Excess:** per period, net return minus the equal-weight return of the
  *eligible* universe (same screens) over the same window. Annualised ×4.
- **Cost, per side:** 15 bp spread and fees (V299; the engine's `CostModel`
  default), plus impact `k · σ · sqrt(participation)`, where for each name traded
  at a rebalance: notional = AUM × |Δw|, participation = notional / (**s** ×
  ADV20 at that date), σ = trailing 60-session daily return sd at that date.
  A name with no σ or ADV at the date is charged at that period's median (a cost
  input, not a return observation) and the count is reported.
- **The new axis, `s` — share of ADV available to the schedule:**
  `1.00` full-day VWAP (V304's implicit assumption), `0.47` last hour + closing
  auction, `0.36` closing auction only. From the V307 5m profile.
- **Grid:** AUM {1, 5, 20, 50}M × k {0.25, 0.5, 1.0} × s {1.00, 0.47, 0.36}, plus
  breakeven AUM per (k, s) by bisection.

## 4. Falsifiers (pre-declared)

**F0 — reproduction gate.** At s = 1.00, k = 0.5, the 63-day row must land within
**±0.75 pp** of V304 §1's `all eligible / 63d` row: **+4.87 / +4.00 / +2.52 /
+1.39** at $1M / $5M / $20M / $50M. If it does not, the re-pricing below is still
reported but labelled *on a reconstruction that does not reproduce V304*, and the
discrepancy is the finding.

**F1 — the bet.** At $5M, k = 0.5: net excess stays **> 0** under s = 0.36. If it
turns negative, V304's "positive at $5M" was schedule-dependent and the verdict
must be restated as *positive only if worked across the day*.

**F2 — the scaling check.** Under the square-root law with a fixed spread
component, breakeven AUM is linear in s (impact ∝ sqrt(Q/(s·V)) ⇒ Q* ∝ s). The
measured breakeven at s = 0.36 must be **0.36× the s = 1.00 breakeven within
±15%**. This is a check on the implementation more than on the market; a miss
means the code is not computing what §3 says.

**Pre-declared expectation:** F1 holds (impact at $5M is a ~1 pp/yr line item and
1.67× of it is still under the ~4.9 pp gross-of-impact margin), and breakeven AUM
falls from V304's "~$200M at k ≤ 0.5" to roughly **$70M** auction-only and
**$95M** last-hour. Which is to say: the schedule matters at size and not at the
size anyone here would run.

## 5. Not in scope

- The spread component is held at 15 bp/side for every schedule. An auction
  print pays no half-spread and a continuous order does; without spread data that
  difference is not modelled, and it would *favour* the auction schedule. Noted,
  not assumed.
- No k is measured. Everything here is still conditional on V299's unmeasured k.
- The thinnest-tercile book is not re-priced: it was already negative at 63d in
  V304 and the schedule can only make it worse.

## 6. Artifacts

`scripts/v308_asx_execution_schedule.py` → `data/asx_runs/v308_execution_schedule.json`.
`omega/nodes/asx/engine.py`: each period now records its `weights` (additive; the
rebalance trade cannot be priced without the book that was traded).

---

## 7. Results

_(blank at pre-registration)_

## 8. Verdict

_(blank at pre-registration)_

## 9. Next

_(blank at pre-registration)_
