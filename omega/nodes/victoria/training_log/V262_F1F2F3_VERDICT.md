# V262-2 F1/F2/F3 — intraday (1h) alpha — VERDICT: **REFUTED**

**Date:** 2026-07-30
**Pre-registration:** [`V262-2.md`](V262-2.md) (committed `55a1b54`, **before** the
scorer was written), under [`V262.md`](V262.md) §5/§6.
**Thesis gates already cleared:** [`V262_F4_VERDICT.md`](V262_F4_VERDICT.md) (PASS),
[`V262_F4b_AUTOCORRELATION_VERDICT.md`](V262_F4b_AUTOCORRELATION_VERDICT.md) (CAVEATED PASS).
**Scorer:** `omega/nodes/intraday_alpha/` (new package — `loader.py`, `signals.py`,
`sim.py`, `v262_scorer.py`).
**Artifacts:** `data/v262_2/v262_2_scorer.json` (md5 `be7e8d4a…`),
`v262_2_trades_{M_momentum,R_reversion}.csv` — all byte-identical across two
independent runs.

**No strategy code touched** (nothing in `victoria/`, `funding_carry/`, or
`on_chain_flow/` modified — the scorer imports only the audited pure-statistics
helpers from `funding_carry/phase0_separator.py`, exactly as V261 did). **No flag
flipped. No live broker. Live daemon untouched.** Standing baseline (V240-selective:
crisis +$599 / trend +$2,997 / recent +$30) untouched and still the shippable answer.

---

## 1. P0 first — the corpus re-freeze and its verification

F4b §9.1 required the microsecond defect be fixed **at source** and the byte-identity
manifest re-asserted **before** F1–F3 read the corpus. Done, and it turned out to be
**two** defects, not one.

### 1a. Defect 1 — the ms/µs unit error (diagnosed by F4b, fixed here)

Binance switched the kline CSV timestamp unit from **milli**seconds to
**micro**seconds at the **2025-01** archive boundary — an era property of the source
data, not of the endpoint (it affects the monthly *and* the daily path). The freeze
took `int(row[0])` verbatim, so 19 months × 13 live names = **247 files / 177,840
bars (26.7% of the corpus)** carried timestamps ~47,000 years in the future.

Fix: a magnitude-cut normaliser `_to_ms()` at the single parse site
(`_parse_klines_zip`). A ms epoch for any plausible span is ~1e12–1e13 and the µs
equivalent ~1e15–1e16, so one cut at 1e14 separates them unambiguously (1e14 ms =
year 5138; 1e14 µs = 1973 — no real bar can sit near the boundary).

**Why the original freeze's audit was blind to it, and the structural gate added so
it cannot recur:** the missing-bar audit counted bars, and 744 bars is 744 bars
whatever the unit — a whole-file unit error is invisible to a count. A new
`_assert_in_month()` now requires every bar's `open_time` to land inside its own
month, which is the check that *can* only pass when the unit is right. The scorer's
loader re-asserts the same invariant independently (`loader.py:CorpusUnitError`), so
a regressed corpus fails loudly at read time instead of silently dropping an era —
which is exactly how this defect survived into F4's committed verdict.

### 1b. Defect 2 — a residual wall-clock channel in the provenance string (found here)

The first verification run came back **906 identical / 13 differing**. Diffing the 13
field-by-field showed the `bars` arrays were **identical** and the *only* difference
was the provenance string: `(27 daily archives)` → `(29 daily archives)`.

The daily-splice path baked the count of archives **fetched** into frozen file
content. That count grows every day `data.binance.vision` publishes another daily
archive for the partial month — a wall-clock quantity sitting in a file whose own
docstring promises it is clock-free. The prior session's `now_ms` bar-bound correctly
pinned the *bars*; it did not pin this string, so a re-freeze days later still could
not reproduce.

Fix: the count is now computed in `_write_frozen` as the number of distinct UTC dates
among the **`now_ms`-bounded retained** bars — a pure function of the frozen data, so
it reproduces on any later re-freeze. Wall-clock `n_days` stays local to the progress
line.

### 1c. Verification — surfaced before any falsifier was run

