# Signal-routing investigation — 2026-05-23

## TL;DR — there is NO signal routing bug

The `ZERO_STREAK_ALERT cycle=N streak=N basket_mean=0 composites={}`
warning in `run_training.py:1146` is **a diagnostic-log bug**, not a
data-flow bug. It iterates `victoria._last_signals` (per-SIGNAL
aggregates keyed by `fear_greed_signal`, `breakout_signal`, etc.,
plus underscore-prefixed metadata) and filters for `"composite" in sig`.
Those per-signal entries were never designed to carry a top-level
"composite" key — those live in the parallel per-TICKER dict
(`BTCUSDT`, `ETHUSDT`, ...) that flows separately into
`strategy._construct_portfolio`.

The V197 assertion (`strategy._construct_portfolio` entry,
SIGNAL_ROUTING_BROKEN sentinel) ran in v197_diagnostic for 30 cycles
and fired **zero times**. Per-ticker composites ARE reaching strategy.

## The actual cause of multi-week zero trades

Flat market. VIX 17.4, fear_greed 0.89 (high greed), TDA
fragmentation 0.994 (near-perfect smoothness). The system is doing
its job — the conviction filter is correctly rejecting weak signals.

## What we did wrong

We treated the diagnostic-log artifact as proof of a real bug. The
log said `composites={}` and we built three follow-up presets
(v194_diagnostic, v195_stripped, v195b_stripped) to "fix" something
that wasn't broken. Each ran for cycles, fired the same misleading
warning, and confirmed our wrong interpretation.

## Two ways the misdiagnosis happened

1. The dict name "composites" in the warning implies per-ticker
   composites, but the code is iterating a per-signal dict.
2. The filter `if ... "composite" in sig` silently produces an empty
   result when applied to the wrong dict — no exception, no clue
   that the diagnostic was looking in the wrong place.

## Fixes (the real ones)

* **V197 assertion** (commit b33143c) — runs at the actual data
  boundary inside `_construct_portfolio`. Logs ERROR + sentinel
  ONLY when per-ticker composites are truly absent. Production-ready.
* **PipelineTracer** (commit 42c7ede) — process-wide tracer with
  shape assertions at any node boundary. Wired into
  `orchestrator._step_strategy`. Logs PIPELINE_VIOLATION + sentinel
  on shape failures. Pending: 5 more boundary wirings tracked as
  follow-up.
* **Fix the misleading diagnostic** in `run_training.py:1146`:
  rename `composites` to `signal_aggregates` and note that this
  dict does not carry per-ticker composites. (Not done yet — would
  also require restarting all live runs to pick up the change.)

## Impact reassessment

Previous claim: "0 trades for ~2 weeks across v186-v196 (~20+ runs)
because of routing bug."

Actual: v186-v196 produced 0-12 trades each depending on market vol
they happened to hit. v177c made 9 trades. v185 made 12 trades
(+$330, PF 6.26). The "0 trades" runs ran during flat-market windows.

## Detection gaps that remain

Even though there is no routing bug today, the surface area for one
is still large. PipelineTracer foundation is committed; remaining
work (Task #10) wires the other 5 boundary points so a real routing
failure would surface immediately rather than after the user notices
the system has been silent for days.
