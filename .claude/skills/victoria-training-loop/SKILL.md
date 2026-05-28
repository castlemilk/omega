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
