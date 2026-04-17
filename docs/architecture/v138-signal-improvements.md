# V138 Signal Improvements Architecture

**Status:** Planned — implementation in progress  
**Prior art:** V136a (Phase A champion), Track A/B attribution analysis (`docs/research/node-effectiveness-v136-v137.md`)

---

## Problem Statement

Attribution analysis (500 cycles, 639 activation traces) identified four categories of underperforming signals:

| Signal | Current IC | Root Cause | Fix Strategy |
|--------|-----------|------------|--------------|
| `momentum_derivative` | -0.064 | Raw first-derivative of SMA crossover is noise-dominated | EMA smoothing + regime-conditional semantics |
| `conviction_trend` | NaN | Signal memory starts empty in backtest (< 3 samples) | Warm-start from first 20 replay cycles |
| `agreement_trend` | NaN | Same — `_signal_memory` cold-start | Same warm-start fix |
| `regime_duration` | NaN | Same — `_signal_memory` cold-start | Same warm-start fix |
| ORC/Fiedler (Gate 4) | always-pass | Correlation matrix starts empty; 150+ cycles to warm | Pre-seed from first 30 snapshot bars |

**User direction:** Improve, don't remove. Every signal encodes a valid market hypothesis; the implementations need fixing.

---

## Track 1 — Signal Improvements (4 feature flags)

### 1.1 `improved_momentum_derivative` flag

**Current implementation** (`signal_memory.py:147–167`):
```
momentum_derivative = (sma_crossover[t] - mean(sma_crossover[t-3:t])) / (|mean| + 1e-8)
```
Problems:
- Raw first-difference is dominated by measurement noise
- Semantics are fixed: always interpreted as continuation
- IC = -0.064 (acts as a contra-indicator — opposite of intent)

**Improved implementation:**

```
# 1. Smooth the derivative via 5-cycle EMA
ema_deriv[t] = 0.4 × raw_deriv[t] + 0.6 × ema_deriv[t-1]   (α=0.4 ≈ 5-period)

# 2. Regime-conditional semantics
if manifold_regime == "trending":
    momentum_derivative = ema_deriv           # continuation: positive = bullish
elif manifold_regime == "mean_reversion":
    momentum_derivative = -|ema_deriv|        # overextension: high magnitude = reversal
else:  # transitional
    momentum_derivative = ema_deriv * 0.5    # attenuated, regime unclear

# 3. New signal: momentum_acceleration (second derivative)
momentum_acceleration = ema_deriv[t] - ema_deriv[t-1]   # bounded ±1
```

**Implementation files:**
- `signal_memory.py`: Add `_ema_derivative()` helper, `_momentum_acceleration()` method, add `ema_deriv_history` deque
- `signal_generation.py`: Pass `manifold_regime` from geometry state when `improved_momentum_derivative=True`

**Expected impact:** IC flips from -0.064 → target +0.05–+0.10 in trending regimes.

---

### 1.2 `signal_memory_warm_start` flag

**Root cause** (`signal_generation.py:363–372`, `signal_memory.py:75–88`):
`_SignalMemory(lookback=20)` starts empty. `get_temporal_features()` returns `{}` until ≥ 3 cycles.
In a 150-cycle backtest, cycles 1–2 have no temporal signals; cycles 3+ are fine but the first 20 cycles
have only partial history (< lookback=20).

**Fix — pre-seeding approach:**

At backtest initialization, before trading cycle 1 begins, run the signal computation silently on the first
20 replay bars to populate `_signal_memory.history`:

```python
# In run_training.py or strategy.py __init__, if signal_memory_warm_start:
for warm_cycle in range(min(20, len(replay_bars))):
    bar = replay_bars[warm_cycle]
    market_data = replay.get_market_data(warm_cycle)  # read without advancing cursor
    sig = signal_node.compute_signals(market_data, record=False)  # no trace, no reinforcement
    signal_memory.update_all(sig, vol_regime)
# Cursor remains at cycle 0; trading begins normally
```

**Implementation files:**
- `signal_generation.py`: Add `warm_start(bars: list[dict], n_cycles: int = 20)` method
- `run_training.py`: Call `signal_node.warm_start(snapshot[:20])` before training loop if flag set

**Expected impact:** `conviction_trend`, `agreement_trend`, `regime_duration` produce non-zero values from cycle 1.

---

### 1.3 `geometry_warm_start` flag

