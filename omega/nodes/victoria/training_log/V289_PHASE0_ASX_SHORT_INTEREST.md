# V289 Phase 0 — short interest as an ASX signal: right sign, untrustworthy magnitude

**Date:** 2026-08-28
**Author:** claude
**Status:** PHASE 0 / FINDINGS — read-only, no strategy code, nothing pre-registered
**Parent:** [`V286_PHASE0_ASX.md`](V286_PHASE0_ASX.md) · [`V288_SHORTED_API_AUDIT.md`](V288_SHORTED_API_AUDIT.md)
**Standing baseline (Victoria):** crisis +$599 / trend +$2,997 / recent +$30 — untouched

---

## §1 — First, a correction to V288

V288 concluded the Shorted API held **~4 months** of history and therefore could not
address V286's survivorship question. **That was wrong.** The 90-date window is a
property of `GetAvailableDates`, not of the dataset. The MCP's `get_stock_history`
returns **16 years**: BHP runs 0.94% on 2010-06-14 → 1.25% on 2026-08-24, 846
observations.

The error was measuring one endpoint and generalising to the API. The MCP surface
(24 tools, `api.shorted.com.au/mcp`) was not audited because it was not reachable at
the time.

## §2 — Data

66 stocks with both short-interest history and prices, **195 months, 2010-06 → 2026-08**.

- **Universe sampled at RANDOM** from the frozen 740-name panel — deliberately not by
  short interest, which would select on the variable under test.
- Short series **lagged one month**. ASIC publishes T+4 and the MCP series is
  downsampled, so a one-month lag guarantees the signal was knowable before the return
  window opens.
- `get_stock_history` **downsamples** (BHP: 846 observations → 170 points), so this is a
  sampled series, adequate for multi-week horizons and not a daily record.

## §3 — Result: the sign is right and stable

Cross-sectional Spearman IC, short interest vs forward return:

| signal | H=1m | H=3m | H=6m | H=12m |
|---|---:|---:|---:|---:|
| short level | −0.0076 | −0.0216 | −0.0238 | **−0.0372** |
| Δshort (3m) | −0.0067 | −0.0192 | −0.0216 | −0.0163 |

**Negative at every horizon, strengthening with horizon** — heavily shorted ASX names
underperform. That is the well-documented short-interest anomaly, replicating here.

**Sign-stable across halves** on all four tested cells (level H=3/H=6, Δ H=3/H=6) — the
test that killed V285's inverted-signal hypothesis. At H=6 the level IC is −0.0246 in the
first half and −0.0230 in the second, which is about as stable as this campaign has seen.

For scale, Victoria's entire signal edge (`sma_crossover`) is IC ≈ +0.03–0.04. The
H=12 level IC is comparable.

## §4 — And the magnitude is not credible

A long-short quintile book (long least-shorted, short most-shorted):

| H | annualised | net of ~40bp/yr | hit rate |
|---:|---:|---:|---:|
| 3m | +33.7% | +32.1% | 61% |
| 6m | +29.5% | +28.7% | 60% |
| 12m | +25.0% | +24.6% | 62% |

**25–34% annualised is a red flag, not a result.** Four reasons it should not be believed:

1. **The t-statistics do not support it.** Raw t looks respectable at H=12 (−2.92), but
   the windows overlap: 182 monthly observations of a 12-month forward return are ~15
   independent draws. A crude overlap adjustment (t/√H) puts every horizon at **−0.7 to
   −0.9 — not significant**. The quintile spread is therefore being carried by a few
   periods, not a persistent effect.
2. **Survivorship, and this time it inflates the LONG leg.** The universe is sampled from
   *today's* panel, so names that delisted are absent. The long leg (least shorted) is
   pure survivors. Note this is the opposite direction to V286 §5, where the bias
   inflated a *reversion* finding — here it flatters the long side specifically.
3. **The short leg is the borrow-constrained leg, by construction.** "Most heavily
   shorted" is exactly the set that is expensive or impossible to borrow. A backtest that
   shorts it at zero borrow cost is pricing a trade that may not exist, and V286 §1
   already flagged retail ASX shorting as a structural problem.
4. **66 names, quintiles of ~13.** Thin cross-sections make quintile spreads noisy.

## §5 — What this is and is not

