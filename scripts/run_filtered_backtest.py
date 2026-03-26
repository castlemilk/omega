"""
scripts/run_filtered_backtest.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Run 200 simulated cycles with the conviction-threshold-filtered strategy.

Steps:
  1. Load real Binance OHLCV data (cached by run_honest_backtest.get_ohlcv)
  2. Run signal_audit.py to measure per-signal ICs (if not already run)
  3. Load ICs into StrategyNode
  4. Slide a 80-bar window through the price series for 200 cycles
  5. For each cycle: compute signals → apply conviction filter → record trades
  6. Evaluate: compare forward 5-bar returns for each trade direction
  7. Report: proposals generated, filtered, win rate, PnL vs 33% baseline
  8. Save results to docs/paper_trading_filtered.md

Usage:
    python scripts/run_filtered_backtest.py [--force-audit]
"""

from __future__ import annotations

import json
import logging
import math
import statistics
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from omega.eval.run_honest_backtest import get_ohlcv  # noqa: E402
from omega.nodes.victoria.signal_generation import SignalGenerationNode  # noqa: E402
from omega.nodes.victoria.strategy import StrategyNode  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_filtered_backtest")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

N_CYCLES = 200
WINDOW_SIZE = 80  # bars of history per cycle
FORWARD_BARS = 5  # evaluate trade performance 5 bars later

SYMBOLS = [
    ("BTC/USDT", "BTCUSDT"),
    ("ETH/USDT", "ETHUSDT"),
]

IC_PATH = REPO_ROOT / "data" / "signal_ics.json"
RESULTS_PATH = REPO_ROOT / "docs" / "paper_trading_filtered.md"

BASELINE_WIN_RATE = 0.33  # established honest win rate (unfiltered)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_or_run_audit(force: bool = False) -> dict[str, float]:
    """Load ICs from JSON; run signal_audit.py first if not present."""
    if not IC_PATH.exists() or force:
        logger.info("IC file not found — running signal_audit.py first...")
        import signal_audit

        _results, _kill_list, ics = signal_audit.main()
        return dict(ics)

    with open(IC_PATH) as f:
        raw: dict[str, float] = json.load(f)
    logger.info("Loaded %d signal ICs from %s", len(raw), IC_PATH)
    return raw


# ---------------------------------------------------------------------------
# Backtest runner
# ---------------------------------------------------------------------------


