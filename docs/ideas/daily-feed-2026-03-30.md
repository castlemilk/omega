# Omega Daily Research Feed - 2026-03-30

## Executive Summary

Today's scan covers 8 target Twitter/X accounts. Key highlights: Unusual Whales launched an MCP Server giving AI assistants live options/equities data access; Bittensor SN13 (Macrocosmos) scaled to 55B+ scraped posts for decentralized data pipelines; Glassnode on-chain metrics show BTC in late-stage bear transition at $66K with five bottom signals flashing; DeFi TVL shows Mantle surging +214% MoM after Aave launch. Quant Science continues pushing Python algo trading education and QF-Lib toolkit.

---

## 1. @unusual_whales - Unusual Whales

**Recent Activity:** HIGH relevance

Unusual Whales launched the **Unusual Whales MCP Server**, a major infrastructure release connecting AI assistants (Claude, Cursor, VS Code) to 100+ live market data endpoints.

**Key Details:**
- 18 tools and 123+ actions for options flow, dark pool, congressional trading, Greek exposure, volatility
- Real-time sweeps, block trades, dark pool prints alongside NBBO context
- 13F filings, insider trades, congressional trading activity
- 30+ built-in analysis prompts (morning-briefing, unusual-flow, pre-earnings, greek-exposure, bullish-confluence)
- Remote endpoint: `https://api.unusualwhales.com/api/mcp`
- NPM package: `@unusualwhales/mcp`
- GitHub: https://github.com/unusual-whales/unusual-whales-official-mcp

**Relevance to Omega: HIGH**
This is directly actionable. The MCP server could be integrated into Omega's research pipeline for real-time options flow data, dark pool analysis, and smart money tracking. The 30+ built-in prompts could seed Omega's own signal generation workflows.

**Action Items:**
- [ ] Evaluate Unusual Whales API pricing and rate limits
- [ ] Prototype MCP integration for options flow signals
- [ ] Backtest correlation between unusual options flow and crypto derivatives moves
- [ ] Explore dark pool data as a leading indicator for institutional crypto positioning

---

## 2. @Data_SN13 / Macrocosmos - Bittensor Subnet 13

**Recent Activity:** HIGH relevance

Macrocosmos (operating Bittensor SN13 - Data Universe) continues scaling as the decentralized data layer for the Bittensor ecosystem.

**Key Details:**
- Now hosts **55 billion+ scraped posts and comments** from X, Reddit, YouTube
- Built a high-fidelity digital twin simulation of the IOTA communication network (SN9)
- Data Universe supplies real-time data pipeline feeding the entire Macrocosmos ecosystem
- Expanding to Tumblr, GitHub as new data sources
- Transparency dashboard in development
- Gravity API for queryable data access
- GitHub: https://github.com/macrocosm-os/data-universe

**Relevance to Omega: HIGH**
55B social media posts is a massive alternative data source for sentiment analysis and social signal extraction. The decentralized scraping model means fresher data than traditional providers. Could be integrated as an alpha signal source for crypto sentiment.

**Action Items:**
- [ ] Test Gravity API for real-time crypto sentiment extraction
- [ ] Compare SN13 data freshness vs. traditional social data providers
- [ ] Build NLP pipeline on SN13 data for crypto-specific sentiment scoring
- [ ] Explore SN13 as a data source for Omega's signal library

---

## 3. @quantscience_ - Quant Science

**Recent Activity:** MEDIUM relevance

Quant Science continues producing educational content around Python algorithmic trading. Key mentions include QF-Lib and their QSConnect/QSResearch/Omega product suite.

**Key Details:**
- **QF-Lib** (Quantitative Finance Library): event-driven Python toolkit for backtesting, market data access, risk assessment, report generation
- Hosts 20,000+ downloadable quant research papers and blogs
- **FinNLP**: playground for LLMs and NLP in finance, with full pipeline for LLM training and fine-tuning
- **TF Quant Finance**: Google's TensorFlow-based quant finance library for options pricing, curve fitting, optimization
- Jason and Matt launched a hedge fund using the same strategies taught in their program

**Tools & Resources Mentioned:**
- QF-Lib: https://github.com/quarkfin/qf-lib (event-driven backtesting)
- FinNLP: LLM/NLP for finance pipeline
- TF Quant Finance: Google's TensorFlow quant library
- 20K+ research papers archive

**Relevance to Omega: MEDIUM**
QF-Lib's event-driven architecture and FinNLP's LLM finance pipeline could inform Omega's backtesting infrastructure. The research paper archive is a good resource for new signal ideas.

**Action Items:**
- [ ] Review QF-Lib architecture for backtesting pipeline ideas
- [ ] Explore FinNLP for crypto-specific NLP model training
- [ ] Mine the 20K paper archive for novel alpha signals applicable to crypto

---

## 4. @DefiLlama - DeFi Llama

**Recent Activity:** MEDIUM relevance

DeFi Llama continues as the primary open DeFi analytics dashboard. March 2026 data highlights notable TVL shifts.

