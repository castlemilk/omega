# Adaptive Engine V2 — From Hard Gates to Continuous Confidence Surfaces

**Status:** Design · April 2026  
**Author:** Omega Code Quality Bot  
**Trigger event:** V141 Phase A — changing `bear_prob_long_block_threshold` from 0.35 to 0.55 caused a $30,000 PnL swing across Phase A snapshots. A production trading system where a single floating-point threshold controls five-figure outcomes is not a system — it is a parameter search problem with an unstable loss surface.

---

## Executive Summary

The current Victoria strategy engine is a sequential pipeline of **47 binary gate exits** operating on **16 distinct hard-coded threshold values**. Each gate is a discontinuous step function: a signal value of 0.349 passes, 0.351 is blocked. This architecture is fundamentally fragile — not because the thresholds are wrong, but because *any* threshold-based system applied to continuous market signals produces an optimization landscape full of sharp ridges and flat plateaus.

This document derives why threshold-based systems are fragile from first principles, specifies a replacement architecture based on continuous confidence surfaces, and defines the robustness metric that validates the replacement is working. It is not a patch — it is a rethink of the computation graph between market signals and position sizes.

The test: after Phase 1, vary the primary entry surface center from 0.30 to 0.60 in steps of 0.05. If the PnL sensitivity drops from the observed $30,000 to below $5,000, the architecture is correct. That test — not backtest PnL alone — is the success criterion.

---

## Part I: Failure Analysis

### 1.1 The Mathematical Structure of Hard Gates

A binary gate applied to a continuous signal `x` has the form:

```
g(x; θ) = 1   if x ≥ θ
           0   otherwise
```

The PnL contribution from trade `i`, given gate parameter `θ`, is:

```
pnl_contribution(i, θ) = pnl_i × g(x_i; θ)
```

The total backtest PnL is:

```
PnL(θ) = Σᵢ pnl_i × g(x_i; θ)
```

This is a **right-continuous step function** of `θ`. It is constant between consecutive values of `{x_i}`, and has a jump discontinuity of magnitude `|pnl_i|` at each `θ = x_i`. The function is not differentiable anywhere the gate changes state.

**Consequence 1: Optimization on this surface fails.** Gradient descent requires a well-defined gradient. On a step function, the gradient is zero almost everywhere and undefined at discontinuities. Any parameter search (grid search, Bayesian optimization, evolutionary algorithms) is operating on a landscape where small perturbations in θ produce zero or infinite gradient — the local information provides no signal about which direction improves PnL.

**Consequence 2: Parameter sensitivity is bounded below by individual trade PnL.** For a perturbation Δθ around the optimized θ*, the set of trades that change state is:

```
S(θ*, Δθ) = {i : x_i ∈ [θ*, θ* + Δθ]}
```

The resulting PnL change is:

```
ΔPnL(Δθ) = Σ_{i ∈ S} pnl_i
```

This sum has no reason to be small. If the system has N trades with signals clustered near the threshold — which is typical in any real system, since the threshold was set to be near the decision boundary — the PnL swing is `O(N × E[|pnl|])`.

**Quantifying the observed V141 fragility:**

In the V141 experiment, the threshold shift was Δθ = 0.20 (from 0.35 to 0.55). The observed PnL swing across the trend and recent snapshots was approximately $30,000. Working backwards:

```
ΔPnL ≈ $30,000
Δθ = 0.20 (bear_prob units)
```

Estimating N_boundary (trades with bear_prob ∈ [0.35, 0.55]):
- In a 500-cycle run with ~25% trade frequency, approximately 125 cycles generate trade proposals
- In a trend/bull snapshot, bear_prob will be distributed across [0.10, 0.65]
- Approximately 25-35% of proposals will have bear_prob in [0.35, 0.55]
- With ~120 total trades per snapshot, N_boundary ≈ 30-40 trades

Average absolute PnL per affected trade:
```
|avg_pnl| ≈ $30,000 / 35 ≈ $857/trade
```

This matches empirical trade data (top losers in V141: $1,100–$3,200; average loss per trade: ~$900).

The key insight: **the system has approximately 30-40 trades sitting right at the decision boundary**. These trades are classified as either "definitely enter" or "definitely don't enter" based on whether bear_prob crosses a single floating-point threshold. Moving that threshold by 0.20 flips all of them simultaneously. This is the cliff.

### 1.2 The Current System: A Catalogue of Hard Gates

`strategy.py` contains **47 `continue` statements** (binary exits), operating on **16 distinct threshold values**, implementing **83 distinct hard-gate patterns**. Every one of these is a cliff. Below is a taxonomy by function:

#### Entry Gates (long path)

| Gate | Code | Threshold | Effect |
|---|---|---|---|
| Composite floor | `composite <= _signal_threshold` | 0.0 (adjustable) | No entry if composite ≤ threshold |
| Bear prob long block | `bear_prob >= bear_prob_long_block_threshold` | 0.55 (V142) | No long if bear_prob too high |
| Crisis long block | `_regime_consolidated == "crisis"` | label-based | No long in crisis label |
| High vol entry block | `_is_high_vol` | label-based | No entry in high_vol |
| Abs min conviction | `abs(w_conv) < _abs_min_conviction` | 0.02–0.06 | No entry if weighted conviction too low |
| Crisis gate | `bear_prob >= 0.65` | 0.65 | Binary crisis classification |
| Crisis gate (HMM) | `bear_prob >= 0.45 AND label=="crisis"` | 0.45 | Secondary crisis classifier |
| Bull gate | `bull_prob >= 0.55` | 0.55 | Binary bull classification |

#### Entry Gates (short path)

| Gate | Code | Threshold | Effect |
|---|---|---|---|
| Short conviction | `composite < _short_conviction_threshold` | 0.04–0.10 | No short if composite too low |
| High vol short block | `high_vol_short_block AND _is_high_vol` | label-based | No short in high_vol |
| Crisis permissive scale | `composite < threshold × scale` | 0.5–0.4× | Scaled short threshold in crisis |
| LLM veto (long) | `llm_mod < llm_crisis_long_veto` | 0.50 | Hard veto on LLM modifier |
| LLM veto (short) | `llm_mod < llm_crisis_short_veto` | 0.20 | Hard veto on LLM modifier |

