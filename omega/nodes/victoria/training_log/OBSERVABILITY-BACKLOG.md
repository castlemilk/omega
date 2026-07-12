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
- **#9 `size_ratio.jsonl` automated per-cycle sizing artifact (MED).** Surfaced by the
  V215/V216 sizing wall-clock channels: there is still no first-class per-cycle record of the
  applied size multiplier (`time_risk_multiplier` × damp × bar-time fence). A `size_ratio.jsonl`
  (cycle, ticker, base_size, applied_multiplier, multiplier_sources) would make "why did this
  replicate trade 46 vs 70?" a one-grep answer instead of a code-read. Queued (not shipped this
  kickoff — V218 shipped the IC-wiring probe + matrix-status instead). Ship with a future
  sizing-touching version.

### Surfaced by V220 — the eval peeled to the trade-PnL layer (SHIP WITH V221)

V220 locked the entry-flip channel (trend trade count now 26/26) and exposed a
**sizing/exit PnL-magnitude channel**: same 26 trades, $2,851 spread. The blind spot
is that every existing fingerprint (V214 cycle-1 signals, V217 per-field IEEE-754)
stops at the **signal layer** — a channel that emerges only in position sizing /
exit-price / PnL accounting is invisible until it flips a trade count or blows up a
spread. V221 bisects it; these instruments make the bisect (and the next magnitude
channel) self-naming.

- ~~#14 trade-ledger diff on the magnitude-FAIL path~~ → **Shipped in V222 ✅**
  (`check_determinism.sh` post-verdict block): when verdict=FAIL AND
  trade_range=0 AND N≥2, auto-runs `trade_field_diff.py` on the r1/r2 pair,
  tees to the run log + `$OUT/trade_field_diff.txt`. Validated against the
  V221 pre-fence FAIL pair — reproduces the hand-bisect (c5 ETHUSDT `size`)
  byte-for-byte.
- **#15 widen `check_no_wallclock.py` AST scan (M) — queue.** Currently scans only the
  2 declared sizing modules; the V221 channel may live outside them (exit-price interp,
  slippage/fee accrual). Widen to the full strategy/exit path.
- **#16 channel-genealogy line in the determinism summary (M) — queue.** Each summary
  records which prior fences are active (BLAS pin, fsum, bar-time, HTTP guard) and
  which layer the residual sits in (signal vs trade) — so "which peel are we on?" is
  in the artifact, not the log archaeology.
- **#17 per-trade PnL-contributor decomposition (L) — queue.** Log size × price-move ×
  side − fees per trade, so a magnitude divergence points to *which factor* drifted.
