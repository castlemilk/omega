# Omega Daily Research Feed — 2026-04-05

## Summary

Today's scan covers the 8 monitored Twitter/X accounts. Direct x.com access remains blocked in this environment; findings are sourced from web search results, cached content, aggregator pages, arXiv, and third-party coverage of account content. Key themes today: **altcoin whale rotation into RWA-linked tokens** (LINK, QNT, BCH cohort accumulation around 3/29–4/4), **Macrocosmos SN13 Data Universe platform expansion** (transparency dashboard + Gravity productisation), **FinRL-X acceptance at PAKDD 2026 DMO-FinTech Workshop** confirming the framework's trajectory, and a **softening perp derivatives regime** (BTC OI ~$46.7B, 24h BTC liquidations only ~$6.6M — a significantly quieter tape than late March). Three of the eight monitored accounts (@browomo, @zostaff, @glaboratory) again had no detectable new posts in search-indexed sources.

Per task rules, Polymarket / prediction-market content is excluded. One promising-looking paper ("PredictionMarketBench") was deliberately skipped on that basis.

---

## @unusual_whales — Altcoin Whale Rotation Into RWA Narrative

**Relevance: HIGH**

Unusual Whales' crypto coverage and mirrored whale-tracker feeds are flagging a rotation out of pure beta (BTC/ETH directional bets) into mid-cap tokens tied to the real-world-asset tokenization narrative. Accumulation window observed 29 March → 4 April:

- **Chainlink (LINK)**: First to show renewed whale-wallet build; concentration driven by RWA oracle narrative (Chainlink integration with ADI Chain announced 3 March has continued to pull flows).
- **Quant (QNT)**: Whale-held supply rose from **7.88M → 7.90M QNT** since 29 March (+20K, ~$1.4M at spot). Coincides with an inverted head-and-shoulders pattern flagged by multiple technicians.
- **Bitcoin Cash (BCH)**: The 10K–100K BCH cohort grew from **4.52M → 4.78M BCH** (+260K, ~$120M) — one of the largest BCH whale adds of the cycle.
- **Secondary names**: CHZ, RAY, ADA cited as April breakout candidates; the 100M–1B ADA cohort executed its largest buy-in in months (+150M ADA).

Contextual derivatives data: BTC open interest ~**$46.7B**, 24h BTC futures liquidations only ~**$6.6M** — a dramatic compression from late-March cascade levels. Market is de-risked and directionally under-positioned relative to early Q1.

**Action items for Omega:**
- Re-run yesterday's **ETH whale accumulation vs. ETF outflow divergence signal** with a rotation overlay: when BTC/ETH whale flows slow AND mid-cap whale accumulation accelerates, this is a "narrative rotation" regime the portfolio overlay should detect.
- Build a **cohort-level accumulation scanner** parameterised over (token, cohort band, lookback). The BCH 10K–100K band moved 260K coins in 7 days — size/time thresholds like this should generate tradeable alerts.
- Tag the **RWA basket** (LINK, QNT, ONDO, POLYX, XDC, MKR) as a distinct sub-universe in Omega's factor model; test whether whale inflows to this basket lead the basket's price return by 2–5 days.
- Factor the **low-liquidation / low-OI regime** into risk sizing: compressed OI after a drawdown historically precedes a volatility expansion — position sizes should be scaled down, not up, into this regime.

