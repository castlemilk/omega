# V295 — #582 fixed at source, and the first clean ASX measurement

**Date:** 2026-09-02
**Status:** measured, clean, NOT significant
**Upstream:** shorted.com.au#582 root-caused and fixed (PR #583); 1,739 corrupt rows removed from production

## 1. Root cause

Alpha Vantage does not reject an exchange suffix it does not carry. Asked for
`AMD.AX` it resolves to the base symbol and returns **NASDAQ's AMD**. The only
thing in the payload that distinguishes that from a correct answer is the
`Meta Data` block, and the provider parsed it away — stamping every record with
the symbol *requested* rather than the one returned.

The production path: on an ASX holiday the Yahoo provider returns no data, the
chain in `sync.go` falls through to Alpha Vantage, and the wrong security's price
is written. Boxing Day 2025 did it across the universe.

The fingerprint was in the data all along: genuine ASX rows carry `volume = 0`,
and 568 of the first 580 corrupt rows carried real volume.

## 2. Two corruption classes, and why the first fix was not enough

**Isolated spikes >10x** — 580 rows, 281 codes, 558 in Nov-Dec 2025.
`ASX:AMD` at $214.99 (NASDAQ AMD), `ASX:AXP` at $381.05 (NYSE American Express).

**Sub-threshold collisions** — 1,159 more rows, 177 codes, spread across
2023-2025. These hid under a 10x rule because the colliding security's price
happened to be within an order of magnitude:

| ASX code | ASX price | written | the other security |
|---|---|---|---|
| ALL | $57.55 | **$207.80** | NYSE Allstate |
| AMC | $12.42 | **$1.69** | AMC Entertainment |
| FPH | $32.90 | **$5.87** | NYSE Five Point Holdings |
| AGL | $9.31 | **$0.73** | — |

FPH was the one my own `_despike` could not catch and it drove the headline for
two runs: a 5.6x error, every Friday, at a third of the usual volume.

The discriminator that finds both classes without deleting real moves is not
magnitude but **isolation plus neighbour agreement**: a day that disagrees with
both neighbours by >2.5x *while the neighbours agree with each other within 25%*.
A genuine move does not revert to within 25% of where it started. Sub-10c names
are excluded, because there a 3x "move" is tick bounce and genuinely traded.

Both sets were exported before deletion; the exports are the undo.

## 3. The result

414 non-overlapping weeks, 2019-04-29 → 2026-08-28, 20bp round trip, vs XJT:

| | despiked locally | #582 fixed | **fixed + cleaned** |
|---|---|---|---|
| mean excess | +0.253%/wk | +0.248% | **+0.141%** |
| sd | 2.899% | 2.899% | **2.043%** |
| **t** | 1.78 | 1.74 | **1.40** |
| **top-3 share** | 0.57 | 0.58 | **0.37** |
| best week | +40.7% | +40.7% | **+8.8%** |
| excl top 3 | t = 1.10 | t = 1.06 | t = 0.93 |

**t = 1.40. No edge is demonstrated.**

But the shape finally changed. For seven versions the pattern was a respectable
mean sitting on three weeks; here the top three carry **37%** of the total and
removing them moves the mean from +0.141% to +0.090%. The best week is +8.8% —
a number a real portfolio can produce. Nothing in this run is an artifact I can
find.

That makes it the first ASX measurement that is *clean and negative* rather than
*dirty and flattering*. The earlier +0.25%/wk at t=1.78 was, in the end, mostly
Five Point Holdings.

## 4. The standing pattern, eighth instance

V283, V284, V285, V289, V291, V292, V293, V295: a stable measurement is necessary
and nowhere near sufficient. What is different is where the effort landed — this
version's work was almost entirely upstream data integrity, and it moved the
headline number DOWN by 44%. Every prior "improvement" that moved a number up
turned out to be a defect.

## 5. What would be next

The signal itself has never been the subject of a real test — eight versions have
been spent making the measurement trustworthy. That is now largely done:
point-in-time universe, real total-return benchmark, live liquidity screens,
binding concentration cap, disjoint periods, clean prices. A genuine attempt at
the signal (sector-neutrality needs #557; cross-sectional demeaning; a horizon
sweep) is the first thing this campaign could try that would not be measuring its
own plumbing.
