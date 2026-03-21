"""
omega.eval.run_composite_backtest
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Composite signal backtest: SMA crossover + RSI + MACD + Bollinger Bands +
volume-weighted momentum, fused via Bayesian aggregation (omega.math.bayesian)
with fat-tail Kelly position sizing (omega.math.kelly).

RESULTS (run 2026-03-21 on 365 days of real Binance daily OHLCV):
=================================================================
Walk-forward OOS: 304 bars (min_train=60, min_lookback=40).
Long-only, half-Kelly sizing, Bayesian Brier-weighted aggregation.

BTC/USDT:
  Composite Sharpe:  -1.4656  [95% CI: -3.2260 .. +0.7564]  NOT SIGNIFICANT
  Max Drawdown:       2.24%   |  Total Return:  -2.02%
  Win Rate (active): 46.7%   |  Active days:    90 / 304
  SMA baseline:      -1.17  →  Composite WORSE by -0.30

ETH/USDT:
  Composite Sharpe:  -1.1158  [95% CI: -3.2263 .. +0.9862]  NOT SIGNIFICANT
  Max Drawdown:       5.76%   |  Total Return:  -4.37%
  Win Rate (active): 45.7%   |  Active days:    94 / 304
  SMA baseline:      +1.00  →  Composite WORSE by -2.12

Portfolio (equal-weight BTC+ETH):
  Sharpe:  -1.3325  [95% CI: -3.2337 .. +0.7494]  NOT SIGNIFICANT
  Max Drawdown: 3.97%   |  Total Return: -3.19%

VERDICT: Composite strategy does NOT beat the SMA-only baseline on
either asset. Bayesian fusion + Kelly sizing adds no edge in this
bear/choppy 2025-2026 crypto period. CIs cross zero throughout —
results are statistically indistinguishable from a flat position.
=================================================================

Usage:
    python -m omega.eval.run_composite_backtest
"""

from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

import numpy as np

from omega.eval.sharpe import compute_sharpe, compute_sharpe_confidence_interval
from omega.math.bayesian import aggregate_signals
from omega.math.kelly import kelly_fractional, rolling_kurtosis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("omega.eval.run_composite_backtest")

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "historical"
PERIODS_PER_YEAR = 365

# Baseline Sharpe from run_honest_backtest (direct mode SMA+RSI)
BASELINE_SMA_SHARPE: dict[str, float] = {
    "BTC/USDT": -1.17,
    "ETH/USDT": 1.00,
}

# Minimum training window before we generate OOS signals
MIN_TRAIN_DAYS = 60

# Commission per trade (0.1% Binance spot fee each side)
COMMISSION = 0.001

# Long-only threshold: go long if Bayesian composite prob > this
LONG_THRESHOLD = 0.52


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_csv(path: Path) -> list[dict]:
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


