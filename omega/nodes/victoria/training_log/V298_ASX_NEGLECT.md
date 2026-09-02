# V298 — It is a neglect premium, not a short-interest signal

**Date:** 2026-09-03
**Status:** hypothesis resolved; V296's framing was wrong
**Depends on:** V296 (IC t=−2.75, Q1 t=+3.16), V297 (survives sector-neutralisation, t=+2.32)

## 1. The discriminating test

V297 raised it: names with no industry classification are five times
over-represented in Q1, and a company nobody classifies is a company nobody
covers or shorts. So "least shorted" may be a proxy for **neglect** rather than a
carrier of information.

The two hypotheses make opposite predictions about where the effect lives:

- **Information** — short interest tells you something, so Q1 works in EVERY
  liquidity bucket. Heavily-traded names are where short sellers are most
  informed, so if anything it should be strongest there.
- **Neglect** — short interest marks how unwatched a name is, so the effect lives
  only where attention is scarce and vanishes among well-covered names.

Double sort, ADV tercile × short-interest quintile, hold 5d. ADV is genuinely
point-in-time (trailing 20 sessions, prior data only), unlike V297's
current-industry labels.

| ADV tercile | median ADV | Q1 excess/wk | t | Q1−Q5 | t |
|---|---|---|---|---|---|
| thinnest | $1.19M | **+0.373%** | **+2.92** | +0.477% | **+3.03** |
| middle | $5.70M | +0.284% | +2.22 | +0.276% | +1.52 |
| **thickest** | **$30.06M** | **−0.002%** | **−0.03** | −0.042% | −0.31 |

**Monotonically decreasing in liquidity and exactly zero in the most-traded
third.** That is the neglect prediction, cleanly, with no room for the
information one.

## 2. What this means for V296

V296's measurements stand — IC t=−2.75 is real, Q1 t=+3.16 is real, and V297's
sector-neutral t=+2.32 is real. The *interpretation* was wrong. This is not
"short interest predicts returns on the ASX". It is "unwatched ASX names earn a
premium, and low short interest is one of the better available markers for being
unwatched".

The distinction is not academic:

- An information effect should **decay** as it is arbitraged. A neglect premium is
  a risk/attention premium and should **persist** — that is the good news.
- But capacity is bounded by the thin end. The edge lives in $1–6M/day names, and
  the ADV screen at $500k/day was letting the strategy hold all three terciles,
  a third of the book in names where the effect is exactly zero.
- Any attempt to scale into liquid names removes the edge by construction. That is
  a hard ceiling, not a tuning problem.

## 3. Why the portfolio underperformed the quintile, finally explained

V296 attributed the gap (Q1 t=3.16 vs portfolio t=1.55) to concentration,
delisting drag and costs. A fourth cause was invisible then and dominates: **a
third of every book was drawn from the thickest tercile, where the expected excess
is zero.** The strategy was diluting a real edge with names that cannot express it.

## 4. The honest position

The campaign has found something real and correctly characterised it. It is
smaller and more capacity-constrained than V296 implied, and it is not the thing
the ASX project was built to find. Whether it is worth trading is now a capacity
question rather than a statistical one — which is a better problem than any this
campaign has had.

## 5. Next

- Rebuild the book from the thin two terciles only and re-measure net of costs.
  Expected to raise t and lower capacity; both numbers are needed before this can
  be called a strategy.
- Costs must be re-estimated for thin names. The 20bp round trip was calibrated
  for liquid ASX stock; at $1M/day ADV, market impact is the dominant cost and
  20bp is optimistic. This is now the binding uncertainty.
- #557 would let V297's sector control be run point-in-time, but it is no longer
  the critical path — V298 answered the question #557 was wanted for.
