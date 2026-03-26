# Regime-Aware Backtest Results

Generated: 2026-03-26 04:52 UTC

## Summary

| Regime | Before Fix | After Fix |
|--------|-----------|-----------|
| BULL    |     +0.9% |     +1.3% |
| BEAR    |     -0.8% |     +0.0% |
| SIDEWAYS |     -0.2% |     +0.0% |

## Detailed Results by Regime

### BULL Regime (2023-10-01 → 2024-03-31)

| Symbol | Baseline Return | Fixed Return | Delta | Sharpe (fixed) | Max DD (fixed) | Active Days |
|--------|----------------|--------------|-------|----------------|----------------|-------------|
| BTC/USDT | +0.7% | +1.1% | +0.4% | +1.588 | 0.9% | 104/142 |
| ETH/USDT | +1.2% | +1.5% | +0.3% | +2.031 | 0.8% | 103/142 |

### BEAR Regime (2022-05-01 → 2022-11-30)

| Symbol | Baseline Return | Fixed Return | Delta | Sharpe (fixed) | Max DD (fixed) | Active Days |
|--------|----------------|--------------|-------|----------------|----------------|-------------|
| BTC/USDT | -0.8% | +0.1% | +0.9% | +1.310 | 0.0% | 2/173 |
| ETH/USDT | -0.8% | +0.0% | +0.8% | +0.000 | 0.0% | 0/173 |

### SIDEWAYS Regime (2024-07-01 → 2024-10-31)

| Symbol | Baseline Return | Fixed Return | Delta | Sharpe (fixed) | Max DD (fixed) | Active Days |
|--------|----------------|--------------|-------|----------------|----------------|-------------|
| BTC/USDT | +0.3% | +0.0% | -0.3% | +0.000 | 0.0% | 0/82 |
| ETH/USDT | -0.7% | +0.0% | +0.7% | +0.000 | 0.0% | 0/82 |

## Live Cycles (200 steps, recent data)

| Symbol | Auto-Regime | 20d Return | Strategy Return | Sharpe | Active Days |
|--------|-------------|-----------|----------------|--------|-------------|
| BTC/USDT | SIDEWAYS | +7.5% | +0.0% | +0.000 | 0/199 |
| ETH/USDT | SIDEWAYS | +11.1% | +0.0% | +0.000 | 0/199 |

## Regime Signal Multipliers Applied

| Signal | BULL | BEAR | SIDEWAYS |
|--------|------|------|----------|
| momentum (SMA) | 1.5 | 0.3 | 0.2 |
| rsi | 0.5 | 1.5 | 1.4 |
| vol_regime | 0.3 | 0.8 | 1.5 |
| bb | 1.0 | 1.3 | 1.2 |
| macd | 1.2 | 0.8 | 0.7 |
| vwm | 1.1 | 0.9 | 0.8 |

## Conviction Thresholds Applied

| Regime | Agreement Ratio | Min Conviction |
|--------|----------------|----------------|
| BULL | ≥ 0.50 | — |
| BEAR | ≥ 0.70 | — |
| SIDEWAYS | ≥ 0.60 | > 0.40 |

## Notes

- Baseline: uniform Brier-weight aggregation, no regime awareness
- Fixed: regime-specific multipliers + BULL momentum floor (min weight 0.30)
- Trend strength gate: 20d+60d momentum agreement AND price > SMA50
- Long-only, half-Kelly sizing, 0.1% commission per side
- Walk-forward expanding window, no lookahead
