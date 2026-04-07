# Omega Improvement Backlog

> **Authoritative backlog** — 6-dimension framework covering all identified improvements.
> Incremental session log lives in `docs/BACKLOG.md`.
> Strategic 12-month roadmap: `omega-strategic-backlog.md`.
> Architecture target state: `docs/architecture/agent-intelligence-architecture.md`.
> Research pipeline: `docs/research/`.

**Last updated:** 2026-04-08 (V71)
**Current training version:** V66 (in progress)
**Last completed:** V65 (-$212.93, 33% WR — ETH:normal long bias in downtrend; fixed in V66)
**Next training target:** V67 (yield curve + signal decay + ML combiner expansion + trailing stop-loss)

---

## Dimension 1 — Alpha Research (Signals)

### Completed [x]

- [x] **SMA crossover** — proportional ratio signal (not binary ±1) `signal_generation.py` (V1.0)
- [x] **RSI 14-day** — continuous `(50-rsi)/50` mapping `signal_generation.py` (V1.1)
- [x] **MACD crossover** — histogram/price normalized `signal_generation.py` (V1.2)
- [x] **Bollinger Bands** — continuous deviation from mid `signal_generation.py` (V1.2)
- [x] **Z-score momentum** — return z-score with 2σ band `signal_generation.py` (V1.2)
- [x] **Volume z-score** — mean-reversion signal (high vol = bearish) `signal_generation.py` (V1.1)
- [x] **BTC beta** — per-asset beta to BTC × BTC signal `signal_generation.py` (V1.2)
- [x] **Volatility regime** — annualised vol vs 90-day; low-vol signal only `signal_generation.py` (V1.2)
- [x] **Funding rate signal** — CoinGecko derivatives z-score; negative funding = bullish `signals/funding_rate.py` (V64)
- [x] **Fear & Greed Index** — Alternative.me 30-day z-score; contrarian ±1.5σ `signals/fear_greed.py` (V65)
- [x] **DXY correlation signal** — 20-day BTC/DXY Pearson; fires when corr < -0.5 `signals/dxy_signal.py` (V65)
- [x] **Exchange flow stub** — Glassnode/CryptoQuant API contracts documented `signals/exchange_flow.py` (V65)
- [x] **Order flow signal** — bid/ask imbalance, trade flow `signals_advanced.py`
- [x] **Cross-asset signal** — multi-asset correlation cluster `signals_advanced.py`
- [x] **RMT denoising** — Random Matrix Theory eigenvalue cleaning `rmt_denoiser.py` (V23)
- [x] **Smart money signal** — wallet clustering, accumulation pattern `victoria_node.py` (V20)
- [x] **FinBERT sentiment** — BERT-based crypto news sentiment `finbert_sentiment.py` (V21)
- [x] **Whale flow signal** — large-wallet on-chain tracking `victoria_node.py` (V22)
- [x] **Timeseries forecast** — LCG bootstrap conformal prediction intervals `timeseries_forecast.py` (V22)
- [x] **Geodesic curvature signal** — Riemannian curvature of signal manifold `curvature_signal.py` (V23+)
- [x] **Spectral graph / Fiedler signal** — Laplacian λ₂ fragmentation indicator `spectral_signals.py`
- [x] **Stablecoin flow signals** — USDT/USDC issuance momentum `stablecoin_signals.py`
- [x] **VRP signal** — variance risk premium from options implied vol `vrp_signal.py`
- [x] **Liquidation cascade signals** — open interest + liquidation momentum `liquidation_signals.py`
- [x] **Pairs signals** — cointegration mean-reversion `pairs_signals.py`
- [x] **Carry signals** — cross-asset carry arbitrage `carry_signals.py`
- [x] **Derivatives signals** — OI, put/call ratio, futures basis `derivatives_signals.py`
- [x] **Alt-data signals framework** — pluggable alternative data connectors `alt_data_signals.py`
- [x] **News projection layer** — 9-topic keyword classifier × IC multipliers `news_projection.py` (V29)
- [x] **Conformal calibrator** — split-conformal prediction intervals `conformal_calibrator.py` (V30)
- [x] **Unusual Whales skeleton** — options flow, dark pool, congressional trading `unusual_whales_node.py`
- [x] **ML signal combiner** — Ridge regression replaces equal-weight composite `ml_combiner.py` (V64)
- [x] **Multi-cycle confirmation** — enter only if prior cycle same direction `strategy.py` (V63)
- [x] **Absolute conviction floor** — 0.12 min regardless of regime `strategy.py` (V63)
- [x] **ETH long suppression in high_vol** — all 5 worst V63 trades `strategy.py` (V65)
- [x] **LONG blacklist** — BTCUSDT, LINKUSDT, MATICUSDT, DOTUSDT `strategy.py` (V63+)
- [x] **Regime-adaptive thresholds** — crisis/bull/normal per-direction thresholds `strategy.py` (V53+)
- [x] **Cross-sectional demeaning** — basket-mean subtracted per cycle `strategy.py` (V35 breakthrough)
- [x] **Conviction-weighted sizing** — continuous `(w_conv/0.25)` ∈ [0.5,2.0] scale `strategy.py` (V65)

