# V293 — #572 landed, and the result it enabled was a data defect

**Date:** 2026-09-01
**Status:** measured, negative — and now trustworthy
**Upstream:** shorted.com.au#572 → #573 (index depth + truncation signal), #551 (liquidity, now effectively closed by `volume` on GetStockPrices)

## 1. What #573 gave, and the tension it exposed

Index coverage is no longer 2 years:

| index | return type | coverage | sessions |
|---|---|---|---|
| XAO / XJO | **price** | 2006-09-01 → 2026-09-01 | ~5,050 |
| XKO | **price** | 2013-03-05 | 3,339 |
| **XJT** | **total** | **2019-04-29** | 1,860 |

Truncation is now signalled: XJT with `period:10Y` returns `truncated=true,
requested_from=2016-09-01, covered_from=2019-04-29`. `return_type` is a real
field, so `benchmark.py` reads the price/total classification from the data
instead of the hardcoded code list I had guessed with.

**The tension:** every series deeper than XJT is price-only. A longer study can
only be bought by giving up dividends — upstream measured that trade at XJO 24.2%
vs XJT 37.6% on the same window. So the study window is 2019-04-29, and that is
an upstream floor #573 states cannot be backfilled.

## 2. A correction to V292

V292 said the 2-year t=1.23 was inflated by ~5x overlap ("effective n≈20, t≈0.55").
**Wrong.** `engine.run` steps by `hold_periods`, so weekly periods are disjoint —
verified: period start-index gaps are exactly `[5]`. t=1.23 was the honest number.
The conclusion (not significant) was unaffected; the reasoning was not.

## 3. The first 7.3-year run was unreadable, and that was the finding

Extending to the full XJT window produced mean excess +1.100%/wk, t=1.89 — and
**sd = 11.2% per week**, which is not a plausible equity number. Decomposed:

| week | name | move | contribution |
|---|---|---|---|
| 2024-08-12 | AEU | $0.0140 → $0.3500 (**+2400%**, exactly 25.0×) | **+200%** |
| 2020-04-06 | SHO | $0.0050 → $0.0230 (+360%) | +40% |
| 2021-03-10 | 88E | $0.1974 → $0.4935 (+150%) | +15% |

Two distinct defects:

1. **No liquidity or price screen.** `min_adv_aud` had been declared and inert
   since the engine was written (#551). The book was ranking sub-cent stocks where
   one tick is a +20% return, in cross-sections of 9–12 names.
2. **A bad price freeze.** AEU's exact 25.0× is a share consolidation, and the API
   holds *no* price history for AEU at all — it was a yfinance artifact. 88E,
   checked against the API, was **real** (+135% on 27–37M shares: the Alaska
   drilling spike). Not every outlier was a bug, which is why they had to be
   checked one at a time rather than winsorised away.

## 4. The fix: upstream prices, and a real ADV filter

`GetStockPrices` returns `adjusted_close` (splits **and** dividends) plus
`volume`, on the same ticker convention and dates as the short series. Refroze
55/69 names from it — the 14 without upstream history are disproportionately the
dead microcaps, AEU among them. `ApiPriceSource.adv20` computes trailing 20-session
dollar volume **point-in-time** (a name with <20 prior sessions gets no value, not
a short-window average). Screens run **before** ranking, so an excluded name cannot
shift the quantile boundary. A missing ADV excludes rather than passes — V279.

Live: `min_adv_aud=$500k/day`, `min_price_aud=$0.20`. Dropped 4,528 name-days on
liquidity and 2,847 on price.

## 5. The clean result

2019-04-29 → 2026-08-28, 379 non-overlapping weeks, 20bp round trip, vs XJT:

- sd **11.2% → 3.75%** — the microcap noise was the variance
- mean excess **+0.142%/wk**, median +0.131%, hit 52.5%, **t = 0.74**
- **excluding the top 3 weeks: mean −0.017%, t = −0.10**
- top-3 share **1.12** — those three weeks exceed the entire total; the rest is net negative
- H1 t=0.77, H2 t=0.15 — no persistence across halves

**No edge.** But unlike V292 this is a *trustworthy* no: correctly adjusted prices,
one adjustment methodology, a real liquidity screen, a genuine total-return
benchmark, disjoint periods.

## 6. Standing pattern, seventh instance

V283, V284, V285, V289, V291, V292, V293: *a stable IC is necessary and nowhere
near sufficient*. V293 adds a sharper form of it — **an unscreened universe will
manufacture a t-statistic out of tick size.** The apparatus that found this (screens
before ranking, point-in-time ADV, per-outlier verification against a second source)
is worth more than the negative result it returned.
