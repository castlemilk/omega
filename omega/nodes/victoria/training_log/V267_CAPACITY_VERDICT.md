# V267 — Funding-carry capacity study: VERDICT = **CAVEATED (2/3)**

**Date:** 2026-08-09 · **Pre-registration:** [`V267.md`](V267.md) (committed
`cd2c2b3`, before any analysis ran) · **Scorer:**
[`scripts/v267_capacity.py`](../../../../scripts/v267_capacity.py) ·
**Artifact:** `data/v267_capacity.json` · **Seed:** 42 ·
**Determinism:** byte-identical re-run **PASS**

---

## 0. Headline

**Capacity is not the binding constraint at the scale that matters.** The V255.C
funding-carry book can be scaled **≈316× per-trade notional** — median **$1.03M per
trade, ~$154M peak concurrent gross book** — before the median trade reaches 1% of
its symbol's daily volume, and the measured edge absorbs **11.8 bps** of extra
per-leg round-trip slippage before Sharpe falls to 1.0. The edge is **concentrated
in the most liquid tercile** (16.35 bps vs 1.05 bps in the least liquid), which is
the *opposite* of a liquidity premium and the best possible news for scaling.

The one gate that fails does so on a single leg — the `recent`-regime Sharpe inside
the top-liquidity tercile — and that leg is **R2 (below-resolution)**, not negative:
Sharpe 0.762, CI95 **[−0.601, +1.193]**, spanning both zero and the 1.0 bar on
n=62 trades.

| Gate | Statistic | Bar | Result | CI95 | Outcome |
|---|---|---|---:|---|---|
| **G0** | ADV join coverage | ≥ 80% | **100.0%** (1225/1225) | — | **PASS** |
| **G0** | OI join coverage | ≥ 60% | **54.9%** (672/1225) | — | **FAIL → OI leg R4-unscored** |
| **G1** | median participation at k=100 | ≤ 1.00% ADV | **0.3166%** | — | **PASS** |
| **G2** | slippage to Sharpe 1.0 | ≥ 5.0 bps | **11.83 bps** | — | **PASS** |
| **G3** | high-tercile median edge vs pooled | ≥ 50% | **248.2%** (16.35 vs 6.59 bps) | [10.60, 21.93] bps | pass |
| **G3** | high-tercile CI excludes 0 | true | **true** | [10.60, 21.93] | pass |
| **G3** | high-tercile `recent` Sharpe | > 1.0 | **0.762** | **[−0.601, +1.193]** | **FAIL (R2)** |
| | | | | | **G3 = FAIL** |

**Verdict: CAVEATED (2/3).** Computed mechanically from the gate booleans by the
scorer; no bar was moved after seeing a result.

---

## 1. Scope exclusion, declared before the run (R4)

The brief's suggested scaffold — *fit an impact model from V255.C fills, report
Sharpe(2k/20k/200k/2M)* — **is not answerable from data on disk**, and V267.md §2
said so before anything ran:

| Required input | On disk? |
|---|---|
| Orderbook depth / L2 snapshots | **NO** — `frozen_series/` holds klines, `fundingRate`, `metrics` (OI + ratios), mark/index klines. No depth, ever. |
| Own fills with observed slippage | **NO** — the ledger has no fill column; the scorer charges a flat 5 bps/side maker fee |
| Fills above $10k notional | **NO** — `notional_distribution.max = 10000.0`, 244 trades already at the cap |

**Zero variation in executed size ⇒ no impact coefficient is estimable.** A
Sharpe(2M) number would have required importing a square-root-law coefficient from
the literature and reporting its output as a measurement. **R4, not attempted.**

What replaced it is strictly measured: a **capacity envelope** against real daily
volume and real open interest, and a **breakeven slippage budget** derived from the
ledger alone — no impact model in either.

## 2. G1 — capacity envelope (**PASS**)

Real Binance quote volume (1h klines summed per UTC date, 2020-01 → 2026-06, **100%
join**) and real 5-minute `sum_open_interest_value`.

| k | median notional/trade | median % of ADV | p75 | p95 | median % of OI¹ |
|---:|---:|---:|---:|---:|---:|
| 1 | $3,267 | 0.0032% | 0.0089% | 0.042% | 0.0030% |
| 10 | $32,667 | 0.0317% | 0.0890% | 0.421% | 0.0303% |
| **100** | **$326,667** | **0.3166%** | 0.8903% | 4.206% | 0.3031% |
| 1000 | $3,266,670 | 3.1656% | 8.9032% | 42.06% | 3.0313% |

¹ OI column is **R4-unscored diagnostic** (54.9% coverage, below the 60% G0 bar) —
see §5.

