# Alpha Edge Research: New Signal Sources for Victoria

**Date**: 2026-03-26
**Objective**: Identify high-value alpha signals available via free APIs to push Victoria from 52.6% win rate / 0.18 Sharpe toward 80%+ / Sharpe >2.0
**Current System**: 11 signal groups + 4 quant models (HMM, factor, info flow, meta-model)

---

## Executive Summary: Signal Priority Matrix

| # | Signal | Availability | Predictive Power | Impl. Effort | Edge Persistence | **Composite** | Priority |
|---|--------|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | Options Microstructure (GEX/IV Skew) | 4 | 5 | 4 | 4 | **17** | **P0** |
| 2 | Liquidation Cascade Prediction | 5 | 4 | 3 | 4 | **16** | **P0** |
| 3 | Stablecoin Flows | 4 | 5 | 2 | 4 | **15** | **P0** |
| 4 | Correlation Regime Shifts | 5 | 4 | 3 | 3 | **15** | **P1** |
| 5 | Cross-Market Lead-Lag | 4 | 4 | 3 | 3 | **14** | **P1** |
| 6 | Whale Wallet Tracking | 3 | 4 | 3 | 3 | **13** | **P1** |
| 7 | Mining Fundamentals | 5 | 3 | 2 | 5 | **15** | **P2** |
| 8 | Macro Event Calendar | 4 | 3 | 2 | 4 | **13** | **P2** |

**Scoring**: 1=worst, 5=best. Composite = sum of all four dimensions.
**Priority**: P0 = implement before 1000-cycle training. P1 = implement during training iteration. P2 = add after baseline established.

---

## 1. Options Microstructure — The Simons Angle

**WHY THIS IS #1**: Options market makers leave mechanical footprints through delta hedging. GEX, IV skew, and max pain create predictable price zones. This is closest to the Renaissance approach: exploiting microstructure patterns invisible to directional traders.

### 1.1 Deribit API (Primary Source)

**Access**: Free public endpoints, no account needed. Authenticated WebSocket recommended for better rate limits.

**Key Endpoints**:
- REST + WebSocket via JSON-RPC v2
- `book.*` channels: order book by strike/expiration
- `trades.*` channels: trade flow
- `ticker.*` channels: best bid/ask per instrument
- DVOL Index: Deribit's implied volatility index

**Rate Limits**: Credit-based system. Free/unauthenticated = IP-rate-limited (stricter). Authenticated accounts get better allocation. Exceeding limits returns error code 10028.

**Data Available**:
- Full options chain (all strikes, all expirations)
- IV by strike (skew/smile computation)
- Open interest by strike
- Volume by strike
- Greeks (delta, gamma, vega, theta)

### 1.2 GEX (Gamma Exposure) Computation

**Formula**:
```
GEX_per_strike = Gamma(K) * OI(K) * ContractMultiplier * Spot^2 * 0.01
Total_GEX = SUM(GEX across all strikes and expirations)
```

**Required Data**: Strike price, OI (calls/puts), IV (to compute gamma via Black-Scholes), DTE, spot price, contract multiplier.

**Market Mechanics**:

| GEX Sign | Dealer Position | Hedging Behavior | Market Effect |
|----------|----------------|------------------|---------------|
| Positive (Long Gamma) | Bought options | Buy dips, sell rallies | Mean-reverting, pinning |
| Negative (Short Gamma) | Sold options | Sell weakness, buy strength | Momentum, breakouts |

**Gamma Flip Points**: Where GEX crosses zero. Price above flip = positive gamma (pinned). Price below flip = negative gamma (momentum). December 2025 example: put gamma floor at $85K, call gamma ceiling at $90K created a dealer-enforced $5K range.

**Glassnode Enhancement (2025)**: Flow-based GEX reconstructs dealer positioning from taker-flow data on each trade, modeling dealer inventory through time.

### 1.3 Max Pain Calculation

**Formula**: For each candidate settlement price, compute total option buyer loss. Max pain = strike where total payout to buyers is minimized.

```python
for settlement_price in all_strikes:
    total_loss = 0
    for strike in chain:
        call_loss = max(0, settlement - strike) * call_OI[strike]
        put_loss = max(0, strike - settlement) * put_OI[strike]
        total_loss += call_loss + put_loss
    max_pain = strike_with_min(total_loss)
```

