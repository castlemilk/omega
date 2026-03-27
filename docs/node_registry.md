# Omega Node Registry

> Auto-generated from `internal/registry/catalog.go`. Do not edit manually — run `omega nodes export` to regenerate.

## Summary

49 nodes | victoria=34 polymarket=6 shared=3 platform=6 | L0=14 L1=16 L2=13 L3=6 L4=0

## Victoria (Crypto Quant)

| Name | Type | L | IC | Memory | Brain | Purpose |
|------|------|---|----|----|---|---|
| **OrderFlowSignal** | signal | L0 | 0.146 | ✗ | ✗ | Detect real-time directional pressure from institutional order flow before price moves. |
| **CrossAssetSignal** | signal | L0 | 0.093 | ✗ | ✗ | Identify when crypto decouples from equities or when ETH/SOL lead BTC — exploitable short-term divergences. |
| **MicrostructureSignal** | signal | L0 | 0.071 | ✗ | ✗ | Measure market liquidity and execution cost regime — widens before large moves, tightens in trending markets. |
| **SentimentSignal** | signal | L0 | 0.058 | ✗ | ✗ | Contrarian and trend-confirming signal — extreme fear predicts reversals, moderate fear trends with momentum. |
| **SignalGenerationNode** | signal | L1 | 0.104 | ✗ | ✗ | Baseline technical signal suite that provides fundamental price-action context for the ensemble. |
| **MarketDataSignal** | signal | L0 | 0.104 | ✗ | ✗ | Foundation signal layer: price-based features consumed by all higher-level nodes. |
| **VRPSignal** | signal | L1 | 0.118 | ✗ | ✗ | Exploit systematic overpricing of options — positive VRP regime favours vol-selling and mean-reversion strategies. |
| **FundingRateSignal** | signal | L0 | 0.082 | ✗ | ✗ | Funding extremes predict mean-reversion — highly positive funding means crowded longs about to unwind. |
| **OpenInterestSignal** | signal | L0 | 0.067 | ✗ | ✗ | Rising OI with rising price = trend confirmation; rising OI with falling price = increasing shorts / bearish. |
| **MacroSignal** | signal | L0 | — | ✗ | ✗ | Regime signal — crypto bull markets historically correlate with monetary expansion and falling real yields. |
| **OptionsSignal** | signal | L0 | — | ✗ | ✗ | Options market provides institutional positioning signals — GEX pinning, skew as tail-risk proxy, max pain as gravitational level. |
| **DerivativesSignal** | signal | L0 | 0.076 | ✗ | ✗ | Basis and carry signals capture institutional term-structure expectations — contango/backwardation regime detection. |
| **LiquidationSignal** | signal | L1 | 0.089 | ✗ | ✗ | Liquidation clusters act as price magnets; signals proximity to cascades for risk management and momentum entries. |
| **LiquidationCascadeSignal** | signal | L2 | 0.096 | ✓ | ✗ | Predict second-order liquidation effects beyond the initial cluster — cascade risk > 1 means hedging required. |
| **StablecoinSignal** | signal | L0 | 0.054 | ✗ | ✗ | Stablecoin inflows signal fresh capital entering crypto; Tether premium above 1% historically precedes bull runs. |
| **NewsSignal** | signal | L1 | 0.045 | ✗ | ✗ | News-driven price gaps are exploitable in the first 30 minutes — source reliability weighting filters noise. |
| **TwitterSignal** | signal | L1 | 0.038 | ✗ | ✗ | Social volume spikes predict volatility; social dominance shifts predict capital rotation between tokens. |
| **OnChainSignal** | signal | L1 | 0.096 | ✗ | ✗ | On-chain signals reflect holder behaviour and miner economics — MVRV and Puell are primary cycle peak/trough indicators. |
| **InformationFlowSignal** | signal | L1 | 0.062 | ✗ | ✗ | BTC-dominance regime detection via information causality — when ETH leads, alt-season dynamics apply. |
| **DisagreementSignal** | signal | L0 | — | ✗ | ✗ | Meta-signal: when all signals agree, conviction is high; when they disagree, reduce position size. |
| **WassersteinRegimeSignal** | signal | L1 | 0.078 | ✗ | ✗ | Model-free regime detection that is sensitive to structural breaks in cross-asset correlations, not just return distributions. |
| **RMTDenoiserNode** | signal | L1 | — | ✗ | ✗ | Noise in correlation matrices degrades portfolio construction — RMT cleaning extracts the true factor structure. |
| **FactorModelNode** | signal | L0 | — | ✗ | ✗ | Identify correlated risk clusters in the signal ensemble — prevent doubling up on the same underlying risk factor. |
| **VictoriaNode** | strategy | L3 | 0.147 | ✓ | ✓ | The orchestrating node that turns a signal ensemble into a position. Brain optional. |
| **StrategyNode** | strategy | L3 | — | ✓ | ✓ | Translates conviction scores into executable position sizes respecting risk limits. |
| **RegimeDetectorNode** | strategy | L2 | — | ✓ | ✗ | All downstream signal multipliers and position sizes are conditioned on regime — getting this right is critical. |
| **MetaModelNode** | strategy | L2 | — | ✓ | ✗ | Non-linear signal combination — captures interaction effects between signals that IC-weighted linear ensemble misses. |
| **PositionSizingNode** | risk | L2 | — | ✓ | ✗ | Bet sizing is the primary driver of long-run returns — Kelly maximizes log-wealth growth rate. |
| **DynamicWeightAllocator** | strategy | L2 | — | ✓ | ✗ | Adaptive signal weighting — signals with recent high IC get more weight; decaying signals get down-weighted. |
| **RiskManagementNode** | risk | L2 | — | ✗ | ✗ | Last line of defence before execution — reject any position that violates structural risk rules. |
| **DataIngestionNode** | execution | L1 | — | ✗ | ✗ | Reliable data pipeline foundation — all signal nodes depend on this node's outputs. |
| **SignalResearchNode** | reasoning | L3 | — | ✓ | ✓ | AI-driven signal discovery — extract patterns from past cycle outcomes that aren't captured by current signal set. |
| **VerificationNode** | execution | L2 | — | ✗ | ✗ | Detect execution drift — when live performance diverges from backtest, the strategy needs re-calibration. |
| **DataCleanersNode** | execution | L2 | — | ✗ | ✗ | Garbage in, garbage out — catch data quality issues before they contaminate signal generation. |

