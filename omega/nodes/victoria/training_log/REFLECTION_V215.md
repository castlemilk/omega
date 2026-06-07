# Reflection after V215 — converging, not stagnating

**Date:** 2026-06-07
**Trigger:** Pre-registered. V215.md committed to writing this reflection if
Falsifier 1 fired (determinism gate spread ≥ $200 with the HTTP guard armed). It
did ($2,584 ON / $2,717 OFF). This document honors that commitment and confronts
the skill's six reflection questions head-on. **Conclusion up front: the eval is
converging on hermeticity — each version since V212 has closed a *named* channel —
so this is the opposite of the stuck parameter-walk the trigger guards against. The
next step is a concrete fence, not a reset.**

## Why the stagnation trigger technically fired (and why it's a false positive)

Trigger 1 reads "3 consecutive versions failed to break any gate's high-water" —
V212, V213, V214, and now V215 are all no-high-water. But this is a
**determinism-diagnosis arc**, and you cannot break a high-water until the eval is
deterministic. The trigger exists to catch *parameter walks that move the gate less
than noise while the author keeps tuning the same dead subsystem.* That is not what
is happening. The diagnostic signature of a dead walk — **same trade count, same
WR, same loss across versions** — is absent: every version here produced a *new,
falsifiable, confirmed* fact about the eval's hidden state.

## The six questions

1. **Eval stability.** Now *measured*, not estimated. The signal layer is
   **byte-identical** across replicates at sleep=10 (fingerprint diff = 0/200 for
   both ON and OFF) after V215's network freeze. The residual spread is **not RNG
   noise** — it is a *deterministic function of wall-clock time*:
   `core/risk_manager.py:316` `time_risk_multiplier` applies a 0.50 size cut during
   14:30–15:30 UTC, read from `datetime.now(UTC)` rather than bar time. A replicate
   that straddles the window halves its sizing. This is reproducible and
   explainable to the minute (on_r4 fully inside → 46 trades; on_r3 clipped → +$134;
   on_r1/r2 clear → identical). **There is no unexplained noise floor left to
   estimate — the residual has a name and a line number.**

2. **Variance estimate.** N/A by the above. The residual is not variance; it is a
   bias that switches on inside a wall-clock window. No multi-seed σ campaign is
   warranted — a single same-seed pair *outside* the window is already
   byte-identical ($0 spread, on_r1==on_r2). The "noise floor" for the hermetic
   eval, once V216 fences the window, is projected to be **$0** (exact replication),
   not a distribution.

3. **Subsystem audit.** The last four versions did NOT tune one subsystem:
   - V212: enabled `strategy_selector` (selector subsystem).
   - V213: canonical basket sort (signal aggregation) — REFUTED + reverted.
   - V214: localized network leak in `signals_advanced` (data layer) — instruments
     only.
   - V215: froze the network leak (data layer) → localized `time_risk_multiplier`
     (sizing layer).
   These are *four different subsystems*, each entered because the previous version
   *ruled the prior one in or out with evidence*. That is convergent localization,
   not a patching loop.

4. **Revert-and-branch.** Not applicable / rejected. V215's network freeze is
   load-bearing and confirmed (it made the signal layer hermetic); reverting it
   would re-open the dominant channel. The high-water holder (V211) differs from
   HEAD only by additive determinism instruments + the freeze — there is nothing to
   revert *to* that would help. Keep building forward.

5. **Untouched dimensions → the next hypothesis.** The fingerprint proves the
   **signal layer is clean**, so every remaining determinism channel must be in the
   **trade-construction layer** (sizing, exit, attribution) — a layer the whole
   V207–V214 arc never inspected because it was chasing signal values. V216's
   hypothesis comes from here: **bar-time fencing of wall-clock reads in the sizing
   path** (`risk_manager.time_risk_multiplier`, `strategy.py:2098` hour damp). This
   is a genuinely new dimension, not a re-tune of a flagged dead end.

6. **Observability-gap audit.** *What would have caught this sooner?*
   - **The fingerprint+guard combo IS the instrument** — and it worked: it
     localized the sizing-time channel in a single N=4 run by (a) proving the signal
     layer hermetic (fp diff = 0) and (b) proving the residual non-network (guard
     blocked 100% of HTTP). The discrimination "signal vs non-signal, network vs
     non-network" that the V207–V213 arc lacked is now one command.
   - **Next blind spot:** wall-clock reads in the *sizing/exit* layer. Cheap new
     instrument (ship in V216): a **backtest wall-clock-read tripwire** — when
     `OMEGA_FROZEN_CACHE=1`, log every `datetime.now`/`time.time` call site reached
     during the cycle loop that is *not* passed a bar timestamp (a lightweight audit
     hook or a one-time AST/grep gate over `strategy.py`/`risk_manager.py`/
     `paper_trading.py`). This would have flagged `time_risk_multiplier(now=None)`
     at cycle 0 instead of after a 4-replicate run. **Queued to
     OBSERVABILITY-BACKLOG (#8).**
   - **Process rule reinforced:** sleep is a determinism variable *and* a wall-clock
     exposure variable — running replicates back-to-back deliberately staggers them
     across time-of-day windows, which is what surfaced this. Keep N≥4 at sleep=10
     so replicates span enough wall-clock to expose time-gated code.

## Decision

Proceed to **V216 = bar-time fence of the sizing-side wall-clock sites** (cites
this reflection's question 5). Do NOT write another network-layer version, do NOT
start the matrix, do NOT expand N blindly. One channel from hermetic.