**Historical Accuracy**: BTC settles within 5% of max pain ~60-65% of the time on quarterly expirations. Much weaker on weeklies/monthlies. Self-fulfilling mechanism: dealers hedge into max pain.

### 1.4 IV Skew and Term Structure

**IV Skew Signal**: Extreme put skew historically preceded +13% BTC returns over 90 days, +133% over 360 days (6-year backtest).

**Term Structure**:
- Contango (normal): longer-dated IV > shorter-dated. Calm market.
- Backwardation (distressed): shorter-dated IV > longer-dated. Short-term fear. Precedes dislocations.

### 1.5 Alternative Data Sources

| Provider | Access | Coverage | Cost |
|----------|--------|----------|------|
| Laevitas | API + dashboard | 15+ exchanges, Greeks, IVs | Free tier / $50/mo premium |
| CoinGlass | Dashboard + API | Max pain, OI, IV by strike | Free tier available |
| CoinAPI | REST + WebSocket | Normalized schema, tick-level | Paid (enterprise) |
| Tardis.dev | Historical | Full trade-by-trade reconstruction | Paid |

### 1.6 Predictive Power Evidence

| Signal | Horizon | Accuracy | Source |
|--------|---------|----------|--------|
| IV Skew extremes | 90-360 days | +13% to +133% avg return | 6-year crypto backtest |
| Max Pain clustering | Hours to expiry | 60-65% (quarterly) | CoinDesk, CoinGlass |
| Gamma Flip breakout | Hours to days | Moderate-high | Glassnode 2025 |
| GEX pinning zones | Intraday | High for direction bias | SpotGamma methodology |
| VPIN (order flow toxicity) | Minutes to hours | Statistically significant | Cornell/Easley et al. 2025 |

