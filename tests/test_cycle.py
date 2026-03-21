"""Tests for omega.core.cycle — CycleContext, CycleResult, CycleHistory."""

import time

import pytest

from omega.core.cycle import CycleContext, CycleHistory, CycleResult

# ---------------------------------------------------------------------------
# CycleContext
# ---------------------------------------------------------------------------


class TestCycleContext:
    def test_new_generates_uuid(self):
        ctx1 = CycleContext.new(cycle_number=0)
        ctx2 = CycleContext.new(cycle_number=1)
        assert ctx1.cycle_id != ctx2.cycle_id

    def test_new_defaults(self):
        ctx = CycleContext.new(cycle_number=5)
        assert ctx.cycle_number == 5
        assert ctx.regime == "normal"
        assert ctx.active_node_ids == ()
        assert ctx.autonomy_levels == {}
        assert ctx.metadata == {}

    def test_new_with_values(self):
        ctx = CycleContext.new(
            cycle_number=10,
            regime="volatile",
            active_node_ids=("abc", "def"),
            autonomy_levels={"abc": "pico", "def": "autonomous"},
            metadata={"foo": "bar"},
        )
        assert ctx.regime == "volatile"
        assert ctx.active_node_ids == ("abc", "def")
        assert ctx.autonomy_levels["abc"] == "pico"
        assert ctx.metadata["foo"] == "bar"

    def test_frozen(self):
        from dataclasses import FrozenInstanceError

        ctx = CycleContext.new(cycle_number=0)
        with pytest.raises(FrozenInstanceError):
            ctx.regime = "crash"

    def test_timestamp_is_recent(self):
        before = time.time()
        ctx = CycleContext.new(cycle_number=0)
        after = time.time()
        assert before <= ctx.timestamp <= after


# ---------------------------------------------------------------------------
# CycleResult
# ---------------------------------------------------------------------------


class TestCycleResult:
    def _make_result(self, cycle_number: int = 0) -> CycleResult:
        ctx = CycleContext.new(cycle_number=cycle_number, regime="normal")
        return CycleResult(context=ctx)

    def test_defaults(self):
        r = self._make_result()
        assert r.signals_generated == 0
        assert r.trades_proposed == 0
        assert r.trades_executed == 0
        assert r.adversarial_flags == []
        assert not r.improvement_proposed
        assert not r.regime_transition
        assert r.error_count == 0

    def test_cycle_id_proxied(self):
        r = self._make_result(cycle_number=7)
        assert r.cycle_id == r.context.cycle_id
        assert r.cycle_number == 7

    def test_add_adversarial_flag(self):
        r = self._make_result()
        r.add_adversarial_flag(ring="ring1", severity="warning", reason="test")
        assert r.had_adversarial_flag
        assert not r.had_critical_flag
        r.add_adversarial_flag(ring="ring2", severity="critical", reason="bad")
        assert r.had_critical_flag

    def test_to_summary_keys(self):
        r = self._make_result()
        r.signals_generated = 5
        r.trades_proposed = 2
        r.trades_executed = 1
        summary = r.to_summary()
        assert summary["signals"] == 5
        assert summary["trades_proposed"] == 2
        assert summary["trades_executed"] == 1
        assert "cycle_id" in summary
        assert "regime" in summary


# ---------------------------------------------------------------------------
# CycleHistory
# ---------------------------------------------------------------------------


def _make_result(cycle_number: int, signals: int = 0, error_count: int = 0) -> CycleResult:
    ctx = CycleContext.new(cycle_number=cycle_number)
    r = CycleResult(context=ctx)
    r.signals_generated = signals
    r.error_count = error_count
    return r


class TestCycleHistory:
    def test_empty(self):
        h = CycleHistory()
        assert len(h) == 0
        assert h.latest is None

    def test_append_and_len(self):
        h = CycleHistory()
        h.append(_make_result(0))
        h.append(_make_result(1))
        assert len(h) == 2

    def test_latest(self):
        h = CycleHistory()
        h.append(_make_result(0))
        h.append(_make_result(1))
        assert h.latest.cycle_number == 1

    def test_rolling_window(self):
        h = CycleHistory(max_size=3)
        for i in range(5):
            h.append(_make_result(i))
        assert len(h) == 3
        assert h.latest.cycle_number == 4

    def test_recent(self):
        h = CycleHistory()
        for i in range(10):
            h.append(_make_result(i))
        recent = h.recent(3)
        assert len(recent) == 3
        assert recent[-1].cycle_number == 9

    def test_cycles_since_improvement_none(self):
        h = CycleHistory()
        for i in range(5):
            h.append(_make_result(i))
        assert h.cycles_since_improvement() == 5  # no improvement seen

    def test_cycles_since_improvement_with_event(self):
        h = CycleHistory()
        for i in range(5):
            r = _make_result(i)
            if i == 3:
                r.improvement_proposed = True
            h.append(r)
        assert h.cycles_since_improvement() == 1  # one cycle after cycle 3

    def test_avg_signals_per_cycle(self):
        h = CycleHistory()
        for i in range(4):
            h.append(_make_result(i, signals=i * 10))
        avg = h.avg_signals_per_cycle(window=4)
        assert avg == pytest.approx((0 + 10 + 20 + 30) / 4)

    def test_error_rate(self):
        h = CycleHistory()
        for i in range(4):
            h.append(_make_result(i, error_count=i))
        # errors: 0, 1, 2, 3 → avg = 1.5
        assert h.error_rate(window=4) == pytest.approx(1.5)

    def test_adversarial_flag_rate(self):
        h = CycleHistory()
        for i in range(4):
            r = _make_result(i)
            if i % 2 == 0:
                r.add_adversarial_flag("ring1", "warning", "test")
            h.append(r)
        assert h.adversarial_flag_rate(window=4) == pytest.approx(0.5)

    def test_regime_transition_rate(self):
        h = CycleHistory()
        for i in range(4):
            r = _make_result(i)
            if i < 2:
                r.regime_transition = True
            h.append(r)
        assert h.regime_transition_rate(window=4) == pytest.approx(0.5)

    def test_metric_trend_improving(self):
        h = CycleHistory()
        for i in range(10):
            r = _make_result(i)
            r.metrics["sharpe"] = float(i)  # clearly increasing
            h.append(r)
        assert h.metric_trend("sharpe", window=10) == "improving"

    def test_metric_trend_stable(self):
        h = CycleHistory()
        for i in range(10):
            r = _make_result(i)
            r.metrics["sharpe"] = 1.0  # flat
            h.append(r)
        assert h.metric_trend("sharpe", window=10) == "stable"

    def test_metric_trend_missing_key(self):
        h = CycleHistory()
        h.append(_make_result(0))
        assert h.metric_trend("nonexistent") == "stable"

    def test_clear(self):
        h = CycleHistory()
        h.append(_make_result(0))
        h.clear()
        assert len(h) == 0

    def test_node_health_trend_no_data(self):
        h = CycleHistory()
        for i in range(3):
            h.append(_make_result(i))
        # No node_results recorded → should return 1.0
        assert h.node_health_trend("nonexistent-id") == 1.0

    def test_node_health_trend_with_data(self):
        h = CycleHistory()
        for i in range(3):
            r = _make_result(i)
            r.node_results["node-a"] = {"health": 0.9}
            h.append(r)
        assert h.node_health_trend("node-a") == pytest.approx(0.9)
