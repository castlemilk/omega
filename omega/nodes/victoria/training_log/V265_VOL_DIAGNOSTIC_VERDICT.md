# V265 — Kronos distributional (volatility-forecast) verdict

**Date:** 2026-08-08
**Scope:** diagnostic only. Regime/sizing lane. No strategy code, no flag, no
overlay, no live-broker.
**Pre-registration:** [`V265.md`](V265.md) (committed at `d1f2cf9`, before any cell ran)

---

## VERDICT: **CAVEATED — 2 of 3 gates PASS. V265-2 is NOT queued.**

| Gate | Statistic | Bar | Result | CI95 (10k paired bootstrap) | |
|---|---|---|---:|---|:--:|
| **F5-vol** | pooled RMSE ratio | < 0.90 | **1.0454** | [1.0047, 1.0837] | **FAIL** |
| **F5-corr** | pooled Spearman ρ | > +0.20 | **+0.4156** | [+0.3852, +0.4441] | **PASS** |
| **F5-regime** | pooled Kruskal-Wallis p | < 0.01 | **4.6 × 10⁻¹¹⁹** | H ∈ [476, 639] | **PASS** |

P(F5-vol passes) = **0.000**. P(F5-corr passes) = **1.000**. Neither near gate is
near its bar; both are decided far outside sampling noise.

**The headline is not "Kronos can't forecast volatility." It plainly can** — every
one of the eight cells shows a positive, highly significant rank correlation with
realized volatility, and the quintile separation is the strongest effect this
campaign has measured on anything. The reason V265-2 is not queued is different
and is stated plainly in §4: the information is real, but it is **mostly already
in a free 24-bar rolling standard deviation**, and the part that isn't costs
seconds of GPU inference per window to obtain.

---

## 1. What was run

One arm — the **fine-tuned** Kronos from V264 (fine-tuned tokenizer + the
epoch-1 best-by-val predictor). Eight pre-declared V263/V264 cells, unchanged.
405 windows/cell, lookback 400, `sample_count = 16`, batch 4. 3,240 windows,
51,840 sampled forecast paths. Holdout fence `2025-01-01` applied to the
**lookback start**, so no scored window touches a bar the model trained on.
Marginal spend **$0** (local MPS). Wall-clock ≈ 1 h 50 m.

**Determinism: PASS.** A full 405-window cell (BTCUSDT_h1) was re-run from
scratch after the main run and is **byte-identical** to the stored artifact
(`cmp`, not a statistic comparison). Per-batch seeds are a deterministic function
of the window index. Zero NaN forecasts across all 3,240 windows.

The scorer had to port the vendored decode path: `kronos.py:467` applies
`np.mean(preds, axis=1)`, which destroys exactly the cross-sample dispersion V265
measures, and `predict_batch` then wraps the averaged result in DataFrames. The
port keeps the sample axis and is otherwise faithful (same normalisation, same
clip, same decode loop). **Vendored code is unmodified**, same discipline V264
used for the fine-tune pipeline.

## 2. Per-cell results

`fcVol` / `naive` / `real` are mean per-bar volatilities in log-return units.
`fc/real` is the **level calibration ratio** — the single most informative column
in this document. `rmseRc` is the secondary in-sample scale-calibrated ratio
(pre-declared in V265.md §5 as diagnostic, **not** gated).

| cell | fcVol | naive | real | **fc/real** | rmseR | rmseRc | ρ(K) | ρ(naive) | **Δρ** | KW p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT_h1 | 0.00326 | 0.00424 | 0.00325 | **1.002** | **0.873** | 0.885 | +0.332 | +0.289 | +0.043 | 1.6e-09 |
| BTCUSDT_h4 | 0.00300 | 0.00424 | 0.00376 | 0.799 | **0.884** | 0.857 | +0.529 | +0.450 | +0.079 | 1.1e-23 |
| BTCUSDT_h12 | 0.00270 | 0.00424 | 0.00416 | 0.651 | 1.071 | 0.929 | +0.453 | +0.408 | +0.045 | 1.2e-15 |
| BTCUSDT_h24 | 0.00230 | 0.00424 | 0.00431 | 0.533 | 1.196 | 0.898 | +0.428 | +0.369 | +0.058 | 2.0e-15 |
| SOLUSDT_h1 | 0.00602 | 0.00768 | 0.00596 | **1.010** | 0.943 | 0.962 | +0.272 | +0.249 | +0.022 | 4.7e-07 |
| SOLUSDT_h24 | 0.00435 | 0.00768 | 0.00769 | 0.566 | 1.275 | 0.975 | +0.447 | +0.439 | +0.007 | 1.2e-16 |
| XRPUSDT_h1 | 0.00534 | 0.00698 | 0.00529 | **1.010** | 0.953 | 0.961 | +0.318 | +0.300 | +0.017 | 4.5e-12 |
| XRPUSDT_h24 | 0.00377 | 0.00698 | 0.00701 | 0.538 | 1.168 | 0.960 | +0.547 | +0.480 | +0.067 | 2.9e-24 |
| **POOLED** | | | | | **1.045** | 0.928 | **+0.416** | +0.373 | **+0.042** | 4.6e-119 |

