"""Tests for omega.core.regime_handler."""

from __future__ import annotations

import time

from omega.core.regime_handler import (
    RegimeHistory,
    RegimeSignalModifier,
    RegimeTransitionHandler,
    TransitionBuffer,
    TransitionEvent,
)

# ---------------------------------------------------------------------------
# RegimeHistory
# ---------------------------------------------------------------------------


class TestRegimeHistory:
    def test_initial_state(self):
        h = RegimeHistory()
        assert h.current is None
        assert h.current_label == "unknown"

    def test_enter_creates_entry(self):
        h = RegimeHistory()
        entry = h.enter("normal", cycle=1, changepoint_prob=0.8)
        assert entry.regime_label == "normal"
        assert entry.is_active
        assert h.current is entry

    def test_second_enter_closes_previous(self):
        h = RegimeHistory()
        e1 = h.enter("normal", cycle=1, changepoint_prob=0.6)
        e2 = h.enter("volatile", cycle=5, changepoint_prob=0.9)
        assert not e1.is_active
        assert e1.exited_at is not None
        assert e1.cycle_out == 5
        assert e2.is_active

    def test_by_label(self):
        h = RegimeHistory()
        h.enter("normal", cycle=1, changepoint_prob=0.5)
        h.enter("volatile", cycle=3, changepoint_prob=0.8)
        h.enter("normal", cycle=10, changepoint_prob=0.5)
        normal_entries = h.by_label("normal")
        assert len(normal_entries) == 2

    def test_by_time_range(self):
        h = RegimeHistory()
        now = time.time()
        h.enter("normal", cycle=1, changepoint_prob=0.5, now=now - 1000)
        h.enter("volatile", cycle=2, changepoint_prob=0.8, now=now - 500)
        results = h.by_time_range(start=now - 600, end=now)
        labels = [e.regime_label for e in results]
        assert "volatile" in labels

    def test_by_cycle_range(self):
        h = RegimeHistory()
        h.enter("normal", cycle=1, changepoint_prob=0.5)
        h.enter("volatile", cycle=10, changepoint_prob=0.9)
        h.enter("normal", cycle=20, changepoint_prob=0.5)
        entries = h.by_cycle_range(8, 15)
        labels = [e.regime_label for e in entries]
        assert "volatile" in labels

    def test_transitions(self):
        h = RegimeHistory()
        h.enter("normal", cycle=1, changepoint_prob=0.5)
        h.enter("volatile", cycle=5, changepoint_prob=0.9)
        h.enter("crash", cycle=10, changepoint_prob=0.95)
        t = h.transitions()
        assert len(t) == 2
        assert t[0][0].regime_label == "normal"
        assert t[0][1].regime_label == "volatile"

    def test_stats(self):
        h = RegimeHistory()
        h.enter("normal", cycle=1, changepoint_prob=0.5)
        h.enter("volatile", cycle=5, changepoint_prob=0.9)
        s = h.stats()
        assert s["total_entries"] == 2
        assert s["current_regime"] == "volatile"


# ---------------------------------------------------------------------------
# TransitionBuffer
# ---------------------------------------------------------------------------


class TestTransitionBuffer:
    def _make_event(self, from_r="normal", to_r="volatile") -> TransitionEvent:
        import uuid

        return TransitionEvent(
            event_id=str(uuid.uuid4()),
            from_regime=from_r,
            to_regime=to_r,
            detected_at=time.time(),
            detected_cycle=1,
        )

    def test_not_buffering_by_default(self):
        buf = TransitionBuffer()
        assert not buf.is_buffering

    def test_start_buffering(self):
        buf = TransitionBuffer()
        event = self._make_event()
        buf.start_buffering(event)
        assert buf.is_buffering
        assert buf.pending_event is event

    def test_push_buffered(self):
        buf = TransitionBuffer()
        buf.start_buffering(self._make_event())
        buf.push({"value": 1})
        buf.push({"value": 2})
        assert buf.buffered_count == 2

    def test_push_no_op_when_not_buffering(self):
        buf = TransitionBuffer()
        buf.push({"value": 1})
        assert buf.buffered_count == 0

    def test_drain_returns_observations(self):
        buf = TransitionBuffer()
        buf.start_buffering(self._make_event())
        buf.push({"a": 1})
        buf.push({"b": 2})
        items = buf.drain()
        assert len(items) == 2
        assert not buf.is_buffering

    def test_reject_clears_buffer(self):
        buf = TransitionBuffer()
        buf.start_buffering(self._make_event())
        buf.push({"x": 1})
        items = buf.reject()
        assert len(items) == 1
        assert not buf.is_buffering

    def test_max_size_enforced(self):
        buf = TransitionBuffer(max_size=3)
        buf.start_buffering(self._make_event())
        for i in range(10):
            buf.push({"i": i})
        assert buf.buffered_count == 3


# ---------------------------------------------------------------------------
# RegimeSignalModifier
# ---------------------------------------------------------------------------


