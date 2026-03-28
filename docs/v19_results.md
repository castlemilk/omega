# V19 Training Results — 2026-03-28

## Run Configuration

| Parameter | Value |
|---|---|
| Log file | `/tmp/v19_training.log` |
| Internal banner | "V12 Training Run" (naming inconsistency — script internal label) |
| Output files | `data/v10_results.json`, `data/v10_trades.csv` |
| Cycles | 100 |
| Sleep between cycles | 30s |
| Total runtime | 3564s (59.4 min) |
| Avg cycle time | 35.64s |
| scipy available | No — Wasserstein regime detector in fallback mode |
| ANTHROPIC_API_KEY | Not set — brain in degraded mode |
| BINANCE_API_KEY | Not set — using CoinGecko only |

## Overall Results

| Metric | Value |
|---|---|
| Closed trades | **25** |
| Open positions at end | 0 |
| Total PnL | **+$32.04** |
| Engine realised PnL | +$32.04 |
| Win rate | **44.0%** (11/25) |
| Gross profit | $73.22 |
| Gross loss | $41.18 |
| Profit factor | **1.78** |
| Regime state | UNKN throughout |
| Long trades | **0** |
| Short trades | **25** |

## Critical Issue: Ring 1 Adversarial Gate Fired Every Cycle

**Ring 1 fired 109 times across 100 cycles** (including cycle 0) — a 100% fire rate. This is the dominant story of V19.

| Stat | Value |
|---|---|
| Ring 1 fires | 109 (100% of cycles) |
| SUPERVISED blocks | 9 explicit |
| Consecutive `basic_signals` divergences at run end | 20 |
| Trade generation cutoff | Cycle ~20 |
| Cycles with zero new trades | 80/100 (cycles 21–100) |

The adversarial gate threshold is 0.40. The perpetual outlier signals (from node `4a3488f6`) are:

1. **`long_short_ratio`** — appeared in Ring 1 warnings on virtually every cycle
2. **`basic_signals`** — 20 consecutive divergences by end, gap reaching 0.93 at peak
3. **`cross_asset`**, **`momentum_factor`**, **`spectral_graph`**, **`onchain`** — frequent co-outliers

These signals are not noise — they're structurally divergent from the consensus cluster. All 25 trades were executed in cycles 1–20 before Ring 1 blockage became total. After cycle 20, no new proposals were ever approved.

### Ring 1 Disagreement Trend (by cycle)

| Cycle | Max Disagreement | Consecutive Divergences |
|---|---|---|
| 0–1 | 0.422 | 1 |
| 82 | 0.634 | — |
| 85 | 0.613 | 5 |
| 90 | 0.532 | 13 |
| 93 | 0.485 | 16 |
| 95 | 0.473 | 18 |
| 97 | 0.512 | 20 |

The disagreement fluctuated but never dropped below the 0.40 threshold at any cycle.

## Per-Symbol Breakdown

| Symbol | Side | Trades | PnL | Win Rate |
|---|---|---|---|---|
| DOTUSDT | short | 3 | **+$20.70** | 67% |
| SOLUSDT | short | 4 | +$5.64 | **75%** |
| ADAUSDT | short | 3 | +$5.42 | 33% |
| BNBUSDT | short | 3 | +$4.79 | 67% |
| XRPUSDT | short | 3 | **-$4.00** | 33% |
| ETHUSDT | short | 2 | -$0.50 | 50% |
| AVAXUSDT | short | 3 | -$0.02 | 33% |
| LINKUSDT | short | 2 | $0.00 | 0% |
| MATICUSDT | short | 2 | $0.00 | 0% |

- **DOTUSDT** is the dominant contributor (+$20.70 = 65% of total PnL), consistent with V16
- **SOLUSDT** best win rate at 75% (4 trades)
- **XRPUSDT** only significant loser again (-$4.00), same pattern as V16
- **LINKUSDT / MATICUSDT** zero PnL — likely stop/take-profit symmetry

## Sit-Out Breakdown

| Reason | Count | % |
|---|---|---|
| stale_data | 0 | 0% |
| vol_low | 0 | 0% |
| vol_high | 0 | 0% |
| regime_uncertain | 0 | 0% |
| normal | 100 | 100% |

All 100 cycles ran normally — sit-out filters were not the problem.

## Regression vs V16

| Version | Closed Trades | PnL | Win Rate | Profit Factor |
|---|---|---|---|---|
| V16 | 161 | **+$103.45** | 39.1% | 1.41 |
| **V19** | **25** | **+$32.04** | **44.0%** | **1.78** |

V19 has **6.4× fewer trades** and **3.2× lower PnL** than V16. The profit factor (1.78 vs 1.41) and win rate (44% vs 39%) are actually better on a per-trade basis — the underlying signal quality is reasonable. The problem is pure volume: Ring 1 strangled trade generation after cycle 20.

The adversarial threshold was raised from 0.20→0.40 in V18. V19 shows that even 0.40 is too restrictive given the structural divergence of `long_short_ratio` and `basic_signals`.

## Known Issues

1. **Ring 1 100% fire rate** — `long_short_ratio` and `basic_signals` are chronically above the 0.40 disagreement threshold. Either:
   - Raise threshold further (e.g. to 0.65–0.70 which is where the learned threshold already sits)
   - Exclude these known-divergent signals from the Ring 1 comparison set
   - Or normalise `basic_signals` output range (it outputs 0.8–0.98 while consensus is 0.03–0.14 — an order of magnitude gap)

2. **Zero long trades** — Regime stays UNKN → fallback 35% binary block → all longs suppressed. This is the same V16 pattern. Needs scipy + proper Wasserstein regime detection to exit UNKN.

3. **DB persist error at startup** — `null value in column "exit_price"`: pre-existing schema issue, non-critical (in-memory trades ran fine).

4. **scipy not installed** — Wasserstein regime detector falls back to mean-distance approximation, degrading regime quality.

5. **ANTHROPIC_API_KEY not set** — brain/improvement engine in degraded mode.

6. **Naming inconsistency** — Script banner says "V12 Training Run", log is `/tmp/v19_training.log`, output files are `v10_*`. Needs cleanup.

## Root Cause Assessment

The adversarial gate (`Ring 1`) is behaving as designed — it correctly identifies that `long_short_ratio` and `basic_signals` are structural outliers divergent from the multi-signal consensus. However, these signals appear to be systematically biased (not noisy), so they fire Ring 1 on every cycle. The fix from V18 (threshold 0.20→0.40) was necessary but insufficient — the actual disagreement level for these signals is 0.47–0.63, well above 0.40.

The learned threshold is already at 0.70 (set by the system), which suggests the adaptive mechanism has recognised this pattern. The hardcoded comparison threshold (0.40) needs to either track the learned value or these signals need to be pre-normalised.

## Next Steps

1. **Raise Ring 1 threshold to 0.65** — match the learned threshold the system already computed
2. **Normalise `basic_signals` output** — currently outputs 0.6–0.98 while consensus is 0.03–0.15; rescale to [0, 1] relative to peers
3. **Suppress `long_short_ratio` from Ring 1** — or clip its value range — it's the primary chronic outlier
4. **Install scipy** — `pip install scipy` to enable proper Wasserstein regime detection and exit UNKN state
5. **Reduce sleep to 10s** — at 25 trades / 100 cycles the system needs more throughput to generate meaningful data
6. **Fix naming** — align script banner, log filename, and output file prefixes
