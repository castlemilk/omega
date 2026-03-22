"""
omega.nodes.victoria.risk_management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
RiskManagementNode — monitors portfolio risk and enforces position limits.

Improvement arc:
  v1.0 — Historical VaR (95%) via simple percentile
  v1.1 — CVaR (Expected Shortfall) added
  v1.2 — Correlation-adjusted position sizing (reduce concentration)
  v1.3 — Volatility-regime detection (tighten limits in high-vol regimes)
"""

import logging
import math
import time
import uuid
from typing import Any

from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.victoria.risk_management")

_DEFAULT_VAR_CONFIDENCE = 0.95
_MAX_POSITION_SIZE = 0.25  # No single position > 25%
_MAX_PORTFOLIO_VAR = 0.02  # Daily VaR limit: 2% of portfolio


class RiskManagementNode(Node):
    """
    Estimates portfolio risk metrics and enforces position sizing limits.

    Capabilities : compute_var, check_risk_limits, compute_correlation
    Improves via : VaR → CVaR → correlation-adjusted sizing → regime detection
    """

    def __init__(self) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._var_confidence = _DEFAULT_VAR_CONFIDENCE
        self._max_position = _MAX_POSITION_SIZE
        self._max_portfolio_var = _MAX_PORTFOLIO_VAR
        self._use_cvar = False
        self._use_correlation = False
        self._use_regime = False
        self._high_vol_regime = False
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._last_portfolio_var = 0.0
        self._last_portfolio_cvar = 0.0
        self._last_max_correlation = 0.0

    # ------------------------------------------------------------------ Node interface

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._node_id,
            name="RiskManagementNode",
            version=self._version,
            health=max(0.0, 1.0 - self._error_rate()),
            capabilities=self.get_capabilities(),
            metrics={
                "avg_latency_ms": self._avg_latency_ms(),
                "error_rate": self._error_rate(),
                "portfolio_var_95": self._last_portfolio_var,
                "portfolio_cvar_95": self._last_portfolio_cvar,
                "max_pairwise_correlation": self._last_max_correlation,
            },
            metadata={
                "var_confidence": self._var_confidence,
                "max_position": self._max_position,
                "use_cvar": self._use_cvar,
                "use_correlation": self._use_correlation,
                "high_vol_regime": self._high_vol_regime,
            },
        )

    def get_capabilities(self) -> list[str]:
        return ["compute_var", "check_risk_limits", "compute_correlation"]

    def describe(self) -> str:
        return (
            "Estimates portfolio risk using historical simulation. Computes "
            "Value-at-Risk (VaR), Conditional VaR (Expected Shortfall), "
            "pairwise correlations, and position sizing limits. "
            "Self-improves by adding CVaR, correlation-adjusted sizing, "
            "and volatility regime detection."
        )

    def execute(self, input: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        action = input.action
        params = input.parameters

        try:
            if action == "compute_var":
                portfolio = params.get("portfolio", {})
                market_data = params.get("market_data", {})
                result = self._compute_portfolio_var(portfolio, market_data)
            elif action == "check_risk_limits":
                portfolio = params.get("portfolio", {})
                market_data = params.get("market_data", {})
                result = self._check_risk_limits(portfolio, market_data)
            elif action == "compute_correlation":
                market_data = params.get("market_data", {})
                result = self._compute_correlation_matrix(market_data)
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
                    "portfolio_var_95": self._last_portfolio_var,
                    "portfolio_cvar_95": self._last_portfolio_cvar,
                    "max_pairwise_correlation": self._last_max_correlation,
                },
            )

        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._execution_count += 1
            self._error_count += 1
            self._total_latency_ms += elapsed
            logger.error("RiskManagementNode error: %s", exc, exc_info=True)
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
            "portfolio_var_95": self._last_portfolio_var,
            "portfolio_cvar_95": self._last_portfolio_cvar,
            "max_pairwise_correlation": self._last_max_correlation,
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        changed = False
        iteration = feedback.get("iteration", 0)

        # v1.1: Add CVaR after first iteration
        if not self._use_cvar and iteration >= 1:
            self._use_cvar = True
            self._version = "1.1"
            logger.info("RiskManagementNode → v1.1: CVaR (Expected Shortfall) enabled")
            changed = True

        # v1.2: Add correlation-adjusted sizing
        if self._use_cvar and not self._use_correlation and iteration >= 2:
            self._use_correlation = True
            self._version = "1.2"
            logger.info("RiskManagementNode → v1.2: correlation-adjusted sizing enabled")
            changed = True

        # v1.3: Volatility regime detection
        if (
            self._use_correlation
            and not self._use_regime
            and (self._last_portfolio_var > self._max_portfolio_var * 1.5 or iteration >= 3)
        ):
            self._use_regime = True
            self._version = "1.3"
            logger.info("RiskManagementNode → v1.3: volatility regime detection enabled")
            changed = True

        # Dynamic limit tightening in high-vol regime
        if self._use_regime and self._high_vol_regime:
            new_max = min(0.15, self._max_position - 0.02)
            if new_max < self._max_position:
                self._max_position = new_max
                logger.info(
                    "RiskManagementNode: high-vol regime → max position tightened to %.0f%%",
                    self._max_position * 100,
                )
                changed = True

        return changed

    # ------------------------------------------------------------------ risk computation

    def _compute_portfolio_var(
        self, portfolio: dict[str, Any], market_data: dict[str, Any]
    ) -> dict[str, Any]:
        weights = portfolio.get("weights", {})
        if not weights:
            return {"var_95": 0.0, "cvar_95": 0.0, "method": "historical"}

        # Compute portfolio daily returns via weighted sum of asset returns
        portfolio_returns = self._compute_portfolio_returns(weights, market_data)

        if not portfolio_returns:
            return {"var_95": 0.0, "cvar_95": 0.0, "method": "historical"}

        var_95 = self._historical_var(portfolio_returns, self._var_confidence)
        result: dict[str, Any] = {
            "var_95": var_95,
            "method": "historical",
            "confidence": self._var_confidence,
            "window_days": len(portfolio_returns),
        }

        self._last_portfolio_var = var_95

        if self._use_cvar:
            cvar_95 = self._historical_cvar(portfolio_returns, self._var_confidence)
            result["cvar_95"] = cvar_95
            self._last_portfolio_cvar = cvar_95

        # Detect volatility regime
        if self._use_regime and len(portfolio_returns) >= 20:
            recent_vol = self._compute_vol(portfolio_returns[-20:])
            long_vol = self._compute_vol(portfolio_returns)
            self._high_vol_regime = recent_vol > long_vol * 1.3
            result["high_vol_regime"] = self._high_vol_regime
            result["recent_vol_annualised"] = recent_vol * math.sqrt(252)

        return result

    def _check_risk_limits(
        self, portfolio: dict[str, Any], market_data: dict[str, Any]
    ) -> dict[str, Any]:
        weights = portfolio.get("weights", {})
        violations: list[str] = []
        adjusted_weights: dict[str, float] = dict(weights)

        # Position size limit
        for ticker, w in weights.items():
            if w > self._max_position:
                violations.append(
                    f"{ticker}: weight {w:.1%} exceeds limit {self._max_position:.1%}"
                )
                adjusted_weights[ticker] = self._max_position

        # Renormalize after capping
        total = sum(adjusted_weights.values())
        if total > 0:
            adjusted_weights = {k: v / total for k, v in adjusted_weights.items()}

        # Portfolio VaR check
        var_result = self._compute_portfolio_var({"weights": adjusted_weights}, market_data)
        portfolio_var = var_result.get("var_95", 0.0)
        if portfolio_var > self._max_portfolio_var:
            violations.append(
                f"Portfolio VaR {portfolio_var:.2%} exceeds daily limit "
                f"{self._max_portfolio_var:.2%}"
            )

        # Correlation check
        if self._use_correlation and len(weights) >= 2:
            corr_matrix = self._compute_correlation_matrix(market_data)
            max_corr = corr_matrix.get("max_correlation", 0.0)
            self._last_max_correlation = max_corr
            if max_corr > 0.9:
                violations.append(f"High pairwise correlation detected: {max_corr:.2f}")

        return {
            "original_weights": weights,
            "adjusted_weights": adjusted_weights,
            "violations": violations,
            "passed": len(violations) == 0,
            "portfolio_var_95": portfolio_var,
            "max_position_limit": self._max_position,
        }

    def _compute_correlation_matrix(self, market_data: dict[str, Any]) -> dict[str, Any]:
        """Compute pairwise return correlations between assets."""
        returns_by_ticker: dict[str, list[float]] = {}

        for ticker, data in market_data.items():
            if not data:
                continue
            prices = self._clean_prices(data.get("adjclose") or data.get("close", []))
            if len(prices) < 10:
                continue
            returns = [
                (prices[i] - prices[i - 1]) / prices[i - 1]
                for i in range(1, len(prices))
                if prices[i - 1] != 0
            ]
            if returns:
                returns_by_ticker[ticker] = returns

        tickers = list(returns_by_ticker.keys())
        if len(tickers) < 2:
            return {"correlations": {}, "max_correlation": 0.0}

        correlations: dict[str, float] = {}
        max_corr = 0.0

        for i in range(len(tickers)):
            for j in range(i + 1, len(tickers)):
                t1, t2 = tickers[i], tickers[j]
                r1 = returns_by_ticker[t1]
                r2 = returns_by_ticker[t2]
                # Align lengths
                min_len = min(len(r1), len(r2))
                corr = self._pearson_correlation(r1[-min_len:], r2[-min_len:])
                key = f"{t1}:{t2}"
                correlations[key] = corr
                if abs(corr) > max_corr:
                    max_corr = abs(corr)

        self._last_max_correlation = max_corr
        return {"correlations": correlations, "max_correlation": max_corr}

    # ------------------------------------------------------------------ statistics

    def _compute_portfolio_returns(
        self, weights: dict[str, float], market_data: dict[str, Any]
    ) -> list[float]:
        """Compute weighted portfolio daily returns."""
        all_returns: dict[str, list[float]] = {}

        for ticker, _weight in weights.items():
            data = market_data.get(ticker)
            if not data:
                continue
            prices = self._clean_prices(data.get("adjclose") or data.get("close", []))
            if len(prices) < 2:
                continue
            rets = [
                (prices[i] - prices[i - 1]) / prices[i - 1]
                for i in range(1, len(prices))
                if prices[i - 1] != 0
            ]
            all_returns[ticker] = rets

        if not all_returns:
            return []

        # Align all return series to shortest
        min_len = min(len(r) for r in all_returns.values())
        portfolio_returns = [0.0] * min_len

        # Normalise weights to sum to 1 for included assets
        included = {k: v for k, v in weights.items() if k in all_returns}
        total_w = sum(included.values())
        if total_w == 0:
            return []

        for ticker, rets in all_returns.items():
            w = weights.get(ticker, 0.0) / total_w
            for i in range(min_len):
                portfolio_returns[i] += w * rets[len(rets) - min_len + i]

        return portfolio_returns

    def _historical_var(self, returns: list[float], confidence: float) -> float:
        """Historical VaR: the (1-confidence) percentile of returns (as loss)."""
        if not returns:
            return 0.0
        sorted_rets = sorted(returns)
        idx = int((1 - confidence) * len(sorted_rets))
        idx = max(0, min(idx, len(sorted_rets) - 1))
        return max(0.0, -sorted_rets[idx])

    def _historical_cvar(self, returns: list[float], confidence: float) -> float:
        """CVaR: mean of returns below VaR threshold (Expected Shortfall)."""
        if not returns:
            return 0.0
        sorted_rets = sorted(returns)
        n_tail = max(1, int((1 - confidence) * len(sorted_rets)))
        tail = sorted_rets[:n_tail]
        return max(0.0, -sum(tail) / len(tail))

    def _compute_vol(self, returns: list[float]) -> float:
        if len(returns) < 2:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        return math.sqrt(variance)

    def _pearson_correlation(self, x: list[float], y: list[float]) -> float:
        n = len(x)
        if n < 2:
            return 0.0
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        var_x = sum((v - mean_x) ** 2 for v in x)
        var_y = sum((v - mean_y) ** 2 for v in y)
        denom = math.sqrt(var_x * var_y)
        return cov / denom if denom > 0 else 0.0

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

    # ------------------------------------------------------------------ helpers

    def _avg_latency_ms(self) -> float:
        return self._total_latency_ms / max(1, self._execution_count)

    def _error_rate(self) -> float:
        return self._error_count / max(1, self._execution_count)
