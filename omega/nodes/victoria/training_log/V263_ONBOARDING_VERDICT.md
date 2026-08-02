# V263 — Kronos onboarding verdict

**Date:** 2026-08-02
**Scope:** Phase 0 (install) + Phase 1 (smoke) only. No scorer, no strategy code.
**Pre-registration:** [`V263.md`](V263.md)

---

## VERDICT: **STOP**

Kronos installs cleanly, runs fast, and produces plausible non-degenerate
forecasts on our frozen 1h corpus. It has **no measurable directional edge** on
that corpus and is **worse than a naive random-walk baseline on error at every
horizon and every symbol tested**.

The pre-declared gate **F4 (pooled Spearman ρ > 0.05) FAILED** at
**ρ = −0.027** — not merely below the bar, but slightly negative. **V263-2 is
not queued.**

This is a clean, cheap closure: ~2 hours wall-clock, $0 marginal spend, no
strategy coupling, and the failure is measured on 3,238 forecast windows rather
than argued from priors.

---

## 1. Install log — what worked, what broke

| Step | Result |
|---|---|
| Clone `shiyu-coder/Kronos` → `third_party/kronos` | OK, pinned at `67b630e` (2026-04-13) |
| `import` verification | **OK** — `from model import Kronos, KronosTokenizer, KronosPredictor` |
| `NeoQuasar/Kronos-Tokenizer-base` | OK — 3.96M params |
| `NeoQuasar/Kronos-small` | OK — **24.74M params**, matches the published 24.7M |
| Device | **MPS** (Apple GPU) auto-detected and used |
| Inference speed | **0.27 s/window** at `sample_count=1`; **1.0 s/window** at `sample_count=8` |

### Dependency handling — the one real decision

Kronos's `requirements.txt` pins `pandas==2.2.2`, `matplotlib==3.9.3`,
`huggingface_hub==0.33.1`. The omega env (Homebrew Python **3.14.6**, no venv)
runs pandas **3.0.1**, matplotlib **3.10.8**, hf_hub **1.17.0**, transformers
**5.9.0**.

**Installing those pins would have been a destructive downgrade of the shared
daemon environment.** Instead only the genuinely missing packages were installed:

```
python3 -m pip install --break-system-packages einops 'torch>=2.0'
# -> einops 0.8.2, torch 2.13.0 (cp314 macOS arm64 wheel), + sympy/networkx/mpmath
```

