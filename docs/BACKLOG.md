# Omega Tactical Backlog

> Tracks completed work and upcoming items at the implementation level.
> For the 12-month strategic roadmap see `omega-strategic-backlog.md`.

---

## Session: 2026-03-28 (Final Round)

### Completed ✅

| Item | Notes |
|------|-------|
| ✅ Ring 1 cosine similarity adversarial gate fix | `omega/core/adversarial_v2.py` — cosine similarity was firing every cycle due to incorrect dot-product logic; now uses proper unit-vector cosine; gate no longer chronically triggers |
| ✅ `long_short_ratio` continuous signal fix | `omega/nodes/victoria/signal_generation.py` — was hard binary ±1; now continuous ratio with rolling z-score normalization |
| ✅ `basic_signals` dampening | `omega/nodes/victoria/signal_generation.py` — 0.3× dampening scalar + EWM smoothing prevents amplitude spikes triggering adversarial gate |
| ✅ `basic_signals` structural refactor | `omega/nodes/victoria/signal_generation.py` — stateless function + explicit context object pattern; eliminates implicit shared state between signal functions |
| ✅ DAG parallel pipeline rebuilt | `omega/core/dag_pipeline.py` — asyncio DAG executor with dependency-layer grouping for concurrent signal execution (was lost in worktree merge; now canonical) |
| ✅ V19 live monitoring | Progressive training run with fixed adversarial gate + continuous signals; monitoring via Grafana |
| ✅ Grafana dashboard provisioning | `deploy/grafana/provisioning/` — datasource + dashboard JSON auto-provisioned via docker-compose; no manual UI steps |
| ✅ Go CLI refresh (8 subcommands) | `cmd/omega/` — `run`, `status`, `nodes`, `signals`, `brain`, `train`, `backtest`, `markets` subcommands with consistent flag patterns |
| ✅ Startup validation system | `omega/core/startup_checks.py` — checks API keys, DB connectivity, signal module imports, and dependency versions at boot; fails fast with clear error messages |
| ✅ Smart money signal (Binance leaderboard + Polymarket top traders) | `omega/nodes/victoria/information_flow.py` + `omega/nodes/polymarket/top_traders.py` — tracks top-decile trader positioning as directional prior |
| ✅ Polymarket CLOB integration | `omega/nodes/polymarket/clob_client.py` — order book depth, best bid/ask, mid-price polling from Polymarket CLOB REST API |
| ✅ Top trader tracking research | `docs/ideas/quantscience-tweet-*.md` — analysis of Binance leaderboard scraping and Polymarket top trader API endpoints |
| ✅ AlphaEar skills research | `docs/research/alphaear_skills.md` — ISQ metric definition, signal lifecycle FSM, per-node skill registry design |
| ✅ 5 worktree consolidation rounds | Merged DAG pipeline, Ring 1 fix, continuous signals, smart money, and startup validation branches back to main |

---

## Session: 2026-03-28

### Completed ✅

| Item | Notes |
|------|-------|
| ✅ Cross-sectional momentum factor (Jegadeesh-Titman) | `omega/nodes/victoria/momentum_factor.py` — rank-based XS momentum with formation/holding period config |
| ✅ Natural gradient signal optimizer (Fisher information matrix) | `omega/nodes/victoria/natural_gradient.py` — geodesic parameter updates on the signal manifold |
| ✅ Fiedler position size modifier (spectral graph stress → sizing) | `omega/nodes/victoria/` — graph Laplacian on correlation matrix; Fiedler value as dynamic position scalar |
| ✅ Historical backtest harness | `scripts/historical_backtest.py` + `omega/eval/` — OHLCV-based backtest with Sharpe/max-DD reporting |
| ✅ Dashboard intelligence page (Bloomberg-style) | `dashboard/src/pages/` — signal table, regime indicator, live/backtest reconciliation panel |
| ✅ Wire LLM brain with API key | `internal/brain/anthropic.go` — `CLAUDE_API_KEY` alias + parent-dir `.env` walk; fixed for Victoria cycles |
| ✅ Per-node skills framework (AlphaEar-inspired) | `omega/core/skill_loader.py`, `omega/nodes/shared/` — SkillRegistry, SignalEvolution FSM, ISQ scoring, RAG retrieval |
| ✅ Laloux RMT paper-grade denoising | `omega/nodes/victoria/rmt_denoiser.py` — Ledoit-Wolf shrinkage + Tracy-Widom threshold + eigenportfolios |
| ✅ DAG parallel signal pipeline | `omega/core/` — asyncio DAG executor, signals grouped by dependency layer, concurrent execution |
| ✅ FinBERT sentiment signal | `omega/nodes/victoria/news_signals.py` — FinBERT embeddings over news headlines, rolling sentiment z-score |
| ✅ Cross-asset z-score normalization fix | `omega/nodes/victoria/` — fixed additive drift in cross-asset normalization; standardized to rolling 252-day window |
| ✅ `trade_id` schema bug fix | `internal/db/schema.go` / `internal/db/writes.go` — missing column added, migration applied |
| ✅ Adversarial threshold raised 0.20 → 0.40 | `omega/core/adversarial_v2.py` — reduces false-positive rejections that were blocking V18 training |
| ✅ `DATABASE_URL` wired into `.env` | `.env.example` updated; Go startup logs DB host on connect |
| ✅ ImprovementEngine evaluator fix | `omega/core/improvement_engine.py` — `SyntheticEvaluator` set as default; evaluator no longer returns `None` |
| ✅ AlphaEar research doc | `docs/ideas/` — skills framework design, ISQ metric definition, signal lifecycle states |
| ✅ Multiple worktree consolidation rounds | Merged per-node-skills, Fiedler, V18 pre-flight branches back to main |
| ✅ V16 / V17 / V18 training runs | Progressive backtest runs; V18 includes Fiedler sizing + adversarial threshold fix |

