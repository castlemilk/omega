# Victoria Next-Gen Alpha Architecture

## Problem Statement

Victoria's current signal pipeline computes 15 flat technical signals on 4-hour CoinGecko REST snapshots, applies cross-sectional demeaning, and enters when the composite crosses a threshold. This works in trending markets (V93: +$130, PF 2.40) but fails catastrophically in choppy/ranging markets (V101: -$212, V102: -$225). The system has no information advantage, no temporal reasoning, and no market microstructure awareness.

**Goal:** Profitable in both trending AND ranging/fear markets. Target: consistent PF > 1.5 across market regimes.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    REAL-TIME DATA LAYER (Phase 1)               │
│  Coinbase WS ──┐                                                │
│  Binance WS  ──┼──▶ StreamRouter ──▶ SignalEngine (per-tick)   │
│  OKX WS      ──┘         │                                     │
│                    ┌──────┴──────┐                               │
│                    │TickBuffer   │ (ringbuffer, last 1000 ticks) │
│                    │OrderBook    │ (L2 snapshots, 100ms refresh) │
│                    │TradeFlow    │ (aggressor tagging)           │
│                    └─────────────┘                               │
├─────────────────────────────────────────────────────────────────┤
│                    SIGNAL LAYERS                                 │
│                                                                  │
│  Layer 0: Microstructure (Phase 4)     ← NEW, tick-level        │
│    order_book_imbalance, trade_flow_direction,                   │
│    liquidation_proximity, spread_zscore, volume_profile          │
│                                                                  │
│  Layer 1: Technical (existing)          ← Current 15 signals    │
│    momentum, mean_reversion, volatility, regime, cross_asset     │
│                                                                  │
│  Layer 2: Temporal Memory (Phase 2)     ← NEW, signal history   │
│    signal_derivative, signal_persistence, signal_crossover,      │
│    regime_duration, conviction_trend                             │
│                                                                  │
│  Layer 3: Geometry (existing, gated)    ← Ricci, ORC, Fiedler  │
│    ricci_scalar, orc_mean, geo_dist_crash, fiedler_raw           │
├─────────────────────────────────────────────────────────────────┤
│                    ADAPTIVE COMBINER (Phase 3)                   │
│                                                                  │
│  SignalRegimeDetector                                            │
│    ├── rolling IC per signal family (20-trade window)            │
│    ├── signal_family_state: {momentum: "hot", mean_rev: "cold"} │
│    └── adaptive_weights = f(rolling_IC, regime, market_state)    │
│                                                                  │
│  AdaptiveComposite                                               │
│    ├── weighted_composite = Σ(signal_i × adaptive_weight_i)     │
│    ├── falls back to equal-weight when IC data insufficient      │
│    └── replaces current static trimmed-mean                      │
├─────────────────────────────────────────────────────────────────┤
│                    STRATEGY + EXECUTION (existing)               │
│    conviction filters → portfolio construction → paper trading   │
│    (unchanged, consumes composite + regime + signals dict)        │
└─────────────────────────────────────────────────────────────────┘
```

## Phase 1: Real-Time WebSocket Data Layer

**Why this first:** The single biggest alpha gap. Every signal computed from REST snapshots is information everyone else already traded on. WebSocket feeds give us sub-second data at zero cost.

### Components

#### 1.1 `omega/nodes/victoria/ws_feeds.py` — WebSocket Feed Manager

```python
class WSFeedManager:
    """Manages WebSocket connections to Coinbase + Binance.
    
    Produces:
      - TickBuffer: ring buffer of last N trades per symbol
      - OrderBookSnapshot: L2 order book (top 20 levels)
      - TradeFlow: aggressor-tagged trades (buy vs sell)
    """
    
    def __init__(self, symbols: list[str]):
        self.symbols = symbols
        self.tick_buffers: dict[str, RingBuffer] = {}  # symbol → last 1000 ticks
        self.order_books: dict[str, OrderBook] = {}     # symbol → L2 snapshot
        self.trade_flows: dict[str, TradeFlow] = {}     # symbol → buy/sell aggregation
    
    async def connect(self):
        """Connect to Coinbase + Binance WebSocket feeds."""
        # Coinbase: wss://advanced-trade-ws.coinbase.com
        # Binance: wss://stream.binance.com:9443/ws (public, not geo-blocked)
        
    def get_microstructure(self, symbol: str) -> dict:
        """Return current microstructure state for signal computation."""
        return {
            "order_book_imbalance": self._compute_imbalance(symbol),
            "trade_flow_direction": self._compute_flow(symbol),
            "spread_zscore": self._compute_spread_z(symbol),
            "volume_profile": self._compute_volume_profile(symbol),
            "tick_momentum": self._compute_tick_momentum(symbol),
        }
