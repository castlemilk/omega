# V297 — The Q1 effect is not a sector bet, but it may be a neglect premium

**Date:** 2026-09-03
**Status:** V296's finding survives its main challenge; a new confound identified
**Depends on:** V296 (IC t=−2.75, Q1 t=+3.16)

## 1. The test

V296 §7 named sector loading as the most likely alternative explanation:
least-shorted names cluster, so Q1 could be a sector bet wearing a signal's
clothes. Sector-neutral construction takes the least-shorted fifth **within each
industry** and weights industries as the eligible universe weights them, so
sector bets are removed by construction and only within-sector selection remains.

| | mean excess/wk | t |
|---|---|---|
| Q1 plain | +0.299% | +3.16 |
| **Q1 sector-neutral** | **+0.232%** | **+2.32** |

The effect loses about a fifth of its magnitude and stays significant. **Sector
loading explains part of it and cannot explain it away.** Roughly four-fifths is
within-sector selection.

## 2. Caveat that must travel with this

The labels are the CURRENT industry classification — #557 is open, so
point-in-time GICS does not exist. A company's industry today need not be its
industry in 2019. Mislabelling of that kind would generally BLUR a sector effect
rather than manufacture one, which is why the test is still worth running; but a
clean version needs #557 and this result should be re-run when it lands.

## 3. The new confound, which is more interesting than the old one

| industry | share of Q1 | share of universe | tilt |
|---|---|---|---|
| Materials | 25.8% | 21.4% | +4.4pp |
| **Not Applic** | **14.5%** | **2.9%** | **+11.6pp** |
| unlabelled | 5.2% | 1.2% | +4.1pp |
| Capital Goods | 6.6% | 4.4% | +2.1pp |
| Equity REITs | 4.8% | 8.8% | −4.0pp |

Names with **no usable industry classification are five times over-represented in
the least-shorted quintile** — together about 20% of Q1 against 4% of the
universe.

The mechanism is not mysterious and that is the problem: a company nobody
classifies is a company nobody covers, and a company nobody covers is a company
nobody shorts. So "least shorted" may be substantially a proxy for **neglect**,
and the measured edge may be a neglect or attention premium rather than
information in the short-interest series.

That the ADV screen (>= $500k/day) does not remove it makes it more interesting,
not less — these are liquid-enough names that are simply unwatched.

Note the sector-neutral test already partly controls for this: "Not Applic" is
treated as its own sector and held to its universe weight of 2.9%, which is part
of why the effect drops from t=3.16 to t=2.32. Surviving that is evidence the
edge is not ONLY neglect.

## 4. Where this leaves V296's claim

Standing: short interest carries information about ASX forward returns
(IC t=−2.75), concentrated almost entirely in the least-shorted quintile
(t=+3.16), which survives sector-neutralisation (t=+2.32) and is therefore not
simply a sector bet.

Unresolved: how much of that is short interest as a *signal* versus short
interest as a *marker for neglect*. These are different claims with different
half-lives — a neglect premium is a risk premium and should persist; an
information effect should decay as it is arbitraged.

## 5. Next

- Re-run §1 when #557 lands, with point-in-time labels.
- Separate the two hypotheses directly: regress forward return on short interest
  while controlling for analyst-coverage proxies (market cap, ADV, index
  membership via XKO/XJO constituency). If short interest survives those, it is a
  signal; if it does not, the campaign has found a neglect premium — still real,
  but a different product with different capacity.
