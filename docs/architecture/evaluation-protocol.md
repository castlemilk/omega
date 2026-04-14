# Victoria Evaluation Protocol

**Status**: Canonical from V128+  
**Problem solved**: V-run PnL comparisons were confounded by market regime variation. V122 > V121 might mean the fix worked, or it might mean the market moved. This protocol eliminates that ambiguity.

---

## The Core Insight

A version comparison is only valid if the market conditions are held constant. Until V127, every V-run sampled a different trailing 90-day window of live data. The only way to attribute performance differences to code changes is to run all candidates against an **identical, frozen dataset**.

---

## Two-Phase Protocol

### Phase A — Benchmark (Deterministic Backtest)

**Goal**: Establish whether a code change actually improves signal quality, independent of market conditions.

**Process**:
1. Pick a fixed set of **regime snapshots** (see below). Each snapshot is a frozen OHLCV + macro JSON file that never changes after creation.
2. Run the candidate version against **all snapshots** using `--backtest-snapshot` mode: `python3 scripts/run_training.py --version vNNN --backtest-snapshot <path> --seed 42`
3. Score the candidate on the **benchmark scorecard** (see schema below).
4. The candidate **must beat the incumbent** on the aggregate leaderboard score to be promoted. Beating on only one snapshot is insufficient — it may reflect regime luck.
5. Produce a commit recording the benchmark result. Do not promote a version without a passing benchmark result on file.

**Determinism guarantee**: with `--backtest-snapshot` + `--seed N`, two runs of identical code against the same snapshot must produce bit-for-bit identical trades.csv. Any stochastic element (random exit timing, KMeans init, embedding cluster assignment) is seeded.

**WS signal behavior**: WebSocket signals (microstructure, whale_prints) degrade to 0.0 automatically in backtest mode. The benchmark therefore measures the replayable signal set only. This is a feature, not a bug — it isolates the core signal quality from data-availability effects.

### Phase B — Live Validation

**Goal**: Measure real-world effectiveness of versions that passed Phase A.

**Process**:
1. Only Phase A passing versions are promoted to live paper-trade runs.
2. Live runs use `run_training.py` without `--backtest-snapshot` (current behavior).
3. WS signals are active in live mode.
4. Record **live vs backtest divergence** as an explicit metric: `live_pnl / backtest_pnl` per snapshot. If divergence > 2x in either direction, the snapshot set is unrepresentative of current market conditions and should be refreshed.

**Retirement trigger**: If a live run is significantly worse than its Phase A benchmark score AND the divergence metric is extreme, pull the version and re-benchmark.

---

## Regime Snapshot Set

Three snapshots cover materially different market regimes. All benchmarks must pass on all three.

| Snapshot | Period | Regime | File |
|----------|--------|--------|------|
| `snap_recent` | Last 90d from creation | Mixed (crisis + normal) | `data/snapshots/snap_20260414.json` |
| `snap_trending` | Q4 2023 (BTC 26k→73k) | Bull / trending | `data/snapshots/snap_trending_2023q4.json` |
| `snap_crisis` | H1 2022 (BTC 68k→28k) | Bear / crisis | `data/snapshots/snap_crisis_2022h1.json` |

Snapshots are **immutable after creation**. Never overwrite a named snapshot — create a new one with a date suffix if conditions have materially changed. Refresh `snap_recent` monthly.

---

## Benchmark Scorecard

Defined in `data/benchmarks/scorecard_schema.json`. Fields per version per snapshot:

| Field | Description | Pass threshold |
|-------|-------------|----------------|
| `pnl` | Total closed PnL ($) | > incumbent |
| `win_rate` | Fraction of winning trades | — (informational) |
| `profit_factor` | Gross profit / gross loss | > 1.0 |
| `max_drawdown` | Peak-to-trough equity drawdown ($) | < incumbent |
| `n_trades` | Total closed trades | ≥ 20 |
| `long_pct` | Fraction of trades that are long | 20–80% |
| `short_pct` | Fraction of trades that are short | 20–80% |
| `regime_pnl` | PnL breakdown: normal / crisis / high_vol | All regimes ≥ -$50 |
| `disposition_coefficient` | median_win_capture − median_loss_capture | > -0.2 |
| `sharpe` | Annualised Sharpe ratio | > 0.5 |

