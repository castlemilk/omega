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
- **V253 (RUNNING since 2026-09-08):** the 90-day headless soak is LIVE.
  `SCHEDULER_ENABLED=1`, `--mode forward`, tick 02:55 UTC, supervised by launchd
  (`com.omega.live_paper`). First cycle 2026-09-08 opened 3 fills (ARBUSDT,
  NEARUSDT, POLUSDT) at equity 100,000. A restart the same day resumed from
  checkpoint with all 3 positions intact — V252's crash-safe resume proven in the
  real deployment, not just its test.

  **This entry read "(NEXT)" from 2026-07-13 to 2026-09-09** while V254–V306
  happened and the soak sat unstarted. A phase tracker whose only job is
  answering "where are we" reported a state that had stopped being true, and the
  sole symptom was that anyone reading it believed it. Corrected here; the ledger
  below exists so the resume gate is a number to read rather than one to
  re-derive.

  Provisioning took four fixes, each of which would have produced a soak that
  looked healthy and was not:
  - **gamma-systems-2 is gone.** The wrapper defaulted `OMEGA_AUDIT_OUTPUT_DIR`
    to it and refused to start. Now local (`~/omega-victoria-data`); the
    runbook's own sizing is ~0.5–2 GB over 90 days against 638 GB free, so the
    100 GB floor's ENOSPC purpose still holds.
  - **The wrapper exec'd Homebrew `python3`**, which has numpy, psycopg and yaml
    all missing. The daemon would have died on import and launchd's KeepAlive
    would have crash-looped it forever — supervised, and never running a cycle.
    Now `./.venv/bin/python`.
  - **It sourced `harness/.env`, a path that has never existed in this repo.**
    Guarded by `[ -f ]`, so it was a silent no-op: a key added to `.env` — the
    obvious place — was read by nothing, and the only symptom was FRED 400s in
    daemon.err. Now sources `.env` first, and logs a WARNING naming the exact
    consequence when the key is absent.
  - **The soak would have rewritten the frozen substrate every cycle.** One
    forward cycle moved `data/macro_cache.db` from 397b9438… to a0bed83b…, a real
    content change. That file's md5 is asserted by `.cache_manifest.json` and
    every backtest reads it, so 90 cycles would have quietly un-frozen the
    baseline while V251's reconciliation went on claiming bit-identity against
    it. `tests/conftest.py` already set the three override vars for exactly this
    reason — it covers pytest, and a launchd daemon is outside it entirely.

### Independent-window ledger (the resume gate)

The V### loop resumes at **20** independent recent windows (see Resume criteria
below). Each elapsed quarter of soak yields ~1. Update this line as they accrue:

| | count | as of |
|---|---:|---|
| independent recent windows banked | **1** | 2026-09-08 |
| required to resume the V### loop | 20 | — |

Window 1 = the soak's first completed cycle. The count is deliberately here and
not derived on demand: V249's constraint is the whole reason the loop is paused,
and a paused loop with no visible counter is how a pause becomes a stall.

### V254–V308 — what happened while the tracker said "V253 NEXT"

Summarised rather than enumerated; each has its own entry. Grouped by what they
were actually doing, because the tracker's job is orientation, not an index.

- **V254–V259 — alt-data scoping, all four tracks PAUSED on data, none refuted.**
  Track C on-chain and Track D Polymarket both hit the same wall: the thesis is
  untested because the data does not exist in frozen form. `V259.md` is the
  clearest statement of the shape — a data blocker recorded as a data blocker,
  not dressed up as a negative result.
- **V260–V286 — the campaign retrospective (V241→V260) and the intraday freeze.**
  1h OHLCV for all 13 names, 2020-01→2026-07, 665,824 bars, byte-identical
  (`V262`). It does NOT by itself fire resume criterion 2: that needs a source
  that changes regime STRUCTURE, and whether intraday regime is orthogonal to
  macro-day regime is exactly the open question.
- **V286–V304 — the ASX line, nine versions, CLOSED with a verdict.**
  `V304_ASX_VERDICT.md`: least-shorted ASX names outperform (Q1−Q5 +0.298%/wk,
  t=+2.85 over 590 weeks, replicated OOS), concentrated in the least-liquid
  third — and a long-only book drawn from that tercile loses money at every
  horizon but quarterly. The premium concentrates exactly where impact costs are
  highest. **That is the mechanism, not a disappointment:** a neglect premium
  persists because it cannot be arbitraged, and it cannot be arbitraged for the
  same reason it is measurable. Not a strategy. The line also upstreamed six data
  defects to shorted.com.au and corrected four of its own methodology errors.
- **V305 — a Victoria defect sweep proposed, then WITHDRAWN on evidence.** The
  inference was that Victoria (~300 versions, same author, same idioms) would
  share the ASX line's three rules. Checked: it does not. The four ASX
  methodology errors were written BY the ASX line, in code days old. The audit
  direction was backwards — the risk is new code written fast, not old code
  written long ago.
- **V306 — the test suite nobody could run.** Ten Victoria files ran real
  multi-cycle simulations with no `slow` marker, so `pytest tests/` looked like
  it hung; inside that unrunnable suite, regression guards had rotted against
  constants superseded ninety versions earlier, and the suite dirtied its own
  frozen substrate on every run. The rule it bought: *a test nobody runs is worse
  than no test — it reports coverage while guarding a contract that moved.*