**Root cause** (`market_manifold.py:143–218`, `ollivier_ricci.py:86–150`):
Both `MarketManifold` and `OllivierRicciCurvature` maintain internal `deque` of returns per ticker.
With `window=30`, the correlation matrix requires 30 bars to be non-degenerate.
In backtest, the OHLCV snapshot starts at the beginning — there are 30+ historical bars available
before the trading window, but the geometry objects ignore them.

**Fix — pre-seed from historical bars:**

```python
# In signal_generation.py __init__ or warm_start(), if geometry_warm_start:
if self._features.geometry_warm_start and snapshot_pre_bars is not None:
    for bar in snapshot_pre_bars[-30:]:  # last 30 bars before trading window
        self._manifold.update(bar)       # populates _returns deques
        self._orc.update(bar)            # populates ORC correlation history
# Now MarketManifold and ORC have full 30-bar history from cycle 1
```

Pre-bars are available from the snapshot file (which includes lookback before the trading window).

**Implementation files:**
- `signal_generation.py`: Add `warm_start_geometry(pre_bars: list)` method
- `providers/replay.py`: Expose `get_pre_bars(n: int)` to return n bars before trading window
- `market_manifold.py`: No changes needed (update() is idempotent)
- `ollivier_ricci.py`: No changes needed

**Expected impact:** Gate 4 (ORC/Fiedler) becomes active from cycle 1 instead of cycle 30+.
ORC provides real network topology signal throughout the backtest.

---

### 1.4 `signal_reasoning` flag

**Current state**: `DecisionTrace` has an `explanation: str` field (terse, 1 sentence). No structured reasoning.

**New `reasoning` field** — natural-language multi-clause explanation:

```
reasoning = (
    "LONG signal: Fear/Greed (+0.98) and SMA Crossover (+0.45) drove composite to +0.143. "
    "Regime: crisis (bear_prob=0.65) → long threshold elevated to 0.20. "
    "AND-gate: [Gate 1 ✓ div=0.12≥0.05] [Gate 2 ✓ cold-start] [Gate 3 ✓ util=0.18] [Gate 4 ✓ warmup]. "
    "Decision: TRADE at threshold_gap=+0.023."
)
```

**Implementation** — `signal_reasoning.py` module:

```python
def build_reasoning(
    ticker: str,
    activations: list[dict],
    composite: float,
    regime: str,
    regime_context: dict,  # bear_prob, bull_prob, thresh_scale
    gate_result: GateResult | None,
    threshold_gap: float,
    final_decision: str,
) -> str:
    top_signals = sorted(activations, key=lambda a: abs(a["weighted_value"]), reverse=True)[:3]
    signal_str = ", ".join(f"{SIGNAL_NAMES[a['name']]} ({a['raw_value']:+.2f})" for a in top_signals)
    
    regime_str = f"Regime: {regime} (bear={regime_context['bear_prob']:.2f}) → thresh×{regime_context['thresh_scale']:.2f}"
    
    gate_str = ""
    if gate_result:
        gate_str = _format_gate_result(gate_result)
    
    return f"{signal_str} → composite={composite:+.3f}. {regime_str}. {gate_str}. Decision: {final_decision} gap={threshold_gap:+.3f}."
```

**Implementation files:**
- NEW: `omega/nodes/victoria/signal_reasoning.py`
- `decision_trace.py`: Add `reasoning: str = ""` field to `DecisionTrace` dataclass
- `strategy.py`: Call `build_reasoning()` before writing trace when `signal_reasoning=True`

**Expected impact:** Observability — dashboards and logs show per-decision reasoning.
Enables LLM-based post-hoc analysis of trade decisions.

---

## Track 2 — Geopolitical Signal (GDELT DOC 2.0)

### 2.1 Data Source

**GDELT DOC 2.0 API** (`https://api.gdeltproject.org/api/v2/doc/doc`):
- Free, no auth, 15-minute article updates
- Returns article-level sentiment tone + counts + source metadata
- Supports date-range queries for historical backtest replay
- Format: JSON

**Queries:**
```python
GDELT_QUERIES = {
    "crypto_regulation": "cryptocurrency regulation SEC CFTC ban",
    "sanctions": "financial sanctions SWIFT blockchain",
    "financial_crisis": "bank failure systemic risk contagion",
    "central_bank": "federal reserve interest rate quantitative easing",
    "geopolitical": "military conflict trade war sanctions embargo",
}
```

**Historical backtest support:** GDELT retains full article history. Queries can include `&STARTDATETIME=...&ENDDATETIME=...` for snapshot-aligned replay.

