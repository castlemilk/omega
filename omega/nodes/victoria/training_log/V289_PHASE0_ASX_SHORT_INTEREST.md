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
