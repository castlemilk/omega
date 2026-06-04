# Omega Research Feed — 2026-04-25 (automated run)

## Items Reviewed
5 items from @0xRicker, @hanakoxbt, @data_sn13, @browomo, @zostaff

---

## Polymarket Multi-Provider LLM Bot (XGBoost + Kelly Ensemble)
**Source:** @0xRicker — https://github.com/guberm/polymarket-bot
**Type:** repo
**Score:** 2/5 × 3/5 = 6/25 — Watch

**Summary:** Community Polymarket trading bot supporting 5 LLM providers (Claude, GPT-4o, Gemini, OpenRouter, Azure). Multi-provider mode queries all simultaneously and aggregates via conviction × confidence trimmed mean. Fractional Kelly sizing capped at 15% per trade. Reports 68.4% win rate, +149% return, -4.2% max drawdown on 312 backtested Polymarket trades.

**Gap analysis:**
- Does Omega do this? Partial — Omega has Kelly (`omega/math/kelly.py`), LLM meta-controller (`omega/nodes/victoria/llm_meta_controller.py`), and FinBERT sentiment. However, Omega trades crypto spot/perps, not prediction markets. The multi-provider conviction aggregation (trimmed mean) is different from Omega's single-provider meta-controller.
- What would change: If targeting Polymarket — new `omega/nodes/polymarket/` node; if adapting for crypto — LLM ensemble voting logic in `llm_meta_controller.py`
- Dependencies: Polymarket CLOB API, multi-provider LLM calls (latency cost per cycle)

**Recommendation:** Omega already has the Kelly and LLM meta-controller primitives. The multi-provider trimmed-mean voting is worth watching — if Victoria's LLM meta-controller accuracy plateaus, adding a second provider with conviction-weighted averaging is a low-risk enhancement (feasibility 4, but impact is marginal since the bottleneck is signal quality, not LLM disagreement). Deprioritised until meta-controller win-rate data shows room for improvement.

---

## MiroFish: Multi-Agent Social Simulation for Market Forecasting
**Source:** @hanakoxbt — https://github.com/666ghj/MiroFish
**Type:** repo
**Score:** 3/5 × 2/5 = 6/25 — Watch

**Summary:** Open-source Python/Vue system that spins up thousands of AI agents with persona, memory (Zep Cloud), and relationship graphs (GraphRAG + CAMEL-AI OASIS) to simulate emergent market outcomes. Users seed with data/reports and get simulation-based forecasts. One practitioner reported $4,266 profit on 338 Polymarket trades using 2,847 agents per decision cycle.

**Gap analysis:**
- Does Omega do this? No — Omega's adversarial layer uses 3 risk personas (bull/bear/neutral) per trade signal, not thousands of autonomous agents. No GraphRAG or multi-agent social simulation.
- What would change: New signal node + infrastructure layer (GraphRAG construction, Zep memory, OASIS agent orchestration). Would not fit existing Python pipeline easily — fundamentally different compute paradigm.
- Dependencies: Zep Cloud (or self-hosted Zep), Alibaba Qwen or OpenAI-compatible LLM, CAMEL-AI OASIS framework, GraphRAG construction pipeline.

**Recommendation:** Architecturally fascinating but operationally expensive — each decision cycle runs thousands of LLM-backed agents. The latency and cost are incompatible with Omega's ~2.1s cycle target and 10s sleep cadence. The core insight (agent consensus as a sentiment proxy) is already partially addressed by Omega's adversarial debate gate and FinBERT sentiment. Worth revisiting if Omega moves to lower-frequency (daily) signals where simulation cost amortises better.

---

## Data Universe (SN13): Real-Time X/Reddit Sentiment via Bittensor MCP
**Source:** @data_sn13 — https://github.com/macrocosm-os/macrocosmos-mcp
**Type:** repo
**Score:** 3/5 × 4/5 = 12/25 — Queue

**Summary:** Bittensor Subnet 13 operates the world's largest open-source social media dataset — up to 1,000 tweets/day plus Reddit/YouTube, scraped decentrally with freshness scoring (>30 days = zero value). The `macrocosmos-mcp` repo exposes a Claude-compatible MCP server for querying this live feed. Their dTAO sentiment analysis found an inverse correlation between dTAO sentiment and TAO price — demonstrating the dataset surfaces non-obvious market dynamics.