### 2.2 Computed Signals

| Signal | Formula | Range |
|--------|---------|-------|
| `geo_event_intensity` | Rolling 24h article count / 7-day mean | 0–3 (normalized) |
| `geo_sentiment` | Mean `avg_tone` across matching articles | -10 to +10 |
| `geo_regime_shift` | 1.0 if event_intensity > 2σ above 7-day mean, else 0.0 | binary |
| `sanctions_signal` | Sanctions query count / baseline, smoothed | 0–1 |

**Effect on composite:** These are market-level signals (like `fear_greed_signal`) applied to all tickers. In crisis/bear regimes, geo_regime_shift acts as a risk multiplier on conviction thresholds.

### 2.3 Cache Layer

```
data/cache/gdelt/
├── geo_event_intensity_{date}_{query_hash}.json   (15-min TTL)
├── geo_sentiment_{date}_{query_hash}.json
└── ...
```

Cache key: `{query_name}_{YYYYMMDD_HHmm}` truncated to 15-min windows.

**Backtest mode:** Query by date from snapshot timestamp → no cache TTL (historical is immutable).
**Live mode:** 15-min TTL, fallback to 0.0 if GDELT unreachable (same pattern as WS feeds).

### 2.4 Architecture

```
signal_generation.py
    └── _compute_geopolitical_signals()
            └── GeopoliticalSignal.compute(timestamp) → dict[str, float]
                    ├── GDELTClient.query(query, start_dt, end_dt)
                    │       └── data/cache/gdelt/ (TTL cache)
                    └── _compute_intensity(), _compute_sentiment(), _compute_regime_shift()
```

**File:** `omega/nodes/victoria/signals/geopolitical.py`

---

## V138 Feature Flags

```python
# features.py additions
improved_momentum_derivative: bool = False
"""V138: EMA-smooth momentum_derivative + regime-conditional semantics + momentum_acceleration signal."""

signal_memory_warm_start: bool = False
"""V138: Pre-seed signal_memory with first 20 replay cycles before trading starts."""

geometry_warm_start: bool = False
"""V138: Pre-seed ORC/Ricci correlation matrices from 30 pre-bars before trading window."""

signal_reasoning: bool = False
"""V138: Write natural-language reasoning to decision_traces as reasoning field."""

geopolitical_signals: bool = False
"""V138: GDELT DOC 2.0 geopolitical event signals (intensity, sentiment, regime_shift, sanctions)."""
```

**V138 Phase A preset (run ONLY after all flags implemented and unit-tested):**
```python
_PRESETS["v138_full"] = VictoriaFeatures(**{
    **_V137_BASE,                           # V137a (crisis_long_block + ATR + AND-gate)
    "improved_momentum_derivative": True,
    "signal_memory_warm_start": True,
    "geometry_warm_start": True,
    "signal_reasoning": True,
    "geopolitical_signals": True,
})
```

---

## Testing Plan

Before running V138 Phase A, each module must pass unit tests:

| Module | Test | Pass Criteria |
|--------|------|--------------|
| `improved_momentum_derivative` | Compute on 20-cycle replay; check EMA smoothing reduces noise | std(EMA_deriv) < std(raw_deriv) |
| `signal_memory_warm_start` | Warm-start 20 cycles; verify temporal features non-zero at cycle 1 | `conviction_trend != 0.0` at cycle 1 |
| `geometry_warm_start` | Pre-seed 30 bars; check ORC mean_curvature != 0 at cycle 1 | `orc_mean != 0.0` at cycle 1 |
| `signal_reasoning` | Generate reasoning for 5 trades; check key fields present | All key clauses in output string |
| `geopolitical_signals` | Query GDELT with date range; check 4 signals non-zero | All signals ∈ valid ranges |
| Integration | Run V138 preset for 10 cycles; check no exceptions | Clean run |

---

## Implementation Order

1. Architecture doc (this file) → commit
2. `signal_reasoning.py` (lowest risk, pure addition)
3. `improved_momentum_derivative` in `signal_memory.py`
4. `signal_memory_warm_start` in `signal_generation.py` + `run_training.py`
5. `geometry_warm_start` in `signal_generation.py` + `providers/replay.py`
6. `geopolitical.py` signal module (most complex, external API)
7. Wire all into `signal_generation.py` + `features.py`
8. Unit tests for all modules
9. Greenlight V138 Phase A
