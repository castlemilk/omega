# Four-Factor AND-Gate Entry Filter — Design Document

**Status**: Draft  
**Author**: Omega Code Quality Bot  
**Date**: 2026-04-15  
**Target version**: V132+ (after V131 early_loss_time_stop is confirmed)  
**Related**: `docs/research/retrospective-alpha-review.md`, `omega/nodes/victoria/exit_controller.py`, `omega/nodes/victoria/strategy.py`

---

## 1. Motivation

### 1.1 The Problem with Weighted Sum Entry

Victoria's current entry logic in `strategy.py:_passes_conviction_filters` (line 1043) is a weighted sum model:

```python
composite = Σ(ic_weight_i × signal_i)          # signal_generation.py
w_conv    = _compute_weighted_conviction(sig)   # strategy.py:_construct_portfolio
enters    = abs(w_conv) >= conv_threshold       # regime-adaptive threshold
```

The Phase A retrospective (`docs/research/retrospective-alpha-review.md`) exposed three systemic failures of this model:

**1. Dead-weight signals contaminate the composite.** Only `sma_crossover` has positive IC across all three benchmark regimes (crisis, trending, recent). `fear_greed_signal` and `ollivier_ricci_signal` are DEAD WEIGHT — negative IC in every regime. Because the weighted sum aggregates all signals, a strong `fear_greed` reading can flip a genuine SMA signal from SELL to BUY.

**2. The disposition coefficient is structurally negative.** Across all V93–V127 configurations the disposition coefficient (`aggregate_disposition()` in `exit_controller.py:264`) is −0.44 to −0.62. The system cuts winners early and holds losers, losing ~50% of potential profit per trade. The current entry filter has no mechanism to detect when this collapse is in progress and pause new entries.

**3. The model ignores whether it is right.** The entry logic computes model conviction from signals, but never checks whether the market agrees via an independent measure. A high-conviction entry into a position where market-implied probability is identical to the model's probability is a zero-edge trade.

### 1.2 The AND-Gate Insight

Instead of a single soft threshold (`w_conv ≥ threshold`), we require four independent binary conditions. Each gate guards a distinct failure mode:

| Gate | Guards against |
|------|---------------|
| `cross_market_divergence_gate` | Zero-edge trades where model = market |
| `disposition_gate` | Entering while exit discipline has collapsed |
| `capital_velocity_gate` | Overleverage / position concentration |
| `pair_network_gate` | Entering during microstructure fragmentation |

Only when all four pass does the system enter. Any gate breaking triggers an exit check (in addition to existing MFE trailing stop and `early_loss_time_stop`).

### 1.3 Expected Effects

- **Fewer trades, higher precision**: If each gate passes independently 70% of the time, `AND(4) = 0.7^4 ≈ 24%` of current trade proposals are accepted. With realistic positive correlation between gates (both `cross_market_divergence_gate` and `pair_network_gate` tighten in market stress), the practical pass rate is 30–40%.
- **Better disposition**: `disposition_gate` directly prevents the system from entering new positions while already bleeding on poorly-exited trades.
- **Regime awareness at entry**: `pair_network_gate` uses the same geometric signals that currently modulate thresholds, but converts them to a hard binary block — cleaner than threshold arithmetic.

---

## 2. Architecture Overview

### 2.1 Entry Flow

```
_construct_portfolio(signals, market_data)
  │
  ├─ existing: _apply_regime_adaptive_thresholds()
  ├─ existing: _passes_conviction_filters(sig, cycle, direction)  [weighted sum]
  │
  └─ NEW (feature-gated):
       FourFactorGate.evaluate(context) → GateResult
         │
         ├─ Gate 1: cross_market_divergence_gate  (model vs market)
         ├─ Gate 2: disposition_gate              (rolling exit discipline)
         ├─ Gate 3: capital_velocity_gate         (utilization + position count)
         └─ Gate 4: pair_network_gate             (ORC / Fiedler network health)
         │
         all_pass? → allow entry
         any_fail? → skip (log failing gate + reason)
```

The existing `_passes_conviction_filters` pipeline runs **first** and is unchanged. The four-factor gate is a second, independent filter applied only when `features.four_factor_and_gate = True`. This ensures V93-baseline parity when the flag is off.

### 2.2 Exit Flow (AND-gate break)

On each call to `PaperTradingEngine.mark_to_market()`, after the existing ATR-based exits:

```
for each open position:
  if features.four_factor_and_gate:
    gate_result = FourFactorGate.evaluate_exit(context, pos)
    if gate_result.any_broken:
      close position (reason = f"gate_break:{gate_result.broken_gate}")
```

Gate breaks on exit use the same gate objects but evaluated against current market state for the position's ticker. The MFE trailing stop (`exit_controller.py`) fires first; gate-break is the secondary exit mechanism.

### 2.3 Data Flow Diagram

```
signal_generation.py
  ├─ per-ticker signals: {"ollivier_ricci_signal": float, "funding_rate_signal": float, ...}
  └─ basket signals: {"_geometry_orc_kappa": float, "_geometry_orc_regime": str, ...}
           │
           ▼
strategy.py:_construct_portfolio
  ├─ existing conviction pipeline
  └─ FourFactorGate(
       raw_composite   = w_conv (pre-threshold)
       funding_rate    = sig["funding_rate_signal"]      # per-ticker
       closed_trades   = engine.closed_trades            # PaperTradingEngine
       open_positions  = engine.positions                # PaperTradingEngine
       initial_capital = engine.initial_capital
       orc_signal      = signals["_geometry_orc_kappa"]  # basket-level
       fiedler_zscore  = _spectral_val.value             # from _spectral.compute()
     )
```

---

## 3. Gate Specifications

### 3.1 Gate 1: `cross_market_divergence_gate`

**Purpose**: Only enter when the model's implied probability and the market-implied probability diverge by a meaningful amount. A trade where both the model and the market agree on direction carries no edge — the market has already priced it.

