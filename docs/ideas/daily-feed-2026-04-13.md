# Omega Daily Research Feed — 2026-04-13

> Auto-generated from Twitter/X account monitoring and web research.
> Focus: crypto quant trading, on-chain analytics, market microstructure, alt data, open-source tools, math finance.

---

## Market Context Snapshot

- **BTC dominance**: 58.5% | **Altcoin Season Index**: 34/100
- **DeFi TVL**: ~$94B (price-adjusted decline, not capital exodus — ETH deposits at all-time highs: 25.3M ETH in DeFi)
- **ETH price**: ~$2,105 | **Fear & Greed**: 12 (Extreme Fear)
- **Funding rates**: Neutral to slightly positive; no extreme crowding
- **BTC basis**: Healthy positive on majors, carry trade moderately attractive (1-2% intra-exchange spreads on BTC, 2-3% on alts)
- **Stablecoin supply**: Flat — limited liquidity expansion constraining directional moves
- **Whale activity**: Wallets net-bought 1.29M ETH in under two weeks despite selloff

---

## Account Monitoring

### @unusual_whales — Whale Tracking & Options Flow
**Relevance to Omega: MEDIUM**

Unusual Whales launched "Unusual Predictions" in January 2026, extending their insider-activity radar to prediction markets. Their core platform continues to flag large block orders, option sweeps, and institutional positioning signals.

**Actionable for Omega:**
- Their options flow data (especially 0DTE flow) could serve as a sentiment/momentum signal for crypto-correlated assets
- The concept of flagging "unusual" flow sizes relative to historical norms is directly applicable to on-chain whale detection in Omega's signal pipeline

---

### @DefiLlama — DeFi Analytics
**Relevance to Omega: HIGH**

DefiLlama (now cited by the ECB as a primary data source) continues to be the gold standard for DeFi TVL tracking across 7000+ protocols on 500+ chains. Key insight: the divergence between dollar-denominated TVL ($94B, down) and ETH-denominated deposits (25.3M, all-time high) is a strong conviction signal.

**Actionable for Omega:**
- **Signal idea**: ETH-denominated TVL vs USD-denominated TVL divergence as a contrarian indicator. When dollar TVL drops but ETH deposits rise, it signals accumulation during fear
- **Data source**: DefiLlama API is free and comprehensive — integrate TVL flows as an alternative data signal
- Airdrop farming rotation cycles cause predictable temporary TVL dips — potential mean-reversion signal

---

### @Data_SN13 (Macrocosmos / Bittensor Subnet 13) — Decentralized Data
**Relevance to Omega: HIGH**

Bittensor's Data Universe (SN13) has scaled to 40 billion rows of social media data (X/Twitter, Reddit). Their Gravity tool enables on-demand real-time data collection from X and Reddit on any topic without technical skill.

