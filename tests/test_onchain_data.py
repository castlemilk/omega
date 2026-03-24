"""
Tests for OnChainDataNode.

Covers:
  - _compute_tvl_trend: BULLISH / BEARISH / NEUTRAL signals
  - 7d and 30d change calculations
  - history_override for deterministic testing
  - signal_value scaling by confidence
  - Node protocol: execute(), get_state(), get_capabilities()
  - Unknown action returns error
"""

import time

import pytest

from omega.core.node import NodeInput
from omega.nodes.victoria.onchain_data import (
    OnChainDataNode,
    _compute_tvl_trend,
)

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_history(n_days: int, start_tvl: float, end_tvl: float) -> list[dict]:
    """Generate synthetic TVL history with linear interpolation."""
    now = int(time.time())
    result = []
    for i in range(n_days):
        t = now - (n_days - 1 - i) * 86400
        frac = i / max(1, n_days - 1)
        tvl = start_tvl + (end_tvl - start_tvl) * frac
        result.append({"date": t, "tvl": tvl})
    return result


def _make_node() -> OnChainDataNode:
    return OnChainDataNode()


def _call(node: OnChainDataNode, history: list[dict]) -> dict:
    out = node.execute(
        NodeInput(
            action="fetch_onchain",
            parameters={"history_override": history},
        )
    )
    assert out.success, out.errors
    return out.result  # type: ignore[no-any-return]


# ─── Unit tests: _compute_tvl_trend ──────────────────────────────────────────


def test_bullish_signal_when_tvl_rising():
    # Need > 5% in 7d: use ~60% total over 40 days → ~7.2% in 7d
    history = _make_history(n_days=40, start_tvl=50e9, end_tvl=80e9)
    result = _compute_tvl_trend(history)
    assert result["signal"] == "BULLISH"
    assert result["tvl_7d_change"] > 0
    assert result["confidence"] > 0.5


def test_bearish_signal_when_tvl_falling():
    # Need < -5% in 7d: ~-30% total over 40 days → ~-5.4% in 7d
    history = _make_history(n_days=40, start_tvl=100e9, end_tvl=75e9)
    result = _compute_tvl_trend(history)
    assert result["signal"] == "BEARISH"
    assert result["tvl_7d_change"] < 0
    assert result["confidence"] > 0.5


def test_neutral_signal_when_tvl_flat():
    # < 5% change over 7 days: ~1% total over 40 days
    history = _make_history(n_days=40, start_tvl=90e9, end_tvl=90.5e9)
    result = _compute_tvl_trend(history)
    assert result["signal"] == "NEUTRAL"


def test_empty_history_returns_neutral():
    result = _compute_tvl_trend([])
    assert result["signal"] == "NEUTRAL"
    assert result["confidence"] == 0.0
    assert result["current_tvl"] is None


def test_single_entry_returns_neutral():
    result = _compute_tvl_trend([{"date": int(time.time()), "tvl": 90e9}])
    assert result["signal"] == "NEUTRAL"


def test_current_tvl_is_latest_entry():
    history = _make_history(n_days=30, start_tvl=80e9, end_tvl=95e9)
    result = _compute_tvl_trend(history)
    assert result["current_tvl"] == pytest.approx(95e9, rel=0.01)


def test_tvl_7d_change_computed_correctly():
    """With linear history, 7d change should be approximately 7/34 of total change."""
    history = _make_history(n_days=35, start_tvl=90e9, end_tvl=99e9)  # +10%
    result = _compute_tvl_trend(history)
    assert result["tvl_7d_change"] is not None
    # 7 out of 34 days of +10% → roughly +2%
    assert 0.005 < result["tvl_7d_change"] < 0.05


def test_30d_change_available_with_enough_history():
    history = _make_history(n_days=60, start_tvl=80e9, end_tvl=100e9)
    result = _compute_tvl_trend(history)
    assert result["tvl_30d_change"] is not None


def test_confidence_is_bounded():
    history = _make_history(n_days=40, start_tvl=100e9, end_tvl=50e9)  # -50%
    result = _compute_tvl_trend(history)
    assert 0.0 <= result["confidence"] <= 1.0


# ─── Node execute() tests ────────────────────────────────────────────────────


def test_execute_bullish():
    node = _make_node()
    history = _make_history(n_days=40, start_tvl=50e9, end_tvl=80e9)
    result = _call(node, history)
    assert result["signal"] == "BULLISH"
    assert result["signal_value"] > 0


def test_execute_bearish():
    node = _make_node()
    history = _make_history(n_days=40, start_tvl=100e9, end_tvl=75e9)
    result = _call(node, history)
    assert result["signal"] == "BEARISH"
    assert result["signal_value"] < 0


def test_execute_returns_all_required_keys():
    node = _make_node()
    history = _make_history(n_days=40, start_tvl=90e9, end_tvl=92e9)
    result = _call(node, history)
    required = {
        "current_tvl",
        "tvl_7d_change",
        "tvl_30d_change",
        "signal",
        "signal_value",
        "confidence",
        "data_source",
        "data_points",
    }
    assert required.issubset(set(result.keys()))


def test_execute_data_source_override():
    node = _make_node()
    history = _make_history(n_days=40, start_tvl=90e9, end_tvl=95e9)
    result = _call(node, history)
    assert result["data_source"] == "override"


def test_execute_data_points_matches_history_length():
    node = _make_node()
    history = _make_history(n_days=40, start_tvl=90e9, end_tvl=95e9)
    result = _call(node, history)
    assert result["data_points"] == 40


def test_execute_empty_history_returns_neutral():
    node = _make_node()
    result = _call(node, [])
    assert result["signal"] == "NEUTRAL"
    assert result["confidence"] == 0.0


def test_execute_unknown_action_returns_error():
    node = _make_node()
    out = node.execute(NodeInput(action="unknown_action", parameters={}))
    assert not out.success
    assert "unknown action" in out.errors[0].lower()


def test_signal_value_is_zero_for_neutral():
    node = _make_node()
    history = _make_history(n_days=40, start_tvl=90e9, end_tvl=90.1e9)  # ~0.1%
    result = _call(node, history)
    assert result["signal"] == "NEUTRAL"
    assert result["signal_value"] == pytest.approx(0.0, abs=0.2)


# ─── Node protocol tests ─────────────────────────────────────────────────────


def test_get_capabilities():
    node = _make_node()
    caps = node.get_capabilities()
    assert "on_chain_metrics" in caps
    assert "tvl_trend" in caps
    assert "ONCHAIN_DATA" in caps


def test_get_state_after_execution():
    node = _make_node()
    history = _make_history(n_days=40, start_tvl=50e9, end_tvl=80e9)
    _call(node, history)
    state = node.get_state()
    assert state.name == "OnChainDataNode"
    assert state.health == 1.0
    assert state.metrics["execution_count"] == 1.0
    assert state.metadata["last_signal"] == "BULLISH"


def test_describe_is_non_empty():
    node = _make_node()
    assert len(node.describe()) > 20


# ─── Alias actions ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "action",
    ["fetch_onchain", "on_chain_metrics", "tvl_trend", "ONCHAIN_DATA"],
)
def test_all_action_aliases_work(action: str):
    node = _make_node()
    history = _make_history(n_days=40, start_tvl=90e9, end_tvl=95e9)
    out = node.execute(NodeInput(action=action, parameters={"history_override": history}))
    assert out.success
