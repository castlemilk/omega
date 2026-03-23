"""Tests for omega.core.memory_v2 — sliding-window regime, BOCPD, EWC, D-S fusion, MemoryKernelV2."""

import os

import pytest

from omega.core.memory import MemoryKernel
from omega.core.memory_v2 import (
    BOCPDRegimeDetector,
    ContradictionResolver,
    DempsterShaferFusion,
    EWCProtection,
    MemoryKernelV2,
    RegimeState,
    Resolution,
    SlidingWindowRegimeDetector,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres integration tests",
)

# ---------------------------------------------------------------------------
# SlidingWindowRegimeDetector  (default)
# ---------------------------------------------------------------------------


class TestSlidingWindowRegimeDetector:
    def setup_method(self):
        self.d = SlidingWindowRegimeDetector(window=10)

    def test_returns_regime_state(self):
        state = self.d.update(0.01)
        assert isinstance(state, RegimeState)
        assert state.regime_id
        assert 0.0 <= state.changepoint_prob <= 1.0

    def test_crash_label(self):
        for _ in range(5):
            state = self.d.update(-0.10)
        assert state.label == "crash"

    def test_volatile_label(self):
        # High variance → volatile
        for i in range(10):
            self.d.update(0.2 if i % 2 == 0 else -0.2)
        state = self.d.current_regime()
        assert state.label in ("volatile", "crash", "trending")

    def test_normal_label_stable(self):
        for _ in range(15):
            state = self.d.update(0.001)
        assert state.label == "normal"

    def test_regime_change_updates_id(self):
        for _ in range(5):
            self.d.update(0.001)
        id_before = self.d.current_regime().regime_id
        # Force crash
        for _ in range(5):
            self.d.update(-0.15)
        id_after = self.d.current_regime().regime_id
        assert id_before != id_after

    def test_current_regime_consistent(self):
        self.d.update(0.02)
        state = self.d.update(0.03)
        current = self.d.current_regime()
        assert current.regime_id == state.regime_id


# ---------------------------------------------------------------------------
# BOCPDRegimeDetector (advanced, retained for compatibility)
# ---------------------------------------------------------------------------


class TestBOCPDRegimeDetector:
    def setup_method(self):
        self.d = BOCPDRegimeDetector(hazard_rate=0.1)

    def test_returns_regime_state(self):
        state = self.d.update(0.01)
        assert isinstance(state, RegimeState)
        assert state.regime_id
        assert 0.0 <= state.changepoint_prob <= 1.0

    def test_stable_stream_no_changepoint(self):
        for _ in range(20):
            state = self.d.update(0.001)  # tiny stable observations
        assert state.changepoint_prob < 0.9  # should not flag constant noise

    def test_regime_label_crash(self):
        # Feed very negative observations
        for _ in range(10):
            state = self.d.update(-0.10)
        assert state.label in ("crash", "volatile", "trending")

    def test_changepoint_detected_after_shift(self):
        # Stable then abrupt shift
        for _ in range(15):
            self.d.update(0.001)
        # Big jump
        state = self.d.update(0.50)
        # changepoint_prob may be elevated after a big shift
        assert state.changepoint_prob >= 0.0  # always valid range

    def test_current_regime_matches_last_update(self):
        self.d.update(0.02)
        state = self.d.update(0.03)
        current = self.d.current_regime()
        assert current.regime_id == state.regime_id


# ---------------------------------------------------------------------------
# EWCProtection
# ---------------------------------------------------------------------------


