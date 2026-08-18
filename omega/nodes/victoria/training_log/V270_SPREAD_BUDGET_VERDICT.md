# V270 VERDICT — spread-budget confirmation: **CONFIRMS AND TIGHTENS V267 G2**

**Date:** 2026-08-18 · **Pre-registration:** [`V270.md`](V270.md) (committed
`a28e870`, **before** `scripts/v270_spread_budget.py` was written) ·
**Scorer:** [`scripts/v270_spread_budget.py`](../../../../scripts/v270_spread_budget.py) ·
**Artefact:** `data/v270_spread_budget.json` (SHA-256 `4994b775f…`) ·
**Seed:** 42 · **Determinism:** byte-identical re-run **PASS**
**Type:** SCORING PASS — no strategy code, no flag, no grid, no backtest, no
spend, no trade. Standing baseline unmoved (crisis +$599 / trend +$2,997 /
recent +$30).

---

## 0. Headline

At V255.C's **actual traded symbol-days**, the realized Binance perp half-spread
is **0.4650 bps** (cluster-bootstrap CI95 **[0.3050, 0.5900]**) against V267 G2's
per-crossing budget of **1.6475 bps**. The whole interval sits **below a third of
the bar**, and **all 13 symbols individually clear it** — the worst, NEARUSDT, at
0.86× budget.

**V267 G2 is confirmed and the real breakeven is looser than V267 assumed.**
Quoted-spread execution cost is **not** what threatens the funding-carry lane.

And that conclusion is worth exactly as much as its coverage, which is **worse
than V269 advertised**: **117 of 1,225 trades (9.55%)**, not 12.6%, and
**0 of 340 `high_vol` trades**. V270 confirms a budget on a tenth of the ledger,
entirely in the calm carry regimes — `high_vol`, the regime V255.B measured
*strongest* and where spreads widen most, is wholly absent — for **one of the two
legs**.

| Gate | Statistic | Bar | Result | Outcome |
|---|---|---:|---:|---|
| **G1** | pooled median half-spread / crossing | ≤ 1.6475 bps | **0.4650** CI95 [0.3050, 0.5900] | **PASS** |
| **G2** | per-symbol median | none > 1.6475 bps | max **1.4100** (NEARUSDT) | **PASS** |
| **G3** | coverage honesty | report in full | 9.55%, high_vol 0/340 | **REPORTED** |
| **G4a** | rule fidelity vs V267 | within 1% | **0.0000%** / **0.0455%** | **PASS** |

**Verdict: CONFIRMS_AND_TIGHTENS_V267_G2**, computed mechanically from the gate
booleans by the scorer. No bar moved after results were seen.

---

## 1. G4a — the join is sound, so G1/G2 mean something (**PASS**)

The scorer re-derives V267's rule from the ledger alone
(`edge_bps = 1e4·pnl/notional`, `s = median(edge)/4`):

| Quantity | V267 published | V270 recomputed | rel-err |
|---|---:|---:|---:|
| pooled median edge | 6.587 bps | **6.5870** | **0.0000%** |
| `slippage_to_median_zero_bps` | 1.6475 bps | **1.6467** | **0.0455%** |