**Key developments:**
- Expanding to new platforms: Tumblr, GitHub
- Transparency dashboard coming soon
- Gravity provides real-time data feeds to other Bittensor subnets (SN44 Score, SN64 Chutes)
- GitHub repo: [macrocosm-os/data-universe](https://github.com/macrocosm-os/data-universe)

**Actionable for Omega:**
- **Alternative data pipeline**: Gravity could replace or supplement custom Twitter scraping for sentiment signals
- **Cost advantage**: Decentralized scraping avoids Twitter/X API rate limits and costs
- **Research**: Evaluate Gravity's data quality, latency, and coverage vs direct X API access for real-time sentiment scoring

---

### @glassnode (note: @glaboratory may be inactive/renamed)
**Relevance to Omega: MEDIUM**

Glassnode has evolved into a full-stack derivatives analytics platform (not just on-chain). New features include Options Max Pain metric tracking across maturity buckets (1W, 1M, 3M, 6M) at 10-min resolution.

**Actionable for Omega:**
- Max Pain tracking across maturity buckets could inform options-implied directional signals
- Exchange flow metrics remain valuable for whale-tracking signals

---

### @quantscience_ / Quant Finance Papers
**Relevance to Omega: HIGH**

Notable recent papers from arXiv q-fin (April 2026):

1. **"Quantitative Alpha in Crypto Markets: A Systematic Review of Factor Models, Arbitrage Strategies, and Machine Learning Applications"** (SSRN 5225612)
   - Systematic review finding size, momentum, and liquidity factors demonstrate statistical significance in crypto
   - N-BEATS and CNN-LSTM hybrids outperform traditional stat methods for non-linear price patterns
   - **Action**: Review for new factor ideas to add to Omega's signal library

2. **"SBBTS: A Unified Schrodinger-Bass Framework for Synthetic Financial Time Series"**
   - Novel approach to synthetic data generation using Schrodinger Bridge
   - **Action**: Could improve Omega's training data augmentation for regime simulation

3. **"PolySwarm: Multi-Agent LLM Framework for Prediction Market Trading and Latency Arbitrage"**
   - Multi-agent LLM architecture for trading — architectural patterns may transfer to Omega's node orchestration
   - **Action**: Review multi-agent coordination patterns (skip the Polymarket-specific parts)

4. **"Knowledge-Integrated Representation Learning for Crypto Anomaly Detection under Extreme Label Scarcity"**
   - Relational domain-logic integration with retrieval-grounded context for anomaly detection
   - **Action**: Relevant for Omega's regime detection under sparse labeled data

5. **"Cryptocurrency as an Investable Asset Class" (Annual Review of Financial Economics, Vol.18)**
   - Seven stylized facts organizing crypto empirical regularities through asset pricing lens
   - **Action**: Useful framework for validating Omega's factor assumptions

---

## Broader Alpha Ideas from Research

### 1. ETH Accumulation Divergence Signal
**Priority: HIGH**

Whale wallets net-bought 1.29M ETH in two weeks while Fear & Greed is at 12. Record ETH in DeFi (25.3M) despite price being at $2,105. This is a classic accumulation-during-fear pattern.

**Implementation**: Track whale wallet cohort net flows (via Glassnode or on-chain directly) against sentiment indices. When divergence exceeds 2 standard deviations, generate a contrarian long signal.

### 2. Funding Rate / Basis Trade Monitor
**Priority: MEDIUM**

Current environment: neutral funding, healthy positive basis, carry trade moderately attractive. BTC basis expansion above 10% APR would signal renewed bullish conviction + crowded longs. ETH basis normalization above 5% confirms sentiment recovery.

**Implementation**: Omega already tracks funding rates — add basis spread monitoring across exchanges (Binance, Bybit via non-US endpoints, Coinbase, Kraken). Alert when basis exceeds historical percentiles.

### 3. DeFi TVL Flow Divergence
**Priority: MEDIUM**

Dollar TVL declining while native-token deposits increase = conviction capital staying. Airdrop rotation cycles create predictable TVL dips.

**Implementation**: Pull DefiLlama API data, compute ETH-denominated vs USD-denominated TVL ratio. Flag divergences as regime signals.

### 4. Bittensor Gravity as Sentiment Data Source
**Priority: LOW (research phase)**

40B rows of social media data available via decentralized network. Could provide cost-effective alternative to direct X API for sentiment scoring.

**Implementation**: Evaluate Gravity API, benchmark data quality/latency against current data sources. If viable, integrate as an alternative data feed for Victoria's sentiment signals.

### 5. N-BEATS / CNN-LSTM for Non-linear Price Patterns
**Priority: MEDIUM**

Recent systematic review confirms these architectures outperform traditional methods for crypto price pattern capture.

**Implementation**: Evaluate N-BEATS architecture for Omega's signal nodes as a complement to existing models. Focus on regime-conditional variants.

---

## Tools & Repos Mentioned

| Tool/Repo | Description | Link |
|-----------|-------------|------|
| macrocosm-os/data-universe | Bittensor SN13 decentralized data scraping | [GitHub](https://github.com/macrocosm-os/data-universe) |
| DefiLlama | DeFi TVL and analytics dashboard | [defillama.com](https://defillama.com) |
| DefiLlama Pro | Custom no-code DeFi dashboards | [defillama.com/pro](https://defillama.com/pro) |
| Unusual Whales | Options flow + whale tracking | [unusualwhales.com](https://unusualwhales.com) |
| Glassnode Studio | On-chain + derivatives analytics | [studio.glassnode.com](https://studio.glassnode.com) |
| QuantConnect | Open-source algorithmic trading platform | [quantconnect.com](https://www.quantconnect.com) |

---

## Papers to Read

1. "Quantitative Alpha in Crypto Markets" — [SSRN 5225612](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5225612)
2. "Alpha-GPT: Human-AI Interactive Alpha Mining" — [arXiv 2308.00016](https://arxiv.org/html/2308.00016v2)
3. "Cryptocurrency as an Investable Asset Class" — Annual Review of Financial Economics, Vol.18, 2026
4. "Scientific Workflow for Generating Alpha in Quantitative Trading in 2026" — [Medium/SetupAlpha](https://medium.com/@setupalpha.capital/my-scientific-workflow-for-generating-alpha-in-quantitative-trading-in-2026-5238b26d4d95)

---

## Summary

Today's research reveals a market in **extreme fear** (F&G=12) with strong **whale accumulation** underneath — a historically bullish divergence. The most actionable items for Omega are:

1. **Immediate**: Add ETH whale-flow divergence as a contrarian signal (HIGH priority)
2. **Short-term**: Integrate DefiLlama TVL flow data as regime context (MEDIUM priority)
3. **Research**: Evaluate Bittensor Gravity for cost-effective sentiment data (LOW priority)
4. **Read**: The SSRN crypto factor model review for new signal ideas (HIGH priority)

Note: Several monitored accounts (@browomo, @zostaff, @adiix_official) had no findable recent activity via web search. Direct X/Twitter access would improve coverage for the next feed.
