# V269 VERDICT — free-tier depth acquisition: PARTIAL (Phase A reduced), SHIPPED (Phase B)

**Date:** 2026-08-17 · **Pre-registration:** [`V269.md`](V269.md) (committed `9307969`,
before any bulk download) · **Implementation:** `0085a8b`
**Type:** DATA ACQUISITION — no strategy code, no flag, no grid, no backtest, no
live-broker, no spend, no trade.

---

## 1. Outcome in one line

The depth data Binance gives away free was acquired to its **actual extent**, which
is materially smaller than its directory listing implies — and it is **depth-1**, so
**V267's R4 `Sharpe(2k→2M)` lane remains data-blocked at source.** What V269 does
deliver is a real, deterministic quoted-spread artefact for 77% of the planned
symbol-days, plus a running forward-L2 collector that is the only $0 path to a true
ladder and accrues one day per day.

| Lane | Status |
|---|---|
| Phase A — historical `bookTicker` aggregate | **PARTIAL** — 876/1,135 symbol-days (77.2%) |
| Phase B — forward L2 collector | **SHIPPED** — installed, running, deterministic |
| V267 R4 `Sharpe(2k→2M)` curve | **STILL R4** — depth-1 cannot be walked |

## 2. What was authorised and what ran

The pre-registered Phase A was **stopped before download** on three grounds
(§3 of `V269.md`): 202 GB vs 17 GiB free, 12.6% join coverage, and depth-1
unfitness. The user authorised **Option B** — stream-and-aggregate, never retaining
raw ticks — which was executed in full.

## 3. Phase A results (measured)

| Metric | Value |
|---|---|
| Symbol-months landed | **71** |
| Symbol-days landed | **876 / 1,135 (77.2%)** |
| Symbol-days absent from the archive | **259 (22.8%)** |
| Minutes retained | **1,258,332** |
| Ticks aggregated | **4,501,157,160** |
| Bytes **transferred** | **50.23 GiB** |
| Bytes **retained** | **46.2 MiB** (1,113× reduction) |
| Peak retained disk during run | **< 800 MB** (3 in-flight archives) |

### 3.1 CORRECTION to pre-registration §2.2 — the archive is smaller than listed

`V269.md` §2.2 recorded the extent as "2023-05 → 2024-04, 12 months", read off the
monthly key listing. **Fetching proved that listing misleading**, and the correction
is load-bearing:

| Claim in §2.2 | Measured reality |
|---|---|
| coverage begins 2023-05 | first **daily** file is **2023-05-16** |
| coverage ends 2024-04 | last **daily** file is **2024-03-30** (uniform across all 13 symbols, HEAD-verified) |
| 2024-04 monthly exists ⇒ April is covered | the 2024-04 monthly is a **36 MB stub containing only 2024-04-01** (3,223,964 rows, verified by decompressing it) |

So the true usable extent is **2023-05-16 → 2024-04-01**, i.e. ~10.5 months, not 12.
Every one of the 259 absent symbol-days falls in **2024-03-31 … 2024-04-20**.

### 3.2 R4 partials — reported, not synthesised

| Gap | Symbol-days | Status |
|---|---|---|
| 2024-04-02 … 2024-04-20 | **233** | **Permanently unavailable.** No daily file, and the April monthly stub stops at 04-01. Not recoverable at any price. |
| 2024-03-31 and 2024-04-01 | **26** | **Exists only inside monthly archives.** Recovering them means pulling full monthly `2024-03` + `2024-04` for 13 symbols ≈ **17.5 GB transferred to gain 26 of 902 possible days (+2.9%)**. **Not fetched** — judged disproportionate, and flagged here rather than silently omitted. |

No missing minute was interpolated, and no book shape was assumed. Per-symbol
missing-day lists are in `data/v269_qc.json`.

A residual **98–108 minutes per symbol** are absent from otherwise-complete days
(e.g. BTCUSDT 74,782 retained vs 74,880 = 52×1440). These are genuine gaps in
Binance's own feed, carried through honestly rather than back-filled.

## 4. Gate results

| Gate | Result | Evidence |
|---|---|---|
| **G-S** storage | **PASS** | Re-checked before every archive and every write; never fired. Free disk rose 17→108 GiB mid-run (macOS purged snapshots under write pressure), so headroom was never contended. |
| **G-D** determinism | **PASS** | Two independent runs of `NEARUSDT 2023-10` produced identical SHA-256 `f3443bb2…`. `mtime=0`, rows sorted by minute, provenance from **retained** rows only. |
| **G-P** structure | **PASS** | `_assert_symbol_matches_partition`, strict minute monotonicity, no duplicate minutes, no cross-month spill, no minute spanning two days — all asserted, none raised. |
| **G-R** rowcount | **PASS, stronger than the bar** | The ±5% bar was replaced by an **exact tick-conservation assertion** (`retained == source_rows − rejected`) run on every symbol-month. All 71 passed; 4.50 B ticks conserved exactly. Rejected rows (crossed/zero/unparseable quotes) are counted, not dropped silently. |
| **G-C** coverage honesty | **PASS** | The 12.6% join and 0% `high_vol` caveat is embedded in *every* partition's `provenance.coverage_note` and reprinted by `v269_qc_report.py` alongside every spread figure. |

