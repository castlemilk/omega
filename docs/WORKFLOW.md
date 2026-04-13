# Victoria Self-Improving Trading Loop

This is the core workflow that drives every iteration of Victoria's paper trading system. It's the reason the system went from -$225 (V102) to +$33 (V114) in the same crisis market — not by guessing, but by systematically tracing decisions, evaluating outcomes, and making evidence-based fixes.

## The Loop

```
  ┌──────────────────────────────────────────────────────────┐
  │                                                          │
  │   1. RUN         Train a version with feature flags ON   │
  │      │                                                   │
  │      ▼                                                   │
  │   2. TRACE       Every trade records its full decision   │
  │      │           tree (signals, weights, thresholds,     │
  │      │           filters, regime, geometry)              │
  │      ▼                                                   │
  │   3. POSTMORTEM  Analyze: which signals were RIGHT vs    │
  │      │           WRONG? Which trades should not have     │
  │      │           been taken?                             │
  │      ▼                                                   │
  │   4. FIX         Apply evidence-based changes via        │
  │      │           feature flags (flip signals, suppress   │
  │      │           symbols, adjust thresholds)             │
  │      ▼                                                   │
  │   5. VALIDATE    Run next version, compare to previous.  │
  │      │           Did the fix improve PnL/WR/PF?         │
  │      │                                                   │
  │      └───────────────── back to 1 ──────────────────────┘
```

Every step has a concrete tool. No step requires intuition — it's all data-driven.

## Step 1: RUN — Launch a training version

```bash
# Run with the current best preset
python3 scripts/run_training.py --version v115 --cycles 200 --sleep 10 --features v115_full_vectors

# Run with V93 baseline (all flags OFF) for comparison
python3 scripts/run_training.py --version v99 --cycles 200 --sleep 10 --features v93_baseline

# Background launch (for overnight runs)
nohup python3 scripts/run_training.py --version v115 --cycles 200 --sleep 10 --features v115_full_vectors > /tmp/v115.log 2>&1 &
```

**What happens during the run:**
- Activation traces write to `data/activation_traces/{version}.jsonl` — one JSON per trade entry
- Trade reinforcement updates `data/reinforcement_state.json` after each closed trade
- Trade results write to `data/{version}_trades.csv`
- Progress snapshots write to `data/{version}_progress.json` every 5 cycles
- Final results write to `data/{version}_results.json`

**Monitor progress:**
```bash
python3 -c "
import json
with open('data/v115_progress.json') as f:
    d = json.load(f)
e = d[-1]
print(f'V115 c{e[\"cycle\"]}/200 PnL=\${e[\"total_pnl\"]:+.2f} T={e[\"trades_closed\"]} WR={e[\"win_rate\"]:.0%} Regime={e[\"regime\"]}')
"
```

## Step 2: TRACE — Activation traces capture every decision

When `activation_tracing` flag is ON, every trade entry records:

```json
{
  "version": "v115",
  "cycle": 42,
  "ticker": "ARBUSDT",
  "side": "long",
  "activations": [
    {"name": "sma_crossover", "raw_value": 0.832, "final_weight": 0.60, "weighted_value": 0.499},
    {"name": "fear_greed_signal", "raw_value": -0.294, "final_weight": 0.77, "weighted_value": -0.226},
    ...
  ],
  "raw_composite": 0.156,
  "demeaned_composite": 0.089,
  "threshold": 0.072,
  "threshold_gap": 0.017,
  "regime": "crisis",
  "conviction": 0.141,
  "position_size": 8509.0,
  "pnl": -25.40,
  "signals_right": ["fear_greed_signal", "mean_reversion"],
  "signals_wrong": ["sma_crossover", "tick_momentum"]
}
```

This is the FULL computation graph. You can reconstruct exactly why any trade was taken.

**View a trace:**
```bash
python3 scripts/view_activations.py --version v115 --limit 5
```

## Step 3: POSTMORTEM — Analyze what went right and wrong

### Trade-level post-mortem
```bash
python3 scripts/postmortem.py --version v115
```

Shows:
- Top 10 losers with full signal alignment (which signals pushed FOR the trade, which AGAINST)
- Signal scorecard: per-signal accuracy across ALL trades (times right/wrong, net contribution)
- Regime breakdown: PnL by regime (normal vs crisis vs high_vol)

**Example output:**
```
SIGNAL SCORECARD (65 trades):
  Signal              Accuracy  Recommendation
  momentum_derivative   73.9%   KEEP (strongest signal)
  tick_momentum         60.9%   KEEP (WebSocket microstructure)
  order_book_imbalance  56.9%   KEEP
  sma_crossover         43.1%   DAMPEN/FLIP (anti-predictive)
  fear_greed_signal     32.3%   FLIP (consistently wrong → flip = 67.7% accurate)

REGIME BREAKDOWN:
  crisis:  +$43.60 (19 trades, 42% WR) ← profitable!
  normal:  -$50.98 (46 trades, 28% WR) ← this is the bleed
```

### Single-trade deep dive
```bash
python3 scripts/signal_heatmap.py --version v115 --trade ARBUSDT_42
```

Shows the full decision tree for one trade: every signal's contribution, filter chain, geometry state, and post-close attribution.

### Reinforcement weight analysis
```bash
python3 scripts/reinforcement_report.py
```

Shows: current signal weights, convergence analysis (stable vs oscillating), effective thresholds after adjustment, actionable recommendations.

### Cross-version aggregation
```bash
python3 scripts/cross_version_analysis.py --versions v110,v111,v113,v114,v115
```

Aggregates signal accuracy across multiple versions for statistically significant conclusions (200+ trades instead of 40-60 per version).

## Step 4: FIX — Apply evidence-based changes

Every fix is a feature flag. Never modify the baseline code path directly.