Both inside the 1% bar (the residual is V267's own published rounding). The
re-implementation is faithful; G1/G2 are not measuring an artefact of a broken
join.

**Why this replaced the briefed G4** (declared in `V270.md` §3.2, before running):
the brief asked the *joinable subset* to reproduce V267's pooled median within
1%. It cannot — the subset is a different, smaller, later-era draw, and §3 below
shows it is 3.1× richer. Requiring that would be a test that fails on a *correct*
join. Rule fidelity is the check that actually validates the join.

## 2. G1 / G2 — the measurement (**PASS**, **PASS**)

Each of the 117 joinable trades contributes two crossings (entry-day, exit-day),
each priced at that symbol-day's median of per-minute `sp_bps_p50`, halved.
CI95 by cluster bootstrap resampling whole **trades** (10,000 resamples, seed 42)
— entry and exit of one trade are dependent and are not resampled apart.

| | bps |
|---|---:|
| pooled median half-spread (234 crossings) | **0.4650** |
| cluster-bootstrap CI95 | **[0.3050, 0.5900]** |
| V267 G2 budget | 1.6475 |
| ratio (median / bar) | **0.28×** |

**Intraday-timing robustness.** A daily-bar strategy does not get to pick the
cheapest minute, so the same statistic was recomputed pricing every crossing at
its day's **p75** and **p90** instead of the median: **0.4675** and **0.4750 bps**.
The conclusion is insensitive to intraday timing — the within-day spread is stable
relative to the cross-day variation.

**G2, per symbol** — every one clears; the spread is not hiding in one name:

| symbol | trades | median | p25 | p75 | × budget |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 7 | 0.0050 | 0.0050 | 0.0100 | 0.00 |
| ETHUSDT | 7 | 0.0100 | 0.0100 | 0.0200 | 0.01 |
| SOLUSDT | 10 | 0.0500 | 0.0288 | 0.2475 | 0.03 |
| BNBUSDT | 7 | 0.1100 | 0.0850 | 0.1600 | 0.07 |
| AVAXUSDT | 9 | 0.1400 | 0.1150 | 0.5000 | 0.08 |
| LINKUSDT | 7 | 0.2700 | 0.2550 | 0.3613 | 0.16 |
| ARBUSDT | 9 | 0.3025 | 0.2600 | 0.4100 | 0.18 |
| SUIUSDT | 10 | 0.4725 | 0.3050 | 0.7512 | 0.29 |
| MATICUSDT | 11 | 0.6000 | 0.5012 | 0.8950 | 0.36 |
| DOTUSDT | 12 | 0.8075 | 0.5500 | 1.2100 | 0.49 |
| XRPUSDT | 9 | 0.8375 | 0.8000 | 0.9637 | 0.51 |
| ADAUSDT | 10 | 0.9325 | 0.7488 | 1.9937 | 0.57 |
| **NEARUSDT** | 9 | **1.4100** | 0.7638 | **3.6375** | **0.86** |

Two honest reads of that table beyond the gate:

1. **The ordering is the V267 G3 finding again, from an independent instrument.**
   Spread falls monotonically with name size — BTC/ETH are ~300× tighter than
   NEAR. V267 found the *edge* concentrated in the most liquid tercile; V270 finds
   the *cost* concentrated in the least. The two agree that this lane's economics
   improve with size, which is the favourable direction, and they agree via
   different data (volume klines vs quoted spread).
2. **NEARUSDT's p75 is 3.64 bps — 2.2× over budget.** Its *median* clears, so G2
   passes as written, but a quarter of NEAR's crossings are above V267's
   median-trade breakeven. A live book should not treat the 13 names as
   interchangeable on execution cost.

## 3. G3 — coverage, stated at full volume

**This is the part that bounds everything above.**

| | |
|---|---|
| joinable (entry-day **and** exit-day present) | **117 / 1,225 = 9.55%** |
| V269 §5's claimed joinable | 154 (12.6%) — a *calendar-month* rule, not a join |
| **V269 overstates the usable set by** | **31.6%** |
| excluded for having only one of the two days | 13 (counted, never half-filled) |
| **`high_vol`** | **0 / 340 = 0.00%** |
| `positive_carry` | 78 / 324 = 24.07% |
| `negative_carry` | 39 / 561 = 6.95% |
| depth | depth-1 top-of-book. **No ladder.** |
| legs | **perp only.** The spot leg of the basis hedge is unmeasured. |

**Correcting V269.** V269 §5 reports "12.6% of the V255.C ledger (154/1,225
trades) is joinable at all." That number counts trades whose entry *and* exit
months fall in the archive window — it is not a join. Requiring both actual days
to be present in the artefact yields **117**. The pre-registration declared this
correction before scoring (`V270.md` §6) rather than surfacing it as a result.

**Explicit statement, as pre-registered: G1 and G2 do not speak to `high_vol`.**
Zero of the 340 `high_vol` trades are covered. `high_vol` is the regime V255.B
measured *strongest*, and it is the regime where spreads widen most. Nothing in
this document constrains execution cost there. A confirmation obtained entirely
in calm-regime, positive-carry-skewed data is the weakest possible place to learn
that spreads are tight.

**G4b — representativeness (diagnostic, no bar).** The joinable subset's own gross
median edge is **20.55 bps** against the pooled **6.587** — the covered window is
**3.1× richer than the ledger average**. This does not invalidate G1/G2 (they
measure *spread*, not edge), and it happens to cut in the confirming direction:
on its own subset the breakeven would be 20.55/4 = **5.14 bps**, making the
measured 0.465 bps **11× covered** rather than 3.5×. But it does mean the covered
days are not a random draw from the ledger, and no one should read the 9.55% as a
representative sample.

