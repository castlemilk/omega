# V255.D — Basis-Data Acquisition Scoping (unlocks V255.C ADOPT)

**Date:** 2026-07-14 · **Author:** claude (Opus 4.8) · **Type:** scoping doc (no code, no run)
**Parent:** [`V255_C_VERDICT.md`](V255_C_VERDICT.md) (KEEP-FLAG-GATED — capped by the
single-`close`-series basis limitation) · [`V255_C.md`](V255_C.md) (pre-reg) ·
[`V255_B_VERDICT.md`](V255_B_VERDICT.md) (where the basis cap was first pre-declared)

> **Scoping only.** This document specifies the data-acquisition work that would unblock
> a V255.C **ADOPT** verdict. It does not acquire, freeze, or run anything, and touches
> no strategy code. Acquisition + re-verify is a follow-on task the user executes with
> live-host HTTPS egress.

## Why this exists — the exact cap V255.C hit

V255.C confirmed funding-carry alpha survives realistic friction: pooled median net PnL
**+$1.56** (bootstrap CI95 **[+$0.85, +$2.39]**, excludes 0), annualized gross carry
**29.0%** / net **18.6%**, level separator **MWU p≈0 in all 3 genuine regimes**. Zero
falsifiers fired — yet the verdict was **hard-capped at KEEP-FLAG-GATED, ADOPT
impossible**, for one reason:

> The frozen data has **one `close` series per symbol**
> (`omega/nodes/funding_carry/data.py`: funding from
> `data/frozen_series/binance_funding_{sym}.json` + `close` stitched from the 32
> walk-forward OHLCV snapshots). The strategy is spot-long / perp-short (or the
> reverse); with a single price series **both legs use the same `close`**, so the price
> PnL cancels to **exactly $0.00 by construction, not by measurement**
> (`v255c_scorer.py` `hedge_cancellation` residual = $0.00, `f4_basis_fail` "cannot fire
> on single-series data"). The basis-cleanliness assumption (zero basis slippage) is
> **UNTESTED**. Per V255_B.md/V255_C.md this is a pre-declared hard cap: no ADOPT
> without real perp-mark + spot-index basis execution data.

V255.D removes exactly that cap and nothing else.

## 1. What "basis data" means

Funding carry is a **two-leg** trade: hold spot, short the perp (collect funding), or
vice-versa. Its P&L has three parts: (a) **funding** collected — already modeled from
frozen funding; (b) **price** PnL on each leg; (c) **basis** = perp mark − spot index,
whose *change over the hold* is the residual price risk the hedge is supposed to cancel.

To measure (b) and (c) honestly we need **two price series per symbol**, not one:

| series | what it is | source field |
|---|---|---|
| **perp mark price** | the futures contract's mark (what the short leg is P&L'd on) | Binance `markPrice` |
| **spot index price** | the underlying spot index (what the long leg tracks) | Binance `indexPrice` (or spot close) |

The **delta** between them (basis) is what today's single-`close` model assumes is
identically zero. Real basis is small but non-zero and moves — that movement, plus
funding on the spot-margin leg and borrow on a short-spot leg, are the frictions
V255.C's thin +$1.56 median cannot currently be charged.

## 2. Sources (all free, public Binance data)

| need | live endpoint | historical archive |
|---|---|---|
| perp **mark** & **index** (real-time) | `https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT` → `{markPrice, indexPrice, lastFundingRate, ...}` | — |
| perp **mark** daily bars (history) | — | `https://data.binance.vision/data/futures/um/daily/markPriceKlines/BTCUSDT/1d/` |
| perp **index** daily bars (history) | — | `https://data.binance.vision/data/futures/um/daily/indexPriceKlines/BTCUSDT/1d/` |
| **spot** klines (already used for OHLCV) | `https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d` | `https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/` |

- **Coverage:** `data.binance.vision` publishes `markPriceKlines/` and
  `indexPriceKlines/` daily archives from **mid-2020** for BTC/ETH; smaller alts start
  **2022+**. This matches funding coverage (funding series are 2020→2026 for the majors).
- **No key needed** — `data.binance.vision` is public S3-fronted static archives; the
  live `fapi`/`api` REST endpoints are keyless for public market data. (Binance REST is
  geo-blocked from the US per `docs/DATA_SOURCES.md`, but `data.binance.vision` static
  archives are not the blocked path — verify egress at acquisition time; if blocked,
  the archives are also mirrored and the historical klines are the load-bearing input,
  not the live REST.)

## 3. Acquisition scope for the MVP

