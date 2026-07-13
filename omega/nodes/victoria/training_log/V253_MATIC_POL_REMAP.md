# V253_MATIC_POL_REMAP — forward live universe MATIC→POL swap

**Date:** 2026-07-13 · **Author:** claude (Opus 4.8) · **Phase:** V253 pre-registration (Deliverable 2)
**Status:** COMPLETE — shipped, byte-identity verified pre **and** post edit.

> Implements the standing forward-universe decision recorded in
> [`V251_MATIC_IMPACT.md`](V251_MATIC_IMPACT.md): remap `MATICUSDT → POLUSDT` for
> the **forward live** universe while keeping `MATICUSDT` for historic backtest
> replay. This unblocks V253 live accumulation (a forward run on the as-defined
> universe would silently drop the dead MATIC name and trade 9, not 10).

## The bet in one line

`MATICUSDT` is delisted (last Binance daily bar **2024-09-10**); `POLUSDT` is its
1:1 economic successor (first bar **2024-09-13**, continuous to today). Swap the
name in the **live-fetch** paths only; the frozen backtest is untouched by
construction, so the standing baseline (crisis +$599 / trend +$2,997 / recent +$30)
is preserved bit-for-bit.

## Why this is a live-only edit that cannot perturb the backtest

The trading universe is **not** defined in `strategy.py`. It lives in two places,
both of which feed only the **live** fetch path:

- `data_ingestion.py:_BASE_PAIRS` — the master live fetch list.
- `data_providers.py` — three provider id maps (CoinGecko / Yahoo / CryptoCompare).

The frozen backtest **never reads either of these**. In backtest mode
(`run_training.py:984-990`), `victoria._ingestion` is *replaced* by
`ReplayIngestionNode`, whose universe is derived purely from **each snapshot's own
keys** (`providers/replay.py:103` — `[k for k in snapshot if not k.startswith("_")
and isinstance(snapshot[k], dict)]`). So the frozen window's traded set is whatever
the freeze baked into that snapshot, independent of the live `_BASE_PAIRS` list.

