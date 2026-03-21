"""Tests for omega.core.bridge_evaluator.BridgeEvaluator.

Tests cover:
  1. Expanding window actually expands with each cycle.
  2. CI-spanning-zero results are rejected (score == -1.0).
  3. min_oos_periods is enforced (score == -999.0 when insufficient data).
"""

from __future__ import annotations

import math
import random
from typing import Any
from unittest.mock import MagicMock, patch

from omega.core.bridge_evaluator import (
    _INSUFFICIENT_DATA_SCORE,
    _REJECTED_SCORE,
    BridgeEvaluator,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(n: int, seed: int = 0) -> list[dict[str, Any]]:
    """Generate deterministic synthetic OHLCV bars."""
    rng = random.Random(seed)
    price = 100.0
    bars = []
    for i in range(n):
        change = rng.gauss(0.0005, 0.01)
        price = max(1.0, price * (1.0 + change))
        bars.append(
            {
                "timestamp": i,
                "open": price * 0.999,
                "high": price * 1.002,
                "low": price * 0.998,
                "close": price,
                "volume": rng.uniform(100, 1000),
            }
        )
    return bars


def _make_fake_bridge_result(oos_sharpe: float = 1.5, n_oos: int = 80) -> MagicMock:
    """Return a mock BacktestResult with configurable OOS returns."""
    rng = random.Random(42)
    # Generate returns that produce approximately oos_sharpe
    mu = oos_sharpe * 0.01 / math.sqrt(252)
    oos_returns = [rng.gauss(mu, 0.01) for _ in range(n_oos)]

    report = MagicMock()
    report.out_of_sample_sharpe = oos_sharpe
    report.in_sample_sharpe = oos_sharpe * 1.1
    report.max_drawdown = 0.05
    report.total_return = 0.12
    report.n_trades = 10

    result = MagicMock()
    result.out_of_sample_returns = oos_returns
    result.report = report
    return result


# ---------------------------------------------------------------------------
# Test: expanding window actually expands
# ---------------------------------------------------------------------------


class TestExpandingWindow:
    """Verify that is_end grows with each cycle."""

    def test_is_end_grows_per_cycle(self):
        """Each cycle should expand the IS window by expansion_step bars."""
        ohlcv = _make_ohlcv(600)
        evaluator = BridgeEvaluator(
            ohlcv=ohlcv,
            min_is_bars=200,
            expansion_step=20,
            min_oos_periods=60,
        )

        logged_is_ends: list[int] = []

        # We intercept bridge.run() calls to capture the window sizes
        with patch("omega.eval.backtest_bridge.OmegaBacktestBridge") as mock_cls:
            mock_bridge = MagicMock()
            mock_cls.return_value = mock_bridge
            mock_bridge.run.return_value = _make_fake_bridge_result(oos_sharpe=1.5, n_oos=80)
            mock_bridge._node._strategy = MagicMock()

            for cycle in range(5):
                _, metrics = evaluator.evaluate(
                    "node-1",
                    params={"short_window": 10},
                    context={"cycle": cycle},
                )
                logged_is_ends.append(metrics.get("is_end", -1))

        # is_end should increase by expansion_step each cycle
        for i in range(1, len(logged_is_ends)):
            assert logged_is_ends[i] > logged_is_ends[i - 1], (
                f"is_end did not grow at cycle {i}: {logged_is_ends[i]} <= {logged_is_ends[i - 1]}"
            )

    def test_window_size_grows_with_cycle(self):
        """oos_end (and thus window_size) should grow per cycle."""
        ohlcv = _make_ohlcv(600)
        evaluator = BridgeEvaluator(
            ohlcv=ohlcv,
            min_is_bars=150,
            expansion_step=15,
            min_oos_periods=60,
        )

        window_sizes: list[int] = []

        with patch("omega.eval.backtest_bridge.OmegaBacktestBridge") as mock_cls:
            mock_bridge = MagicMock()
            mock_cls.return_value = mock_bridge
            mock_bridge.run.return_value = _make_fake_bridge_result(oos_sharpe=1.2, n_oos=80)
            mock_bridge._node._strategy = MagicMock()

            for cycle in range(4):
                _, metrics = evaluator.evaluate(
                    "node-1",
                    params={},
                    context={"cycle": cycle},
                )
                window_sizes.append(metrics.get("window_size", 0))

        for i in range(1, len(window_sizes)):
            assert window_sizes[i] >= window_sizes[i - 1], (
                f"window_size did not grow at cycle {i}: {window_sizes[i]} < {window_sizes[i - 1]}"
            )

    def test_cycle_from_context_overrides_trial_count(self):
        """Cycle in context should take precedence over internal trial counter."""
        ohlcv = _make_ohlcv(500)
        evaluator = BridgeEvaluator(
            ohlcv=ohlcv,
            min_is_bars=120,
            expansion_step=10,
            min_oos_periods=60,
        )

        with patch("omega.eval.backtest_bridge.OmegaBacktestBridge") as mock_cls:
            mock_bridge = MagicMock()
            mock_cls.return_value = mock_bridge
            mock_bridge.run.return_value = _make_fake_bridge_result(n_oos=80)
            mock_bridge._node._strategy = MagicMock()

            # Pass cycle=10 explicitly — is_end should be min_is_bars + 10*step
            _, metrics = evaluator.evaluate("node-1", params={}, context={"cycle": 10})

        expected_is_end = 120 + 10 * 10  # = 220
        assert metrics["is_end"] == expected_is_end


# ---------------------------------------------------------------------------
# Test: CI-spanning-zero results are rejected
# ---------------------------------------------------------------------------


class TestCISpansZeroRejection:
    """Verify that a CI spanning zero causes rejection (score = -1.0)."""

    def _make_zero_spanning_ci_result(self, n_oos: int = 100) -> MagicMock:
        """OOS returns with roughly zero mean so CI spans zero."""
        rng = random.Random(99)
        # Very noisy, near-zero mean — CI will almost certainly span zero
        oos_returns = [rng.gauss(0.0, 0.03) for _ in range(n_oos)]

        report = MagicMock()
        report.out_of_sample_sharpe = 0.05
        report.in_sample_sharpe = 0.10
        report.max_drawdown = 0.08
        report.total_return = 0.01
        report.n_trades = 5

        result = MagicMock()
        result.out_of_sample_returns = oos_returns
        result.report = report
        return result

    def test_ci_spanning_zero_returns_rejected_score(self):
        """When CI = [negative, positive], score must be _REJECTED_SCORE."""
        ohlcv = _make_ohlcv(500)
        evaluator = BridgeEvaluator(
            ohlcv=ohlcv,
            min_is_bars=120,
            expansion_step=10,
            min_oos_periods=60,
            n_bootstrap=200,  # Faster for tests
        )

        with patch("omega.eval.backtest_bridge.OmegaBacktestBridge") as mock_cls:
            mock_bridge = MagicMock()
            mock_cls.return_value = mock_bridge
            mock_bridge.run.return_value = self._make_zero_spanning_ci_result(n_oos=100)
            mock_bridge._node._strategy = MagicMock()

            # Force CI to span zero by patching compute_sharpe_confidence_interval
            with patch(
                "omega.core.bridge_evaluator.compute_sharpe_confidence_interval",
                return_value=(-0.5, 0.8),
            ):
                score, metrics = evaluator.evaluate("node-1", params={}, context={"cycle": 0})

        assert score == _REJECTED_SCORE, f"Expected {_REJECTED_SCORE}, got {score}"
        assert metrics["rejected"] is True
        assert metrics["reason"] == "ci_spans_zero"
        assert metrics["ci_lower"] < 0.0
        assert metrics["ci_upper"] > 0.0

    def test_positive_ci_not_rejected(self):
        """When both CI bounds are positive, the trial should be accepted."""
        ohlcv = _make_ohlcv(500)
        evaluator = BridgeEvaluator(
            ohlcv=ohlcv,
            min_is_bars=120,
            expansion_step=10,
            min_oos_periods=60,
            n_bootstrap=200,
        )

        with patch("omega.eval.backtest_bridge.OmegaBacktestBridge") as mock_cls:
            mock_bridge = MagicMock()
            mock_cls.return_value = mock_bridge
            mock_bridge.run.return_value = _make_fake_bridge_result(oos_sharpe=2.0, n_oos=80)
            mock_bridge._node._strategy = MagicMock()

            with patch(
                "omega.core.bridge_evaluator.compute_sharpe_confidence_interval",
                return_value=(0.4, 1.8),
            ):
                score, metrics = evaluator.evaluate("node-1", params={}, context={"cycle": 0})

        assert score > _REJECTED_SCORE
        assert metrics.get("rejected") is False

    def test_negative_ci_not_rejected_as_zero_spanning(self):
        """A fully negative CI ([-2, -0.3]) should NOT trigger ci_spans_zero."""
        ohlcv = _make_ohlcv(500)
        evaluator = BridgeEvaluator(
            ohlcv=ohlcv,
            min_is_bars=120,
            expansion_step=10,
            min_oos_periods=60,
            n_bootstrap=200,
        )

        with patch("omega.eval.backtest_bridge.OmegaBacktestBridge") as mock_cls:
            mock_bridge = MagicMock()
            mock_cls.return_value = mock_bridge
            mock_bridge.run.return_value = _make_fake_bridge_result(oos_sharpe=-0.8, n_oos=80)
            mock_bridge._node._strategy = MagicMock()

            with patch(
                "omega.core.bridge_evaluator.compute_sharpe_confidence_interval",
                return_value=(-2.0, -0.3),
            ):
                _score, _metrics = evaluator.evaluate("node-1", params={}, context={"cycle": 0})

        # CI entirely negative — not zero-spanning, so reason should NOT be ci_spans_zero
        assert _metrics.get("reason") != "ci_spans_zero"


# ---------------------------------------------------------------------------
# Test: min_oos_periods enforcement
# ---------------------------------------------------------------------------


class TestMinOosPeriods:
    """Verify min_oos_periods is checked before running the bridge."""

    def test_insufficient_data_before_bridge_call(self):
        """When available OOS bars < min_oos_periods, bridge.run() must not be called."""
        # Small dataset: only 130 bars with min_is=120, min_oos=60 → oos only 10 bars
        ohlcv = _make_ohlcv(130)
        evaluator = BridgeEvaluator(
            ohlcv=ohlcv,
            min_is_bars=120,
            min_oos_periods=60,
            expansion_step=0,
        )

        with patch("omega.eval.backtest_bridge.OmegaBacktestBridge") as mock_cls:
            mock_bridge = MagicMock()
            mock_cls.return_value = mock_bridge

            score, metrics = evaluator.evaluate("node-1", params={}, context={"cycle": 0})

            mock_bridge.run.assert_not_called()

        assert score == _INSUFFICIENT_DATA_SCORE
        assert metrics["rejected"] is True
        assert metrics["reason"] == "insufficient_oos_periods"

    def test_sufficient_data_calls_bridge(self):
        """When dataset is large enough, bridge.run() must be called."""
        ohlcv = _make_ohlcv(400)
        evaluator = BridgeEvaluator(
            ohlcv=ohlcv,
            min_is_bars=100,
            min_oos_periods=60,
            expansion_step=0,
        )

        with patch("omega.eval.backtest_bridge.OmegaBacktestBridge") as mock_cls:
            mock_bridge = MagicMock()
            mock_cls.return_value = mock_bridge
            mock_bridge.run.return_value = _make_fake_bridge_result(n_oos=80)
            mock_bridge._node._strategy = MagicMock()

            with patch(
                "omega.core.bridge_evaluator.compute_sharpe_confidence_interval",
                return_value=(0.3, 1.5),
            ):
                score, _metrics = evaluator.evaluate("node-1", params={}, context={"cycle": 0})

            mock_bridge.run.assert_called_once()

        assert score != _INSUFFICIENT_DATA_SCORE

    def test_min_oos_periods_enforced_on_bridge_output(self):
        """If bridge returns fewer OOS returns than min_oos_periods, reject."""
        ohlcv = _make_ohlcv(400)
        evaluator = BridgeEvaluator(
            ohlcv=ohlcv,
            min_is_bars=100,
            min_oos_periods=80,
            expansion_step=0,
        )

        # Bridge returns only 30 OOS bars — well below min_oos_periods=80
        with patch("omega.eval.backtest_bridge.OmegaBacktestBridge") as mock_cls:
            mock_bridge = MagicMock()
            mock_cls.return_value = mock_bridge
            mock_bridge.run.return_value = _make_fake_bridge_result(n_oos=30)
            mock_bridge._node._strategy = MagicMock()

            score, metrics = evaluator.evaluate("node-1", params={}, context={"cycle": 0})

        assert score == _INSUFFICIENT_DATA_SCORE
        assert metrics["rejected"] is True
        assert "insufficient_oos" in metrics["reason"]

    def test_exact_min_oos_periods_is_accepted(self):
        """Bridge returning exactly min_oos_periods OOS bars should proceed to CI check."""
        ohlcv = _make_ohlcv(400)
        min_oos = 60
        evaluator = BridgeEvaluator(
            ohlcv=ohlcv,
            min_is_bars=100,
            min_oos_periods=min_oos,
            expansion_step=0,
        )

        with patch("omega.eval.backtest_bridge.OmegaBacktestBridge") as mock_cls:
            mock_bridge = MagicMock()
            mock_cls.return_value = mock_bridge
            mock_bridge.run.return_value = _make_fake_bridge_result(n_oos=min_oos)
            mock_bridge._node._strategy = MagicMock()

            with patch(
                "omega.core.bridge_evaluator.compute_sharpe_confidence_interval",
                return_value=(0.2, 1.2),
            ):
                score, _metrics = evaluator.evaluate("node-1", params={}, context={"cycle": 0})

        assert score != _INSUFFICIENT_DATA_SCORE, (
            "Exactly min_oos_periods should not be rejected for data insufficiency"
        )

    def test_custom_min_oos_periods(self):
        """BridgeEvaluator respects custom min_oos_periods values."""
        ohlcv = _make_ohlcv(600)
        evaluator = BridgeEvaluator(
            ohlcv=ohlcv,
            min_is_bars=200,
            min_oos_periods=120,  # Stricter requirement
            expansion_step=0,
        )

        with patch("omega.eval.backtest_bridge.OmegaBacktestBridge") as mock_cls:
            mock_bridge = MagicMock()
            mock_cls.return_value = mock_bridge
            # Return 100 OOS bars — below 120 threshold
            mock_bridge.run.return_value = _make_fake_bridge_result(n_oos=100)
            mock_bridge._node._strategy = MagicMock()

            score, metrics = evaluator.evaluate("node-1", params={}, context={"cycle": 0})

        assert score == _INSUFFICIENT_DATA_SCORE
        assert metrics["min_oos_periods"] == 120

    # ------------------------------------------------------------------
    # Trial counter
    # ------------------------------------------------------------------

    def test_trial_count_increments(self):
        """trial_count should increment on each evaluate() call."""
        ohlcv = _make_ohlcv(400)
        evaluator = BridgeEvaluator(
            ohlcv=ohlcv,
            min_is_bars=100,
            min_oos_periods=60,
            expansion_step=0,
        )
        assert evaluator.trial_count == 0

        with patch("omega.eval.backtest_bridge.OmegaBacktestBridge") as mock_cls:
            mock_bridge = MagicMock()
            mock_cls.return_value = mock_bridge
            mock_bridge.run.return_value = _make_fake_bridge_result(n_oos=80)
            mock_bridge._node._strategy = MagicMock()

            with patch(
                "omega.core.bridge_evaluator.compute_sharpe_confidence_interval",
                return_value=(0.3, 1.5),
            ):
                for i in range(3):
                    evaluator.evaluate("node-1", params={}, context={"cycle": i})

        assert evaluator.trial_count == 3
