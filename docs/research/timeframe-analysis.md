# Timeframe Analysis: 1h vs 15-min vs 5-min cadence for Victoria

**Date:** 2026-04-28
**Status:** Initial analysis + 15-min test launched (v167_15min, in progress).

## Question

Should Victoria run at a faster cadence than 1h bars in live mode?

## Trade frequency by cadence (observed + projected)

| Run | Cadence | Cycles | Wall-clock | Trades/day-equivalent |
|---|---|---|---|---|
| v161_live | 10s (broken) | 500 | 1.4h | n/a (cadence collapse — not independent decisions) |
| v163_live | 1h | 30 | 30h | **8.0** |
| v164_live | 1h | 24 | 24h | **3.0** |
| v166_live | 1h | 12 | 12h | **6.0** (in progress) |

Three 1h pilots average **5-6 trades/day**. Statistical power per day is poor —
a 30-day window gives ~150 trades, of which maybe ~50 are independent decision
moments (cycles 11/13/19 in v163 generated correlated trade bursts, so 10
trades was closer to 4 decisions). Very slow learning loop.

**At 15-min cadence:** projected ~20-30 trades/day. **At 5-min:** 60-90/day.

## Signal validity at shorter timeframes

| Signal | 1h | 15-min | 5-min |
|---|---|---|---|
| Microstructure (OBI, trade flow, tick momentum) | OK | **Better** — signal lives sub-second | **Best** — exactly the design timeframe |
| WS-based whale prints, VPIN | OK | Better | Best |
| Cross-exchange divergence (V166 new) | OK | **Better** — gap closes in seconds, faster cadence captures more arbs | Best |
| SMA crossover, breakout | Good | Marginal — 4× more whipsaws | Poor |
| ADX, ATR | Good | Marginal | Poor |
| Wasserstein regime | Good | Needs warmup | Too few obs |
| TDA persistent homology | Good | Needs warmup | Insufficient cloud size |
| Bayesian regime detector | Good | Acceptable | **Brittle** — 20-bar minimum window = 100 min of data |
| Fear/greed index | OK (cached daily) | Useless — caches stale | Useless |
| Funding rate | OK (8h settlement) | Useless inside 8h | Useless |
| DXY, yield curve, VIX | OK (FRED is daily/EOD) | Useless | Useless |

**Verdict:** the signal stack splits cleanly into "fast" (microstructure + cross-exchange + technical) and "slow" (macro + regime). At 15-min cadence, ~half the stack contributes meaningful information per cycle; the other half is held constant from the last hourly refresh.

## The coinman2 lesson

200-500 trades/day on 5-15-min Polymarket contracts is *industrial-scale*
latency arb. The edge is mechanical (Binance leads spot prices by ~2-3s; the
binary's price catches up). They take many tiny bets, Kelly-sized, with
fast convergence on outcomes.

We're trying to extract directional alpha from the same underlying signal
stack — that's a different game. But the **trade-frequency argument** still
holds: more trades = more outcomes per unit time = faster IC estimation,
faster auto-improve convergence, faster live calibration.

## Recommended hybrid

Don't move *all* signals to 15-min. Move *decisions* to 15-min, while letting
slow signals refresh on their natural cadence:

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  WS feeds    │    │  Hourly bar  │    │  Daily macro │
│  (sub-sec)   │    │   refresh    │    │   refresh    │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │
       ▼                   ▼                   ▼
   Microstructure       Technical          Fear/greed,
   Cross-exchange       (SMA, ADX,         DXY, VIX,
   Whale prints         breakout)          yield curve,
   Tick momentum                           funding (8h)
       │                   │                   │
       └───────┬───────────┴────────┬──────────┘
               │                    │
               ▼                    ▼
        ┌─────────────────────────────┐
        │ Decision cycle: every 15min │
        │ Reads latest of each stream │
        └─────────────────────────────┘
```

The slow signals are *cached* and read by every 15-min cycle — but they only
*update* on their natural cadence. The fast signals refresh continuously via
WS pumps. The decision cycle samples both at 15-min intervals.

This means: signals like `fear_greed_signal` will be the same value across 4
consecutive 15-min cycles in a given hour, but `cross_exchange_divergence`
and `tick_momentum` will vary. The composite picks up the variation from the
fast signals, while the slow signals provide a stable directional bias.

## Costs at shorter cadence

1. **Fees & slippage** — 4-8× more trades = 4-8× more taker fees. At 0.05% taker on $1M of trade volume per day, that's $500/day fees vs ~$60/day at 1h cadence. Erodes edge fast unless WR or avg-win improves enough.

2. **Tighter stops** — at 15-min bars, ATR shrinks, so stops need recalibration. Current ATR multipliers (`atr_stop_mult` etc.) were tuned on 1h bars. May need a separate tuning pass.

3. **More fee impact** → **Kelly becomes essential.** Half-Kelly (V166) caps single-trade risk; with many small bets the expectation has a much smaller variance. Kelly sizing was added in V166 specifically anticipating this.

4. **WS becomes critical, REST too slow.** At 1h cadence, REST polling every minute is overkill. At 15-min, REST polling every 30s is barely fresh enough. At 5-min, REST is hopeless — must use WS streams. We already have Binance + Coinbase WS infrastructure.

## Test launched

`v167_15min` — 96 cycles × 15-min sleep = 24h wall-clock.

```bash
OMEGA_METRICS_DIR=data/runs FRED_API_KEY=... \
  python3 scripts/run_training.py \
    --version v167_15min --cycles 96 --sleep 900 \
    --features v161_live
```

Comparing to v164_live (24h × 1h) and v166_live (in-progress 24h × 1h):
- Trade count: expect 4-6× more (12-30 trades vs 3-6)
- WR: probably lower (more whipsaws on technical signals)
- PnL: open question — fee drag is real

## Decision tree

After v167_15min completes:

- **If WR and trades-per-day both improve** → ship v168_live at 15-min cadence,
  recalibrate ATR multipliers in a follow-up.
- **If WR drops but trades-per-day rises** → 15-min is faster but worse;
  evaluate the hybrid (slow-signal caching + 15-min decisions) before
  abandoning.
- **If both worsen** → 1h cadence is correct; don't change. Focus on signal
  recalibration instead.

## Open questions

1. The strategy was trained on 1h bars (regime-adaptive thresholds, position
   sizing scalers). Without retraining at 15-min, signal IC weights are
   miscalibrated. v167_15min is an honest test of "drop-in cadence change",
   but the right test is "retrain at 15-min cadence then evaluate".

2. ATR-based stops scale with bar size. At 15-min bars, ATR is ~25-40% of
   1h ATR (volatility scaling roughly with √time). Stops that worked at 1h
   may be too wide (effectively no stop) or too tight (chopped out). Needs
   a separate calibration pass.

3. The Bayesian regime detector and HMM both have minimum-window requirements
   measured in bars. At 15-min, a 20-bar window is 5h — too short to
   distinguish a regime change from intraday noise. May need to lengthen
   windows or accept that regime labels are noisier.

4. Cross-exchange divergence and microstructure signals are *currently gated
   off* in v161_live. They would need to be enabled (with IC calibration)
   to capture the full benefit of 15-min cadence — that's where their alpha
   actually lives. v167_15min won't show this benefit.
