# Adaptive Engine V2 — Architecture Rethink

**Status:** Design · April 2026  
**Trigger:** V141 Phase A — changing `bear_prob_long_block` from 0.35 → 0.55 caused a $30k PnL swing across snapshots. A system where a single threshold controls $30k of outcome is too fragile to promote to live.

---

## 1. Why We're Stuck: The Fragility Diagnosis

The current system is a **sequential hard-gate pipeline**:

```
signals → static IC weights → composite → hard threshold → hard gates (regime, AND-gate, LLM veto) → enter/exit
```

Every decision boundary is a **binary cliff**: `bear_prob=0.34` → full entry; `bear_prob=0.36` → blocked. This creates a structurally fragile system where:

| Problem | Mechanism | Evidence |
|---|---|---|
| **Cliff effects** | A threshold flips ALL trades near the boundary simultaneously | bear_prob 0.35→0.55: $30k PnL swing |
| **No learning** | The same threshold is used at cycle 1 and cycle 500 | PF doesn't improve within a run |
| **Context blindness** | A 0.35 threshold means the same thing in H1-2022 bear and Q4-2023 bull | Hysteresis bled from crisis into trend snapshot |
| **LLM as gate, not advisor** | The LLM veto is another hard threshold (mod < 0.30 → block) | LLM gave mod=0.35 for longs that were wrong — threshold, not reasoning |
| **Signal aggregation loses uncertainty** | `composite = Σ(signal × weight)` can give 0.12 from two signals canceling | System enters on net-zero conviction |

### The Threshold Tuning Loop

We keep doing this:
1. V1xx ships with threshold T
2. Backtest shows a regime where T is wrong
3. Tune T → T' to fix that regime
4. T' breaks a different regime
5. Back to step 1

This loop does not converge. Each version fixes one regime at the cost of another. The root cause is not the wrong threshold — it's that **a single scalar threshold cannot represent a decision surface that varies by market context, position history, and signal reliability**.

---

## 2. The Right Frame: What Are We Actually Trying to Do?

The engine's job is:

> **Given current market signals and regime context, estimate the expected PnL of entering a position, and size it proportionally to that expectation.**

A hard gate answers a different question: *"does this pass a minimum bar?"* That question throws away all information about HOW MUCH conviction exists above the bar, and prevents partial entries when conviction is intermediate.

