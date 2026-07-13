# V249 Phase 0 — Manifest / data audit

**Date:** 2026-07-13 · **Author:** claude (Opus 4.8)
**Mandate:** V249 brief Phase 0 — before proposing any manifest widening,
quantify how many *independent* windows (especially **recent**) can be
harvested from already-frozen data. The decisive number the brief asks for
first: **"how many new windows can we harvest for free."**

**Reproduction:** all counts below are mechanical from
`data/walk_forward_manifest.json` + the freeze recipe in
`scripts/walk_forward_freeze.py` (WINDOW_DAYS=90, STRIDE_DAYS=90, span
2020-01-01 → 2026-06-30). Re-derivable with the inline python in the V249
session log.

---

## Headline finding (answer to the decisive question)

**Independent recent windows harvestable for free: 0.**
**Independent windows of ANY regime harvestable for free: 0.**

The primary 90d/90d grid **already tiles the entire span with zero gaps**:

- Theoretical non-overlapping 90d windows in 2020-01-01 → 2026-06-30: **26**
- Primary (non-offset) windows already in the manifest: **26**
- ⇒ every independent 90d calendar slot in the span is already used.

Of those 26 independent slots, the mechanical regime classifier assigns only
**4 to recent**. The manifest's nominal "recent n=10" is **4 independent +
6 overlapping** offset-45d supplements (each overlaps two primary neighbors
by 45 days — literal data reuse, not new information).

