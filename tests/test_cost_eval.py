"""Tests for omega.eval.cost_eval — CostEvaluator."""

from __future__ import annotations

import math

import pytest

from omega.eval.cost_eval import (
    DEFAULT_INPUT_COST_PER_1M,
    DEFAULT_OUTPUT_COST_PER_1M,
    TYPICAL_TOKEN_BUDGETS,
    CostEvaluator,
    CostReport,
    CycleTokenUsage,
)

# ---------------------------------------------------------------------------
# CycleTokenUsage
# ---------------------------------------------------------------------------


class TestCycleTokenUsage:
    def test_creation(self):
        usage = CycleTokenUsage(
            cycle_type="signal_analysis",
            input_tokens=1200,
            output_tokens=300,
            cost_usd=0.001,
        )
        assert usage.cycle_type == "signal_analysis"
        assert usage.input_tokens == 1200


# ---------------------------------------------------------------------------
# CostEvaluator — basic recording
# ---------------------------------------------------------------------------


class TestCostEvaluatorRecording:
    def test_record_cycle_returns_usage(self):
        ev = CostEvaluator()
        usage = ev.record_cycle("signal_analysis", 1200, 300)
        assert isinstance(usage, CycleTokenUsage)
        assert usage.cycle_type == "signal_analysis"
        assert usage.input_tokens == 1200
        assert usage.output_tokens == 300
        assert usage.cost_usd > 0

    def test_cost_calculation(self):
        ev = CostEvaluator(input_cost_per_1m=3.0, output_cost_per_1m=15.0)
        usage = ev.record_cycle("test", 1_000_000, 1_000_000)
        # $3 input + $15 output = $18
        assert usage.cost_usd == pytest.approx(18.0, rel=1e-6)

    def test_record_typical_cycle(self):
        ev = CostEvaluator()
        records = ev.record_typical_cycle("signal_analysis", n=3)
        assert len(records) == 3
        for r in records:
            assert r.cycle_type == "signal_analysis"

    def test_record_typical_cycle_unknown_type(self):
        ev = CostEvaluator()
        records = ev.record_typical_cycle("unknown_type", n=2)
        assert len(records) == 2

    def test_clear(self):
        ev = CostEvaluator()
        ev.record_cycle("a", 100, 50)
        ev.record_cycle("b", 200, 100)
        ev.clear()
        assert ev.total_cost_usd() == 0.0
        assert ev.cost_per_cycle_type() == {}

    def test_total_cost_accumulates(self):
        ev = CostEvaluator()
        ev.record_cycle("a", 1000, 200)
        ev.record_cycle("b", 500, 100)
        total = ev.total_cost_usd()
        assert total > 0
        # Should be sum of both records
        usage_a = ev._compute_cost(1000, 200)
        usage_b = ev._compute_cost(500, 100)
        assert total == pytest.approx(usage_a + usage_b, rel=1e-9)


# ---------------------------------------------------------------------------
# CostEvaluator — cost_per_cycle_type
# ---------------------------------------------------------------------------


class TestCostPerCycleType:
    def test_groups_by_type(self):
        ev = CostEvaluator()
        ev.record_cycle("signal_analysis", 1000, 200)
        ev.record_cycle("signal_analysis", 1000, 200)
        ev.record_cycle("parameter_proposal", 800, 150)
        costs = ev.cost_per_cycle_type()
        assert "signal_analysis" in costs
        assert "parameter_proposal" in costs
        # signal_analysis should be ~2x the cost of parameter_proposal (roughly)
        assert costs["signal_analysis"] > costs["parameter_proposal"]

    def test_empty_returns_empty_dict(self):
        ev = CostEvaluator()
        assert ev.cost_per_cycle_type() == {}

    def test_tokens_per_type(self):
        ev = CostEvaluator()
        ev.record_cycle("signal_analysis", 1000, 200)
        ev.record_cycle("signal_analysis", 500, 100)
        tokens = ev.tokens_per_cycle_type()
        assert tokens["signal_analysis"] == 1800  # (1000+200) + (500+100)


