# Omega Daily Research Feed - 2026-03-28

## Summary

Moderate activity across monitored accounts. Key themes: Polymarket bot dominance intensifying, quant approaches to prediction markets, and open-source automated stock analysis tooling. Two accounts (@hanakoxbt, @0xricker) had no retrievable recent activity.

---

## Findings

### @browomo (Blaze)
**Topic:** Polymarket bot profitability dominance
**Summary:** Posted a detailed thread claiming 90% of Polymarket profits in 2026 are captured by Python scripts. Key data points: only 16% of users are profitable, most profitable wallets are bots (14 of top 20 on leaderboard). Highlighted specific bot strategies:
- **Latency arbitrage**: One bot turned $313 into $438K in a month by front-running BTC price updates from Binance to Polymarket
- **Risk-free arbitrage**: Bots exploit YES+NO < $1 mispricing thousands of times daily; avg opportunity window down to 2.7 seconds (from 12.3s in 2024)
- **Stream parsing**: Esports bots parse game streams faster than humans and bet on stale odds
- Dynamic fees introduced to counter simple bots have only raised the bar to AI-level bots

**Links:** https://x.com/browomo/status/2009704865476600058
**Relevance:** HIGH - Directly relevant to Omega's Polymarket bot strategy. The latency arbitrage approach and the $40M annual arbitrage extraction figure validate the opportunity. The shrinking opportunity windows (2.7s avg) suggest speed infrastructure matters more than ever.

---

### @zostaff
**Topic 1:** Codex-powered trading bot architecture
**Summary:** Posted about using OpenAI Codex to build an automated trading system without programming skills. The approach uses Codex to generate: product docs, implementation priority files, architecture plans, and tech stack definitions. Claims potential for $1M in 3 months by trading market errors with a custom LLM executing trades.
**Links:** https://x.com/zostaff/status/2032835829014446096
**Relevance:** MEDIUM - The Codex-as-architect approach is interesting for rapid prototyping of trading systems. Worth monitoring for any open-source artifacts.

**Topic 2:** Quant approach to prediction markets
**Summary:** Thread on how quant traders view prediction markets differently from retail. Core insight: quants don't trade opinions, they trade the divergence between price and their probability model. This aligns with how firms like DRW, Susquehanna, and Jump Trading are building dedicated prediction market desks focused on market making, microstructure exploitation, and cross-platform arbitrage.
**Links:** https://x.com/zostaff/status/2031100908185018664
**Relevance:** HIGH - The price-vs-model divergence framework is directly applicable to Omega's approach. The mention of KL-Divergence for flagging statistical inconsistencies between related markets is a concrete technique worth implementing.

**Topic 3:** Free automated stock analysis tool
**Summary:** Shared a self-hosted daily stock analysis pipeline: 3 lines of code to clone, configure, and run. Pulls data from AKshare/Tushare/YFinance, parses news in real-time, runs through an LLM, and delivers daily buy/sell notifications. Claims it replaces $3K/month in paid services.
**Links:** https://x.com/zostaff/status/2033283040584331566
**Relevance:** MEDIUM - The open-source stock analysis pipeline could be adapted for commodity/weather market analysis. Worth cloning the repo to evaluate.

---

### @adiix_official (AdiiX)
**Topic:** Polymarket analysis / AresPro partnership
**Summary:** Active Polymarket analyst and AresPro partner. All content noted as sponsored/commissioned. Recent posts appear focused on crypto/blockchain project promotion. No standout alpha or strategy content found in recent activity.
**Links:** https://x.com/adiix_official
**Relevance:** LOW - Mostly sponsored content. Monitor but don't prioritize.

---

### @hanakoxbt
**Topic:** No recent trading-related activity found
**Summary:** Web search did not surface recent posts from this account related to trading, crypto signals, or prediction markets. The account may be inactive, private, or posting under different topics.
**Links:** N/A
**Relevance:** N/A - Unable to assess. May need direct X platform check.

---

### @0xricker
**Topic:** No recent activity found
**Summary:** Web search returned no results for this account. May be suspended, renamed, or have very low engagement.
**Links:** N/A
**Relevance:** N/A - Unable to assess. Consider removing from watchlist or verifying account status.

---

### @data_sn13 (Data Universe / SN13)
**Topic:** Bittensor decentralized data layer + dTAO sentiment analysis
**Summary:** Data Universe (Subnet 13 on Bittensor) continues building decentralized data infrastructure. Recent notable activity includes dTAO sentiment analysis tracking public opinion shifts around Bittensor's emission model changes. Their Gravity tool enables scraping real-time data from X and Reddit across topics without technical skills. Backed by Macrocosmos AI.
**Links:** https://x.com/Data_SN13/status/1995864290171998510
**Relevance:** MEDIUM - The Gravity data scraping tool could be useful for building sentiment signals for Omega's prediction market models. The dTAO sentiment analysis methodology is worth reviewing as a template for our own market sentiment tracking.

---

## Recommendations for Full /research Analysis

1. **@browomo's Polymarket bot profitability data** (HIGH priority) - The latency arbitrage numbers ($313 -> $438K) and the shrinking opportunity windows need deeper investigation. Research should cover: replicability, infrastructure requirements, and whether Omega can compete at sub-100ms execution speeds.

2. **@zostaff's quant prediction market framework** (HIGH priority) - The price-vs-model divergence approach and KL-Divergence technique for cross-market inconsistency detection should be researched and potentially prototyped.

3. **@zostaff's open-source stock analysis pipeline** (MEDIUM priority) - Clone and evaluate the repo for adaptability to Omega's use cases (weather, commodities, prediction markets).

4. **@data_sn13's Gravity tool** (MEDIUM priority) - Evaluate whether Bittensor's SN13 data layer could serve as a sentiment signal source for Omega's models.