**Gap analysis:**
- Does Omega do this? Partial — Omega has FinBERT sentiment on crypto news headlines (`omega/nodes/victoria/finbert_sentiment.py`) and Fear&Greed Index. However, it has no real-time Twitter/Reddit scraping, no high-volume social dataset, and no decentralised data source.
- What would change: New signal node `omega/nodes/victoria/social_sentiment_sn13.py` calling the Macrocosmos MCP. The MCP returns structured sentiment data that could replace or augment the current FinBERT headline pipeline with fresh, high-volume social signal.
- Dependencies: Macrocosmos MCP server (open-source, self-hostable); TAO token for Bittensor subnet participation (or API key if they offer direct access); `mcp__macrocosmos__*` tool registration in omega.

**Recommendation:** This is the most directly actionable item. Omega's known gap is "no real-time Twitter/Reddit scraping" — SN13 closes that gap with an MCP interface. Concrete next steps: (1) Clone `macrocosm-os/macrocosmos-mcp` and stand it up locally; (2) Add `MACROCOSMOS_API_KEY` to `.env` if required; (3) Create `omega/nodes/victoria/social_sentiment_sn13.py` following the pattern of `finbert_sentiment.py` — fetch sentiment score for each ticker symbol per cycle, normalize to [-1, 1], add to `signal_generation.py` composite; (4) Add to `data_providers.py` failover logic so it degrades gracefully if SN13 is unavailable. Expected impact: incremental win-rate improvement in high-sentiment-divergence regimes where FinBERT lags Twitter consensus.

---

## Polymarket Lag-Arbitrage and Spread Extraction
**Source:** @browomo — https://x.com/browomo/status/2012141283364774268
**Type:** tweet
**Score:** 1/5 × 1/5 = 1/25 — Skip

**Summary:** Analysis of a wallet that grew $5→$3.7M by exploiting broadcast latency (TV feed delay) on Polymarket sports markets. Separate analysis of a 98%-win-rate wallet holding simultaneous UP+DOWN positions to extract market-making spread. Both strategies are prediction market specific.

**Gap analysis:**
- Does Omega do this? No — and it's not applicable. Omega trades crypto perpetuals and spot markets, not prediction markets. Latency arbitrage on TV feeds requires co-location and proprietary market access.
- What would change: N/A
- Dependencies: N/A

**Recommendation:** Prediction-market-specific strategies with no direct transfer to crypto spot/perp trading. The underlying insight (look for wallets extracting structural inefficiencies) overlaps conceptually with Omega's smart money flow signal but at a granularity Omega can't currently match. Skip.

---

## Wallet Clustering Before Resolution as On-Chain Smart Money Signal
**Source:** @zostaff — https://x.com/zostaff/status/2043354864525168735
**Type:** tweet
**Score:** 3/5 × 3/5 = 9/25 — Watch

**Summary:** Detecting wallets that cluster into the winning leg of prediction market outcomes in the hours before resolution — interpreted as informed wallets moving early. A community implementation reportedly generated $890/week from a single Claude Code prompt. The core idea: smart money reveals information asymmetry via on-chain position concentration before resolution events.

**Gap analysis:**
- Does Omega do this? Partial — Omega has `omega/nodes/victoria/smart_money_signal.py` tracking whale wallet flows, but no event-time clustering analysis or resolution-proximity detection. The concept maps to crypto as: detecting wallet clustering before major scheduled events (protocol upgrades, token unlocks, expiry dates).
- What would change: Enhancement to `smart_money_signal.py` — add event calendar lookup (token unlock/expiry schedules) and measure wallet flow concentration in the 1–6 hours before known events.
- Dependencies: On-chain wallet data (Dune Analytics or Nansen API — currently a known gap); event calendar (CoinGecko events API has partial coverage).

**Recommendation:** The crypto analogue is compelling — smart money clustering before token unlocks or protocol events could be a high-information signal. However, the gap is infrastructure: Omega has no on-chain wallet data beyond DefiLlama TVL, and adding Dune/Nansen is a multi-session effort. Queue behind SN13 sentiment (easier win) and revisit when on-chain data layer is added. File: `omega/nodes/victoria/smart_money_signal.py` is the right insertion point.

---

*Generated by omega-twitter-feed-monitor scheduled task*

---

# Omega Research Feed — 2026-04-25 14:00 (second run — academic sources)

## Items Reviewed
3 items from arXiv academic search (Twitter accounts not directly accessible; broader search used)

---

## Kalshi Prediction Markets as Crypto Volatility Signals
**Source:** arXiv — https://arxiv.org/abs/2604.01431
**Type:** paper
**Score:** 3/5 × 3/5 = 9/25 — Watch