#### Regime Classification Gates

| Gate | Code | Threshold | Effect |
|---|---|---|---|
| `is_crisis` | `bear_prob >= 0.65` | 0.65 | Primary crisis trigger |
| `is_crisis` (label) | `bear_prob >= 0.45` | 0.45 | Label-confirmed crisis |
| `is_bull` | `bull_prob >= 0.55` | 0.55 | Bull classification |
| `_is_high_vol` | `regime == "high_vol"` | label | High-vol classification |
| Hysteresis gate | `bear_prob > 0.50` | 0.50 | Hysteresis lock condition (V142) |

#### Exit Gates (exit_controller.py)

| Gate | Code | Threshold | Effect |
|---|---|---|---|
| Hard MAE stop | `unrealized <= -(mae_stop_k × ATR)` | 0.8× ATR | Immediate close |
| MFE trailing stop | `mfe >= mfe_trail_k × ATR` | 1.0× ATR | Trailing activation |
| Retracement cap | `unrealized < mfe × (1 - cap)` | 0.25 | Trail fires |
| Early loss stop | `unrealized <= -(early_loss_k × ATR)` | 0.3× ATR | Early cut |
| Zero-MFE exit | `mfe <= 0 AND age >= N` | age 2 | Time-based block |

**Total hard decision boundaries in the entry-to-exit path: approximately 22.** Each one is a cliff. Each one interacts with all others.

### 1.3 Interaction Effects: The Maze of Sharp Ridges

Two gates near their boundaries simultaneously create a two-dimensional discontinuity. Consider the bear_prob gate (θ_bear) and the conviction threshold (θ_conv):

The PnL surface in the (θ_bear, θ_conv) plane has ridges at every (x_bear_i, x_conv_j) coordinate pair. For a system with N=100 trades:
- 100 ridges along the θ_bear axis
- 100 ridges along the θ_conv axis
- A grid of 10,000 intersection points where gradients are undefined

The parameter space is not a smooth bowl — it is a checkerboard of sharp ridges with flat plateaus between them. **Gradient-based optimization is impossible. Grid search finds a local optimum in the space between ridges but provides no information about the true optimum.** Every threshold value we've chosen (0.35, 0.45, 0.50, 0.55, 0.65) is a guess in a discontinuous space.

### 1.4 Why Each Fix Breaks Something Else

The V-series pattern is:

```
V139: crisis loses. Forensics: bear_prob gate at 0.55 misses bear-market longs.
V141: lower gate to 0.35. Crisis flips positive (+$896). Trend regresses -$30k.
V142: raise gate to 0.55. Trend recovers (hopefully). Crisis may regress.
```

This is not a tuning problem — it is an architectural constraint. The bear_prob gate at any fixed value θ will be simultaneously:
- Too permissive for crisis-regime longs (where bear_prob can be 0.35-0.55 during "normal" oscillations)
- Too restrictive for trend-regime longs (where bear_prob occasionally spikes to 0.40-0.50 during volatility)

No single value of θ solves both simultaneously. The system is overdetermined: it has one degree of freedom (θ) and two conflicting requirements (crisis-safe, trend-permissive). The continuous surface architecture introduces additional degrees of freedom — specifically, the temperature T — that allows the surface to simultaneously be decisive at the extremes and uncertain at the boundary.

---

## Part II: Continuous Confidence Surfaces

### 2.1 Mathematical Formulation

Replace every binary gate `g(x; θ)` with a **sigmoid confidence function**:

```
c(x; μ, T) = σ((x - μ) / T) = 1 / (1 + exp(-(x - μ) / T))
```

Where:
- `μ` (center) is the midpoint of the transition, analogous to the old threshold θ
- `T` (temperature) controls the sharpness of the transition:
  - `T → 0`: approaches hard gate (high sensitivity)
  - `T → ∞`: approaches constant 0.5 (complete uncertainty)
  - `T = 0.10`: 80% of the transition from 0 to 1 occurs in a ±2T = ±0.20 window

For the **long bear-probability surface** (high confidence when bear_prob is LOW):

```
c_long(bear_prob; μ_bear, T_bear) = σ(-(bear_prob - μ_bear) / T_bear)
                                  = 1 / (1 + exp((bear_prob - μ_bear) / T_bear))
```

Evaluation at key points (μ=0.45, T=0.10):

| bear_prob | Confidence | Position size |
|---|---|---|
| 0.10 | 0.98 | 98% of base |
| 0.25 | 0.91 | 91% of base |
| 0.35 | 0.73 | 73% of base |
| 0.45 | 0.50 | 50% of base |
| 0.55 | 0.27 | 27% of base |
| 0.65 | 0.12 | 12% of base |
| 0.80 | 0.05 | 5% of base |

This is not "blocking longs in crisis" — it is **reducing long size proportionally to bear probability**. A trade that was arbitrarily blocked at bear_prob=0.36 now enters at 64% of full size. A trade that was fully admitted at bear_prob=0.34 now enters at 67% of full size. The discontinuity is eliminated.

### 2.2 Position Sizing: The Multiplicative Confidence Model

All confidence factors multiply to produce final position size:

```
size = base_size × c_bear(bear_prob) × c_composite(composite) × c_regime(regime, bear_prob) × c_llm(llm_mod)
```

Where each factor `c ∈ [0, 1]`. Properties:
- **Conjunction**: a position must have reasonable confidence on ALL dimensions to achieve full size. Poor composite AND poor regime = very small position.
- **No cliffs**: each factor varies smoothly. No single dimension can cause a discontinuity.
- **Minimum size floor**: when `size < $500` (minimum notional), the trade is skipped. This is the effective "block" — but it is reached gracefully as multiple confidence factors approach zero, not by a single threshold flip.
- **Interpretability**: each factor can be logged independently, providing a continuous "decision trace" rather than pass/fail.

**The multiplicative model vs additive alternatives:** An additive model `c = c_bear + c_composite + c_regime` would allow a trade with excellent bear_prob but poor composite to be entered at full size. Multiplication enforces that EACH dimension must contribute — consistent with the AND-gate logic that was implicit in the hard-gate system, but without the cliff effects.