- **#18 per-ticker PRE-demean composite fingerprint (S) — queue (surfaced V221).** The
  aggregate `per_field_fingerprint.jsonl` records `basic_signals.value` POST-demean, where
  mean(composites) ≈ 0 by construction — an O(0.1) per-ticker presence flap read as "sub-ulp"
  for a whole session. Fingerprint `(cycle, ticker) → raw_composite hex + sub-signal name set`
  so a presence flap (a signal entering/leaving one ticker's composite) is named directly.
- **#19 epsilon-guard amplifier tripwire (S) — queue (surfaced V221).** AST-grep for
  `else 1e-N` std/var fallbacks followed by division (the `funding_rate.py:137` class —
  constant input + tiny-epsilon guard = sub-ulp residue amplified to O(1) output). Known
  sibling: `geometry/market_manifold.py:424`.

### Surfaced by REFLECTION_V237 (2026-07-04 — the $0-separator era's own gaps)

Ship-with-V238 (the reflection's 2 cheap/high-impact picks, listed here for
tracking): (a) `omega/tools/forensics/separator_lab.py` — shared loader for
the pooled walk-forward trades + snapshots with `mann_whitney`/`terciles`/
`bootstrap_ci`, so each separator is a conditioning function, not a rewrite;
(b) committed per-trade conditioning CSV (window, symbol, entry bar, PnL,
ER20, VR, β60, C60) so future separators and the Section-4 surface reuse
identical rows.

- **#20 frozen-series freshness/gap validator (M) — SHIPPED V238** as the
  freeze acceptance gate (`scripts/check_frozen_series_coverage.py`): per-series
  per-window FULL/PARTIAL/ABSENT report + md5 freeze-integrity check; strict
  mode wired into `prepare_session.sh` (opt-in `OMEGA_CHECK_FROZEN_SERIES=1`)
  and as the v238_wf_grid.sh preflight. A silent gap in a frozen non-price
  series was the feed build's new runtime-inert-subsystem class; the validator
  makes it a one-grep answer.

### Surfaced by V238 (frozen-series feed build, 2026-07-04)

- **#22 composite-membership probe (S) — SHIP-NEXT.** V238 discovered a
  V213-class silent-inertness variant one layer deeper than the wiring banner:
  a signal can be **instantiated, flag-ON, and injected into the per-ticker
  signal dict** yet still be **invisible to the composite**, because
  `_ic_weighted_composite`/`_balanced_composite` only consume keys ending
  `_signal` (+ `sma_crossover`). The V115 `whale_flow` member names
  (`oi_rate_of_change`, `stablecoin_velocity`, `exchange_net_flow`) and 3/4
  GDELT `geo_*` keys have been fed to `ts` since inception but **never reached
  a composite** — live or frozen. The startup banner says "ACTIVE" (it IS
  wired into `ts`); the composite silently drops it. **Instrument:** a cycle-0
  probe that intersects the set of injected `ts` keys against the composite's
  `endswith("_signal")` filter and logs any key that is injected-but-dropped
  (`COMPOSITE-INVISIBLE: <key>`). Grep-catchable, ~15 lines. V238 fixed
  whale_flow by aliasing to `*_signal`; the GDELT `geo_event_intensity` /
  `geo_regime_shift` / `sanctions_signal` keys remain composite-invisible and
  are queued for the V240+ GDELT feed build.
- **#23 per-signal frozen-coverage-at-decision log (S) — queue.** The
  freeze-gap validator reports coverage per *window*; it does not report which
  signals were actually NaN-skipped *at each entry bar*. A per-trade column
  (which of the six frozen signals were present vs out-of-range at entry) would
  let the Section-4 surface condition on "info-set completeness" and catch a
  PARTIAL-coverage window silently degrading a signal for its first N cycles.
- **#21 entry/exit PnL attribution split (M) — queue.** MAE/MFE-based
  decomposition of per-trade PnL into entry-timing vs exit-timing loss, from
  columns already in every trades CSV. Every recent-targeted bet so far has
  been entry-side; this names whether the next one should be.

### Surfaced by the 2026-06 strategic audit (`STRATEGIC_AUDIT_2026-06.md`)

- **#10 "every flag does something" preflight (MED) — the meta-fix for the inert-subsystem
  failure mode.** The V148–V218 recurring waste (strategy_selector inert V199–V211,
  `regime_signal_weighting` UNDECLARED, V170 IC never wired, V218.B IC subsystem inert) is the
  same class every time: a flag is added, gated, never declared/wired, `getattr→False` silences
  it, and nothing asserts it changed anything. The V213 banner *detects* this but is reactive
  (prints a warning a human must read). Promote it to an **enforced preflight**: for each
  declared feature flag, run 1 cycle ON + 1 cycle OFF at a fixed seed and **assert the
  fingerprints differ** (or the flag carries a `# no-op-ok` annotation). A flag whose ON/OFF grid
  is byte-identical FAILS preflight. This is the dual of the V217 determinism lesson ("a fix
  isn't done until the ON/OFF grid is byte-*identical*") → "a feature isn't wired until its
  ON/OFF grid is byte-*different*." Would have caught all of the above at cycle 0. Reuses the
  V217 per-field fingerprint + `check_determinism.sh`. Effort M.
- **#11 committed-macro-cache integrity check (S) — eval-integrity blocker.** V218 found the
  "hermetic" V217 baseline depended on an **uncommitted** `data/macro_cache.db`
  (`V218-matrix.md:188`); a no-op control diverged from the README baseline by >$6k. Add a
  cycle-0 preflight that asserts `macro_cache.db`'s md5 matches a committed manifest (same
  freeze discipline as the snapshots / `frozen_advanced_signals.json`). Until this lands, no
  cross-version PnL comparison is reproducible from a clean checkout. Effort S. **Ship first** —
  it is upstream of every other measurement.
- **#12 composite-weight artifact (S).** The `signal_contribs.jsonl` already records per-signal
  `weight`, but nothing asserts/aggregates it: today every weight is `1.0` (IC-weighting inert)
  and no run flags that. Add a cycle-0 line — `COMPOSITE: equal-weight (IC inert)` vs
  `IC-weighted (N signals)` — so "is the composite actually weighted?" is a grep, not a code
  read. Pairs with the V218 IC-INERT probe. Effort S.

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

- **#10 macro-cache health tripwire (S, HIGH-IMPACT).** Surfaced V218: the `macro_cache` table
  is all `date='__failed__'`/`value=0.0` (FRED warm-up silently failing) → the eval has been
  running with **VIX=0, yields=0, dollar index=0** for an unknown number of versions. Add a
  cycle-0 preflight that FAILS (or loudly warns) if any `macro_cache.value` is 0/`__failed__` —
  the macro analogue of the IC-WEIGHTING-INERT probe. Would have caught a silent input outage
  that compromises every macro/regime-derived signal.
- **#11 deterministic cache manifest (MED, HIGH-IMPACT).** Surfaced V218: `macro_cache.db` +
  `funding_rate_cache` are warm-up-overwritten and were never frozen, so the V217 "hermetic"
  baseline was reproducible only within its own session (a committed-state no-op control diverged
  by >$6k / 16 trades). Freeze both like the OHLCV snapshots (a committed `frozen_macro.db` +
  `frozen_funding.json`) and check an md5 manifest at cycle 0. Makes cross-version PnL comparison
  actually valid.
- **#12 frozen funding feed for carry (S).** Surfaced V218.A: carry plumbing is untestable
  because funding is absent from replay snapshots and live Binance is (correctly) HTTP-blocked.
  Add `funding_rate` to the frozen snapshots or a `frozen_funding_feed.json` (analogous to
  `frozen_advanced_signals.json`) so carry/derivatives signals can be exercised in backtest.

## Shipped in V221  ✅

- **#13 `scripts/trade_field_diff.py` — trade-level IEEE-754 ledger diff (S)** — aligns two
  replicates' trades by `(cycle, symbol, side, occurrence)`, hex-encodes every numeric ledger
  field (`struct.pack('!d', v)`), reports trade-set drift + the first divergent (trade, field);
  wall-clock fields excluded by construction. **Named both V221 channels:** the c4 ARBUSDT
  `size` 5000↔6666 (= `budget/N` 3:4 → demean selection channel) and, post-fence, the c5
  ETHUSDT `size` divergence whose contribs trace exposed the funding presence flap. The signal
  layer read "clean" both times — exactly the blind spot this tool was queued for.

## Shipped in V218  ✅

- **IC-weighting wiring probe (S)** — `run_training.py`. Two parts: (1) the startup banner now
  probes `per_regime_ic_weighting` (prints `UNDECLARED — silent no-op` on main); (2) a new
  post-strategy-build probe logs `IC-WEIGHTING INERT: _signal_ics empty` whenever the IC-weighted
  conviction path is a no-op. **Caught the V218.B blocker at kickoff** instead of after a wasted
  version: the entire IC-weighting subsystem (pooled *and* per-regime) is runtime-inert in the
  eval because `update_signal_ics` has zero callers in the training path, so a per-regime-IC bet
  was unrunnable. Exactly the V148–V202 "runtime-inert subsystem" class, now a cycle-0 grep.
- **`scripts/v218_matrix_status.sh` (S)** — single-pane health monitor for N concurrent matrix
  cells (PID liveness + last DETERMINISM verdict + gate-completion count + log tail). Made
  3-worktree parallel runs observable without per-cell manual `tail`/`pgrep`.
- **`SNAP_OVERRIDE` env in `check_determinism.sh` (S)** — substitute a gate's snapshot at
  invocation time (cell E's 2020q1 crisis run) with zero code diff; reusable for any future
  snapshot-generalisation cell.

## Queued from REFLECTION_V241 (2026-07-12 — reasoning-layer refutation)

The V241 tracer measured *activity* (99.6% intervention) but not *quality* —
phase 0 could not distinguish "active and useful" from "active and random."

### V244 #1 — counterfactual drop scorer  (effort: S) — **PREREQUISITE for any reasoning revisit**
Join a fill pass's `*_reasoning_trace.jsonl` drops against the ALREADY-EXISTING
baseline (OFF-arm) trades.csv per window and score the realized PnL of the
trades the layer would have vetoed. The OFF cells predate the fill, so V241's
verdict was computable ~4h before the grid ran — this turns any future
reasoning variant into a $0 pre-grid separator proof (V234 rule). A veto-only
variant may only be pre-registered if the drop set shows negative-PnL skew here.

### V244 #2 — intervention→PnL attribution ledger  (effort: M)
Per-window Δ attribution to drops vs scale-downs (extend the
`trade_field_diff.py` join over ON-vs-OFF ledgers keyed by (cycle, symbol,
side)). Without it, V241's −$18.7k trend window (`snap_wf_20201226`) cannot be
attributed to a vetoed winner vs a scaled loser without manual diffing.

### V244 #3 — fill cost predictor  (effort: S)
Calls/window = candidate-density driven (observed 17–26). A manifest-time
estimate (candidates per cycle × cycles × call cadence) prices a fill pass
before committing wall-clock; V241's 4h16m was estimated only from the phase-0
window's pace.

### Shipped with V241 ✅ — inertness tracer + intervention report  (effort: S)
`OMEGA_REASONING_TRACE` JSONL in `reasoning_layer.py` (per-call candidates
in/out, drops, scale-downs, cache-hit, latency) +
`scripts/v241_intervention_report.py` (per-window intervention rate, INERT /
VETO-EVERYTHING / ACTIVE verdict). Standing instrument for any LLM-in-loop
subsystem; the phase-0 gate it implements is now the template for "prove the
mechanism moves before burning the grid" on model-mediated features.

## Queued from V244 (2026-07-13 — corr-cap refuted at scoring)

### V245 #1 — reusable ledger↔bar join helper  (effort: S)
V236, V242, and V244 each re-derived the trades.csv → snapshot-bar mapping
(`entry_bar = cycle − hold_cycles + 28`) inline in a one-off analysis script.
Extract it into `scripts/ledger_join.py` (load window ledgers + frozen
snapshot, yield per-trade rows joined to any per-bar series) so every future
$0 separator scorer starts from a tested join instead of a fourth
re-derivation. What it would have caught: nothing — but it cuts the cost and
mapping-bug risk of the separator-first rule that has now killed three bets
(V236/V237/V244) at $0.

## How to use this file

1. During a reflection's observability-gap audit, add new gaps as `V###+1 #N`
   entries here with effort (S/M/L) and a one-line "what it would have caught".
2. When a version ships, move the 2 it shipped to **Shipped** with a ✅ and the
   file/flag it lives in.
3. Never let the queue imply "covered" — if a version bounds its own coverage
   (sampled, capped, no-retry), say so in its V###.md, not silently.
