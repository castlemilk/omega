"""
Tests for the slippage model in StrategyNode.

TDD RED phase: tests fail until _calculate_slippage is implemented.
"""

from __future__ import annotations

import math


class TestCalculateSlippage:
    def _make_node(self):
        from omega.nodes.vectora.strategy import StrategyNode

        return StrategyNode()

    def test_returns_float(self):
        """_calculate_slippage returns a float."""
        node = self._make_node()
        result = node._calculate_slippage(order_size=1000.0, daily_volume=1_000_000.0)
        assert isinstance(result, float)

    def test_base_spread_dominates_for_tiny_order(self):
        """Very small order → slippage ≈ base_spread_bps."""
        node = self._make_node()
        slippage = node._calculate_slippage(
            order_size=0.0001,
            daily_volume=1_000_000.0,
            base_spread_bps=5.0,
            impact_bps=10.0,
        )
        # sqrt(0.0001 / 1_000_000) ≈ 3.16e-6 → impact ≈ 3.16e-5 bps → negligible
        assert abs(slippage - 5.0) < 0.01

    def test_slippage_increases_with_order_size(self):
        """Larger order → more market impact → higher slippage."""
        node = self._make_node()
        small = node._calculate_slippage(order_size=1_000.0, daily_volume=1_000_000.0)
        large = node._calculate_slippage(order_size=100_000.0, daily_volume=1_000_000.0)
        assert large > small

    def test_slippage_decreases_with_daily_volume(self):
        """Higher daily volume → lower market impact → lower slippage."""
        node = self._make_node()
        low_vol = node._calculate_slippage(order_size=10_000.0, daily_volume=100_000.0)
        high_vol = node._calculate_slippage(order_size=10_000.0, daily_volume=10_000_000.0)
        assert low_vol > high_vol

    def test_sqrt_formula_numerically(self):
        """Verify slippage_bps = base + impact * sqrt(order / volume)."""
        node = self._make_node()
        order_size = 10_000.0
        daily_volume = 1_000_000.0
        base_spread_bps = 5.0
        impact_bps = 10.0
        expected = base_spread_bps + impact_bps * math.sqrt(order_size / daily_volume)
        result = node._calculate_slippage(
            order_size=order_size,
            daily_volume=daily_volume,
            base_spread_bps=base_spread_bps,
            impact_bps=impact_bps,
        )
        assert abs(result - expected) < 1e-10

    def test_default_parameters(self):
        """Default params are base_spread_bps=5, impact_bps=10."""
        node = self._make_node()
        order_size = 50_000.0
        daily_volume = 1_000_000.0
        result = node._calculate_slippage(order_size=order_size, daily_volume=daily_volume)
        expected = 5.0 + 10.0 * math.sqrt(order_size / daily_volume)
        assert abs(result - expected) < 1e-10

    def test_configurable_parameters(self):
        """Custom base_spread_bps and impact_bps are respected."""
        node = self._make_node()
        result = node._calculate_slippage(
            order_size=10_000.0,
            daily_volume=1_000_000.0,
            base_spread_bps=2.0,
            impact_bps=20.0,
        )
        expected = 2.0 + 20.0 * math.sqrt(10_000.0 / 1_000_000.0)
        assert abs(result - expected) < 1e-10

    def test_zero_order_size(self):
        """Zero order size → slippage = base_spread_bps."""
        node = self._make_node()
        result = node._calculate_slippage(
            order_size=0.0, daily_volume=1_000_000.0, base_spread_bps=5.0, impact_bps=10.0
        )
        assert abs(result - 5.0) < 1e-10

    def test_nonnegative(self):
        """Slippage is always non-negative."""
        node = self._make_node()
        for order_size in [0.0, 100.0, 10_000.0, 1_000_000.0]:
            result = node._calculate_slippage(order_size=order_size, daily_volume=1_000_000.0)
            assert result >= 0.0

    def test_full_daily_volume_order(self):
        """Order size == daily_volume → impact_bps * 1 added."""
        node = self._make_node()
        result = node._calculate_slippage(
            order_size=1_000_000.0,
            daily_volume=1_000_000.0,
            base_spread_bps=5.0,
            impact_bps=10.0,
        )
        # sqrt(1) = 1 → slippage = 5 + 10*1 = 15
        assert abs(result - 15.0) < 1e-10