| Gate | Result |
|---|---|
| **Byte-identity re-freeze** (`--verify`, full re-download + re-freeze into scratch, `now_ms` re-derived from the committed manifest) | **PASS — identical=919, differing=0, missing=0** |
| Corpus totals | **919 files / 665,824 bars** — unchanged from the original freeze |
| µs-unit bars remaining | **0 / 919 files** |
| Bars outside their own month | **0** |
| Non-monotonic / off-hour-grid bars | **0 / 0** |
| Bars past the pinned `now_ms` | **0** |
| **2020-01 → 2024-12 preserved byte-identical vs `HEAD`** | **PASS — 672 / 672 cells, 0 differing** |
| Cells rewritten | **247** (156 × 2025 + 91 × 2026) + `MANIFEST.json`; MATICUSDT correctly untouched (history ends 2024-09) |

### 1d. Corrected F4 coverage (F4's PASS is confirmed, not inverted)

F4 re-run on the corrected corpus. Every live name gains **+137 windows**; MATIC
gains **0**, correctly, because its history ends 2024-09.

| Symbol | n windows (F4 as committed) | **n windows (corrected)** | Δ | V (committed) | **V (corrected)** | agreement | nMI |
|---|---:|---:|---:|---:|---:|---:|---:|
| SOLUSDT | 427 | **564** | +137 | 0.1299 | **0.1262** | 0.326 | 0.0372 |
| BNBUSDT | 486 | **623** | +137 | 0.0806 | **0.0886** | 0.273 | 0.0554 |
| AVAXUSDT | 416 | **553** | +137 | 0.1951 | **0.1802** | 0.349 | 0.0710 |
| XRPUSDT | 486 | **623** | +137 | 0.0788 | **0.0783** | 0.281 | 0.0232 |
| SUIUSDT | 162 | **299** | +137 | 0.1432 | **0.1205** | 0.391 | 0.0421 |
| POLUSDT | 29 | **166** | +137 | 0.3664 | **0.1869** | 0.458 | 0.1430 |
| ADAUSDT | 486 | **623** | +137 | 0.1330 | **0.1344** | 0.289 | 0.0705 |
| NEARUSDT | 410 | **547** | +137 | 0.1346 | **0.1138** | 0.325 | 0.0289 |
| ARBUSDT | 173 | **309** | +136 | 0.1360 | **0.1337** | 0.401 | 0.0739 |
| MATICUSDT | 456 | **456** | +0 | 0.1113 | **0.1113** | 0.246 | 0.0277 |
| **Universe mean (10)** | | | | **0.150898** | **0.127395** | | |
| Universe **max** | | | | 0.36645 | **0.186909** | | |

**F4 = PASS is unchanged and now stronger.** Corrected mean Cramér's V **0.1274**
(was 0.1509) against the 0.7 cut; the diagnostic sqrt-scaled arm moves 0.1782 →
**0.1452**, still non-degenerate (0/10). The one loose end F4 §6.4 flagged —
"POLUSDT n=29 is thin, and is the one elevated reading" — **resolves**: at the true
n=166, POL's V falls 0.3664 → **0.1869**, and the universe max drops with it. The
elevated reading was a thin-history artifact of the truncation, exactly as suspected.

## 2. What was pre-registered (all of it before any number was seen)

Every parameter is fixed in [`V262-2.md`](V262-2.md), committed `55a1b54`. Summary:
30-observation z-window at each member's **native** cadence then forward-filled;
entry `|composite z| ≥ 1.0` with a `hourly_volume_z ≥ 0` participation filter;
direction `sign(z)`; **primary hold 5 bars**; $10k notional; **12 bps/side ⇒ 24 bps
round-trip** (Binance VIP-0 spot taker 10 bps + 2 bps slippage, single-leg — *not*
the V255.B 2-leg model); non-overlapping holds with **timestamp** contiguity (never
index adjacency, so no hold spans a real hole); `hourly_basis_z` dropped as
🔴 BLOCKED per the audit verdict; MATIC/POL kept as two never-spliced name-histories.

The `hourly_return_z` **sign is not determined a priori**, so both readings were
pre-declared as arms — **M (momentum, +1)** and **R (reversion, −1)** — under a
**Bonferroni α = 0.05/2 = 0.025**, with F1+F2+F3 required to pass *within the same
arm*. All significance is **N_eff-deflated by the F4b SLEM factor 0.778**.

## 3. Coverage limitation, surfaced not swallowed

