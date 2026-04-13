# Victoria Pattern Detection: Full Vector Space + Geometric Pattern Recognition

## Vision

Detect all market patterns across every available information vector and front-run them using differential geometry to identify pattern formation BEFORE price reflects it.

The key insight: price is a lagging indicator. By the time a candle closes, the pattern is already priced. The edge comes from detecting the PRECURSORS — order flow shifts, whale movements, funding rate flips, correlation breakdown, liquidity drainage — and using geometric methods to recognize when these precursors form a pattern that historically leads to a specific price move.

## The Full Vector Space

### Tier 1: Sub-Second Vectors (WebSocket feeds — BUILT, needs expansion)

These are the highest-alpha vectors because they capture information before anyone trading on candles can see it.

| Vector | Source | Update Freq | Signal | Status |
|--------|--------|-------------|--------|--------|
| Order book imbalance | Coinbase/Binance WS | 100ms | Bid/ask volume ratio at top 5 levels | ✅ Built |
| Trade flow direction | Coinbase WS | per-trade | Net aggressive buy/sell volume | ✅ Built |
| Spread z-score | Coinbase WS | 100ms | Spread anomaly detection | ✅ Built |
| Volume profile | Coinbase WS | per-trade | Current vs 24h average | ✅ Built |
| Tick momentum | Coinbase WS | per-trade | Weighted sum of last 50 tick directions | ✅ Built |
| **Liquidation cascade proximity** | Binance WS / OI data | 1s | Funding × OI → cascade risk | 🔧 Partial |
| **Large trade detection** | Coinbase/Binance WS | per-trade | Trades > 2σ from mean size | ❌ TODO |
| **Order book depth shift** | Binance WS | 100ms | Rate of change of book depth | ❌ TODO |
| **Trade intensity (VPIN)** | Computed from trades | 10s | Volume-synchronized probability of informed trading | ❌ TODO |

### Tier 2: Whale & Smart Money Vectors (minutes-hours)

These track what the informed money is doing before the market follows.

| Vector | Source | Update Freq | Signal | Status |
|--------|--------|-------------|--------|--------|
| **Exchange inflow/outflow** | DefiLlama / on-chain | 15min | Net flow to exchanges = sell pressure | ❌ TODO |
| **Whale wallet movements** | Etherscan / Blockchair API | 5min | Large transfers to/from exchanges | ❌ TODO |
| **Stablecoin mint/burn** | DefiLlama stablecoins API | 1h | USDT/USDC supply changes = buying power | ❌ TODO |
| **DEX volume divergence** | DefiLlama DEX API | 15min | On-chain vs off-chain volume ratio | ❌ TODO |
| **Open interest changes** | OKX/Binance API | 1min | OI rising + price flat = squeeze setup | ❌ TODO |
| **Funding rate velocity** | OKX/Coinbase | 8h settle, 1min rate | Rate of change of funding, not just level | ✅ Partial (level only) |
| **Options flow (put/call ratio)** | Deribit API | 1h | Skew changes = institutional hedging | ❌ TODO |

### Tier 3: Macro & Cross-Asset Vectors (hours-days)

These provide the regime context for interpreting the faster vectors.

| Vector | Source | Update Freq | Signal | Status |
|--------|--------|-------------|--------|--------|
| Fear & Greed Index | alternative.me | 24h | Contrarian extreme detector | ✅ Built |
| DXY (Broad Dollar) | FRED DTWEXBGS cache | 24h | Dollar strength = crypto pressure | ✅ Built |
| VIX | yfinance | 15min | Equity vol = risk appetite | ✅ Built |
| Yield curve (2Y-10Y spread) | FRED DGS2/DGS10 cache | 24h | Inversion = recession signal | ✅ Built |
| SPY momentum | yfinance | 15min | Equity correlation when > 0.4 | ✅ Built |
| **BTC dominance rate of change** | CoinGecko | 4h | BTC.D rising = altcoin rotation out | ❌ TODO |
| **Stablecoin dominance** | DefiLlama | 1h | Stablecoin % of total market cap = risk-off | ❌ TODO |
| **ETH/BTC ratio momentum** | CoinGecko | 4h | ETH outperformance = risk-on for alts | ❌ TODO |

### Tier 4: Temporal & Derived Vectors (computed from Tiers 1-3)

These are the pattern recognition layer — computed from the raw vectors above.

| Vector | Computation | Signal | Status |
|--------|------------|--------|--------|
| Signal derivatives | d(signal)/dt for all signals | Acceleration matters more than level | ✅ Built |
| Signal persistence | Consecutive same-sign cycles | Duration of trend | ✅ Built |
| Signal crossovers | Zero-crossing detection | Regime change moments | ✅ Built |
| Conviction trend | Slope of composite over time | Is edge growing or decaying? | ✅ Built |
| **Cross-signal divergence** | Signal A says buy, Signal B says sell | Disagreement = uncertainty | 🔧 Partial (confluence) |
| **Regime transition speed** | Rate of regime probability change | Fast transition = opportunity | ❌ TODO |
| **Pattern recurrence** | Cluster matching on historical traces | "This looks like cycle 42 of V107" | 🔧 Partial (embeddings) |

