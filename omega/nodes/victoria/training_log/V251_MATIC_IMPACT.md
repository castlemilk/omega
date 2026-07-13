# V251_MATIC_IMPACT — MATIC→POL contamination analysis (pre-harness)

**Date:** 2026-07-13 · **Author:** claude (Opus 4.8) · **Phase:** V251 Phase 2
**Status:** COMPLETE — done BEFORE building the reconciliation harness, per mandate.

> This is the go/no-go input the V250 handoff flagged as the **#1 V251 entry item**.
> It answers: *did the MATIC→POL delisting materially shape the standing baseline,
> and does that block the V250 feed-layer merge?*

## Method

Source: the V240-selective walk-forward confirm ledgers (the ledgers that PRODUCED
the standing baseline), 32 per-window trade CSVs at
`/Volumes/gamma-systems-2/omega-victoria-data/v240wf_snap_wf_*_universe_selective_*_r1_trades.csv`.
Regime tag read from the filename; per-trade `pnl` summed per regime, isolating
`MATICUSDT` rows. Per-regime totals reproduce the standing baseline **exactly**
(crisis mean/window $598.53 ≈ +$599; trend $2996.92 ≈ +$2,997; recent $29.64 ≈
+$30) — confirming these are the baseline-defining ledgers.

## Result — MATIC contribution per regime

| Regime | Baseline (mean/window) | MATIC total | MATIC mean/window | MATIC share | Falsifier (>$300/regime) |
|--------|-----------------------:|------------:|------------------:|------------:|--------------------------|
| crisis | +$598.53 (n=12) | **−$69.45** | −$5.79 | −0.97% | **not fired** (immaterial) |
| trend  | +$2996.92 (n=10) | **+$9,329.39** | **+$932.94** | +31.1% | **FIRED** (>$300, massively) |
| recent | +$29.64 (n=10) | **−$461.78** | −$46.18 | −155.8% of the tiny mean | fired at $300? no; but sign-relevant |

**The trend clause fires hard.** MATIC alone is +$933/window — 31% of the entire
trend baseline. Recent is a −$46/window drag (small in absolute $ but larger than
the +$30 baseline itself: ex-MATIC, recent would be +$76/window). Crisis is inert.

### Concentration — the trend number is one 2020 trade

The +$9,329 trend MATIC total is **not** broad-based:

| Window | Trend total | MATIC in window |
|--------|------------:|----------------:|
| 20201226 | +$17,366.58 | **+$10,337.43** (one long) |
| 20220619 | +$2,687.34 | +$975.78 |
| others (7 windows) | — | net **−$1,984** |

**Ex the single 20201226 monster trade, trend MATIC is −$1,008 across the other 9
windows.** So MATIC's positive trend contribution is *entirely* one 2020-bull
long. This is fragile, single-window alpha — exactly the kind of concentration the
walk-forward discipline exists to expose.

### Temporal note — every MATIC trade predates the delisting

The **last** MATIC trade in the ledgers is window `20230729`. All 40 MATIC trades
fall in windows ending ≤ 2023, i.e. **well before the 2024-09-10 delisting**. No
post-delisting window (20241205, 20250305, 20250603, 20250718, 20250901, 20251130,
20260228) traded MATIC. This matters for reconciliation feasibility (below).

## POL coherence check (live, this session)

Binance klines, live-fetched this session:

- `MATICUSDT`: last daily bar **2024-09-10** (delisted; historical klines still
  served up to that date).
- `POLUSDT`: first daily bar **2024-09-13**, continuous to 2026-07-13 (669 bars).

Clean 3-day handoff = the 1:1 MATIC→POL token swap (Polygon rebrand, Sept 2024).
POL is the **economic successor of the same underlying asset**, price-continuous
since the swap. **POL has zero pre-2024 history** — it cannot backfill any of the
2020–2023 windows where MATIC actually traded.

## Does this block the V250 merge? — TWO SEPARATE QUESTIONS

The falsifier clause conflates two things; they resolve differently:

### 1. Does MATIC contamination invalidate the V251 *reconciliation*? — **NO.**

The reconciliation replays the **same 32 frozen windows** through both arms
(frozen replay vs live-feed replay). MATIC appears in **both** arms identically:
every MATIC-trading window predates the delisting, and live Binance klines for
`MATICUSDT` **are still served historically up to 2024-09-10** (V250 smoke + this
session both confirm). So Arm A and Arm B both see MATIC bars for those windows —
MATIC is a *controlled, matched* variable in the A/B comparison, not a divergence
source. The reconciliation's internal validity is intact; **build it with MATIC as
the frozen baseline defines it.** (POL cannot substitute — no pre-2024 data.)

### 2. Is the *forward live-paper universe* structurally different? — **YES.**

Going forward (V253 quarterly accumulation), MATIC is **untradeable** — dead since
2024-09-10. A forward live-paper run on the V240-selective universe as-defined
would silently drop MATIC and run 9 names, losing the (fragile, concentrated) MATIC
exposure the historic trend baseline banked. This is the real, structural
live-vs-backtest gap the V250 smoke was built to catch. It does **not** block the
feed-layer merge (default OFF, trades nothing), but it **must** be resolved before
any live accumulation turns ON.

## Recommendation — REMAP MATIC→POL for the forward universe; keep MATIC for historic reconciliation

**Adopt POL remap (recommended over 9-name shrink):**

- **Forward live universe:** `MATICUSDT → POLUSDT`. POL is the 1:1 economic
  successor (same Polygon asset), price-continuous since 2024-09-13, live-fresh.
  One config line, no strategy change, keeps the 10-name selective universe
  economically faithful and forward-tradeable.
- **Historic reconciliation (V251) and any backtest replay of pre-2024 windows:**
  **keep MATICUSDT** — POL has no history there, and all MATIC-trading windows
  predate the delisting so live klines cover them. The reconciliation is a
  MATIC-vs-MATIC comparison and stays valid.

**Trade-offs vs the alternative (drop MATIC → 9 names):**

| Option | Forward tradeable | Historic reconciliation | Economic faithfulness | Cost |
|--------|-------------------|-------------------------|-----------------------|------|
| **POL remap (rec.)** | ✅ POL continuous | ✅ MATIC retained pre-2024 | ✅ 1:1 successor token | 1 config line; POL/MATIC price not bit-identical across swap (but 1:1 economically) |
| 9-name shrink | ✅ (no MATIC) | ✅ MATIC retained | ⚠️ permanently drops a name; changes universe (V235 = strategy change, needs re-validation as universe_9 vs universe_10) | re-validation grid |

The POL remap is cheaper, keeps the universe stable, and defers no re-validation
debt. The concentration finding (trend MATIC = one 2020 trade) means we are **not**
banking robust MATIC alpha either way — but the remap preserves the *name slot* for
the economically-continuous asset rather than silently shrinking the universe.

## Verdict for V251

- **Reconciliation proceeds unchanged** — MATIC is a matched variable across both
  arms; the harness builds with the frozen universe as-is.
- **MATIC contamination is CONTROLLED** for the reconciliation falsifier clause:
  the >$300 trend contribution is real but appears identically in both arms, so it
  cannot produce an eval-vs-live Δ. The clause's intent ("live-vs-backtest gap is
  real and structural") is satisfied by the forward-universe finding + the POL
  remap recommendation, which is documented here and does **not** block the
  feed-layer merge (default OFF).
- **Forward-universe action (POL remap)** is a P0 pre-requisite for V253 live
  accumulation, NOT for the V250 feed-layer merge. Recorded as the standing
  forward-universe decision; implement as a config edit under a later version when
  live accumulation is turned on.
