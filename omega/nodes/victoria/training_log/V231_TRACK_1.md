# V231 — Track 1: Snapshot Inventory + Sourcing Plan

**Scope:** Read-only audit of `data/snapshots/*.json` + sourcing plan for new
historical windows. **No strategy code changed.**

**Date:** 2026-06-22 · **Author:** Track 1 · **Time-boxed:** ~15 min (complete)

---

## 1. The 13-symbol universe (authoritative)

Source of truth is `scripts/freeze_snapshot.py:54` (`ALL_SYMBOLS`), NOT
`projects/victoria.yaml` (which lists only 10 and is stale — missing
NEAR/SUI/ARB, and the YAML `market_feed` is not what the freeze recipe uses).

```
BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT ADAUSDT DOTUSDT
AVAXUSDT LINKUSDT MATICUSDT NEARUSDT SUIUSDT ARBUSDT
```

Per-symbol **Binance daily first-bar** (probed live via ccxt, the exact path the
recipe uses):

| Symbol | First Binance daily bar | Notes |
|--------|------------------------|-------|
| BTC, ETH, BNB, XRP, ADA, LINK | pre-2019 | always available |
| MATIC | 2019-04-26 | **DELISTED → POL; last MATICUSDT bar ~Sep 2024; ZERO bars in 2025** |
| DOGE | 2019-07-05 | (not in universe but probed) |
| SOL | 2020-08-11 | no pre-2020 data |
| DOT | 2020-08-18 | no pre-2020 data |
| AVAX | 2020-09-22 | no pre-2020 data |
| NEAR | 2020-10-14 | no pre-2020 data |
| ARB | 2023-03-23 | no pre-2023 data |
| SUI | 2023-05-03 | no pre-2023 data |
| POL | 2024-09 (migration); full 2025 coverage | MATIC successor ticker |

---

## 2. Inventory of existing snapshots

All four are **true daily OHLCV time series** (close/open/high/low/volume/timestamps
arrays, length = days in window), NOT static scalars. Schema is identical across
all four. Macro block (`_macro`) carries only **current scalars**
(`funding_rates`, `fear_greed`, `btc_dominance`) — these are snapshot-time
constants, not historical series.

| File | id | date range | days/sym | symbols | gate |
|------|----|-----------|---------|---------|------|
| `snap_20260414.json` | snap_20260414 | 2024-06-13 → 2026-04-14* | 90 | **13/13** | recent |
| `snap_crisis_2020q1.json` | snap_20200101_20200430 | 2020-01-01 → 2020-04-30 | 121 | **7/13** (BTC ETH BNB XRP ADA LINK MATIC) | crisis |
| `snap_crisis_2022h1.json` | snap_crisis_2022h1 | 2022-01-01 → 2022-06-30 | 181 | **11/13** (missing SUI, ARB) | crisis |
| `snap_trending_2023q4.json` | snap_trending_2023q4 | 2023-10-01 → 2024-03-31 | 183 | **13/13** | trend |

\* `snap_20260414` `_date_range` shows 2024-06-13→2026-04-14 but `_lookback:90`
and each symbol has exactly **90 bars** — the range field is mislabeled
(min/max-ts spread vs the real 90-bar tail). Treat it as a ~90-day recent window
ending 2026-04-14. **Action item for whoever runs the build:** confirm by
inspecting timestamps; this is a metadata quirk, not a data problem.

### Schema (per `freeze_snapshot.py`)
```json
{
  "_snapshot_id": "snap_...", "_created_at": <unix>,
  "_date_range": ["YYYY-MM-DD","YYYY-MM-DD"], "_symbols": [...],
  "_lookback": 90,
  "BTCUSDT": {"close":[...],"open":[...],"high":[...],"low":[...],
              "volume":[...],"timestamps":[...],"meta":{...}},
  ... (one block per symbol) ...,
  "_macro": {"funding_rates":{...},"fear_greed":N,"btc_dominance":F}
}
```

---

## 3. V215 freeze recipe (how snapshots are built)

`scripts/freeze_snapshot.py` is the recipe. Two modes:

- **Recent mode** (default): `fetch_ohlcv()` → `DataIngestionNode` (live providers,
  Binance→CoinGecko→Bybit failover), last `--lookback` days.