#### Formula

**Step 1 — model probability** (logistic mapping of IC-weighted composite):

```python
import math

def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))

# w_conv is already computed by _compute_weighted_conviction(sig)
# scale=5.0 maps w_conv=±0.20 → p_model ≈ 0.73/0.27
p_model: float = sigmoid(w_conv * scale)   # scale = 5.0 (tunable)
```

For a long entry `w_conv > 0` → `p_model > 0.5` (model says price goes up).  
For a short entry `w_conv < 0` → `p_model < 0.5`; use `1 - p_model` for "probability of down".

**Step 2 — market-implied probability** (from funding rate):

Perpetual swap funding rates encode the market's aggregate leverage bias. Positive funding means longs are paying shorts → market leans long. Conversion to probability:

```python
# funding_rate is the raw per-period funding rate (e.g. 0.0001 = 0.01%)
# Clamp to ±0.001 (100 bps / period) before mapping; outliers are circuit-breaker events
FUNDING_CLIP = 0.001
fr_clipped = max(-FUNDING_CLIP, min(FUNDING_CLIP, funding_rate))

# Linear map: 0 funding → 0.50, +FUNDING_CLIP → 0.75, -FUNDING_CLIP → 0.25
p_implied: float = 0.50 + (fr_clipped / FUNDING_CLIP) * 0.25
```

**Step 3 — divergence check**:

```python
divergence: float = abs(p_model - p_implied)
gate_passes: bool = divergence >= DIVERGENCE_THRESHOLD   # default 0.05
```

#### Data Sources

| Variable | Source | File:line |
|----------|--------|-----------|
| `w_conv` | `_compute_weighted_conviction(sig)` | `strategy.py:1074` |
| `funding_rate` | `sig["funding_rate_signal"]` injected by `FundingRateSignal.compute(ticker)` | `signal_generation.py:816` |

The funding rate signal is already computed per-ticker each cycle when `self._funding_signal is not None` (line 811, `signal_generation.py`). It is available in the per-ticker `sig` dict.

#### Parameters

| Parameter | Default | Range | Notes |
|-----------|---------|-------|-------|
| `sigmoid_scale` | 5.0 | 2.0–10.0 | Higher = sharper; 5.0 maps w_conv=0.20 to ~73% |
| `divergence_threshold` | 0.05 | 0.02–0.15 | 5 percentage points |
| `funding_clip` | 0.001 | fixed | Clips extreme funding events |

#### Failure Mode Analysis

- **Funding rate unavailable** (Binance/Bybit geo-blocked from US, see `docs/DATA_SOURCES.md`): `funding_rate_signal` is 0.0. With fr=0.0, `p_implied=0.50`. Gate then passes iff `|p_model - 0.50| >= 0.05`, i.e. only on stronger-than-marginal conviction. This is a *conservative* degradation — acceptable.
- **Both signals weak** (`w_conv ≈ 0`, `fr ≈ 0`): `p_model ≈ 0.50`, `p_implied ≈ 0.50`, `divergence ≈ 0` → gate blocks. Correct: no edge to trade.
- **Sigmoid scale too high**: very sensitive to marginal `w_conv` values; scale=5.0 is deliberately conservative.

---

### 3.2 Gate 2: `disposition_gate`

**Purpose**: Prevent the system from opening new positions when its exit discipline has collapsed. The Phase A retrospective showed disposition_coefficient = −0.44 to −0.62 is a *structural* property of the current exit logic. After V128/V131 exits are in place, this gate monitors whether the fix is actually holding in live operation.

#### Formula

```python
from omega.nodes.victoria.exit_controller import aggregate_disposition

def disposition_gate_passes(
    closed_trades: list[dict],
    window: int = 50,
    min_trades: int = 10,
) -> bool:
    if len(closed_trades) < min_trades:
        return True   # cold-start: insufficient data, pass by default

    recent = closed_trades[-window:]  # most recent N closed trades
    stats = aggregate_disposition(recent)
    disp = stats.get("disposition_coefficient")

    if disp is None:
        return True   # no exit telemetry yet (pre-V128 trades), pass

    return disp > 0.0
```

`aggregate_disposition` (defined at `exit_controller.py:264`) returns `median(win_capture) - median(loss_capture)`. Positive means winners captured more of their MFE than losers captured of their MAE → good exit discipline.

#### Data Sources

| Variable | Source | File:line |
|----------|--------|-----------|
| `closed_trades` | `PaperTradingEngine._closed_trades` | `paper_trading.py:117` |
| `aggregate_disposition` | imported from `exit_controller` | `exit_controller.py:264` |

`PaperTradingEngine.closed_trades` property (line 199) exposes the list. The `FourFactorGate` receives this list reference on each evaluation.

#### Parameters

| Parameter | Default | Range | Notes |
|-----------|---------|-------|-------|
| `window` | 50 | 20–100 | Rolling window of recent closed trades |
| `min_trades` | 10 | 5–20 | Cold-start threshold; gate passes freely below |

#### Failure Mode Analysis

- **Cold start** (< `min_trades` closed): gate passes. New runs have no history; blocking all entries indefinitely is wrong. The system needs to trade to build history.
- **V128 exits not enabled**: `win_capture`/`loss_capture` columns are absent from pre-V128 trades. `aggregate_disposition` returns `None` for telemetry-less trades (line 302). Gate passes by default — do not penalise old trades for lacking new telemetry.
- **Sudden drawdown series**: if 10 consecutive trades are all losers, `disposition_gate` will block new entries within 10 trades. This is the desired behavior — it is a circuit breaker.
- **Interaction with V131 `early_loss_time_stop`**: V131 improves `loss_capture` by cutting losers early (before they reach MAE). Over time, `disposition_coefficient` improves. The gate is the *observable confirmation* that V131 is working. If `disposition_gate` keeps failing even with V131 on, the `early_loss_cycles`/`early_loss_k_atr` parameters need tuning.

