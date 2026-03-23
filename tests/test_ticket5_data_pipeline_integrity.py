"""
Tests for Ticket #5 — Data pipeline integrity fixes.

Covers:
  - DataQualityError raised when real data unavailable and allow_synthetic=False
  - allow_synthetic=True falls back to synthetic data without raising
  - Synthetic results marked with is_synthetic=True in BacktestResult and meta
  - Real data results marked with is_synthetic=False
  - Configurable orchestrator sleep: "fixed" mode
  - Configurable orchestrator sleep: "next_candle" mode
  - Adaptive sleep: backs off to 1s when cycle is too fast and sleep_seconds < 1
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from omega.core.errors import DataQualityError

# ---------------------------------------------------------------------------
# DataQualityError — basic error class tests
# ---------------------------------------------------------------------------


class TestDataQualityError:
    def test_is_subclass_of_omega_error(self):
        from omega.core.errors import OmegaError

        err = DataQualityError("test", source="binance", symbol="BTCUSDT")
        assert isinstance(err, OmegaError)

    def test_attributes_stored(self):
        err = DataQualityError("bad data", source="backtest", symbol="ETHUSDT")
        assert err.source == "backtest"
        assert err.symbol == "ETHUSDT"
        assert "bad data" in str(err)

    def test_to_dict_includes_source(self):
        err = DataQualityError("stale", source="binance")
        d = err.to_dict()
        assert d["source"] == "binance"
        assert d["error_type"] == "DataQualityError"

    def test_default_source_and_symbol(self):
        err = DataQualityError("missing")
        assert err.source == ""
        assert err.symbol == ""

    def test_extra_context_stored(self):
        err = DataQualityError("stale", source="s", freshness_minutes=120.0)
        assert err.context["freshness_minutes"] == 120.0


# ---------------------------------------------------------------------------
# BacktestEngine — DataQualityError raised when allow_synthetic=False
# ---------------------------------------------------------------------------


class TestBacktestEngineDataQualityError:
    def _engine(self, allow_synthetic: bool = False):
        from unittest.mock import MagicMock

        from omega.backtest import BacktestEngine

        cfg = MagicMock()
        return BacktestEngine(config=cfg, symbols=["BTCUSDT"], allow_synthetic=allow_synthetic)

    def test_raises_data_quality_error_when_real_data_unavailable(self):
        engine = self._engine(allow_synthetic=False)
        with (
            patch.object(engine, "_load_real_data", side_effect=Exception("network error")),
            pytest.raises(DataQualityError) as exc_info,
        ):
            engine._load_data("2024-01-01", "2024-03-01")
        assert "allow_synthetic=True" in str(exc_info.value)
        assert exc_info.value.source == "backtest"

    def test_does_not_raise_when_allow_synthetic_true(self):
        engine = self._engine(allow_synthetic=True)
        with patch.object(engine, "_load_real_data", side_effect=Exception("network error")):
            data, is_synthetic = engine._load_data("2024-01-01", "2024-02-01")
        assert is_synthetic is True
        assert "BTCUSDT" in data

    def test_returns_is_synthetic_false_for_real_data(self):
        engine = self._engine()
        real_data = {"BTCUSDT": []}
        with patch.object(engine, "_load_real_data", return_value=real_data):
            data, is_synthetic = engine._load_data("2024-01-01", "2024-02-01")
        assert is_synthetic is False
        assert data is real_data


# ---------------------------------------------------------------------------
# BacktestResult — is_synthetic flag propagation
# ---------------------------------------------------------------------------


class TestBacktestResultIsSynthetic:
    def _run_synthetic(self):
        from unittest.mock import MagicMock

        from omega.backtest import BacktestEngine

        cfg = MagicMock()
        engine = BacktestEngine(config=cfg, symbols=["BTCUSDT", "ETHUSDT"], allow_synthetic=True)
        # Force real data to fail → synthetic fallback
        with patch.object(engine, "_load_real_data", side_effect=Exception("no network")):
            return engine.run("2024-01-01", "2024-06-01", pico_only=True)

    def test_pico_result_marked_synthetic(self):
        report = self._run_synthetic()
        assert report["pico"]["is_synthetic"] is True

    def test_meta_marked_synthetic(self):
        report = self._run_synthetic()
        assert report["meta"]["is_synthetic"] is True

    def test_omega_result_marked_synthetic(self):
        from unittest.mock import MagicMock

        from omega.backtest import BacktestEngine

        cfg = MagicMock()
        engine = BacktestEngine(config=cfg, symbols=["BTCUSDT"], allow_synthetic=True)
        with patch.object(engine, "_load_real_data", side_effect=Exception("no network")):
            report = engine.run("2024-01-01", "2024-04-01", compare_pico=True)
        assert report["omega"]["is_synthetic"] is True
        assert report["pico"]["is_synthetic"] is True

    def test_real_data_not_marked_synthetic(self):
        from datetime import date, timedelta
        from unittest.mock import MagicMock

        from omega.backtest import OHLCV, BacktestEngine

        cfg = MagicMock()
        engine = BacktestEngine(config=cfg, symbols=["BTCUSDT"])

        # Build a minimal real dataset
        start = date(2024, 1, 1)
        bars = []
        price = 40000.0
        for i in range(60):
            d = (start + timedelta(days=i)).isoformat()
            bars.append(OHLCV("BTCUSDT", d, price, price * 1.01, price * 0.99, price, 1000.0))
            price *= 1.001
        real_data = {"BTCUSDT": bars}

        with patch.object(engine, "_load_real_data", return_value=real_data):
            report = engine.run("2024-01-01", "2024-03-01", pico_only=True)

        assert report["pico"]["is_synthetic"] is False
        assert report["meta"]["is_synthetic"] is False


# ---------------------------------------------------------------------------
# Orchestrator sleep — _compute_sleep
# ---------------------------------------------------------------------------


class TestOrchestratorComputeSleep:
    def _compute(self, sleep_until, sleep_seconds, cycle_duration=None):
        from omega.core.orchestrator_v2 import OmegaOrchestrator

        mock_result = MagicMock()
        mock_result.duration_seconds = cycle_duration
        return OmegaOrchestrator._compute_sleep(sleep_until, sleep_seconds, mock_result)

    # "fixed" mode
    def test_fixed_returns_sleep_seconds(self):
        wait = self._compute("fixed", 5.0, cycle_duration=1.0)
        assert wait == pytest.approx(5.0)

    def test_fixed_returns_zero_when_sleep_seconds_zero(self):
        wait = self._compute("fixed", 0.0, cycle_duration=1.0)
        assert wait == pytest.approx(0.0)

    def test_fixed_adaptive_back_off_when_cycle_too_fast(self):
        # sleep_seconds=0.1 (<1) and cycle_duration=0.01 (<0.05) → back off to 1s
        wait = self._compute("fixed", 0.1, cycle_duration=0.01)
        assert wait == pytest.approx(1.0)

    def test_fixed_no_back_off_when_sleep_already_1s_or_more(self):
        # sleep_seconds=2.0 (≥1) → return as-is even if cycle was fast
        wait = self._compute("fixed", 2.0, cycle_duration=0.01)
        assert wait == pytest.approx(2.0)

    def test_fixed_no_back_off_when_cycle_slow_enough(self):
        # sleep_seconds=0.1 but cycle_duration=0.5 (≥0.05) → no back off
        wait = self._compute("fixed", 0.1, cycle_duration=0.5)
        assert wait == pytest.approx(0.1)

    def test_fixed_no_cycle_result_no_back_off(self):
        from omega.core.orchestrator_v2 import OmegaOrchestrator

        wait = OmegaOrchestrator._compute_sleep("fixed", 0.1, None)
        assert wait == pytest.approx(0.1)

    # "next_candle" mode
    def test_next_candle_returns_positive_seconds(self):
        wait = self._compute("next_candle", 0.0, cycle_duration=None)
        assert 0 < wait <= 3600.0

    def test_next_candle_minimum_1s(self):
        # Even at the exact boundary the minimum is 1s

        from omega.core.orchestrator_v2 import OmegaOrchestrator

        # Patch datetime to be exactly on the hour
        class _FakeUTCNow:
            minute = 0
            second = 0
            microsecond = 0

        with patch("omega.core.orchestrator_v2.datetime") as mock_dt:
            mock_dt.now.return_value = _FakeUTCNow()
            wait = OmegaOrchestrator._compute_sleep("next_candle", 0.0, None)
        assert wait >= 1.0

    def test_next_candle_ignores_sleep_seconds(self):
        wait1 = self._compute("next_candle", 0.0)
        wait2 = self._compute("next_candle", 999.0)
        # Both should be within the same hourly window (within ~1s of each other)
        assert abs(wait1 - wait2) < 2.0


# ---------------------------------------------------------------------------
# Orchestrator run() — sleep_until param accepted
# ---------------------------------------------------------------------------


class TestOrchestratorRunSleepParam:
    def test_run_accepts_sleep_until_fixed(self):
        from omega.core.orchestrator_v2 import OmegaOrchestrator

        orch = OmegaOrchestrator()
        # Run 1 cycle with fixed sleep, should not raise
        history = orch.run(max_cycles=1, sleep_until="fixed", sleep_seconds=0.0)
        assert history is not None

    def test_run_accepts_sleep_until_next_candle(self):
        from omega.core.orchestrator_v2 import OmegaOrchestrator

        orch = OmegaOrchestrator()
        # Patch _compute_sleep to return 0 so the test doesn't actually sleep
        with patch.object(OmegaOrchestrator, "_compute_sleep", return_value=0.0):
            history = orch.run(max_cycles=1, sleep_until="next_candle")
        assert history is not None