### OrderFlowSignal

**Module:** `omega.nodes.victoria.signals_advanced`  
**Type:** signal | **Project:** victoria | **Autonomy:** L0  
**Version:** 1.2 (added 2026-01-15)

Computes order-book depth imbalance, cumulative-volume-delta (CVD), and bid-ask spread from Binance L2 order book snapshots.

**Data Sources:**
- Binance REST order book (depth 20)
- Binance trade stream

**References:**
- *Order imbalance based strategy in high frequency trading* — Cartea, Jaimungal & Penalva 2015
  > Theoretical basis for bid-ask imbalance as a short-term alpha signal
- *Informed Trading in Futures Markets* — Ederington & Lee 1993
  > Order flow imbalance predicts short-term price direction

**Changelog:** V1.0: bid-ask imbalance only → V1.1: added CVD → V1.2: configurable depth levels

---

### CrossAssetSignal

**Module:** `omega.nodes.victoria.signals_advanced`  
**Type:** signal | **Project:** victoria | **Autonomy:** L0  
**Version:** 1.1 (added 2026-01-15)

Measures rolling cross-correlations between BTC, ETH, SOL and SPY to detect regime shifts via co-movement changes.

**Data Sources:**
- Binance OHLCV (BTC/ETH/SOL)
- Yahoo Finance SPY daily

**References:**
- *Cross-asset signals in quantitative trading* — Asness, Moskowitz & Pedersen 2013
  > Cross-asset momentum and correlation timing
- *Crypto–equity correlation dynamics* — Corbet et al. 2021
  > BTC-SPY correlation regime changes during market stress

**Changelog:** V1.0: BTC/ETH only → V1.1: added SOL + SPY

---

### MicrostructureSignal

**Module:** `omega.nodes.victoria.signals_advanced`  
**Type:** signal | **Project:** victoria | **Autonomy:** L0  
**Version:** 1.0 (added 2026-02-01)

Estimates effective bid-ask spread, Kyle's lambda (price impact), and trade intensity from tick-level Binance data.

**Data Sources:**
- Binance aggTrades stream
- Binance order book

**References:**
- *Continuous Auctions and Insider Trading* — Kyle 1985
  > Lambda (price impact coefficient) from Kyle model
- *A New Approach to Measuring Financial Contagion* — Forbes & Rigobon 2002
  > Spread-based microstructure regime classification

**Changelog:** V1.0: initial

---

### SentimentSignal

**Module:** `omega.nodes.victoria.signals_advanced`  
**Type:** signal | **Project:** victoria | **Autonomy:** L0  
**Version:** 1.1 (added 2026-01-20)

Aggregates the Fear & Greed Index (alternative.me) and CryptoPanic bullish/bearish vote ratio into a composite sentiment score.

**Data Sources:**
- alternative.me Fear & Greed API
- CryptoPanic API votes

**References:**
- *Investor sentiment and the cross-section of stock returns* — Baker & Wurgler 2006
  > Sentiment as contrarian signal at extremes
- *Speculative Betas* — Hong & Sraer 2016
  > Sentiment-driven mispricing in high-beta assets

**Changelog:** V1.0: F&G only → V1.1: added CryptoPanic votes

---

### SignalGenerationNode

**Module:** `omega.nodes.victoria.signal_generation`  
**Type:** signal | **Project:** victoria | **Autonomy:** L1  
**Version:** 1.0 (added 2026-01-10)

Computes classical technical indicators: SMA crossover, RSI, MACD, Bollinger Bands, and volume momentum from OHLCV data. Self-improving via improve() — currently stuck at v1.0 (improve() never called by orchestrator).

**Data Sources:**
- Binance OHLCV REST

**References:**
- *Technical Analysis of the Financial Markets* — Murphy 1999
  > SMA/RSI/MACD baseline indicator definitions
