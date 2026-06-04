# Daily Research Feed — 2026-04-12

**Source:** Twitter/X (unauthenticated browse via Chrome MCP)
**Window:** last ~24h from pull time
**Filter:** Polymarket / prediction-market / US-restricted content excluded per scheduled-task instructions.

## TL;DR

Thin day. Three of the eight tracked accounts (`@browomo`, `@zostaff`, `@adiix_official`) are now running almost entirely Polymarket hype content and are explicitly out of scope for this feed. `@unusual_whales` was in political/news mode with no usable flow posts in the window scraped. `@glaboratory` resolves to an unrelated 2011 Indonesian guitar school account — this handle in the watchlist is almost certainly wrong (likely intended `@glassnode` / `@glassnodeTeam`).

The only signal-bearing accounts today were **@quantscience_**, **@Data_SN13**, and **@DefiLlama**. Nothing in the window meets a HIGH-relevance bar for Omega. Two MEDIUM items worth following up on: DefiLlama's "LlamaAI" auto-dashboard pipeline (useful pattern for Omega's own project dashboards) and Quant Science's recurring "Stock Prediction AI" repo pointer (worth auditing as a baseline ML-price-prediction benchmark).

---

## @browomo — SKIP (out of scope)

Bio now reads "prediction market || dm always are open". Pinned and recent posts are Polymarket narrative/stories. Nothing non-Polymarket in the last 24h.

- **Relevance:** N/A (filtered out)
- **Action:** Consider removing from the daily watchlist until the account drifts back toward crypto quant content.

## @zostaff — LOW (mostly off-topic)

Recent posts are (a) self-promo of "The Complete Claude Code Guide", (b) a "built a trading bot in 34 minutes without writing code" hype post that references Polymarket, and (c) a direct "trading here: polymarket.com/?r=zostaff" referral post. The Claude Code guide itself is a meta-productivity article, not a quant alpha source.

- **Relevance:** LOW
- **Repos/tools:** none actually linked (no GitHub)
- **Action:** Ignore today. If `@zostaff` posts an actual code/tooling link in a future run, extract and evaluate.

## @Data_SN13 — LOW (no new content in window)

Most recent posts are from Apr 9 and earlier — outside the 24h window. Topics: language drift analysis on social datasets, Gravity jobs infra migration (Apr 1), and `macrocosm-os/dataverse-cli` (Mar 31) which lets agents pull 50 data entities via API for large-scale dataset construction.

- **Relevance:** LOW (nothing new today)
- **Repos/tools:** `github.com/macrocosm-os/dataverse-cli` (from Mar 31, still worth a look as a potential upstream for alt-data / social signals into Omega)
- **Action:** Park `dataverse-cli` in the "alt data sources to evaluate" list. Re-check account next run.

## @adiix_official — SKIP (out of scope)

All recent posts are Polymarket hype ("$1 → $76,546", "buy every contract under 1¢, set limit at 99¢"). One Claude Code agents tweet but framed as a prediction-market shill.

- **Relevance:** N/A (filtered out)
- **Action:** Flag for removal from watchlist — the account's signal-to-noise for crypto quant is effectively zero since the recent pivot.

## @quantscience_ — MEDIUM

Two real posts in window plus a workshop promo:

1. **"Stock Prediction AI: ML/DL to predict stock price movements in Python"** (~6h ago). Claims 100% free Python code on GitHub. Link to the actual repo was not visible in the scrape (thread teaser). Historically Quant Science tweets this style pointing at public GitHub notebooks.
2. **"How to make your own algorithmic trading system in Python (a complete roadmap)"** (~10h ago). Thread-style roadmap post.

Pinned post is notable: it literally names their internal tool "Omega" — "Omega: Automate trade execution with Python" — as part of their paid QS Connect / QS Research / Omega stack. Name collision only; unrelated to our Omega.

- **Relevance:** MEDIUM
- **Repos/tools:** "Stock Prediction AI" GitHub repo (URL not captured in this pull — resolve in next run by opening the thread)
- **Action:** Next run, open the Stock Prediction AI thread directly and extract the repo URL. If it turns out to be the well-known `borisbanushev/stockpredictionai` repo or similar, treat as a baseline ML-price-prediction benchmark to run against Omega's own signal nodes (comparison point only, not something to merge).

