# Historical Backtest Results

_Generated: 2026-03-26 15:00:10 UTC_

## Regimes Tested

| Regime | Period | Description | Train End |
|--------|--------|-------------|-----------|
| BULL | 2023-10-01 → 2024-03-15 | BTC $26K → $73K (+180%) | 2024-01-08 |
| BEAR | 2022-05-01 → 2022-11-15 | BTC $38K → $16K (−58%) | 2022-08-27 |
| SIDEWAYS | 2024-07-01 → 2024-10-15 | BTC $55K–$70K (ranging) | 2024-09-02 |

**Walk-forward**: first 60% used for meta-model training (IC-derived signal weights); last 40% used for out-of-sample evaluation.

## Performance Metrics (Test Period — Out-of-Sample)

| Metric | BULL | BEAR | SIDEWAYS |
|--------|------|------|----------|
| Total Return % | -30.34% | +3.55% | +16.51% |
| Annualised Return % | -54.84% | +6.65% | +69.24% |
| Sharpe Ratio | -4.121 | +0.586 | +3.398 |
| Sortino Ratio | -4.950 | +0.784 | +4.725 |
| Max Drawdown % | 38.99% | 9.00% | 4.94% |
| Calmar Ratio | -1.407 | +0.739 | +14.029 |
| Profit Factor | 0.228 | 9.990 | 9.990 |
| Win Rate | 55.6% | 100.0% | 100.0% |
| Long Win Rate | 100.0% | 100.0% | 100.0% |
| Short Win Rate | 42.9% | 100.0% | 100.0% |
| Total Trades | 9 | 2 | 6 |
| Avg Trade Duration | 17.3 days | 16.5 days | 11.5 days |
| Avg MAE % | 26.70% | 19.83% | 5.39% |
| Avg MFE % | 6.98% | 24.26% | 9.23% |

## Signal IC Attribution

> **IC** = Pearson correlation between signal value at day _t_ and
> next-day return at day _t+1_. Positive IC → signal correctly predicts direction.
> Values are averaged across BTC, ETH, SOL.

| Signal | BULL | BEAR | SIDEWAYS | Notes |
|--------|------|------|----------|-------|
| `sma_cross` | +0.0567 | -0.1750 | -0.2139 | SMA(10/30) crossover — trend following |
| `rsi` | -0.1153 | +0.1442 | +0.1402 | RSI(14) mean reversion — fade extremes |
| `macd` | +0.0939 | -0.1292 | -0.2799 | MACD(12/26/9) momentum |
| `bb_pct` | -0.1133 | +0.0610 | +0.0656 | Bollinger %B(20,2) — range fade |
| `momentum_20` | +0.1162 | -0.1720 | -0.1894 | 20-day price momentum |
| `momentum_60` | -0.0682 | -0.0727 | -0.0860 | 60-day price momentum |
| `vol_regime` | +0.1381 | +0.0787 | -0.3892 | Volatility regime filter |

## Training-Period Signal Weights (Meta-Model)

IC-derived weights from the first 60% of each period. These weights are
then applied to generate the combined trading signal in the test period.

| Signal | BULL | BEAR | SIDEWAYS |
|--------|------|------|----------|
| `sma_cross` | -0.0832 | +0.0140 | -0.4343 |
| `rsi` | +0.1792 | -0.0242 | +0.1395 |
| `macd` | -0.0433 | +0.1839 | -0.0294 |
| `bb_pct` | +0.1576 | -0.0653 | +0.0920 |
| `momentum_20` | -0.1553 | +0.0092 | -0.3048 |
| `momentum_60` | -0.1596 | -0.3421 | +0.0000 |
| `vol_regime` | -0.2216 | -0.3613 | +0.0000 |

## Key Findings

- **Best regime**: SIDEWAYS (Sharpe +3.398)
- **Worst regime**: BULL (Sharpe -4.121)
- **BULL** strongest signal: `vol_regime` (IC +0.1381)
- **BEAR** strongest signal: `sma_cross` (IC -0.1750)
- **SIDEWAYS** strongest signal: `vol_regime` (IC -0.3892)
- **Total trades across all regimes**: 17

## Methodology

- **Data**: Binance public API, daily OHLCV (BTC, ETH, SOL), cached to `data/historical/`
- **Signals**: SMA crossover, RSI, MACD, Bollinger Bands, 20d/60d momentum, vol regime
- **Meta-model**: IC-weighted signal combination (weights derived from training period)
- **Entry**: next bar's open when score ≥ 0.15 (long) or ≤ −0.15 (short)
- **Exit**: next bar's open when combined score crosses zero
- **MAE**: max adverse excursion from daily low/high; **MFE**: max favorable
- **Sharpe/Sortino**: annualised (×√252). Portfolio = equal-weight average of BTC+ETH+SOL
- **No look-ahead bias**: signals use only close-of-day data; execute at next-day open
