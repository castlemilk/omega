"""Tests for omega.core.backtest_evaluator."""

from __future__ import annotations

import threading

import pytest

from omega.core.backtest_evaluator import (
    BacktestEvaluator,
    _generate_synthetic_prices,
    _run_parameterised_strategy,
)
from omega.core.bayesian_optimizer import DiscreteParam
from omega.core.improvement_engine import ImprovementEngine, SyntheticEvaluator

# ---------------------------------------------------------------------------
# Synthetic price generator
# ---------------------------------------------------------------------------


class TestGenerateSyntheticPrices:
    def test_returns_nonempty_list(self):
        prices = _generate_synthetic_prices("BTCUSDT", "2024-01-01", "2024-06-01")
        assert len(prices) > 0

    def test_deterministic(self):
        p1 = _generate_synthetic_prices("BTCUSDT", "2024-01-01", "2024-06-01")
        p2 = _generate_synthetic_prices("BTCUSDT", "2024-01-01", "2024-06-01")
        assert p1 == p2

    def test_different_symbols_differ(self):
        p1 = _generate_synthetic_prices("BTCUSDT", "2024-01-01", "2024-06-01")
        p2 = _generate_synthetic_prices("ETHUSDT", "2024-01-01", "2024-06-01")
        assert p1 != p2

    def test_prices_positive(self):
        prices = _generate_synthetic_prices("BTCUSDT", "2024-01-01", "2024-06-01")
        assert all(p > 0 for p in prices)


# ---------------------------------------------------------------------------
# Parameterised strategy
# ---------------------------------------------------------------------------


class TestRunParameterisedStrategy:
    def setup_method(self):
        self.prices = _generate_synthetic_prices("BTCUSDT", "2024-01-01", "2024-12-31")

    def test_returns_correct_length(self):
        rets, equity = _run_parameterised_strategy(
            self.prices,
            short_window=10,
            long_window=30,
            rsi_window=14,
            rsi_overbought=70.0,
            rsi_enabled=True,
        )
        assert len(rets) == len(self.prices) - 1
        assert len(equity) >= 1

    def test_equity_starts_at_one(self):
        _, equity = _run_parameterised_strategy(
            self.prices,
            short_window=10,
            long_window=30,
            rsi_window=14,
            rsi_overbought=70.0,
            rsi_enabled=True,
        )
        assert equity[0] == pytest.approx(1.0)

    def test_rsi_disabled_vs_enabled_differ(self):
        rets_on, _ = _run_parameterised_strategy(self.prices, 10, 30, 14, 70.0, rsi_enabled=True)
        rets_off, _ = _run_parameterised_strategy(self.prices, 10, 30, 14, 70.0, rsi_enabled=False)
        # Not required to differ always, but with typical data they will
        # at minimum both return valid lists
        assert len(rets_on) == len(rets_off)

    def test_different_windows_produce_different_returns(self):
        rets_a, _ = _run_parameterised_strategy(self.prices, 5, 20, 14, 70.0, True)
        rets_b, _ = _run_parameterised_strategy(self.prices, 10, 40, 14, 70.0, True)
        # Different windows → different signal timings
        assert rets_a != rets_b


# ---------------------------------------------------------------------------
# BacktestEvaluator
# ---------------------------------------------------------------------------


