# V218 — Matrix experiment (3 cells, shared V217-OFF hermetic baseline)

**Date:** 2026-06-09 (pre-staged in V217; DO NOT START until V217 ships 6/6)
**Author:** claude
**Parent:** V217 — third determinism channel (multi-threaded Accelerate BLAS) closed;
eval is 6/6 hermetic at sleep=10 (the precondition the matrix waited on since V213).
**Status:** RUNNING (kickoff 2026-06-09). Per the skill, the matrix runs only on a fully
hermetic eval. V217 delivered it.

## Kickoff preflight (2026-06-09) — Step-1 observability-gap audit results

Before launching, a wiring audit of the two code cells (A, B) surfaced a finding that
**reclassifies cell B from a runnable bet to BLOCKED**, and ships the instrument that would
have caught it at pre-reg time:

- **Cell A — RUNNABLE.** `signals["carry"]` IS populated in the replay eval
  (`victoria_node.py:1120`, fields `value`/`confidence`/`regime_tag`) — exactly what
  cbbfb07's hunk-1 injection reads. Whether `_carry_value != 0.0` holds under `--frozen-cache`
  is precisely what A's falsifier (≥1 carry-attributed trade) measures. Proceed.
- **Cell B — BLOCKED (deeper than the pre-reg anticipated).** The pre-reg assumed pooled IC
  weighting was the live baseline and only the *per-regime* branch was dormant. Static + log
  audit shows the **entire IC-weighting subsystem is runtime-inert in the eval**:
  1. `StrategyNode._signal_ics` is initialised empty (`strategy.py:437`) and its **only**
     populate path is `update_signal_ics`, which has **zero callers** in the training/audit
     path (not in `run_training.py` HEAD, not in `victoria_node.py`). Confirmed empirically:
     **no `"StrategyNode: loaded ICs"` line appears in any V217 run log.**
  2. `_compute_weighted_conviction` (`strategy.py:1025`) runs every cycle (called at `:1429`
     inside `_passes_conviction_filters`) but hits `if not self._signal_ics: return composite`
     at `:1032` — it **returns before ever reaching the `_per_regime` branch at `:1056`.**
  3. `per_regime_ic_weighting` is **undeclared** on `VictoriaFeatures`; `from_env` filters
     overrides to declared fields (`features.py:699`), so even passing it via env is a no-op.
  4. `update_regime_ics` has **no cycle-feasible data source**: `signal_ic_history.json` is
     pooled, not regime-tagged; the only regime-IC producer is the on-demand
     `_analyze_regime_ic` *action* (`signal_research.py:311`), not a per-cycle hook.

  → Per the advisor and the matrix one-bet rule, **B's scope is NOT expanded** (loading pooled
  ICs to clear the early-return is a *second* bet — raw-composite → IC-weighted — that would
  confound B's Δ). B runs as a **flag-only no-op** (declare the field, default True in its
  worktree) to empirically confirm Δ=$0.00 even with the flag ON, then carries verdict
  **BLOCKED**. Its pre-registered falsifier ("switch inert → no read") anticipated exactly this.
  V219.B-corrected gets the real prerequisite: **wire pooled ICs from `signal_ic_history.json`
  as its own one-bet version, then per-regime becomes testable.**

**Observability shipped this kickoff (the instrument that catches this class at cycle 0):**
- `run_training.py` startup banner extended: probes `per_regime_ic_weighting` (→ prints
  `UNDECLARED — silent no-op` on main) **and** a new post-build `_signal_ics`-populated probe
  (→ warns `IC-WEIGHTING INERT: _signal_ics empty` when the subsystem is unwired).
- `scripts/v218_matrix_status.sh` — single-pane health monitor for the 3 concurrent cells
  (PID liveness + log tail + per-cell gate progress).
- `check_determinism.sh` gains `SNAP_OVERRIDE` env (lets cell E run its crisis gate against
  `snap_crisis_2020q1.json` with no code diff). Remaining backlog item (`size_ratio.jsonl`
  automated artifact) queued to `OBSERVABILITY-BACKLOG.md`.

## σ band (resolves the stale-σ caveat below)

