"""
tests/test_meta_learner.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for the Phase 2 meta-learning layer (V144).

Tests:
  - T sharpens when rolling PF > 1.5
  - T softens when rolling PF < 0.8
  - T stays bounded in [0.05, 0.30]
  - Center drifts toward winning entry values
  - Per-regime independence (crisis buffer doesn't affect normal)
  - State persistence: save → reload preserves learned params
  - Signal IC tracking
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from omega.nodes.victoria.meta_learner import (
    MetaLearner, T_MIN, T_MAX, T_SHARPEN, T_SOFTEN, PF_HIGH, PF_LOW, ROLLING_WINDOW
)


# ── helpers ────────────────────────────────────────────────────────────────

def _make_learner(tmp_path: Path) -> MetaLearner:
    return MetaLearner(state_file=tmp_path / "meta_state.json")


def _flood_regime(learner: MetaLearner, regime: str, side: str, n: int,
                  win_pnl: float = 500.0, loss_pnl: float = -200.0,
                  win_frac: float = 1.0, entry_value: float = 0.25) -> None:
    """Push n trades of alternating win/loss into a regime buffer."""
    for i in range(n):
        pnl = win_pnl if (i / n) < win_frac else loss_pnl
        learner.record_trade(pnl=pnl, side=side, regime=regime,
                             entry_confidence=0.5, entry_value=entry_value)


# ── T convergence tests ────────────────────────────────────────────────────

class TestTemperatureAdjustment:

    def test_high_pf_sharpens_T(self, tmp_path):
        """After ROLLING_WINDOW wins (PF=∞ → > 1.5), T should decrease."""
        learner = _make_learner(tmp_path)
        initial_T = learner._surfaces["bear_long"].temperature

        # Fill buffer with only wins → PF > 1.5
        _flood_regime(learner, "crisis", "long", ROLLING_WINDOW, win_frac=1.0)

        final_T = learner._surfaces["bear_long"].temperature
        assert final_T < initial_T, f"Expected T to decrease: {initial_T} → {final_T}"
        assert final_T >= T_MIN, f"T went below minimum: {final_T}"

    def test_low_pf_softens_T(self, tmp_path):
        """After ROLLING_WINDOW losses (PF=0 → < 0.8), T should increase."""
        learner = _make_learner(tmp_path)
        initial_T = learner._surfaces["bear_long"].temperature

        # Fill buffer with only losses → PF = 0.0 < 0.8
        _flood_regime(learner, "crisis", "long", ROLLING_WINDOW,
                      win_pnl=-100.0, loss_pnl=-200.0, win_frac=0.0)

        final_T = learner._surfaces["bear_long"].temperature
        assert final_T > initial_T, f"Expected T to increase: {initial_T} → {final_T}"
        assert final_T <= T_MAX, f"T exceeded maximum: {final_T}"

    def test_T_lower_bound_enforced(self, tmp_path):
        """T must never go below T_MIN regardless of how many wins we record."""
        learner = _make_learner(tmp_path)
        # Force T to minimum by flooding with 1000 wins
        for _ in range(1000):
            learner.record_trade(pnl=500.0, side="long", regime="crisis")

        T = learner._surfaces["bear_long"].temperature
        assert T >= T_MIN, f"T below minimum: {T}"

    def test_T_upper_bound_enforced(self, tmp_path):
        """T must never exceed T_MAX regardless of how many losses we record."""
        learner = _make_learner(tmp_path)
        for _ in range(1000):
            learner.record_trade(pnl=-500.0, side="long", regime="crisis")

        T = learner._surfaces["bear_long"].temperature
        assert T <= T_MAX, f"T above maximum: {T}"

    def test_T_stable_on_neutral_pf(self, tmp_path):
        """When PF ≈ 1.2 (between 0.8 and 1.5), T should not change."""
        learner = _make_learner(tmp_path)
        initial_T = learner._surfaces["composite_long"].temperature

        # Alternating win/loss gives PF ≈ win_sum/loss_sum = 500*10 / 200*10 = 2.5
        # Use balanced win_pnl = 200, loss_pnl = 200 → PF = 1.0 (no change)
        for _ in range(ROLLING_WINDOW):
            learner.record_trade(pnl=200.0, side="long", regime="normal")
            learner.record_trade(pnl=-200.0, side="long", regime="normal")

        # PF = 1.0 which is between 0.8 and 1.5 → no adjustment
        final_T = learner._surfaces["composite_long"].temperature
        assert final_T == initial_T


# ── Regime independence ─────────────────────────────────────────────────────

class TestRegimeIndependence:

    def test_crisis_does_not_affect_normal(self, tmp_path):
        """Wins in crisis should not change normal composite_long surface."""
        learner = _make_learner(tmp_path)
        normal_T_before = learner._surfaces["composite_long"].temperature

        _flood_regime(learner, "crisis", "long", ROLLING_WINDOW, win_frac=1.0)

        normal_T_after = learner._surfaces["composite_long"].temperature
        assert normal_T_after == normal_T_before, \
            "Crisis wins must not affect normal_long surface"

    def test_long_does_not_affect_short_surface(self, tmp_path):
        """Crisis long wins should adjust bear_long but not bear_short."""
        learner = _make_learner(tmp_path)
        bear_short_T_before = learner._surfaces["bear_short"].temperature

        _flood_regime(learner, "crisis", "long", ROLLING_WINDOW, win_frac=1.0)

        bear_short_T_after = learner._surfaces["bear_short"].temperature
        assert bear_short_T_after == bear_short_T_before, \
            "Crisis long wins must not adjust bear_short surface"


# ── Center adjustment ───────────────────────────────────────────────────────

class TestCenterAdjustment:

    def test_center_drifts_toward_winner_entry_values(self, tmp_path):
        """Center should EMA-drift toward mean entry_value of winning trades."""
        learner = _make_learner(tmp_path)
        initial_center = learner._surfaces["bear_long"].center
        target_value = 0.20  # winning trades entered at bear_prob=0.20

        # Fill with winning trades at entry_value=0.20
        for _ in range(ROLLING_WINDOW):
            learner.record_trade(pnl=500.0, side="long", regime="crisis",
                                 entry_value=target_value)

        final_center = learner._surfaces["bear_long"].center
        # Center should have moved toward 0.20
        assert abs(final_center - target_value) < abs(initial_center - target_value), \
            f"Center {final_center:.4f} didn't move toward target {target_value}"

    def test_center_stays_bounded(self, tmp_path):
        """Center must stay in (0.01, 0.95) regardless of entry values."""
        learner = _make_learner(tmp_path)
        for _ in range(500):
            learner.record_trade(pnl=100.0, side="long", regime="normal",
                                 entry_value=0.001)  # extreme low

        center = learner._surfaces["composite_long"].center
        assert center >= 0.01, f"Center below 0.01: {center}"
        assert center <= 0.95, f"Center above 0.95: {center}"


# ── Persistence ─────────────────────────────────────────────────────────────

class TestStatePersistence:

    def test_save_and_reload(self, tmp_path):
        """Learned T and center survive save → reload cycle."""
        learner = _make_learner(tmp_path)
        _flood_regime(learner, "crisis", "long", ROLLING_WINDOW, win_frac=1.0)

        saved_T = learner._surfaces["bear_long"].temperature
        saved_center = learner._surfaces["bear_long"].center
        saved_n = learner._surfaces["bear_long"].n_adjustments

        learner.save_state()

        # Create fresh instance that loads saved state
        learner2 = _make_learner(tmp_path)
        assert abs(learner2._surfaces["bear_long"].temperature - saved_T) < 1e-6
        assert abs(learner2._surfaces["bear_long"].center - saved_center) < 1e-6
        assert learner2._surfaces["bear_long"].n_adjustments == saved_n

    def test_regime_buffer_survives_reload(self, tmp_path):
        """Regime trade buffer is persisted and reloaded."""
        learner = _make_learner(tmp_path)
        for i in range(8):
            learner.record_trade(pnl=100.0 * (-1 if i % 3 == 0 else 1),
                                 side="short", regime="high_vol")
        pf_before = learner._regime_buffers["high_vol"].profit_factor()

        learner.save_state()
        learner2 = _make_learner(tmp_path)
        pf_after = learner2._regime_buffers["high_vol"].profit_factor()

        assert pf_before is not None
        assert abs(pf_after - pf_before) < 0.01

    def test_no_state_file_gives_defaults(self, tmp_path):
        """Missing state file → default surface params (no crash)."""
        learner = MetaLearner(state_file=tmp_path / "nonexistent.json")
        assert learner._surfaces["bear_long"].temperature == 0.12
        assert learner._surfaces["bear_long"].center == 0.35


# ── Surface config output ───────────────────────────────────────────────────

class TestSurfaceConfigOutput:

    def test_get_surface_config_returns_valid_config(self, tmp_path):
        from omega.nodes.victoria.confidence_surface import SurfaceConfig
        learner = _make_learner(tmp_path)
        cfg = learner.get_surface_config()
        assert isinstance(cfg, SurfaceConfig)
        assert 0.01 < cfg.bear_long.center < 1.0
        assert T_MIN <= cfg.bear_long.temperature <= T_MAX

    def test_learned_params_propagate_to_config(self, tmp_path):
        learner = _make_learner(tmp_path)
        _flood_regime(learner, "crisis", "long", ROLLING_WINDOW, win_frac=1.0)

        cfg = learner.get_surface_config()
        assert cfg.bear_long.temperature == learner._surfaces["bear_long"].temperature


# ── Signal IC ───────────────────────────────────────────────────────────────

class TestSignalIC:

    def test_ic_increases_for_correct_direction(self, tmp_path):
        learner = _make_learner(tmp_path)
        ic_before = learner._signal_ic["momentum"]

        for _ in range(20):
            learner.record_trade(pnl=200.0, side="long", regime="normal",
                                 signal_contribs={"momentum": 0.5})

        assert learner._signal_ic["momentum"] > ic_before

    def test_ic_decreases_for_wrong_direction(self, tmp_path):
        learner = _make_learner(tmp_path)
        ic_before = learner._signal_ic["momentum"]

        for _ in range(20):
            learner.record_trade(pnl=-200.0, side="long", regime="normal",
                                 signal_contribs={"momentum": 0.5})

        assert learner._signal_ic["momentum"] < ic_before

    def test_emphasis_bounded(self, tmp_path):
        learner = _make_learner(tmp_path)
        for _ in range(500):
            learner.record_trade(pnl=500.0, side="long", regime="normal",
                                 signal_contribs={"momentum": 1.0})

        emphasis = learner.get_signal_family_emphasis()
        assert emphasis["momentum"] <= 1.5
        for v in emphasis.values():
            assert 0.5 <= v <= 1.5


# ── Summary ─────────────────────────────────────────────────────────────────

class TestSummary:

    def test_summary_returns_expected_keys(self, tmp_path):
        learner = _make_learner(tmp_path)
        s = learner.summary()
        assert "surfaces" in s
        assert "regime_pf" in s
        assert "signal_ic" in s
        assert "bear_long" in s["surfaces"]
        assert "crisis" in s["regime_pf"]

    def test_reset_clears_state(self, tmp_path):
        learner = _make_learner(tmp_path)
        _flood_regime(learner, "crisis", "long", ROLLING_WINDOW, win_frac=1.0)

        learner.reset()
        assert learner._surfaces["bear_long"].n_adjustments == 0
        assert len(learner._regime_buffers["crisis"].trades) == 0