- *151 Formulas for Algorithmic Trading Strategies* — Kakushadze & Serur 2018
  > Formulas 1–15: momentum and trend indicators

**Changelog:** V1.0: SMA + RSI + MACD + BB + volume (v1.1–v1.3 implemented but never unlocked)

---

### MarketDataSignal

**Module:** `omega.nodes.victoria.market_data_signals`  
**Type:** signal | **Project:** victoria | **Autonomy:** L0  
**Version:** 1.0 (added 2026-01-10)

Computes price returns (1h, 4h, 24h), realized volatility, and momentum scores from raw OHLCV.

**Data Sources:**
- Binance OHLCV REST

**References:**
- *Returns to Buying Winners and Selling Losers* — Jegadeesh & Titman 1993
  > Cross-sectional momentum from return windows

**Changelog:** V1.0: initial

---

### VRPSignal

**Module:** `omega.nodes.victoria.vrp_signal`  
**Type:** signal | **Project:** victoria | **Autonomy:** L1  
**Version:** 1.1 (added 2026-02-10)

Computes the Volatility Risk Premium as the spread between 30-day implied volatility (Deribit ATM options) and subsequent realized volatility. Generates a carry regime signal when VRP is positive.

**Data Sources:**
- Deribit options REST
- Binance OHLCV (realized vol)

**References:**
- *The Variance Risk Premium* — Bollerslev, Tauchen & Zhou 2009
  > VRP measurement and its predictive content for equity returns
- *Volatility Risk Premia and Future Stock Returns* — Carr & Wu 2009
  > Cross-sectional and time-series VRP as alpha signal

**Changelog:** V1.0: raw VRP → V1.1: z-score normalization + regime output

---

### FundingRateSignal

**Module:** `omega.nodes.victoria.alt_data_signals`  
**Type:** signal | **Project:** victoria | **Autonomy:** L0  
**Version:** 1.0 (added 2026-01-20)

Reads Binance perpetual swap funding rates (8-hourly) and computes a rolling z-score to signal crowded long/short positioning.

**Data Sources:**
- Binance futures funding rate API

**References:**
- *The Cross-Section of Cryptocurrency Returns* — Liu, Tsyvinski & Wu 2022
  > Funding rate as carry signal in crypto perpetuals

**Changelog:** V1.0: initial

---

### OpenInterestSignal

**Module:** `omega.nodes.victoria.alt_data_signals`  
**Type:** signal | **Project:** victoria | **Autonomy:** L0  
**Version:** 1.0 (added 2026-01-25)

Tracks Binance perpetual open interest change (1h delta and 24h delta) as a proxy for new speculative capital entering or leaving the market.

**Data Sources:**
- Binance futures open interest API

**References:**
- *Open Interest and Futures Price Volatility* — Bessembinder & Seguin 1992
  > OI as proxy for speculative participation and volatility regime

**Changelog:** V1.0: initial

---

### MacroSignal

**Module:** `omega.nodes.victoria.macro_signals`  
**Type:** signal | **Project:** victoria | **Autonomy:** L0  
**Version:** 1.0 (added 2026-02-05)

Ingests US macro data from FRED: M2 money supply growth, federal funds rate, real 10Y yield, 2s10s yield curve, DXY, and Fed net liquidity (assets minus RRP minus TGA).

**Data Sources:**
- FRED API (M2SL, FEDFUNDS, DFII10, T10Y2Y, DTWEXBGS)
- FRED balance sheet series

**References:**
- *The Fed Model: A Note* — Asness 2003
  > Fed liquidity and real yield impact on risk asset valuations
- *Global Liquidity and Bitcoin* — Cieslak & Schrimpf 2022
  > Net liquidity measure as crypto price predictor

**Changelog:** V1.0: initial

---

### OptionsSignal

**Module:** `omega.nodes.victoria.options_signals`  
**Type:** signal | **Project:** victoria | **Autonomy:** L0  
**Version:** 1.1 (added 2026-02-15)

Fetches Deribit BTC/ETH options data to compute gamma exposure (GEX), put/call ratio, IV skew (25-delta RR), max pain price, and term structure slope.

**Data Sources:**
- Deribit options REST API

**References:**
- *Gamma Exposure and Market Maker Hedging* — Bouchaud & Potters 2003
  > GEX pinning effect near large gamma strikes
- *The Information Content of the Implied Volatility Term Structure* — Mixon 2007
  > IV term structure slope as forward-looking fear indicator

**Changelog:** V1.0: put/call + skew → V1.1: GEX + max pain + term structure

---

### DerivativesSignal

**Module:** `omega.nodes.victoria.derivatives_signals`  
**Type:** signal | **Project:** victoria | **Autonomy:** L0  
**Version:** 1.0 (added 2026-02-01)

Computes futures basis (spot-perp spread), funding rate carry, and basis term structure from Binance quarterly and perpetual contracts.

**Data Sources:**
- Binance futures REST
- Binance perp funding rate

**References:**
- *Carry Trades and Global FX Volatility* — Menkhoff et al. 2012
  > Carry strategy returns and crash risk in derivative markets

**Changelog:** V1.0: initial

---

### LiquidationSignal