### 2.3 Confidence Surface Definitions

**Bear probability surface (long direction):**
```python
c_bear_long(bp; μ=0.45, T=0.10) = σ(-(bp - 0.45) / 0.10)
```

**Bear probability surface (short direction):** shorts benefit from high bear_prob:
```python
c_bear_short(bp; μ=0.40, T=0.10) = σ((bp - 0.40) / 0.10)
```

**Composite conviction surface (long):**
```python
c_composite_long(comp; μ=0.08, T=0.04) = σ((comp - 0.08) / 0.04)
```
Center at 0.08 = just above the historical mean for entered long trades. T=0.04 is narrower (conviction is a more reliable discriminator than bear_prob).

**Composite conviction surface (short):** composites are negative for shorts, so:
```python
c_composite_short(comp; μ=-0.05, T=0.04) = σ((-comp - 0.05) / 0.04)
```

**Regime surface (long):** continuous function of both regime label and bear_prob:
```python
c_regime_long(regime, bp) = regime_base[regime] × σ(-(bp - 0.50) / 0.15)
```
Where `regime_base = {crisis: 0.30, high_vol: 0.20, normal: 0.95, bull: 1.00}`.

The sigmoid on bear_prob within the regime surface provides the second dimension of smoothness: even within the "normal" regime, longs are sized down when bear_prob is elevated.

**Regime surface (short):**
```python
c_regime_short(regime, bp) = regime_base_short[regime] × σ((bp - 0.35) / 0.15)
```
Where `regime_base_short = {crisis: 0.90, high_vol: 0.40, normal: 0.70, bull: 0.25}`.

**LLM modifier surface:** the LLM already returns a continuous modifier in [0, 1]. Replace the hard veto (`if mod < 0.30: block`) with a direct inclusion in the product:
```python
c_llm(llm_mod) = llm_mod  # direct, no threshold
```
A modifier of 0.28 now contributes 0.28 to the product instead of causing a complete block.

### 2.4 Sensitivity Analysis: The Core Claim

**Hard gate sensitivity:** for threshold shift Δθ = 0.20 and N=35 boundary trades with average absolute PnL $857:
```
ΔPnL_hard ≈ Σ_{i ∈ boundary} pnl_i ≈ $30,000
```

**Sigmoid sensitivity:** the change in confidence for a boundary trade when center shifts by Δμ = 0.20 is:
```
Δc_i = c(x_i; μ + Δμ, T) - c(x_i; μ, T)
```

For a trade at x_i = μ (the midpoint, worst case): c starts at 0.50, ends at σ(-0.20/0.10) = σ(-2) ≈ 0.12. Change = -0.38.

For a trade at x_i = μ + 0.10 (one temperature unit above center): c starts at σ(-1) ≈ 0.27, ends at σ(-3) ≈ 0.05. Change = -0.22.

For a trade at x_i = μ - 0.10 (one temperature unit below center): c starts at σ(1) ≈ 0.73, ends at σ(-1) ≈ 0.27. Change = -0.46.

Average |Δc| across boundary trades ≈ 0.35 (roughly, for T=0.10, Δμ=0.20).

But with the hard gate, every boundary trade that was admitted had c=1.0, and after the shift has c=0.0. Average |Δc|=1.0. The sigmoid reduces this by a factor of approximately 1.0/0.35 ≈ 2.9×.

Furthermore, the position sizes in the sigmoid system are already reduced for boundary trades (average c ≈ 0.5 for trades near the center). So the DOLLAR change is:

```
ΔPnL_sigmoid ≈ Σ_{i ∈ boundary} pnl_i × Δc_i
             ≈ N × E[pnl_i] × E[Δc_i]
             ≈ 35 × $857 × 0.35
             ≈ $10,500
```

With temperature T=0.15 (wider transition):
- E[Δc_i] for Δμ=0.20 ≈ 0.25 (less sharp transition)
- ΔPnL_sigmoid ≈ 35 × $857 × 0.25 ≈ $7,500

**Target T for <$5,000 sensitivity: T ≈ 0.20.**

However, there is a second-order effect that compounds the improvement: in the multiplicative model, boundary trades are affected by multiple confidence factors simultaneously. When c_bear changes by 0.35, but c_composite is also 0.60 (not at full confidence), the actual dollar impact is:

```
ΔPnL_per_trade = pnl_i × (c_composite × c_regime × c_llm) × Δc_bear
               = $857 × 0.60 × 0.95 × 0.90 × 0.35
               ≈ $857 × 0.51 × 0.35 ≈ $153
```

Aggregated: 35 × $153 ≈ **$5,350** — already near target with T=0.10.

This is the mathematical argument for why the multiplicative confidence model achieves the robustness target: the product of multiple imperfect confidences naturally reduces the sensitivity of any single surface.

### 2.5 Temperature as the Key Hyperparameter

Temperature `T` controls the fundamental tradeoff between decisiveness and robustness:

```
Low T (→ 0):  Approaches hard gate. Maximum decisiveness. Maximum sensitivity.
High T (→ ∞): Approaches constant 0.5. Zero decisiveness. Zero sensitivity.
T = 0.05:     Very sharp. 95% of transition in ±0.10 window. Near-hard-gate.
T = 0.10:     Moderate. 95% of transition in ±0.20 window. Recommended start.
T = 0.20:     Smooth. 95% of transition in ±0.40 window. Robust but less precise.
T = 0.50:     Very smooth. Barely distinguishes high from low bear_prob.
```

The key insight: T should not be a fixed hyperparameter tuned in advance. It should **adapt based on system performance**. When the system is well-calibrated (regime PF > 1.5), lower T for more decisiveness. When miscalibrated (regime PF < 0.8), raise T for more robustness.

This is the Meta-Learning Layer (Part III).

---

## Part III: Meta-Learning Layer — Self-Adjusting Surfaces

### 3.1 Motivation

Static confidence surfaces are better than hard gates but still have a fixed geometry. The right T for a trending market in Q4-2023 may be different from the right T in H1-2022 bear market. The Meta-Learning Layer observes the system's own recent performance and adjusts the surface shape in real-time.

