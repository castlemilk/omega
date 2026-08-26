# V277 (DRAFT) — Crisis-term recompute-proofing: make the V227 term invariant to three defaults

> ## ⚠️ DRAFT — NOT APPROVED, NOT PRE-REGISTERED, NOT RUN
>
> This document is a **draft pre-registration**. It has **not** been approved by the
> operator, **no** cells have been run, **no** numbers in it are observations, and the
> feature flag it describes (`crisis_term_rebind_enabled`) ships **default `False`**.
> Nothing here moves the standing baseline. Approving this draft means: reviewing §2's
> bars, fixing them, renaming the file to `V277.md`, committing it, and only then
> launching §4's grid. Until that happens the code on this branch is a dormant,
> byte-identical-by-default seam.

**Status:** DRAFT (pre-registration not committed, not approved, not run)
**Date:** 2026-08-20
**Author:** claude
**Parent:** [`V274.md`](V274.md) (IC-provenance audit: the standing baseline is IC-OFF in all 32 cells)
**Standing baseline (MUST NOT MOVE):** crisis +$599 / trend +$2,997 / recent +$30
**Branch:** `crisis-term-hardening` (not pushed)

---

## 0. What this version is, and what it explicitly is NOT

- **NOT a new signal.** No new term, no new gate, no new threshold, no new weight.
  The V227 crisis-skew signal, its regime gate, its X=0.12 drawdown AND-gate and its
  W=0.2 gated weight are all untouched.
- **NOT a re-gating.** The seam never re-evaluates the gate. It re-applies the
  *already-gated, already-stashed* float.
- **NOT a change to when the term fires.** `skew_on_cycles` / `gate_accept_cycles`
  are computed exactly as before.
- **IS an INVARIANCE change.** It removes the dependence of the V227 term's *measured
  efficacy* on three unrelated feature defaults that happen to be inert today.

## 1. Hypothesis

The V227 crisis-skew term is applied once, additively, post-demean, and lives **only**
in `composite` — deliberately never a `*_signal` key, so the equal-weight basket
selector cannot trim a one-sided term. That design is what makes it work, and it is
also what makes it fragile: **three separate paths rebuild `composite` from the
`*_signal` keys and thereby delete the term, while its fire counters keep
incrementing.** Verified by trace on 2026-08-18; corroborated by the V274 IC-provenance
audit.

| # | Site | Today's status | Why it's inert today |
|---|---|---|---|
| 1 | `strategy.py:_compute_weighted_conviction` IC-weighted return (`fsum(_weighted_terms)/total_ic`) | **LIVE whenever IC is on** | Only inert because the standing baseline runs `ic_seed_weighting: false` in all 32 cells (V274). The **default is `true`** with 18 seeded ICs in `data/signal_ic_history.json` — so on defaults the term loses its primary lever silently. |
| 2 | `strategy.py:_apply_regime_signal_weights` (mean of `*_signal` keys) | inert | `strategy_selector_enabled` defaults `False` |
| 3 | `strategy.py` V141 crisis-dampening + V153 trend-dampening recomputes, inside the per-ticker candidate loop immediately before `_passes_conviction_filters` | inert | `fear_greed_crisis_weight` / `sma_crisis_weight` / `trend_mean_reversion_weight` all default `1.0`. Note the V141 one fires under `_is_bear_context` — **exactly when the crisis term fires.** |

> **The bet:** the crisis term's contribution (V227: crisis +$630) is currently
> conditional on `ic_seed_weighting=false` plus two dampening defaults staying at
> `1.0`. With `crisis_term_rebind_enabled=True` the term's effect becomes
> **invariant** to all three — i.e. the 2020q1 / 2022h1 crisis deltas that the campaign
> attributes to V227 should **reproduce under `ic_seed_weighting=true`**, where today
> they largely vanish.

The falsifier is symmetric and cheap: if the OFF/ON crisis deltas are identical under
IC-ON as well as IC-OFF, the diagnosis is wrong and the seam is unnecessary.

