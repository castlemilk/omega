# V283 Phase 1 — TimesFM measured on V265's locked volatility gates

**Date:** 2026-08-27
**Author:** claude
**Status:** PHASE 1 / FINDINGS — read-only. No strategy module imported, no flag added, no version pre-registered.
**Parent:** [`V282_PHASE0_TIMESFM.md`](V282_PHASE0_TIMESFM.md) · gates from [`V265.md`](V265.md)
**Standing baseline:** crisis +$599 / trend +$2,997 / recent +$30 — untouched

---

## §0 — Installed, contrary to the Phase 0 assessment

V282 Phase 0 concluded TimesFM "cannot be installed on this machine right now" —
`torch`/`jax` absent and every large install failing. **That is now false**: `torch 2.13.0`
(MPS available), `timesfm` (exposing `TimesFM_2p5_200M_torch`), and 883 MB of weights all
installed on retry. The Phase 0 blocker was transient network, not a real constraint, and
is withdrawn.

`scipy`, installed in the same pass, resolved a four-version mystery — see `V282.md`.

## §1 — Instrument

Deliberately **V265's gates, not new ones**, so the result is directly comparable to
Kronos's `CAVEATED 2/3`:

| Gate | Bar |
|---|---|
| **F5-corr** | pooled Spearman ρ(model spread, realized vol) **> +0.20** |
| **F5-vol** | pooled RMSE(model)/RMSE(naive) **< 0.90** |

Corpus: `data/frozen_series/binance_intraday/{SYM}/1h` — the same frozen V262 shards,
tracked in git, spanning **2020-01 → 2026-07**. Context 512 bars, horizon 24, stride 48.
Realized vol is V265's estimator (RMS per-bar log return). Naive baseline is a 72-bar
rolling std. Each predictor is rescaled onto realized units by an in-sample global
scalar, per V265's stated method ("separates *no information* from *wrong units*").

**Estimator deviation, stated:** V265 used Kronos's *cross-sample path* spread. TimesFM
exposes a quantile head instead, so the analogue used here is the mean **q90 − q10** band
over the horizon, normalised by the last close and by √H. Analogous in spirit, **not
byte-identical** — a like-for-like RMSE comparison against V265's Kronos numbers is
therefore not claimed.

## §2 — Result: both gates PASS pooled

800 windows, 4 symbols:

| Gate | Bar | TimesFM | naive (ref) | Verdict |
|---|---|---:|---:|---|
| F5-corr | > +0.20 | **+0.7883** (p=1.7e-170) | +0.7467 | **PASS** |
| F5-vol | < 0.90 | **0.8379** | — | **PASS** |

### It subsumes the naive predictor

The interesting number is not ρ — vol clustering makes *any* predictor look good — but
what survives conditioning:

| | |
|---|---:|
| partial ρ(TimesFM, realized \| naive) | **+0.3876** |
| partial ρ(naive, realized \| TimesFM) | **+0.0829** |
| OOS RMSE ratio (temporal 50/50, scalar fit in-sample) | **0.8632** |
| fitted weight on naive, given TimesFM | **−0.2214** |

Naive retains almost nothing once TimesFM is controlled for, and takes a **negative**
weight in the combined fit. The advantage survives an out-of-sample temporal split.

## §3 — The memorisation probe (Phase 0's blocker, tested)

Phase 0's live concern was corpus memorisation: TimesFM's pretraining set and cutoff are
undocumented, so a strong result on 2020–21 crypto could be recall rather than skill.
That is not directly auditable, but its **observable consequence** is: memorisation should
decay sharply outside any plausible pretraining window.

| Era | n | ρ TimesFM | ρ naive | RMSE ratio | partial(fm \| naive) |
|---|---:|---:|---:|---:|---:|
| EARLY 2020–2021 | 1062 | +0.7015 | +0.6539 | 0.8583 | **+0.3581** |
| LATE 2025–2026 | 822 | +0.6702 | +0.6177 | 0.9093 | **+0.3417** |

**No memorisation signature.** Both predictors degrade slightly in the later era and they
degrade *together*; the conditional advantage is essentially unchanged (+0.358 → +0.342).
Recall of specific 2020 series would not generalise to 2026 bars this evenly.

**Reported against the model, not for it:** on the LATE era the RMSE ratio is **0.9093 —
a marginal FAIL of the <0.90 bar**. F5-vol passes pooled and on EARLY, and fails on the
most recent data. Anyone citing this result must cite that too.

This weakens the memorisation hypothesis; it does not *prove* the corpus is clean. Only
the corpus contents could, and they remain undocumented.

## §4 — What this does and does not establish

**Does:** TimesFM's quantile spread is a materially better volatility forecaster than the
naive baseline on this corpus, the advantage is conditional-on-naive rather than
redundant with it, it survives a temporal split, and it shows no era-decay signature.
That is a **better result than Kronos achieved** (V263 R1 no-effect, V264 R2
below-resolution, V265 CAVEATED 2/3).

**Does NOT:** establish one dollar of PnL. V265's Kronos also cleared two of three gates
and led nowhere, because *forecast quality is not the objective function*. Nothing here
has touched the strategy, and the V235 rule stands — a claim needs the walk-forward
distribution, not a forecasting scorer.

Also outstanding: only 3–4 symbols; overlapping windows within each era; and the
estimator deviation in §1.

## §5 — Recommendation

**Run V282 Phase 0 §4's oracle probe next — it is now the binding question.**

Substitute *realised* forward volatility (a perfect, unattainable forecast) into the
sizing path and measure the walk-forward Δ:

- **Oracle Δ inside the MDE** ⇒ no volatility forecaster can help, TimesFM included. The
  lane closes for **$0**, and the §2/§3 result becomes a good forecaster with nothing to
  do — which is exactly what V265's 2/3 turned out to be.
- **Oracle Δ material** ⇒ the lane is real and TimesFM has a measured, non-memorised
  share of that headroom. *Then* pre-register an integration.

Running it first costs nothing and can close the lane outright. Integrating first risks
repeating V265: a passing scorer, an unmeasured objective, and a caveated verdict nobody
can act on.

**Still do NOT put TimesFM in the entry composite** — V263's refuted role (ρ = −0.027),
compounded by V280's measured dilution.