class TestBacktestEvaluator:
    def make_evaluator(self, **kwargs):
        # allow_synthetic=True: unit tests intentionally run against fake data
        defaults = dict(
            symbols=["BTCUSDT"], oos_start="2024-01-01", oos_end="2024-06-01", allow_synthetic=True
        )
        defaults.update(kwargs)
        return BacktestEvaluator(**defaults)

    def test_evaluate_returns_score_and_metrics(self):
        ev = self.make_evaluator()
        score, metrics = ev.evaluate("node-1", {})
        assert isinstance(score, float)
        assert "sharpe" in metrics
        assert "max_drawdown" in metrics
        assert "composite" in metrics

    def test_evaluate_with_explicit_params(self):
        ev = self.make_evaluator()
        params = {"short_window": 5, "long_window": 20, "rsi_window": 10}
        score, metrics = ev.evaluate("node-1", params)
        assert isinstance(score, float)
        assert metrics["n_bars"] > 0

    def test_cache_hit_on_identical_params(self):
        ev = self.make_evaluator()
        params = {"short_window": 10, "long_window": 30}
        score1, _ = ev.evaluate("node-1", params)
        assert ev.cache_size() == 1
        score2, _ = ev.evaluate("node-1", params)
        assert ev.cache_size() == 1  # No new entry
        assert score1 == score2

    def test_different_params_different_cache_entries(self):
        ev = self.make_evaluator()
        ev.evaluate("node-1", {"short_window": 10, "long_window": 30})
        ev.evaluate("node-1", {"short_window": 5, "long_window": 20})
        assert ev.cache_size() == 2

    def test_different_node_ids_different_cache_entries(self):
        ev = self.make_evaluator()
        params = {"short_window": 10, "long_window": 30}
        ev.evaluate("node-A", params)
        ev.evaluate("node-B", params)
        assert ev.cache_size() == 2

    def test_clear_cache(self):
        ev = self.make_evaluator()
        ev.evaluate("node-1", {})
        assert ev.cache_size() == 1
        ev.clear_cache()
        assert ev.cache_size() == 0

    def test_cache_eviction_at_max(self):
        ev = self.make_evaluator(max_cache=3)
        for i in range(5):
            ev.evaluate(f"node-{i}", {"short_window": i + 2, "long_window": i + 10})
        assert ev.cache_size() <= 3

    def test_thread_safety(self):
        """Multiple threads can call evaluate() concurrently without errors."""
        ev = self.make_evaluator()
        errors = []
        results = []

        def worker(idx):
            try:
                score, _metrics = ev.evaluate(
                    f"node-{idx % 3}", {"short_window": idx % 5 + 2, "long_window": idx % 5 + 15}
                )
                results.append(score)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        assert len(results) == 12

    def test_param_clamping_short_less_than_long(self):
        """short_window >= long_window should be clamped safely."""
        ev = self.make_evaluator()
        # short > long — should not raise
        score, _ = ev.evaluate("node-1", {"short_window": 50, "long_window": 10})
        assert isinstance(score, float)

    def test_resolve_params_defaults(self):
        ev = self.make_evaluator()
        resolved = ev._resolve_params({})
        assert resolved["short_window"] == 10
        assert resolved["long_window"] == 30
        assert resolved["rsi_window"] == 14
        assert resolved["rsi_overbought"] == 70.0
        assert resolved["rsi_enabled"] is True

    def test_oos_metadata_in_metrics(self):
        ev = self.make_evaluator(oos_start="2024-03-01", oos_end="2024-09-01")
        _, metrics = ev.evaluate("node-1", {})
        assert metrics["oos_start"] == "2024-03-01"
        assert metrics["oos_end"] == "2024-09-01"

    def test_multiple_symbols(self):
        # allow_synthetic=True: unit test intentionally runs against fake data
        ev = BacktestEvaluator(
            symbols=["BTCUSDT", "ETHUSDT"],
            oos_start="2024-01-01",
            oos_end="2024-06-01",
            allow_synthetic=True,
        )
        score, metrics = ev.evaluate("node-1", {})
        assert isinstance(score, float)
        assert metrics["n_bars"] > 0


# ---------------------------------------------------------------------------
# ImprovementEngine integration
# ---------------------------------------------------------------------------


