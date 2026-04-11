# Omega TODO

Tracking all in-flight work across training iterations, observability, reasoning, and platform.

## Version Scoreboard (current bests)

| Version | PnL | WR | Trades | PF | Notes |
|---------|-----|-----|--------|-----|-------|
| **V93** | **+$130.91** | **48%** | **60** | **2.40** | CHAMPION — SUI blacklist, short=0.07 |
| V92 | +$126.75 | 46% | 76 | 1.49 | Multi-asset breakthrough (NEAR/ARB added) |
| V75 | +$110.90 | 100% | 3 | ∞ | Crisis only (3 lucky shorts) |
| V97 | +$94.14 | 32% | ? | ? | Geometry modifiers regressed |
| V63 | +$81.43 | 47% | 36 | 1.71 | Pre-crisis mixed regime |

## Feature Flag Status

`VICTORIA_FEATURES=<preset>` or `--features <preset>` to `run_training.py`.

| Flag | Default | What it does | Source |
|------|---------|-------------|--------|
| `ricci_sizing` | OFF | Reduce long sizes when approaching crash manifold | V95 / main |
| `orc_stress_reduction` | OFF | Reduce all sizes when ORC kappa > 0.1 (contagion) | V95 / main |
| `geodesic_crash_distance` | OFF | Raise long_thresh when crash_prox ≥ 0.6 | V95 / main |
| `fiedler_conviction_modulation` | OFF | Fragmented→lower short, consensus→lower both thresholds | V95 / main |
| `decision_traces` | OFF | Write per-ticker DecisionTrace JSONL each cycle | strange-clarke |
| `signal_confluence` | OFF | ConfluenceAnalyzer: boost/dampen sizes by signal agreement | strange-clarke |
| `signal_correlation_monitor` | OFF | 50-cycle rolling Pearson matrix, saved to /tmp | strange-clarke |
| `anomaly_detector` | OFF | 3σ deviation alerting on pnl_delta, trades, zero_streak | strange-clarke |
| `decision_embeddings` | OFF | KMeans cluster bias applied to conviction at inference | hopeful-mendeleev |
| `llm_trade_review` | OFF | Post-trade LLM post-mortem → data/decision_traces/ | hopeful-mendeleev |
| `v96_crisis_detection_fix` | OFF | bear_prob=-1 → trust regime_label directly | elastic-buck |
| `v96_multi_cycle_bypass` | OFF | Lower normal-short bypass threshold 0.09→0.07 | lucid-pascal |

**Presets**: `v93_baseline` (all OFF) · `v97_geometry` · `observability_only` · `embeddings_only` · `v98_full_obs` · `v99_full`

**V99 baseline run** (verify refactor is clean, should match V93):
```bash
python scripts/run_training.py --version v99 --cycles 200 --sleep 10 --features v93_baseline
```

**Ablation** (compare presets side-by-side — do not run yet):
```bash
python scripts/ablate.py --cycles 200 --presets v93_baseline,v97_geometry,observability_only
```

## In Progress

### ✅ V98 — Full observability launch (DONE — gates FAILED)
- Completed 200 cycles, PnL -$112, WR 32%, 34 trades
- Gates failed: pnl_floor (-$112 < -$92 baseline) + regime_parity[normal]
- All 34 trades were longs (0 shorts) — conviction drought 85% zero-trade cycles
- Anomaly detector (>3σ deviation warnings)
- Ricci / ORC / geodesic / Fiedler geometry modifiers
- Session: `local_23e03b9d-fe5f-418e-9260-c0f442b070c7`

## High-Leverage Next (parallel tracks)

