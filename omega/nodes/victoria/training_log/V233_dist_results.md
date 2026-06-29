# V233 application-SITE eval — determinism gate: **PASS**

_12 cells aggregated. Baseline (post_demean_w0.2 = V227 skew standing-main) from `/Volumes/gamma-systems-2/omega-victoria-data/v232_dist/distribution.json`._

_Each config tests the V227 skew PROBE under a different application site/weight. Δ = config PnL − baseline PnL per window. Falsifier branch-1: binding window (snap_crisis_2024aug) Δ>0 (loss-reducing) AND no non-binding window regressed (min Δ≥0)._

## crisis

| config | 2024aug Δ (binding) | nonbinding min Δ | mean Δ | site-fix wins? |
|---|---:|---:|---:|:--:|
| pre_demean_common_mode_w0.2 | $6.31 | $-182.34 | $212.35 | — |
| pre_demean_w0.2 | $0.00 | $-4,461.38 | $-1,355.29 | — |
| pre_demean_w0.4 | $0.00 | $-4,485.00 | $-1,363.16 | — |
| pre_demean_w0.6 | $0.00 | $-4,852.27 | $-1,483.16 | — |

### pre_demean_common_mode_w0.2 — per-window detail

| window | config PnL | baseline PnL | Δ |
|---|---:|---:|---:|
| snap_crisis_2020q1 | $15,320.67 | $15,503.01 | $-182.34 |
| snap_crisis_2022h1 | $-2,178.08 | $-2,991.17 | $813.09 |
| snap_crisis_2024aug | $-9,501.57 | $-9,507.88 | $6.31 |

### pre_demean_w0.2 — per-window detail

| window | config PnL | baseline PnL | Δ |
|---|---:|---:|---:|
| snap_crisis_2020q1 | $15,898.53 | $15,503.01 | $395.52 |
| snap_crisis_2022h1 | $-7,452.55 | $-2,991.17 | $-4,461.38 |
| snap_crisis_2024aug | $-9,507.88 | $-9,507.88 | $0.00 |

### pre_demean_w0.4 — per-window detail

| window | config PnL | baseline PnL | Δ |
|---|---:|---:|---:|
| snap_crisis_2020q1 | $15,898.53 | $15,503.01 | $395.52 |
| snap_crisis_2022h1 | $-7,476.17 | $-2,991.17 | $-4,485.00 |
| snap_crisis_2024aug | $-9,507.88 | $-9,507.88 | $0.00 |

### pre_demean_w0.6 — per-window detail

| window | config PnL | baseline PnL | Δ |
|---|---:|---:|---:|
| snap_crisis_2020q1 | $15,905.79 | $15,503.01 | $402.78 |
| snap_crisis_2022h1 | $-7,843.44 | $-2,991.17 | $-4,852.27 |
| snap_crisis_2024aug | $-9,507.88 | $-9,507.88 | $0.00 |
