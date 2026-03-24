"""
Tests for LiquidationCascadeNode.

Covers:
  - cascade_probability_from_funding thresholds
  - HIGH_LONG / HIGH_SHORT / LOW risk labels
  - funding_rate_override for deterministic testing
  - nearest_cluster calculation
  - Node protocol: execute(), get_state(), get_capabilities()
  - Unknown action returns error
"""

import pytest

from omega.core.node import NodeInput
from omega.nodes.victoria.liquidation_cascade import (
    LiquidationCascadeNode,
    MockLiquidationDataSource,
    _cascade_probability_from_funding,
    _nearest_cluster,
)

# ─── Unit tests: _cascade_probability_from_funding ───────────────────────────


def test_long_cascade_above_threshold():
    prob, label = _cascade_probability_from_funding(0.0006)  # > 0.0005
    assert label == "HIGH_LONG"
    assert prob > 0.6


def test_short_cascade_below_threshold():
    prob, label = _cascade_probability_from_funding(-0.0004)  # < -0.0003
    assert label == "HIGH_SHORT"
    assert prob > 0.6


def test_neutral_zone_low_risk():
    prob, label = _cascade_probability_from_funding(0.0001)
    assert label == "LOW"
    assert prob < 0.4


def test_zero_funding_low_risk():
    prob, label = _cascade_probability_from_funding(0.0)
    assert label == "LOW"
    assert 0.0 <= prob <= 0.4


def test_extreme_long_capped_at_0_95():
    prob, label = _cascade_probability_from_funding(0.01)  # very high
    assert label == "HIGH_LONG"
    assert prob <= 0.95


def test_extreme_short_capped_at_0_95():
    prob, label = _cascade_probability_from_funding(-0.01)
    assert label == "HIGH_SHORT"
    assert prob <= 0.95


def test_boundary_just_above_long_threshold():
    """Funding rate just above threshold → HIGH_LONG, minimal elevation."""
    prob, label = _cascade_probability_from_funding(0.00051)
    assert label == "HIGH_LONG"
    assert 0.6 <= prob <= 0.65


def test_boundary_exactly_at_long_threshold_is_neutral():
    """Funding rate exactly at threshold (not strictly above) → LOW."""
    _prob, label = _cascade_probability_from_funding(0.0005)
    assert label == "LOW"


def test_negative_boundary_just_below_short_threshold():
    prob, label = _cascade_probability_from_funding(-0.00031)
    assert label == "HIGH_SHORT"
    assert 0.6 <= prob <= 0.65


def test_negative_boundary_exactly_at_threshold_is_neutral():
    """Funding rate exactly at threshold (not strictly below) → LOW."""
    _prob, label = _cascade_probability_from_funding(-0.0003)
    assert label == "LOW"


# ─── Unit tests: _nearest_cluster ────────────────────────────────────────────


def test_nearest_cluster_picks_highest_value():
    btc_price = 50_000.0
    clusters = [
        {"price": 49_000.0, "long_liquidations_usd": 10e6, "short_liquidations_usd": 5e6},
        {"price": 48_000.0, "long_liquidations_usd": 100e6, "short_liquidations_usd": 50e6},
    ]
    price, dist = _nearest_cluster(clusters, btc_price)
    assert price == 48_000.0
    assert dist == pytest.approx(4.0, rel=0.05)


def test_nearest_cluster_empty_list():
    price, dist = _nearest_cluster([], 50_000.0)
    assert price is None
    assert dist is None


def test_nearest_cluster_zero_price():
    clusters = [{"price": 49_000.0, "long_liquidations_usd": 1e6, "short_liquidations_usd": 0}]
    price, _dist = _nearest_cluster(clusters, 0.0)
    assert price is None


# ─── Unit tests: MockLiquidationDataSource ───────────────────────────────────


def test_mock_clusters_returns_four_levels():
    mock = MockLiquidationDataSource()
    data = mock.fetch_clusters(50_000.0)
    assert data["source"] == "mock"
    assert len(data["clusters"]) == 4


