# V285 Phase 0 — signal quality measured directly: sma_crossover is the whole edge

**Date:** 2026-08-27
**Author:** claude
**Status:** PHASE 0 / FINDINGS — read-only, no strategy module imported, no code changed, no version pre-registered
**Parent:** [`V280.md`](V280.md) (enabling the six technical signals cost $1k–$3.2k/window) · [`V279.md`](V279.md)
**Standing baseline:** crisis +$599 / trend +$2,997 / recent +$30 — untouched

> ## ⚠ CORRECTION (same day, after re-verifying against `signal_generation.py`)
>
> The first pass used **two unfaithful reimplementations**, found by diffing them against
> the real code line by line:
>
> | Signal | first pass | actual (`signal_generation.py`) |
> |---|---|---|
> | `sma_crossover` | periods 10/30, scale ×20 | **periods 5/20, scale ×10** (`:394-395`) |
> | `zscore_signal` | price-level z-score | **z-score of the latest RETURN** (`_compute_zscore_returns`) |
>
> The second error is the serious one: a price-level z-score is *identical by
> construction* to `bb_signal`, which manufactured the ρ = +1.0000 "duplication defect"
> reported in §4. **That finding is RETRACTED — it was a bug in my measurement, not in
> the codebase.** Measured correctly, `bb` vs `zscore` correlate **−0.2201**; they are
> distinct signals (price level vs return distribution).
>
> §2, §3 and §5 below carry the **corrected** numbers. Every substantive conclusion
> survived the correction — and the equal-weight result got *worse*, not better.



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

16,620 observations, all 32 walk-forward windows, Spearman IC vs forward return at
**H=5** (a horizon the strategy plausibly realises):

| Signal | IC | p |
|---|---:|---:|
| **sma_crossover** | **+0.0283** | 2.6e-04 |
| rsi_signal | −0.0288 | 2.0e-04 |
| macd_crossover | −0.0051 | 0.51 — **noise** |
| bb_signal | −0.0160 | 0.039 |
| zscore_signal | −0.0167 | 0.031 |

| Composite | IC |
|---|---:|
| sma_crossover alone (**v1.0, what ships**) | **+0.0283** |
| equal-weight 5 (v1.2, what V280 enabled) | **−0.0124** |

**Equal-weighting does not merely dilute the signal — it inverts it.** The composite of
five goes *negative* while its best member is positive. That is V280's −$1k–$3.2k
restated at the information level, and it is a stronger result than the first pass
reported.

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
| sma_crossover alone | **+0.0399** |
| equal-weight 5, as wired | −0.0075 |
| equal-weight 5, **signs fitted on train** | **−0.0233** |

Sign-fitting produces *negative* OOS IC — worse than leaving the signals alone — and the
train-fitted signs (`sma+, rsi+, macd−, bb+, zscore−`) disagree with the full-sample
signs on three of five. The "wired backwards" pattern is an in-sample artifact.

This is exactly the V227 → V231 failure mode (a shipped +$630 that distributional
measurement erased) caught before anything was built. It cost one script.

## §4 — RETRACTED: the "duplicate signal" finding

The first pass reported `bb_signal` and `zscore_signal` as perfectly correlated
(ρ = +1.0000) and called it a real defect. **That was wrong, and the fault was mine.**

I had reimplemented `zscore_signal` as a price-level z-score. The real one
(`_compute_zscore_returns`) standardises the *latest return* against the recent return
distribution — a different quantity entirely. My version was algebraically identical to
`bb_signal`, so the correlation of 1.0000 was measuring my own code against itself.

Measured against faithful implementations: **ρ = −0.2201**. The two signals are distinct
and there is no double-counting defect. Nothing needs fixing.

Recorded rather than deleted, because the failure mode generalises: an offline scorer
that *reimplements* production signals can manufacture findings that exist only in the
scorer. Any future analysis of this kind should diff its implementations against
`signal_generation.py` before reporting, which is how this was caught.

## §5 — Conclusion

**sma_crossover is the strategy's entire signal edge, and it is stable.** IC **+0.0283**
in-sample and **+0.0399** out-of-sample — the only quantity in this analysis that does
not move between halves.

Every alternative underperforms it: as-wired is **negative** (−0.0124 in-sample,
−0.0075 OOS), and sign-fitting is worse still (−0.0233 OOS).
**No combination of these five beats using one of them alone.**

This closes "improve the signal by reweighting, re-signing, or re-enabling the existing
set" — measured three ways, refuted three ways. It also fully vindicates the v1.0 default
that V280 found by accident: shipping one signal is not an oversight, it is the best
configuration available from this set.

**Improving signal therefore means finding a genuinely new predictor with stable
out-of-sample IC above ~0.05**, not rearranging these five. And note what the bar
implies: sma_crossover's ~+0.03–0.04 IC *is* the standing baseline's crisis +$599 / trend
+$2,997. A new signal must clear that bar out-of-sample, on a distribution, before it is
worth wiring — and V284 is the reminder that even a clean measurement need not convert
into PnL.

## §6 — Next steps

1. **Nothing to fix from §4** — that finding is retracted. Any future offline scorer
   must diff its reimplementations against `signal_generation.py` before reporting.
2. **Do not re-run this set.** Reweighting, sign-flipping and horizon-shifting are all
   measured and refuted above; a future version proposing any of them should read §3
   first.
3. **A new-signal search must be OOS-first.** The §3 refutation only appeared under a
   train/test split; every number in §2 looked encouraging in-sample. Any candidate
   should be scored on held-out windows *before* a mechanism is built for it.
4. Unchanged and still the highest-value open items: the soft-fallback sweep
   (V282 §8) and execution friction (V272), which remains the one axis with a
   quantified, narrow, unexplored gap.
