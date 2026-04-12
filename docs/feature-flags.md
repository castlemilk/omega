# Victoria Feature Flags

Victoria's experimental features are controlled by a lightweight flag system in
`omega/nodes/victoria/features.py`. All flags default to `False`, preserving
the V93 champion baseline when no environment variable is set.

## Why feature flags?

Each worktree experiment (V95 geometry, strange-clarke observability,
hopeful-mendeleev LLM/embeddings) is now merged into `main` behind a flag.
This means:

- **No code is ever deleted.** Each experiment is gatable, not discarded.
- **Ablation is trivial.** Run the same N cycles with different presets and
  compare in a table.
- **Regressions are recoverable.** If a new flag hurts PnL, turn it off
  without reverting code.
- **V93 baseline is sacred.** `VICTORIA_FEATURES=` (empty or unset) → identical
  behaviour to the V93 champion run.

---

## How to enable flags

### 1. Environment variable (recommended for training runs)

```bash
# Named preset
VICTORIA_FEATURES=v97_geometry python3 scripts/run_training.py --version v100

# Inline JSON (mix and match)
VICTORIA_FEATURES='{"ricci_sizing":true,"anomaly_detector":true}' python3 scripts/run_training.py
```

### 2. CLI argument to run_training.py

```bash
python3 scripts/run_training.py --version v100 --cycles 200 --features observability_only
```

`--features` accepts a preset name or a JSON dict. It sets `VICTORIA_FEATURES`
before initialising the strategy, so the behaviour is identical to the env var.

### 3. Programmatic (scripts / notebooks)

```python
from omega.nodes.victoria.features import VictoriaFeatures

f = VictoriaFeatures.preset("v97_geometry")     # named preset
f = VictoriaFeatures.from_preset("v97_geometry") # alias
f = VictoriaFeatures(ricci_sizing=True)          # field overrides
f = VictoriaFeatures.from_env()                  # reads VICTORIA_FEATURES

print(f.enabled())   # ['fiedler_conviction_modulation', 'geodesic_crash_distance', ...]
f.log_header()       # logs one-liner to omega.victoria.features logger
```

---

## Flag reference

### Geometry modifiers (V95)

All four modifiers were live in V97/V98 and caused a regression vs V93
(+$94 / -$112 vs +$131). They are **off by default** pending forensic analysis
(Track E in TODO.md).

| Flag | What it does | Cost | Benefit | When to enable |
|------|-------------|------|---------|----------------|
| `ricci_sizing` | Reduce long sizes when approaching crash manifold (Ricci curvature > 0.3) | Misses some longs in normal markets | Smaller draw in pre-crash regimes | After forensics confirm it's not the regression source |
| `orc_stress_reduction` | Scale all sizes down when ORC κ > 0.1 (contagion signal) | Reduces size in volatile, potentially profitable periods | Limits contagion exposure | Same — forensics first |
| `geodesic_crash_distance` | Raise `long_thresh` from 0.10 → 0.20 when crash proximity ≥ 0.6 | Suppresses longs near crash | Hard gate before crash | After isolating vs other geometry flags |
| `fiedler_conviction_modulation` | Fragmented graph → lower short threshold; consensus → lower both | Adds noise in choppy regimes | Better entry timing in trending markets | After forensics |

**Forensics command** (compare geometry vs baseline):
```bash
python3 -m omega.tools.forensics.run_diff \
  --baseline-results data/v93_results.json  --baseline-trades data/v93_trades.csv \
  --target-results   data/v97_results.json  --target-trades   data/v97_trades.csv \
  --out-md docs/training/v93-v97-forensics.md
```

---

### Observability stack (strange-clarke)

Zero PnL impact expected. Safe to enable alongside any preset.

| Flag | What it does | Cost | Benefit | When to enable |
|------|-------------|------|---------|----------------|
| `decision_traces` | Write per-ticker `DecisionTrace` JSONL each cycle to `data/decision_traces/{version}.jsonl` | ~1 ms/cycle, ~5 MB/200 cycles | Full audit trail of conviction, thresholds, sit-out reason | Always in production runs |
| `signal_confluence` | `ConfluenceAnalyzer`: boost/dampen size by sub-signal agreement ratio | Slight size variance | Filters noise when signals disagree | When hunting for precision improvements |
| `signal_correlation_monitor` | 50-cycle rolling Pearson matrix across signals, saved to `/tmp/{version}_corr.json` | ~2 ms/50 cycles | Detects signal redundancy / decay | During exploratory phases |
| `anomaly_detector` | Alert when pnl_delta, trades/cycle, zero_streak, or basket_std deviate > 3σ | None | Early warning for strategy drift | Always in production runs |

