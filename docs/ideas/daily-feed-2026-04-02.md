# Omega Daily Research Feed — 2026-04-02

## Summary

Today's scan covers 8 monitored Twitter/X accounts. Key themes: DefiLlama launches MCP for AI agents, hedge funds deepening software shorts ($24B profit YTD), quant approaches to prediction market arbitrage, and a comprehensive 151-strategy paper resurfaces. The @glaboratory account had no detectable recent activity; Glassnode Q1 2026 report provides supplementary on-chain context.

---

## @DefiLlama — DefiLlama MCP Launch

**Relevance: HIGH**

DefiLlama announced the **DefiLlama MCP** (Model Context Protocol) — an on-chain data layer for AI agents with 23 tools covering TVL, yields, prices, protocol metrics, and guided research workflows.

**Key details:**
- 23 tool endpoints for DeFi data (TVL, DEX volumes, stablecoin data, yield farming pools, token prices)
- Guided research workflows that teach agents structured DeFi analysis
- Built on FastMCP framework — compatible with Claude, Cursor, and any MCP-compatible agent
- Available with DefiLlama API plan

**Repos/tools mentioned:**
- [demcp/demcp-defillama-mcp](https://github.com/demcp/demcp-defillama-mcp) — community MCP server
- [IQAIcom/mcp-defillama](https://github.com/IQAIcom/mcp-defillama) — alternative MCP server
- [DefiLlama AI page](https://defillama.com/ai) — LlamaAI combining DeFi + TradFi data

**Action items for Omega:**
- Integrate DefiLlama MCP into Omega's data pipeline for real-time DeFi metrics
- Evaluate LlamaAI's parallel research + PDF export for automated report generation
- Consider building custom MCP tools wrapping Omega's proprietary signals

**Source:** [DefiLlama MCP announcement](https://x.com/DefiLlama/status/2037234604629753954)

---

## @unusual_whales — Hedge Fund Software Shorts & Market Signals

**Relevance: HIGH**

Key market intelligence from unusual_whales:

1. **Hedge funds made $24 billion shorting software stocks in 2026 YTD** (per CNBC/S3 Partners), and are increasing positions. Software sector market cap down ~$1 trillion. Heaviest shorts: TeraWulf (35% SI), Asana (25% SI), Dropbox (19%), Cipher Mining (17%). The thesis: basic automation services easily replicated by AI tools.

2. **S&P 500 to 8,000** forecast by Capital Economics.

3. **IBM Quantum Nighthawk** — IBM claims first verified quantum advantage proven by end of 2026.

**Action items for Omega:**
- Build a short-interest momentum factor for software/SaaS names — the crowded short thesis may create squeeze opportunities
- Monitor TeraWulf and Cipher Mining (crypto-adjacent miners) for basis trade opportunities
- Track S&P 500 / crypto correlation regime shifts at the 8,000 level

**Source:** [Hedge fund shorts](https://x.com/unusual_whales/status/2021951676186255637) | [S&P 8000](https://x.com/unusual_whales/status/2026994907110617329)

---

## @zostaff — Quant Approaches to Prediction Markets

**Relevance: MEDIUM**

Thread on how quant traders approach prediction markets differently from retail:

1. **Cross-platform arbitrage**: Bots earned ~$40M in profit from April 2024–2025 on arbitrage divergences alone.
2. **Longshot bias exploitation**: Retail overestimates underdogs (lottery effect). Quants systematically sell longshot contracts to harvest the premium.
3. **Intra-market arbitrage**: Related contracts on the same platform create exploitable inefficiencies.
4. **Institutional entry**: DRW, Susquehanna, Jump Trading building dedicated prediction market desks (market making, microstructure exploitation, cross-platform arb).

Also posted about making "$1M in 3 months with Codex" — likely engagement bait but worth monitoring for any open-source tooling referenced.

**Action items for Omega:**
- The longshot bias and cross-platform arb frameworks translate directly to crypto perpetuals (funding rate arb, cross-exchange basis)
- Study DRW/Jump's microstructure exploitation techniques for application to DEX orderbooks
- Note: Polymarket excluded per task rules, but the *methods* (model-vs-price divergence trading) are universal

**Source:** [Quant prediction markets thread](https://x.com/zostaff/status/2031100908185018664)

---

## @quantscience_ — 151 Trading Strategies Paper & Algo Trading Threads

**Relevance: MEDIUM**

Two notable items:

1. **151 Trading Strategies** (Kakushadze & Serur) — 361-page paper covering strategies across stocks, options, fixed income, futures, ETFs, commodities, FX, convertibles, crypto, volatility, and more. Includes mathematical formulas for each strategy. Available on [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3247865).

2. **472% return strategy thread** — Monthly flow-effect strategy exploiting calendar anomalies:
   - Short entries: 1st and 5th day of each month
   - Long entries: 7 days and 1 day before month-end
   - Based on recurring monthly "flow effects" (rebalancing, options expiry)

3. **Free algo trading course** — 100-hour Python algo trading course released.

**Papers/repos mentioned:**
- [151 Trading Strategies PDF](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3247865)
- [41-page factor paper on 10x stocks](https://ideas.repec.org/p/akf/cafewp/33.html)

**Action items for Omega:**
- Backtest the monthly calendar anomaly strategy on BTC/ETH perpetuals — crypto has even stronger month-end rebalancing flows
- Mine the 151 strategies paper for crypto-adaptable signals (especially volatility, momentum, and mean-reversion categories)
- The 10x stock factor paper may identify characteristics transferable to altcoin screening

**Source:** [151 strategies](https://x.com/quantscience_/status/2036780451239481837) | [472% strategy](https://x.com/quantscience_/status/2025922683083370930)

---

## @Data_SN13 — Bittensor Data Universe & Sentiment Analysis

**Relevance: MEDIUM**

Data Universe (SN13) published a dTAO sentiment analysis showing:
- dTAO sentiment is **negatively correlated** with TAO price
- Sentiment rises during Bittensor breakout moments but drops when TAO price goes up

Also: **Gravity** tool (powered by SN13) enables on-demand scraping of X and Reddit data across arbitrary topics — no technical skills required.

**Tools mentioned:**
- [Gravity by Macrocosmos](https://x.com/MacrocosmosAI/status/1908164761520595235) — real-time X/Reddit data collection
- SN13 Data Universe — decentralized data extraction at scale

**Action items for Omega:**
- The inverse sentiment-price correlation in TAO is a potential contrarian signal — investigate if this pattern holds for other L1 tokens
- Evaluate Gravity as an alternative data source for Omega's sentiment pipeline (decentralized, potentially cheaper than commercial APIs)
- Bittensor subnet data could be an alpha source — decentralized data markets are under-researched

**Source:** [dTAO sentiment analysis](https://x.com/Data_SN13/status/1995864290171998510)

---

## @browomo — Bot Dominance in Markets

**Relevance: LOW**

Post about Python bots dominating markets — one bot reportedly converted $313 into $438K in a month. Claims AI robots read news and respond within milliseconds. Primarily focused on Polymarket (excluded per task rules), but the broader point about bot competition in thin markets is relevant to crypto DEX trading.

**Source:** [Bot dominance post](https://x.com/browomo/status/2009704865476600058)

---

## @adiix_official — Limited Recent Activity

**Relevance: LOW**

Profile describes AdiiX as a "Polymarket analyst" — most content appears Polymarket-focused (excluded per task rules). No recent non-Polymarket activity detected in search results.

---

## @glaboratory — No Detectable Recent Activity

**Relevance: N/A**

No recent posts found from this account in search results. The account may have limited visibility or reduced posting frequency. As a supplement, Glassnode's Q1 2026 report notes Bitcoin entered 2026 following a "decisive drawdown and consolidation phase" with reduced profit-taking pressure and early structural stabilization signs.

**Supplementary source:** [Glassnode Q1 2026](https://insights.glassnode.com/coinbase-glassnode-charting-crypto-q1-2026/)

---

## Priority Implementation List

| Priority | Item | Source | Effort |
|----------|------|--------|--------|
| 1 | Integrate DefiLlama MCP into data pipeline | @DefiLlama | Medium |
| 2 | Backtest monthly calendar anomaly on crypto perps | @quantscience_ | Low |
| 3 | Build short-interest momentum factor for software/crypto-miners | @unusual_whales | Medium |
| 4 | Evaluate Gravity (SN13) for sentiment data pipeline | @Data_SN13 | Low |
| 5 | Mine 151 strategies paper for crypto-adaptable signals | @quantscience_ | High |
| 6 | Study cross-exchange arb / microstructure techniques | @zostaff | Medium |
| 7 | Investigate inverse sentiment-price correlation across L1s | @Data_SN13 | Low |
