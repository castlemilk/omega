# V264 — Kronos fine-tuning verdict

**Date:** 2026-08-08
**Scope:** Phases 0–4. Fine-tune (tokenizer + predictor) on the V262 1h corpus,
then re-run the V263 F4 gate on a strict holdout. No strategy code, no scorer
beyond the gate, no live-broker.
**Pre-registration:** [`V264.md`](V264.md)

---

## VERDICT: **STOP**

The pre-declared gate **F4-ft (pooled Spearman ρ > +0.05) FAILED** at
**ρ = +0.0465**.

It failed by 0.0035 — close enough that the honest statement is not "fine-tuning
made it worse" but **"fine-tuning did not settle it, and the campaign's own rules
say a locked bar missed is a bar missed."** The supporting statistics say the same
thing more usefully than the point estimate does:

| Quantity | Value | CI95 (10k paired bootstrap) | Reading |
|---|---:|---|---|
| Fine-tuned pooled ρ | **+0.0465** | [+0.0096, +0.0830] | real but small; **excludes 0**, **does not exclude the bar** |
| Zero-shot pooled ρ (same windows) | +0.0277 | [−0.0088, +0.0645] | indistinguishable from 0 |
| **Δ (fine-tuned − zero-shot)** | **+0.0188** | **[−0.0108, +0.0469]** | **includes 0 — the improvement is NOT established** |

P(true fine-tuned ρ > bar) = **0.42**. A coin flip. P(Δ > 0) = 0.89 — suggestive,
not significant.

So the fine-tuned model has a **small, non-zero directional rank correlation**
(the CI excludes zero, which V263 could not say), and **fine-tuning cannot be
shown to be what produced it.**

**V264-2 is NOT queued.** Reasoning in §5.

---

## 1. What was actually done

| Phase | Result |
|---|---|
| 0 — preflight | MPS available on M2 Max/64 GB; torch 2.13.0; corpus 665,824 bars verified |
| 1 — data prep | temporal split, leakage assertions PASS |
| 2 — tokenizer fine-tune | 3 epochs, 51.6 min, val loss ↓ monotonically |
| 3 — predictor fine-tune | 3 epochs, 91.4 min, val bottoms at epoch 1 |
| 4 — F4-ft | 2 arms × 8 cells × 405 windows = 6,480 forecasts |

Total wall-clock ≈ 5.5 h. Marginal spend **$0** (all local MPS inference).

### 1a. Two upstream defects found at Phase 0

Both in `third_party/kronos/finetune_csv/`, both blocking, both worked around
**without modifying vendored code**:

1. **No MPS branch.** `finetune_tokenizer.py:291` and `finetune_base_model.py:375`
   both read `device = cuda if torch.cuda.is_available() else cpu`. As shipped, on
   this host, fine-tuning would have run on CPU — silently, at roughly an order of
   magnitude slower, with no warning.
2. **Single-CSV, ratio split.** `CustomKlineDataset` reads one CSV and splits by
   row *ratio*. Feeding it 13 concatenated symbols would let a 425-bar sliding
   window straddle a symbol boundary — conditioning a SOL forecast on BTC history —
   and a ratio split cannot express V264's date split.

`scripts/v264_kronos_finetune.py` ports the pipeline faithfully (same feature
layout, same per-window z-score + clip(5.0), same losses, same AdamW/OneCycleLR,
same grad-clip norms 2.0/3.0) with an MPS device and a multi-symbol dataset whose
windows never cross a symbol boundary.

### 1b. Anti-leakage

Split is strictly temporal and disjoint by calendar date:

| Split | Range | Symbols | Bars |
|---|---|--:|--:|
| train | → 2023-12-31 | 13 | 373,871 |
| val | 2024 | 14 | 114,113 |
| test (holdout) | 2025-01-01 → 2026-07 | 13 | 177,840 |

`v264_kronos_prep.py` asserts `max(train) < min(val)` and `max(val) < min(test)`
per symbol and refuses to write on violation — **PASS**. F4-ft windows are further
constrained so the **400-bar lookback start**, not merely the forecast anchor, is
≥ 2025-01-01: no scored forecast can condition on a bar the model trained on.

MATICUSDT has no test bars (series ends 2024-09) and POLUSDT has no train bars
(archive starts 2024-09) — the known V255.D-era data-era gap, not a new defect.
Each is simply dropped from the split where it is empty.

---

## 2. Fine-tune quality gate — **PASS**

### Tokenizer (3.96M params, stride 4 → 92,096 windows/epoch)

| Epoch | Train loss | Val loss (recon MSE) | Time |
|---|---:|---:|---:|
| 1 | −0.029764 | 0.003665 | 17.8 min |
| 2 | −0.030487 | 0.003473 | 16.8 min |
| 3 | −0.030679 | **0.003470** | 17.0 min |

Train ↓ monotone, val ↓ monotone, no divergence. Reconstruction MSE fell from
0.0067 (step 5) to ~0.0036. **Converged** — epoch 3 bought 0.09%.

### Predictor (24.74M params, frozen fine-tuned tokenizer, stride 6 → 61,403 windows/epoch)

