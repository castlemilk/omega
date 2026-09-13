# V308 — V304's capacity table was an execution schedule in disguise

**Date:** 2026-09-13
**Status:** COMPLETE — pre-registered at `7b5eb983` before the script ran. F0 FAIL (V304 not reproduced; comparator identified), F1 FAIL, F2 PASS. The ASX verdict is restated in §8.
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

**Run:** 48 quarterly dates 2016-01-04 → 2026-08-18, **47 periods** (V304's n
exactly), 990 codes in the panel, median eligible cross-section 240, median book
50 names. Absolute, net of explicit cost: mean **+3.21%/qtr**, median +3.53%,
hit rate 63.8%, top-3 share 45% (not outlier-driven).

### 7.1 The harness defect this version had to fix first

The first run reproduced nothing (−2.1% at $1M against V304's +4.9%) because
`engine.run` built its own panel from the **default price source — the old
68-name survivor freeze** — and had no parameter to take the v3 substrate. Every
V294→V304 point-in-time result must therefore have been produced by assembling
the panel by hand outside the engine, which is precisely why none of them were
reproducible from a script. `run()` now takes `price_source` and `short_series`
(additive); with v3 passed through, the period count lands on 47.

### 7.2 F0 — reproduction: FAIL, and the decomposition says why

At s = 1.00, k = 0.5 (annualised net excess, %/yr):

| | $1M | $5M | $20M | $50M |
|---|---:|---:|---:|---:|
| V304 §1 | +4.87 | +4.00 | +2.52 | +1.39 |
| **reconstruction (vs EW eligible universe)** | **−0.51** | **−1.97** | **−4.61** | **−7.68** |
| Δ pp | −5.38 | −5.97 | −7.13 | −9.07 |

Impact at $1M is 0.30%/qtr, so the 5-point gap is in the **gross** number.
Per-period means at $1M, k = 0.5, s = 1:

| component | %/qtr |
|---|---:|
| book gross | +3.376 |
| explicit cost (15 bp/side) | −0.162 |
| impact | −0.296 |
| **comparator: EW eligible universe** | **3.045** |
| comparator: EW whole panel | 5.681 |
| comparator: *median* eligible name | 1.725 |

Annualised net excess at $1M **by comparator**: vs EW eligible **−0.51**; vs EW
whole panel −11.05; **vs median eligible +4.77 — V304's +4.87 to within 0.1 pp.**
V304's code is not committed, so this is inference, but no other definition in
the neighbourhood lands within five points. The journal's "universe-relative
excess" was, on the evidence, the book against the *median* name.

That comparator is wrong for this book. The book is **equal-weight**; a random
equal-weight 20% draw from the universe earns the universe's equal-weight mean,
not its median. On a right-skewed microcap universe the median name trails the
mean by 1.3 pp/qtr, and that gap is the entire "edge".

### 7.3 The grid (annualised net excess, %/yr, vs EW eligible universe)

| schedule | s | k | $1M | $5M | $20M | $50M | breakeven AUM |
|---|---:|---:|---:|---:|---:|---:|---:|
| full-day VWAP | 1.00 | 0.25 | +0.09 | −0.65 | −1.97 | −3.50 | $1.31M |
| full-day VWAP | 1.00 | **0.5** | −0.51 | −1.97 | −4.61 | −7.68 | **$0.33M** |
| full-day VWAP | 1.00 | 1.0 | −1.69 | −4.61 | −9.90 | −16.05 | — |
| last hour + auction | 0.47 | 0.25 | −0.19 | −1.25 | −3.18 | −5.42 | $0.62M |
| last hour + auction | 0.47 | 0.5 | −1.05 | −3.18 | −7.04 | −11.52 | $0.15M |
| last hour + auction | 0.47 | 1.0 | −2.77 | −7.04 | −14.75 | −23.72 | — |
| auction only | 0.36 | 0.25 | −0.31 | −1.53 | −3.73 | −6.29 | $0.47M |
| auction only | 0.36 | 0.5 | −1.29 | −3.73 | −8.14 | −13.26 | $0.12M |
| auction only | 0.36 | 1.0 | −3.27 | −8.14 | −16.95 | −27.19 | — |

t-statistics at k = 0.5, full-day: −0.19 / −0.76 / −1.77 / −2.92 across the four
sizes. 177 name-rebalances (of several thousand) had σ or ADV defaulted to the
period median; reported, not hidden.

**F1 — FAIL.** $5M, k = 0.5, auction-only: **−3.73%/yr.** But so is full-day
(−1.97%): the schedule did not decide it, the comparator did.

**F2 — PASS.** Breakeven ratio auction/full-day at k = 0.5: **0.360** against the
predicted 0.36. The implementation computes what §3 says; the square-root law
scales exactly as derived.

## 8. Verdict

**The one positive configuration in the ASX line does not survive a committed
reconstruction with the right comparator.** Against its own equal-weight eligible
universe, the quarterly least-shorted book is net negative at every size and
schedule for k ≥ 0.5, and clears zero only at $1M with k = 0.25 (+0.09%/yr). Gross
of all costs it earns ~+1.3%/yr over its universe — a real but small long-only
residue of the V303 spread, which was always a long-*short* statistic — and
explicit cost (0.65%/yr) plus impact (1.2%/yr at $1M) eat it.

The execution-schedule question is therefore moot: it moves breakeven from $0.33M
to $0.12M, which is the difference between two sizes nobody would run. F2's exact
scaling stands as a check that the pricing code is right.

**Restated ASX verdict, superseding V304 §3:** the neglect *spread* is a
statistical fact (V303, t = +2.85, long-short, weekly); the long-only *book* built
from it has no net edge over its universe at any frequency, size or schedule
under the stated cost model. Nothing in V286→V308 supports trading the ASX from
this data, daily or otherwise.

Two rules bought here, both about the same thing:

- **A capacity number that exists only in a journal is not a result.** The
  V299–V304 tables could not be re-run, and the first attempt to re-run them
  found the harness could not even build the right panel. This script is the
  first ASX capacity figure anyone can reproduce.
- **The comparator is part of the strategy.** V304's edge was the distance between
  a mean and a median. Report the comparator's definition next to every excess,
  and match its weighting to the book's.

## 9. Next

- **V309 — the forward ASX lane, re-scoped by this result.** Not a paper book
  claiming PnL: a forward, daily, no-broker job that appends prices, short
  positions and the 1h bars to the frozen substrate, and each week records the
  realised **Q1−Q5 spread** and the **Q1 minus EW-universe excess** with the
  comparator written into the artifact. One un-Goodhartable observation per week
  of the only ASX statistic that is real. If the spread persists forward at the
  V303 rate, a long-short version becomes the thing to price — with borrow, which
  V289 ruled out for a retail account, priced explicitly.
- **Not queued:** further re-pricing of the long-only book. It is negative before
  the schedule matters.
- **Housekeeping:** V304 §1's table should be read with this entry beside it. The
  journal is not rewritten; the correction is a later entry, as with V303.