### Pending [ ]

- [x] **VIX signal** — CBOE `^VIX` via yfinance; threshold + z-score modes; capitulation reversal at VIX>35 for 3+ days `signals/vix_signal.py` (V66)
- [x] **Yield curve signal** — FRED `DGS2`/`DGS10` 2s10s spread; inversion/steepening/shock modes; 4h cache `signals/yield_curve.py` (V67)
- [x] **SPY correlation signal** — BTC/SPY 20d rolling Pearson; fires when corr > 0.4; 4h SPY momentum → risk-on +0.3 / risk-off -0.3 `signals/spy_signal.py` (V71)
- [ ] **Gold signal** — BTC/XAU co-movement as inflation-hedge regime identifier. yfinance `GC=F`. **Priority: Low**
- [ ] **Exchange flow signal (live)** — Wire Glassnode/CryptoQuant API; stub exists at `signals/exchange_flow.py`. Requires API key (`GLASSNODE_API_KEY`). **Priority: High when key available**
- [ ] **Unusual Whales live data** — Complete `unusual_whales_node.py` once API key obtained. Options flow + dark pool alpha. **Priority: High when key available**
- [ ] **TimesFM / Chronos zero-shot forecast** — Google/Amazon time-series foundation models as drop-in forecast signal. Replace hand-crafted GARCH. **Priority: Medium**
- [ ] **Synthetic DXY basket** — Compute DXY from individual FX pairs (EURUSD, USDJPY, GBPUSD) via yfinance to avoid single-ticker dependency. See `docs/research/cross-asset-signals.md §1`. **Priority: Low**
- [ ] **Gauge theory / fiber bundle arb** — Research from `docs/research/2026-03-30-gauge-theory-fiber-bundles-arbitrage.md`. Triangular arbitrage on correlated assets using connection curvature. **Priority: Research**
- [ ] **Persistent homology / TDA crash prediction** — Research from `docs/research/2026-04-06-persistent-homology-tda-crash-prediction.md`. Topological data analysis for regime change detection. **Priority: Research**
- [ ] **Intraday DXY lead** — 1h DXY bars (Twelve Data free tier) to capture London session leads 2-6h ahead of crypto. **Priority: Low**

---

## Dimension 2 — Signal Intelligence (ML / Weighting)

### Completed [x]