- **8/8** cells beat the naive baseline on rank correlation.
- **4/8** cells beat it on RMSE — and they are exactly the three h1 cells plus BTC h4.
- Pooled quintile mean realized-vol rank rises monotonically across `σ̂` quintiles:
  **0.347 → 0.416 → 0.504 → 0.535 → 0.699**. In raw units (BTC h24):
  0.00301 → 0.00376 → 0.00449 → 0.00440 → 0.00590, a **1.96× spread** from lowest
  to highest forecast-spread quintile.

## 3. The horizon structure — why F5-vol failed

The `fc/real` column is monotone in horizon and nearly identical across all three
symbols:

| horizon | fc/real (BTC) | fc/real (SOL) | fc/real (XRP) |
|---|---:|---:|---:|
| h1 | 1.002 | 1.010 | 1.010 |
| h4 | 0.799 | — | — |
| h12 | 0.651 | — | — |
| h24 | 0.533 | 0.566 | 0.538 |

At **h1 the fine-tuned model's cross-sample dispersion is level-accurate to within
1%**, on three different assets, with no calibration applied. That is a genuinely
striking result and it is not what V263 would have predicted — V263 measured the
*zero-shot* model's paths at ~⅓ of realized volatility. V264's diagnosis that
fine-tuning taught Kronos our volatility is now confirmed **quantitatively, at
the 1-hour horizon.**

The failure is a **dispersion-propagation defect, not an information defect**.
`σ̂` divides each timestep's cross-sample dispersion by `√t`, the correct
de-trending under a diffusion. The ratio decaying to ~0.54 by h24 means the
sampled paths fan out **sub-diffusively** — they stay closer together than
independent random walks would, so the model under-propagates its own uncertainty
as the horizon extends. Meanwhile realized volatility *rises* with horizon
(BTC 0.00325 → 0.00431). The two move in opposite directions and RMSE punishes
the gap, which is why the RMSE ratio degrades monotonically (0.873 → 1.196) while
rank correlation stays high (+0.33 → +0.43) throughout.

The secondary calibrated ratio confirms the diagnosis: granting a **free
in-sample** global scale per cell pulls the pooled ratio from 1.045 to **0.928** —
a large repair, and it *still misses the 0.90 bar*. So the level error is real and
most of the RMSE gap is scale, but scale is not the whole gap either.

## 4. Honest diagnosis — the question the brief asked

> *If REFUTED, is it because Kronos-spread is uncorrelated with realized vol, or
> because the naive baseline is just too strong at 1h?*

**Neither, and the distinction matters.**

1. **Kronos-spread is emphatically not uncorrelated.** ρ = +0.416 pooled, CI
   [+0.385, +0.444], all eight cells significant, KW p = 10⁻¹¹⁹. This is not a
   marginal effect and it is not an R1 (no-effect) refutation. Any claim that
   "Kronos knows nothing about our volatility" is contradicted by this document.
2. **The naive baseline is strong, but Kronos beats it — by a small, real
   margin.** Naive pooled ρ = +0.373. The paired delta is **+0.0424, CI95
   [+0.0134, +0.0722], P(Δ > 0) = 0.9973.** The incremental rank information is
   statistically established and **8/8 cells agree in sign**. It is simply small.
   Hourly volatility is highly persistent — vol clustering means a 24-bar rolling
   RMS already captures most of what is knowable, and a 24.7M-parameter
   transformer sampling 16 autoregressive paths recovers about **+0.04 of rank
   correlation** beyond it.
3. **The RMSE failure is a third, separate thing** — the sub-diffusive
   calibration defect of §3, which is a property of the model's sampler, not of
   the information content.

So the correct classification is **R2 (below the value bar), with a calibration
defect layered on top** — the same family as V264, and *not* the "naive is too
strong" story. The naive baseline is strong; Kronos is stronger; the increment
does not justify the machine.

