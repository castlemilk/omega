# V255.D-EXTENDED — VERDICT: **ADOPT extends to the full liquid universe** (real basis is clean on all 12 measured names)

**Date:** 2026-07-15 · **Author:** claude (Opus 4.8)
**Parent:** [`V255_D_VERDICT.md`](V255_D_VERDICT.md) (BTC/ETH-only ADOPT — the cap this widens) ·
[`V255_D_SCOPING.md`](V255_D_SCOPING.md) (acquisition pattern) · [`V255_C_VERDICT.md`](V255_C_VERDICT.md)
**Pre-registered decision rule:** unchanged from V255_D_SCOPING.md §5.4 (basis median |residual| < 10 bps AND pooled median net > $0 with bootstrap CI95 excluding 0). This task only *widens the measured coverage*; it does not move the goalposts.
**Code:** `scripts/v255d_freeze_basis.py` (freeze; one manifest-completeness fix), `scripts/v255d_per_symbol_basis.py` (new, read-only per-symbol analysis over the scorer's own CSV). **Zero edits to `omega/nodes/victoria/`; no scorer-logic edits — the scorer auto-detects frozen symbols.**
**Data:** `data/frozen_series/binance_futures/{11 new symbols}/{mark_price,index_price}.json` (+ `.md5` sidecars; MANIFEST now covers all 13 symbols / 26 files).
**Artifacts:** `/Volumes/gamma-systems-2/omega-victoria-data/v255_D_ext/{zero,frozen}/{v255c_scorer.json,v255c_trades.csv}` + `per_symbol.json`.

> **Result: real basis now priced on 1,108 of 1,225 trades (90.4%, up from V255.D's
> 168 / 13.7%). Pooled median net +$1.95, CI95 [+$1.13, +$2.80] (excludes 0). Measured
> median |basis residual| = 3.55 bps < the 10 bps bar. All 12 real-basis names are
> basis-CLEAN (median |residual| < 5 bps each). Verdict = ADOPT — the BTC/ETH-only cap
> lift widens to the full liquid funding-carry universe.**

---

## 1. Coverage delta (Phase 0–2)

All 11 non-BTC/ETH names in the V255.C universe have both `markPriceKlines` and
`indexPriceKlines` daily archives on `data.binance.vision` (HEAD 200 for every one). All
froze with **< 1% missing daily bars** — far under the 5% ceiling:

| symbol | earliest | n_obs (mark/index) | span | missing% | note |
|---|---|---|---|---:|---|
| ADAUSDT | 2020-01-19 | 2365 / 2364 | 6.5 yr | 0.13–0.17 | |
| BNBUSDT | 2020-01-01 | 2377 / 2373 | 6.5 yr | 0.38–0.54 | |
| LINKUSDT | 2020-01-15 | 2361 / 2367 | 6.5 yr | 0.21–0.38 | |
| XRPUSDT | 2020-01-01 | 2373 / 2382 | 6.5 yr | 0.17–0.34 | |
| DOTUSDT | 2020-08-19 | 2145 / 2145 | 5.9 yr | 0.42–0.46 | |
| SOLUSDT | 2020-09-01 | 2122 / 2138 | 5.9 yr | 0.19–0.38 | |
| AVAXUSDT | 2020-09-22 | 2112 / 2107 | 5.8 yr | 0.42–0.66 | |
| NEARUSDT | 2020-10-14 | 2091 / 2095 | 5.8 yr | 0.19–0.38 | |
| ARBUSDT | 2023-03-23 | 1208 / 1206 | 3.3 yr | 0.08–0.25 | |
| SUIUSDT | 2023-05-03 | 1167 / 1167 | 3.2 yr | 0.09 | |
| POLUSDT | 2024-09-13 | 668 / 668 | 1.8 yr | 0.15 | **< 2yr (partial); inert — see §3** |

**Determinism (byte-identity gate).** All 26 committed files pass `--verify` (sidecar MD5 ==
recomputed MD5). A scratch re-freeze of BNBUSDT reproduced the committed `mark_price.json`
**byte-identically** (same MD5) and matched `index_price.json` on **all 2,373 settled bars
with zero value diffs** — the only delta was one *newly-published trailing bar* (2026-07-14,
which had not yet published at freeze time). That is the expected live-edge behavior, not
freeze non-determinism: the committed set is uniformly frozen through 2026-07-13 (consistent
with the BTC/ETH V255.D files), and the clock-free JSON guarantees settled-bar byte-identity.
A re-freeze with `--end 2026-07-13` is byte-identical.

**One freeze-script fix (scripts-only).** `_update_manifest` previously rebuilt `MANIFEST.json`
from only *this run's* `--symbols`, so an incremental extend dropped the earlier symbols'
entries (BTC/ETH vanished from the manifest until regenerated). Fixed to always write a
full-tree manifest; MANIFEST now lists all 13 symbols / 26 files. The frozen JSON files
themselves were never affected (BTC/ETH bytes untouched throughout).

## 2. Re-verify results (Phase 3)

Freezing the 11 names lets the scorer's `_apply_frozen_basis` re-price **1,108 of 1,225
trades** on real mark/index (it auto-applies real basis to every symbol with a frozen pair;
no `--symbols` flag needed):

| metric | V255.C / V255.D (zero, or BTC/ETH-only real) | V255.D-EXT (real on 12 names) |
|---|---:|---:|
| trades with real basis | 168 (13.7%) | **1,108 (90.4%)** |
| pooled median net | +$1.56 | **+$1.95** |
| bootstrap CI95 (median net) | [+$0.86, +$2.53] | **[+$1.13, +$2.80]** (excludes 0) |
| measured median \|basis residual\| | 3.04 bps | **3.55 bps** (< 10 bps bar) |
| basis residual PnL (total) | +$122.88 / 168 | **+$3,248.80 / 1,108** (mean +$2.93, PF 3.41, WR 57.5%) |
| annualized gross carry | 29.0% | 29.0% |
| falsifiers fired | none | **none (f1–f4 all false)** |

Real basis on the wider universe was again a **net tailwind, not a tax** — it *raised* the
pooled median (+$1.56 → +$1.95) and tightened the CI's lower bound above zero. The zero-basis
assumption held across the whole liquid book, not just the majors.

## 3. Per-name classification

Frozen-basis per-symbol distributional read (`v255c_trades.csv`; medians are per-trade net
PnL in $). **Every** real-basis name is basis-CLEAN — median |residual| < 5 bps, all under
the 10 bps §5.4 bar. No name has dirty basis.

| symbol | N | frozen median net | Δmed vs zero | med \|resid\| | basis | eligibility |
|---|---:|---:|---:|---:|---|---|
| BNBUSDT | 104 | **+$10.54** | +1.72 | 4.49 bps | CLEAN | **ADOPT** |
| BTCUSDT | 93 | **+$3.60** | +1.19 | 2.28 bps | CLEAN | **ADOPT** |
| SOLUSDT | 100 | **+$3.31** | +1.37 | 3.85 bps | CLEAN (FTX tail¹) | **ADOPT** |
| DOTUSDT | 123 | **+$3.02** | −0.06 | 4.08 bps | CLEAN | **ADOPT** |
| ETHUSDT | 103 | **+$2.97** | +0.93 | 2.70 bps | CLEAN | **ADOPT** |
| MATICUSDT | 86 | +$2.47 | 0.00 | — | NO-BASIS² | ADOPT (zero-basis only) |
| LINKUSDT | 117 | **+$1.47** | +0.79 | 3.59 bps | CLEAN | **ADOPT** |
| ADAUSDT | 125 | +$0.91 | +0.28 | 2.48 bps | CLEAN | ADOPT (thin) |
| XRPUSDT | 116 | +$0.70 | +0.02 | 2.93 bps | CLEAN | ADOPT (thin) |
| AVAXUSDT | 106 | +$0.34 | +0.14 | 3.39 bps | CLEAN | ADOPT (thin) |
| ARBUSDT | 23 | −$0.01 | +0.79 | 4.91 bps | CLEAN | FLAG (≈0, small-N) |
| NEARUSDT | 107 | −$0.08 | −0.28 | 4.15 bps | CLEAN | FLAG (thin, sign-flipped) |
| SUIUSDT | 22 | −$0.69 | −0.45 | 3.34 bps | CLEAN | FLAG (small-N, negative) |

¹ **SOL FTX tail.** SOL's max single-trade residual is 2,122 bps (2022-11-09→11-16, the
FTX-collapse week — a genuine perp-mark/spot-index dislocation during the liquidation
cascade, not a data gap; entry/exit are a normal 7-day hold, both dates present). It is
**one** trade of 100; SOL's *median* residual is 3.85 bps and its p95 is 50 bps (elevated vs
peers' ~13–30 bps). The verdict is a median test and is robust to it, but SOL live sizing
should respect that carry into an exchange-solvency event can see basis blow out ~20% on a
single hold.

