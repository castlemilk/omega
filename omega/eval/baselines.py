"""
omega.eval.baselines
~~~~~~~~~~~~~~~~~~~~~
Mandatory baseline strategies for honest evaluation.

Every strategy must beat ALL baselines to claim alpha.
These are the minimum bars — not the competition.

Baseline strategies
-------------------
buy_and_hold  : THE mandatory baseline. Simply hold the asset from day 1.
sma_crossover : Classic trend-following (fast/slow SMA). A common quant benchmark.
random_strategy: Random buy/sell decisions (seeded). Sanity-check floor.

All return BaselineResult with a standardised interface.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field

from omega.eval.metrics import TradeRecord, compute_max_drawdown, compute_win_rate
from omega.eval.sharpe import compute_sharpe


@dataclass
class BaselineResult:
    """Standardised result for a baseline strategy run."""

    name: str
    returns: list[float]
    trades: list[TradeRecord]
    sharpe: float
    max_drawdown: float
    total_return: float
    equity_curve: list[float] = field(default_factory=list)
    win_rate: float = 0.0
    n_trades: int = 0

    def summary(self) -> dict[str, float]:
        return {
            "sharpe": self.sharpe,
            "max_drawdown": self.max_drawdown,
            "total_return": self.total_return,
            "win_rate": self.win_rate,
            "n_trades": float(self.n_trades),
        }


def buy_and_hold(
    prices: Sequence[float],
    periods_per_year: int = 252,
) -> BaselineResult:
    """
    Buy-and-hold baseline: buy at prices[0], hold to prices[-1].

    Returns daily returns series and a single trade record.
    This is THE mandatory baseline — any strategy must beat this.

    Parameters
    ----------
    prices           : Sequence of close prices (daily).
    periods_per_year : Annualisation factor for Sharpe.
    """
    p = [float(x) for x in prices]
    if len(p) < 2:
        return BaselineResult(
            name="buy_and_hold",
            returns=[],
            trades=[],
            sharpe=0.0,
            max_drawdown=0.0,
            total_return=0.0,
        )

    returns = [(p[i] - p[i - 1]) / p[i - 1] for i in range(1, len(p))]

    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1.0 + r))

    total_ret = equity[-1] - 1.0
    max_dd = compute_max_drawdown(equity)
    sharpe = compute_sharpe(returns, periods_per_year=periods_per_year)

    # Single trade: buy at start, sell at end
    trade = TradeRecord(
        pnl=total_ret,
        entry_price=p[0],
        exit_price=p[-1],
        size=1.0,
        timestamp=0,
    )

    return BaselineResult(
        name="buy_and_hold",
        returns=returns,
        trades=[trade],
        sharpe=sharpe,
        max_drawdown=max_dd,
        total_return=total_ret,
        equity_curve=equity,
        win_rate=1.0 if total_ret > 0 else 0.0,
        n_trades=1,
    )


def sma_crossover(
    prices: Sequence[float],
    fast: int = 10,
    slow: int = 30,
    periods_per_year: int = 252,
) -> BaselineResult:
    """
    SMA crossover baseline: long when fast SMA > slow SMA, flat otherwise.

    No short selling. Position = 1 (long) or 0 (flat).
    Enters at close of crossover signal day, exits at next opposite signal.

    Parameters
    ----------
    prices           : Sequence of close prices (daily).
    fast             : Fast SMA window.
    slow             : Slow SMA window.
    periods_per_year : Annualisation factor for Sharpe.
    """
    p = [float(x) for x in prices]
    n = len(p)
    if n < slow + 1:
        return BaselineResult(
            name=f"sma_crossover_{fast}_{slow}",
            returns=[],
            trades=[],
            sharpe=0.0,
            max_drawdown=0.0,
            total_return=0.0,
        )

    def _sma(window: int, i: int) -> float:
        if i < window - 1:
            return float("nan")
        return sum(p[i - window + 1 : i + 1]) / window

    # Generate signals
    signals: list[int] = []  # 1 = long, 0 = flat
    for i in range(n):
        fast_sma = _sma(fast, i)
        slow_sma = _sma(slow, i)
        if math.isnan(fast_sma) or math.isnan(slow_sma):
            signals.append(0)
        else:
            signals.append(1 if fast_sma > slow_sma else 0)

    # Compute strategy returns
    returns: list[float] = []
    trades: list[TradeRecord] = []
    position = 0
    entry_price = 0.0
    entry_idx = 0

    for i in range(1, n):
        price_ret = (p[i] - p[i - 1]) / p[i - 1] if p[i - 1] != 0 else 0.0
        signal = signals[i - 1]  # signal computed at previous close

        if signal == 1 and position == 0:
            # Enter long
            position = 1
            entry_price = p[i - 1]
            entry_idx = i - 1

        elif signal == 0 and position == 1:
            # Exit long
            pnl = (p[i - 1] - entry_price) / entry_price if entry_price != 0 else 0.0
            trades.append(
                TradeRecord(
                    pnl=pnl,
                    entry_price=entry_price,
                    exit_price=p[i - 1],
                    size=1.0,
                    timestamp=entry_idx,
                )
            )
            position = 0

        strategy_ret = price_ret if position == 1 else 0.0
        returns.append(strategy_ret)

    # Close any open position at end
    if position == 1 and p[-1] != 0 and entry_price != 0:
        pnl = (p[-1] - entry_price) / entry_price
        trades.append(
            TradeRecord(
                pnl=pnl,
                entry_price=entry_price,
                exit_price=p[-1],
                size=1.0,
                timestamp=entry_idx,
            )
        )

    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1.0 + r))

    total_ret = equity[-1] - 1.0
    max_dd = compute_max_drawdown(equity)
    sharpe = compute_sharpe(returns, periods_per_year=periods_per_year)
    win_rate = compute_win_rate(trades)

    return BaselineResult(
        name=f"sma_crossover_{fast}_{slow}",
        returns=returns,
        trades=trades,
        sharpe=sharpe,
        max_drawdown=max_dd,
        total_return=total_ret,
        equity_curve=equity,
        win_rate=win_rate,
        n_trades=len(trades),
    )


def random_strategy(
    prices: Sequence[float],
    seed: int = 42,
    periods_per_year: int = 252,
) -> BaselineResult:
    """
    Random buy/sell strategy (seeded). Sanity-check floor.

    At each bar randomly decides to be long (1) or flat (0) with equal probability.
    No short selling. Seeded for reproducibility.

    Parameters
    ----------
    prices           : Sequence of close prices (daily).
    seed             : Random seed for reproducibility.
    periods_per_year : Annualisation factor for Sharpe.
    """
    p = [float(x) for x in prices]
    n = len(p)
    if n < 2:
        return BaselineResult(
            name="random_strategy",
            returns=[],
            trades=[],
            sharpe=0.0,
            max_drawdown=0.0,
            total_return=0.0,
        )

    rng = random.Random(seed)

    returns: list[float] = []
    trades: list[TradeRecord] = []
    position = 0
    entry_price = 0.0
    entry_idx = 0

    for i in range(1, n):
        signal = rng.choice([0, 1])
        price_ret = (p[i] - p[i - 1]) / p[i - 1] if p[i - 1] != 0 else 0.0

        if signal == 1 and position == 0:
            position = 1
            entry_price = p[i - 1]
            entry_idx = i - 1
        elif signal == 0 and position == 1:
            pnl = (p[i - 1] - entry_price) / entry_price if entry_price != 0 else 0.0
            trades.append(
                TradeRecord(
                    pnl=pnl,
                    entry_price=entry_price,
                    exit_price=p[i - 1],
                    size=1.0,
                    timestamp=entry_idx,
                )
            )
            position = 0

        strategy_ret = price_ret if position == 1 else 0.0
        returns.append(strategy_ret)

    if position == 1 and entry_price != 0:
        pnl = (p[-1] - entry_price) / entry_price
        trades.append(
            TradeRecord(
                pnl=pnl,
                entry_price=entry_price,
                exit_price=p[-1],
                size=1.0,
                timestamp=entry_idx,
            )
        )

    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1.0 + r))

    total_ret = equity[-1] - 1.0
    max_dd = compute_max_drawdown(equity)
    sharpe = compute_sharpe(returns, periods_per_year=periods_per_year)
    win_rate = compute_win_rate(trades)

    return BaselineResult(
        name="random_strategy",
        returns=returns,
        trades=trades,
        sharpe=sharpe,
        max_drawdown=max_dd,
        total_return=total_ret,
        equity_curve=equity,
        win_rate=win_rate,
        n_trades=len(trades),
    )
