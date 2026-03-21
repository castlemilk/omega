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
    Run a direct SMA+RSI strategy on `bars` and return a summary dict.

    Bypasses the orchestrator entirely — uses omega.backtest strategy
    implementations directly against real OHLCV data with real slippage.
    """
    from omega.backtest import OHLCV, _multi_signal_strategy, _sma_crossover_strategy
    from omega.eval.sharpe import sharpe_ratio
    from omega.eval.significance import sharpe_is_significant

    commission = 0.001  # 0.1% Binance spot fee (entry + exit = 0.2% round-trip)

    logger.info("=" * 60)
    logger.info("Running backtest: %s (%d bars)", symbol, len(bars))
    logger.info("=" * 60)

    # Convert to OHLCV objects
    ohlcv_bars = [
        OHLCV(
            symbol=ticker,
            date=datetime.fromtimestamp(b["timestamp"], tz=UTC).date().isoformat(),
            open=float(b["open"]),
            high=float(b["high"]),
            low=float(b["low"]),
            close=float(b["close"]),
            volume=float(b["volume"]),
        )
        for b in bars
    ]

    # ------------------------------------------------------------------
    # Main strategy: SMA(10/30) crossover gated by RSI < 70
    # ------------------------------------------------------------------
    trades, daily_rets = _multi_signal_strategy(ticker, ohlcv_bars)

    # Deduct commission on each round-trip trade
    for t in trades:
        t.pnl_pct -= 2 * commission

    # ------------------------------------------------------------------
    # Walk-forward split (60% in-sample / 40% out-of-sample)
    # ------------------------------------------------------------------
    split = int(len(daily_rets) * 0.60)
    is_rets = daily_rets[:split]
    oos_rets = daily_rets[split:]
    is_sharpe = sharpe_ratio(is_rets, periods_per_year=PERIODS_PER_YEAR)
    oos_sharpe = sharpe_ratio(oos_rets, periods_per_year=PERIODS_PER_YEAR)

    # ------------------------------------------------------------------
    # Bootstrap CI on full returns
    # ------------------------------------------------------------------
    sig, sharpe_pt, (ci_lo, ci_hi) = sharpe_is_significant(
        daily_rets,
        periods_per_year=PERIODS_PER_YEAR,
        n_bootstrap=2000,
        seed=42,
    )

    # Max drawdown (equity-based, compound returns)
    equity, peak_eq, max_dd = 1.0, 1.0, 0.0
    for r in daily_rets:
        equity *= 1.0 + r
        if equity > peak_eq:
            peak_eq = equity
        dd = (peak_eq - equity) / peak_eq
        if dd > max_dd:
            max_dd = dd

    total_return = equity - 1.0  # compound total return

    # ------------------------------------------------------------------
    # Baselines
    # ------------------------------------------------------------------
    closes = [b["close"] for b in bars]
    bnh_rets = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    bnh_sharpe = sharpe_ratio(bnh_rets, periods_per_year=PERIODS_PER_YEAR)
    bnh_eq = 1.0
    for r in bnh_rets:
        bnh_eq *= 1.0 + r
    bnh_total = bnh_eq - 1.0

    _sma_trades, sma_rets = _sma_crossover_strategy(ticker, ohlcv_bars, short=10, long=30)
    sma_sharpe_val = sharpe_ratio(sma_rets, periods_per_year=PERIODS_PER_YEAR)

    logger.info(
        "  %s: trades=%d sharpe=%.3f [%.3f, %.3f] sig=%s",
        symbol,
        len(trades),
        sharpe_pt,
        ci_lo,
        ci_hi,
        sig,
    )

    return {
        "symbol": symbol,
        "n_bars": len(bars),
        "n_trades": len(trades),
        "sharpe": sharpe_pt,
        "sharpe_ci_lo": ci_lo,
        "sharpe_ci_hi": ci_hi,
        "sharpe_significant": sig,
        "max_drawdown": max_dd,
        "total_return": total_return,
        "in_sample_sharpe": is_sharpe,
        "out_of_sample_sharpe": oos_sharpe,
        "bnh_sharpe": bnh_sharpe,
        "bnh_total_return": bnh_total,
        "sma_sharpe": sma_sharpe_val,
    }


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
