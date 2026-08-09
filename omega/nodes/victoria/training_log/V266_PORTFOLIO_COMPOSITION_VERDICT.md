# V266 — Portfolio composition verdict: spot Victoria × funding-carry V255.C

**Date:** 2026-08-09
**Scope:** offline ledger analysis only. No strategy code, no flag, no grid, no
backtest, no live-broker. Daemon PID 10329 untouched.
**Pre-registration:** [`V266.md`](V266.md) (gates locked in the brief before any
analysis ran)
**Artifact:** `data/v266_portfolio.json` ·
**Script:** [`scripts/v266_portfolio_composition.py`](../../../../scripts/v266_portfolio_composition.py)
**Determinism:** re-run byte-identical (bootstrap pinned, seed 42). ✅

---

## VERDICT: **CAVEATED — 1 of 3 gates PASS.**

| Gate | Statistic | Bar | Result | CI95 (10k bootstrap) | |
|---|---|---:|---:|---|:--:|
| **G1** | Pearson ρ(daily net PnL) | < 0.50 | **−0.0151** | [−0.0472, +0.0019] | **PASS** |
| **G2** | Sharpe(50/50) vs 1.05× best single | > 2.3141 | **1.2577** | [0.6227, 1.8691] | **FAIL** |
| **G3** | max DD(combined) vs 0.9× min single | < $88.73 | **$4,203.25** | — | **FAIL** |

**The one-line finding: the diversification premise is confirmed decisively, and it
does not convert into a composition benefit.** The two lanes are genuinely
orthogonal — H1 is not merely accepted, it is accepted at ρ ≈ 0 with a CI that
excludes anything material. But orthogonality is *necessary, not sufficient*.
Combining a Sharpe-2.20 lane with an orthogonal Sharpe-0.72 lane at any material
weight **dilutes** the good lane. G2 and G3 do not fail because the lanes
interfere; they fail because **the lanes are of very unequal quality**, and
diversification cannot manufacture quality it isn't given.

**This is NOT the STOP outcome.** The alpha search has *not* been double-counting.
The two-lane story survives — it is the *equal-weight combination* story that dies.

---

## 1. Phase 1 — common daily series

Victoria's per-window ledgers carry a **wall-clock** `timestamp` (the run date,
2026-07-10), not a simulated bar date. Exit dates were reconstructed from the replay
geometry instead: `providers/replay.py` starts its cursor at `window` (=28), so the
decision/exit bar for cycle *c* is series index **26 + c**, and the date is
`window_start + (26 + c)` days.

Only the **26 independent primary** walk-forward windows are used. The 6
`_recent_supplements` overlap their primary neighbours by 45d and would double-count
calendar days (V249 independent-N rule).

| | Victoria (spot) | Funding-carry V255.C |
|---|---:|---:|
| Common date range | 2020-02-07 → 2026-05-14 | ← same |
| Observed days | 1,590 | 1,590 |
| Days with a trade | 215 | 326 |
| Trades in common range | 285 | 853 (of 1,225 total) |
| Total net PnL in range | **+$36,630.63** | **+$29,481.63** |
| Mean daily net PnL | +$23.04 | +$18.54 |
| **σ daily net PnL** | **$613.26** | **$160.73** |
| Worst single day | −$1,867.46 | **−$68.28** |
| Best single day | +$17,756.72 | +$3,441.34 |

**1,375 of 1,590 days are joint zeros** (neither lane traded). This is handled
explicitly in §3.

### 1.1 Reconciliation against the published V240 confirm table

| Regime | V266 window mean (n) | Published V240 `universe_selective` | |
|---|---:|---|:--:|
| crisis | **+$598.53** (n=12) | +$598.53 (n=12) | exact ✅ |
| trend | **+$2,996.92** (n=10) | +$2,996.92 (n=10) | exact ✅ |
| recent | **−$921.23** (n=4) | +$29.64 (n=10 nominal) | see note |

`recent` differs **only** because V266 uses the 4 *independent* primary recent
windows; the published +$29.64 is over 10 *nominal* windows including the 6
overlapping supplements. Individual window sums tie out exactly
(e.g. `snap_wf_20201226` = $17,366.58, `snap_wf_20200101` = −$2,709.05).

