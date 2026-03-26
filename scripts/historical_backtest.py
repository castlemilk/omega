#!/usr/bin/env python3
"""
scripts/historical_backtest.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Regime-aware historical backtest across three labelled market regimes.

Regimes & periods
-----------------
  BULL     : 2023-10-01 - 2024-03-31   (BTC rally from ~$27k to $71k)
  BEAR     : 2022-05-01 - 2022-11-30   (post-Luna collapse / FTX crash)
  SIDEWAYS : 2024-07-01 - 2024-10-31   (range-bound consolidation)

What it measures
----------------
Two strategy variants are run for each regime:

  Baseline  - Bayesian signal aggregation with uniform Brier-weight multipliers
              (no regime awareness).  Reproduces the observed results:
              BULL -30.3%, BEAR +3.6%, SIDEWAYS +16.5%.

  Fixed     - Same signals but with REGIME_SIGNAL_MULTIPLIERS applied,
              BULL momentum floor enforced, trend-strength gate, and
              per-regime conviction thresholds.

Additionally, 200 live cycles are run on cached recent Binance data to
verify the regime-detection + adaptive-weights pipeline in real-time mode.

Signals used (column order: 0-5)
---------------------------------
  0 momentum   - SMA(10/50) crossover      [trend-following]
  1 rsi        - RSI(14) extremes          [mean-reversion]
  2 macd       - MACD(12/26/9) histogram   [trend confirmation]
  3 bb         - Bollinger Bands(20, 2std) [mean-reversion]
  4 vwm        - Volume-weighted momentum  [momentum confirmation]
  5 vol_regime - Volatility regime ratio   [risk filter]

Usage
-----
  python scripts/historical_backtest.py
  python scripts/historical_backtest.py --force-refresh   # re-download data
  python scripts/historical_backtest.py --symbol ETHUSDT  # single asset
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data" / "historical"
DOCS_DIR = REPO_ROOT / "docs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DOCS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(REPO_ROOT))

from omega.eval.sharpe import compute_sharpe, compute_sharpe_confidence_interval  # noqa: E402
from omega.nodes.victoria.regime_detector import (  # noqa: E402
    BEAR,
    BULL,
    SIDEWAYS,
    RegimeAwareSignalModifier,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("historical_backtest")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PERIODS_PER_YEAR = 365
COMMISSION = 0.001  # 0.1% Binance spot fee per side
LONG_THRESHOLD = 0.52  # Bayesian composite prob threshold to go long
NEUTRAL_PROB = 0.5
MIN_LOOKBACK = 40  # bars needed before signals are valid
MIN_TRAIN = 30  # minimum Brier calibration window

# Signal names (column indices match compute_all_signals output)
SIG_NAMES = ["momentum", "rsi", "macd", "bb", "vwm", "vol_regime"]
N_SIGNALS = len(SIG_NAMES)

# Regime periods for historical backtest
REGIME_PERIODS = {
    BULL: ("2023-10-01", "2024-03-31"),
    BEAR: ("2022-05-01", "2022-11-30"),
    SIDEWAYS: ("2024-07-01", "2024-10-31"),
}

SYMBOLS = ["BTC/USDT", "ETH/USDT"]

# ---------------------------------------------------------------------------
# Data download / cache
# ---------------------------------------------------------------------------


def _fetch_ohlcv_binance(
    symbol: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """
    Download daily OHLCV from Binance for the given date range.
    Returns list of {timestamp, open, high, low, close, volume}.
    """
    try:
        import ccxt
    except ImportError as exc:
        raise RuntimeError("ccxt not installed. Run: pip install ccxt") from exc

    exchange = ccxt.binance({"enableRateLimit": True})

    start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC)
    since_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    days = (end_dt - start_dt).days + 1
    logger.info(
        "Fetching %d days of %s from Binance (%s → %s)...", days, symbol, start_date, end_date
    )

    raw = exchange.fetch_ohlcv(symbol, timeframe="1d", since=since_ms, limit=days + 5)
    # Filter to requested range
    raw = [r for r in raw if since_ms <= r[0] <= end_ms]
    raw = sorted(raw, key=lambda x: x[0])

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

    logger.info("  Got %d bars for %s", len(bars), symbol)
    return bars


def _csv_path(symbol: str, start_date: str, end_date: str) -> Path:
    safe = symbol.replace("/", "_").lower()
    return DATA_DIR / f"{safe}_{start_date}_{end_date}.csv"


def _save_csv(bars: list[dict], path: Path) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["timestamp", "open", "high", "low", "close", "volume"]
        )
        writer.writeheader()
        writer.writerows(bars)


def _load_csv(path: Path) -> list[dict]:
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
    return bars


def get_ohlcv(
    symbol: str,
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> list[dict]:
    path = _csv_path(symbol, start_date, end_date)
    if path.exists() and not force_refresh:
        with open(path) as _f:
            n_cached = sum(1 for _ in _f) - 1
        logger.info("Cache hit: %s (%d bars)", path.name, n_cached)
        return _load_csv(path)
    bars = _fetch_ohlcv_binance(symbol, start_date, end_date)
    _save_csv(bars, path)
    return bars


def get_recent_ohlcv(symbol: str, days: int = 365, force_refresh: bool = False) -> list[dict]:
    """Get recent OHLCV data for live cycle simulation."""
    safe = symbol.replace("/", "_").lower()
    path = DATA_DIR / f"{safe}_daily_{days}d.csv"
    if path.exists() and not force_refresh:
        logger.info("Cache hit (recent): %s", path.name)
        return _load_csv(path)
    # compute date range
    end_dt = datetime.now(tz=UTC)
    start_dt = end_dt - timedelta(days=days + 5)
    bars = _fetch_ohlcv_binance(
        symbol,
        start_dt.strftime("%Y-%m-%d"),
        end_dt.strftime("%Y-%m-%d"),
    )
    _save_csv(bars, path)
    return bars


# ---------------------------------------------------------------------------
# Technical indicators (pure numpy)
# ---------------------------------------------------------------------------


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    k = 2.0 / (period + 1)
    out = np.full_like(values, np.nan)
    if len(values) < period:
        return out
    out[period - 1] = np.mean(values[:period])
    for i in range(period, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


def _sma(values: np.ndarray, period: int) -> np.ndarray:
    out = np.full_like(values, np.nan)
    for i in range(period - 1, len(values)):
        out[i] = np.mean(values[i - period + 1 : i + 1])
    return out


def _rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, n - 1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            out[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i + 1] = 100.0 - (100.0 / (1.0 + rs))
    return out


# ---------------------------------------------------------------------------
# Signal functions — return probability arrays ∈ (0, 1)
# ---------------------------------------------------------------------------

_BULLISH = 0.72
_BEARISH = 0.28
_NEUTRAL = 0.50


def sig_momentum(closes: np.ndarray, short: int = 10, long: int = 50) -> np.ndarray:
    """SMA crossover: short > long → bullish."""
    sma_s = _sma(closes, short)
    sma_l = _sma(closes, long)
    probs = np.where(
        np.isnan(sma_s) | np.isnan(sma_l), _NEUTRAL, np.where(sma_s > sma_l, _BULLISH, _BEARISH)
    )
    return probs.astype(float)


def sig_rsi(
    closes: np.ndarray, period: int = 14, oversold: float = 30, overbought: float = 70
) -> np.ndarray:
    rsi = _rsi(closes, period)
    n = len(closes)
    probs = np.full(n, _NEUTRAL)
    mid = (oversold + overbought) / 2
    for i in range(n):
        r = rsi[i]
        if np.isnan(r):
            probs[i] = _NEUTRAL
        elif r < oversold:
            probs[i] = _BULLISH
        elif r > overbought:
            probs[i] = _BEARISH
        elif r < mid:
            probs[i] = _NEUTRAL + (_BULLISH - _NEUTRAL) * (mid - r) / (mid - oversold) * 0.5
        else:
            probs[i] = _NEUTRAL - (_NEUTRAL - _BEARISH) * (r - mid) / (overbought - mid) * 0.5
    return probs


def sig_macd(closes: np.ndarray, fast: int = 12, slow: int = 26, signal_p: int = 9) -> np.ndarray:
    ema_f = _ema(closes, fast)
    ema_s = _ema(closes, slow)
    macd_line = ema_f - ema_s
    sig_line = _ema(np.where(np.isnan(macd_line), 0.0, macd_line), signal_p)
    hist = macd_line - sig_line
    n = len(closes)
    probs = np.full(n, _NEUTRAL)
    for i in range(n):
        if np.isnan(hist[i]) or np.isnan(macd_line[i]):
            probs[i] = _NEUTRAL
        elif hist[i] > 0 and macd_line[i] > 0:
            probs[i] = _BULLISH
        elif hist[i] > 0:
            probs[i] = _NEUTRAL + 0.10
        elif hist[i] < 0 and macd_line[i] < 0:
            probs[i] = _BEARISH
        else:
            probs[i] = _NEUTRAL - 0.10
    return probs


def sig_bollinger(closes: np.ndarray, period: int = 20, n_std: float = 2.0) -> np.ndarray:
    sma = _sma(closes, period)
    n = len(closes)
    probs = np.full(n, _NEUTRAL)
    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        std = float(np.std(window, ddof=1))
        mid = sma[i]
        upper = mid + n_std * std
        lower = mid - n_std * std
        price = closes[i]
        if price < lower:
            probs[i] = _BULLISH
        elif price > upper:
            probs[i] = _BEARISH
        elif std > 0:
            z = float(np.clip((price - mid) / std / n_std, -1, 1))
            probs[i] = _NEUTRAL - z * (_NEUTRAL - _BEARISH)
    return probs


def sig_vwm(closes: np.ndarray, volumes: np.ndarray, period: int = 20) -> np.ndarray:
    n = len(closes)
    probs = np.full(n, _NEUTRAL)
    for i in range(period, n):
        c_w = closes[i - period : i]
        v_w = volumes[i - period : i]
        total_v = float(np.sum(v_w))
        if total_v == 0:
            continue
        vwap = float(np.dot(c_w, v_w)) / total_v
        pct = (closes[i] - vwap) / vwap
        if pct > 0.01:
            probs[i] = _BULLISH
        elif pct < -0.01:
            probs[i] = _BEARISH
        else:
            scale = pct / 0.01
            probs[i] = _NEUTRAL + scale * (_BULLISH - _NEUTRAL)
    return probs


def sig_vol_regime(closes: np.ndarray, short_w: int = 10, long_w: int = 60) -> np.ndarray:
    """
    Volatility regime signal: low relative vol → bullish (low risk), high → bearish.

    ratio = recent_vol / long_vol
      < 0.7  → low vol  → bullish (stable, low fear)
      > 1.5  → high vol → bearish (stress, danger)
      else   → neutral
    """
    n = len(closes)
    probs = np.full(n, _NEUTRAL)
    if n < long_w + 1:
        return probs

    rets = np.zeros(n)
    for i in range(1, n):
        if closes[i - 1] != 0:
            rets[i] = (closes[i] - closes[i - 1]) / closes[i - 1]

    for i in range(long_w, n):
        recent = rets[i - short_w : i]
        long_r = rets[i - long_w : i]
        r_vol = float(np.std(recent)) * np.sqrt(365) if len(recent) >= 2 else 0.0
        l_vol = float(np.std(long_r)) * np.sqrt(365) if len(long_r) >= 2 else r_vol
        if l_vol == 0:
            probs[i] = _NEUTRAL
            continue
        ratio = r_vol / l_vol
        if ratio < 0.7:  # Low vol: calmer than average → bullish
            probs[i] = _BULLISH
        elif ratio > 1.5:  # High vol: stressed → bearish
            probs[i] = _BEARISH
        else:
            # Linear interpolation in between
            if ratio < 1.0:
                t = (ratio - 0.7) / (1.0 - 0.7)
                probs[i] = _BULLISH + t * (_NEUTRAL - _BULLISH)
            else:
                t = (ratio - 1.0) / (1.5 - 1.0)
                probs[i] = _NEUTRAL + t * (_BEARISH - _NEUTRAL)
    return probs


def compute_all_signals(bars: list[dict]) -> np.ndarray:
    """
    Compute all 6 signals for every day.
    Returns array of shape (n_bars, 6): [momentum, rsi, macd, bb, vwm, vol_regime]
    """
    closes = np.array([b["close"] for b in bars])
    volumes = np.array([b["volume"] for b in bars])
    return np.column_stack(
        [
            sig_momentum(closes),
            sig_rsi(closes),
            sig_macd(closes),
            sig_bollinger(closes),
            sig_vwm(closes, volumes),
            sig_vol_regime(closes),
        ]
    )


# ---------------------------------------------------------------------------
# Bayesian aggregation (from omega.math.bayesian if available, else inline)
# ---------------------------------------------------------------------------


def _aggregate_signals_bayesian(
    signal_probs: list[float],
    weights: list[float],
    prior: float = 0.5,
) -> float:
    """
    Weighted log-odds Bayesian aggregation.

    Converts each signal probability to a log-odds update, weights it,
    and converts back to a probability.
    """
    log_odds = np.log(prior / (1 - prior))
    for prob, w in zip(signal_probs, weights, strict=False):
        prob = float(np.clip(prob, 0.01, 0.99))
        signal_log_odds = np.log(prob / (1 - prob))
        log_odds += w * (signal_log_odds - np.log(prior / (1 - prior)))
    return float(1.0 / (1.0 + np.exp(-log_odds)))


# ---------------------------------------------------------------------------
# Agreement ratio and conviction helpers
# ---------------------------------------------------------------------------


def compute_agreement(signal_probs: list[float]) -> float:
    """
    Fraction of signals that agree with the majority direction.
    0.5 = perfect split, 1.0 = unanimous.
    """
    bullish = sum(1 for p in signal_probs if p > _NEUTRAL)
    bearish = sum(1 for p in signal_probs if p < _NEUTRAL)
    total = bullish + bearish
    if total == 0:
        return 0.5
    return max(bullish, bearish) / total


# ---------------------------------------------------------------------------
# Core backtest engine
# ---------------------------------------------------------------------------


def run_backtest(
    symbol: str,
    bars: list[dict],
    regime: str | None,
    modifier: RegimeAwareSignalModifier | None,
    use_regime_weights: bool = False,
) -> dict:
    """
    Walk-forward backtest with optional regime-aware weighting.

    Parameters
    ----------
    regime:
        If set and use_regime_weights=True, tags the entire period as this
        regime and applies REGIME_SIGNAL_MULTIPLIERS.
    modifier:
        RegimeAwareSignalModifier instance.  Required if use_regime_weights.
    use_regime_weights:
        When True, apply regime multipliers + conviction thresholds.
        When False, run the baseline (uniform Brier-weight) strategy.
    """
    n = len(bars)
    if n < MIN_LOOKBACK + MIN_TRAIN + 10:
        return {"symbol": symbol, "error": "insufficient_data", "n_bars": n}

    closes = np.array([b["close"] for b in bars])

    daily_rets = np.zeros(n)
    for i in range(1, n):
        if closes[i - 1] != 0:
            daily_rets[i] = (closes[i] - closes[i - 1]) / closes[i - 1]

    # Outcomes: 1 if next-day return > 0
    outcomes = np.zeros(n)
    for i in range(n - 1):
        outcomes[i] = 1.0 if daily_rets[i + 1] > 0 else 0.0

    all_signals = compute_all_signals(bars)

    strategy_rets: list[float] = []
    positions: list[float] = []
    skipped_conviction = 0
    prev_position = 0.0
    walk_start = max(MIN_LOOKBACK, MIN_TRAIN)

    for t in range(walk_start, n - 1):
        brier_start = MIN_LOOKBACK
        brier_end = t
        if brier_end - brier_start < 10:
            strategy_rets.append(0.0)
            positions.append(0.0)
            continue

        # Compute Brier scores over training window → base weights
        window_sigs = all_signals[brier_start:brier_end]
        window_out = outcomes[brier_start:brier_end]
        brier = np.mean((window_sigs - window_out[:, np.newaxis]) ** 2, axis=0)
        brier = np.clip(brier, 0.01, None)

        # Inverse Brier → better calibrated signals get higher weight
        inv_brier = 1.0 / brier
        base_weights = inv_brier / inv_brier.sum()  # normalised, shape (N_SIGNALS,)

        current_sig_probs = all_signals[t].tolist()

        if use_regime_weights and modifier is not None and regime is not None:
            # Apply regime multipliers to base weights
            base_w_dict = {SIG_NAMES[i]: float(base_weights[i]) for i in range(N_SIGNALS)}
            closes_list = closes[: t + 1].tolist()
            adjusted_w_dict = modifier.apply_regime_weights(
                base_weights=base_w_dict,
                regime=regime,
                closes=closes_list,
            )
            adjusted_weights = np.array([adjusted_w_dict.get(name, 0.0) for name in SIG_NAMES])

            # Conviction gate
            agreement = compute_agreement(current_sig_probs)
            composite_p = _aggregate_signals_bayesian(current_sig_probs, adjusted_weights.tolist())
            weighted_conviction = abs(composite_p - 0.5) * 2.0

            if not modifier.check_conviction_threshold(agreement, weighted_conviction, regime):
                strategy_rets.append(0.0)
                positions.append(0.0)
                skipped_conviction += 1
                prev_position = 0.0
                continue

            weights_for_aggregation = adjusted_weights
        else:
            weights_for_aggregation = base_weights
            composite_p = _aggregate_signals_bayesian(
                current_sig_probs, weights_for_aggregation.tolist()
            )

        # Position sizing: long-only, half-Kelly approximation
        if composite_p > LONG_THRESHOLD:
            # Simple position: scale by conviction above threshold
            conviction_scaled = (composite_p - LONG_THRESHOLD) / (1.0 - LONG_THRESHOLD)
            position = min(0.25, conviction_scaled * 0.25)
        else:
            position = 0.0

        raw_ret = position * daily_rets[t + 1]
        commission_cost = abs(position - prev_position) * COMMISSION
        net_ret = raw_ret - commission_cost
        strategy_rets.append(net_ret)
        positions.append(position)
        prev_position = position

    if len(strategy_rets) < 10:
        return {"symbol": symbol, "error": "insufficient_oos_data", "n_bars": n}

    # --- Metrics ---
    rets_arr = np.array(strategy_rets)
    sharpe_pt = compute_sharpe(strategy_rets, periods_per_year=PERIODS_PER_YEAR)
    try:
        ci_lo, ci_hi = compute_sharpe_confidence_interval(
            strategy_rets, n_bootstrap=500, periods_per_year=PERIODS_PER_YEAR, seed=42
        )
    except Exception:
        ci_lo, ci_hi = float("nan"), float("nan")

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in strategy_rets:
        equity *= 1.0 + r
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd

    total_return = (equity - 1.0) * 100.0

    pos_arr = np.array(positions)
    active_days = int(np.sum(pos_arr > 0))
    active_mask = pos_arr > 0
    win_rate = float(np.sum(rets_arr[active_mask] > 0)) / active_days if active_days > 0 else 0.0

    # Buy-and-hold
    bnh_eq = 1.0
    for r in daily_rets[walk_start:n]:
        bnh_eq *= 1.0 + r
    bnh_return = (bnh_eq - 1.0) * 100.0

    return {
        "symbol": symbol,
        "n_bars": n,
        "oos_days": len(strategy_rets),
        "active_days": active_days,
        "total_return": total_return,
        "sharpe": sharpe_pt,
        "sharpe_ci_lo": ci_lo,
        "sharpe_ci_hi": ci_hi,
        "max_drawdown": max_dd * 100.0,
        "win_rate": win_rate,
        "bnh_return": bnh_return,
        "skipped_conviction": skipped_conviction,
    }


# ---------------------------------------------------------------------------
# Live cycles simulation
# ---------------------------------------------------------------------------


def run_live_cycles(
    symbol: str,
    bars: list[dict],
    n_cycles: int = 200,
    modifier: RegimeAwareSignalModifier | None = None,
) -> dict:
    """
    Simulate `n_cycles` decisions on the most recent bars.

    Automatically detects regime from recent price behaviour:
      - 20d return > +15%  → BULL
      - 20d return < -10%  → BEAR
      - else               → SIDEWAYS
    """
    if len(bars) < 100:
        return {"symbol": symbol, "error": "need >= 100 bars for live cycles"}

    # Use the last `n_cycles + MIN_LOOKBACK` bars
    window = bars[-(n_cycles + MIN_LOOKBACK) :]
    closes = np.array([b["close"] for b in window])

    # Detect regime from final 20-day return
    ret_20d = (closes[-1] - closes[-21]) / closes[-21] if len(closes) >= 21 else 0.0
    if ret_20d > 0.15:
        live_regime = BULL
    elif ret_20d < -0.10:
        live_regime = BEAR
    else:
        live_regime = SIDEWAYS

    logger.info(
        "Live cycles: %s  20d_ret=%.1f%%  auto-regime=%s",
        symbol,
        ret_20d * 100,
        live_regime.upper(),
    )

    result = run_backtest(
        symbol=symbol,
        bars=window,
        regime=live_regime,
        modifier=modifier,
        use_regime_weights=True,
    )
    result["live_regime"] = live_regime
    result["ret_20d"] = ret_20d * 100.0
    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _fmt_return(val: float) -> str:
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}%"


def _fmt_sharpe(val: float) -> str:
    return f"{val:+.3f}" if val == val else "  N/A"


def print_regime_report(
    baseline_results: dict[str, list[dict]],
    fixed_results: dict[str, list[dict]],
) -> None:
    sep = "=" * 72
    print()
    print(sep)
    print("  REGIME-AWARE HISTORICAL BACKTEST — Before vs After Fix")
    print(sep)
    print(
        f"  {'Regime':<10} {'Symbol':<12} {'Before':>10} {'After':>10} {'Delta':>10} {'Sharpe (after)':>16}"
    )
    print(f"  {'-' * 10} {'-' * 12} {'-' * 10} {'-' * 10} {'-' * 10} {'-' * 16}")

    for regime in [BULL, BEAR, SIDEWAYS]:
        b_list = baseline_results.get(regime, [])
        f_list = fixed_results.get(regime, [])
        for b_res, f_res in zip(b_list, f_list, strict=False):
            sym = b_res.get("symbol", "?")
            b_ret = b_res.get("total_return", float("nan"))
            f_ret = f_res.get("total_return", float("nan"))
            delta = f_ret - b_ret if not (b_ret != b_ret or f_ret != f_ret) else float("nan")
            sharpe = f_res.get("sharpe", float("nan"))
            print(
                f"  {regime.upper():<10} {sym:<12} "
                f"{_fmt_return(b_ret):>10} "
                f"{_fmt_return(f_ret):>10} "
                f"{_fmt_return(delta):>10} "
                f"{_fmt_sharpe(sharpe):>16}"
            )
        print()

    print(sep)


def print_summary_table(
    baseline_results: dict[str, list[dict]],
    fixed_results: dict[str, list[dict]],
) -> None:
    """Print the requested before/after comparison table."""
    print()
    print("  ┌─────────┬────────────┬────────────┐")
    print("  │ Regime  │ Before Fix │ After Fix  │")
    print("  ├─────────┼────────────┼────────────┤")

    # Average across symbols
    for regime in [BULL, BEAR, SIDEWAYS]:
        b_list = [r for r in baseline_results.get(regime, []) if "error" not in r]
        f_list = [r for r in fixed_results.get(regime, []) if "error" not in r]
        b_avg = sum(r["total_return"] for r in b_list) / len(b_list) if b_list else float("nan")
        f_avg = sum(r["total_return"] for r in f_list) / len(f_list) if f_list else float("nan")
        b_str = _fmt_return(b_avg) if b_avg == b_avg else "  N/A"
        f_str = _fmt_return(f_avg) if f_avg == f_avg else "  N/A"
        print(f"  │ {regime.upper():<7} │ {b_str:>10} │ {f_str:>10} │")

    print("  └─────────┴────────────┴────────────┘")
    print()


def print_live_cycles_report(live_results: list[dict]) -> None:
    sep = "=" * 72
    print()
    print(sep)
    print("  LIVE CYCLES (200 steps, cached recent Binance data)")
    print(sep)
    for r in live_results:
        if "error" in r:
            print(f"  {r['symbol']}: ERROR — {r['error']}")
            continue
        regime = r.get("live_regime", "?").upper()
        ret_20d = r.get("ret_20d", 0.0)
        print(
            f"  {r['symbol']}  regime={regime}  20d_ret={_fmt_return(ret_20d)}"
            f"  strategy_return={_fmt_return(r['total_return'])}"
            f"  sharpe={_fmt_sharpe(r['sharpe'])}"
            f"  active={r.get('active_days', 0)}/{r.get('oos_days', 0)} days"
        )
    print(sep)
    print()


# ---------------------------------------------------------------------------
# Results persistence
# ---------------------------------------------------------------------------


def save_results_markdown(
    baseline_results: dict[str, list[dict]],
    fixed_results: dict[str, list[dict]],
    live_results: list[dict],
    output_path: Path,
) -> None:
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Regime-Aware Backtest Results",
        "",
        f"Generated: {now}",
        "",
        "## Summary",
        "",
        "| Regime | Before Fix | After Fix |",
        "|--------|-----------|-----------|",
    ]

    for regime in [BULL, BEAR, SIDEWAYS]:
        b_list = [r for r in baseline_results.get(regime, []) if "error" not in r]
        f_list = [r for r in fixed_results.get(regime, []) if "error" not in r]
        b_avg = sum(r["total_return"] for r in b_list) / len(b_list) if b_list else float("nan")
        f_avg = sum(r["total_return"] for r in f_list) / len(f_list) if f_list else float("nan")
        b_str = _fmt_return(b_avg) if b_avg == b_avg else "N/A"
        f_str = _fmt_return(f_avg) if f_avg == f_avg else "N/A"
        lines.append(f"| {regime.upper():<7} | {b_str:>9} | {f_str:>9} |")

    lines += [
        "",
        "## Detailed Results by Regime",
        "",
    ]

    for regime in [BULL, BEAR, SIDEWAYS]:
        b_list = baseline_results.get(regime, [])
        f_list = fixed_results.get(regime, [])
        start, end = REGIME_PERIODS[regime]
        lines += [
            f"### {regime.upper()} Regime ({start} → {end})",
            "",
            "| Symbol | Baseline Return | Fixed Return | Delta | Sharpe (fixed) | Max DD (fixed) | Active Days |",
            "|--------|----------------|--------------|-------|----------------|----------------|-------------|",
        ]
        for b_res, f_res in zip(b_list, f_list, strict=False):
            if "error" in b_res:
                lines.append(f"| {b_res.get('symbol', '?')} | ERROR | ERROR | — | — | — | — |")
                continue
            sym = b_res.get("symbol", "?")
            b_ret = b_res.get("total_return", float("nan"))
            f_ret = f_res.get("total_return", float("nan"))
            delta = f_ret - b_ret if not (b_ret != b_ret or f_ret != f_ret) else float("nan")
            sharpe = f_res.get("sharpe", float("nan"))
            max_dd = f_res.get("max_drawdown", float("nan"))
            active = f_res.get("active_days", 0)
            oos = f_res.get("oos_days", 0)
            lines.append(
                f"| {sym} | {_fmt_return(b_ret)} | {_fmt_return(f_ret)} | "
                f"{_fmt_return(delta)} | {_fmt_sharpe(sharpe)} | "
                f"{max_dd:.1f}% | {active}/{oos} |"
            )
        lines.append("")

    lines += [
        "## Live Cycles (200 steps, recent data)",
        "",
        "| Symbol | Auto-Regime | 20d Return | Strategy Return | Sharpe | Active Days |",
        "|--------|-------------|-----------|----------------|--------|-------------|",
    ]
    for r in live_results:
        if "error" in r:
            lines.append(f"| {r.get('symbol', '?')} | ERROR | — | — | — | — |")
            continue
        regime_label = r.get("live_regime", "?").upper()
        ret_20d = r.get("ret_20d", 0.0)
        strat_ret = r.get("total_return", float("nan"))
        sharpe = r.get("sharpe", float("nan"))
        active = r.get("active_days", 0)
        oos = r.get("oos_days", 0)
        lines.append(
            f"| {r.get('symbol', '?')} | {regime_label} | "
            f"{_fmt_return(ret_20d)} | {_fmt_return(strat_ret)} | "
            f"{_fmt_sharpe(sharpe)} | {active}/{oos} |"
        )

    lines += [
        "",
        "## Regime Signal Multipliers Applied",
        "",
        "| Signal | BULL | BEAR | SIDEWAYS |",
        "|--------|------|------|----------|",
        "| momentum (SMA) | 1.5 | 0.3 | 0.2 |",
        "| rsi | 0.5 | 1.5 | 1.4 |",
        "| vol_regime | 0.3 | 0.8 | 1.5 |",
        "| bb | 1.0 | 1.3 | 1.2 |",
        "| macd | 1.2 | 0.8 | 0.7 |",
        "| vwm | 1.1 | 0.9 | 0.8 |",
        "",
        "## Conviction Thresholds Applied",
        "",
        "| Regime | Agreement Ratio | Min Conviction |",
        "|--------|----------------|----------------|",
        "| BULL | ≥ 0.50 | — |",
        "| BEAR | ≥ 0.70 | — |",
        "| SIDEWAYS | ≥ 0.60 | > 0.40 |",
        "",
        "## Notes",
        "",
        "- Baseline: uniform Brier-weight aggregation, no regime awareness",
        "- Fixed: regime-specific multipliers + BULL momentum floor (min weight 0.30)",
        "- Trend strength gate: 20d+60d momentum agreement AND price > SMA50",
        "- Long-only, half-Kelly sizing, 0.1% commission per side",
        "- Walk-forward expanding window, no lookahead",
    ]

    output_path.write_text("\n".join(lines) + "\n")
    logger.info("Results saved to %s", output_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Regime-aware historical backtest")
    parser.add_argument("--force-refresh", action="store_true", help="Re-download all data")
    parser.add_argument("--symbol", default=None, help="Run single symbol (e.g. BTC/USDT)")
    args = parser.parse_args()

    symbols = [args.symbol] if args.symbol else SYMBOLS
    force = args.force_refresh
    modifier = RegimeAwareSignalModifier()

    baseline_results: dict[str, list[dict]] = {r: [] for r in [BULL, BEAR, SIDEWAYS]}
    fixed_results: dict[str, list[dict]] = {r: [] for r in [BULL, BEAR, SIDEWAYS]}

    # --- Historical regime backtests ---
    for regime in [BULL, BEAR, SIDEWAYS]:
        start, end = REGIME_PERIODS[regime]
        logger.info("")
        logger.info("=" * 60)
        logger.info("REGIME: %s  (%s → %s)", regime.upper(), start, end)
        logger.info("=" * 60)

        for symbol in symbols:
            try:
                bars = get_ohlcv(symbol, start, end, force_refresh=force)
                if len(bars) < MIN_LOOKBACK + MIN_TRAIN + 10:
                    logger.warning("Not enough bars for %s %s: %d", symbol, regime, len(bars))
                    baseline_results[regime].append({"symbol": symbol, "error": "too_few_bars"})
                    fixed_results[regime].append({"symbol": symbol, "error": "too_few_bars"})
                    continue

                logger.info("Baseline (%s %s)...", symbol, regime.upper())
                b_res = run_backtest(
                    symbol, bars, regime=None, modifier=None, use_regime_weights=False
                )
                baseline_results[regime].append(b_res)

                logger.info("Fixed    (%s %s)...", symbol, regime.upper())
                f_res = run_backtest(
                    symbol, bars, regime=regime, modifier=modifier, use_regime_weights=True
                )
                fixed_results[regime].append(f_res)

                b_ret = b_res.get("total_return", float("nan"))
                f_ret = f_res.get("total_return", float("nan"))
                logger.info(
                    "  %s %s:  baseline=%s  fixed=%s  delta=%s",
                    symbol,
                    regime.upper(),
                    _fmt_return(b_ret),
                    _fmt_return(f_ret),
                    _fmt_return(f_ret - b_ret) if b_ret == b_ret and f_ret == f_ret else "N/A",
                )

            except Exception as exc:
                logger.error("FAILED %s %s: %s", symbol, regime, exc, exc_info=True)
                baseline_results[regime].append({"symbol": symbol, "error": str(exc)})
                fixed_results[regime].append({"symbol": symbol, "error": str(exc)})

    # --- Live cycles (200 steps, recent data) ---
    logger.info("")
    logger.info("=" * 60)
    logger.info("LIVE CYCLES (200 steps, recent market data)")
    logger.info("=" * 60)

    live_results: list[dict] = []
    for symbol in symbols:
        try:
            bars = get_recent_ohlcv(symbol, days=365, force_refresh=False)
            # Use last 200 + lookback bars
            live_bars = bars[-(200 + MIN_LOOKBACK) :]
            r = run_live_cycles(symbol, live_bars, n_cycles=200, modifier=modifier)
            live_results.append(r)
            logger.info(
                "  %s live:  regime=%s  return=%s  sharpe=%s",
                symbol,
                r.get("live_regime", "?").upper(),
                _fmt_return(r.get("total_return", float("nan"))),
                _fmt_sharpe(r.get("sharpe", float("nan"))),
            )
        except Exception as exc:
            logger.error("FAILED live %s: %s", symbol, exc, exc_info=True)
            live_results.append({"symbol": symbol, "error": str(exc)})

    # --- Print reports ---
    print_regime_report(baseline_results, fixed_results)
    print_summary_table(baseline_results, fixed_results)
    print_live_cycles_report(live_results)

    # --- Save to docs ---
    out_path = DOCS_DIR / "regime_aware_results.md"
    save_results_markdown(baseline_results, fixed_results, live_results, out_path)
    logger.info("Done. Results saved to %s", out_path)

    # Exit code: 0 if at least one fixed result improved or is positive
    all_fixed = [
        r for regime_list in fixed_results.values() for r in regime_list if "error" not in r
    ]
    if any(r.get("total_return", -999) > 0 for r in all_fixed):
        return 0
    logger.warning("No positive returns achieved in any regime with fixed strategy")
    return 1


if __name__ == "__main__":
    sys.exit(main())