- **Target names:** **BTC, ETH first** — V255.B/C's dominant contributors (the +$30.7k
  high_vol total is majors-led). Add SOL/XRP/AVAX only if the MVP re-verify clears.
- **Historical span:** **2020-06-01 → present**, **daily** bars (matches the funding +
  OHLCV frozen span; the mark/index archives begin ~mid-2020).
- **Freeze format:** mirror the existing frozen-series layout under a new
  `data/frozen_series/binance_futures/{SYMBOL}/` tree (the dir exists as a placeholder
  and is currently empty), one JSON per series:
  `mark_price.json`, `index_price.json`, matching the frozen-series schema
  (`{name, source:"binance-vision", fetched_at_utc, frequency:"daily",
  first_date, last_date, n_obs, unit, series:{date→value}}`). Same freeze-once /
  canonical-JSON / MD5 discipline as V238/V257.

### Acquisition command sketch (the freeze the user runs — script is V255.D build work)

```bash
# per symbol, per series: pull daily archives, normalize to frozen-series JSON
python3 scripts/v255d_freeze_basis.py \
  --symbols BTCUSDT,ETHUSDT \
  --series mark,index \
  --start 2020-06-01 --end 2026-07-14 \
  --out data/frozen_series/binance_futures/
# byte-identity: re-freeze into scratch, diff MD5 (same pattern as V257 runbook Step 3)
```

`scripts/v255d_freeze_basis.py` mirrors `scripts/v238_freeze_series.py` (freeze-once,
canonical JSON, manifest MD5). It writes only new frozen-series files — no strategy code.

## 4. Costs

| axis | estimate |
|---|---|
| **money** | **$0** — all Binance public data (archives + keyless REST). |
| **egress** | ~**500 MB** total: 2 names × ~6 years × 2 series (mark + index) daily archives (daily kline zips are small; the bound is generous). Adding SOL/XRP/AVAX later ≈ +250 MB. |
| **compute** | ~**1 hour** to download + normalize + MD5-check 2 names. Network-bound. |

## 5. What V255.D re-verify needs (post-freeze)

The acquisition is only half — the re-verify is what converts KEEP-FLAG-GATED → ADOPT
or exposes the optimism. **This part touches the funding-carry scorer (a V255.D code
task, out of scope for the current docs-only mandate), NOT Victoria strategy code.**

1. **Load mark + index as separate series.** Extend
   `omega/nodes/funding_carry/data.py` so a symbol carries `mark_price` and
   `index_price` (from the new frozen tree) alongside funding — instead of one `close`.
2. **Re-run the V255.C scorer with the two legs priced independently:**

   ```bash
   python3 -m omega.nodes.funding_carry.v255c_scorer \
     /Volumes/gamma-systems-2/omega-victoria-data/v255_D
   ```

   With mark ≠ index, `hedge_cancellation` residual is now a **measured** number, not
   $0.00 by construction — falsifier #4 (`f4_basis_hedge_fails_empirically`) becomes
   able to fire.
3. **Charge realistic basis frictions** on the thin median: basis slippage at entry/exit,
   funding on the spot-margin leg, borrow on the short-spot leg.
4. **Decision rule (pre-declared here so the re-verify is not a fit):**
   - **Basis residual empirically SMALL** (< **0.1% of notional** on the 3–7d holds) AND
     the pooled median stays net-positive after basis frictions ⇒ the V255.C
     "zero basis slippage" assumption was sound ⇒ **V255.C ADOPT is unblocked**.
   - **Basis residual empirically LARGE** (≥ 0.1% of notional, or it flips the pooled
     median ≤ $0) ⇒ the implicit zero-basis assumption was too optimistic ⇒ the alpha
     ceiling **shrinks**; funding-carry stays flag-gated and the median must be
     re-earned (longer hold / higher |funding| entry bar) under real basis costs.

   The +$1.56 median is thin (V255.C §"honest sensitivity"): a basis friction of even a
   few bps per leg is the difference between ADOPT and a re-scope. That fragility is
   precisely why real basis data is the mandatory gate.

## Scope guardrails (this doc)

- **Docs only.** No acquisition, no freeze, no scorer edit, no Victoria strategy code,
  no live-broker in this task.
- Acquisition writes only new `data/frozen_series/binance_futures/` files; the re-verify
  edits only `omega/nodes/funding_carry/` (parallel book — never imports Victoria code).
- ADOPT remains **impossible** until the measured basis residual clears the §5 decision
  rule — this scoping does not itself lift the cap, it defines the work that can.