def test_mock_clusters_symmetric_around_price():
    mock = MockLiquidationDataSource()
    btc = 100_000.0
    data = mock.fetch_clusters(btc)
    prices = [c["price"] for c in data["clusters"]]
    below = [p for p in prices if p < btc]
    above = [p for p in prices if p > btc]
    assert len(below) >= 1
    assert len(above) >= 1


# ─── Node execute() tests ────────────────────────────────────────────────────


def _make_node() -> LiquidationCascadeNode:
    return LiquidationCascadeNode()


def _call(node: LiquidationCascadeNode, **params) -> dict:
    out = node.execute(
        NodeInput(
            action="monitor_liquidations",
            parameters=params,
        )
    )
    assert out.success, out.errors
    return out.result  # type: ignore[no-any-return]


def test_execute_with_high_long_funding():
    node = _make_node()
    result = _call(node, funding_rate_override=0.001)
    assert result["funding_rate_signal"] == "HIGH_LONG"
    assert result["cascade_probability"] > 0.6
    assert result["confidence"] > 0.0


def test_execute_with_high_short_funding():
    node = _make_node()
    result = _call(node, funding_rate_override=-0.0005)
    assert result["funding_rate_signal"] == "HIGH_SHORT"
    assert result["cascade_probability"] > 0.6


def test_execute_with_neutral_funding():
    node = _make_node()
    result = _call(node, funding_rate_override=0.0001)
    assert result["funding_rate_signal"] == "LOW"
    assert result["cascade_probability"] < 0.4


def test_execute_returns_all_required_keys():
    node = _make_node()
    result = _call(node, funding_rate_override=0.0002)
    required = {
        "cascade_probability",
        "leverage_ratio",
        "funding_rate",
        "funding_rate_signal",
        "nearest_liquidation_cluster",
        "distance_to_cluster",
        "data_source",
        "confidence",
    }
    assert required.issubset(set(result.keys()))


def test_execute_with_market_data_extracts_btc_price():
    node = _make_node()
    market_data = {"close": [45_000.0, 46_000.0, 47_000.0]}
    result = _call(node, funding_rate_override=0.0001, market_data=market_data)
    # Should have cluster data since price was extractable
    assert result["nearest_liquidation_cluster"] is not None
    assert result["distance_to_cluster"] is not None


def test_execute_without_market_data():
    node = _make_node()
    result = _call(node, funding_rate_override=0.0001)
    # No price → no cluster data
    assert result["nearest_liquidation_cluster"] is None
    assert result["distance_to_cluster"] is None


def test_execute_unknown_action_returns_error():
    node = _make_node()
    out = node.execute(NodeInput(action="unknown_action", parameters={}))
    assert not out.success
    assert "unknown action" in out.errors[0].lower()


def test_leverage_ratio_scales_with_funding():
    node = _make_node()
    r_low = _call(node, funding_rate_override=0.0001)
    r_high = _call(node, funding_rate_override=0.001)
    assert r_high["leverage_ratio"] > r_low["leverage_ratio"]


# ─── Node protocol tests ─────────────────────────────────────────────────────


def test_get_capabilities():
    node = _make_node()
    caps = node.get_capabilities()
    assert "liquidation_monitor" in caps
    assert "cascade_probability" in caps
    assert "LIQUIDATION_CASCADE" in caps


def test_get_state():
    node = _make_node()
    _call(node, funding_rate_override=0.0002)
    state = node.get_state()
    assert state.name == "LiquidationCascadeNode"
    assert state.health == 1.0
    assert state.metrics["execution_count"] == 1.0


def test_describe_is_non_empty():
    node = _make_node()
    assert len(node.describe()) > 20


# ─── Alias actions ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "action",
    ["monitor_liquidations", "liquidation_monitor", "cascade_probability", "LIQUIDATION_CASCADE"],
)
def test_all_action_aliases_work(action: str):
    node = _make_node()
    out = node.execute(NodeInput(action=action, parameters={"funding_rate_override": 0.0002}))
    assert out.success