---

### LLM / embedding (hopeful-mendeleev)

Requires `claude` CLI in PATH (or `ANTHROPIC_API_KEY` as fallback).

| Flag | What it does | Cost | Benefit | When to enable |
|------|-------------|------|---------|----------------|
| `decision_embeddings` | `DecisionEmbedder` KMeans cluster bias applied to conviction score | Requires `numpy` + `scikit-learn`; no-op if absent | Learned bias from historical decision clusters | After fitting: `python -m omega.nodes.victoria.decision_embeddings --version v99` |
| `llm_trade_review` | Post-trade LLM post-mortem (Claude deep tier) written to `data/decision_traces/{version}_llm_review.md` | ~5–10 s per review, API cost if no CLI | Qualitative hypothesis generation | After a 200+ cycle run with ≥ 30 trades |

---

### Version-specific fixes

| Flag | What it does | Status |
|------|-------------|--------|
| `v96_crisis_detection_fix` | When `bear_prob=-1`, trust `regime_label='crisis'` directly instead of the old heuristic | Off pending ablation — potential improvement in bear markets |
| `v96_multi_cycle_bypass` | Lower normal-short multi-cycle bypass threshold 0.09 → 0.07 | Off pending ablation — may increase short frequency in normal regime |
| `crisis_high_vol_long_block` | Hard-block all long allocations when regime is `crisis` or `high_vol` (shorts unchanged). Cost: misses recovery longs in post-crash bounce. Benefit: eliminates -$106 combined crisis/high_vol long loss from V99. Enable via `v101_regime_safe` preset. | V101 — targets regime-aware sizing improvement |

---

## Presets

| Preset | Flags ON | Use case |
|--------|----------|----------|
| `v93_baseline` | none | Reproduce V93 champion. The comparison baseline for all ablations. |
| `v97_geometry` | `ricci_sizing`, `orc_stress_reduction`, `geodesic_crash_distance`, `fiedler_conviction_modulation` | Isolate geometry modifier impact |
| `observability_only` | `decision_traces`, `signal_confluence`, `signal_correlation_monitor`, `anomaly_detector` | Production observability without changing trading logic |
| `embeddings_only` | `decision_embeddings`, `llm_trade_review` | LLM + embedding features only |
| `v98_full_obs` | geometry + observability (8 flags) | Reproduce V98 (warning: -$112 in April crisis market) |
| `v99_full` | all 12 flags | Full stack. Use only after individual presets are validated. |
| `v101_regime_safe` | `decision_embeddings`, `crisis_high_vol_long_block` | V101 target: embeddings + regime-safe long blocking |

---

## Adding a new flag

1. Add a `bool` field to `VictoriaFeatures` in `features.py` (default `False`).
2. Add a docstring explaining what the flag controls.
3. Wrap the experimental code in `strategy.py` (or wherever):
   ```python
   if self.features.my_new_flag:
       # experimental code
   ```
4. Add the flag to any relevant presets in `_PRESETS`.
5. Document it in this file under the appropriate section.

**Do not** enable a new flag in `v93_baseline`. That preset must always produce
identical output to the V93 champion run.

---

## Running ablations

```bash
# Quick sanity check (100 cycles × 3 presets ≈ 3 hours)
python3 scripts/ablate.py --cycles 100 --presets v93_baseline,observability_only,embeddings_only

# Full geometry forensics (200 cycles × 2 presets ≈ 3.5 hours)
python3 scripts/ablate.py --cycles 200 --presets v93_baseline,v97_geometry --version-prefix geo

# Custom output directory
python3 scripts/ablate.py --cycles 100 --output-dir data/my_ablation
```

Output is saved to `data/ablation_{timestamp}/`:
- `{preset}_results.json` — raw training result per preset
- `summary.json` — comparison table data

The comparison table is also printed to stdout with ANSI colour coding:
green = better than baseline, red = worse.

---

## Example commands

```bash
# V93 baseline (should match +$130 over 200 cycles in same market)
python3 scripts/run_training.py --version v100 --cycles 200 --features v93_baseline

# Observability only (no PnL change expected)
python3 scripts/run_training.py --version v101 --cycles 200 --features observability_only

# Check which flags are active in a preset
python3 -c "from omega.nodes.victoria.features import VictoriaFeatures; print(VictoriaFeatures.preset('v97_geometry').enabled())"

# Run LLM post-mortem on completed run
python3 -m omega.nodes.victoria.llm_trade_review --version v100

# Fit decision embeddings from completed run
python3 -m omega.nodes.victoria.decision_embeddings --version v100
```
