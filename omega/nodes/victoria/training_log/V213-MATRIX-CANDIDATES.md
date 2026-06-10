# V213 — Matrix candidate menu (parking lot)

> **Status:** candidate menu, NOT yet pre-registered.
> V212 is in flight; its results may reorder these priorities before
> V213 actually starts. The matrix mode itself is documented in the
> `victoria-training-loop` skill ("Matrix exploration" section).

V211 closed with: recent +$2,177, trend +$8,328, crisis −$24,828.
Crisis remains the static gate after three crisis-targeted versions
(V207a → V211); the V210 reflection flagged the
`crisis_short_bias` subsystem as a likely dead end and called for
work outside it. The V211 parking lot + V204 salvage shortlist +
V205 untouched-axes list together give the candidate set below.

When V213 is pre-registered, pick **2–3 cells** from this list and
write `training_log/V213-matrix.md` with one subsection per chosen
cell (hypothesis / files / falsifier / targeted gate). The rest stay
parked here.

## Candidates

### V213.A — V199 carry plumbing isolation
- **Subsystem:** funding-carry signal routing into composite.
- **Change:** cherry-pick commit `cbbfb07` (V199 carry-only sub-strategy plumbing) onto V211 HEAD.
- **Why a candidate:** V199 showed carry could reach the composite
  but its standalone result was muddied by other concurrent edits.
  Isolated on V211's baseline it's a clean read of "does carry
  contribute on recent?"
- **Targeted gate:** recent (carry is a normal-regime edge).
- **Complexity:** small (single cherry-pick + tracer verification).

### V213.B — V170 per-regime IC weighting
- **Subsystem:** signal weighting (`update_regime_ics` in the ensemble voter).
- **Change:** activate the dormant `update_regime_ics` path so IC
  weights are recomputed per regime label (`crisis` / `high_vol` /
  `normal`) instead of pooled.
- **Why a candidate:** V170 implemented the machinery but never
  flipped the switch. Per-regime IC could change which sub-signals
  dominate the composite in crisis without touching
  `crisis_short_bias` (which the reflection flagged as dead).
- **Targeted gate:** crisis primarily; trend secondarily.
- **Complexity:** medium (config flag + verify weights actually
  diverge per regime; needs tracer evidence).

### V213.C — V166 normalization activation
- **Subsystem:** signal pre-normalization before composite.
- **Change:** turn on V166's normalization pass for sub-signals
  with heterogeneous scales (carry vs OFI vs momentum).
- **Why a candidate:** V166's normalization was implemented but
  parked because we couldn't isolate it from concurrent V165/V167
  edits. On a clean V211 baseline its effect is measurable.
- **Targeted gate:** trend and recent (better-scaled composites
  help most where multiple signals coexist; crisis is dominated
  by short-bias).
- **Complexity:** small (config flag).

### V213.D — Snapshot-conditioned V157 weights
- **Subsystem:** static signal weights conditioned on snapshot
  identity rather than regime label.
- **Change:** load a V157-style weight vector keyed on the
  snapshot name (`snap_recent` / `snap_trend` / `snap_crisis_2022`)
  instead of regime-only.
- **Why a candidate:** V157 had per-snapshot weights but we
  abandoned them to chase per-regime weights (V170). On a static
  snapshot the snapshot-name conditioning is strictly more
  specific than regime-label conditioning.
