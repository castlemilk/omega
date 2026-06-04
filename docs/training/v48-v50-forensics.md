# V35 → V48 Forensics Report

**Generated:** 2026-04-06T06:37:51.922364+00:00

## Summary

| Metric | V35 | V48 | Delta |
|---|---|---|---|
| Total PnL (USD) | 31.97 | -97.02 | -128.99 |
| Trades | 103 | 115 | +12 |
| Win rate | 31.07% | 20.00% | -11.07% |
| Profit factor | 1.34 | 0.65 | -0.69 |
| Zero-trade cycles | 115 | 112 | -3 |

## Conviction Histogram

| Band | V35 | V48 |
|---|---|---|
| HOLD (< 0.20) | 100% | 100% |
| Trade (>= 0.20) | 0% | 0% |
| Mean conviction | 0.065 | 0.064 |

## Top-3 Hypotheses

### 1. (confidence 0.41)

Per-symbol PnL loss is concentrated in AVAXUSDT: $-56.85 delta (44% of the total gap). Targeted signal re-weighting for this symbol is a cheap first fix.

**Evidence:** signal_contribution_delta_proxy

### 2. (confidence 0.34)

93 baseline trades were skipped by V48, representing $25.25 of the $128.99 PnL gap (20% coverage). Most were profitable baseline entries below V48's current threshold.

**Evidence:** skipped_trades, baselines

### 3. (confidence 0.31)

Conviction magnitudes collapsed: V48 mean conviction (0.064) is 0.99x V35 (0.065). The HOLD band is now 100% of trades vs 100% in V35, consistent with post-demean thresholds not tracking signal magnitude.

**Evidence:** conviction_histogram, observability.conviction_filter_rate

## Skipped Trades

