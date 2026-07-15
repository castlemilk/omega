# V255.D — VERDICT: **ADOPT UNLOCKED** (real basis is clean; the zero-basis assumption held)

**Date:** 2026-07-15 · **Author:** claude (Opus 4.8)
**Parent:** [`V255_D_SCOPING.md`](V255_D_SCOPING.md) (acquisition + re-verify spec) ·
[`V255_C_VERDICT.md`](V255_C_VERDICT.md) (KEEP-FLAG-GATED, the cap this lifts)
**Pre-registered decision rule:** V255_D_SCOPING.md §5.4 (written before any basis data was fetched)
**Code:** `scripts/v255d_freeze_basis.py` (freeze), `omega/nodes/funding_carry/{basis_data.py,v255c_scorer.py}` (re-verify) — **zero edits to `omega/nodes/victoria/`**
**Data:** `data/frozen_series/binance_futures/{BTCUSDT,ETHUSDT}/{mark_price,index_price}.json` (+ `.md5` sidecars + `MANIFEST.json`)
**Artifacts:** `/Volumes/gamma-systems-2/omega-victoria-data/v255_D/{zero,frozen}/{v255c_scorer.json,v255c_trades.csv}`
**Determinism:** freeze is byte-identical on re-run (clock-free JSON; MD5 matches across two independent freezes — see §1). Scorer bootstrap is fixed-seed (20250714).

> **Pre-registered gate (§5.4).** ADOPT requires **BOTH**: (a) the measured basis
> residual is SMALL — median |residual| **< 0.1% (10 bps) of notional** over the
> 3–7d holds — AND (b) the pooled median net PnL stays **> $0 with a bootstrap
> CI95 excluding zero** after real basis is charged. LARGE basis (≥ 10 bps, or it
> flips the median ≤ $0) ⇒ stays KEEP-FLAG-GATED.
> **Result: median |basis residual| = 3.04 bps (< 10 bps) AND pooled median net
> = +$1.56, CI95 [+$0.86, +$2.53] (excludes 0). BOTH clauses pass ⇒ ADOPT.**

---

## What changed vs V255.C

V255.C priced both carry legs off ONE `close` series per symbol, so
`spot_price_pnl + perp_price_pnl` cancelled to **exactly $0 by construction** —
the basis-cleanliness assumption was *untested*, hard-capping the verdict at
KEEP-FLAG-GATED. V255.D freezes the **two real price series** Binance publishes —
perp **mark** (`markPriceKlines`) and spot **index** (`indexPriceKlines`) — and
re-prices the perp leg on mark, the spot leg on index. The price-leg residual is
now a **measured** number (Δbasis over the hold), not an algebraic zero, so the
`f4_basis_hedge_fails_empirically` falsifier can finally fire. It did not.

## 1. Data frozen (Phase 1–2)

`scripts/v255d_freeze_basis.py` pulled the monthly `data.binance.vision`
`markPriceKlines` + `indexPriceKlines` daily archives (sha256-verified against
each `.CHECKSUM` sidecar; raw zips mirrored to the gamma volume, compact
daily-close JSON committed):

| symbol | series | n_obs | span | missing daily bars |
|---|---|---:|---|---:|
| BTCUSDT | mark_price | 2225 | 2020-06-01 → 2026-07-13 | — |
| BTCUSDT | index_price | 2221 | 2020-06-01 → 2026-07-13 | — |
| ETHUSDT | mark_price | 2231 | 2020-06-01 → 2026-07-13 | — |
| ETHUSDT | index_price | 2230 | 2020-06-01 → 2026-07-13 | — |

**Coverage assertions (both PASS):** BTC 6.12 yr / 0.81% missing, ETH 6.12 yr /
0.18% missing — both ≫ the 3-year floor and ≪ the 5%-missing ceiling.
**Determinism gate PASSES:** a second independent freeze produced byte-identical
MD5s on all four files (`c8081fdc…`, `f7f28a8c…`, `ac46112d…`, `622f6788…`).

### Realized basis distribution (perp mark − spot index, on the common days)

| symbol | mean | p50 | p75 | p95 (\|·\|) | max (\|·\|) |
|---|---:|---:|---:|---:|---:|
| BTCUSDT (bps of index) | −1.57 | −3.47 | 0.00 | 8.07 | 18.84 |
| ETHUSDT (bps of index) | −1.17 | −3.27 | +0.46 | 9.33 | 31.83 |

Basis *level* is small and mean-reverting (median ≈ −3.4 bps, clustered near 0).
The quantity that actually hits the hedge is the **change** in basis over the
hold — reported next.

## 2. Measured basis residual over the holds (the §5.4 decision variable)

Re-pricing the two legs independently on 168 BTC+ETH carry trades (the frozen
names in the V255.C trade set; the other 1,029 trades on the 11 unfrozen symbols
retain the zero-basis assumption, so the pooled trade SET is unchanged):