# ---------------------------------------------------------------------------
# CostEvaluator — cost_per_sharpe_unit
# ---------------------------------------------------------------------------


class TestCostPerSharpeUnit:
    def test_positive_sharpe(self):
        ev = CostEvaluator()
        ev.record_cycle("signal_analysis", 1000, 200)
        cps = ev.cost_per_sharpe_unit(sharpe=1.5)
        assert cps > 0
        assert math.isfinite(cps)

    def test_zero_sharpe_returns_inf(self):
        ev = CostEvaluator()
        ev.record_cycle("signal_analysis", 1000, 200)
        cps = ev.cost_per_sharpe_unit(sharpe=0.0)
        assert cps == math.inf

    def test_negative_sharpe_returns_inf(self):
        ev = CostEvaluator()
        ev.record_cycle("signal_analysis", 1000, 200)
        cps = ev.cost_per_sharpe_unit(sharpe=-0.5)
        assert cps == math.inf

    def test_custom_total_cost_override(self):
        ev = CostEvaluator()
        cps = ev.cost_per_sharpe_unit(sharpe=2.0, total_cost=10.0)
        assert cps == pytest.approx(5.0, rel=1e-6)

    def test_higher_sharpe_lower_cost_per_unit(self):
        ev = CostEvaluator()
        ev.record_cycle("signal_analysis", 1000, 200)
        cps_low = ev.cost_per_sharpe_unit(sharpe=0.5)
        cps_high = ev.cost_per_sharpe_unit(sharpe=2.0)
        assert cps_high < cps_low


# ---------------------------------------------------------------------------
# CostEvaluator — cost_adjusted_sharpe
# ---------------------------------------------------------------------------


class TestCostAdjustedSharpe:
    def test_cost_reduces_sharpe(self):
        ev = CostEvaluator()
        # Record significant cost
        for _ in range(100):
            ev.record_cycle("signal_analysis", 10_000, 3_000)

        raw = 1.5
        adjusted = ev.cost_adjusted_sharpe(raw_sharpe=raw, capital=100_000.0)
        assert adjusted < raw

    def test_zero_capital(self):
        ev = CostEvaluator()
        ev.record_cycle("signal_analysis", 1000, 200)
        adjusted = ev.cost_adjusted_sharpe(raw_sharpe=1.0, capital=0.0)
        # Should return raw_sharpe when capital=0
        assert adjusted == pytest.approx(1.0, rel=1e-6)

    def test_zero_cost_unchanged_sharpe(self):
        ev = CostEvaluator()
        # No records → zero cost
        adjusted = ev.cost_adjusted_sharpe(raw_sharpe=1.5, capital=100_000.0)
        assert adjusted == pytest.approx(1.5, rel=1e-6)

    def test_custom_cost_override(self):
        ev = CostEvaluator()
        adjusted = ev.cost_adjusted_sharpe(raw_sharpe=1.0, total_cost=0.0, capital=100_000.0)
        assert adjusted == pytest.approx(1.0, rel=1e-6)


# ---------------------------------------------------------------------------
# CostEvaluator — break_even_capital
# ---------------------------------------------------------------------------


class TestBreakEvenCapital:
    def test_positive_improvement_returns_finite(self):
        ev = CostEvaluator()
        ev.record_cycle("signal_analysis", 1000, 200)
        bec = ev.break_even_capital(sharpe_improvement=0.1)
        assert math.isfinite(bec)
        assert bec > 0

    def test_zero_improvement_returns_inf(self):
        ev = CostEvaluator()
        ev.record_cycle("signal_analysis", 1000, 200)
        bec = ev.break_even_capital(sharpe_improvement=0.0)
        assert bec == math.inf

    def test_custom_cost_per_cycle(self):
        ev = CostEvaluator()
        bec = ev.break_even_capital(cost_per_cycle=0.01, sharpe_improvement=0.1)
        assert math.isfinite(bec)
        # At 0.1 Sharpe improvement with 15% vol: +0.015/year return
        # Annual cost = 0.01 * 252 = 2.52
        # BEC = 2.52 / 0.015 = 168
        expected = (0.01 * 252) / (0.1 * 0.15)
        assert bec == pytest.approx(expected, rel=1e-4)

    def test_higher_cost_higher_bec(self):
        ev = CostEvaluator()
        bec_low = ev.break_even_capital(cost_per_cycle=0.001, sharpe_improvement=0.2)
        bec_high = ev.break_even_capital(cost_per_cycle=0.01, sharpe_improvement=0.2)
        assert bec_high > bec_low

    def test_higher_improvement_lower_bec(self):
        ev = CostEvaluator()
        bec_small = ev.break_even_capital(cost_per_cycle=0.005, sharpe_improvement=0.05)
        bec_large = ev.break_even_capital(cost_per_cycle=0.005, sharpe_improvement=0.5)
        assert bec_large < bec_small


