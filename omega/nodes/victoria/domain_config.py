"""
omega.nodes.victoria.domain_config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Victoria domain configuration — trading-specific defaults that were previously
embedded in framework core files (autonomy.py, improvement_engine.py,
regime_handler.py, adversarial_v2.py).

Usage::

    from omega.nodes.victoria.domain_config import VictoriaDomainConfig
    orchestrator.register_domain(VictoriaDomainConfig())

This is the single place where Victoria declares its domain-specific
performance criteria, adversarial debate layer, regime signal weights,
and improvement evaluator.
"""

from __future__ import annotations

from omega.core.domain import PerformanceMetric
from omega.core.improvement_engine import SyntheticEvaluator


class VictoriaDomainConfig:
    """
    Domain configuration for the Victoria crypto quant trading system.

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
        """Trading-domain signal multiplier table per market regime.

        Original four BOCPD labels (normal/trending/volatile/crash) are retained
        for backwards compatibility.  Three backtest-calibrated labels are added:

        bull / bear / sideways
            Derived from per-signal Information Coefficients measured across
            labelled historical periods.  These multipliers are applied ON TOP
            of base IC weights by RegimeAwareSignalModifier in regime_detector.py.

        Signal name mapping:
            "momentum"   → SMA crossover (trend-following)
            "rsi"        → RSI mean-reversion
            "vol_regime" → Volatility regime (low-vol bullish, high-vol bearish)
            "bb"         → Bollinger Band mean-reversion
            "macd"       → MACD histogram crossover
            "vwm"        → Volume-weighted momentum
        """
        return {
            # --- Legacy BOCPD labels ---
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
            # --- Backtest-calibrated regime labels ---
            # BULL: momentum/trend-following dominant; vol_regime and RSI de-weighted
            "bull": {
                "momentum": 1.5,
                "rsi": 0.5,
                "vol_regime": 0.3,
                "bb": 1.0,
                "macd": 1.2,
                "vwm": 1.1,
            },
            # BEAR: RSI oversold bounces primary; momentum faded; BB supports entries
            "bear": {
                "momentum": 0.3,
                "rsi": 1.5,
                "vol_regime": 0.8,
                "bb": 1.3,
                "macd": 0.8,
                "vwm": 0.9,
            },
            # SIDEWAYS: vol_regime strongest predictor; momentum actively harmful
            "sideways": {
                "momentum": 0.2,
                "rsi": 1.4,
                "vol_regime": 1.5,
                "bb": 1.2,
                "macd": 0.7,
                "vwm": 0.8,
            },
        }

    @property
    def evaluator(self) -> SyntheticEvaluator:
        """
        Default evaluator for the Victoria trading domain.

        In production, replace with::

            from omega.core.backtest_evaluator import BacktestEvaluator
            from omega.core.bridge_evaluator import BridgeEvaluator
        """
        return SyntheticEvaluator()
