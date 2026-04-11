# Victoria Feature Flag Ablation Report

**Run timestamp:** 2026-04-11T11:27:39Z  
**Ablation dir:** `data/ablation_20260411T100444/`  
**Command to reproduce:**
```bash
cd /Users/benebsworth/projects/omega
export DATABASE_URL=postgresql://omega:omega@localhost:5432/omega
python3 scripts/ablate.py --cycles 100 --sleep 10 \
  --presets v93_baseline,observability_only,embeddings_only \
  --version-prefix ablate
```

---

## Results Table

| Preset | PnL | WR | Trades | PF | Zero% | Delta vs Baseline |
|---|---|---|---|---|---|---|
| v93_baseline (baseline) | -$25.46 | 38.1% | 21 | 0.80 | 84% | — |
| observability_only | $0.00 | 0.0% | 0 | N/A | 100% | +$25.46 (no trades) |
| **embeddings_only** | **+$51.78** | **33.3%** | **21** | **1.46** | **85%** | **+$77.24** |

---

## Winner: `embeddings_only`

`embeddings_only` is the clear winner, generating **+$51.78 PnL** versus the baseline's **-$25.46**, a delta of **+$77.24**. It achieved the same trade count (21) and comparable activity level (85% zero-trade cycles) as the baseline, but with a substantially better profit factor of 1.46 vs 0.80.

---

## Per-Preset Interpretation

### v93_baseline
The V93 champion configuration with all feature flags OFF serves as the control. Over 100 cycles it produced 21 closed trades with a negative PnL of -$25.46 and a profit factor below 1.0 (0.80). Win rate was 38%, and 84% of cycles produced no trades. This is the floor the other presets are measured against. Notably all 21 trades were long-only — the short side appears suppressed in the current regime conditions (NORMAL/HIGH_VOL alternating).

### observability_only
Enabling only the decision-trace, confluence scoring, signal correlation monitoring, and anomaly detection features resulted in **zero trades across all 100 cycles** (100% zero-trade cycle rate). The anomaly detectors immediately flagged high signal correlations (SMA crossover ↔ funding rate at 0.84, SMA crossover ↔ Ollivier-Ricci at 0.93) and a zero-streak alert was triggered as early as cycle 38. The observability layer is too aggressive in its sit-out behavior — it identifies genuine structural issues (redundant signals, potential sign bugs in Ricci curvature vs Ollivier-Ricci at -0.99 correlation) but suppresses all trading as a result. This preset is a **regression** in production terms: zero revenue, though it surfaces real signal integrity problems worth fixing.

### embeddings_only (WINNER)
Enabling only `decision_embeddings` and `llm_trade_review` features produced **+$51.78 PnL** with a profit factor of 1.46, the only preset to clear the 1.0 PF threshold. Trade count matched the baseline exactly (21 closed), indicating similar activity without sacrificing participation rate. The embedding-augmented trade review appears to improve trade quality — gross profit of $164.39 vs gross loss of $112.61. Win rate (33%) was slightly lower than baseline (38%), but the average win was significantly larger relative to average loss, explaining the better PF. This preset is a **net improvement** and warrants promotion for further validation.

---

## Key Observations

1. **Signal redundancy is real**: The observability preset detected highly correlated signals (SMA/funding_rate at 0.84, Ricci variants at -0.99). These should be investigated and deduplicated before enabling observability features in production, as the current thresholds fully suppress trading.

2. **Short-side suppression**: All three presets showed 100% long-only trades. The BULL/NORMAL regime thresholds (long=0.05, short=0.20) appear to be suppressing shorts entirely in the current market conditions.

3. **embeddings_only PF 1.46 is promising** but below the 1.5 green threshold. It represents a meaningful improvement over the <1.0 baseline without adding observable overhead to trade frequency.

4. **observability_only needs threshold tuning**: The sit-out suppression is too broad. Correlation anomaly thresholds and zero-streak alert sensitivity should be calibrated before re-running, possibly via `--presets observability_tuned` once parameters are adjusted.

---

## Raw Data

| File | Path |
|---|---|
| Summary JSON | `data/ablation_20260411T100444/summary.json` |
| v93_baseline results | `data/ablation_20260411T100444/v93_baseline_results.json` |
| observability_only results | `data/ablation_20260411T100444/observability_only_results.json` |
| embeddings_only results | `data/ablation_20260411T100444/embeddings_only_results.json` |