## 2. Pre-registered questions and bars

> **DRAFT NOTE — the $ bars in Q2/Q3 are placeholders.** They must be fixed by the
> operator before this becomes a real pre-registration. The *directional* bars (Q1, Q4)
> are already falsifiable as written.

| ID | Question | Bar |
|---|---|---|
| **Q1** (primary) | Under `ic_seed_weighting=true`, does the crisis term produce a non-zero effect on the crisis trio when the rebind is ON? | `mean Δ(rebind_ON − rebind_OFF)` over the crisis trio is **≠ 0** and **directionally the same sign** as the IC-OFF V227 crisis effect. A Δ of exactly $0.00 across all three windows ⇒ **REFUTED** (the IC path was not the wall). |
| **Q2** | Does the IC-ON rebind-ON arm *reproduce* the IC-OFF crisis effect? | placeholder — e.g. within ±50% of the V227 IC-OFF crisis Δ per window. **Operator must fix.** |
| **Q3** | No-harm on benign tape | `snap_recent_2024aug` (the null control): \|Δ\| ≤ placeholder. Expected **exactly $0.00** — the gate does not fire there, so nothing is stashed and the seam is unreachable. A non-zero Δ on 2024aug is a **bug report**, not a result. |
| **Q4** (identity) | Is the OFF arm byte-identical to standing-main? | every rebind-OFF cell must reproduce its standing-main sibling **to the cent and to the trade fingerprint**, with `crisis_rebind_composite_cycles == 0` and `crisis_rebind_ic_cycles == 0`. Any deviation ⇒ **HALT**, the change is not default-safe. |

## 3. Changes (already implemented on the branch, all behind the flag)

