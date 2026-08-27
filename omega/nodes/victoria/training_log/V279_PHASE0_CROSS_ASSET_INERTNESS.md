# V279 Phase 0 — the `cross_asset` signal family is inert in every frozen backtest

**Date:** 2026-08-27
**Author:** claude
**Status:** PHASE 0 / FINDINGS — no version pre-registered, no code changed, no flag added
**Parent:** [`V278.md`](V278.md) §7 item 2
**Standing baseline:** crisis +$599 / trend +$2,997 / recent +$30 — untouched, not edited

---

## §0 — First, a correction to V278 §7

V278 §7 item 2 claimed that if the market-level signals are *"structurally cancelled by
the cross-sectional demean, then five signals are dead weight"*, and called it **"one
grep plus one probe away."** Two parts of that were wrong and are corrected here:

1. **The demean-cancellation mechanism is NOT what makes them inert**, and remains
   untested (§4).
2. **The supporting observation was an artifact over-read.** V278 §5 noted that every
   trade's `signal_traces` contains only `sma_crossover`. That field is a *partial* view
   — the per-cycle signal fingerprint for the same run records `_signal_count = 20.0`
   and `_signal_coverage = 0.87`, with many non-zero groups. **The standing baseline
   does not rest on a single signal**, and nothing in V278 should be read as saying so.
   V278's own gate results are unaffected; only that §7 remark was overstated.

The finding below is narrower than V278 predicted, and better evidenced.

---

## §1 — The measurement

All four members of the `cross_asset` signal family, computed under
`OMEGA_FROZEN_CACHE=1` against the committed substrate, with a non-degenerate BTC
series (the V278 probe's monotonic input is not reused):

```
dxy_signal          = +0.000000
yield_curve_signal  = +0.000000
vix_signal          = +0.000000
spy_signal          = +0.000000
```

The family is defined at `omega/nodes/victoria/adaptive_combiner.py:48`:

```python
"cross_asset": ["dxy_signal", "vix_signal", "spy_signal", "yield_curve_signal"],
```

**All four are exactly zero, for three different reasons** — which is why no single
prior audit caught it as one fact:

| Signal | Why it is 0.0 under a frozen backtest | Since |
|---|---|---|
| `vix_signal` | explicit fence, `vix_signal.py:106` — `if OMEGA_FROZEN_CACHE == "1": return 0.0` | V227 |
| `spy_signal` | explicit fence, `spy_signal.py:116` — same shape | V226 |
| `yield_curve_signal` | reads real (future) rates, but +68.8 bp maps to the `neutral` band ⇒ 0.0 | measured V278 |
| `dxy_signal` | 0.0 on the committed `DTWEXBGS` series | measured here |

## §2 — Consequence

`signal_generation.py:1223-1230` injects each of these into a ticker's signal dict
**only when the value is non-zero**:

```python
if _dxy_val != 0.0 and math.isfinite(_dxy_val):
    ts["dxy_signal"] = _dxy_val
```

So in a frozen backtest none of the four is ever inserted into any ticker's signal dict.
They do not dilute the composite mean, they do not shift it, they are simply **absent**.

Therefore:

- **The `cross_asset` family contributes exactly nothing to the standing baseline.**
  Crisis +$599 / trend +$2,997 / recent +$30 were all produced with the family empty.
- **`AdaptiveCombiner`'s `cross_asset` family weight is computed over an empty set** in
  every frozen run — an adaptive weight for signals that are never present.
- **Any version that tuned these four signals in a frozen backtest was measuring
  nothing.** This is the V148–V202 *runtime-inert subsystem* failure mode — four-plus
  versions tuning subsystems that never ran — recurring in a shape the V213 startup
  banner does **not** cover. The banner reports **flag wiring** (`UNDECLARED —
  getattr→False`, `module importable → ACTIVE`); it says nothing about a correctly
  wired, correctly imported signal whose **value** is identically zero.

This is not a defect in any one signal. Two of the four are zero *by deliberate design*
(the V226/V227 determinism fences) and that is correct. The defect is that **nothing
reports the aggregate consequence.**

## §3 — A legibility trap worth recording

`cross_asset` names two unrelated things, and the collision cost this probe two steps:

| Name | What it is | Value in the run |
|---|---|---|
| `adaptive_combiner.py:48` `SIGNAL_FAMILIES["cross_asset"]` | a **family label** grouping the four market-level signals | all members 0.0 |
| `victoria_node.py:157` `CrossAssetSignal()` → `signals["cross_asset"]` | a **separate signal node** | `cross_asset.value = 0.121` |

Reading `cross_asset.value = 0.121` in a fingerprint and concluding "the cross-asset
signals are live" is wrong, and is exactly the inference this document nearly made. Any
future audit reading fingerprints needs this distinction.

## §4 — Explicitly NOT established

**The demean-cancellation mechanism is untested and is MOOT here.** The theory is sound:
the composite is a mean over `*_signal` keys, so a market-level constant `c` applied to
every ticker contributes `c / (n_i + 1)` to ticker *i*, which the cross-sectional demean
removes **exactly** iff every ticker carries the same number of signals `n_i` — and
`n_i` varies, because several signals are inserted conditionally
(`funding_rate_signal` only when non-zero, `volume_signal` only when the z-score
computes). If cardinality varies, a market-level constant does **not** fully cancel and
leaves a per-ticker residue.

None of that matters at present, because the four values are `0.0` and are never
injected at all. It would matter immediately if any of them became non-zero — e.g. a
macro cache containing an inverted yield curve (V278 §5). **The question is real, live,
and unanswered; it is simply not the reason for today's inertness.**

Also not established: `fear_greed_signal` (family `sentiment`, not `cross_asset`) was
not measured here.

## §5 — Recommendation

**Ship the observability delta, not a mechanism.** The V213 banner exists because
"a subsystem that silently does nothing" already cost this campaign four versions. It
covers flags; it should cover values:

> At startup, after the first full cycle, log each signal **family** with its member
> count, how many members produced a non-zero value, and mark a family with **zero
> live members as `INERT`.**

That is cheap (one aggregation over data the fingerprint already writes), it is the
exact shape of instrument the V213 arc proved pays for itself, and it would have
surfaced this finding as one banner line instead of a four-step probe.

**Do NOT** "fix" the four signals by unfencing them. `vix`/`spy` are fenced for
determinism (V226/V227) and unfencing would reintroduce a live-HTTP leak into frozen
runs. The correct outcome is that the inertness is **visible**, not that it is removed.
