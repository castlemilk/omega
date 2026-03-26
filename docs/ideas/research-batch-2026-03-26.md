# Research Batch — 2026-03-26

## 1. Volatility Harvester / Christensen & Prabhala (1998)

### Source
- Tweet: [@browomo](https://x.com/browomo/status/2035806025778118762)
- Paper: [The relation between implied and realized volatility](https://doi.org/10.1016/S0304-405X(98)00034-8) — B.J. Christensen & N.R. Prabhala, *Journal of Financial Economics* 50(2), Nov 1998, pp. 125–150. Cited 622 times.

### Paper Summary
Christensen & Prabhala challenge the prevailing finding that S&P 100 implied volatility is a biased/inefficient forecast of future realized volatility. Using longer time series and non-overlapping data, they find the opposite: **implied volatility outperforms past volatility in forecasting future volatility** and even subsumes its information content. The earlier bias results were driven by a regime shift around the Oct 1987 crash and overlapping data problems.

**Key insight:** When implied vol and realized vol disagree, implied vol is the better predictor — but that disagreement itself is a tradeable signal.

### The browomo "Volatility Harvester" Strategy
browomo fed Claude the paper and got back a Polymarket bot that:
1. Every 15-min BTC round on Polymarket has **implied volatility** baked into contract prices
2. Binance/Bybit provide **realized volatility** in real-time
3. When implied >> realized (e.g., implied 0.58 vs realized 0.09 after a panic), contracts are overpriced
4. Bot **sells both YES and NO sides**, collecting combined premium > $1.00 against $1.00 max payout
5. The spread (e.g., 5¢ per round) is locked profit before resolution

**Results claimed:** $2,180 in 36 hours. 48 rounds/day. Average edge $3.40/round, up to $18 on high-crush rounds.

### How This Compares to Victoria
- We don't currently have a **vol-arb module** — this is a gap
- Our existing signal pipeline focuses on directional bets, not market-neutral premium harvesting
- The implied-vs-realized spread is a **model-free signal** — no ML needed, just real-time data comparison

### What to Implement
- **Vol-spread monitor**: Track implied vol from Polymarket contract prices vs realized vol from exchange data (Binance/Bybit OHLCV)
- **Dual-side premium harvester**: When vol spread exceeds threshold, sell both sides of short-duration contracts
- **Regime detection**: Per the paper, vol relationships shift around crashes — need a regime-change detector to avoid selling into actual breakouts
- **Copy-trading signal**: browomo mentions wallet `@BoshBashBish` running this at scale — could track as a validation signal

---

## 2. TradingAgents (Tauric Research)

### Source
- Repo: [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
- Paper: [arXiv:2412.20138](https://arxiv.org/abs/2412.20138)
- Claims: up to 30.5% annualized returns

### Architecture
Five-stage sequential pipeline mirroring a trading firm:

1. **Analyst Team** (4 parallel agents):
   - Fundamentals Analyst — company financials, performance metrics
   - Sentiment Analyst — social media sentiment scoring
   - News Analyst — macro indicators, global news
   - Technical Analyst — MACD, RSI, price patterns

2. **Research Team** (Bull vs Bear):
   - Structured debate between bullish and bearish researchers
   - Configurable `max_debate_rounds` for depth

3. **Trader Agent**: Synthesizes analyst + researcher reports into trading decisions

4. **Risk Management Team**: Evaluates volatility, liquidity, counterparty risk, enforces risk parameters

5. **Fund Manager (Portfolio Manager)**: Final approve/reject gate before execution

Built on **LangGraph**. Supports dual-model tiers: `deep_think_llm` (complex reasoning) and `quick_think_llm` (fast decisions). Multi-provider: OpenAI, Anthropic, Google, xAI, Ollama.

### What We Already Have (Victoria)
- Per-agent memory systems ✅
- Multi-perspective risk debate ✅
- Adversarial risk gate ✅

### What We're Missing / What They Do Better
| Gap | TradingAgents | Victoria |
|-----|---------------|----------|
| **Formal bull/bear debate** | Dedicated bullish + bearish researcher agents with structured rounds | We have multi-perspective but not adversarial debate format |
| **Dual-model tiers** | `deep_think` for analysis, `quick_think` for execution speed | We use single model tier |
| **Parallel analyst pipeline** | 4 specialized analysts run concurrently, then merge | Our signals are more sequential |
| **Explicit fund manager gate** | Separate portfolio-level approval after risk check | Our risk gate is the final gate — no portfolio-level view |
| **Data source breadth** | Alpha Vantage, social media, news, technicals all as separate streams | We should formalize data source agents |

### What to Implement
- **Formal bull/bear debate round** before trade execution — force a structured "why this fails" analysis
- **Two-tier model strategy**: Use Opus/deep model for analysis, Haiku/fast model for real-time signal processing
- **Portfolio-level manager**: Add a post-risk-gate that evaluates trades in context of overall portfolio exposure
- **Parallel analyst fanout**: Run fundamental/sentiment/technical/news agents concurrently with LangGraph-style orchestration

---

## 3. Weather Prediction Market Trading

### Source
- Tweet: [@adiix_official](https://x.com/adiix_official/status/2036039332541161860)
- Referenced: [@0xMovez guide](https://x.com/0xMovez) on Polymarket weather bots

### The Strategy
A trader turned $5 into $15,000 on Polymarket weather markets with a **100% win rate** across 490 trades.

**Core approach:**
- Buy YES only when price < 10–15¢ (heavily discounted)
- Buy NO only when price > 40–50¢ (still overpriced on the other side)
- Risk < $5 per position
- Biggest single win: $2,600

**Why it works:** Weather prediction markets are inefficient because:
- NOAA forecasts are highly accurate (especially < 24hr out) but market prices lag
- Most participants are casual bettors, not data-driven
- Arbitrage between NOAA forecast probability and Polymarket price creates consistent edge
- High frequency of events (daily weather) = lots of compounding opportunities

### How This Compares to Victoria
- We're already targeting Polymarket but haven't focused on **weather markets** specifically
- Weather markets have structural advantages: high frequency, reliable oracle data (NOAA), low competition from sophisticated traders
- The "buy at extreme discount" strategy is essentially **expected value harvesting** with a known probability source

### What to Implement
- **NOAA integration**: Pull NOAA forecast data (temperature, precipitation probability) as a signal source
- **Weather market scanner**: Monitor Polymarket weather markets for mispriced contracts (implied prob vs NOAA forecast prob)
- **Micro-bet accumulator**: Small position sizes, high volume, positive EV grinding — similar to the described strategy
- **Market efficiency tracker**: Measure how quickly weather market prices converge to NOAA forecasts to time entries

---

## 4. Crypto Liquidation Cascade Trading

### Source
- Tweet: [@0xRicker](https://x.com/0xRicker/status/2036065528230314420)
- Referenced: [@AleiahLock's "60+ Market Edges" guide](https://x.com/AleiahLock)

### The Strategy
A trader made $135K in a single week ($571K total PnL, 13,292 predictions) trading BTC Up/Down markets on Polymarket in **5-minute windows** using liquidation cascade signals.

**Core mechanism:**
1. Monitor Coinglass for **liquidation cluster buildup** on high-leverage perps
2. When a cascade is building, enter the "Down" side at elevated odds on Polymarket
3. Price wicks down as liquidations trigger → position resolves green
4. Captures 88¢ → $1.00 moves (12% return per trade) with structural edge

**Why it works:** Liquidation cascades are predictable because leveraged positions cluster at known price levels. When price approaches a cluster, cascading stops create a self-reinforcing downdraft. This is essentially front-running predictable forced selling.

### How This Compares to Victoria
- We don't currently use **liquidation heatmap data** as a signal source
- This is a **short-duration, high-conviction directional** strategy — complementary to our vol-arb approaches
- The edge is structural (forced selling) rather than informational — harder to compete away

### What to Implement
- **Coinglass integration**: Pull real-time liquidation heatmaps, open interest, and funding rates
- **Liquidation cascade detector**: Identify when leveraged positions cluster near current price, calculate cascade probability
- **Short-window Polymarket sniper**: When cascade probability exceeds threshold, enter 5-min directional bets
- **Funding rate divergence signal**: High funding rates = overcrowded leverage = cascade risk

---

## Priority Matrix

| Strategy | Expected Edge | Implementation Effort | Data Requirements | Priority |
|----------|--------------|----------------------|-------------------|----------|
| Vol-spread harvester (#1) | High — market-neutral | Medium | Exchange vol data + Polymarket prices | **P1** |
| Weather market grinder (#3) | Medium — consistent | Low | NOAA API + Polymarket | **P1** |
| Liquidation cascade sniper (#4) | High — but episodic | Medium | Coinglass + Polymarket | **P2** |
| TradingAgents architecture (#2) | Structural improvement | High | Refactor existing pipeline | **P2** |

### Recommended Next Steps
1. **Immediately**: Build vol-spread monitor and weather market scanner as new signal sources
2. **This week**: Integrate Coinglass data for liquidation signals
3. **This sprint**: Refactor Victoria's pipeline to add formal bull/bear debate and two-tier model architecture
4. **Backlog**: Portfolio-level manager, parallel analyst fanout