## 5. Data QC observation — NOT a verdict, NOT an impact model

Reported because it is the honest use of depth-1 data, and explicitly **not** scored:

| | bps |
|---|---|
| Pooled median **full** quoted spread | 0.960 |
| Pooled median **half** spread | **0.480** |
| V267 G2 slippage budget (`slippage_to_median_zero_bps`) | 1.6475 |

Per-symbol median half-spread ranges from **0.005 bps** (BTCUSDT — one $0.10 tick on
a ~$63k contract) to **1.365 bps** (NEARUSDT).

**The quoted spread at the touch sits inside V267's slippage budget.** That is a real
measurement, and it is also nearly the *least* interesting thing about capacity: a
touch spread describes the cost of trading the *first* contract, not the 200th. It
says nothing about $200k or $2M, which is exactly the quantity R4 needed.

**Binding caveats on every number above (V269 §5 G-C):**
- **12.6%** of the V255.C ledger (154/1,225 trades) is joinable at all.
- **0/340** `high_vol` trades are covered — the regime V255.B measured strongest is
  entirely absent from this window.
- **depth-1 only.** No ladder. `Sharpe(2k→2M)` is **not** derivable here.
- **MATIC/POL:** historical is `MATICUSDT`-only, forward is `POLUSDT`-only, and the
  two never overlap in either source — no continuous depth history for that lane.

Scoring is **V270's** job under its own pre-registration. V269 deliberately did not
run V267's scorer.

## 6. Phase B — forward L2 collector (SHIPPED)

| Property | Value |
|---|---|
| launchd label | `com.omega.depth_collector` (distinct from `com.omega.live_paper`) |
| PID / uptime at report | **76450**, stable ~2.5 h, `LastExitStatus = 0` |
| Cadence | 300 s, aligned to the wall-clock 5-minute grid |
| Universe | 13 symbols, **13/13 success on every cycle** |
| Ladder | `limit=100` — **100 bid + 100 ask levels verified present** |
| Rate-limit headroom | 65 weight/cycle vs 2,400/min cap (~2.7% of budget) |
| Footprint | ~1.3 KB/snapshot gz ⇒ **≈4.9 MB/day**, ≈1.8 GB/yr |
| Determinism | **PASS** — finalize run twice over a *copy* of the live spool gave byte-identical output for all 13 symbols |
| Durability | fsync'd NDJSON spool per snapshot; finalizes to `{YYYY-MM-DD}.json.gz` at UTC rollover; resumes stale spools on restart; torn final lines dropped, never guessed |

**MATIC→POL applied forward-only.** Verified 2026-08-17: `/fapi/v1/depth?symbol=MATICUSDT`
returns HTTP **200 with an empty book and no timestamp** — a delisted contract that
would have silently produced zero-depth rows. `POLUSDT` serves a full ladder. This is
V253's remap, and the failure mode it prevents was live.

**The V268 caveat applies and is stated up front:** this collector accrues **one day
per day**. It cannot back-fill the ledger. Any V270 analysis leaning on true L2 is
gated on calendar time — the same wall V268 hit.

## 7. Safety

- `com.omega.live_paper` untouched: **PID 13829** throughout, started **Aug 15
  17:37**, two days before this session. (The brief named PID 10329; that process had
  already been replaced by launchd's own `KeepAlive` before this session began —
  nothing here touched it, its plist, or its logs.)
- Nothing under `omega/nodes/` was read or written. All V269 code is in `scripts/`
  and imports no `omega` module.
- No order placed, no money moved. `data.binance.vision` and `/fapi/v1/depth` are
  unauthenticated public read-only endpoints; no key was needed or stored.
- Not pushed to origin — held for the user's decision alongside V267/V268.

## 8. What V270 inherits

1. `data/frozen_series/binance_bookticker/{SYMBOL}/{YYYY-MM}.json.gz` — 71 partitions,
   46.2 MiB, deterministic, per-minute quoted spread + top-of-book resting size.
2. `data/frozen_series/binance_depth_forward/{SYMBOL}/{YYYY-MM-DD}.json.gz` — true
   100-level L2, accruing from 2026-08-17.
3. `data/v269_qc.json` — per-symbol coverage, missing-day lists, spread summary.
4. Regenerate inputs with `python3 -m omega.nodes.funding_carry.v255c_scorer
   --basis-source frozen data/v269_ledger` then
   `python3 scripts/v269_fetch_bookticker.py --plan`.

**The open question V270 must pre-register against:** given depth-1 history covering
12.6% of the ledger with 0% `high_vol`, and true L2 that starts today, is *any*
honest capacity curve reachable — or is the correct answer that funding-carry's
capacity is permanently unmeasurable from free data, and the lane should be sized on
participation limits alone (V267's G1, which already passed)?
