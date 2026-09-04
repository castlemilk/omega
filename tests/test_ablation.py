"""Tests for omega.eval.ablation — AblationHarness."""

from __future__ import annotations

import pytest

from omega.eval.ablation import (
    AblationHarness,
    EvalReport,
    _AblationNode,
    _max_drawdown_from_returns,
    _sharpe_from_returns,
)

# Marked slow: these run real multi-cycle Victoria simulations and take minutes.
# Unmarked, they made `pytest tests/` appear to hang, so the suite was not run —
# which is how a whole stale TestRegimeAdaptivity class sat failing unnoticed.
pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_harness(n_cycles: int = 30, seed: int = 42) -> AblationHarness:
    return AblationHarness(n_cycles=n_cycles, base_sharpe=1.2, seed=seed)


# ---------------------------------------------------------------------------
# EvalReport
# ---------------------------------------------------------------------------


class TestEvalReport:
    def test_repr(self):
        report = EvalReport(
            ablation_name="test",
            n_cycles=10,
            sharpe=1.5,
            max_drawdown=0.05,
            avg_signals_per_cycle=2.0,
            adversarial_flag_rate=0.1,
            error_rate=0.0,
            trades_executed=8,
            improvement_cycles=0,
            duration_seconds=0.1,
        )
        r = repr(report)
        assert "test" in r
        assert "1.5" in r


# ---------------------------------------------------------------------------
# _AblationNode
# ---------------------------------------------------------------------------


class TestAblationNode:
    def test_capabilities(self):
        node = _AblationNode()
        caps = node.get_capabilities()
        assert "poll" in caps
        assert "compute_signals" in caps
        assert "construct_portfolio" in caps

    def test_poll(self):
        from omega.core.node import NodeInput

        node = _AblationNode(seed=1)
        inp = NodeInput(action="poll", parameters={}, context={})
        out = node.execute(inp)
        assert out.success
        assert "price" in out.result

    def test_compute_signals_advanced(self):
        from omega.core.node import NodeInput

        node = _AblationNode(use_advanced=True, seed=1)
        inp = NodeInput(action="compute_signals", parameters={}, context={})
        out = node.execute(inp)
        assert out.success
        assert "composite_signal" in out.result

    def test_compute_signals_basic(self):
        from omega.core.node import NodeInput

        node = _AblationNode(use_advanced=False, seed=1)
        inp = NodeInput(action="compute_signals", parameters={}, context={})
        out = node.execute(inp)
        assert out.success
        assert "composite_signal" in out.result

    def test_portfolio_pico_mode(self):
        from omega.core.node import NodeInput

        node = _AblationNode(pico_forced=True, seed=1)
        for _ in range(10):
            inp = NodeInput(
                action="construct_portfolio",
                parameters={"pico_mode": False},
                context={},
            )
            node.execute(inp)
        assert len(node.returns) == 10


# ---------------------------------------------------------------------------
# AblationHarness — individual runs
# ---------------------------------------------------------------------------


class TestAblationHaressIndividual:
    def test_run_full_returns_eval_report(self):
        harness = make_harness(n_cycles=20)
        report = harness.run_full()
        assert isinstance(report, EvalReport)
        assert report.ablation_name == "full"
        assert report.n_cycles == 20

    def test_run_without_ring1(self):
        harness = make_harness(n_cycles=20)
        report = harness.run_without_ring1()
        assert report.ablation_name == "no_ring1"
        assert report.n_cycles == 20

    def test_run_without_memory(self):
        harness = make_harness(n_cycles=20)
        report = harness.run_without_memory()
        assert report.ablation_name == "no_memory"

    def test_run_without_tpe(self):
        harness = make_harness(n_cycles=20)
        report = harness.run_without_tpe()
        assert report.ablation_name == "no_tpe"

    def test_run_without_autonomy(self):
        harness = make_harness(n_cycles=20)
        report = harness.run_without_autonomy()
        assert report.ablation_name == "no_autonomy"

    def test_run_without_signals(self):
        harness = make_harness(n_cycles=20)
        report = harness.run_without_signals()
        assert report.ablation_name == "no_signals"

    def test_report_fields_populated(self):
        harness = make_harness(n_cycles=15)
        report = harness.run_full()
        assert isinstance(report.sharpe, float)
        assert isinstance(report.max_drawdown, float)
        assert report.duration_seconds >= 0
        assert report.trades_executed >= 0

    def test_sharpe_is_finite(self):
        import math

        harness = make_harness(n_cycles=50)
        report = harness.run_full()
        assert math.isfinite(report.sharpe)


