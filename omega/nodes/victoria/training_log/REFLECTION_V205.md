# Reflection — V205 (post-V205, blocking V206 pre-registration)

**Date:** 2026-06-01
**Author:** claude (mandatory reflection trigger #2: pre-registered no-op moves gate by >>2σ)
**Scope:** V205's crisis "high-water" of −$8,533 (+14,277σ vs V204), and the V172 architectural stack it was framed against.

This document was prompted while attempting to pre-register V206 per
the brief's plan to "audit V170 per-regime IC weighting in isolation."
Code inspection revealed the V170 path is dead under `v93_baseline`,
which forced a wider audit and surfaced that **V205 itself was a
no-op functionally** despite its 14,277σ gate move. The reflection
trigger (#2) is unambiguous; the skill requires writing this
before any new V###.md.

---

## 1. The V172 architectural stack is mostly runtime-inert under v93_baseline

Direct verification, file-by-file:

| Layer | Gate flag | Default | Set in any preset? | Active under v93_baseline? |
|-------|-----------|---------|--------------------|-----------------------------|
| V156 strategy_selector | `strategy_selector_enabled` | `False` (`getattr` fallback) | **No** | **No** |
| V157 `_REGIME_SIGNAL_WEIGHTS["CRISIS"/"TREND"]` dispatch | gated by `_strategy_selector is not None` AND `regime_signal_weighting` | both `False` | **No** | **No** |
| V166 live signal normalization | `live_signal_normalization` | `False` | **No** | **No** |
| V170 per-regime IC weighting | `per_regime_ic_weighting` AND `self._regime_ics` populated | `False`; `update_regime_ics` has zero callers in repo | **No** | **No, doubly inert** |
| V172_pruned excluded_signals | `excluded_signals` | `None` | **No** | **No** |

Verification commands run:

```
grep -rn "strategy_selector_enabled\|regime_signal_weighting\|per_regime_ic_weighting\|live_signal_normalization" omega/ projects/ scripts/ data/ docs/training/ --include="*.py" --include="*.yaml" --include="*.json"
```

Only matches are the call-sites in `strategy.py` and one docstring. **No preset, no project config, no env-set training script, and no snapshot fixture turns any of these on.**

The training-log INFO line `"V156 strategy_selector initialised"`
(strategy.py:656) is absent from both `/tmp/v204_v172_crisis_s42_training.log`
and `/tmp/v205_crisis_training.log`. Strategy_selector was None
throughout both runs, so `_apply_regime_signal_weights` (the sole
consumer of `_REGIME_SIGNAL_WEIGHTS`) never executed.

**Implication for V205's narrative.** The V205 entry claims that
emptying `_REGIME_SIGNAL_WEIGHTS["CRISIS"]` removed the CRISIS damping
of trend-following signals, letting the strategy short into the
2022 H1 crash and recovering $14,277 vs V204. That claim cannot be
true — the dict was never read in either run. The V172 "architecture
stack" V204's revert restored is **code-present, runtime-absent.**

## 2. Yet the gate moved 14,277σ. The eval has hidden state coupling.

This is exactly the failure mode REFLECTION_V202 named (60–70%
per-trade PnL drift on pre-registered no-ops):

| Run | Snapshot | Seed | Trades | PnL | Sole code delta |
|-----|----------|-----:|-------:|----:|-----------------|
| V204 (`98a0b26`) | crisis_2022h1 | 42 | 60 | −$22,809 | V172 baseline restoration |
| V205 (`db60417`) | crisis_2022h1 | 42 | 38 | **−$8,533** | `_REGIME_SIGNAL_WEIGHTS["CRISIS"] = {}` |

The diff that "caused" $14,277 of crisis PnL movement is a
mutation of a dict that is never iterated. Trade-count drop 60→38
isn't decision-side; it's downstream of perturbed state. Most
plausible vectors (not narrowed yet):

- `data/decision_traces/` rotation / RNG advancement off persisted state
- `memory.db` carryover between runs (run timestamps differ; episodic store reads recent entries)
- Cycle-level metric file (`/tmp/v###_metrics.jsonl`) used as seed-mixer downstream
- Dict-iteration order side effect: a 20-line cosmetic edit anywhere in `strategy.py` shifts module hash → import order → cached random.Random state

V202 reflection already established this pattern on V199→V200
trend (+$46 aggregate but 64% of identically-IDed trades had
non-zero per-trade PnL drift). Same shape here, larger amplitude.

**The +$14,277 "crisis high-water" claimed by V205 is not
attributable to the pre-registered code change.** Treat it as
noise from an uncharacterised hidden-state source until proven
otherwise.

## 3. Subsystem audit — V199 through V205

| Version | Claimed change | Subsystem hit | Actually executable under v93_baseline? |
|--------:|-----------------|----------------|-------------------------------------------|
| V199 | Carry signal + carry sub-strategy | `crisis_short_bias` / carry injection | Partially — carry path runs; `crisis_short_bias` gated by flag |
| V200 | HMM-gated suppressor on V199 carry | same | same (gate flags inactive) |
| V201 | Strip `crisis_short_bias` threshold ×0.6×0.6 amps | `crisis_short_bias` entry | **No** if `crisis_short_bias` flag off (need to verify) |
| V202 | Strip `crisis_short_bias` size ×1.3/×0.5 + restore Kelly | `crisis_short_bias` sizing | **No** if flag off |
| V203 | Multi-seed variance estimate | (methodology) | n/a |
| V204 | Revert strategy.py to V172 baseline | All V173+ ablations | Removes code that was already unreachable |
| V205 | Strip `_REGIME_SIGNAL_WEIGHTS["CRISIS"]` | V157 regime weights | **No — dead path** |

The pattern that V202 reflection identified ("two subsystems in four
versions, both `crisis_short_bias`") extends: **at least V204 and V205
both touched code paths that don't execute under the standard run
config.** V202's diagnosis was right and we kept doing it.

**Provisional high-water rescissions pending eval-stability run:**
- Crisis high-water V205 −$8,533 — **provisionally rescinded.** Not
  attributable to V205's change. Crisis ceiling reverts to V204's
  −$22,809 or whatever the noise-floor study lands on.
- Trend high-water V204 +$22,105 — **also under suspicion.** V204's
  revert removed code that wasn't running; the +$22,105 vs V203's
  trend number may also be noise-driven. Trend ceiling needs a
  multi-seed re-measurement before any future claim cites it.
- Recent high-water — unchanged status (V199 +$2,478 already flagged
  by V202 reflection).

## 4. Revert-and-branch is no longer enough

V202 reflection's revert-and-branch recommendation (which produced
V204) was the right call structurally, but it implicitly assumed the
V172 stack's code-presence was the same as runtime-activeness. It
isn't. Reverting to V172 + leaving every advertised feature flag off
yields a code-equivalent of "execute conviction filter + paper
trading + nothing else" — i.e. a much smaller surface than the
4,000-line file suggests. **Any further architectural reverts are
cosmetic unless paired with an explicit decision about which flags to
turn on.**

The actual binding constraint on Victoria right now is: **we have
been running a stripped-down conviction filter and reading dict-edit
noise as architectural signal for the last 6 versions.** No amount
of code archaeology fixes that.

## 5. Untouched dimensions — the real surface

Cataloguing from a *runtime* perspective, not a code-presence one:

**Flag-gated machinery that has never been turned on in a gate run** (each is a candidate bet, but each must be characterised before being used):
- `strategy_selector_enabled` (makes V156 / V157 dispatch actually fire)
- `regime_signal_weighting` (the V157 dict consumer)
- `per_regime_ic_weighting` + populating `update_regime_ics(...)` from `signal_audit.py`
- `live_signal_normalization` (V166)
- `crisis_short_bias` (V202's target — needs to confirm whether its flag is on or off in v93_baseline)
- `decision_embeddings`, `temporal_memory`, `adaptive_combiner` (V103/V106 era)
- `ricci_sizing`, `orc_stress_reduction`, `geodesic_crash_distance`, `fiedler_conviction_modulation` (V97/V98 era)

**Dimensions still untouched from REFLECTION_V202's list** (none have been tried in V203–V205):
- Per-regime trail multipliers / time-stop / R-multiple partials / MAE adaptation
- Defensive abstention (skip crisis trading entirely, skip crisis shorts only)
- Volatility-targeted sizing, confidence-weighted sizing, per-symbol size caps
- Second crisis snapshot (`snap_crisis_2020q1.json`, still unused)
- Multi-snapshot ensemble, holdout validation

**New from this reflection:**
- Eval-stability *fix*. The hidden-state coupling is now a measured
  property of two consecutive reflections; the next version that
  doesn't address it is wasted.
- Snapshot-of-state at run start, byte-comparison between
  consecutive runs of identical seed+config, to *locate* the
  state leak (memory.db row count? decision_traces append-only?
  metrics file mode?).

## 6. Concrete actions (commit-able)

1. **Eval-stability measurement (mandatory before V206 hypothesis lands).**
   Run a literal no-op change against the V204 baseline (add a
   comment to `strategy.py`), execute `python3 scripts/run_training.py
   --version v205_repro --cycles 200 --snapshot crisis --seed 42`,
   compare PnL. Whichever it lands near (−$22,809 V204 or −$8,533
   V205) discriminates seed-coupling from genuine causation.
   Background; do not poll.

2. **State-leak audit.** Before/after the v205_repro run, diff:
   - `state.db` (sqlite, dump rowcounts per table)
   - `memory.db` (episodic/semantic/working memory row counts)
   - `/tmp/v###_metrics.jsonl` (if pre-existing, training accumulates)
   - `data/decision_traces/` (append-only path)
   - filesystem inode of any pickled model artifact loaded by `StrategyNode.__init__`
   Identify which mutates across runs.

3. **Flag-activation roadmap.** Before V206 is pre-registered, pick
   ONE flag from §5's list whose activation has a defensible
   directional hypothesis, document expected behaviour, and use that
   as V206's bet. The flag flip is the change; the dict contents are
   secondary.

4. **Amend the V206 revert commit message.** Current message says
   "V157 CRISIS strip too coarse" which implies the strip did
   something. Rewrite to "revert V205 — V157 dict path inert under
   v93_baseline; see REFLECTION_V205".

## 7. Branch decision for V206

V206 is **NOT** an audit of V170 per-regime IC weighting in
isolation. That bet, as briefed, executes a no-op. V206 must
either:

- **V206a** = enable `strategy_selector_enabled` (and `regime_signal_weighting`) and measure whether the V157/V158 dict the codebase has carried since V148 actually does what the docstrings claim, OR
- **V206b** = the eval-stability + state-leak audit from §6 actions 1–2, treated as a methodology version with no strategy change. Lock down the noise floor before any further code edits, so the next 6 versions don't repeat V199–V205.

**Recommendation: V206b first.** Three consecutive reflections
(V202, this one, and whatever follows V206a if it lands amid noise)
will say the same thing if we don't measure the noise floor
empirically. V206b's deliverable is a one-number σ estimate per
gate, a state-leak source identified or ruled out, and a
methodology commit. V206a then becomes V207 with a known
significance threshold.

## References

- REFLECTION_V202.md — methodology for ID-aligned trade comparison and noise-floor reasoning. Same disease, different surface.
- V204.md, V205.md — to be cross-referenced and have their high-water claims annotated `[provisional — see REFLECTION_V205]` after this commits.
- strategy.py:650-658 (strategy_selector init), 1623-1631 (V157 dispatch), 1035-1051 (V170 dispatch) — the three dead gates.
- features.py:720 (`v93_baseline` preset) — confirms the flags are absent.
- /tmp/v204_v172_crisis_s42_training.log, /tmp/v205_crisis_training.log — neither contains the "V156 strategy_selector initialised" line.
