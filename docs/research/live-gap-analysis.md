# Gap analysis — live + snapshot v17x/v18x trades

Total closed trades aggregated: **2805**

- Total PnL: $-56,729
- Win rate: 1009/2805 (36%)
- Profit factor: 0.84
- Average PnL per trade: $-20.22

## By symbol

| Symbol | Trades | PnL | Avg | WR | PF |
|---|---|---|---|---|---|
| NEARUSDT | 324 | $+33,744 | $+104.1 | 34% | 1.85 |
| ARBUSDT | 232 | $+6,945 | $+29.9 | 42% | 1.52 |
| DOTUSDT | 3 | $+35 | $+11.6 | 100% | 34783400000.00 |
| LINKUSDT | 4 | $+26 | $+6.5 | 50% | 26097700000.00 |
| BNBUSDT | 3 | $+4 | $+1.3 | 67% | 2.47 |
| MATICUSDT | 3 | $+0 | $+0.0 | 0% | 0.00 |
| SOLUSDT | 2 | $-9 | $-4.7 | 0% | 0.00 |
| XRPUSDT | 4 | $-11 | $-2.7 | 25% | 0.07 |
| AVAXUSDT | 3 | $-13 | $-4.3 | 33% | 0.50 |
| ADAUSDT | 938 | $-40,959 | $-43.7 | 40% | 0.73 |
| ETHUSDT | 1289 | $-56,490 | $-43.8 | 32% | 0.63 |

## By side

| Side | Trades | PnL | WR | PF |
|---|---|---|---|---|
| short | 1423 | $-144,846 | 33% | 0.44 |
| long | 1382 | $+88,117 | 39% | 1.84 |

## By regime

| Regime | Trades | PnL | WR | PF |
|---|---|---|---|---|
| crisis | 1021 | $+26,432 | 37% | 1.23 |
| high_vol | 227 | $+3,485 | 35% | 1.27 |
| unknown | 29 | $+24 | 41% | 1.34 |
| normal | 1528 | $-86,670 | 35% | 0.63 |

## By hour of day (UTC)

| Hour | Trades | PnL | WR |
|---|---|---|---|
| 00:00 | 5 | $+37 | 60% |
| 01:00 | 273 | $+897 | 36% |
| 02:00 | 47 | $+112 | 38% |
| 03:00 | 97 | $+3,341 | 39% |
| 04:00 | 198 | $-20,976 | 39% |
| 05:00 | 91 | $-1,934 | 27% |
| 06:00 | 293 | $-2,523 | 32% |
| 07:00 | 135 | $-98 | 37% |
| 08:00 | 123 | $+2,166 | 40% |
| 09:00 | 6 | $+757 | 50% |
| 10:00 | 137 | $-102 | 31% |
| 11:00 | 126 | $+248 | 33% |
| 12:00 | 177 | $+2,213 | 40% |
| 13:00 | 525 | $-37,898 | 39% |
| 14:00 | 11 | $+561 | 64% |
| 15:00 | 4 | $+460 | 50% |
| 16:00 | 6 | $+165 | 33% |
| 17:00 | 4 | $-144 | 0% |
| 18:00 | 3 | $+626 | 67% |
| 19:00 | 2 | $+70 | 50% |
| 20:00 | 8 | $+171 | 50% |
| 21:00 | 76 | $+2,478 | 41% |
| 22:00 | 126 | $-88 | 32% |
| 23:00 | 332 | $-7,268 | 32% |

## By hold time (cycles)

| Hold (cycles) | Trades | PnL | Avg | WR |
|---|---|---|---|---|
| 1-2 | 1015 | $-169,681 | $-167.2 | 3% |
| 3-5 | 1057 | $-15,321 | $-14.5 | 35% |
| 6-10 | 732 | $+128,176 | $+175.1 | 83% |
| 10+ | 1 | $+97 | $+96.8 | 100% |

## Loser MFE pattern (catchable with tighter trail)

- Total losers: 1768
- Losers that touched positive MFE before reversing: 773 (44%)
- Their mean MFE: $133.92
- Their mean realized PnL: $-249.18

## Conviction × regime (was conviction inversion real?)

| Bucket | Regime | Trades | PnL | WR |
|---|---|---|---|---|
| high(>=.25) | crisis | 145 | $+15,299 | 24% |
| high(>=.25) | high_vol | 74 | $+6,338 | 35% |
| high(>=.25) | normal | 399 | $-15,985 | 28% |
| low(<.15) | crisis | 799 | $+6,592 | 39% |
| low(<.15) | high_vol | 130 | $-1,791 | 35% |
| low(<.15) | normal | 917 | $-64,637 | 38% |
| low(<.15) | unknown | 29 | $+24 | 41% |
| mid(.15-.25) | crisis | 77 | $+4,541 | 42% |
| mid(.15-.25) | high_vol | 23 | $-1,061 | 30% |
| mid(.15-.25) | normal | 212 | $-6,048 | 38% |

## By version (top 15 by trade count)

| Version | Trades | PnL | WR |
|---|---|---|---|
| v172_pruned_trend | 68 | $+23,760 | 51% |
| v177_ensemble_extended | 67 | $+1,174 | 30% |
| v172_trend | 64 | $+18,437 | 44% |
| v171_trend | 63 | $+14,727 | 41% |
| v172_pruned_crisis | 62 | $-35,475 | 32% |
| v172_pruned_recent | 61 | $-12,534 | 36% |
| v172_recent | 60 | $-2,232 | 43% |
| v172_crisis | 59 | $-31,599 | 31% |
| v171_crisis | 56 | $-28,526 | 30% |
| v171_recent | 55 | $-7,040 | 49% |
| v172_fresh_60d | 54 | $+1,487 | 37% |
| v172_fresh_30d | 50 | $-22 | 36% |
| v174c_fresh_live | 46 | $+777 | 35% |
| v172_fresh_live | 45 | $+277 | 36% |
| v176_rebaseline | 45 | $-74 | 27% |