- [x] **Dynamic weight allocator** — IC-EMA rolling weights per signal `dynamic_weights.py`
- [x] **IC decay detection** — EMA IC below floor triggers signal retirement `intelligence_metrics.py` (V30)
- [x] **AttentionRouter weight decay** — EMA decay prevents stale signal over-emphasis `attention_router.go`
- [x] **Signal retirement** — auto-zero routing weight on IC decay `attention_router.go` (V30)
- [x] **ML signal combiner (Ridge)** — 30-sample min, online refit, persist to JSON `ml_combiner.py` (V64)
- [x] **Combiner update from closed trades** — `update_combiner()` called on trade PnL `signal_generation.py` (V64)
- [x] **News projection IC multipliers** — topic × signal IC nudges `news_projection.py`, `dynamic_weights.py` (V29)
- [x] **Signal waterfall logging** — per-trade sub-signal values to `/tmp/{version}_trade_details.jsonl` (V65)
- [x] **ML weight snapshots** — every-20-cycle combiner weight dump to metrics JSONL (V65)
- [x] **Cross-asset signals in metric row** — fear_greed, funding_rate, dxy per cycle (V65)
- [x] **Rolling IC per signal (SignalDecayDetector)** — 20-trade Pearson IC, decay/anti-predictive warnings, persists to `data/signal_ic_history.json` `signal_decay.py` (V67)

### Pending [ ]

- [x] **ML combiner feature expansion** — Added `funding_rate_signal`, `fear_greed_signal`, `dxy_signal`, `vix_signal`, `yield_curve_signal` to `SIGNAL_KEYS` in `ml_combiner.py`. All 5 cross-asset market-level signals now feed Ridge regression (V67)
- [ ] **Per-regime ML weights** — Train separate Ridge models per regime (crisis/normal/high_vol) rather than pooled. Crisis regime signals differ fundamentally from normal. **Priority: Medium**
- [ ] **Signal IC backtesting** — Offline IC analysis over historical training runs; identify which signals contributed alpha across which regimes. Use `data/v*_signal_contribs.jsonl` files. **Priority: Medium**
- [ ] **Wasserstein K-means regime detector** — Better than HMM for non-Gaussian crypto regimes. Research saved in `docs/ideas/`. **Priority: Medium**
- [ ] **TimesFM / Chronos integration** — Zero-shot time-series foundation model as forecast signal. Replaces current LCG bootstrap conformal predictor. **Priority: Medium**
- [ ] **Meta-Harness → decision trace loop** — Wire `meta_harness.py` to `DecisionTraceAnalyzer` output so harness can learn from actual decision outcomes. Currently separate. **Priority: Medium**
- [ ] **LLM-driven signal hypothesis generation** — Wire `AnthropicBrain` (claude-opus-4-6) to Alpha Research agent pattern library; LLM proposes signal hypotheses from market narratives. See `docs/architecture/agent-intelligence-architecture.md §2.1`. **Priority: Medium**
- [ ] **Sentiment pipeline** — LLM interprets crypto Twitter narratives → tradeable signal. See architecture doc. **Priority: Low**
- [ ] **OOS holdout gate enforcement** — `omega/eval/overfitting_gate.py` exists but is not integrated into `run_training.py`. Add gate check before saving results. **Priority: Medium**

---

## Dimension 3 — Risk Management

### Completed [x]

- [x] **Kelly position sizing** — half-Kelly from rolling 50-trade history `strategy.py` (V64)
- [x] **Conviction-weighted sizing** — continuous `w_conv/0.25` ∈ [0.5,2.0] multiplier `strategy.py` (V65)
- [x] **Asymmetric hold limits** — loss exits at 4 cycles, profit holds to 10 `paper_trading.py` (V65)
- [x] **Stop-loss** — 2% ROI floor per position `paper_trading.py`
- [x] **Sit-out circuit breaker** — N consecutive loss cycles halts trading `sit_out_breaker.py` (V30)
- [x] **Regime-adaptive conviction gates** — crisis hard-blocks longs (0.99 threshold) `strategy.py` (V53)
- [x] **Crisis short threshold lowered** — 0.05 → 0.02; crisis favors shorts `strategy.py` (V65)
- [x] **ETH long suppression in high_vol** — blacklist pattern on regime×symbol `strategy.py` (V65)
- [x] **Long blacklists** — BTCUSDT, LINKUSDT, MATICUSDT, DOTUSDT `strategy.py`
- [x] **Fiedler spectral size scaling** — λ₂ Laplacian fragmentation reduces position size `strategy.py`
- [x] **Time-of-day filter** — 22-00h UTC US-close reversal window, 50% size reduction `strategy.py`
- [x] **Vol-low sit-out** — zero position in < 20th percentile vol (no mean-reversion edge) `strategy.py`
- [x] **Vol-high sit-out** — 50% size reduction in > 80th percentile vol `strategy.py`
- [x] **Multi-cycle confirmation** — prevents whipsaw entries on single-cycle spikes `strategy.py` (V63)
- [x] **Max positions cap** — max_positions // 2 per side prevents capital dilution `strategy.py`
- [x] **PositionRiskManager** — `omega/core/risk_manager.py` enforces hard limits
- [x] **Conformal prediction intervals** — uncertainty-adjusted signals `conformal_calibrator.py` (V30)
- [x] **OOS overfitting gate** — mandatory 3-split TPE; blocks on OOS Sharpe < threshold `overfitting_gate.py` (V30)
- [x] **Adversarial debate gate** — cosine similarity check blocks contradictory proposals `adversarial/debate_gate.go`