**Module:** `omega.nodes.victoria.liquidation_signals`  
**Type:** signal | **Project:** victoria | **Autonomy:** L1  
**Version:** 1.1 (added 2026-02-10)

Fetches Coinglass and Bybit liquidation data to compute cascade risk scores — proximity to large liquidation clusters predicts volatility spikes.

**Data Sources:**
- Coinglass liquidation heatmap API
- Bybit risk limit tiers

**References:**
- *Fire Sales in a Model of Complexity* — Caballero & Simsek 2013
  > Liquidation cascade mechanics in leveraged markets

**Changelog:** V1.0: Coinglass only → V1.1: Bybit levels + historical window

---

### LiquidationCascadeSignal

**Module:** `omega.nodes.victoria.liquidation_cascade`  
**Type:** signal | **Project:** victoria | **Autonomy:** L2  
**Version:** 1.0 (added 2026-02-20)

Models the amplification factor of liquidation cascades using historical price-liquidation co-movements. Outputs a cascade amplification score and estimated cascade radius.

**Data Sources:**
- Coinglass historical liquidations
- Binance OHLCV

**References:**
- *Systemic Risk and Liquidation Cascades* — Brunnermeier & Pedersen 2009
  > Liquidity spirals and cascade amplification in leveraged systems

**Changelog:** V1.0: initial with historical learning

---

### StablecoinSignal

**Module:** `omega.nodes.victoria.stablecoin_signals`  
**Type:** signal | **Project:** victoria | **Autonomy:** L0  
**Version:** 1.0 (added 2026-02-15)

Tracks USDT and USDC on-chain supply growth via DeFiLlama, plus Tether premium (USDT/USD on OTC markets) as a measure of crypto market demand.

**Data Sources:**
- DeFiLlama stablecoin API
- CoinGecko USDT price

**References:**
- *Is Bitcoin Really Untethered?* — Griffin & Shams 2020
  > USDT issuance as demand signal and price predictor

**Changelog:** V1.0: initial

---

### NewsSignal

**Module:** `omega.nodes.victoria.news_signals`  
**Type:** signal | **Project:** victoria | **Autonomy:** L1  
**Version:** 1.1 (added 2026-02-01)

Aggregates CryptoPanic API headlines and RSS feeds, applies VADER sentiment NLP, and learns per-source reliability weights from outcome feedback.

**Data Sources:**
- CryptoPanic API
- CoinDesk RSS
- CoinTelegraph RSS

**References:**
- *The Impact of News Sentiment on Cryptocurrency Markets* — Kraaijeveld & De Smedt 2020
  > News sentiment predictive content for BTC/ETH

**Changelog:** V1.0: VADER on all sources equally → V1.1: per-source reliability weights learned from feedback

---

### TwitterSignal

**Module:** `omega.nodes.victoria.twitter_signals`  
**Type:** signal | **Project:** victoria | **Autonomy:** L1  
**Version:** 1.0 (added 2026-02-01)

Reads CryptoCompare social stats API for tweet volume, Reddit activity, and social dominance scores for BTC/ETH/SOL.

**Data Sources:**
- CryptoCompare Social Stats API

**References:**
- *Twitter Sentiment and the Stock Market* — Bollen, Mao & Zeng 2011
  > Social sentiment as leading predictor of price moves

**Changelog:** V1.0: initial

---

### OnChainSignal

**Module:** `omega.nodes.victoria.onchain_data`  
**Type:** signal | **Project:** victoria | **Autonomy:** L1  
**Version:** 1.2 (added 2026-01-25)

Pulls on-chain metrics from ErcinDedeoglu's GitHub dataset and CryptoQuant: MVRV Z-score, Puell Multiple, exchange netflow, taker buy/sell ratio, and Coinbase premium index.

**Data Sources:**
- ErcinDedeoglu GitHub (bitcoin-on-chain-indicators)
- CryptoQuant exchange netflow
- Binance taker ratio API

**References:**
- *The Bitcoin Network Momentum and Value Cycles* — Plan B 2019
  > MVRV as market cycle indicator for BTC
- *Puell Multiple as a Mining-Driven Cycle Indicator* — Dedeoglu 2019
  > Miner revenue relative to 365-day average as cycle signal

**Changelog:** V1.0: MVRV + Puell → V1.1: exchange netflow → V1.2: Coinbase premium + taker ratio

---

### InformationFlowSignal

**Module:** `omega.nodes.victoria.information_flow`  
**Type:** signal | **Project:** victoria | **Autonomy:** L1  
**Version:** 1.0 (added 2026-02-20)

Computes transfer entropy from BTC returns to ETH and SOL returns to detect which asset is the current information leader.

**Data Sources:**
- Binance OHLCV (BTC/ETH/SOL)

**References:**
- *Information Transfer Between Stock Market Sectors* — Kwon & Yang 2008
  > Transfer entropy methodology for financial time series
- *151 Formulas for Algorithmic Trading Strategies* — Kakushadze & Serur 2018
  > Formula 103: information ratio and cross-asset information flow

**Changelog:** V1.0: initial

---

### DisagreementSignal