**Summary:** April 2026 paper constructs daily volume-weighted probability-change signals from ten Kalshi event series (KXFED, KXRECSSNBER, KXCPI) and tests their ability to predict five-day-ahead realized volatility for Bitcoin, Ethereum, Solana, Cardano, Avalanche, and Chainlink. Fed rate repricing predicts BTC volatility in-sample (t=3.63, p<0.001). Recession signal is stable out-of-sample (MSFE=0.979). CPI repricing predicts ETH volatility OOS (MSFE=0.959). Signals survive orthogonalization against Fed Funds futures and Treasury yields, confirming they carry information not already in conventional instruments.

**Gap analysis:**
- Does Omega do this? No — Omega has VRP (implied vs realized vol spread via `omega/nodes/victoria/vrp_signal.py`) and Fear&Greed, but no prediction market signals and no dedicated volatility-forecasting channel.
- What would change: New signal node `omega/nodes/victoria/kalshi_vol_signal.py` — fetch Kalshi contract probability changes (KXFED, KXRECSSNBER, KXCPI); use as a vol-regime conditioning feature in `strategy.py:_apply_regime_adaptive_thresholds` and as a Kelly denominator multiplier.
- Dependencies: Kalshi public API (free tier, US-accessible, no geo-block); signal predicts volatility level not direction, so targets position-sizing and threshold scaling rather than directional conviction.

**Recommendation:** This is an orthogonal macro vol-forecasting layer Omega completely lacks. Omega's current vol-regime detection uses endogenous rolling std — it captures realized vol but not forward-looking macro regime risk. A Kalshi-derived vol forecast would give the Kelly sizer a forward-looking denominator and could preemptively tighten conviction thresholds before FOMC/CPI events. Concrete next steps: (1) Register Kalshi API at kalshi.com/developers; (2) Implement `omega/nodes/victoria/kalshi_vol_signal.py` following `finbert_sentiment.py` pattern; (3) Integrate into `strategy.py` as a `_thresh_scale` multiplier; (4) Gate via `omega/eval/overfitting_gate.py`.

---

## Explainable Patterns in Cryptocurrency Microstructure (LOB Signals)
**Source:** arXiv — https://arxiv.org/abs/2602.00776
**Type:** paper
**Score:** 3/5 × 1/5 = 3/25 — Skip

**Summary:** February 2026 paper analyzing 1-second Binance Futures perpetual LOB data across BTC, LTC, ETC, ENJ, ROSE (2022–2025). CatBoost + SHAP shows order flow imbalance, bid-ask spread, and adverse selection features are stable cross-asset predictors of short-term price direction. Top-of-book taker and fixed-depth maker strategies validated in backtesting.

**Gap analysis:**
- Does Omega do this? No — LOB/L2 data is an explicit known gap. Omega uses OBV and funding rate but no tick-level order flow imbalance.
- What would change: Requires new streaming data infrastructure for 1-second LOB snapshots — fundamentally different from Omega's polling-based candle ingestion.
- Dependencies: L2 streaming data. Binance geo-blocked from US (451). Coinbase/Kraken have L2 feeds but different liquidity profile; significant infrastructure lift.

**Recommendation:** Architecturally desirable but infeasible without L2 streaming infrastructure and a non-geo-blocked exchange. The cross-asset stability finding is valuable but requires a streaming pipeline absent from Omega's stack. Skip until US-accessible exchange L2 data (Coinbase/Kraken WebSocket) is integrated or Omega moves to a lower-latency execution environment.

---

## Orchestration Framework for Financial Agents: From Algorithmic to Agentic Trading
**Source:** arXiv — https://arxiv.org/abs/2512.02227
**Type:** paper
**Score:** 2/5 × 4/5 = 8/25 — Watch

**Summary:** December 2025 paper mapping traditional algorithmic trading components to nine LLM agents: Planner/Orchestrator, Alpha, Risk, Portfolio, Backtest, Execution, Audit, and Memory. Demonstrated 8.39% Bitcoin return vs 3.80% benchmark. Claims to democratize institutional trading architecture via modular coordinated agents.

**Gap analysis:**
- Does Omega do this? Mostly — multi-node orchestration, adversarial debate gate (bull/bear/neutral personas), memory system, risk node, and Kelly sizing cover ~70% of this framework. Missing: dedicated Backtest Agent and Audit Agent that validates live decisions against backtest expectations.
- What would change: Wire `internal/conformance/` conformance runner to emit structured per-decision audit records (entry rationale, signal states, exit PnL vs expected, regime) persisted to episodic memory for meta-analyst consumption.
- Dependencies: None new — gap is wiring, not infrastructure.