**Sources:** [BeInCrypto whales April 2026](https://beincrypto.com/crypto-whales-buying-april-2026/) | [CCN whales altcoins](https://www.ccn.com/analysis/crypto/crypto-whales-altcoins-potential-gains-april-2026/) | [CryptoAdventure whales](https://cryptoadventure.com/what-crypto-whales-are-buying-for-potential-gains-in-april-2026/) | [Unusual Whales crypto dashboard](https://unusualwhales.com/crypto) | [CoinGlass BTC](https://www.coinglass.com/currencies/BTC)

---

## @Data_SN13 — Macrocosmos SN13 Productisation & Gravity Expansion

**Relevance: HIGH**

Subnet 13 Data Universe continues to productise. New / confirmed developments:

- **Gravity** (the job-based scraping service layer sitting on top of SN13 miners) now supports both **X and Reddit**; **YouTube transcript scraping** is in active rollout. Users specify keyword/phrase jobs and receive decentralised scraping output.
- Dataset scale reported as **17B+ social-media items on Hugging Face** (aggregated across X and Reddit miners). Macrocosmos has signalled a **transparency dashboard** and **new data source integrations** (Tumblr, GitHub) on the near-term roadmap.
- Positioning is now firmly "from subnet to services" — Macrocosmos is exposing SN13 as commercial APIs rather than raw subnet infrastructure only, significantly reducing integration cost for consumers.

**Action items for Omega:**
- **Run a paid Gravity pilot** targeting a narrow keyword set (BTC, ETH, SOL + 10 large-cap tickers + known whale alias handles) for a 30-day window. Compare the resulting social feed's predictive power against existing commercial alt-data feeds (LunarCrush, Santiment) on a cost-adjusted basis.
- If/when **GitHub scraping** lands on SN13, build an "open-source quant repo momentum" signal — new commits, stars, and fork velocity on quant-adjacent repos have historically led developer-attention narratives by several weeks.
- Treat the **Hugging Face 17B dataset** as a corpus for offline training of Omega's in-house sentiment model; evaluate licensing terms before committing infrastructure.

**Sources:** [Macrocosmos SN13 docs](https://docs.macrocosmos.ai/subnets/subnet-13-data-universe) | [Macrocosmos — Gravity](https://macrocosmosai.substack.com/p/from-subnets-to-services-how-gravity) | [SN13 GitHub](https://github.com/macrocosm-os/data-universe) | [Tensorplex SN13 primer](https://medium.com/@tensorplexlabs/bittensor-subnet-13-data-universe-decentralised-data-scraping-3787abfe2ae0)

---

## @quantscience_ — FinRL-X Confirmed at PAKDD 2026 DMO-FinTech Workshop

**Relevance: HIGH**

Follow-up on yesterday's @quantscience_ thread on FinRL-X: the paper (Hongyang Yang et al.) is confirmed **accepted at the DMO-FinTech Workshop at PAKDD 2026**. The workshop venue matters — PAKDD's fintech track has historically been a reliable filter for reproducible, production-oriented ML-for-finance work (versus the bulk of arXiv q-fin preprints that don't survive out-of-sample testing).

Separately, @quantscience_ continues to promote its three-product stack publicly (QSConnect for data, QSResearch for ML strategies, Omega for execution — note the naming collision; this is unrelated to our platform). The recurring workshop funnel is useful as a sourcing signal but not directly actionable.

**Key paper(s) surfaced today on arXiv q-fin (non-Polymarket, non-restricted):**
- **"From Deep Learning to LLMs: A Survey of AI in Quantitative Investment"** (arXiv:2503.21422) — broad survey of LLM-based quant workflows, agent-based automation, and predictive modelling. Useful as a literature map for Omega's research agenda even if no single technique is directly new.
- **"A Comprehensive Analysis of ML Models for Algorithmic Trading of Bitcoin"** (arXiv:2407.18334) — benchmarks 41 ML models (21 classifiers, 20 regressors). Older but relevant as a baseline comparison set when Omega evaluates new signal models.

**Action items for Omega:**
- **Clone and evaluate FinRL-X** on a contained sub-problem (e.g. single-venue BTC/USDT 1-minute momentum) to measure whether the modular infrastructure actually reduces iteration time versus our existing pipeline. This has been on the priority list for two days — today's PAKDD confirmation should bump it to "start this week".
- Use the arXiv:2407.18334 **41-model benchmark** as a baseline matrix: any new model Omega introduces for BTC short-horizon prediction should at minimum tie the best classifier / regressor from that set on the same data split.
- Extract and tabulate the LLM-quant survey's (arXiv:2503.21422) agent architectures — map each to an Omega component (data → research → execution) to see which categories we're under-invested in.

**Sources:** [arXiv q-fin recent](https://arxiv.org/list/q-fin/recent) | [Deep Learning to LLMs in Quant Investment](https://arxiv.org/html/2503.21422v1) | [ML Models for BTC Algo Trading](https://arxiv.org/html/2407.18334v1) | [@quantscience_ on X](https://x.com/quantscience_)

---

## @DefiLlama — Stablecoin Mainstreaming & DeFi TVL Context

**Relevance: MEDIUM**

Today's incremental data from DefiLlama dashboards (no single headline post was recovered from the account, but aggregate dashboard state is the more actionable signal anyway):

- **Stablecoin market cap: ~$316.84B** — continuing the 2025 trajectory (161 → 214 tracked stablecoins, 36 → 51 crossing $50M, 11 → 18 crossing $1B).
- **USDT + USDC still ~85%** of total supply. USDT +34% YoY, USDC +75% YoY.
- **Yield-bearing stablecoin supply doubled YoY** and is positioned as 2026's core DeFi collateral type — still the highest-conviction structural opportunity from the DefiLlama data set.

**Action items for Omega:**
- Upgrade yesterday's proposed **yield-bearing stablecoin yield curve tracker** from "backlog" to "in progress". Target tokens: sDAI, sUSDe, USDY, USDM, USD0++, sUSDS. Compute a weighted average "yield-bearing basis" vs. 3-month T-bills and vs. USDC lending rates — this is the core spread for the carry trade.
- Build a **stablecoin supply-growth factor**: monthly net issuance by issuer + by chain. Growth in yield-bearing stablecoin supply should correlate with compressed ETH DeFi lending APRs; if not, that's a mispricing to investigate.
- Model **USDC 75% YoY issuance growth vs. USDT 34%** as a "regulatory-approved liquidity" signal — whether venues and counterparties treat USDC vs. USDT asymmetrically as a funding currency is a meaningful execution consideration.

**Sources:** [DefiLlama](https://defillama.com/) | [DefiLlama stablecoin page](https://defillama.com/stablecoins) | [DL News State of DeFi 2025](https://www.dlnews.com/research/internal/state-of-defi-2025/)

---

## Market Microstructure Context — Funding, OI, Liquidations

**Relevance: HIGH** (supplementary, cross-account)

Today's derivatives snapshot (2026-04-05):

- **BTC open interest: ~$46.7B** — down materially from the $84.1B system-wide figure flagged in the 3 April feed. Traders have de-levered.
- **BTC 24h liquidations: ~$6.6M** — a very quiet tape. Compare to late-March cascade days where single-hour figures exceeded this.
- **Historical anchor (January 2026)**: Institutional futures OI $180–200B, BTC funding +0.51% (70.2% APR), ETH funding +0.56% (76.4% APR). The current regime is materially softer on OI and almost certainly on funding rate too (direct real-time funding numbers were not recovered in today's search window).

**Interpretation**: market is in a **post-cascade, under-positioned state**. The playbook for this regime is distinct from the late-March crowded-long regime:
- Mean-reversion signals have less fuel (no forced liquidation sellers to overshoot into).
- Momentum continuation signals are higher-quality (without leveraged bystanders, moves that do occur reflect real spot demand).
- Basis and carry trades have compressed yields (demand for leverage has fallen).

**Action items for Omega:**
- Add a **leverage regime classifier** with two inputs: (a) rolling 7-day average BTC OI change, (b) rolling 7-day average liquidation volume. Classify regimes as {over-leveraged, neutral, under-leveraged, post-cascade}. Route signals through regime-specific weight tables.
- Lower position sizing automatically in the "post-cascade" regime — this is the regime where narrative/rotation trades (see Unusual Whales section) tend to dominate, and directional beta strategies underperform.
- **Build a funding-rate acquisition pipeline** if it doesn't already exist — today's scan couldn't recover real-time funding numbers, which is a gap the research process should not have. Prefer CoinGlass API + Binance/Bybit/OKX direct feeds with a cache.

**Sources:** [CoinGlass](https://www.coinglass.com/) | [CoinGlass BTC open interest](https://www.coinglass.com/open-interest/BTC) | [Coinalyze](https://coinalyze.net/) | [Gate derivatives signals wiki](https://web3.gate.com/crypto-wiki/article/how-do-futures-open-interest-funding-rates-and-liquidation-data-predict-crypto-derivatives-market-signals-in-2026-20260111)

---

## @browomo — No New Activity Detected

**Relevance: N/A**

Third consecutive day with no new content from @browomo recovered in the scan window. Consistent with a low-frequency or search-unindexed posting pattern. Recommendation: deprioritise unless the account posts something directly referenced elsewhere, or switch to a direct API poll if Omega's alt-data layer can absorb one more feed.

---

## @zostaff — No New Activity Detected

**Relevance: N/A**

No recent content surfaced for @zostaff (open-source quant tooling). As with @browomo, the signal-to-effort ratio on search-indexed scanning is low here; consider switching to a GitHub + RSS fallback for this account's likely content type (repos, releases) rather than relying on X post discovery.

---

## @adiix_official — Polymarket-Dominant; Skipped Per Task Rules

**Relevance: LOW**

@adiix_official remains oriented toward Polymarket content, which is excluded per task rules. No non-Polymarket crypto analytics content was detected in the scan window. No action.

---

## @glaboratory — No New Activity Detected

**Relevance: N/A**

No direct @glaboratory activity surfaced. Glassnode's institutional feed does show continued coverage of Bitcoin on-chain activity in early April 2026 — the phrase "onchain activity is a ghost town, but whales grow more dominant beneath the surface" has been recycled in recent coverage, consistent with the low-liquidation regime flagged above. This is colour, not a signal.

**Sources:** [Glassnode Insights](https://insights.glassnode.com/) | [The Block — Glassnode ghost town quote](https://www.theblock.co/post/358985/bitcoin-onchain-activity-ghost-town-but-whales-grow-more-dominant-glassnode)

---

## Priority Implementation List

| Priority | Item | Source | Effort |
|----------|------|--------|--------|
| 1 | Build cohort-level whale accumulation scanner (token × cohort band × lookback) | @unusual_whales rotation signal | Medium |
| 2 | Start FinRL-X single-venue BTC/USDT pilot (confirmed at PAKDD 2026) | @quantscience_ / arXiv | Medium |
| 3 | Build leverage regime classifier (OI Δ + liquidation volume) and route signals regime-wise | Market microstructure | Medium |
| 4 | Launch Gravity (SN13) 30-day paid scraping pilot on BTC/ETH/SOL + 10 large-caps + whale alias handles | @Data_SN13 | Low |
| 5 | Tag RWA basket (LINK, QNT, ONDO, POLYX, XDC, MKR) as distinct factor sub-universe | @unusual_whales | Low |
| 6 | Upgrade yield-bearing stablecoin yield curve tracker to "in progress" | @DefiLlama | Medium |
| 7 | Build funding-rate real-time acquisition pipeline (CoinGlass + exchange direct) | Market microstructure | Low |
| 8 | Integrate arXiv:2407.18334 41-model BTC benchmark as baseline for new signal evaluation | @quantscience_ / arXiv | Low |
| 9 | Extract LLM-quant agent architecture taxonomy from arXiv:2503.21422 survey | @quantscience_ / arXiv | Low |
| 10 | Switch @browomo and @zostaff scanning to GitHub/RSS fallback feeds | Internal process | Low |

---

## Papers & Repos Referenced Today

| Item | Link | Category |
|------|------|----------|
| FinRL-X (PAKDD 2026 DMO-FinTech accepted) | https://arxiv.org/list/q-fin/recent | Open-source framework |
| Deep Learning to LLMs in Quant Investment (survey) | https://arxiv.org/html/2503.21422v1 | Math finance / ML survey |
| Comprehensive ML Models for BTC Algo Trading (41-model benchmark) | https://arxiv.org/html/2407.18334v1 | Baseline / ML |
| Macrocosmos SN13 Data Universe | https://github.com/macrocosm-os/data-universe | Alt-data infrastructure |
| Macrocosmos Gravity (services layer on SN13) | https://macrocosmosai.substack.com/p/from-subnets-to-services-how-gravity | Alt-data productisation |
| DefiLlama DeFi & stablecoin dashboard | https://defillama.com/ | DeFi analytics |
| CoinGlass derivatives dashboard | https://www.coinglass.com/ | Market microstructure |
| Unusual Whales crypto dashboard | https://unusualwhales.com/crypto | Whale tracking |

---

## Methodology Note

This report was produced autonomously under the scheduled-task skill. Direct x.com access is unavailable in this environment; per-account findings therefore rely on indirect sources (aggregator pages, third-party coverage, arXiv, GitHub, project documentation, and cached content). Accounts marked "no new activity detected" should be understood as "no activity recovered through indirect web search today" — not as a definitive absence of posts. Polymarket-related material was actively excluded throughout.
