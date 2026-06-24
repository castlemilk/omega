# V232 distributional eval — determinism gate: **PASS**

_6 cells aggregated._

_ON = V227 skew + RV-term-structure brake; OFF = V227 skew only. Δ = brake marginal on top of skew. Ship iff mean-Δ>0 AND min-Δ>0._

## crisis  (n_windows=3, Δ ⚠️ not all + (or n/a))

| metric | mean | spread | min | max |
|---|---:|---:|---:|---:|
| PnL OFF | $1,001.32 | $25,010.89 | $-9,507.88 | $15,503.01 |
| PnL ON | $655.50 | $25,010.89 | $-9,507.88 | $15,503.01 |
| Δ (ON−OFF) | $-345.82 | $1,037.46 | $-1,037.46 | $0.00 |

### per-window detail

| window | PnL OFF | PnL ON | Δ |
|---|---:|---:|---:|
| snap_crisis_2020q1 | $15,503.01 | $15,503.01 | $0.00 |
| snap_crisis_2022h1 | $-2,991.17 | $-4,028.63 | $-1,037.46 |
| snap_crisis_2024aug | $-9,507.88 | $-9,507.88 | $0.00 |
