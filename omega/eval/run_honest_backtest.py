"""
omega.eval.run_honest_backtest
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Download 1 year of real daily OHLCV from Binance (no API key required)
and run the OmegaBacktestBridge to produce honest Sharpe numbers.

Usage:
    python -m omega.eval.run_honest_backtest
"""

from __future__ import annotations

import csv
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("omega.eval.run_honest_backtest")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "historical"
DATA_DIR.mkdir(parents=True, exist_ok=True)

PERIODS_PER_YEAR = 365  # daily crypto, 365 trading days/year

# ---------------------------------------------------------------------------
# Data download
# ---------------------------------------------------------------------------


def _fetch_ohlcv_binance(symbol: str, days: int = 365) -> list[dict]:
    """
    Download `days` daily candles for `symbol` from Binance public API.

    Returns list of dicts: {timestamp, open, high, low, close, volume}
    where timestamp is unix seconds (int).
    """
    try:
        import ccxt
    except ImportError as exc:
        raise RuntimeError("ccxt not installed. Run: pip install ccxt") from exc

    exchange = ccxt.binance({"enableRateLimit": True})

    logger.info("Fetching %d daily bars for %s from Binance...", days, symbol)

    # Binance limit per request is 1000 candles; daily 365 fits in one shot
    since_ms = int((time.time() - days * 86_400) * 1000)

    raw = exchange.fetch_ohlcv(symbol, timeframe="1d", since=since_ms, limit=days + 10)

    # Trim to exactly `days` most recent bars
    raw = sorted(raw, key=lambda x: x[0])  # oldest first
    if len(raw) > days:
        raw = raw[-days:]

    bars = []
    for row in raw:
        ts_sec = int(row[0] // 1000)
        bars.append(
            {
                "timestamp": ts_sec,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        )

    logger.info(
        "  Got %d bars for %s (first=%s last=%s)",
        len(bars),
        symbol,
        datetime.fromtimestamp(bars[0]["timestamp"], tz=UTC).date() if bars else "N/A",
        datetime.fromtimestamp(bars[-1]["timestamp"], tz=UTC).date() if bars else "N/A",
    )
    return bars


def _save_csv(bars: list[dict], path: Path) -> None:
    """Save OHLCV bars to CSV."""
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["timestamp", "open", "high", "low", "close", "volume"]
        )
        writer.writeheader()
        writer.writerows(bars)
    logger.info("Saved %d bars → %s", len(bars), path)


def _load_csv(path: Path) -> list[dict]:
    """Load OHLCV bars from CSV."""
    bars = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(
                {
                    "timestamp": int(row["timestamp"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
            )
    logger.info("Loaded %d bars from %s", len(bars), path)
    return bars


def get_ohlcv(symbol: str, days: int = 365, force_refresh: bool = False) -> list[dict]:
    """
    Get OHLCV data — from cache CSV if available, otherwise download.
    """
    safe_name = symbol.replace("/", "_").lower()
    csv_path = DATA_DIR / f"{safe_name}_daily_{days}d.csv"

    if csv_path.exists() and not force_refresh:
        logger.info("Cache hit: %s", csv_path)
        return _load_csv(csv_path)

    bars = _fetch_ohlcv_binance(symbol, days)
    _save_csv(bars, csv_path)
    return bars


# ---------------------------------------------------------------------------
# Backtest runner
# ---------------------------------------------------------------------------


def run_backtest_for_symbol(symbol: str, ticker: str, bars: list[dict]) -> dict:
    """
    Run OmegaBacktestBridge on `bars` and return a summary dict.
    """
    from omega.eval.backtest_bridge import BacktestMode, OmegaBacktestBridge
    from omega.eval.significance import sharpe_is_significant

    logger.info("=" * 60)
    logger.info("Running backtest: %s (%d bars)", symbol, len(bars))
    logger.info("=" * 60)

    bridge = OmegaBacktestBridge(
        mode=BacktestMode.PICO,
        ticker=ticker,
        lookback_window=30,  # 30-day lookback for daily data
        initial_capital=1.0,
        commission=0.001,  # 0.1% Binance spot fee
        periods_per_year=PERIODS_PER_YEAR,
    )

    result = bridge.run(bars)

    # ------------------------------------------------------------------
    # Extract key metrics
    # ------------------------------------------------------------------
    report = result.report
    bnh = result.baselines.get("buy_and_hold")
    sma = result.baselines.get("sma_crossover")

    sig, sharpe_pt, (ci_lo, ci_hi) = sharpe_is_significant(
        result.returns,
        periods_per_year=PERIODS_PER_YEAR,
        n_bootstrap=2000,
        seed=42,
    )

    summary = {
        "symbol": symbol,
        "n_bars": result.n_bars,
        "n_trades": report.n_trades if report else 0,
        "sharpe": sharpe_pt,
        "sharpe_ci_lo": ci_lo,
        "sharpe_ci_hi": ci_hi,
        "sharpe_significant": sig,
        "max_drawdown": report.max_drawdown if report else 0.0,
        "total_return": report.total_return if report else 0.0,
        "in_sample_sharpe": report.in_sample_sharpe if report else 0.0,
        "out_of_sample_sharpe": report.out_of_sample_sharpe if report else 0.0,
        "bnh_sharpe": bnh.sharpe if bnh else 0.0,
        "bnh_total_return": bnh.total_return if bnh else 0.0,
        "sma_sharpe": sma.sharpe if sma else 0.0,
    }

    return summary


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------


def print_report(summaries: list[dict]) -> None:
    """Print a formatted report of all backtest results."""
    sep = "=" * 70

    print()
    print(sep)
    print("  OMEGA HONEST BACKTEST RESULTS — Real Binance Daily OHLCV Data")
    print(sep)

    for s in summaries:
        print(f"\n  Symbol: {s['symbol']}")
        print(f"  Bars:   {s['n_bars']}  |  Trades: {s['n_trades']}")
        print()
        print(
            f"  Strategy Sharpe:    {s['sharpe']:+.4f}  "
            f"[95% CI: {s['sharpe_ci_lo']:+.4f} .. {s['sharpe_ci_hi']:+.4f}]  "
            f"{'✓ SIGNIFICANT' if s['sharpe_significant'] else '✗ NOT SIGNIFICANT'}"
        )
        print(f"  Max Drawdown:       {s['max_drawdown'] * 100:.2f}%")
        print(f"  Total Return:       {s['total_return'] * 100:.2f}%")
        print()
        print("  Walk-Forward:")
        print(f"    In-Sample  Sharpe: {s['in_sample_sharpe']:+.4f}")
        print(f"    Out-Sample Sharpe: {s['out_of_sample_sharpe']:+.4f}")
        print()
        print("  Baselines:")
        print(
            f"    Buy & Hold Sharpe: {s['bnh_sharpe']:+.4f}  "
            f"(Total Return: {s['bnh_total_return'] * 100:.2f}%)"
        )
        print(f"    SMA Crossover:     {s['sma_sharpe']:+.4f}")

        beats_bnh = s["sharpe"] > s["bnh_sharpe"]
        beats_sma = s["sharpe"] > s["sma_sharpe"]
        print()
        print(
            f"  Alpha vs Buy&Hold:  {'BEATS' if beats_bnh else 'LOSES TO'} baseline  "
            f"(delta: {s['sharpe'] - s['bnh_sharpe']:+.4f})"
        )
        print(
            f"  Alpha vs SMA Cross: {'BEATS' if beats_sma else 'LOSES TO'} baseline  "
            f"(delta: {s['sharpe'] - s['sma_sharpe']:+.4f})"
        )

    print()
    print(sep)

    # Overall verdict
    all_significant = all(s["sharpe_significant"] for s in summaries)
    beats_all_bnh = all(s["sharpe"] > s["bnh_sharpe"] for s in summaries)

    print()
    if all_significant and beats_all_bnh:
        print("  VERDICT: Strategy shows statistically significant Sharpe above")
        print("           buy-and-hold across all tested assets. Alpha may be real.")
    elif all_significant:
        print("  VERDICT: Sharpe is statistically significant (CI > 0) but does NOT")
        print("           beat buy-and-hold. Strategy has no edge over passive.")
    else:
        print("  VERDICT: Sharpe is NOT statistically significant. The CI crosses 0.")
        print("           Cannot distinguish from luck with this sample size.")

    print()
    print("  NOTE: PICO mode used (deterministic signal extraction only).")
    print("        Supervised/Autonomous mode may differ.")
    print(sep)
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    symbols = [
        ("BTC/USDT", "BTCUSDT"),
        ("ETH/USDT", "ETHUSDT"),
    ]

    summaries = []
    errors = []

    for symbol, ticker in symbols:
        try:
            bars = get_ohlcv(symbol, days=365)
            summary = run_backtest_for_symbol(symbol, ticker, bars)
            summaries.append(summary)
        except Exception as exc:
            logger.error("FAILED for %s: %s", symbol, exc, exc_info=True)
            errors.append((symbol, str(exc)))

    if summaries:
        print_report(summaries)
    else:
        print("\nNo successful backtests. Errors:")
        for sym, err in errors:
            print(f"  {sym}: {err}")
        return 1

    if errors:
        print(f"\nPartial failures ({len(errors)} symbols failed):")
        for sym, err in errors:
            print(f"  {sym}: {err}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
