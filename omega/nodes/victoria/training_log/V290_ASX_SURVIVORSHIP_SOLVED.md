# V290 — The ASX survivorship blocker was never a data problem

**Date:** 2026-08-31
**Author:** claude
**Status:** FINDING + frozen artifact. No strategy claim.
**Supersedes the blocking caveat in:** [`V286_PHASE0_ASX.md`](V286_PHASE0_ASX.md) §5 · [`V289_PHASE0_ASX_SHORT_INTEREST.md`](V289_PHASE0_ASX_SHORT_INTEREST.md) §4/§7

---

## §1 — The finding

Every ASX result so far carried the same caveat: the universe was today's listed names,
so delisted companies were absent and any result was survivorship-biased. V286 §5 called
it "the specific threat to this specific result". V289 §7 escalated it to "the binding
constraint". I filed it upstream as the single most valuable thing the API could add.

**It was already there.** `GetMarketByDate` reads `FROM shorts s LEFT JOIN
"company-metadata" m` filtered on date alone (`postgres.go:1200`), so a company that
delisted in 2018 still has rows for every date up to 2018 and is returned for those
dates. Measured against prod:

| date | universe |
|---|---:|
| 2012-09-28 | 431 |
| 2015-06-30 | 471 |
| 2020-03-31 | 567 |
| 2024-06-28 | 667 |
| 2026-08-21 | 740 |

The universe **grows**, which is what genuine point-in-time membership looks like. And
the attrition is severe: **273 of the 471 names listed on 2015-06-30 (58%) are gone by
2026**, and they are all present in the historical snapshots.

## §2 — Why it stayed hidden, and the cost

`GetAvailableDates` returns **90 dates**. Every integrator asking *"how far back can I
query"* uses it, is told four months, and stops.

I did exactly that. V288 audited the API, concluded the history was ~4 months, and
recorded that it "does not solve the survivorship problem... four months cannot answer a
question that needs a decade." That was **wrong**, and it was wrong in the most expensive
possible way: it was a confident, documented negative that closed a line of enquiry which
was in fact open.

The error was the same one twice — **measuring one endpoint and generalising to the
dataset**. V288 §3 even stated the limit as decisive. It should have said "this endpoint
reports 90 dates" and tested another.

## §3 — The artifact

`data/frozen_series/asx/universe_pit/` — 35 quarter-end snapshots, **2012-12-31 →
2026-06-30**, md5-manifested, one request per snapshot.

| | |
|---|---:|
| universe 2012-12-31 | 393 |
| universe 2026-06-30 | 752 |
| **union of all codes ever seen** | **2,080** |
| a survivor-only view uses | **36% of the true universe** |

**64% of the historical ASX universe is invisible to any current-membership sample.**
V286 drew 20 names from it; V289 drew 66. Both were sampling from the surviving third.

## §4 — What this does to the standing findings

Neither is refuted. Both become **testable**, having previously been untestable.

- **V286's reversion finding** (MA-crossover mean-reverts, all 12 cells negative,
  OOS-stable). §5 named survivorship as the mechanism that would *manufacture* exactly
  that result, because names that fell and kept falling are the ones that delist. With
  2,080 codes this is now directly checkable, and it is the check most likely to kill it.
- **V289's short-interest finding** (negative IC at every horizon, sign-stable). §7 found
  the long-only excess was outlier-driven, with `unpriced_at_exit: 0` across 66 names
  over 15 years — an impossibility that proved the universe was 100% survivors. The
  outliers may well *be* the delisted names.

## §5 — The remaining gap is prices, not universe

The universe is solved; returns are not. yfinance has no prices for delisted codes, so
the 64% that matter most for de-biasing have short-interest history and **no return
series**. Computing a survivorship-free IC still needs price data for names that no
longer trade — which is upstream **#549** (no OHLCV in the API), now promoted from
convenience to the blocking item.

So the honest state: **the universe blocker is solved and the price blocker is not**, and
they were always two problems wearing one label.

## §6 — Next

1. **Re-run V286 §3 on the point-in-time universe** for the names that do have prices,
   and report how the result moves as coverage falls. The *direction* of the move is
   informative even where coverage is incomplete.
2. **Upstream #549** is now the single blocking ask. Filed comment on #541 and #537
   explaining that #537 (date discoverability) is what hid all of this.
3. Do not re-caveat future ASX work with "survivorship-biased universe" — say
   "survivorship-biased *returns*", which is the part that is still true.
