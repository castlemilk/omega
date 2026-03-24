"""
omega.nodes.victoria.risk_management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
RiskManagementNode — monitors portfolio risk and enforces position limits.

Improvement arc:
  v1.0 — Historical VaR (95%) via simple percentile
  v1.1 — CVaR (Expected Shortfall) added
  v1.2 — Correlation-adjusted position sizing (reduce concentration)
  v1.3 — Volatility-regime detection (tighten limits in high-vol regimes)
  v1.4 — Multi-persona risk debate (V-TR4): Aggressive / Conservative / Neutral consensus
"""

import logging
import math
import time
import uuid
from dataclasses import dataclass
from typing import Any

from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.victoria.risk_management")

_DEFAULT_VAR_CONFIDENCE = 0.95
_MAX_POSITION_SIZE = 0.25  # No single position > 25%
_MAX_PORTFOLIO_VAR = 0.02  # Daily VaR limit: 2% of portfolio

# VRP regime adjustments
_VRP_FEAR_POSITION_SCALE = 0.75  # FEAR: reduce max position by 25%
_VRP_CIRCUIT_BREAKER_ZSCORE = -2.0  # COMPLACENCY circuit breaker threshold

# ---------------------------------------------------------------------------
# V-TR4 — Multi-persona risk debate
# ---------------------------------------------------------------------------


@dataclass
class RiskPersona:
    """
    Parameter bundle for one risk evaluation persona.

    Each persona applies independent thresholds to the same portfolio and
    produces a recommendation.  The three built-in personas are:

    Aggressive   — tolerates larger drawdowns and higher concentration.
    Conservative — tighter stops, smaller positions, more cash.
    Neutral      — balanced view (mirrors the original single-persona logic).
    """

    name: str
    max_position: float  # largest allowed single-asset weight
    max_portfolio_var: float  # largest allowed daily VaR (fractional)
    max_correlation_threshold: float  # flag pairwise correlation above this
    vrp_fear_scale: float  # position-size multiplier in FEAR VRP regime
    var_confidence: float = 0.95  # historical VaR confidence level
    weight: float = 1.0 / 3  # consensus weight (sum across personas should = 1)


@dataclass
class PersonaDebateResult:
    """Result of running one persona's risk check on the portfolio."""

    persona_name: str
    recommendation: str  # "approve" | "reduce" | "reject"
    adjusted_weights: dict[str, float]
    violations: list[str]
    portfolio_var: float
    max_position_limit: float


@dataclass
class RiskDebateConsensus:
    """
    Aggregated outcome of the 3-persona risk debate.

    ``consensus_weights``  : weighted average of each persona's adjusted weights.
    ``persona_results``    : individual results for inspection / logging.
    ``recommendation``     : majority vote across personas.
    ``final_violations``   : violations flagged by at least 2 of 3 personas.
    ``position_scale``     : blended VRP position scale (weighted average).
    """

    consensus_weights: dict[str, float]
    persona_results: list[PersonaDebateResult]
    recommendation: str  # "approve" | "reduce" | "reject"
    final_violations: list[str]
    position_scale: float = 1.0


# Built-in personas (module-level constants so tests can import them directly)
PERSONA_AGGRESSIVE = RiskPersona(
    name="aggressive",
    max_position=0.35,  # allows up to 35% in one asset
    max_portfolio_var=0.04,  # tolerates up to 4% daily VaR
    max_correlation_threshold=0.95,  # only flags very high correlation
    vrp_fear_scale=0.85,  # mild reduction in FEAR regime
    weight=1.0 / 3,
)

PERSONA_CONSERVATIVE = RiskPersona(
    name="conservative",
    max_position=0.15,  # at most 15% in one asset
    max_portfolio_var=0.01,  # very tight 1% daily VaR limit
    max_correlation_threshold=0.75,  # flags moderate correlation
    vrp_fear_scale=0.50,  # halve positions in FEAR regime
    weight=1.0 / 3,
)

PERSONA_NEUTRAL = RiskPersona(
    name="neutral",
    max_position=_MAX_POSITION_SIZE,  # 25% — matches original logic
    max_portfolio_var=_MAX_PORTFOLIO_VAR,  # 2% — matches original logic
    max_correlation_threshold=0.90,
    vrp_fear_scale=_VRP_FEAR_POSITION_SCALE,
    weight=1.0 / 3,
)

