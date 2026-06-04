# V35 → V48 Forensics Report

**Generated:** 2026-04-09T12:14:47.268113+00:00

## Summary

| Metric | V35 | V48 | Delta |
|---|---|---|---|
| Total PnL (USD) | 130.91 | -37.86 | -168.77 |
| Trades | 60 | 69 | +9 |
| Win rate | 48.33% | 30.43% | -17.90% |
| Profit factor | 2.40 | 0.82 | -1.58 |
| Zero-trade cycles | 155 | 153 | -2 |

## Conviction Histogram

| Band | V35 | V48 |
|---|---|---|
| HOLD (< 0.20) | 98% | 99% |
| Trade (>= 0.20) | 2% | 1% |
| Mean conviction | 0.084 | 0.086 |

## Top-3 Hypotheses

### 1. (confidence 0.85)

49 baseline trades were skipped by V48, representing $156.45 of the $168.77 PnL gap (93% coverage). Most were profitable baseline entries below V48's current threshold.

**Evidence:** skipped_trades, baselines

### 2. (confidence 0.37)

Per-symbol PnL loss is concentrated in ARBUSDT: $-60.93 delta (36% of the total gap). Targeted signal re-weighting for this symbol is a cheap first fix.

**Evidence:** signal_contribution_delta_proxy

### 3. (confidence 0.30)

Conviction magnitudes collapsed: V48 mean conviction (0.086) is 1.02x V35 (0.084). The HOLD band is now 99% of trades vs 98% in V35, consistent with post-demean thresholds not tracking signal magnitude.

**Evidence:** conviction_histogram, observability.conviction_filter_rate

## Skipped Trades

| Cycle | Symbol | Side | Baseline PnL | Conviction | Regime |
|---|---|---|---|---|---|
| 7 | ETHUSDT | long | -3.16 | 0.058 | normal |
| 15 | ETHUSDT | long | -2.12 | 0.058 | crisis |
| 39 | ETHUSDT | long | -1.16 | 0.054 | normal |
| 41 | NEARUSDT | long | -5.01 | 0.067 | high_vol |
| 43 | ARBUSDT | long | +7.64 | 0.078 | high_vol |
| 43 | ADAUSDT | short | +2.04 | 0.051 | high_vol |
| 45 | ETHUSDT | long | -4.02 | 0.054 | high_vol |
| 60 | ADAUSDT | long | +3.34 | 0.083 | normal |
| 62 | ETHUSDT | long | +1.88 | 0.083 | high_vol |
| 62 | NEARUSDT | long | +0.00 | 0.083 | high_vol |
| 66 | ARBUSDT | long | +8.18 | 0.083 | high_vol |
| 70 | ADAUSDT | short | -0.00 | 0.050 | high_vol |
| 80 | NEARUSDT | long | -6.22 | 0.083 | normal |
| 82 | ARBUSDT | long | -9.65 | 0.098 | normal |
| 82 | ADAUSDT | long | +6.67 | 0.083 | normal |
| 84 | ADAUSDT | short | -0.00 | 0.051 | normal |
| 86 | ADAUSDT | long | +3.33 | 0.083 | normal |
| 90 | NEARUSDT | long | +0.00 | 0.083 | normal |
| 92 | ARBUSDT | long | +7.69 | 0.078 | normal |
| 96 | ADAUSDT | short | +2.01 | 0.050 | normal |
| 98 | ARBUSDT | long | -7.72 | 0.079 | normal |
| 100 | NEARUSDT | long | +12.97 | 0.087 | normal |
| 102 | ETHUSDT | long | +0.12 | 0.054 | crisis |
| 106 | ADAUSDT | long | +3.33 | 0.083 | crisis |
| 108 | ARBUSDT | long | +9.66 | 0.098 | crisis |
| 110 | NEARUSDT | long | +0.00 | 0.087 | crisis |
| 114 | ETHUSDT | long | +1.30 | 0.083 | crisis |
| 118 | ARBUSDT | long | +0.00 | 0.098 | normal |
| 124 | ETHUSDT | long | +1.91 | 0.083 | normal |
| 124 | ARBUSDT | long | -9.63 | 0.098 | normal |
| 128 | NEARUSDT | long | +0.00 | 0.087 | normal |
| 131 | ETHUSDT | long | -0.75 | 0.065 | crisis |
| 134 | ARBUSDT | long | +0.00 | 0.098 | crisis |
| 138 | NEARUSDT | long | +6.50 | 0.087 | crisis |
| 141 | ETHUSDT | long | -2.18 | 0.083 | normal |
| 144 | ADAUSDT | long | +3.33 | 0.083 | normal |
| 144 | NEARUSDT | long | -6.50 | 0.087 | normal |
| 146 | ARBUSDT | long | +9.63 | 0.098 | normal |
| 154 | NEARUSDT | long | +12.44 | 0.083 | high_vol |
| 156 | ARBUSDT | long | +0.00 | 0.098 | crisis |
| 167 | NEARUSDT | long | -6.55 | 0.088 | high_vol |
| 169 | ETHUSDT | long | +4.13 | 0.063 | high_vol |
| 169 | ARBUSDT | long | +19.42 | 0.099 | high_vol |
| 173 | ADAUSDT | short | -0.00 | 0.051 | high_vol |
| 187 | ETHUSDT | long | +4.05 | 0.083 | crisis |
| 187 | ADAUSDT | long | +13.33 | 0.083 | crisis |
| 187 | NEARUSDT | long | +24.82 | 0.083 | crisis |
| 191 | ARBUSDT | long | +38.36 | 0.098 | crisis |
| 199 | NEARUSDT | long | +13.02 | 0.088 | crisis |

## Regime Breakdown

| Regime | V35 PnL | V48 PnL | Delta |
|---|---|---|---|
| crisis | +112.98 | -56.29 | -169.27 |
| high_vol | +40.72 | +42.14 | +1.41 |
| normal | -22.79 | -23.71 | -0.91 |