**Academic Support**: Cornell (Easley et al., SSRN #4814346) — microstructure metrics significantly predict short-term crypto price dynamics. Roll measure consistently most important feature.

**Rating**: Availability 4/5 | Predictive Power 5/5 | Impl. Effort 4/5 | Edge Persistence 4/5

---

## 2. Liquidation Cascade Prediction

**WHY THIS MATTERS**: Liquidation cascades create the largest intraday moves. Not useful as standalone alpha (Feb 2026 research debunked pure liquidation trading), but **extremely valuable as a risk filter** — reducing tail losses by 3-8x.

### 2.1 Real-Time Liquidation Streams

**Bybit (Fastest — 500ms updates)**:
```
WebSocket: wss://stream.bybit.com/v5/public/linear
Topic: allLiquidation.BTCUSDT
```
```json
{
  "topic": "allLiquidation.BTCUSDT",
  "type": "snapshot",
  "ts": 1739502303204,
  "data": [{
    "T": 1739502302929,
    "s": "BTCUSDT",
    "S": "Sell",
    "v": "1.25",
    "p": "42500.50"
  }]
}
```
Free public access, no auth required, no rate limit on market data streams.

**Binance (1000ms updates)**:
```
WebSocket: wss://fstream.binance.com/ws/!forceOrder@arr
```
```json
{
  "e": "forceOrder",
  "o": {
    "s": "BTCUSDT",
    "S": "SELL",
    "q": "0.001",
    "p": "25000",
    "ap": "24999.50",
    "X": "FILLED"
  }
}
```
Free. Only pushes latest liquidation per symbol per 1000ms window.

**Coinglass Aggregated API**:
- `https://open-api.coinglass.com/public/v2/liquidation` — historical
- `https://open-api.coinglass.com/public/v2/liqHeatmap` — real-time heatmap
- Aggregates 30+ exchanges. Free tier with limitations.

### 2.2 Liquidation Cluster Map Methodology

**Estimating Liquidation Prices**:
```
Long Liquidation = Entry * (1 - 1/Leverage)
Short Liquidation = Entry * (1 + 1/Leverage)

Example: BTC at $85K, 10x leverage
  Long liq: $85K * 0.9 = $76.5K
  Short liq: $85K * 1.1 = $93.5K
```

**Building the Map**:
1. Segment OI by leverage bands (1x, 2-5x, 5-10x, 10-20x, 20x+)
2. For each price level ($100 bands), sum OI that would liquidate
3. Apply kernel density estimation to smooth clusters
4. Overlay funding rate severity as risk intensity

### 2.3 Cascade Prediction Signals

**Pre-Cascade Setup (70%+ probability within 72h)**:
```
IF:
  OI > 40% above 90-day average AND
  Funding rate > 0.05% per 8-hour (18% APR) AND
  Funding sustained 3+ consecutive periods AND
  Macro volatility score elevated
THEN:
  Cascade risk = HIGH
```

**October 2025 Cascade Example**: OI at $54.7B (+82% YTD), funding at 18%+ APR. Trump tariff announcement triggered $2.3B liquidated in single day, $19B OI erased in 36 hours. 86% were long liquidations.

### 2.4 Implementation Architecture

**Best Use: Risk Filter (NOT standalone alpha)**
```python
if cascade_risk_score > 75:
    position_sizing *= 0.5      # Reduce by 50%
    stop_loss_pct *= 0.75       # Tighten 25%
    max_leverage -= 1           # Reduce one notch
```

**Evidence**: Feb 2026 study — standalone liquidation cascade strategy showed +299% return but it was leveraged beta, not alpha. However, as a regime filter it predicts tail crashes at 5.13x crash rate ratio.

**Rating**: Availability 5/5 | Predictive Power 4/5 | Impl. Effort 3/5 | Edge Persistence 4/5

---

## 3. Stablecoin Flows as Leading Indicator

**WHY THIS MATTERS**: 95.24% correlation between stablecoin supply growth and BTC price. Direct measurement of capital staging for crypto purchases. Cleaner signal than macro aggregates.

### 3.1 Data Sources

**CoinGecko API** (Supply Tracking):
- Endpoint: `/simple/price` with market_cap and volume params
- Use coin IDs: `tether`, `usd-coin`
- Rate limit: 5-15 calls/min (free), 30/min (demo)
- Update: 1-5 minute cache

**Etherscan API** (Minting Detection):
- Track USDT contract: `0xdac17f958d2ee523a2206206994597c13d831ec7`
- Minting = transfer FROM null address or Tether Treasury
- Burning = transfer TO null address
- Rate limit: 3 req/sec, 100K calls/day (free)
- V2 endpoint (required since Aug 2025):
```
https://api.etherscan.io/v2/api?chainid=1&module=account&action=tokentx
  &contractaddress=0xdac17f958d2ee523a2206206994597c13d831ec7
  &address=TREASURY_ADDRESS&sort=desc
```

**Whale Alert API** (Real-Time Minting Alerts):
- WebSocket: Real-time alerts for large mints/burns
- Tracks 90%+ of global stablecoin transactions
- Free trial available, then paid tiers

**CryptoQuant** (Exchange Reserves):
- Stablecoin Exchange Reserve: accumulated stablecoins ready for purchase
- Exchange Netflow: directional changes
- Available endpoints: All Stablecoins (ERC20) Exchange Reserve/Netflow/Flows
- Basic plan has limited access; Advanced $39/mo

**Glassnode** (Free Tier):
- Daily resolution (one data point per day)
- Delayed (yesterday's data)
- Tracks 150+ stablecoins via metadata API
- 600 req/min standard rate limit

### 3.2 Signal Interpretation

| Pattern | Signal | Timeframe |
|---------|--------|-----------|
| Rising exchange stablecoin reserve | Capital staging for buys (bullish) | 1-3 days |
| Large minting events (>$500M) | Liquidity injection | 1-2 day lag |
| Exchange outflows + supply reduction | Capital exiting (bearish) | 1-3 days |
| Sustained net issuance rise | Macro bullish trend | Weekly |

### 3.3 Predictive Power Evidence

- **95.24% correlation** between stablecoin supply growth and BTC price
- **1-2 trading day lead**: USDT returns positively predict next-day price across most quantiles
- **Weekly aggregates**: Cleanest trend identification (reduces noise)
- **BIS Working Paper 1270**: $3.5B stablecoin inflows reduce Treasury bill yields 2.5-5bp; outflows have 2-3x asymmetric effect
- **2025 scale**: $4 trillion annualized stablecoin volume, $300B circulating supply

**Rating**: Availability 4/5 | Predictive Power 5/5 | Impl. Effort 2/5 | Edge Persistence 4/5

---

## 4. Correlation Regime Shifts

**WHY THIS MATTERS**: BTC-SPY correlation shifted from near-zero to 0.87 post-ETF. When correlation regimes break, massive mispricing occurs. Detecting the break early = front-running the repricing.

### 4.1 Data Sources (All Free)

| Asset | Ticker | Source | API |
|-------|--------|--------|-----|
| SPY | SPY | yfinance | `yf.download('SPY')` |
| BTC | BTC-USD | yfinance | `yf.download('BTC-USD')` |
| DXY | DX-Y.NYB | yfinance | `yf.download('DX-Y.NYB')` |
| Gold | XAU via Metals-API | metals-api.com | Free tier |
| VIX | ^VIX | yfinance | `yf.download('^VIX')` |

**Alpha Vantage** (backup): 25 free requests/day. Supports all tickers.

### 4.2 Correlation Patterns (2025-2026)

| Pair | Normal Correlation | Regime Break Signal |
|------|-------------------|-------------------|
| BTC/SPY | +0.48 to +0.87 | Decoupling = BTC safe-haven mode |
| BTC/DXY | -0.5 to -0.8 | Positive flip = structural break |
| BTC/Gold | +0.68 to +0.75 (risk-off) | Gold rallying, BTC flat = institutional exit |
| BTC/VIX | Negative (VIX up = BTC down) | Desensitization = regime change |

### 4.3 Detection Methods

**Recommended Stack**:

1. **Real-time detection**: CUSUM + 60-day rolling correlation
   - Library: `statsmodels.stats.diagnostic.breaks_cusumolsresid()`
   - Detects unknown breakpoints without prior specification

2. **Confirmation**: Chow test at suspected breakpoint
   - Library: `statsmodels.regression.linear_model.OLS` + `breaks_chowtest()`

3. **Regime quantification**: DCC-GARCH
   - Library: `mgarch` (pip install mgarch) or `arch`
   - Config: GARCH(1,1) with GED distribution for crypto heavy tails
   - Output: Daily evolving correlation matrix

4. **State labeling**: Hidden Markov Model
   - Library: `hmmlearn.hmm.GaussianHMM`
   - Config: n_components=2 (high-corr vs low-corr regimes)
   - Provides probabilistic state transitions

5. **Multi-regime detection**: Change point detection
   - Library: `ruptures` (PELT algorithm)
   - Config: `rpt.Pelt(model="l2").fit(correlation_series).predict(pen=10)`

### 4.4 Alpha Estimates

| Strategy | Annual Alpha (vs BTC) | Sharpe |
|----------|----------------------|--------|
| Simple correlation breakpoint | 3-8% | 0.8-1.2 |
| DCC-GARCH weighted positioning | 5-12% | 1.2-1.8 |
| Multi-regime HMM | 8-15% | 1.5-2.5 |
| Volatility-adjusted regime overlay | 10-20% | 2.0+ |

**Degradation**: Alpha typically decays 30-50% after strategy publication.

**Rating**: Availability 5/5 | Predictive Power 4/5 | Impl. Effort 3/5 | Edge Persistence 3/5

---

## 5. Cross-Market Lead-Lag Timing

**WHY THIS MATTERS**: Different markets process information at different speeds. CME futures lead spot. Coinbase premium tracks US institutional flow. Price dislocations precede volatility.

### 5.1 CME BTC Futures vs Spot

**Price Discovery**: CME futures play a leading role in price formation (transaction-size dependent).

**CME Gap Statistics**: Gaps under $700 fill with 92% probability within 30 trading days.

**Free Data Sources**:
- Databento: $125 free credits for real-time/historical CME data
- CoinGlass: Free aggregated CME OI at `coinglass.com/BitcoinOpenInterest`
- CryptoDataDownload.com: Free historical futures data

**IMPORTANT**: CME implementing 24/7 trading in early 2026 — gap-based signals will degrade.

### 5.2 Coinbase Premium Index

**Calculation**: `(Coinbase BTC/USD - Binance BTC/USDT) / Binance Price * 100`

**API Endpoints**:
- Coinbase: WebSocket ticker channel for BTC-USD (requires HMAC SHA-256 auth)
  - Docs: `docs.cdp.coinbase.com/advanced-trade/`
- Binance (free, no auth): `GET https://data-api.binance.vision/api/v3/ticker/price?symbol=BTCUSDT`

**Signal**:
- Positive premium: US institutional buying, ETF flows (bullish)
- Negative premium: US risk aversion, overseas dominance (bearish)
- Historical: Positive flips coincide with bull market rallies

**Free Dashboards**: CryptoQuant, CoinGlass, TradingView community scripts

### 5.3 Korean Premium (Kimchi Premium)

**Calculation**: `(Upbit KRW price / USD_KRW rate) - Binance USD price`

**API**: Upbit Open API at `global-docs.upbit.com/` — free public market data

**Current Status (March 2026)**: -2.15% negative premium (inverted). Signal has largely collapsed due to regulatory tightening. **Limited current utility** but worth monitoring for extreme readings.

### 5.4 GBTC Premium/Discount

**Current**: ~+0.02% premium (nearly at NAV) post-ETF conversion. **Limited predictive utility** in current regime.

**Free Data**: CryptoQuant, YCharts, CoinGlass, TheBlock

### 5.5 Lead-Lag Hierarchy

1. CME Futures (price leader, especially large transactions)
2. Binance Spot (primary global reference)
3. Coinbase (US institutional barometer)
4. Upbit (regional/retail sentiment)

**Cross-exchange spread >0.5%** = volatility precursor. Stablecoin deviations mean-revert with ~24-minute half-life.

**Rating**: Availability 4/5 | Predictive Power 4/5 | Impl. Effort 3/5 | Edge Persistence 3/5

---

## 6. Whale Wallet Tracking

**WHY THIS MATTERS**: Philadelphia Fed study (2024) confirmed large ETH holders increase positions before price rises. Whales have informational advantages. Lead time: 6-24 hours.

### 6.1 Data Sources

**Whale Alert API**:
- Base URL: `https://api.whale-alert.io/v1/`
- Transaction endpoint: `/transaction/ethereum/{hash}`
- WebSocket: Real-time alerts for large transactions
- Free: 7-day trial. Paid plans for customizable thresholds.
- JSON fields: blockchain, symbol, transaction_type, from/to (with owner), amount, amount_usd

**Etherscan API V2** (ETH whale tracking):
- Endpoint: `https://api.etherscan.io/v2/api?chainid=1&module=account&action=txlist`
- Free tier: 3 req/sec, 100K calls/day
- Client-side filtering on `value` field (wei) for whale thresholds
- V1 deprecated; V2 required since Aug 2025

**Arkham Intelligence** (entity identification):
- No public free tier. Application-based API access.
- Address-to-entity mapping across chains
- Endpoints: `/intelligence/address/:address/all`, entity lookups, top token holders

### 6.2 Key Addresses to Track

| Entity | Approx Holdings | Category |
|--------|----------------|----------|
| Binance Cold Wallet | ~248,600 BTC | Exchange |
| Robinhood Cold Wallet | ~140,600 BTC | Exchange |
| Bitfinex Cold Wallet | ~130,010 BTC | Exchange |

**Tracking Tools**: CoinGlass Balance Tracker for exchange reserves. Nansen for pre-categorized entities (VCs, funds).

### 6.3 Predictive Power

- **"Moby Dick Effect" (2025 study)**: Whale transactions trigger contagion in top 15 cryptos. Peak impact: 6-24 hours.
- **Q-Learning + whale data**: 22% improvement in BTC volatility forecasts
- **Nansen ML on blockchain microstructure**: 82.68% directional accuracy
- **Philadelphia Fed WP 24-14**: Large holders increase positions before price rises. Informational advantage, not manipulation.

**Rating**: Availability 3/5 | Predictive Power 4/5 | Impl. Effort 3/5 | Edge Persistence 3/5

---

## 7. Mining Fundamentals

**WHY THIS MATTERS**: Hash Ribbons have identified every major BTC bottom since 2015 with 614% average return per signal. Slow-moving but high-conviction. Edge persists because few traders use on-chain mining data.

### 7.1 Hash Rate Data

**Blockchain.com API**: `https://www.blockchain.com/api` — free, daily, JSON/CSV

**CoinMetrics Community API** (best free option):
- `https://community-api.coinmetrics.io/v4`
- No API key required. Creative Commons license.
- Hash rate in hashes/second. JSON and CSV output.
- Historical data via GitHub archives.

**Glassnode**: Free tier = daily resolution, yesterday's data. 600 req/min.

### 7.2 Hash Ribbons Computation

**Methodology (Charles Edwards)**:
```python
hash_rate_30d_ma = hash_rate.rolling(30).mean()
hash_rate_60d_ma = hash_rate.rolling(60).mean()

capitulation = hash_rate_30d_ma < hash_rate_60d_ma  # Red = miners capitulating
buy_signal = (hash_rate_30d_ma > hash_rate_60d_ma) & \
             (hash_rate_30d_ma.shift(1) < hash_rate_60d_ma.shift(1))  # Crossover
```

**Historical Track Record**:

| Date | Signal | Outcome |
|------|--------|---------|
| Jan 2015 | Buy | Major bottom, massive rally |
| May 2021 | Buy | China mining ban recovery |
| Jun 2022 | Buy | Pre-bottom signal |
| Nov 2022 | Buy | FTX collapse capitulation recovery |
| Nov 2025 | Buy | BTC $81K to $90K recovery |

**Average return per signal: 614%** (9 signals, 2015-2025)

**Limitation**: Failed to predict May & July 2025 downtrends. Improved by combining with 10/20-day price SMA crossover.

### 7.3 Puell Multiple

**Formula**: `Daily Miner Revenue / 365-day MA(Miner Revenue)`

**Data Source**: CoinMetrics miner revenue endpoint. CoinGlass free chart at `coinglass.com/pro/i/PM`.

**Thresholds**:
- < 0.5: Extreme miner stress (historically flawless at identifying bottoms)
- > 4.0: Overbought miner profitability (top signal)

### 7.4 Miner Wallet Tracking

**Pool Address Databases** (GitHub):
- `github.com/bitcoin-data/mining-pools` — coinbase tags + output addresses
- `github.com/mempool/mining-pools` — coinbase tags
- Foundry + AntPool = 53% of mining rewards
- Foundry routes 89% of major exchange inflows to Coinbase/Kraken/Gemini

**Sell Signal**: Large miner outflows to exchanges.

### 7.5 Difficulty Adjustment

- Every 2,016 blocks (~2 weeks)
- Free estimators: Newhedge, BitRef, CoinWarz
- API: Hashrate Index `/v1/hashrateindex/network/difficulty-adjustment`

**Rating**: Availability 5/5 | Predictive Power 3/5 | Impl. Effort 2/5 | Edge Persistence 5/5

---

## 8. Macro Event Calendar

**WHY THIS MATTERS**: BTC volatility runs 50-100% higher on FOMC days. 87.5% of 2025 FOMC meetings produced negative 48-hour returns. This is an exploitable pattern.

### 8.1 Data Sources

**FRED API** (Primary for economic data):
- Free API key at `fred.stlouisfed.org`
- 800,000+ time series
- Key series: `CPIAUCSL` (CPI), `UNRATE` (unemployment), `GDP`
- Python library: `pip install fredapi`

**FOMC Calendar**:
- No official Fed API. Parse from `federalreserve.gov/monetarypolicy/fomccalendars.htm`
- Alternative: MNI Markets FOMC Calendar

**TradingEconomics API**:
- Calendar endpoint: `tradingeconomics.com/api/calendar.aspx`
- 20M indicators from 196 countries
- WebSocket streaming for live updates
- JSON/CSV/XML output. Subscription required for full access.

### 8.2 FOMC Trading Pattern (2025 Data)

| Metric | Value |
|--------|-------|
| FOMC meetings with negative 48h BTC returns | 7 of 8 (87.5%) |
| Average post-announcement BTC drop | ~8% |
| FOMC-day volatility vs normal | 50-100% higher |
| Pre-event range compression | Weekly range narrowed to 1.3% |
| Optimal entry after announcement | 4-6 hours post-Powell presser |

**Academic Support**:
- 1bp tightening in 2Y Treasury yield on FOMC day = 0.25% BTC price decrease
- Pre-event Bollinger Band squeeze is reliable signal
- Expansion follows compression within 72 hours with 4-6% directional moves

### 8.3 Implementation

```python
# Vol compression detection
bb_squeeze = (bb_upper - bb_lower) / bb_middle < threshold
if bb_squeeze and days_to_fomc < 3:
    signal = "pre_event_compression"
    # Reduce position sizing, wait for post-event direction
```

**Rating**: Availability 4/5 | Predictive Power 3/5 | Impl. Effort 2/5 | Edge Persistence 4/5

---

## Prioritized Implementation Plan

### Phase 1: Before 1000-Cycle Training (P0 Signals)

**Week 1-2: Options Microstructure**
1. Connect to Deribit WebSocket (authenticated, free account)
2. Build options chain ingestion pipeline
3. Compute GEX in real-time (identify gamma flip points)
4. Compute max pain for active quarterly expirations
5. Track IV skew (25-delta put-call spread)
6. Feed into meta-model as features: `gex_sign`, `gex_magnitude`, `max_pain_distance`, `iv_skew_zscore`, `term_structure_slope`

**Week 2-3: Liquidation Cascade Risk Filter**
1. Connect to Bybit WebSocket (500ms liquidation stream)
2. Connect to Binance forceOrder stream (backup)
3. Integrate Coinglass liquidation heatmap API
4. Build liquidation cluster map (OI by leverage band, estimated liq prices)
5. Compute cascade risk score from: OI_vs_90d_avg, funding_rate, funding_persistence, cluster_proximity
6. Wire as risk overlay: when cascade_risk > threshold, reduce sizing/tighten stops

**Week 3-4: Stablecoin Flow Signals**
1. Set up Etherscan V2 polling for USDT minting events (treasury address monitoring)
2. Integrate CoinGecko for USDT/USDC supply changes (daily)
3. Integrate Glassnode free tier for exchange stablecoin reserves (daily)
4. Compute: supply_change_7d, exchange_reserve_change, mint_burn_ratio
5. Feed as features to meta-model

### Phase 2: During Training Iteration (P1 Signals)

**Week 4-5: Correlation Regime Detection**
1. Pull SPY, DXY, Gold, VIX via yfinance (free, daily)
2. Compute 30/60/90-day rolling correlations (BTC vs each)
3. Implement CUSUM for real-time breakpoint detection
4. Add DCC-GARCH for dynamic correlation modeling
5. Train 2-state HMM on correlation series
6. Feed regime probabilities into meta-model

**Week 5-6: Cross-Market Lead-Lag**
1. Compute Coinbase premium in real-time (Coinbase + Binance APIs)
2. Track CME gap (via CoinGlass or Databento free credits)
3. Monitor cross-exchange spreads as volatility precursor
4. Compute: coinbase_premium_zscore, cme_gap_pct, max_spread_across_exchanges

**Week 6-7: Whale Tracking**
1. Integrate Whale Alert API (free trial + monitor for large transactions)
2. Set up Etherscan V2 for large ETH transfers (>$1M filter client-side)
3. Track exchange hot/cold wallet balance changes (CoinGlass)
4. Compute: whale_net_flow_24h, large_tx_count, exchange_reserve_change

### Phase 3: After Baseline Established (P2 Signals)

**Week 8: Mining Fundamentals**
1. Pull hash rate from CoinMetrics Community API (free, daily)
2. Compute Hash Ribbons (30d/60d MA crossover)
3. Compute Puell Multiple (miner revenue / 365d MA)
4. These are slow signals — use as regime context, not trade timing

**Week 9: Macro Calendar**
1. Parse FOMC calendar dates (static, update quarterly)
2. Integrate FRED API for CPI/PPI/NFP release dates
3. Compute days_to_fomc, vol_compression_score, pre_event_squeeze
4. Reduce position sizing during pre-event windows, delay entries post-announcement

---

## Expected Impact Assessment

### Current Baseline
- Win rate: 52.6%
- Sharpe: 0.18
- Signals: 11 groups + 4 quant models

### With P0 Signals Added (Conservative Estimate)
- Options microstructure: +3-5% win rate (gamma regime awareness)
- Liquidation risk filter: -30% max drawdown (tail protection, not win rate)
- Stablecoin flows: +2-3% win rate (capital flow anticipation)
- **Expected**: ~58-61% win rate, Sharpe 0.5-0.8

### With P1 Signals Added
- Correlation regime: +2-4% win rate (regime-aware positioning)
- Cross-market lead-lag: +1-2% win rate (information edge)
- Whale tracking: +1-2% win rate (smart money following)
- **Expected**: ~62-69% win rate, Sharpe 0.8-1.5

### With Full Stack + Optimized Meta-Model
- Mining fundamentals: regime context (reduces false signals)
- Macro calendar: timing overlay (avoids adverse events)
- Combined ensemble effect with meta-model retraining
- **Expected**: ~68-75% win rate, Sharpe 1.5-2.5

### Reality Check: 80% Win Rate
Getting to 80% requires not just more signals but:
1. **Superior feature engineering**: Interaction terms between signals (e.g., high GEX + stablecoin inflow + positive funding)
2. **Non-linear meta-model**: Gradient boosted trees or neural net ensembles, not linear combination
3. **Adaptive regime switching**: Different signal weights for different market regimes
4. **Execution optimization**: Entry timing, partial fills, slippage management
5. **Aggressive filtering**: Only trade when 4+ signals align (fewer trades, higher conviction)

Renaissance's Medallion Fund achieves ~66% win rate with Sharpe >6 — but with thousands of signals, petabytes of data, and PhD-level researchers. 70-75% with proper implementation of the above is ambitious but achievable. 80% requires either very selective trading (low frequency, high conviction only) or a breakthrough in signal discovery.

---

## Key API Quick Reference

| Signal | Primary API | Endpoint | Auth | Rate Limit | Cost |
|--------|-------------|----------|------|------------|------|
| Options Chain | Deribit | WebSocket JSON-RPC v2 | Recommended | Credit-based | Free |
| Liquidations | Bybit | `wss://stream.bybit.com/v5/public/linear` | None | None | Free |
| Liquidations | Binance | `wss://fstream.binance.com/ws/!forceOrder@arr` | None | Standard | Free |
| Liq Heatmap | Coinglass | `/public/v2/liqHeatmap` | API key | Plan-based | Free tier |
| Stablecoin Supply | CoinGecko | `/simple/price` | Optional | 5-15/min | Free |
| USDT Minting | Etherscan V2 | `/v2/api?module=account&action=tokentx` | API key | 3/sec | Free |
| Exchange Reserves | Glassnode | Community endpoints | None | 600/min | Free (daily) |
| SPY/VIX/DXY | yfinance | `yf.download()` | None | Generous | Free |
| Gold | Metals-API | REST | API key | Tier-based | Free tier |
| Hash Rate | CoinMetrics | `community-api.coinmetrics.io/v4` | None | Standard | Free |
| Miner Revenue | CoinMetrics | Same as above | None | Standard | Free |
| FRED Data | FRED | `fred.stlouisfed.org/api` | API key | Standard | Free |
| Whale Alerts | Whale Alert | `api.whale-alert.io/v1/` | API key | Plan-based | Trial |
| ETH Large Txs | Etherscan V2 | `/v2/api?module=account&action=txlist` | API key | 3/sec | Free |

---

## Required Python Dependencies

```
# Data retrieval
yfinance>=0.2.25
fredapi
requests
websockets
aiohttp

# Computation
numpy>=1.23
pandas>=1.5
scipy>=1.9

# Options math
py_vollib  # Black-Scholes for gamma computation

# Volatility modeling
arch>=5.0
mgarch

# Regime detection
hmmlearn>=0.3.0
ruptures>=1.1.8
statsmodels>=0.14.0
scikit-learn>=1.0
```

---

## References

### Academic Papers
- Easley, O'Hara, Yang, Zhang (2025). "Microstructure and Market Dynamics in Crypto." SSRN #4814346.
- Philadelphia Federal Reserve WP 24-14 (2024). "Beneath the Crypto Currents: The Hidden Effect of Crypto Whales."
- BIS Working Paper 1270. "Stablecoins and Safe Asset Prices."
- "The Moby Dick Effect: Contagious Bitcoin Whales." ScienceDirect 2025.
- "Bitcoin Price Regime Shifts: Bayesian MCMC and Hidden Markov Model Analysis." MDPI 2025.
- "Impact of Bitcoin ETF Approval on Hedging Properties." arXiv:2512.12815.
- "Institutional Adoption and Correlation Dynamics." arXiv:2501.09911.
- "Chasing Liquidation Cascade Alpha in Crypto." Medium, Feb 2026.
- "Anatomy of Oct 10-11, 2025 Crypto Liquidation Cascade." SSRN #5611392.

### API Documentation
- Deribit: docs.deribit.com
- Bybit: bybit-exchange.github.io/docs/v5/
- Binance: developers.binance.com/docs/
- Coinglass: coinglass.com/CryptoApi
- CoinGecko: docs.coingecko.com
- Etherscan V2: docs.etherscan.io
- CoinMetrics: docs.coinmetrics.io/api/v4/
- Glassnode: docs.glassnode.com
- FRED: fred.stlouisfed.org/docs/api/fred/
- Whale Alert: developer.whale-alert.io/documentation/
- Laevitas: docs.laevitas.ch
