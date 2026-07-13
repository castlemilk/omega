# Victoria training campaign — status

Top-level phase tracker for the Victoria training loop. Per-version detail lives
in `V###.md`; the standing baseline table lives in `README.md`. This file records
which **phase** the campaign is in and the explicit criteria to advance.

---

## Current phase: **Phase 1 COMPLETE — paused pending resume criteria**

**Phase 1 = V241–V249 (the seam-free walk-forward + V247-ruler era).**
Closed 2026-07-13 by `V249.md`.

### What Phase 1 delivered

- **Standing baseline (the deliverable):** crisis **+$599** / trend **+$2,997** /
  recent **+$30** — positive in all three regimes, cushion in 2 of 3, honestly
  measured on the 32×90d seam-free walk-forward distribution, surviving the V247
  pooled-MDE ruler. Config = V227-skew + `universe_selective_enabled` (V240.A).
  Full table in `README.md`.
- **The V247 ruler:** acceptance bars re-derived from the variance table
  (pooled-gated 2·SE by coupling class + recent no-regression floor). Adjudication
  is now noise-floor-aware; V248 proved it by declining a +$494 near-miss at $0
  grid.
- **A complete refutation map** (`V249.md` §S4): composite-site, candidate
  selection, trend-IC, chop/β/info-feeds (entry-side, daily-bar — 5 bets closed),
  portfolio sizing + correlation (family sealed), exit adaptivity (global +
  regime-conditional, saturated), and ruler-repair itself. One adopt-track win:
  the selective universe (V240).

### Why Phase 1 is paused (not "failed", not "abandoned")

`V249.md`: recent-regime alpha is **calendar-bound**. The primary 90d grid already
tiles the full 2020→2026 span with zero gaps (26 independent slots, all used, only
**4 recent**). Doubling recent N — the only thing that would make the V246/V248/
V243-A near-misses adjudicable — is **calendar-infeasible** from frozen data. The
loop is out of the one resource it consumes: independent recent windows. This is a
resolution limit, **not** an absence of alpha. Continuing to draw mechanisms against
a sub-resolution objective is variance mining, not science.

---

## Resume criteria (either one fires the loop back up → V250+)

1. **Calendar / live-paper accumulation:** N independent **recent** windows ≥ 20.
   Reached by running a live **paper** trading harness (real market data →
   simulated PnL, **no broker, no funds** — per the standing guardrail) that
   manufactures ~1 new independent recent window per elapsed quarter. At N≥20 the
   V247 α manifest-widening becomes real, the recent 2·SE bar drops to adjudicating
   resolution, and the parked flags (V243-A blacklist ext, V246/V248 exit
   adaptivity) get re-run under the tightened bar.

2. **New data source that changes regime structure:** an intraday OHLCV freeze, an
   on-chain/options-surface feed, or any input that lifts the "entry-side saturated
   *at daily bars*" qualifier or re-labels the regime taxonomy to create
   adjudicable recent structure. This reopens the entry-side composite that the
   V236→V245 streak closed at daily granularity only.

Until one fires: **the standing baseline is the answer, every V241–V248 flag stays
OFF, and the loop waits on the calendar rather than mining variance.**

---

## Recommended next phase

**Phase 2 = live PAPER trading** (simulated PnL against real, forward, streaming
market data — explicitly NOT live-broker execution, NOT moving money). Rationale in
`V249.md` §S5: the passage of time is the only source of the independent recent
windows the frozen manifest cannot supply, and forward paper PnL is the first
genuinely out-of-sample measurement the campaign will have. Phase 2 is an
**acquisition** phase (accumulate windows / new feeds), feeding a future Phase 3
that re-runs the training loop once resume criterion 1 or 2 is met.

---

## Phase history

| Phase | Versions | Era | Outcome |
|---|---|---|---|
| Pre-loop | V148 and earlier | single-snapshot, high-water | superseded (wrap-seam contamination) |
| Loop v1 | V172–V221 | determinism arc + IC/ensemble | 6 FP-order channels closed; eval made hermetic |
| Loop v2 | V222–V234 | crisis mechanism hunt | closed OBE — crisis was sign-positive; window-selection artifact |
| Walk-forward | V235–V240 | distributional re-baseline | priors inverted; selective universe ADOPTED (baseline moved) |
| **Phase 1** | **V241–V249** | **V247-ruler adjudication** | **COMPLETE — standing baseline shipped; recent found calendar-bound** |
| Phase 2 (proposed) | V250+ | live-paper accumulation | pending — see resume criteria |