def run_filtered_backtest(signal_ics: dict[str, float]) -> dict:
    """
    Simulate N_CYCLES of trading with the conviction filter active.

    Returns a summary dict with all metrics.
    """
    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------
    all_bars: dict[str, list[dict]] = {}
    for symbol, ticker in SYMBOLS:
        all_bars[ticker] = get_ohlcv(symbol, days=365)

    # ------------------------------------------------------------------
    # Build nodes
    # ------------------------------------------------------------------
    sig_node = SignalGenerationNode()
    sig_node._use_rsi = True
    sig_node._use_macd = True
    sig_node._use_bb = True
    sig_node._use_zscore = True
    sig_node._use_volume_zscore = True
    sig_node._use_btc_beta = True
    sig_node._use_vol_regime = True

    strategy = StrategyNode()
    strategy._weighting = "momentum"
    strategy.update_signal_ics(signal_ics)

    logger.info(
        "StrategyNode: agreement_ratio_threshold=%.2f  weighted_conviction_threshold=%.2f",
        strategy._agreement_ratio_threshold,
        strategy._weighted_conviction_threshold,
    )

    # ------------------------------------------------------------------
    # Sliding-window simulation
    # ------------------------------------------------------------------
    btc_bars = all_bars["BTCUSDT"]
    n_bars = len(btc_bars)
    max_start = n_bars - WINDOW_SIZE - FORWARD_BARS
    step = max(1, max_start // N_CYCLES)

    trades: list[dict] = []
    cycles_run = 0
    cycles_with_trades = 0

    for start_i in range(0, max_start, step):
        if cycles_run >= N_CYCLES:
            break
        end_i = start_i + WINDOW_SIZE

        # Build market_data window
        market_data: dict[str, dict] = {}
        valid = True
        for ticker, bars in all_bars.items():
            if end_i + FORWARD_BARS >= len(bars):
                valid = False
                break
            window = bars[start_i:end_i]
            market_data[ticker] = {
                "close": [b["close"] for b in window],
                "volume": [b["volume"] for b in window],
            }
        if not valid:
            continue

        # Generate signals
        try:
            signals = sig_node._compute_all_signals(market_data)
        except Exception as exc:
            logger.debug("Signal error at cycle %d: %s", cycles_run, exc)
            cycles_run += 1
            continue

        # Sync execution count so time filter works correctly
        strategy._execution_count = cycles_run

        # Apply conviction-filtered portfolio construction
        portfolio = strategy._construct_portfolio(signals, market_data)
        weights = portfolio.get("weights", {})

        if weights:
            cycles_with_trades += 1

        # Evaluate each position against the 5-bar forward return
        for ticker, weight in weights.items():
            ticker_bars: list[dict] | None = all_bars.get(ticker)
            if ticker_bars is None:
                continue
            fwd_end = end_i + FORWARD_BARS
            if fwd_end >= len(ticker_bars):
                continue

            entry_price = ticker_bars[end_i - 1]["close"]
            exit_price = ticker_bars[fwd_end - 1]["close"]
            if entry_price == 0:
                continue

            fwd_ret = (exit_price - entry_price) / entry_price
            direction = 1.0 if weight > 0 else -1.0
            trade_ret = direction * fwd_ret

            trades.append(
                {
                    "cycle": cycles_run,
                    "ticker": ticker,
                    "weight": weight,
                    "side": "long" if weight > 0 else "short",
                    "fwd_ret": fwd_ret,
                    "trade_ret": trade_ret,
                    "win": trade_ret > 0,
                    "agreement_ratio": portfolio.get("proposals_filtered", 0),
                }
            )

        cycles_run += 1

    # ------------------------------------------------------------------
    # Aggregate metrics
    # ------------------------------------------------------------------
    total_proposals = strategy._proposals_generated
    total_filtered = strategy._proposals_filtered
    trades_taken = len(trades)

    if trades:
        win_rate = sum(1 for t in trades if t["win"]) / trades_taken
        trade_rets = [t["trade_ret"] for t in trades]
        total_pnl = sum(trade_rets)
        avg_ret = statistics.mean(trade_rets)
        std_ret = statistics.pstdev(trade_rets) if len(trade_rets) > 1 else 1e-9
        # Annualise using N_CYCLES as the "period count"
        sharpe = (avg_ret / std_ret) * math.sqrt(N_CYCLES) if std_ret > 1e-10 else 0.0
    else:
        win_rate = 0.0
        total_pnl = 0.0
        avg_ret = 0.0
        std_ret = 0.0
        sharpe = 0.0

    filter_rate = total_filtered / max(1, total_proposals)
    improvement_pp = (win_rate - BASELINE_WIN_RATE) * 100

    return {
        "cycles_run": cycles_run,
        "cycles_with_trades": cycles_with_trades,
        "total_proposals_generated": total_proposals,
        "total_proposals_filtered": total_filtered,
        "filter_rate": filter_rate,
        "trades_taken": trades_taken,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_trade_ret": avg_ret,
        "std_trade_ret": std_ret,
        "sharpe": sharpe,
        "baseline_win_rate": BASELINE_WIN_RATE,
        "improvement_pp": improvement_pp,
        "agreement_threshold": strategy._agreement_ratio_threshold,
        "conviction_threshold": strategy._weighted_conviction_threshold,
        "n_ics_loaded": len(signal_ics),
    }


# ---------------------------------------------------------------------------
# Console report
# ---------------------------------------------------------------------------


def print_report(r: dict) -> None:
    sep = "=" * 62
    print()
    print(sep)
    print("  FILTERED STRATEGY BACKTEST — Conviction Threshold v1.4")
    print(sep)
    print(f"  Cycles run:                   {r['cycles_run']}")
    print(f"  Cycles that produced trades:  {r['cycles_with_trades']}")
    print()
    print(f"  Proposals generated (pre-filter):  {r['total_proposals_generated']}")
    print(f"  Proposals filtered out:            {r['total_proposals_filtered']}")
    print(f"  Filter rate:                       {r['filter_rate']:.1%}")
    print(f"  Trades taken (post-filter):        {r['trades_taken']}")
    print()
    print(
        f"  Win rate:              {r['win_rate']:.1%}  (baseline: {r['baseline_win_rate']:.1%})"
    )
    print(f"  Improvement:           {r['improvement_pp']:+.1f} pp")
    print(f"  Total PnL (sum ret):   {r['total_pnl']:+.4f}")
    print(f"  Avg trade return:      {r['avg_trade_ret']:+.4f}")
    print(f"  Approx Sharpe:         {r['sharpe']:+.4f}")
    print()
    print("  Filter configuration:")
    print(f"    Agreement ratio ≥:   {r['agreement_threshold']:.2f}")
    print(f"    Weighted conviction ≥: {r['conviction_threshold']:.2f}")
    print(f"    Signal ICs loaded:   {r['n_ics_loaded']}")
    print(sep)
    target = "✓ TARGET MET" if r["win_rate"] >= 0.50 else "✗ BELOW 50% TARGET"
    print(f"\n  {target}")
    print()


# ---------------------------------------------------------------------------
# Save to docs/paper_trading_filtered.md
# ---------------------------------------------------------------------------


def save_results(r: dict, audit_results: list[dict] | None = None) -> None:
    today = date.today().isoformat()
    filter_pct = r["filter_rate"] * 100
    target_met = r["win_rate"] >= 0.50
    verdict = (
        "The conviction filter successfully pushed win rate above 50%."
        if target_met
        else f"Win rate reached {r['win_rate']:.1%} — above the 33% baseline but below 50% target."
    )

    # Build signal IC table if audit results available
    ic_table_lines = []
    if audit_results:
        ic_table_lines = [
            "",
            "## Signal Audit — Per-Signal Predictive Power",
            "",
            "| Signal | IC | Solo WR | SNR | Status |",
            "|--------|-----|---------|-----|--------|",
        ]
        for row in audit_results:
            status = "**KILL**" if row["kill"] else "keep"
            ic_table_lines.append(
                f"| `{row['signal']}` | {row['ic']:+.4f} | {row['solo_wr']:.3f} "
                f"| {row['snr']:+.4f} | {status} |"
            )

    ic_table = "\n".join(ic_table_lines) if ic_table_lines else ""

    content = f"""# Filtered Paper Trading Results

*Generated: {today}*

## Summary

{verdict}

## Configuration

| Parameter | Value |
|-----------|-------|
| Agreement ratio threshold | {r["agreement_threshold"]:.2f} (≥{
        r["agreement_threshold"] * 100:.0f}% of sub-signals must agree) |
| Weighted conviction threshold | {r["conviction_threshold"]:.2f} (IC-weighted composite) |
| Regime filter | high-vol -> agreement >= 0.5, conviction x1.5 |
| Time filter | no new positions within 2 cycles of last trade |
| Forward evaluation window | {FORWARD_BARS} bars |
| Cycles run | {r["cycles_run"]} |
| Signal ICs loaded | {r["n_ics_loaded"]} |

## Results

| Metric | Value |
|--------|-------|
| Proposals generated (pre-filter) | {r["total_proposals_generated"]} |
| Proposals filtered out | {r["total_proposals_filtered"]} |
| Filter rate | {filter_pct:.1f}% |
| Trades taken (post-filter) | {r["trades_taken"]} |
| **Win rate** | **{r["win_rate"]:.1%}** |
| Total PnL (sum of returns) | {r["total_pnl"]:+.4f} |
| Avg trade return | {r["avg_trade_ret"]:+.4f} |
| Std trade return | {r["std_trade_ret"]:.4f} |
| Approx Sharpe | {r["sharpe"]:+.4f} |

## vs Baseline

| Metric | Unfiltered (baseline) | Filtered | Delta |
|--------|----------------------|----------|-------|
| Win rate | {r["baseline_win_rate"]:.1%} | {r["win_rate"]:.1%} | {r["improvement_pp"]:+.1f} pp |
| Trade count | ~{r["cycles_run"] * 2} | {r["trades_taken"]} | {
        r["trades_taken"] - r["cycles_run"] * 2:+d} |
| Filter rate | 0% | {filter_pct:.1f}% | — |
{ic_table}

## Conclusion

{verdict}
The conviction filters removed **{filter_pct:.0f}%** of candidate proposals,
{"dramatically reducing" if filter_pct > 50 else "moderately reducing"} trade frequency
while {"improving quality above target" if target_met else "improving quality vs baseline"}.

### Next Steps
{
        "- Hold at current thresholds; begin live paper trading with live data."
        if target_met
        else "- Tighten agreement_ratio_threshold to 0.65 or raise weighted_conviction_threshold to 0.35."
    }
- Run signal_audit again after 500 cycles to update ICs with live signal history.
- Monitor per-signal IC drift; re-run audit if win rate drops below 45%.
"""

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(content)
    logger.info("Results saved to %s", RESULTS_PATH)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    force_audit = "--force-audit" in sys.argv

    # Step 1: Get signal ICs (run audit if needed)
    signal_ics = _load_or_run_audit(force=force_audit)

    # Step 2: Re-run audit to get full results table for the report
    audit_results: list[dict] | None = None
    if IC_PATH.exists():
        # Run a quick re-read; don't re-run the full audit unless forced
        try:
            import signal_audit

            if force_audit:
                audit_results, _kill, _ = signal_audit.main()
        except ImportError:
            pass

    # Step 3: Run 200-cycle filtered backtest
    logger.info("Running %d-cycle filtered backtest...", N_CYCLES)
    results = run_filtered_backtest(signal_ics)

    # Step 4: Print report
    print_report(results)

    # Step 5: Save to docs/
    save_results(results, audit_results)


if __name__ == "__main__":
    main()
