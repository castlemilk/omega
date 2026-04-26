# Live Trading Lessons (v161, v163, v164 retrospective)

**Date:** 2026-04-26
**Status:** Living document; updated after each live run.

## Data sources

- **v161_live** — 500 cycles × 10s (cadence wrong, see [backtest-live-gap-v161.md](backtest-live-gap-v161.md)). 127 closed trades, 27.6% WR, −$139 PnL.
- **v163_live** — 30 cycles × 1h before /tmp wipeout killed the run (see "Process loss" below). 10 closed trades, 30% WR, −$44 PnL.
- **v164_live** — currently running (cycle 1-2 at time of writing), too early to draw conclusions.
- **Backtest reference** — `v164bt_recent_metrics.jsonl` (300 cycles, snap_20260414).

The v161 numbers are *not* per-bar comparable to backtest (cadence collapsed
500 cycles into ~2-3 bars). The v163 numbers ARE per-bar — 30 genuine 1h
observations — and that is the only true live evidence we currently have.

## Trade forensics — v163_live (10 trades)

| cyc | sym | side | pnl | hold | conv | regime |
|-----|-----|------|-----|------|------|--------|
| 3 | ETHUSDT | short | −$19 | 2 | 0.109 | normal |
| 11 | NEARUSDT | long | **+$54** | 10 | 0.095 | normal |
| 11 | ARBUSDT | long | **+$215** | 10 | 0.096 | normal |
| 11 | ETHUSDT | short | −$11 | 8 | 0.087 | normal |
| 13 | ADAUSDT | long | −$71 | 2 | 0.090 | normal |
| 13 | NEARUSDT | long | −$64 | 2 | 0.090 | normal |
| 13 | ETHUSDT | short | **+$44** | 2 | 0.120 | normal |
| 16 | NEARUSDT | long | −$13 | 3 | 0.090 | normal |
| 19 | ARBUSDT | long | **−$164** | 6 | 0.119 | high_vol |
| 19 | ETHUSDT | long | −$15 | 6 | 0.091 | high_vol |

**Wins:** 3 / **Losses:** 7. Total: +$313 / −$357 → **−$44 net**.

**Key observations:**

1. **Conviction does NOT predict outcome.** Avg conviction WIN=0.103 vs LOSS=0.097 — essentially identical. The conviction filter is calibrated to backtest signal distributions that don't reproduce live.

2. **Hold time bifurcates.** Avg hold WIN=7.3 cycles vs LOSS=4.1 cycles. Either (a) `early_loss_time_stop` is correctly cutting losers fast (good), or (b) it's cutting trades that would recover (bad — these become opportunity-cost losses we never see). Forensic resolution requires comparing predicted-vs-actual paths, which we don't currently log.

3. **All 3 winners opened cycle 11.** A *single* setup snapshot fired three correlated longs/shorts. When the system is right it's right on multiple tickers; when wrong, wrong on multiple. **Trade decisions are not independent across tickers** — sample size is closer to "decisions" (4) than to "trades" (10).

4. **High_vol entries lose.** The 2 high_vol entries (cycle 19, both longs) lost a combined −$179 (40% of total losses). This corroborates the V142 hard-block rationale, even though the block had been disabled (or `_use_surface=True` bypassed it) on this run. **The block has empirical support, not just historical training-data support.**

5. **Long bias loses, short bias wins** (small sample, n=10): 5L lost / 2L won (28% L-WR), 2S won / 1S lost (67% S-WR).

## Live signal scorecard

Per-cycle stats from v164_live (2 cycles only, indicative) vs v164bt_recent (300 cycles, baseline). Live trade-traces from v163_live (7 trades) supplement.

