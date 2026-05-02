# Feedback Mechanisms — Beyond Static Voting

**Date:** 2026-05-02
**Status:** V174 design + impl notes.

## Why this matters

V173 ensemble (3 sub-strategies vote, majority wins) is the first
architectural change in 9 attempts that beat the V161 baseline (+55% on
fresh-snapshot composite, PF 10.21 on `fresh_60d`). The win came from
**enforced consensus** — restrictive 3-way voting kicks out marginal trades
and only fires when at least 2 sub-strategies agree.

But the ensemble is *static*. Every sub-strategy weights its vote equally
forever, regardless of whether it's been right or wrong recently. Real
markets shift regimes; what worked last week may be wrong this week. The
next layer of robustness is making the ensemble **self-correcting** based on
recent outcomes.

## The 6 mechanisms — ranked

### 1. Adaptive ensemble decay (highest ROI, lowest risk) — IMPLEMENTING

Each sub-strategy tracks its hit rate over the last 20 trades. If it's been
wrong recently, its vote is faded:

```
sub_weight = clip(0.0, 1.0, recent_hit_rate / 0.5)
```

So a sub-strategy at 50% recent WR votes at full weight; at 25% it votes at
half; at 10% it's nearly silenced. When it recovers, its weight grows back
automatically. **No manual intervention.**

Implementation: extend `aggregate()` to take a `recent_hit_rates: dict[name,
float]` argument. The strategy node computes recent hit rates from
`paper_engine._closed_trades` (which sub-strategy called each trade is now
recorded on the trade row).

### 2. Brier score calibration (medium ROI, monitoring-only first)

If the system claims 70% confidence on entries that win 40% of the time, it's
over-confident — and we should size DOWN. Brier score = mean squared error
between predicted probability and actual outcome.

Implementation: just monitor for now (write `data/brier_scores.jsonl`).
Adjusting sizing automatically based on calibration is risky — defer until
we have at least 100 trades of calibration data.

### 3. Temporal pattern recognition (medium ROI, needs n=200+ to trust)

Hour-of-day and day-of-week effects are real but tiny per-sample. Need lots
of data to see signal through noise. Track per-bucket WR; report; do not
auto-act on it until n=200+ per bucket.

### 4. Adversarial self-play (low cost, high signal) — IMPLEMENTING

For each proposed trade, recompute the ensemble decision with all signal
values negated. If the negated decision also has high conviction, the
underlying signals are ambiguous — sit out. If the negated decision is
strongly opposite, that's confirmation.

This is the simplest form of the bull/bear LLM debate from the coinman2
article — but it costs zero LLM calls because we're just re-evaluating the
same code path with sign-flipped inputs.

Implementation: in `decide()`, also call `decide(negated_signals, regime)`.
Compare the two decisions:
- Same direction? Strong signal — boost size_mult by 1.2 (cap at 1.0)
- Opposite direction with similar magnitude? Confirmed — keep size_mult
- Same direction but opposite is also strong? Ambiguous — sit out
- Opposite direction with low magnitude? Standard — keep decision

### 5. Trade outcome feedback (longer-term — defer)

Lightweight running log of "last 3 momentum trades lost" type context.
Useful as LLM analyst input but not as a direct strategy lever yet. Defer
until LLM analyst is reactivated.

### 6. Conviction pyramid (medium ROI, invasive impl) — DEFERRED

Build positions in 3 tranches (25/25/50%) instead of binary in/out. This
requires significant changes to PaperTradingEngine to track "growing"
positions, partial fills, conviction recomputation per cycle on open
positions. Bigger refactor — defer to a separate session.

## V174 = V173 ensemble + #1 + #4

Implementing #1 (adaptive decay) and #4 (adversarial check) together. Both
are pure additions to `ensemble_strategy.py` — no changes to paper_trading,
no schema migrations.

Feature flags:
- `adaptive_ensemble_decay: bool = False`
- `adversarial_check: bool = False`

V174 preset = V173 + both flags on. Phase A on 3 fresh snapshots vs V173
baseline (+$2,693 composite).

## Expected ranges

If **adaptive decay** works: composite ~$3,000-3,500 (10-30% lift). The
mechanism's value is asymmetric — it can't make a winning sub-strategy
better, only fade a losing one. Big wins come during regime shifts.

If **adversarial check** works: composite ~$2,800-3,500 (5-30% lift). Lower
trade count (more sit-outs on ambiguous signals), higher PF.

If both compound cleanly: ~$3,500+ composite. If they fight (decay says
"trust this trade", adversarial says "ambiguous, sit out") then ~+0% over
V173.

## What this isn't

This isn't a fundamentally new strategy. It's **risk management on top of
the existing ensemble.** The alpha source is still the underlying signal
stack on 15-min bars in current crypto regimes. These mechanisms shave the
tails — fewer bad trades during the system's bad weeks, slightly bigger
trades during its good weeks.

The real next-step alpha source (after V174) is integrating the new signals
(mempool, google_trends, vwap, rsi_divergence) into the ensemble's
sub-strategies. Currently they're computed but no sub-strategy uses them.
That's a separate work item.