### Why CAVEATED resolves to "do not build"

The pre-registration required a judgement call at 2/3. The call is **no**, on
four grounds:

1. **The gated economic statistic is the one that failed**, and it failed
   decisively (CI excludes even parity with naive, let alone 0.90). F5-corr and
   F5-regime establish that a *ranking* exists; F5-vol was the gate that asked
   whether the forecast is usable as a *quantity*, which a sizing overlay needs.
2. **The increment is +0.042 ρ over an estimator that costs one subtraction.**
   Kronos costs **~3.1 s/window at h24** on this host for 16 paths. A drop-only
   sizing overlay driven by a rank signal that a rolling std reproduces to within
   0.04 is a large amount of new machinery — model loading, checkpoint
   provenance, MPS inference in the live path, a new failure mode in the daemon —
   bought for very little.
3. **Precedent.** This is the pattern the V241–V258 retrospective names as the
   campaign's dominant waste: building a mechanism against an objective that sits
   below the value bar. V264 declined to move a bar by 0.0035; V265 declines to
   build on a 2/3 with the economically-binding gate missed by 0.145.
4. **The one place it *does* work is already served.** The cells where Kronos
   beats naive on RMSE are h1 and h4 — precisely the horizons V262-2 closed for
   trading, because a real ~14 bps 1h effect sits below a 24 bps friction wall.
   A better 1-hour volatility estimate has no consumer in the standing lanes,
   which trade daily bars.

### The honest reopener (recorded, not queued)

If the regime/sizing lane ever needs a **short-horizon** volatility input, the
h1/h4 result is the strongest thing Kronos has produced in three versions:
level-accurate to 1% at h1 across three assets, and RMSE-beating naive at 0.873 /
0.884 / 0.943 / 0.953. Stating it does not move the bar — the gate was declared
pooled and pooled is how it is scored — but pretending the horizon structure
isn't there would be dishonest. Any revisit should be **h1/h4-only, sizing-lane,
and must clear its own pre-registered bar against a same-cost baseline.**

## 5. Campaign placement — Track H fully closes

V263 closed Track H at zero-shot and named fine-tuning as reopener (1). V264
executed it and closed that, naming **distributional use** as reopener (3) — the
last untested Kronos idea. V265 has now executed reopener (3).

**All three Kronos reopeners are now spent.** The foundation-model direction is
exhausted for this universe, and the closure is better-evidenced than either
predecessor's: V263 closed on "no effect," V264 on "effect below the bar," and
V265 closes on **"large effect, mostly redundant with a free baseline, and
mis-calibrated where it isn't."**

Remaining untested in principle: Kronos-base (102.3M). Prior remains low —
V264 established the 24.7M model already overfits 374k bars by epoch 2, so
capacity is not the binding constraint, data is. **Not queued.**

**Standing state unchanged.** Two validated lanes: **spot Victoria** and
**funding-carry** (V255.C/D basis-hedged carry, the one confirmed alpha).
**Live-paper (V253) remains the only lane accruing new independent evidence**
toward the recent-N ≥ 20 resume gate. All V241–V265 flags stay OFF. No strategy
code was touched in this version.

## 6. Operational notes

- **Live-paper daemon untouched.** launchd `com.omega.live_paper`, PID 10329. No
  V265 process interacted with it.
- **V264's OOM lesson applied.** Batch was held at 4 × 16 = 64 concurrent
  sequences (V264 established 64 as the stable ceiling; 192 was SIGKILLed). All
  log polling used `tail`/`sed -n`, never a repo-wide `grep`. No OOM, no stall;
  throughput held flat at 3.0–3.8 s/window on the h24 cells for the whole run.
- Artifacts are on gamma, never in the repo.

## 7. Files

| Artifact | Path |
|---|---|
| Vol scorer (sample-path port + F5 gates) | `scripts/v265_kronos_vol_scorer.py` |
| Paired bootstrap CIs | `scripts/v265_kronos_bootstrap.py` |
| Per-window artifacts + summary | `$AUDIT/v265/vol/finetuned/` |
| Bootstrap result | `$AUDIT/v265/vol/finetuned/bootstrap.json` |
| Fine-tuned checkpoints (from V264) | `$AUDIT/v264/checkpoints/{tokenizer,predictor}/best_model` |

`$AUDIT` = `/Volumes/gamma-systems-2/omega-victoria-data`.
