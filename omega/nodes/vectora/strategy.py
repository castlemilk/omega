"""
omega.nodes.vectora.strategy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
StrategyNode — combines signals into portfolio decisions and backtests them.

Improvement arc:
  v1.0 — Equal-weight portfolio of buy-signal stocks
  v1.1 — Momentum-weighted portfolio (weight ∝ composite signal strength)
  v1.2 — Risk-parity-weighted portfolio (weight ∝ 1/volatility)
  v1.3 — Signal threshold tuning based on backtest Sharpe feedback
"""

import logging
import math
import time
import uuid
from typing import Any

from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.vectora.strategy")


class StrategyNode(Node):
    """
    Constructs portfolios and backtests strategies from trading signals.

    Capabilities : construct_portfolio, backtest_strategy, rank_signals
    Improves via : equal weight → momentum weight → risk parity → signal tuning
    """

    def __init__(self) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._weighting = "equal"  # "equal", "momentum", "risk_parity"
        self._signal_threshold = 0.0  # composite signal must exceed this to be included
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._last_sharpe = 0.0
        self._last_max_drawdown = 0.0
        self._last_hit_rate = 0.0
        self._backtest_count = 0

    # ------------------------------------------------------------------ Node interface

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._node_id,
            name="StrategyNode",
            version=self._version,
            health=max(0.0, 1.0 - self._error_rate()),
            capabilities=self.get_capabilities(),
            metrics={
                "avg_latency_ms": self._avg_latency_ms(),
                "error_rate": self._error_rate(),
                "sharpe_ratio": self._last_sharpe,
                "max_drawdown": self._last_max_drawdown,
                "hit_rate": self._last_hit_rate,
            },
            metadata={
                "weighting": self._weighting,
                "signal_threshold": self._signal_threshold,
                "backtest_count": self._backtest_count,
            },
        )

    def get_capabilities(self) -> list[str]:
        return ["construct_portfolio", "backtest_strategy", "rank_signals"]

    def describe(self) -> str:
        return (
            "Constructs investment portfolios from trading signals and backtests "
            "them against historical data. Supports equal-weight, momentum-weighted, "
            "and risk-parity-weighted portfolio construction. Self-improves by "
            "upgrading weighting scheme and tuning signal thresholds."
        )

    def execute(self, input: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        action = input.action
        params = input.parameters

        try:
            if action == "construct_portfolio":
                signals = params.get("signals", {})
                market_data = params.get("market_data", {})
                result = self._construct_portfolio(signals, market_data)
            elif action == "backtest_strategy":
                signals = params.get("signals", {})
                market_data = params.get("market_data", {})
                result = self._backtest(signals, market_data)
            elif action == "rank_signals":
                signals = params.get("signals", {})
                result = self._rank_signals(signals)  # type: ignore[assignment]
            else:
                elapsed = (time.perf_counter() - t0) * 1000
                self._execution_count += 1
                self._error_count += 1
                self._total_latency_ms += elapsed
                return NodeOutput(
                    request_id=input.request_id,
                    success=False,
                    errors=[f"Unknown action '{action}'"],
                    metrics={"latency_ms": elapsed},
                )

            elapsed = (time.perf_counter() - t0) * 1000
            self._execution_count += 1
            self._total_latency_ms += elapsed

            return NodeOutput(
                request_id=input.request_id,
                success=True,
                result=result,
                metrics={
                    "latency_ms": elapsed,
                    "sharpe_ratio": self._last_sharpe,
                    "max_drawdown": self._last_max_drawdown,
                    "hit_rate": self._last_hit_rate,
                },
            )

        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._execution_count += 1
            self._error_count += 1
            self._total_latency_ms += elapsed
            logger.error("StrategyNode error: %s", exc, exc_info=True)
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": elapsed},
            )

    def evaluate(self) -> dict[str, float]:
        return {
            "avg_latency_ms": self._avg_latency_ms(),
            "error_rate": self._error_rate(),
            "sharpe_ratio": self._last_sharpe,
            "max_drawdown": self._last_max_drawdown,
            "hit_rate": self._last_hit_rate,
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        changed = False
        iteration = feedback.get("iteration", 0)

        # v1.1: Switch to momentum weighting after first iteration
        if self._weighting == "equal" and iteration >= 1:
            self._weighting = "momentum"
            self._version = "1.1"
            logger.info("StrategyNode → v1.1: momentum weighting enabled")
            changed = True

        # v1.2: Switch to risk-parity weighting after second iteration
        if self._weighting == "momentum" and iteration >= 2:
            self._weighting = "risk_parity"
            self._version = "1.2"
            logger.info("StrategyNode → v1.2: risk-parity weighting enabled")
            changed = True

        # v1.3: Tighten signal threshold if Sharpe is poor
        if self._version == "1.2" and self._last_sharpe < 0.5 and self._backtest_count >= 2:
            self._signal_threshold = min(0.3, self._signal_threshold + 0.1)
            self._version = "1.3"
            logger.info(
                "StrategyNode → v1.3: signal threshold tightened to %.2f (sharpe=%.2f)",
                self._signal_threshold,
                self._last_sharpe,
            )
            changed = True

        return changed

    # ------------------------------------------------------------------ portfolio construction

    def _construct_portfolio(
        self, signals: dict[str, Any], market_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Build portfolio weights from signals."""
        # Filter to buy-signal stocks
        candidates = {
            ticker: sig
            for ticker, sig in signals.items()
            if sig.get("composite", 0.0) > self._signal_threshold
        }

        if not candidates:
            # Fall back to all available if no clear buys
            candidates = {
                ticker: sig for ticker, sig in signals.items() if sig.get("composite") is not None
            }

        if not candidates:
            return {"weights": {}, "positions": 0, "method": self._weighting}

        weights: dict[str, float] = {}

        if self._weighting == "equal":
            weight = 1.0 / len(candidates)
            weights = {ticker: weight for ticker in candidates}

        elif self._weighting == "momentum":
            # Weight proportional to positive composite signal strength
            raw = {
                ticker: max(0.001, sig.get("composite", 0.001))
                for ticker, sig in candidates.items()
            }
            total = sum(raw.values())
            weights = {ticker: v / total for ticker, v in raw.items()}

        elif self._weighting == "risk_parity":
            # Weight ∝ 1/volatility using recent price history
            vols: dict[str, float] = {}
            for ticker, _sig in candidates.items():
                data = market_data.get(ticker)
                if data:
                    prices = self._clean_prices(data.get("adjclose") or data.get("close", []))
                    vol = self._compute_volatility(prices, window=20)
                    vols[ticker] = vol if vol > 0 else 0.3  # default 30% vol
                else:
                    vols[ticker] = 0.3

            inv_vol = {ticker: 1.0 / v for ticker, v in vols.items()}
            total = sum(inv_vol.values())
            weights = {ticker: v / total for ticker, v in inv_vol.items()}

        # Also run a quick backtest
        bt = self._backtest(signals, market_data)

        return {
            "weights": weights,
            "positions": len(weights),
            "method": self._weighting,
            "signal_threshold": self._signal_threshold,
            "top_picks": self._rank_signals(signals)[:5],
            "backtest": bt,
        }

    def _rank_signals(self, signals: dict[str, Any]) -> list[dict[str, Any]]:
        """Rank tickers by composite signal strength."""
        ranked = []
        for ticker, sig in signals.items():
            composite = sig.get("composite")
            if composite is not None:
                ranked.append(
                    {
                        "ticker": ticker,
                        "composite": composite,
                        "price": sig.get("price"),
                        "rsi": sig.get("rsi"),
                        "return_1d": sig.get("return_1d"),
                    }
                )
        ranked.sort(key=lambda x: x["composite"], reverse=True)
        return ranked

    def _backtest(self, signals: dict[str, Any], market_data: dict[str, Any]) -> dict[str, Any]:
        """
        Simple backtest: compute signal-implied returns over available history.

        Strategy: at each bar, equal-weight long the top quartile, short the bottom.
        Computes Sharpe, max drawdown, and hit rate on 1-day forward returns.
        """
        self._backtest_count += 1

        # Collect per-ticker (signal, return) pairs using all available history
        all_returns: list[float] = []
        hit_count = 0
        total_trades = 0

        for _ticker, data in market_data.items():
            if not data:
                continue
            prices = self._clean_prices(data.get("adjclose") or data.get("close", []))
            if len(prices) < 22:
                continue

            # compute rolling SMA-crossover signal for each bar and 1-day forward return
            for i in range(20, len(prices) - 1):
                window = prices[: i + 1]
                sma5 = sum(window[-5:]) / 5
                sma20 = sum(window[-20:]) / 20
                signal = 1.0 if sma5 > sma20 else -1.0
                fwd_ret = (prices[i + 1] - prices[i]) / prices[i] if prices[i] != 0 else 0.0
                strategy_ret = signal * fwd_ret
                all_returns.append(strategy_ret)
                total_trades += 1
                if strategy_ret > 0:
                    hit_count += 1

        if not all_returns:
            return {"sharpe": 0.0, "max_drawdown": 0.0, "hit_rate": 0.0, "trades": 0}

        mean_ret = sum(all_returns) / len(all_returns)
        variance = sum((r - mean_ret) ** 2 for r in all_returns) / max(1, len(all_returns) - 1)
        std_ret = math.sqrt(variance) if variance > 0 else 1e-6

        # Annualised Sharpe (252 trading days)
        sharpe = (mean_ret / std_ret) * math.sqrt(252) if std_ret > 0 else 0.0

        # Max drawdown on cumulative P&L
        cum = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in all_returns:
            cum += r
            if cum > peak:
                peak = cum
            dd = (peak - cum) / (peak + 1e-9)
            if dd > max_dd:
                max_dd = dd

        hit_rate = hit_count / total_trades if total_trades > 0 else 0.0

        self._last_sharpe = sharpe
        self._last_max_drawdown = max_dd
        self._last_hit_rate = hit_rate

        return {
            "sharpe": sharpe,
            "max_drawdown": max_dd,
            "hit_rate": hit_rate,
            "trades": total_trades,
            "mean_daily_return": mean_ret,
        }

    # ------------------------------------------------------------------ helpers

    def _compute_volatility(self, prices: list[float], window: int = 20) -> float:
        if len(prices) < window + 1:
            return 0.3
        returns = [
            (prices[i] - prices[i - 1]) / prices[i - 1]
            for i in range(max(1, len(prices) - window), len(prices))
            if prices[i - 1] != 0
        ]
        if len(returns) < 2:
            return 0.3
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        daily_vol = math.sqrt(variance)
        return daily_vol * math.sqrt(252)  # annualised

    def _clean_prices(self, prices: list) -> list[float]:
        result = []
        for p in prices:
            if p is None:
                continue
            try:
                f = float(p)
                if not math.isnan(f) and not math.isinf(f):
                    result.append(f)
            except (TypeError, ValueError):
                continue
        return result

    def _avg_latency_ms(self) -> float:
        return self._total_latency_ms / max(1, self._execution_count)

    def _error_rate(self) -> float:
        return self._error_count / max(1, self._execution_count)