---

### 3.3 Gate 3: `capital_velocity_gate`

**Purpose**: Prevent overleverage and excessive position concentration. "Capital velocity" here means the rate at which capital is being deployed into open risk. High utilization with multiple open positions amplifies tail risk non-linearly.

#### Formula

```python
def capital_velocity_gate_passes(
    positions: dict[str, dict],
    initial_capital: float,
    utilization_cap: float = 0.50,
    max_positions: int = 5,
) -> bool:
    open_notional = sum(
        abs(pos.get("size", 0.0))
        for pos in positions.values()
    )
    utilization = open_notional / initial_capital if initial_capital > 0 else 1.0

    utilization_ok = utilization < utilization_cap
    count_ok = len(positions) < max_positions

    return utilization_ok and count_ok
```

Note: `PaperTradingEngine._total_open_notional()` (line 148, `paper_trading.py`) computes this identically. The gate should call the engine's helper directly to avoid drift.

#### Data Sources

| Variable | Source | File:line |
|----------|--------|-----------|
| `positions` | `PaperTradingEngine._positions` | `paper_trading.py:111` |
| `initial_capital` | `PaperTradingEngine.initial_capital` | `paper_trading.py:102` |
| `_total_open_notional()` | `PaperTradingEngine._total_open_notional` | `paper_trading.py:148` |

The existing `_can_add_position()` method (line 156) already enforces `max_portfolio_exposure` and `max_position_per_symbol`. The capital_velocity_gate is a *portfolio-level* check that fires before the per-symbol check — it is more aggressive.

#### Parameters

| Parameter | Default | Range | Notes |
|-----------|---------|-------|-------|
| `utilization_cap` | 0.50 | 0.30–0.80 | 50% deployed = gate blocks new entries |
| `max_positions` | 5 | 3–10 | Hard limit on concurrent open positions |

#### Failure Mode Analysis

- **Initial capital is 0**: guard division by zero; gate fails conservatively (`utilization = 1.0 > cap`).
- **Tiny positions from historical fills**: positions with size near zero could accumulate and hit `max_positions` count. Guard: only count positions with `abs(size) > 1e-6`.
- **Interaction with `max_portfolio_exposure`**: `PaperTradingEngine` already enforces `max_portfolio_exposure * initial_capital` as the max total notional (line 156). The gate's 0.50 utilization cap is *more restrictive* when `max_portfolio_exposure > 0.50`. In default config (`max_portfolio_exposure = 0.30` from `domain_config.py`), the engine's own cap binds first. The gate's 0.50 cap acts as a belt-and-suspenders for configurations where `max_portfolio_exposure` is set higher.

---

### 3.4 Gate 4: `pair_network_gate`

**Purpose**: Sit out during market microstructure fragmentation. When the pairwise correlation network between basket assets breaks down (edges weakening, ORC going negative), the basket is no longer behaving as a coherent market. Mean-reversion and cross-asset signals become unreliable; entry here is speculative.

#### Formula

**Primary check** (Ollivier-Ricci curvature, basket-level):

```python
def pair_network_gate_passes(
    orc_kappa: float | None,
    fiedler_zscore: float | None,
    orc_threshold: float = -0.3,
    fiedler_floor: float = 0.0,
) -> bool:
    # Primary: ORC mean curvature
    if orc_kappa is not None:
        return orc_kappa > orc_threshold

    # Fallback: Fiedler z-score (λ₂ of signal correlation Laplacian)
    # fiedler_zscore > 0 means Fiedler is above its rolling mean → graph connected
    if fiedler_zscore is not None:
        return fiedler_zscore > fiedler_floor

    # Neither available (warmup period or ORC disabled): pass conservatively
    return True
```

#### Interpretation of ORC Threshold

`orc_kappa` is `_orc_state.mean_curvature` — the mean Ollivier-Ricci curvature across all edges in the asset correlation network (computed by `OllivierRicciCurvature.update()` in `signal_generation.py:689`).

- **`orc_kappa > 0`**: network is positively curved (Ricci-positive), signals are flowing coherently between assets. Normal market structure.
- **`orc_kappa ≈ 0`**: neutral; network is Euclidean. Marginal.
- **`orc_kappa < -0.3`**: network is under significant stress. Correlations are breaking. This is the pre-crisis fragmentation signature identified in the Phase A retrospective.

The `ollivier_ricci_signal` (per-ticker, range ±1) is a *normalized* version of `orc_kappa` mapped through `_orc_state.signal` — suitable for composite scoring but not directly for the gate threshold. The gate uses the raw `orc_kappa` (stored in `signals["_geometry_orc_kappa"]`) for interpretable threshold semantics.

#### Data Sources

| Variable | Source | File:line |
|----------|--------|-----------|
| `orc_kappa` | `signals["_geometry_orc_kappa"]` | `signal_generation.py:724` |
| `orc_regime` | `signals["_geometry_orc_regime"]` | `signal_generation.py:725` |
| `fiedler_zscore` | `_spectral_val.value` from `self._spectral.compute(_sv)` | `strategy.py:1451` |
| `fiedler_tag` | `_spectral_val.regime_tag` | `strategy.py:1452` |

Both values are computed before the per-ticker loop in `_construct_portfolio` and are available at gate evaluation time.

#### Parameters

| Parameter | Default | Range | Notes |
|-----------|---------|-------|-------|
| `orc_threshold` | −0.3 | −0.5 to 0.0 | More negative = more permissive |
| `fiedler_floor` | 0.0 | −1.0 to 1.0 | Positive = require above-average connectivity |

#### Failure Mode Analysis