## @unusual_whales — LOW (news mode)

Last 24h posts on the front of the timeline were dominated by political news (Trump/NATO/Iran quotes, Gen-Z workplace WSJ quote, Barron Trump beverage brand). No unusual-options-flow or dark-pool blocks captured in the scrape window. Pinned post is still the March announcement of the "Unusual Whales MCP Server" which streams equities/options/prediction-market data to LLM agents.

- **Relevance:** LOW today; MEDIUM as a general infra item
- **Repos/tools:** Unusual Whales MCP Server (commercial; equities + options focus — only partially useful for a crypto quant stack)
- **Action:** No action from today's feed. Keep the MCP server on the "integrations to evaluate" list for the equities-flavored research side of Omega if that ever becomes in scope.

## @DefiLlama — MEDIUM

Multiple substantive posts in the ~72h window:

1. **Apr 11 — "LlamaAI one-shotted this Monad dashboard."** Claims the LlamaAI agent produced a full Monad ecosystem dashboard pulling directly from the DefiLlama database (onchain fundamentals, tokenomics, ecosystem overview).
2. **Apr 10 — Spark Finance dashboard.** "Most comprehensive dashboard for @sparkdotfi on the market" with detailed financials and usage across Spark products.
3. **Apr 10 — Federal Reserve paper cited DefiLlama as its primary source for stablecoin data.** Useful credibility signal; points at stablecoin time-series as a reliable onchain macro input.
4. **Apr 8 (pinned-ish) — Investor relations portal launched in partnership with Spark.** Protocol-side IR channel; probably out of scope for alpha but worth knowing exists.

- **Relevance:** MEDIUM
- **Repos/tools:** LlamaAI (internal DefiLlama product, not open-source); DefiLlama stablecoin dataset (already public API — `api.llama.fi` / `stablecoins.llama.fi`)
- **Action:**
  - Audit Omega's coverage of DefiLlama's stablecoin endpoints. The Fed-paper-cited dataset is a candidate input for a regime-detection signal (stablecoin market cap deltas as a risk-on/risk-off proxy).
  - LlamaAI is a good design reference for the pattern "natural-language question → dashboard generated from a structured protocol DB". Relevant when we next iterate on how Victoria / project nodes surface their training runs.

## @glaboratory — ACCOUNT MISMATCH

`https://x.com/glaboratory` resolves to `@Glaboratory` ("franzzy G-lab"), an Indonesian guitar school with 184 followers and last activity in 2011. This is clearly not the "on-chain metrics" account intended.

- **Relevance:** N/A
- **Action:** Fix the watchlist. The intended account is almost certainly one of:
  - `@glassnode` — Glassnode (on-chain analytics)
  - `@glassnodeTeam`
  - `@_glassnode`

  Recommend updating the scheduled task to `@glassnode` and re-running.

---

## Cross-cutting notes for Omega

- **Watchlist hygiene:** Three of eight accounts have drifted into Polymarket-only content since the watchlist was built (`@browomo`, `@zostaff`, `@adiix_official`). Since Polymarket is explicitly out-of-scope for this feed, these accounts will produce zero usable output on most days. Suggest replacing them — candidate replacements to consider: `@CryptoQuant_com`, `@Nansen_ai`, `@ArkhamIntel`, `@0xfbifemboy`, `@CL207`, `@tradingriot`.
- **One broken handle:** `@glaboratory` is wrong (fix to `@glassnode`).
- **Only real signal today:** DefiLlama stablecoin dataset audit + Quant Science "Stock Prediction AI" repo audit. Both are MEDIUM priority, both are research-only (no code changes implied for Omega).
- **No HIGH-relevance items** were found in this window. This is a thin day — not a blocker, just noting so the empty signal isn't mistaken for a collection failure.

---

## Run metadata

- Date (local): 2026-04-12
- Pull method: Chrome MCP, unauthenticated X/Twitter profile pages
- Known limitations of this pull: X's virtualized timeline truncated to the top ~5–10 tweets per profile without a logged-in session; thread expansions and embedded media links were not followed. Counts of tweets per profile should be treated as a lower bound.
- Polymarket / prediction-market content filtered out per scheduled-task instructions (Polymarket not available in AU).