| Signal | Live behaviour | Backtest behaviour | Verdict |
|---|---|---|---|
| composite_score | μ=+0.05 σ=0.04 | μ=−0.02 σ=0.04 | **GREEN** — varies normally, similar magnitude |
| sma_crossover | trade-traces μ=−0.25 σ=0.24 | μ=+0.28 σ=0.33 | **GREEN** — sign flipped (live=short bias) |
| timeframe_signal | μ=+0.44 σ=0.43 | μ=−0.11 σ=0.61 | **GREEN** — live more bullish |
| breakout_signal | μ=+0.01 σ=0.03 | μ=−0.03 σ=0.13 | **YELLOW-low_var** — live 4× tighter |
| adx_signal | μ=+0.05 σ=0.12 | μ=−0.03 σ=0.26 | **YELLOW-low_var** — live 2× tighter |
| ollivier_ricci | μ=−0.88 σ=0.03 | μ=−0.79 σ=0.09 | **YELLOW-scale** — live 3× tighter |
| ricci_curvature | μ=−0.0 σ=0.78 | μ=+0.09 σ=0.64 | GREEN |
| w2_crisis / w2_normal / w2_trend | σ ≈ 0 (2 cycles) | σ ≈ 0.004 | **YELLOW-too-few-cycles** — re-evaluate at v164 cycle 24 |
| tda_fragmentation, tda_betti0, tda_pers_entropy | live: constant 0.99/1.0/1.0 | bt: constant 0.0/0/0 (dead) | **RED — both broken differently.** TDA dead in backtest replay (no warmup buffer); frozen in live (real, but topology stable over 30-cycle window — structural, not the buffer bug fixed earlier) |
| vol_rank | 0 in both | 0 in both | **RED-dead-everywhere** — config/API gap |
| fear_greed_signal | 0 in metrics; +0.96 constant in trade-traces | 0 in metrics | **RED-broken in metrics, possibly stale-cached in trades** |
| funding_rate_btc | 0 | 0 | **RED-dead-everywhere** |
| dxy_signal | 0 | 0 | **RED-dead-everywhere** |

**Top finding from the scorecard:** at least 4 macro signals (`vol_rank`,
`fear_greed_signal`, `funding_rate_btc`, `dxy_signal`) are silently zero **in
both backtest and live**. The "20 active signals" reported in training logs is
misleading — the effective signal count is closer to 12-14. This is an
ingestion/config gap (no FRED key, no Binance funding access, etc.), not a
live-specific bug.

## Structural lessons

1. **Conviction filter is the weakest link in live.** It separates trades by
   composite-vs-threshold, but the threshold is calibrated on backtest
   distributions that have ~2× the variance in 4 of 8 measured signals. In
   live, marginal trades all cluster near the threshold and outcome becomes
   essentially random. **Fix candidate:** rolling-percentile conviction
   (e.g., trade only if conviction is in top 25% of last 50 cycles).

2. **The system trades in correlated bursts, not independent decisions.**
   Cycle 11 → 3 winners, cycle 13 → 1W/2L, cycle 19 → 2 losers. We are
   making ~3-4 independent decisions per 30 cycles, not 10. Statistical
   evaluation must reflect this — 30% WR on n=4 decisions is far less
   informative than 30% WR on n=10 trades.

3. **High_vol-entry block is empirically justified, but partial sizing
   could capture more alpha.** Both high_vol entries lost $179. If we had
   half-sized them, the loss would be $90 — still negative but $89 better.
   On the recent backtest snapshot, removing the block adds $1.6k of
   alpha. A half-size compromise might net positive there *and* halve crisis
   losses. **Fix candidate:** `high_vol_size_mult=0.5` instead of full block.

4. **Process loss is a real risk.** v163_live died at cycle 30 because
   /tmp got cleared by macOS. We lost 25 hours of run and need decisions
   under partial data. **Fix applied (v164):** `OMEGA_METRICS_DIR` env var
   honored by `run_training.py`; v164_live writes to `data/runs/`.

5. **Per-ticker decision traces are silently throttled.** v163_live's
   `decision_traces` JSONL only captured `per_ticker` payloads on cycles 1,
   3, 5, 7, 9, 11, 13, 15 — nothing after cycle 16. This means we cannot
   forensically inspect *why* normal-regime cycles 24, 31, 32 generated no
   trades. **Fix candidate:** disable trace sampling in live mode, or log the
   sampling rate so future forensics know what they're missing.