```

#### 1.2 Integration with existing pipeline

The WSFeedManager runs in a background thread. The existing synchronous signal pipeline queries it once per cycle via `get_microstructure(symbol)`. No async rewrite needed — the WS feeds accumulate data continuously, the strategy samples them at cycle boundaries.

```
Existing cycle: fetch REST → compute signals → strategy → trade
New cycle:      WS feeds (continuous) → sample at cycle start → compute signals + microstructure → strategy → trade
```

#### 1.3 Feature flag: `ws_microstructure`

Gated behind a flag. When OFF, microstructure signals return 0.0 (baseline preserved). When ON, 5 new signals are injected into the signal dict alongside existing signals.

### Data Sources

| Feed | Source | Data | Latency | Cost |
|------|--------|------|---------|------|
| Trades | Coinbase Advanced Trade WS | Per-trade: price, size, side, timestamp | ~100ms | Free |
| L2 Book | Coinbase Advanced Trade WS | Top 20 bid/ask levels | ~100ms | Free |
| Trades | Binance WS (public) | Per-trade: same as above | ~100ms | Free (public endpoint, not geo-blocked for reads) |
| Funding | OKX REST (already wired) | 8h funding rate | 8h cache | Free |

### Microstructure Signals (5 new)

| Signal | Computation | Alpha Thesis |
|--------|------------|--------------|
| `order_book_imbalance` | `(bid_volume - ask_volume) / (bid_volume + ask_volume)` at top 5 levels | Imbalance predicts short-term price direction. Bid-heavy → price up. |
| `trade_flow_direction` | Net buy volume / total volume over last 60 seconds | Aggressive buying/selling precedes moves. |
| `spread_zscore` | Current spread vs 100-tick rolling mean/std | Wide spread = uncertainty/illiquidity = avoid. Tight spread = conviction. |
| `volume_profile` | Current volume vs 24h average | Volume spikes confirm moves. Low volume = false signal. |
| `tick_momentum` | Weighted sum of last 50 tick directions | Micro-trend detection. Catches moves before 4h candle reflects them. |

---

## Phase 2: Temporal Signal Memory

**Why:** A funding rate that just flipped negative is a completely different signal than one that's been negative for 20 cycles. The system treats them identically.

### Components

#### 2.1 `omega/nodes/victoria/signal_memory.py` — Signal History Tracker

```python
class SignalMemory:
    """Tracks signal history per ticker for temporal feature computation."""
    
    def __init__(self, lookback: int = 20):
        self.lookback = lookback
        self.history: dict[str, dict[str, deque]] = {}  # ticker → signal_name → deque
    
    def update(self, ticker: str, signals: dict[str, float]):
        """Record current cycle's signals."""
        
    def get_temporal_features(self, ticker: str) -> dict[str, float]:
        """Compute temporal features from signal history."""
        return {
            # Derivatives: is the signal accelerating?
            "momentum_derivative": self._derivative("momentum", ticker),
            "funding_rate_derivative": self._derivative("funding_rate_btc", ticker),
            
            # Persistence: how many cycles has this been positive/negative?
            "momentum_persistence": self._persistence("momentum", ticker),
            "regime_duration": self._persistence("regime_consolidated", ticker),
            
            # Crossovers: did the signal just flip sign?
            "momentum_crossover": self._crossover("momentum", ticker),
            "funding_crossover": self._crossover("funding_rate_btc", ticker),
            
            # Trend: is conviction strengthening or weakening?
            "conviction_trend": self._trend("composite", ticker),
            
            # Signal agreement trend: are signals converging or diverging?
            "agreement_trend": self._trend("agreement_ratio", ticker),
        }
    
    def _derivative(self, signal: str, ticker: str) -> float:
        """First derivative: (current - previous) / previous."""
        
    def _persistence(self, signal: str, ticker: str) -> int:
        """Count of consecutive cycles with same sign."""
        
    def _crossover(self, signal: str, ticker: str) -> float:
        """1.0 if signal just crossed zero, 0.0 otherwise."""
        
    def _trend(self, signal: str, ticker: str) -> float:
        """Slope of linear regression over last N values."""
