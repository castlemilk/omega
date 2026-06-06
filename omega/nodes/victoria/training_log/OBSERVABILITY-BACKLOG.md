# Victoria training — observability backlog

> Required reading for the **observability-gap audit** step of every reflection
> (see `.claude/skills/victoria-training-loop/SKILL.md` → Reflection). Each
> training version asks: *"What instrumentation would have caught this sooner?
> What's the next blind spot?"* — answers land here, get prioritised, and the
> two cheapest/highest-impact ship with that version.

## The recurring failure mode

The V148→V212 history wasted whole versions because the eval could not answer
basic questions about itself:

| Arc | Versions burned | What was missing |
|-----|-----------------|------------------|
| V148–V202 | 4+ versions tuned subsystems that were **runtime-inert** (flag undeclared → `getattr→False`; or `ImportError` silently caught) | A startup banner listing every "active" subsystem with a live wiring probe. |
| V207a–V211 | 4 versions hand-hunting noise sources via manual cycle-1 bisects | An automatic same-seed byte/PnL-diff between consecutive runs, built into the gate runner. |
| V212 | A determinism break found **only** via a hand-written 4-replicate diagnostic | N≥2 replicates per gate run **by default** + an automatic spread report. |

The theme: instrumentation that turns a multi-version manual investigation into a
one-command / one-grep answer.

## Shipped

### ✅ V213 delta #1 — subsystem wiring banner  (effort: S)
`scripts/run_training.py` startup now prints, per audited subsystem, the flag's
declared/value state **plus a live wiring probe** (is the flag a real dataclass
field? does the module import?). Grep a run log for `SILENTLY INERT` or
`UNDECLARED` to catch the V148-V202 inert-subsystem class of bug at cycle 0.
Covers `strategy_selector`, `regime_signal_weighting`, `mode_transition_blend`,
`bayesian_regime`, `hmm_regime`. (Note: on first run it correctly reports
`regime_signal_weighting: UNDECLARED` — that flag is read at `strategy.py:1638`
but never added to `VictoriaFeatures`, so the V157 regime-weight path is a silent
no-op today. That is itself a finding the banner surfaces.)

### ✅ V213 delta #2 — auto-replicate determinism check  (effort: S/M)
`scripts/check_determinism.sh GATE [N] [FEATURES] [VPREFIX] [FLOOR] [SLEEP]` runs N
replicates as **separate processes** (the gold standard for exposing
id()/async-order non-determinism), restores run-written disk state between
replicates (Fix-B isolation), and emits one `DETERMINISM: PASS|FAIL spread=$X`
line + a `summary.json`. This is the instrument the V207–V211 arc lacked. Doubles
as the V213 audit harness and the cheap pre-audit fix-validation tool. **The
`SLEEP` knob (added mid-V213) earned its keep immediately:** sweeping it
(0/3/10) is what exposed that the selector channel is *sleep-triggered*, killing
the V213 sort hypothesis.

### ⚠️ V213 cross-sleep lesson — measure determinism at the CANONICAL condition
V213 nearly shipped a wrong fix because the audit ran at **sleep=0** (chosen for
speed) while every prior version's eval ran at **sleep=10**. At sleep=0 the
target channel is dormant, so the sort *looked* load-bearing ($18,720→$132); the
canonical sleep=10 control showed it FAILS with or without the sort. **Rule:
determinism claims must be made at the same eval condition prior baselines used —
sleep is a determinism variable here, not just wall-clock.** Always run the
sleep=10 control before concluding. (Codified in the skill's reflection section.)

## Queued (V214+ candidates)

> **V213 promoted #3 and #4 to V214's critical path.** V213 relocalized the
> selector non-determinism to a **sleep/async-timing channel** (dormant at sleep
> ≤3s, active at sleep=10, flips actual entries 81↔83). Localizing it needs
> exactly #3 (mode-switch trace) + #4 (signal-values fingerprint) to find the
> first sleep=10 cycle where two runs diverge. These are no longer "nice to
> have" — they are the V214 tooling.

### V214 #3 — per-cycle mode-switch trace  (effort: S)
When `strategy_selector` changes mode, emit a structured line to
`data/{ver}_mode_switches.jsonl`: `{cycle, from, to, bull_prob, bear_prob,
regime_label, bull_above, bear_above}`. The V212 diagnosis ("the selector arms a
mode one cycle off between identical runs") took a manual `signal_contribs.jsonl`
bisect; with this it is a 2-file `diff`. **Highest-value queued item** — it
directly instruments the exact mechanism V213 is fencing.

### V214 #4 — per-cycle signal-values fingerprint  (effort: M)
Each cycle, hash the canonically-sorted `signal_values` vector (and the
post-demean composite vector) to `data/{ver}_sigfp.jsonl`. Diffing two runs'
fingerprint streams pinpoints the **first cycle** where signal computation
diverges — which is exactly what localizes channels like the V213
cross-sectional-demean wobble. Would have collapsed the V207–V211 arc to one diff.

### V214 #5 — determinism gate inside the gate runner  (effort: M)
Promote delta #2 from a standalone script into `run_training.py`'s gate runner:
a `--check-determinism` flag (or auto-trigger when `--seed` is set) that runs the
2-replicate pair and writes a `determinism: {spread, verdict, floor}` block into
`{ver}_results.json`. Makes every gated run self-certify its own noise floor; no
high-water claim can be made on a run whose determinism block says FAIL.

### V215 #6 — async-order lint / runtime assertion  (effort: L)
A debug-mode check (lint rule + optional runtime assert) that flags any
`signals.items()` / `.values()` float reduction not preceded by a `sorted(...)`.
The V213 channel was a `sorted()` that V211 applied in `strategy.py` but not in
`signal_generation.py`'s copy of the same aggregation — a lint would have caught
the asymmetry. Larger effort (needs an AST rule); lowest priority.

## How to use this file

1. During a reflection's observability-gap audit, add new gaps as `V###+1 #N`
   entries here with effort (S/M/L) and a one-line "what it would have caught".
2. When a version ships, move the 2 it shipped to **Shipped** with a ✅ and the
   file/flag it lives in.
3. Never let the queue imply "covered" — if a version bounds its own coverage
   (sampled, capped, no-retry), say so in its V###.md, not silently.
