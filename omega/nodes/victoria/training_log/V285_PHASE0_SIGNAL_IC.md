# V285 Phase 0 — signal quality measured directly: sma_crossover is the whole edge

**Date:** 2026-08-27
**Author:** claude
**Status:** PHASE 0 / FINDINGS — read-only, no strategy module imported, no code changed, no version pre-registered
**Parent:** [`V280.md`](V280.md) (enabling the six technical signals cost $1k–$3.2k/window) · [`V279.md`](V279.md)
**Standing baseline:** crisis +$599 / trend +$2,997 / recent +$30 — untouched

---

## §1 — The question

V280 measured that enabling RSI, MACD, Bollinger Bands, Z-score, BTC-beta and vol-regime
costs **$1k–$3.2k per window**. That leaves two very different diagnoses, needing
opposite fixes:

- **quality** — the signals carry no information, so nothing can save them; or
- **weighting** — they carry information but `_balanced_composite`'s *equal-weight mean*
  dilutes the one good signal.

This measures signal quality directly, from the same snapshot closes the strategy sees,
importing no strategy module — so the answer is independent of wiring, gating and
weighting.

## §2 — Per-signal information coefficients

17,344 observations, all 32 walk-forward windows, Spearman IC vs forward return:

| Signal | IC (H=3) | p |
|---|---:|---:|
| **sma_crossover** | **+0.0403** | 1.1e-07 |
| rsi_signal | −0.0241 | 1.5e-03 |
| macd_crossover | +0.0039 | 0.61 — **noise** |
| bb_signal | −0.0137 | 0.071 |
| zscore_signal | −0.0137 | 0.071 |

| Composite | IC |
|---|---:|
| sma_crossover alone (**v1.0, what ships**) | **+0.0403** |
| equal-weight 5 (v1.2, what V280 enabled) | **+0.0064** (p=0.40) |
| IC-weighted 5, weights fitted **in-sample** | +0.0319 |

**Equal-weighting degrades the signal 6×**, which is V280's PnL result restated at the
information level. And the IC-weighted row is an *optimistic upper bound* — its weights
are fitted on the very data they are scored against — and it **still loses to
sma_crossover alone**. Reweighting cannot rescue this set.

## §3 — A tempting hypothesis, and its refutation

`rsi_signal`, `bb_signal` and `zscore_signal` are all **contrarian** constructions
(`(50-rsi)/50`, distance below the mean, negative z-score). Their consistently negative
ICs therefore look like a *sign* error — momentum paying where the code bets on
reversion. A horizon sweep made it look compelling:

| Signal | H=1 | H=2 | H=3 | H=5 | H=10 | H=20 |
|---|---:|---:|---:|---:|---:|---:|
| sma_crossover | +0.0092 | +0.0256 | +0.0351 | +0.0461 | +0.0514 | **+0.1100** |
| rsi_signal | −0.0227 | −0.0482 | −0.0518 | −0.0587 | −0.0594 | **−0.1498** |
| macd_crossover | +0.0291 | +0.0473 | +0.0509 | +0.0602 | +0.0945 | +0.1001 |
| bb_signal | −0.0126 | −0.0359 | −0.0387 | −0.0427 | −0.0547 | −0.1271 |
| zscore_signal | −0.0126 | −0.0359 | −0.0387 | −0.0427 | −0.0547 | −0.1271 |

Read naively: invert three signals and `rsi` becomes **+0.1498**, stronger than
`sma_crossover`'s +0.1100 — i.e. the strategy's entire edge, currently wired backwards.

**It does not survive an out-of-sample test.** Fitting each signal's sign on windows
1–16 and scoring on windows 17–32:

| | OOS IC (windows 17–32) |
|---|---:|
| sma_crossover alone | **+0.0538** |
| equal-weight 5, as wired | −0.0492 |
| equal-weight 5, **signs fitted on train** | **−0.0275** |

The fitted signs (`sma+, rsi+, macd−, bb+, zscore+`) are **nearly the opposite** of the
full-sample signs. The "wired backwards" pattern is an in-sample artifact: sign-fitting
produces *negative* OOS IC — worse than leaving the signals alone.

This is exactly the V227 → V231 failure mode (a shipped +$630 that distributional
measurement erased) caught before anything was built. It cost one script.

## §4 — A real defect found along the way

**`bb_signal` and `zscore_signal` are perfectly correlated: ρ = +1.0000.**

Not "similar" — identical, at every horizon, to four decimal places. Both reduce to a
standardised distance of price below its rolling mean. Any weighting scheme that treats
them as two signals **double-counts one**, and `AdaptiveCombiner.SIGNAL_FAMILIES` lists
both under `mean_reversion` (V279).

This is inert today (both are off by default), but it would silently corrupt any future
weighting work, and it is worth fixing independently of everything else here.

## §5 — Conclusion

**sma_crossover is the strategy's entire signal edge, and it is stable.** IC **+0.0534**
in-sample and **+0.0538** out-of-sample — the only quantity in this analysis that does
not move between halves.

Every alternative underperforms it: as-wired (+0.0053), sign-corrected in-sample
(+0.0250), duplicate-dropped (+0.0263), IC-weighted with lookahead weights (+0.0319).
**No combination of these five beats using one of them alone.**

This closes "improve the signal by reweighting, re-signing, or re-enabling the existing
set" — measured three ways, refuted three ways. It also fully vindicates the v1.0 default
that V280 found by accident: shipping one signal is not an oversight, it is the best
configuration available from this set.

**Improving signal therefore means finding a genuinely new predictor with stable
out-of-sample IC above ~0.05**, not rearranging these five. And note what the bar
implies: sma_crossover's +0.053 IC *is* the standing baseline's crisis +$599 / trend
+$2,997. A new signal must clear that bar out-of-sample, on a distribution, before it is
worth wiring — and V284 is the reminder that even a clean measurement need not convert
into PnL.

## §6 — Next steps

1. **Fix the `bb_signal` / `zscore_signal` duplication** (§4). Small, real, independent
   of any hypothesis.
2. **Do not re-run this set.** Reweighting, sign-flipping and horizon-shifting are all
   measured and refuted above; a future version proposing any of them should read §3
   first.
3. **A new-signal search must be OOS-first.** The §3 refutation only appeared under a
   train/test split; every number in §2 looked encouraging in-sample. Any candidate
   should be scored on held-out windows *before* a mechanism is built for it.
4. Unchanged and still the highest-value open items: the soft-fallback sweep
   (V282 §8) and execution friction (V272), which remains the one axis with a
   quantified, narrow, unexplored gap.