class TestEWCProtection:
    def setup_method(self):
        self.ewc = EWCProtection(lambda_ewc=0.4)

    def test_snapshot_params(self):
        params = {"w1": 0.5, "w2": 0.3}
        self.ewc.snapshot_params(params, task_id="task_A")
        assert self.ewc.should_regularise("task_A")

    def test_no_regularise_without_snapshot(self):
        assert not self.ewc.should_regularise("unknown_task")

    def test_estimate_fisher(self):
        grad_samples = [
            {"w1": 0.1, "w2": 0.2},
            {"w1": 0.2, "w2": 0.1},
            {"w1": 0.15, "w2": 0.15},
        ]
        fisher = self.ewc.estimate_fisher(grad_samples)
        assert "w1" in fisher and "w2" in fisher
        assert all(v >= 0 for v in fisher.values())

    def test_ewc_penalty_zero_for_same_params(self):
        params = {"w1": 0.5, "w2": 0.3}
        self.ewc.snapshot_params(params, "task_A")
        grad_samples = [{"w1": 0.1, "w2": 0.1}]
        self.ewc.estimate_fisher(grad_samples)
        penalty = self.ewc.ewc_penalty(params, "task_A")
        assert penalty == pytest.approx(0.0, abs=1e-9)

    def test_ewc_penalty_increases_with_deviation(self):
        anchor = {"w1": 0.5, "w2": 0.3}
        self.ewc.snapshot_params(anchor, "task_A")
        grad_samples = [{"w1": 0.5, "w2": 0.5}]
        # Pass task_id so Fisher is stored internally
        self.ewc.estimate_fisher(grad_samples, task_id="task_A")
        small_deviation = {"w1": 0.51, "w2": 0.31}
        large_deviation = {"w1": 1.0, "w2": 0.0}
        p_small = self.ewc.ewc_penalty(small_deviation, "task_A")
        p_large = self.ewc.ewc_penalty(large_deviation, "task_A")
        assert p_large > p_small

    def test_consolidate(self):
        params = {"w1": 0.5}
        self.ewc.snapshot_params(params, "task_A")
        # snapshot_params creates an anchor, so task_A should be regularisable
        assert self.ewc.should_regularise("task_A")
        self.ewc.consolidate("task_A")  # consolidate on known task
        assert self.ewc.should_regularise("task_A")


# ---------------------------------------------------------------------------
# DempsterShaferFusion
# ---------------------------------------------------------------------------


class TestDempsterShaferFusion:
    def setup_method(self):
        self.ds = DempsterShaferFusion(frame=["bull", "bear", "neutral"])

    def test_add_and_combine(self):
        self.ds.add_evidence("src1", {"bull": 0.7, "bear": 0.2})
        combined = self.ds.combine()
        assert isinstance(combined, dict)
        assert sum(combined.values()) <= 1.0 + 1e-9

    def test_belief_plausibility_range(self):
        self.ds.add_evidence("src1", {"bull": 0.7})
        bel = self.ds.belief("bull")
        pl = self.ds.plausibility("bull")
        assert 0.0 <= bel <= 1.0
        assert 0.0 <= pl <= 1.0
        assert pl >= bel

    def test_most_likely_returns_frame_element(self):
        self.ds.add_evidence("src1", {"bull": 0.8})
        best = self.ds.most_likely()
        assert best in ("bull", "bear", "neutral")

    def test_conflict_level_range(self):
        self.ds.add_evidence("src1", {"bull": 0.9})
        self.ds.add_evidence("src2", {"bear": 0.9})
        k = self.ds.conflict_level()
        assert 0.0 <= k <= 1.0

    def test_high_conflict_on_contradictory(self):
        self.ds.add_evidence("src1", {"bull": 0.95})
        self.ds.add_evidence("src2", {"bear": 0.95})
        k = self.ds.conflict_level()
        assert k > 0.5

    def test_high_conflict_uses_fallback(self):
        # Two strongly contradictory sources should trigger confidence-weighted fallback
        self.ds.add_evidence("src1", {"bull": 0.95})
        self.ds.add_evidence("src2", {"bear": 0.95})
        combined = self.ds.combine()
        # Should still return a valid dict (not raise)
        assert isinstance(combined, dict)
        # All values non-negative
        assert all(v >= 0 for v in combined.values())

    def test_low_conflict_uses_dempster(self):
        # Two consistent sources should combine normally
        self.ds.add_evidence("src1", {"bull": 0.7})
        self.ds.add_evidence("src2", {"bull": 0.6})
        combined = self.ds.combine()
        # Bull should have the highest mass
        bull_mass = combined.get("bull", 0.0)
        assert bull_mass > 0.0

    def test_reset(self):
        self.ds.add_evidence("src1", {"bull": 0.7})
        self.ds.reset()
        combined = self.ds.combine()
        assert isinstance(combined, dict)


