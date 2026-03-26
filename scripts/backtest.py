#!/usr/bin/env python3
"""
scripts/backtest.py
~~~~~~~~~~~~~~~~~~~
Honest multi-period backtest across bull, bear, and sideways crypto regimes.

Downloads historical daily OHLCV from Binance (free public API, no key needed),
then replays through the SMA+RSI strategy used in production and reports
honest metrics segmented by market regime.

Tested periods
--------------
bull     : Oct 2023 - Mar 2024  (BTC 26k to 73k)
bear     : May 2022 - Nov 2022  (BTC 38k to 16k)
sideways : Jul 2024 - Oct 2024  (BTC 55k-65k chop)

Honest metrics per period
--------------------------
  win_rate      - fraction of closed trades with pnl > 0
  profit_factor - gross_profit / gross_loss (need > 1.5 for real edge)
  expectancy    - (win_rate * avg_win) + (loss_rate * avg_loss)
  max_drawdown  — worst peak-to-trough equity drawdown
  total_return  — compound return over the period
  sharpe_ratio  — annualised Sharpe (risk-free = 0)
  calmar_ratio  — annualised_return / max_drawdown
  avg_mae       — average max adverse excursion per trade
  avg_mfe       — average max favourable excursion per trade
  n_trades      — total trades in the period

Usage::
    pip install ccxt
    python scripts/backtest.py [--force-refresh]

Results are printed to stdout and saved to docs/paper_trading_results_honest.md.
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backtest")

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data" / "historical"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DOCS_DIR = REPO_ROOT / "docs"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

PERIODS_PER_YEAR = 365  # daily bars


# ---------------------------------------------------------------------------
# Test periods (name, start, end)
# ---------------------------------------------------------------------------

PERIODS = [
    ("bull", "2023-10-01", "2024-03-31"),  # BTC 26k → 73k
    ("bear", "2022-05-01", "2022-11-30"),  # BTC 38k → 16k
    ("sideways", "2024-07-01", "2024-10-31"),  # BTC 55k-65k chop
]

SYMBOLS = [
    ("BTC/USDT", "BTCUSDT"),
    ("ETH/USDT", "ETHUSDT"),
    ("SOL/USDT", "SOLUSDT"),
]

COMMISSION = 0.001  # 0.1% Binance spot fee per side


# ---------------------------------------------------------------------------
# Data download & caching
# ---------------------------------------------------------------------------


@dataclass
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def _fetch_binance(symbol: str, start: str, end: str) -> list[Bar]:
    """Download daily OHLCV from Binance public REST for a specific date range."""
    try:
        import ccxt
    except ImportError as exc:
        raise RuntimeError("ccxt not installed. Run: pip install ccxt") from exc

    exchange = ccxt.binance({"enableRateLimit": True})
    start_dt = datetime.fromisoformat(start).replace(tzinfo=UTC)
    end_dt = datetime.fromisoformat(end).replace(tzinfo=UTC)
    since_ms = int(start_dt.timestamp() * 1000)

    days = (end_dt - start_dt).days + 5  # small buffer
    logger.info("Fetching %s  %s → %s  (%d bars)...", symbol, start, end, days)

    raw = exchange.fetch_ohlcv(symbol, timeframe="1d", since=since_ms, limit=days)
    bars: list[Bar] = []
    for row in raw:
        bar_date = datetime.fromtimestamp(row[0] / 1000, tz=UTC).date().isoformat()
        if bar_date < start or bar_date > end:
            continue
        bars.append(
            Bar(
                date=bar_date,
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
        )
    bars.sort(key=lambda b: b.date)
    logger.info("  Got %d bars for %s (%s → %s)", len(bars), symbol, start, end)
    return bars


def _cache_path(symbol_safe: str, start: str, end: str) -> Path:
    return DATA_DIR / f"{symbol_safe}_{start}_{end}_daily.csv"


def _save_csv(bars: list[Bar], path: Path) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "open", "high", "low", "close", "volume"])
        for b in bars:
            writer.writerow([b.date, b.open, b.high, b.low, b.close, b.volume])


def _load_csv(path: Path) -> list[Bar]:
    bars = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(
                Bar(
                    date=row["date"],
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
    return bars


def get_bars(symbol: str, start: str, end: str, force_refresh: bool = False) -> list[Bar]:
    safe = symbol.replace("/", "_").lower()
    path = _cache_path(safe, start, end)
    if path.exists() and not force_refresh:
        logger.info("Cache hit: %s", path.name)
        return _load_csv(path)
    bars = _fetch_binance(symbol, start, end)
    if bars:
        _save_csv(bars, path)
    return bars


# ---------------------------------------------------------------------------
# Strategy: SMA(10/30) crossover gated by RSI < 70
# ---------------------------------------------------------------------------


def _sma(prices: list[float], window: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(prices)):
        if i < window - 1:
            out.append(None)
        else:
            out.append(sum(prices[i - window + 1 : i + 1]) / window)
    return out


def _rsi(prices: list[float], window: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * window
    gains, losses = [], []
    for i in range(1, window + 1):
        d = prices[i] - prices[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains) / window
    avg_l = sum(losses) / window
    for i in range(window, len(prices)):
        d = prices[i] - prices[i - 1]
        avg_g = (avg_g * (window - 1) + max(d, 0.0)) / window
        avg_l = (avg_l * (window - 1) + max(-d, 0.0)) / window
        out.append(100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l))
    return out


@dataclass
class TradeResult:
    symbol: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    pnl_pct: float  # net of commission
    mae: float  # max adverse excursion (worst intra-trade return)
    mfe: float  # max favourable excursion (best intra-trade return)
    duration_days: int


def run_strategy(symbol: str, bars: list[Bar]) -> tuple[list[TradeResult], list[float]]:
    """
    SMA(10/30) crossover gated by RSI < 70.  Long-only.

    Entry at next bar open after signal, exit at next bar open after death cross.
    Tracks MAE and MFE for every trade using the high/low within the holding period.
    """
    closes = [b.close for b in bars]
    sma_s = _sma(closes, 10)
    sma_l = _sma(closes, 30)
    rsi_v = _rsi(closes, 14)

    trades: list[TradeResult] = []
    daily_rets: list[float] = []

    position = False
    entry_price = 0.0
    entry_date = ""
    entry_idx = 0
    mae = 0.0
    mfe = 0.0

    for i in range(1, len(bars)):
        if sma_s[i] is None or sma_l[i] is None or rsi_v[i] is None:
            if position:
                ret = (bars[i].close - bars[i - 1].close) / bars[i - 1].close
                daily_rets.append(ret)
                mae = min(mae, (bars[i].low - entry_price) / entry_price)
                mfe = max(mfe, (bars[i].high - entry_price) / entry_price)
            else:
                daily_rets.append(0.0)
            continue

        prev_s = sma_s[i - 1]
        prev_l = sma_l[i - 1]
        cur_s: float = sma_s[i]  # type: ignore[assignment]
        cur_l: float = sma_l[i]  # type: ignore[assignment]

        if prev_s is None or prev_l is None:
            daily_rets.append(0.0)
            continue

        rsi_ok = float(rsi_v[i]) < 70.0  # type: ignore[arg-type]

        if not position:
            # Golden cross + RSI filter -> enter on next bar open
            if prev_s <= prev_l and cur_s > cur_l and rsi_ok and i + 1 < len(bars):
                position = True
                entry_price = bars[i + 1].open
                entry_date = bars[i + 1].date
                entry_idx = i + 1
                mae = 0.0
                mfe = 0.0
            daily_rets.append(0.0)
        else:
            # Track intra-trade high/low for MAE/MFE
            mae = min(mae, (bars[i].low - entry_price) / entry_price)
            mfe = max(mfe, (bars[i].high - entry_price) / entry_price)

            # Death cross → exit on next bar open
            if prev_s >= prev_l and cur_s < cur_l:
                exit_price = bars[i + 1].open if i + 1 < len(bars) else bars[i].close
                exit_date = bars[i + 1].date if i + 1 < len(bars) else bars[i].date
                pnl = (exit_price - entry_price) / entry_price - 2 * COMMISSION
                trades.append(
                    TradeResult(
                        symbol=symbol,
                        entry_date=entry_date,
                        exit_date=exit_date,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        pnl_pct=pnl,
                        mae=mae,
                        mfe=mfe,
                        duration_days=i - entry_idx,
                    )
                )
                position = False
                daily_rets.append(
                    (exit_price - bars[i].close) / bars[i].close
                    if exit_price != bars[i].close
                    else 0.0
                )
                continue

            daily_rets.append((closes[i] - closes[i - 1]) / closes[i - 1])

    return trades, daily_rets


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------


@dataclass
class PeriodMetrics:
    period: str
    symbol: str
    n_trades: int
    win_rate: float
    profit_factor: float
    expectancy_pct: float
    total_return_pct: float
    annualised_return_pct: float
    sharpe: float
    max_drawdown_pct: float
    calmar_ratio: float
    avg_mae_pct: float
    avg_mfe_pct: float
    max_mae_pct: float
    recovery_factor: float  # net_profit / max_drawdown
    pct_time_in_drawdown: float
    bnh_return_pct: float  # buy-and-hold baseline for the same period


def compute_metrics(
    period: str,
    symbol: str,
    bars: list[Bar],
    trades: list[TradeResult],
    daily_rets: list[float],
) -> PeriodMetrics:
    n = len(trades)
    closes = [b.close for b in bars]
    days = len(bars)

    # Buy-and-hold baseline
    bnh_ret = (closes[-1] - closes[0]) / closes[0] if closes else 0.0

    if n == 0:
        return PeriodMetrics(
            period=period,
            symbol=symbol,
            n_trades=0,
            win_rate=0.0,
            profit_factor=0.0,
            expectancy_pct=0.0,
            total_return_pct=0.0,
            annualised_return_pct=0.0,
            sharpe=0.0,
            max_drawdown_pct=0.0,
            calmar_ratio=0.0,
            avg_mae_pct=0.0,
            avg_mfe_pct=0.0,
            max_mae_pct=0.0,
            recovery_factor=0.0,
            pct_time_in_drawdown=0.0,
            bnh_return_pct=round(bnh_ret * 100, 2),
        )

    pnls = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    win_rate = len(wins) / n
    profit_factor = sum(wins) / abs(sum(losses)) if losses else float("inf") if wins else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    loss_rate = 1.0 - win_rate
    expectancy = (win_rate * avg_win) + (loss_rate * avg_loss)

    # Equity curve from daily returns
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    in_dd_days = 0
    for r in daily_rets:
        equity *= 1.0 + r
        if equity > peak:
            peak = equity
        else:
            in_dd_days += 1
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd

    total_ret = equity - 1.0
    ann_ret = (equity ** (PERIODS_PER_YEAR / max(days, 1))) - 1.0
    calmar = ann_ret / max_dd if max_dd > 0 else 0.0
    recovery = total_ret / max_dd if max_dd > 0 else 0.0
    pct_in_dd = in_dd_days / max(len(daily_rets), 1)

    # Sharpe
    if len(daily_rets) > 1:
        mean_r = sum(daily_rets) / len(daily_rets)
        var = sum((r - mean_r) ** 2 for r in daily_rets) / (len(daily_rets) - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        sharpe = (mean_r / std * math.sqrt(PERIODS_PER_YEAR)) if std > 0 else 0.0
    else:
        sharpe = 0.0

    # MAE / MFE
    maes = [t.mae * 100 for t in trades]
    mfes = [t.mfe * 100 for t in trades]

    return PeriodMetrics(
        period=period,
        symbol=symbol,
        n_trades=n,
        win_rate=round(win_rate, 4),
        profit_factor=round(profit_factor, 4) if profit_factor != float("inf") else 999.0,
        expectancy_pct=round(expectancy * 100, 4),
        total_return_pct=round(total_ret * 100, 2),
        annualised_return_pct=round(ann_ret * 100, 2),
        sharpe=round(sharpe, 4),
        max_drawdown_pct=round(max_dd * 100, 2),
        calmar_ratio=round(calmar, 4),
        avg_mae_pct=round(sum(maes) / n, 2),
        avg_mfe_pct=round(sum(mfes) / n, 2),
        max_mae_pct=round(min(maes), 2),
        recovery_factor=round(recovery, 4),
        pct_time_in_drawdown=round(pct_in_dd * 100, 1),
        bnh_return_pct=round(bnh_ret * 100, 2),
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


_VERDICT = {
    "bull": "Expected to see positive returns — bulls should be kind to trend-followers.",
    "bear": "Expected losses if long-only — tells us if strategy knows when to stay flat.",
    "sideways": "Chop eats trend strategies — expected low win rate and negative expectancy.",
}


def _pf_str(pf: float) -> str:
    if pf >= 999.0:
        return "∞ (no losses)"
    return f"{pf:.3f}"


def print_report(all_metrics: list[PeriodMetrics]) -> str:
    """Print and return the full report as a markdown string."""
    sep = "=" * 72
    lines: list[str] = []

    def ln(s: str = "") -> None:
        lines.append(s)
        print(s)

    ln()
    ln(sep)
    ln("  OMEGA HONEST BACKTEST — Multi-Period, Multi-Asset")
    ln("  Strategy: SMA(10/30) + RSI<70 gate, long-only, 0.2% round-trip cost")
    ln(sep)
    ln("  Periods: bull (Oct 2023-Mar 2024) | bear (May-Nov 2022) | sideways (Jul-Oct 2024)")
    ln("  Assets:  BTC/USDT | ETH/USDT | SOL/USDT")
    ln(sep)

    by_period: dict[str, list[PeriodMetrics]] = {}
    for m in all_metrics:
        by_period.setdefault(m.period, []).append(m)

    for period, mlist in by_period.items():
        ln()
        ln(f"  ── {period.upper()} PERIOD ──")
        ln(f"  {_VERDICT.get(period, '')}")
        ln()
        header = f"  {'Symbol':<12} {'Trades':>6}  {'WinRate':>7}  {'PF':>6}  {'Expect%':>8}  {'TotRet%':>8}  {'Sharpe':>7}  {'MaxDD%':>7}  {'Calmar':>7}  {'AvgMAE%':>8}  {'AvgMFE%':>8}  {'BnH%':>8}"
        ln(header)
        ln("  " + "-" * 108)
        for m in mlist:
            ln(
                f"  {m.symbol:<12} {m.n_trades:>6}  {m.win_rate * 100:>6.1f}%  "
                f"{_pf_str(m.profit_factor):>6}  {m.expectancy_pct:>+8.3f}  "
                f"{m.total_return_pct:>+8.2f}  {m.sharpe:>+7.3f}  "
                f"{m.max_drawdown_pct:>7.2f}  {m.calmar_ratio:>+7.3f}  "
                f"{m.avg_mae_pct:>+8.2f}  {m.avg_mfe_pct:>+8.2f}  "
                f"{m.bnh_return_pct:>+8.2f}"
            )

        # Period summary across assets
        valid = [m for m in mlist if m.n_trades > 0]
        if valid:
            avg_wr = sum(m.win_rate for m in valid) / len(valid)
            avg_pf = sum(m.profit_factor for m in valid) / len(valid)
            avg_exp = sum(m.expectancy_pct for m in valid) / len(valid)
            avg_sharpe = sum(m.sharpe for m in valid) / len(valid)
            ln()
            ln(
                f"  Average across {len(valid)} assets: win_rate={avg_wr * 100:.1f}%  profit_factor={avg_pf:.3f}  expectancy={avg_exp:+.3f}%  sharpe={avg_sharpe:+.3f}"
            )

    ln()
    ln(sep)
    ln()
    ln("  VERDICT")
    ln("  -------")

    # Aggregate verdict
    bull_metrics = [m for m in all_metrics if m.period == "bull" and m.n_trades > 0]
    bear_metrics = [m for m in all_metrics if m.period == "bear" and m.n_trades > 0]
    side_metrics = [m for m in all_metrics if m.period == "sideways" and m.n_trades > 0]

    def _period_avg_wr(ms: list[PeriodMetrics]) -> float:
        return sum(m.win_rate for m in ms) / len(ms) if ms else 0.0

    def _period_avg_exp(ms: list[PeriodMetrics]) -> float:
        return sum(m.expectancy_pct for m in ms) / len(ms) if ms else 0.0

    def _period_avg_pf(ms: list[PeriodMetrics]) -> float:
        return sum(m.profit_factor for m in ms) / len(ms) if ms else 0.0

    b_wr = _period_avg_wr(bull_metrics)
    br_wr = _period_avg_wr(bear_metrics)
    s_wr = _period_avg_wr(side_metrics)

    ln(
        f"  Bull  win rate: {b_wr * 100:.1f}%  profit_factor: {_period_avg_pf(bull_metrics):.3f}  expectancy: {_period_avg_exp(bull_metrics):+.3f}%"
    )
    ln(
        f"  Bear  win rate: {br_wr * 100:.1f}%  profit_factor: {_period_avg_pf(bear_metrics):.3f}  expectancy: {_period_avg_exp(bear_metrics):+.3f}%"
    )
    ln(
        f"  Side  win rate: {s_wr * 100:.1f}%  profit_factor: {_period_avg_pf(side_metrics):.3f}  expectancy: {_period_avg_exp(side_metrics):+.3f}%"
    )
    ln()

    if all(
        _period_avg_pf(m_list) > 1.5 and _period_avg_exp(m_list) > 0
        for m_list in [bull_metrics, bear_metrics, side_metrics]
        if m_list
    ):
        ln("  OVERALL: Genuine edge. PF > 1.5 and positive expectancy in ALL regimes.")
    elif _period_avg_pf(bull_metrics) > 1.5 and _period_avg_exp(bull_metrics) > 0:
        if _period_avg_exp(bear_metrics) < 0:
            ln("  OVERALL: Edge is regime-dependent. Works in bull, loses in bear.")
            ln("           Add regime detection or short-side filter before live trading.")
        else:
            ln("  OVERALL: Marginal edge. Positive expectancy in bull, unclear elsewhere.")
    else:
        ln("  OVERALL: No consistent edge. Expectancy <= 0 across regimes.")
        ln("           More signal work needed before live trading is justified.")

    ln()
    ln("  NOTE: Results use production SMA(10/30)+RSI strategy with real Binance")
    ln("        historical data. 0.2% round-trip commission applied. Long-only.")
    ln(sep)

    return "\n".join(lines)


def save_markdown(report: str) -> Path:
    """Save the report to docs/paper_trading_results_honest.md."""
    out = DOCS_DIR / "paper_trading_results_honest.md"
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    with open(out, "w") as f:
        f.write("# Paper Trading - Honest Backtest Results\n\n")
        f.write(f"Generated: {ts}\n\n")
        f.write("```\n")
        f.write(report)
        f.write("\n```\n")
    logger.info("Saved report → %s", out)
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(force_refresh: bool = False) -> int:
    all_metrics: list[PeriodMetrics] = []
    errors: list[str] = []

    for period_name, start, end in PERIODS:
        logger.info("")
        logger.info("=== PERIOD: %s  (%s → %s) ===", period_name.upper(), start, end)
        for symbol, _ticker in SYMBOLS:
            try:
                bars = get_bars(symbol, start, end, force_refresh=force_refresh)
                if len(bars) < 35:  # need at least SMA-30 window + a few trades
                    logger.warning(
                        "Too few bars (%d) for %s %s — skipping", len(bars), symbol, period_name
                    )
                    continue
                trades, daily_rets = run_strategy(symbol, bars)
                m = compute_metrics(period_name, symbol, bars, trades, daily_rets)
                all_metrics.append(m)
                logger.info(
                    "  %s %s: %d trades  win_rate=%.1f%%  PF=%.3f  expect=%.3f%%  ret=%.2f%%",
                    period_name,
                    symbol,
                    m.n_trades,
                    m.win_rate * 100,
                    m.profit_factor,
                    m.expectancy_pct,
                    m.total_return_pct,
                )
            except Exception as exc:
                msg = f"{period_name}/{symbol}: {exc}"
                logger.error("FAILED: %s", msg, exc_info=True)
                errors.append(msg)

    if not all_metrics:
        print("\nNo results produced.")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1

    report = print_report(all_metrics)
    out_path = save_markdown(report)
    print(f"\nReport saved: {out_path}")

    if errors:
        print(f"\nPartial failures ({len(errors)}):")
        for e in errors:
            print(f"  {e}")

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Honest multi-period backtest")
    parser.add_argument("--force-refresh", action="store_true", help="Re-download all OHLCV data")
    args = parser.parse_args()
    sys.exit(main(force_refresh=args.force_refresh))