_DEFAULT_PERSONAS = (PERSONA_AGGRESSIVE, PERSONA_CONSERVATIVE, PERSONA_NEUTRAL)


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
        self._vrp_regime = "NEUTRAL"
        self._vrp_zscore = 0.0
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
        return [
            "compute_var",
            "check_risk_limits",
            "compute_correlation",
            "apply_vrp_constraints",
            "risk_debate",
        ]

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
                vrp_regime = params.get("vrp_regime", self._vrp_regime)
                vrp_zscore = params.get("vrp_zscore", self._vrp_zscore)
                result = self._check_risk_limits(portfolio, market_data, vrp_regime, vrp_zscore)
            elif action == "compute_correlation":
                market_data = params.get("market_data", {})
                result = self._compute_correlation_matrix(market_data)
            elif action == "apply_vrp_constraints":
                vrp_regime = params.get("vrp_regime", "NEUTRAL")
                vrp_zscore = params.get("vrp_zscore", 0.0)
                self._vrp_regime = vrp_regime
                self._vrp_zscore = vrp_zscore
                result = self._apply_vrp_constraints(vrp_regime, vrp_zscore)
            elif action == "risk_debate":
                portfolio = params.get("portfolio", {})
                market_data = params.get("market_data", {})
                vrp_regime = params.get("vrp_regime", self._vrp_regime)
                vrp_zscore = params.get("vrp_zscore", self._vrp_zscore)
                debate = self.risk_debate(portfolio, market_data, vrp_regime, vrp_zscore)
                result = {
                    "consensus_weights": debate.consensus_weights,
                    "recommendation": debate.recommendation,
                    "final_violations": debate.final_violations,
                    "position_scale": debate.position_scale,
                    "personas": [
                        {
                            "name": pr.persona_name,
                            "recommendation": pr.recommendation,
                            "violations": pr.violations,
                            "portfolio_var": pr.portfolio_var,
                        }
                        for pr in debate.persona_results
                    ],
                }
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

    def _apply_vrp_constraints(self, vrp_regime: str, vrp_zscore: float) -> dict[str, Any]:
        """
        Compute VRP-based position sizing adjustments.

        FEAR        : IV >> RV — reduce max position by 25%, flag increased cash.
        COMPLACENCY : IV << RV — if zscore < -2sigma, trigger circuit breaker.
        NEUTRAL     : no adjustment.
        """
        adjustments: dict[str, Any] = {
            "vrp_regime": vrp_regime,
            "vrp_zscore": vrp_zscore,
            "position_scale": 1.0,
            "circuit_breaker": False,
            "notes": [],
        }

        if vrp_regime == "FEAR":
            adjustments["position_scale"] = _VRP_FEAR_POSITION_SCALE
            adjustments["notes"].append(
                f"FEAR regime (zscore={vrp_zscore:.2f}): max position scaled to "
                f"{_VRP_FEAR_POSITION_SCALE * 100:.0f}%"
            )
        elif vrp_regime == "COMPLACENCY" and vrp_zscore < _VRP_CIRCUIT_BREAKER_ZSCORE:
            adjustments["circuit_breaker"] = True
            adjustments["notes"].append(
                f"COMPLACENCY circuit breaker: vrp_zscore={vrp_zscore:.2f} < "
                f"{_VRP_CIRCUIT_BREAKER_ZSCORE:.1f}sigma — flagged for manual review"
            )
            logger.warning(
                "RiskManagementNode: VRP circuit breaker triggered (vrp_zscore=%.2f, regime=%s)",
                vrp_zscore,
                vrp_regime,
            )

        return adjustments

    def _check_risk_limits(
        self,
        portfolio: dict[str, Any],
        market_data: dict[str, Any],
        vrp_regime: str = "NEUTRAL",
        vrp_zscore: float = 0.0,
    ) -> dict[str, Any]:
        weights = portfolio.get("weights", {})
        violations: list[str] = []
        adjusted_weights: dict[str, float] = dict(weights)

        # VRP-based position size adjustment
        vrp_adj = self._apply_vrp_constraints(vrp_regime, vrp_zscore)
        effective_max_position = self._max_position * vrp_adj["position_scale"]
        if vrp_adj["notes"]:
            violations.extend(f"VRP: {note}" for note in vrp_adj["notes"])
        if vrp_adj["circuit_breaker"]:
            violations.append("VRP circuit breaker active — manual review required")

        # Position size limit (VRP-adjusted)
        for ticker, w in weights.items():
            if w > effective_max_position:
                violations.append(
                    f"{ticker}: weight {w:.1%} exceeds limit {effective_max_position:.1%}"
                )
                adjusted_weights[ticker] = effective_max_position

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
            "max_position_limit": effective_max_position,
            "vrp_regime": vrp_regime,
            "vrp_position_scale": vrp_adj["position_scale"],
            "vrp_circuit_breaker": vrp_adj["circuit_breaker"],
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

    # ------------------------------------------------------------------ V-TR4 multi-persona debate

    def risk_debate(
        self,
        portfolio: dict[str, Any],
        market_data: dict[str, Any],
        vrp_regime: str = "NEUTRAL",
        vrp_zscore: float = 0.0,
        personas: tuple[RiskPersona, ...] | None = None,
    ) -> RiskDebateConsensus:
        """
        Run the portfolio through 3 independent risk personas and return a consensus.

        Each persona applies its own thresholds to ``_check_persona()``.
        The consensus weights are a weighted average of each persona's adjusted weights.
        The final recommendation is determined by majority vote.
        Violations flagged by ≥2 personas are surfaced as ``final_violations``.

        Parameters
        ----------
        portfolio    : dict with ``weights`` key mapping ticker → float.
        market_data  : OHLCV data keyed by ticker (for VaR / correlation).
        vrp_regime   : "NEUTRAL" | "FEAR" | "COMPLACENCY"
        vrp_zscore   : Z-score of the current VRP signal.
        personas     : override the default 3-persona set (useful for tests).
        """
        active_personas = personas if personas is not None else _DEFAULT_PERSONAS
        persona_results: list[PersonaDebateResult] = []

        for persona in active_personas:
            result = self._check_persona(persona, portfolio, market_data, vrp_regime, vrp_zscore)
            persona_results.append(result)

        # Consensus weights: weighted average of each persona's adjusted_weights
        all_tickers: set[str] = set()
        for pr in persona_results:
            all_tickers.update(pr.adjusted_weights.keys())

        total_persona_weight = sum(p.weight for p in active_personas)
        consensus_weights: dict[str, float] = {}
        for ticker in all_tickers:
            blended = 0.0
            for persona, pr in zip(active_personas, persona_results, strict=True):
                w = pr.adjusted_weights.get(ticker, 0.0)
                blended += w * (persona.weight / total_persona_weight)
            consensus_weights[ticker] = blended

        # Renormalise
        total_w = sum(consensus_weights.values())
        if total_w > 0:
            consensus_weights = {k: v / total_w for k, v in consensus_weights.items()}

        # Majority vote on recommendation
        rec_counts: dict[str, float] = {}
        for persona, pr in zip(active_personas, persona_results, strict=True):
            rec_counts[pr.recommendation] = rec_counts.get(pr.recommendation, 0.0) + persona.weight
        recommendation = max(rec_counts, key=lambda r: rec_counts[r])

        # Violations flagged by ≥2 personas (compare after stripping persona prefix)
        def _bare(v: str) -> str:
            """Strip [persona_name] prefix for cross-persona deduplication."""
            if v.startswith("[") and "] " in v:
                return v.split("] ", 1)[1]
            return v

        bare_counts: dict[str, int] = {}
        bare_to_full: dict[str, str] = {}
        for pr in persona_results:
            seen_bare: set[str] = set()
            for v in pr.violations:
                b = _bare(v)
                if b not in seen_bare:
                    seen_bare.add(b)
                    bare_counts[b] = bare_counts.get(b, 0) + 1
                    bare_to_full.setdefault(b, v)
        final_violations = [bare_to_full[b] for b, cnt in bare_counts.items() if cnt >= 2]

        # Blended position scale (weighted average of per-persona effective scales)
        blended_scale = 0.0
        for persona in active_personas:
            vrp_scale = persona.vrp_fear_scale if vrp_regime == "FEAR" else 1.0
            blended_scale += vrp_scale * (persona.weight / total_persona_weight)

        return RiskDebateConsensus(
            consensus_weights=consensus_weights,
            persona_results=persona_results,
            recommendation=recommendation,
            final_violations=final_violations,
            position_scale=blended_scale,
        )

    def _check_persona(
        self,
        persona: RiskPersona,
        portfolio: dict[str, Any],
        market_data: dict[str, Any],
        vrp_regime: str,
        vrp_zscore: float,
    ) -> PersonaDebateResult:
        """Run a single persona's risk check and return its result."""
        weights = portfolio.get("weights", {})
        violations: list[str] = []
        adjusted_weights: dict[str, float] = dict(weights)

        # VRP position scaling for this persona
        position_scale = persona.vrp_fear_scale if vrp_regime == "FEAR" else 1.0
        if vrp_regime == "COMPLACENCY" and vrp_zscore < _VRP_CIRCUIT_BREAKER_ZSCORE:
            violations.append(f"[{persona.name}] VRP circuit breaker: vrp_zscore={vrp_zscore:.2f}")

        effective_max = persona.max_position * position_scale

        # Position size cap — use a normalised message so dedup works across personas
        for ticker, w in weights.items():
            if w > effective_max:
                # Format: "[persona] TICKER: N% exceeds position limit (persona limit: M%)"
                violations.append(f"[{persona.name}] {ticker}: {w:.1%} exceeds position limit")
                adjusted_weights[ticker] = effective_max

        # Renormalise
        total = sum(adjusted_weights.values())
        if total > 0:
            adjusted_weights = {k: v / total for k, v in adjusted_weights.items()}

        # Portfolio VaR — normalised message
        portfolio_returns = self._compute_portfolio_returns(adjusted_weights, market_data)
        portfolio_var = (
            self._historical_var(portfolio_returns, persona.var_confidence)
            if portfolio_returns
            else 0.0
        )
        if portfolio_var > persona.max_portfolio_var:
            violations.append(f"[{persona.name}] Portfolio VaR {portfolio_var:.2%} exceeds limit")

        # Correlation check
        if self._use_correlation and len(weights) >= 2:
            corr_matrix = self._compute_correlation_matrix(market_data)
            max_corr = corr_matrix.get("max_correlation", 0.0)
            if max_corr > persona.max_correlation_threshold:
                violations.append(f"[{persona.name}] High pairwise correlation: {max_corr:.2f}")

        # Recommendation
        if violations:
            recommendation = "reject" if len(violations) >= 3 else "reduce"
        else:
            recommendation = "approve"

        return PersonaDebateResult(
            persona_name=persona.name,
            recommendation=recommendation,
            adjusted_weights=adjusted_weights,
            violations=violations,
            portfolio_var=portfolio_var,
            max_position_limit=effective_max,
        )

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

    def signal_debate(
        self,
        signals: dict[str, Any],
        portfolio_weights: dict[str, float] | None = None,
        market_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Structured bull/bear debate on a proposed portfolio.

        Aggregates positive-direction signals into a bull_score and risk /
        negative-direction signals into a bear_score.  Optionally runs a
        full risk-limit check when portfolio_weights are provided.

        Returns a consensus dict with:
            bull_score     : float 0..1
            bear_score     : float 0..1
            recommendation : "go" | "hold" | "abort"
            violations     : list[str] — risk constraint breaches
            edge           : float — bull_score minus bear_score
        """
        market_data = market_data or {}
        portfolio_weights = portfolio_weights or {}

        bull_contributions: list[float] = []
        bear_contributions: list[float] = []

        for name, sig in signals.items():
            if name.startswith("_"):
                continue
            if not isinstance(sig, dict):
                continue
            value = float(sig.get("value", 0.0))
            confidence = float(sig.get("confidence", 0.5))
            weighted = abs(value) * confidence
            if value > 0:
                bull_contributions.append(weighted)
            elif value < 0:
                bear_contributions.append(weighted)

        bull_score = min(1.0, sum(bull_contributions) / max(len(bull_contributions), 1))
        bear_score = min(1.0, sum(bear_contributions) / max(len(bear_contributions), 1))

        # Risk-limit check (uses existing _check_risk_limits machinery)
        violations: list[str] = []
        if portfolio_weights:
            try:
                risk_result = self._check_risk_limits(
                    {"weights": portfolio_weights},
                    market_data,
                )
                violations = risk_result.get("violations", [])
            except Exception as exc:
                logger.debug("risk_debate: risk-limit check failed: %s", exc)

        edge = bull_score - bear_score
        if violations or edge < -0.1:
            recommendation = "abort"
        elif edge >= 0.2:
            recommendation = "go"
        else:
            recommendation = "hold"

        return {
            "bull_score": bull_score,
            "bear_score": bear_score,
            "recommendation": recommendation,
            "violations": violations,
            "edge": edge,
        }

    # ------------------------------------------------------------------ helpers

    def _avg_latency_ms(self) -> float:
        return self._total_latency_ms / max(1, self._execution_count)

    def _error_rate(self) -> float:
        return self._error_count / max(1, self._execution_count)
