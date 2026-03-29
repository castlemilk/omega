# Omega Tactical Backlog

> Tracks completed work and upcoming items at the implementation level.
> For the 12-month strategic roadmap see `omega-strategic-backlog.md`.

---

## Session: 2026-03-28 (Epic Session — 50+ Items, V16→V23, $0→+$67 PnL)

### Completed ✅ — Full Session Summary

#### Signal Types (18 total)
| Item | Notes |
|------|-------|
| ✅ Cross-sectional momentum factor (Jegadeesh-Titman) | `omega/nodes/victoria/momentum_factor.py` — rank-based XS momentum with formation/holding period config |
| ✅ Natural gradient signal optimizer (Fisher information matrix) | `omega/nodes/victoria/natural_gradient.py` — geodesic parameter updates on the signal manifold |
| ✅ Fiedler position size modifier (spectral graph stress → sizing) | `omega/nodes/victoria/` — graph Laplacian on correlation matrix; Fiedler value as dynamic position scalar |
| ✅ FinBERT sentiment signal | `omega/nodes/victoria/news_signals.py` — FinBERT embeddings over news headlines, rolling sentiment z-score |
| ✅ Timeseries forecast signal | `omega/nodes/victoria/timeseries_forecast.py` — ARIMA/Prophet-based forward projection as directional signal |
| ✅ Whale flow signal | `omega/nodes/victoria/whale_signal.py` — on-chain large-wallet accumulation/distribution as size signal |
| ✅ Smart money signal (Binance leaderboard + Polymarket top traders) | `omega/nodes/victoria/information_flow.py` + `omega/nodes/polymarket/top_traders.py` — tracks top-decile trader positioning as directional prior |
| ✅ Spectral graph signals | Laplacian eigenvalue features for correlation regime detection |
| ✅ Stablecoin flow signals | USDT/USDC issuance momentum as macro liquidity signal |
| ✅ VRP signal | Variance risk premium from options data |
| ✅ Liquidation cascade signals | Large liquidation event detection and directional impact |
| ✅ Pairs signals | Cointegration-based mean reversion |
| ✅ Carry signals | Funding rate carry / basis carry |
| ✅ Derivatives signals | Open interest, funding rate, basis |
| ✅ Alt-data signals framework | `omega/nodes/victoria/alt_data_signals.py` — extensible alt-data ingestion |
| ✅ `long_short_ratio` continuous signal fix | Was hard binary ±1; now continuous ratio with rolling z-score normalization |
| ✅ `basic_signals` dampening | 0.3× dampening scalar + EWM smoothing prevents adversarial gate false-fires |
| ✅ `basic_signals` structural refactor | Stateless function + explicit context object; eliminates implicit shared state |

#### Platform & Architecture
| Item | Notes |
|------|-------|
| ✅ Per-node skills framework (AlphaEar-inspired) | `omega/core/skill_loader.py`, `omega/nodes/shared/` — SkillRegistry, SignalEvolution FSM, ISQ scoring, RAG retrieval |
| ✅ Cross-project memory bus (Victoria ↔ Polymarket) | `omega/core/memory_bus.py` — publish/subscribe regime state events across node boundaries |
| ✅ DAG parallel signal pipeline | `omega/core/dag_pipeline.py` — asyncio DAG executor, signals grouped by dependency layer, concurrent execution |
| ✅ Startup validator | `omega/core/startup_checks.py` — checks API keys, DB connectivity, signal imports, dependency versions at boot |
| ✅ Signal performance tracker | Per-signal IC, Sharpe, win rate, and regime attribution tracked across cycles |
| ✅ Multi-project platform architecture | Project isolation, per-project navigation, project-driven `runCycle` |
| ✅ Go/Python pipeline bridge | `pipeline_client.go`, `pipeline_server.py` — bidirectional RPC bridge |
| ✅ Go CLI refresh (8 subcommands) | `cmd/omega/` — `run`, `status`, `nodes`, `signals`, `brain`, `train`, `backtest`, `markets` |

#### Mathematics
| Item | Notes |
|------|-------|
| ✅ Laloux RMT paper-grade denoising | `omega/nodes/victoria/rmt_denoiser.py` — Ledoit-Wolf shrinkage + Tracy-Widom threshold + eigenportfolios |
| ✅ Cosine similarity adversarial gate | `omega/core/adversarial_v2.py` — proper unit-vector cosine; gate no longer chronically triggers |

