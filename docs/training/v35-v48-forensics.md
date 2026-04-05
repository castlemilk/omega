# V35 → V48 Forensics Report

**Generated:** 2026-04-05T15:22:32.671919+00:00

## Summary

| Metric | V35 | V48 | Delta |
|---|---|---|---|
| Total PnL (USD) | 159.24 | 31.97 | -127.27 |
| Trades | 249 | 103 | -146 |
| Win rate | 24.50% | 31.07% | +6.57% |
| Profit factor | 1.36 | 1.34 | -0.02 |
| Zero-trade cycles | 290 | 115 | -175 |

## Conviction Histogram

| Band | V35 | V48 |
|---|---|---|
| HOLD (< 0.20) | 100% | 100% |
| Trade (>= 0.20) | 0% | 0% |
| Mean conviction | 0.084 | 0.065 |

## Top-3 Hypotheses

### 1. (confidence 0.90)

247 baseline trades were skipped by V48, representing $159.25 of the $127.27 PnL gap (100% coverage). Most were profitable baseline entries below V48's current threshold.

**Evidence:** skipped_trades, baselines

### 2. (confidence 0.59)

Per-symbol PnL loss is concentrated in ADAUSDT: $-93.48 delta (73% of the total gap). Targeted signal re-weighting for this symbol is a cheap first fix.

**Evidence:** signal_contribution_delta_proxy

### 3. (confidence 0.53)

Conviction magnitudes collapsed: V48 mean conviction (0.065) is 0.77x V35 (0.084). The HOLD band is now 100% of trades vs 100% in V35, consistent with post-demean thresholds not tracking signal magnitude.

**Evidence:** conviction_histogram, observability.conviction_filter_rate

## Skipped Trades