This is distinct from the existing reinforcement EMA mechanism:
- **Reinforcement EMA** (existing): adjusts signal *weights* (IC multipliers). Modifies WHAT signals contribute to the composite.
- **Meta-Learning Layer** (new): adjusts surface *shape* (center μ and temperature T). Modifies HOW composite translates to position size.

They are orthogonal and should compose: the EMA ensures the right signals are weighted correctly; the meta-learner ensures the signal stack's output is translated to position size with appropriate confidence.

### 3.2 Meta-Learner Architecture

The meta-learner maintains a rolling buffer of recent trades, partitioned by regime:

```python
@dataclass
class RegimePerformanceBuffer:
    regime: str
    trades: deque[dict]  # max 20 trades
    
    @property
    def rolling_pf(self) -> float:
        gross_profit = sum(t['pnl'] for t in self.trades if t['pnl'] > 0)
        gross_loss   = abs(sum(t['pnl'] for t in self.trades if t['pnl'] < 0))
        return gross_profit / max(gross_loss, 1.0)
    
    @property
    def rolling_wr(self) -> float:
        if not self.trades: return 0.5
        wins = sum(1 for t in self.trades if t['pnl'] > 0)
        return wins / len(self.trades)
    
    @property
    def signal_ic(self) -> dict[str, float]:
        # rolling IC per signal (direction alignment with PnL sign)
        ...
```

**Adaptation rules:**

| Condition | Adjustment | Rationale |
|---|---|---|
| `rolling_pf[regime] > 1.5` | Decrease T by 0.01 (sharpen surface) | System is well-calibrated; be more decisive |
| `rolling_pf[regime] < 0.8` | Increase T by 0.02 (soften surface) | System is miscalibrated; be more cautious |
| `rolling_pf[regime] ∈ [0.8, 1.5]` | No change | Satisfactory performance; maintain current shape |
| `rolling_wr < 0.25` | Shift μ by +0.02 (raise entry bar) | Systematic miss; entry criteria too loose |
| `rolling_wr > 0.65` | Shift μ by -0.01 (lower entry bar) | May be over-filtering; too few trades |
| Regime transitions > 10/50 cycles | Increase T by 0.03 (soften for instability) | Regime detector uncertain; reduce conviction |

**Bounds:**
```
T ∈ [0.05, 0.30]   — prevents collapse to hard gate or total diffusion
μ ∈ [μ₀ - 0.15, μ₀ + 0.15]   — prevents drift far from calibrated baseline
```

### 3.3 Relationship to Existing EMA Reinforcement

The existing reinforcement mechanism (in `trade_reinforcement.py`) maintains a semantic memory database and adjusts per-signal EMA weights. Its adaptation rate is one update per `improve_call` cycle (approximately every 50-100 cycles).

The meta-learner adapts at the trade level: every closed trade updates the performance buffer and may trigger a surface adjustment. This is faster (responds within 20 trades) and operates at a different abstraction level.

**Composition:** both mechanisms update in sequence:
1. Closed trade → update EMA (reinforcement): signal weights → `composite` changes
2. Closed trade → update performance buffer (meta-learner): T and μ → surface shape changes
3. Next entry proposal: `composite` is evaluated against the updated surface with updated T and μ

The two mechanisms cannot interfere because they operate on different variables: EMA adjusts signal weights (upstream of composite computation); meta-learner adjusts surface parameters (downstream of composite, applied to sizing).

### 3.4 Convergence Analysis

**When does the meta-learner converge?** Under a stationary regime (consistent market conditions), the rolling PF converges to the true regime PF. If true PF > 1.5, T decreases until hitting the floor T=0.05. If true PF < 0.8, T increases until hitting the ceiling T=0.30. In both cases, the meta-learner converges to a boundary.

**Can the meta-learner oscillate?** In a regime with true PF ≈ 1.0-1.5, the meta-learner may oscillate. Rolling PF crosses 1.5 → decrease T → sharper surface → more aggressive entries → PF temporarily drops below 0.8 → increase T → etc. This is a hunting oscillation.

**Dampening mechanisms:**
1. **Minimum adjustment interval**: apply adjustments at most once per 10 trades. Prevents rapid oscillation.
2. **Exponential moving adjustment**: instead of discrete step changes, apply `T ← T × (1 + δ_T_relative)` where `δ_T_relative` is small (±5%). Dampens oscillation amplitude.
3. **Conservative dead band**: no adjustment for `rolling_pf ∈ [0.90, 1.40]`. Only adjust on clear signals.

---

## Part IV: LLM as Meta-Controller

### 4.1 Current Design: LLM as Gate

The current LLM integration has the model produce a `conviction_modifier ∈ [0, 1]` for each proposed trade. Trades are vetoed if the modifier falls below a threshold (0.30 normally; 0.50 in crisis mode). The LLM is called every 10 cycles.

**Problems with this design:**

1. **The LLM veto is itself a hard gate** — creating the same cliff effect at modifier=0.30 that we're trying to eliminate from the signal pipeline.

2. **Per-trade context is shallow.** The LLM receives the current cycle's market data and one proposed trade. It doesn't see: what the system's rolling PF is, whether this is the 5th losing ADAUSDT long in the current regime, or whether the crisis signal was wrong 80% of the time in the past 50 cycles.

3. **Cost/impact mismatch.** At 10-cycle cadence with 25% trade frequency, approximately 5-8 trades are reviewed per run. Each call costs $0.01-0.03. A call that modifies a $1,000 trade by 0.10 in the modifier changes position size by $100. The information density is low.

4. **No feedback loop.** The LLM doesn't know if its modifiers are helping. A modifier of 0.40 that caused a veto on what turned out to be the best trade of the run gets no correction signal.

### 4.2 Proposed Design: LLM as Strategic Meta-Controller

**Cadence:** every 50 cycles (down from 10). This covers roughly 12-15 trades.