Within-config spread is **$0** under the V217 hermetic regime (each cell re-confirms via its
own trend determinism gate). The V203 2σ thresholds were measured under the OLD regime
(multi-threaded BLAS + pre-fence sizing) and are NOT trusted for cross-config comparison.
**Decision:** use a flat **$100 acceptance band** (noise-floor $0 × generous margin; well
above the 2.5σ-at-N=3 inflation when σ≈$0). A cell's gate Δ counts as real signal only if
**|Δ| > $100**. Cell E compares **absolute PnL** on the new 2020q1 snapshot, not Δ vs the
2022h1 crisis baseline (different window).

## Why matrix now

The matrix has waited since V213 because the eval was not hermetic (V212 selector
non-determinism → V213 sleep/async → V214 network → V215 network fix → V216 sizing
wall-clock → V217 BLAS threading). With 6/6 cells byte-identical at sleep=10, per-cell
deltas are finally trustworthy and three **independent** bets can run in parallel against
one baseline instead of three sequential ~8h versions.

## Shared baseline (V217 OFF, hermetic, single-threaded BLAS, sleep=10)

| Gate    | V217 OFF baseline (det.) | Trades | Noise floor |
|---------|-------------------------:|-------:|------------:|
| recent  | -$1,905.71               | 38     | $0 (hermetic — every cell $0.00) |
| trend   | +$1,039.24               | 35     | $0 |
| crisis  | -$2,199.50               | 38     | $0 |

(V217 ON arm, for reference: recent +$2,334.40 / trend −$6,392.99 / crisis −$3,420.26;
selector Δ = recent +$4,240 / trend −$7,432 / crisis −$1,221 — all clean.)

Because V217 is byte-identical, the within-config noise floor is **$0** — but to guard
against many-comparisons false positives with N=3 cells, use the skill's **2.5σ → here a
flat acceptance band**: a cell counts as a real move only if its gate Δ exceeds the larger of
(a) the V203 variance 2σ thresholds (recent $5,094 / crisis $1 / trend $2) and (b) any
residual within-cell spread (expected $0). Document the chosen band per cell below.

> ⚠️ **Stale-σ caveat (resolve at V218 kickoff).** The V203 2σ thresholds were measured under
> the OLD regime (**multi-threaded BLAS + pre-fence sizing**). The V217 hermetic baseline is a
> DIFFERENT regime (single-threaded BLAS + 0.375× bar-time sizing). Within-config spread is now
> $0, but the *cross-config* variance that actually governs cell-vs-baseline comparisons is
> **unmeasured under the new regime**. Before trusting the V203 band, either re-derive a noise
> floor under V217 HEAD or treat the V203 numbers as a conservative upper bound only.

## Cells (each in its own worktree `.claude/worktrees/v218-<letter>-<name>/`)

