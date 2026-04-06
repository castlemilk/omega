# V52 Training Forensics

**Run**: 2026-04-06, 200 cycles, 44.5 min (13.4s/cycle avg)
**Result**: PnL **-$55.90** | WR **24.7%** | 85 closed trades | Profit factor **0.583**
**Gates**: ❌ FAILED (4/4 gates)

---

## Final Numbers

| Metric | V52 | V48 (baseline) | Delta |
|--------|-----|----------------|-------|
| Total PnL | -$55.90 | +$31.97 | -$87.87 |
| Win Rate | 24.7% | — | — |
| Closed Trades | 85 | — | — |
| Long trades | 49 | — | — |
| Short trades | 36 | — | — |
| Crisis PnL | -$89.53 | -$1.58 | -$87.95 |
| Normal PnL | -$4.71 | +$16.49 | -$21.20 |
| High-vol PnL | +$4.93 | +$17.06 | -$12.13 |
| Zero-trade cycles | 132/200 (66%) | — | — |
| Ring-1 pass rate | 100% | — | — |
| Conviction filter rate | 59.3% | — | — |

---

## Gate Failures

1. **pnl_floor**: -$55.90 < v48 +$31.97 ❌
2. **regime_parity[crisis]**: -$89.53 < v48 -$1.58 (delta -$87.95) ❌
3. **regime_parity[normal]**: -$4.71 < v48 +$16.49 (delta -$21.20) ❌
4. **regime_parity[high_vol]**: +$4.93 < v48 +$17.06 (delta -$12.13) ❌

---

## Per-Symbol Breakdown

| Symbol | PnL | Trades | WR | Sides | Regimes |
|--------|-----|--------|----|-------|---------|
| ETHUSDT | **-$54.65** | 37 | 43.2% | all long | crisis:14, normal:19, high_vol:4 |
| AVAXUSDT | **-$23.36** | 3 | 0.0% | all long | crisis:1, normal:2 |
| DOTUSDT | **-$10.42** | 24 | 20.8% | all short | normal:13, crisis:9, high_vol:2 |
| LINKUSDT | -$0.88 | 22 | 27.3% | all long | crisis:7, normal:14, high_vol:1 |
| MATICUSDT | $0.00 | 27 | 0.0% | all short | normal:14, crisis:12, high_vol:1 |

**BTCUSDT: always blacklisted (0 trades)**

---

## Per-Regime Breakdown

| Regime | PnL | Trades | WR |
|--------|-----|--------|----|
| **crisis** | **-$89.53** | 43 | 14.0% |
| normal | -$4.71 | 62 | 30.6% |
| high_vol | +$4.93 | 8 | 25.0% |

Crisis is the catastrophic regime: 43 trades, only 6 wins (14% WR), -$89.53.

---

## Top 10 Losing Trades

| Cycle | Symbol | Side | PnL | Conv | Regime | Hold |
|-------|--------|------|-----|------|--------|------|
| 16 | AVAXUSDT | long | -$18.08 | 0.0571 | crisis | 5 |
| 106 | DOTUSDT | short | -$12.79 | 0.0547 | normal | 5 |
| 16 | ETHUSDT | long | -$11.10 | 0.0692 | crisis | 3 |
| 23 | ETHUSDT | long | -$10.34 | 0.0577 | crisis | 6 |
| 31 | DOTUSDT | short | -$9.02 | 0.0577 | crisis | 6 |
| 171 | DOTUSDT | short | -$8.66 | 0.0558 | normal | 6 |
| 177 | DOTUSDT | short | -$8.63 | 0.0557 | normal | 4 |
| 86 | ETHUSDT | long | -$8.54 | 0.0588 | crisis | 7 |
| 8 | ETHUSDT | long | -$7.69 | 0.0692 | crisis | 7 |
| 12 | ETHUSDT | long | -$6.65 | 0.0692 | crisis | 3 |

All losing ETH/AVAX trades: crisis-regime longs with convictions 0.057–0.069.
DOTUSDT shorts: initially profitable (early cycles) then reversed after cycle ~100.

---

## Conviction Distribution

- Range: **0.0500 – 0.0750** (all 85 trades in an 0.025 band — zero differentiation)
- Mean: 0.0600
- Score when trading: mean 0.035 | holding: mean 0.021 (barely distinguishable)
- Hold-cycle stats: min=3, max=7, mean=5.0

The filter at 59.3% rate is blocking some trades but not discriminating between good and bad.

---

## Root Cause Analysis

### RC1 (Critical): Wasserstein bear_prob stuck at 0.3333 forever

**Evidence**: All 157 parsed decisions show `regime_w_bear=0.3333`, `regime_w_bull=0.3333`.

**Why**: `WassersteinRegimeDetector.update()` expects signal keys from `SIGNAL_NAMES = ["basic_signals", "order_flow", "cross_asset", ...]`. The actual signal dict has keys like `sma_crossover`, not those names. Every call gets an all-zero vector → all Wasserstein distances are equal → uniform 1/3 priors forever.

**Impact**: `_apply_regime_adaptive_thresholds()` requires `bear_prob >= 0.55` to set `long_threshold=0.20`. Since bear_prob is stuck at 0.333, the crisis long suppression is **never applied**. Normal threshold (0.10, then scaled down) allows crisis-regime longs at conviction 0.057.