# ---------------------------------------------------------------------------
# CostEvaluator — roi_by_subsystem
# ---------------------------------------------------------------------------


class TestROIBySubsystem:
    def test_returns_dict(self):
        ev = CostEvaluator()
        for ct in TYPICAL_TOKEN_BUDGETS:
            ev.record_typical_cycle(ct, n=10)
        attributions = {"ring1": 0.3, "memory": 0.1, "tpe": 0.2, "autonomy": 0.0, "signals": 0.5}
        roi = ev.roi_by_subsystem(attributions, capital=500_000.0)
        assert isinstance(roi, dict)

    def test_high_sharpe_attribution_positive_roi(self):
        ev = CostEvaluator(input_cost_per_1m=0.1, output_cost_per_1m=0.1)  # very cheap
        for ct in ["signal_analysis"]:
            ev.record_typical_cycle(ct, n=10)
        attributions = {"signals": 2.0}  # massive Sharpe contribution
        roi = ev.roi_by_subsystem(attributions, capital=1_000_000.0)
        assert roi.get("signals", 0) > 0

    def test_zero_attribution_zero_or_inf_roi(self):
        ev = CostEvaluator()
        attributions = {"autonomy": 0.0}
        roi = ev.roi_by_subsystem(attributions)
        # autonomy has no direct cost, so ROI = 0 (zero contribution, zero cost)
        assert roi.get("autonomy") == 0.0 or roi.get("autonomy") == math.inf

    def test_empty_attributions(self):
        ev = CostEvaluator()
        roi = ev.roi_by_subsystem({})
        assert roi == {}


# ---------------------------------------------------------------------------
# CostEvaluator — report
# ---------------------------------------------------------------------------


class TestCostReport:
    def test_report_returns_cost_report(self):
        ev = CostEvaluator()
        for ct in ["signal_analysis", "parameter_proposal"]:
            ev.record_typical_cycle(ct, n=5)
        report = ev.report(sharpe=1.2, capital=200_000.0)
        assert isinstance(report, CostReport)

    def test_report_str(self):
        ev = CostEvaluator()
        ev.record_typical_cycle("signal_analysis", n=3)
        report = ev.report(sharpe=1.0)
        s = str(report)
        assert "CostReport" in s
        assert "signal_analysis" in s

    def test_report_total_cycles(self):
        ev = CostEvaluator()
        ev.record_cycle("a", 100, 50)
        ev.record_cycle("b", 200, 100)
        report = ev.report()
        assert report.total_cycles == 2

    def test_report_cost_consistency(self):
        ev = CostEvaluator()
        ev.record_cycle("a", 1000, 200)
        ev.record_cycle("b", 500, 100)
        report = ev.report()
        assert report.total_cost_usd == pytest.approx(ev.total_cost_usd(), rel=1e-9)
        assert report.cost_per_cycle == pytest.approx(report.total_cost_usd / 2, rel=1e-9)


# ---------------------------------------------------------------------------
# Default constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_typical_budgets_defined(self):
        for ct in ["signal_analysis", "parameter_proposal", "scenario_generation"]:
            assert ct in TYPICAL_TOKEN_BUDGETS

    def test_default_pricing(self):
        assert DEFAULT_INPUT_COST_PER_1M == 3.0
        assert DEFAULT_OUTPUT_COST_PER_1M == 15.0
