"""
omega.nodes.vectora.domain_config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Vectora domain configuration — trading-specific defaults that were previously
embedded in framework core files (autonomy.py, improvement_engine.py,
regime_handler.py, adversarial_v2.py).

Usage::

    from omega.nodes.vectora.domain_config import VectoraDomainConfig
    orchestrator.register_domain(VectoraDomainConfig())

This is the single place where Vectora declares its domain-specific
performance criteria, adversarial debate layer, regime signal weights,
and improvement evaluator.
"""

from __future__ import annotations

from omega.core.domain import PerformanceMetric
from omega.core.improvement_engine import SyntheticEvaluator


class VectoraDomainConfig:
    """
    Domain configuration for the Vectora crypto quant trading system.

    Attributes
    ----------
    name
        "trading"
    metrics
        Sharpe ratio (higher is better) and max_drawdown (lower is better).
    debate_gate
        DebateGate instance for adversarial signal debate (BUY/SELL/HOLD).
    regime_actions
        Signal multiplier table for the four market regimes.
    evaluator
        SyntheticEvaluator by default; replace with BacktestEvaluator or
        BridgeEvaluator in production runs.
    """

    name: str = "trading"

    @property
    def metrics(self) -> list[PerformanceMetric]:
        return [
            PerformanceMetric(
                name="sharpe",
                direction="higher_is_better",
                threshold_promote=0.5,
                threshold_demote=0.0,
            ),
            PerformanceMetric(
                name="max_drawdown",
                direction="lower_is_better",
                threshold_promote=0.15,
                threshold_demote=0.20,
            ),
        ]

    @property
    def debate_gate(self) -> object:
        from omega.adversarial.debate_gate import DebateGate

        return DebateGate()

    @property
    def regime_actions(self) -> dict[str, dict[str, float]]:
        """Trading-domain signal multiplier table per market regime."""
        return {
            "normal": {},
            "trending": {
                "momentum": 1.5,
                "trend_follow": 1.4,
                "mean_reversion": 0.6,
                "volatility_spike": 0.8,
            },
            "volatile": {
                "momentum": 0.5,
                "trend_follow": 0.4,
                "mean_reversion": 1.3,
                "volatility_spike": 1.6,
                "defensive": 1.5,
            },
            "crash": {
                "momentum": 0.2,
                "trend_follow": 0.2,
                "mean_reversion": 0.8,
                "volatility_spike": 2.0,
                "defensive": 2.0,
                "risk_off": 2.0,
            },
        }

    @property
    def evaluator(self) -> SyntheticEvaluator:
        """
        Default evaluator for the Vectora trading domain.

        In production, replace with::

            from omega.core.backtest_evaluator import BacktestEvaluator
            from omega.core.bridge_evaluator import BridgeEvaluator
        """
        return SyntheticEvaluator()