**Input:** full system state snapshot:
```json
{
  "cycles": 50,
  "regime_distribution": {"crisis": 0.45, "normal": 0.40, "high_vol": 0.15},
  "regime_accuracy": 0.68,
  "rolling_pf": {"crisis": 1.42, "normal": 0.71, "high_vol": 0.0},
  "rolling_wr": {"crisis": 0.50, "normal": 0.22, "high_vol": 0.00},
  "signal_ic_drift": {
    "ollivier_ricci_signal": +0.08,
    "fear_greed_signal": -0.15,
    "sma_crossover": -0.12
  },
  "recent_trades": [
    {"cycle": 45, "symbol": "ADAUSDT", "side": "long", "regime": "normal", "pnl": -890, "regime_label_at_entry": "normal", "bear_prob_at_entry": 0.42},
    ...
  ],
  "surface_params": {"T_bear_long": 0.12, "mu_bear_long": 0.45, ...},
  "macro_context": "BTC -55% YTD; DXY +15%; Fed funds 5.25%; credit spreads widening"
}
```

**Output:** surface parameter adjustments and strategic context:
```json
{
  "surface_adjustments": {
    "bear_long": {"mu_delta": -0.05, "T_delta": +0.02},
    "composite_long": {"mu_delta": 0.0, "T_delta": 0.0},
    "regime_long_normal_base": 0.70
  },
  "signal_emphasis": {
    "ollivier_ricci_signal": 1.5,
    "fear_greed_signal": 0.2,
    "sma_crossover": 0.3
  },
  "strategic_context": "Normal-regime longs are losing at 22% WR. Bear prob averaging 0.42 in 'normal' — system is trading longs in a bear-biased environment. Recommend tightening long surface center by 0.05 (from 0.45 to 0.40) to filter weaker long setups.",
  "next_call_cycles": 50
}
```

**What changes:** the LLM adjusts surface GEOMETRY (μ, T, regime base weights) and SIGNAL EMPHASIS (applied as multipliers to signal contributions before composite computation). It does not approve or reject individual trades.

### 4.3 Why This Is Better

**Cost:** $0.05 per run vs $0.50 per run (10× cheaper). The LLM makes one strategic call vs 5-8 tactical calls per run.

**Impact:** adjusting μ_bear_long from 0.45 to 0.40 shifts the sizing of ALL subsequent longs in the normal regime. If there are 15 longs in the next 50 cycles, this change affects all 15. A single trade veto affects exactly one trade.

**Context depth:** the LLM receives 50-cycle performance history, signal IC drift, and regime accuracy. It can detect patterns that the meta-learner's simple rules miss (e.g., "fear_greed IC has drifted -0.15 — the signal is anti-predictive right now").

**Composability:** the LLM's adjustments are bounded by the same limits as the meta-learner. Adjustments are PRIORS that the meta-learner then updates with realized data. The system doesn't blindly follow the LLM — it treats the LLM's recommendation as initialization and adjusts based on what actually happens.

**Correction loop (partial):** the LLM can observe whether its previous recommendation improved PF. If the prior adjustment tightened longs and PF improved, the current call can confirm and deepen. If PF didn't improve, it can recommend reverting. This is a crude feedback loop — better than none.

### 4.4 Composition with Meta-Learner

```
LLM call (every 50 cycles) → provides Δμ_llm, ΔT_llm for each surface
Meta-learner (every trade)  → provides Δμ_ml, ΔT_ml based on rolling PF

Final μ = μ₀ + Δμ_llm + α × Δμ_ml   (α ∈ [0.3, 0.7], meta-learner influence)
Final T = clamp(T₀ + ΔT_llm + α × ΔT_ml, T_min, T_max)
```

The LLM provides a strategic PRIOR (longer horizon, macro-informed). The meta-learner provides DATA-DRIVEN correction (shorter horizon, realized performance). Final parameters are a weighted blend.

When the two conflict — LLM says tighten (lower T), meta-learner says soften (raise T) — the weighted blend produces a moderate adjustment. The system doesn't have to choose between them.

---

## Part V: Ensemble Signal Voting

### 5.1 The Problem with Weighted Sum

The current composite:

```
composite = Σᵢ (signal_i × ic_weight_i)
```

Properties that create fragility:
- **Cancellation**: a strongly bearish SMA signal (−0.30) can cancel a strongly bullish ORC signal (+0.28), producing composite ≈ 0. The system sits out a trade where two out of five signals strongly disagree but three signals are mildly bullish.
- **Outlier domination**: a single high-weight signal with anomalous value can push the composite past the threshold even if all other signals disagree. This happened in V139 crisis: fear_greed_signal averaged +1.0 (extreme fear = buy signal, coded contrariwise) and pushed composites toward longs in a bear market.
- **Weight sensitivity**: the composite is directly proportional to IC weights. A weight change of 0.1 on a signal with value 0.5 changes the composite by 0.05 — potentially enough to cross the conviction threshold.

### 5.2 Ensemble Voting: Preserving Uncertainty

Replace the weighted sum with a structured vote:

```python
@dataclass
class SignalVote:
    direction: Literal["long", "short", "abstain"]
    confidence: float  # [0, 1] — how strongly does the signal indicate this direction?
    signal_name: str
    raw_value: float   # for logging
```

**Vote computation from signal value:**
```python
def signal_to_vote(name: str, value: float, ic: float) -> SignalVote:
    threshold = 0.05  # minimum signal strength to vote directionally
    if abs(value) < threshold or abs(ic) < 0.1:
        return SignalVote("abstain", confidence=0.5, ...)
    direction = "long" if value > 0 else "short"
    # confidence scales with both signal magnitude and IC reliability
    confidence = min(abs(value) / 0.30, 1.0) * min(abs(ic) / 0.50, 1.0)
    return SignalVote(direction, confidence, name, value)
```

**Aggregation:**
```python
votes = [signal_to_vote(n, v, ic[n]) for n, v in signals.items()]

long_score  = sum(v.confidence for v in votes if v.direction == "long")
short_score = sum(v.confidence for v in votes if v.direction == "short")
total_score = long_score + short_score + sum(v.confidence for v in votes if v.direction == "abstain")

# Direction: majority by weighted vote
direction = "long" if long_score > short_score else "short"
# Agreement ratio: how decisive is the vote?
agreement = max(long_score, short_score) / max(total_score, 1.0)
# Maximum signal confidence
max_confidence = max(v.confidence for v in votes if v.direction == direction)

# Final conviction: combination of agreement and maximum signal strength
conviction = agreement * (0.7 + 0.3 × max_confidence)
```

