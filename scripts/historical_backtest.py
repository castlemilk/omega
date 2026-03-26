#!/usr/bin/env python3
"""
scripts/historical_backtest.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Historical backtest harness — replays real Binance OHLCV data across three
distinct market regimes with walk-forward validation, per-signal IC attribution,
and comprehensive performance metrics.

Regimes:
  BULL     : 2023-10-01 -> 2024-03-15  (BTC $26K -> $73K)
  BEAR     : 2022-05-01 -> 2022-11-15  (BTC $38K -> $16K)
  SIDEWAYS : 2024-07-01 -> 2024-10-15  (BTC $55K-$70K)

Walk-forward: train on first 60%, evaluate metrics on last 40%.

Usage:
  python scripts/historical_backtest.py

Dependencies: stdlib only (no numpy/pandas/requests required).
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data" / "historical"
DOCS_DIR = ROOT / "docs"
RESULTS_MD = DOCS_DIR / "historical_backtest_results.md"
TRADES_CSV = DOCS_DIR / "historical_backtest_trades.csv"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

REGIMES: dict[str, tuple[str, str]] = {
    "BULL": ("2023-10-01", "2024-03-15"),
    "BEAR": ("2022-05-01", "2022-11-15"),
    "SIDEWAYS": ("2024-07-01", "2024-10-15"),
}

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
TRAIN_FRAC = 0.60
LONG_THRESH = 0.15  # enter long when combined score > threshold
SHORT_THRESH = -0.15  # enter short when combined score < threshold

SIGNAL_NAMES = [
    "sma_cross",
    "rsi",
    "macd",
    "bb_pct",
    "momentum_20",
    "momentum_60",
    "vol_regime",
]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Candle:
    symbol: str
    date: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Trade:
    symbol: str
    direction: str  # "long" | "short"
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    pnl_pct: float  # decimal (0.05 = 5%)
    duration_days: int
    mae_pct: float  # max adverse excursion (negative = loss, as decimal)
    mfe_pct: float  # max favorable excursion (positive = gain, as decimal)


@dataclass
class SymbolResult:
    """Per-symbol metrics over the test period."""

    symbol: str
    sharpe: float
    sortino: float
    max_drawdown_pct: float
    total_return_pct: float
    trades: list[Trade] = field(default_factory=list)
    daily_returns: list[float] = field(default_factory=list)


@dataclass
class PeriodResult:
    regime: str
    start_date: str
    end_date: str
    train_end_date: str
    # Aggregate performance (averaged or pooled across symbols)
    total_return_pct: float
    annualised_return_pct: float
    sharpe: float
    sortino: float
    max_drawdown_pct: float
    calmar: float
    profit_factor: float
    win_rate: float
    long_win_rate: float
    short_win_rate: float
    total_trades: int
    avg_duration_days: float
    avg_mae_pct: float
    avg_mfe_pct: float
    # Signal attribution (IC on test period, averaged across symbols)
    signal_ic: dict[str, float] = field(default_factory=dict)
    # Training-period IC (used to derive signal weights)
    train_ic: dict[str, float] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 1. Data download & CSV caching
# ---------------------------------------------------------------------------


def _dt_to_ms(date_str: str) -> int:
    """Convert YYYY-MM-DD to Binance millisecond timestamp (UTC midnight)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def download_candles(symbol: str, start: str, end: str) -> list[Candle]:
    """
    Return daily OHLCV candles for *symbol* between *start* and *end* (inclusive).
    Results are cached to DATA_DIR/<symbol>_<start>_<end>.csv.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = DATA_DIR / f"{symbol}_{start}_{end}.csv"

    if cache.exists():
        bars = _load_csv(symbol, cache)
        print(f"  {symbol}: {len(bars)} candles (cached)")
        return bars

    print(f"  {symbol}: downloading {start} → {end} …", end=" ", flush=True)
    bars = _fetch_binance(symbol, start, end)
    _save_csv(bars, cache)
    print(f"{len(bars)} candles → {cache.name}")
    return bars


def _fetch_binance(symbol: str, start: str, end: str) -> list[Candle]:
    """Paginate Binance /api/v3/klines (1000 rows per page)."""
    start_ms = _dt_to_ms(start)
    end_ms = _dt_to_ms(end)
    raw: list[Candle] = []

    while start_ms < end_ms:
        params = urllib.parse.urlencode(
            {
                "symbol": symbol,
                "interval": "1d",
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 1000,
            }
        )
        url = f"{BINANCE_KLINES_URL}?{params}"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                rows = json.loads(resp.read())
        except Exception as exc:
            raise RuntimeError(f"Binance fetch failed for {symbol}: {exc}") from exc

        if not rows:
            break

        for row in rows:
            # Binance kline: [open_time, open, high, low, close, volume, close_time, ...]
            dt = datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC)
            raw.append(
                Candle(
                    symbol=symbol,
                    date=dt.strftime("%Y-%m-%d"),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            )

        last_close_ms = int(rows[-1][6])
        start_ms = last_close_ms + 1
        if len(rows) < 1000:
            break
        time.sleep(0.1)

    # Deduplicate & sort
    seen: set[str] = set()
    candles: list[Candle] = []
    for c in sorted(raw, key=lambda x: x.date):
        if c.date not in seen:
            seen.add(c.date)
            candles.append(c)
    return candles


def _save_csv(candles: list[Candle], path: Path) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for c in candles:
            w.writerow([c.date, c.open, c.high, c.low, c.close, c.volume])


def _load_csv(symbol: str, path: Path) -> list[Candle]:
    candles: list[Candle] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            candles.append(
                Candle(
                    symbol=symbol,
                    date=row["date"],
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
    return candles


# ---------------------------------------------------------------------------
# 2. Signal library (pure OHLCV, zero look-ahead)
# ---------------------------------------------------------------------------


def _sma(values: list[float], n: int) -> list[float | None]:
    result: list[float | None] = [None] * (n - 1)
    for i in range(n - 1, len(values)):
        result.append(sum(values[i - n + 1 : i + 1]) / n)
    return result


def _ema(values: list[float], n: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (n + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mu = sum(values) / len(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / len(values))


def signal_sma_cross(bars: list[Candle]) -> list[float | None]:
    """
    SMA(10)/SMA(30) difference, normalized by price.
    Positive → fast above slow (bullish), negative → fast below slow (bearish).
    """
    closes = [b.close for b in bars]
    s10 = _sma(closes, 10)
    s30 = _sma(closes, 30)
    result: list[float | None] = []
    for i, c in enumerate(closes):
        if s10[i] is None or s30[i] is None or c == 0:
            result.append(None)
        else:
            result.append((s10[i] - s30[i]) / c)  # type: ignore[operator]
    return result


def signal_rsi(bars: list[Candle], period: int = 14) -> list[float | None]:
    """
    RSI(14) mapped to [-1, +1].  Oversold (<30) → +1 bull, overbought (>70) → -1 bear.
    """
    closes = [b.close for b in bars]
    if len(closes) <= period:
        return [None] * len(closes)

    result: list[float | None] = [None] * period
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, period + 1)]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, period + 1)]
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period

    for i in range(period, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
        rsi = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
        # Invert: oversold = buy signal
        result.append(max(-1.0, min(1.0, -(rsi - 50.0) / 50.0)))

    return result


def signal_macd(
    bars: list[Candle], fast: int = 12, slow: int = 26, sig_p: int = 9
) -> list[float | None]:
    """
    MACD histogram (MACD line - signal line), normalized by price.
    Positive histogram = bullish momentum.
    """
    closes = [b.close for b in bars]
    min_len = slow + sig_p
    if len(closes) < min_len:
        return [None] * len(closes)

    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow, strict=False)]
    # Signal line starts at index slow-1
    sig_input = macd_line[slow - 1 :]
    sig_line = _ema(sig_input, sig_p)

    pad = slow - 1 + sig_p - 1
    result: list[float | None] = [None] * pad
    for j, sv in enumerate(sig_line):
        idx = slow - 1 + j
        if idx >= len(macd_line):
            break
        hist = macd_line[idx] - sv
        p = closes[min(pad + j, len(closes) - 1)]
        result.append(hist / p if p != 0 else 0.0)

    while len(result) < len(bars):
        result.append(None)
    return result[: len(bars)]


def signal_bb_pct(
    bars: list[Candle], period: int = 20, std_mult: float = 2.0
) -> list[float | None]:
    """
    Bollinger Bands %B mapped to [-1, +1].
    Above upper band → -1 (overbought/bearish), below lower band → +1 (oversold/bullish).
    """
    closes = [b.close for b in bars]
    result: list[float | None] = []
    for i, c in enumerate(closes):
        if i < period - 1:
            result.append(None)
            continue
        window = closes[i - period + 1 : i + 1]
        mid = sum(window) / period
        std = _stddev(window)
        if std == 0:
            result.append(0.0)
            continue
        pct_b = (c - (mid - std_mult * std)) / (2 * std_mult * std)
        result.append(max(-1.0, min(1.0, 1.0 - 2.0 * pct_b)))
    return result


def signal_momentum_20(bars: list[Candle]) -> list[float | None]:
    """20-day return, clipped to [-1, +1]."""
    closes = [b.close for b in bars]
    result: list[float | None] = [None] * 20
    for i in range(20, len(closes)):
        base = closes[i - 20]
        ret = (closes[i] - base) / base if base != 0 else 0.0
        result.append(max(-1.0, min(1.0, ret)))
    return result


def signal_momentum_60(bars: list[Candle]) -> list[float | None]:
    """60-day return, clipped to [-1, +1]."""
    closes = [b.close for b in bars]
    result: list[float | None] = [None] * 60
    for i in range(60, len(closes)):
        base = closes[i - 60]
        ret = (closes[i] - base) / base if base != 0 else 0.0
        result.append(max(-1.0, min(1.0, ret)))
    return result


def signal_vol_regime(bars: list[Candle]) -> list[float | None]:
    """
    Volatility regime: current 20d annualised vol vs 90d average.
    High vol → bearish signal (-), low/calm vol → bullish signal (+).
    """
    closes = [b.close for b in bars]
    rets = [0.0] + [
        (closes[i] - closes[i - 1]) / closes[i - 1] if closes[i - 1] != 0 else 0.0
        for i in range(1, len(closes))
    ]
    result: list[float | None] = [None] * 90
    for i in range(90, len(closes)):
        vol_20 = _stddev(rets[i - 20 : i]) * math.sqrt(252)
        vol_90 = _stddev(rets[i - 90 : i]) * math.sqrt(252)
        if vol_90 == 0:
            result.append(0.0)
            continue
        ratio = vol_20 / vol_90
        result.append(max(-1.0, min(1.0, (1.0 - ratio) * 0.5)))
    return result


SignalFn = Callable[[list[Candle]], list[float | None]]

SIGNAL_FUNCS: dict[str, SignalFn] = {
    "sma_cross": signal_sma_cross,
    "rsi": signal_rsi,
    "macd": signal_macd,
    "bb_pct": signal_bb_pct,
    "momentum_20": signal_momentum_20,
    "momentum_60": signal_momentum_60,
    "vol_regime": signal_vol_regime,
}


def compute_all_signals(bars: list[Candle]) -> dict[str, list[float | None]]:
    return {name: fn(bars) for name, fn in SIGNAL_FUNCS.items()}


# ---------------------------------------------------------------------------
# 3. IC attribution
# ---------------------------------------------------------------------------


def _pearson(x: list[float], y: list[float]) -> float:
    n = min(len(x), len(y))
    if n < 5:
        return 0.0
    x, y = x[:n], y[:n]
    mx, my = sum(x) / n, sum(y) / n
    num = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    dx = math.sqrt(sum((v - mx) ** 2 for v in x))
    dy = math.sqrt(sum((v - my) ** 2 for v in y))
    return num / (dx * dy) if dx * dy > 0 else 0.0


def compute_signal_ic(
    bars: list[Candle],
    signals: dict[str, list[float | None]],
    start_idx: int,
    end_idx: int,
) -> dict[str, float]:
    """
    IC = Pearson correlation between signal[t] and next-day return[t+1],
    computed over bars[start_idx : end_idx].
    """
    closes = [b.close for b in bars]
    fwd_rets: list[float] = []
    valid_idxs: list[int] = []
    for i in range(start_idx, min(end_idx, len(bars) - 1)):
        if closes[i] != 0:
            fwd_rets.append((closes[i + 1] - closes[i]) / closes[i])
            valid_idxs.append(i)

    ic: dict[str, float] = {}
    for sig_name, sig_vals in signals.items():
        sv, rv = [], []
        for j, idx in enumerate(valid_idxs):
            v = sig_vals[idx] if idx < len(sig_vals) else None
            if v is not None and not math.isnan(v):
                sv.append(v)
                rv.append(fwd_rets[j])
        ic[sig_name] = _pearson(sv, rv)
    return ic


# ---------------------------------------------------------------------------
# 4. Walk-forward meta-model
# ---------------------------------------------------------------------------


def derive_weights(train_ic: dict[str, float]) -> dict[str, float]:
    """
    Signal weights ∝ training-period IC.
    Positive IC → follow signal direction.
    Negative IC → invert signal direction.
    Weights are normalised so Σ|w| = 1.
    """
    total = sum(abs(v) for v in train_ic.values())
    if total == 0:
        n = max(len(train_ic), 1)
        return {k: 1.0 / n for k in train_ic}
    return {k: v / total for k, v in train_ic.items()}


def daily_score(
    i: int,
    signals: dict[str, list[float | None]],
    weights: dict[str, float],
) -> float | None:
    """Weighted sum of signal values at bar index *i*."""
    s = 0.0
    w_sum = 0.0
    for name, vals in signals.items():
        if i >= len(vals):
            continue
        v = vals[i]
        if v is None or math.isnan(v):
            continue
        w = weights.get(name, 0.0)
        s += w * v
        w_sum += abs(w)
    return s if w_sum > 0 else None


# ---------------------------------------------------------------------------
# 5. Paper trading engine (replay loop)
# ---------------------------------------------------------------------------


@dataclass
class _Position:
    symbol: str
    direction: str
    entry_date: str
    entry_price: float
    worst_price: float  # tracks min(low) for longs, max(high) for shorts
    best_price: float  # tracks max(high) for longs, min(low) for shorts


def run_backtest_symbol(
    symbol: str,
    bars: list[Candle],
    signals: dict[str, list[float | None]],
    weights: dict[str, float],
    start_idx: int,
    end_idx: int,
) -> tuple[list[Trade], list[float]]:
    """
    Replay bars[start_idx:end_idx] through the signal pipeline.

    Execution model:
      - Signal computed from end-of-day data at bar t (no look-ahead).
      - Entry / exit at open of bar t+1.
      - Daily equity returns computed close-to-close while in position.
      - MAE / MFE from daily high / low of intra-trade bars.
    """
    trades: list[Trade] = []
    daily_rets: list[float] = []
    pos: _Position | None = None

    for i in range(start_idx, end_idx):
        bar = bars[i]

        # --- 1. Update intra-trade extremes with today's candle ---
        if pos is not None:
            if pos.direction == "long":
                pos.worst_price = min(pos.worst_price, bar.low)
                pos.best_price = max(pos.best_price, bar.high)
            else:
                pos.worst_price = max(pos.worst_price, bar.high)
                pos.best_price = min(pos.best_price, bar.low)

        # --- 2. Daily return while in position (close-to-close) ---
        if pos is not None and i > start_idx:
            prev_c = bars[i - 1].close
            if prev_c != 0:
                dr = (bar.close - prev_c) / prev_c
                daily_rets.append(dr if pos.direction == "long" else -dr)
            else:
                daily_rets.append(0.0)
        else:
            daily_rets.append(0.0)

        # --- 3. Compute signal at end of today ---
        score = daily_score(i, signals, weights)

        # Need a next bar to act on
        if i + 1 >= end_idx:
            if pos is not None:
                _close(pos, bar.close, bar.date, trades)
                pos = None
            continue

        next_open = bars[i + 1].open
        next_date = bars[i + 1].date

        # --- 4. Exit logic ---
        if pos is not None and score is not None:
            should_exit = (pos.direction == "long" and score < 0) or (
                pos.direction == "short" and score > 0
            )
            if should_exit:
                _close(pos, next_open, next_date, trades)
                pos = None
                # Immediately re-enter if strong signal in new direction
                if score >= LONG_THRESH:
                    pos = _Position(symbol, "long", next_date, next_open, next_open, next_open)
                elif score <= SHORT_THRESH:
                    pos = _Position(symbol, "short", next_date, next_open, next_open, next_open)
                continue

        # --- 5. Entry logic (flat) ---
        if pos is None and score is not None:
            if score >= LONG_THRESH:
                pos = _Position(symbol, "long", next_date, next_open, next_open, next_open)
            elif score <= SHORT_THRESH:
                pos = _Position(symbol, "short", next_date, next_open, next_open, next_open)

    return trades, daily_rets


def _close(pos: _Position, exit_price: float, exit_date: str, trades: list[Trade]) -> None:
    if pos.direction == "long":
        pnl = (exit_price - pos.entry_price) / pos.entry_price
        mae = (pos.worst_price - pos.entry_price) / pos.entry_price  # ≤ 0
        mfe = (pos.best_price - pos.entry_price) / pos.entry_price  # ≥ 0
    else:
        pnl = (pos.entry_price - exit_price) / pos.entry_price
        mae = (pos.entry_price - pos.worst_price) / pos.entry_price  # ≤ 0
        mfe = (pos.entry_price - pos.best_price) / pos.entry_price  # ≥ 0

    entry_dt = datetime.strptime(pos.entry_date, "%Y-%m-%d")
    exit_dt = datetime.strptime(exit_date, "%Y-%m-%d")
    trades.append(
        Trade(
            symbol=pos.symbol,
            direction=pos.direction,
            entry_date=pos.entry_date,
            exit_date=exit_date,
            entry_price=round(pos.entry_price, 4),
            exit_price=round(exit_price, 4),
            pnl_pct=round(pnl, 6),
            duration_days=(exit_dt - entry_dt).days,
            mae_pct=round(mae, 6),
            mfe_pct=round(mfe, 6),
        )
    )


# ---------------------------------------------------------------------------
# 6. Metrics computation
# ---------------------------------------------------------------------------


def _sharpe(rets: list[float]) -> float:
    if len(rets) < 10:
        return 0.0
    mu = sum(rets) / len(rets)
    std = statistics.stdev(rets)
    return mu / std * math.sqrt(252) if std > 0 else 0.0


def _sortino(rets: list[float]) -> float:
    if len(rets) < 10:
        return 0.0
    mu = sum(rets) / len(rets)
    down = [r for r in rets if r < 0]
    if not down:
        return _sharpe(rets)
    ds = statistics.stdev(down) if len(down) > 1 else abs(down[0])
    return mu / ds * math.sqrt(252) if ds > 0 else 0.0


def _max_drawdown(rets: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    mdd = 0.0
    for r in rets:
        equity *= 1.0 + r
        peak = max(peak, equity)
        mdd = max(mdd, (peak - equity) / peak) if peak > 0 else mdd
    return mdd


def compute_metrics(
    regime: str,
    start_date: str,
    end_date: str,
    train_end_date: str,
    all_trades: list[Trade],
    daily_returns: list[float],
    signal_ic: dict[str, float],
    train_ic: dict[str, float],
) -> PeriodResult:
    days = (
        datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")
    ).days or 1

    # Equity & return
    equity = 1.0
    for r in daily_returns:
        equity *= 1.0 + r
    total_ret = (equity - 1.0) * 100
    ann_ret = ((equity ** (365.0 / days)) - 1.0) * 100 if equity > 0 else 0.0

    sharpe = _sharpe(daily_returns)
    sortino = _sortino(daily_returns)
    mdd = _max_drawdown(daily_returns)
    calmar = (ann_ret / 100.0) / mdd if mdd > 0 else 0.0

    # Trade stats
    n = len(all_trades)
    if n > 0:
        wins = sum(1 for t in all_trades if t.pnl_pct > 0)
        longs = [t for t in all_trades if t.direction == "long"]
        shorts = [t for t in all_trades if t.direction == "short"]
        l_wins = sum(1 for t in longs if t.pnl_pct > 0)
        s_wins = sum(1 for t in shorts if t.pnl_pct > 0)

        win_rate = wins / n
        long_wr = l_wins / len(longs) if longs else 0.0
        short_wr = s_wins / len(shorts) if shorts else 0.0

        gross_pos = sum(t.pnl_pct for t in all_trades if t.pnl_pct > 0)
        gross_neg = abs(sum(t.pnl_pct for t in all_trades if t.pnl_pct < 0))
        profit_factor = gross_pos / gross_neg if gross_neg > 0 else float("inf")

        avg_dur = sum(t.duration_days for t in all_trades) / n
        # MAE is negative; report absolute magnitude as %
        avg_mae = abs(sum(t.mae_pct for t in all_trades) / n) * 100
        avg_mfe = sum(t.mfe_pct for t in all_trades) / n * 100
    else:
        win_rate = long_wr = short_wr = 0.0
        profit_factor = 0.0
        avg_dur = avg_mae = avg_mfe = 0.0

    return PeriodResult(
        regime=regime,
        start_date=start_date,
        end_date=end_date,
        train_end_date=train_end_date,
        total_return_pct=round(total_ret, 2),
        annualised_return_pct=round(ann_ret, 2),
        sharpe=round(sharpe, 3),
        sortino=round(sortino, 3),
        max_drawdown_pct=round(mdd * 100, 2),
        calmar=round(calmar, 3),
        profit_factor=round(profit_factor if profit_factor != float("inf") else 9.99, 3),
        win_rate=round(win_rate, 3),
        long_win_rate=round(long_wr, 3),
        short_win_rate=round(short_wr, 3),
        total_trades=n,
        avg_duration_days=round(avg_dur, 1),
        avg_mae_pct=round(avg_mae, 2),
        avg_mfe_pct=round(avg_mfe, 2),
        signal_ic=signal_ic,
        train_ic=train_ic,
        trades=all_trades,
    )


# ---------------------------------------------------------------------------
# 7. Regime backtest orchestrator
# ---------------------------------------------------------------------------


def run_regime(regime: str, start_date: str, end_date: str) -> PeriodResult:
    print(f"\n{'=' * 60}")
    print(f"  REGIME: {regime}   {start_date} → {end_date}")
    print(f"{'=' * 60}")

    # Download
    all_bars: dict[str, list[Candle]] = {}
    for sym in SYMBOLS:
        all_bars[sym] = download_candles(sym, start_date, end_date)

    # Walk-forward split (use BTC as reference for date)
    ref = all_bars[SYMBOLS[0]]
    split_idx = max(1, int(len(ref) * TRAIN_FRAC))
    train_end = ref[split_idx - 1].date
    print(f"\n  Train: {start_date} → {train_end}  ({split_idx} days)")
    print(f"  Test:  {train_end} → {end_date}  ({len(ref) - split_idx} days)")

    # --- Training phase: compute IC per symbol, then average ---
    pooled_ic: dict[str, list[float]] = {s: [] for s in SIGNAL_NAMES}
    per_sym_signals: dict[str, dict[str, list[float | None]]] = {}

    for sym, bars in all_bars.items():
        sym_split = max(1, int(len(bars) * TRAIN_FRAC))
        sigs = compute_all_signals(bars)
        per_sym_signals[sym] = sigs
        ic = compute_signal_ic(bars, sigs, 0, sym_split)
        for sig, val in ic.items():
            pooled_ic[sig].append(val)

    avg_train_ic = {s: sum(vs) / len(vs) if vs else 0.0 for s, vs in pooled_ic.items()}
    weights = derive_weights(avg_train_ic)

    print("\n  Training IC:  " + "  ".join(f"{k}={v:+.3f}" for k, v in avg_train_ic.items()))
    print("  Weights:      " + "  ".join(f"{k}={v:+.3f}" for k, v in weights.items()))

    # --- Test phase: backtest + test IC ---
    all_trades: list[Trade] = []
    pooled_test_ic: dict[str, list[float]] = {s: [] for s in SIGNAL_NAMES}
    # Collect returns per symbol then average per-day later
    sym_returns: dict[str, list[float]] = {}

    print("\n  Running test period...")
    for sym, bars in all_bars.items():
        sym_split = max(1, int(len(bars) * TRAIN_FRAC))
        sigs = per_sym_signals[sym]

        test_ic = compute_signal_ic(bars, sigs, sym_split, len(bars))
        for sig, val in test_ic.items():
            pooled_test_ic[sig].append(val)

        trades, rets = run_backtest_symbol(sym, bars, sigs, weights, sym_split, len(bars))
        all_trades.extend(trades)
        sym_returns[sym] = rets
        print(f"    {sym}: {len(trades)} trades, {sum(1 for t in trades if t.pnl_pct > 0)} wins")

    # Build portfolio daily return = simple average across symbols
    max_len = max((len(v) for v in sym_returns.values()), default=0)
    portfolio_rets: list[float] = []
    for d in range(max_len):
        day_rets = [sym_returns[s][d] for s in SYMBOLS if d < len(sym_returns[s])]
        portfolio_rets.append(sum(day_rets) / len(day_rets) if day_rets else 0.0)

    avg_test_ic = {s: sum(vs) / len(vs) if vs else 0.0 for s, vs in pooled_test_ic.items()}

    return compute_metrics(
        regime=regime,
        start_date=start_date,
        end_date=end_date,
        train_end_date=train_end,
        all_trades=all_trades,
        daily_returns=portfolio_rets,
        signal_ic=avg_test_ic,
        train_ic=avg_train_ic,
    )


# ---------------------------------------------------------------------------
# 8. Output: comparison table
# ---------------------------------------------------------------------------


def print_table(results: dict[str, PeriodResult]) -> None:
    col_w = 13
    col_names = ["BULL", "BEAR", "SIDEWAYS"]

    def fmt(r: PeriodResult, fn: Callable[[PeriodResult], str]) -> str:
        return fn(r)

    rows = [
        ("Total Return %", lambda r: f"{r.total_return_pct:>+.2f}%"),
        ("Annualised %", lambda r: f"{r.annualised_return_pct:>+.2f}%"),
        ("Sharpe Ratio", lambda r: f"{r.sharpe:>+.3f}"),
        ("Sortino Ratio", lambda r: f"{r.sortino:>+.3f}"),
        ("Max Drawdown %", lambda r: f"{r.max_drawdown_pct:>.2f}%"),
        ("Calmar Ratio", lambda r: f"{r.calmar:>+.3f}"),
        ("Profit Factor", lambda r: f"{r.profit_factor:>.3f}"),
        ("Win Rate", lambda r: f"{r.win_rate:.1%}"),
        ("Long Win Rate", lambda r: f"{r.long_win_rate:.1%}"),
        ("Short Win Rate", lambda r: f"{r.short_win_rate:.1%}"),
        ("Total Trades", lambda r: f"{r.total_trades:>d}"),
        ("Avg Duration (days)", lambda r: f"{r.avg_duration_days:.1f}d"),
        ("Avg MAE %", lambda r: f"{r.avg_mae_pct:.2f}%"),
        ("Avg MFE %", lambda r: f"{r.avg_mfe_pct:.2f}%"),
    ]

    print("\n")
    print("=" * 68)
    print("  BACKTEST RESULTS - Walk-Forward Test Period (40% of data)")
    print("=" * 68)
    header = f"  {'Metric':<22}" + "".join(f"{c:>{col_w}}" for c in col_names)
    print(header)
    print("-" * 68)
    for label, fn in rows:
        line = f"  {label:<22}"
        for c in col_names:
            line += f"{fmt(results[c], fn):>{col_w}}" if c in results else f"{'N/A':>{col_w}}"
        print(line)
    print("-" * 68)

    print("\n  Signal IC Attribution (test period, mean across BTC/ETH/SOL)")
    print("-" * 68)
    sig_header = f"  {'Signal':<22}" + "".join(f"{c:>{col_w}}" for c in col_names)
    print(sig_header)
    print("-" * 68)
    for sig in SIGNAL_NAMES:
        line = f"  {sig:<22}"
        for c in col_names:
            if c in results:
                ic = results[c].signal_ic.get(sig, 0.0)
                line += f"{ic:>+{col_w}.4f}"
            else:
                line += f"{'N/A':>{col_w}}"
        print(line)
    print("=" * 68)


# ---------------------------------------------------------------------------
# 9. Output: markdown + CSV
# ---------------------------------------------------------------------------


def save_markdown(results: dict[str, PeriodResult]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    col_names = ["BULL", "BEAR", "SIDEWAYS"]

    lines: list[str] = [
        "# Historical Backtest Results",
        "",
        f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}_",
        "",
        "## Regimes Tested",
        "",
        "| Regime | Period | Description | Train End |",
        "|--------|--------|-------------|-----------|",
        "| BULL | 2023-10-01 -> 2024-03-15 | BTC $26K -> $73K (+180%) | "
        + (results["BULL"].train_end_date if "BULL" in results else "N/A")
        + " |",
        "| BEAR | 2022-05-01 -> 2022-11-15 | BTC $38K -> $16K (-58%) | "
        + (results["BEAR"].train_end_date if "BEAR" in results else "N/A")
        + " |",
        "| SIDEWAYS | 2024-07-01 -> 2024-10-15 | BTC $55K-$70K (ranging) | "
        + (results["SIDEWAYS"].train_end_date if "SIDEWAYS" in results else "N/A")
        + " |",
        "",
        "**Walk-forward**: first 60% used for meta-model training (IC-derived signal weights); "
        "last 40% used for out-of-sample evaluation.",
        "",
        "## Performance Metrics (Test Period - Out-of-Sample)",
        "",
        "| Metric | BULL | BEAR | SIDEWAYS |",
        "|--------|------|------|----------|",
    ]

    metric_rows = [
        ("Total Return %", lambda r: f"{r.total_return_pct:+.2f}%"),
        ("Annualised Return %", lambda r: f"{r.annualised_return_pct:+.2f}%"),
        ("Sharpe Ratio", lambda r: f"{r.sharpe:+.3f}"),
        ("Sortino Ratio", lambda r: f"{r.sortino:+.3f}"),
        ("Max Drawdown %", lambda r: f"{r.max_drawdown_pct:.2f}%"),
        ("Calmar Ratio", lambda r: f"{r.calmar:+.3f}"),
        ("Profit Factor", lambda r: f"{r.profit_factor:.3f}"),
        ("Win Rate", lambda r: f"{r.win_rate:.1%}"),
        ("Long Win Rate", lambda r: f"{r.long_win_rate:.1%}"),
        ("Short Win Rate", lambda r: f"{r.short_win_rate:.1%}"),
        ("Total Trades", lambda r: str(r.total_trades)),
        ("Avg Trade Duration", lambda r: f"{r.avg_duration_days:.1f} days"),
        ("Avg MAE %", lambda r: f"{r.avg_mae_pct:.2f}%"),
        ("Avg MFE %", lambda r: f"{r.avg_mfe_pct:.2f}%"),
    ]

    for label, fn in metric_rows:
        row = f"| {label} |"
        for c in col_names:
            row += f" {fn(results[c])} |" if c in results else " N/A |"
        lines.append(row)

    # Signal IC table
    lines += [
        "",
        "## Signal IC Attribution",
        "",
        "> **IC** = Pearson correlation between signal value at day _t_ and",
        "> next-day return at day _t+1_. Positive IC = signal correctly predicts direction.",
        "> Values are averaged across BTC, ETH, SOL.",
        "",
        "| Signal | BULL | BEAR | SIDEWAYS | Notes |",
        "|--------|------|------|----------|-------|",
    ]

    notes = {
        "sma_cross": "SMA(10/30) crossover - trend following",
        "rsi": "RSI(14) mean reversion - fade extremes",
        "macd": "MACD(12/26/9) momentum",
        "bb_pct": "Bollinger %B(20,2) - range fade",
        "momentum_20": "20-day price momentum",
        "momentum_60": "60-day price momentum",
        "vol_regime": "Volatility regime filter",
    }
    for sig in SIGNAL_NAMES:
        row = f"| `{sig}` |"
        for c in col_names:
            ic = results[c].signal_ic.get(sig, 0.0) if c in results else 0.0
            row += f" {ic:+.4f} |"
        row += f" {notes.get(sig, '')} |"
        lines.append(row)

    # Training weights
    lines += [
        "",
        "## Training-Period Signal Weights (Meta-Model)",
        "",
        "IC-derived weights from the first 60% of each period. These weights are",
        "then applied to generate the combined trading signal in the test period.",
        "",
        "| Signal | BULL | BEAR | SIDEWAYS |",
        "|--------|------|------|----------|",
    ]
    for sig in SIGNAL_NAMES:
        row = f"| `{sig}` |"
        for c in col_names:
            if c in results:
                w = derive_weights(results[c].train_ic).get(sig, 0.0)
                row += f" {w:+.4f} |"
            else:
                row += " N/A |"
        lines.append(row)

    # Auto-generated findings
    lines += ["", "## Key Findings", ""]
    if len(results) == 3:
        best = max(results.items(), key=lambda x: x[1].sharpe)
        worst = min(results.items(), key=lambda x: x[1].sharpe)
        lines.append(f"- **Best regime**: {best[0]} (Sharpe {best[1].sharpe:+.3f})")
        lines.append(f"- **Worst regime**: {worst[0]} (Sharpe {worst[1].sharpe:+.3f})")
        for regime, result in results.items():
            if result.signal_ic:
                top = max(result.signal_ic.items(), key=lambda x: abs(x[1]))
                lines.append(f"- **{regime}** strongest signal: `{top[0]}` (IC {top[1]:+.4f})")
        lines.append(
            f"- **Total trades across all regimes**: "
            f"{sum(r.total_trades for r in results.values())}"
        )

    lines += [
        "",
        "## Methodology",
        "",
        "- **Data**: Binance public API, daily OHLCV (BTC, ETH, SOL), cached to `data/historical/`",
        "- **Signals**: SMA crossover, RSI, MACD, Bollinger Bands, 20d/60d momentum, vol regime",
        "- **Meta-model**: IC-weighted signal combination (weights derived from training period)",
        "- **Entry**: next bar's open when score >= 0.15 (long) or <= -0.15 (short)",
        "- **Exit**: next bar's open when combined score crosses zero",
        "- **MAE**: max adverse excursion from daily low/high; **MFE**: max favorable",
        "- **Sharpe/Sortino**: annualised (x sqrt(252)). Portfolio = equal-weight average of BTC+ETH+SOL",
        "- **No look-ahead bias**: signals use only close-of-day data; execute at next-day open",
    ]

    RESULTS_MD.write_text("\n".join(lines) + "\n")
    print(f"\n  Saved: {RESULTS_MD}")


def save_trades_csv(results: dict[str, PeriodResult]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    with open(TRADES_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "regime",
                "symbol",
                "direction",
                "entry_date",
                "exit_date",
                "entry_price",
                "exit_price",
                "pnl_pct",
                "duration_days",
                "mae_pct",
                "mfe_pct",
            ]
        )
        for regime, result in results.items():
            for t in result.trades:
                w.writerow(
                    [
                        regime,
                        t.symbol,
                        t.direction,
                        t.entry_date,
                        t.exit_date,
                        t.entry_price,
                        t.exit_price,
                        t.pnl_pct,
                        t.duration_days,
                        t.mae_pct,
                        t.mfe_pct,
                    ]
                )
    print(f"  Saved: {TRADES_CSV}")


# ---------------------------------------------------------------------------
# 10. Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    print("Omega Historical Backtest Harness")
    print("=" * 40)
    print(f"Symbols : {', '.join(SYMBOLS)}")
    print(f"Regimes : {', '.join(REGIMES)}")
    print(f"Split   : {int(TRAIN_FRAC * 100)}% train / {int((1 - TRAIN_FRAC) * 100)}% test")

    results: dict[str, PeriodResult] = {}
    for regime, (start, end) in REGIMES.items():
        results[regime] = run_regime(regime, start, end)

    print_table(results)
    save_markdown(results)
    save_trades_csv(results)

    total_trades = sum(r.total_trades for r in results.values())
    print(f"\nComplete. {total_trades} trades recorded across all regimes.")


if __name__ == "__main__":
    main()