**It IS** the most promising signal this campaign has measured: correct sign, consistent
with a documented anomaly, sign-stable across halves, at a magnitude comparable to
Victoria's whole edge — and, unlike V286's reversion finding, it is not an artifact of
the bias direction.

**It is NOT** a validated strategy. The honest summary is *"the sign replicates; the size
does not survive scrutiny."* This session has three standing precedents for exactly that
gap: V283 measured a genuinely better volatility forecaster with no consumer; V284 built
the consumer and it lost money; V285's most exciting table evaporated under a train/test
split.

## §6 — What would make it real, in order

1. **Widen the universe and de-bias it.** 66 → the full 740-name panel, and
   delisted-inclusive if constituent history can be acquired. This is still V286 §5's
   blocking question, and it is now the blocking question for *this* finding too.
2. **Long-only variant.** If the edge survives without the short leg, the borrow problem
   disappears and the strategy becomes executable retail. This is the single highest-value
   follow-up: it tests whether §4's fatal objection actually binds.
3. **Non-overlapping evaluation.** Annual rebalance, or a proper Newey-West correction,
   so the t-statistic means something.
4. **Only then** a pre-registered mechanism with a distributional falsifier (V235).

Do **not** build a strategy from §4's headline number. The number that matters is §3's
IC, and its honest t-statistic is under 1.


---

## §7 — Follow-up (2026-08-31): the long-only test, and it fails

§6 item 2 named the long-only variant as the highest-value follow-up, because it tests
whether §4's borrow objection actually binds. Run:

### The borrow objection does NOT bind

Decomposing the long/short spread into its legs (excess over the equal-weight universe):

| H | Q1 − mkt (**long**) | mkt − Q5 (short) | total | long share |
|---:|---:|---:|---:|---:|
| 3m | +4.44% | +3.09% | +7.53% | **59%** |
| 6m | +8.28% | +5.51% | +13.79% | **60%** |
| 12m | +15.37% | +9.67% | +25.04% | **61%** |

**~60% of the spread is in the tradeable long leg.** So the strategy does not depend on
shorting hard-to-borrow names — objection §4.3 is answered, and answered favourably.

### But the return profile is not a process

Long-only excess is not significant after adjusting for overlapping windows (t_adj 1.25–1.37,
against a ~2 bar), and the **hit rate is a coin flip**: 52% / 49% / 51%. A large positive
mean with a 50% hit rate means outliers, and the decomposition confirms it:

| H | mean | **median** | winsorised 5% | skew | top-3 periods' share of total |
|---:|---:|---:|---:|---:|---:|
| 3m | +4.44% | **+0.30%** | +1.81% | 4.51 | **61%** |
| 6m | +8.28% | **−0.28%** | +3.91% | 3.36 | 36% |
| 12m | +15.37% | +1.46% | +14.92% | 2.26 | 20% |

At H=3, **three periods carry 61% of the entire return**. At H=6 the **median period
loses money** while the mean is +8.28%. That is a lottery with positive expectation, not
an edge you can run a book on — and with ~15 independent draws at H=12, the one horizon
that looks robust is also the one with the least evidence.

### Verdict

**The sign is real; the trade is not.** §3's IC finding stands — negative at every
horizon, sign-stable across halves, magnitude comparable to Victoria's entire edge. What
does not stand is any claim that this converts into returns: the long-only profile is
outlier-driven, the median is ~0, and the significance is under the bar at every horizon.

This is the fourth time in this campaign that a clean measurement has failed to become
PnL (V283 forecaster with no consumer, V284 consumer that lost money, V285 table that
died OOS, now this). The pattern is worth naming: **a stable IC is necessary and nowhere
near sufficient.**

### What would still change the answer

1. **The de-biased universe (§6 item 1) is now the binding constraint, not a caveat.**
   66 survivors cannot distinguish "outlier-driven" from "the outliers are exactly the
   delisted names I am missing." Filed upstream as
   [castlemilk/shorted.com.au#541](https://github.com/castlemilk/shorted.com.au/issues/541).
2. **Non-overlapping evaluation** — annual rebalance at H=12, so the ~15 independent
   draws are counted honestly rather than inflated to 182.
3. Do **not** pursue the L/S book. Its extra return over long-only comes from the leg
   that is hardest to borrow, for a spread whose significance is already under 1.
