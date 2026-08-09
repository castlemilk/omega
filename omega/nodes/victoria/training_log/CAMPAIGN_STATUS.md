# Victoria training campaign — status

Top-level phase tracker for the Victoria training loop. Per-version detail lives
in `V###.md`; the standing baseline table lives in `README.md`. This file records
which **phase** the campaign is in and the explicit criteria to advance.

---

## Current phase: **Phase 2 IN PROGRESS — live-paper harness build (acquisition)**

**Phase 1 = V241–V249 (the seam-free walk-forward + V247-ruler era).**
Closed 2026-07-13 by `V249.md`.

**Phase 2 = V250+ (live-paper accumulation).** In progress:
- **V250 (DONE, 2026-07-13):** live data-feed layer (`omega/live_paper/`) built +
  retrospective smoke (7/8 falsifiers PASS; F1 caught the MATIC→POL delisting).
  ADOPT, default OFF.
- **V251 (DONE, 2026-07-13) — the reconciliation gate PASSED.** Live feed
  reproduces the frozen backtest **bit-identically**: 32/32 windows OHLCV
  byte-identical, $0.00 PnL arm-Δ on all three sentinels (crisis/trend/recent),
  N=2 determinism $0, frozen-path guard clean. **V250 feed layer merged to main
  via `--no-ff`.** MATIC contamination controlled (matched variable, both arms;
  MATIC→POL forward-universe remap queued as P0 for V253, not a merge blocker).
  See `V251.md` + `V251_MATIC_IMPACT.md`.
- **V252 (DONE, 2026-07-13) — scheduler + crash-safe checkpoint ADOPTED (default
  OFF).** `omega/live_paper/{scheduler,checkpoint,runner}.py` +
  `scripts/live_paper_daemon.{py,sh}`. All 3 smoke tests PASS: Test A (3-day sim,
  2.0 s constant drift, no accumulation, 0 alerts, 3 MD5 checkpoints, 3 monotonic
  PnL lines); Test B (crash mid-cycle → restart **byte-identical** to clean run,
  equity exact, no dupes, no orphan tmp files, both crash-windows reconciled);
  **Test C reconciliation preservation** — all 3 sentinels reproduce V251
  **exactly** (crisis $1,149.76 / trend $4,679.67 / recent $771.98, $0.0000 Δ)
  through the full daemon path. Zero strategy code touched. `SCHEDULER_ENABLED=0`
  default; V253 flips ON. See `V252.md`.
- **V253 (NEXT):** 90-day headless soak + first quarterly freeze-and-label. Entry
  criterion (V252 tests pass) **met**. Before flipping `SCHEDULER_ENABLED=1`: apply
  the MATIC→POL forward-universe remap (P0) + provision the run host
  (`FRED_API_KEY`, GDELT + Binance egress) — full checklist in `V252.md` → Next
  steps.

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

   **Status (V262, 2026-07-25): the intraday freeze is DONE — data-side only.**
   1h OHLCV for all 13 universe names, 2020-01→2026-07, 665,824 bars, byte-identical
   ([`V262.md`](V262.md), [`V262_AUDIT_VERDICT.md`](V262_AUDIT_VERDICT.md)).
   **This does NOT by itself fire criterion 2.** The criterion requires a source that
   *changes regime structure*, and whether intraday regime is orthogonal to macro-day
   regime is an open empirical question — it is V262-2's pre-registered falsifier F4
   (REFUTE if per-name-hour vs macro-day regime correlation > 0.7). Criterion 2 fires
   **only if F4 passes.** Until then the freeze is a loaded gun, not a fired one.

   ⚠️ Criterion 1 is **not currently accruing**: as of 2026-07-25 no live-paper daemon
   is running and the configured checkpoint dir does not exist (V253 shipped with
   `SCHEDULER_ENABLED=0` pending host provisioning). Recent-N is static.

Until one fires: **the standing baseline is the answer, every V241–V261 flag stays
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
| **Phase 2** | **V250–V252** | **live-paper harness build** | **feed layer + reconciliation gate + scheduler/checkpoint DONE; V253 = 90-day soak** |
| Phase 2 (cont.) | V254–V261 | offline alt-data lanes | funding-carry ADOPTED (V255.C/D, full liquid book); Tracks C/D/E/F all REFUTED or blocked — offline alpha search closed |
| **Phase 2 (cont.)** | **V262** | **intraday data unlock** | **1h corpus frozen (665,824 bars, 14 MB, byte-identical). Audit+freeze only — no strategy code. V262-2 gated on falsifier F4** |
| Phase 2 (cont.) | V263–V265 | Kronos foundation-model (Track H) | CLOSED — zero-shot (no effect), fine-tuned (below bar), distributional (real but redundant with a free 24-bar rolling σ) |
| **Phase 2 (cont.)** | **V266** | **portfolio composition** | **CAVEATED 1/3 — the two validated lanes are genuinely INDEPENDENT (ρ = −0.015, ≈0 in every regime) but do NOT compose: naive 50/50 and risk-parity both refuted; only an 8/92 tangency mix clears 1.05× and only by a hairline. Independence premise behind the two-lane story CONFIRMED; naive combination CLOSED** |