- **Historical mode**: `--start-date/--end-date` → `fetch_ohlcv_historical()` uses
  **ccxt Binance public API directly** (`timeframe="1d"`), filters bars to the
  exact `[start,end]` window. This is the path used for all the crisis/trend
  snapshots.

Sources: **Binance daily OHLCV via ccxt** (primary, all historical builds).
Yahoo/Glassnode are mentioned in the V215 lineage but the committed recipe code
fetches OHLCV from Binance only; `_macro` is best-effort live scalars (OKX funding,
fear/greed, CoinGecko dominance) and is NOT historically backfilled.

Symbols missing from a window are silently dropped (logged as "no bars in range"),
which is exactly how `snap_crisis_2020q1` ended up 7/13 — **this is the V218.E
universe-shrink trap**: a snapshot with fewer symbols changes the cross-sectional
demean basket and confounds the result.

---

## 4. Coverage probe results (live ccxt, 13-symbol)

| Candidate window | range | all-13? | missing |
|------------------|-------|---------|---------|
| **Crisis 2024-Aug (yen-carry)** | 2024-07-15 → 2024-09-15 | **✅ 13/13** | — |
| Crisis 2022-Nov (FTX) | 2022-10-01 → 2022-12-31 | 11/13 | SUI, ARB |
| Crisis 2021-May (China ban) | 2021-04-15 → 2021-07-15 | 11/13 | SUI, ARB |
| **Trend 2024-Q1 (post-halving)** | 2024-01-01 → 2024-03-31 | **✅ 13/13** | — |
| Trend 2020-Q4 | 2020-10-01 → 2020-12-31 | 11/13 | SUI, ARB |
| Recent 2025-06→07 | 2025-06-01 → 2025-07-31 | 12/13 | MATIC (→POL) |
| Recent 2025-08→09 | 2025-08-01 → 2025-09-30 | 12/13 | MATIC (→POL) |
| Recent 2025-10→11 | 2025-10-01 → 2025-11-30 | 12/13 | MATIC (→POL) |

**Critical data gap:** MATICUSDT has **zero** Binance bars in 2025 (token migrated
to POL Sep 2024). Any 2025+ recent window is intrinsically ≤12/13 on the frozen
universe unless POLUSDT is substituted (POL covers 2025-01-01 → 2026-02-04 fully).

---

## 5. Ranked add-3 list (≥1 per gate, all-13 prioritized)

### #1 — Crisis: **2024-Aug yen-carry unwind** (BEST — all 13)
The only crisis candidate with full 13/13 coverage. Aug 5 2024 was a sharp global
risk-off (BTC −15%+ intraday). Gives crisis gate its 3rd window with NO universe
shrink.

```bash
python3 scripts/freeze_snapshot.py \
  --start-date 2024-07-15 --end-date 2024-09-15 \
  --id snap_crisis_2024aug --out data/snapshots/snap_crisis_2024aug.json
```

### #2 — Trend: **2024-Q1 post-halving rally** (BEST — all 13)
Full 13/13. Clean uptrend, distinct from the existing 2023-Q4 (which already ends
2024-03-31 — pick a non-overlapping or extend differently if overlap is a concern;
2024-Q1 overlaps the tail of 2023Q4, so consider widening to capture the full
Jan–May 2024 run, still 13/13).

```bash
python3 scripts/freeze_snapshot.py \
  --start-date 2024-01-01 --end-date 2024-03-31 \
  --id snap_trending_2024q1 --out data/snapshots/snap_trending_2024q1.json
```

### #3 — Recent: **3 sequential 60-day 2025 windows** (12/13, MATIC unavoidable)
"Recent" is rolling. Propose three non-overlapping 60-day windows. All are 12/13
because MATIC is dead on Binance in 2025 — this is a known, universe-wide gap
(NOT the same as the V218.E selective shrink; the gap is identical across all
three windows so cross-window comparison stays apples-to-apples). If a true 13/13
recent set is required, substitute POLUSDT for MATICUSDT (POL = MATIC successor).

