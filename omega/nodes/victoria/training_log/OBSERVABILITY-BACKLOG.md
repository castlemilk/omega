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

### ⚠️ V214 lesson — "subsystem-OPEN" claims need the same runtime-gate check as "subsystem-closed" ones

V207b wrongly *closed* concurrency as a determinism channel by grepping only
`strategy.py` for `ThreadPoolExecutor` (zero hits) and missing the indirect import
chain. A prior V214 attempt then committed the **inverse** error: it *opened*
`omega/core/dag_pipeline.py`'s `ThreadPoolExecutor` as "the real channel" **without
checking whether that code runs in the eval at all**. It does not — `DAGPipeline`
is gated behind `if os.getenv("DAG_PARALLEL")` (`victoria_node.py:927`), and
`DAG_PARALLEL` is never set anywhere (run_training, check_determinism, Makefiles,
.env, live shell — only *reads* exist). The serial eval path has zero in-process
concurrency. A canonical-order "fix" there would have been theatre on dead code.

**Rule:** before naming any subsystem as the cause OR the cure of a behavior,
confirm it actually *executes* under the eval condition — check the env flag /
feature flag / import that gates it, not just that the code exists. The V213
**subsystem wiring banner** does this for the 5 audited subsystems; the cheap delta
is to **add the DAG path (and `DAG_PARALLEL`) to the banner's probe list** so a run
log says `dag_parallel: off → serial path` and no future attempt can assert the DAG
is live without contradicting cycle-0 output. (Queued as V215 #7 below.)

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

### ✅ V214 delta #3 — per-cycle mode-switch trace  (effort: S)
`scripts/run_training.py` cycle loop now writes
`data/{version}_mode_transitions.jsonl` — one line per regime/selector-mode
transition: `{cycle, prev, new, regime, bull_prob, bear_prob, bull_above,
bear_above}`. The V212 diagnosis ("the selector arms a mode one cycle off between
identical runs") took a manual `signal_contribs.jsonl` bisect; it is now a 2-file
align. Always-on, try/except-guarded.

### ✅ V214 delta #4 — per-cycle signal-values fingerprint  (effort: M)
`scripts/run_training.py` cycle loop now writes
`data/{version}_signal_fingerprint.jsonl` — one line per cycle: `{cycle, regime,
fp (sha1 of sorted full-precision signal scalars), n, values:{name→value}}`.
`scripts/fingerprint_diff.py A.jsonl B.jsonl` reports the **first cycle** where two
same-seed runs diverge + the exact signals that moved (sorted by drift magnitude) +
how long each stays split. This is the discriminator that localizes channels like
the V213 cross-sectional-demean wobble — would have collapsed the V207–V211 arc to
one diff. **This is V214's primary deliverable.**

## Queued (V215+ candidates)

### V215 #5 — determinism gate inside the gate runner  (effort: M)
Promote delta #2 from a standalone script into `run_training.py`'s gate runner:
a `--check-determinism` flag (or auto-trigger when `--seed` is set) that runs the
2-replicate pair and writes a `determinism: {spread, verdict, floor}` block into
`{ver}_results.json`. Makes every gated run self-certify its own noise floor; no
high-water claim can be made on a run whose determinism block says FAIL.

### V215 #7 — add DAG/`DAG_PARALLEL` to the subsystem wiring banner  (effort: S)
Extend `run_training.py`'s startup wiring banner (V213 #1) to probe the parallel
DAG path: print `dag_parallel: off → serial signal path` (or `ON → DAGPipeline`)
based on `os.getenv("DAG_PARALLEL")`. Closes the "subsystem-OPEN claim without
runtime-gate check" gap (V214 lesson above) — makes "is the DAG live?" a cycle-0
grep so no future version can assert it as a channel without contradiction.

### V215 #6 — async-order lint / runtime assertion  (effort: L)
A debug-mode check (lint rule + optional runtime assert) that flags any
`signals.items()` / `.values()` float reduction not preceded by a `sorted(...)`.
The V213 channel was a `sorted()` that V211 applied in `strategy.py` but not in
`signal_generation.py`'s copy of the same aggregation — a lint would have caught
the asymmetry. Larger effort (needs an AST rule); lowest priority.

### V216 #8 — backtest wall-clock-read tripwire (sizing/exit layer)  (effort: S)
**Surfaced by V215.** The signal-fingerprint instrument proves the *signal* layer is
hermetic, but V215's residual determinism FAIL was a wall-clock read in the *sizing*
layer (`core/risk_manager.py:316` `time_risk_multiplier(now=None)` →
`datetime.now(UTC)` → 50% size cut in 14:30–15:30 UTC). Add a lightweight tripwire:
when `OMEGA_FROZEN_CACHE=1`, log (or assert) any `datetime.now`/`time.time` call site
reached during the cycle loop in `strategy.py`/`risk_manager.py`/`paper_trading.py`
that is **not** passed a bar timestamp. Would have flagged `time_risk_multiplier(now=
None)` at cycle 0 instead of after a 4-replicate sleep=10 run. Pairs with the
fingerprint (signals clean → any residual is *here*). Ship with V216's bar-time fix.

## Shipped in V216  ✅

- **#8 sizing-layer wall-clock tripwire** — `scripts/check_no_wallclock.py`. AST-based
  static checker: fails preflight if any sizing-path module (`strategy.py`,
  `core/risk_manager.py`) reads `datetime.now`/`utcnow`/`time.time` without a
  `# wallclock-ok: <reason>` annotation. AST (not grep) → never false-positives on
  comments/docstrings. Wired into `check_determinism.sh` preflight. **Would have caught
  the V215 `time_risk_multiplier` leak (and the V207–V214 wall-clock chase) at cycle 0**
  instead of after a 4-replicate sleep=10 run. Realizes the spirit of the queued
  "sizing-layer wall-clock tripwire" above (chose static-checker over runtime monkeypatch
  because the bar-time fix intentionally retains live `datetime.now` fallbacks — the
  annotation encodes "guarded" auditably).

## Shipped in V217  ✅

- **#1 per-field full-precision fingerprint hash** — `scripts/run_training.py` now emits
  `data/{version}_per_field_fingerprint.jsonl`: one line per `(cycle, signal_name)` with
  `value_hex = struct.pack('!d', value).hex()` (IEEE-754 double, bit-exact). New tool
  `scripts/per_field_diff.py` names the first divergent `(cycle, signal_name)` between two
  same-seed replicates. **Closes the V216 dead-end** where `fingerprint_diff.py` reported
  `(fp differs but no scalar value differs)` because the `values` dump rounds to 12 places:
  the per-field IEEE hash exposes any sub-12th-bit drift and names the field. Guaranteed to
  localize — `fp` is a pure function of exactly those per-field values, so a `fp` mismatch
  with matched key-sets means at least one field's bits differ by construction. Effort: S.

## Queued (V218+)  📋

- **`size_ratio.jsonl` default artifact (MED).** The r1/r4 trade-CSV size-ratio diff (median
  0.500) localized the V215 sizing channel. Make it a per-run default (size ratio binned by
  cycle vs a baseline run) for future sizing-channel bisects. Effort: S–M (post-run trade-CSV
  alignment). Carried from V216.
- **#6 transitive subsystem-closure runtime probe (MED).** Carried from V216.
- **#7 DAG / `DAG_PARALLEL` in the startup wiring banner (S).** Carried from V215/V216 — make
  "is the DAG live?" a cycle-0 grep so no future version can assert it as a channel without
  contradiction.

## Shipped in V215  ✅

- **Frozen-cache HTTP enforcement guard** (the strongest queued obs delta; supersedes
  the spirit of #5's "self-certify"). `run_training.py` monkeypatches
  `urllib.request.OpenerDirector.open` when `OMEGA_FROZEN_CACHE=1` → blocks + logs +
  counts all outbound HTTP; count in `results.observability.http_blocked_count`,
  per-URL log in `data/{ver}_http_during_backtest.jsonl`. **Import-style-agnostic**
  (catches `from urllib.request import urlopen` too, e.g. `whale_flow.py`). Caught a
  leak **far broader than V214's 3 signals** (2,637 calls/run across ~25 endpoints).
  **Would have prevented the entire V207–V214 determinism hunt.** With network provably
  blocked, any residual spread is *definitionally non-network* — the discrimination
  that localized the V215 sizing-time channel in one run.
- **Process rule:** fingerprint-first-bisect is the default first tool on any
  determinism FAIL (signal-vs-non-signal); the HTTP guard proves network-vs-non-network.
  Together they bisect the channel space in one N=4 run.

## How to use this file

1. During a reflection's observability-gap audit, add new gaps as `V###+1 #N`
   entries here with effort (S/M/L) and a one-line "what it would have caught".
2. When a version ships, move the 2 it shipped to **Shipped** with a ✅ and the
   file/flag it lives in.
3. Never let the queue imply "covered" — if a version bounds its own coverage
   (sampled, capped, no-retry), say so in its V###.md, not silently.
