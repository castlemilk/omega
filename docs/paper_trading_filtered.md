# Filtered Paper Trading Results

*Generated: 2026-03-26*

## Summary

Win rate reached 42.9% — above the 33% baseline but below 50% target.

## Configuration

| Parameter | Value |
|-----------|-------|
| Agreement ratio threshold | 0.60 (≥60% of sub-signals must agree) |
| Weighted conviction threshold | 0.30 (IC-weighted composite) |
| Regime filter | high-vol → agreement ≥ 0.5, conviction × 1.5 |
| Time filter | no new positions within 2 cycles of last trade |
| Forward evaluation window | 5 bars |
| Cycles run | 200 |
| Signal ICs loaded | 1 |

## Results

| Metric | Value |
|--------|-------|
| Proposals generated (pre-filter) | 42 |
| Proposals filtered out | 28 |
| Filter rate | 66.7% |
| Trades taken (post-filter) | 14 |
| **Win rate** | **42.9%** |
| Total PnL (sum of returns) | +0.0048 |
| Avg trade return | +0.0003 |
| Std trade return | 0.0732 |
| Approx Sharpe | +0.0666 |

## vs Baseline

| Metric | Unfiltered (baseline) | Filtered | Delta |
|--------|----------------------|----------|-------|
| Win rate | 33.0% | 42.9% | +9.9 pp |
| Trade count | ~400 | 14 | -386 |
| Filter rate | 0% | 66.7% | — |

## Signal Audit — Per-Signal Predictive Power

| Signal | IC | Solo WR | SNR | Status |
|--------|-----|---------|-----|--------|
| `volume_signal` | +0.0299 | 0.534 | +0.1083 | keep |
| `bb_signal` | -0.0021 | 0.525 | -0.0475 | **KILL** |
| `zscore_signal` | -0.0061 | 0.497 | -0.0098 | **KILL** |
| `rsi_signal` | -0.0164 | 0.549 | -0.0895 | **KILL** |
| `sma_crossover` | -0.0664 | 0.430 | -0.0853 | **KILL** |
| `btc_beta_signal` | -0.0835 | 0.400 | -0.1284 | **KILL** |

## Conclusion

Win rate reached 42.9% — above the 33% baseline but below 50% target.
The conviction filters removed **67%** of candidate proposals,
dramatically reducing trade frequency
while improving quality vs baseline.

### Next Steps
- Tighten agreement_ratio_threshold to 0.65 or raise weighted_conviction_threshold to 0.35.
- Run signal_audit again after 500 cycles to update ICs with live signal history.
- Monitor per-signal IC drift; re-run audit if win rate drops below 45%.
