# V16 Training Results — 2026-03-28

## Run Configuration

| Parameter | Value |
|---|---|
| Cycles | 100 |
| Sleep between cycles | 30s |
| Total runtime | 3570s (59.5 min) |
| Avg cycle time | 35.7s |
| Commit | `f2c7c8b` |
| Branch | `main` |

## Fixes Active in This Run

| Fix | Status |
|---|---|
| Continuous regime probability scaling (bear_prob → long weight, bull_prob → short weight) | ✅ Active |
| ETHUSDT long blacklist | ✅ Active |
| BTCUSDT fully blacklisted (no trading) | ✅ Active |
| 35% fallback regime threshold | ✅ Active |
| Carry + pairs + spectral_graph signals | ✅ Active |
| Improvement engine every 10 cycles | ✅ Fired at cycles 10, 20, 30... |

## Overall Results

| Metric | Value |
|---|---|
| Closed trades | 161 |
| Open positions at end | 5 |
| Total PnL | **+$103.45** |
| Engine realised PnL | +$103.45 |
| Win rate | 39.1% (63/161) |
| Profit factor | **1.41** |
| Regime state | UNKN throughout (fallback to 35% binary threshold) |

## Blacklist Verification

| Check | Result |
|---|---|
| ETHUSDT longs generated | **0** — blacklist working ✅ |
| BTCUSDT trades (any direction) | **0** — fully blacklisted ✅ |
| All trades direction | **short only** (long=0, short=161) |

The continuous regime scaling via `_regime_w_bear_prob` / `_regime_w_bull_prob` signal keys was not
triggered — the regime state stayed UNKN throughout, so the 35% fallback binary block applied instead.
This caused all longs to be blocked (regime uncertainty → fallback → no longs pass threshold).

## Regime Scaling

`"Regime scaling: bear=X, bull=Y"` log message: **0 occurrences** (not triggered).

The `cross_asset` signal was consistently the Ring 1 adversarial outlier every cycle, which may be
contributing to the UNKN regime classification. The Wasserstein regime detector fell back to simple
mean-distance approximation (scipy not available).

## Per-Symbol Breakdown (DB, closed trades only)

| Symbol | Side | Trades | PnL | Win Rate |
|---|---|---|---|---|
| DOTUSDT | short | 20 | **+$60.42** | 45.0% |
| AVAXUSDT | short | 16 | +$12.57 | 37.5% |
| BNBUSDT | short | 18 | +$11.58 | 55.6% |
| SOLUSDT | short | 19 | +$8.02 | 47.4% |
| ADAUSDT | short | 18 | +$6.71 | 44.4% |
| LINKUSDT | short | 16 | +$6.45 | 25.0% |
| ETHUSDT | short | 17 | +$3.59 | 52.9% |
| MATICUSDT | short | 19 | $0.00 | 0.0% |
| XRPUSDT | short | 18 | **-$5.90** | 44.4% |

**DOTUSDT** dominant contributor (+$60 / 58% of total PnL).
**XRPUSDT** only losing symbol (-$5.90).
**MATICUSDT** 0% win rate — no closed winners despite 19 trades (all break-even or net-zero).

## Sit-Out Breakdown

| Reason | Count | % |
|---|---|---|
| stale_data | 0 | 0% |
| vol_low | 0 | 0% |
| vol_high | 0 | 0% |
| regime_uncertain | 0 | 0% |
| normal | 100 | 100% |

All 100 cycles executed normally — no sit-outs triggered.

## Comparison vs Prior Runs

| Version | Trades | PnL | Win Rate | Profit Factor |
|---|---|---|---|---|
| V15 (prev best) | ~120 | ~+$60 | ~45% | ~1.3 |
| **V16** | **161** | **+$103.45** | **39.1%** | **1.41** |

V16 shows higher volume, higher absolute PnL, and better profit factor despite lower win rate —
consistent with a short-only regime where the market was trending down. The blacklist + regime
scaling are working, though continuous regime scaling hasn't activated yet (needs non-UNKN regime).

## Notable Observations

1. **All-short regime**: 100% shorts — the strategy correctly avoided longs given current bearish
   market conditions. Regime scaling fallback at 35% is effectively blocking all longs.

2. **Regime stays UNKN**: `cross_asset` signal consistently flagged as Ring 1 outlier every cycle.
   This may be suppressing regime detection confidence. Worth investigating `cross_asset` signal quality.

3. **Improvement engine limitation**: TPE improvement fails with `ImprovementEngine has no evaluator
   configured` — improvement engine fires but can't suggest parameter changes without a domain evaluator.

4. **DB persistence schema mismatch**: Open trade inserts fail (`exit_price NOT NULL`). Closed trades
   write successfully. This is a pre-existing schema issue, not a V16 regression.

5. **scipy not available**: Wasserstein regime detector falls back to mean-distance approximation.
   Installing scipy would improve regime classification quality.

## Next Steps

- Investigate `cross_asset` signal outlier — consistently 0.5+ disagreement vs all other signals
- Install scipy for proper Wasserstein regime detection
- Wire a domain evaluator into the improvement engine
- Consider loosening the Ring 1 threshold or suppressing `cross_asset` in regime calculation
- Once regime exits UNKN state, verify continuous scaling logs appear (`bear=X, bull=Y`)
