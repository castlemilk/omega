---
name: victoria-training-loop
description: Use whenever the user wants to run, plan, kick off, iterate on, or close out a Victoria training version (e.g. "let's start V200", "next training run", "kick off the next iteration", "what should we try next for Victoria", "ship V###", "log this training run"). Codifies the continual-improvement loop — read the latest entry in omega/nodes/victoria/training_log/, propose the next version's hypothesis, run the gates, write the new V###.md entry, update the high-water table, commit, and push.
---

# Victoria training loop

Victoria training improves one version at a time. Each version lives
as a markdown file in `omega/nodes/victoria/training_log/` (e.g.
`V199.md`, `V200.md`). That file is the contract: hypothesis →
changes → gate results → conclusion → next steps for V###+1.

This skill walks the loop end-to-end without skipping the log step
(which is what historically caused work to scatter across run dirs
and chat history).

## When to invoke

Trigger on any of: "start the next training version", "run V###",
"ship V###", "kick off the next iteration", "log the latest training
run", "what's next for Victoria", "continue the training loop".

Also trigger if the user shows you fresh `data/v###_*` artifacts
and asks "where do we go from here" — that's the close-out half of
the loop.

## The seven steps

1. **Read the latest entry.** `ls -t omega/nodes/victoria/training_log/V*.md`
   gives newest first. Read it. Its **Next steps** section is the
   brief for the new version. Also read `README.md` for the current
   high-water table — you need it to know what "improved" means.

   **Then check the reflection trigger (see "Mandatory reflection"
   below).** If any trigger fires, the next deliverable is
   `REFLECTION_V###.md`, NOT a new version. Reflection blocks
   pre-registration until it's committed.

2. **Propose the next version's hypothesis.** State it out loud to
   the user *before* writing code:
   - What version number? (parent + 1, or `Va` / `Vb` sibling if
     branching)
   - What's the one-sentence bet?
   - Which file(s) will change?
   - Which gate is this aimed at (recent / trend / crisis)?
   - What would convince us the bet was wrong?

   Wait for user confirmation. Don't silently invent versions.

3. **Create the new `V###.md` from `_template.md`.** Fill in
   hypothesis, planned changes, and leave gate results blank. Commit
   this *before* implementing — the log entry is a pre-registration,
   not a retrospective.

4. **Implement the change.** Edit the files identified in step 2.
   Keep edits minimal — one version, one bet. If the change requires
   touching > 3 files, that's a yellow flag: re-read the
   parent's "next steps" and check you're not silently bundling
   multiple bets.

5. **Run the gates.** The standard invocation is:
   ```bash
   python3 scripts/run_training.py --version v### --cycles 200 --sleep 10
   ```
   For per-gate snapshots: append `--snapshot recent` / `--snapshot
   trend` / `--snapshot crisis`. Outputs land in
   `data/v###_<gate>_results.json` (+ `_trades.csv`, `_gate_result.json`).
   See the project root `CLAUDE.md` "Victoria Training" section for
   the full artifact list.

   While the run is going, do NOT poll. Use `ScheduleWakeup` or
   `run_in_background` and let the harness notify you when it
   completes. (See "Why no polling" below.)

6. **Fill in the entry.** From each gate's `_results.json` pull:
   `total_pnl_usd`, `total_closed`, `win_rate`, `profit_factor`,
   and where available max drawdown. Drop them into the gate table.
   Write the conclusion honestly — confirmed / refuted /
   inconclusive — and propose next steps for V###+1.

   **Update `README.md`'s high-water table** if any gate's best was
   beaten. Don't quietly omit regressions: if the run was worse than
   parent on a gate, say so explicitly.

7. **Commit + push.** Two commits is the right granularity:
   - `feat(victoria): V### — <one-line hypothesis>` (the code change)
   - `docs(training): V### log entry + high-water update` (the
     markdown)
   Then `git push origin HEAD`.

## Why each step exists

- **Pre-registration (step 3 before step 4)** prevents
  retrospective hypothesis-shaping. If you write the hypothesis
  *after* seeing the result, you'll always rationalize it.
- **One bet per version (step 4)** is what makes the trajectory
  diagnosable. The V148→V198+ history has several phases (V186,
  V189) where multiple bets stacked silently and we couldn't tell
  which one helped or hurt.
- **Update README's high-water table on every run (step 6)** because
  the table is the only thing that travels forward; without it,
  "are we improving" can't be answered without re-reading every log.
- **Two commits (step 7)** keeps the code change reviewable
  independently of the narrative. The code can be cherry-picked
  without dragging the log entry; the log can be edited later
  without rewriting code history.

## Mandatory reflection (added after V202)

