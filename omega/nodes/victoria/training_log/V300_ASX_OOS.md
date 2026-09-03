# V300 — The Q1 effect replicates out of sample; the neglect story does not (yet)

**Date:** 2026-09-03
**Status:** core finding CONFIRMED out of sample; V298's mechanism unconfirmed
**Depends on:** V296–V299

## 1. How an out-of-sample test was possible at all

XJT (total return) starts 2019-04-29 and #573 states it cannot be backfilled. But
a **Q1−Q5 spread is benchmark-relative — the benchmark cancels** — so a spread
test needs no index, and "Q1 vs the eligible universe" needs none either. That
frees the sample from XJT's floor and back to where prices exist: 2015-10-15.

The universe was re-enumerated from 2013 rather than 2019, adding 283 codes that
existed then and have since delisted.

## 2. The result

Weekly, all eligible names:

| period | n | Q1−Q5 spread | t | Q1 vs universe | t |
|---|---|---|---|---|---|
| 2015-10 → 2019-04 (**OOS**) | 191 | +0.223% | +1.74 | **+0.224%** | **+2.83** |
| 2019-04 → 2026-09 (IS) | 399 | +0.298% | +2.66 | +0.182% | +2.82 |
| **FULL** | **590** | +0.274% | **+3.17** | **+0.196%** | **+3.87** |

The Q1-vs-universe effect is **+0.224% out of sample against +0.182% in sample**,
with t≈2.8 in both halves. That is as close to a clean replication as this data
allows, on a period no part of the strategy was developed against.

Full sample: **t = +3.87 over 590 weekly periods.** This is the strongest result
the campaign has produced on any asset class.

## 3. The survivorship caveat, and why it makes this conservative

All 283 pre-2019 codes are **unpriceable** (#576) — the universe grew 1,658 →
1,941 while priced names stayed at 1,005. So 2015-2019 is survivor-only.

The direction is knowable rather than merely acknowledged: heavily-shorted names
delist more often, so dropping failures inflates Q5 and **understates** the
spread. The OOS number is therefore a floor, not a point estimate. It is the only
reason the test is worth running under this bias.

## 4. Where V298's mechanism does NOT replicate

Restricting to the thin two terciles, where V298 located the entire edge:

| period | n | spread | t |
|---|---|---|---|
| 2015-10 → 2019-04 (OOS) | 150 | +0.102% | **+0.59** |
| 2019-04 → 2026-09 (IS) | 339 | +0.331% | +2.39 |

In-sample the thin names carry the effect; out of sample they do not. n=150 is
small and this is one noisy estimate rather than a refutation, but it is exactly
the shape of a finding that was fitted to one period.

**V298's headline stands, its mechanism is now provisional.** The claim "the edge
lives in the thin two terciles and is zero in the liquid third" was measured on
2019-2026 only, and the earlier period does not confirm it. V299's capacity
analysis is built on that mechanism, so the $20–50M quarterly capacity figure
inherits the doubt.

## 5. Standing position

- **Least-shorted ASX names outperform**: replicated, t=+3.87 over 590 weeks, with
  a survivorship bias that runs against the finding. This is now solid.
- **Why** they outperform: unresolved. Neglect (V298) fits 2019-2026 and not
  2015-2019.
- **Whether it is tradeable**: unresolved, and now doubly so — V299's capacity
  rests on V298's mechanism.

The campaign has, for the first time, a robust empirical fact and an unresolved
explanation, rather than an artifact and a story. That is the right order.

## 6. Next

1. Re-run V298's tercile split on the full 2015-2026 sample rather than 2019+.
   One run; decides whether the mechanism survives.
2. #576 remains the binding data gap and is now quantified precisely: 936 of 1,941
   codes unpriceable, including 100% of the pre-2019 delisted names.