## 4. Derived colour — reported, **not** gated

Median net per-trade edge on the joinable subset, charging the **measured** spread:

| | bps |
|---|---:|
| gross median edge (subset) | 20.5491 |
| **C1** — measured perp half-spread, entry + exit (2 crossings), spot at 0 | **19.1629** |
| **C2** — spot half-spread **assumed** equal to perp (4 crossings) | **17.7379** |

C1 is a **lower bound on cost** (it charges nothing for the spot leg). C2's spot
figure is an **assumption, not a measurement** — Binance USD-M `bookTicker` says
nothing about spot. Even under C2, quoted spread consumes **13.7%** of the gross
edge on this subset. Neither line is an impact model; depth-1 cannot produce one,
which is exactly why V267's R4 lane stays R4.

## 5. What this changes

1. **V267 G2's slippage budget is confirmed by direct measurement, and the true
   breakeven is looser than assumed.** Realized touch spread is 0.28× the budget,
   with the entire CI95 and every per-symbol median beneath it. The
   "is the median trade too thin to execute?" worry raised by V267 §3 is answered
   *for quoted spread*: it is not.
2. **The answer is narrow in three named ways** — 9.55% of the ledger, 0%
   `high_vol`, perp leg only. It is a real measurement of a small, non-random,
   calm-regime slice.
3. **Two independent instruments now agree the lane gets cheaper with size.**
   V267's volume-based tercile split and V270's quoted spread both put the good
   economics in the large names. This is the opposite of an illiquidity premium.
4. **What still blocks promotion is unchanged and is not execution cost.** It is
   independent `recent` windows (V249's wall, re-confirmed by V267 G3 at Sharpe
   0.762 [−0.601, +1.193]) and, for the capacity curve, true L2 depth. V270 moved
   neither, and no offline pass can.
5. **V269's QC observation is upheld under proper scoring** — 0.480 bps
   (all retained minutes) vs 0.4650 bps (at traded days). Opus 5 was right to
   leave the scoring to a pre-registered pass; the numbers agree, but the *caveats*
   only became visible by doing the join properly (the 12.6%→9.55% correction and
   the 3.1× subset richness are both V270 findings, invisible in the QC pass).

## 6. Should V270-2 or a follow-up be queued? **No.**

The honest read is: **V269's QC observation is confirmed, and no new test is
warranted.**

- **Re-scoring this artefact differently would be mining.** A different intraday
  statistic, a looser join, or a per-regime cut on a subset with 0 `high_vol`
  trades all pull from the same 117 rows. The p75/p90 robustness already shows the
  answer does not depend on the estimator.
- **The uncovered part cannot be reached offline.** The 233 `2024-04-02…04-20`
  symbol-days are permanently unavailable at any price (V269 §3.2), and no
  `high_vol` trade falls inside the archive's 2023-05→2024-04 extent. Widening
  coverage means a *purchase* or *elapsed time*, not another scoring pass.
- **The lane's binding constraint is not spread.** Confirming a cost bar that was
  already passing does not move promotion an inch; V267 G3's unadjudicable
  `recent` cell does, and it needs windows, not depth.
- **The forward L2 collector is already the correct response** and is running
  (`com.omega.depth_collector`, PID 76450, ~4.9 MB/day). It accrues one day per
  day. The next genuinely new measurement on this axis is available when it has
  enough history to cover a `high_vol` episode with a real ladder — that is a
  calendar event, not a queued version.

**If a follow-up is ever justified it is V271 = depth acquisition** (purchase
historical L2, or wait out the collector), which is a data-acquisition decision
for the user, not a mechanism V###.

## 7. Safety

- `com.omega.live_paper` **PID 13829** and `com.omega.depth_collector` **PID
  76450** verified unchanged at start and end. Neither plist, log, nor spool
  touched; the collector was read-only and never stopped.
- Nothing under `omega/nodes/` written except this log entry and `V270.md`. The
  scorer lives in `scripts/` and imports no `omega` module.
- No re-freeze, no backfill, no download. Zero network calls.
- Pre-existing dirty working tree (11 modified / 31 untracked) left untouched, as
  in every V### since V266.
- No order placed, no money moved.

---

**Scorer SHA (implementation):** `4cfb95e` — the tree this verdict was produced
from. The verdict commit is the one adding this file, immediately on top of it.
**Pre-registration SHA:** `a28e870` (committed before the scorer existed).