class TestRegimeSignalModifier:
    def test_normal_regime_passthrough(self):
        mod = RegimeSignalModifier()
        signals = {"momentum": 1.0, "trend_follow": 0.5}
        result = mod.modify(signals, "normal")
        assert result == signals

    def test_volatile_regime_reduces_momentum(self):
        mod = RegimeSignalModifier()
        signals = {"momentum": 1.0}
        result = mod.modify(signals, "volatile")
        assert result["momentum"] < 1.0

    def test_crash_regime_amplifies_defensive(self):
        mod = RegimeSignalModifier()
        signals = {"defensive": 1.0}
        result = mod.modify(signals, "crash")
        assert result["defensive"] > 1.0

    def test_trending_regime_boosts_momentum(self):
        mod = RegimeSignalModifier()
        signals = {"momentum": 1.0}
        result = mod.modify(signals, "trending")
        assert result["momentum"] > 1.0

    def test_unknown_signal_passes_through(self):
        mod = RegimeSignalModifier()
        signals = {"custom_signal_xyz": 0.8}
        result = mod.modify(signals, "crash")
        assert result["custom_signal_xyz"] == 0.8

    def test_original_not_mutated(self):
        mod = RegimeSignalModifier()
        signals = {"momentum": 1.0}
        original = dict(signals)
        mod.modify(signals, "volatile")
        assert signals == original

    def test_set_multiplier(self):
        mod = RegimeSignalModifier()
        mod.set_multiplier("normal", "my_signal", 2.0)
        assert mod.get_multiplier("my_signal", "normal") == 2.0

    def test_custom_overrides_applied(self):
        mod = RegimeSignalModifier(multiplier_overrides={"normal": {"momentum": 1.5}})
        result = mod.modify({"momentum": 1.0}, "normal")
        assert result["momentum"] == 1.5


# ---------------------------------------------------------------------------
# RegimeTransitionHandler
# ---------------------------------------------------------------------------


class TestRegimeTransitionHandler:
    def test_initial_regime(self):
        handler = RegimeTransitionHandler()
        assert handler.current_regime == "normal"
        assert not handler.is_transitioning

    def test_no_transition_below_threshold(self):
        handler = RegimeTransitionHandler(detection_threshold=0.5)
        result = handler.update("volatile", changepoint_prob=0.3)
        assert result is None
        assert not handler.is_transitioning

    def test_transition_detected_above_threshold(self):
        handler = RegimeTransitionHandler(
            detection_threshold=0.5,
            confirmation_steps=3,
        )
        handler.update("volatile", changepoint_prob=0.6)
        assert handler.is_transitioning
        assert handler.pending_transition is not None
        assert handler.pending_transition.to_regime == "volatile"

    def test_transition_confirmed_after_steps(self):
        handler = RegimeTransitionHandler(
            detection_threshold=0.5,
            confirmation_threshold=0.55,
            rejection_threshold=0.1,
            confirmation_steps=3,
            ema_alpha=0.5,
        )
        event = None
        for _ in range(5):
            event = handler.update("volatile", changepoint_prob=0.8)
            if event is not None:
                break
        assert event is not None
        assert event.confirmed
        assert handler.current_regime == "volatile"
        assert not handler.is_transitioning

    def test_transition_rejected_when_prob_drops(self):
        handler = RegimeTransitionHandler(
            detection_threshold=0.5,
            rejection_threshold=0.3,
            confirmation_steps=5,
            ema_alpha=0.5,
        )
        handler.update("volatile", changepoint_prob=0.6)
        assert handler.is_transitioning

        # Low probabilities should drive EMA below rejection threshold
        for _ in range(4):
            handler.update("volatile", changepoint_prob=0.05)

        assert not handler.is_transitioning
        assert handler.current_regime == "normal"

    def test_same_regime_does_not_trigger_transition(self):
        handler = RegimeTransitionHandler(detection_threshold=0.5)
        handler.update("normal", changepoint_prob=0.9)
        assert not handler.is_transitioning

    def test_history_updated_on_confirmation(self):
        handler = RegimeTransitionHandler(
            detection_threshold=0.4,
            confirmation_threshold=0.5,
            rejection_threshold=0.1,
            confirmation_steps=2,
            ema_alpha=0.6,
        )
        for _ in range(5):
            handler.update("volatile", changepoint_prob=0.9)

        assert handler.history.current_label == "volatile"

    def test_buffer_receives_observations_during_transition(self):
        handler = RegimeTransitionHandler(
            detection_threshold=0.5,
            confirmation_steps=10,  # long window so it stays pending
        )
        handler.update("volatile", changepoint_prob=0.6)
        assert handler.is_transitioning

        for i in range(3):
            handler.update("volatile", changepoint_prob=0.6, observation={"i": i})

        assert handler.buffer.buffered_count >= 3

    def test_modify_signals_uses_current_regime(self):
        handler = RegimeTransitionHandler()
        # default is "normal" — all signals should pass through unchanged
        signals = {"momentum": 1.0, "defensive": 0.5}
        result = handler.modify_signals(signals)
        assert result == signals

    def test_stats_structure(self):
        handler = RegimeTransitionHandler()
        s = handler.stats()
        assert "current_regime" in s
        assert "is_transitioning" in s
        assert "total_events" in s
        assert "history" in s

    def test_all_events_tracks_history(self):
        handler = RegimeTransitionHandler(
            detection_threshold=0.4,
            confirmation_threshold=0.5,
            rejection_threshold=0.1,
            confirmation_steps=2,
            ema_alpha=0.6,
        )
        for _ in range(5):
            handler.update("volatile", changepoint_prob=0.9)

        events = handler.all_events()
        assert len(events) >= 1
        confirmed = [e for e in events if e.confirmed]
        assert len(confirmed) >= 1
