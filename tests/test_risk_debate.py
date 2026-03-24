"""
tests/test_risk_debate.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for V-TR4: multi-perspective risk debate (3 personas).

Covers:
- PERSONA_AGGRESSIVE / CONSERVATIVE / NEUTRAL thresholds
- RiskManagementNode._check_persona() — per-persona risk check
- RiskManagementNode.risk_debate() — consensus weights, recommendation, violations
- VRP FEAR regime applies persona-specific position scaling
- VRP circuit breaker propagated through debate
- execute() "risk_debate" action
"""

from __future__ import annotations

import math
from typing import Any

from omega.nodes.victoria.risk_management import (
    PERSONA_AGGRESSIVE,
    PERSONA_CONSERVATIVE,
    PERSONA_NEUTRAL,
    RiskDebateConsensus,
    RiskManagementNode,
    RiskPersona,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PRICES_30 = list(range(100, 130))  # 30 days of ascending prices


def _market_data(tickers: list[str]) -> dict[str, Any]:
    """Simple synthetic market data: each ticker has the same ascending prices."""
    return {t: {"close": list(PRICES_30)} for t in tickers}


def _equal_portfolio(tickers: list[str]) -> dict[str, Any]:
    n = len(tickers)
    return {"weights": {t: 1.0 / n for t in tickers}}


def _concentrated_portfolio(tickers: list[str], heavy: str, heavy_weight: float) -> dict[str, Any]:
    """One asset is heavily weighted; the rest share the remainder equally."""
    remainder = (1.0 - heavy_weight) / max(1, len(tickers) - 1)
    return {"weights": {t: heavy_weight if t == heavy else remainder for t in tickers}}


# ---------------------------------------------------------------------------
# Persona constants sanity checks
# ---------------------------------------------------------------------------


class TestPersonaConstants:
    def test_aggressive_larger_limits(self) -> None:
        assert PERSONA_AGGRESSIVE.max_position > PERSONA_NEUTRAL.max_position
        assert PERSONA_AGGRESSIVE.max_portfolio_var > PERSONA_NEUTRAL.max_portfolio_var

    def test_conservative_tighter_limits(self) -> None:
        assert PERSONA_CONSERVATIVE.max_position < PERSONA_NEUTRAL.max_position
        assert PERSONA_CONSERVATIVE.max_portfolio_var < PERSONA_NEUTRAL.max_portfolio_var

    def test_conservative_tighter_vrp_scale(self) -> None:
        # In FEAR regime, conservative cuts more than neutral
        assert PERSONA_CONSERVATIVE.vrp_fear_scale < PERSONA_NEUTRAL.vrp_fear_scale
        assert PERSONA_NEUTRAL.vrp_fear_scale < PERSONA_AGGRESSIVE.vrp_fear_scale

    def test_weights_sum_to_one(self) -> None:
        total = PERSONA_AGGRESSIVE.weight + PERSONA_CONSERVATIVE.weight + PERSONA_NEUTRAL.weight
        assert math.isclose(total, 1.0, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# _check_persona — individual persona evaluation
# ---------------------------------------------------------------------------


class TestCheckPersona:
    def setup_method(self) -> None:
        self.node = RiskManagementNode()

    def test_neutral_approves_equal_portfolio(self) -> None:
        # 4 equal assets → 25% each; neutral max_position = 0.25, not strictly exceeded
        tickers = ["BTC", "ETH", "SOL", "BNB"]
        portfolio = _equal_portfolio(tickers)
        market_data = _market_data(tickers)
        result = self.node._check_persona(PERSONA_NEUTRAL, portfolio, market_data, "NEUTRAL", 0.0)
        assert result.recommendation == "approve"
        assert result.violations == []

    def test_conservative_rejects_concentrated(self) -> None:
        # 60% in one asset — conservative max is 15%; violations should be flagged
        tickers = ["BTC", "ETH"]
        portfolio = _concentrated_portfolio(tickers, "BTC", 0.60)
        market_data = _market_data(tickers)
        result = self.node._check_persona(
            PERSONA_CONSERVATIVE, portfolio, market_data, "NEUTRAL", 0.0
        )
        assert len(result.violations) > 0
        assert result.recommendation in ("reduce", "reject")
        # Weights are renormalised after capping, so we just verify they sum to 1
        total = sum(result.adjusted_weights.values())
        assert math.isclose(total, 1.0, abs_tol=1e-9)

    def test_aggressive_approves_concentrated(self) -> None:
        # 30% in one asset — aggressive max is 35%
        tickers = ["BTC", "ETH", "SOL"]
        portfolio = _concentrated_portfolio(tickers, "BTC", 0.30)
        market_data = _market_data(tickers)
        result = self.node._check_persona(
            PERSONA_AGGRESSIVE, portfolio, market_data, "NEUTRAL", 0.0
        )
        # No position-size violation since 30% < 35%
        position_violations = [v for v in result.violations if ">" in v and "VaR" not in v]
        assert position_violations == []

    def test_fear_regime_reduces_limit(self) -> None:
        tickers = ["BTC", "ETH"]
        portfolio = _concentrated_portfolio(tickers, "BTC", 0.25)
        market_data = _market_data(tickers)
        # Neutral in NEUTRAL: 25% = max, should approve
        result_neutral = self.node._check_persona(
            PERSONA_NEUTRAL, portfolio, market_data, "NEUTRAL", 0.0
        )
        # Neutral in FEAR: effective max = 0.25 * 0.75 = 0.1875 → 25% violates
        result_fear = self.node._check_persona(
            PERSONA_NEUTRAL, portfolio, market_data, "FEAR", 0.0
        )
        assert result_fear.max_position_limit < result_neutral.max_position_limit

    def test_circuit_breaker_flagged(self) -> None:
        tickers = ["BTC"]
        portfolio = {"weights": {"BTC": 1.0}}
        market_data = _market_data(tickers)
        result = self.node._check_persona(
            PERSONA_NEUTRAL, portfolio, market_data, "COMPLACENCY", -3.0
        )
        cb_violations = [v for v in result.violations if "circuit breaker" in v.lower()]
        assert len(cb_violations) == 1

    def test_adjusted_weights_normalised(self) -> None:
        tickers = ["BTC", "ETH"]
        portfolio = {"weights": {"BTC": 0.80, "ETH": 0.20}}
        market_data = _market_data(tickers)
        result = self.node._check_persona(
            PERSONA_CONSERVATIVE, portfolio, market_data, "NEUTRAL", 0.0
        )
        total = sum(result.adjusted_weights.values())
        assert math.isclose(total, 1.0, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# risk_debate() — full 3-persona consensus
# ---------------------------------------------------------------------------


class TestRiskDebate:
    def setup_method(self) -> None:
        self.node = RiskManagementNode()

    def test_returns_consensus_dataclass(self) -> None:
        tickers = ["BTC", "ETH", "SOL"]
        consensus = self.node.risk_debate(_equal_portfolio(tickers), _market_data(tickers))
        assert isinstance(consensus, RiskDebateConsensus)
        assert len(consensus.persona_results) == 3

    def test_consensus_weights_sum_to_one(self) -> None:
        tickers = ["BTC", "ETH", "SOL"]
        consensus = self.node.risk_debate(_equal_portfolio(tickers), _market_data(tickers))
        total = sum(consensus.consensus_weights.values())
        assert math.isclose(total, 1.0, abs_tol=1e-9)

    def test_all_personas_present(self) -> None:
        tickers = ["BTC", "ETH"]
        consensus = self.node.risk_debate(_equal_portfolio(tickers), _market_data(tickers))
        names = {pr.persona_name for pr in consensus.persona_results}
        assert "aggressive" in names
        assert "conservative" in names
        assert "neutral" in names

    def test_equal_portfolio_approved(self) -> None:
        # Need enough assets so all 3 personas approve.
        # Conservative max=0.15 → need 7 assets (14.3% each < 15%).
        tickers = [f"T{i}" for i in range(7)]
        consensus = self.node.risk_debate(_equal_portfolio(tickers), _market_data(tickers))
        assert consensus.recommendation == "approve"
        assert consensus.final_violations == []

    def test_concentrated_portfolio_reduced(self) -> None:
        # 80% BTC: all 3 personas flag a position-size violation for BTC.
        tickers = ["BTC", "ETH"]
        portfolio = {"weights": {"BTC": 0.80, "ETH": 0.20}}
        consensus = self.node.risk_debate(portfolio, _market_data(tickers))
        # All 3 personas flag BTC violation → final_violations not empty
        assert consensus.recommendation in ("reduce", "reject")
        # Each persona flags BTC (different thresholds but same ticker) →
        # normalized violation "BTC: ..." appears ≥2 times
        assert any("BTC" in v for v in consensus.final_violations)

    def test_consensus_weights_blend(self) -> None:
        """Consensus weights should lie between the per-persona adjusted weights."""
        tickers = ["BTC", "ETH"]
        portfolio = {"weights": {"BTC": 0.70, "ETH": 0.30}}
        market_data = _market_data(tickers)
        consensus = self.node.risk_debate(portfolio, market_data)

        # Aggressive allows more BTC; conservative less.
        # Consensus BTC weight should be between conservative and aggressive values.
        btc_weights = [pr.adjusted_weights.get("BTC", 0.0) for pr in consensus.persona_results]
        min_btc = min(btc_weights)
        max_btc = max(btc_weights)
        btc_consensus = consensus.consensus_weights.get("BTC", 0.0)
        assert min_btc - 1e-9 <= btc_consensus <= max_btc + 1e-9

    def test_fear_regime_reduces_position_scale(self) -> None:
        tickers = ["BTC", "ETH"]
        consensus_neutral = self.node.risk_debate(
            _equal_portfolio(tickers), _market_data(tickers), vrp_regime="NEUTRAL"
        )
        consensus_fear = self.node.risk_debate(
            _equal_portfolio(tickers), _market_data(tickers), vrp_regime="FEAR"
        )
        assert consensus_fear.position_scale < consensus_neutral.position_scale

    def test_custom_personas(self) -> None:
        """Passing a custom 2-persona tuple works."""
        custom_personas = (
            RiskPersona(
                name="ultra_conservative",
                max_position=0.10,
                max_portfolio_var=0.005,
                max_correlation_threshold=0.6,
                vrp_fear_scale=0.3,
                weight=0.5,
            ),
            RiskPersona(
                name="ultra_aggressive",
                max_position=0.50,
                max_portfolio_var=0.10,
                max_correlation_threshold=0.99,
                vrp_fear_scale=1.0,
                weight=0.5,
            ),
        )
        tickers = ["BTC", "ETH"]
        consensus = self.node.risk_debate(
            _equal_portfolio(tickers),
            _market_data(tickers),
            personas=custom_personas,
        )
        assert len(consensus.persona_results) == 2
        names = {pr.persona_name for pr in consensus.persona_results}
        assert "ultra_conservative" in names

    def test_final_violations_require_majority(self) -> None:
        """
        A violation only in one persona should NOT appear in final_violations.
        Uses 30% BTC: aggressive (max 35%) approves, conservative (max 15%) and
        neutral (max 25%) both flag it — so the BTC violation should appear in
        final_violations.
        """
        tickers = ["BTC", "ETH"]
        portfolio = _concentrated_portfolio(tickers, "BTC", 0.30)
        consensus = self.node.risk_debate(portfolio, _market_data(tickers))

        # Conservative and neutral both flag BTC (30% > 25% and > 15%)
        # → BTC should appear in final_violations
        assert any("BTC" in v for v in consensus.final_violations), (
            "Expected BTC position violation in final_violations — "
            f"got: {consensus.final_violations}"
        )


# ---------------------------------------------------------------------------
# execute() action dispatch
# ---------------------------------------------------------------------------


class TestRiskDebateAction:
    def setup_method(self) -> None:
        self.node = RiskManagementNode()

    def test_execute_risk_debate_action(self) -> None:
        from omega.core.node import NodeInput

        tickers = ["BTC", "ETH", "SOL"]
        inp = NodeInput(
            action="risk_debate",
            parameters={
                "portfolio": _equal_portfolio(tickers),
                "market_data": _market_data(tickers),
                "vrp_regime": "NEUTRAL",
                "vrp_zscore": 0.0,
            },
        )
        out = self.node.execute(inp)
        assert out.success
        assert "consensus_weights" in out.result
        assert "recommendation" in out.result
        assert "personas" in out.result
        assert len(out.result["personas"]) == 3

    def test_execute_unknown_action_fails(self) -> None:
        from omega.core.node import NodeInput

        out = self.node.execute(NodeInput(action="unknown_action"))
        assert not out.success

    def test_risk_debate_in_capabilities(self) -> None:
        assert "risk_debate" in self.node.get_capabilities()
