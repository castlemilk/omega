# Backtest vs Live: Train/Test Split Architecture

**Status**: Design approved — Phase 1 in progress  
**Problem**: V-series version comparisons are confounded by market regime variation. V122 > V121 may reflect a regime change, not a signal fix. We cannot attribute performance differences to code changes.  
**Solution**: Freeze a versioned historical snapshot; run all version comparisons against identical data.

---

## 1. Current State (V93–V122)

Every training cycle calls `DataIngestionNode.execute()` which fetches live data:

```
run_training.py
  └─ orchestrator.run_one_cycle()
       └─ VictoriaNode.execute()
            └─ DataIngestionNode  ← Binance REST API (90d OHLCV per symbol, live)
            └─ SignalGenerationNode ← uses live WS state (microstructure)
            └─ StrategyNode
            └─ PaperTradingEngine
```

**Caching in place** (does NOT make runs deterministic):
- `data/bt_ohlcv_cache.json` — 6-hour TTL; subsequent cycles within 6h reuse the same fetch
- `data/macro_cache.db` — FRED + funding rates, 4–8h TTL
- Both caches are invalidated between training runs

**Result**: Each V-run samples a different 90-day trailing window. V122 (Apr 14 2026) and V121 (Apr 13 2026) share ~99% of their OHLCV data — but their first/last bar differs, and more critically, their live WS microstructure signals (VPIN, whale_print, order_book_imbalance) sample completely different tick streams. **There is no basis for causal attribution of performance differences to code changes.**

### Existing backtest infrastructure (not yet wired to training loop)

| File | Purpose | Gap |
|------|---------|-----|
| `omega/nodes/victoria/backtest.py` | Victoria signal+strategy replay on cached OHLCV | Only 4 symbols; 6h TTL cache (still not frozen per-version) |
| `omega.core.backtest_evaluator` | TPE walk-forward evaluator (60/20/20 split) | Only used by improvement engine, not training loop |
| `omega.eval.backtest_bridge` | OmegaOrchestrator replay on historical bars | Walk-forward design, not version-to-version comparison |
| `scripts/backtest.py` | SMA+RSI multi-period backtest (bull/bear/sideways) | Uses a simplified strategy, not full V-series pipeline |

The machinery exists. What's missing is a **frozen versioned snapshot** and a **training mode switch**.

---

## 2. Proposed Architecture

### Two modes, same artifacts

```
BACKTEST MODE                        LIVE MODE
──────────────────────────────       ──────────────────────────────
run_training.py --bt-snapshot        run_training.py
  data/snapshots/snap_YYYYMMDD.json    (current behavior)
  │                                    │
  └─ ReplayDataProvider                └─ DataIngestionNode (live)
       reads frozen OHLCV                  polls Binance each cycle
       WS signals → 0.0 stub               WS signals → live WS feeds
       macro signals from cache            macro signals from cache
  │                                    │
  Same: SignalGenerationNode           Same: SignalGenerationNode
        StrategyNode                         StrategyNode
        PaperTradingEngine                   PaperTradingEngine
        activation traces                    activation traces
        trades.csv / results.json            trades.csv / results.json
```

### Promotion gate

```
                    ┌─────────────────────┐
    Code change     │   BACKTEST MODE     │  Fixed snapshot
  (V_N → V_{N+1}) ──►  (deterministic)   │  same for all versions
                    │                     │
                    │  Compare V_N vs     │
                    │  V_{N+1} on SAME    │
                    │  historical data    │
                    └────────┬────────────┘
                             │ Pass backtest gates?
                             │ (PnL > prev, regime parity,
                             │  drawdown < ceiling, n_trades >= 20)
                             ▼
                    ┌─────────────────────┐
                    │    LIVE MODE        │  Real-time market
                    │  (paper trade)      │  WS signals active
                    │  200 cycles on      │  Measures real-world
                    │  live market        │  behaviour
                    └─────────────────────┘
```

---

## 3. Signal Replayability

### Replayable from OHLCV + cached macro (12 signals)