**Disclosure — edge trimming.** The common range is bounded by the funding ledger
(first exit 2020-02-07, last 2026-05-14). This trims Victoria's leading days
(`snap_wf_20200101` is live from 2020-01-28) and trailing days (`snap_wf_20260228`
runs to 2026-05-27). Net effect: **−$3,163.95 of Victoria PnL is excluded**, and
because that trimmed slice is a net loss, **Victoria looks $3.2k better inside the
overlap than its own published baseline**. All G1–G3 numbers below are computed on
the overlap. This flatters Victoria and therefore *cannot* explain the G2/G3
failures — it works against them.

---

## 2. Phase 2 — G1 correlation (**PASS**, and it is the headline)

| Statistic | Value | CI95 (10k bootstrap) |
|---|---:|---|
| **Pearson ρ** | **−0.0151** | [−0.0472, +0.0019] |
| **Spearman ρ** | **−0.0410** | [−0.0936, +0.0124] |

Bar is ρ < 0.50. The point estimate is **33 standard-error-widths below the bar** and
the entire CI sits at or below zero. There is no plausible reading of this data in
which the lanes share material daily exposure.

### 2.1 Robustness — three ways the result could have been an artifact

**(a) Joint-zero attenuation.** 1,375 of 1,590 days are joint zeros, which drags ρ
toward 0 mechanically. Restricting to the 53 days where **both** lanes traded:
ρ = **−0.172**, CI95 [−0.381, +0.053]. Still ≤ 0. The conclusion survives — if
anything the lanes are mildly *anti*-correlated when both are active.

**(b) Horizon aggregation.** At the 90-day window level ρ = **+0.712** — which
would be a serious caveat if it were stable. It is not:

- Dropping the single largest window (`snap_wf_20201226`, Victoria +$17,367 — the
  Dec-2020/Q1-2021 bull run) collapses it to **+0.221**.
- Rank-based Spearman is only **+0.257**, CI95 **[−0.183, +0.651]** — spans zero.

The apparent quarterly co-movement is **one window**, not a common component. At
n=26 it is unadjudicable and it does not survive its own influence check.

**(c) Regime conditioning.** Diversification that evaporates in crisis is not
diversification. It does not evaporate:

| Regime | days | ρ | Sharpe Victoria | Sharpe funding | PnL Victoria | PnL funding |
|---|---:|---:|---:|---:|---:|---:|
| crisis | 746 | **+0.006** | 0.615 | 2.107 | +$9,743 | +$11,931 |
| trend | 613 | **−0.025** | 1.081 | 2.528 | +$29,969 | +$16,301 |
| recent | 231 | **−0.057** | −0.941 | 2.058 | −$3,082 | +$1,250 |

ρ ≈ 0 in **every** regime, including crisis. And note the *recent* row: Victoria is
negative (Sharpe −0.94) exactly where funding-carry keeps earning (Sharpe +2.06).
That is the single most useful line in this document — see §5.

---

## 3. Phase 3 — G2 Sharpe composition (**FAIL**)

Annualised ×√365 (crypto trades every calendar day).

| Portfolio | Weights (vic, fund) | Sharpe | CI95 |
|---|---|---:|---|
| Victoria alone | (1, 0) | **0.7177** | — |
| Funding-carry alone | (0, 1) | **2.2039** | — |
| **Bar (1.05 × best single)** | | **2.3141** | |
| **50/50 equal-dollar (pre-registered G2 leg)** | (0.500, 0.500) | **1.2577** | [0.6227, 1.8691] |
| Risk parity (∝ 1/σ) | (0.208, 0.792) | 2.0817 | — |
| Mean-variance tangency | (0.082, 0.918) | 2.3284 | — |

**Why 50/50 fails so badly.** Sharpe is scale-free per lane, but *equal dollar
weight is not equal risk weight*. Victoria's daily σ is $613.26 vs funding's
$160.73 — a 3.8× ratio — so a 50/50 dollar split puts **79% of portfolio variance
into the Sharpe-0.72 lane**. The result (1.258) is close to the variance-weighted
blend of the two Sharpes, exactly as orthogonality predicts. This is dilution, not
interference.

