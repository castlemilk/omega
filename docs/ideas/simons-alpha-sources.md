# Simons-Grade Alpha Sources for Victoria

## Thinking Like Renaissance Technologies About Crypto Markets

> *"The best way to predict the future is to study the past, or prognosticate."* — Jim Simons

Renaissance Technologies' Medallion Fund averaged ~66% annual returns (before fees) for over 30 years. Their edge wasn't one big signal — it was hundreds of weak learners combined, each earning 0.01–0.05% per trade across millions of trades annually. This document maps that philosophy onto Victoria's crypto trading infrastructure.

**What Victoria already has:** 14+ market signals (OHLCV, cross-asset, order flow, sentiment, derivatives, news, twitter, on-chain, options GEX, liquidation, stablecoin flows, BTC dominance, long/short ratio), quant models (HMM regime, PCA factors, transfer entropy, Kelly sizing, GradientBoosting meta-model), memory/reflection system, inter-node attention fusion.

**What this document adds:** The macro, political, trade, and alternative data layer that transforms Victoria from a crypto-native system into a cross-asset intelligence platform.

---

## Table of Contents

1. [Macro-Crypto Linkages](#1-macro-crypto-linkages)
2. [Political-Crypto Linkages](#2-political-crypto-linkages)
3. [Global Trade Linkages](#3-global-trade-linkages)
4. [Market Microstructure](#4-market-microstructure)
5. [Alternative Data (The Simons Edge)](#5-alternative-data-the-simons-edge)
6. [What Would Simons Actually Build?](#6-what-would-simons-actually-build)
7. [Master Data Source Registry](#7-master-data-source-registry)
8. [Prioritized Implementation Plan](#8-prioritized-implementation-plan)
9. [Architecture Integration](#9-architecture-integration)

---

## 1. Macro-Crypto Linkages

The single most important insight: **crypto is a liquidity derivative**. Bitcoin's price is ultimately a function of global monetary conditions. Understanding the transmission mechanisms gives Victoria predictive power that most crypto-native systems lack entirely.

### 1.1 Federal Funds Rate → Crypto

**The Mechanism:** Interest rates affect crypto through three channels: (a) opportunity cost — higher rates make risk-free yields more attractive vs. non-yielding BTC; (b) risk appetite — rate hikes signal tightening, reducing speculative capital; (c) discount rate — higher rates reduce the present value of speculative future narratives.

**Critical Nuance — Rate vs. Rate-of-Change:** The academic evidence (IMF Working Paper 2023/163, NY Fed Staff Report No. 1052) shows it's the **rate of change** and **surprise component** that moves crypto, not the level itself. Markets price in expected hikes. The tradeable signal is the deviation from expectations (measured via Fed Funds futures).

**Time-Varying Relationship:** Pre-2020, US tightening actually *increased* Bitcoin prices (BTC as inflation hedge narrative). Post-2020, the correlation flipped — contractionary policy now consistently depresses crypto. This regime change coincides with institutional adoption making crypto behave as a high-beta risk asset correlated ~0.5-0.7 with S&P 500.

**Lead Time:** FOMC decisions have immediate impact (minutes), but the full transmission to crypto takes 2-6 weeks as the liquidity effect propagates through the financial system.

**Data Source:**
- **FRED API** — `DFEDTARU` (Fed Funds upper target), `DFF` (effective fed funds rate)
- **CME FedWatch** — Implied probabilities from Fed Funds futures
- **API:** `https://api.stlouisfed.org/fred/series/observations?series_id=DFF&api_key=YOUR_KEY&file_type=json`
- **Frequency:** Daily (FRED), real-time (futures)
- **History:** Back to 1954 (FRED)
- **Implementation Complexity:** Low — simple REST API, well-documented Python wrapper (`fredapi`)

### 1.2 M2 Money Supply — The 70-Day Lag Thesis

**The Thesis:** Global M2 money supply leads Bitcoin price by approximately 70-90 days. When M2 expands, new money eventually flows into risk assets including crypto, with the lag representing the time for monetary expansion to work through the banking system into financial markets.

**Academic Evidence:**
- A 2025 cointegration analysis (Preprints.org) found a 1% increase in M2 associates with a 2.65% increase in BTC price
- The correlation between BTC and M2 (shifted 84 days) reaches 0.77-0.78 in 2025 data
- The 90-day lag is empirically derived but approximate — it varies by 20-30 days depending on market conditions
- The relationship is stronger during risk-on regimes and weakens during crypto-specific events (hacks, regulatory shocks, halvings)

**Critical Assessment:** The M2-BTC correlation is real but not a silver bullet. It broke down during the 2022 FTX collapse (crypto-specific shock), during the 2024 ETF approval (crypto-specific demand shock), and during periods of extreme dollar strength. The lag also isn't fixed — it compresses during high-volatility periods and extends during low-vol regimes.

**The Real Signal:** Don't just track M2 level. Track **M2 YoY growth rate** and its **second derivative** (acceleration/deceleration of money printing). The acceleration signal is the strongest predictor.

**Data Sources:**
- **FRED API** — `M2SL` (US M2, monthly), `WM2NS` (weekly M2)
- **Global M2** — Requires aggregating: US (`M2SL`), EU (`ECB BSI data`), Japan (`BOJ monetary base`), China (`PBOC M2`)
- **BGeometrics** — Pre-aggregated global M2 vs BTC chart + API subscription
- **Frequency:** Weekly (US), Monthly (global)
- **History:** US M2 back to 1959 on FRED
- **Implementation Complexity:** Medium — US is easy via FRED; global requires scraping/aggregating from 4+ central bank APIs

### 1.3 DXY (Dollar Strength Index)

**The Mechanism:** BTC is priced in USD. When the dollar strengthens (DXY rises), BTC denominated in USD falls — and vice versa. The correlation coefficient ranges from -0.3 to -0.65 depending on the period.

**When The Correlation Breaks:**
1. **Crypto-specific demand shocks** (ETF approvals, halvings) — BTC rallies regardless of DXY
2. **Simultaneous risk-off events** — Both BTC and USD can fall together as investors rush to cash (March 2020)
3. **FOMO-driven retail rallies** — Pure hype overrides macro (late-stage bull markets)
4. **The narrative regime matters** — If BTC is in "digital gold" mode, DXY weakness is very bullish; if BTC is in "risk asset" mode, the relationship is looser

**The Tradeable Signal:** DXY's **rate of change** is more predictive than its level. A DXY breakdown below key moving averages (50-day, 200-day) is a strong BTC buy signal. Conversely, DXY breakouts above resistance compress BTC valuations.

**Data Sources:**
- **FRED API** — `DTWEXBGS` (Trade-weighted US Dollar Index, Broad)
- **Yahoo Finance** — `DX-Y.NYB` (DXY futures)
- **TradingView** — Real-time DXY via websocket
- **Frequency:** Daily (FRED), real-time (futures)
- **History:** Back to 1973

### 1.4 Real Yields (TIPS Spread)

**The Mechanism:** Real yield = nominal Treasury yield minus expected inflation. This is the **actual opportunity cost** of holding crypto. When real yields are negative (2020-2021), holding BTC has zero opportunity cost because even "safe" assets lose purchasing power. When real yields go positive (2022+), every dollar in BTC has a real alternative return it's foregoing.

**Why This Matters More Than Nominal Yields:** In 2021, 10Y yields were 1.5% but inflation was 7% — real yields were deeply negative (-5.5%), making BTC extremely attractive. In 2023, 10Y yields were 4.5% with 3% inflation — real yields of +1.5% made safe assets genuinely competitive.

**The Tradeable Signal:** Real yield inflection points are powerful BTC signals. The transition from negative to positive real yields (Q1 2022) preceded the crypto bear market by weeks. Watch the 5Y and 10Y TIPS breakeven rates.

**Data Sources:**
- **FRED API** — `DFII10` (10Y TIPS yield), `T10YIE` (10Y breakeven inflation), `REAINTRATREARAT10Y` (real interest rate)
- **Frequency:** Daily
- **History:** Back to 2003

### 1.5 Yield Curve (2s10s Spread)

**The Mechanism:** The spread between 10Y and 2Y Treasury yields has preceded every US recession in the last 50+ years when inverted. Inversions signal the market expects rate cuts (short-end high) and economic slowdown (long-end depressed).

**The Paradox for Crypto:** Inversions initially hurt crypto (risk-off signal). But the subsequent **de-inversion** (steepening) is often more damaging — it typically coincides with the actual onset of recession and aggressive rate cuts. The steepening in late 2023 preceded notable crypto weakness.

**However:** The eventual rate-cutting cycle that follows is extremely bullish for crypto, as it expands liquidity and lowers opportunity costs. The key is timing the transition.

**The Tradeable Signal:** Track the spread AND its velocity. Rapid steepening from inverted territory is a warning sign. Track alongside the HMM regime model — regime shifts often coincide with yield curve inflection points.

**Data Sources:**
- **FRED API** — `T10Y2Y` (10Y-2Y spread, daily)
- **CryptoSlate** — Pre-built BTC vs 2s10s overlay charts
- **Frequency:** Daily
- **History:** Back to 1976

### 1.6 Global Liquidity (The Master Signal)

**The Thesis:** Bitcoin is the world's most liquidity-sensitive asset. The "Global Liquidity Index" — aggregating major central bank balance sheets (Fed, ECB, BOJ, PBOC, BOE) minus sterilization factors (TGA, RRP) — is arguably the single best macro predictor of BTC direction.

**The Formula:**
```
Net Global Liquidity = (Fed Balance Sheet - TGA - RRP) + ECB Balance Sheet + BOJ Balance Sheet + PBOC Balance Sheet + BOE Balance Sheet
```

All converted to USD using current exchange rates.

**The Nuance:** Since 2021, **Treasury bill issuance and fiscal liquidity channels** (not just central bank balance sheets) have shown the strongest leading relationship with Bitcoin. The TGA drain (Treasury spending down its account at the Fed) injects liquidity into the system just as effectively as QE.

**Correlation Strength:** 0.8-0.9 during major liquidity-driven bull markets, though the relationship has broken down during crypto-specific events (2019, 2022, 2024).

**Data Sources:**
- **FRED API** — `WALCL` (Fed balance sheet), `WTREGEN` (TGA), `RRPONTSYD` (RRP)
- **ECB Statistical Data Warehouse** — Balance sheet data via SDMX API
- **BOJ** — Monthly balance sheet via statistics portal
- **BGeometrics** — Pre-aggregated global liquidity index with API
- **Blockcircle Global Liquidity Scorecard** — Tracks all 5 central banks
- **Frequency:** Weekly (Fed), Monthly (others)
- **History:** Fed back to 2002; global composite from ~2008
- **Implementation Complexity:** High for DIY aggregation, Medium if using BGeometrics/Blockcircle

---

## 2. Political-Crypto Linkages

### 2.1 US Election Cycles

**Historical Pattern (incredibly consistent):**
- BTC dips 2-3 months before elections (uncertainty premium)
- BTC rallies hard in the 90 days post-election regardless of winner
- Post-election 90-day returns: +87% (2012), +44% (2016), +145% (2020), +39% in first week alone (2024)
- Election years coincide with halving years (2012, 2016, 2020, 2024) creating compounding bullish pressure

**2024 Case Study:** BTC surged from ~$68K to $93K in the week following Trump's victory. Total crypto market cap increased $750B (+31%) in one week. This was driven by expectations of pro-crypto regulation, strategic BTC reserve, and SEC reform.

**The Tradeable Signal:** The election cycle is a well-known pattern now, reducing its alpha. The edge is in tracking the **policy specifics** that emerge post-election and positioning ahead of implementation timelines. Track executive orders, cabinet nominations (especially SEC/CFTC chairs), and legislative calendars.

**Data Sources:**
- **PredictIt / Polymarket** — Election odds (real-time)
- **Congress.gov API** — Bill status tracking
- **Federal Register API** — Executive orders
- **Frequency:** Event-driven
- **Implementation Complexity:** Medium

### 2.2 Regulatory Announcements (SEC/CFTC)

**The Opportunity:** Regulatory announcements move crypto prices violently and predictably. The Jan 2026 SEC-CFTC "Project Crypto" joint initiative and subsequent token taxonomy guidance are recent examples.

**Detection Strategy:** NLP pipeline monitoring:
1. **SEC EDGAR RSS feeds** — New filings, enforcement actions
2. **SEC/CFTC press release pages** — Scrape every 60 seconds
3. **Federal Register** — New proposed/final rules
4. **Congressional hearing schedules** — Advance notice of testimony

**Classification Framework:**
- **Bullish:** ETF approvals, favorable classifications, safe harbor provisions
- **Bearish:** Enforcement actions, exchange lawsuits, new restrictions
- **Neutral:** Guidance clarifications, industry workshops

**The Edge:** Most crypto participants react to regulatory news via Twitter/crypto media with a 5-30 minute delay. Scraping primary sources (SEC.gov, CFTC.gov) directly gives a critical speed advantage.

**Data Sources:**
- **SEC EDGAR Full-Text Search API** — `https://efts.sec.gov/LATEST/search-index?q=crypto`
- **SEC RSS Feeds** — `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=&dateb=&owner=include&count=40&search_text=&action=getcompany`
- **Congress.gov API** — `https://api.congress.gov/v3/bill?api_key=YOUR_KEY`
- **Frequency:** Real-time (scraping), minutes (RSS)
- **Implementation Complexity:** Medium-High (NLP classification layer needed)

### 2.3 Geopolitical Risk & Sanctions

**The Mechanism:** Countries facing sanctions or capital controls develop BTC premiums. Turkey, Nigeria, Russia, and Argentina have all shown persistent premiums of 2-15% on local exchanges during periods of currency crisis or sanctions.

**Bitcoin as Safe Haven — The Nuanced Reality:**
- BTC is a **weak safe haven** during geopolitical crises (academic consensus from multiple GARCH studies)
- Gold remains the superior safe haven during extreme events
- BTC shows **stronger safe-haven properties under extreme market conditions** vs. moderate ones
- The Swiss Franc and BTC show safe-haven properties for geopolitical risk during market crashes; gold and Treasuries do not (surprisingly)

**The Tradeable Signal:** Track the **Geopolitical Risk Index (GPR)** published by Caldara & Iacoviello (Fed economists). Spikes in GPR correlate with short-term crypto volatility increases and medium-term BTC demand from affected regions.

**Data Sources:**
- **GPR Index** — `https://www.matteoiacoviello.com/gpr.htm` (monthly, free download)
- **OFAC Sanctions Lists** — US Treasury SDN list updates
- **LocalBitcoins/Paxful P2P premiums** — Regional BTC premium tracking (mostly defunct, now track via Binance P2P regional spreads)
- **Frequency:** Monthly (GPR), event-driven (sanctions)
- **History:** GPR back to 1900

### 2.4 China Crypto Policy

**Historical Impact:** China's various crypto bans (2013, 2017, 2021) have caused 20-65% drawdowns. The 2021 mining ban shifted global hash rate distribution permanently (China dropped from 76% to ~0%; US rose to 37.8%).

**Current Vectors:**
- CBDC (digital yuan) progress — Competitive with decentralized crypto
- Hong Kong crypto licensing — China's proxy for controlled crypto exposure
- Capital flight indicators — USDT premium on Asian exchanges

**Data Sources:**
- **Cambridge Bitcoin Electricity Consumption Index** — Hash rate by country
- **Mining pool APIs** (F2Pool, AntPool, Foundry) — Pool-level hash rate distribution
- **Frequency:** Daily (hash rate), event-driven (policy)

### 2.5 Congressional Crypto Legislation

**Key Bills to Track:**
- **GENIUS Act** (stablecoin framework)
- **FIT21** (market structure / SEC-CFTC jurisdiction)
- **Digital Commodity Exchange Act**
- Any tax legislation affecting crypto (wash sale rules, reporting requirements)

**The Edge:** Bill progression through committee hearings → floor votes → conference → signing creates predictable sentiment waves. Most crypto traders track this poorly.

**Data Sources:**
- **Congress.gov API** — Track bill status changes
- **GovTrack.us** — Bill prognosis scores
- **Quorum Analytics** — Congressional crypto caucus tracking
- **Frequency:** Event-driven, check daily

---

## 3. Global Trade Linkages

### 3.1 Manufacturing PMI → Mining Economics

**The Chain:** China/US PMI → economic activity → energy demand/pricing → electricity costs → miner profitability → hash rate → difficulty adjustment → miner capitulation/accumulation → BTC price.

This is a slow-moving signal (weeks to months) but powerful for identifying miner stress points. When PMI contracts, energy costs often drop, improving miner profitability. Conversely, strong PMI can drive energy competition.

**Data Sources:**
- **FRED API** — `MANEMP` (US manufacturing employment), `ISM-PMI` proxies
- **IHS Markit/S&P Global PMI** — Direct PMI data (paid)
- **NBS China** — Chinese PMI (free, monthly)
- **Frequency:** Monthly
- **Implementation Complexity:** Low

### 3.2 Semiconductor Cycle

**The Mechanism:** NVIDIA/AMD GPU prices → mining profitability → network participation. But since 2023, AI demand has fundamentally altered this equation. GPU prices are now driven more by AI training demand than crypto mining, creating a new dynamic where AI compute shortage → higher GPU costs → mining becomes less profitable → potential miner capitulation.

**The New Angle:** NVIDIA earnings and guidance are now a leading indicator for crypto mining economics. If Jensen Huang signals supply constraints, mining profitability compresses. The 10x annual rise in AI compute demand reported by NVIDIA is permanently restructuring the GPU market.

**Data Sources:**
- **NVIDIA quarterly earnings** — GPU revenue segment breakdown
- **GPU price tracking** — PCPartPicker, eBay sold listings (scraping)
- **TSMC utilization rates** — Leading indicator for chip supply
- **Frequency:** Quarterly (earnings), weekly (GPU prices)

### 3.3 Energy Prices → Mining Profitability

**The Mechanism:** Electricity represents 60-80% of mining operational costs. Mining cost per BTC ranges from $1,324 (Iran) to $321,112 (Ireland). US miners face average costs of $40K-60K per BTC. When BTC price approaches mining cost, miners sell reserves to cover operating costs (capitulation), creating selling pressure that accelerates drawdowns.

**The Tradeable Signals:**
1. **Hash rate declining while difficulty hasn't adjusted** = Miners shutting off = Capitulation selling imminent
2. **Mining profitability crossing below zero** = Forced selling from highly-leveraged miners
3. **Miner outflow to exchanges** = Direct on-chain signal of selling pressure
4. **Hash ribbons** (30-day vs 60-day hash rate MA crossover) = Classic capitulation/accumulation signal

**Data Sources:**
- **EIA API** — US electricity prices by state (free)
- **Henry Hub Natural Gas** — FRED `DHHNGSP`
- **Hashrate Index** — Real-time mining profitability by ASIC model
- **Glassnode** — Miner outflows, revenue, hash rate
- **Frequency:** Daily (energy), real-time (hash rate)

### 3.4 Trade Balance & Container Shipping

**Baltic Dry Index (BDI):** Leading indicator for global trade activity and risk appetite. BDI rising → economic optimism → risk-on → bullish for crypto (indirect). The correlation with crypto is indirect and time-varying — strongest during macro-driven regimes, weakest during crypto-specific narratives.

**Trade Balance Data:** USD demand from trade flows affects DXY, which affects BTC. Countries running large trade deficits need to sell local currency and buy USD, strengthening DXY.

**Data Sources:**
- **FRED API** — `BOPGSTB` (US trade balance)
- **TradingEconomics** — BDI historical data + API
- **Freightos Baltic Index (FBX)** — Container shipping rates
- **Frequency:** Daily (BDI), monthly (trade balance)
- **Implementation Complexity:** Low
- **Estimated Predictive Power:** Low-Medium (indirect, slow-moving, but useful as regime context for the HMM model)

---

## 4. Market Microstructure

### 4.1 Cross-Exchange Order Book Asymmetry

**The Signal:** When Binance shows strong buying pressure while Coinbase displays selling pressure (or vice versa), this divergence creates both arbitrage opportunities and predictive signals. Binance leads price discovery for most pairs; Coinbase leads for BTC/USD during US hours.

**Bid-Ask Asymmetry Research:** Academic studies confirm asymmetric behavior between bid and ask sides, with the ask side deteriorating more during crises. Buy pressure translates into faster price adjustments than sell pressure (consistent with herd effects and FOMO dynamics in crypto).

**Implementation:**
- Track order book imbalance: `(bid_volume - ask_volume) / (bid_volume + ask_volume)` within top N levels
- Cross-exchange divergence: Compare Binance vs Coinbase vs Bybit imbalance ratios
- Feed as features into the GradientBoosting meta-model

**Data Sources:**
- **Binance WebSocket** — `wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms` (Level 2, free)
- **Coinbase Advanced Trade API** — Level 2 order book via WebSocket
- **CoinAPI** — Unified order book data across exchanges (Level 2/3, paid)
- **CoinGlass** — Aggregated order book depth and liquidity delta
- **Frequency:** Real-time (100ms-1s updates)
- **Implementation Complexity:** Medium (need to normalize across exchanges, handle reconnections)

### 4.2 Stablecoin Velocity

**The Signal:** Not just stablecoin supply (which Victoria already tracks), but **velocity** — the ratio of transaction volume to market cap. High velocity = active usage and capital deployment. Low velocity = hoarding/dormancy.

**Why This Matters:** Dune analysts identify stablecoin velocity as the single clearest on-chain metric in 2026, as it separates active usage from passive holding. Rising velocity with stable supply = capital being deployed into crypto (bullish). Rising supply with low velocity = capital parked but not yet deployed (potentially bullish, waiting for catalyst).

**Data Sources:**
- **Dune Analytics** — Pre-built stablecoin velocity dashboards (free SQL queries)
- **Glassnode** — USDT/USDC transfer volume by chain
- **Visa Onchain Analytics** — Stablecoin transaction data
- **Artemis Terminal** — Stablecoin comprehensive analytics
- **Frequency:** Daily aggregation, hourly granularity available
- **Implementation Complexity:** Medium (Dune SQL queries → API → pipeline)

### 4.3 Gas Fees as DeFi Demand Proxy

**The Signal:** Ethereum gas prices reflect DeFi activity intensity. Sustained high gas = active DeFi usage = organic demand. Gas spikes during crashes = liquidation cascades. Gas at multi-month lows = DeFi dormancy (contrarian bullish for eventual reactivation).

**Data Sources:**
- **Etherscan API** — Gas oracle (free)
- **Glassnode** — Historical gas metrics
- **Frequency:** Block-by-block (~12 seconds)

### 4.4 CEX vs DEX Volume Ratio

**The Signal:** Rising DEX share of total volume indicates structural shift toward decentralization and often coincides with retail/degen speculation peaks. Currently DEX represents ~4.2% of total crypto volume, contracted from 6.5% 30 days ago — indicating speculative activity migrating to CEX derivatives (typical late-consolidation pattern).

**Data Sources:**
- **The Block** — DEX vs CEX volume charts
- **DefiLlama** — DEX volume aggregation across chains
- **Frequency:** Daily

---

## 5. Alternative Data (The Simons Edge)

Renaissance was famous for finding signal in non-obvious places — weather data, satellite imagery, obscure government databases. Here's the crypto equivalent:

### 5.1 Google Trends — "Buy Bitcoin"

**The Evidence:** 91% correlation between BTC price and "buy bitcoin" search volume during 2017 bull run. Google Trends Granger-causes Bitcoin trading volume (but has weaker direct price prediction power). Short-lived effect — useful as 1-3 day leading indicator at extremes, not for medium-term prediction.

**The Contrarian Twist:** Track "Bitcoin going to zero" searches as a bottom indicator. Extreme pessimism searches have historically marked local bottoms.

**Implementation:**
- Use Google Trends API (unofficial `pytrends` library) for automated data pulls
- Track: "buy bitcoin", "bitcoin price", "bitcoin going to zero", "crypto crash"
- Compute z-scores relative to 90-day rolling window
- Extreme positive z-scores (>2.0) = retail FOMO (contrarian sell signal)
- Extreme negative z-scores (<-2.0) = capitulation (contrarian buy signal)

**Data Sources:**
- **Google Trends** — `pytrends` Python library (unofficial, rate-limited)
- **Frequency:** Daily (with some lag)
- **History:** Back to 2004
- **Implementation Complexity:** Low
- **Estimated Predictive Power:** Medium at extremes, Low at normal levels

### 5.2 Coinbase App Store Ranking

**The Evidence:** Historical benchmarks suggest Coinbase reaching top 175 in US App Store marks bull market peaks. Rankings below 500 indicate bear market conditions. Currently at #260 (as of Sept 2025), suggesting retail still muted.

**Caveat:** ETFs have fragmented the retail entry point — some investors now access crypto through Fidelity, Schwab, or Robinhood rather than Coinbase. The signal is degrading over time but still useful as a component.

**Data Sources:**
- **Sensor Tower API** — App store rankings (paid, ~$500/mo)
- **App Annie / data.ai** — Alternative app analytics (paid)
- **Manual tracking** — Free via App Store daily checks
- **Frequency:** Daily
- **Implementation Complexity:** Low (if paid), Medium (if scraped)

### 5.3 GitHub Developer Activity

**The Evidence:** A trading strategy based on high GitHub commit activity outperformed buy-and-hold, with less than 1% of random strategies outperforming it. Developer activity is a fundamental health signal — projects with sustained high commit activity are more likely to ship features and attract users.

**Caveats:** Forked projects inherit commit history without doing work. Use weighted metrics (Santiment's approach) that filter for "pure development" events: code pushes, PR merges, issue interactions — excluding forks, stars, and bot activity.

**Data Sources:**
- **CryptoMiso** — GitHub commit rankings (free)
- **Santiment API** — Weighted development activity metric (freemium)
- **GitHub API** — Direct repo statistics (free, rate-limited)
- **Frequency:** Daily
- **History:** Full Git history available

### 5.4 Memecoin Index (Speculation Thermometer)

**The Thesis:** Memecoin volume on Solana (especially pump.fun activity) is the purest measure of retail speculation in crypto. Pump.fun accounts for up to 71% of all tokens minted on Solana and 40-67% of total DEX transactions. This is pure degeneracy — and degeneracy peaks mark cycle tops.

**Implementation:**
- Build a composite "Speculation Index" from: Solana memecoin daily volume, pump.fun token launch rate, memecoin TVL, new wallet creation rate on Solana
- Z-score the composite against 90-day rolling window
- Extreme positive z-scores = peak speculation = contrarian sell signal
- Collapse in memecoin activity after sustained period = washout complete = accumulation signal

**Data Sources:**
- **Dune Analytics** — pump.fun metrics, Solana DEX volume
- **DefiLlama** — Solana TVL breakdown
- **Solscan/Helius API** — Solana on-chain metrics
- **Frequency:** Real-time to daily
- **Implementation Complexity:** Medium

### 5.5 Energy/Weather → Mining Economics

**The Thesis (Historical):** Sichuan province hydropower seasons used to drive Chinese mining hash rate seasonally. Post-2021 ban, the relevant weather patterns are now US (Texas heat waves → grid stress → mining curtailment) and Nordic (seasonal hydropower availability).

**Current Application:** Texas hosts ~30% of US Bitcoin mining. During extreme heat events, miners voluntarily curtail operations (ERCOT demand response programs). This creates predictable hash rate dips and can be front-run using weather forecasts.

**Data Sources:**
- **NOAA Weather API** — Temperature forecasts for mining regions (free)
- **ERCOT** — Texas grid demand data (free, real-time)
- **Frequency:** Daily forecasts, real-time grid data
- **Implementation Complexity:** Medium
- **Estimated Predictive Power:** Low (niche, seasonal, but non-correlated with other signals)

### 5.6 Credit Card / Consumer Spending Data

**The Thesis:** Consumer spending patterns indicate risk appetite. When consumers are spending freely, they're also more likely to speculate in crypto. Declining consumer spending = risk-off approaching.

**Data Sources:**
- **FRED API** — `PCE` (personal consumption expenditures), `RSAFS` (retail sales)
- **University of Michigan Consumer Sentiment** — `UMCSENT` on FRED
- **Frequency:** Monthly
- **Implementation Complexity:** Low

### 5.7 Prediction Markets

**The Thesis:** Polymarket, Kalshi, and similar prediction markets aggregate information about regulatory outcomes, election results, and policy changes faster than traditional news. Polymarket crypto-specific markets (ETF approval odds, regulatory outcomes) have shown strong predictive power.

**Data Sources:**
- **Polymarket API** — Market odds for crypto-relevant events
- **Kalshi API** — Regulated prediction market
- **Frequency:** Real-time
- **Implementation Complexity:** Low-Medium

---

## 6. What Would Simons Actually Build?

Renaissance's real edge wasn't any single data source. It was their **methodology**:

### 6.1 Extremely High-Frequency Pattern Recognition

Medallion operated on intraday timeframes — detecting patterns in tick data that persist for minutes to hours, not days. For Victoria, this means:
- Microstructure signals (order flow imbalance, trade arrival rates) at sub-second resolution
- Cross-exchange latency arbitrage (BTC price leads/lags between Binance, Coinbase, Bybit)
- Funding rate oscillations as mean-reverting signals

### 6.2 Cross-Asset Statistical Arbitrage

Not "BTC goes up" but "when the spread between BTC perpetual funding rate and ETH funding rate exceeds 2 standard deviations, mean reversion occurs within 4 hours." Renaissance found thousands of such micro-relationships. For crypto:
- **Perpetual vs Spot basis** across exchanges
- **Cross-pair correlations** — BTC/ETH, SOL/ETH, DOGE/SHIB relative value
- **Crypto vs Traditional** — BTC/GLD ratio, BTC/SPY ratio, ETH/QQQ ratio as mean-reverting pairs
- **Cross-timeframe momentum** — 1-hour momentum conflicting with daily momentum creates tradeable divergences

### 6.3 Ensemble of Weak Learners

Medallion reportedly ran hundreds of small models simultaneously, each with a tiny edge. The ensemble — properly weighted and risk-managed — produced extraordinary returns. Victoria's meta-model should:
- Maintain 50+ independent signal generators (each of the data sources above)
- Weight signals dynamically based on recent predictive performance (online learning)
- Require consensus across multiple uncorrelated signals before taking large positions
- Accept that individual signals will have 51-55% win rates — the edge is in combination

### 6.4 Massive Computational Backtesting

Simons tested every hypothesis against decades of data before deploying. Victoria needs:
- Full tick-level BTC/ETH history (available from Tardis.dev, Kaiko)
- Macro data aligned to crypto timestamps (FRED + crypto data time-alignment pipeline)
- Walk-forward cross-validation (not in-sample backtesting)
- Monte Carlo simulation of signal degradation (how quickly does each edge decay?)
- Transaction cost modeling (slippage, fees, funding rates eat into micro-edges)

### 6.5 Signal Decay Awareness

Renaissance constantly retired decaying signals and discovered new ones. Every signal Victoria uses should have:
- A real-time performance tracker (rolling Sharpe ratio of each signal)
- Automatic degradation alerts when a signal's predictive power drops below threshold
- Periodic re-estimation of signal parameters (adaptive, not static)

---

## 7. Master Data Source Registry

### Tier 1: High Priority / Strong Evidence / Easy Implementation

| Source | API | Frequency | History | Predictive Power | Complexity | Status |
|--------|-----|-----------|---------|-------------------|------------|--------|
| FRED Fed Funds Rate | `fred/series/DFF` | Daily | 1954+ | High (post-2020) | Low | **NEW** |
| FRED M2 Money Supply | `fred/series/WM2NS` | Weekly | 1959+ | High (r=0.77 w/lag) | Low | **NEW** |
| FRED Real Yields (TIPS) | `fred/series/DFII10` | Daily | 2003+ | High | Low | **NEW** |
| FRED Yield Curve 2s10s | `fred/series/T10Y2Y` | Daily | 1976+ | Medium-High | Low | **NEW** |
| FRED Fed Balance Sheet | `fred/series/WALCL` | Weekly | 2002+ | High | Low | **NEW** |
| FRED TGA | `fred/series/WTREGEN` | Weekly | 2005+ | High | Low | **NEW** |
| DXY Dollar Index | Yahoo Finance `DX-Y.NYB` | Daily/RT | 1973+ | Medium-High | Low | **NEW** |
| Google Trends | `pytrends` (unofficial) | Daily | 2004+ | Medium (at extremes) | Low | **NEW** |
| Stablecoin Velocity | Dune Analytics SQL | Daily | 2020+ | Medium-High | Medium | **ENHANCE** |
| Order Book Imbalance | Binance/Coinbase WS | Real-time | N/A | High (intraday) | Medium | **ENHANCE** |

### Tier 2: Medium Priority / Solid Evidence / Moderate Implementation

| Source | API | Frequency | History | Predictive Power | Complexity | Status |
|--------|-----|-----------|---------|-------------------|------------|--------|
| Global Liquidity Index | BGeometrics API | Monthly | 2008+ | High | Medium | **NEW** |
| Prediction Markets | Polymarket API | Real-time | 2020+ | Medium-High | Low | **NEW** |
| Coinbase App Ranking | Sensor Tower API | Daily | 2014+ | Medium | Medium | **NEW** |
| GitHub Dev Activity | Santiment/GitHub API | Daily | Full history | Medium | Medium | **NEW** |
| SEC/CFTC Filings | EDGAR RSS/API | Real-time | 1990s+ | High (event-driven) | Medium-High | **NEW** |
| Congress Legislation | Congress.gov API | Daily | 2000+ | Medium | Medium | **NEW** |
| GPR Index | matteoiacoviello.com | Monthly | 1900+ | Low-Medium | Low | **NEW** |
| CEX vs DEX Ratio | DefiLlama API | Daily | 2020+ | Medium | Low | **NEW** |
| Memecoin Index | Dune Analytics | Daily | 2023+ | Medium (contrarian) | Medium | **NEW** |

### Tier 3: Lower Priority / Indirect Signal / Higher Implementation Cost

| Source | API | Frequency | History | Predictive Power | Complexity | Status |
|--------|-----|-----------|---------|-------------------|------------|--------|
| Consumer Sentiment | FRED `UMCSENT` | Monthly | 1952+ | Low-Medium | Low | **NEW** |
| Baltic Dry Index | TradingEconomics | Daily | 1985+ | Low (indirect) | Low | **NEW** |
| Energy Prices (NG) | FRED `DHHNGSP` | Daily | 1997+ | Low-Medium | Low | **NEW** |
| ERCOT Grid Data | ERCOT API | Real-time | 2010+ | Low (seasonal) | Medium | **NEW** |
| GPU Pricing | PCPartPicker scrape | Weekly | 2010+ | Low | Medium | **NEW** |
| Weather/Mining | NOAA API | Daily | Decades | Low (niche) | Medium | **NEW** |
| Semiconductor Earnings | Company filings | Quarterly | Decades | Low (slow) | Low | **NEW** |

---

## 8. Prioritized Implementation Plan

### Phase 1: FRED Macro Dashboard (Week 1-2)

**Estimated Alpha Contribution: HIGH**

Build a unified macro data ingestion pipeline from FRED. This is the highest-ROI work because FRED is free, reliable, well-documented, and provides the most academically-validated signals.

**Tasks:**
1. Register FRED API key
2. Build `FREDDataNode` that pulls all Tier 1 FRED series daily
3. Compute derived signals:
   - M2 YoY growth rate + second derivative
   - M2 with 70/84/90 day forward shift (test which lag works best in backtest)
   - Real yield (10Y nominal minus breakeven)
   - Net liquidity = Fed balance sheet - TGA - RRP
   - Fed funds surprise = actual rate - Fed funds futures implied rate
4. Create feature vectors and feed into GradientBoosting meta-model
5. Backtest each signal individually and in combination against BTC daily returns (2015-present)

**Architecture:**
```
FRED API → FREDDataNode → Feature Engineering → Meta-Model
                ↓
         HMM Regime Node (macro regime context)
```

### Phase 2: Global Liquidity Aggregation (Week 2-3)

**Estimated Alpha Contribution: HIGH**

Extend the FRED pipeline to build the full Global Liquidity Index.

**Tasks:**
1. Add ECB balance sheet data (SDMX API)
2. Add BOJ monetary base
3. Add PBOC M2 (or use BGeometrics as shortcut)
4. Build USD-normalized composite index
5. Test various lag structures against BTC (60-120 day window, 5-day increments)
6. Compare with BGeometrics pre-built index for validation

### Phase 3: Political/Regulatory NLP Pipeline (Week 3-5)

**Estimated Alpha Contribution: MEDIUM-HIGH**

Build real-time monitoring of regulatory and political events.

**Tasks:**
1. SEC EDGAR RSS feed scraper (every 60 seconds)
2. CFTC press release scraper
3. Congress.gov bill tracker (daily)
4. Federal Register executive order monitor
5. NLP classification layer:
   - Fine-tune a small LLM (or use zero-shot classification) to categorize announcements as bullish/bearish/neutral for crypto
   - Sentiment score → feature vector for meta-model
6. Polymarket integration for prediction market odds on regulatory outcomes
7. Backtest against historical SEC/CFTC announcements and price reactions

### Phase 4: Microstructure Enhancement (Week 4-6)

**Estimated Alpha Contribution: HIGH (intraday)**

Upgrade Victoria's existing order flow signals with cross-exchange analysis.

**Tasks:**
1. Add Coinbase Advanced Trade WebSocket alongside existing Binance feed
2. Compute cross-exchange order book imbalance divergence
3. Build Binance-Coinbase price lead/lag detector
4. Integrate stablecoin velocity from Dune Analytics
5. Build "Speculation Index" from memecoin/pump.fun activity
6. CEX vs DEX volume ratio tracking via DefiLlama

### Phase 5: Alternative Data Layer (Week 6-8)

**Estimated Alpha Contribution: MEDIUM**

Layer in the non-obvious signals that are uncorrelated with existing features.

**Tasks:**
1. Google Trends automated ingestion (`pytrends`)
2. Coinbase App Store ranking tracker
3. GitHub developer activity via Santiment
4. Energy/mining economics:
   - Hash rate vs difficulty adjustment timing
   - ERCOT grid demand (Texas mining proxy)
   - Mining profitability threshold monitoring
5. Consumer sentiment from FRED

### Phase 6: Simons-Grade Backtesting Infrastructure (Ongoing)

**Estimated Alpha Contribution: CRITICAL (meta-level)**

This isn't a signal — it's the infrastructure that makes all signals trustworthy.

**Tasks:**
1. Acquire tick-level historical crypto data (Tardis.dev recommended)
2. Build time-alignment pipeline for macro data + crypto data
3. Implement walk-forward cross-validation framework
4. Build signal decay monitoring (rolling 30/60/90 day Sharpe per signal)
5. Monte Carlo simulation for portfolio-level risk assessment
6. Transaction cost model (exchange fees, slippage, funding)
7. Automatic signal retirement when performance degrades

---

## 9. Architecture Integration

### How New Signals Wire Into Victoria's Existing Pipeline

```
┌─────────────────────────────────────────────────────────┐
│                   DATA INGESTION LAYER                   │
├──────────────┬──────────────┬──────────────┬────────────┤
│ Existing     │ FRED Macro   │ Political/   │ Alt Data   │
│ (14 signals) │ Dashboard    │ Regulatory   │ Layer      │
│              │ (Phase 1-2)  │ NLP (Phase 3)│ (Phase 5)  │
└──────┬───────┴──────┬───────┴──────┬───────┴─────┬──────┘
       │              │              │             │
       ▼              ▼              ▼             ▼
┌─────────────────────────────────────────────────────────┐
│              FEATURE ENGINEERING LAYER                    │
│  - Derived signals (M2 growth, real yields, net liq.)   │
│  - Z-scores and regime-conditional normalization         │
│  - Cross-signal interaction features                     │
│  - Lag optimization per signal                           │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│              EXISTING MODEL LAYER                        │
│                                                          │
│  HMM Regime ──► NOW INFORMED BY MACRO REGIME CONTEXT    │
│  PCA Factors ──► EXPANDED FACTOR SPACE                   │
│  Transfer Entropy ──► MACRO→CRYPTO CAUSALITY DETECTION  │
│  Kelly Sizing ──► MACRO-ADJUSTED POSITION SIZING         │
│  GradientBoosting Meta ──► 50+ FEATURES (up from 14)    │
│                                                          │
│  Inter-Node Attention Fusion ──► EXPANDED ATTENTION      │
│  Memory/Reflection ──► MACRO CONTEXT IN MEMORY           │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│              SIGNAL QUALITY MONITORING                    │
│  - Per-signal rolling Sharpe ratio                       │
│  - Decay detection and automatic retirement              │
│  - Cross-signal correlation monitoring (avoid crowding)  │
│  - Regime-conditional performance tracking               │
└─────────────────────────────────────────────────────────┘
```

### Key Integration Points

1. **HMM Regime Model Enhancement:** Feed macro indicators (yield curve, real yields, DXY momentum) directly into the HMM as observable emissions. This lets the regime model distinguish between "crypto bull + macro tailwind" (high conviction) vs "crypto bull + macro headwind" (lower conviction, tighter sizing).

2. **Transfer Entropy Expansion:** Currently measures causality between crypto pairs. Expand to measure macro→crypto transfer entropy: Does M2 growth Granger-cause BTC returns? Does DXY change transfer entropy to ETH/BTC ratio? These directional causality measures will dynamically weight macro signals.

3. **Kelly Sizing with Macro Overlay:** Current Kelly criterion uses crypto-only volatility. Add a macro-adjustment factor: reduce Kelly fraction when macro signals conflict with crypto signals (regime uncertainty), increase when macro and crypto signals align.

4. **Meta-Model Feature Expansion:** The GradientBoosting meta-model goes from ~14 features to 50+. Use feature importance tracking to identify which new signals contribute most. Periodically retrain with walk-forward validation.

5. **Memory System Enhancement:** Store macro regime context in the reflection/memory system. "Last time real yields crossed above 2% while M2 growth was decelerating, BTC declined 35% over 6 weeks" — this kind of pattern memory is exactly what Renaissance built.

---

## Appendix: FRED API Quick Reference

```python
# Install: pip install fredapi
from fredapi import Fred
fred = Fred(api_key='YOUR_KEY')

# Key series for Victoria
SERIES = {
    'fed_funds': 'DFF',           # Federal Funds Rate (daily)
    'm2_weekly': 'WM2NS',         # M2 Money Supply (weekly)
    'm2_monthly': 'M2SL',         # M2 Money Supply (monthly)
    'real_yield_10y': 'DFII10',   # 10Y TIPS Yield (daily)
    'breakeven_10y': 'T10YIE',    # 10Y Breakeven Inflation (daily)
    'yield_2s10s': 'T10Y2Y',      # 2Y-10Y Spread (daily)
    'fed_balance_sheet': 'WALCL', # Fed Total Assets (weekly)
    'tga': 'WTREGEN',             # Treasury General Account (weekly)
    'rrp': 'RRPONTSYD',           # Reverse Repo (daily)
    'dxy': 'DTWEXBGS',            # Trade-Weighted Dollar (daily)
    'nat_gas': 'DHHNGSP',         # Henry Hub Natural Gas (daily)
    'consumer_sentiment': 'UMCSENT',  # UMich Sentiment (monthly)
    'pce': 'PCE',                 # Personal Consumption (monthly)
    'trade_balance': 'BOPGSTB',   # Trade Balance (monthly)
}

# Example: Get M2 with 84-day lag alignment to BTC
m2 = fred.get_series('WM2NS', observation_start='2015-01-01')
m2_lagged = m2.shift(84)  # 84 trading days ≈ 12 weeks

# Net Liquidity calculation
fed_bs = fred.get_series('WALCL')
tga = fred.get_series('WTREGEN')
rrp = fred.get_series('RRPONTSYD')
net_liquidity = fed_bs - tga - rrp
```

---

*Document Version: 1.0*
*Created: 2026-03-26*
*For: Victoria (Omega Platform)*
*Philosophy: Hundreds of small edges, rigorously tested, dynamically weighted, constantly refreshed.*
