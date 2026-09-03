# V299 — Capacity, and the rebalance frequency that decides it

**Date:** 2026-09-03
**Status:** the binding constraint quantified; strategy viable only at small size
**Depends on:** V296 (Q1 t=+3.16), V297 (survives sector-neutralisation), V298 (neglect premium, zero in the liquid third)

## 1. Why capacity became the question

V298 put the edge in $1–6M/day names and exactly zero in the most-traded third.
A flat 20bp round trip is the wrong cost model for that: it ignores the component
that scales with *your own size*, which is the only component that matters when
the edge lives at the thin end.

Cost model, per side: 15bp spread and fees, plus square-root impact
`k · σ · sqrt(participation)` with participation measured against each name's own
point-in-time ADV and σ its own daily volatility (median **5.26%** — these are
volatile microcaps, and that is what makes impact bite). k is not tuned; tuning a
cost model until a strategy passes is the exact failure this campaign exists to
avoid.

## 2. The result is sensitive to k, so the sensitivity IS the result

V291's rule: where a result is sensitive to methodology, report the sensitivity,
not the result. Published calibrations of the square-root law put k in roughly
0.3–1.0, and the verdict moves across that range.

Weekly rebalancing, 100 names — largest AUM with positive net excess:

| k | breakeven AUM |
|---|---|
| 0.25 | $10M |
| 0.50 | $2M |
| 0.75 | $1M |
| 1.00 | $0.5M |

A twentyfold range. What is NOT sensitive is the order of magnitude of the
conclusion: **at weekly rebalancing this is a single-digit-millions strategy under
every plausible calibration.** The gross edge (~+0.22%/wk) is simply not large
relative to the cost of trading names this thin.

## 3. Rebalance frequency is worth more than any other lever

The signal is slow — V296 found IC stable out to 63 days — so weekly rebalancing
pays turnover for information that has not changed. Annualised net excess, k=0.5:

| hold | $1M | $5M | $20M | $50M | $100M |
|---|---|---|---|---|---|
| 5d | +2.91% | −2.82% | −12.92% | −20.19% | −23.43% |
| 10d | +6.21% | +2.00% | −5.25% | −10.19% | −12.29% |
| 21d | +3.50% | +0.28% | −4.88% | −8.22% | −9.65% |
| 42d | +2.91% | +0.95% | −2.06% | −4.00% | −4.87% |
| **63d** | **+5.29%** | **+3.84%** | **+1.62%** | **+0.12%** | −0.54% |

Breakeven AUM at k=0.5 goes **$2M (weekly) → $50M (quarterly)**, a 25x
improvement from doing less. That is the largest single effect found anywhere in
the ASX work, and it comes from matching trading frequency to the signal's decay
rather than to the data's frequency.

## 4. Honest position

- The premium is real (V296–V298) and is a neglect premium, not a short-interest
  signal.
- Traded quarterly it is economically positive up to roughly $20–50M at k=0.5,
  earning +1.6% to +5.3%/yr excess depending on size.
- **But it rests on 32 independent quarterly periods** (t ≈ 1.8), which is not
  significance. The capacity analysis is therefore conditional on an edge that is
  itself unproven.

Those two weaknesses are independent and both must be fixed before this is
tradeable: more periods (or a second market) for the statistics, and a real
impact calibration for the economics.

## 5. What would actually settle it

1. **Calibrate k rather than assume it.** Any live or paper fills on ASX microcaps
   would pin the one number the verdict swings on. This is the highest-value
   measurement available and needs no new research.
2. **Extend the sample.** 2019-04-29 is an upstream floor for XJT (#573, cannot be
   backfilled), but XKO reaches 2013 and is price-only — usable for a Q1−Q5 spread
   test, which is benchmark-relative and so unaffected by the missing dividends.
   That would roughly double the period count.
3. **#576** — delisting drag is still charged as a zero return. With ~39% of the
   universe unpriceable, this remains the largest unquantified bias in the work.