Before pre-registering a new version, check **all four** triggers.
If **any** fire, the next deliverable is a reflection document
(`training_log/REFLECTION_V###.md`), **not** a new V###.md.
Reflection is committed before any new pre-registration.

### Triggers

0. **Goodhart tripwire (checked FIRST, added after V234/DEEP_REVIEW
   2026-06):** ≥3 consecutive refutations **on the same snapshot
   window** force a REFLECTION questioning whether that window is a
   legitimate optimization target at all — vs a Goodhart-trapped
   outlier draw from a wide distribution — BEFORE any new mechanism
   may be pre-registered against it. The other triggers police the
   *subsystem* dimension; this one polices the *objective* dimension.
   History: V227→V234 logged 8 consecutive refutations on
   `snap_crisis_2024aug` (one draw of a distribution with $25,435
   measured cross-window spread) and each reflection re-aimed at the
   same window. The reflection must compare the window against its
   regime's walk-forward distribution (`data/walk_forward_manifest.json`)
   and either justify the target distributionally or retire it.

1. **Stagnation:** 3 consecutive versions have failed to break
   *any* gate's high-water (recent / trend / crisis).
2. **Eval-noise flag:** a pre-registered no-op change (or a change
   pre-registered as "will not affect gate X") moves gate X by
   > $500. The eval has hidden state coupling and the current
   single-seed deltas are no longer trustworthy.
3. **Subsystem patching loop:** the failing gate (typically crisis)
   has been static for K ≥ 3 versions AND the last K-1 hypotheses
   all target the same subsystem (e.g. all touch `crisis_short_bias`
   parameters; all touch carry injection; all touch the same
   threshold stack). Same trade count + same WR + same loss across
   versions is the diagnostic — selection/sizing isn't moving the
   gate.
4. **Drifted high-water:** the current best on any gate is from a
   version > 5 versions ago and we still haven't matched it.

### What the reflection step must do

The document answers all six and commits the answer:

1. **Eval stability.** Either (a) re-run the current best version
   on its gate with `--seed 42` and compare vs the recorded number,
   or (b) provide direct evidence from existing trade CSVs (align
   trades across versions by `(cycle, symbol, side)`, count rows
   with PnL drift on no-op gates). Establish a noise floor in
   dollars.
2. **Variance estimate.** Commission multi-seed runs of the
   current best on its gate (seeds {1, 2, 3, 42} minimum). Cost is
   ~2 hours per gate; queue as background. Until σ is known,
   **any future gate delta < 2σ is "in noise" and does NOT count
   as a high-water break.** Document the threshold in the
   reflection.
3. **Subsystem audit.** List the last K hypotheses and which
   subsystem each touched. If they're all the same subsystem and
   the gate hasn't moved, name the entire subsystem as the
   suspected dead end and propose work outside it.
4. **Revert-and-branch option.** State the structural delta
   between the current code and the version that holds the gate's
   high-water. Decide whether reverting to that baseline and
   branching from there is cheaper than continuing the parameter
   walk.
5. **Untouched dimensions.** Explicitly enumerate signal classes,
   regimes, sizing approaches, exit strategies, snapshot diversity,
   and meta-evaluation approaches that have NOT been tried in the
   last 10+ versions. The next version's hypothesis should come
   from this list, not from the last entry's "next steps."
6. **Observability-gap audit** (see below). Required output:
   *"What instrumentation would have caught this sooner? What's the
   next blind spot?"* Propose 3–5 concrete deltas; ship the 2
   cheapest/highest-impact with the next version; queue the rest in
   `training_log/OBSERVABILITY-BACKLOG.md`.

### Observability-gap audit (required output #6)

Every reflection must end by asking, of the issue that triggered it:
**what instrumentation would have caught this sooner, and what's the
next blind spot?** This is the cheapest lever in the whole loop — the
V148→V212 history shows the eval repeatedly burning versions because
it couldn't answer basic questions about itself.

Concrete templates (each is a real arc that wasted versions for lack
of one cheap instrument):

- **V148–V202 — runtime-inert subsystems.** Four-plus versions tuned
  subsystems that never ran (flag undeclared → `getattr→False`; or
  module `ImportError` silently caught). **Instrument:** a startup
  banner that lists every "active" subsystem with a live wiring probe
  (flag a real dataclass field? module importable?). Shipped V213 —
  grep a run log for `SILENTLY INERT` / `UNDECLARED`.
- **V207a–V211 — hand-hunting noise sources.** Four versions ran
  manual cycle-1 bisects to localize a determinism channel.
  **Instrument:** an automatic same-seed byte/PnL diff between
  consecutive runs. Shipped V213 (`scripts/check_determinism.sh`).
