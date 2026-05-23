# Signal-routing investigation — 2026-05-23

## Context

Multi-week zero-trade pattern across v186-v196 (~20+ runs). The
`ZERO_STREAK_ALERT` warning in `strategy.py:3034` reports
`composites={}` which was initially interpreted as per-ticker signal
dicts being stripped between `signal_generation` and `strategy`.

## Trace

Followed orchestrator path:

* `orchestrator_v2._step_signals` at line 1140 sets
  `signal_data[state.node_id] = out.result`. `signal_data` is keyed by
  `node_id`, not ticker.
* `orchestrator_v2._step_strategy` at line 1216 passes
  `{"signals": signal_data}` to the strategy node — still keyed by
  `node_id`.
* `strategy.execute` (line 822) calls
  `_construct_portfolio(signals, market_data)` with that node-keyed
  dict.

If `signal_data` were `{node_id: {ticker: sig_dict}}`, then
`_construct_portfolio` would iterate top-level keys (`node_id`),
and the per-ticker structure would be one level deeper. The
`_basket_composites` comprehension at line 2260 requires
`"composite" in sig` AT THE TOP LEVEL of each iterated value — which
the node-keyed shape would never satisfy.

## V197 assertion (added 2026-05-23)

Added `SIGNAL_ROUTING_BROKEN` log + sentinel file at
`_construct_portfolio` entry (`strategy.py:1767`). Logs ERROR with
sample keys + value-type map whenever zero per-ticker composites are
detected in the input.

## Findings so far

* v197_diagnostic cycle 1 did NOT trip the assertion. That means
  strategy IS receiving correctly-shaped signals at startup. The
  orchestrator wrapping hypothesis is wrong.
* So either the old `composites={}` warning is a log-format bug (the
  `_composites` dict has entries but the ternary `if _composites else
  "{}"` mis-renders), OR the shape changes only after the
  zero_candidate_streak counter passes 30.

## Next steps

* Wait for v197 to reach cyc 30+. If the new SIGNAL_ROUTING_BROKEN
  assertion never fires while the old warning fires, the original
  warning is a misleading log artifact and there is no routing bug
  to fix — flat market is the actual cause of zero trades.
* If the new assertion DOES fire post-cycle-30, the orchestrator does
  reshape signals mid-cycle and the routing fix needs to happen
  inside whatever mutates the dict.

## Safeguards committed regardless

* `SIGNAL_ROUTING_BROKEN` sentinel file at
  `strategy.py:_construct_portfolio` entry (commit b33143c).
* Future: zero-trade circuit breaker (auto-halt after configurable
  no-trade streak), startup pre-flight validation, integration test
  for signal_generation → strategy round-trip — pending evidence
  from v197 about whether a real bug exists.
