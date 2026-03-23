"""
omega.eval.metrics
~~~~~~~~~~~~~~~~~~
Comprehensive performance metrics for the eval framework.

All Sharpe calculations delegate to omega.eval.sharpe — never reimplement.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from omega.eval.sharpe import compute_sharpe


@dataclass
class TradeRecord:
    """Single trade result used for win-rate / profit-factor calculations."""

    pnl: float  # realised P&L for the trade
    entry_price: float = 0.0
    exit_price: float = 0.0
    size: float = 1.0
    timestamp: int = 0  # cycle index


@dataclass
class EvalReport:
    """All metrics for a single evaluation run."""

    # Identity
    strategy_name: str = ""
    mode: str = ""  # PICO / SUPERVISED / AUTONOMOUS / baseline

    # Return stats
    total_return: float = 0.0
    annualised_return: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    information_ratio: float = 0.0

    # Risk stats
    max_drawdown: float = 0.0  # negative value, e.g. -0.15 means 15% drawdown
    volatility_ann: float = 0.0

    # Trade stats
    n_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0

    # Walk-forward
    in_sample_sharpe: float = 0.0
    out_of_sample_sharpe: float = 0.0

    # Raw series
    returns: list[float] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)

    def summary(self) -> dict[str, float]:
        return {
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "calmar": self.calmar,
            "max_drawdown": self.max_drawdown,
            "total_return": self.total_return,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "n_trades": float(self.n_trades),
            "in_sample_sharpe": self.in_sample_sharpe,
            "out_of_sample_sharpe": self.out_of_sample_sharpe,
        }


# ---------------------------------------------------------------------------
# Metric functions
# ---------------------------------------------------------------------------


def compute_max_drawdown(equity_curve: Sequence[float]) -> float:
    """
    Compute maximum drawdown from an equity curve.

    Parameters
    ----------
    equity_curve : Sequence of portfolio values (e.g. starting at 1.0).

    Returns
    -------
    Maximum drawdown as a negative float (e.g. -0.20 for 20% drawdown).
    Returns 0.0 for an empty or single-element curve.
    """
    curve = [float(x) for x in equity_curve]
    if len(curve) < 2:
        return 0.0

    peak = curve[0]
    max_dd = 0.0
    for value in curve[1:]:
        if value > peak:
            peak = value
        if peak > 0:
            dd = (value - peak) / peak
            if dd < max_dd:
                max_dd = dd
    return max_dd


def compute_win_rate(trades: Sequence[TradeRecord]) -> float:
    """
    Fraction of winning trades (pnl > 0).

    Returns 0.0 for empty trade list.
    """
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl > 0)
    return wins / len(trades)


def compute_profit_factor(trades: Sequence[TradeRecord]) -> float:
    """
    Gross profit / gross loss.

    Returns 0.0 if there are no losing trades (avoids division by zero).
    Returns float('inf') if all trades are winners.
    """
    if not trades:
        return 0.0
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = sum(-t.pnl for t in trades if t.pnl < 0)
    if gross_loss == 0.0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def compute_calmar_ratio(
    returns: Sequence[float],
    max_dd: float,
    periods_per_year: int = 252,
) -> float:
    """
    Calmar ratio: annualised return / |max drawdown|.

    Parameters
    ----------
    returns          : Per-period returns.
    max_dd           : Max drawdown (negative float, e.g. -0.20).
    periods_per_year : Annualisation factor.

    Returns
    -------
    Calmar ratio. Returns 0.0 if max_dd is 0 or returns is empty.
    """
    r = [float(x) for x in returns]
    if not r or max_dd >= 0.0:
        return 0.0
    ann_return = compute_annualised_return(r, periods_per_year)
    return ann_return / abs(max_dd)


def compute_sortino_ratio(
    returns: Sequence[float],
    target: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """
    Sortino ratio: mean(excess returns) / downside deviation.

    Downside deviation uses sample variance (N-1) on returns below target.

    Parameters
    ----------
    returns          : Per-period returns.
    target           : Minimum acceptable return per period (default 0.0).
    periods_per_year : Annualisation factor.

    Returns
    -------
    Sortino ratio. Returns 0.0 if no downside deviation.
    """
    r = [float(x) for x in returns]
    n = len(r)
    if n < 2:
        return 0.0

    mean_r = sum(r) / n
    downside = [min(0.0, x - target) for x in r]
    n_down = sum(1 for d in downside if d < 0)

    if n_down < 2:
        # No or single downside observations — infinite Sortino
        return float("inf") if mean_r > target else 0.0

    downside_var = sum(d**2 for d in downside) / (n - 1)
    downside_std = math.sqrt(downside_var)

    if downside_std == 0.0:
        return 0.0

    excess_mean = mean_r - target
    return excess_mean / downside_std * math.sqrt(periods_per_year)


def build_equity_curve(returns: Sequence[float], initial: float = 1.0) -> list[float]:
    """
    Convert a returns series to an equity curve.

    Parameters
    ----------
    returns : Per-period simple returns (not log returns).
    initial : Starting portfolio value.

    Returns
    -------
    List of portfolio values, length = len(returns) + 1.
    """
    curve = [initial]
    for r in returns:
        curve.append(curve[-1] * (1.0 + float(r)))
    return curve


def compute_annualised_return(returns: Sequence[float], periods_per_year: int = 252) -> float:
    """Annualised compound return (CAGR)."""
    r = [float(x) for x in returns]
    n = len(r)
    if n == 0:
        return 0.0
    equity = build_equity_curve(r)  # already defined in this file
    # Guard against zero or negative final equity (extreme edge case)
    final: float = equity[-1]
    if final <= 0.0:
        return -1.0
    return float(final ** (periods_per_year / n)) - 1.0


def compute_annualised_volatility(returns: Sequence[float], periods_per_year: int = 252) -> float:
    """Annualised return volatility using sample std."""
    r = [float(x) for x in returns]
    n = len(r)
    if n < 2:
        return 0.0
    mean = sum(r) / n
    var = sum((x - mean) ** 2 for x in r) / (n - 1)
    return math.sqrt(var) * math.sqrt(periods_per_year)


def build_eval_report(
    strategy_name: str,
    mode: str,
    returns: list[float],
    trades: list[TradeRecord] | None = None,
    benchmark_returns: list[float] | None = None,
    in_sample_returns: list[float] | None = None,
    out_of_sample_returns: list[float] | None = None,
    periods_per_year: int = 252,
) -> EvalReport:
    """
    Build a complete EvalReport from a returns series.

    This is the preferred way to construct an EvalReport — it ensures all
    metrics are computed consistently.
    """
    trades = trades or []
    equity = build_equity_curve(returns)
    max_dd = compute_max_drawdown(equity)

    sharpe = compute_sharpe(returns, periods_per_year=periods_per_year)
    sortino = compute_sortino_ratio(returns, periods_per_year=periods_per_year)
    calmar = compute_calmar_ratio(returns, max_dd, periods_per_year=periods_per_year)

    ir = 0.0
    if benchmark_returns:
        from omega.eval.sharpe import compute_information_ratio

        ir = compute_information_ratio(returns, benchmark_returns, periods_per_year)

    total_ret = equity[-1] / equity[0] - 1.0 if equity else 0.0
    ann_ret = compute_annualised_return(returns, periods_per_year)
    vol_ann = compute_annualised_volatility(returns, periods_per_year)

    is_sharpe = (
        compute_sharpe(in_sample_returns, periods_per_year=periods_per_year)
        if in_sample_returns
        else 0.0
    )
    oos_sharpe = (
        compute_sharpe(out_of_sample_returns, periods_per_year=periods_per_year)
        if out_of_sample_returns
        else 0.0
    )

    return EvalReport(
        strategy_name=strategy_name,
        mode=mode,
        total_return=total_ret,
        annualised_return=ann_ret,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        information_ratio=ir,
        max_drawdown=max_dd,
        volatility_ann=vol_ann,
        n_trades=len(trades),
        win_rate=compute_win_rate(trades),
        profit_factor=compute_profit_factor(trades),
        in_sample_sharpe=is_sharpe,
        out_of_sample_sharpe=oos_sharpe,
        returns=returns,
        equity_curve=equity,
        trades=trades,
    )