**POLUSDT is feed-blocked and contributes 0 trades.** There is no frozen
`binance_funding_polusdt` or `binance_oi_polusdt` series (only `…_maticusdt`), so
two composite members have no coverage for POL and the pre-declared all-or-nothing
fence drops every POL bar. This is the declared fence operating, not a silent drop —
the scorer reports `feed_blocked_symbols` and `missing_frozen_feeds` explicitly.
Substituting a neutral 0.0 was rejected: that fabricates a signal value, the failure
mode the V235 seam lesson and the V221 epsilon lesson both warn against.

**Effective verdict universe = 9 names** (SOL, BNB, AVAX, XRP, SUI, ADA, NEAR, ARB,
MATIC). This is the same POL data-era gap V255.D-EXT hit, one layer up.

## 4. Primary-arm results (verdict-bearing: hold 5 bars, 12 bps/side)

| | **M (momentum, +1)** | **R (reversion, −1)** |
|---|---:|---:|
| Trades | 1,628 | 1,614 |
| **Median net PnL** | **−$31.98** | **−$9.96** |
| Mean net PnL | −$23.72 | −$11.42 |
| Total net PnL | −$38,611.17 | −$18,433.17 |
| Net p25 / p75 | −$138.68 / +$81.56 | −$128.90 / +$112.64 |
| Net win rate | 0.4269 | 0.4771 |
| Net profit factor | 0.765 | 0.880 |
| **Median GROSS PnL** | −$7.98 | **+$14.04** |
| Total gross PnL | +$460.83 | **+$20,302.83** |
| Gross win rate | 0.4736 | **0.5285** |
| Gross profit factor | 1.003 | **1.151** |
| **Annualized net** (F3 reading) | **−415.52%** | **−200.09%** |
| Annualized gross | +4.96% | **+220.39%** |
| Duty cycle | 1.84% | 1.83% |
| Duty-cycled net, per symbol-year | −7.66% | −3.66% |
| **MWU on entry \|z\|, p deflated** | **0.3305** | **0.4880** |
| MWU p undeflated (reported) | 0.2700 | 0.4318 |
| **Break-even round-trip bps** | — (gross median ≤ 0) | **14.04 bps** |

### Per-name results, primary arm (verdict-bearing 10)

| Symbol | M trades | M median net | M median gross | R trades | R median net | R median gross |
|---|---:|---:|---:|---:|---:|---:|
| SOLUSDT | 217 | −$39.94 | −$15.94 | 221 | −$10.12 | +$13.88 |
| BNBUSDT | 191 | −$27.20 | −$3.20 | 181 | −$12.39 | +$11.61 |
| AVAXUSDT | 192 | −$28.70 | −$4.70 | 209 | −$17.04 | +$6.96 |
| XRPUSDT | 251 | −$39.49 | −$15.49 | 247 | −$6.87 | +$17.13 |
| SUIUSDT | 110 | −$43.17 | −$19.17 | 107 | **+$1.57** | +$25.57 |
| **POLUSDT** | **0** | — | — | **0** | — | — |
| ADAUSDT | 194 | −$17.38 | +$6.62 | 201 | −$3.97 | +$20.03 |
| NEARUSDT | 189 | −$44.25 | −$20.25 | 189 | −$24.00 | $0.00 |
| ARBUSDT | 137 | −$4.86 | +$19.14 | 130 | −$15.97 | +$8.03 |
| MATICUSDT | 147 | −$20.07 | +$3.93 | 129 | −$18.79 | +$5.21 |