### Pending [ ]

- [x] **Trailing stop-loss** — trail at 50% of MFE; fires when unrealized < 0.5×MFE and MFE > 0.5% of size. Prevents giving back large winners. `paper_trading.py` `mark_to_market()` (V67)
- [ ] **Per-symbol blacklist auto-update** — when a symbol generates 3+ consecutive losses, auto-add to a session blacklist. Currently manual. **Priority: Medium**
- [ ] **Regime-specific max hold** — tighter hold limit in crisis (max 3 cycles) since crisis is high-velocity. Currently uniform. **Priority: Medium**
- [ ] **Portfolio heat limit** — if total open notional > X% of capital, block new entries until positions close. Currently unlimited open count within max_positions. **Priority: Medium**
- [ ] **Correlation-aware position sizing** — reduce size when open positions are highly correlated (systemic risk). Fiedler scale is a proxy but doesn't account for existing position correlation. **Priority: Medium**
- [ ] **Slippage model** — current slippage = 0.0; add realistic model (0.05-0.15% depending on size/liquidity). Affects PnL accuracy. **Priority: Low**

---

## Dimension 4 — Observability & Traceability

### Completed [x]

- [x] **Structured JSONL metrics** — per-cycle JSON row → `/tmp/{version}_metrics.jsonl` `run_training.py`
- [x] **Signal contribution capture** — per-trade signal traces → `data/{version}_signal_contribs.jsonl` `run_training.py`
- [x] **Per-trade signal waterfall** — all sub-signal values + ML weights + filters → `/tmp/{version}_trade_details.jsonl` `run_training.py` (V65)
- [x] **ML weight snapshots** — combiner weights to metrics JSONL every 20 cycles `run_training.py` (V65)
- [x] **Cross-asset signal values in metric row** — fear_greed, funding_rate, dxy per cycle `run_training.py` (V65)
- [x] **Decision snapshot system** — `DecisionSnapshot` + `DecisionWriter` to SQLite + Postgres `decision_snapshot.py`
- [x] **Training watchdog** — zero-streak alerts, escalation ladder `training_watchdog.py` (V30)
- [x] **Training preflight checks** — data freshness, DB, signal imports validated before start `training_preflight.py` (V30)
- [x] **`print_training_diagnostics()`** — cycle-0 + every-10-cycle blocker analysis `run_training.py` (V30)
- [x] **Forensics tool** — `run_diff.py` two-run comparison: per-symbol PnL delta, conviction histogram, hypotheses `omega/tools/forensics/`
- [x] **Performance attribution** — PnL decomposed into alpha/beta/timing/selection; auto-generated after each training run → `data/{version}_attribution.json` `omega/nodes/victoria/performance_attribution.py` (V70+)
- [x] **V49 hard gates** — 6 gates (PnL, regime parity, drawdown, trade count, signal integrity, audit) `eval/v49_gates.py`
- [x] **OTel tracing** — `internal/telemetry/` distributed traces → Tempo → Grafana `make otel-up`
- [x] **Prometheus metrics** — `internal/observability/metrics.go` + Grafana dashboards `monitoring/grafana/`
- [x] **Node health scorer** — 5-component 0-100 composite `observability/node_health_scorer.go`
- [x] **Circuit breaker** — `observability/circuit_breaker.go` + degradation detection `observability/degradation.go`
- [x] **Heartbeat system** — Python nodes ping Go control plane every N seconds `heartbeat_client.py` + `heartbeat/handler.go`
- [x] **Signal performance tracker** — rolling IC/Sharpe/win-rate per signal `signal_performance.py`
- [x] **EMA intelligence metrics** — per-signal decay-aware scoring `intelligence_metrics.py`
- [x] **Decision trace analyzer** — `omega/core/analyzer.py` → attribution by signal + regime