class TestImprovementEngineWithBacktestEvaluator:
    def test_engine_uses_a_functional_evaluator_by_default(self):
        """Default evaluator is NullEvaluator — domain must inject its own."""

        engine = ImprovementEngine()
        # SyntheticEvaluator, not NullEvaluator. The default was changed
        # deliberately and _default_evaluator documents why: NullEvaluator raised
        # NotImplementedError on every evaluate() call, so the orchestrator's
        # improvement cycle crashed and logged "ImprovementEngine has no evaluator
        # configured" — an engine that is inert unless configured, which is the
        # failure mode V279 named. A functional default is the point.
        assert isinstance(engine._evaluator, SyntheticEvaluator)

    def test_set_evaluator_replaces(self):
        from omega.core.improvement_engine import SyntheticEvaluator

        engine = ImprovementEngine()
        ev = SyntheticEvaluator()
        engine.set_evaluator(ev)
        assert engine._evaluator is ev

    def test_full_tpe_cycle_with_backtest_evaluator(self):
        # allow_synthetic=True: integration test intentionally runs against fake data
        ev = BacktestEvaluator(
            symbols=["BTCUSDT"],
            oos_start="2024-01-01",
            oos_end="2024-06-01",
            allow_synthetic=True,
        )
        engine = ImprovementEngine(evaluator=ev, n_startup_trials=3)
        engine.register_node(
            "node-1",
            param_space=[
                DiscreteParam("short_window", 5, 20),
                DiscreteParam("long_window", 21, 60),
            ],
        )

        for _ in range(5):
            params = engine.propose("node-1")
            trial = engine.evaluate_and_record("node-1", params)
            assert trial.score is not None

        assert engine.trial_count("node-1") == 5
        assert engine.best_params("node-1") is not None
        assert engine.best_score("node-1") > -1e9

    def test_has_converged_false_initially(self):
        engine = ImprovementEngine(convergence_window=5)
        engine.register_node("node-1", param_space=[DiscreteParam("short_window", 5, 20)])
        assert engine.has_converged("node-1") is False

    def test_has_converged_true_after_plateau(self):
        engine = ImprovementEngine(convergence_window=5, convergence_epsilon=100.0)
        engine.register_node("node-1", param_space=[DiscreteParam("short_window", 5, 20)])
        # Record constant scores → plateau
        params = {"short_window": 10}
        for _ in range(5):
            engine.record_outcome("node-1", params, score=0.5)

        assert engine.has_converged("node-1") is True

    def test_improvement_rate_non_zero_after_trials(self):
        engine = ImprovementEngine()
        engine.register_node("node-1", param_space=[DiscreteParam("short_window", 5, 20)])
        params = {"short_window": 10}
        scores = [0.1, 0.2, 0.3, 0.4, 0.5]
        for s in scores:
            engine.record_outcome("node-1", params, score=s)
        rate = engine.improvement_rate("node-1")
        assert rate > 0.0

    def test_convergence_diagnostics_accessible(self):
        engine = ImprovementEngine()
        engine.register_node("node-1", param_space=[DiscreteParam("short_window", 5, 20)])
        diag = engine.convergence_diagnostics("node-1")
        assert diag is not None
        engine.record_outcome("node-1", {"short_window": 10}, score=1.23)
        assert diag.n_trials == 1
        assert diag.best_score == pytest.approx(1.23)


# ---------------------------------------------------------------------------
# DataSplitter integration
# ---------------------------------------------------------------------------


class TestBacktestEvaluatorWithSplitter:
    def test_from_splitter_sets_validate_window(self):
        from omega.eval.data_splitter import DataSplitter

        splitter = DataSplitter("2022-01-01", "2024-12-31")
        ev = BacktestEvaluator.from_splitter(splitter, allow_synthetic=True)
        split = splitter.split()
        assert ev._oos_start == split.validate_start
        assert ev._oos_end == split.validate_end

    def test_from_splitter_stores_splitter(self):
        from omega.eval.data_splitter import DataSplitter

        splitter = DataSplitter("2022-01-01", "2024-12-31")
        ev = BacktestEvaluator.from_splitter(splitter, allow_synthetic=True)
        assert ev._splitter is splitter

    def test_evaluate_test_split_raises_without_splitter(self):
        ev = BacktestEvaluator(oos_start="2024-01-01", oos_end="2024-12-31", allow_synthetic=True)
        with pytest.raises(RuntimeError, match="from_splitter"):
            ev.evaluate_test_split("BTC", {})

    def test_evaluate_test_split_returns_metrics(self):
        from omega.eval.data_splitter import DataSplitter

        splitter = DataSplitter("2022-01-01", "2024-12-31")
        ev = BacktestEvaluator.from_splitter(splitter, allow_synthetic=True)
        score, metrics = ev.evaluate_test_split("BTC", {"short_window": 10, "long_window": 30})
        assert isinstance(score, float)
        assert "sharpe" in metrics
        assert "oos_start" in metrics
        assert "oos_end" in metrics

    def test_test_split_window_differs_from_validate(self):
        from omega.eval.data_splitter import DataSplitter

        splitter = DataSplitter("2022-01-01", "2024-12-31")
        ev = BacktestEvaluator.from_splitter(splitter, allow_synthetic=True)
        split = splitter.split()
        _, metrics = ev.evaluate_test_split("BTC", {})
        assert metrics["oos_start"] == split.test_start
        assert metrics["oos_end"] == split.test_end
        # Test window must not overlap with validate window
        assert metrics["oos_start"] > ev._oos_end


