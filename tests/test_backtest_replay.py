"""Fast regressions for historical input isolation in the backtest bridge."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

from omega.core.actions import NodeAction
from omega.core.node import NodeInput, NodeOutput
from omega.eval.backtest_bridge import OmegaBacktestBridge
from omega.nodes.victoria.victoria_node import VictoriaNode


@pytest.mark.parametrize("window", [{}, {"BTCUSDT": {"close": [100.0, 101.0]}}])
def test_replay_poll_preserves_supplied_window(
    window: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = OmegaBacktestBridge()
    bridge._node._last_market_data = window
    live = {"LIVE": {"close": [999.0]}}
    ingestion = Mock(return_value=NodeOutput(success=True, result=live))
    monkeypatch.setattr(bridge._node._ingestion, "execute", ingestion)

    output = bridge._node.execute(NodeInput(action=NodeAction.POLL.value))

    assert output.success
    assert output.result == window
    assert bridge._node._last_market_data is window
    ingestion.assert_not_called()


def test_live_victoria_poll_still_uses_ingestion(monkeypatch: pytest.MonkeyPatch) -> None:
    node = VictoriaNode()
    live = {"BTCUSDT": {"close": [999.0]}}
    ingestion = Mock(return_value=NodeOutput(success=True, result=live))
    monkeypatch.setattr(node._ingestion, "execute", ingestion)

    output = node.execute(NodeInput(action=NodeAction.POLL.value))

    assert output.success
    assert output.result == live
    ingestion.assert_called_once()


def test_each_replay_cycle_feeds_its_historical_window_to_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = OmegaBacktestBridge(lookback_window=2)
    live = {"LIVE": {"close": [999.0]}}
    ingestion = Mock(return_value=NodeOutput(success=True, result=live))
    monkeypatch.setattr(bridge._node._ingestion, "execute", ingestion)
    windows: list[dict[str, Any]] = []

    def record_signals(inp: NodeInput) -> dict[str, Any]:
        windows.append(inp.parameters["market_data"])
        return {}

    monkeypatch.setattr(bridge._node, "_do_compute_signals", record_signals)
    monkeypatch.setattr(bridge._node, "_do_construct_portfolio", Mock(return_value=[]))
    monkeypatch.setattr(bridge._orchestrator, "_heartbeat", Mock())
    bars = [
        {
            "timestamp": i,
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.5 + i,
            "volume": 1_000.0,
        }
        for i in range(6)
    ]

    result = bridge.run(bars)

    assert result.n_cycles == 3
    assert [w[bridge.ticker]["close"] for w in windows] == [
        [100.5, 101.5, 102.5],
        [101.5, 102.5, 103.5],
        [102.5, 103.5, 104.5],
    ]
    ingestion.assert_not_called()