**Recommendation:** Omega already implements most of this organically. The incremental value is formalizing the Audit Agent: after each trade, the conformance runner emits a structured audit record → episodic memory → meta-harness consumption. This closes the self-improvement loop without new infrastructure. Lower priority than SN13 (Score 12) but useful as architectural framing when wiring the meta-harness. Files: `internal/conformance/` + `omega/core/memory.py`.

---

*Generated by omega-twitter-feed-monitor scheduled task*

---

# Omega Research Feed — 2026-04-25 (third run — latest arXiv q-fin.TR/CP)

## Items Reviewed
3 new items (none overlapping prior runs today). Access note: direct x.com profile fetches returned HTTP 402 (X blocks unauthenticated scraping) and WebSearch does not index per-account post content for @browomo/@zostaff/@hanakoxbt/@0xricker/@adiix_official/@data_sn13 — only generic influencer listicles. This run pulled from the latest arXiv q-fin.TR and q-fin.CP listings (the research substrate those accounts typically surface) as a fallback. Future runs should switch to an authenticated X API path or a Nitter mirror to track the specified handles reliably.

---

## Early Detection of Latent Microstructure Regimes in Limit Order Books
**Source:** arXiv q-fin.TR (April 2026) — https://arxiv.org/abs/2604.20949
**Type:** paper
**Score:** 4/5 × 2/5 = 8/25 — Watch

**Summary:** Formalizes a three-regime causal model (stable → latent build-up → stress) for LOBs with identifiability proofs, then implements a trigger detector via MAX aggregation over signal channels plus rising-edge + adaptive thresholding. Validated on BTC/USDT LOB with mean lead-time 18.6 ± 3.2 timesteps at perfect precision, beating classical change-point and microstructure baselines. Distinct from the Feb 2026 LOB microstructure paper in run 2 — this one predicts *latent pre-stress* rather than classifying realized direction.

**Gap analysis:**
- Does Omega do this? **Partial.** HMM 2-state + `bayesian_regime.py` operate on bar-level OHLCV, not L2; they detect *current* regime, not latent build-up.
- What would change: new `latent_regime_detector` node wired into `_apply_regime_adaptive_thresholds` as an early-stress flag that tightens short-side thresholds ahead of HMM switching.
- Dependencies: L2 order book streaming ingest — the same blocker called out for run 2's microstructure paper. Coinbase/Kraken L2 websocket feasible; Binance/Bybit US-blocked.

**Recommendation:** Watch. High-value signal (early stress detection directly helps the crisis-regime short path Omega already tunes for), but feasibility is gated on the L2/streaming workstream. If that initiative starts, this paper becomes a natural first consumer — it's strictly better than the realized-direction LOB model in run 2 for Omega's use case because it targets regime gating (where Omega already has the plumbing) rather than directional prediction (which needs a full new signal stack).

---

## Machine Spirits: Speculation and Adaptation of LLM Agents in Asset Markets
**Source:** arXiv q-fin.TR (April 2026) — https://arxiv.org/abs/2604.18602
**Type:** paper
**Score:** 2/5 × 3/5 = 6/25 — Watch

**Summary:** Tested 15 LLMs across providers in simulated homogeneous and heterogeneous markets. Found LLM agents generate speculative bubbles defying rational expectations, adapt strategies to counterparts (advanced models exploit less-sophisticated ones), and can *amplify* rather than stabilize volatility. Empirical evidence against using LLMs for open-ended market autonomy.

**Gap analysis:**
- Does Omega do this? No — Omega has `llm_meta_controller.py` (V145–V148) but gates its outputs via the conviction pipeline, not as open-ended agents.
- What would change: nothing implementable; this is a design constraint, not a component.
- Dependencies: none.

**Recommendation:** Skip as implementation. Keep as a written constraint on the LLM meta-controller roadmap: any future LLM role must stay bounded (classification / gating / calibration) — not free-form position decisions. Worth one line in the meta-controller design notes and in the V148 best-of-phases follow-up.

---

## Agentic Artificial Intelligence in Finance: A Comprehensive Survey
**Source:** arXiv q-fin.CP (April 23 2026, Aldridge et al., 25 authors) — https://arxiv.org/abs/2604.21672
**Type:** paper (survey, 35 pages)
**Score:** 3/5 × 4/5 = 12/25 — Queue