**Advantages over weighted sum:**
1. **Outlier robustness:** the fear_greed signal voting wrong direction gets one wrong vote, not an additive push that swamps all other signals.
2. **Uncertainty preservation:** a 60/40 split produces agreement=0.60 and conviction≈0.42 (half size). A weighted sum with two canceling signals produces composite≈0 and conviction=0 (no entry). The ensemble correctly sizes down rather than sitting out.
3. **Anti-predictive signal handling:** in crisis regime, the known anti-predictive signals (sma_crossover, fear_greed) can be forced to "abstain" in that regime rather than voting against the rest. The meta-controller specifies this: `{"regime": "crisis", "signal_emphasis": {"fear_greed_signal": 0.0}}` → votes "abstain".
4. **Interpretability:** the vote breakdown (5 long, 2 short, 1 abstain) is human-readable and debuggable. A composite of 0.073 is not.

### 5.3 Composability with Confidence Surfaces

The ensemble conviction `c_votes` becomes an additional factor in the multiplicative confidence model:

```
size = base_size × c_bear × c_regime × c_votes × c_llm
```

Where `c_votes = f(agreement, max_confidence)` — the ensemble's aggregate signal quality. This composes naturally: a unanimous vote + good bear_prob + favorable regime → near-full size. A split vote → half size regardless of other factors.

---

## Part VI: Bayesian Regime Detection

### 6.1 Current Regime Classification: A Hard Gate Tree

The current regime classification is effectively:

```
if bear_prob >= 0.65:                          → crisis
elif regime_label == "crisis" and bear_prob >= 0.45:  → crisis
elif bear_prob < 0.0 and regime_hmm == "bear": → crisis (fallback)
elif bull_prob >= 0.55:                        → bull
elif regime_label == "high_vol":              → high_vol
else:                                         → normal
```

This is a decision tree with five hard thresholds (0.65, 0.45, 0.55, plus two label-based cutoffs). The V141 hysteresis adds a sixth threshold (0.50 for lock engagement). The regime label drives approximately half of all entry/exit decisions.

**Problems:**
- Regime classification is binary (crisis or not), but markets exist on a spectrum
- A bear_prob of 0.64 is "normal" and a bear_prob of 0.66 is "crisis" — a $30k difference
- The Wasserstein regime detector's raw output (bear_prob) is already a continuous probability — we immediately discretize it and throw away the uncertainty information

### 6.2 Bayesian Posterior over Regimes

Define a posterior `P(regime | signals, LLM)` over regimes R = {crisis, high_vol, normal, bull}:

```
P(regime | signals, LLM) ∝ P(signals | regime) × P(regime | LLM)
```

**Prior: LLM macro assessment (updated every 50 cycles)**

The LLM provides a macro-informed prior over regime states:
```python
# LLM returns in structured output:
prior = {"crisis": 0.25, "high_vol": 0.15, "normal": 0.50, "bull": 0.10}
```

This prior encodes macro context (Fed policy, crypto market structure, cross-asset correlations) that the quant signals cannot observe directly.

**Likelihood: P(signals | regime)**

From historical calibration (using the 3 Phase A snapshots as training data):

```
P(bear_prob=0.55 | crisis)    ≈ 0.35   (common in crisis)
P(bear_prob=0.55 | normal)    ≈ 0.08   (rare in normal)
P(bear_prob=0.55 | high_vol)  ≈ 0.15   (moderate in high_vol)
P(bear_prob=0.55 | bull)      ≈ 0.02   (very rare in bull)
```

Similarly for ORC (Ollivier-Ricci curvature), SMA alignment, and fear/greed index. The joint likelihood assumes conditional independence (reasonable given signal diversity):

```
P(signals | regime) = Π_s P(signal_s | regime)
```

**Posterior:**
```
P(crisis | signals, LLM) ∝ P(signals | crisis) × P(crisis | LLM)
```

**Entry sizing:** proportional to the posterior probability of the favorable regime:
```python
regime_size_multiplier = (
    P_posterior["crisis"] × regime_mult["crisis"][side] +
    P_posterior["high_vol"] × regime_mult["high_vol"][side] +
    P_posterior["normal"] × regime_mult["normal"][side] +
    P_posterior["bull"] × regime_mult["bull"][side]
)
```

Where `regime_mult[regime][side]` is the size multiplier for each regime/direction combination (derived from historical regime PF data).

This subsumes the regime gate, the bear_prob_long_block, and the LLM regime override into a **single coherent probabilistic framework**. No hard cutoffs. The system is proportionally confident in each regime and sizes accordingly.

### 6.3 Calibration and Practical Approximation

Full Bayesian inference requires calibrating `P(signal | regime)` distributions from historical data. Given our Phase A snapshots (3 distinct regimes), this calibration is tractable.

For Phase 5 implementation, a practical approximation uses a mixture model:

```python
# Approximate posterior using bear_prob directly as crisis probability
P_crisis_approx = sigmoid((bear_prob - 0.45) / 0.10)
P_bull_approx   = sigmoid((bull_prob - 0.45) / 0.10) × (1 - P_crisis_approx)
P_high_vol_approx = P(label=="high_vol") × 0.8  # label is reliable for high_vol
P_normal_approx   = 1 - P_crisis_approx - P_bull_approx - P_high_vol_approx
```

This approximation can be implemented immediately as part of Phase 1, providing a continuous posterior without full Bayesian inference. It effectively IS the confidence surface — but the Bayesian framing clarifies what we're doing and provides a path to full calibration.

---

## Part VII: Implementation Roadmap

### Phase 1 — V143: Continuous Confidence Surfaces

**Goal:** eliminate all hard entry gates. Replace with continuous sigmoid surfaces. Validate with parameter sensitivity test.

**New module:** `omega/nodes/victoria/confidence_surface.py`

Components:
- `SurfaceParams` dataclass: `center`, `temperature` per surface type
- `SurfaceConfig` dataclass: all surfaces for a strategy configuration
- `ConfidenceSurface` class: stateless evaluator, `long_confidence()`, `short_confidence()`
- Default calibration derived from V139 trade data (Phase A snapshots)

