"""Fast numerical regressions for ablation metrics; no simulation cycles."""

from __future__ import annotations

import math
from decimal import Decimal, localcontext

import pytest

from omega.eval.ablation import _AblationNode, _sharpe_from_returns


def _decimal_sharpe(returns: list[float], risk_free: float = 0.0) -> float:
    """Reference the exact supplied floats, including the daily risk-free subtraction."""
    if len(returns) < 2:
        return 0.0
    with localcontext() as ctx:
        ctx.prec = 100
        excess = [Decimal.from_float(r - risk_free / 252) for r in returns]
        mean = sum(excess, Decimal(0)) / len(excess)
        variance = sum(((r - mean) ** 2 for r in excess), Decimal(0)) / (len(excess) - 1)
        if variance == 0:
            return 0.0
        return float(mean / variance.sqrt() * Decimal(252).sqrt())


@pytest.mark.parametrize("value", [0.0, 0.001, -0.001, 0.1, -0.1])
@pytest.mark.parametrize("count", [2, 3, 252])
@pytest.mark.parametrize("risk_free", [0.0, 0.0252])
def test_identical_returns_have_zero_sharpe(value: float, count: int, risk_free: float) -> None:
    assert _sharpe_from_returns([value] * count, risk_free=risk_free) == 0.0


@pytest.mark.parametrize("returns", [[], [0.001]])
def test_insufficient_returns_have_zero_sharpe(returns: list[float]) -> None:
    assert _sharpe_from_returns(returns) == 0.0


@pytest.mark.parametrize(
    "returns",
    [
        [0.01, 0.03],
        [-0.02, 0.01, 0.04],
        [-0.02, -0.01, 0.0],
        [-0.01, 0.01],
        [0.001, -0.002, 0.003, -0.004, 0.005] * 50,
    ],
)
@pytest.mark.parametrize("risk_free", [0.0, 0.0252])
def test_mixed_returns_match_sample_sharpe_reference(
    returns: list[float], risk_free: float
) -> None:
    expected = _decimal_sharpe(returns, risk_free)
    assert _sharpe_from_returns(returns, risk_free) == pytest.approx(expected, rel=1e-14, abs=0)


@pytest.mark.parametrize("value", [0.001, -0.001])
@pytest.mark.parametrize("count", [3, 252])
def test_adjacent_float_returns_keep_their_nonzero_variation(value: float, count: int) -> None:
    adjacent = math.nextafter(value, math.inf)
    returns = [value] * (count - 1) + [adjacent]
    expected = _decimal_sharpe(returns)
    actual = _sharpe_from_returns(returns)
    # One representable step is real variation, even far below common epsilon cutoffs.
    assert actual != 0.0
    assert math.isfinite(actual)
    assert actual == pytest.approx(expected, rel=1e-14, abs=0)


@pytest.mark.parametrize(
    "returns",
    [
        [0.001] * 252,
        [-0.001] * 252,
        [-0.02, 0.01, 0.04],
        [0.001] * 251 + [math.nextafter(0.001, math.inf)],
    ],
)
def test_node_evaluation_matches_sample_sharpe_reference(returns: list[float]) -> None:
    node = _AblationNode(seed=42)
    node._returns = list(returns)
    assert node.evaluate()["sharpe"] == pytest.approx(_decimal_sharpe(returns), rel=1e-14, abs=0)