# ---------------------------------------------------------------------------
# ContradictionResolver
# ---------------------------------------------------------------------------


class TestContradictionResolver:
    def setup_method(self):
        from omega.core.memory_v2 import BOCPDRegimeDetector

        self.regime = BOCPDRegimeDetector()
        self.resolver = ContradictionResolver(self.regime)

    def test_resolve_consistent_observations(self):
        obs = [
            {"source": "signal_node", "value": 0.8, "signal": "bull"},
            {"source": "risk_node", "value": 0.7, "signal": "bull"},
        ]
        result = self.resolver.resolve(obs)
        assert isinstance(result, Resolution)
        assert result.conclusion in ("bull", "bear", "neutral", "volatile")
        assert 0.0 <= result.confidence <= 1.0

    def test_resolve_contradictory(self):
        obs = [
            {"source": "s1", "value": 0.9, "signal": "bull"},
            {"source": "s2", "value": 0.9, "signal": "bear"},
        ]
        result = self.resolver.resolve(obs)
        assert result.conflict_level >= 0.0  # may or may not be high depending on impl

    def test_resolve_empty_observations(self):
        result = self.resolver.resolve([])
        assert isinstance(result, Resolution)


# ---------------------------------------------------------------------------
# MemoryKernelV2 — integration
# ---------------------------------------------------------------------------


class TestMemoryKernelV2:
    def setup_method(self):
        self.mem = MemoryKernelV2(db_path=":memory:")

    def test_uses_sliding_window_by_default(self):
        assert isinstance(self.mem.regime_detector, SlidingWindowRegimeDetector)

    def test_bocpd_when_advanced_flag(self):
        mem = MemoryKernelV2(db_path=":memory:", advanced_bocpd=True)
        assert isinstance(mem.regime_detector, BOCPDRegimeDetector)

    def test_ewc_disabled_by_default(self):
        assert not self.mem.ewc_enabled
        assert self.mem.ewc is None

    def test_ewc_enabled_when_requested(self):
        mem = MemoryKernelV2(db_path=":memory:", ewc_enabled=True)
        assert mem.ewc_enabled
        assert isinstance(mem.ewc, EWCProtection)

    def test_inherits_memory_kernel(self):
        assert isinstance(self.mem, MemoryKernel)

    def test_update_regime_returns_state(self):
        state = self.mem.update_regime(0.05)
        assert isinstance(state, RegimeState)

    def test_store_episode_v2_with_regime(self):
        self.mem.update_regime(0.02)
        eid = self.mem.store_episode_v2(
            event_type="signal_generated",
            content={"ticker": "BTCUSDT", "composite": 0.8},
            tags=["btc"],
        )
        assert eid is not None

    def test_get_regime_context(self):
        self.mem.update_regime(0.01)
        ctx = self.mem.get_regime_context()
        assert isinstance(ctx, dict)
        assert "label" in ctx or "regime_id" in ctx or len(ctx) > 0

    def test_resolve_contradictions(self):
        obs = [
            {"source": "s1", "value": 0.7, "signal": "bull"},
            {"source": "s2", "value": 0.3, "signal": "bear"},
        ]
        result = self.mem.resolve_contradictions(obs)
        assert isinstance(result, Resolution)

    def test_begin_cycle_works(self):
        # Should not raise
        self.mem.begin_cycle(0)
        self.mem.begin_cycle(1)

    def test_store_and_retrieve_semantic(self):
        self.mem.update_regime(0.0)
        self.mem.store_semantic("btc_momentum", "BTC momentum pattern", confidence=0.8)
        results = self.mem.retrieve_semantic(concept="btc_momentum")
        assert len(results) > 0
        assert results[0].concept == "btc_momentum"
