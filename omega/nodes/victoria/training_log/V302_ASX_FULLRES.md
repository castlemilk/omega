# V302 — The panel had been weekly averages the whole time

**Date:** 2026-09-03
**Status:** substrate defect found and fixed; every result strengthens
**Depends on:** V296–V301

## 1. The defect, which was mine

`GetStockData` buckets 5Y/10Y/MAX into **weekly averages by default**. The builder
requested `{"productCode": c, "period": "max"}` and nothing else, so the entire
short-interest panel — every result from V296 to V301 — was computed on weekly
means rather than observations.

BHP: **846 bucketed points against 4,085 real ones.** Across the universe,
**461,469 observations became 2,119,446** once `full_resolution: true` was set.
The API had been reporting `downsampled: true` on every one of those responses and
I never read the field.

`max_points: 0` was also missing, and `as_of` — which exists precisely so a caller
does not hand-roll a publication lag (#550) — was never used, so
`panel.knowable_short`'s blunt 7-day offset was doing work the API offers to do
correctly.

## 2. No lookahead, but that was luck

A weekly bucket labelled D contains days after D, so averaging is a lookahead
hazard. It did not bite here only because `knowable_short` applies a 7-day lag,
which happens to cover exactly one bucket. Had the lag been 3 days — a defensible
choice for T+4 publication — every result since V296 would have been contaminated
and nothing in the pipeline would have said so.

## 3. Every result strengthens

| measurement | weekly-bucketed | full resolution |
|---|---|---|
| Q1 vs universe, OOS 2015-19 | t=+2.83 | **t=+3.05** |
| Q1 vs universe, IS 2019-26 | t=+2.82 | **t=+3.13** |
| **Q1 vs universe, FULL (n=590)** | t=+3.87 | **t=+4.24** |
| Q1−Q5 spread, FULL | t=+3.17 | **t=+3.42** |
| thinnest tercile spread, FULL | t=+3.63 | **t=+4.08** |
| thinnest tercile, OOS | t=+1.64 | **t=+1.87** |

Uniformly stronger, which is the direction better data should move a real effect.
An improvement that arrived from a *defect* would be the warning sign — this one
arrived from removing noise, and the OOS/IS agreement held throughout.

## 4. Standing position

- **Least-shorted ASX names outperform**: t = **+4.24** over 590 weekly periods,
  replicated out of sample (t=+3.05 OOS, t=+3.13 IS), survivorship bias running
  against the finding.
- **Concentrated in the least-liquid third** (~$1.2M/day ADV): t = **+4.08** full
  sample, monotone across terciles in both halves, zero-to-negative among heavily
  traded names.
- Capacity remains the open question and remains worse than V299 estimated.

## 5. The lesson, which is the same one as V293

Eight versions found data defects by measuring something that looked like a
result. This one was found by reading a proto comment while looking for something
else, and the API had been announcing it in a response field the whole time.

The rule this campaign already had — *an input that quietly evaluates to something
is worse than one that errors* — needs a companion: **read the metadata the
response returns about itself.** `downsampled: true` was there on every call.