**Key Details:**
- Tracks 7,000+ DeFi protocols across 500+ chains
- **Mantle**: top-performing chain in top 50, +214% MoM TVL growth after Aave launched on network, now #12 largest chain by TVL
- **Streamflow**: top-performing protocol in top 50, +97.09% MoM
- Fastest-growing chains (weekly, >$10M TVL): Mayachain, Katana, DeFiChain EVM
- DefiLlama Pro launched custom no-code DeFi dashboards combining TVL, fees, volume, and protocol metrics

**Relevance to Omega: MEDIUM**
TVL flow data is a useful signal for identifying chain rotation and protocol momentum. The Mantle/Aave surge is an example of a detectable alpha event. DefiLlama API is already a standard integration point.

**Action Items:**
- [ ] Build automated TVL momentum signals from DefiLlama API
- [ ] Track Aave deployment chain announcements as a leading indicator
- [ ] Monitor chain rotation patterns (fastest-growing chains) for trading signals
- [ ] Integrate DefiLlama Pro metrics into Omega dashboards

---

## 5. @glassnode / @glaboratory - Glassnode

**Recent Activity:** HIGH relevance

Glassnode's on-chain metrics are flashing a convergence of bottom signals for Bitcoin as of late March 2026.

**Key Details:**
- **BTC at $66,416**, down 44% from ATH of $126K (Oct 2025)
- Five simultaneous bottom indicators:
  - MVRV Z-Score: 1.2
  - aSOPR: below 1.0
  - Realized Profit: down 96% from peak ($3B/day in Jul 2025 to <$100M)
  - Hashrate: declining 22%
  - Exchange Reserves: 7-year low at 2.21M BTC
- Glassnode characterizes this as a **"late-stage bear market transition"**
- **Capital flows**: BTC -$9.6B, ETH -$3.2B, Stablecoins +$6.2B
- Ethereum TVL peak outflows of -$23.7B/month in February
- **BTC dominance**: 58.78%, total crypto market cap $2.36T
- **Altcoin Vector 45** index dropping amid high BTC dominance

**Relevance to Omega: HIGH**
Multiple converging bottom signals is a high-conviction macro setup. The stablecoin inflow divergence (+$6.2B vs. BTC/ETH outflows) suggests dry powder accumulation. This is actionable for position sizing and regime detection.

**Action Items:**
- [ ] Implement MVRV Z-Score + aSOPR + Exchange Reserves composite signal
- [ ] Build regime detection model incorporating these 5 bottom indicators
- [ ] Track stablecoin inflow/outflow divergence as a leading indicator
- [ ] Model historical returns from similar multi-indicator convergence events
- [ ] Monitor hashrate recovery as potential trend reversal confirmation

---

## 6. @browomo

**Recent Activity:** No specific content found

Unable to find recent public activity from this account in web search results. The account may be private, inactive, or using a different handle.

**Relevance to Omega: N/A**

---

## 7. @zostaff

**Recent Activity:** No specific content found

Unable to find recent public activity from this account in web search results. The account may be private, inactive, or using a different handle.

**Relevance to Omega: N/A**

---

## 8. @adiix_official

**Recent Activity:** LOW relevance

Limited recent public content found. The account appears active but specific March 2026 posts were not indexed in search results.

**Relevance to Omega: LOW**

---

## Top Priority Action Items

### Immediate (This Week)
1. **Integrate Unusual Whales MCP Server** - Evaluate API, prototype options flow signal pipeline
2. **Implement Glassnode composite bottom signal** - MVRV + aSOPR + Exchange Reserves convergence detector
3. **Build stablecoin divergence monitor** - Track stablecoin inflows vs. BTC/ETH outflows as regime signal

### Short-Term (Next 2 Weeks)
4. **Test Macrocosmos/SN13 Gravity API** - Evaluate decentralized social data for sentiment alpha
5. **Build DefiLlama TVL momentum signals** - Automated chain rotation and protocol momentum detection
6. **Review QF-Lib architecture** - Assess event-driven backtesting patterns for Omega

### Research Queue
7. **Mine Quant Science 20K paper archive** for novel crypto-applicable alpha signals
8. **Model historical returns** from multi-bottom-indicator convergence events
9. **Explore FinNLP** for crypto-specific LLM-based signal generation

---

## Market Context Snapshot (2026-03-30)

| Metric | Value |
|---|---|
| BTC Price | $66,416 |
| BTC Dominance | 58.78% |
| Total Crypto Market Cap | $2.36T |
| BTC from ATH | -44% |
| Stablecoin Net Flows | +$6.2B |
| BTC Capital Flows | -$9.6B |
| ETH Capital Flows | -$3.2B |
| ETH TVL Outflows (Feb) | -$23.7B/mo |
| Exchange BTC Reserves | 2.21M (7yr low) |
| Glassnode Regime | Late-stage bear transition |

---

*Report generated automatically by Omega Research Feed. Data sourced from public web searches of target Twitter/X accounts and associated platforms.*