| Signal | Source | Notes |
|--------|--------|-------|
| `sma_long`, `sma_short`, `sma_crossover` | OHLCV close | Pure technical |
| `price`, `return_1d` | OHLCV close | Direct price features |
| `momentum_derivative`, `momentum_persistence`, `momentum_crossover` | OHLCV + rolling history | Needs warm-up window |
| `ricci_curvature_signal`, `fiedler_signal` | Signal correlation matrix | Computed from other signals |
| `funding_rate`, `funding_velocity`, `funding_derivative` | `macro_cache.db` OKX rates | 8h cache, replayable |
| `fear_greed_signal` | Alternative.me API (daily) | Backfillable from API history |
| `regime_duration`, `conviction_trend`, `agreement_trend` | Rolling internal state | Computed from history |
| `btc_dominance` | CoinGecko market cap | Daily snapshots replayable |
| `exchange_net_flow`, `stablecoin_velocity`, `oi_rate_of_change` | DefiLlama + OKX (15-min cache) | Deterministic with snapshot |

### Live-only (degrade to 0.0 in backtest mode)

| Signal | Source | Why not replayable |
|--------|--------|-------------------|
| `order_book_imbalance` | Binance L2 WS | Real-time depth state, no historical reconstruction |
| `trade_flow_direction` | Binance agg-trade WS | Tick-by-tick, directional flow can't be reconstructed from OHLCV |
| `spread_zscore` | Binance WS bid/ask | Requires live spread ticks |
| `volume_profile` | Binance agg-trade WS | Intraday volume distribution |
| `tick_momentum` | Binance agg-trade WS | Sub-second trade direction |
| `liquidation_proximity` | Binance WS liquidations | Real-time liquidation feed |
| `whale_print` | Binance agg-trade WS | Large-trade detection (2σ threshold on rolling mean) |
| `book_depth_velocity` | Binance L2 WS | Rate of change of bid/ask depth |
| `vpin` | Binance agg-trade WS | Volume-synchronised; accumulates over 50-trade buckets |
| `long_short_ratio` | Binance top-trader API | No public historical endpoint |

**Impact**: 9 WS signals degrade to 0.0 in backtest mode. These are exactly the signals that caused the V117-V121 regression (vpin, whale_print, trade_flow_direction). Backtest mode will give a cleaner signal quality measurement for the replayable signals.

---

## 4. Data Requirements

### What we need to freeze

A snapshot contains, per symbol, the **full OHLCV series** over a fixed date range plus associated macro state:

```json
{
  "_snapshot_id": "snap_20260414",
  "_created_at": 1744636800,
  "_date_range": ["2026-01-14", "2026-04-14"],
  "_symbols": ["ETHUSDT", "ADAUSDT", "NEARUSDT", "ARBUSDT", "BTCUSDT"],
  "ETHUSDT": {
    "close": [...],   // 90 floats
    "open": [...],
    "high": [...],
    "low": [...],
    "volume": [...],
    "timestamps": [...]  // unix seconds, one per bar
  },
  // ... other symbols
  "_macro": {
    "funding_rates": {"ETHUSDT": 0.00012, ...},
    "fear_greed": 45,
    "btc_dominance": 0.523
  }
}
```

Storage: ~13 symbols × 90 days × 5 OHLCV fields × 8 bytes ≈ **~50 KB per snapshot**. Keep 12 rolling monthly snapshots = ~600 KB total.

### What's on disk now

- `data/bt_ohlcv_cache.json` — 6h-TTL cache; exists but not version-pinned
- `data/macro_cache.db` — FRED + funding rates; replayable, persisted across runs
- `data/historical/` — Created by `scripts/backtest.py` for named bull/bear/sideways periods

---

## 5. Implementation Phases

### Phase 1 (now): Deterministic backtest mode on frozen OHLCV ✅ Implementing

**Goal**: Run V_N and V_{N+1} against identical OHLCV data. WS signals degrade to 0.0.