**Risk parity doesn't rescue it either** (2.082 < 2.204). Equalising *risk* still
allocates 21% of it to the weaker lane, and with ρ ≈ 0 there is no covariance term
to pay for that.

**The tangency portfolio is the only mix that clears 1.05×**, at
**2.3284 = 1.0565× best single**, CI95 **[1.0006, 1.1787]** (weights refit inside
each bootstrap resample). Read this honestly:

- The CI's lower bound is **1.0006** — it excludes 1.0 by 0.06%. That is a
  hairline, not a result.
- The point estimate is a **+5.7% Sharpe uplift**, and it is still in-sample on the
  full period.
- It requires an **8.2% / 91.8%** split. The "optimal combination" of these two
  lanes is, in substance, **"hold funding-carry, and hold a small Victoria
  satellite."**

**G2 is pre-registered on the 50/50 leg and is scored FAIL. The tangency number is
reported as a Phase-3 deliverable, not as a re-score.**

---

## 4. Phase 4 — G3 tail protection (**FAIL**)

Max peak-to-trough decline of the cumulative net-PnL curve.

| Portfolio | Max drawdown |
|---|---:|
| Victoria alone | $11,172.91 |
| **Funding-carry alone** | **$98.59** |
| **Bar (0.9 × min single)** | **$88.73** |
| 50/50 equal-dollar | **$4,203.25** |
| Risk parity | $1,448.14 |

**Funding-carry's $98.59 drawdown is real, not a bug.** It was verified directly:
worst single day −$68.28, 154 losing days out of 1,590, cumulative equity never
falls below $465 after inception, and 90.3% of daily steps are non-decreasing. This
is the expected shape of a **basis-hedged** carry book — `spot_price_pnl` and
`perp_price_pnl` cancel almost exactly, leaving funding accrual minus a fixed
$4 fee, so the downside is structurally bounded.

**σ-normalised diagnostic** (each lane rescaled to unit daily σ before combining,
to remove the notional mismatch):

| | drawdown (σ-units) |
|---|---:|
| Victoria | 18.22 |
| Funding-carry | 0.61 |
| 50/50 combined | 5.69 |
| **combined ÷ min single** | **9.27×** |

G3 fails under **both** the raw-dollar and the scale-neutral reading, so the
failure is not an artifact of the notional mismatch.

**The honest interpretation:** there is no tail protection available here, because
**funding-carry is already the tail-protected lane**. Its drawdown is 113× smaller
than Victoria's in dollars and 30× smaller in σ-units. Any non-trivial Victoria
weight can only inject drawdown. H3 was, in hindsight, structurally unwinnable
against this pair — a gate asking a smooth hedged-carry curve to be made smoother
by adding a directional spot book.

---

## 5. Diagnosis — what this actually means

**H1 confirmed, decisively. The lanes are not the same trade.** ρ = −0.015 pooled,
≈0 in every regime, ≤0 on joint-active days, and the one contrary signal
(window-level +0.71) is a single-window artifact that dies under its own influence
check. **The campaign has not been double-counting exposure.** The V254 premise —
that funding-carry manufactures genuinely *independent* N rather than re-slicing
Victoria's — is now measured rather than assumed. That premise was load-bearing for
the entire post-V249 phase and it holds.

**H2 and H3 refuted, for one reason: the lanes are wildly unequal.** Sharpe 2.20 vs
0.72; drawdown $99 vs $11,173. Diversification improves risk-adjusted return only
when the added stream's Sharpe is competitive relative to the correlation you avoid.
At ρ ≈ 0 the tangency weight collapses to roughly the Sharpe ratio scaled by inverse
σ — which is why the optimiser lands at 8% Victoria and the uplift is a rounding
error (+5.7%, CI lower bound 1.0006).

**The composition heuristic that IS real** (the one thing to carry forward):

> Funding-carry is the portfolio. Victoria is a satellite, correctly sized at
> **≲10% of risk**, and its value is **not** Sharpe — it is the +$30k of trend-regime
> PnL that funding-carry alone does not capture (trend: Victoria +$29,969 vs funding
> +$16,301).

Equal-weight and risk-parity are both **wrong** for this pair, and by a wide margin
(1.26 and 2.08 vs 2.20 for funding alone). If any allocation is ever run, it must be
Sharpe/σ-aware, never naive.

