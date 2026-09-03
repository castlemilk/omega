# V303 — Correction: 9.4% of held positions were being charged a 0% return

**Date:** 2026-09-03
**Status:** methodology defect found; V296–V302 headline REVISED DOWN
**Supersedes:** the "t=+4.24" figure reported in V302

## 1. The defect

The return loop summed over names that had a price at the exit date and left the
weights normalised to 1. A name with no exit price therefore contributed **0%
while still holding its weight** — a silent drag on every period.

That would be defensible if such names were delistings. They are not. Over 14,377
held name-periods at a weekly hold:

| | share |
|---|---|
| priced at exit | 90.33% |
| **hole in the series** (priced again later) | **9.41%** |
| genuinely delisted (never priced again) | 0.26% |

**97% of "missing" names are gaps, not delistings.** Charging a gap 0% asserts the
position was flat over a week when the truth is that we do not know what it did.

## 2. The fix

A gap is now **excluded and the book renormalised** over what is priced — the
honest reading of an unknown. A genuine delisting keeps its weight and its 0%,
because that position really did stop existing and must not be renormalised away.
The two are distinguished by whether the code is ever priced again after the exit
date, which needs no new data.

## 3. It cuts against the headline

| measure | as reported | corrected |
|---|---|---|
| **Q1 vs universe, FULL (n=590)** | **t=+4.14** | **t=+1.95** |
| Q1 vs universe, IS 2019-26 | t=+3.09 | **t=+1.09** |
| Q1 vs universe, OOS 2015-19 | t=+2.88 | t=+2.58 |
| **Q1−Q5 spread, FULL** | t=+3.31 | **t=+2.85** |

The Q1-vs-universe claim was substantially an artifact of the gap treatment: the
universe carries more gaps than Q1 does, so charging them 0% dragged the
comparator toward zero and inflated the excess.

**The Q1−Q5 spread survives** (t=+2.85), and that is the more robust statistic for
exactly the reason it survived every earlier correction: both legs are drawn from
the same universe and take the same treatment, so a bias in the mechanics largely
cancels. The out-of-sample number also barely moved (2.88 → 2.58), which is the
reassuring part — the replication was not an artifact.

## 4. Standing position, revised

- **Q1−Q5 spread: +0.298%/wk, t=+2.85 over 590 weekly periods**, replicated out of
  sample. This is the claim that has survived every correction and is the one to
  carry forward.
- **Q1 vs universe: t=+1.95.** Marginal. Not a claim to build on.
- V299/V301's capacity numbers were computed on the defective return and must be
  re-derived. The earlier capacity re-run in this session is void for the same reason.

## 5. The pattern, ninth instance

Nine versions, and the defect was again something that quietly evaluated to a
number instead of erroring — 9.41% of positions silently asserting "flat this
week". V293 named the rule and V302 added a companion; this adds a third:

**A missing input must be excluded, never defaulted.** Charging a gap 0% is a
default dressed as a measurement, and it survived four rounds of review because
0% looks conservative. It is not conservative — it is a fabricated observation,
and it happened to point the way the hypothesis wanted.
