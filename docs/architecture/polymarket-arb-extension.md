# Polymarket Latency Arbitrage Extension

**Status:** Design only. Not yet built. Tracked here so we can scope the work
before committing to it.
**Date:** 2026-04-27
**Owner:** TBD

## What this is

A **separate Omega project** that runs alongside Victoria. Victoria trades
crypto perps on Coinbase / Kraken / Binance-via-fapi. The Polymarket project
trades **prediction markets** — specifically, the short-duration BTC/ETH binary
contracts ("Will BTC be above $X at 5pm UTC?") that Polymarket lists every few
minutes.

The edge the public reference (coinman2's $1M+ stack, 200-500 trades/day) lives
on is simple in shape:

- Binance updates BTC/ETH spot/perp prices on every tick (sub-second).
- Polymarket's CLOB lags those moves by ~2-3 seconds because order-book
  liquidity reprices slower on event venues.
- A bot watching Binance WS computes the **fair probability** of "BTC > $X by
  5pm" given the current spot price and time-to-resolution, and compares it to
  Polymarket's mid price. Gap > threshold → enter; convergence → exit.

This is industrial latency arb, not a model edge. The asset isn't an opinion;
it's a deterministic function of underlying spot. The only real questions are:

1. Can we place orders fast enough to capture the 2-3-second window?
2. Can we size them so a single adverse move doesn't blow up the bankroll?
3. Can we exit on convergence before someone else does?

## Why this slots into Omega

Omega already has the relevant pieces:

- **`projects/polymarket.yaml`** registry stub — project namespace exists.
- **`internal/polymarket/client.go`** — Go-side Polymarket REST client stub.
- **`omega/nodes/polymarket/clob_client.py`** — Python CLOB client (uses
  `py-clob-client` for the order side).
- **Binance WS infrastructure** — `omega/nodes/victoria/ws_feeds.py` already
  tails `wss://stream.binance.com:9443` for aggTrade and depth20. We can reuse
  the WS pump but we need a *separate* state object since Victoria's per-symbol
  state is for crypto perps not for binary contracts.
- **Action enum** — `omega/core/actions.py`: would need new `POLYMARKET_QUOTE`,
  `POLYMARKET_PLACE_ORDER`, `POLYMARKET_CANCEL`, `POLYMARKET_OBSERVE` entries.
- **Memory + scheduler** — Go-layer (`internal/`) handles persistence. New
  state schema needed for: open binary positions, fair-value cache, per-event
  resolution window.

## Architecture (proposed)

```
┌──────────────────────────────────────────────────────────────────────┐
│ Binance WS (existing pump in ws_feeds.py)                            │
│   → SymbolState (BTCUSDT, ETHUSDT)                                   │
│   → exposes get_latest_price(symbol)                                 │
└──────────────────────────────────────────────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ FairValueCalculator                                                  │
│   inputs:   ws_price, strike, time_remaining_seconds, vol_estimate   │
│   output:   P(price > strike at expiry)                              │
│   model:    Black-Scholes-style barrier with empirical vol from a    │
│             rolling 5-min realized-vol window                        │
└──────────────────────────────────────────────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ PolymarketCLOBClient (existing stub) — REST + WS                     │
│   → GET /markets?active=true&category=crypto                          │
│   → GET /book/{token_id}                                              │
│   → expose: poly_mid_price, poly_top_bid, poly_top_ask                │
└──────────────────────────────────────────────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ ArbEngine                                                            │
│   gap = fair_value - poly_mid                                        │
│   if |gap| > entry_threshold (e.g. 0.03):                             │
│     direction = "yes" if gap > 0 else "no"                           │
│     size = kelly_sizing(edge=|gap|, odds=1/poly_price)               │
│     post limit order at poly_top_ask + 1 tick (taker if marketable)  │
│   while position open:                                               │
│     if convergence (|gap| < exit_threshold) OR resolution: exit      │
└──────────────────────────────────────────────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ State + Audit (Go layer)                                             │
│   - open_positions table                                             │
│   - per-event PnL ledger                                             │
│   - hourly metrics: trades/hour, hit rate, avg gap captured          │
└──────────────────────────────────────────────────────────────────────┘
```

## Risks / open questions

1. **Order latency.** Polymarket CLOB orders settle on Polygon. Best-case
   Polygon block time is ~2 seconds, but order acceptance is a separate path.
   If our round-trip exceeds the 2-3 second window, we eat the gap-closing
   move. Need to measure end-to-end latency before committing capital.

2. **Inventory risk on rejection.** If we place a yes-side order that
   gets only partial fill, we hold an unhedged position. Need a kill-switch
   that cancels remaining orders on partial fill *and* a residual handling
   policy (close at market, hold to resolution, hedge with no-side, etc.).

3. **Collateral capital.** Each binary trade consumes USDC up to the implied
   probability × notional. With 200-500 trades/day and bankroll fragmenting
   across many open contracts, capital efficiency matters. Need a cap on
   simultaneously open contracts.

4. **Event lifecycle.** Resolution windows are minutes-to-hours. We need to
   know when each contract resolves (close out positions before) and when new
   contracts list (so we can register and start quoting fair value
   immediately). Polymarket emits new contract events; subscribing to them is
   straightforward via their WS.

5. **Fair-value model accuracy.** The simple "P(price > strike at expiry)"
   formula assumes log-normal returns and constant vol. Reality has fat tails
   and vol-of-vol. The reference stack uses a rolling realized-vol estimate
   tied to the contract's time horizon — we should do the same and stress-test
   the model on historic Polymarket data before going live.

6. **Concentration.** Two BTC contracts at the same time are not independent
   — they share the same underlying. Need correlation-aware sizing (Kelly per
   contract is too aggressive when contracts are highly correlated).

## Build phases (proposed)

**Phase 0 — read-only telemetry (1-2 days)**
- Tail Polymarket CLOB for active BTC/ETH contracts; record `(timestamp,
  contract_id, strike, time_to_expiry, poly_mid)` to a JSONL.
- Compute `fair_value` from Binance WS (using existing pump). Record gap.
- Run for 24-48h. Inspect: how often does |gap| > 3%? > 5%? What's the
  distribution of gap-close times?
- Output: `data/polymarket_telemetry/{date}.jsonl` and one analysis pass
  to validate the edge actually exists in our environment.

**Phase 1 — paper-trade (3-5 days)**
- Implement `ArbEngine` with simulated fills (no real orders). Use the Phase 0
  telemetry to backtest. Compute paper PnL, hit rate, average held duration.
- Feature flag: `polymarket_arb_enabled=False`. Default off.

**Phase 2 — live with strict caps (1-2 weeks)**
- Set initial bankroll cap to $500. Max simultaneously open contracts: 3.
- Enable real order placement via `clob_client.py`.
- Compare live results to paper-trade Phase 1 — drift indicates
  execution-quality issues (latency, slippage, partial fills) and is a
  blocker before scaling.

**Phase 3 — scale to operating size**
- Only after Phase 2 paper/live drift < 10%. Raise caps, expand to ETH and
  multi-contract correlation handling.

## Reference repos (not vendored, links only)

- `github.com/Polymarket/agents` — official Polymarket AI agent framework. Has
  CLOB client, prompt templates, vector-DB integration. Good for inspiration
  on the agent layer; we don't need the LLM agent for pure latency arb but the
  CLOB integration patterns are useful.
- `github.com/txbabaxyz/mlmodelpoly` — Binance price collector + fair-value
  predictor. Closest reference to Phase 0 telemetry pipe.
- `github.com/evan-kolberg/prediction-market-backtesting` — backtesting
  framework. Useful for Phase 1 paper-trade evaluation.
- `github.com/ent0n29/polybot` — full execution stack with Kafka + ClickHouse +
  Grafana. Probably overkill for our scale; cherry-pick the order-placement
  and partial-fill handling patterns.
- `github.com/TauricResearch/TradingAgents` — multi-agent (bull/bear/risk)
  framework. Not directly useful for latency arb (no debate needed when the
  edge is mechanical) but worth keeping in mind for the Victoria LLM rework.

## What this does NOT do

- It does not predict crypto direction. It does not hold positions for hours.
  It does not have an opinion on whether BTC will be above $X — only whether
  Polymarket's stated probability *right now* is consistent with Binance's
  spot *right now*.
- It does not replace Victoria. It runs alongside, on different capital, with
  different risk parameters. The two share infrastructure (WS pump, action
  enum, scheduler) but not strategy.
- It is not a low-frequency strategy. 200-500 trades/day is the operating
  point. Anything below 50/day per coinman2's article is "not the actual
  edge — that's something else." We commit to building it at the right
  cadence or not building it.

## Decision before any code

Before Phase 0 starts, agree on:

1. **Capital allocation**: how much total bankroll to dedicate? ($500 to start
   per Phase 2, $5k to scale per Phase 3.)
2. **Maximum simultaneous risk**: bankroll % at risk across all open contracts
   at any moment.
3. **Operating hours**: 24/7 or limited to known-liquid windows?
4. **Latency budget**: if our worst-case round-trip is > 5s, do we kill the
   bot? (Recommend yes — past that the edge is gone.)

Once these are agreed, Phase 0 is a 1-2-day spike: write the telemetry pipe,
run it for a day, look at the distribution. Cheap to verify the edge exists
in our environment before investing in the full stack.