```

#### 2.2 Integration

In `signal_generation.py`, after computing all signals:
```python
# Existing: compute raw signals
signals = self._compute_all_signals(ticker, market_data)

# New: add temporal features
if self.features.temporal_memory:
    self.signal_memory.update(ticker, signals)
    temporal = self.signal_memory.get_temporal_features(ticker)
    signals.update(temporal)
```

#### 2.3 Feature flag: `temporal_memory`

---

## Phase 3: Adaptive Signal Weighting

**Why:** In the current choppy market, momentum signals are anti-predictive. Mean-reversion signals would be profitable. The system needs to detect which signal family is working NOW and upweight it dynamically.

### Components

#### 3.1 `omega/nodes/victoria/adaptive_combiner.py`

```python
class AdaptiveCombiner:
    """Replaces static trimmed-mean composite with IC-weighted adaptive composite.
    
    Uses the existing SignalDecayDetector's per-signal IC data to dynamically
    weight signals based on their recent predictive power.
    """
    
    SIGNAL_FAMILIES = {
        "momentum": ["momentum", "trend_strength", "cross_sectional_momentum"],
        "mean_reversion": ["mean_reversion", "bollinger_zscore"],
        "volatility": ["volatility_regime", "basket_std"],
        "sentiment": ["fear_greed_signal", "funding_rate_btc"],
        "cross_asset": ["dxy_signal", "vix_signal", "spy_signal", "yield_curve"],
        "microstructure": ["order_book_imbalance", "trade_flow_direction", 
                          "spread_zscore", "volume_profile", "tick_momentum"],
        "temporal": ["momentum_derivative", "conviction_trend", "agreement_trend"],
    }
    
    def compute_adaptive_weights(self, signal_ics: dict[str, float]) -> dict[str, float]:
        """Compute per-signal weights based on rolling IC."""
        weights = {}
        for signal, ic in signal_ics.items():
            if ic > 0.05:        # Signal is predictive
                weights[signal] = ic / 0.05  # Scale by IC magnitude
            elif ic > 0.0:       # Signal is weak
                weights[signal] = 0.5        # Downweight but keep
            elif ic > -0.02:     # Signal is noise
                weights[signal] = 0.1        # Nearly zero weight
            else:                # Signal is anti-predictive
                weights[signal] = -0.5       # FLIP the signal
        return weights
    
    def compute_composite(self, signals: dict, weights: dict) -> float:
        """Weighted composite using adaptive weights."""
        num = sum(signals.get(s, 0) * weights.get(s, 1.0) for s in signals if not s.startswith("_"))
        den = sum(abs(weights.get(s, 1.0)) for s in signals if not s.startswith("_"))
        return num / den if den > 0 else 0.0