### Common fix patterns (proven in V106-V115 arc):

**Pattern: Signal is anti-predictive (<40% accuracy)**
```
Evidence: postmortem shows sma_crossover at 43.1% accuracy across 65 trades
Fix: Flip the signal (multiply by -1) via `postmortem_signal_filter` flag
Result: V113 flipped 6 signals → 45 shorts generated (first time shorts > longs)
```

**Pattern: One symbol is dragging**
```
Evidence: postmortem shows NEAR shorts lost -$93 on 22 trades (27% WR)
Fix: Add NEAR to SHORT_SUPPRESSED list in `postmortem_signal_filter`
Result: V114 = +$33.45 (vs V113's -$4.07)
```

**Pattern: Regime-specific losses**
```
Evidence: V99 daily report shows crisis=-$23, high_vol=-$83, normal=+$169
Fix: Add `crisis_high_vol_long_block` flag (or `crisis_short_bias`)
Result: Test via ablation before committing
```

**Pattern: New signal family needed**
```
Evidence: postmortem shows all existing signals <55% accurate
Fix: Add new vector (whale_prints, book_depth_velocity, etc.) via feature flag
Result: V115 added 7 new signals, test via postmortem comparison
```

### Adding a new feature flag

1. Add the flag to `omega/nodes/victoria/features.py`:
```python
@dataclass
class VictoriaFeatures:
    my_new_flag: bool = False  # Description of what it does
```

2. Gate the code in `strategy.py` or `signal_generation.py`:
```python
if self.features.my_new_flag:
    # New behavior
else:
    # V93 baseline behavior (unchanged)
```

3. Add a preset if useful:
```python
_PRESETS["v116_my_experiment"] = lambda: VictoriaFeatures(
    decision_embeddings=True,
    my_new_flag=True,
)
```

4. Test with ablation:
```bash
python3 scripts/ablate.py --cycles 100 --presets v93_baseline,v116_my_experiment
```

## Step 5: VALIDATE — Compare to previous version

After each fix, run the next version and compare:

```bash
# Quick comparison
python3 -c "
import json
for v in ['v113', 'v114', 'v115']:
    with open(f'data/{v}_results.json') as f:
        d = json.load(f)
    t = d['trades']
    print(f'{v}: PnL=\${t[\"total_pnl_usd\"]:+.2f} WR={t[\"win_rate\"]:.0%} T={t[\"total_closed\"]} PF={t.get(\"profit_factor\",\"n/a\")}')
"
```

**Validation criteria:**
- PnL improved (or at least didn't regress)
- WR maintained or improved
- PF above 1.0 (system is net profitable)
- No zero-trade death spirals (max zero streak < 30)
- Trades are diversified across symbols (not single-asset concentration)

Then run postmortem on the new version to find the next improvement.

## Real Example: V110 → V114 Arc

This is how the loop produced 4 compounding improvements in the same crisis market:

| Step | Version | Action | PnL | Evidence Used |
|------|---------|--------|-----|---------------|
| RUN | V110 | 20% threshold reduction + reinforcement | -$7.38 | Ablation showed embeddings add alpha |
| POSTMORTEM | V110 | `scripts/postmortem.py --version v110` | — | sma/fear_greed <40% accurate, microstructure >57% |
| FIX | V112 | Zero out dead signals | $0.00 | Zeroing killed composite magnitude (wrong fix!) |
| FIX | V113 | FLIP dead signals instead of zeroing | -$4.07 | Flipping preserves magnitude, corrects direction |
| POSTMORTEM | V113 | `scripts/postmortem.py --version v113` | — | NEAR shorts lost -$93 on 22 trades |
| FIX | V114 | Suppress NEAR shorts | **+$33.45** | V113 was +$89.77 excluding NEAR |
| VALIDATE | V114 | Compare to V110 baseline | +$40 improvement | Postmortem-driven fixes compound |

Each fix was driven by specific evidence from the postmortem, not intuition. Each fix was gated behind a feature flag so it could be tested in isolation.

## File Reference

| File | Purpose | When to use |
|------|---------|-------------|
| `scripts/run_training.py` | Launch training runs | Every iteration |
| `scripts/postmortem.py` | Analyze trade outcomes | After every completed run |
| `scripts/signal_heatmap.py` | Deep dive into single trade | When investigating a specific loss |
| `scripts/reinforcement_report.py` | Check weight convergence | After 3+ versions with reinforcement |
| `scripts/cross_version_analysis.py` | Aggregate accuracy across versions | When you need statistical significance |
| `scripts/view_activations.py` | Browse activation traces | When debugging trace format |
| `scripts/ablate.py` | A/B test feature presets | Before committing a new feature |
| `omega/nodes/victoria/features.py` | Feature flag definitions | When adding new experiments |
| `omega/nodes/victoria/trade_reinforcement.py` | Signal weight learning | Runs automatically during training |
| `omega/nodes/victoria/activation_trace.py` | Decision tree recording | Runs automatically when flag ON |
| `omega/nodes/victoria/trade_attribution.py` | PnL decomposition per signal | Called by postmortem tools |
| `data/reinforcement_state.json` | Persisted signal weights | Carries learning across versions |
| `data/activation_traces/*.jsonl` | Decision provenance | Input to all analysis tools |

## Key Principle

**Never guess. Always trace, analyze, then fix based on evidence.**

The system has 360+ trades of activation trace data across 9 version files. Every signal's accuracy is measurable. Every trade's decision tree is reproducible. The postmortem tools turn raw data into actionable recommendations. The feature flag system lets you test each recommendation in isolation.

This is what makes the system self-improving: each iteration's mistakes become the next iteration's improvements, and the improvements compound because they're based on growing evidence, not shrinking intuition.
</content>
</invoke>