6. **TDA is structurally low-variation at 1h cadence on short windows.**
   Even with the `update_returns` fix, TDA's persistence diagram is stable
   over 30 cycles because the topological structure of (r_t, r_{t+1}) on
   60 returns doesn't change much in 30 hours. This is not a bug — it
   means TDA contributes near-constant signal in short live runs and only
   becomes informative over multi-day windows.

## Proposed fixes (V165)

| # | Fix | Feature flag | Default | Hypothesis |
|---|-----|--------------|---------|------------|
| 1 | Half-size in high_vol (alternative to hard block) | `high_vol_size_mult` | 1.0 | Captures half the lost alpha while halving downside |
| 2 | Bear-prob conditional block, threshold lowered | `conditional_high_vol_block` + `high_vol_block_bear_threshold=0.30` | False / 0.40 | 0.40 was too permissive (V164bt failed); 0.30 captures more crisis cycles |
| 3 | Live signal-health watchdog | `live_signal_health_check` | False | Log WARN if any signal stays 0/NaN for >10 cycles — stop silent degradation |
| 4 | Disable per-ticker trace sampling in live | `decision_trace_full_in_live` | False | Always-on traces give us forensic data without re-running |

V165 Phase A target: confirm composite ≥ V161's +$41,850 with crisis ≥ +$2,000.

### V165 Phase A result — FAILED

| Snap | V161 baseline | V165 (cond gate 0.30 + size_mult 0.5) | Δ |
|---|---|---|---|
| recent | +$4,319 | **+$2,259** | **−$2,060** |
| crisis | +$2,606 | **−$28,655** | **−$31,261** |
| trend  | +$34,925 | +$27,346 | −$7,579 |
| **composite** | **+$41,850** | **+$950** | **−$40,900 (−98%)** |

Worse than both V163bt (no block: +$10,357) and V164bt (cond block 0.40:
+$11,333). V165 is the worst variant tested.

**Why crisis breaks at any conditional threshold:** the crisis snapshot
contains cycles labeled `high_vol` (not `crisis`) where the Bayesian regime
detector hasn't yet caught up to the crash, so `bear_prob` is still low.
These are *exactly* the cycles V142's hard block was designed to catch. Any
gate that depends on `bear_prob >= threshold` lets them through, and they
lose at full or half size.

**Conclusion: the V142 hard `high_vol_entry_block` is unconditionally
correct.** Removing or weakening it costs $30-40k composite PnL. The $1.6k
recent-snapshot alpha gained by softening the block is dominated by the
crisis-snapshot loss by an order of magnitude.

**Recommendation:** keep `high_vol_entry_block=True` permanently. Do NOT
ship `conditional_high_vol_block` or `high_vol_size_mult` — leave them as
dead-code feature flags or remove them in a future cleanup commit. Future
work to capture the recent-snapshot high_vol alpha should focus on signal
recalibration (the conviction filter doesn't separate winners from losers
in live, lesson #1) rather than gate softening.

## Process changes already shipped

- **TDA/W2 buffer bug** — `update_returns` extends → replaces (commit `a2998e8`).
- **Persistent metrics dir** — `OMEGA_METRICS_DIR` env var (commit included
  in V164 work).
- **Auto_improve PARAM_BOUNDS expanded 5→7** (commit `7eef278`) — note
  V163's 7-param run did not improve over the 3-param +$41,850 best.

## Open questions for next live run

1. Does `v164_live` (24 cycles, current run) show the same single-burst
   trading pattern as v163 (3 trades on cycle 11)? If yes, that's a
   **structural** property of the strategy, not a v163 fluke.
2. With `OMEGA_METRICS_DIR=data/runs/`, do per-cycle metrics now persist
   through process restart? (Validation: if v164 is killed, is the JSONL
   still on disk?)
3. Do macro signals turn on if we set `FRED_API_KEY` and `COINGECKO_API_KEY`?
   The scorecard implies the answer is mostly "no, the integrations are
   stale" — but worth a 1-cycle test before designing around them.