**The uncomfortable finding nobody asked for.** The regime table shows Victoria at
Sharpe **−0.94** in `recent` while funding-carry earns **+2.06** there. The recent
regime is precisely the one the campaign has been calendar-blocked on since V249 —
V241→V248's eight refutations, the live-paper soak, the whole N≥20 resume gate.
**Funding-carry is already profitable in the regime Victoria cannot solve**, and it
is profitable there with a bounded drawdown. On this evidence the recent-N wall is
much less binding on the *portfolio* than on *Victoria specifically*.

### 5.1 Caveats that constrain how far this can be pushed

1. **Capacity, not Sharpe, is funding-carry's binding constraint.** V255.C runs
   $2,000 notional per trade and the V255.C verdict was a **median +$1.95/trade**.
   A Sharpe of 2.20 on a hedged carry book with per-trade PnL in the single dollars
   is exactly what theory predicts and says nothing about deployable capital. The
   Sharpe comparison in §3 is mathematically valid but compares two lanes with very
   different scaling behaviour. **Do not read "Sharpe 2.2 lane" as "put the book
   there."**
2. **Funding-carry remains KEEP-FLAG-GATED** (V255.C/V255.D). V266 does not change
   its status and is not evidence for flipping it on.
3. **Victoria's overlap numbers are $3.2k flattered** by edge trimming (§1.1). This
   works against G2/G3, so it strengthens rather than weakens the failures.
4. **Drawdown curves span walk-forward gaps.** Victoria's equity is stitched across
   26 windows each carrying a 28-bar warmup gap; the drawdown is therefore a
   *stitched* quantity, not a continuously-tradeable one. Funding-carry's is
   continuous. The comparison favours Victoria (gaps hide intra-gap losses), and it
   still loses by 113×.
5. **n=26 windows / 1,590 days.** The daily-ρ result is well-powered; the
   window-level and tangency-uplift results are not, and are labelled as such.

---

## 6. Outcome and what is (and is not) queued

**Verdict: CAVEATED (1/3).**

**V266-2 is NOT queued.** ADOPT required 3/3, and the honest reading of the 1/3 is
that there is no equal-weight portfolio to build. A sizing/allocation
pre-registration would be pre-registering the *tangency* result — whose entire
uplift is +5.7% with a CI lower bound of 1.0006, in-sample, at an 8/92 split. That
is variance mining, and it is exactly the R1 noise-floor death pattern the
V241–V258 retrospective catalogued.

**What V266 changes:**

- The **independence premise behind the two-lane story is now measured**, not
  assumed. ρ ≈ 0 in every regime. That is the campaign-level deliverable.
- **Naive combination is closed.** Equal-weight and risk-parity are refuted for this
  pair with numbers, not intuition. Nobody needs to re-ask this.
- The composition heuristic — **funding-carry primary, Victoria ≲10% satellite for
  trend-regime capture** — is recorded for whenever an allocation question becomes
  live.

**What V266 does NOT change:** the standing baseline, any flag (all V241–V265 stay
OFF), funding-carry's KEEP-FLAG-GATED status, or the V253 live-paper soak and its
N≥20 recent resume gate.

**The honest next question this raises** (not queued, not pre-registered): the
recent-regime split in §5 suggests the campaign's binding constraint may have been
mis-scoped — it is a *Victoria* constraint, not a *portfolio* constraint. Whether
funding-carry's recent-regime performance can be widened to more independent windows
is a data question (basis coverage, name count), not a mechanism question, and it
would need its own Phase-0 audit.

---

## 7. Reproduce

```bash
OMEGA_AUDIT_OUTPUT_DIR=/Volumes/gamma-systems-2/omega-victoria-data \
  python3 scripts/v266_portfolio_composition.py --out data/v266_portfolio.json
```

Inputs (read-only, both archived):
- `$AUDIT/v240wf_snap_wf_*_universe_selective_*_determinism/*_r1_trades.csv` (26 primary cells)
- `$AUDIT/v255_D_ext/frozen/v255c_trades.csv` (1,225 trades, 13 names)
- `data/walk_forward_manifest.json` (window dates, regimes, supplement list)

Re-running produces a byte-identical `v266_portfolio.json`.