**Aggregate leaderboard score** = PnL rank + PF rank + Sharpe rank (lower rank = better), summed across all three snapshots. Lowest total score wins.

---

## Disposition Coefficient

Measures exit discipline. Captures the *disposition effect* — the tendency to realise winners too early and hold losers too long.

```
# Per-trade (requires MFE/MAE in trades CSV — V128+ only)
win_capture  = pnl / mfe         (if pnl > 0, else NaN)
loss_capture = pnl / mae         (if pnl < 0, else NaN)  # both negative; ratio ∈ [0,1]
exit_score   = win_capture − loss_capture

# Aggregate
disposition_coefficient = nanmedian(win_capture) − nanmedian(loss_capture)
```

Target: `> 0.3` acceptable, `> 0.5` good. Negative = classic disposition effect (cutting winners, holding losers).

**Backfill approximation** for V93–V127 (no MFE/MAE in those CSVs):
```
# Hold-duration asymmetry — disposition proxy
hold_winner_mean = mean hold_cycles for trades with pnl > 0
hold_loser_mean  = mean hold_cycles for trades with pnl < 0
hold_ratio       = hold_winner_mean / hold_loser_mean
# hold_ratio > 1 = holding winners longer → good
# hold_ratio < 1 = holding losers longer → disposition effect
```

---

## Usage

### Freeze a new snapshot (today's market)
```bash
python3 scripts/freeze_snapshot.py
# → data/snapshots/snap_YYYYMMDD.json
```

### Freeze a historical period snapshot
```bash
python3 scripts/freeze_snapshot.py \
  --start-date 2023-10-01 --end-date 2024-03-31 \
  --out data/snapshots/snap_trending_2023q4.json
```

### Run a Phase A benchmark
```bash
python3 scripts/run_training.py \
  --version v128 \
  --cycles 200 \
  --features v115_full_vectors \
  --backtest-snapshot data/snapshots/snap_20260414.json \
  --seed 42
```

### Run the full leaderboard (all versions × all snapshots)
```bash
python3 scripts/run_leaderboard.py \
  --versions v93_baseline v112_evidence_based v115_full_vectors \
  --snapshots data/snapshots/snap_*.json \
  --cycles 200 \
  --seed 42 \
  --out data/benchmarks/leaderboard.json
```

---

## What Changes for the Overnight Loop

The overnight loop (`scripts/overnight_loop.py`) should operate in **backtest mode by default** from V128+:

```bash
python3 scripts/overnight_loop.py \
  --start v128 \
  --max-versions 5 \
  --mode backtest \
  --snapshot data/snapshots/snap_20260414.json \
  --seed 42
```

In `--mode backtest`:
- Each version runs against the frozen snapshot (no live API waits — much faster)
- Postmortem/forensics work on backtest artifacts unchanged
- Balance guardrail checks backtest L/S ratio
- Version is committed only if it passes backtest gates
- Live promotion is a separate manual step

---

## Divergence Monitoring

After each live run of a promoted version, compute:

```
live_divergence = live_pnl / backtest_pnl_on_snap_recent
```

Log to `data/benchmarks/divergence_log.json`. If `|live_divergence| > 2.0` for two consecutive versions:
- The `snap_recent` snapshot is stale — refresh it
- Re-run Phase A leaderboard on the new snapshot before promoting further versions

---

## Version Config Definitions

For leaderboard comparisons, "version config" means feature flags + signal filter state (not codebase git hash). Canonical configs:

| Config name | Feature flags | Dead signals | Notes |
|-------------|---------------|-------------|-------|
| `v93_baseline` | all OFF | none | Baseline — no ML, no WS |
| `v112_evidence_based` | embeddings + traces + reinforcement | sma_long/short/crossover, price, return_1d, fear_greed, liquidation_proximity | First evidence-based filter |
| `v115_full_vectors` | v112 + ws_microstructure + temporal + whale_prints + whale_flow + funding_velocity | above + vpin + ricci + trade_flow_direction | Current production config |
| `v128_clean` | v115 but NO dead signals | none | Test: do flips help or hurt? |

---

*Protocol effective from V128. Existing V93–V127 results are informational only — they were run on live data and cannot be compared fairly.*