- **V307 — the ASX line REOPENED on a new resolution: the intraday map.**
  yfinance serves 730 days of 1h bars for `.AX` codes, which is a resolution
  V286–V304 never had. Frozen once (119 names, point-in-time top-120 by ADV as
  of the window's first day, byte-identity PASS) and mapped into eight
  pre-registered time-of-day buckets. `V307_ASX_INTRADAY.md` carries the map,
  the verdict, and what it means for V304's "cheaper way to hold the exposure".
- **V308 — V304's "+4%/yr at $5M" was the distance between a mean and a median.**
  The V299–V304 capacity tables were never committed; the first committed
  reconstruction found `engine.run` could not even take the v3 substrate, and
  once it could, V304's row is reproduced only by comparing the equal-weight
  book against the *median* eligible name. Against the equal-weight universe
  the quarterly book is net negative at every size and schedule for k ≥ 0.5.
  `V308_ASX_EXECUTION.md` restates the ASX verdict: the neglect spread is a
  statistical fact; the long-only book has no net edge. Nothing supports
  trading the ASX from this data.

**Victoria's standing open problem is unchanged and named in V305:** V279-class
inertness — components that import cleanly, are wired correctly, and do nothing.
See OBSERVABILITY-BACKLOG.md for the queued instrument.

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

   ✅ **Criterion 1 IS accruing (as of 2026-08-12).** The V253 live-paper daemon is
   running under launchd (`com.omega.live_paper`, PID 10329, up 8d, tick 02:55 UTC),
   `SCHEDULER_ENABLED=1`, writing MD5-chained daily checkpoints to
   `…/live_paper_v253_smoke_v2/live_paper/checkpoint/` — 21 cycles through
   2026-08-11, regime source `hmm`, equity $98,666.60. This supersedes the
   2026-07-25 "not accruing" note. **Victoria-lane only** — there is no
   funding-carry lane (the harness carries one book, `schema_version: 1`).

   ⚠️ **V268 (2026-08-12) bounds what criterion 1 can buy.** Criterion 1 accrues
   ~1 *calendar window* per quarter, which is true — but the quantity that gates
   **funding-carry** promotion is the capacity-conditioned trade count
   (high-ADV-tercile, `recent`), and that accrues **~30× slower**: 7–22 trades/yr,
   against the 138 more needed to close V267's G3 CI ⇒ **6.4–19.4 years**
   ([`V268_SOAK_FEASIBILITY_VERDICT.md`](V268_SOAK_FEASIBILITY_VERDICT.md), **R3**).
   Criterion 1 remains valid for the **Victoria** lane's recent-N; it does **not**
   put funding-carry's G3 leg within reach on any decision-relevant timescale.

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
| **Phase 2 (cont.)** | **V267** | **funding-carry capacity** | **CAVEATED 2/3 — capacity is NOT the binding constraint: book scales to ~316x per-trade notional (~$154M peak gross) under a 1%-of-ADV threshold, edge absorbs 11.8 bps of extra per-leg slippage before Sharpe 1.0, and the edge is CONCENTRATED in the most-liquid tercile (16.35 vs 1.05 bps) — the illiquidity-premium fear is refuted. G3 fails on one R2 leg: top-liquidity `recent` Sharpe 0.762, CI95 [-0.601, +1.193], n=62 — which CORRECTS V266's "recent-N wall is Victoria-specific": conditioned on tradeable liquidity, funding-carry's recent edge is unadjudicable too. Fitted-impact Sharpe curve declared R4 up front (no depth data, no fills above the $10k cap). V267-2 NOT queued** |
| **Phase 2 (cont.)** | **V268** | **scaled live-paper soak feasibility** | **STOP 0/2 — the soak cannot buy what V267 needs, and its "scaled" half measures nothing. F1 ACCRUAL FAIL (R3): the blocking quantity (high-ADV-tercile `recent` trades) accrues at 7–22/yr against 138 more needed ⇒ 6.4 yr best case, 19.4 yr on last-12m evidence; the rate has fallen 3× in three years as funding compressed in exactly the liquid names that carry the edge (BTC 1 / ETH 4 trades in 24m). F2 PAYLOAD FAIL (R5): annualised Sharpe is **bit-identical** across k = 1…1000 ($3.3k…$3.3M per trade) — with the impact lane R4 (no depth data), cost is proportional and every ratio statistic cancels k; the only nonlinearity is an 820×-paper-equity margin artifact. **No lane activated, daemon PID 10329 untouched, no strategy code.** Closes the "wait for the calendar" path *for this objective*; what remains is a data-acquisition decision, not a mechanism** |
| **Phase 2 (cont.)** | **V271** | **funding-carry live-paper lane (V268 option a)** | **R5 STOP 0/2 — the confirmed alpha cannot be run forward, because its entry rule reads the future. F0a FAIL: V255.B/C/D exclude the `near_zero` funding regime, but that label comes from a **full-span**-standardized market index (`regime._standardize`); recomputed causally it flips the trade/no-trade decision on **21.5%** of dates (bar 5%), and the filter gates **53.5%** of all level-passing candidates, so it is load-bearing. Both repairs (causal classifier / frozen constants) are edits to `omega/nodes/funding_carry/` — pre-excluded by scope, and circular: they change the rule whose ledger G2 reconciles against. No online-safe variant exists (the only filter-free variant, v2 directional, was refuted at V255 Phase 0). F0b FAIL: the V253 harness has **no lane concept** — one `cycle_fn`, one checkpoint, one PnL curve, 0 occurrences of "lane"; a lane must be built, not hot-added. Bonus (not a gate): G2 as pre-registered is near-vacuous — CI half-width at the precommitted N=100 is $2.50, so any live median in ≈[−$1.37, +$5.30] would "overlap" [$1.13, $2.80]. **No lane activated; daemon PID 13829 uninterrupted; depth collector PID 76450 untouched; no strategy code.** New dead-end class: R2/R3 are not-enough-data; this is the artifact being the wrong shape — the one confirmed alpha was only ever specified retrospectively |
