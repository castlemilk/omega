# V305 — Victoria does not share the ASX line's defects, and that is the finding

**Date:** 2026-09-03
**Status:** audit complete, negative — hypothesis withdrawn

## 1. The hypothesis

The ASX line bought three rules with nine versions and found four methodology
defects. The obvious inference was that Victoria — ~300 versions old, same author,
same idioms, never audited against those rules — would share them, and that a
sweep would be the highest-value next work.

That inference was wrong, and it is worth recording why.

## 2. What was checked, and what was found

**V303 — a missing input must be excluded, never defaulted.** 288 sites match
`.get(key, <number>)`; narrowing to numeric paths carrying an *observation*
(price, pnl, fill) leaves a handful, and every one is already correct:

| site | verdict |
|---|---|
| `strategy.py:1168/1204/1269` `signals_dict.get("composite", 0.0)` | dead default — `risk_management.py:799` indexes `sub_v["composite"]` directly and would crash if it could be absent |
| `liquidation_cascade.py:163` `c.get("price", 0)` | **guarded** — `if price <= 0: continue` on the next line. Excluded, not defaulted. Exactly the V303 rule. |
| `liquidation_signals.py:216` `order.get("averagePrice", …, 0)` | V303-shaped, but on Binance `allForceOrders` — geo-blocked from this host, so inert (CLAUDE.md, Known Environment Constraints) |
| `exit_controller.py:345-347` `t.get("pnl"/"mfe"/"mae", 0)` | telemetry percentiles, not a trading path; `compute_exit_telemetry` guards the degenerate case |

**V302 — read the metadata the response returns about itself.** Victoria requests
an explicit `interval` (default `"1d"`) from every provider, and Coinbase maps it
through `_COINBASE_GRANULARITY` deliberately. Resolution is *requested*, never
inherited from a default. This is precisely the opposite of the ASX mistake, where
taking the default silently produced weekly buckets.

**V293 — an input that quietly evaluates to something is worse than one that
errors.** This one IS present, and was already known: V279 found five inertness
findings. No new work needed; it is the campaign's oldest open problem.

## 3. The correction

The four ASX methodology errors — the non-binding concentration cap, weekly
bucketing, benchmark misuse, and gaps charged 0% — were **written by the ASX line
itself**, in code that was days old. They were not inherited idioms.

The audit direction was therefore backwards. The risk was not that old code
carries old bugs; it was that new code written quickly carries new ones, and the
ASX engine went from nothing to a full research pipeline in about a week. Every
one of those four defects was introduced during that sprint and survived because
each produced a plausible number.

## 4. What this changes about what to do next

- A Victoria defect sweep is **not** the highest-value work. It was proposed on an
  inference that did not survive checking, which is the correct outcome for an
  audit and the reason to run one before acting on a hypothesis.
- The generalisable lesson is about *velocity*, not *age*: the three rules should
  be applied hardest to code written in the last week, not the last year.
- Victoria's actual open problem remains V279's inertness — components that import
  cleanly, are wired correctly, and do nothing. That is a different failure from
  the three rules and needs its own treatment.

## 5. Housekeeping recorded here

Merging this branch surfaced a live substrate drift: `data/macro_cache.db` in the
working tree had diverged from the manifest-blessed hash (69,632 → 73,728 bytes,
`c86fe0be…` against `397b9438…`) because a training run wrote to it. The committed
blob was clean; only the worktree had moved. `tests/test_cache_manifest.py` caught
it, which is the V277 guard doing exactly its job — and the reason it exists is
that this same file drifted silently once before.