**Net median is negative on 9 of 9 traded names in the momentum arm and 8 of 9 in the
reversion arm** (SUI's +$1.57 is the lone positive, on 107 trades). Gross median is
positive on 8 of 9 in the reversion arm — the same "real but sub-friction" pattern as
the pooled book. POL contributes 0 trades (§3).

Reported-only names (excluded from the verdict, per V262.md §3) show the same shape —
reversion gross positive, net negative: BTC −$10.24 net / +$13.76 gross; ETH −$23.88 /
+$0.12; DOT +$2.86 / +$26.86; LINK −$6.73 / +$17.27. Full `net`/`gross` blocks for all
14 names are in `data/v262_2/v262_2_scorer.json` → `arms.*.per_name` and
`.reported_only_names`.

## 5. Falsifiers — each against its pre-registered number

| Falsifier | Pre-registered REFUTE condition | M (momentum) | R (reversion) |
|---|---|---|---|
| **F1** — pooled median | median ≤ $0, **or** deflated CI95 does not exclude 0 | **REFUTED** — median **−$31.98** ≤ $0 (deflated CI95 [−$39.96, −$21.62] excludes zero, but *below* it) | **REFUTED** — median **−$9.96** ≤ $0, and deflated CI95 **[−$22.99, +$1.80] contains zero** |
| **F2** — mechanism | MWU p ≥ 0.025 (Bonferroni, N_eff-deflated) | **REFUTED** — p = **0.3305** ≥ 0.025 | **REFUTED** — p = **0.4880** ≥ 0.025 |
| **F3** — annualized net | annualized net < 15% | **REFUTED** — **−415.52%** | **REFUTED** — **−200.09%** |

**All three fire in both arms.** No arm passes anything, so the FLAG-GATED branch is
not reached either: it required F2 to pass (mechanism real) *with* the gross book
clearing F1/F3, and F2 fails in both arms.

> ### **F1 = REFUTED · F2 = REFUTED · F3 = REFUTED**
> ### **Overall verdict: REFUTED**
> Intraday (1h) resolution does **not** reopen the entry-side composite.

## 6. Honest diagnosis — what actually fired, and what did not

**Something real is in the data, and it is not the pre-declared mechanism.**

The reversion arm's **gross** book is not empty: median **+$14.04** per $10k trade
(≈14 bps), win rate **52.85%**, profit factor **1.151**, +$20.3k total over 1,614
trades. A 1-hour mean-reversion tendency in liquid alt majors is visible at gross.

Three independent readings say it is not tradable alpha, and not the V262 thesis:

1. **It has no dose-response.** F2 is the test of whether the *pre-declared composite
   magnitude* grades outcomes, and it fails at **p = 0.4880** — winners' entry |z| is
   statistically indistinguishable from losers'. The intraday-native-only diagnostic
   arm makes this starker: at **38,139 trades** (a large sample, deflation
   irrelevant) the reversion median gross is **+$11.22** with MWU **p = 0.9234** —
   about as flat a non-relationship as the test can report. The effect is a roughly
   *constant* per-trade reversion, not a signal that pays more when it speaks louder.
   That is the fingerprint of **bid-ask bounce / microstructure noise**, which
   `V262.md` §7 listed as a named risk ("1h bars carry bid-ask bounce and thin-book
   artifacts that daily bars average away") — and it is the same shape that killed
   V261 (p = 0.942).

2. **It is smaller than the friction, at every hold in the ladder.** The break-even
   round-trip is **14.04 bps** against a declared **24 bps**. And the edge *decays*
   with holding period rather than accumulating:

   | Hold | M median gross | M break-even bps | R median gross | **R break-even bps** |
   |---|---:|---:|---:|---:|
   | 5 bars (5 h) | −$7.98 | — | **+$14.04** | **14.04** |
   | 24 bars (1 d) | −$25.42 | — | +$10.58 | 10.58 |
   | 72 bars (3 d) | −$34.71 | — | −$9.95 | — |
   | 168 bars (7 d) | −$60.41 | — | −$52.29 | — |

   **There is no hold in the pre-declared ladder at which the gross edge covers the
   round-trip cost** — the best case clears 58% of it, and lengthening the hold makes
   it worse, not better. That closes the obvious rescue before it can be attempted,
   and it is why lengthening the hold would have been tuning rather than discovery.

3. **The momentum arm is simply flat.** Annualized gross **+4.96%**, gross profit
   factor **1.003**, gross median negative. Momentum at 1h is not there at all.

**On F3's magnitude.** The −415% / −200% annualized net figures are the *inherited
V261 convention* (mean return per hold × holds per year, i.e. capital continuously
recycled). At a 5-hour hold that is 1,752 holds per year, so a 24 bps round-trip
compounds to a very large drag — the arithmetic this version's own pre-registration
predicted in §7 before any run. The realized duty cycle is only **1.8%**, so the
honest realized figures are the duty-cycled **−7.66% / −3.66% per symbol-year**.
Both readings are reported; F3's pre-registered gate reads the fully-deployed one.
Either way the sign is negative and F3 fires.

**The prediction on the record held.** `V262-2.md` §7, `V262.md` §7,
`V262_AUDIT_VERDICT.md` §4 and both F4 verdicts all named F3 / transaction cost as
the most likely killer, citing V255.B (a *confirmed* 36.4% gross alpha that still
died at −$5.95 median net). That is what happened, with F2 failing alongside it.

**What this does not say.** F4 and F4b remain PASS: intraday windows *are* genuinely
orthogonal to the macro-day regime (V = 0.1274) and *do* manufacture real independent
samples at ~0.78–0.87 efficiency (~19–21×). The effective-N thesis survived. What
died is the **payoff** — the samples are real, and the pre-declared composite has no
tradable edge in them at intraday frequency, net of realistic friction. R2
("signal below eval resolution") is not the diagnosis here; this is a genuine
negative at full resolution.

## 7. Consequence for the campaign

**Redirects to spot Victoria + funding-carry**, exactly as the success frame
anticipated for an F3 refutation:

- **The last untried non-calendar axis is now closed.** V249 named two resume paths:
  (1) live-paper accrual to recent-N ≥ 20, and (2) *"a new data source that changes
  regime structure — explicitly naming intraday OHLCV freeze."* Path (2) was this
  version. It is spent at 1h, on specific evidence rather than on data absence.
- **The one confirmed alpha is unchanged:** V255.C funding-carry, KEEP-FLAG-GATED,
  with V255.D/D-EXT's real basis adopted.
- **Live-paper (V253) is now the only lane that accrues new independent evidence**,
  at ~1 independent recent window per quarter. That raises its priority; it is the
  only path to the recent-N ≥ 20 resume gate.
- **5m should NOT be frozen on the strength of this.** The pre-declared tier order
  (V262.md §4) gated 5m on 1h clearing F4 **and F3**. F3 refuted. Going to 5m would
  multiply the bars 288× against a friction wall that already beat us at 1h with the
  edge *decaying* toward longer holds, and would add 288× the overfit surface. The
  storage-is-cheap correction in the audit verdict does not change this — the
  argument against 5m was always scientific, and F3 just supplied the evidence.

## 8. Residual risks / what this verdict does not clear

1. **POL is feed-blocked** (§3) — 9 of 10 verdict names carried the composite. Adding
   frozen POL funding/OI would be a small freeze task, but nothing in the result
   suggests one name would move a verdict where all three falsifiers fire in both
   arms by wide margins.
2. **Six of the nine composite member signs were declared on economic grounds**, not
   transplanted from Victoria's live signal classes (which embed regime-conditional
   weighting that cannot be lifted into an offline scorer without importing strategy
   code — forbidden here). The funding sign is inherited from the confirmed V255.C
   direction. A different sign set is a different composite; that would be a new
   pre-registration, not a re-read of this one.
3. **The composite-mean construction makes `entry_z = 1.0` a ~3σ gate.** Averaging
   nine roughly-independent z's shrinks the composite's own dispersion, so the
   inherited V261 threshold is much more selective at 9 members than at V261's 4 —
   hence 1,628 trades from 665,824 bars and a 1.8% duty cycle. The threshold was
   inherited rather than re-chosen on purpose (anti-Goodhart), but the trade count is
   a consequence worth naming. The intraday-native-only arm (38,139 trades) is the
   high-N cross-check, and it agrees — more emphatically (p = 0.9234).
4. **Only 1h was tested.** This refutes the intraday thesis **at 1h**, at the
   pre-declared composite and friction. It does not prove no intraday effect exists
   at any frequency for any mechanism — but see §7 on why 5m is not the next move.
5. **The fee model is a declared assumption.** 24 bps round-trip is Binance VIP-0
   spot taker plus 2 bps slippage. A VIP-tier or maker-rebate operator faces less;
   however the best break-even in the entire ladder is 14.04 bps, so the round-trip
   would have to fall below ~14 bps *and* F2's absent dose-response would still have
   to be explained.

## 9. What this task delivered

**Delivered:** the P0 corpus re-freeze (two defects fixed at source, byte-identity
919/919 re-asserted, 672 pre-2025 cells preserved), the structural in-month gate that
makes the unit defect non-recurrable, the new `omega/nodes/intraday_alpha/` offline
scorer (deterministic — byte-identical across two independent runs), the corrected F4
coverage table, this verdict, a correction note on `V262_F4_VERDICT.md`, and the
`V254_ALT_DATA_SCOPING.md` intraday update.

**Explicitly NOT delivered:** no strategy code, no flag, no 5m freeze, no live
broker, no daemon change, no post-hoc re-tuning of the hold or fee to rescue F3.
Every V241–V262 flag stays **OFF**.