- **ORC warmup** (`_orc is None` or `confidence < 0.3`): `orc_kappa` absent from `signals`. Gate falls back to Fiedler. If both absent, gate passes. Conservative degradation.
- **ORC disabled** (geometry flags off): same as warmup. Pass by default.
- **ORC fires during genuine crisis**: `orc_kappa << -0.3` correctly blocks entry. Interaction with `_is_crisis` in `strategy.py`: the system is already hard-blocking longs in crisis (line 1447). The gate adds a network-structure check for the short side: even in crisis, if ORC is very negative (network completely broken), the signal correlation assumptions underlying the composite are invalid.
- **Note on `ollivier_ricci_signal` as DEAD WEIGHT**: the retrospective marks `ollivier_ricci_signal` (the normalized per-ticker composite signal) as dead weight (0.41/0.43/0.48 win rates). This design does NOT use `ollivier_ricci_signal` in the composite. Instead it uses the raw `orc_kappa` (a structural indicator, not a directional signal) as a binary gate. The distinction is critical — ORC curvature as a *filter* (should I enter?) is different from ORC as a *direction signal* (should I go long or short?).

---

## 4. Interaction with Existing Systems

### 4.1 Conviction Filter Pipeline (strategy.py:_passes_conviction_filters)

The four-factor gate is applied **after** the existing conviction pipeline. The execution order in `_construct_portfolio` is:

```
1. _apply_regime_adaptive_thresholds()          # sets long/short thresholds
2. Fiedler streak tracker + long_thresh raise    # existing, lines 1467–1488
3. fiedler_conviction_modulation                 # existing, lines 1507–1530
4. per-ticker loop:
   a. _passes_conviction_filters(sig, cycle, direction)   # existing gate
   b. FourFactorGate.evaluate(context)                    # NEW (if feature enabled)
   c. build candidate entry
```

If `_passes_conviction_filters` returns False, we never reach the four-factor gate (no wasted computation). If conviction passes but a four-factor gate fails, the ticker is skipped with a log entry recording which gate failed.

**Important**: the four-factor gate does NOT replace the conviction filter. Both must pass for entry. This preserves the existing signal quality floor while adding the structural checks.

### 4.2 MFE Trailing Stop + Early Loss Time Stop (exit_controller.py)

The exit hierarchy (highest priority to lowest):

```
1. Hard MAE stop:        ExitController.should_close() when loss >= mae_stop_k * ATR
2. MFE trailing stop:    ExitController.should_close() when MFE retracement >= cap
3. Gate-break exit:      FourFactorGate.evaluate_exit() when any gate breaks
4. Early loss time-stop: ExitConfig.early_loss_time_stop (V131) — age >= N AND loss >= K*ATR
5. Time exit fallback:   existing max_hold_cycles logic
```

