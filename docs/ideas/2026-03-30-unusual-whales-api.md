# /research: Unusual Whales API — Options Flow, Dark Pool & Congressional Trading

**Source:** https://unusualwhales.com/public-api + https://github.com/unusual-whales/unusual-whales-official-mcp
**Date:** 2026-03-30
**Score:** 4/5 × 3/5 = **12/25 — Queue for next sprint**

---

## What It Is

Unusual Whales provides a REST API + official MCP server with **100+ endpoints** across 15 data
categories. Primary value is market microstructure intelligence that Omega has no equivalent for:
real-time options flow, dark pool transactions (with NBBO context), congressional trading,
insider filings, and institutional 13F holdings.

- **API base:** `https://api.unusualwhales.com/api`
- **OpenAPI spec:** `https://api.unusualwhales.com/api/openapi`
- **Auth:** `Authorization: Bearer <UW_API_KEY>` header
- **Rate limits:** not publicly documented; assumed tiered
- **Free tier:** unconfirmed — paid plan required; historical options data ~$250/mo

---

## Endpoint Categories (15 total)

| Category | Key Endpoints | Omega Value |
|---|---|---|
| **Flow** | `/flow/alerts`, `/flow/full-tape`, `/flow/net-flow`, `/flow/sector-flow` | ★★★★★ — put/call ratio, IV crush signals |
| **Dark Pool** | `/darkpool/{ticker}`, `/darkpool/recent` | ★★★★★ — smart money accumulation |
| **Congress** | `/congress/trades`, `/congress/late-filings`, `/congress/member/{member}` | ★★★★☆ — alternative alpha |
| **Insider** | `/insider/{ticker}`, `/insider/sector-flow` | ★★★☆☆ — confirms whale signal |
| **Institutions** | `/institutions/{ticker}`, `/institutions/ownership-changes` | ★★★☆☆ — 13F lagged |
| **Stock** | `/stock/{ticker}/options-flow`, `/stock/{ticker}/iv-rank`, `/stock/{ticker}/max-pain` | ★★★★☆ — fills IV gap |
| **Shorts** | `/shorts/{ticker}/interest`, `/shorts/{ticker}/borrow-rate` | ★★★☆☆ — borrow cost signal |
| **Seasonality** | `/seasonality/monthly`, `/seasonality/yearly` | ★★☆☆☆ — useful for regime context |
| **Market** | `/market/overview`, `/market/sector-tide` | ★★★☆☆ — macro flow context |
| **ETF** | `/etf/{ticker}/flows`, `/etf/{ticker}/holdings` | ★★☆☆☆ — institutional proxy |
| **Earnings** | `/earnings/upcoming`, `/earnings/historical` | ★★☆☆☆ — event calendar |
| **News** | `/news/market` | ★★☆☆☆ — duplicates FinBERT feed |
| **Screener** | `/screener/stocks`, `/screener/options` | ★★☆☆☆ — discovery only |
| **Options** | `/options/{contract}/flow`, `/options/{contract}/historic` | ★★★★☆ — contract-level microstructure |
| **Politicians** | `/politicians/{member}/portfolio` | ★★★☆☆ — premium tier required |

---

## Gap Analysis vs Omega V23

**Fills real gaps:**
1. **No options pricing / IV surface model** (flagged in `project_omega.md`) → `/stock/{ticker}/iv-rank` + flow tape directly address this
2. **No dark pool / L2 intelligence** → `/darkpool/{ticker}` with NBBO context
3. **No congressional/insider alternative data** → pure alpha from documented outperformance
4. **VRP signal** currently estimates IV; this gives actual IV rank per ticker

**Already covered — skip:**
- OHLCV / technical indicators (SMA, RSI, MACD, etc.) — Omega's 6-provider chain is sufficient
- News sentiment — FinBERT already handles this

---

## Signal Design (post-integration)

### 1. Options Flow Signal
- Compute net call/put premium delta over rolling 2h window
- Bullish: net call premium > 2× put premium AND large trades > $500k
- Bearish: inverse
- Confidence scaled by unusual volume ratio (flow vs 30d avg)

### 2. Dark Pool Signal
- Detect dark pool print clusters near technical support/resistance
- Bullish: dark pool accumulation > 1% of ADV below 20d MA
- Bearish: distribution above recent high

### 3. Congressional Alpha Signal
- Track net buy/sell ratio of congress members per sector
- Congress tends to outperform by documented ~14% annually (2021 Unusual Whales report)
- Weight: low (slow signal, 30-90d holding horizon)

---

## Implementation Plan

**Files created (this PR):**
- `omega/nodes/victoria/unusual_whales_provider.py` — HTTP client + DataProvider subclass
- `omega/nodes/victoria/unusual_whales_node.py` — `@omega_node` SignalAdapter wrapping UW flow signals

**Future work (needs API key):**
- Wire into Victoria's signal ensemble and meta-model router
- Backtest options flow signal IS/OOS with overfitting gate
- Add `UW_API_KEY` to `.env.example`

---

## Recommendation

Build the skeleton now (done in this commit). Wire up signals once API key is available.
The options flow + dark pool combination directly fills the biggest gap in Omega's signal library.
Congressional trading adds a slow but well-documented alternative alpha source.

**Next action:** Obtain API key from unusualwhales.com/settings/api-dashboard and run IS/OOS backtest on options flow signal against BTC/ETH.