**Module:** `omega.nodes.victoria.disagreement_signal`  
**Type:** signal | **Project:** victoria | **Autonomy:** L0  
**Version:** 1.0 (added 2026-03-01)

Measures the pairwise disagreement entropy across all signal outputs in the current cycle. High disagreement indicates regime uncertainty; low disagreement indicates consensus.

**Data Sources:**
- Internal signal bus (no external API)

**References:**
- *Analyst Disagreement and Return Predictability* — Diether, Malloy & Scherbina 2002
  > Disagreement among forecasters as uncertainty proxy

**Changelog:** V1.0: initial

---

### WassersteinRegimeSignal

**Module:** `omega.nodes.victoria.wasserstein_regime`  
**Type:** signal | **Project:** victoria | **Autonomy:** L1  
**Version:** 1.0 (added 2026-03-05)

Uses optimal transport (Wasserstein-2 distance) between rolling 30-day correlation matrices to detect regime transitions — large distance = regime change.

**Data Sources:**
- Binance OHLCV (BTC/ETH/SOL/BNB)

**References:**
- *Optimal Transport: Old and New* — Villani 2009
  > Wasserstein distance theory for probability distributions
- *Wasserstein Distance for Portfolio Regime Detection* — Marti et al. 2021
  > Financial correlation matrix comparison via optimal transport

**Changelog:** V1.0: initial Wasserstein-2 on Pearson correlation matrices

---

### RMTDenoiserNode

**Module:** `omega.nodes.victoria.rmt_denoiser`  
**Type:** signal | **Project:** victoria | **Autonomy:** L1  
**Version:** 1.0 (added 2026-03-10)

Applies Random Matrix Theory (Marchenko-Pastur law) to eigenvalue-clean the signal correlation matrix, separating true signal structure from noise.

**Data Sources:**
- Internal signal bus (correlation matrix of all signals)

**References:**
- *Distribution of eigenvalues for some sets of random matrices* — Marchenko & Pastur 1967
  > Foundational RMT result defining the noise eigenvalue bulk
- *Noise Dressing of Financial Correlation Matrices* — Laloux et al. 1999
  > Application of RMT to financial covariance matrix cleaning

**Changelog:** V1.0: Marchenko-Pastur eigenvalue clipping on signal correlation matrix

---

### FactorModelNode

**Module:** `omega.nodes.victoria.factor_model`  
**Type:** signal | **Project:** victoria | **Autonomy:** L0  
**Version:** 1.0 (added 2026-03-10)

Decomposes the signal matrix into orthogonal PCA factors and computes each signal's factor loadings for risk attribution.

**Data Sources:**
- Internal signal bus

**References:**
- *Risk Models and Their Uses* — Ross 1976
  > APT factor model as basis for risk decomposition
- *151 Formulas for Algorithmic Trading Strategies* — Kakushadze & Serur 2018
  > Formula 78: PCA-based risk factor construction

**Changelog:** V1.0: initial PCA factor decomposition

---

### VictoriaNode

**Module:** `omega.nodes.victoria.victoria_node`  
**Type:** strategy | **Project:** victoria | **Autonomy:** L3  
**Version:** 3.4 (added 2026-01-10)

Top-level Victoria trading node. Composes all signal subsystems, applies IC-weighted ensemble scoring, routes through DebateGate adversarial filter, and constructs final portfolio. Supports pico/supervised/autonomous modes.

**Data Sources:**
- All signal subsystems
- SignalBus
- MemoryBus

**References:**
- *The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market* — Thorp 1997
  > Kelly-based position sizing as core portfolio construction method

**Changelog:** V1: single-signal → V2: ensemble + IC weights → V3: DebateGate + MemoryBus → V3.4: pico baseline + regime multipliers

---

### StrategyNode

**Module:** `omega.nodes.victoria.strategy`  
**Type:** strategy | **Project:** victoria | **Autonomy:** L3  
**Version:** 2.1 (added 2026-01-15)

Reads peer signals from SignalBus and VictoriaNode output to construct Kelly-optimal portfolio with regime-aware position scaling.

**Data Sources:**
- SignalBus
- RegimeDetectorNode output

**Changelog:** V1: fixed Kelly → V2: regime-aware scaling → V2.1: SignalBus peer reads

---

### RegimeDetectorNode

**Module:** `omega.nodes.victoria.regime_detector`  
**Type:** strategy | **Project:** victoria | **Autonomy:** L2  
**Version:** 1.3 (added 2026-01-20)

Classifies market into bullish/bearish/neutral/crisis regimes using HMM with Gaussian emissions on log-returns and realized volatility.

**Data Sources:**
- Binance OHLCV
- WassersteinRegimeSignal output

**References:**
- *A New Approach to the Economic Analysis of Nonstationary Time Series* — Hamilton 1989
  > Hidden Markov Model for regime-switching in financial time series

**Changelog:** V1.0: 2-state HMM → V1.2: 4-state + vol features → V1.3: WassersteinRegime input

---

### MetaModelNode

**Module:** `omega.nodes.victoria.meta_model`  
**Type:** strategy | **Project:** victoria | **Autonomy:** L2  
**Version:** 1.1 (added 2026-02-15)

