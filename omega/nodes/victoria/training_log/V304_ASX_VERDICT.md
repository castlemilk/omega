# V304 — The edge is real where it cannot be traded, and tradeable where it is not real

**Date:** 2026-09-03
**Status:** ASX line of work reaches a verdict
**Supersedes:** V299 and V301 capacity figures (computed on the return V303 corrected)

## 1. Capacity, on the corrected return

Everything the earlier attempts got wrong, fixed together: gaps excluded rather
than charged 0% (V303), universe-relative excess so the sample is 2015-2026 rather
than XJT's 2019+ (V301), selectivity expressed as a fraction of the drawn universe
so the tercile comparison is not confounded, and square-root impact against each
name's own point-in-time ADV.

Annualised net excess vs the eligible universe, top 20%, k=0.5:

| universe | hold | $1M | $5M | $20M | $50M |
|---|---|---|---|---|---|
| all eligible | 5d | −1.14% | −6.20% | −15.06% | −21.74% |
| all eligible | 21d | +1.72% | −0.34% | −3.94% | −6.74% |
| **all eligible** | **63d** | **+4.87%** | **+4.00%** | **+2.52%** | **+1.39%** |
| thinnest tercile | 5d | −10.57% | −24.19% | −38.87% | −41.15% |
| thinnest tercile | 21d | −4.82% | −10.09% | −15.88% | −16.77% |
| thinnest tercile | 63d | +3.55% | +1.54% | −0.74% | −1.14% |

Only **quarterly** rebalancing survives contact with a realistic cost model, and
only over the whole eligible universe. At $5M: **+4.00%/yr, t = +1.78, n = 47.**

## 2. The finding that ties the whole line of work together

V301 established that the Q1−Q5 spread is **strongest in the thinnest tercile**
(t = +4.08). This table shows a long-only book drawn from that same tercile
**loses money at every horizon** except quarterly, and is barely positive there
(t = +0.43).

Both are true, and together they are the answer:

**The premium concentrates exactly where impact costs are highest.** The thinness
that creates the neglect is the same thinness that makes the neglect unharvestable.
That is not a disappointment — it is the mechanism. A neglect premium *persists*
because it cannot be arbitraged, and it cannot be arbitraged for the same reason
it is measurable: nobody can trade size in a $1.2M/day stock without moving it.

Every earlier version of this campaign was looking for an edge that costs had not
yet eaten. This one explains why the edge exists at all, and the explanation is
that costs eat it.

## 3. The honest verdict on the ASX line

- **The statistical fact stands**: Q1−Q5 spread +0.298%/wk, **t = +2.85** over 590
  weekly periods, replicated out of sample (V303-corrected). Least-shorted ASX
  names outperform, concentrated in the least-liquid third.
- **It is not a strategy.** The only configuration that is net positive after
  realistic impact — quarterly, whole universe — earns ~+4%/yr at $5M on 47
  periods with t = +1.78. That is not significance, and +4%/yr is not worth the
  operational surface of a live book.
- **Breakeven is entirely a function of k**, which was never measured: $200M at
  k≤0.5, $10M at k=1.0 for quarterly. The one number that decides it is the one
  nobody has calibrated.

## 4. What would change the verdict

Only two things, and neither is more analysis of this data:

1. **A measured k.** Real fills on ASX microcaps. Everything else is now downstream
   of this single unmeasured parameter, and no amount of further backtesting
   substitutes for it.
2. **A cheaper way to hold the exposure.** The edge is in illiquid names at
   quarterly frequency; anything that reduces impact — patient limit orders,
   crossing, longer holds still — attacks the only binding constraint.

## 5. Nine versions, and what actually got built

The ASX line found no tradeable strategy. It did find, fix and upstream six data
defects (#572, #576, #577, #582, #584, and the paging bug), correct four of its own
methodology errors (concentration cap, weekly bucketing, benchmark misuse, data
gaps), and end with a coherent economic explanation rather than a number.

The three rules the campaign now carries, each bought with a version:

- V293: an input that quietly evaluates to something is worse than one that errors.
- V302: read the metadata the response returns about itself.
- V303: a missing input must be excluded, never defaulted.

All three describe the same failure, and all three were learned from results that
looked good before they looked wrong.