```

#### 3.2 Key insight: Anti-predictive signal flipping

When a signal's IC goes below -0.02 (anti-predictive), instead of removing it, we FLIP its sign. A consistently wrong signal is valuable — it tells us to do the opposite. This is how the system adapts to ranging markets: momentum's IC goes negative → the combiner automatically flips it into a mean-reversion signal.

#### 3.3 Feature flag: `adaptive_combiner`

---

## Phase 4: Market Microstructure Signals (detailed)

Built on top of Phase 1's WebSocket data. These signals capture the information that exists between candles.

### 4.1 Order Book Imbalance

```python
def compute_imbalance(book: OrderBook, levels: int = 5) -> float:
    """Bid vs ask volume imbalance at top N levels.
    
    Range: [-1, +1]. Positive = more bids = bullish pressure.
    Updated every 100ms from WS feed, sampled at cycle boundary.
    """
    bid_vol = sum(level.size for level in book.bids[:levels])
    ask_vol = sum(level.size for level in book.asks[:levels])
    return (bid_vol - ask_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else 0.0
```

### 4.2 Trade Flow (Aggressor Tagging)

```python
def compute_trade_flow(trades: list[Trade], window_seconds: int = 60) -> float:
    """Net aggressive buy volume over total volume.
    
    Range: [-1, +1]. Positive = net buying pressure.
    Uses trade side from exchange (Coinbase provides this natively).
    """
    recent = [t for t in trades if t.age_seconds < window_seconds]
    buy_vol = sum(t.size for t in recent if t.side == "buy")
    sell_vol = sum(t.size for t in recent if t.side == "sell")
    total = buy_vol + sell_vol
    return (buy_vol - sell_vol) / total if total > 0 else 0.0
```

### 4.3 Liquidation Proximity

```python
def compute_liquidation_proximity(price: float, funding_rate: float, 
                                   open_interest: float) -> float:
    """Estimate proximity to liquidation cascade.
    
    When funding is extremely positive AND OI is high, longs are overleveraged.
    A small price drop triggers cascading liquidations → sharp move.
    
    Returns: 0.0 (safe) to 1.0 (liquidation cascade imminent).
    """
    leverage_stress = abs(funding_rate) * open_interest / price
    return min(1.0, leverage_stress / threshold)
```

---

## Implementation Plan

### Phase 1: WebSocket Data Layer (highest ROI)
- **Files:** `omega/nodes/victoria/ws_feeds.py` (new), `signal_generation.py` (wire 5 signals)
- **Flag:** `ws_microstructure`
- **Effort:** ~4 hours
- **Dependencies:** `websockets` Python package, Coinbase/Binance WS endpoints
- **Test:** Compare signal values from WS vs REST to validate correctness

### Phase 2: Temporal Signal Memory
- **Files:** `omega/nodes/victoria/signal_memory.py` (new), `signal_generation.py` (wire temporal features)
- **Flag:** `temporal_memory`
- **Effort:** ~2 hours
- **Dependencies:** None (pure Python, uses existing signal dict)
- **Test:** Verify derivatives/persistence/crossovers match manual calculation on V100 traces

### Phase 3: Adaptive Signal Weighting
- **Files:** `omega/nodes/victoria/adaptive_combiner.py` (new), `signal_generation.py` (replace trimmed-mean)
- **Flag:** `adaptive_combiner`
- **Effort:** ~3 hours
- **Dependencies:** SignalDecayDetector (existing), needs 20+ trades of IC data
- **Test:** Backtest on V93 + V101 data — should improve V101's choppy-market performance

### Phase 4: Microstructure Signals (detail build on Phase 1)
- **Files:** Extend `ws_feeds.py`, add `omega/nodes/victoria/signals/microstructure.py`
- **Flag:** `ws_microstructure` (same flag, additional signals)
- **Effort:** ~3 hours
- **Dependencies:** Phase 1 WebSocket feeds running
- **Test:** Ablation: V93_baseline vs ws_microstructure vs temporal_memory vs adaptive_combiner

---

## Trade-off Analysis

| Decision | Chosen | Alternative | Rationale |
|----------|--------|-------------|-----------|
| WS threading model | Background thread + sync sampling | Full async rewrite | Avoids rewriting strategy.py. WS accumulates continuously, strategy samples at cycle boundaries. |
| Temporal lookback | 20 cycles | 50 or 100 | 20 cycles = ~5 hours of history. Enough for derivative/persistence without stale data. Configurable. |
| Anti-predictive flipping | Flip sign at IC < -0.02 | Remove signal entirely | Flipping extracts value from consistently wrong signals. More alpha than removing. |
| Microstructure source | Coinbase primary, Binance fallback | Binance-only | Coinbase gives native aggressor tags. Binance requires inference from trade direction. |
| Implementation order | WS → Temporal → Adaptive → Micro | All at once | Each phase is independently testable. WS is highest ROI. |

## Success Criteria

1. **Phase 1:** At least 2 microstructure signals producing non-zero values in 90%+ of cycles
2. **Phase 2:** Temporal features show >0.03 IC on at least 3 features across 100-trade window
3. **Phase 3:** Adaptive combiner achieves PF > 1.0 on V101/V102 market data (where static combiner got PF 0.29)
4. **Phase 4:** Combined system achieves PF > 1.5 in both trending (V93-era) and ranging (V101-era) markets
5. **Overall:** V103+ consistently profitable regardless of market regime
</content>
</invoke>