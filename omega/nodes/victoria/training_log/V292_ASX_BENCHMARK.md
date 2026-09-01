# V292 — The ASX benchmark landed, and the edge did not survive it

**Date:** 2026-09-01
**Status:** measured, negative
**Upstream:** castlemilk/shorted.com.au#556 (landed), #565 (fixed), #572 (filed today)

## 1. What changed upstream

`MarketService/GetIndexSeries` shipped. Before today the ASX engine had no index
at all and `benchmark_relative()` proxied "the market" with an equal-weight
average of the surviving names in its own universe.

`ordinaryOnly` (#565) is also fixed: `totalCount=691`, page=691, all `ordinary`,
against 740 unfiltered (`ordinary 691 / etf 24 / debt 21 / other 4`).

## 2. A prediction of mine that was wrong, and its sign

I recorded the old proxy as "wrong in a way that flatters the strategy."
Measured against XJT over 100 weekly periods:

| comparator | mean excess / period |
|---|---|
| real index (XJT, total return) | **+0.445%** |
| old survivor-only universe proxy | **+0.198%** |

The proxy was **harsher**, not kinder — it understated excess by 0.247%/period.
A survivor-only *benchmark* is a higher bar, because survivors outperformed. I
had conflated it with survivorship bias in the strategy's *own* universe, which
is a separate effect, still present, and still flattering. Two biases, opposite
signs, and I had asserted the sign of the wrong one.

## 3. Total-return vs price-only is worth 3.7%/yr

Over the identical window: **XJT +19.35%, XJO +11.64%** — 7.7pp over two years.
The engine's prices are dividend-adjusted, so benchmarking against price-only XJO
would have manufactured that entire gap as alpha. `benchmark.py` defaults to XJT
and logs a warning if a price-only index is selected.

## 4. The result

Weekly rebalance, 20bp round trip, 100 periods, 2024-09-02 → 2026-08-28:

- strategy: mean +0.635%/period, median +0.889%, hit 56.0%, costs 3.14% of NAV
- excess vs XJT: mean **+0.445%**, median +0.695%, hit 56.0%, sd 3.63%
- **naive t = 1.23** — and that is before overlap adjustment. Hold is 5 days on a
  daily grid, so periods overlap ~5x; effective n ≈ 20 and t ≈ 0.55.
- top 3 of 100 periods carry **67%** of the total excess (+11.81%, +10.65%, +7.36%).
  Excluding them: mean falls +0.445% → **+0.151%**.

**Not an edge.** This is the V289 §7 shape exactly, now on a different asset class:
a positive mean, a respectable-looking median, and two-thirds of the total sitting
in three weeks out of two years.

## 5. Standing pattern, sixth instance

V283, V284, V285, V289, V291, and now V292: *a stable IC is necessary and nowhere
near sufficient*. Six clean measurements have failed to become PnL. The measuring
apparatus is not the bottleneck and has not been for some time.

## 6. What the benchmark still cannot do

The index serves ~2 years; `GetStockData` serves ~16. The benchmark covers **11%**
of the frozen price history, so the decade-long study still has no comparator for
89% of its span. Filed as #572 (backfill XJT; signal truncation when `period:10Y`
silently returns 2Y; mark total-return vs price-only in `ListIndices`).

Periods outside coverage return `None`, never `0.0` — a silent zero would read as
"the market was flat" and hand the strategy the market's whole return as excess.
`tests/test_asx_benchmark.py` pins this, and pins the 2024-09-02 floor so that a
successful backfill *fails the test* rather than leaving the docs stale.