- **New flag** `crisis_term_rebind_enabled: bool = False` — `omega/nodes/victoria/features.py`
  (declared + documented per the file's conventions; `from_env` picks it up automatically).
- **New leaf module** `omega/nodes/victoria/signals/crisis_rebind.py` — stdlib-only
  (imports nothing from victoria), so both `signal_generation` and `strategy` import it
  with no cycle. Holds `stash_applied_term` / `apply_crisis_terms` /
  `bind_ic_conviction` and the run-scoped counter dict `_CRISIS_REBIND_STATE`.
- **Bind site** `signal_generation.py` (the post-demean V227 site): when the flag is ON,
  stashes the **applied** term `_skew_w * _skew_val` under `_crisis_term_applied`, plus
  the resulting composite under `_crisis_term_bound_composite` (the idempotence marker).
  The arithmetic is unchanged (`_wt` is just a name for the product that was already
  computed inline).
- **Three rebind call sites** in `strategy.py`, each *immediately after* the recompute
  line so a future edit to the recompute is covered by construction:
  `_apply_regime_signal_weights` (which gained an optional `features` parameter),
  the V141 crisis-dampening recompute, and the V153 trend-dampening recompute.
- **IC-path bind** in `_compute_weighted_conviction`: the IC-weighted return now goes
  through `bind_ic_conviction`, which adds the stashed magnitude with the same
  2-element `math.fsum` + `[-1, 1]` clamp the composite path uses. The `total_ic == 0`
  and V223/V229 escape hatches return the raw `composite`, which **already** carries the
  term — so they are deliberately left alone (no double-count).
- **Observability** (`scripts/run_training.py`): `crisis_term_rebind_enabled`,
  `crisis_rebind_composite_cycles`, `crisis_rebind_ic_cycles` in
  `results.json['observability']`.
- **Tests**: `tests/test_crisis_rebind.py` (17 tests).

**Deliberately NOT covered:** the V233 `pre_demean` / `pre_demean_common_mode`
application site does not stash. That term is routed *through* the demean by design;
rebinding it after a downstream recompute would silently change its semantics, and the
V233 site is not part of this experiment. If a future version wants rebind + pre-demean
together, that is its own pre-registration.

## 4. Cells to run (2×2, crisis trio) — **NOT RUN**

The `ic_seed_weighting` toggle is the whole point: it is the flag whose *default*
(`true`) the standing baseline never exercised (V274: IC-OFF in 32/32 cells).

| Cell | `crisis_term_rebind_enabled` | `ic_seed_weighting` | Role |
|---|---|---|---|
| `A_icoff_rebindoff` | false | false | **standing-main reproduction** — must be byte-identical (Q4) |
| `B_icoff_rebindon` | true | false | isolates sites 2–3 only; expected **Δ = $0.00** (all three recompute sites inert on defaults), which is itself a clean identity check on the seam |
| `C_icon_rebindoff` | false | true | the **default-config incumbent** — the arm where the term is silently lost |
| `D_icon_rebindon` | true | true | the **treatment** — Q1/Q2 are measured on `D − C` |

Windows — the V231/V232/V233 crisis trio (`scripts/v233_dist_grid.sh` window set):

- `data/snapshots/snap_crisis_2020q1.json`
- `data/snapshots/snap_crisis_2022h1.json`
- `data/snapshots/snap_crisis_2024aug.json`

Plus, for Q3's no-harm control, the trend and recent gates for cells **C** and **D**
only (the two that can differ), run **after** a crisis-side result — not speculatively.

Shared base (mirrors the V233 grid's `BASE`, minus the IC pin which is now a variable):

```
"crisis_skew_enabled": true,
"crisis_skew_regime_gate_enabled": true,
"crisis_skew_drawdown_threshold": 0.12,
"rv_term_brake_enabled": false,
"crisis_term_predemean_enabled": false
```

Execution discipline: **sequential** (`MAXP=1`) — `data/` is a hardcoded global and
concurrent in-checkout cells corrupt the shared `*.db` + `signal_ic_history.json`
(the V233 grid note). Each cell must pass `scripts/assert_cell_identity.py`; the
rebind counters give it a new, direct inertness check (`rebind ON + composite_cycles=0
+ ic_cycles=0` on an IC-OFF cell is *expected*; on an IC-ON cell it is a **mislabeled
control**).

## 5. Expected effect (pre-registered predictions, not observations)

- **2020q1 / 2022h1 under IC-ON (D vs C):** a non-zero crisis Δ with the same sign as
  the V227 IC-OFF crisis effect. This is the prediction the whole version rests on.
- **2024aug:** **exactly $0.00** in every arm. Seven consecutive versions
  (V227–V233) returned Δ==$0.00 on that window because a post-demean W=0.2 composite
  nudge never crosses a trade-decision boundary on the broad yen-carry grind-down.
  V275 does not change the magnitude of the term, so it must not change that null.
  A non-zero 2024aug Δ would mean the seam is doing something other than restoring the
  same term — investigate before reading any other cell.
- **B (IC-OFF, rebind ON):** **exactly $0.00** vs A. All three composite-recompute
  sites are inert on defaults, so the seam has nothing to rebind onto.
- **Trend / recent:** ~$0 — the regime+drawdown AND-gate does not fire in benign tape,
  so no term is stashed and the seam is unreachable.

## 6. Standing-baseline gates that apply

Per-cell, `omega/eval/standing_gates.py` (post-run only, writes
`data/{version}_gate_result.json` for **every** verdict):

- `cell_pnl_floor` — candidate PnL ≥ the family's `per_cell_floor_usd` ($0.00 for all
  three families). Crisis cells map to family `crisis` via `provenance.snapshot` →
  `data/walk_forward_manifest.json`. A cell below the family campaign mean (+$599
  crisis / +$2,997 trend / +$30 recent) but at/above the floor **passes** with the
  `below_campaign_mean` advisory — advisory only, never a bar, never a failure.
- `trade_count_floor` — ≥ 20 closed trades (blocks "win by sitting out").
- `drawdown_ceiling` — evaluated only if `observability.max_drawdown_usd` is present;
  otherwise `not_evaluated` (never a silent `pass`).
- `sibling_comparison` — informational only. Expect it to flag **B ≡ A** and
  (predicted) **D ≢ C**; neither decides a verdict.

Grid level: `omega/eval/grid_ruler.py` is **not** run here. This is a 3-window crisis
probe, not the 32-window manifest — the ruler would (correctly) return
`INSUFFICIENT_GRID`. If V275 is later promoted toward the standing baseline, that
promotion is its own pre-registration and *must* run the full ruler with a declared
`--coupling` class.

**Nothing in this version may edit `data/standing_baseline.json`.** Moving the standing
baseline is a separate journal act with its own pre-registration.

## 7. Kill / halt conditions

- **HALT** if any rebind-OFF cell fails to reproduce its standing-main sibling to the
  cent and to the trade fingerprint (Q4). The flag is not default-safe; nothing else
  in this document may be read.
- **HALT** if any counter shows the seam fired on a cell where the gate never accepted
  (`skew_on_cycles == 0` but `crisis_rebind_*_cycles > 0`) — that would mean the seam
  is applying an ungated term.
- **REFUTED (clean stop)** if `D − C` is $0.00 across the crisis trio: the IC path was
  not where the term was being lost, and the flag stays OFF permanently.

## 8. Verification performed on the branch so far (code only — NO runs)

- `pytest tests/test_crisis_rebind.py` — 17 passed.
- `pytest tests/test_crisis_skew_regime_gate.py tests/test_crisis_skew_signal.py
  tests/test_strategy_factory.py tests/test_action_contracts.py` — 88 passed with the
  new file included.
- **No training run, no grid, no live call, no `data/` write.**

### Determinism spot-proof — and its stated limitation

A true byte-identical proof would diff this checkout against a pristine pre-V275
checkout on identical fixtures. That is impractical to run cross-checkout inside a unit
test, so it was **not** done. What is proven instead, in `tests/test_crisis_rebind.py`:

1. With the flag OFF the bind site writes **no stash keys at all**, so the seam
   short-circuits at its entry and returns without touching the dict
   (`test_flag_off_seam_writes_no_keys`) — there is no reachable mutation.
2. Each recompute expression is asserted to still produce the value computed by the
   **literal pre-V275 expression**, with exact float equality
   (`test_flag_off_site1_byte_identical`, `test_flag_off_dampening_sites_byte_identical`,
   `test_flag_off_ic_path_byte_identical`).

Together these bound the flag-OFF blast radius to zero, but they are unit-level.
**The real default-safety evidence is cell A of §4**, which has not been run.

## 9. Why the seam must NOT re-evaluate the gate

The stash is the cycle's truth. The term that entered the composite is the term that
must survive a recompute *of that composite*. Re-deriving the gate at the rebind site
would be a second, differently-timed gate decision reading state (regime label,
`_skew_dd_mag`, weight) that may have been mutated downstream — a new determinism
channel of exactly the V211/V220/V221 class the campaign has spent four versions
closing, and a way for a mid-cycle label flip to silently delete a term that had
already moved the composite. `test_seam_does_not_reevaluate_the_gate` pins this: a ts
whose `crisis_skew` has since been zeroed and whose `_regime` now reads `normal` still
rebinds the stashed value.

## 10. Next steps

→ **Operator**: fix the Q2/Q3 bars, decide whether the 2×2 is the right shape, then
rename to `V275.md` and commit *before* any cell runs.

Open questions / parking lot:

- Should the IC path receive the term **before** or **after** the conviction threshold
  scaling (`_thresh_scale`)? Currently after — the term is added to the returned
  conviction, matching where it sits in the composite path. An argument exists for
  treating it as a threshold shift instead; that is a different experiment.
- If Q1 confirms, the natural follow-up is whether `ic_seed_weighting`'s default should
  itself change — a much larger question that V274 already opened and that this version
  deliberately does not touch.
- Sites 2 and 3 remain unmeasurable while their flags default to inert values. Their
  coverage here is insurance, not a result.
