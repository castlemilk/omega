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

## Keep the workspace clean

**One-line rule: never leave the repo dirty between iterations.**

Wedged sessions (timed-out python runs, killed git operations,
interrupted commits) accumulate stale `.git/*.lock` files and
uncommitted `training_log/V*.md` work that blocks the next
iteration. This section is mandatory.

### Before pre-registration (step 3)

1. `git status` must be clean OR you explicitly enumerate untracked
   files in the response. Stale `data/v*_*` artifacts are expected;
   untracked `.md` files in `training_log/` are NOT — see recovery
   rule below.
2. Check `.git/index.lock`, `.git/HEAD.lock`, `.git/objects/maintenance.lock`,
   `.git/refs/heads/*.lock`. If any exist AND mtime > 60s old AND
   no live `git` process holds them (`ps -ef | grep '[g]it '`),
   delete them: `rm -f .git/index.lock .git/HEAD.lock .git/objects/maintenance.lock`.
3. Confirm `git status` returns promptly (< 5s). If not, escalate
   — don't try invasive surgery on `.git/`.

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