**Doubling recent N from 10 → 20 (the V249 brief's premise) is
calendar-infeasible from existing frozen data.** There are only 26
independent 90d slots in the whole span; 22 of them are crisis/trend. You
cannot manufacture 16 more independent recent windows that the calendar does
not contain.

---

## 1. What exists on disk vs what's manifested

### 1a. Ledger-relevant frozen data enumerated

| Store | Contents | Coverage | Cadence | OHLCV? |
|---|---|---|---|---|
| `data/snapshots/walk_forward/snap_wf_*.json` (32 files) | per-window OHLCV (the price data the grid **replays**) | 2020-01-01 → 2026-05-29, in 90d windows | daily bars, 91 bars/window | **YES** — this is the only ledger OHLCV |
| `data/frozen_series/` (49 files, `MANIFEST.json`) | **auxiliary signal feeds only**: funding, OI, taker-ratio, dvol, fng, FRED (VIX/DGS10/DGS2/DTWEXBGS), gdelt tone/vol, stablecoin supply | series-dependent, ~2020→2026-07 | daily | **NO** |
| `data/frozen_llm_cache/` | reasoning-layer cache (V240.D) | n/a — OFF since V241 | n/a | NO |
| `macro_cache.db` | per-window `_macro` scalars (copied from `snap_crisis_2024aug`) | static block | n/a | NO |
| `/Volumes/gamma-systems-2/omega-victoria-data/` | **audit output only** (v231–v246 grid dirs, determinism cells, `frozen_series/` mirror, `tmp/`) | n/a | n/a | **NO new OHLCV** |

**Key correction to a natural assumption:** `frozen_series/` does **not**
contain price/OHLCV series. It is the V238 auxiliary-feed store (funding, OI,
macro, gdelt). The only price data on disk is the 32 committed window
snapshots. So "slice new windows from the frozen daily series" is **not**
available for OHLCV — new windows require the freeze recipe's OHLCV fetch.

### 1b. Currently manifested

32 windows = **26 primary** (90d/90d contiguous tiling) + **6 offset-45d
recent supplements**. Regime counts: crisis 12 / trend 10 / recent 10.

| | primary (independent) | offset (overlapping) | total |
|---|---:|---:|---:|
| crisis | 12 | 0 | 12 |
| trend | 10 | 0 | 10 |
| recent | **4** | **6** | 10 |
| **all** | **26** | **6** | **32** |

Recent primary (independent): `20210922, 20230316, 20250305, 20260228`.
Recent offset (overlap ±45d): `20200813, 20230130, 20230430, 20230729,
20240723, 20250718`.

### 1c. Delta — additional windows from existing frozen data, no acquisition

- **Independent (non-overlapping 90d), any regime: 0.** Span fully tiled.
- **Independent recent: 0.** All 4 recent-labeled independent slots already in.
- **Overlapping offset-45d, non-recent: 20** (the V235 supplement pass
  labeled all 26 offset windows and kept only the 6 recent). These are
  harvestable — but they **overlap** primary neighbors by 45d, so nominal
  n≠effective n, and they add **0** to recent (recent offsets already in).
- **Denser offsets (30d/15d) for more recent:** could raise nominal recent
  to ~13–15 (V247 Phase 1 estimate) but every added window overlaps ≥67%;
  effective independent recent barely moves off 4.
- **Shorter windows (45–60d):** INFEASIBLE — `ReplayIngestionNode` needs a
  30-bar warmup and the grid caps `--cycles = min_bars − 31`; a 45d window
  leaves ~15 honest cycles (below hold length → trades never close), a 60d
  window halves per-window trade count and breaks comparability with every
  committed 90d result.
- **Span extension beyond 2026-06-30:** yields **0** complete windows. Last
  window ends 2026-05-29; the next 90d slot (2026-05-29 → 2026-08-27) needs
  data through late August — today is 2026-07-13, it does not exist yet.

### 1d. OHLCV re-fetch feasibility (tested, not assumed)

The freeze recipe fetches OHLCV via `ccxt.binance.fetch_ohlcv` (Binance REST).
Project lore says Binance is US-geo-blocked (451/403). **Empirically probed
this session: `BTC/USDT` 1d klines fetched OK, 5 rows returned.** So the
geo-block is **not** active in this environment — re-fetching the 20 offset
windows is feasible (minutes of fetch). This removes the hard
infeasibility-STOP branch, but does **not** change the calendar-boundedness
of recent N.

---

## 2. Classification schema per regime (audited)

**Algorithmic, zero discretion** (`walk_forward_freeze.py:regime_label`):

```
crisis : max_dd >= 0.30  OR  basket_ret <= -0.15   (drawdown-first)
trend  : basket_ret >= +0.20  AND not crisis
recent : otherwise
high_vol tag (independent): ann_vol >= 0.90
```

Computed from the equal-weight basket of available symbols' daily closes over
each window (fsum-fenced). **Applied to any extra date range this classifier
is fully mechanical** — but there is no extra independent date range to apply
it to (§1c). Applying it to *overlapping* offset stretches is what produced
the 6 existing recent supplements; a denser offset grid would re-apply it to
progressively more-overlapping stretches with diminishing independent yield.

**Why recent is structurally scarce:** at 90d granularity the 30% max-drawdown
crisis bar is hit often (crypto's 90d windows routinely draw down ≥30% even in
flat markets), so "recent/chop" only survives in the 4 calmest independent
90d stretches of the whole 6.5-year span. This is a property of the
regime definition × window length × asset volatility, not a labeling bug.

---

## 3. Coverage gaps (excluded periods)

No calendar gaps in the OHLCV tiling — the 26 primary windows are contiguous.
Per-window **symbol** coverage gaps exist and are already recorded in the
manifest `dropped_symbols` (listings/delistings: DOT 2020-08, ARB 2023-03,
SUI 2023-03, MATIC→POL 2024-09). These reduce per-window universe size (7–13
names) but do not create harvestable new windows.

---

## 4. What this means for the V249 bet (feeds Phase 1)

The brief's goal — "double recent N so V246-exit / V248-composition /
V243-A-blacklist near-misses become adjudicable at real resolution" —
**cannot be met from existing frozen data.** Recent independent N is
calendar-locked at 4 (nominal 10 with overlap); the span contains no more
independent recent stretches to harvest, at any cost short of *waiting for
future recent-regime months to occur*.

The **only** executable widening from existing data is V247 Phase 1's
α sub-path 1: refetch the 20 non-recent offset windows to grow **pooled**
n 32→52 (cluster-robust, since they overlap). This sharpens the **pooled**
instrument — the one β actually gates on — from MDE ~$875 → ~$750, but:

- leaves **recent** N and recent MDE ($1,043) **unchanged**;
- flips **no** near-miss to ADOPT (V248 composition pooled +$494 stays below
  even the tightened pooled bar);
- permanently raises every future grid's cost ~60% (52 vs 32 OFF-arm cells).

Whether that modest pooled sharpening is worth the permanent cost — versus
STOPPING and declaring recent calendar-bound (V250 = acquire future windows
over time) — is the Phase 1 decision fork, surfaced to the user before any
compute is sunk.
