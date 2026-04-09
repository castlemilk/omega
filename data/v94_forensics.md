# V94 Forensics Report

**Generated**: 2026-04-09  
**Baseline**: V93 (+$130.91, 60T, 48.3% WR, PF 2.396)  
**Target**: V94 (-$37.86, 69T, 30.4% WR, PF 0.820)  
**Delta**: -$168.77 PnL, +9T count, -18pp WR

---

## Summary

V94 introduced one change: lowered normal regime `short_thresh` from 0.07 → 0.05, intended to generate more shorts. Instead, the extra 14 sub-0.07 short trades netted approximately +$14. The real cause of V94's failure was a pre-existing thresh_scale deflation bug that was already present in V93 but was masked by V93's favorable market conditions.

**Root cause**: `_thresh_scale = basket_std / 0.20` has no lower floor. In quiet markets during V94 (`basket_std ≈ 0.033`), `thresh_scale = 0.165`. This deflates crisis `long_thresh` from 0.50 to `0.50 × 0.165 = 0.083` — allowing trades at conviction=0.083 to pass through a threshold that was intended to require conviction=0.50.

---

## Per-Symbol PnL Delta (V93 → V94)

| Symbol   | V93 Trades | V94 Trades | V93 PnL    | V94 PnL    | Delta      |
|----------|-----------|-----------|-----------|-----------|-----------|
| ADAUSDT  | 15        | 16        | +$17.39   | -$37.77   | **-$55.15** |
| ARBUSDT  | 14        | 16        | +$73.58   | +$12.64   | -$60.93  |
| NEARUSDT | 15        | 17        | +$38.97   | -$7.03    | -$46.00  |
| ETHUSDT  | 16        | 20        | +$0.98    | -$5.71    | -$6.69   |

---

## Regime Breakdown

### V93 (baseline)
| Regime   | Trades | WR   | PnL      |
|----------|--------|------|---------|
| crisis   | 16     | 69%  | +$112.98 |
| high_vol | 12     | 50%  | +$40.72  |
| normal   | 32     | 34%  | -$22.79  |

### V94 (target)
| Regime   | Trades | WR   | PnL      |
|----------|--------|------|---------|
| crisis   | 31     | 19%  | -$56.29  |
| high_vol | 14     | 43%  | +$28.15  |
| normal   | 24     | 25%  | -$9.72   |

**Crisis regime degradation**: +$112.98 → -$56.29 (**Δ-$169.27**). This is virtually the entire performance delta.

---

## Crisis Regime Deep Dive (V94)

| Symbol   | Trades | WR  | PnL      |
|----------|--------|-----|---------|
| ADAUSDT  | 8      | 0%  | -$36.49  |
| NEARUSDT | 6      | 0%  | -$19.05  |
| ETHUSDT  | 10     | 40% | -$13.13  |
| ARBUSDT  | 7      | 14% | +$12.38  |

ADAUSDT and NEARUSDT combined: 14 trades, **0% win rate**, -$55.54.

---

## Root Cause: thresh_scale Deflation in Quiet Markets

### The bug

In `strategy.py` (~line 1082):
```python
_thresh_scale = min(_basket_std / 0.20, 1.5)
```

There is **no lower floor**. The scale factor can approach zero.

### During V94

- Market regime: quiet (low volatility)  
- `basket_std ≈ 0.033`  
- `thresh_scale = 0.033 / 0.20 = 0.165`

Crisis threshold after scaling:
```
long_thresh = 0.50 × 0.165 = 0.083
```

A trade at conviction=0.083 passes a threshold meant to represent conviction=0.50. The system was accepting "barely-there" conviction signals during the riskiest regime.

### Why V93 didn't show this

V93 ran in higher-volatility market conditions. When `basket_std ≈ 0.20+`, `thresh_scale ≈ 1.0`, and crisis `long_thresh ≈ 0.50` as intended. The bug was latent.

### Why the short_thresh change wasn't the culprit

The 14 extra sub-0.07 short trades introduced by V94's threshold change netted approximately +$14 (these were small, spread across normal and high_vol). They were not the cause of the -$168.77 swing.

---

## The Fix

Add a floor to `thresh_scale` to prevent crisis threshold collapse:

```python
# Before (line ~1082):
_thresh_scale = min(_basket_std / 0.20, 1.5)

# After:
_thresh_scale = max(min(_basket_std / 0.20, 1.5), 0.5)
```

This ensures that even in quiet markets, all regime thresholds are scaled to at most half their intended values — not to 16%. Crisis `long_thresh` will floor at `0.50 × 0.50 = 0.25` instead of `0.50 × 0.165 = 0.083`.

---

## Additional Issues Identified

1. **short_thresh 0.05 reverted to 0.07**: V94 showed the looser threshold was acceptable but the extra signals were noise. Reverting in V95.

2. **All new symbols vulnerable in crisis**: ADAUSDT (0% WR in crisis) and NEARUSDT (0% WR in crisis) suggest these altcoins are less reliable crisis indicators than ETH. Consider per-symbol crisis conviction floors or altcoin-specific crisis suppression.

3. **Crisis regime assignment accuracy**: 31/69 V94 trades were labeled crisis. If `basket_std` was low, `bear_prob` may have been marginally elevated, causing over-classification into crisis where the actual risk was minimal.

---

## Recommendations for V95

1. **Fix thresh_scale floor**: `max(min(basket_std/0.20, 1.5), 0.5)` — prevents threshold collapse in quiet markets
2. **Revert short_thresh**: 0.05 → 0.07 (V93 value)
3. **Geometry signals** (parallel track): Ricci sizing, ORC stress, geodesic crash distance, Fiedler conviction modulation — these should provide independent signal corroboration to avoid low-conviction trades slipping through even if thresholds are accidentally deflated