### Pending [ ]

- [ ] **Dashboard wired to real API** — 27 pages exist but most consume mock data. Priority: DecisionTrace, NodeHealth, TradeAnalysis, VictoriaTrades. **Priority: High**
- [ ] **Live trade detail viewer** — Surface `/tmp/{version}_trade_details.jsonl` in dashboard. Per-trade signal waterfall visualization. **Priority: Medium**
- [ ] **ML weight chart** — Plot Ridge weights over training time from metrics JSONL snapshots. Shows which signals the combiner is learning to trust. **Priority: Medium**
- [ ] **Go layer end-to-end smoke test** — `omega run` → Python heartbeat client → Go heartbeat store → `GET /api/v1/heartbeats` round-trip. **Priority: High**
- [ ] **OTLP backend deployment** — Grafana Cloud or self-hosted LGTM stack. Currently OTel collector configured but no backend. **Priority: Medium** (`EPIC-001`)
- [ ] **Safety violation persistence** — write adversarial/safety events to Postgres. Currently in-memory only. **Priority: Medium** (`EPIC-004`)
- [ ] **Regime-by-regime PnL attribution** — automate the forensics tool to run after each training run and append to a rolling `docs/training/regime_attribution.csv`. **Priority: Medium**
- [ ] **Signal IC heatmap dashboard** — per-signal IC by regime, shown as a matrix. Identifies where each signal adds value. **Priority: Low**

---

## Dimension 5 — Platform (Go Services)

### Completed [x]

- [x] **Connect-RPC server** — `cmd/omega-api/` on port 8080; OrchestratorService, NodeService, MemoryService `internal/handler/`
- [x] **`omega run` CLI** — pure Go orchestrator CLI `cmd/omega/run.go`
- [x] **Heartbeat system** — `internal/heartbeat/store.go` + handler + Python client
- [x] **Decision trace store** — `internal/heartbeat/decisions.go` bounded ring buffer
- [x] **Lifecycle store** — `internal/heartbeat/lifecycle.go` node state transition ring
- [x] **Node health scorer** — `internal/observability/node_health_scorer.go` 5-component 0-100
- [x] **Circuit breaker** — `internal/observability/circuit_breaker.go`
- [x] **Degradation detector** — `internal/observability/degradation.go`
- [x] **Coord layer** — `internal/coord/` leader election, partition, work queue, sync
- [x] **AttentionRouter** — `internal/coordination/attention_router.go` EMA weights + decay
- [x] **StateService** — `internal/coordination/handler.go` state tensor + outcomes store
- [x] **Memory service** — `internal/handler/memory_handler.go` episodic + semantic read/write
- [x] **Go ↔ Python bridge** — `internal/bridge/pipeline_client.go` + `omega/bridge/pipeline_server.py`
- [x] **Auth middleware** — JWT + API key `internal/auth/`
- [x] **SSE streaming** — `internal/api/sse.go` server-sent events for dashboard live feed
- [x] **Training progress SSE stream** — `GET /api/v1/training/stream?version=vN` polls JSONL every 2s, streams new rows as SSE events, sends `complete` event when `results.json` appears `internal/handler/training_handler.go` (V70+)
- [x] **Terminal service** — `internal/terminal/` PTY-based shell execution via gRPC

### Pending [ ]

