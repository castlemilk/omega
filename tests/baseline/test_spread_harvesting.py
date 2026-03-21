"""Test 1: Simple Spread Harvesting — PICO vs Omega comparison.

PICO (NoBrain): fixed symmetric spread capture with static threshold.
Omega (Brain): parameter-optimised spread capture (AI-tuned params).

Tests verify that the Sharpe delta measurement infrastructure works correctly
so Phase 1 evaluation is valid.
"""

import math

from tests.baseline.conftest import cumprod, max_drawdown, sharpe_ratio

# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------


def run_spread_harvesting_nobrain(snapshots: list, *, entry_bps: float = 2.0) -> list[float]:
    """PICO: fixed rule — enter whenever spread >= entry_bps, exit next tick."""
    trades = []
    for snap in snapshots:
        if snap["spread_bps"] >= entry_bps:
            gross = snap["spread_bps"] / 20000
            net = gross - 0.5 / 10000
            trades.append(net)
        else:
            trades.append(0.0)
    return trades


def run_spread_harvesting_brain(
    snapshots: list, *, entry_bps: float = 1.5, size_scale: float = 1.3
) -> list[float]:
    """Omega: AI-optimised — lower threshold, scaled by book depth."""
    trades = []
    for snap in snapshots:
        if snap["spread_bps"] >= entry_bps:
            gross = snap["spread_bps"] / 20000
            total_bid = sum(s for _, s in snap["bids"][:2])
            total_ask = sum(s for _, s in snap["asks"][:2])
            depth_ratio = min(total_bid, total_ask) / (total_bid + total_ask + 1e-9)
            size_factor = 1.0 + (depth_ratio - 0.5) * size_scale
            net = gross * size_factor - 0.5 / 10000
            trades.append(net)
        else:
            trades.append(0.0)
    return trades


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSpreadHarvesting:
    def test_nobrain_produces_nonzero_returns(self, synthetic_order_book):
        returns = run_spread_harvesting_nobrain(synthetic_order_book)
        assert len(returns) == len(synthetic_order_book)
        nonzero = sum(1 for r in returns if r != 0.0)
        assert nonzero > 0, "NoBrain never traded — check entry_bps vs spread range"

    def test_brain_produces_more_trades(self, synthetic_order_book):
        """Lower threshold means Brain enters more often."""
        nb = run_spread_harvesting_nobrain(synthetic_order_book)
        br = run_spread_harvesting_brain(synthetic_order_book)
        nb_trades = sum(1 for r in nb if r != 0.0)
        br_trades = sum(1 for r in br if r != 0.0)
        assert br_trades >= nb_trades, (
            f"Brain ({br_trades}) should trade at least as often as NoBrain ({nb_trades})"
        )

    def test_sharpe_is_trackable(self, synthetic_order_book):
        """Sharpe ratio is computable and finite for both modes."""
        nb_ret = run_spread_harvesting_nobrain(synthetic_order_book)
        br_ret = run_spread_harvesting_brain(synthetic_order_book)

        nb_sharpe = sharpe_ratio(nb_ret)
        br_sharpe = sharpe_ratio(br_ret)

        assert math.isfinite(nb_sharpe), "NoBrain Sharpe is not finite"
        assert math.isfinite(br_sharpe), "Brain Sharpe is not finite"

    def test_sharpe_delta_is_measurable(self, synthetic_order_book):
        """The Sharpe improvement metric can be recorded."""
        nb_ret = run_spread_harvesting_nobrain(synthetic_order_book)
        br_ret = run_spread_harvesting_brain(synthetic_order_book)

        nb_sharpe = sharpe_ratio(nb_ret)
        br_sharpe = sharpe_ratio(br_ret)
        delta = br_sharpe - nb_sharpe

        assert isinstance(delta, float)
        assert math.isfinite(delta)
        print(
            f"\nSpread Harvesting Sharpe — NoBrain: {nb_sharpe:.3f}, Brain: {br_sharpe:.3f}, Delta: {delta:+.3f}"
        )

    def test_max_drawdown_tracked(self, synthetic_order_book):
        """Max drawdown can be computed for both modes."""
        nb_ret = run_spread_harvesting_nobrain(synthetic_order_book)
        br_ret = run_spread_harvesting_brain(synthetic_order_book)

        nb_eq = cumprod(nb_ret)
        br_eq = cumprod(br_ret)

        nb_dd = max_drawdown(nb_eq)
        br_dd = max_drawdown(br_eq)

        assert 0.0 <= nb_dd <= 1.0
        assert 0.0 <= br_dd <= 1.0
        print(f"\nMax Drawdown — NoBrain: {nb_dd:.4f}, Brain: {br_dd:.4f}")

    def test_result_shape_consistency(self, synthetic_order_book):
        """Both strategies return same-length lists."""
        nb_ret = run_spread_harvesting_nobrain(synthetic_order_book)
        br_ret = run_spread_harvesting_brain(synthetic_order_book)
        assert len(nb_ret) == len(br_ret)
        assert len(nb_ret) == len(synthetic_order_book)
