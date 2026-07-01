# REFLECTION_V234

**Trigger:** V234's pre-committed **falsifier branch 3** fired *before the grid ran* — a
pre-grid forensic (env-gated stderr instrumentation of the throttle site, run against the
exact grid config on `snap_crisis_2024aug`) showed the size throttle is **structurally
inert on 2024aug at the pre-registered threshold**, and, more importantly, showed *why*:
the V227 drawdown gate does not select the traded losers. The grid was **not launched** —
at a fixed `crisis_skew_drawdown_threshold = 0.12` every throttle cell is guaranteed
Δ == $0.00, so a 3-window × N=2 crisis burn would only have re-confirmed branch 3 at cost.

## What V234 got right, and the hypothesis it disproved

V234 was the correct *class* of move (act downstream of the composite, on size/exit, per
REFLECTION_V233 branch 4). The implementation is sound:

- The throttle site (`strategy.py:~3384`, in `StrategyNode._construct_portfolio`'s
  `raw_weights` path) **is on the live training/backtest path.** Direct instrumentation
  confirmed the per-symbol weighted proposals that become the 2024aug trades originate
  there (dispatch: orchestrator `_step_strategy` → `victoria_node._do_construct_portfolio`
  → `self._strategy.execute(CONSTRUCT_PORTFOLIO)`).
- The gate reads `_skew_dd_mag` off the trade candidates, and **the key is present on
  100% of candidates** (`key_present == candidate count`). The session-entry hypothesis
  — "size throttle reads 0 because `_skew_dd_mag` is not propagated to the sizing site" —
  is **disproved.** There is no wiring bug.

## The measured wall (branch 3, quantified)

The throttle fires on 0 candidates because the per-ticker realized drawdown of the
**actually-traded** 2024aug candidates never approaches the gate:

| window / run | max `_skew_dd_mag` on traded candidates | throttled @ 0.12 |
|---|---:|---:|
| snap_crisis_2024aug, 200 cycles | **0.0644** | 0 |
| snap_crisis_2024aug, 20 cycles (one obs) | 0.1003 | 0 |

Fraction of traded candidates exceeding a threshold (200-cycle):
`>0.12: 0%` · `>0.10: 0%` · `>0.08: 0%` · `>0.05: 25%` · `>0.03: 50%`.

**No traded candidate reaches 0.12 at entry.** The throttle at thresh 0.12 is a no-op on
the binding window; the grid would print Δ == $0.00 across `s0.5` and `s0.25`.

## The structural lesson (and a correction to REFLECTION_V233)

`_skew_dd_mag` is **realized PAST drawdown at entry**. The 2024aug loss is dominated by
**shorts entered before reversals**: a rising/flat asset carries ~0 pre-entry drawdown, so
a *lagging* realized-drawdown selector structurally cannot flag the names that go on to
lose. The V227 gate and the 2024aug traded losers are **disjoint sets.**

This corrects REFLECTION_V233's premise. V233 asserted "the V227 drawdown gate *fires
correctly* on 2024aug (drawdown 0.292 = 2.4× threshold)" and called the signal "sound and
selective." That 0.292 is a **non-traded** ticker (and/or a mid-hold recomputation) — it is
**not** a traded-candidate-at-entry value, of which the maximum measured is 0.0644. The
deadband was never only a conviction→trade boundary residual; the **selector itself misses
the losers.** Seven versions of composite-additive terms (V227–V233) plus one sizing throttle
(V234) all failed on 2024aug for the *same underlying reason*: every one of them keys off a
signal that does not discriminate the 2024aug losing set at entry.

## Reflection action → V235 = candidate-SELECTION layer

Per the pre-committed branch 3, V235 abandons "gate size/exit on realized drawdown" and moves
to the **candidate-selection** layer — change *which* names enter, or veto the pre-reversal
shorts, using a signal that is discriminating at entry (forward/cross-sectional, not lagging
realized drawdown). See `V235.md`.

## Carry-forward (unchanged, still deferred)

- **Track B #2** cross-sectional correlation-spike signal — now *promoted* to a V235
  candidate: a corr-spike / basket-beta selector is exactly the entry-time discriminator the
  drawdown gate lacked.
- **B2 trend-IC** ≥3-window trend distribution; **recent 2025** distribution (MATIC→POL fork)
  — both still open, both lower priority than the 2024aug selection problem.

## Retained code

The correctly-wired, default-inert throttle (`features.py:crisis_size_throttle*`,
`strategy.py:~3384`) is **kept** (flag OFF ⇒ byte-identical standing main). V235 can reuse
the *actuator* (size scaling at the raw_weights site) with a *different gate* — the
implementation was never the problem, the selector was.