| Epoch | Train loss | Val loss | Time |
|---|---:|---:|---:|
| 1 | 2.618028 | **2.569746** ← best, checkpointed | 31.3 min |
| 2 | 2.540422 | 2.576359 | 30.3 min |
| 3 | 2.527136 | 2.578182 | 29.8 min |

Train ↓ monotone; val bottoms at epoch 1 then drifts up 0.33%. Mild overfit onset,
not divergence. Checkpointing is best-by-val, so **Phase 4 used the epoch-1
predictor.**

This matters for the anti-Goodhart record: **the epoch budget was not tuned against
F4-ft.** 3 epochs were declared up front, all 3 ran, the gate was checked once. The
curves independently say more epochs would not have helped — the predictor was
already overfitting by epoch 2.

---

## 3. F4-ft — the gate

Eight V263 cells, unchanged. 405 windows/cell, `sample_count=8`, lookback 400.
Both arms scored on **byte-identical window sets** (asserted: realized returns
match across arms).

| cell | zero-shot ρ | **fine-tuned ρ** | Δ | p(ρ) | Bonf | RMSE ratio | rawAcc | MCC |
|---|---:|---:|---:|---:|:--:|---:|---:|---:|
| BTCUSDT_h1 | +0.0362 | +0.0920 | +0.0558 | 0.0645 | — | 1.216 | 0.533 | +0.067 |
| BTCUSDT_h4 | −0.0048 | −0.0290 | −0.0242 | 0.5595 | — | 1.328 | 0.481 | −0.037 |
| BTCUSDT_h12 | −0.0473 | −0.0218 | +0.0255 | 0.6606 | — | 1.686 | 0.514 | +0.026 |
| BTCUSDT_h24 | +0.0528 | +0.1068 | +0.0540 | 0.0319 | — | 2.093 | 0.516 | +0.032 |
| SOLUSDT_h1 | +0.0179 | −0.0301 | −0.0480 | 0.5451 | — | 1.263 | 0.496 | −0.003 |
| SOLUSDT_h24 | +0.0731 | +0.1067 | +0.0336 | 0.0319 | — | 2.239 | 0.523 | +0.046 |
| XRPUSDT_h1 | −0.0265 | −0.0012 | +0.0253 | 0.9813 | — | 1.297 | 0.476 | −0.049 |
| XRPUSDT_h24 | +0.1204 | +0.1487 | +0.0283 | **0.0028** | **PASS** | 1.898 | 0.551 | +0.118 |
| **POOLED** | **+0.0277** | **+0.0465** | **+0.0188** | | 1/8 | **0/8 < 1.0** | | |

- **F4-ft: FAIL** (+0.0465 vs +0.05).
- 4 of 8 cells clear the bar individually; **1 of 8** survives Bonferroni
  (α = 0.00625) — XRPUSDT_h24.
- **Stretch F1-ft: FAIL.** 0 of 8 cells beat the naive random walk on RMSE; the
  bar was ≥ 4 of 8.

### 3a. The horizon pattern is real and points the wrong way

All three h24 cells are positive (+0.107, +0.107, +0.149) while h1/h4/h12 are
mixed-to-negative. Rank correlation improves with horizon. But **RMSE ratio also
gets monotonically worse with horizon** (BTC: 1.22 → 1.33 → 1.69 → 2.09), and
fine-tuning made RMSE *worse than zero-shot* at every cell (BTC h24: 1.321 → 2.093;
SOL h24: 1.346 → 2.239).

That combination has a clean mechanical reading. V263 diagnosed the zero-shot model
as suffering **conditional-mean collapse** — it forecast paths ~⅓ as volatile as
reality. Fine-tuning on crypto 1h partially fixed that: the model now emits
higher-dispersion paths that better match our universe's volatility. Higher
dispersion **helps rank ordering slightly** and **hurts point-forecast error a
lot**. Fine-tuning taught Kronos our volatility, not our direction.

### 3b. V263's headline number was period-dependent, not wrong

V263 reported zero-shot pooled ρ = **−0.027** over 2020→2026. V264 measures the
**same zero-shot model** at **+0.0277** over 2025→2026. Nothing is contradictory —
a zero-shot model cannot be contaminated, and these are simply different periods.
But the swing is instructive: pooled ρ for this model moves ~0.055 between periods,
which is **larger than the entire F4 bar**.

That is the most durable finding in this document. It means neither V263's −0.027
nor V264's +0.0465 is a stable estimate of anything, and it retroactively softens
V263's confident R1 ("no effect present") classification to something closer to
"effect, if any, is smaller than the between-period noise." Recorded as a
correction to the campaign record, not as a rescue of the lane.

---

## 4. Why STOP and not CAVEATED PROCEED

The temptation is real: 4/8 cells over the bar, pooled CI excluding zero, a miss of
0.0035. Every one of those observations is a reason to *look again*, and none is a
reason to *build*.

1. **The bar is locked.** V264.md §4a: *"No post-hoc adjustment, in either
   direction, for any reason."* +0.0465 < +0.05. Moving the bar 0.004 after seeing
   the number is precisely the Goodhart move this campaign has spent 30 versions
   learning not to make, and it would be the first time the campaign did it.