| basis residual / notional | value |
|---|---:|
| n (real-basis trades) | 168 |
| median \|residual\| | **3.04 bps** |
| p75 \|residual\| | 6.19 bps |
| p95 \|residual\| | 12.85 bps |
| max \|residual\| | 41.61 bps |
| mean (signed) | +0.89 bps |
| median (signed) | +1.32 bps |

The residual is **small at the center (3.04 bps ≪ the 10 bps bar) and slightly
POSITIVE-signed** — over these holds the basis converged in the carry-receiver's
favor more often than not. As realized PnL, the basis residual across the 168
trades totalled **+$122.88** (mean +$0.73, median +$0.35, win rate 59.5%,
PF 1.75). **Real basis was a small tailwind, not the friction tax the cap
feared.**

## 3. Re-verify results (Phase 3)

**Full universe (real basis on BTC/ETH, zero-basis retained on the other 11):**

| metric | V255.C (zero basis) | V255.D (real basis) |
|---|---:|---:|
| n trades | 1225 | 1225 |
| pooled median net | +$1.56 | **+$1.56** |
| bootstrap point median | +$1.5646 | +$1.5646 |
| **CI95 (median net)** | **[+$0.85, +$2.39]** | **[+$0.86, +$2.53]** |
| CI excludes zero | yes | **yes (lo > 0)** |
| annualized gross | 29.0% | 29.0% |

The full-universe median is **unchanged** and its CI still cleanly excludes zero —
charging real basis on the majors did not erode it (marginally widened the upper
bound).

**BTC+ETH-only measured subset (the pure test — no zero-basis fallback):**

| metric | same 168 under zero basis | 168 under REAL basis |
|---|---:|---:|
| median net | +$2.22 | **+$3.09** |
| total net | +$4,955 | +$5,078 |
| win rate | — | 66.1% |
| **CI95 (median net)** | — | **[+$0.83, +$6.74]** (excludes 0) |
| BTC-only median | — | +$3.60 |
| ETH-only median | — | +$2.97 |

On the names where basis is *actually measured*, the carry alpha **survives
independently** (BTC and ETH each positive, CI excludes zero) and real basis
**improved** the subset median by +$0.87 (+$122.88 total). No falsifier fired
(`f1–f4` all false).

## 4. Verdict → **ADOPT**

Both pre-registered §5.4 clauses pass:
1. **Basis is clean** — median |residual| 3.04 bps < the 10 bps bar.
2. **Median stays net-positive with CI excluding zero** — full-universe +$1.56,
   CI95 [+$0.86, +$2.53]; and the measured-only subset is *stronger* (+$3.09,
   CI [+$0.83, +$6.74]).

**The zero-basis assumption V255.C rested on was sound** (indeed conservative —
real basis helped). **V255.C ADOPT is unlocked: the KEEP-FLAG-GATED cap is
removed for the BTC/ETH funding-carry book.** Funding carry moves from
`VALIDATED, FLAG-GATED` to `VALIDATED, ADOPT (BTC/ETH)`.

### Honest limitations (bounding the ADOPT)

- **Measured on 2 of 13 names.** BTC + ETH are the dominant V255.B/C contributors
  (the high_vol majors-led total), and the measured-only subset independently
  clears the bar — but the 11 unfrozen symbols (84% of the pooled trade count)
  still carry the *untested* zero-basis assumption. ADOPT is scoped to **BTC/ETH**;
  extending it to SOL/XRP/AVAX/… requires freezing their mark/index and re-running
  (the freeze script already takes `--symbols`). Their monthly archives begin
  ~2022, so expect shorter history.
- **Tail basis exceeds the bar.** The residual's p95 (12.85 bps) and max
  (41.61 bps) are *above* the 10 bps line even though the median is well under it.
  The decision rule is a median test (central tendency), which passes cleanly, but
  live sizing/risk should respect occasional wide-basis events — they are real and
  can erase a thin per-trade median on a single hold.
- **In-sample basis was favorable.** ADOPT rests on the residual being *small*
  (robust), not on it being *favorable* (a realized-sample fact that need not
  persist). The edge is charged as clean, not as a basis alpha.
- **Daily-close basis, not intraday execution.** We measured basis at daily marks,
  matching the daily backtest cadence; intraday entry/exit slippage on the two
  legs is a separate (smaller) friction not modeled here.

## Reproduce

```bash
# freeze (byte-identical on re-run):
python3 scripts/v255d_freeze_basis.py --symbols BTCUSDT,ETHUSDT --series mark,index \
  --start 2020-06-01 --end 2026-07-14 --out data/frozen_series/binance_futures/
python3 scripts/v255d_freeze_basis.py --verify --out data/frozen_series/binance_futures/

# re-verify (default zero == byte-identical to V255.C; frozen == real basis):
python3 -m omega.nodes.funding_carry.v255c_scorer --basis-source zero
python3 -m omega.nodes.funding_carry.v255c_scorer --basis-source frozen
```