- **V212 — determinism break found only by a hand-written
  4-replicate diagnostic.** **Instrument:** N≥2 replicates per gate
  run by default + an automatic spread report + a `DETERMINISM:
  PASS|FAIL` line. Shipped V213; queued #5 promotes it into the gate
  runner so every run self-certifies its noise floor.
- **V213 — a determinism fix validated at the wrong condition.** The
  V213 sort *looked* load-bearing because the audit ran at sleep=0
  while every prior eval ran at sleep=10; the channel is dormant at
  sleep=0. **Rule (not just an instrument): always measure
  determinism at the SAME eval condition prior baselines used.**
  sleep is a determinism variable, not just wall-clock pacing — run
  the canonical-condition control before concluding a fix worked.
  Two variables changed at once (sleep + fix) ⇒ attribution is
  impossible until you hold sleep fixed.

For each proposed delta record: **what to add, where, effort
(S/M/L), and ship-now vs queue.** Pick the 2 cheapest/highest-impact
to ship with the next version (don't bloat it); document the rest in
`training_log/OBSERVABILITY-BACKLOG.md`. When a shipped instrument
surfaces a new finding (e.g. the V213 banner revealing
`regime_signal_weighting` is an undeclared no-op), that finding feeds
the next version's parking lot.

### Output

- Write `training_log/REFLECTION_V###.md` where `###` is the
  most-recent version. Structure as in `REFLECTION_V202.md`.
- Commit: `docs(training): reflection after V### — <one-line
  conclusion>`.
- The next pre-registered version's hypothesis must cite the
  reflection's "untouched dimensions" or its revert-and-branch
  recommendation. If you find yourself pre-registering another
  iteration on the same subsystem the reflection flagged as dead,
  STOP — re-read the reflection.

### Why this exists

The V199–V202 arc tuned `crisis_short_bias` for three consecutive
versions while the gate moved less than the eval's own noise floor.
The trade CSVs revealed 60–70% per-trade PnL drift across changes
pre-registered as no-ops on those gates — the eval has hidden RNG
coupling we weren't measuring, and we were reading $100–$500
deltas as signal. The fix is to force a noise-floor measurement
and a subsystem audit at the moment the trajectory shape says
"you're stuck," not after another three wasted versions.

## Walk-forward requirement (added V235 — mandatory)

**No V### may claim a strategy improvement from a single window, for
ANY gate.** Every claimed win must be measured on ≥5 walk-forward
windows per targeted regime from `data/walk_forward_manifest.json`
(26 regime-tagged 60-day windows, 2020→2026, built by
`scripts/walk_forward_freeze.py`; grid runner
`scripts/walk_forward_grid.sh`; aggregator
`scripts/walk_forward_aggregate.py`). The acceptance unit is the
DISTRIBUTION (mean / p25 / min against a pre-registered bar — e.g.
the V232-style mean-Δ>0 AND min-Δ floor), never a single-window
scalar; single-window numbers are diagnostic color only. Retire
"high-water" language for new results: the standing baseline is a
per-regime distribution. (Why: V231 at N=3 immediately refuted
V227's shipped +$630; recent's +$4,901 and the banked trend +$1,428
sat on N=1 for 13 versions. See DEEP_REVIEW_2026-06_FABLE.)

**Pre-grid separator proof (standing rule, from V234):** no grid
until an env-gated probe shows the gate variable actually
discriminates on the binding window(s). Cost ~2 short runs; saved
V234's entire burn.

### Calendar-independent-N preflight (added V249 — mandatory for recent-targeted V###)

**Before pre-registering any version whose falsifier gates on the
`recent` regime (or any regime you suspect is window-scarce), first
count how many *independent* windows that regime actually has.** This
is the check V249 wishes V246/V248 had run first.

The nominal per-regime N in `data/walk_forward_manifest.json` is NOT
the independent N. The primary 90d/90d grid tiles the span with
non-overlapping windows, but supplements added via ±45d (or denser)
offsets **overlap their primary neighbours** and are literal data
reuse — nominal N ≠ effective N. Compute it mechanically:

- Independent 90d slots in the span 2020-01-01 → today =
  `floor(span_days / 90)` (V249: **26** for 2020→2026-06).
- Cross-reference against the manifest's primary (non-offset) windows;
  the regime classifier (`walk_forward_freeze.py:regime_label`) assigns
  each to crisis/trend/recent. V249's count: **crisis 12 / trend 10 /
  recent 4 independent** (recent's nominal 10 = 4 independent + 6
  overlapping offsets).
- The recent MDE at n=4-effective / n=10-nominal is ~$1,043 (2·SE
  ~$727–$1,043). **If your target effect size is below that floor, the
  bet is structurally unfalsifiable — do NOT run it.** Widening recent N
  from frozen data is calendar-infeasible (the span is fully tiled;
  denser offsets only add overlap; shorter windows break the warmup/cap
  contract). See `V249_MANIFEST_AUDIT.md` for the full derivation.

If the preflight shows the targeted regime is calendar-bound below your
effect size, the correct move is NOT another mechanism — it is the
phase transition below.

## Phase transition — when to STOP training and switch to live-paper (added V249)

The loop consumes **independent windows**. When the targeted regime
runs out of them, no mechanism and no offline compute can adjudicate a
sub-resolution effect — continuing is variance mining, not science.
V249 hit exactly this: recent-regime alpha is **calendar-bound** (4
independent recent windows in the whole 2020→2026 span; doubling N is
calendar-infeasible from frozen data). The V241→V248 "8 refutations"
were the objective going below the noise floor, which the V247 ruler
correctly exposed.

**Declare a phase transition (STOP the sequential V### loop) when ALL
of these hold:**

1. **Reflection stagnation trigger has fired** (≥3 consecutive
   refutations) AND the reflection's conclusion is that the binding
   constraint is the **measurement instrument / data volume**, not a
   subsystem (REFLECTION_V246's finding).
2. **The V247 ruler's bars are honest** (derived from the variance
   table) and the near-misses sit in the "inside noise, no adopt" band
   — i.e. the candidates might be real but are unadjudicable, "no
   adjudication" NOT "no alpha."
3. **The calendar-independent-N preflight shows the targeted regime is
   structurally scarce** and cannot be widened from frozen data (V249's
   Phase 0 audit).

When declared, write a **campaign-level** doc (`V249.md` is the
template — NOT a mechanism V###: no code, no flag, no grid) covering:
the calendar constraint (numbers), what it means (unadjudicable ≠ no
alpha), the standing baseline as the phase's shippable deliverable, the
exhausted-axes map, the recommended next phase, and the retained
infrastructure + resume criteria. Also add/update
`training_log/CAMPAIGN_STATUS.md` (the top-level phase tracker) with
explicit resume criteria.

**The recommended next phase is live PAPER trading** — real, forward,
streaming market data → the frozen strategy's decisions → **simulated**
PnL, **no broker, no orders, no funds** (the standing "never execute a
trade / move money" guardrail is absolute here). Rationale: the
passage of time is the ONLY source of the independent windows the
frozen manifest cannot supply — each elapsed 90d = 1 new independent,
zero-overlap, correctly-labelled window, accruing at ~1/quarter. It is
also the first genuinely out-of-sample (un-Goodhartable) measurement
the campaign will have.

**Resume the training loop (V250+) when EITHER:** (1) N independent
recent windows ≥ 20 (via live-paper accumulation) — the V247 α
manifest-widening becomes real and the parked flags get re-run under
the tightened bar; or (2) a new data source changes regime structure
(intraday OHLCV freeze, on-chain/options feed) — reopening the
entry-side composite the V236→V245 streak closed *at daily bars only*.
Until then the standing baseline is the answer and every parked flag
stays OFF.

## Universe re-validation trigger (added V235)

Any time evidence emerges that the EFFECTIVE universe is materially
smaller than the nominal one (blacklists, long-suppressions, missing
bars, delistings — e.g. the V235 finding that `_TRADING_BLACKLIST`
had silently reduced 13 names to 4 on ~99 pre-hermetic trades), run a
universe re-validation forensic (template:
`training_log/V235_UNIVERSE_REVIEW.md`) BEFORE the next intervention.
Exclusion evidence bar: a ticker stays excluded only on hermetic-era
N≥50 trades with a distributional read (≥3 windows). Universe changes
are strategy changes: measure them as universe_full vs universe_legacy
cells on the walk-forward distribution.

## Common traps (learned from V148→V198+)

- **Silent gate override.** A new signal exists but a gate upstream
  (`range_bound`, `strategy_selector`, conviction floor) prevents
  it from reaching the composite. Always use the V197 PipelineTracer
  to verify a new signal actually enters the composite before
  trusting that 0-trade live runs mean "no edge".
- **WS-only backtest replay misleads.** VPIN / Kyle's λ / OFI need
  sustained live WS accumulation. A 200-cycle backtest is too short
  for them to dominate the composite. If you're trialing a
  microstructure signal, give it time before declaring it dead.
- **Don't add more entry gates.** V137/V178/V181/V183/V189 already
  stack — adding another gate is almost always the wrong move.
  Prefer adding a sub-strategy that *fires* in conditions where
  the current stack is silent.
- **`composites={}` in logs is a log-format artifact**, not a
  routing bug (V197 post-mortem). Don't spend a session chasing it.
- **Sequential ablations are contaminated by state drift**
  (commit `e4ab82d`). If you need a clean A/B, snapshot state first.

### FP-order audit pattern (when a determinism gate FAILs)

When a determinism cell FAILs with a *tiny* spread (sub-dollar to a
few hundred $, driven by a 1-trade flip), the cause is almost always
a **floating-point summation-order channel**, not a logic bug. Three
precedents have now closed exactly this:

- **V211** — `basket_std` / `basket_mean` cross-sectional aggregations
  → two `sorted()` wraps (`strategy.py:1722`/`:2130`).
- **V217** — Apple vecLib BLAS multi-threaded parallel-reduction order
  → pin BLAS to 1 thread before numpy loads (`run_training.py:55-64`).
- **V220** — `basic_signals` composite mean → `math.fsum` at
  `victoria_node.py:960` + `signal_generation.py:_balanced_composite`.

**Default first check before any deep bisect:** grep the divergent
field's producer for unsorted FP reductions — `sum(`, `+=`, or
`np.mean/np.sum` over dict/set/list iteration of floats whose order
isn't pinned. Localise the field with `scripts/per_field_diff.py`
(per-field IEEE-754 fingerprint), then fence the named site.

**Fix preference:** `math.fsum(...)` over `sorted()`+`sum`. `fsum` is
exact-rounded (full-precision sum, single rounding) so it is
permutation-invariant *without* inventing a stable sort key — it
closes *every* permutation, not just the one you sorted against.
Reach for `sorted()` only when you also need the sorted sequence
itself (e.g. a trimmed mean).

**Watch for channel-shift (the V213 failure mode):** after fencing a
site, re-run the per-field bisect on the *next* cell that drifts — a
sort/fsum that merely *moves* the channel rather than closing it will
make a previously-passing cell newly FAIL. The falsifier is always
"all cells PASS", never "the one cell I targeted PASSes".
**Measure determinism at the SAME `--sleep` prior baselines used** —
sleep is a determinism variable (V213 lesson), not just pacing.

### Layered-channel debugging (V211→V217→V219→V220→V221)

The determinism arc has now peeled **five** order-channels, each exposed
only after the previous was closed. This is not bad luck — it is the
structural shape of FP-order non-determinism, and recognising it saves
versions:

| V | Channel | Layer | Named by |
|---|---|---|---|
| V211 | `basket_std`/`basket_mean` cross-sectional sums | signal aggregation | hand bisect → `sorted()` |
| V217 | Apple vecLib BLAS parallel-reduction order | numpy/BLAS | per-field IEEE-754 fingerprint |
| V219→V220 | `basic_signals.value` sub-ulp sign-flip | composite mean → **entry decision** | `per_field_diff.py` → `math.fsum` |
| V220 (exposed) | trade PnL magnitude | **trade-PnL accounting** | trade count locked, PnL still spread |
| V221 | cross-sectional **demean** `_basket_mean` (`signal_generation.py:1160`) | candidate **selection** → sizing | `trade_field_diff.py` → `math.fsum` |

**The four rules of the pattern:**

1. **Each fence can reveal a deeper channel.** Closing one is progress
   even when the gate still FAILs — the *new* FAIL names the next layer.
   Don't read "still FAIL" as "fix didn't work"; bisect again.

2. **Binary (threshold/decision) channels MASK analog (magnitude/sizing)
   channels.** While an entry flip (27↔26) is open, its single-trade
   swing dominates the spread and hides a continuous sizing wobble
   beneath. Lock the binary channel (e.g. trade count) and the analog
   one steps into view. Expect the spread to sometimes *grow* when you
   close a binary channel — that is the analog channel becoming visible,
   not a regression.

3. **Bisect at the RIGHT LAYER, with the right tool.** Signal layer →
   `per_field_diff.py` (per-(cycle,signal) IEEE-754 hex). Trade layer →
   `trade_field_diff.py` (per-(cycle,symbol,side) ledger-field hex). If
   the signal layer reads "clean" but PnL diverges, the channel is
   downstream — switch tools, don't conclude "hermetic." V220 burned its
   whole bet because `per_field_diff.py` stops at the signal layer.

4. **Don't chase "the fix" until you've NAMED the field.** A guessed
   fence at the wrong site either no-ops or shifts the channel (V213).
   Name the first divergent (trade, field), trace it to its producer,
   *then* fence. The trace matters: V221's symptom was `size`, but the
   root was a demean `sum()` three call-frames upstream — fencing `size`
   directly would have done nothing.

**Selection vs sizing nuance (V221):** a reduction that *looks* like
sizing (`size` diverges) can actually be a **selection** channel — a
demean/normalisation whose sub-ulp wobble flips a near-boundary ticker
in/out of the basket, changing N and thus every `1/N` weight. The tell:
`entry_price`/`exit_price` are bit-identical but `size` jumps by a clean
ratio (5000:6666 = 3:4 = `budget/N`). Grep the *selection* path
(cross-sectional demean, rank/threshold, basket normalisation), not just
the arithmetic sizing path, when sizes diverge at clean ratios.

**Presence-flap channels & epsilon-guard amplifiers (V221 residual, 6th
peel):** not every channel is a summation-order reduction. A signal whose
*presence* in the composite flaps between replicates (inserted only `if
value != 0.0`) diverges by O(0.1), not sub-ulp. The V221 residual:
`FundingRateSignal._zscore_signal` guarded zero variance with `std=1e-8`
— for a CONSTANT cached rate r, `fl(n·r)/n ≠ r` at history lengths where
n·r rounds (n=3,6,7,…), every deviation is the same rounding residual,
and z collapses to exactly ±√((n-1)/n): the epsilon guard **amplifies
sub-ulp residue into an O(1) signal** that flickers with n. A ±1
call-count offset between replicates phase-shifts the flicker. Fix shape:
semantic degeneracy fence (`if max(hist) == min(hist): return 0.0`), not
a smaller epsilon. Two diagnostics to remember:

1. **Exact algebraic constants are a fingerprint.** A divergent value
   equal to √(2/3)/2, 1/√2, √(4/5)/2… screams degenerate-variance
   z-score, just as clean ratios (3:4) scream `budget/N` selection.
2. **Post-demean aggregate fingerprints are structurally blind.** After
   cross-sectional demeaning, mean(composites) ≈ 0 by construction, so
   the aggregate `basic_signals.value` fingerprint reads "sub-ulp" even
   while a per-ticker composite shifted by 0.14. When the aggregate says
   sub-ulp but trades flip, diff `signal_contribs.jsonl` (per-trade
   `signal_traces` lists each composite's sub-signal names) — the extra/
   missing NAME names the channel instantly.

## Keep the workspace clean

**One-line rule: never leave the repo dirty between iterations.**

Wedged sessions (timed-out python runs, killed git operations,
interrupted commits) accumulate stale `.git/*.lock` files and
uncommitted `training_log/V*.md` work that blocks the next
iteration. This section is mandatory.

### Preflight — the FIRST bash call of every code task (step 0)

**Run `bash scripts/prepare_session.sh` as the very first Bash call,
before anything else — no exceptions.** It is idempotent and safe to
re-run. It does, in one shot, what the old manual checklist did by
hand: kills only stray `git` processes (never python runs), removes
stale `.git/*.lock` files, re-asserts the Mac `core.fsmonitor=false` /
`gc.auto=0` hardening, and verifies git responds within 5s.

- **Exit 0** → `[prepare_session] OK (<sha>, branch <name>)`. Proceed.
- **Non-zero** → the environment is genuinely unhealthy (a kernel /
  FSEvents / disk wedge below git, which lock-removal can't fix).
  **STOP and report to the user that manual cleanup is needed. Do NOT
  retry the script in a loop and do NOT start hand-surgery on `.git/`.**
  Retrying a real kernel wedge just burns the session.

After preflight returns OK, `git status` must be clean OR you
explicitly enumerate untracked files in the response. Stale
`data/v*_*` artifacts are expected (now `.gitignore`d); untracked
`.md` files in `training_log/` are NOT — see the recovery rule below.

**Why this replaced the manual checklist:** the V210→V220 arc kept
re-deriving the same lock-cleanup by hand and occasionally wedged
*worse* by racing a live process or deleting the wrong thing.
`prepare_session.sh` is the single audited, idempotent path. Root
causes it neutralises: stale locks from a killed commit, an index
held by a background nohup run, macOS fsmonitor hangs, and a fresh
config that lost the hardening.

### During a gate run (step 5)

When launching `scripts/run_training.py` in background, capture the
PID immediately and persist it:

```bash
python3 scripts/run_training.py --version v### ... &
echo $! >> data/v###_pids.txt
```

At task end, verify those PIDs are gone:

```bash
for pid in $(cat data/v###_pids.txt 2>/dev/null); do
    kill -0 $pid 2>/dev/null && echo "STILL ALIVE: $pid" && kill $pid
done
```

A wedged python process holding open file descriptors is the most
common cause of the next session's lock issues.

### External audit-output storage (avoid ENOSPC during long grids)

The host disk filling with *non-omega* data caused the ENOSPC faults
that killed the V232 grid and paused V233 mid-cell (omega's own `data/`
is only ~450M, so nothing in the training layer can recover from it —
the disk fills from outside). Before launching any long `v###_dist`
grid, check `df -h /` and, if host free space is tight, redirect the
large audit/trace writes to an external mount:

```bash
export OMEGA_AUDIT_OUTPUT_DIR=/Volumes/gamma-systems-2/omega-victoria-data
N=2 GATES=crisis nohup bash scripts/v###_dist_grid.sh > /tmp/v###_grid.log 2>&1 &
```

`OMEGA_AUDIT_OUTPUT_DIR` is honored by `run_training.py`,
`check_determinism.sh`, and the `v###_dist_grid.sh` template; it moves
only WRITE artifacts (results/trades/progress/`*_fingerprint.jsonl`/
trace dirs/determinism cells). **Frozen-cache INPUTS** (`macro_cache.db`,
`signal_ic_history.json`, `.cache_manifest.json`, `data/snapshots/`)
stay in `data/`, so determinism is unaffected. **The default falls back
to `data/` if unset** — set it only when you want output off the host
disk. The active mount path is recorded in `data/SESSION_STATE.json`
(`audit_output_dir`). See `training_log/RESILIENCY_AUDIT_2026-06.md` →
"External audit-output storage (gamma-systems-2)".

### Recovery: first action when entering a possibly-wedged repo

Before doing anything else, run:

```bash
git status --short | grep -E "training_log/(V|REFLECTION_V)[0-9]+.*\.md"
```

If this returns any uncommitted `training_log/V###.md` or
`REFLECTION_V###.md` files (modified OR untracked), they are
autosaves from a wedged prior session. Commit them FIRST, with an
`(autosaved from wedged session)` suffix in the commit message,
before pre-registering the new version. Example:

```
docs(training): V210 results (autosaved from wedged session)
```

Then proceed with the normal loop. **Never start V###+1 work on
top of an uncommitted V### that you didn't write yourself in this
session.**

### Concurrent-session discipline (one index, one writer)

**Two code-task sessions must NOT run in the same cwd concurrently.**
They share one `.git/index`; the moment both stage or commit, one
wedges the other — this is the dominant lock-wedge cause that
`prepare_session.sh` can only *recover* from, not prevent. Prefer
single-task orchestration over multiple sessions in the same dir.

If a version genuinely needs parallelism (matrix mode), give each
parallel line of work its **own** index via a git worktree
(`.claude/worktrees/v###-<cell>/` — see *Matrix exploration* below).
Each worktree has a separate index, so concurrent commits don't
contend. Never fan out parallel sessions against the shared main
checkout.

If `prepare_session.sh` itself times out (exit non-zero on the
`git rev-parse` step), that is a genuine kernel/FSEvents wedge —
**stop and report to the user; manual cleanup is needed.** Do not
keep retrying.

## Matrix exploration

The default loop is sequential: one V### = one bet, ~8h per cell.
That's right when each bet's outcome decides the next bet — the
V202→V203→V204 noise-diagnosis arc only made sense as a chain
because each step refined the previous answer.

When 2+ candidate bets are **independent** (different subsystems,
different falsifiers, no shared parameter surface), sequential is
wasteful. Matrix mode runs N cells in parallel against the same
baseline and measures N bets in ~8h instead of N×8h.

### When to use matrix vs sequential

- **Sequential**: the next hypothesis depends on this one's result.
  Refinement chains, debugging arcs, parameter walks.
- **Matrix**: 2+ candidates touch disjoint subsystems and each has
  its own falsifier. Examples: V199 carry plumbing vs V170 IC
  weighting vs V166 normalization — three different files, three
  different gates targeted, no shared state.

If you can't articulate why two cells are independent, run them
sequentially.

### Naming convention

`V###.A`, `V###.B`, `V###.C`. The parent `V###` ties the cells
together as one matrix experiment; the letter identifies the cell.
The high-water table records the winning cell as `V###.X` if any.

Example: V213.A = restore V199 carry plumbing; V213.B = enable V170
per-regime IC weighting; V213.C = activate V166 normalization. All
three run against the same V211 baseline.

### Isolation per cell

Each cell lives in its own worktree at
`.claude/worktrees/v###-<cell-letter>-<short-name>/` (same pattern
as V204/V205 module pinning). Each worktree:

- Has its own `strategy.py` (and any other) mutations.
- Runs its own 2-pair × 3-gate audit (12 runs minimum).
- Captures PIDs to `data/v###<letter>_pids.txt`.
- Writes its own artifacts to `data/v###<letter>_audit/`.

`main` stays untouched until one cell wins.

### Pre-registration: one document per matrix

ONE document `training_log/V###-matrix.md` covers all cells.
Each cell gets a subsection: **Hypothesis**, **Files touched**,
**Falsifier**, **Targeted gate**. The matrix doc is committed
BEFORE any cell starts running — that's what makes it
pre-registration. Per-cell sub-docs are not necessary; everything
lives in the matrix doc.

The matrix structure makes it harder to retrofit hypotheses
cell-by-cell after seeing results — they're all on the page from
the start.

### Shared baseline

All cells compare against the **same V###-1 baseline numbers**
(e.g. V213 cells all compare against V211: recent +$2,177, trend
+$8,328, crisis −$24,828). Same noise floors apply (recent
$200, trend $200, crisis $28 from V210 reflection). If the
baseline changes mid-matrix (e.g. V212 ships during the run),
hold the matrix to its original baseline — don't re-baseline
partway through.

### Concurrent execution

Cells run truly in parallel. The standard pattern:

```bash
# In each cell's worktree:
cd .claude/worktrees/v213-a-carry/
nohup python3 scripts/run_training.py --version v213a --cycles 200 \
    --snapshot recent > /tmp/v213a_recent.log 2>&1 &
echo $! >> data/v213a_pids.txt
disown
```

Tag every PID with the cell letter (`v213a_pids.txt`,
`v213b_pids.txt`) so cleanup can distinguish them. The
workspace-clean rule still applies before each cell's commit —
each worktree must end clean.

### Result aggregation

When all cells complete, fill `V###-matrix.md` with a comparison
table:

| Cell | Hypothesis | Recent Δ | Trend Δ | Crisis Δ | Verdict |
|---|---|---:|---:|---:|---|
| V213.A | carry plumbing | … | … | … | pass/fail |
| V213.B | V170 IC | … | … | … | pass/fail |
| V213.C | V166 norm | … | … | … | pass/fail |

**Only ONE cell's code can merge to main per V###** (or zero, if
no cell wins beyond the adjusted noise threshold on any gate). If
multiple cells pass, V###+1 either stacks the strongest pair OR
runs them as a 2×2 interaction matrix (`V###.AB`) — do not silently
merge two cells.

### Failure modes specific to matrix mode

- **Shared runtime state contamination.** Cells that both write to
  `data/macro_cache.db`, `state.db`, or other shared paths
  contaminate each other. Pre-flight: each worktree's `.gitignore`
  must isolate cache writes, and use `OMEGA_FROZEN_CACHE` (V207a)
  to pin the macro cache snapshot.
- **Many-comparisons false positives.** Running N cells inflates
  the chance of a spurious 2σ move. Adjust the noise threshold:
  **2.5σ for N=3, 3σ for N=5**. Document the chosen threshold in
  the matrix pre-reg's falsifiers section.
- **Reflection still applies.** If a matrix run shows ALL cells
  within noise on every gate, the reflection triggers fire as if
  the cells had run sequentially — don't just expand the matrix
  to N+1.

## File layout

```
omega/nodes/victoria/training_log/
├── README.md            # index + high-water table + loop summary
├── _template.md         # starting point for new V###.md entries
├── V148.md              # one file per version (or per phase)
├── V172.md
├── V176.md
├── ...
└── V199.md              # next planned version
```

The skill never touches `data/v###_*` files directly — those are
produced by `scripts/run_training.py` and read by the log entry.

## Why no polling

`scripts/run_training.py --cycles 200 --sleep 10` takes 30+ minutes.
Don't `sleep` between status checks — the harness already notifies
you on background task completion. Use `run_in_background: true` on
the Bash call that kicks off the run, then keep your context lean
until the notification arrives.

If the run is long and the user is waiting, schedule a wake-up
with `ScheduleWakeup` set to 1200-1800s as a fallback heartbeat in
case the notification is missed.

## Example pass through the loop

User: "let's start V200"

You:
1. Read `V199.md` — see it's the carry-only sub-strategy. Check
   `README.md` — recent high-water is V176 +$1,189, trend is V172
   +$18,437, crisis still negative.
2. Propose: "V200 should ungate `funding_carry_signal` from the
   `range_bound=1.0` check and route it into a new
   `carry_sub_strategy`. Aimed at recent. Files: `strategy.py`,
   `ensemble_voter.py`. Falsifier: < 5 trades in 200 cycles means
   carry still isn't reaching composite — that's a tracer bug, not
   a signal-edge bug."
3. User confirms → write `V200.md` from `_template.md`, commit
   pre-registration.
4. Implement.
5. `python3 scripts/run_training.py --version v200 --cycles 200`
   in background. Wait for notification.
6. Fill in gate table. If recent > $1,189, update README high-water
   to V200.
7. Two commits, push.