Gate-break on exit sits between the ATR-anchored exits (#1/#2) and the time-based fallbacks (#4/#5). This ordering means the ATR exits handle definitive price-action signals; the gate-break handles structural regime changes that aren't yet reflected in price.

### 4.3 Regime-Adaptive Thresholds (_apply_regime_adaptive_thresholds)

The regime-adaptive threshold system adjusts `long_conviction_threshold` and `short_conviction_threshold` based on HMM/Wasserstein regime detection. The four-factor gate interacts with this as follows:

- **`pair_network_gate`** partially overlaps with the Fiedler-fragmented streak logic (lines 1467–1488). The difference: the streak logic *raises a threshold* (from 0.10 to 0.25), while the gate *blocks entirely*. The gate is more conservative and fires faster (single-cycle ORC check vs 30-cycle streak accumulation).
- **`cross_market_divergence_gate`** is regime-independent. It fires based on model-vs-market divergence, not on what regime label the HMM has assigned.
- **`disposition_gate`** is also regime-independent — exit discipline degradation is a property of the strategy's behavior, not the market's regime.

### 4.4 Blacklists and Suppressions

The gate system is independent of per-symbol blacklists (`_TRADING_BLACKLIST`, `_LONG_BLACKLIST` in `strategy.py`). Blacklisted symbols are rejected before reaching either the conviction filter or the four-factor gate. No changes to blacklist logic are required.

---

## 5. Expected Trade Frequency Impact

### 5.1 Per-Gate Pass Rates (Estimated)

Based on Phase A benchmark data and the gate definitions:

| Gate | Estimated Pass Rate | Reasoning |
|------|--------------------|-----------| 
| `cross_market_divergence_gate` | 65–75% | Divergence ≥ 5pp is common when model has genuine conviction; marginal signals (w_conv ≈ 0) blocked |
| `disposition_gate` | 85–90% | Rarely fails once V128/V131 exits are working; mainly fires during sustained drawdown sequences |
| `capital_velocity_gate` | 80–90% | Fires when 5+ positions are open or > 50% deployed; normal trading keeps utilization lower |
| `pair_network_gate` | 70–80% | ORC kappa < −0.3 occurs during crisis and pre-crisis fragmentation; ~20–30% of backtest cycles |

### 5.2 Combined Pass Rate

**Independence assumption** (upper bound):
```
AND(4) = 0.70 × 0.875 × 0.85 × 0.75 ≈ 0.39
```

**With positive correlation** (gates 1 and 4 both tighten in market stress): realistic estimate 25–35% of current entries.

**In trending regime** (Q4-2023 benchmark, Victoria's best regime):
- `pair_network_gate` passes ~85% (healthy network in trend)
- `cross_market_divergence_gate` passes ~80% (SMA divergence clear in trend)
- Combined: ~55% of current entries — still a significant reduction, targeting the weakest signals

**In crisis regime** (H1-2022 benchmark, Victoria's worst regime):
- `pair_network_gate` passes ~40% (ORC highly negative during sustained bear)
- `disposition_gate` may fail after the first wave of losers
- Combined: ~20% of current entries — exactly the desired behavior (sit out most of crisis, capture clear shorts only)

### 5.3 Trade Count Floor

The minimum trade requirement for the hard gates in `omega/eval/v49_gates.py` is ≥ 20 trades per 200-cycle run. With a 30% pass rate, a run that currently produces 50 trades would produce ~15 trades — potentially below the gate floor. **The hard gates should be adjusted for four-factor runs to ≥ 10 trades** (or the min_trades parameter of the gate itself should be tuned).

---

## 6. Implementation Plan

### 6.1 Feature Flag

Add `four_factor_and_gate: bool = False` to `VictoriaFeatures` at `omega/nodes/victoria/features.py:39`:

```python
# ------------------------------------------------------------------
# V132 four-factor AND-gate entry filter
# ------------------------------------------------------------------

four_factor_and_gate: bool = False
"""V132: Replace soft weighted-sum entry with four binary AND-gates.

All four gates must pass for entry; any gate breaking triggers exit check.
  - cross_market_divergence_gate: model vs market-implied probability
  - disposition_gate: rolling exit discipline (requires V128 telemetry)
  - capital_velocity_gate: utilization + open position count
  - pair_network_gate: ORC curvature / Fiedler network health

See docs/research/four-factor-and-gate-design.md for full specification.
When to enable: after V131 early_loss_time_stop is confirmed working.
Preset: v132_four_factor.
"""

# Sub-parameters for four_factor_and_gate (only used when gate is True)
ffg_sigmoid_scale: float = 5.0
"""Sigmoid scale for cross_market_divergence_gate model probability mapping."""

ffg_divergence_threshold: float = 0.05
"""Minimum |p_model - p_implied| to pass cross_market_divergence_gate."""

ffg_disposition_window: int = 50
"""Rolling window of closed trades for disposition_gate."""

ffg_disposition_min_trades: int = 10
"""Minimum closed trades before disposition_gate activates."""

ffg_utilization_cap: float = 0.50
"""Maximum open notional / initial_capital for capital_velocity_gate."""

ffg_max_positions: int = 5
"""Maximum concurrent open positions for capital_velocity_gate."""

ffg_orc_threshold: float = -0.3
"""Minimum ORC mean curvature (orc_kappa) for pair_network_gate."""

ffg_fiedler_floor: float = 0.0
"""Minimum Fiedler z-score for pair_network_gate fallback."""
```

Also add the preset to `_PRESETS` in `features.py`:

```python
"v132_four_factor": VictoriaFeatures(
    disposition_exit_controller=True,
    mfe_trail_k=1.0,
    mfe_retracement_cap=0.25,
    mae_stop_k=0.8,
    early_loss_time_stop=True,     # V131 prerequisite
    early_loss_cycles=3,
    early_loss_k_atr=0.3,
    four_factor_and_gate=True,
    activation_tracing=True,       # full observability for validation
),
```

### 6.2 New Module: FourFactorGate

Create `omega/nodes/victoria/four_factor_gate.py`:

```python
"""
omega/nodes/victoria/four_factor_gate.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Four-factor AND-gate entry/exit filter.

All four gates must pass for entry. Any gate breaking triggers exit evaluation.

Gates:
  1. cross_market_divergence_gate  — model vs market-implied probability
  2. disposition_gate              — rolling exit discipline
  3. capital_velocity_gate         — portfolio utilization + position count
  4. pair_network_gate             — ORC / Fiedler network health

Usage in strategy._construct_portfolio:
    from omega.nodes.victoria.four_factor_gate import FourFactorGate, GateContext
    gate = FourFactorGate(features)
    ctx = GateContext(
        w_conv=w_conv,
        funding_rate=sig.get("funding_rate_signal", 0.0),
        closed_trades=engine.closed_trades,
        open_positions=engine.positions,
        initial_capital=engine.initial_capital,
        orc_kappa=float(signals.get("_geometry_orc_kappa", 0.0)) or None,
        fiedler_zscore=float(_spectral_val.value),
    )
    result = gate.evaluate(ctx)
    if not result.all_pass:
        continue  # skip this ticker entry
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GateContext:
    """All inputs needed by FourFactorGate for a single entry evaluation."""
    w_conv: float                           # IC-weighted composite pre-threshold
    funding_rate: float                     # sig["funding_rate_signal"], 0.0 if absent
    closed_trades: list[dict[str, Any]]     # PaperTradingEngine.closed_trades
    open_positions: dict[str, dict]         # PaperTradingEngine.positions
    initial_capital: float                  # PaperTradingEngine.initial_capital
    orc_kappa: float | None                 # signals["_geometry_orc_kappa"], None if absent
    fiedler_zscore: float | None            # _spectral_val.value, None if warmup


@dataclass
class GateResult:
    """Result of evaluating all four gates."""
    all_pass: bool
    cross_market_divergence: bool
    disposition: bool
    capital_velocity: bool
    pair_network: bool
    # Diagnostics
    p_model: float = 0.0
    p_implied: float = 0.0
    divergence: float = 0.0
    disposition_coefficient: float | None = None
    utilization: float = 0.0
    n_positions: int = 0
    failing_gates: list[str] = field(default_factory=list)

    @property
    def any_broken(self) -> bool:
        return not self.all_pass


class FourFactorGate:
    """Evaluates the four-factor AND-gate for entry/exit decisions."""

    def __init__(self, features: Any) -> None:
        # Read parameters from VictoriaFeatures, falling back to defaults
        self._sigmoid_scale = getattr(features, "ffg_sigmoid_scale", 5.0)
        self._divergence_threshold = getattr(features, "ffg_divergence_threshold", 0.05)
        self._disposition_window = getattr(features, "ffg_disposition_window", 50)
        self._disposition_min_trades = getattr(features, "ffg_disposition_min_trades", 10)
        self._utilization_cap = getattr(features, "ffg_utilization_cap", 0.50)
        self._max_positions = getattr(features, "ffg_max_positions", 5)
        self._orc_threshold = getattr(features, "ffg_orc_threshold", -0.3)
        self._fiedler_floor = getattr(features, "ffg_fiedler_floor", 0.0)

    @staticmethod
    def _sigmoid(x: float) -> float:
        try:
            return 1.0 / (1.0 + math.exp(-x))
        except OverflowError:
            return 0.0 if x < 0 else 1.0

    def _gate1_cross_market(self, ctx: GateContext) -> tuple[bool, float, float, float]:
        """Gate 1: cross_market_divergence_gate."""
        FUNDING_CLIP = 0.001
        p_model = self._sigmoid(ctx.w_conv * self._sigmoid_scale)
        fr_clipped = max(-FUNDING_CLIP, min(FUNDING_CLIP, ctx.funding_rate))
        p_implied = 0.50 + (fr_clipped / FUNDING_CLIP) * 0.25
        divergence = abs(p_model - p_implied)
        return divergence >= self._divergence_threshold, p_model, p_implied, divergence

    def _gate2_disposition(
        self, ctx: GateContext
    ) -> tuple[bool, float | None]:
        """Gate 2: disposition_gate."""
        from omega.nodes.victoria.exit_controller import aggregate_disposition  # local import

        n = len(ctx.closed_trades)
        if n < self._disposition_min_trades:
            return True, None   # cold-start: pass

        recent = ctx.closed_trades[-self._disposition_window :]
        stats = aggregate_disposition(recent)
        disp = stats.get("disposition_coefficient")
        if disp is None:
            return True, None   # no telemetry: pass
        return disp > 0.0, disp

    def _gate3_capital_velocity(
        self, ctx: GateContext
    ) -> tuple[bool, float, int]:
        """Gate 3: capital_velocity_gate."""
        positions = {
            sym: pos
            for sym, pos in ctx.open_positions.items()
            if abs(pos.get("size", 0.0)) > 1e-6
        }
        open_notional = sum(abs(p.get("size", 0.0)) for p in positions.values())
        utilization = open_notional / ctx.initial_capital if ctx.initial_capital > 0 else 1.0
        n_pos = len(positions)
        passes = utilization < self._utilization_cap and n_pos < self._max_positions
        return passes, utilization, n_pos

    def _gate4_pair_network(self, ctx: GateContext) -> bool:
        """Gate 4: pair_network_gate."""
        if ctx.orc_kappa is not None:
            return ctx.orc_kappa > self._orc_threshold
        if ctx.fiedler_zscore is not None:
            return ctx.fiedler_zscore > self._fiedler_floor
        return True   # warmup: pass

    def evaluate(self, ctx: GateContext) -> GateResult:
        """Evaluate all four gates and return combined result."""
        g1, p_model, p_implied, divergence = self._gate1_cross_market(ctx)
        g2, disp = self._gate2_disposition(ctx)
        g3, utilization, n_pos = self._gate3_capital_velocity(ctx)
        g4 = self._gate4_pair_network(ctx)

        failing = []
        if not g1:
            failing.append(f"cross_market_divergence(div={divergence:.3f}<{self._divergence_threshold})")
        if not g2:
            failing.append(f"disposition(coeff={disp:.3f}<=0)")
        if not g3:
            failing.append(f"capital_velocity(util={utilization:.2f},n={n_pos})")
        if not g4:
            orc_info = f"orc={ctx.orc_kappa:.3f}" if ctx.orc_kappa is not None else f"fiedler={ctx.fiedler_zscore:.3f}"
            failing.append(f"pair_network({orc_info})")

        return GateResult(
            all_pass=g1 and g2 and g3 and g4,
            cross_market_divergence=g1,
            disposition=g2,
            capital_velocity=g3,
            pair_network=g4,
            p_model=p_model,
            p_implied=p_implied,
            divergence=divergence,
            disposition_coefficient=disp,
            utilization=utilization,
            n_positions=n_pos,
            failing_gates=failing,
        )

    def evaluate_exit(
        self, ctx: GateContext, pos: dict[str, Any]
    ) -> GateResult:
        """Evaluate gates for an open position — check if any gate has broken.

        For exit purposes, only gates 1, 3, and 4 are checked (gate 2 is
        entry-only — we do not close positions because recent exit discipline
        has been bad, since that would create a feedback loop).
        """
        g1, p_model, p_implied, divergence = self._gate1_cross_market(ctx)
        g3, utilization, n_pos = self._gate3_capital_velocity(ctx)
        g4 = self._gate4_pair_network(ctx)

        failing = []
        if not g1:
            failing.append(f"cross_market_divergence(div={divergence:.3f}<{self._divergence_threshold})")
        if not g3:
            failing.append(f"capital_velocity(util={utilization:.2f},n={n_pos})")
        if not g4:
            orc_info = f"orc={ctx.orc_kappa:.3f}" if ctx.orc_kappa is not None else f"fiedler={ctx.fiedler_zscore:.3f}"
            failing.append(f"pair_network({orc_info})")

        return GateResult(
            all_pass=g1 and g3 and g4,
            cross_market_divergence=g1,
            disposition=True,   # not checked on exit
            capital_velocity=g3,
            pair_network=g4,
            p_model=p_model,
            p_implied=p_implied,
            divergence=divergence,
            disposition_coefficient=None,
            utilization=utilization,
            n_positions=n_pos,
            failing_gates=failing,
        )
```

### 6.3 Wiring into strategy.py

In `strategy.py:_construct_portfolio`, after `fiedler_conviction_modulation` (around line 1530) and before the per-ticker loop, instantiate the gate once per portfolio construction call:

```python
# V132: Four-factor AND-gate (feature-gated)
_ffg: FourFactorGate | None = None
if self.features.four_factor_and_gate:
    from omega.nodes.victoria.four_factor_gate import FourFactorGate, GateContext
    _ffg = FourFactorGate(self.features)
    _ffg_orc_kappa = float(signals.get("_geometry_orc_kappa") or 0.0) or None
    _ffg_fiedler_z = float(_spectral_val.value) if _spectral_val else None
```

Inside the per-ticker loop, after `_passes_conviction_filters` returns True:

```python
# V132: Four-factor AND-gate check
if _ffg is not None:
    _ffg_ctx = GateContext(
        w_conv=w_conv,
        funding_rate=float(sig.get("funding_rate_signal", 0.0)),
        closed_trades=engine.closed_trades if engine else [],
        open_positions=engine.positions if engine else {},
        initial_capital=engine.initial_capital if engine else 100_000.0,
        orc_kappa=_ffg_orc_kappa,
        fiedler_zscore=_ffg_fiedler_z,
    )
    _ffg_result = _ffg.evaluate(_ffg_ctx)
    if not _ffg_result.all_pass:
        logger.info(
            "FFG blocked %s %s: %s",
            ticker, direction, "; ".join(_ffg_result.failing_gates)
        )
        self._last_ticker_decisions[ticker] = {
            "action": "SKIP_FFG",
            "failing_gates": _ffg_result.failing_gates,
        }
        continue
```

In `PaperTradingEngine.mark_to_market()`, after the ATR-based exit checks:

```python
# V132: Four-factor AND-gate break exit
if self._ffg is not None:
    _exit_ctx = GateContext(
        w_conv=0.0,   # not used for exit evaluation
        funding_rate=float(sym_signals.get("funding_rate_signal", 0.0)),
        closed_trades=list(self._closed_trades),
        open_positions=dict(self._positions),
        initial_capital=self.initial_capital,
        orc_kappa=_basket_orc_kappa,   # passed in from strategy cycle
        fiedler_zscore=_basket_fiedler_z,
    )
    _exit_result = self._ffg.evaluate_exit(_exit_ctx, pos)
    if _exit_result.any_broken:
        close = True
        reason = f"gate_break:{','.join(_exit_result.failing_gates)}"
```

### 6.4 Logging and Observability

Each gate evaluation should emit a structured log line at DEBUG level for normal operation and INFO level when a gate blocks:

```
FFG eval ETH LONG: g1=pass(div=0.12) g2=pass(disp=0.23) g3=pass(util=0.31,n=2) g4=pass(orc=0.04)
FFG blocked ETH LONG: disposition(coeff=-0.18<=0); pair_network(orc=-0.41<-0.3)
```

When `activation_tracing=True`, the `GateResult` should be serialized into the activation trace (alongside existing fields) so post-hoc attribution can correlate gate states with trade outcomes.

---

## 7. Backtest Isolation Strategy

### 7.1 Prerequisites

The four-factor gate **must not be enabled** until V131 (`early_loss_time_stop`) is confirmed working in Phase A benchmarks. Rationale:

- `disposition_gate` (Gate 2) measures whether exit discipline is working. If V131 is not active, `disposition_coefficient` will be −0.44 to −0.62 and Gate 2 will almost always fail, blocking all entries after 10 trades. This is technically correct but makes the system untestable.
- The gate system is designed to work *with* good exits, not to substitute for them.

**Confirmed prerequisite**: V131 `early_loss_time_stop=True` with `early_loss_cycles=3`, `early_loss_k_atr=0.3` must produce `disposition_coefficient > 0` in at least 2 out of 3 Phase A benchmark snapshots.

### 7.2 Phase A Protocol

Run the same three-snapshot protocol from `docs/research/retrospective-alpha-review.md`:

| Snapshot | Period | Key failure mode |
|----------|--------|-----------------|
| `crisis_2022h1` | H1 2022 | ORC-negative, HMM-slow, should produce very few trades |
| `trending_2023q4` | Q4 2023 | Healthy network, strong SMA signals, should trade actively |
| `recent_2026` | Recent | Mixed regime, baseline for live comparison |

Run `v132_four_factor` preset against all three. Gate pass rates should be logged per snapshot so we can measure gate correlation empirically.

### 7.3 Gate Calibration Sequence

1. **Run with `activation_tracing=True`** to capture gate states for every proposed entry.
2. **Check gate pass rates** per snapshot: if any gate passes < 20% of the time in trending regime, the threshold is too aggressive.
3. **Tune thresholds independently**: 
   - If `divergence_threshold=0.05` is blocking too many trending entries, try 0.03.
   - If `orc_threshold=-0.3` is blocking too many trending entries (ORC healthy in trend), this is a code bug — check that `_geometry_orc_kappa` is being correctly populated.
4. **Compare to V131 baseline**: the four-factor gate should improve precision (higher PnL per trade) at the cost of lower trade count. If total PnL drops significantly in trending regime, the gate is miscalibrated.

### 7.4 Pass/Fail Criteria for Promotion

The four-factor gate is promoted to the default config if:

1. `disposition_coefficient > 0.1` in all three snapshots (improvement from −0.44 baseline).
2. Trade count ≥ 10 in each snapshot (above hard gate floor).
3. PnL per trade ≥ 1.5× V131 baseline (higher precision trade selection).
4. Trending snapshot total PnL not degraded by more than 30% from V131 (cost of fewer trades is bounded).

---

## 8. Open Questions

### 8.1 Gate Correlation: Cross-Market and Pair-Network

Gates 1 (`cross_market_divergence`) and 4 (`pair_network`) both tighten during market stress:
- In crisis: ORC goes negative (Gate 4 blocks) AND funding rates spike extreme (Gate 1 tightens because `p_implied` is far from 0.5 in either direction, potentially matching `p_model` and blocking).
- In trending: ORC is positive (Gate 4 passes freely) AND funding is moderate (Gate 1 passes for moderate conviction).

**Risk**: the effective AND-gate pass rate in trending is higher than in crisis, which is the desired behavior. But in a sudden volatility shock (high_vol, not crisis), both gates may simultaneously fail, producing a *complete entry blackout* rather than a graceful reduction. This may make the system appear broken when what's happening is structurally correct.

**Proposed resolution**: compute gate correlation empirically across the three benchmark snapshots. If correlation > 0.6 between Gate 1 and Gate 4, consider an OR-fallback: "if either gate passes, allow entry with reduced size".

### 8.2 Cold-Start Problem for Disposition Gate

Gate 2 passes freely for the first 10 closed trades (`min_trades=10`). This means the first ~10 entries in any run have no disposition check. In a 200-cycle run that generates 20 total trades, this is 50% of all entries.

**Options**:
- Lower `min_trades` to 5 at the cost of high variance in the disposition estimate.
- Seed `closed_trades` from a prior run's trade log (carry disposition history across runs). This requires saving the last N trades to disk and loading them on startup — an additional stateful dependency.
- Accept the cold-start limitation for now. The other three gates still apply during cold-start.

### 8.3 Sigmoid Scale Calibration

The `sigmoid_scale=5.0` for Gate 1 maps:
- `w_conv = 0.10` → `p_model = sigmoid(0.5) = 0.62`
- `w_conv = 0.20` → `p_model = sigmoid(1.0) = 0.73`
- `w_conv = 0.30` → `p_model = sigmoid(1.5) = 0.82`

With `p_implied ≈ 0.50` (neutral funding) and `divergence_threshold = 0.05`, Gate 1 passes for `w_conv ≥ 0.10` — roughly matching the normal long_conviction_threshold. This means Gate 1 is approximately redundant with the existing conviction filter in the neutral-funding case.

Gate 1 adds genuine value primarily when funding is non-neutral: when the market is strongly long-biased (`p_implied = 0.70`), Gate 1 blocks our long entries unless `w_conv` is high enough for `p_model > 0.75` — preventing us from entering consensus longs. This is the correct behavior.

**Question**: what sigmoid scale produces the right sensitivity at the conviction thresholds used in practice? This requires empirical calibration using activation trace data from a V131 run to see the distribution of `w_conv` values at entry.

### 8.4 Exit Gate Sensitivity

Gate-break exits (particularly Gate 4, pair_network) fire on basket-level ORC state, not on the individual position's ticker. This means a single basket fragmentation event can trigger simultaneous exits on all open positions, regardless of whether individual positions are currently profitable.

This is a *feature* in genuine crisis (exit all before the wave), but a *bug* in noisy fragmentation events (momentary ORC dip below -0.3 causes a mass exit, then ORC recovers and we miss the continuation).

**Proposed solution**: for exit evaluation, require ORC < threshold for 2 consecutive cycles before triggering (a persistence filter on Gate 4 exit). Add `ffg_exit_orc_persistence: int = 2` to `VictoriaFeatures`.

### 8.5 Interaction with `postmortem_signal_filter` (V112)

`features.postmortem_signal_filter` (defined in `features.py`) zeros out `sma_long`, `sma_short`, `price`, `return_1d`, `sma_crossover`, `fear_greed_signal`, and `liquidation_proximity` — the same signals identified as dead weight in the retrospective. If this flag is enabled alongside `four_factor_and_gate`, the `w_conv` fed to Gate 1 will be based on a much smaller signal set, making `p_model` less sensitive to the removed signals.

**Recommended combination**: enable `postmortem_signal_filter=True` with `four_factor_and_gate=True` only after separately validating that `w_conv` still has enough variance with the filtered signal set to drive meaningful divergence in Gate 1. If `w_conv` collapses near zero with `postmortem_signal_filter`, Gate 1 becomes permanently permissive (which negates its purpose).

---

## Appendix A: File Reference Summary

| File | Relevant section | Purpose |
|------|-----------------|---------|
| `omega/nodes/victoria/strategy.py:1043` | `_passes_conviction_filters` | Existing entry gate — AND-gate runs after this |
| `omega/nodes/victoria/strategy.py:1261` | `_construct_portfolio` | Wire point for gate instantiation and per-ticker check |
| `omega/nodes/victoria/strategy.py:1440–1530` | Fiedler + ORC geometry block | Source of `_spectral_val`, `_geometry_orc_kappa` |
| `omega/nodes/victoria/exit_controller.py:264` | `aggregate_disposition` | Gate 2 computation |
| `omega/nodes/victoria/exit_controller.py:1` | `ExitConfig`, `ExitController` | Exit hierarchy Gate 3 sits within |
| `omega/nodes/victoria/features.py:39` | `VictoriaFeatures` | Add `four_factor_and_gate` flag here |
| `omega/nodes/victoria/signal_generation.py:689` | ORC computation | Source of `_geometry_orc_kappa` |
| `omega/nodes/victoria/signal_generation.py:814` | Funding rate signal injection | Source of `sig["funding_rate_signal"]` |
| `omega/core/paper_trading.py:102` | `initial_capital` | Gate 3 capital reference |
| `omega/core/paper_trading.py:111` | `_positions` | Gate 3 position count |
| `omega/core/paper_trading.py:117` | `_closed_trades` | Gate 2 trade history |
| `omega/core/paper_trading.py:148` | `_total_open_notional` | Gate 3 utilization helper |
| `docs/research/retrospective-alpha-review.md` | Phase A results | Evidence base for this design |

## Appendix B: Quick Reference — Gate Parameter Defaults

```python
FourFactorGate defaults:
  ffg_sigmoid_scale          = 5.0
  ffg_divergence_threshold   = 0.05   # 5 percentage points
  ffg_disposition_window     = 50     # trades
  ffg_disposition_min_trades = 10     # cold-start floor
  ffg_utilization_cap        = 0.50   # 50% of capital deployed
  ffg_max_positions          = 5      # concurrent open positions
  ffg_orc_threshold          = -0.3   # ORC mean curvature floor
  ffg_fiedler_floor          = 0.0    # Fiedler z-score floor (fallback)
```