- **Max scale under the 1%-of-ADV threshold: k = 315.9×.**
- **Peak concurrent gross book** (7-day holds overlap, both legs counted): **$486,483
  at k=1 → ~$154M at k=316.** The per-trade figure alone understates the book by
  ~150×; this is the number that matters for an allocation decision.
- On the OI-covered subset the binding scale would be k ≈ 165× (~$80M book) — still
  two orders of magnitude above today.

The p95 column is the honest caveat: the *tail* trade hits 4.2% of ADV already at
k=100. Scaling is not uniform across names and days; a live book would need
per-symbol participation caps, not a flat multiplier.

## 3. G2 — slippage budget (**PASS**)

Per-trade edge = 6.587 bps of notional (CI95 [4.44, 9.07]). Extra slippage `s` is
charged on 2 legs × entry+exit (4×). Daily book PnL over **every calendar day the
book is live** (2,296 days, zero-filled).

| extra slippage (bps/leg) | 0 | 1 | 2 | 3 | 5 | 10 | 20 |
|---|---:|---:|---:|---:|---:|---:|---:|
| annualised Sharpe | **2.207** | 2.129 | 2.046 | 1.960 | 1.775 | 1.231 | −0.231 |

- **Slippage to Sharpe 1.0: 11.83 bps** (bar 5.0) → **PASS**.
- **Slippage to pooled median net = 0: 1.65 bps.**

Those two numbers disagree on purpose and the disagreement is the finding: **the
median trade is thin (dies at 1.65 bps) while the book is carried by the right tail
of the distribution** (mean $36.17 vs median $1.95). The book, not the typical trade,
is what survives execution cost. Any live sizing must be aware it is harvesting a
skewed distribution — a per-trade "is this one worth it" filter calibrated on the
median would destroy the strategy.

**Baseline reconciliation:** the corrected day grid reproduces V266's funding-lane
Sharpe **2.207 ≈ 2.20** exactly. (An exit-days-only grid gives 4.94 over 481 days —
that variant is retained in the artifact as
`sharpe_exit_days_only_diagnostic` and is *not* used for any gate; see §6.)

## 4. G3 — liquidity-conditioned edge (**FAIL**, on one R2 leg)

Trades tercile-split by entry-date ADV. Pooled median edge = 6.587 bps.

| ADV tercile | n | median ADV | median edge | CI95 | Sharpe |
|---|---:|---:|---:|---|---:|
| **high** | 409 | $781M | **16.35 bps** | [10.60, 21.93] | 1.73 |
| mid | 408 | $131M | 6.53 bps | [4.03, 10.48] | 2.18 |
| low | 408 | $26.7M | **1.05 bps** | [−0.12, 2.72] | 1.76 |

**The edge is 15.6× larger in the most liquid tercile than the least, and the least
liquid tercile's CI includes zero.** The capacity fear — that this is an illiquidity
premium that evaporates the moment you need size — is **refuted**. Whatever
funding-carry is harvesting, it lives in BTC/ETH-scale volume, exactly where capacity
is.

By walk-forward regime (26 independent primary windows; all 1,225 trades map, 0
unmapped):

| regime | high tercile n | median edge | Sharpe | total PnL |
|---|---:|---:|---:|---:|
| trend | 150 | 38.50 bps | 1.65 | +$9,796 |
| crisis | 197 | 15.31 bps | 1.10 | +$9,677 |
| **recent** | **62** | **2.14 bps** | **0.762** | +$680 |

**Why the gate fails.** The `recent` bar (Sharpe > 1.0 in the top-liquidity tercile)
is missed at 0.762. But its CI95 is **[−0.601, +1.193]** on 62 trades — it spans
zero *and* the bar. This is **R2 (below-resolution)**, the pattern V267.md §6
pre-assigned to exactly this cell. It is **not** evidence that recent-regime carry
fails at scale; it is evidence that 62 trades cannot adjudicate it — the same
calendar-bound recent-N wall that has gated this campaign since V249, now confirmed
to bind funding-carry too once you condition on liquidity.

**Correcting the V266 finding.** V266 recorded funding-carry at Sharpe **+2.06** in
`recent` and framed it as the lane that solves the regime Victoria cannot. That
number is pooled across all liquidity. Conditioned on the top-liquidity tercile —
i.e. the part of the book that can actually hold size — recent falls to **0.762,
unadjudicable**. V266's campaign finding (ii) ("the V249 recent-N wall is
Victoria-specific") **does not survive the capacity conditioning** and should be read
as: funding-carry's recent-regime edge is currently unadjudicable at scale, not
demonstrated.

**OI-tercile robustness read** (diagnostic only, 672-trade covered subset): high
3.51 bps [−0.28, 7.61], mid 0.98 [−2.37, 4.01], low −3.49 [−5.29, −0.97]. Same
direction — edge rises with market size — but every cell except the low one has a
CI spanning zero on the smaller subset.