² **MATIC/POL mapping gap.** The funding-carry trade universe carries this name as
**MATICUSDT**; Binance's futures basis archive is under the post-rebrand **POLUSDT**. POL
froze cleanly (668 obs) but `BasisLoader.available()` keys on the trade symbol, so POL's
basis does not join the 86 MATICUSDT trades — they retain the zero-basis assumption (Δmed
$0.00). Closing this needs a MATIC→POL alias in `basis_data.py` (a follow-on; not done here
to avoid touching scorer-adjacent logic mid-verdict). MATIC's carry is positive under
zero-basis (+$2.47); its real-basis cleanliness is *untested* — treat as ADOPT-provisional.

### Honest read on the marginal names

The three FLAG names (ARB, NEAR, SUI) are **basis-CLEAN** — their weakness is *carry-alpha
thinness*, not basis cost. Their sign is inside per-trade noise: for every name with
|median| < ~$0.50 (XRP, AVAX, ARB, NEAR) a single-trade swing moves the sign, and ARB/SUI
carry only 22–23 trades. Real basis did not *cause* any name to fail — where it moved a thin
median negative (NEAR −$0.28, SUI −$0.45) the shift is well inside the per-trade dispersion,
and it *helped* ARB (+$0.79) and every major. **The decision-grade result is the pooled
median (+$1.95, CI excl 0) and the five clearly-positive, well-beyond-noise majors (BNB,
SOL, BTC, ETH, DOT).**

