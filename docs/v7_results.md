# V7 Paper Trading Results — 100 Cycles (2026-03-26)

## Run Summary

- **Branch**: `claude/amazing-yonath`
- **Cycles**: 100 completed
- **Interval**: 30s sleep between cycles
- **Total wall time**: ~57 min
- **Stale price cache fix**: cherry-picked (`abcc22b`) before run

## Cycle Execution

| Metric | Value |
|--------|-------|
| Cycles completed | 100/100 |
| Avg cycle latency | 3.8s |
| Min latency | 2.2s |
| Max latency | 12.7s (cycle 1 warm-up) |
| Cycles >5s | 13 |

## Safety / Adversarial Events

| Event | Count |
|-------|-------|
| Ring 1 disagreement fires | 109 (every cycle, multiple per cycle) |
| Critical adversarial → autonomy demotion | 14 |
| VRP circuit breaker | 1 (zscore=-4.24, extreme COMPLACENCY) |

**Dominant outlier**: `macro_signals` flagged as Ring 1 outlier on nearly every cycle. Secondary: `disagreement`, `order_flow`.

## Trade Persistence

**No trades persisted.** `DATABASE_URL` env var not set — `PaperTradingEngine` skipped postgres writes silently. SQLite state DBs (`omega_victoria_state.db`, `omega_victoria.db`) also show 0 node_executions — the `OmegaOrchestrator` wrapper doesn't write to the local state store.

Cycles ran end-to-end in-memory; signal generation, adversarial gating, and Ring 1 checks all fired correctly.

## Key Observations

1. **Ring 1 fires every cycle** — `macro_signals` is consistently >0.44 distance from the signal ensemble. This is a persistent outlier, not noise. Either macro signals are genuinely contrarian or the threshold (0.200) is too tight for this signal's natural variance.

2. **Adversarial demotions** — 14 critical flags across 100 cycles. Node autonomy level being demoted each time. Likely driven by Ring 1 disagreements escalating to adversarial gate.

3. **VRP COMPLACENCY** — zscore=-4.24 on one cycle. IV (0.52) below RV (0.57), flagged for manual review. Vol regime worth monitoring.

4. **No trade data** — to get actual PnL/win-rate stats, need either:
   - Set `DATABASE_URL=postgresql://...` before running
   - Use `scripts/run_paper_trading.py` which has its own postgres path
   - Check `data/omega_victoria.db` iterations table (has 0 rows from this run)

## Next Steps

- Set `DATABASE_URL` and re-run for real trade metrics
- Investigate `macro_signals` Ring 1 outlier — consider raising threshold or investigating signal scale
- VRP complacency signal worth tracking as a regime indicator