**Summary:** Survey distinguishing agentic AI (autonomous goal-orientation, continuous learning, multi-agent coordination) from algorithmic trading and generative AI. Covers architecture, market applications, regulation, systemic risk, interpretability, and multi-agent coordination patterns. Broader and more recent than the Dec 2025 orchestration framework paper (2512.02227) reviewed in run 2.

**Gap analysis:**
- Does Omega do this? Partial — Omega's orchestrator v2 + meta-analyst + coordination bus sit in the agentic lane, but the continuous-learning loop is offline (training-version cadence) and there's no explicit taxonomy of inter-agent coordination patterns.
- What would change: reading output → short `docs/ideas/agentic-survey-notes.md` pulling (a) any coordination patterns Omega's orchestrator is missing, and (b) regulatory/interpretability framings that could extend the V49 gate 6 (auto-apply audit) safety story.
- Dependencies: none — reading only.

**Recommendation:** Queue. 1–2 hour read pass, write a short notes file. Complements the Audit Agent work flagged for 2512.02227 in run 2 — if anything actionable comes out, fold it into that wiring rather than spinning up a new initiative.

---

*Generated by omega-twitter-feed-monitor scheduled task (run 3)*

# Omega Research Feed — 2026-04-25 (run 4)

## Items Reviewed
2 items. Direct-handle searches (browomo, zostaff, hanakoxbt, 0xricker, adiix_official, data_sn13) returned no usable Twitter content this run — fell back to topical searches in the LOB-microstructure and LLM-trading-agent areas.

---

## Better Inputs Matter More Than Stacking Another Hidden Layer (LOB microstructure)
**Source:** arXiv 2506.05764 — https://arxiv.org/abs/2506.05764
**Type:** paper
**Score:** 4/5 × 2/5 = 8/25 — Watch

**Summary:** Benchmarks logistic regression / XGBoost / DeepLOB / Conv1D+LSTM on Bybit BTC/USDT LOB snapshots (100 ms → multi-second). With Kalman + Savitzky-Golay filtering on the inputs, simpler models match or beat deep architectures on up/down/flat classification while being faster and more interpretable. Headline claim: feature engineering > architectural depth for short-horizon LOB prediction.

**Gap analysis:**
- Does Omega do this? **No** — Omega has no L2/order book ingestion at all (documented gap in `project_omega.md`).
- What would change: would require a new `internal/marketdata/` streaming L2 ingestor + a Python signal node. Bybit US-blocked → use Coinbase or Kraken L2.
- Dependencies: WebSocket L2 client, snapshot store, Kalman/SG filters in numpy, training harness for the classifier.

**Recommendation:** Watch, not queue. The paper's takeaway (preprocessing > depth) is useful but Omega's real blocker is the missing L2 pipe, which is multi-week infra work and was already deprioritised in earlier runs. Pin the result for whenever the L2 ingestion epic is picked up — it shapes the v1 signal as "logistic + good filters" rather than "DeepLOB clone".

---

## TauricResearch/TradingAgents v0.2.0 (multi-agent LLM trading framework)
**Source:** github.com/TauricResearch/TradingAgents
**Type:** repo
**Score:** 3/5 × 3/5 = 9/25 — Watch

**Summary:** LangGraph-based multi-agent framework: Fundamentals / Sentiment / News / Technical analysts feed Bull vs Bear researchers, then Trader, then Risk Manager / Portfolio Manager. v0.2.0 (Feb 2026) adds multi-provider LLM support (GPT-5.x, Gemini 3.x, Claude 4.x, Grok 4.x) and a decision log that tracks realized returns vs SPY for self-reflection.

**Gap analysis:**
- Does Omega do this? **Partial.** Omega already has a meta-controller (`llm_meta_controller.py`, V143-V148) and ensemble voter, but only one LLM in the loop and no explicit bull/bear debate stage. No formal "researcher debate → trader → risk" pipeline.
- What would change: could borrow the bull-vs-bear debate sub-stage and slot it between `signal_generation.py` and `exit_controller.py` as a pre-trade adversarial check.
- Dependencies: existing `openai_compatible` provider (V145) is enough; adds latency + token cost per cycle.

**Recommendation:** Watch. The architecture is interesting but Omega's recent V148 best-of-phases result (meta_learner_exit_only + continuous_sizing) is the current performance leader and adding a debate layer would muddy attribution. Revisit if a future training cycle plateaus and we want a structured way to add adversarial reasoning beyond the current ensemble vote.

---

*Generated by omega-twitter-feed-monitor scheduled task (run 4)*
