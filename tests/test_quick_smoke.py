"""
tests/test_quick_smoke.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
5-second smoke test: verifies imports, one full signal→portfolio cycle, and output structure.

Run before every training iteration to catch import errors and API breakage:
  pytest tests/test_quick_smoke.py -v

All tests in this file must complete in < 5 seconds.
"""

from __future__ import annotations

import math
import uuid


# ---------------------------------------------------------------------------
# Helpers (defined at module level so they don't contribute to import time)
# ---------------------------------------------------------------------------


def _ohlcv(n: int = 50, base: float = 1_000.0, trend: float = 0.002, seed: int = 0) -> dict:
    prices = [
        max(0.01, base * (1.0 + trend) ** i + base * 0.01 * math.sin(i + seed))
        for i in range(n)
    ]
    return {
        "close": prices,
        "adjclose": prices,
        "open": [p * 0.999 for p in prices],
        "high": [p * 1.005 for p in prices],
        "low": [p * 0.995 for p in prices],
        "volume": [1_000_000.0 for _ in range(n)],
    }


def _market_data() -> dict:
    return {
        "BTCUSDT": _ohlcv(n=50, base=60_000.0, trend=+0.004, seed=1),
        "ETHUSDT": _ohlcv(n=50, base=3_000.0,  trend=+0.002, seed=2),
        "SOLUSDT": _ohlcv(n=50, base=150.0,    trend= 0.000, seed=3),
        "BNBUSDT": _ohlcv(n=50, base=400.0,    trend=-0.002, seed=4),
        "ADAUSDT": _ohlcv(n=50, base=0.50,     trend=-0.004, seed=5),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_signal_generation_imports():
    """Smoke: signal_generation module imports without error."""
    from omega.nodes.victoria.signal_generation import SignalGenerationNode  # noqa: F401

    assert SignalGenerationNode is not None


def test_strategy_imports():
    """Smoke: strategy module imports without error."""
    from omega.nodes.victoria.strategy import (  # noqa: F401
        ConvictionLevel,
        StrategyNode,
        conviction_size_multiplier,
        score_to_conviction,
    )

    assert StrategyNode is not None
    assert len(list(ConvictionLevel)) == 5


def test_conviction_level_enum_complete():
    """Smoke: ConvictionLevel must have exactly 5 levels with correct integer values."""
    from omega.nodes.victoria.strategy import ConvictionLevel

    assert ConvictionLevel.STRONG_BUY == 2
    assert ConvictionLevel.BUY == 1
    assert ConvictionLevel.HOLD == 0
    assert ConvictionLevel.SELL == -1
    assert ConvictionLevel.STRONG_SELL == -2


def test_one_cycle_signal_generation():
    """Smoke: SignalGenerationNode.execute() returns a valid signals dict."""
    from omega.core.node import NodeInput
    from omega.nodes.victoria.signal_generation import SignalGenerationNode

    node = SignalGenerationNode()
    node._use_rsi = True
    node._use_zscore = True

    out = node.execute(
        NodeInput(
            request_id=str(uuid.uuid4()),
            action="compute_signals",
            parameters={"market_data": _market_data()},
        )
    )

    assert out.success, f"Signal generation failed: {out.errors}"
    assert isinstance(out.result, dict), "result must be a dict"

    # Must produce composites for the tickers
    composites = {
        t: sig["composite"]
        for t, sig in out.result.items()
        if isinstance(sig, dict) and "composite" in sig and not t.startswith("_")
    }
    assert len(composites) >= 3, f"Expected ≥3 composites, got {len(composites)}"

    # All composites must be finite floats in a reasonable range
    for ticker, v in composites.items():
        assert math.isfinite(v), f"{ticker} composite={v} is not finite"
        assert -10.0 <= v <= 10.0, f"{ticker} composite={v} is out of expected range"


def test_one_cycle_portfolio_construction():
    """Smoke: StrategyNode.execute(construct_portfolio) returns expected keys."""
    from omega.core.node import NodeInput
    from omega.nodes.victoria.signal_generation import SignalGenerationNode
    from omega.nodes.victoria.strategy import StrategyNode

    market_data = _market_data()

    # -- signals --
    sig_node = SignalGenerationNode()
    sig_node._use_rsi = True
    sig_out = sig_node.execute(
        NodeInput(
            request_id=str(uuid.uuid4()),
            action="compute_signals",
            parameters={"market_data": market_data},
        )
    )
    assert sig_out.success, f"Signal step failed: {sig_out.errors}"

    # -- portfolio --
    strat_node = StrategyNode()
    port_out = strat_node.execute(
        NodeInput(
            request_id=str(uuid.uuid4()),
            action="construct_portfolio",
            parameters={"signals": sig_out.result, "market_data": market_data},
        )
    )
    assert port_out.success, f"Portfolio step failed: {port_out.errors}"

    result = port_out.result
    assert isinstance(result, dict), "Portfolio result must be a dict"

    # Required structural keys
    for key in ("weights", "positions", "conviction_distribution"):
        assert key in result, f"Missing required key '{key}' in portfolio output"

    assert isinstance(result["weights"], dict)
    assert isinstance(result["positions"], int)
    assert isinstance(result["conviction_distribution"], dict)

    # Absolute weight sum must be ≤ 1.0 (may be less due to Fiedler/risk-manager scaling)
    # Signed sum may differ from 1.0 when longs and shorts are mixed.
    if result["weights"]:
        abs_total = sum(abs(w) for w in result["weights"].values())
        assert 0.0 < abs_total <= 1.0 + 1e-6, (
            f"Portfolio |weights| sum to {abs_total:.6f} (expected 0 < x ≤ 1.0)"
        )
        for ticker, w in result["weights"].items():
            assert math.isfinite(w), f"Weight for {ticker!r} is not finite: {w}"

    # All conviction levels must be present in distribution
    from omega.nodes.victoria.strategy import ConvictionLevel

    dist = result["conviction_distribution"]
    for level in ConvictionLevel:
        assert level.name in dist, f"conviction_distribution missing '{level.name}'"


def test_one_cycle_output_types():
    """Smoke: verify key output field types are correct (no type coercion surprises)."""
    from omega.core.node import NodeInput
    from omega.nodes.victoria.signal_generation import SignalGenerationNode
    from omega.nodes.victoria.strategy import StrategyNode

    market_data = _market_data()

    sig_out = SignalGenerationNode().execute(
        NodeInput(
            request_id=str(uuid.uuid4()),
            action="compute_signals",
            parameters={"market_data": market_data},
        )
    )
    port_out = StrategyNode().execute(
        NodeInput(
            request_id=str(uuid.uuid4()),
            action="construct_portfolio",
            parameters={"signals": sig_out.result, "market_data": market_data},
        )
    )

    assert sig_out.success and port_out.success

    result = port_out.result

    # proposals_generated must be an int
    if "proposals_generated" in result:
        assert isinstance(result["proposals_generated"], int), (
            f"proposals_generated is {type(result['proposals_generated'])}, expected int"
        )

    # convictions values must be strings (level names)
    if "convictions" in result:
        for ticker, level_name in result["convictions"].items():
            assert isinstance(level_name, str), (
                f"conviction for {ticker!r} is {type(level_name)}, expected str"
            )


def test_signals_have_required_per_ticker_keys():
    """Smoke: each ticker's signal dict must have 'composite', 'price', 'ticker' keys."""
    from omega.core.node import NodeInput
    from omega.nodes.victoria.signal_generation import SignalGenerationNode

    node = SignalGenerationNode()
    out = node.execute(
        NodeInput(
            request_id=str(uuid.uuid4()),
            action="compute_signals",
            parameters={"market_data": _market_data()},
        )
    )
    assert out.success

    for ticker, sig in out.result.items():
        if ticker.startswith("_") or not isinstance(sig, dict):
            continue
        assert "composite" in sig, f"{ticker}: missing 'composite' key"
        assert "price" in sig, f"{ticker}: missing 'price' key"
        assert "ticker" in sig, f"{ticker}: missing 'ticker' key"
        assert sig["ticker"] == ticker, (
            f"ticker mismatch: sig['ticker']={sig['ticker']!r} != key {ticker!r}"
        )
