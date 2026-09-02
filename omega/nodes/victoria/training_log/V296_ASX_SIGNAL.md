# V296 — The first real test of the signal, and it is genuinely there

**Date:** 2026-09-03
**Status:** signal CONFIRMED at the cross-section; strategy NOT significant net of costs
**Upstream:** #579, #581, #583 all merged; 1,739 corrupt price rows removed

## 1. Eight versions of plumbing, one test of the signal

Every prior ASX version measured the apparatus. With the universe point-in-time,
the benchmark total-return, the screens live, the cap binding and the prices clean,
the signal could finally be interrogated directly. Three tests, none run before.

## 2. Short interest DOES order ASX returns

**Information coefficient** (Spearman, short % vs forward return, eligible names
only, hold 5d): mean **−0.0157**, median −0.0203, **t = −2.75**, negative in 55.4%
of 410 periods. Negative is the predicted sign: more shorted → lower forward
return. It is stable across every horizon tested, and at hold=1d over 2,027
periods it reaches **t = −5.33**.

That is the first statistically solid signal measurement this campaign has
produced on any asset class.

## 3. But it is not a monotonic ranking — it is a Q1 effect

| quintile | mean excess/wk | t |
|---|---|---|
| **Q1 (least shorted)** | **+0.299%** | **+3.16** |
| Q2 | +0.095% | +1.25 |
| Q3 | −0.020% | −0.33 |
| Q4 | +0.043% | +0.56 |
| Q5 (most shorted) | −0.018% | −0.18 |

Q1−Q5 spread: +0.317%/wk, t = +3.05.

Q2 through Q5 are indistinguishable from zero and from each other. So the
tradeable statement is **"the least-shorted quintile outperforms"**, NOT "short
interest ranks returns". Any construction that leans on ordering *within* the
bulk of the distribution is leaning on nothing, and the long-only design (V289 §7)
turns out to have been right for a reason it did not know.

## 4. Why the portfolio gets less than the quintile

Q1 is +0.299%/wk gross at t=3.16. The best portfolio configuration nets +0.150%/wk
at t=1.55. Three things account for the gap, in order of size:

- **Concentration.** `max_names=25` holds the extreme tail of Q1, not Q1. A breadth
  sweep confirms the edge is broad and shallow — t peaks at 100 names (1.55) and
  collapses at 300 (0.22, where the book has diluted into Q2).
- **Delisting drag.** A name that vanishes before the exit contributes 0 return
  while still holding weight. The quintile test excludes such names entirely; the
  portfolio does not, and that is the honest treatment.
- **Costs.** 0.07-0.09%/period against ~0.22% gross — about 30%, material but not
  decisive. Turnover was the suspected killer and is not.

| max_names | t |
|---|---|
| 25 | +1.40 |
| 75 | +1.52 |
| **100** | **+1.55** |
| 150 | +1.48 |
| 300 | +0.22 |

## 5. Horizon

Holding longer raises per-period return faster than cost, but sample size falls:

| hold | n | mean/period | t | annualised excess |
|---|---|---|---|---|
| 5d | 414 | +0.150% | +1.55 | +7.6% |
| **10d** | 207 | +0.382% | **+1.94** | **+9.6%** |
| 21d | 98 | +0.510% | +1.42 | +6.1% |
| 63d | 32 | +1.623% | +1.78 | +6.5% |

Best is 10 days: **+9.6%/yr excess, t = 1.94**.

## 6. The honest verdict

The **signal is real** — IC t = −2.75 over 410 periods, t = −5.33 daily, Q1 t = +3.16.
The **strategy is not proven**: no configuration clears t = 2 net of costs and
delisting drag. +9.6%/yr excess at t = 1.94 is suggestive, is the best result this
campaign has produced, and is still short of the bar.

This is the first version where the thing that failed was the *implementation of a
real edge* rather than a measurement artifact. Every previous negative dissolved
into a data defect on inspection; this one does not.

## 7. What follows

- **Sector neutrality (#557, open).** Q1 may be loading on a sector — least-shorted
  names cluster. Until GICS is point-in-time this cannot be ruled out, and it is
  the single most likely alternative explanation for the Q1 effect.
- The Q1-only shape argues for a **binary in/out** construction rather than a
  ranked weighting, since the rank carries no information below Q1.
- Delisting drag is now a measurable cost; #576's `has_price_history` flag makes
  it quantifiable rather than assumed.