| Cycle | Symbol | Side | Baseline PnL | Conviction | Regime |
|---|---|---|---|---|---|
| 6 | MATICUSDT | short | -0.00 | 0.100 | normal |
| 6 | ADAUSDT | short | +11.91 | 0.100 | normal |
| 7 | DOTUSDT | short | +15.48 | 0.100 | normal |
| 10 | MATICUSDT | short | -0.00 | 0.100 | normal |
| 11 | ADAUSDT | short | +7.95 | 0.100 | normal |
| 12 | DOTUSDT | short | -7.75 | 0.100 | crisis |
| 15 | ADAUSDT | short | +3.98 | 0.100 | crisis |
| 16 | DOTUSDT | short | -0.00 | 0.100 | crisis |
| 17 | MATICUSDT | short | -0.00 | 0.100 | normal |
| 18 | ADAUSDT | short | +3.32 | 0.083 | normal |
| 22 | MATICUSDT | short | -0.00 | 0.083 | high_vol |
| 24 | DOTUSDT | short | -6.46 | 0.083 | high_vol |
| 25 | ADAUSDT | short | -9.96 | 0.083 | high_vol |
| 30 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 32 | DOTUSDT | short | +6.45 | 0.083 | normal |
| 32 | ADAUSDT | short | +6.63 | 0.083 | normal |
| 37 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 40 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 41 | ADAUSDT | short | +3.32 | 0.083 | crisis |
| 44 | DOTUSDT | short | -6.46 | 0.083 | crisis |
| 46 | ADAUSDT | short | +9.95 | 0.083 | crisis |
| 48 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 50 | DOTUSDT | short | +6.45 | 0.083 | crisis |
| 52 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 56 | ADAUSDT | short | -3.32 | 0.083 | crisis |
| 57 | DOTUSDT | short | -6.46 | 0.083 | normal |
| 58 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 61 | ADAUSDT | short | +3.32 | 0.083 | crisis |
| 64 | DOTUSDT | short | +6.45 | 0.083 | crisis |
| 66 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 67 | ADAUSDT | short | -6.64 | 0.083 | crisis |
| 71 | ADAUSDT | short | +16.59 | 0.083 | crisis |
| 73 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 74 | DOTUSDT | short | +6.47 | 0.083 | crisis |
| 76 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 78 | ADAUSDT | short | -6.65 | 0.083 | crisis |
| 80 | DOTUSDT | short | +6.47 | 0.083 | normal |
| 82 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 84 | DOTUSDT | short | -0.00 | 0.083 | high_vol |
| 84 | ADAUSDT | short | -0.00 | 0.083 | high_vol |
| 89 | ADAUSDT | short | -0.00 | 0.083 | normal |
| 90 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 93 | ADAUSDT | short | +6.65 | 0.083 | normal |
| 95 | DOTUSDT | short | -12.96 | 0.083 | normal |
| 95 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 96 | ADAUSDT | short | -3.33 | 0.083 | normal |
| 100 | ADAUSDT | short | +9.98 | 0.083 | normal |
| 102 | DOTUSDT | short | -12.94 | 0.083 | normal |
| 102 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 105 | ADAUSDT | short | +6.66 | 0.083 | normal |
| 106 | DOTUSDT | short | +6.46 | 0.083 | normal |
| 107 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 108 | ADAUSDT | short | -0.00 | 0.083 | normal |
| 112 | ADAUSDT | short | +6.67 | 0.083 | crisis |
| 113 | DOTUSDT | short | +19.39 | 0.083 | crisis |
| 114 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 117 | DOTUSDT | short | -0.00 | 0.083 | crisis |
| 118 | ADAUSDT | short | -0.00 | 0.083 | crisis |
| 123 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 123 | ADAUSDT | short | +3.34 | 0.083 | normal |
| 126 | DOTUSDT | short | -19.44 | 0.083 | normal |
| 127 | ADAUSDT | short | +16.69 | 0.083 | normal |
| 130 | MATICUSDT | short | -0.00 | 0.083 | high_vol |
| 131 | DOTUSDT | short | -19.39 | 0.083 | high_vol |
| 133 | ADAUSDT | short | -6.69 | 0.083 | high_vol |
| 135 | DOTUSDT | short | -0.00 | 0.083 | high_vol |
| 138 | ADAUSDT | short | -6.68 | 0.083 | normal |
| 140 | DOTUSDT | short | +6.45 | 0.083 | normal |
| 142 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 145 | DOTUSDT | short | +12.91 | 0.083 | normal |
| 146 | ADAUSDT | short | +6.69 | 0.083 | normal |
| 147 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 151 | ADAUSDT | short | +10.04 | 0.083 | normal |
| 152 | DOTUSDT | short | -0.00 | 0.083 | normal |
| 153 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 156 | ADAUSDT | short | -3.35 | 0.083 | normal |
| 157 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 160 | DOTUSDT | short | +12.93 | 0.083 | normal |
| 162 | ADAUSDT | short | +16.75 | 0.083 | normal |
| 164 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 164 | DOTUSDT | short | +19.43 | 0.083 | normal |
| 168 | ADAUSDT | short | +13.42 | 0.083 | normal |
| 168 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 170 | DOTUSDT | short | -0.00 | 0.083 | normal |
| 173 | ADAUSDT | short | -0.00 | 0.083 | high_vol |
| 176 | MATICUSDT | short | -0.00 | 0.083 | high_vol |
| 176 | DOTUSDT | short | -19.47 | 0.083 | high_vol |
| 179 | ADAUSDT | short | -0.00 | 0.083 | high_vol |
| 182 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 182 | ADAUSDT | short | -0.00 | 0.083 | normal |
| 183 | DOTUSDT | short | +6.47 | 0.083 | normal |
| 189 | DOTUSDT | short | +32.40 | 0.083 | normal |
| 189 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 190 | ADAUSDT | short | +20.16 | 0.083 | normal |
| 193 | DOTUSDT | short | -0.00 | 0.083 | normal |
| 194 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 196 | ADAUSDT | short | -10.11 | 0.083 | normal |
| 200 | DOTUSDT | short | -6.51 | 0.083 | normal |
| 200 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 200 | ADAUSDT | short | -3.36 | 0.083 | normal |
| 205 | DOTUSDT | short | +6.50 | 0.083 | normal |
| 205 | ADAUSDT | short | +6.73 | 0.083 | normal |
| 208 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 208 | DOTUSDT | short | -13.01 | 0.083 | normal |
| 210 | ADAUSDT | short | -3.37 | 0.083 | normal |
| 212 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 214 | DOTUSDT | short | -0.00 | 0.083 | normal |
| 215 | ADAUSDT | short | -0.00 | 0.083 | normal |
| 218 | ADAUSDT | short | -10.09 | 0.083 | crisis |
| 219 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 222 | DOTUSDT | short | -0.00 | 0.083 | crisis |
| 222 | ADAUSDT | short | -0.00 | 0.083 | crisis |
| 225 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 228 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 229 | DOTUSDT | short | -6.49 | 0.083 | normal |
| 230 | ADAUSDT | short | -10.08 | 0.083 | normal |
| 233 | DOTUSDT | short | +6.49 | 0.083 | normal |
| 234 | ADAUSDT | short | +3.36 | 0.083 | normal |
| 235 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 239 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 240 | DOTUSDT | short | -0.00 | 0.083 | crisis |
| 241 | ADAUSDT | short | -0.00 | 0.083 | crisis |
| 252 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 252 | ADAUSDT | short | -6.72 | 0.083 | normal |
| 253 | DOTUSDT | short | -0.00 | 0.083 | normal |
| 256 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 256 | ADAUSDT | short | -3.36 | 0.083 | normal |
| 260 | DOTUSDT | short | -0.00 | 0.083 | crisis |
| 260 | ADAUSDT | short | -0.00 | 0.083 | crisis |
| 263 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 264 | DOTUSDT | short | -0.00 | 0.083 | crisis |
| 266 | ADAUSDT | short | -3.36 | 0.083 | crisis |
| 271 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 272 | DOTUSDT | short | -13.01 | 0.083 | normal |
| 276 | ADAUSDT | short | +3.36 | 0.083 | normal |
| 277 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 278 | DOTUSDT | short | +6.50 | 0.083 | normal |
| 283 | ADAUSDT | short | -6.71 | 0.083 | normal |
| 284 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 284 | DOTUSDT | short | -6.50 | 0.083 | normal |
| 287 | ADAUSDT | short | -3.35 | 0.083 | crisis |
| 288 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 290 | ADAUSDT | short | -0.00 | 0.083 | crisis |
| 291 | DOTUSDT | short | -12.99 | 0.083 | crisis |
| 294 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 296 | ADAUSDT | short | +10.05 | 0.083 | crisis |
| 298 | DOTUSDT | short | -0.00 | 0.083 | normal |
| 298 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 302 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 303 | ADAUSDT | short | +10.06 | 0.083 | crisis |
| 305 | DOTUSDT | short | +12.97 | 0.083 | crisis |
| 307 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 307 | ADAUSDT | short | -6.71 | 0.083 | crisis |
| 310 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 310 | ADAUSDT | short | -0.00 | 0.083 | crisis |
| 312 | DOTUSDT | short | -12.99 | 0.083 | crisis |
| 314 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 314 | ADAUSDT | short | -0.00 | 0.083 | crisis |
| 318 | ADAUSDT | short | -0.00 | 0.083 | normal |
| 320 | DOTUSDT | short | +12.97 | 0.083 | normal |
| 322 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 324 | DOTUSDT | short | -0.00 | 0.083 | high_vol |
| 325 | ADAUSDT | short | -0.00 | 0.083 | high_vol |
| 328 | ADAUSDT | short | -0.00 | 0.083 | high_vol |
| 330 | MATICUSDT | short | -0.00 | 0.083 | high_vol |
| 331 | DOTUSDT | short | -0.00 | 0.083 | high_vol |
| 340 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 341 | DOTUSDT | short | +6.50 | 0.083 | normal |
| 344 | ADAUSDT | short | +3.36 | 0.083 | normal |
| 344 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 348 | DOTUSDT | short | +19.50 | 0.083 | normal |
| 350 | ADAUSDT | short | +10.11 | 0.083 | normal |
| 352 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 352 | DOTUSDT | short | +19.55 | 0.083 | normal |
| 356 | ADAUSDT | short | -10.12 | 0.083 | normal |
| 356 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 357 | DOTUSDT | short | -13.06 | 0.083 | normal |
| 360 | DOTUSDT | short | -6.52 | 0.083 | normal |
| 362 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 364 | ADAUSDT | short | +6.74 | 0.083 | normal |
| 366 | DOTUSDT | short | -0.00 | 0.083 | normal |
| 367 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 369 | ADAUSDT | short | -0.00 | 0.083 | crisis |
| 373 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 374 | DOTUSDT | short | -6.52 | 0.083 | crisis |
| 377 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 378 | ADAUSDT | short | -0.00 | 0.083 | crisis |
| 378 | DOTUSDT | short | -0.00 | 0.083 | crisis |
| 382 | DOTUSDT | short | +6.51 | 0.083 | normal |
| 383 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 383 | ADAUSDT | short | -0.00 | 0.083 | normal |
| 386 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 388 | DOTUSDT | short | -6.52 | 0.083 | normal |
| 389 | ADAUSDT | short | -13.51 | 0.083 | crisis |
| 391 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 392 | DOTUSDT | short | -0.00 | 0.083 | crisis |
| 394 | ADAUSDT | short | +6.74 | 0.083 | crisis |
| 394 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 401 | ADAUSDT | short | +16.87 | 0.083 | crisis |
| 403 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 404 | DOTUSDT | short | +26.04 | 0.083 | crisis |
| 404 | ADAUSDT | short | -13.52 | 0.083 | crisis |
| 409 | DOTUSDT | short | -0.00 | 0.083 | crisis |
| 409 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 410 | ADAUSDT | short | -3.38 | 0.083 | crisis |
| 414 | DOTUSDT | short | +6.53 | 0.083 | normal |
| 414 | ADAUSDT | short | +10.12 | 0.083 | normal |
| 418 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 419 | DOTUSDT | short | -0.00 | 0.083 | normal |
| 422 | ADAUSDT | short | -6.76 | 0.083 | normal |
| 423 | DOTUSDT | short | -0.00 | 0.083 | normal |
| 424 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 428 | DOTUSDT | short | +6.54 | 0.083 | normal |
| 428 | ADAUSDT | short | -13.50 | 0.083 | normal |
| 429 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 432 | DOTUSDT | short | -0.00 | 0.083 | normal |
| 433 | MATICUSDT | short | -0.00 | 0.083 | high_vol |
| 436 | ADAUSDT | short | -6.74 | 0.083 | high_vol |
| 439 | MATICUSDT | short | -0.00 | 0.083 | high_vol |
| 440 | DOTUSDT | short | -0.00 | 0.083 | high_vol |
| 441 | ADAUSDT | short | -0.00 | 0.083 | normal |
| 444 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 444 | ADAUSDT | short | -3.37 | 0.083 | normal |
| 448 | DOTUSDT | short | -6.54 | 0.083 | normal |
| 448 | ADAUSDT | short | -3.36 | 0.083 | normal |
| 452 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 456 | DOTUSDT | short | +13.06 | 0.083 | normal |
| 456 | ADAUSDT | short | +13.45 | 0.083 | normal |
| 460 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 462 | ADAUSDT | short | -3.37 | 0.083 | crisis |
| 464 | DOTUSDT | short | -6.54 | 0.083 | crisis |
| 465 | MATICUSDT | short | -0.00 | 0.083 | crisis |
| 468 | DOTUSDT | short | -13.07 | 0.083 | crisis |
| 470 | ADAUSDT | short | -0.00 | 0.083 | crisis |
| 472 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 474 | DOTUSDT | short | -0.00 | 0.083 | normal |
| 474 | ADAUSDT | short | -6.74 | 0.083 | normal |
| 478 | MATICUSDT | short | -0.00 | 0.083 | high_vol |
| 479 | ADAUSDT | short | +3.37 | 0.083 | high_vol |
| 480 | DOTUSDT | short | -0.00 | 0.083 | high_vol |
| 488 | ADAUSDT | short | +3.37 | 0.083 | normal |
| 489 | DOTUSDT | short | -6.52 | 0.083 | normal |
| 490 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 492 | ADAUSDT | short | -0.00 | 0.083 | normal |
| 495 | DOTUSDT | short | -0.00 | 0.083 | normal |
| 496 | MATICUSDT | short | -0.00 | 0.083 | normal |
| 496 | ADAUSDT | short | -0.00 | 0.083 | normal |

## Regime Breakdown

| Regime | V35 PnL | V48 PnL | Delta |
|---|---|---|---|
| crisis | +25.11 | -1.58 | -26.69 |
| high_vol | -65.34 | +17.06 | +82.40 |
| normal | +199.48 | +16.49 | -182.99 |