**Changes to strategy.py:**
- Feature flag: `continuous_surfaces: bool = False`
- When enabled: replace all entry `continue` statements in the long path with confidence factor computation
- Final size = `base_size × product(all_confidence_factors)`
- Minimum position floor ($500) as the effective block
- All confidence factors logged to decision trace

**Parameter sensitivity test:** 7 backtests with sigmoid center varying 0.30–0.60 on crisis snapshot. Success: PnL range < $5,000.

**Timeline:** 1-2 days implementation. Runs alongside V142 Phase A.

### Phase 2 — V144: Meta-Learning Layer

**Goal:** surfaces self-adjust based on realized regime performance.

**New module:** `omega/nodes/victoria/surface_meta_learner.py`

Components:
- `RegimePerformanceBuffer`: rolling 20-trade window per regime
- `MetaLearner`: computes T/μ adjustments from rolling PF
- Integration: called on each `trade_closed` event in `paper_trading.py`

**Changes to strategy.py:**
- MetaLearner instance created in `__init__`, updated on each cycle
- Surface parameters read from MetaLearner at trade evaluation time

**Success:** crisis PF improves within a 500-cycle run (positive slope in rolling PF).

### Phase 3 — V145: LLM Meta-Controller

**Goal:** LLM provides 50-cycle strategic surface adjustments.

**Changes to LLM analyst:**
- New call type: `meta_controller` (vs existing `trade_modifier`)
- Input: full system state JSON
- Output: structured surface parameter adjustments
- Applied as prior to MetaLearner's running adjustments

**Success:** equal or better PnL with 10× fewer LLM calls.

### Phase 4 — V146: Ensemble Voting

**Goal:** replace `composite = Σ(signal × weight)` with structured vote aggregation.

**New module:** `omega/nodes/victoria/signal_ensemble.py`

Components:
- `SignalVote` dataclass
- `VoteAggregator`: computes agreement ratio, directional confidence
- `ensemble_composite()`: drop-in replacement for weighted sum

**Success:** signal IC outlier impact reduced. Anti-predictive signals can be neutralized per-regime without weight tuning.

### Phase 5 — V147: Bayesian Regime Detection

**Goal:** replace hard regime thresholds with calibrated posterior.

**New module:** `omega/nodes/victoria/regime_posterior.py`

Components:
- `RegimeLikelihood`: calibrated from Phase A snapshot data
- `BayesianRegimeDetector`: computes posterior from signals + LLM prior
- `RegimeSizingMixer`: converts posterior to regime size multiplier

**Success:** regime classification calibration error < 10%. No hard cutoffs in regime path.

---

## Part VIII: Risk Analysis

### 8.1 Over-Smoothing

**Risk:** if temperature T is set too high, the system loses all decisiveness. Every trade gets c ≈ 0.5 on every surface, resulting in half-size positions everywhere. The system "hedges" by never taking conviction positions.

**Evidence this is a real risk:** in the V141 ablation, the LLM modifier approach (which is already soft) produced fewer trades (81 vs 141 without LLM) but higher quality. Moving entirely to soft surfaces may reduce trade frequency further.

**Mitigation:**
1. **T floor**: minimum T = 0.05. Below this, the surface is effectively a hard gate.
2. **Meta-learner sharps decisively**: when PF > 1.5, T decreases. Allows confident market periods to produce high-conviction positions.
3. **Monitor trade frequency**: if cycles-per-trade > 10 (vs historical 4-6), soften surfaces (increase T) — the system is filtering too aggressively.
4. **Minimum position size guard**: if average position size drops below 40% of base_size across a 50-trade window, the surfaces may be too soft. Alert and adjust.

### 8.2 Computational Cost

**Sigmoid**: O(1), negligible. Calling sigmoid 5-6 times per trade proposal adds ~1 microsecond.

**Meta-learner**: O(window_size) per update = O(20) per closed trade. Negligible.

**Ensemble voting**: O(N_signals × N_votes) per trade = O(8 × 8) = O(64). Negligible.

**Bayesian posterior (Phase 5)**: depends on approximation. The practical sigmoid approximation is O(1). Full calibrated inference with N_signals likelihood components is O(N_signals) per evaluation = O(8). Negligible.

**Net**: continuous surfaces do not meaningfully change runtime. The existing LLM call (10-15 seconds per call) dominates. Reducing LLM call frequency in Phase 3 will decrease total runtime.

### 8.3 Backtest Validity

**Hard gates overfit in ways continuous surfaces don't.** When a hard gate at θ=0.35 is found to perform well in backtest, it is often because the backtest data has a natural cluster of good trades just above 0.35 and bad trades just below — a statistical accident. A continuous surface cannot exploit this accident in the same way: it doesn't rely on a specific cutpoint.

**Conversely, temperature calibration can overfit.** Setting T=0.08 specifically because it minimizes backtest PnL variance on the 3 Phase A snapshots is a form of overfitting to those snapshots. Mitigation: use T=0.10 as a calibration-free default, and only allow meta-learner adjustment within a ±0.05 band relative to T=0.10.

### 8.4 The Crisis Snapshot Wrap Problem

All Phase A analysis is confounded by the fact that the crisis snapshot wraps 151 bars over 500 cycles (3.3×). The same losing ADAUSDT long setup repeats at cycle 87, 239, 391 with identical losses of -$2,210 each. No architectural improvement will prevent this — the correct fix is not entering these positions, and the architecture addresses that. But the confidence surface will reduce their size (not eliminate them) unless the sigmoid center is set such that the composite for these positions falls into the near-blocked zone.

This is a fundamental limitation of synthetic snapshot backtesting. Phase B (live trading) will not have this wrap problem.

### 8.5 Signal Quality vs Decision Quality

Continuous confidence surfaces address **decision quality** — how we translate signals to positions. They do not address **signal quality** — whether the signals themselves contain predictive information.

The 0% high_vol WR is a signal quality problem: in high_vol regimes, the current signal stack (ORC, SMA, fear/greed, momentum) appears to have near-zero IC. Making the entry surface softer in high_vol (reduced regime_base weight) will reduce losses but will not make high_vol profitable. This requires either vol-specific signals (VIX term structure, realized vol acceleration) or a structural decision to sit out high_vol entirely.