## 4. Verdict → **ADOPT (full liquid universe)**

Both §5.4 clauses pass on the widened coverage:
1. **Basis is clean everywhere it was measured** — pooled median |residual| 3.55 bps < 10 bps,
   and *every one* of the 12 real-basis names is individually < 5 bps. Zero dirty names.
2. **Pooled median stays net-positive with CI excluding zero** — +$1.95, CI95 [+$1.13, +$2.80]
   (tighter and higher than the BTC/ETH-only +$1.56).

**V255.C's ADOPT extends from BTC/ETH to the full liquid funding-carry book.** Real basis is
not a friction the strategy must overcome — across 90% of the trade set it is a small,
clean, slightly-favorable perturbation. The names that deserve ADOPT are the ones with
positive carry alpha (BNB, SOL, BTC, ETH, DOT decisively; LINK/ADA/XRP/AVAX positive but
thin); ARB/NEAR/SUI stay FLAG-GATED on **carry thinness / small-N**, not on basis. MATIC is
ADOPT-provisional pending the POL alias.

### Bounding the ADOPT (unchanged in spirit from V255.D)

- **Per-trade medians are thin** ($ per hold). The pooled CI is the trustworthy statistic;
  individual small-alt sign flips are noise, not signal.
- **Tail basis is real and name-specific.** SOL's FTX-week 21% single-hold residual is the
  concrete instance of the p95/max tail the median test does not see. Size for it.
- **In-sample basis was favorable**, not just small — ADOPT rests on *small* (robust), and
  the edge is charged as clean, not as a basis alpha.
- **POL/MATIC untested for real basis** (mapping gap) and **ARB/SUI are < 3.3 yr / N≈22**.

## Reproduce

```bash
# extend the freeze to the 11-name universe (byte-identical per settled bar):
python3 scripts/v255d_freeze_basis.py \
  --symbols SOLUSDT,BNBUSDT,AVAXUSDT,XRPUSDT,SUIUSDT,POLUSDT,ADAUSDT,NEARUSDT,ARBUSDT,DOTUSDT,LINKUSDT \
  --series mark,index --start 2020-01-01 --end 2026-07-13 \
  --out data/frozen_series/binance_futures/
python3 scripts/v255d_freeze_basis.py --verify --out data/frozen_series/binance_futures/

# re-verify (scorer auto-applies real basis to every frozen symbol):
OUT=/Volumes/gamma-systems-2/omega-victoria-data/v255_D_ext
python3 -m omega.nodes.funding_carry.v255c_scorer $OUT/zero   --basis-source zero
python3 -m omega.nodes.funding_carry.v255c_scorer $OUT/frozen --basis-source frozen
python3 scripts/v255d_per_symbol_basis.py \
  --zero $OUT/zero/v255c_trades.csv --frozen $OUT/frozen/v255c_trades.csv \
  --out-json $OUT/per_symbol.json
```