- [ ] **Vector memory service (Go)** — Migrate `omega/core/vector_memory.py` to `internal/memory/` Go service. Per spec: platform layer must be Go. **Priority: Medium** (`P2-001`)
- [ ] **Task scheduler (Go)** — Migrate improvement scheduler logic to `internal/coord/` Go service. **Priority: Medium** (`P2-001`)
- [ ] **Self-repair daemon (Go)** — `internal/observability/` Go process monitors node health and triggers recovery procedures. **Priority: Medium**
- [ ] **StateService → Postgres connectivity verification** — `ACTION-009`: confirm `internal/coordination/handler.go` writes state tensor rows; currently 0 rows in DB. **Priority: High**
- [ ] **REST autonomy gate fix** — `ACTION-006`: `GET /api/v1/nodes` blocked at PICO autonomy level. **Priority: Medium**
- [ ] **Dashboard heartbeat integration** — node cards show live/stale status from `/api/v1/heartbeats`; replace polling stub. **Priority: High**
- [ ] **Security hardening** — default creds, unauth RPC endpoints, audit log. `EPIC-024`. **Priority: Medium**
- [ ] **Go platform services E2E test** — `omega run` → full cycle → DB write → API read round-trip. **Priority: High**

---

## Dimension 6 — Multi-Agent Architecture

### Completed [x]

- [x] **Agent contract** — `execute()` / `evaluate()` / `improve()` three-method interface `omega/core/node.py`
- [x] **OmegaOrchestrator v2** — `orchestrator_v2.py` multi-node cycle coordination
- [x] **ImprovementEngine** — `improvement_engine.py` propose→evaluate→apply loop
- [x] **Meta-Harness** — `meta_harness.py` LLM-optional self-improvement iteration
- [x] **Conformance suite** — `omega/conformance/` 20+ scenario contracts
- [x] **SemanticMemoryNode** — `nodes/shared/semantic_memory.py` every-10-cycle consolidation
- [x] **Multi-project platform** — project isolation via YAML; Victoria + Polymarket nodes
- [x] **Brain providers** — Anthropic, OpenRouter, Ollama, Claude CLI, Codex CLI `internal/brain/`
- [x] **Per-node skill registry** — `omega/core/node_skills.py` + `omega/skills/` SKILL.md registry
- [x] **Polymarket node** — `omega/nodes/polymarket/` edge detection, CLOB client, weather ensemble
- [x] **Architecture doc** — full multi-agent design in `docs/architecture/agent-intelligence-architecture.md`

### Pending [ ]

- [ ] **Alpha Research Agent decomposition** — Decompose `victoria_node.py` monolith into specialized agents (alpha research, signal eval, risk, execution, portfolio construction). See architecture doc §2.1. **Priority: Low** (victoria_node.py is 113KB and tightly integrated; decompose after profitable training baseline established)
- [ ] **Signal Research Agent (Meta-Harness wired to decision traces)** — Connect `meta_harness.py` to `DecisionTraceAnalyzer` output. Currently harness runs independently. **Priority: Medium**
- [ ] **LLM research paper ingestion** — Automated quant paper summarization → signal hypotheses. Feeds Alpha Research Agent. **Priority: Low**
- [ ] **Polymarket weather ensemble** — `omega/nodes/polymarket/weather_ensemble.py` needs live weather API. **Priority: Medium**
- [ ] **DeepSeek R1 provider** — Add as low-cost reasoning brain option for meta-harness iterations. **Priority: Low**
- [ ] **Multi-agent coordination protocol** — Formalize the signal proposal protocol (Alpha agent publishes → Signal Research agent evaluates → Risk agent gates → Execution agent sizes). Currently implicit. **Priority: Low**
- [ ] **Node memory index** — Per-node vector embedding index for semantic memory retrieval (codedb-inspired). See `docs/ideas/2026-03-31-meta-harness-self-improvement.md`. **Priority: Low**

---

## Training Version History