#### Infrastructure & Data Resilience
| Item | Notes |
|------|-------|
| ✅ 6-provider data resilience | Binance → Bybit → CoinGecko → Coinbase → Kraken → CryptoCompare failover chain |
| ✅ Coinbase + Kraken providers | US-accessible exchange providers as 4th/5th priority fallbacks |
| ✅ Circuit breakers | Per-provider circuit breakers with exponential backoff |
| ✅ Stale data detection | Freshness guard per provider; staleness triggers failover |
| ✅ Polymarket CLOB integration | `omega/nodes/polymarket/clob_client.py` — order book depth, best bid/ask, mid-price polling |
| ✅ Grafana dashboard provisioning | `deploy/grafana/provisioning/` — datasource + dashboard JSON auto-provisioned via docker-compose |

#### Bug Fixes
| Item | Notes |
|------|-------|
| ✅ Ring 1 confidence filter / warmup grace period | New signals skip adversarial gate for first N cycles to build baseline stats; prevents chronic false fires |
| ✅ Ring 1 cosine similarity adversarial gate fix | Incorrect dot-product logic fixed; gate uses proper unit-vector cosine similarity |
| ✅ `trade_id` schema bug fix | `internal/db/schema.go` / `internal/db/writes.go` — missing column added, migration applied |
| ✅ `cross_asset` normalization fix | Fixed additive drift; standardized to rolling 252-day window |
| ✅ Adversarial threshold raised 0.20 → 0.40 | Reduces false-positive rejections that were blocking V18+ training |
| ✅ `DATABASE_URL` wired into `.env` | `.env.example` updated; Go startup logs DB host on connect |
| ✅ ImprovementEngine evaluator fix | `SyntheticEvaluator` set as default; evaluator no longer returns `None` |

#### Risk Controls
| Item | Notes |
|------|-------|
| ✅ PositionRiskManager | `omega/core/risk_manager.py` — 5-layer portfolio risk controls |
| ✅ Max drawdown protection | Hard stop at configurable max DD threshold |
| ✅ Correlation limits | Portfolio-level correlation cap prevents concentration risk |
| ✅ Vol-scaled position sizing | Position size inversely proportional to realized volatility |
| ✅ Kelly criterion sizing | `omega/math/kelly.py` — fractional Kelly with confidence weighting |

#### Dashboard & Observability
| Item | Notes |
|------|-------|
| ✅ Victoria dashboard (Bloomberg-style) | Trading pages, portfolio, signals, backtest, positions |
| ✅ Dashboard intelligence page | Signal table, regime indicator, live/backtest reconciliation panel |
| ✅ Polymarket dashboard page | Odds tracking, edge detection, bet history |
| ✅ Grafana provisioning | Auto-provisioned dashboards for nodes, memory, brain, challenges, Victoria |

#### Training Progression (V16 → V23)
| Run | Key Addition | Result |
|-----|-------------|--------|
| V16 | Fixed adversarial gate baseline | Stable baseline |
| V17 | + Continuous signals | Improved signal quality |
| V18 | + Fiedler sizing + adversarial threshold fix | Reduced gate false-fires |
| V19 | + Cosine similarity gate fix | Gate no longer chronic |
| V20 | + Smart money signal | Directional prior added |
| V21 | + FinBERT sentiment | News-driven signal layer |
| V22 | + Whale flow + timeseries forecast | 18-signal stack complete |
| **V23** | **+ RMT denoising + full risk controls** | **+$67 PnL with live data** |

#### Research & Analysis
| Item | Notes |
|------|-------|
| ✅ AlphaEar skills research | ISQ metric definition, signal lifecycle FSM, per-node skill registry design |
| ✅ Awesome-Finance-Skills research | Survey of open-source quant libraries applicable to Omega signal stack |
| ✅ Smart money tracking research | Binance leaderboard scraping and Polymarket top trader API endpoints |
| ✅ Tweet analysis × 2 | `docs/ideas/quantscience-tweet-*.md` — two tweet thread analyses feeding signal ideas |

#### Automation
| Item | Notes |
|------|-------|
| ✅ Trade analyzer | Automated trade outcome attribution by signal and regime |
| ✅ Attention router training | `NewAttentionRouter()` EMA prior training from routing/outcome tuples |
| ✅ Signal performance tracker | Automated per-cycle IC/Sharpe/win-rate tracking written to DB |

#### Worktree Management
| Item | Notes |
|------|-------|
| ✅ 5+ worktree consolidation rounds | Merged DAG pipeline, Ring 1 fix, continuous signals, smart money, startup validation, PositionRiskManager, Coinbase/Kraken branches back to main |

---

## Session: 2026-03-29 (Signal Intelligence Layer — News Projection + Conformal Forecast + Integration Tests)

### Completed ✅