> **Worktrees are created at V218 kickoff, NOT pre-created in V217.** V217 is
> pre-registration only (the skill's "don't START matrix runs in V217" rule). The paths
> below are the agreed naming convention; the three worktrees do not yet exist on disk.

### V218.A — V199 carry plumbing isolation
- **Hypothesis:** routing the funding-carry signal into the composite (V199's carry-only
  sub-strategy plumbing) adds a clean normal-regime edge on recent.
- **Change:** cherry-pick `cbbfb07` (V199 carry plumbing) onto V217 HEAD; verify with the
  V197 PipelineTracer that carry actually enters the composite (≥1 carry-attributed trade).
- **Files touched:** `strategy.py`, `ensemble_voter.py` (carry routing).
- **Targeted gate:** recent.
- **Falsifier:** < 5 carry-attributed trades in 200 cycles → carry still gated out (tracer
  bug, not edge); recent Δ within 2σ → no edge.

### V218.B — V170 per-regime IC weighting  →  **BLOCKED at kickoff (see preflight above)**
- **Hypothesis (original):** recomputing IC weights per regime label (crisis/high_vol/normal)
  instead of pooled changes which sub-signals dominate the composite in crisis without touching
  the reflection-flagged `crisis_short_bias` dead end.
- **Change (as run):** declare `per_regime_ic_weighting: bool = True` on `VictoriaFeatures` in
  the cell-B worktree only — a **flag-only no-op** to empirically confirm the subsystem is
  inert even with the flag ON. **NOT** expanded to load pooled ICs or build a regime-IC
  accumulator (that would be a second bet; see preflight).
- **Files touched:** `features.py` (one field declaration).
- **Targeted gate:** crisis (primary), trend (secondary) — *moot; subsystem unwired*.
- **Falsifier (FIRED at preflight):** "per-regime weights identical to pooled / switch inert →
  no read." Confirmed: `_signal_ics` empty → `_compute_weighted_conviction` early-returns the
  raw composite before the per-regime branch. Expected audit Δ = **$0.00 on all gates**.
- **Verdict:** BLOCKED. Root cause = pooled `update_signal_ics` never called in the eval.
  V219.B-corrected = wire pooled ICs first (its own version).

### V218.E — `snap_crisis_2020q1` generalisation check (no code change)
- **Hypothesis:** if V217's crisis loss is snapshot-specific (LUNA/FTX 2022h1 dynamics) vs
  structural (any drawdown), a second crisis snapshot (COVID 2020q1) reveals it.
- **Change:** NONE. Run V217 HEAD against `data/snapshots/snap_crisis_2020q1.json`.
- **Files touched:** none (eval extension only).
- **Targeted gate:** crisis (extended).
- **Falsifier:** n/a (pure diagnostic) — informative either way.

## Independence argument (required before running matrix)

A (carry routing, `strategy.py`/`ensemble_voter`) and B (IC weighting path) touch disjoint
subsystems; E is a pure eval extension (no code). No shared parameter surface →
matrix-eligible. Pre-flight: each worktree pins `OMEGA_FROZEN_CACHE` + the V217 BLAS pin and
isolates cache writes (`data/macro_cache.db`, `state.db`) so cells don't contaminate each
other (the matrix-mode shared-state failure mode).

## Merge rule

Only ONE cell's code merges to main (or zero if none clears the band). A + B both passing →
V219 stacks the pair OR runs a 2×2 interaction; do not silently merge two cells. E never
merges (no code); its result informs whether crisis work generalises.

## Run config (launched 2026-06-09T09:17Z)

- **Per cell:** 3-gate audit at **sleep=10, selector OFF, N=2** (one determinism pair per
  gate). **trend runs first and doubles as the determinism abort gate** (spread > $200 ⇒
  abort cell before recent/crisis). Orchestrator: `/tmp/v218_cell_orch.sh`; status monitor:
  `scripts/v218_matrix_status.sh`.
- **N=2 (not the protocol's 2-pair/N=4) rationale:** the eval is certified 6/6 hermetic at
  V217 ($0.00 spread), so a single pair confirms within-cell determinism + yields the
  deterministic PnL, while keeping the 3-cell parallel matrix inside the ~8h budget (each
  200-cycle sleep=10 run is ~35min, sleep-dominated; N=4 across 3 cells ≈ 8.2h, at the edge).
  trend-first preserves the cheap-abort property the protocol's separate det gate provided.
- **Cell E crisis** uses `SNAP_OVERRIDE=data/snapshots/snap_crisis_2020q1.json`; its recent +
  trend gates run the standard snapshots and should reproduce V217 OFF exactly (no code diff).
- **Smoke-validated before launch:** the new IC-WEIGHTING INERT + `per_regime_ic_weighting`
  banner probes fire correctly; runs proceed without `DATABASE_URL` (frozen mode degrades
  heartbeat/DB writes to warnings).

## Results (completed 2026-06-09T13:02Z; all 18 audit runs determinism PASS $0.00)

### Raw per-cell × per-gate (N=2, sleep=10, selector OFF; all spreads $0.00)

| Cell | recent | trend | crisis | Determinism |
|------|-------:|------:|-------:|-------------|
| V218.A carry | +$4,529.74 (22t) | +$455.70 (25t) | −$2,862.86 (31t) | 6/6 PASS $0.00 |
| V218.B IC (no-op) | +$4,529.74 (22t) | +$455.70 (25t) | −$2,862.86 (31t) | 6/6 PASS $0.00 |
| V218.E 2020q1 | +$4,529.74 (22t)* | +$455.70 (25t)* | **+$13,051.74 (28t)** | 6/6 PASS $0.00 |

\* E's recent/trend run the standard snapshots (no code diff) → identical to B; E's crisis
runs `snap_crisis_2020q1.json`.

### ⚠️ Baseline note — README V217 numbers are NOT reproducible from committed state (two eval-integrity defects)

The in-matrix no-op control (cell B) is **+$4,529.74 / +$455.70 / −$2,862.86 (22/25/31t)**,
which does **not** match the README V217 OFF baseline (−$1,905.71 / +$1,039.24 / −$2,199.50,
38/35/38t). Forensics on `data/macro_cache.db` found **two** defects:

1. **Macro is degraded to all-zeros in BOTH the committed and the working-tree cache.** The
   `macro_cache` table holds 4 rows — DGS2, DGS10, DTWEXBGS, VIXCLS — every one with
   `date='__failed__'` and `value=0.0`. So **the entire eval (matrix AND the V217 baseline) ran
   with VIX=0, 2y/10y yields=0, dollar index=0** — a failed FRED warm-up that silently persisted
   zeros. (My first read of this — "committed degraded vs working-tree real" — was WRONG; both
   are zero. The md5 differs only in the `funding_rate_cache` table, see #2.)
2. **`funding_rate_cache` differs** between committed (`md5 2b8f5e44`: BTC 1.0e-4, SOL −8.2e-5)
   and main working-tree (`md5 a12b941d`: BTC 2.5e-5, SOL 1.0e-4). This cache is overwritten by
   each warm-up and was never frozen/committed deterministically, so the V217 baseline used a
   different funding snapshot than the worktrees inherited — the most likely driver of the
   22-vs-38-trade gap (funding-derived signals shift while macro stays pinned at zero).

**Conclusion:** the V217 "hermetic" baseline was reproducible only *within a session* — it
depended on transient, uncommitted cache state (a failed-macro stub + a session-specific funding
snapshot). It is **not reproducible from committed state.** This is reflection-trigger #2
(eval-noise: a pre-registered no-op control diverged from the README baseline by >$6k) **and** an
eval-integrity blocker for V219. **Within the matrix it is harmless** — all 3 cells share the
*identical* committed cache, so cell-vs-cell comparisons (A−B, E−B) are byte-clean. **Use cell B
as the baseline, not the README numbers.**

### Verdict table (baseline = cell B no-op control; $100 band)

| Cell | Hypothesis | recent Δ(vs B) | trend Δ | crisis Δ | Verdict |
|------|------------|---------------:|--------:|---------:|---------|
| V218.A | carry plumbing | $0.00 | $0.00 | $0.00 | **FAIL — inert** (carry untestable in frozen eval) |
| V218.B | V170 IC | — (baseline) | — | — | **BLOCKED** (IC subsystem unwired; flag ON yet Δ=$0) |
| V218.E | 2020q1 crisis | ≡B | ≡B | abs **+$13,051.74** | **CANDIDATE — window-dependence real, magnitude suspect (zero-macro)** |

### Cell findings

- **V218.A — FAIL (carry inert; falsifier fired).** A's trade CSV is **byte-identical to B's**
  on every gate. Cause: `FundingCarrySignal._get_funding_rate` reads `market_data["funding_rate"]`
  (absent from the replay snapshots) then falls back to a **live Binance fetch
  `fapi.binance.com/fapi/v1/fundingRate`**, which the V215 frozen HTTP guard blocks — **200
  blocked funding fetches/cycle** logged → funding=0 → `_carry_value==0.0` → the injection guard
  (`if _carry_value != 0.0`) skips every cycle. The plumbing is *correct*; there is simply **no
  funding data to drive it** in the frozen eval (independent of the macro_cache issue — funding
  ≠ FRED). Falsifier "<5 carry-attributed trades → carry gated out" fired (0 trades). To test
  carry, V219 must add `funding_rate` to the frozen snapshots (or a `frozen_funding_feed.json`
  analogous to `frozen_advanced_signals.json`).
- **V218.B — BLOCKED (as pre-classified).** Flag declared + default ON in the cell worktree; the
  banner printed `per_regime_ic_weighting: ON → ACTIVE` while the new probe printed
  `IC-WEIGHTING INERT: _signal_ics empty` — and audit Δ=$0.00 vs B-baseline (A≡B≡E proves it).
  Empirically confirms the subsystem is a no-op even with the flag ON. V219.B-corrected = wire
  pooled ICs first.
- **V218.E — CANDIDATE (directional win, magnitude not bankable).** Under **identical code +
  cache**, the crisis gate flips from **−$2,862.86 (2022h1, 31t)** to **+$13,051.74 (2020q1,
  28t)**. Verification (the 3 checks the adversarial review demanded):
  - ✅ **Crisis path DID run** on 2020q1 — the regime column shows **8 crisis / 2 high_vol / 18
    normal** trades (vs 2022h1's 6 / 5 / 20), so the +$13k is *not* "crisis logic skipped." The
    COVID-crash price action triggers crisis regime (price-driven, since macro is zero in both).
  - ✅ **Snapshot is a real window, not a stub** — `snap_20200101_20200430`, 91 daily bars
    (Jan–Apr 2020, spans the COVID crash); 2022h1 = 151 bars. Shorter but legitimate.
  - ⚠️ **Macro is zero in BOTH runs** (the all-`__failed__` cache above). So the sign-flip is
    *internally valid* (macro held constant ⇒ the difference is the price window), but the
    **absolute +$13,051 ran on a degraded zero-macro eval** and is not a trustworthy "the recipe
    earns $13k in COVID" claim. Regime labels themselves are partly macro-derived → suspect.
  - **Net:** the **directional finding is real** — crisis P&L is window/price-dependent and
    *sign-flips* between two crisis windows, so V217's crisis loss is **at least partly a
    single-window artifact, not a fixed structural property** of the OFF recipe. The **magnitude
    and the "generalises" verdict are pending a real-macro re-run** (V219 #1 → #2). The entire
    crisis "gate" through V199–V217 optimising against one window is the live concern.

## Merge decision — ZERO cells merge

- **A:** carry inert (untestable in frozen eval) → nothing to merge; the code is correct but
  unexercised. Re-test in V219 once funding is frozen.
- **B:** BLOCKED no-op → nothing to merge.
- **E:** no code → never merges (diagnostic only).

No cell cleared the $100 band on any gate vs the no-op control (A=$0 by inertness; E is a
diagnostic, not a code change). `main` is unchanged. The three worktrees + branches
(`v218.a-carry-plumbing`, `v218.b-v170-ic`, `v218.e-snap-crisis-2020q1`) are **retained** —
V219 re-runs A (after funding is frozen) and B (after pooled ICs are wired) directly on the
existing code, and the audit artifacts under each worktree's `data/` are the forensic record.

## V219 brief (priority order)

1. **EVAL-INTEGRITY FIX (hard blocker, ship first).** Two defects, both eval-invalidating:
   (a) **Macro is all-zeros** — the FRED warm-up is failing and persisting `__failed__`/0.0 for
   VIX, DGS2, DGS10, DTWEXBGS. The eval has been running with **no macro at all**. Fix the
   warm-up (or commit a real frozen macro table) so VIX/yields are non-zero, and add a preflight
   tripwire that FAILS if any `macro_cache.value` is 0/`__failed__` at cycle 0 (this is the exact
   IC-WEIGHTING-INERT-style probe for macro). (b) **`funding_rate_cache` is uncommitted +
   warm-up-overwritten** → non-reproducible funding between sessions. Freeze it like the
   snapshots. Until BOTH are fixed, no cross-version PnL comparison is trustworthy — the V217
   "hermetic" baseline was reproducible only within its own session. Add a committed cache
   manifest (md5) checked at cycle 0.
2. **V219.E-followup — crisis snapshot diversity, RE-RUN ON REAL MACRO (headline).** The crisis
   sign-flip is real but was measured on zero macro; re-run 2020q1 + 2022h1 after fix #1 to get
   bankable magnitudes. Then build ≥3 crisis snapshots (2020q1 ✓, 2022h1 ✓, + e.g. 2018q4,
   2021-05) and evaluate the OFF recipe's crisis *distribution* — a point-estimate crisis gate is
   meaningless if P&L sign-flips by window. The V219 regime-gated-selector case gains urgency:
   selector value is plausibly crisis-snapshot-dependent too.
3. **V219.A-corrected — make carry testable.** Add `funding_rate` to the frozen snapshots or a
   `frozen_funding_feed.json`; re-run the carry-plumbing cell (`v218.a-carry-plumbing` branch
   already has the code).
4. **V219.B-corrected — wire pooled ICs.** Call `update_signal_ics` in the training path from
   `signal_ic_history.json` (one bet); only then does per-regime IC weighting become testable.