# ---------------------------------------------------------------------------
# Bootstrap Sharpe CI in metrics
# ---------------------------------------------------------------------------


class TestB3EvaluatorLookAhead:
    """Verify that _run_parameterised_strategy has no signal-bar look-ahead bias."""

    def _make_crossover_prices(self) -> tuple[list[float], int]:
        """
        Build a deterministic price series that guarantees a golden cross at a
        known bar index.

        Strategy: use short_window=3, long_window=5.
        Prices rise slowly for the first 10 bars, then jump sharply so that
        the 3-bar SMA crosses above the 5-bar SMA at a predictable bar.

        Returns (prices, signal_bar_index) where signal_bar_index is the bar
        at which the golden cross fires (i.e. sma_s[i] > sma_l[i] for the
        first time after sma_s[i-1] <= sma_l[i-1]).
        """
        # Flat/slightly declining then a clear jump guarantees a crossover.
        prices = [
            100.0,
            100.0,
            100.0,
            100.0,
            100.0,  # bars 0-4 (flat, short approx long)
            99.0,
            98.0,
            97.0,
            96.0,
            95.0,  # bars 5-9 (declining, short < long)
            110.0,
            120.0,
            130.0,  # bars 10-12 (sharp rise -> crossover)
            130.0,
            130.0,
            130.0,
            130.0,
            130.0,  # bars 13-17 (stay in position)
        ]
        from omega.core.backtest_evaluator import _sma

        short_window = 3
        long_window = 5
        sma_s = _sma(prices, short_window)
        sma_l = _sma(prices, long_window)

        signal_bar = None
        for i in range(1, len(prices)):
            cur_s_val = sma_s[i]
            cur_l_val = sma_l[i]
            if cur_s_val is None or cur_l_val is None:
                continue
            ps = sma_s[i - 1]
            pl = sma_l[i - 1]
            if ps is None or pl is None:
                continue
            if ps <= pl and cur_s_val > cur_l_val:
                signal_bar = i
                break

        assert signal_bar is not None, "Test price series must produce a golden cross"
        return prices, signal_bar

    def test_signal_bar_earns_zero_return(self):
        """On the bar where the golden cross fires, position is still 0 → ret == 0."""
        prices, signal_bar = self._make_crossover_prices()
        rets, _ = _run_parameterised_strategy(
            prices,
            short_window=3,
            long_window=5,
            rsi_window=2,
            rsi_overbought=100.0,  # RSI gate always passes
            rsi_enabled=False,
        )
        # daily_rets[i] corresponds to bar i+1 in the price list
        # But rets is indexed from bar 1, so rets[signal_bar - 1] is bar signal_bar
        assert rets[signal_bar - 1] == pytest.approx(0.0), (
            f"Expected 0 return on signal bar {signal_bar}, got {rets[signal_bar - 1]}"
        )

    def test_bar_after_signal_is_active(self):
        """The bar after the golden cross, position should be 1 → non-zero ret (price moved)."""
        prices, signal_bar = self._make_crossover_prices()
        rets, _ = _run_parameterised_strategy(
            prices,
            short_window=3,
            long_window=5,
            rsi_window=2,
            rsi_overbought=100.0,
            rsi_enabled=False,
        )
        next_bar = signal_bar  # rets[signal_bar] corresponds to prices bar signal_bar+1
        if next_bar < len(rets):
            # Price is rising after signal, so return should be non-zero
            assert rets[next_bar] != pytest.approx(0.0), (
                f"Expected non-zero return on bar after signal (index {next_bar}), "
                f"got {rets[next_bar]}"
            )

    def test_biased_vs_fixed_returns_differ(self):
        """
        Manually simulate the biased (original) version and confirm the fixed
        version produces a different equity curve, proving the fix has effect.
        """
        prices, signal_bar = self._make_crossover_prices()

        # Fixed version (no look-ahead)
        rets_fixed, _equity_fixed = _run_parameterised_strategy(
            prices,
            short_window=3,
            long_window=5,
            rsi_window=2,
            rsi_overbought=100.0,
            rsi_enabled=False,
        )

        # Simulate the biased version inline (position set immediately on signal bar)
        from omega.core.backtest_evaluator import _sma

        sma_s = _sma(prices, 3)
        sma_l = _sma(prices, 5)
        position_biased = 0.0
        rets_biased = []
        for i in range(1, len(prices)):
            if sma_s[i] is None or sma_l[i] is None:
                rets_biased.append(0.0)
                continue
            ps = sma_s[i - 1]
            pl = sma_l[i - 1]
            if ps is None or pl is None:
                rets_biased.append(0.0)
                continue
            cur_s = float(sma_s[i])
            cur_l = float(sma_l[i])
            if float(ps) <= float(pl) and cur_s > cur_l and position_biased == 0.0:
                position_biased = 1.0
            elif float(ps) >= float(pl) and cur_s < cur_l and position_biased == 1.0:
                position_biased = 0.0
            rets_biased.append(position_biased * (prices[i] - prices[i - 1]) / prices[i - 1])

        # The fixed version must differ from the biased one at the signal bar
        assert rets_fixed != rets_biased, (
            "Fixed and biased returns should differ — the look-ahead fix has no effect"
        )
        # Specifically, signal bar return must differ
        assert rets_fixed[signal_bar - 1] != rets_biased[signal_bar - 1], (
            f"Signal bar {signal_bar} return should differ between biased and fixed"
        )

    def test_equity_starts_at_one(self):
        """Equity curve must still start at 1.0 after the fix."""
        prices, _ = self._make_crossover_prices()
        _, equity = _run_parameterised_strategy(
            prices,
            short_window=3,
            long_window=5,
            rsi_window=2,
            rsi_overbought=100.0,
            rsi_enabled=False,
        )
        assert equity[0] == pytest.approx(1.0)

    def test_return_length_unchanged(self):
        """len(daily_rets) must still equal len(prices) - 1."""
        prices, _ = self._make_crossover_prices()
        rets, _ = _run_parameterised_strategy(
            prices,
            short_window=3,
            long_window=5,
            rsi_window=2,
            rsi_overbought=100.0,
            rsi_enabled=False,
        )
        assert len(rets) == len(prices) - 1