- **Targeted gate:** all three (different weight per gate).
- **Complexity:** medium (need a fitted weight vector per snapshot
  — fit on the first 100 cycles, eval on the remaining 100, or
  pull from V157's `data/v157_weights.json` if it survived).
- **Caveat:** risks overfitting to the snapshot, which is fine for
  an audit signal but DOES NOT generalize. Treat as a diagnostic
  cell, not a candidate for merge unless V213.E also passes.

### V213.E — `snap_crisis_2020q1.json` generalisation check
- **Subsystem:** none. Pure eval-extension cell.
- **Change:** NO code change. Run V211 HEAD against a second
  crisis snapshot (`snap_crisis_2020q1.json` — COVID crash) in
  addition to the existing `snap_crisis_2022.json` (LUNA / FTX
  era).
- **Why a candidate:** V210 reflection's "untouched dimensions"
  list called out snapshot diversity. If V211's crisis loss is
  snapshot-specific (LUNA dynamics) vs structural (any drawdown),
  the second snapshot reveals it. Cheap and informative.
- **Targeted gate:** crisis (extended).
- **Complexity:** small (snapshot file + audit harness; no code
  change). Probably the best ROI cell — zero risk of breaking
  anything, biggest informational payoff.

### V213.F — V204/V205 runtime ensemble (regime-aware stacking)
- **Subsystem:** strategy selector / runtime ensemble.
- **Change:** at runtime, blend V204 (carry-heavy) and V205
  (momentum-pinned) sub-strategy outputs weighted by current
  regime probability instead of hard-switching.
- **Why a candidate:** V204 and V205 each won on different gates
  in isolation; neither dominated overall. A regime-weighted
  runtime blend is a different bet than picking one or the other.
- **Targeted gate:** trend and recent (V204/V205 didn't move
  crisis).
- **Complexity:** large (touches `strategy_selector` + composite
  routing + needs tracer evidence both legs fire). Lowest-priority
  cell — defer unless V213.A/B/C all stagnate.

## Audit-driven candidates (added 2026-06 by `STRATEGIC_AUDIT_2026-06.md`)

> These come from the senior-quant audit, not the V204/V205/V211 parking lots. Several are
> **prerequisites** — they unblock the rest. Read the audit's "Top 5" for the dependency order.
> **None merges without clearing the audit's R3 distributional band** (≥3 snapshots per regime).

### V219.G — Wire the existing IC machinery (pooled)  ⭐ master lever
- **Subsystem:** composite weighting (`_compute_weighted_conviction`, `_signal_ics`).
- **Change:** call `update_signal_ics` from the training path off `signal_ic_history.json`;
  remove/condition the `strategy.py:1032` early-return so the weighted path runs. ONE bet
  (raw-mean → IC-weighted); do NOT also add per-regime in the same cell.
- **Why a candidate:** the composite is a flat equal-weight average today (IC subsystem
  runtime-inert, proven at V218.B). Wiring it auto-down-weights the research-flagged dead
  signals (`fear_greed`, `ollivier_ricci`) AND is the prerequisite for V213.B/V219 per-regime IC.
- **Targeted gate:** recent + trend (where dead signals dilute alpha).
- **Caveat:** `signal_ic_history.json` is **pooled, not regime-tagged**, and its ICs are
  estimated on the noisy single-window eval — validate the source before trusting it.
- **Complexity:** small–medium. **Prerequisite for V213.B.**

### V219.H — Distributional eval (≥3 snapshots per regime)  ⭐ prerequisite
- **Subsystem:** none — eval harness only.
- **Change:** build crisis {2018q4, 2020q1✓, 2021-05, 2022h1✓}, trend {2021-bull, 2023q4✓},
  recent {≥2 rolling}; report mean ± cross-window spread as the gate unit.
- **Why a candidate:** V218.E proved one gate = one snapshot is an artifact (crisis sign-flips
  −$2.9k→+$13k across windows). Until gates are distributions, no delta (incl. the selector Δ)
  is known to generalize. Uses the existing `SNAP_OVERRIDE` knob.
- **Targeted gate:** all three. **Gates every other audit candidate.**
- **Complexity:** medium (snapshot construction + harness loop).

### V219.I — Eval-integrity: commit/freeze `macro_cache.db`  ⭐ blocker, ship first
- **Subsystem:** eval reproducibility.
- **Change:** freeze a canonical `macro_cache.db` (or `data/snapshots/frozen_macro.db` + loader
  pin) + cycle-0 md5 manifest check. See OBSERVABILITY-BACKLOG #11.
- **Why a candidate:** the V217 "hermetic" baseline was not reproducible from committed state
  (`V218-matrix.md:188`). No cross-version comparison means anything until this lands.
- **Targeted gate:** all (stabilizes, doesn't move).
- **Complexity:** small. **Upstream of everything.**

### V219.J — Spot–perp basis as a frozen-feed signal
- **Subsystem:** new crisis-prior signal + reusable frozen-feed plumbing.
- **Change:** `frozen_basis_feed.json` (CCXT spot+perp), route as a `*_signal` key into the
  composite, PipelineTracer-verify ≥5 attributed trades.
- **Why a candidate:** highest a-priori crisis signal (carry collapse leads stress,
  `cross-asset-signals.md`), one-fetch-away, orthogonal to the technical core. Builds the feed
  plumbing options-skew / OI-velocity reuse. V218.A lesson: a correct signal is untestable
  without a frozen feed.
- **Targeted gate:** crisis (over the V219.H distribution).
- **Falsifier:** <5 basis-attributed trades → still gated out (plumbing); crisis Δ within band
  → prior doesn't survive Victoria's horizon.
- **Complexity:** medium. **Needs V219.G + V219.H first to be measurable.**

### V219.K — Options skew (Deribit 25Δ risk-reversal), frozen-feed
- Same plumbing as V219.J; second crisis-prior signal. Free Deribit REST. Effort M.

### V219.L — Perp OI velocity (dOI/dt), frozen-feed
- Leverage-buildup-reversal momentum signal, all-regime prior. Coinglass/CCXT. Effort M.

### V219.M — VIX extreme mean-reversion transform
- VIX *level* is already wired; add the sustained-extreme (>35 for N days → capitulation)
  transform as a distinct `*_signal`. Effort S.

### V219.N — Dead-signal pruning control
- Remove `fear_greed_signal` + `ollivier_ricci_signal` from the composite as a **control** vs
  V219.G (does explicit pruning match IC-down-weighting?). Diagnostic, not a standalone merge.
  Effort S.

### V219.O — Cadence-gate the intraday risk windows on daily bars
- Fix the daily-bar artifact where both `time_risk_multiplier` windows fire every cycle →
  uniform ~0.375× sizing (the current baseline is defined on this). Re-bases the baseline →
  pre-register. Orthogonal to determinism. Effort S.

### V219.P — Selector as a distribution test (not a point estimate)
- Re-run the V217 selector Δ across the V219.H snapshot distribution before committing to a
  regime-gated toggle. The current Δ (recent +$4,240 / trend −$7,432 / crisis −$1,221) is three
  single-window point estimates. Effort S (eval only). Confirm the §2.2 mechanism first by
  reading `mode_transitions.jsonl`.

## How to pick

- **Bias toward independence.** V213.A (carry) + V213.B (IC weights)
  + V213.E (extra snapshot) is a strong default trio — three
  different subsystems, one is a pure eval extension.
- **Avoid stacking same-subsystem cells.** V213.B and V213.D both
  touch signal weighting — running both in the same matrix
  contaminates the read.
- **V213.E should almost always be included.** It costs nothing,
  blocks nothing, and answers the snapshot-generalization question
  the V210 reflection raised.
- With N=3 cells, use the 2.5σ many-comparisons threshold from
  the skill's matrix section. With N=2, stay at 2σ.