GradientBoosting ensemble meta-learner that takes all signal outputs as features and learns optimal weighting from realized PnL outcomes.

**Data Sources:**
- All signal node outputs
- PaperTradingEngine PnL

**References:**
- *Greedy Function Approximation: A Gradient Boosting Machine* — Friedman 2001
  > GBM as meta-learner for signal stacking

**Changelog:** V1.0: sklearn GBM → V1.1: regime-conditional training

---

### PositionSizingNode

**Module:** `omega.nodes.victoria.position_sizing`  
**Type:** risk | **Project:** victoria | **Autonomy:** L2  
**Version:** 1.2 (added 2026-01-20)

Computes dynamic position sizes using a fractional Kelly criterion adjusted for estimated IC and signal correlation, with risk parity overlay.

**Data Sources:**
- Signal IC history
- Portfolio correlation matrix

**References:**
- *A New Interpretation of Information Rate* — Kelly 1956
  > Original Kelly criterion for optimal bet sizing
- *Risk Parity Portfolios: Efficient Frontiers and Optimal* — Qian 2011
  > Risk parity as diversification constraint on Kelly positions

**Changelog:** V1.0: fixed Kelly → V1.1: fractional Kelly → V1.2: risk parity overlay

---

### DynamicWeightAllocator

**Module:** `omega.nodes.victoria.dynamic_weights`  
**Type:** strategy | **Project:** victoria | **Autonomy:** L2  
**Version:** 1.1 (added 2026-01-15)

Maintains rolling Bayesian IC estimates per signal using exponential decay. Updates weights after each cycle outcome. Powers IC-weighted ensemble in VictoriaNode.

**Data Sources:**
- Per-cycle signal predictions vs outcomes (internal)

**References:**
- *Bayesian Learning in Undirected Graphical Models* — Koller & Friedman 2009
  > Bayesian updating framework for IC estimation

**Changelog:** V1.0: equal weights → V1.1: Bayesian IC decay

---

### RiskManagementNode

**Module:** `omega.nodes.victoria.risk_management`  
**Type:** risk | **Project:** victoria | **Autonomy:** L2  
**Version:** 1.1 (added 2026-01-10)

Enforces position limits, max drawdown stops, and portfolio-level concentration rules. Integrates DebateGate adversarial checks before any trade is approved.

**Data Sources:**
- Portfolio state
- DebateGate adversarial output

**Changelog:** V1.0: basic limits → V1.1: DebateGate integration

---

### DataIngestionNode

**Module:** `omega.nodes.victoria.data_ingestion`  
**Type:** execution | **Project:** victoria | **Autonomy:** L1  
**Version:** 1.2 (added 2026-01-10)

Fetches OHLCV data from Binance REST with CoinGecko fallback. Caches results and tracks per-source health scores.

**Data Sources:**
- Binance REST klines
- CoinGecko OHLCV

**Changelog:** V1.0: Binance only → V1.1: CoinGecko fallback → V1.2: health tracking

---

### SignalResearchNode

**Module:** `omega.nodes.victoria.signal_research`  
**Type:** reasoning | **Project:** victoria | **Autonomy:** L3  
**Version:** 1.0 (added 2026-02-20)

Uses QUICK-tier LLM to analyze MemoryKernel episodes and generate research hypotheses about new alpha signals. Currently generates hypotheses but does not auto-test them.

**Data Sources:**
- MemoryKernel episodes
- Cycle outcome history

**References:**
- *Hypothesis Generation in Scientific Discovery* — Langley et al. 1987
  > Automated hypothesis generation as ML loop component

**Changelog:** V1.0: LLM hypothesis generation from episodes

---

### VerificationNode

**Module:** `omega.nodes.victoria.verification`  
**Type:** execution | **Project:** victoria | **Autonomy:** L2  
**Version:** 1.0 (added 2026-02-15)

Compares live trade outcomes to backtest expectations and flags systematic divergences (slippage, latency, fill rate).

**Data Sources:**
- Live trade records
- Backtest reference database

**Changelog:** V1.0: initial divergence checks

---

### DataCleanersNode

**Module:** `omega.nodes.victoria.cleaners`  
**Type:** execution | **Project:** victoria | **Autonomy:** L2  
**Version:** 1.1 (added 2026-02-10)

Multi-stage data validation pipeline: DataIntegrityNode (NaN/outlier detection), LintNode (schema validation), PropertyTestNode (statistical invariants), ConvergenceMonitorNode (IC trend monitoring).

**Data Sources:**
- All upstream signal outputs (validation only)

**Changelog:** V1.0: NaN + outlier detection → V1.1: IC trend monitoring

---

## Polymarket

