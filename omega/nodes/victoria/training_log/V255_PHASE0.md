# V255 Phase 0 — Funding-carry offline separator (v2 directional)

**Date:** 2026-07-14 · **Author:** claude (Opus 4.8) · **Type:** Phase-0 $0 offline separator
**Parent scope:** [`V255.md`](V255.md) · **Companion:** [`V254_ALT_DATA_SCOPING.md`](V254_ALT_DATA_SCOPING.md) option B (#1-ranked)
**Code:** `omega/nodes/funding_carry/` (new module, zero edits to `omega/nodes/victoria/`)
**Artifacts:** `/Volumes/gamma-systems-2/omega-victoria-data/v255/v255_phase0_{separator.json,trades.csv}`

## Verdict: **REFUTED** (v2 directional form)

> Pre-registered gate (V255.md §F): PASS iff **Mann-Whitney U two-sided p ≤ 0.10
> AND pooled median trade PnL > $0**. Result: **p = 0.6068, pooled median = −$44.06.
> Both fail. REFUTED.**

The entry funding z-score does **not** discriminate winners from losers
(winners' median |z| = 1.412 vs losers' 1.442 — statistically identical), and
the strategy loses money in aggregate. scipy `mannwhitneyu` cross-check confirms
the pure-python statistic exactly (U = 652048, p = 0.606809).

## What was tested

The v2 directional funding-mean-reversion strategy, exactly as pre-registered:
- Universe: 13 Binance-perp names with frozen funding data (BTC, ETH, SOL, BNB,
  XRP, ADA, DOT, AVAX, LINK, MATIC, NEAR, SUI, ARB).
- Span: **2020-01-01 → 2026-05-29** (2341 aligned daily obs; funding from
  `frozen_series`, close stitched from the 32 walk-forward OHLCV snapshots,
  0 gaps).
- Signal: trailing funding z-score, lookback 30d. Entry SHORT when z > +1.0,
  LONG when z < −1.0. Fixed 7-day hold. One position/symbol at a time.
- PnL = notional·(price_ret + funding_accrual − round-trip fee). $10k notional,
  5 bps/side. **2300 trades enumerated.**

## Pooled result

| metric | value |
|---|---:|
| trades | 2300 |
| total PnL | **−$260,312** |
| mean / trade | −$113.18 |
| median / trade | −$44.06 |
| win rate | 48.0% |
| profit factor | 0.792 |
| p25 / p75 | −$726 / +$588 |

## The load-bearing decomposition — *why* it failed

Splitting each trade's return into components (per-unit-notional × $10k):

| component | total | mean/trade | median/trade |
|---|---:|---:|---:|
| **price_ret** | **−$292,509** | −$127.18 | −$43.12 |
| **funding_ret** | **+$55,197** | +$24.00 | +$8.50 |
| cost_ret (fees) | −$23,000 | −$10.00 | −$10.00 |

**Price risk is the killer, not the carry thesis.** The directional rule
(short high-funding / long low-funding) is a momentum-*contrarian* bet — it
shorts the assets that are rallying hardest (high funding = crowded longs =
usually a strong uptrend). The **funding component is positive exactly as §A
predicted (+$55k gross, +$24/trade mean)** — it is swamped by the directional
price loss the v2 form takes on.

## Secondary diagnostics (shape the follow-on, do NOT overturn the verdict)

These are honest post-hoc analyses of the same trade ledger. They do **not**
re-run the gate — v2 is refuted. They tell us *where the carry alpha actually
lives* so the next-step recommendation is evidence-based, not a guess.

**1. The right entry variable is funding LEVEL, not z-score.**
A separator on |entry funding| against **hedged-carry** outcome (funding+cost,
price stripped) is highly significant: winners' median entry funding 0.000207
vs losers' 0.000058, **MWU p < 0.0001**. Carry winners are simply the trades
entered when funding was already high — a level signal, not a z-extreme timing
signal. v2 used the wrong variable.

**2. The loss is entirely in the `near_zero` funding regime.**
Bucketing v2 trades by entry funding-regime (classifier defined *before* the
strategy, §E):

| funding regime | trades | total PnL | median | WR |
|---|---:|---:|---:|---:|
| near_zero | 1333 | **−$287,962** | −$121.27 | 43.6% |
| negative_carry | 608 | +$47,107 | +$90.08 | 54.9% |
| high_vol | 193 | −$16,675 | +$139.50 | 53.9% |
| positive_carry | 166 | −$2,781 | +$107.12 | 51.8% |

58% of trades fall in `near_zero` — where there is no funding structure to
harvest, so the trade is pure price-noise-fighting-momentum, and it accounts
for **more than 100% of the total loss**. In the three regimes with *actual*
funding structure, v2 trades have **positive medians and >50% win rates**.

**3. Hedged basis carry (v1) is real but thin and tail-driven.**
If price were perfectly hedged (the v1 basis trade), funding+cost carry totals
+$32,197 (mean +$14/7d hold ≈ **7.3% annualized gross**, WR 47.3%, **median
−$1.50**). Restricting to the natural direction (harvest positive funding only)
lifts it to mean +$18.46, **median +$1.42, WR 52.7%** (~9.6% annualized gross).
This is *below* the §A thesis's 15–30% and is **before** the frictions the
offline sim doesn't model (perp-spot borrow, two-leg slippage, basis tracking).

## The independent-window claim (§E) — partially undercut

The V254 thesis for ranking carry #1 was that funding regimes manufacture
*independent* recent windows. Tiling the 2341-day span into 26 non-overlapping
90d slots and majority-labelling each by funding regime:

`{near_zero: 16, negative_carry: 7, high_vol: 3, positive_carry: 0}`

This is a **different** partition than spot (spot: crisis 12 / trend 10 /
recent 4 — V249) — so it *is* structurally independent — **but it is not a
windfall of new windows.** `near_zero` swamps the count (16/26), and no 90d slot
is majority `positive_carry`. A carry strategy that only earns in genuine
funding regimes has an *effective* independent-N of ~7 (negative_carry) + 3
(high_vol) — comparable to, not dramatically larger than, spot's recent-4. The
"genuinely independent windows" argument survives (different clock) but the
"much more N" argument does **not** clearly hold for this classifier.

## Determinism

Pure-python stats (no RNG), `math.fsum` reductions, canonical `sorted` iteration.
Re-running under `PYTHONHASHSEED=42` is byte-identical; scipy cross-check matches
the hand-rolled MWU to 6 dp. No Victoria state touched.

## Recommendation → see [`V255.md`](V255.md) §Conclusion

v2 directional: **closed, refuted.** The carry component is real but the
directional form is dead (price risk) and the hedged form is marginal. Two
legitimate next bets, ranked in V255.md:
- **V255.B** — level-entry, regime-filtered (`near_zero`-excluded), basis-hedged
  carry harvest. The separators above say this is where the signal is.
- **V254 Track C** — on-chain flow primary universe, if the thin pre-friction
  carry magnitude doesn't clear the bar for a full basis-trade build.