# ---------------------------------------------------------------------------
# AblationHarness — run_all_ablations
# ---------------------------------------------------------------------------


class TestRunAllAblations:
    def test_returns_all_names(self):
        harness = make_harness(n_cycles=10)
        results = harness.run_all_ablations()
        expected = {"full", "no_ring1", "no_memory", "no_tpe", "no_autonomy", "no_signals"}
        assert set(results.keys()) == expected

    def test_all_reports_have_cycles(self):
        harness = make_harness(n_cycles=10)
        results = harness.run_all_ablations()
        for name, report in results.items():
            assert report.n_cycles == 10, f"{name}: expected 10 cycles"

    def test_results_cached(self):
        harness = make_harness(n_cycles=10)
        results1 = harness.run_all_ablations()
        # results property returns cached copy
        cached = harness.results
        assert set(cached.keys()) == set(results1.keys())


# ---------------------------------------------------------------------------
# AblationHarness — compute_attribution
# ---------------------------------------------------------------------------


class TestComputeAttribution:
    def test_returns_dict_with_subsystems(self):
        harness = make_harness(n_cycles=15)
        harness.run_all_ablations()
        attribution = harness.compute_attribution()
        expected_keys = {"ring1", "memory", "tpe", "autonomy", "signals"}
        assert set(attribution.keys()) == expected_keys

    def test_values_are_floats(self):
        harness = make_harness(n_cycles=15)
        harness.run_all_ablations()
        attribution = harness.compute_attribution()
        for k, v in attribution.items():
            assert isinstance(v, float), f"{k} is not float"

    def test_without_full_run_returns_empty(self):
        harness = make_harness()
        result = harness.compute_attribution()
        assert result == {}

    def test_attribution_formula(self):
        """Verify attribution = Sharpe(full) - Sharpe(ablated)."""
        harness = make_harness(n_cycles=20)
        results = harness.run_all_ablations()
        attribution = harness.compute_attribution()
        full_sharpe = results["full"].sharpe
        for subsystem, ablation_name in [
            ("ring1", "no_ring1"),
            ("signals", "no_signals"),
        ]:
            expected = round(full_sharpe - results[ablation_name].sharpe, 6)
            assert attribution[subsystem] == pytest.approx(expected, abs=1e-8)


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------


class TestMetricHelpers:
    def test_sharpe_empty(self):
        assert _sharpe_from_returns([]) == 0.0

    def test_sharpe_single(self):
        assert _sharpe_from_returns([0.01]) == 0.0

    def test_sharpe_positive_returns(self):
        returns = [0.001] * 252
        s = _sharpe_from_returns(returns)
        # All identical returns → zero std → 0 Sharpe
        assert s == 0.0

    def test_sharpe_mixed_returns(self):
        import random

        rng = random.Random(42)
        returns = [rng.gauss(0.001, 0.01) for _ in range(252)]
        s = _sharpe_from_returns(returns)
        assert isinstance(s, float)

    def test_max_drawdown_empty(self):
        assert _max_drawdown_from_returns([]) == 0.0

    def test_max_drawdown_no_loss(self):
        dd = _max_drawdown_from_returns([0.01, 0.01, 0.01])
        assert dd == pytest.approx(0.0, abs=1e-9)

    def test_max_drawdown_with_loss(self):
        returns = [0.1, -0.2, 0.05]
        dd = _max_drawdown_from_returns(returns)
        assert dd > 0