This is exactly the split V251_MATIC_IMPACT recommended ("remap forward; keep MATIC
for historic reconciliation"). It falls out of the existing architecture — **no
runtime flag is required.**

## Answer to the pre-registration question: "does any sentinel window extend past 2024-09-10?"

**Yes — the `recent` sentinel does — but it resolves cleanly, not into the "harder" branch.**

| Sentinel | `_date_range` | vs 2024-09-10 (MATIC last day) | MATIC in frozen snapshot? |
|----------|---------------|--------------------------------|---------------------------|
| crisis `snap_wf_20240310` | 2024-03-10 → 2024-06-08 | **before** | present & traded (retained) |
| trend `snap_wf_20230912`  | 2023-09-12 → 2023-12-11 | **before** | present & traded (retained) |
| recent `snap_wf_20250305` | 2025-03-05 → 2025-06-03 | **after**  | **already dropped by the freeze** (absent) |

The naive "assert all windows end ≤ 2024-09-10" heuristic from the task brief would
have flagged `recent` and forced the Option-A/Option-B fork. But the fork is moot:

- The crisis/trend windows are pre-delisting, so their freeze baked in MATIC bars.
  The remap doesn't touch the replay path → those bars stay → identical trades.
- The recent window is post-delisting, and the freeze process **already dropped
  MATIC** from it (`_symbols` has no MATICUSDT; live Binance served no MATIC klines
  in 2025). POL is also absent (never fetched at that freeze). So MATIC contributes
  $0 there before and after the edit.

Corroborating fact from V251_MATIC_IMPACT: the **last** MATIC trade across all 32
confirm ledgers is window `20230729` — every MATIC trade predates the delisting.
No post-delisting window ever traded MATIC.

## Path recommendation (the task asked for one)

**Neither Option A (re-freeze) nor Option B (runtime live-only flag) is needed.**

- **Option A (re-freeze post-2024-09-10 windows with POL substituted): NOT executed,
  and not necessary.** POL has zero pre-2024 history, so it cannot backfill the
  historic windows anyway; and the post-delisting windows correctly have MATIC
  dropped. Re-freezing would only matter if we wanted POL *in* a historic backtest
  window, which we do not (those windows are MATIC-era or MATIC-absent by fact).
- **Option B (runtime flag to override live-only): unnecessary** — the code is
  *already* architecturally split (live universe = `_BASE_PAIRS`; frozen universe =
  snapshot keys). A flag would add coupling for a separation that already exists.
- **Adopted path: plain name swap in the live-fetch paths.** Forward live freezes
  (V253 quarterly accumulation) will naturally bake POL into each new snapshot at
  freeze time — self-consistent going forward, since live now fetches POL.

## Files changed (7 sites, 4 files — live-fetch paths only)

| File | Site | Edit |
|------|------|------|
| `omega/live_paper/config.py` | `_UNIVERSE_ALL` (~L46) | `"MATICUSDT"` → `"POLUSDT"` + V253 note — **the live-paper daemon fetch universe** (`LivePaperConfig.universe = SELECTIVE_UNIVERSE`); this is the one that actually makes the forward daemon fetch POL |
| `data_ingestion.py` | header `Pairs:` comment (~L14) | MATICUSDT → POLUSDT |
| `data_ingestion.py` | `_BASE_PAIRS` (~L64) | `"MATICUSDT"` → `"POLUSDT"` + V253 note |
| `data_providers.py` | CoinGecko id map (~L67) | `"matic-network"` → `"POLUSDT": "polygon-ecosystem-token"` |
| `data_providers.py` | Yahoo id map (~L948) | `"MATIC-USD"` → `"POLUSDT": "POL-USD"` |
| `data_providers.py` | CryptoCompare id map (~L997) | `"MATIC"` → `"POLUSDT": "POL"` |
| `strategy.py` | `_TRADING_BLACKLIST` roster (~L207) | `"MATICUSDT"` → `"POLUSDT"` + V253 note |

> **`live_paper/config._UNIVERSE_ALL` is the load-bearing site.** `data_ingestion._BASE_PAIRS`
> feeds the legacy `DataIngestionNode` fetch path; the V250+ live-paper daemon fetches
> its universe from `LivePaperConfig.universe` (derived from `SELECTIVE_UNIVERSE` →
> `_UNIVERSE_ALL`). It is orthogonal to the reconcile/backtest path (which never
> instantiates `LivePaperConfig`), so it too is byte-identical for the frozen windows.

The `strategy.py` swap is functionally inert for both paths (a name absent from
`_TRADING_BLACKLIST` is tradeable via `_universe_blocked`'s first check, so MATIC's
tradeable status is unchanged; the sole other consumer, `signal_generation.py:527`,
filters a hardcoded `[ETH,NEAR,ARB,ADA,BTC]` ws list that never contained MATIC and
is gated OFF in frozen backtest). It is kept only to keep the universe roster
documentation coherent. Historical MATIC mentions in `strategy.py` comments (L33,
L122, L179) are left as-is — they record why the name was originally added.

> ⚠️ Provider ids for POL (`polygon-ecosystem-token` / `POL-USD` / `POL`) are the
> well-established mappings but are validated for real only when live fetch runs
> (frozen-cache mode blocks all egress). The V253 provisioning checklist includes a
> live one-cycle smoke that exercises these lookups before `SCHEDULER_ENABLED=1`.

## Evidence — backtest byte-identity (the hard guardrail)

`scripts/v252_reconcile_smoke.py` (the V251/V252 reconciliation harness) run against
the three per-regime sentinels, **before and after** the remap edit:

| Window | Regime | V251 recorded | daemon-path PnL | Δ | n_closed |
|--------|--------|--------------:|----------------:|----:|---------:|
| snap_wf_20240310 | crisis | $1,149.76 | $1,149.76 | **$0.0000** | 9 |
| snap_wf_20230912 | trend  | $4,679.67 | $4,679.67 | **$0.0000** | 6 |
| snap_wf_20250305 | recent | $771.98   | $771.98   | **$0.0000** | 13 |

**Verdict: PASS** — identical PnL and identical trade counts pre- and post-edit on
all three windows. The remap does not move a single frozen trade. Guardrail
satisfied; the standing baseline is preserved. Re-run a **third** time after the
`live_paper/config._UNIVERSE_ALL` site was added — still $0.0000 Δ x3, confirming
the live-paper fetch-universe edit is also orthogonal to the frozen path.
