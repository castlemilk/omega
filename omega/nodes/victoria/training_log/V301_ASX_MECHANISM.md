# V301 — Correction: the neglect mechanism DOES replicate, and it is the thinnest tercile alone

**Date:** 2026-09-03
**Status:** corrects V300 §4; V298's mechanism confirmed and sharpened
**Depends on:** V296–V300

## 1. The correction

V300 §4 reported that V298's mechanism failed out of sample (t=+0.59) and called
it "provisional". That conclusion came from a mis-specified test and is withdrawn.

Two faults in it:

1. It grouped the **thin two terciles together** (`ADV <= $12M`). The middle
   tercile is approximately zero, so combining it with the thinnest dilutes the
   estimate. That alone explains +0.59 against the correct +1.64.
2. The double-sort it was compared against measured Q1 excess **against XJT**,
   which does not exist before 2019-04-29, so the pre-2019 window silently
   produced no rows at all. A spread is benchmark-relative and needs no index;
   using one threw the sample away.

Re-run benchmark-free, Q1−Q5 spread within each ADV tercile:

| tercile | median ADV | OOS 2015-10→2019-04 | IS 2019-04→2026-09 | FULL |
|---|---|---|---|---|
| **thinnest** | $1.19M | **+0.401% (t=+1.64)** | **+0.519% (t=+3.26)** | **+0.483% (t=+3.63)** |
| middle | $5.71M | −0.051% (t=−0.22) | +0.182% (t=+0.95) | +0.111% (t=+0.74) |
| thickest | $28.91M | −0.105% (t=−0.77) | −0.073% (t=−0.52) | −0.083% (t=−0.78) |

The sign and the ordering replicate exactly across both periods. OOS t=+1.64 is
weak on n=150, but it is the same effect, in the same place, in a period the work
was never fitted to. Full sample **t = +3.63**.

## 2. What actually changed in the claim

V298 said the edge lives in the "thin two terciles". It does not — it lives in the
**thinnest tercile alone**, around $1M/day ADV. The middle tercile ($5.7M) is
indistinguishable from zero in both halves.

That is a sharper and more uncomfortable finding: the tradeable universe is
narrower than V298 implied, and V299's capacity model was run over `ADV <= $12M`,
which includes a middle tercile that contributes nothing while consuming capacity.
The $20–50M quarterly figure is therefore optimistic and must be re-derived over
the thinnest tercile only.

## 3. Standing position after V296-V301

- **Least-shorted ASX names outperform.** t=+3.87 over 590 weekly periods, replicated
  out of sample, with a survivorship bias running against the finding. Solid.
- **The effect is concentrated in the least-liquid third**, ~$1M/day ADV, and is
  zero or negative among heavily traded names. Replicated in both halves.
  Consistent with a neglect or attention premium rather than information in short
  interest.
- **Capacity is the open question**, and it is worse than V299 estimated because
  the eligible universe is one tercile, not two.

## 4. A methodological note worth keeping

Both faults in V300 §4 had the same shape: a **benchmark was used where none was
needed**, and a **bucket was widened past where the effect lives**. Each silently
weakened a real result rather than fabricating a false one — which is the failure
mode that survives review, because a weakened result looks like honest caution.
The campaign's rule about reporting sensitivity has a companion: when a test
returns weaker than a prior one, check the test before believing the weakening.