| Name | Type | L | IC | Memory | Brain | Purpose |
|------|------|---|----|----|---|---|
| **EdgeDetectionNode** | signal | L2 | — | ✓ | ✗ | Only bet when expected value is positive and large enough to justify execution cost. |
| **VolArbNode** | signal | L2 | — | ✓ | ✗ | Vol arb between prediction markets and options markets exploits model disagreement on event probability distributions. |
| **WeatherEnsembleNode** | signal | L2 | — | ✓ | ✗ | Weather prediction markets are dominated by retail bettors — ensemble meteorological models have systematic edge over simple forecasts. |
| **PolymarketPricingNode** | execution | L1 | — | ✗ | ✗ | Market data ingestion layer for Polymarket — all edge detection depends on accurate current prices. |
| **LatencyArbNode** | strategy | L1 | — | ✗ | ✗ | Polymarket markets referencing crypto prices lag Binance by 30–120 seconds — first mover wins edge. |
| **BinanceFeedNode** | execution | L0 | — | ✗ | ✗ | Provides the Binance price reference that LatencyArbNode uses to detect lagged Polymarket updates. |

### EdgeDetectionNode

**Module:** `omega.nodes.polymarket.edge_detection`  
**Type:** signal | **Project:** polymarket | **Autonomy:** L2  
**Version:** 1.1 (added 2026-02-01)

Computes edge as the difference between Omega's model probability and Polymarket's market price for binary events. Calculates Kelly fraction when edge exceeds threshold.

**Data Sources:**
- Gamma API (Polymarket markets)
- Internal probability models

**References:**
- *A New Interpretation of Information Rate* — Kelly 1956
  > Kelly criterion applied to binary prediction market betting

**Changelog:** V1.0: fixed edge threshold → V1.1: adaptive threshold from outcome history

---

### VolArbNode

**Module:** `omega.nodes.polymarket.vol_arb`  
**Type:** signal | **Project:** polymarket | **Autonomy:** L2  
**Version:** 1.0 (added 2026-02-15)

Detects opportunities where Polymarket's implied volatility (from binary option pricing) diverges significantly from realized volatility on the underlying asset.

**Data Sources:**
- Gamma API
- Binance options (realized vol)
- Deribit (implied vol)

**Changelog:** V1.0: initial vol comparison

---

### WeatherEnsembleNode

**Module:** `omega.nodes.polymarket.weather_ensemble`  
**Type:** signal | **Project:** polymarket | **Autonomy:** L2  
**Version:** 1.2 (added 2026-02-20)

Runs a 30-member NOAA GEFS weather ensemble for 57 cities and aggregates probabilistic temperature/precipitation forecasts to price Polymarket weather event markets.

**Data Sources:**
- NOAA GEFS ensemble API (open-meteo)
- Polymarket weather markets

**References:**
- *The ECMWF Ensemble Prediction System* — Buizza et al. 2008
  > Ensemble weather forecasting methodology and calibration

**Changelog:** V1.0: 10-member ensemble, 20 cities → V1.1: 30-member → V1.2: 57 cities + adaptive confidence

---

### PolymarketPricingNode

**Module:** `omega.nodes.polymarket.pricing`  
**Type:** execution | **Project:** polymarket | **Autonomy:** L1  
**Version:** 1.1 (added 2026-02-01)

Fetches active Polymarket event markets via Gamma API and computes fair value probabilities using calibrated Bayesian priors.

**Data Sources:**
- Gamma API (Polymarket)

**Changelog:** V1.0: basic fetch → V1.1: Bayesian calibration

---

### LatencyArbNode

**Module:** `omega.nodes.polymarket.strategies.latency_arb`  
**Type:** strategy | **Project:** polymarket | **Autonomy:** L1  
**Version:** 1.0 (added 2026-03-01)

Detects latency arbitrage opportunities when Binance crypto price moves before Polymarket crypto-related event markets update.

**Data Sources:**
- BinanceFeedNode (real-time prices)
- Gamma API (event markets)

**Changelog:** V1.0: initial latency arb detection

---

### BinanceFeedNode

**Module:** `omega.nodes.polymarket.strategies.binance_feed`  
**Type:** execution | **Project:** polymarket | **Autonomy:** L0  
**Version:** 1.0 (added 2026-03-01)

Stateless Binance spot price feed connector for Polymarket correlation detection. Fetches current prices and 24h stats.

**Data Sources:**
- Binance REST ticker API

**Changelog:** V1.0: initial

---

## Shared Intelligence

| Name | Type | L | IC | Memory | Brain | Purpose |
|------|------|---|----|----|---|---|
| **ReasoningNode** | reasoning | L3 | — | ✓ | ✓ | Cross-project reasoning layer — any node that needs LLM decision-making delegates here. |
| **ReflectionNode** | reasoning | L3 | — | ✓ | ✓ | Continuous learning via self-reflection — turn cycle outcomes into persistent strategic knowledge. |
| **SemanticMemoryNode** | memory | L2 | — | ✓ | ✗ | Break project silos — Victoria's regime knowledge should inform Polymarket's event probability models. |

### ReasoningNode

**Module:** `omega.nodes.shared.reasoning_node`  
**Type:** reasoning | **Project:** shared | **Autonomy:** L3  
**Version:** 1.1 (added 2026-02-01)

LLM-powered structured reasoning with QUICK-tier brain and MemoryBus context injection. Produces structured decisions with confidence and evidence fields.

**Data Sources:**
- MemoryBus (regime insights, risk warnings)
- Caller-provided context

**Changelog:** V1.0: basic LLM calls → V1.1: MemoryBus context injection

---

### ReflectionNode