### Track A — Long-horizon training run (500-1000 cycles)
- **Why:** Every run is ~55 min of live market. ML combiner needs 30+ closed trades before it activates. IC-weighted signals need real history.
- **How:** `python3 scripts/run_training.py --version v99 --cycles 500 --sleep 10`
- **Prereq:** V98 must finish first (to validate observability doesn't break)
- **Success:** ML combiner becomes active, generates first IC-weighted composite overrides
- **Owner:** TBD

### ✅ Track B — LLM brain wire-up
- **Status:** DONE — `omega/core/llm_shell.py` + `omega/nodes/victoria/llm_trade_review.py`
- **No API key needed** — uses `claude` CLI (Claude Code) via subprocess. Auth handled by existing CC login session.
- **llm_shell.py**: thin subprocess wrapper. `invoke(prompt, model="deep")` → str. Shell-first, API key fallback.
- **AnthropicBrain**: refactored to shell-first (`_shell_consult`) → urllib fallback (`_urllib_consult`). `is_available()` returns True if either transport ready.
- **llm_trade_review.py** reads trades CSV + decision JSONL → calls Claude (deep) → writes `data/decision_traces/{version}_llm_review.md`
- **Usage:** `python -m omega.nodes.victoria.llm_trade_review --version v98`
- Falls back to rule-based summary if no CLI or API key.

### ✅ Track C — Vectorized decision embeddings
- **Status:** DONE — `omega/nodes/victoria/decision_embeddings.py`
- `DecisionEmbedder`: KMeans clustering on signal_vec + regime_onehot + geometry + conviction_score
- Per-cluster WR/PnL → `bias` in [-0.5, +0.5] → `adjusted = raw_conviction * (1.0 + bias)`
- Fit: `python -m omega.nodes.victoria.decision_embeddings --version v98`
- Requires numpy + scikit-learn (degrades to no-op if absent)
- **Next:** Wire `cluster_bias()` call into `strategy.py` conviction filter for V100+

### Track D — Go WebSocket streaming
- **Why:** Live dashboard updates. Currently must refresh. Low effort / high QoL.
- **How:** Add WebSocket handler to Go API at `/ws/v1/training/{version}`. Push progress every 5 cycles instead of client polling.
- **Files:** `internal/handler/training_handler.go`, `dashboard/src/pages/TrainingAnalysis.tsx`
- **Success:** Dashboard shows live cycle updates without refresh
- **Owner:** TBD

### Track E — Geometry modifier forensics
- **Why:** V97 (with geometry) was $94 vs V93 (without) $131. The modifiers are actively hurting in current market conditions.
- **How:**
  1. Run V93 config + V97 config side-by-side on same data
  2. Isolate which of the 4 modifiers caused the regression: Ricci, ORC, geodesic, or Fiedler
  3. Either fix or gate them behind a regime condition
- **Files:** `omega/nodes/victoria/strategy.py`, `omega/nodes/victoria/geometry/`
- **Success:** Geometry modifiers add PnL or are disabled by default
- **Owner:** TBD

## Lower Priority

### Track F — Coinbase/OKX WebSocket feeds (replace REST polling)
- Replaces REST with WebSocket subscriptions for real-time prices + funding rates
- Eliminates rate limits entirely for market data

### Track G — On-chain data via Reth node
- Stand up Reth Ethereum mainnet node + indexer
- Gives us free whale flows, exchange inflows, liquidation cascades (vs $99/mo Glassnode)

### Track H — Historical backtest expansion
- Backtest harness exists (446 lines) but only tested against fresh data
- Build cached OHLCV corpus (30-90 days across all symbols)
- Validates changes in seconds instead of 55-min live runs

### Track I — Multi-agent architecture
- Docs exist (`docs/architecture/agent-intelligence-architecture.md`)
- Build Reason/Remember/Act agent layers in Go
- Each "desk" = dedicated agent with memory + LLM reasoning

## Recently Shipped (today)

- ✅ Feature flag harness — `omega/nodes/victoria/features.py` + `VictoriaFeatures.from_env()`
- ✅ `scripts/ablate.py` — multi-preset ablation runner with comparison table
- ✅ Worktree consolidation — strange-clarke (observability stack), hopeful-mendeleev (LLM/embeddings) cherry-picked to main with feature flags
- ✅ V98 V95 geometry gated (ricci_sizing, orc_stress_reduction, geodesic_crash_distance, fiedler_conviction_modulation)
- ✅ V96/V97 fixes gated (v96_crisis_detection_fix, v96_multi_cycle_bypass)
- ✅ `llm_trade_review.py` — LLM post-trade post-mortem (Track B)
- ✅ `decision_embeddings.py` — KMeans decision clustering + conviction bias (Track C)
- ✅ FRED SQLite data cache + daily fetch
- ✅ OKX + Coinbase INTX funding rate fallback chain
- ✅ DXY switched from yfinance to FRED DTWEXBGS
- ✅ Multi-asset basket (NEAR, ARB, SUI added)
- ✅ Conviction-proportional position sizing
- ✅ Regime transition cooldown (3-cycle pause)
- ✅ `_thresh_scale` cap [0.5, 1.5] — fixed V94 regression
- ✅ Crisis short bypass (composite < -0.07)
- ✅ Half-Kelly crisis sizing
- ✅ IC-weighted signal aggregation
- ✅ Portfolio risk caps (80%/15%)
- ✅ Trade replay dashboard panel
- ✅ 446-line historical backtest harness
- ✅ 14 stale worktrees cleaned
- ✅ Ollivier-Ricci curvature + brain evaluator
- ✅ Decision trace system (per-ticker per-cycle JSONL)
- ✅ Signal confluence detector
- ✅ Signal correlation monitor + Go endpoint
- ✅ Anomaly detector (>3σ warnings)
- ✅ Decision Replay dashboard tab

## Champion Configuration (V93 baseline)

```
long_thresh_normal = 0.10
short_thresh_normal = 0.07
long_thresh_crisis = 0.50 (hard block effectively)
short_bypass_crisis = composite <= -0.07
_thresh_scale = max(min(basket_std/0.20, 1.5), 0.5)
half_kelly_crisis = True
regime_cooldown_cycles = 3
blacklist = {BTC, DOT, MATIC, XRP, SUI}
active_basket = {ETH, SOL, BNB, AVAX, LINK, NEAR, ARB, ADA}
```

## Update Log
- 2026-04-11: TODO.md created. V98 running, V97 regressed, V93 remains champion.
</content>
</invoke>