## How Differential Geometry Detects Patterns

The raw vectors above are coordinates in a high-dimensional signal space. Differential geometry gives us tools to detect STRUCTURE in this space — patterns that repeat, curvatures that predict, and flows that indicate where the market is heading.

### 1. Fisher-Rao Metric: Distance Between Market States

The market at any moment is a probability distribution (μ, σ) of returns. The Fisher-Rao metric defines the natural distance between two market states on the statistical manifold.

**Pattern detection:** When the geodesic distance from the current state to a known crash state drops below a threshold, we're approaching a crash pattern. This is our existing `geodesic_crash_distance` signal — but it should be computed from ALL vectors, not just price returns.

**Enhancement:** Build a multivariate Fisher-Rao metric that includes order flow, funding, whale activity, and macro vectors. The distance to crash states in THIS higher-dimensional manifold is far more informative than price-only distance.

### 2. Ricci Curvature: Market Regime Geometry

Positive Ricci curvature → market is mean-reverting (geodesics converge)
Negative Ricci curvature → market is trending (geodesics diverge)
Zero curvature → market is random/efficient

**Pattern detection:** When Ricci curvature flips sign, the regime is changing. Our V97 implementation used price-only Ricci. The enhancement: compute Ricci on the FULL vector manifold. When order flow curvature goes negative while price curvature is still positive, it means the smart money is trending while the market hasn't noticed yet — that's the front-running edge.

### 3. Ollivier-Ricci on Correlation Networks: Contagion Detection

ORC measures how much the "geometry" of the correlation network is stressed. When assets that normally move independently start moving together, ORC goes negative — diversification is breaking down.

**Pattern detection:** ORC becoming increasingly negative across the basket means a cascade is building. Historical pattern: when ORC drops below -0.5, a liquidation cascade follows within 2-4 cycles. Our existing ORC implementation captures this but isn't wired to the full vector set.

### 4. Fiedler Value (Spectral Gap): Market Fragmentation

The Fiedler eigenvalue of the correlation Laplacian measures how connected the market is. Low Fiedler = fragmented (assets decoupled), High Fiedler = unified (everything moving together).

**Pattern detection:** A rapidly falling Fiedler value means the market is fragmenting — some assets are decoupling from the basket. This predicts which assets will move independently (alpha opportunities) vs which will follow the herd (no alpha).

### 5. Natural Gradient: Optimal Learning on the Weight Manifold

The signal weights live on a probability simplex. Standard gradient descent (our EMA reinforcement) treats this as flat space, but it's actually curved. Natural gradient descent uses the Fisher information matrix to move in the direction of steepest descent ON THE MANIFOLD.

**Enhancement:** Replace the EMA-based `TradeReinforcer` with a natural gradient optimizer. This converges faster, maintains sharper weight separation (doesn't wash to zero like EMA), and respects the geometry of the weight space.

## Implementation Priority

### Phase 1: Expand Sub-Second Vectors (highest alpha/effort ratio)
- Large trade detection (whale prints in real-time)
- Order book depth shift rate (smart money pulling bids/asks)
- VPIN (probability of informed trading)
- Wire all into existing `ws_feeds.py` framework

### Phase 2: Whale & Smart Money Vectors
- Exchange inflow/outflow via DefiLlama `bridges` + `stablecoins` endpoints (FREE)
- Open interest rate of change via OKX API (FREE)
- Funding rate velocity (already have level, compute derivative)
- Stablecoin mint/burn via DefiLlama (FREE)

### Phase 3: Multivariate Geometry
- Extend MarketManifold from (μ,σ) of price to (μ,σ) of FULL vector space
- Compute Fisher-Rao distance in the expanded manifold
- Compute Ricci curvature on order flow vectors (not just price)
- Build "geometry divergence" signal: when vector-space curvature disagrees with price curvature

### Phase 4: Natural Gradient Reinforcement
- Replace EMA reinforcer with natural gradient on probability simplex
- Uses Fisher information matrix of signal weight space
- Sharper weight separation, faster convergence, no wash-to-zero

### Phase 5: Pattern Matching at Scale
- Build a library of known patterns from activation traces (300+ now)
- For each new decision, find the nearest historical cluster
- Use cluster WR/PnL as a prior on the current decision
- This is the "vectorized decision embedding" approach but with geometry-aware distance (Fisher-Rao, not Euclidean)

## The Convergence Target

When all 5 phases are complete, the system will:

1. **See** every information vector before price reflects it (sub-second WS + whale tracking + macro)
2. **Recognize** patterns in the high-dimensional vector space using geometric methods (Fisher-Rao distance, Ricci curvature, ORC, Fiedler)
3. **Learn** which patterns predict which outcomes using natural gradient optimization on the signal weight manifold
4. **Act** on the highest-confidence patterns with conviction-proportional sizing
5. **Evaluate** every decision post-trade with full activation tracing and postmortem analysis
6. **Improve** continuously as the reinforcement loop accumulates more trade outcomes and the pattern library grows

This is the "full trading house of quants" — each vector is a research desk, the geometry is the chief risk officer seeing cross-desk patterns, and the reinforcement loop is the P&L committee that decides which desks get more capital.
</content>
</invoke>