## 5. G0 — the OI coverage miss is a data era, not a bug

ADV joined **100%**. OI joined **54.9%**, below the 60% bar, so the G1 OI leg is
**R4-unscored** per the pre-registration (no imputation, no forward-fill; the 553
unjoined trades are dropped and counted, never filled). The cause is the Binance
`metrics` archive start date per symbol — BTCUSDT 2020-09-01, ADAUSDT 2021-12-01,
SUIUSDT 2023-05-03 — against a ledger that starts 2020-01-31. Missing counts are
concentrated in each symbol's pre-archive era (BTC 18, ADA 65, ETH 65, LINK 65, XRP
63, …; ARB and SUI 0 because they list after the archive begins).

This costs nothing material: OI and ADV agree on direction and the ADV leg — which
has full coverage — is the binding one at k=316 vs k=165.

## 6. Scorer corrections made during execution (disclosed)

Three implementation defects were corrected against the **pre-registered method
text**; **no bar was changed**, and the pre-registration commit (`cd2c2b3`) predates
every result.

1. **Day grid.** The first implementation aggregated Sharpe over exit-days only (481
   days), giving 4.94. V267.md §5.5 pre-registered *"crypto trades every calendar
   day — same convention as V266"*. Corrected to the full zero-filled calendar grid
   (2,296 days) → 2.207, which reproduces V266's 2.20. The uncorrected variant is
   retained in the artifact as a labelled diagnostic. **This correction made G2
   harder, not easier** (slippage budget fell 15.69 → 11.83 bps).
2. **G0 partial handling.** The first implementation collapsed the whole run to
   `R4_DATA_BLOCKED` when *either* join missed. V267.md §4 says only the *dependent
   leg* goes unscored. Corrected: ADV is load-bearing (all three gates); OI
   under-coverage unscores the G1 OI leg alone.
3. **G3 diagnostic added.** Bootstrap CI on the high-tercile recent Sharpe — a
   *supplementary diagnostic*, explicitly permitted by V267.md §7 and used only to
   classify the failure as R2. It does not re-score the gate; G3 still reads FAIL.

## 7. What this changes

1. **Capacity is answered, and the answer is favourable.** ~$150M gross book at the
   1%-ADV threshold, 11.8 bps of slippage headroom, edge concentrated in the liquid
   names. The V266 caveat that gated every downstream move — *"is Sharpe an artifact
   of $2k notional?"* — is **resolved in the negative**. It is not an artifact.
2. **But the promotion-relevant regime is still unadjudicable.** The recent-regime
   read at scale is Sharpe 0.762 [−0.60, +1.19] on 62 trades. Capacity was never the
   thing blocking promotion; **independent recent windows still are** — the V249 wall
   applies to both lanes once you condition on tradeable liquidity.
3. **The thin-median finding is a live-execution constraint.** 1.65 bps kills the
   median trade; 11.83 bps kills the book. Live sizing must harvest the distribution,
   not filter to "good-looking" trades.
4. **Standing baseline unmoved** (crisis +$599 / trend +$2,997 / recent +$30) — this
   version writes no strategy code and cannot move it. Daemon PID 10329 untouched.
   No trade executed, no funds moved; live-PAPER only.

## 8. Should V267-2 be queued? **No.**

2/3 with the failing leg unadjudicable is *not* the "honest partial win" that
warrants a follow-up mechanism. Concretely:

- A V267-2 that re-scores the recent cell with a different tercile cut, a different
  liquidity proxy, or a pooled-liquidity bar would be **mining a CI that spans the
  bar** — the exact R1 noise-floor pattern that kept V266-2 out of the queue, and
  the R2/R3 meta-cause the V241–V258 retrospective named as dominant.
- The blocking quantity is **independent recent windows**, and no offline analysis
  can manufacture them. The only supply is elapsed time: the V253 live-paper soak,
  accruing ~1 independent window per quarter toward the N≥20 resume gate.
- The impact-curve lane stays R4 until there is depth data or real fills at size —
  and real fills at size cannot be obtained from a paper book.

**Recommended next lateral direction (user's call):** the honest options are (a)
extend the live-paper soak to run the funding-carry lane forward at a *scaled*
notional so the recent-regime read accrues at capacity-relevant size — measurement,
not promotion; or (b) acquire orderbook/depth history for the 13 names, which is the
one purchase that would unblock the R4 impact lane. Neither is a V###; both are
data-acquisition decisions.

---

**HEAD SHA at verdict:** `717c572`
**Pre-registration SHA:** `cd2c2b3` (committed before any analysis ran).