2. **The delta is not significant.** Δ CI95 [−0.0108, +0.0469] includes zero. The
   pre-registered hypothesis was *"fine-tuning produces edge zero-shot lacked."*
   That specific claim is **unsupported**, independent of the gate.
3. **RMSE moved the wrong way, decisively.** 0/8, and worse than zero-shot in
   every cell. Whatever fine-tuning bought, it was not forecast accuracy.
4. **ρ ≈ 0.047 is far below the friction wall.** This is the V262-2 precedent
   applied honestly: V262-2 found a *real* ~14 bps 1h mean-reversion with p≈0 at
   n=38k and it still died against the 24 bps round-trip. A rank correlation of
   0.047 at 1h, whose own CI reaches down to 0.0096, is not in the same postcode as
   tradability. Building an F1/F2/F3 scorer here would be a guaranteed refutation
   at ~100× the cost — the "mechanism against a below-resolution objective" pattern
   the V241–V258 retrospective names as the campaign's dominant waste.
5. **Only 1/8 survives multiple-comparison correction**, and it is a single cell
   (XRPUSDT_h24) in a sweep explicitly designed to expect one such draw.

---

## 5. Campaign placement — Track H closes

This is refutation pattern **R2 (below resolution)**, not V263's R1 (no effect).
The distinction is now measurable: there *is* a small positive directional
correlation whose CI excludes zero; it simply sits below the pre-registered
tradability bar and below the between-period noise in its own estimate.

**Track H (foundation models) is CLOSED for this universe** — both zero-shot
(V263) and fine-tuned (V264) fail the same gate, and the fine-tuned arm fails the
stretch error gate more badly than zero-shot did.

**Honest scope of the closure.** V264 refutes *Kronos-small, fine-tuned 3 epochs on
our 1h corpus, as a directional forecaster*. It does not refute foundation models
generally. What remains untested, in descending order of prior:

1. **Distributional rather than point use** — V263's reopener (3), still untouched
   and now *better* motivated: V264's evidence is that fine-tuning taught the model
   our **volatility structure** (§3a). A volatility/uncertainty estimate feeding
   the regime layer needs no directional edge to be useful. This is the only Kronos
   idea this campaign has not tested, and it is a **regime input, not an entry
   signal**.
2. **Kronos-base (102.3M)** — tests capacity as the binding constraint. Low prior:
   the fine-tuned 24.7M model already overfits by epoch 2 on 374k bars, so capacity
   is not obviously the limit; data is.
3. Longer fine-tuning — **actively contraindicated** by the epoch-2 val turn.

None is queued. (1) is the only one worth a future task, and it belongs to the
regime-detection lane, not the alpha lane.

**Standing state is unchanged.** The two validated lanes remain **spot Victoria +
funding-carry** (V255.C/D basis-hedged carry being the one confirmed alpha), and
**live-paper (V253) remains the only lane accruing new independent evidence**
toward the recent-N ≥ 20 resume gate. All V241–V264 flags stay OFF. No strategy
code was touched in this version.

---

## 6. Operational notes

- **Live-paper daemon untouched.** The brief named PID 11165; the launchd job
  `com.omega.live_paper` is currently PID **10329** — launchd restarted it at some
  point independently of this work. No V264 process interacted with it.
- **OOM incident (resolved, worth recording).** The first F4 run was SIGKILLed
  mid-cell with no traceback. Cause: `--batch 24 × sample_count 8` = 192 concurrent
  424-token sequences, on a host whose swap was already exhausted — *by this
  session's own polling `grep` calls*, each of which spawned a repo-wide `ugrep`
  that ballooned to **5.2 GB RSS at 96% CPU within 44 s**. Throughput degraded
  5.4 → 10.8 s/window before the kill. Fix: `--batch 8` (stable at 1.0–1.8 s/window)
  plus a `--resume` path so completed cells are not recomputed. **Lesson for future
  long MPS runs on this host: poll logs with `tail`, never `grep`.**
- Determinism: per-batch seeds are a deterministic function of the window index;
  identical arguments reproduce forecasts.

## 7. Files

| Artifact | Path |
|---|---|
| Data prep + leakage assertions | `scripts/v264_kronos_prep.py` |
| Fine-tune driver (MPS, multi-symbol) | `scripts/v264_kronos_finetune.py` |
| F4-ft gate (both arms, resumable) | `scripts/v264_kronos_f4.py` |
| Paired bootstrap CIs | `scripts/v264_kronos_bootstrap.py` |
| Prepped pickles + manifest | `$AUDIT/v264/kronos_finetune/` |
| Fine-tuned checkpoints + loss curves | `$AUDIT/v264/checkpoints/{tokenizer,predictor}/` |
| F4-ft per-window artifacts + summaries | `$AUDIT/v264/f4/{zeroshot_holdout,finetuned}/` |
| Bootstrap result | `$AUDIT/v264/f4/bootstrap.json` |
| Training logs | `$AUDIT/v264/logs/` |

`$AUDIT` = `/Volumes/gamma-systems-2/omega-victoria-data`. Checkpoints and data are
on gamma, never in the repo.