| Version | Key Change | PnL | WR | Trades | Notes |
|---------|-----------|-----|----|--------|-------|
| V35 | Cross-sectional demeaning | +$151 | — | — | Breakthrough: bidirectional trades |
| V44 | Signal integrity test suite | — | — | — | Regression prevention |
| V48 | Regime-adaptive thresholds (V53 logic) | — | — | — | Baseline for V49 gates |
| V52 | Ring 1 adversarial gate fix | — | — | — | Gate no longer chronic |
| V53 | CRISIS hard-block longs (0.99 threshold) | — | — | — | Stopped crisis long bleeding |
| V55 | Wasserstein regime, news projection | — | — | — | Regime detection improved |
| V59 | Long threshold 0.10→0.13 (normal) | — | — | — | V58 WR was 37% on normal longs |
| V61 | Normal short threshold 0.05→0.10 | — | — | — | V59 DOT normals -$28.93 |
| V62 | MATICUSDT added to long blacklist | — | — | — | 16 zero-PnL trades |
| V63 | Multi-cycle confirmation + abs conv floor | +$81 | 47% | 36 | Best run to date |
| V64 | ML combiner + funding rate + Kelly sizing | -$31 | 37% | 54 | 71/200 crisis cycles hurt |
| V65 | ETH long suppression + asymmetric hold + crisis short threshold + conviction sizing | TBD | TBD | TBD | Not yet run |

### V64 Post-Mortem
- **Gate failures:** PnL floor (V63 +$81 → V64 -$31) and regime parity (normal: -$61, high_vol: -$3)
- **Crisis drag:** 71/200 cycles in crisis; crisis longs hard-blocked (correct), but 35 longs still placed in normal/high_vol with poor WR
- **Normal regime worst:** -$60.78 in normal — ML combiner over-fitted on short V63 history (only 36 trades), Ridge underfit in normal regime
- **Short side bright spot:** crisis shorts earned +$33.15 — asymmetric hold + lower short threshold in V65 targets this
- **Conviction problem:** Ridge combiner weights not yet differentiated (need 30+ trades per regime to calibrate)

### V65 Changes (committed, awaiting run)
1. ETH long suppression in high_vol (`strategy.py`)
2. Asymmetric hold: loss→4 cycles, profit→10 (`paper_trading.py`)
3. Crisis short threshold 0.05→0.02 (`strategy.py`)
4. Conviction-weighted sizing: continuous `(w_conv/0.25)` ∈ [0.5,2.0] (`strategy.py`)
5. FearGreedSignal wired (`signal_generation.py`)
6. DXYSignal wired (`signal_generation.py`)
7. Per-trade signal waterfall logging (`run_training.py`)

---

## Open Action Items

| ID | Item | Priority | Dimension |
|----|------|----------|-----------|
| ACTION-006 | Fix REST autonomy gate (`GET /api/v1/nodes` blocked at PICO) | P2 | Platform |
| ACTION-007 | Fix `Tracer.end_span()` type confusion (TraceContext vs str) | P2 | Observability |
| ACTION-009 | Confirm StateService → Postgres connection (0 rows in DB) | P1 | Platform |
| ACTION-011 | Wire `GoalArchitecture` into cycle | P2 | Multi-Agent |
| ACTION-012 | Fix Python trace IDs to W3C-compliant format | P2 | Observability |
| ACTION-013 | Wire memory kernel to cycle output | P3 | Multi-Agent |
| EPIC-001 | Deploy OTLP backend (Grafana Cloud or self-hosted LGTM) | P1 | Observability |
| EPIC-004 | Safety violation persistence to Postgres | P1 | Platform |
| EPIC-023 | Data pipeline integrity (equity curve, look-ahead bias, freshness guard) | P0 | Risk |
| EPIC-024 | Security hardening (default creds, unauth RPC, audit log) | P1 | Platform |

---

## Quick Reference: Next 3 Signals to Implement

1. **VIX** — `omega/nodes/victoria/signals/vix_signal.py` — yfinance `^VIX` — 2h build — medium alpha
2. **Exchange flow (live)** — `signals/exchange_flow.py` exists as stub — wire Glassnode API — 4h build — high alpha when available
3. **ML combiner feature expansion** — Add cross-asset keys to `SIGNAL_KEYS` in `ml_combiner.py` — 30min — free alpha from existing signals