**Module:** `omega.nodes.shared.reflection_node`  
**Type:** reasoning | **Project:** shared | **Autonomy:** L3  
**Version:** 1.2 (added 2026-02-01)

Per-cycle LLM reflection that analyzes cycle outcomes and writes regime insights to both the episodic MemoryKernel and cross-project MemoryBus. Memory consolidation gap: written episodes never consolidated to semantic.

**Data Sources:**
- Cycle outcome metrics
- MemoryKernel episodes

**Changelog:** V1.0: episodic writes only → V1.1: MemoryBus writes → V1.2: structured insight format

---

### SemanticMemoryNode

**Module:** `omega.nodes.shared.semantic_memory`  
**Type:** memory | **Project:** shared | **Autonomy:** L2  
**Version:** 1.0 (added 2026-02-10)

Cross-project semantic memory index that enables Victoria and Polymarket to share distilled strategic insights. Wraps the MemoryBus with semantic retrieval (embedding-based similarity).

**Data Sources:**
- MemoryBus
- MemoryKernel (both projects)

**Changelog:** V1.0: initial cross-project semantic retrieval

---

## Platform

| Name | Type | L | IC | Memory | Brain | Purpose |
|------|------|---|----|----|---|---|
| **DevilsAdvocateNode** | reasoning | L3 | — | ✓ | ✗ | Force explicit risk consideration before every trade — if the devil can't find a flaw, proceed with higher confidence. |
| **DashboardNode** | platform | L2 | — | ✗ | ✗ | Single pane of glass for system health — tracks all node metrics and generates actionable improvement suggestions. |
| **SkillCreatorNode** | platform | L1 | — | ✗ | ✗ | Self-extending platform — new capabilities discovered during cycles are formalized as reusable skills. |
| **CalculatorNode** | platform | L1 | — | ✗ | ✗ | Reference node for testing the autonomy framework — also used in integration tests. |
| **TextAnalyzerNode** | platform | L1 | — | ✗ | ✗ | Demonstration of self-improving node pattern — shows how improve() unlocks higher-capability versions. |
| **WebFetcherNode** | platform | L1 | — | ✗ | ✗ | Resilient HTTP layer used by any node that needs to fetch external data without managing retry logic itself. |

### DevilsAdvocateNode

**Module:** `omega.nodes.devils_advocate`  
**Type:** reasoning | **Project:** platform | **Autonomy:** L3  
**Version:** 1.1 (added 2026-01-20)

Adversarial challenger that generates counter-arguments to proposed trades via ChallengeRegistry and DebateGate. Currently rule-based; LLM challenge generation is not yet wired.

**Data Sources:**
- ChallengeRegistry (internal)
- Proposed trade parameters

**References:**
- *Thinking, Fast and Slow* — Kahneman 2011
  > Adversarial pre-mortem as bias reduction technique

**Changelog:** V1.0: ChallengeRegistry + DebateGate → V1.1: structured rebuttal format

---

### DashboardNode

**Module:** `omega.nodes.dashboard_node`  
**Type:** platform | **Project:** platform | **Autonomy:** L2  
**Version:** 1.1 (added 2026-01-20)

Monitoring and reporting node that self-evaluates system health, generates improvement reports, and exports metrics. Cannot take action — observes only.

**Data Sources:**
- All node health metrics (internal)
- StateStore

**Changelog:** V1.0: health metrics → V1.1: improvement report generation

---

### SkillCreatorNode

**Module:** `omega.nodes.skill_creator`  
**Type:** platform | **Project:** platform | **Autonomy:** L1  
**Version:** 1.0 (added 2026-02-01)

Factory node that generates new SKILL.md capability definitions at runtime based on observed node behaviour patterns.

**Data Sources:**
- Node capability logs (internal)

**Changelog:** V1.0: initial SKILL.md generation

---

### CalculatorNode

**Module:** `omega.nodes.calculator`  
**Type:** platform | **Project:** platform | **Autonomy:** L1  
**Version:** 1.0 (added 2026-01-10)

Stateful arithmetic node with add/subtract/multiply/divide. Tracks operation counts and error rates as a reference implementation for the node framework.

**Changelog:** V1.0: initial reference implementation

---

### TextAnalyzerNode

**Module:** `omega.nodes.text_analyzer`  
**Type:** platform | **Project:** platform | **Autonomy:** L1  
**Version:** 1.0 (added 2026-01-15)

Sequential text analysis with progressive feature unlock: v1.0 (word count), v1.1 (sentiment), v1.2 (entity extraction), v1.3 (topic modelling). Demonstrates the improve() progression pattern.

**Data Sources:**
- Text input (caller-provided)

**Changelog:** V1.0: word count only (v1.1–v1.3 implemented but improve() never called)

---

### WebFetcherNode

**Module:** `omega.nodes.web_fetcher`  
**Type:** platform | **Project:** platform | **Autonomy:** L1  
**Version:** 1.1 (added 2026-01-15)

HTTP fetch with exponential-backoff retry, response caching, and per-URL reliability score learning from historic success/failure rates.

**Data Sources:**
- Any HTTP endpoint (caller-provided)

**Changelog:** V1.0: basic retry → V1.1: per-URL reliability scoring

---