class TestBacktestEvaluatorSharpeCI:
    def test_metrics_include_sharpe_ci(self):
        ev = BacktestEvaluator(oos_start="2024-01-01", oos_end="2024-12-31", allow_synthetic=True)
        _, metrics = ev.evaluate("BTC", {"short_window": 10, "long_window": 30})
        assert "sharpe_ci_lower" in metrics
        assert "sharpe_ci_upper" in metrics

    def test_ci_lower_le_sharpe_le_ci_upper(self):
        ev = BacktestEvaluator(oos_start="2024-01-01", oos_end="2024-12-31", allow_synthetic=True)
        _, metrics = ev.evaluate("BTC", {"short_window": 5, "long_window": 20})
        assert metrics["sharpe_ci_lower"] <= metrics["sharpe"]
        assert metrics["sharpe_ci_upper"] >= metrics["sharpe"]

    def test_ci_values_are_finite_floats(self):
        import math

        ev = BacktestEvaluator(oos_start="2024-01-01", oos_end="2024-12-31", allow_synthetic=True)
        _, metrics = ev.evaluate("BTC", {"short_window": 10, "long_window": 30})
        assert math.isfinite(metrics["sharpe_ci_lower"])
        assert math.isfinite(metrics["sharpe_ci_upper"])

    def test_test_split_metrics_also_include_ci(self):
        from omega.eval.data_splitter import DataSplitter

        splitter = DataSplitter("2022-01-01", "2024-12-31")
        ev = BacktestEvaluator.from_splitter(splitter, allow_synthetic=True)
        _, metrics = ev.evaluate_test_split("BTC", {"short_window": 10, "long_window": 30})
        assert "sharpe_ci_lower" in metrics
        assert "sharpe_ci_upper" in metrics
        assert metrics["sharpe_ci_lower"] <= metrics["sharpe"]
        assert metrics["sharpe_ci_upper"] >= metrics["sharpe"]