#### Signal Intelligence
| Item | Notes |
|------|-------|
| ✅ **News-projection layer** | `omega/nodes/victoria/news_projection.py` — keyword topic classification (9 topics: macro, liquidation, derivatives, whale, sentiment, technical, onchain, news_positive, news_negative) → per-signal IC multipliers ∈ [0.70, 1.30] with EMA smoothing; zero ML dependencies |
| ✅ **`apply_news_prior()` on DynamicWeightAllocator** | `omega/nodes/victoria/dynamic_weights.py` — nudges IC EMAs by news-alignment multipliers; only adjusts signals with sufficient IC history; strength-gated (noop < 0.05) |
| ✅ **VictoriaNode step 3c wiring** | `omega/nodes/victoria/victoria_node.py` — `NewsProjectionLayer.project_from_signals()` called after RMT (step 3b); result wired to `apply_news_prior()`; `_news_dominant_topic` and `_news_strength` surfaced in signals dict |
| ✅ **Conformal prediction / bootstrap uncertainty intervals** | `omega/nodes/victoria/timeseries_forecast.py` — LCG deterministic bootstrap (50 samples) produces (p10, p50, p90) quantile intervals; `_uncertainty_score()` maps interval width to [0,1]; `_interval_adjusted_signal()` attenuates by zero-straddle fraction; forecast confidence penalised by `1.0 - 0.5 * uncertainty` |
| ✅ **Timeseries forecast raw output extended** | `compute()` now returns `avg_uncertainty`, `agg_p10`, `agg_p90` in raw dict; `regime_tag = "high_uncertainty"` when `avg_uncertainty > 0.7` |

#### Verification (P0 check)
| Item | Notes |
|------|-------|
| ✅ **Wasserstein / scipy dependency** | Confirmed resolved: `wasserstein_regime.py` uses `try/except ImportError` fallback to mean absolute deviation — no hard scipy requirement |
| ✅ **ACTION-010 already wired** | Confirmed `orchestrator_v2.py` already calls `self._adversarial.run_v2(...)` — no change needed |

#### Test Coverage
| Item | Notes |
|------|-------|
| ✅ **Integration test suite for all 20 signal types** | `tests/test_signal_integration.py` — real OHLCV input → valid SignalValue output, no NaN/inf, values in [-1, +1]; all network mocked; parametrized malformed-input coverage |
| ✅ **News-projection + conformal prediction test suite** | `tests/test_news_projection.py` — topic-specific boost assertions, multiplier range validation, EMA smoothing, `apply_news_prior()` integration, `_bootstrap_forecast` / `_uncertainty_score` / `_interval_adjusted_signal` unit tests |

### Files Changed
| File | Change |
|------|--------|
| `omega/nodes/victoria/news_projection.py` | **Created** — NewsProjectionLayer, TopicScore, NewsProjectionResult |
| `omega/nodes/victoria/dynamic_weights.py` | **Modified** — added `apply_news_prior()` |
| `omega/nodes/victoria/victoria_node.py` | **Modified** — import + instantiate NewsProjectionLayer; step 3c in `_do_compute_signals` |
| `omega/nodes/victoria/timeseries_forecast.py` | **Modified** — added `_bootstrap_forecast`, `_uncertainty_score`, `_interval_adjusted_signal`; extended `TickerForecast` and `compute()` output |
| `tests/test_signal_integration.py` | **Created** — 20-signal integration test suite |
| `tests/test_news_projection.py` | **Created** — NewsProjectionLayer + DynamicWeightAllocator + conformal prediction tests |

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

### Next Session Priorities

- [ ] **Kronos-style time-series foundation model integration** — Pre-trained TSF model (Chronos / Moirai) as a signal source; zero-shot regime prediction and anomaly detection. Replaces hand-crafted GARCH baselines.
- [ ] **Historical backtest validation of geometric signals vs momentum baseline** — Jegadeesh-Titman, natural gradient, Fiedler sizing vs V14 baselines on 3 historical windows. Sharpe, max-DD, Calmar, IC decomposition.
- [x] **Integration test coverage for all 20 signal types** — ✅ Done: `tests/test_signal_integration.py`
- [x] **News-projection layer** — ✅ Done: `omega/nodes/victoria/news_projection.py` + `apply_news_prior()` + step 3c wiring
- [ ] **Dashboard: signal evolution visualization** — EMERGING → STABLE → FALSIFIED state badges, sparkline IC trend, last-transition timestamp surfaced in intelligence page.
- [ ] **Attention router empirical training** — Collect 1000+ `(goal, routing, outcome)` tuples from V23+ runs; offline-train EMA priors.
- [ ] **Run V24** — First run with news-projection layer + conformal forecast uncertainty. Compare Sharpe and max-DD vs V23 baseline.

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