Continuous surfaces make the system more robust to parameter choice; they make unprofitable signals less damaging but cannot make them profitable.

---

## Part IX: The Architectural North Star

After all five phases, the computation graph looks like:

```
Market data → Signal generation (N signals with IC weights, reinforcement EMA)
                      ↓
              Ensemble voting (direction, agreement, confidence)
                      ↓
              Bayesian regime posterior (P(crisis | signals, LLM_prior))
                      ↓
              Continuous confidence surfaces (c_bear × c_composite × c_regime)
                      ↓
              Meta-learner adjustment (rolling PF → temperature update)
                      ↓
              LLM meta-controller (50-cycle strategic prior adjustment)
                      ↓
              Final size = base_size × Π(confidence_factors)
                      ↓
              Position if size > floor ($500)
```

Every decision in this graph is continuous. No hard gates. No cliffs. The LLM and meta-learner provide priors; the confidence surfaces translate priors and signals to sizes; the ensemble voting aggregates signal information without losing uncertainty.

**The test that validates this is working:** run the parameter sensitivity grid (center 0.30→0.60, 7 steps) at each phase. If architecture is correct, sensitivity decreases monotonically across phases:

| Phase | Expected sensitivity |
|---|---|
| V141 (hard gate) | ~$30,000 (empirical) |
| V143 (Phase 1, T=0.10) | ~$10,000 |
| V143 (Phase 1, T=0.15) | ~$7,000 |
| V144 (Phase 2, meta-learner) | ~$5,000 |
| V145 (Phase 3, LLM prior) | ~$4,000 |
| V146 (Phase 4, ensemble) | ~$3,000 |
| V147 (Phase 5, Bayesian) | ~$2,000 |

The target is $5,000 by Phase 2. If Phase 1 alone achieves this, the subsequent phases provide robustness, interpretability, and adaptability — not just reduced sensitivity.

---

## Appendix A: Calibrating Surface Parameters from Phase A Data

Surface centers `μ` and temperatures `T` should be calibrated from empirical Phase A data, not set by intuition.

**Bear probability center μ_bear:** set to the bear_prob value that separates winning and losing long trades:

```python
long_trades = load_trades('data/bt_v139_recent_trades.csv', side='long')
bear_probs_wins  = [t['bear_prob_at_entry'] for t in long_trades if t['pnl'] > 0]
bear_probs_losses= [t['bear_prob_at_entry'] for t in long_trades if t['pnl'] < 0]
# Optimal center ≈ value that minimizes classification error
# Approximate: midpoint of means
μ_bear = (mean(bear_probs_wins) + mean(bear_probs_losses)) / 2
```

**Temperature T:** set to the standard deviation of bear_prob among boundary trades (those near the optimal center):

```python
boundary_trades = [t for t in long_trades if abs(t['bear_prob'] - μ_bear) < 0.15]
T_bear = std([t['bear_prob'] for t in boundary_trades]) × 1.5
```

A wider T (1.5× the boundary std dev) ensures smooth transitions. A narrower T would risk recreating the hard-gate behavior.

This calibration should be re-run whenever the Phase A snapshot data is updated. The result is stored in `data/surface_calibration.json` and loaded at runtime.

---

## Appendix B: Hard Gate Inventory (Current System)

For reference: every binary gate in the current system that Phase 1 (V143) replaces.

| Location | Variable | Threshold | Direction | Current behavior |
|---|---|---|---|---|
| strategy.py:889 | `bear_prob` | 0.65 | `>` | `is_crisis = True` |
| strategy.py:891 | `bear_prob` | 0.45 | `>=` | `is_crisis = True` (with HMM label) |
| strategy.py:892 | `bear_prob` | 0.45 | `>=` | `is_crisis = True` (with regime label) |
| strategy.py:896 | `bear_prob` | 0.65 | `>=` | `is_crisis = True` (V95 non-HMM) |
| strategy.py:898 | `bear_prob` | 0.45 | `>=` | `is_crisis = True` (V95 HMM) |
| strategy.py:899 | `bear_prob` | 0.45 | `>=` | `is_crisis = True` (V95 label) |
| strategy.py:936 | `bull_prob` | 0.55 | `>=` | `is_bull = True` |
| strategy.py:1772 | `_regime_consolidated` | "crisis" | `==` | Long blocked |
| strategy.py:1785 | `bear_prob_long_block_threshold` | 0.55 | `>=` | Long blocked |
| strategy.py:1795 | `_is_high_vol` | label | `==` | Long blocked (crisis_high_vol_long_block) |
| strategy.py:~1800 | `_is_high_vol` | label | `==` | Long blocked (high_vol_entry_block V142) |
| strategy.py:1809 | `composite` | `_signal_threshold` | `<=` | Long rejected (no conviction) |
| strategy.py:1184 | `abs(w_conv)` | `_abs_min_conviction` | `<` | Short rejected |
| strategy.py:2101 | composite | scaled threshold | `<` | Short rejected (crisis scale) |
| strategy.py:2109 | `_is_high_vol` | label | `==` | Short blocked (high_vol_short_block) |
| strategy.py:~2112 | `_is_high_vol` | label | `==` | Short blocked (high_vol_entry_block V142) |
| exit_controller.py:234 | `unrealized` | `mae_stop_k × ATR` | `<=` | Hard stop |
| exit_controller.py:257 | `mfe` | `mfe_trail_k × ATR` | `>=` | Trail activates |
| exit_controller.py:259 | `unrealized` | `mfe × (1-cap)` | `<` | Trail fires |
| exit_controller.py:224 | `unrealized` | `early_loss_k × ATR` | `<=` | Early loss stop |
| exit_controller.py:210 | `mfe` | 0.0 | `<=` | Zero-MFE exit |

*Note: Exit gates (ExitController) are not replaced in Phase 1. Exit sizing is already somewhat continuous via ATR multipliers. These may be addressed in a later phase.*

---

*Document end. Implementation begins with `omega/nodes/victoria/confidence_surface.py`.*