```bash
# Recent A
python3 scripts/freeze_snapshot.py --start-date 2025-06-01 --end-date 2025-07-31 \
  --id snap_recent_2025_06 --out data/snapshots/snap_recent_2025_06.json
# Recent B
python3 scripts/freeze_snapshot.py --start-date 2025-08-01 --end-date 2025-09-30 \
  --id snap_recent_2025_08 --out data/snapshots/snap_recent_2025_08.json
# Recent C
python3 scripts/freeze_snapshot.py --start-date 2025-10-01 --end-date 2025-11-30 \
  --id snap_recent_2025_10 --out data/snapshots/snap_recent_2025_10.json
```

**To get 13/13 recent** (optional, requires `--symbols` override with POL):
```bash
python3 scripts/freeze_snapshot.py --start-date 2025-06-01 --end-date 2025-07-31 \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,DOTUSDT,AVAXUSDT,LINKUSDT,POLUSDT,NEARUSDT,SUIUSDT,ARBUSDT \
  --id snap_recent_2025_06_pol --out data/snapshots/snap_recent_2025_06_pol.json
```
⚠️ POL substitution makes the recent universe non-identical to the crisis/trend
snapshots (which use MATIC). If cross-gate basket identity matters, keep MATIC and
accept 12/13, OR re-cut MATIC→POL across ALL new snapshots. **This is a genuine
design fork — flag to the V231 lead.**

---

## 6. Post-V231 gate tally (if all 3 built)

| Gate | Windows after add-3 | Target ≥3 |
|------|--------------------|-----------|
| Crisis | 2020-Q1 (7/13), 2022-H1 (11/13), **2024-Aug (13/13)** | ✅ 3 |
| Trend  | 2023-Q4 (13/13), **2024-Q1 (13/13)** | ⚠️ 2 — need 1 more |
| Recent | 2026-04-14 (13/13), **2025-06/08/10 (12/13 ×3)** | ✅ 4 |

**Trend is short by 1** (the brief asked for 2+ new; only one clean all-13 trend
window exists outside 2023-Q4). Options for trend window #3:
- **2020-Q4** (11/13, missing SUI/ARB) — strongest historical bull but shrinks universe.
- A **2025 bull window** if one exists (12/13, MATIC gap) — e.g. a Q1-2025 or
  late-2025 uptrend; coverage not yet probed (out of time-box).

**Recommendation (UPDATED after probe):** 2025 trend windows turned out NOT to be
uptrends — probed BTC return was **2025-Q1 −12.7%** and **2025-Q4 (Oct–mid-Dec)
−27.1%**, both down-markets (would mislabel as crisis, not trend). So no clean
2025 *bull* window exists for the trend gate. Therefore the trend gate's 3rd
window should be **2020-Q4** (11/13, missing SUI/ARB) — the strongest available
historical bull — accepting the universe shrink, OR widen the **2024 post-halving**
build (e.g. 2024-01-01 → 2024-05-31, still 13/13) and treat 2024-Q1 + 2024-Apr/May
as two distinct trend cuts. **Widening 2024 is the cleaner play** (stays 13/13,
avoids any shrink). Build for the 2020-Q4 fallback:

```bash
python3 scripts/freeze_snapshot.py \
  --start-date 2020-10-01 --end-date 2020-12-31 \
  --id snap_trending_2020q4 --out data/snapshots/snap_trending_2020q4.json
```

---

## 7. Incomplete / follow-ups (time-box)

1. ~~Did NOT probe 2025 trend windows~~ **DONE:** 2025-Q1 (−12.7%) and 2025-Q4
   (−27.1%) are both down-markets, not trend windows. Trend gate's 3rd slot →
   widen 2024 (13/13) or fall back to 2020-Q4 (11/13). See Section 6.
2. **`snap_20260414` `_date_range` metadata** looks mislabeled (90 bars but
   ~2yr range string) — verify timestamps before relying on the range field.
3. **MATIC→POL design fork** (Section 5 #3) needs a decision from the V231 lead:
   accept 12/13 recent, or re-cut all snapshots on POL.
4. The recipe does NOT backfill historical macro (`_macro` = live scalars at
   build time). If any signal consumes historical funding/fear-greed, those will
   be snapshot-build-time constants, not period-accurate — confirm no signal
   depends on period-accurate macro before trusting crisis-window results.
