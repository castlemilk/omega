# State drift contaminates sequential ablations

## The bug

Three consecutive ablations (V182, V183, V184) appeared to regress vs
`v176_ensemble` baseline on the same `fresh_0508` snapshot. Each was
concluded to be an over-fit and the flag was left disabled.

A re-baseline of `v176_ensemble` against the same snapshot — same code,
same seed, same data file — produced a **completely different result:**

| Run | PnL | Trades | WR | PF |
|---|---|---|---|---|
| v176 baseline (earlier, 2026-05-12) | +$47 | 39 | 36% | 1.36 |
| v176 rebaseline (now, 2026-05-13) | **-$74** | 45 | 27% | 0.73 |

Same code. Same snapshot. **$121 swing.**

## Cause

The training engine mutates files in `data/` on every run:
* `data/signal_ic_history.json` — rolling IC weights for each signal
* `data/reinforcement_state.json` — RL state for the meta-learner
* `data/training_version.txt` — version counter, auto-incremented
* `data/omega_victoria_memory.db` — semantic and episodic memory
* `data/activation_traces/` — per-cycle decision traces

These updates persist across runs. The signal IC history especially
matters: it directly weighs signals during composite computation. After
a sequence of training runs, the IC weights have shifted, so the same
snapshot replay produces different conviction values → different trade
decisions → different PnL.

## What this changes

Every V18x conclusion was measured against a stale baseline. Re-interpreted
against today's same-time baseline:

| Preset | PnL | PF | vs same-time baseline (-$74 / 0.73) |
|---|---|---|---|
| v181_short_filter | +$44 | 1.75 | **+$118, PF +1.02** |
| v184_lock50 | -$11 | 0.95 | +$63, PF +0.22 |
| v184_lock70 | -$9 | 0.96 | +$65, PF +0.23 |
| v184_stacked | +$8 | 1.04 | +$82, PF +0.31 |
| v185_phase_a | -$19 | 0.93 | +$55, PF +0.20 |

**Every V18x flag is positive vs the same-time baseline.**

V181 short-side filter is the biggest winner — it had already been
acknowledged as the snapshot-best variant, but the magnitude was
understated. PF 1.75 vs current 0.73 is a 2.4× improvement.

V184 lock50 trail and V185 (with VPIN/Kyle/LOB inactive in backtest)
all show double-digit dollar improvements vs same-time baseline.

## The methodology fix

**Future ablations must control state.** Three options:

1. **Snapshot the data/ dir before each ablation; restore between
   runs.** Cleanest. ~50 lines of shell wrapper around
   `scripts/run_training.py`.
2. **Run all variants in parallel from the same state.** Less precise
   (each run still mutates the file as it runs, contaminating the
   others), but avoids the sequential drift.
3. **Compare deltas, not absolutes.** Always run a fresh `v176_ensemble`
   baseline back-to-back with the variant, and report
   `delta_pnl = variant_pnl - baseline_pnl`.

Option 3 is the cheapest and most reliable. Adopting going forward.

## Action items

* [x] Document state drift in this file
* [x] Re-interpret V18x results vs same-time baseline (above)
* [ ] Promote V181 to a live deployment slot (highest snapshot edge)
* [ ] Deploy V185 Phase A live (it carries V184_lock50 + 3 new
      microstructure signals; live A/B vs V177 baseline is the only
      way to measure VPIN/Kyle/LOB alpha)
* [ ] Build the snapshot-restore wrapper for future ablations
* [ ] Audit the v177c / v168c live runs that keep dying ~30 min after
      relaunch — root cause separate from this issue but blocks long
      live A/B comparisons
