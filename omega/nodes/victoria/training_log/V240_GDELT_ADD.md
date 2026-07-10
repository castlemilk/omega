# V240 Track C — gdelt frozen source (6th series signal): SHIPPED

**Date:** 2026-07-11 · **Author:** claude (Fable 5)

The 6th info-class signal (`gdelt`, V138 GeopoliticalSignal) was `ABSENT`
under frozen replay since V238 (no frozen source; the live DOC-API path is
inert under the V215 guards). This track builds the frozen source and wires
consumption.

## What shipped

- **`scripts/v240_freeze_gdelt.py`** — freeze-once builder. One GDELT DOC 2.0
  API call per (query, mode): 5 V138 queries × {timelinevol, timelinetone} =
  10 series, `data/frozen_series/gdelt_{vol,tone}_<query>.json` in the V238
  schema, md5 + provenance in `MANIFEST.json`. Resumable (skips existing
  files) — needed in practice: the API 429-throttles well above its nominal
  1-req/5s (fetches required 30s spacing + 60–300s backoff).
- **Coverage:** 2,391 daily obs per series, **2019-12-01 → 2026-07-10** —
  covers every `walk_forward_manifest` window (2020→2026) incl. the 31-bar
  warmup. GDELT DOC 2.0 serves 2017+, so deeper history is available if the
  manifest ever extends back.
- **`GeopoliticalSignal.compute_from_series(vol_windows, tone_windows)`** —
  frozen analog of the live count-based semantics on coverage fractions:
  intensity (today/trailing-7d mean, clamp [0,3]), volume-weighted mean tone
  (clamp ±10), regime shift (>2σ above trailing, **degenerate-variance fenced
  per V221**: max==min ⇒ 0.0), sanctions ratio (EMA, clamp [0,1]).
  `math.fsum`-fenced aggregations (V220/V221).
- **Wiring** (`signal_generation.py`): replaces the V238 warn-only block.
  Gated on `_sp_active("gdelt")` (the V240.B `frozen_series_signals`
  allowlist) + `geopolitical_signals` (constructs the object). Missing or
  out-of-range series ⇒ honestly ABSENT for the cycle — never live fetch,
  never silent 0.0. **V213-class alias fix:** the three bare `geo_*` keys
  inject as `geo_*_signal` so they are composite-visible (previously only
  `sanctions_signal` was, live or frozen).

## Smoke (all PASS)

| bar | intensity | sentiment | regime_shift | sanctions |
|---|---:|---:|---:|---:|
| 2020-03-15 (COVID crash) | 3.00 | −1.68 | 1.0 | 0.00 |
| 2022-02-25 (Ukraine invasion) | 3.00 | −3.93 | 1.0 | 0.30 |
| 2024-08-05 (crypto unwind, not geo) | 0.52 | −4.54 | 0.0 | 0.21 |
| 2026-06-01 | 3.00 | −1.88 | 1.0 | 0.45 |

Face-valid: the two genuine geopolitical shocks max intensity + trip regime
shift; the crypto-endogenous Aug-2024 unwind does not. Pre-coverage bar
raises `SeriesOutOfRange`; repeat computation deterministic.

## Not measured here

No PnL claim. gdelt joins the per-signal forensics frame: a future solo cell
(`frozen_series_signals="gdelt"` + `geopolitical_signals` on) measures its
walk-forward delta the same way as the 5 V238 feeds (Track B grid). Queued
for V241+ alongside the Track B verdicts.
