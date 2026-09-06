"""Tests for signal retirement mechanism in node_skills.py."""

from __future__ import annotations

from omega.core.node_skills import (
    SignalEvolutionTracker,
    SignalLifecycle,
    SignalRetirementReason,
)

IC_THRESHOLD = 0.02
RETIREMENT_WINDOW = 50


class TestSignalNotRetiredWhenHealthy:
    def test_signal_above_threshold_not_retired(self):
        tracker = SignalEvolutionTracker(
            ic_threshold=IC_THRESHOLD, retirement_window=RETIREMENT_WINDOW
        )
        for _ in range(60):
            tracker.observe("momentum", 0.5)
            tracker.record_ic("momentum", 0.05)  # above threshold
        assert not tracker.is_retired("momentum")

    def test_signal_below_threshold_not_retired_before_window(self):
        tracker = SignalEvolutionTracker(
            ic_threshold=IC_THRESHOLD, retirement_window=RETIREMENT_WINDOW
        )
        for _ in range(49):
            tracker.observe("momentum", 0.1)
            tracker.record_ic("momentum", 0.001)  # below threshold
        assert not tracker.is_retired("momentum")


class TestSignalRetirementTriggered:
    def test_signal_retires_after_retirement_window_cycles_below_threshold(self):
        tracker = SignalEvolutionTracker(
            ic_threshold=IC_THRESHOLD, retirement_window=RETIREMENT_WINDOW
        )
        for _ in range(RETIREMENT_WINDOW):
            tracker.observe("momentum", 0.1)
            tracker.record_ic("momentum", 0.001)  # below threshold
        assert tracker.is_retired("momentum")

    def test_retired_signal_lifecycle_state_is_retired(self):
        tracker = SignalEvolutionTracker(
            ic_threshold=IC_THRESHOLD, retirement_window=RETIREMENT_WINDOW
        )
        for _ in range(RETIREMENT_WINDOW):
            tracker.observe("carry", 0.05)
            tracker.record_ic("carry", 0.000)
        assert tracker.get_evolution("carry").current_state == SignalLifecycle.RETIRED

    def test_retirement_reason_is_recorded(self):
        tracker = SignalEvolutionTracker(
            ic_threshold=IC_THRESHOLD, retirement_window=RETIREMENT_WINDOW
        )
        for _ in range(RETIREMENT_WINDOW):
            tracker.observe("momentum", 0.1)
            tracker.record_ic("momentum", 0.0)
        ev = tracker.get_evolution("momentum")
        assert ev.retirement_reason is not None
        assert ev.retirement_reason == SignalRetirementReason.LOW_IC

    def test_retirement_logs_the_cycle_count(self):
        tracker = SignalEvolutionTracker(
            ic_threshold=IC_THRESHOLD, retirement_window=RETIREMENT_WINDOW
        )
        for _ in range(RETIREMENT_WINDOW):
            tracker.observe("vrp", 0.1)
            tracker.record_ic("vrp", 0.0)
        ev = tracker.get_evolution("vrp")
        assert ev.cycles_below_ic_threshold == RETIREMENT_WINDOW


class TestRetiredSignalStaysRetired:
    def test_signal_stays_retired_after_ic_recovers(self):
        tracker = SignalEvolutionTracker(
            ic_threshold=IC_THRESHOLD, retirement_window=RETIREMENT_WINDOW
        )
        for _ in range(RETIREMENT_WINDOW):
            tracker.observe("carry", 0.1)
            tracker.record_ic("carry", 0.0)
        assert tracker.is_retired("carry")

        # IC recovers — should still be retired
        for _ in range(20):
            tracker.observe("carry", 0.8)
            tracker.record_ic("carry", 0.5)
        assert tracker.is_retired("carry")

    def test_retired_signal_observations_do_not_change_lifecycle_state(self):
        tracker = SignalEvolutionTracker(
            ic_threshold=IC_THRESHOLD, retirement_window=RETIREMENT_WINDOW
        )
        for _ in range(RETIREMENT_WINDOW):
            tracker.observe("sentiment", 0.1)
            tracker.record_ic("sentiment", 0.0)
        for _ in range(10):
            tracker.observe("sentiment", 0.9)
            tracker.record_ic("sentiment", 0.9)
        assert tracker.get_evolution("sentiment").current_state == SignalLifecycle.RETIRED


class TestGetRetiredSignals:
    def test_get_retired_signals_returns_empty_when_none_retired(self):
        tracker = SignalEvolutionTracker(
            ic_threshold=IC_THRESHOLD, retirement_window=RETIREMENT_WINDOW
        )
        tracker.observe("a", 0.5)
        assert tracker.get_retired_signals() == []

    def test_get_retired_signals_returns_retired_names(self):
        tracker = SignalEvolutionTracker(
            ic_threshold=IC_THRESHOLD, retirement_window=RETIREMENT_WINDOW
        )
        for _ in range(RETIREMENT_WINDOW):
            tracker.observe("a", 0.1)
            tracker.record_ic("a", 0.0)
            tracker.observe("b", 0.5)
            tracker.record_ic("b", 0.5)
        retired = tracker.get_retired_signals()
        assert "a" in retired
        assert "b" not in retired

    def test_summary_includes_retired_count(self):
        tracker = SignalEvolutionTracker(
            ic_threshold=IC_THRESHOLD, retirement_window=RETIREMENT_WINDOW
        )
        for _ in range(RETIREMENT_WINDOW):
            tracker.observe("stale", 0.1)
            tracker.record_ic("stale", 0.0)
        summary = tracker.summary()
        assert summary["by_state"].get("RETIRED", 0) == 1
