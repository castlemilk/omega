# V291 — The ASX short-interest finding flips sign under a methodology fix

**Date:** 2026-08-31
**Author:** claude
**Status:** FINDING — no strategy claim. The claim is that there is no claim.
**Supersedes the headline of:** [`V289_PHASE0_ASX_SHORT_INTEREST.md`](V289_PHASE0_ASX_SHORT_INTEREST.md) §3

---

## §1 — What happened

Upstream landed the fixes that made an honest study possible (#537 date discovery, #549
prices, #550 `availableFrom`, #552 share counts). Re-running V289's study on the
corrected footing **reverses its central result**.

| | V289 | V291 |
|---|---:|---:|
| universe | 66, sampled from **today's** panel | 41, sampled from the **2016** point-in-time universe |
| prices | yfinance, joined by ticker | `StockService/GetStockPrices` (same codes) |
| timing | **guessed** 7-day lag | **real** `availableFrom` (T+4, verified: median 6d) |
| span | 2010–2026 | 2016–2026 |
| **IC @ H=6** | **−0.0238** (t_adj −0.71) | **+0.0777** (t_adj **+2.01**) |
| **IC @ H=12** | −0.0372 | **+0.1084** (t_adj +2.44) |

V289 said heavily shorted names **underperform** — the documented anomaly, sign-stable
across halves. V291 says they **outperform**, with t-statistics that now clear the bar
V289's failed.

## §2 — The right conclusion is not "the new number"

**Five things changed at once.** Universe construction, price source, timing convention,
sample period and sample size all moved together, so nothing attributes the flip to a
cause. The tempting read — *"the corrected study is the true one"* — does not follow, and
taking it would repeat the exact error V285 §3 caught: an encouraging table that inverted
under a methodology change is evidence of **fragility**, not of a newly-discovered truth.

The defensible conclusion is narrower and more useful:

> **A result that reverses sign when the methodology is corrected was never a result.**
> Neither −0.0238 nor +0.0777 should be trusted. n=41 with overlapping monthly windows
> over one decade cannot separate a real effect from a sampling artifact.

The supporting evidence is in the same table: the long-only excess is now **negative at
every horizon** (−2.43% at H=6, −5.64% at H=12) with hit rates of 34–41%, and the
top-3-share diagnostics come back as 127%, −66% and −30% — values that are only possible
when the total is near zero. Those are noise readings, and they sit beside the
"significant" ICs in the same run.

## §3 — What the survivorship measurement did establish

Two things worth keeping, both firmer than the signal itself.

**1. The hole is 53%, and it is now measured rather than feared.** Sampling 90 names from
the 2016 universe: 88 have short history, **42 have prices, 46 return 404**. So a
return study on the current API covers **47%** of the universe as it stood in 2016.

**2. The hole is NOT concentrated in the shorted names.** Comparing the two groups:

| | mean 2016 short% | median | mean peak |
|---|---:|---:|---:|
| survivors (n=42) | 2.140 | 0.952 | 7.567 |
| vanished (n=46) | 2.200 | 1.132 | 6.598 |

Mann-Whitney p = **0.55** (2016 level) and **0.90** (peak). No difference. So the missing
names are not disproportionately the heavily-shorted ones, and the survivorship bias in a
return study is therefore **less directional than V289 §4.2 assumed**.

That cuts both ways, and the second way matters: if short sellers were identifying doomed
companies, the delisted group should have carried higher short interest. It did not.
Note also that "vanished" mixes **failures and takeovers** — and takeovers usually resolve
at a premium — so the sign of the residual bias is genuinely ambiguous rather than
conveniently benign.

## §4 — What would settle it

1. **Delisted pricing.** 53% of the universe is unpriceable; no amount of care on the
   remaining 47% fixes that. Raised upstream on #549.
2. **A wider cross-section.** 41 names is too thin for quintiles. The API supports ~740
   current and 2,080 historical codes — the constraint is request budget, not data.
3. **Non-overlapping evaluation.** 116 monthly observations of a 12-month forward return
   are ~10 independent draws, whatever the t-statistic says.

## §5 — The lesson, which is the durable output

This is the fifth time in this campaign that a clean measurement failed to survive
contact with a better method (V283, V284, V285, V289, now V291). The pattern is now
specific enough to state as a rule:

> **Where a result is sensitive to methodology, report the sensitivity, not the result.**

V289 published an IC with a sign and a stability claim. The honest artifact would have
been the IC *and* the note that it rested on a guessed lag, a survivor-only universe and
a bolted-on price source — any of which could move it. It took landing four upstream
fixes to discover that all three mattered.