| Cycle | Symbol | Side | Baseline PnL | Conviction | Regime |
|---|---|---|---|---|---|
| 4 | ETHUSDT | long | +0.00 | 0.069 | normal |
| 5 | LINKUSDT | long | +7.99 | 0.069 | normal |
| 9 | ETHUSDT | long | +0.00 | 0.069 | normal |
| 10 | LINKUSDT | long | -15.97 | 0.069 | crisis |
| 12 | ETHUSDT | long | -2.56 | 0.069 | crisis |
| 16 | LINKUSDT | long | +0.00 | 0.067 | crisis |
| 17 | ETHUSDT | long | -6.58 | 0.100 | normal |
| 18 | DOTUSDT | short | -0.00 | 0.067 | normal |
| 18 | MATICUSDT | short | -0.00 | 0.067 | normal |
| 20 | ETHUSDT | long | +3.13 | 0.083 | normal |
| 20 | LINKUSDT | long | +6.42 | 0.056 | normal |
| 26 | ETHUSDT | long | -0.11 | 0.058 | crisis |
| 29 | MATICUSDT | short | -0.00 | 0.055 | crisis |
| 30 | DOTUSDT | short | +8.80 | 0.055 | crisis |
| 32 | ETHUSDT | long | +0.36 | 0.083 | crisis |
| 34 | LINKUSDT | long | +0.00 | 0.055 | crisis |
| 36 | MATICUSDT | short | -0.00 | 0.056 | crisis |
| 37 | DOTUSDT | short | +4.48 | 0.056 | normal |
| 37 | ETHUSDT | long | -0.77 | 0.083 | normal |
| 38 | LINKUSDT | long | +0.00 | 0.060 | normal |
| 43 | ETHUSDT | long | -0.06 | 0.057 | normal |
| 44 | LINKUSDT | long | -6.60 | 0.057 | normal |
| 46 | ETHUSDT | long | +1.19 | 0.057 | normal |
| 50 | ETHUSDT | long | +0.28 | 0.057 | normal |
| 50 | LINKUSDT | long | -6.63 | 0.057 | normal |
| 55 | LINKUSDT | long | +6.69 | 0.058 | high_vol |
| 57 | ETHUSDT | long | +1.64 | 0.058 | high_vol |
| 61 | ETHUSDT | long | +0.04 | 0.082 | high_vol |
| 61 | LINKUSDT | long | -9.45 | 0.082 | high_vol |
| 62 | DOTUSDT | short | -0.00 | 0.054 | high_vol |
| 65 | MATICUSDT | short | -0.00 | 0.054 | high_vol |
| 65 | LINKUSDT | long | +9.54 | 0.083 | high_vol |
| 66 | ETHUSDT | long | +2.57 | 0.083 | high_vol |
| 68 | LINKUSDT | long | +0.00 | 0.058 | high_vol |
| 72 | DOTUSDT | short | -0.00 | 0.053 | normal |
| 72 | ETHUSDT | long | -0.65 | 0.083 | normal |
| 76 | LINKUSDT | long | +9.58 | 0.083 | normal |
| 78 | MATICUSDT | short | -0.00 | 0.052 | normal |
| 79 | ETHUSDT | long | +1.05 | 0.083 | normal |
| 81 | DOTUSDT | short | -0.00 | 0.052 | high_vol |
| 82 | ETHUSDT | long | -2.27 | 0.083 | high_vol |
| 83 | LINKUSDT | long | -6.69 | 0.058 | high_vol |
| 87 | MATICUSDT | short | -0.00 | 0.052 | normal |
| 88 | DOTUSDT | short | -0.00 | 0.052 | normal |
| 90 | ETHUSDT | long | +2.46 | 0.087 | normal |
| 95 | LINKUSDT | long | +0.00 | 0.060 | crisis |
| 96 | ETHUSDT | long | +0.15 | 0.060 | crisis |
| 97 | MATICUSDT | short | -0.00 | 0.052 | crisis |
| 98 | DOTUSDT | short | +4.19 | 0.052 | crisis |
| 101 | LINKUSDT | long | +0.00 | 0.058 | crisis |
| 102 | ETHUSDT | long | +1.89 | 0.083 | crisis |
| 104 | DOTUSDT | short | -0.00 | 0.053 | crisis |
| 105 | LINKUSDT | long | +0.00 | 0.057 | crisis |
| 106 | ETHUSDT | long | +2.25 | 0.086 | normal |
| 109 | LINKUSDT | long | +0.00 | 0.057 | normal |
| 110 | ETHUSDT | long | -2.69 | 0.085 | normal |
| 111 | MATICUSDT | short | -0.00 | 0.054 | normal |
| 112 | DOTUSDT | short | +4.31 | 0.054 | normal |
| 113 | LINKUSDT | long | +0.00 | 0.059 | normal |
| 118 | ETHUSDT | long | -1.11 | 0.059 | high_vol |
| 119 | LINKUSDT | long | -6.75 | 0.059 | high_vol |
| 121 | DOTUSDT | short | +4.37 | 0.054 | high_vol |
| 122 | LINKUSDT | long | +6.55 | 0.057 | high_vol |
| 126 | ETHUSDT | long | -0.41 | 0.085 | normal |
| 127 | DOTUSDT | short | +4.35 | 0.054 | normal |
| 127 | MATICUSDT | short | -0.00 | 0.054 | normal |
| 130 | LINKUSDT | long | -6.53 | 0.057 | normal |
| 132 | ETHUSDT | long | +0.31 | 0.059 | normal |
| 134 | LINKUSDT | long | +0.00 | 0.061 | normal |
| 140 | ETHUSDT | long | -0.58 | 0.085 | high_vol |
| 142 | LINKUSDT | long | +6.48 | 0.056 | high_vol |
| 143 | DOTUSDT | short | -0.00 | 0.055 | high_vol |
| 148 | ETHUSDT | long | +0.04 | 0.090 | normal |
| 148 | MATICUSDT | short | -0.00 | 0.055 | normal |
| 149 | DOTUSDT | short | -0.00 | 0.055 | normal |
| 155 | ETHUSDT | long | -0.16 | 0.080 | normal |
| 160 | ETHUSDT | long | +0.00 | 0.058 | normal |
| 162 | LINKUSDT | long | +6.70 | 0.058 | high_vol |
| 168 | ETHUSDT | long | -0.67 | 0.081 | high_vol |
| 170 | LINKUSDT | long | +0.00 | 0.081 | normal |
| 170 | MATICUSDT | short | -0.00 | 0.055 | normal |
| 172 | DOTUSDT | short | -8.81 | 0.055 | normal |
| 173 | ETHUSDT | long | +0.00 | 0.085 | normal |
| 178 | LINKUSDT | long | +0.00 | 0.082 | normal |
| 178 | ETHUSDT | long | -0.32 | 0.082 | normal |
| 178 | MATICUSDT | short | -0.00 | 0.054 | normal |
| 181 | DOTUSDT | short | -0.00 | 0.054 | normal |
| 184 | LINKUSDT | long | +0.00 | 0.082 | normal |
| 185 | ETHUSDT | long | +0.60 | 0.082 | normal |
| 192 | ETHUSDT | long | -0.89 | 0.059 | crisis |
| 192 | LINKUSDT | long | -6.81 | 0.059 | crisis |
| 197 | LINKUSDT | long | +9.38 | 0.081 | crisis |
| 199 | ETHUSDT | long | +1.50 | 0.081 | normal |

## Regime Breakdown

| Regime | V35 PnL | V48 PnL | Delta |
|---|---|---|---|
| crisis | -1.58 | +15.42 | +17.00 |
| high_vol | +17.06 | +14.09 | -2.96 |
| normal | +16.49 | -126.52 | -143.01 |