# ---------------------------------------------------------------------------
# Technical indicator helpers (pure numpy, no external TA lib)
# ---------------------------------------------------------------------------


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average."""
    k = 2.0 / (period + 1)
    out = np.full_like(values, np.nan)
    # Seed with SMA of first `period` values
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
    """Wilder RSI."""
    n = len(closes)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    # Seed with SMA of first period
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
# Signal generators — each returns array of probabilities ∈ (0, 1)
# ---------------------------------------------------------------------------

_NEUTRAL = 0.5
_BULLISH = 0.72
_BEARISH = 0.28


def signal_sma(closes: np.ndarray, short: int = 10, long: int = 50) -> np.ndarray:
    """SMA crossover: bullish when short > long."""
    sma_s = _sma(closes, short)
    sma_l = _sma(closes, long)
    n = len(closes)
    probs = np.full(n, _NEUTRAL)
    for i in range(n):
        if np.isnan(sma_s[i]) or np.isnan(sma_l[i]):
            probs[i] = _NEUTRAL
        elif sma_s[i] > sma_l[i]:
            probs[i] = _BULLISH
        else:
            probs[i] = _BEARISH
    return probs


def signal_rsi(
    closes: np.ndarray,
    period: int = 14,
    overbought: float = 70,
    oversold: float = 30,
) -> np.ndarray:
    """RSI mean-reversion: oversold → bullish, overbought → bearish."""
    rsi = _rsi(closes, period)
    n = len(closes)
    probs = np.full(n, _NEUTRAL)
    for i in range(n):
        if np.isnan(rsi[i]):
            probs[i] = _NEUTRAL
        elif rsi[i] < oversold:
            probs[i] = _BULLISH
        elif rsi[i] > overbought:
            probs[i] = _BEARISH
        else:
            # Linear interpolation between neutral and extremes
            mid = (overbought + oversold) / 2
            if rsi[i] < mid:
                # Low RSI → slightly bullish
                probs[i] = (
                    _NEUTRAL + (_BULLISH - _NEUTRAL) * (mid - rsi[i]) / (mid - oversold) * 0.5
                )
            else:
                # High RSI → slightly bearish
                probs[i] = (
                    _NEUTRAL - (_NEUTRAL - _BEARISH) * (rsi[i] - mid) / (overbought - mid) * 0.5
                )
    return probs


def signal_macd(
    closes: np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> np.ndarray:
    """MACD: histogram crossing zero → bullish, negative → bearish."""
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(np.where(np.isnan(macd_line), 0, macd_line), signal_period)
    histogram = macd_line - signal_line
    n = len(closes)
    probs = np.full(n, _NEUTRAL)
    for i in range(n):
        if np.isnan(histogram[i]) or np.isnan(macd_line[i]):
            probs[i] = _NEUTRAL
        elif histogram[i] > 0 and macd_line[i] > 0:
            probs[i] = _BULLISH
        elif histogram[i] > 0 and macd_line[i] <= 0:
            # Turning up from negative territory — mild bullish
            probs[i] = _NEUTRAL + 0.1
        elif histogram[i] < 0 and macd_line[i] < 0:
            probs[i] = _BEARISH
        else:
            # Turning down from positive — mild bearish
            probs[i] = _NEUTRAL - 0.1
    return probs


def signal_bollinger(
    closes: np.ndarray,
    period: int = 20,
    n_std: float = 2.0,
) -> np.ndarray:
    """Bollinger Band mean-reversion: below lower band → bullish, above upper → bearish."""
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
            # Oversold — mean-reversion bullish
            probs[i] = _BULLISH
        elif price > upper:
            # Overbought — mean-reversion bearish
            probs[i] = _BEARISH
        elif std > 0:
            # Between bands: scale linearly by z-score
            z = (price - mid) / std
            # z=0 → neutral; z=+2 → bearish; z=-2 → bullish
            z_clamped = float(np.clip(z / n_std, -1, 1))
            probs[i] = _NEUTRAL - z_clamped * (_NEUTRAL - _BEARISH)
    return probs


def signal_vwm(
    closes: np.ndarray,
    volumes: np.ndarray,
    period: int = 20,
) -> np.ndarray:
    """Volume-weighted momentum: positive VW momentum → bullish."""
    n = len(closes)
    probs = np.full(n, _NEUTRAL)
    for i in range(period, n):
        c_window = closes[i - period : i]
        v_window = volumes[i - period : i]
        total_vol = float(np.sum(v_window))
        if total_vol == 0:
            continue
        # Volume-weighted average price in window
        vwap = float(np.dot(c_window, v_window)) / total_vol
        pct_above_vwap = (closes[i] - vwap) / vwap
        # Positive momentum → bullish
        if pct_above_vwap > 0.01:
            probs[i] = _BULLISH
        elif pct_above_vwap < -0.01:
            probs[i] = _BEARISH
        else:
            # Small deviation → scale toward neutral
            scale = pct_above_vwap / 0.01
            probs[i] = _NEUTRAL + scale * (_BULLISH - _NEUTRAL)
    return probs


def compute_all_signals(bars: list[dict]) -> np.ndarray:
    """
    Compute all 5 signal probabilities for every day.

    Returns array of shape (n_bars, 5) where each column is a signal.
    Column order: [SMA, RSI, MACD, BB, VWM]
    """
    closes = np.array([b["close"] for b in bars])
    volumes = np.array([b["volume"] for b in bars])

    sma_probs = signal_sma(closes)
    rsi_probs = signal_rsi(closes)
    macd_probs = signal_macd(closes)
    bb_probs = signal_bollinger(closes)
    vwm_probs = signal_vwm(closes, volumes)

    return np.column_stack([sma_probs, rsi_probs, macd_probs, bb_probs, vwm_probs])


# ---------------------------------------------------------------------------
# Brier score computation
# ---------------------------------------------------------------------------


def compute_brier_scores(
    signals_matrix: np.ndarray,
    outcomes: np.ndarray,
    start: int,
    end: int,
) -> np.ndarray:
    """
    Compute per-signal Brier scores over [start, end) window.

    signals_matrix: (n, 5) — signal probs for each day
    outcomes: (n,) — 1 if next-day return > 0, else 0
    Returns: (5,) array of Brier scores; clamped to min 0.01 to avoid zero-weight.
    """
    window_signals = signals_matrix[start:end]
    window_outcomes = outcomes[start:end]
    # Brier score = mean squared error
    bs = np.mean((window_signals - window_outcomes[:, np.newaxis]) ** 2, axis=0)
    # Clamp to avoid zero (undefined weights)
    return np.asarray(np.clip(bs, 0.01, None), dtype=float)


# ---------------------------------------------------------------------------
# Walk-forward expanding-window backtest
# ---------------------------------------------------------------------------


def walk_forward_backtest(
    symbol: str,
    bars: list[dict],
    min_train: int = MIN_TRAIN_DAYS,
) -> dict:
    """
    Expanding-window walk-forward backtest with Bayesian aggregation + fat-tail Kelly.

    Returns a summary dict with performance metrics.
    """
    n = len(bars)
    closes = np.array([b["close"] for b in bars])

    # Daily returns: ret[i] = (close[i] - close[i-1]) / close[i-1]
    daily_rets = np.zeros(n)
    for i in range(1, n):
        daily_rets[i] = (closes[i] - closes[i - 1]) / closes[i - 1]

    # Binary outcomes: 1 if next day's return > 0
    # outcome[i] = 1 if daily_rets[i+1] > 0 (signal at i predicts day i+1)
    outcomes = np.zeros(n)
    for i in range(n - 1):
        outcomes[i] = 1.0 if daily_rets[i + 1] > 0 else 0.0

    # Compute all signals once (no lookahead — each signal uses only data up to day i)
    all_signals = compute_all_signals(bars)

    # Minimum lookback for any signal (MACD slow=26 + signal=9 + buffer = 40)
    min_lookback = 40

    # Rolling kurtosis window for Kelly fat-tail
    kurt_window = 30
    kurt_arr = rolling_kurtosis(daily_rets.tolist(), kurt_window)

    strategy_rets: list[float] = []
    trade_returns: list[float] = []
    positions: list[float] = []
    prev_position = 0.0

    # Start walk-forward from max(min_lookback, min_train)
    walk_start = max(min_lookback, min_train)

    for t in range(walk_start, n - 1):
        # Only compute Brier scores from day min_lookback onward (signals valid there)
        brier_start = min_lookback
        brier_end = t

        if brier_end - brier_start < 10:
            # Not enough training data yet — go flat
            strategy_rets.append(0.0)
            positions.append(0.0)
            continue

        # Compute calibration-weighted Brier scores over training window
        brier_scores = compute_brier_scores(all_signals, outcomes, brier_start, brier_end)

        # Current signal probabilities at end of day t
        current_signals = all_signals[t]

        # Clamp to valid range for aggregate_signals
        current_signals_clamped = np.clip(current_signals, 0.01, 0.99)

        # Bayesian aggregation
        composite_prob = aggregate_signals(
            signals=current_signals_clamped.tolist(),
            brier_scores=brier_scores.tolist(),
            prior=0.5,
        )

        # Determine win probability and estimate win/loss ratio from training
        # Use recent training returns for win rate & ratio estimation
        recent_window = min(60, t)
        recent_rets = daily_rets[t - recent_window : t]
        wins = recent_rets[recent_rets > 0]
        losses = recent_rets[recent_rets < 0]
        avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.005
        avg_loss = abs(float(np.mean(losses))) if len(losses) > 0 else 0.005
        b_ratio = avg_win / avg_loss if avg_loss > 0 else 1.0

        # Fat-tail kurtosis at day t
        kurtosis_t = float(kurt_arr[t]) if not np.isnan(kurt_arr[t]) else 3.0

        # Position sizing: long if composite_prob > threshold
        if composite_prob > LONG_THRESHOLD:
            position = kelly_fractional(
                p=composite_prob,
                b=max(b_ratio, 0.1),
                fraction=0.5,
                kurtosis=kurtosis_t,
                max_position=0.25,
            )
        else:
            position = 0.0

        # Strategy return on day t+1
        raw_ret = position * daily_rets[t + 1]

        # Commission on position changes
        position_change = abs(position - prev_position)
        commission_cost = position_change * COMMISSION

        net_ret = raw_ret - commission_cost
        strategy_rets.append(net_ret)
        positions.append(position)

        if position == 0.0 and prev_position > 0:
            # Closing trade — record trade return
            trade_returns.append(raw_ret - commission_cost)

        prev_position = position

    if len(strategy_rets) < 10:
        logger.warning("Insufficient OOS data for %s", symbol)
        return {"symbol": symbol, "error": "insufficient_data"}

    # Compute metrics
    rets_arr = np.array(strategy_rets)
    sharpe_pt = compute_sharpe(strategy_rets, periods_per_year=PERIODS_PER_YEAR)
    ci_lo, ci_hi = compute_sharpe_confidence_interval(
        strategy_rets,
        n_bootstrap=1000,
        periods_per_year=PERIODS_PER_YEAR,
        seed=42,
    )

    # Max drawdown
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

    total_return = equity - 1.0

    # Win rate (day-level)
    profitable_days = sum(1 for r in strategy_rets if r > 0)
    win_rate = profitable_days / len(strategy_rets) if strategy_rets else 0.0

    # Active win rate (only days we had a position)
    pos_arr = np.array(positions)
    active_mask = pos_arr > 0
    if np.sum(active_mask) > 0:
        active_rets = rets_arr[active_mask]
        active_win_rate = float(np.sum(active_rets > 0)) / len(active_rets)
    else:
        active_win_rate = 0.0

    # Baseline SMA Sharpe reference
    sma_baseline = BASELINE_SMA_SHARPE.get(symbol, 0.0)

    return {
        "symbol": symbol,
        "n_bars": n,
        "n_oos_days": len(strategy_rets),
        "n_active_days": int(np.sum(active_mask)),
        "sharpe": sharpe_pt,
        "sharpe_ci_lo": ci_lo,
        "sharpe_ci_hi": ci_hi,
        "sharpe_significant": ci_lo > 0,
        "max_drawdown": max_dd,
        "total_return": total_return,
        "win_rate_overall": win_rate,
        "win_rate_active": active_win_rate,
        "sma_baseline_sharpe": sma_baseline,
        "beats_baseline": sharpe_pt > sma_baseline,
        "delta_vs_baseline": sharpe_pt - sma_baseline,
    }


# ---------------------------------------------------------------------------
# Composite (portfolio) results
# ---------------------------------------------------------------------------


def compute_portfolio_results(
    all_bars: dict[str, list[dict]],
    min_train: int = MIN_TRAIN_DAYS,
) -> dict:
    """
    Compute equal-weighted portfolio of all assets.
    Aligns returns by index (assumes same time period / same n_bars).
    """
    symbol_rets: dict[str, list[float]] = {}
    min_len = None

    for symbol, bars in all_bars.items():
        n = len(bars)
        closes = np.array([b["close"] for b in bars])

        daily_rets = np.zeros(n)
        for i in range(1, n):
            daily_rets[i] = (closes[i] - closes[i - 1]) / closes[i - 1]

        outcomes = np.zeros(n)
        for i in range(n - 1):
            outcomes[i] = 1.0 if daily_rets[i + 1] > 0 else 0.0

        all_signals = compute_all_signals(bars)
        min_lookback = 40
        kurt_arr = rolling_kurtosis(daily_rets.tolist(), 30)

        rets: list[float] = []
        pos_prev = 0.0
        walk_start = max(min_lookback, min_train)

        for t in range(walk_start, n - 1):
            brier_start = min_lookback
            brier_end = t
            if brier_end - brier_start < 10:
                rets.append(0.0)
                continue

            brier_scores = compute_brier_scores(all_signals, outcomes, brier_start, brier_end)
            current_signals = np.clip(all_signals[t], 0.01, 0.99)
            composite_prob = aggregate_signals(
                signals=current_signals.tolist(),
                brier_scores=brier_scores.tolist(),
                prior=0.5,
            )

            recent_window = min(60, t)
            recent_rets = daily_rets[t - recent_window : t]
            wins = recent_rets[recent_rets > 0]
            losses = recent_rets[recent_rets < 0]
            avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.005
            avg_loss = abs(float(np.mean(losses))) if len(losses) > 0 else 0.005
            b_ratio = avg_win / avg_loss if avg_loss > 0 else 1.0
            kurtosis_t = float(kurt_arr[t]) if not np.isnan(kurt_arr[t]) else 3.0

            if composite_prob > LONG_THRESHOLD:
                position = kelly_fractional(
                    p=composite_prob,
                    b=max(b_ratio, 0.1),
                    fraction=0.5,
                    kurtosis=kurtosis_t,
                    max_position=0.25,
                )
            else:
                position = 0.0

            raw_ret = position * daily_rets[t + 1]
            commission_cost = abs(position - pos_prev) * COMMISSION
            rets.append(raw_ret - commission_cost)
            pos_prev = position

        symbol_rets[symbol] = rets
        if min_len is None or len(rets) < min_len:
            min_len = len(rets)

    if min_len is None or min_len < 10:
        return {"error": "insufficient_data"}

    # Equal-weight portfolio returns
    portfolio_rets: list[float] = [
        float(np.mean([symbol_rets[sym][i] for sym in symbol_rets])) for i in range(min_len)
    ]

    sharpe_pt = compute_sharpe(portfolio_rets, periods_per_year=PERIODS_PER_YEAR)
    ci_lo, ci_hi = compute_sharpe_confidence_interval(
        portfolio_rets,
        n_bootstrap=1000,
        periods_per_year=PERIODS_PER_YEAR,
        seed=42,
    )

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in portfolio_rets:
        equity *= 1.0 + r
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd

    return {
        "sharpe": sharpe_pt,
        "sharpe_ci_lo": ci_lo,
        "sharpe_ci_hi": ci_hi,
        "sharpe_significant": ci_lo > 0,
        "max_drawdown": max_dd,
        "total_return": equity - 1.0,
    }


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------


def print_report(summaries: list[dict], portfolio: dict) -> None:
    sep = "=" * 72
    print()
    print(sep)
    print("  OMEGA COMPOSITE SIGNAL BACKTEST — Walk-Forward, Bayesian + Kelly")
    print(sep)
    print("  Signals: SMA(10/50) | RSI(14) | MACD(12/26/9) | BB(20,2std) | VWM")
    print("  Aggregation: Bayesian (calibration-weighted, expanding window)")
    print("  Sizing: Half-Kelly with fat-tail kurtosis adjustment")
    print(sep)

    for s in summaries:
        if "error" in s:
            print(f"\n  {s['symbol']}: ERROR — {s['error']}")
            continue

        sig_marker = "✓ SIGNIFICANT" if s["sharpe_significant"] else "✗ NOT SIGNIFICANT"
        beats_marker = "BEATS" if s["beats_baseline"] else "LOSES TO"

        print(f"\n  {s['symbol']}")
        print(
            f"  Bars: {s['n_bars']}  |  OOS days: {s['n_oos_days']}  |  Active days: {s['n_active_days']}"
        )
        print()
        print(
            f"  Composite Sharpe:  {s['sharpe']:+.4f}  "
            f"[95% CI: {s['sharpe_ci_lo']:+.4f} .. {s['sharpe_ci_hi']:+.4f}]  "
            f"{sig_marker}"
        )
        print(f"  Max Drawdown:      {s['max_drawdown'] * 100:.2f}%")
        print(f"  Total Return:      {s['total_return'] * 100:.2f}%")
        print(f"  Win Rate (all):    {s['win_rate_overall'] * 100:.1f}%")
        print(f"  Win Rate (active): {s['win_rate_active'] * 100:.1f}%")
        print()
        print(f"  SMA baseline:      {s['sma_baseline_sharpe']:+.2f}  (from direct mode)")
        print(
            f"  Composite vs SMA:  {beats_marker} baseline  (delta: {s['delta_vs_baseline']:+.4f})"
        )

    print()
    print(sep)
    print("  COMPOSITE PORTFOLIO (equal-weighted BTC + ETH)")
    print(sep)

    if "error" in portfolio:
        print(f"  ERROR: {portfolio['error']}")
    else:
        port_sig = "✓ SIGNIFICANT" if portfolio["sharpe_significant"] else "✗ NOT SIGNIFICANT"
        print(
            f"  Portfolio Sharpe:  {portfolio['sharpe']:+.4f}  "
            f"[95% CI: {portfolio['sharpe_ci_lo']:+.4f} .. {portfolio['sharpe_ci_hi']:+.4f}]  "
            f"{port_sig}"
        )
        print(f"  Max Drawdown:      {portfolio['max_drawdown'] * 100:.2f}%")
        print(f"  Total Return:      {portfolio['total_return'] * 100:.2f}%")

    print()
    print(sep)

    # Honest verdict
    significant_count = sum(1 for s in summaries if "error" not in s and s["sharpe_significant"])
    beating_count = sum(1 for s in summaries if "error" not in s and s["beats_baseline"])
    valid = [s for s in summaries if "error" not in s]

    print()
    if not valid:
        print("  VERDICT: No valid results.")
    elif significant_count == len(valid) and beating_count == len(valid):
        print("  VERDICT: Composite strategy is statistically significant AND beats")
        print("           the SMA-only baseline on all tested assets.")
    elif significant_count == len(valid):
        print("  VERDICT: Sharpe is statistically significant but does NOT beat")
        print("           SMA baseline on all assets. Bayesian fusion adds limited edge.")
    elif beating_count > 0:
        print(f"  VERDICT: Beats SMA baseline on {beating_count}/{len(valid)} assets,")
        print("           but NOT statistically significant. May be noise.")
    else:
        print("  VERDICT: Composite strategy does NOT beat the SMA-only baseline")
        print("           and lacks statistical significance. No clear edge found.")

    print()
    print("  NOTE: Walk-forward OOS results only. In-sample overfitting excluded.")
    print("        Long-only strategy with expanding Bayesian calibration window.")
    print(sep)
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    assets = [
        ("BTC/USDT", "btc_usdt_daily_365d.csv"),
        ("ETH/USDT", "eth_usdt_daily_365d.csv"),
    ]

    summaries = []
    all_bars_for_portfolio: dict[str, list[dict]] = {}

    for symbol, filename in assets:
        csv_path = DATA_DIR / filename
        if not csv_path.exists():
            logger.error("Data file not found: %s", csv_path)
            summaries.append({"symbol": symbol, "error": f"missing file: {filename}"})
            continue

        try:
            bars = load_csv(csv_path)
            logger.info("Running walk-forward backtest for %s (%d bars)...", symbol, len(bars))
            result = walk_forward_backtest(symbol, bars)
            summaries.append(result)
            all_bars_for_portfolio[symbol] = bars
        except Exception as exc:
            logger.error("FAILED for %s: %s", symbol, exc, exc_info=True)
            summaries.append({"symbol": symbol, "error": str(exc)})

    # Portfolio composite
    portfolio: dict
    if len(all_bars_for_portfolio) >= 2:
        logger.info("Computing equal-weighted portfolio composite...")
        portfolio = compute_portfolio_results(all_bars_for_portfolio)
    else:
        portfolio = {"error": "need at least 2 assets"}

    print_report(summaries, portfolio)
    return 0 if summaries else 1


if __name__ == "__main__":
    sys.exit(main())