1. **`scripts/freeze_snapshot.py`** — CLI to fetch 90d OHLCV for all 13 symbols and save to `data/snapshots/snap_YYYYMMDD.json`. No TTL — once frozen, the file never changes.
2. **`--backtest-snapshot PATH`** flag in `run_training.py` — when set, replaces `DataIngestionNode` live fetch with `ReplayDataProvider` that reads the snapshot. Also sets WS features to degrade gracefully (no WS connection attempted; WS signals return 0.0).
3. **`ReplayDataProvider`** in `omega/nodes/victoria/providers/replay.py` — wraps the snapshot dict; each `get_market_data(symbol, window_end)` call slices the frozen series.
4. **Overnight loop `--mode backtest`** — passes `--backtest-snapshot` to each training run; skips WS warmup.
5. Produce identical artifacts: `trades.csv`, `results.json`, `activation_traces/` — postmortem tools work unchanged.

**What this enables**: For the first time, V_N vs V_{N+1} is a controlled comparison. The only variable is the code change.

### Phase 2: Funding + macro replayability

- Snapshot includes funding rate time series (not just current value) from OKX/macro_cache
- Fear/Greed backfilled from Alternative.me history endpoint
- `funding_rate_velocity` and `funding_derivative` computed correctly across the replayed window
- Result: ~15 signals fully deterministic vs 9 WS stubs

### Phase 3: Partial WS replay from recorded snapshots

- Add a `data/ws_snapshots/` collector: during live runs, periodically write `{timestamp, symbol, bids, asks, recent_trades}` to a rolling JSONL file
- `ReplayDataProvider` serves these for the 9 WS signals when available
- Gradual improvement: WS coverage starts at 0%, grows as we accumulate recordings

### Phase 4: Full train/validate/test gate

- Backtest gate (V49-style) extended: must pass on **both** the last frozen snapshot AND a held-out "test" snapshot
- Overnight loop: `backtest → gate → live paper-trade → promote`
- `BacktestEvaluator.from_splitter()` (already exists in `omega.core.backtest_evaluator`) drives the TPE walk-forward

---

## 6. Overnight Loop Integration (post-Phase 1)

```
# Current (live, confounded)
overnight_loop.py --start v122 --max-versions 5

# After Phase 1
overnight_loop.py --start v128 --max-versions 5 --mode backtest \
  --snapshot data/snapshots/snap_20260414.json

# After Phase 4
overnight_loop.py --start v128 --max-versions 5 \
  --mode backtest-then-live \
  --snapshot data/snapshots/snap_20260414.json
```

When `--mode backtest`:
- Each version runs against the frozen snapshot (deterministic, fast — no live API waits)
- Postmortem/forensics run on backtest artifacts
- Balance guardrail checks backtest L/S ratio
- Version is committed only if it passes backtest gates
- Live run is NOT launched until a version meets the gate

---

## 7. Signals That Will Change Behaviour in Backtest Mode

The following V115 features are disabled / zeroed when `--backtest-snapshot` is set:

| Feature flag | Live behaviour | Backtest behaviour |
|---|---|---|
| `ws_microstructure` | 6 live WS signals | All 6 → 0.0 |
| `whale_prints` | 3 WS informed-flow signals | All 3 → 0.0 |
| WS feed manager | Starts async WS connection | Not started |
| `whale_flow` | DefiLlama + OKX (15-min cache) | Snapshot macro value (static) |
| `funding_velocity` | Live OKX 3-reading derivative | Stub 0.0 until Phase 2 |

**Implication for V128+**: The first backtest versions will effectively run on the V112 signal set (the 10 replayable non-WS signals + temporal memory + embeddings). This is a cleaner baseline and isolates the WS signal contribution.

---

## 8. Snapshot Management

```
data/snapshots/
  snap_20260414.json     # First frozen snapshot (Phase 1)
  snap_20260501.json     # Monthly refresh
  snap_20260601.json
  ...
```

- Snapshots are **never modified after creation** — they are immutable historical records
- A version is always associated with the snapshot it was trained on: `v128_snap_20260414_results.json`
- Comparing V128 vs V129 is valid only if they used the same snapshot
- Comparing V128 (snap A) vs V140 (snap B) requires forensic care — note regime differences

---

*Phase 1 implementation begins after this doc is committed. Overnight loop will complete V126/V127 on live data (already running), then pause for backtest harness before V128+.*
