"""
omega.eval
~~~~~~~~~~
Honest evaluation framework for the Omega trading system.

Exports
-------
OmegaBacktestBridge  : Runs the real orchestrator against historical data.
BacktestMode         : PICO / SUPERVISED / AUTONOMOUS.
BacktestResult       : Full result from a backtest run.
CycleRecord          : Per-cycle record during backtest.

compute_sharpe                    : THE Sharpe formula (single source of truth).
compute_sharpe_confidence_interval: Bootstrap CI for Sharpe.
sharpe_difference_significant     : Paired t-test on Sharpe difference.
compute_information_ratio         : Alpha / tracking error.

buy_and_hold    : Mandatory baseline.
sma_crossover   : SMA trend baseline.
random_strategy : Sanity-check floor.
BaselineResult  : Standardised baseline result.

EvalReport            : Bundled metrics for a single run.
TradeRecord           : Single trade record.
compute_max_drawdown  : Maximum drawdown from equity curve.
compute_win_rate      : Fraction of winning trades.
compute_profit_factor : Gross profit / gross loss.
compute_calmar_ratio  : Annualised return / |max drawdown|.
compute_sortino_ratio : Sharpe using only downside deviation.
build_eval_report     : Build complete EvalReport from returns.
"""

from __future__ import annotations

from omega.eval.backtest_bridge import (
    BacktestMode,
    BacktestResult,
    CycleRecord,
    OmegaBacktestBridge,
)
from omega.eval.baselines import BaselineResult, buy_and_hold, random_strategy, sma_crossover
from omega.eval.metrics import (
    EvalReport,
    TradeRecord,
    build_eval_report,
    compute_calmar_ratio,
    compute_max_drawdown,
    compute_profit_factor,
    compute_sortino_ratio,
    compute_win_rate,
)
from omega.eval.sharpe import (
    compute_information_ratio,
    compute_sharpe,
    compute_sharpe_confidence_interval,
    sharpe_difference_significant,
)

__all__ = [
    "BacktestMode",
    "BacktestResult",
    "BaselineResult",
    "CycleRecord",
    "EvalReport",
    "OmegaBacktestBridge",
    "TradeRecord",
    "build_eval_report",
    "buy_and_hold",
    "compute_calmar_ratio",
    "compute_information_ratio",
    "compute_max_drawdown",
    "compute_profit_factor",
    "compute_sharpe",
    "compute_sharpe_confidence_interval",
    "compute_sortino_ratio",
    "compute_win_rate",
    "random_strategy",
    "sharpe_difference_significant",
    "sma_crossover",
]