---

### New Items Added

#### High Priority

- [ ] **Kronos-style time-series foundation model integration**
  Source: AlphaEar research doc. Pre-trained TSF model (Chronos / Moirai) as a signal source — zero-shot regime prediction and anomaly detection. Replaces hand-crafted GARCH baselines.
  *Relates to: EPIC-013 (LLM-as-Analyst), EPIC-014 (Geometric Math Library)*

- [ ] **Historical backtest validation of geometric signals vs momentum baseline**
  Run the Jegadeesh-Titman XS momentum, natural gradient optimizer, and Fiedler sizing against the V14 buy-and-hold and simple-momentum baselines on the 3 historical windows. Sharpe, max-DD, Calmar, and IC decomposition required.
  *Prerequisite for trusting any geometric signal in production*

- [ ] **Integration test coverage for all signal types**
  Each signal module (`momentum_factor`, `natural_gradient`, `rmt_denoiser`, `news_signals`, `spectral_signals`, `stablecoin_signals`, `vrp_signal`) needs a minimum integration test: real OHLCV input → valid output schema, no NaN/inf, consistent shape.
  *Relates to: EPIC-023 (Data Pipeline Integrity)*

#### Medium Priority

- [ ] **News-projection layer (bias predictions with news embeddings)**
  Use FinBERT embeddings to project news sentiment onto each signal's historical IC — weight signal contributions by news-alignment score. Treats the LLM-derived sentiment as a soft prior over signal relevance.
  *Extension of FinBERT signal completed this session*

- [ ] **Dashboard: signal evolution visualization (EMERGING → STABLE → FALSIFIED states)**
  The per-node skills framework defines signal lifecycle FSM states. Surface these in the dashboard intelligence page — sparkline IC trend, current state badge, last-transition timestamp, and reason.
  *Requires ISQ metric written to DB per cycle*

- [ ] **Attention router empirical training**
  `NewAttentionRouter()` initialises `RoutingWeightAdapter` as `nil` (EPIC-025 partial fix applied). Need: collect 1000+ `(goal, routing, outcome)` tuples from V18+ runs, then offline-train EMA priors and load them at startup.
  *Relates to: EPIC-016 (Coordination Layer v2)*

- [ ] **Cross-project memory bus (Victoria ↔ Polymarket)**
  Victoria regime state (trending/mean-reverting/volatile) is a useful prior for Polymarket edge detection. Wire `MemoryBus` so Polymarket node can subscribe to Victoria regime events. Define shared schema for cross-node memory payloads.
  *Relates to: EPIC-017 (Cross-Node Composition)*

---

## Open Items (Carried Forward)

> Items from prior sessions still open. See `omega-strategic-backlog.md` for full specs.

| ID | Item | Priority | Status |
|----|------|----------|--------|
| ACTION-006 | Fix REST autonomy gate (`GET /api/v1/nodes` blocked at PICO) | P0 | Open |
| ACTION-007 | Fix `Tracer.end_span()` type confusion (TraceContext vs str) | P2 | Open |
| ACTION-009 | Confirm StateService → Postgres connection (0 rows in DB) | P1 | Open |
| ACTION-010 | Wire `AdversarialPressureV2` in `_step_adversarial()` | P1 | Open |
| ACTION-011 | Wire `GoalArchitecture` into cycle | P2 | Open |
| ACTION-012 | Fix Python trace IDs to W3C-compliant format | P2 | Open |
| ACTION-013 | Wire memory kernel to cycle output | P3 | Open |
| ACTION-014 | Populate adversarial structural challenges (concentration, staleness, correlation) | P2 | Open |
| ACTION-015 | OOS contamination — add third TPE split (train/validate/test) | P2 | Open |
| EPIC-001 | Deploy OTLP backend (Grafana Cloud or self-hosted LGTM) | P0 | Not started |
| EPIC-004 | Safety violation persistence to Postgres | P1 | Not started |
| EPIC-023 | Data pipeline integrity (multiplicative equity curve, look-ahead bias, freshness guard) | P0 | Partial |
| EPIC-024 | Security hardening (default creds, unauth RPC endpoints, audit log) | P1 | Not started |
| EPIC-025 | Self-improvement loop completion (apply_params, goal architecture, ring-1 temporal) | P1 | Partial |

---

## Completed Archive

### 2026-03-27 and earlier

- ✅ AlphaEar skill infrastructure (SkillRegistry protobuf, `node_skills.py`)
- ✅ Spectral graph signals (Laplacian eigenvalue features)
- ✅ Stablecoin flow signals (USDT/USDC issuance momentum)
- ✅ VRP signal (variance risk premium from options data)
- ✅ Liquidation cascade signals
- ✅ Pairs signals (cointegration-based mean reversion)
- ✅ Carry signals
- ✅ Derivatives signals (open interest, funding rate)
- ✅ Alt-data signals framework
- ✅ Victoria V14–V16 runs (progressive backtest series)
- ✅ Multi-project platform architecture (project isolation, per-project nav)
- ✅ Go/Python pipeline bridge (`pipeline_client.go`, `pipeline_server.py`)
- ✅ Intelligence instrumentation design (`docs/superpowers/specs/`)
- ✅ Victoria dashboard (Bloomberg-style trading pages, portfolio, signals, backtest)
- ✅ Paper trading engine (`omega/nodes/victoria/paper_trading.py`)
- ✅ `make dev` target (Postgres + Python bridge + Go API in one command)
- ✅ ImprovementEngine wired to VictoriaNode (ACTION-003)
- ✅ Project-driven `runCycle` (ACTION-001)
- ✅ CLI per-step results with `--cycles N` flag (ACTION-005)
