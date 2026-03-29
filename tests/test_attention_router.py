"""Tests for AttentionRouter — attention weight decay for signal routing."""

from __future__ import annotations

import pytest

from omega.core.orchestrator_v2 import AttentionRouter


class TestAttentionRouterInitialState:
    def test_new_signal_gets_uniform_weight(self):
        router = AttentionRouter(n_decay_cycles=10)
        w = router.get_weight("momentum")
        assert w == 1.0

    def test_get_weights_returns_equal_weights_for_all_signals(self):
        router = AttentionRouter(n_decay_cycles=10)
        router.record_signals_this_cycle(["momentum", "sentiment", "carry"])
        weights = router.get_weights()
        assert set(weights.keys()) == {"momentum", "sentiment", "carry"}
        # All equal
        values = list(weights.values())
        assert all(abs(v - values[0]) < 1e-9 for v in values)


class TestAttentionRouterBoostOnWin:
    def test_contributing_signals_get_boosted_on_winning_trade(self):
        router = AttentionRouter(n_decay_cycles=10, boost=0.1)
        router.record_signals_this_cycle(["momentum", "sentiment", "carry"])
        initial_w = router.get_weight("momentum")
        router.record_trade_outcome(
            winning=True, contributing_signals=["momentum", "sentiment"]
        )
        assert router.get_weight("momentum") > initial_w
        assert router.get_weight("sentiment") > initial_w

    def test_non_contributing_signals_not_boosted_on_winning_trade(self):
        router = AttentionRouter(n_decay_cycles=10, boost=0.1)
        router.record_signals_this_cycle(["momentum", "sentiment", "carry"])
        initial_w = router.get_weight("carry")
        router.record_trade_outcome(
            winning=True, contributing_signals=["momentum", "sentiment"]
        )
        assert router.get_weight("carry") == initial_w

    def test_losing_trade_does_not_boost_any_signal(self):
        router = AttentionRouter(n_decay_cycles=10, boost=0.1)
        router.record_signals_this_cycle(["momentum", "sentiment"])
        initial_w = router.get_weight("momentum")
        router.record_trade_outcome(
            winning=False, contributing_signals=["momentum", "sentiment"]
        )
        assert router.get_weight("momentum") == initial_w


class TestAttentionRouterWeightDecay:
    def test_weights_decay_toward_uniform_after_n_idle_cycles(self):
        router = AttentionRouter(n_decay_cycles=3, boost=0.5, decay_rate=0.5)
        # Boost momentum
        router.record_signals_this_cycle(["momentum", "carry"])
        router.record_trade_outcome(winning=True, contributing_signals=["momentum"])
        boosted_w = router.get_weight("momentum")
        assert boosted_w > 1.0

        # Advance 3 cycles without momentum contributing to a win
        for _ in range(3):
            router.advance_cycle()

        # Weight should have decayed back toward 1.0
        decayed_w = router.get_weight("momentum")
        assert decayed_w < boosted_w

    def test_decay_moves_weight_toward_uniform(self):
        router = AttentionRouter(n_decay_cycles=1, boost=1.0, decay_rate=0.5)
        router.record_signals_this_cycle(["momentum"])
        router.record_trade_outcome(winning=True, contributing_signals=["momentum"])
        boosted = router.get_weight("momentum")

        router.advance_cycle()  # 1 idle cycle triggers decay

        decayed = router.get_weight("momentum")
        # Should move toward 1.0
        assert 1.0 <= decayed < boosted

    def test_weight_does_not_decay_below_uniform(self):
        router = AttentionRouter(n_decay_cycles=1, decay_rate=0.99)
        router.record_signals_this_cycle(["momentum"])
        for _ in range(100):
            router.advance_cycle()
        # Should not go below 1.0 (uniform floor)
        assert router.get_weight("momentum") >= 1.0

    def test_weight_does_not_exceed_max_weight(self):
        router = AttentionRouter(n_decay_cycles=10, boost=5.0, max_weight=3.0)
        router.record_signals_this_cycle(["momentum"])
        for _ in range(20):
            router.record_trade_outcome(winning=True, contributing_signals=["momentum"])
        assert router.get_weight("momentum") <= 3.0


class TestAttentionRouterCycleTracking:
    def test_idle_cycles_reset_after_win(self):
        router = AttentionRouter(n_decay_cycles=3, boost=0.2, decay_rate=0.5)
        router.record_signals_this_cycle(["momentum"])
        router.record_trade_outcome(winning=True, contributing_signals=["momentum"])

        # 2 idle cycles — not yet at decay threshold
        router.advance_cycle()
        router.advance_cycle()
        w_before = router.get_weight("momentum")

        # Win again resets the idle counter
        router.record_trade_outcome(winning=True, contributing_signals=["momentum"])
        router.advance_cycle()
        router.advance_cycle()
        # Still 2 idle cycles from the second win — should not have decayed more
        assert router.get_weight("momentum") >= w_before

    def test_routing_decisions_counter_increments_per_cycle(self):
        router = AttentionRouter(n_decay_cycles=5)
        router.record_signals_this_cycle(["a", "b"])
        router.advance_cycle()
        router.record_signals_this_cycle(["a", "b"])
        router.advance_cycle()
        assert router.routing_decisions >= 2