### RC2 (Critical): Only `sma_crossover` active — cross-sectional demeaning creates false BUY signals

**Evidence**: Every decision in `/tmp/v52_decisions.jsonl` has exactly 1 entry in `signal_traces`: `sma_crossover`. Preflight warning: `ccxt` not installed → many signals fail silently.

**Why**: In a down-trending market (basket_mean ≈ -0.34 throughout), cross-sectional demeaning makes "less bearish" look like BUY:
- MATIC falls -100% (clipped), DOT -66%
- ETH falls -1%, LINK -8.8%, AVAX -12.7%
- After demeaning: ETH/LINK/AVAX score positive → LONG
- But "less bearish than MATIC" ≠ "will go up" → longs lose

**Impact**: All 37 ETH longs, all 22 LINK longs, all 3 AVAX longs are "less bad than basket" artifacts — not genuine bullish signals.

### RC3 (Critical): Vol-regime label and conviction threshold are disconnected

**Evidence**: `regime_hmm="crisis"` fires in decisions JSONL, but `regime_w_bear=0.333` (flat Wasserstein) means the conviction filter uses normal thresholds.

**Why**: `_apply_regime_adaptive_thresholds()` uses ONLY the Wasserstein bear_prob to gate crisis threshold. The HMM vol-regime label (`_regime_hmm`) is not consulted for threshold selection.

**Impact**: Even when HMM correctly identifies "crisis", the long threshold stays at ~0.08 (normal * thresh_scale) instead of 0.20.

---

## V53 Proposed Fixes

### Fix 1 [P0]: Bridge vol_regime → conviction threshold
**File**: `omega/nodes/victoria/strategy.py:_apply_regime_adaptive_thresholds()`

```python
# After reading bear_prob/bull_prob, ALSO check HMM regime label
bear_prob = float(signals.get("_regime_w_bear_prob", -1.0))
bull_prob = float(signals.get("_regime_w_bull_prob", -1.0))
regime_hmm = str(signals.get("_regime_hmm", "normal")).lower()

# Crisis = Wasserstein bear OR HMM crisis label (handles broken Wasserstein)
is_crisis = bear_prob >= 0.55 or regime_hmm in ("crisis", "bear")
is_bull = (bull_prob >= 0.55 or regime_hmm == "bull") and not is_crisis

if is_crisis:
    self._long_conviction_threshold = 0.20   # suppressed
    self._short_conviction_threshold = 0.05  # permissive
elif is_bull:
    self._long_conviction_threshold = 0.05   # permissive
    self._short_conviction_threshold = 0.20  # suppressed
else:
    self._long_conviction_threshold = 0.10
    self._short_conviction_threshold = 0.05  # V49 normal-short fix
```

This is the single highest-impact fix. Would have blocked all crisis-regime ETH/AVAX longs (-$76 total).

### Fix 2 [P0]: Basket-direction long gate
**File**: `omega/nodes/victoria/strategy.py` — in the per-ticker trade loop

```python
# Compute basket mean before per-ticker loop
_raw_composites = [
    float(sig["composite"]) for t, sig in signals.items()
    if not t.startswith("_") and isinstance(sig, dict) and "composite" in sig
]
_basket_mean = sum(_raw_composites) / len(_raw_composites) if _raw_composites else 0.0

# In _passes_conviction_filters or before trade decision:
if _basket_mean < -0.10 and direction == "long":
    return False, f"basket_direction({_basket_mean:.3f}<-0.10)"
```

In V52, basket_mean was -0.33 to -0.34 throughout all 200 cycles. This filter would have suppressed virtually all longs without harming shorts.

### Fix 3 [P1]: Fix Wasserstein signal key mapping
**File**: `omega/nodes/victoria/wasserstein_regime.py`

SIGNAL_NAMES currently maps to abstract group names that don't match the signal dict. Change to use actual composite values that ARE available:

```python
SIGNAL_NAMES = [
    "sma_crossover",
    "order_flow",       # use 0.0 default when absent — still better than wrong keys
    "microstructure",
    "sentiment",
    "vrp",
    "onchain",
    "long_short_ratio",
    "btc_dominance",
    "rmt_signal",
    "spectral_graph",
    "alt_data",
]
```

Or alternatively, pass the per-ticker demeaned composites as the regime signal vector.

### Fix 4 [P1]: DOTUSDT short — add momentum reversal awareness
**Observation**: DOT shorts were profitable cycles 1-65 (+$19.79) but lost cycles 100-200 (-$30.21). The SMA-only signal can't detect reversal until the moving average crosses. Adding a short-term momentum signal (e.g., 3-cycle ROC) would exit DOT shorts earlier.

### Fix 5 [P2]: Minimum signal diversity gate (deferred)
Only allow trades when ≥ 3 distinct signal names are active per ticker. With only sma_crossover, the cross-sectional approach has no signal diversity. This requires ccxt installation to be effective.

---

## Priority Order for V53

1. Fix 1 (vol_regime → threshold bridge) — **single biggest impact**, -$87 crisis fix
2. Fix 2 (basket-direction long gate) — defense-in-depth against Fix 1 bypass
3. Fix 3 (Wasserstein key mapping) — fixes root cause of Fix 1's workaround need
4. Fix 4 (DOT momentum reversal) — recovers -$30 from late DOT shorts
5. Install ccxt — unlocks 14+ additional signals, removes single-signal fragility