Kronos's actual imports are `numpy, pandas, torch, einops, tqdm, safetensors,
huggingface_hub.PyTorchModelHubMixin` — all stable APIs. It ran without
modification against the newer pandas/hf_hub. **No conflict materialised; no
existing omega dep was touched; no venv isolation was needed.**

**Footgun found:** `pip` on PATH is `/opt/homebrew/bin/pip` → **Python 3.11**,
not the 3.14 the omega code runs under. `pip index versions torch` reported
`INSTALLED: 2.12.1` while `python3 -c "import torch"` raised `ModuleNotFoundError`.
Always use `python3 -m pip` in this repo.

### Data-format reconciliation

V262's corpus stores `[open_ms, open, high, low, close, volume]` — **no `amount`
(quote-volume) column**, which the upstream example uses. This is a non-issue:
`KronosPredictor.predict` derives it (`kronos.py:531`) as
`amount = volume × mean(OHLC)` when absent. Timestamps are epoch **ms** →
converted to tz-naive UTC datetimes for `calc_time_stamps`.

---

## 2. Smoke test results

### 2a. The five named windows (BTCUSDT, 400-bar lookback → 24-bar forecast)

Plots: `/Volumes/gamma-systems-2/omega-victoria-data/v263_det_a/v263_kronos_smoke/window_*.png`

| Window | Realized 24h | Forecast 24h | Dir | RMSE ratio (vs naive) | Vol ratio |
|---|---:|---:|:--:|---:|---:|
| post-covid recovery (2020-06-15) | +0.90% | +1.79% | HIT | 1.26 | 0.14 |
| may-2021 crash (2021-05-19) | **−14.38%** | **+6.42%** | miss | 1.35 | 0.14 |
| 2022 bear (2022-06-15) | +2.02% | +11.50% | HIT | 2.11 | 0.27 |
| 2024aug crisis (2024-08-05) | **−7.12%** | **+9.65%** | miss | 1.44 | 0.14 |
| recent (2025-11-03) | −3.58% | −0.68% | HIT | 0.90 | 0.12 |

The two windows that matter most to this campaign — the **May-2021 crash** and the
**2024aug crisis window** — are both forecast *up* while price fell 14% and 7%.
The 2024aug plot is diagnostic: Kronos extrapolates a smooth continuation, misses
the crash entirely, and forecasts flat volume while realized volume spikes ~20×.

### 2b. Sanity checks (the four questions asked)

**1. Plausible forecasts?** **Yes.** No NaNs, no constant paths, in any cell.
Forecast prices stay within `[0.85, 1.20] ×` the last close over 24h — a
reasonable BTC range. The model is behaving correctly; it is not broken.

**2. Directional accuracy?** **No edge.** Raw accuracy 46–56% across cells,
mean ≈ 49.8%. Critically, **raw accuracy is drift-confounded**, so the roll-up
also reports realized-up-rate, balanced accuracy, MCC and Spearman ρ:

| Cell | n | rawAcc | realized↑ | forecast↑ | balAcc | MCC | **ρ** | p(ρ) | Bonf | RMSE ratio |
|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|--:|
| BTCUSDT h1 | 405 | 0.523 | 0.528 | 0.462 | 0.526 | 0.051 | **+0.066** | 0.184 | — | 1.172 |
| BTCUSDT h4 | 405 | 0.494 | 0.518 | 0.437 | 0.496 | −0.008 | −0.010 | 0.834 | — | 1.122 |
| BTCUSDT h12 | 405 | 0.462 | 0.511 | 0.452 | 0.463 | −0.075 | −0.101 | 0.043 | — | 1.186 |
| BTCUSDT h24 | 405 | 0.489 | 0.521 | 0.435 | 0.492 | −0.017 | −0.059 | 0.237 | — | 1.369 |
| SOLUSDT h1 | 404 | 0.480 | 0.473 | 0.463 | 0.482 | −0.036 | −0.040 | 0.427 | — | 1.194 |
| SOLUSDT h24 | 404 | **0.562** | 0.497 | 0.493 | 0.565 | 0.129 | +0.068 | 0.171 | — | 1.316 |
| XRPUSDT h1 | 405 | 0.474 | 0.543 | 0.442 | 0.483 | −0.033 | −0.095 | 0.055 | — | 1.179 |
| XRPUSDT h24 | 405 | 0.499 | 0.499 | 0.516 | 0.502 | 0.005 | −0.043 | 0.382 | — | 1.331 |

- **Mean Spearman ρ = −0.027** vs the F4 bar of **+0.05** → **F4 FAIL**.
- **0 of 8 cells** pass Bonferroni (α = 0.05/8 = 0.0063).
- The only nominally interesting cell, **SOLUSDT h24** (raw 56.2%, uncorrected
  binomial p = 0.015), is **not** a drift artifact (realized↑ = 0.497) but is
  **1 of 8 tested cells at p = 0.015 > 0.0063**, and it points the opposite way
  from BTCUSDT h24 (0.489). That is the 1-in-8 draw you expect by chance, and
  reporting it as a finding would be the exact Goodhart move this campaign has
  spent 29 versions learning not to make.

**3. RMSE / MAPE vs naive?** **Loses everywhere.** Median RMSE ratio 1.12–1.37
across all 8 cells; **0/8 below 1.0**. BTCUSDT h24 median MAPE **1.48%** vs naive
**0.99%**. Kronos beats the naive baseline on only 28–41% of individual windows
depending on horizon.

**4. Distribution shape?** **Over-smooth — it does not capture volatility
clustering.** Median forecast/realized bar-to-bar log-return dispersion ratio is
**0.31–0.39** across cells (0.12–0.27 on the named windows). Kronos forecasts
paths roughly **one-third as volatile as reality**, and forecast volume is nearly
flat through realized volume spikes. This is the classic conditional-mean
collapse of a sampled autoregressive forecaster and is the single clearest
statement of why it has nothing to trade here.

### 2c. A systematic short bias

Forecast up-rate is **0.435–0.516 (mean 0.46)** while realized up-rate is
**0.473–0.543 (mean 0.51)**. Kronos is consistently biased *down* relative to our
universe's realized drift — plausibly a prior inherited from its
equity/A-share-heavy pretraining mix. Noted as an observation; it is not
exploitable, because the bias is unconditional (it shows no correlation with
realized moves — that is what ρ ≈ 0 means).

### 2d. Determinism

Two runs with identical seed and arguments produced **bit-identical** forecasts
across all five named windows (e.g. `109784.2031` vs `109784.2031`). Seeded
sampling is reproducible; `--greedy` (`top_k=1`) is available for sampling-free
decoding. **No determinism defect found** — a welcome contrast to V262's two.

### 2e. Methodological note — the sample-count fairness fix

The first pass used `sample_count=1`, which compares a **single draw from a
predictive distribution** against a **point-forecast** baseline — structurally
unfair to Kronos (a single sampled path carries the full predictive variance).
All reported numbers use **`sample_count=8`**, which averages 8 sampled paths and
approximates the conditional mean. This *improved* Kronos's numbers
(BTCUSDT h24 RMSE ratio 1.47 → 1.37) and it still loses on every cell. The
verdict is not an artifact of unfair baselining.

---

## 3. Why STOP rather than CAVEATED PROCEED

A CAVEATED PROCEED would be right if the model showed edge under some restricted
condition. It does not:

- Not at any horizon — the sweep `{1, 4, 12, 24}` was pre-declared and all four fail.
- Not on any symbol — BTC, SOL, XRP all fail.
- Not on error — 0/8 cells beat a random walk.
- Not on direction — pooled ρ is **negative**.

There is no restriction left to caveat. And the failure is *upstream* of friction:
V262-2 at least found a real 14 bps gross effect that friction then killed. Kronos
has **no gross effect to kill**. Building an F1/F2/F3 scorer on top of a forecaster
with ρ = −0.027 would produce a guaranteed refutation at 100× the cost.

### What would reopen this lane

Not speculation — concrete, in rough order of cost:

1. **Fine-tuning.** Kronos ships a `finetune/` pipeline. Zero-shot failure on
   crypto 1h is genuinely uninformative about the fine-tuned case; the model was
   pretrained on a mix our universe is a small and unusual corner of. This is the
   only serious rehabilitation path.
2. **`Kronos-base` (102.3M) / `Kronos-mini` (4.1M, 2048 ctx).** Tests whether the
   binding constraint is capacity or context rather than domain. Cheap (~1 hour)
   but a low prior given how flat the small-model result is.
3. **Distributional rather than point use.** The forecast *spread* across sampled
   paths might be a usable volatility/uncertainty estimate even when the *mean* is
   directionless — a regime input, not an entry signal. This is the most likely
   place any residual value lives, and it does not require directional edge.

None of these is queued. (1) and (3) are the ones worth revisiting if the campaign
returns to this lane.

---

## 4. Cost estimates for a hypothetical V263-2 (recorded, not queued)

Measured: **1.0 s/window** at `sample_count=8`, `pred_len=24`, Kronos-small on MPS.

| Item | Estimate |
|---|---|
| Naive walk-forward, 32,000 windows × 10 names | 320,000 inferences ≈ **89 GPU-hours** |
| With `predict_batch` (batch 32, same lookback/horizon) | ≈ **6–12 hours** — the batch path is the only tractable route |
| At `sample_count=1` (unfair, but 4× cheaper) | ≈ 22 h naive / 2–4 h batched |
| Model + tokenizer storage (HF cache, gamma) | **110 MB** |
| Upstream repo | 25 MB |
| Marginal $ spend | **$0** (local MPS inference, no API) |

Compute was never the blocker. The blocker is that there is no signal to compute on.

---

## 5. Campaign placement

Track H in [`V254_ALT_DATA_SCOPING.md`](V254_ALT_DATA_SCOPING.md).

This is refutation-pattern **R1** (no effect present), not R2 (below resolution)
or R3 (calendar-bound N) — and notably it is the **cheapest** closure in the
campaign to date: killed at Phase 0/1 for ~2 hours and $0, before any scorer
existed. That is the separator-proof discipline (standing rule from V234) working
as designed.

**It does not change the standing state.** The two validated lanes remain spot
Victoria + funding-carry across the full liquid book, and **live-paper (V253)
remains the only lane accruing new independent evidence** toward the recent-N ≥ 20
resume gate. All V241–V263 flags stay OFF.