The fragility problem is precisely this: near the threshold, expected PnL varies continuously but our action is binary (enter full / don't enter). Any threshold will be wrong for some trades.

---

## 3. Proposed Architecture: Continuous Adaptive Engine

Five phases, each independently improvable. Phase 1 alone eliminates the bear_prob fragility.

### Phase 1: Continuous Confidence Surfaces (V143)

**Replace every hard gate with a continuous sigmoid.**

Instead of:
```python
if bear_prob > 0.35:
    continue  # block long
```

Use:
```python
long_confidence = sigmoid(-(bear_prob - center) / temperature)
# At center=0.45, temperature=0.10:
#   bear_prob=0.20 → confidence=0.99 (full entry)
#   bear_prob=0.45 → confidence=0.50 (half size)
#   bear_prob=0.70 → confidence=0.07 (near-blocked)
```

**Position size is multiplied by confidence.** Near the boundary, the system takes a smaller position. Well inside the boundary, it's full size. Well outside, it's effectively zero.

The parameter sensitivity test: vary `center` from 0.30 to 0.60. With hard gates, PnL swings $30k. With sigmoid sizing, the swing should be <$5k because boundary trades are already small.

**Signal composite confidence:**
```python
# Instead of: composite = Σ(signal × weight)
# Use: composite_confidence = sigmoid((composite - threshold) / temperature)
# Size ∝ composite_confidence × bear_prob_confidence × regime_confidence
```

**All three sizing factors multiply:**
```
final_size = base_size × long_confidence(bear_prob) × composite_confidence × regime_confidence
```

No trade is ever "blocked" — it either has tiny size or is below the minimum position floor (which sits at notional $500 as a practical zero).

**Implementation:** `omega/nodes/victoria/confidence_surface.py` — stateless `ConfidenceSurface` dataclass with `long_confidence(bear_prob)`, `composite_confidence(composite)`, `regime_confidence(regime_label, bear_prob)` methods. Temperature and center become the tunable parameters instead of hard thresholds.

### Phase 2: Meta-Learning Layer (V145+)

**The system adapts its confidence surface parameters in real-time based on recent performance.**

Track a rolling 20-trade window per regime:
- `rolling_pf[regime]` — profit factor over last 20 trades in this regime
- `rolling_wr[regime]` — win rate

Adaptation rules:
- `rolling_pf["crisis"] < 0.8` → tighten crisis entries: decrease temperature (sharper sigmoid, closer to hard gate)
- `rolling_pf["crisis"] > 1.5` → loosen: increase temperature (flatter sigmoid, more permissive sizing)
- `rolling_pf["normal"] < 0.9` → shift normal long_confidence center toward 0.50 (require clearer conviction)

This is **not** the reinforcement EMA (which adjusts signal IC weights). This adjusts the **entry surface shape** — how conviction translates to position size — based on realized regime performance.

The meta-learner is a lightweight addition to `_apply_regime_adaptive_thresholds`. It reads from a rolling window buffer, not from an ML model. No training required.

### Phase 3: LLM as Meta-Controller (V147+)

**Replace per-trade LLM veto with strategic regime advice.**

Current: LLM called every 10 cycles, returns modifier [0, 1], trades vetoed if mod < 0.30.

Problems:
- The LLM doesn't know if its veto is actually helping (no feedback loop)
- Per-trade veto is a hard gate — same fragility as threshold tuning
- 10-cycle cadence is too frequent for strategic assessment, too infrequent for real-time signal

Proposed: LLM called every 50 cycles, receives:
- Last 50 cycles of PF, WR per regime
- Current rolling confidence surface parameters
- Regime distribution (% crisis/normal/high_vol)
- Signal IC drift vs prior 50 cycles

Returns:
- `regime_temperature_adjustment: dict` — e.g., `{"crisis": -0.02, "normal": +0.01}` (tighten/loosen surface)
- `signal_weight_recommendation: dict` — e.g., `{"fear_greed_signal": 0.1, "ollivier_ricci_signal": 1.8}` (IC recalibration)
- `strategic_note: str` — reasoning (logged to `data/llm_strategy_log/`)

The LLM adjusts parameters, not individual trades. This is cheaper (10× fewer calls), more impactful (affects all subsequent entries, not just one), and gives the LLM the right level of abstraction — strategic regime awareness, not per-trade assessment.

### Phase 4: Ensemble Signal Voting (V149+)

**Replace weighted sum with ensemble voting that preserves uncertainty.**

Current: `composite = Σ(signal × weight)` — signals cancel each other and the sum can be near zero from strong opposing votes.

Proposed:
```python
@dataclass
class SignalVote:
    direction: Literal["long", "short", "abstain"]
    confidence: float  # 0-1
    signal_name: str

votes = [vote_from_signal(s, v) for s, v in signals.items()]
long_votes  = sum(v.confidence for v in votes if v.direction == "long")
short_votes = sum(v.confidence for v in votes if v.direction == "short")
abstain_votes = sum(v.confidence for v in votes if v.direction == "abstain")

# Direction: majority by weighted vote
# Conviction: unanimous > split
agreement_ratio = max(long_votes, short_votes) / (long_votes + short_votes + abstain_votes)
# agreement_ratio ≈ 1.0: high conviction (strong majority)
# agreement_ratio ≈ 0.5: split vote, uncertain
```

Size = `base_size × agreement_ratio × regime_confidence`

Advantage: a strong bullish outlier signal with 4 opposing signals produces agreement_ratio=0.3 (small size), not a composite near zero (no entry at all). The system takes the trade but size-corrects for uncertainty. This matches how a risk manager actually thinks.

### Phase 5: Bayesian Regime Detection (V150+)

**Replace threshold-based regime classification with full posterior.**

Current: `is_crisis = bear_prob > 0.65 OR (label=="crisis" AND bear_prob > 0.45)` — two hard cutoffs.

Proposed: maintain a Bayesian posterior over regime states {crisis, high_vol, normal, bull}.

```
Prior: LLM macro assessment (updated every 50 cycles)
       P(crisis) = 0.20, P(normal) = 0.60, P(bull) = 0.20

Likelihood: Wasserstein distance, VIX proxy (ORC), bear_prob, SMA alignment
            L(data | crisis) = p(Wasserstein=X | crisis) × p(ORC=Y | crisis) × ...

Posterior: Bayes rule (simple categorical update)
           P(crisis | data) = P(data | crisis) × P(crisis) / P(data)
```

Entry sizing uses the full posterior:
```python
regime_confidence = sum(
    P_regime[r] * regime_multiplier[r]
    for r in ["crisis", "high_vol", "normal", "bull"]
)
```

No hard cutoffs. The system naturally positions larger in clear regimes and smaller in ambiguous ones.

---

## 4. Implementation Roadmap

| Phase | Version | Core change | Robustness metric |
|---|---|---|---|
| 0 (current) | V142 | Quick fix: threshold tuning | — |
| 1 | V143 | Sigmoid confidence surfaces | bear_prob sensitivity < $5k |
| 2 | V145 | Meta-learning (rolling PF → temperature) | Crisis PF improves within run |
| 3 | V147 | LLM as meta-controller | 10× fewer LLM calls, equal or better PnL |
| 4 | V149 | Ensemble voting | Composite uncertainty < 0.05 on avg |
| 5 | V150 | Bayesian regime posterior | Regime calibration error < 10% |

**Gate for progression:** each phase must independently pass the Phase A triple snapshot (crisis + trend + recent) without regression on any snapshot vs the prior version.

---

## 5. The Robustness Test

After Phase 1 (V143), run the **parameter sensitivity test**:

```python
for center in [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]:
    # Run 500 cycles on crisis snapshot with sigmoid center = center
    # Record total PnL
sensitivity_range = max(pnl_by_center) - min(pnl_by_center)
```

**Target:** `sensitivity_range < $5,000` on the crisis snapshot.

Current hard-gate system: $30k sensitivity range (0.35 vs 0.55 center = $30k swing).

If sensitivity_range < $5k after Phase 1, the architecture is working. The system is making money robustly across a wide range of parameter choices — not because we found the magic threshold, but because position sizing absorbs the uncertainty.

---

## 6. What This Doesn't Fix

Phase 1-5 make the system more **robust to parameter choice** and more **adaptive to regime changes**. They do not fix:

- **Signal quality in high_vol:** High_vol has 0% WR because the underlying signals (SMA crossover, ORC, fear/greed) are genuinely uninformative during vol spikes. Sigmoid sizing will reduce losses (smaller positions) but won't make high_vol profitable. Need vol-specific signals (VIX term structure, realized vol acceleration) or continued sit-out.
- **Data freshness:** Crisis snapshot wraps 151 bars over 500 cycles (3.3×). The same trade setups recur identically. Phase A crisis WR will always be lower than live because we're trading the same losing setup 3× without learning.
- **Execution quality:** All results assume zero slippage, instant fill. Live will have spread + depth constraints.

---

## 7. V142 as Bridge

V142 (running now) is not the architectural fix — it's the **minimum viable patch** to keep the pipeline moving while V143 is developed:
- Raises bear_prob gate to 0.55 (conservative, reduces trend/recent regression)
- Gates hysteresis to bear_prob > 0.50 (prevents trend-snapshot bleed)
- Blocks high_vol entirely (0% WR → cleaner to sit out)
- Keeps LLM crisis mode (proven +$3,161 delta in V141 ablation)

If V142 passes Phase A (crisis positive, trend/recent ≥ V139), promote to Phase B and begin V143. If V142 still regresses trend/recent, the bear_prob gate itself is the wrong mechanism and Phase 1 (sigmoid) is the correct solution — implement V143 directly from V141 base.

---

*Written: 2026-04-19 | Author: Omega Code Quality Bot | Trigger: V141 Phase A $30k fragility event*
