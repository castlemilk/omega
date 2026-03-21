"""Tests for omega.core.scenario_bank."""

from __future__ import annotations

import pytest

from omega.core.adversarial import Scenario
from omega.core.scenario_bank import (
    HistoricalScenarioBank,
    RunResult,
    ScenarioRecord,
    ScenarioRunner,
    SimulationGate,
    SyntheticScenarioGenerator,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


BASE_SIGNALS = {"BTCUSDT": 0.8, "ETHUSDT": 0.6, "SOLUSDT": 0.4}


def simple_strategy(signals: dict, scenario: Scenario) -> dict:
    """Trivial pass-through strategy that clips negative values to 0."""
    return {t: max(0.0, s) for t, s in signals.items()}


def zero_strategy(signals: dict, scenario: Scenario) -> dict:
    """Strategy that always returns zero signals (worst case)."""
    return {t: 0.0 for t in signals}


def panic_strategy(signals: dict, scenario: Scenario) -> dict:
    """Strategy that raises on flash crash scenarios."""
    if "flash" in scenario.name.lower() or "crash" in scenario.name.lower():
        raise RuntimeError("Strategy panicked on crash scenario")
    return {t: max(0.0, s) for t, s in signals.items()}


# ---------------------------------------------------------------------------
# HistoricalScenarioBank
# ---------------------------------------------------------------------------


class TestHistoricalScenarioBank:
    def test_loads_canonical_scenarios(self):
        bank = HistoricalScenarioBank()
        assert len(bank) >= 7, "Expected at least 7 canonical historical scenarios"

    def test_get_by_tag_crash(self):
        bank = HistoricalScenarioBank()
        crashes = bank.get_by_tag("crash")
        assert len(crashes) >= 3

    def test_get_by_tag_historical(self):
        bank = HistoricalScenarioBank()
        hist = bank.get_by_tag("historical")
        assert len(hist) >= 5

    def test_get_by_severity_high(self):
        bank = HistoricalScenarioBank()
        severe = bank.get_by_severity(min_severity=0.90)
        assert len(severe) >= 2
        for record in severe:
            assert record.scenario.severity >= 0.90

    def test_get_by_severity_range(self):
        bank = HistoricalScenarioBank()
        mid = bank.get_by_severity(min_severity=0.70, max_severity=0.85)
        for record in mid:
            assert 0.70 <= record.scenario.severity <= 0.85

    def test_add_custom_scenario(self):
        bank = HistoricalScenarioBank()
        initial_count = len(bank)
        custom = Scenario(
            scenario_id="test_custom_001",
            name="Test Custom",
            description="A custom test scenario",
            market_shocks={"BTCUSDT": -0.10},
            vol_multiplier=1.5,
            correlation_breakdown=False,
            severity=0.50,
        )
        record = ScenarioRecord(
            scenario=custom,
            tags=["custom", "test"],
            source="user",
        )
        bank.add(record)
        assert len(bank) == initial_count + 1
        assert bank.get("test_custom_001") is not None

    def test_get_nonexistent_returns_none(self):
        bank = HistoricalScenarioBank()
        assert bank.get("does_not_exist_xyz") is None

    def test_all_scenarios_returns_list(self):
        bank = HistoricalScenarioBank()
        scenarios = bank.all_scenarios()
        assert isinstance(scenarios, list)
        assert all(isinstance(s, Scenario) for s in scenarios)

    def test_all_records_returns_records(self):
        bank = HistoricalScenarioBank()
        records = bank.all_records()
        assert all(isinstance(r, ScenarioRecord) for r in records)

    def test_scenario_fields_valid(self):
        bank = HistoricalScenarioBank()
        for record in bank.all_records():
            s = record.scenario
            assert 0.0 <= s.severity <= 1.0
            assert s.vol_multiplier >= 1.0
            assert s.scenario_id
            assert s.name
            assert isinstance(s.market_shocks, dict)


# ---------------------------------------------------------------------------
# SyntheticScenarioGenerator
# ---------------------------------------------------------------------------


class TestSyntheticScenarioGenerator:
    def test_generate_returns_correct_count(self):
        gen = SyntheticScenarioGenerator(seed=42)
        scenarios = gen.generate(BASE_SIGNALS, n_scenarios=8)
        assert len(scenarios) == 8

    def test_generate_sorted_by_severity_desc(self):
        gen = SyntheticScenarioGenerator(seed=42)
        scenarios = gen.generate(BASE_SIGNALS, n_scenarios=10)
        severities = [s.severity for s in scenarios]
        assert severities == sorted(severities, reverse=True)

    def test_generate_empty_signals_returns_empty(self):
        gen = SyntheticScenarioGenerator(seed=0)
        scenarios = gen.generate({}, n_scenarios=5)
        assert scenarios == []

    def test_generate_amplitude_scaling(self):
        gen = SyntheticScenarioGenerator(seed=7)
        scenarios = gen.generate(BASE_SIGNALS, n_scenarios=20, modes=["amplitude_scaling"])
        assert len(scenarios) == 20
        for s in scenarios:
            # All amplitude shocks should be present for each ticker
            for ticker in BASE_SIGNALS:
                assert ticker in s.market_shocks

    def test_generate_tail_shock(self):
        gen = SyntheticScenarioGenerator(seed=3)
        scenarios = gen.generate(BASE_SIGNALS, n_scenarios=5, modes=["tail_shock"])
        for s in scenarios:
            # Tail shock targets highest signal asset — BTCUSDT=0.8 is highest
            assert "BTCUSDT" in s.market_shocks

    def test_generate_regime_flip(self):
        gen = SyntheticScenarioGenerator(seed=99)
        scenarios = gen.generate(BASE_SIGNALS, n_scenarios=5, modes=["regime_flip"])
        for s in scenarios:
            # Regime flip inverts directions
            for ticker, sig in BASE_SIGNALS.items():
                shock = s.market_shocks.get(ticker, 0.0)
                # inverted: shock = -sig * 0.5 → same sign as -sig
                expected_sign = -1 if sig > 0 else (1 if sig < 0 else 0)
                if sig != 0:
                    assert (shock * expected_sign) >= 0, (
                        f"Expected shock sign for {ticker} to match -{sig}"
                    )

    def test_generate_correlation_nuke_sets_breakdown(self):
        gen = SyntheticScenarioGenerator(seed=5)
        scenarios = gen.generate(BASE_SIGNALS, n_scenarios=5, modes=["correlation_nuke"])
        for s in scenarios:
            assert s.correlation_breakdown is True

    def test_generate_vol_explosion_zero_shocks(self):
        gen = SyntheticScenarioGenerator(seed=1)
        scenarios = gen.generate(BASE_SIGNALS, n_scenarios=5, modes=["vol_explosion"])
        for s in scenarios:
            for shock in s.market_shocks.values():
                assert shock == 0.0
            assert s.vol_multiplier >= 5.0

    def test_perturb_specific_mode(self):
        gen = SyntheticScenarioGenerator(seed=42)
        s = gen.perturb(BASE_SIGNALS, mode="regime_flip", intensity=1.0)
        assert "regime" in s.name.lower() or "flip" in s.name.lower()

    def test_perturb_unknown_mode_returns_zero_severity(self):
        gen = SyntheticScenarioGenerator(seed=0)
        s = gen.perturb(BASE_SIGNALS, mode="invalid_mode")
        assert s.severity == 0.0

    def test_severity_clamped_0_to_1(self):
        gen = SyntheticScenarioGenerator(seed=42)
        scenarios = gen.generate(BASE_SIGNALS, n_scenarios=30)
        for s in scenarios:
            assert 0.0 <= s.severity <= 1.0

    def test_scenario_ids_unique(self):
        gen = SyntheticScenarioGenerator(seed=42)
        scenarios = gen.generate(BASE_SIGNALS, n_scenarios=20)
        ids = [s.scenario_id for s in scenarios]
        assert len(ids) == len(set(ids)), "Scenario IDs should be unique"

    def test_deterministic_with_seed(self):
        gen1 = SyntheticScenarioGenerator(seed=123)
        gen2 = SyntheticScenarioGenerator(seed=123)
        s1 = gen1.generate(BASE_SIGNALS, n_scenarios=5, modes=["amplitude_scaling"])
        s2 = gen2.generate(BASE_SIGNALS, n_scenarios=5, modes=["amplitude_scaling"])
        for a, b in zip(s1, s2, strict=True):
            assert abs(a.severity - b.severity) < 1e-9


# ---------------------------------------------------------------------------
# ScenarioRunner
# ---------------------------------------------------------------------------


class TestScenarioRunner:
    def _make_scenarios(self, n: int = 3) -> list[Scenario]:
        return [
            Scenario(
                scenario_id=f"test_s{i}",
                name=f"Test Scenario {i}",
                description="",
                market_shocks={"BTCUSDT": -0.10 * i, "ETHUSDT": -0.05 * i},
                vol_multiplier=1.5,
                correlation_breakdown=False,
                severity=0.3 * i,
            )
            for i in range(1, n + 1)
        ]

    def test_run_returns_one_result_per_scenario(self):
        runner = ScenarioRunner(strategy=simple_strategy, pass_threshold=0.30)
        scenarios = self._make_scenarios(4)
        results = runner.run(scenarios, BASE_SIGNALS)
        assert len(results) == 4

    def test_run_result_fields(self):
        runner = ScenarioRunner(strategy=simple_strategy, pass_threshold=0.30)
        scenarios = self._make_scenarios(2)
        results = runner.run(scenarios, BASE_SIGNALS)
        for r in results:
            assert isinstance(r, RunResult)
            assert 0.0 <= r.resilience_score <= 1.0
            assert isinstance(r.passed, bool)
            assert r.scenario_id
            assert r.scenario_name

    def test_zero_strategy_scores_zero(self):
        runner = ScenarioRunner(strategy=zero_strategy, pass_threshold=0.30)
        scenarios = self._make_scenarios(3)
        results = runner.run(scenarios, BASE_SIGNALS)
        for r in results:
            assert r.resilience_score == pytest.approx(0.0)
            assert r.passed is False

    def test_simple_strategy_scores_positive(self):
        runner = ScenarioRunner(strategy=simple_strategy, pass_threshold=0.10)
        scenarios = self._make_scenarios(3)
        results = runner.run(scenarios, BASE_SIGNALS)
        for r in results:
            assert r.resilience_score >= 0.0

    def test_panicking_strategy_does_not_raise(self):
        runner = ScenarioRunner(strategy=panic_strategy, pass_threshold=0.30)
        scenarios = self._make_scenarios(3)
        # Should not raise; exceptions are caught and scored 0
        results = runner.run(scenarios, BASE_SIGNALS)
        assert len(results) == 3

    def test_custom_resilience_scorer(self):
        # Custom scorer always returns 1.0
        runner = ScenarioRunner(
            strategy=zero_strategy,
            resilience_scorer=lambda out, sc: 1.0,
            pass_threshold=0.30,
        )
        scenarios = self._make_scenarios(2)
        results = runner.run(scenarios, BASE_SIGNALS)
        for r in results:
            assert r.resilience_score == pytest.approx(1.0)
            assert r.passed is True

    def test_pass_threshold_respected(self):
        # Zero strategy scores 0; anything above 0 threshold should fail
        runner = ScenarioRunner(strategy=zero_strategy, pass_threshold=0.01)
        scenarios = self._make_scenarios(2)
        results = runner.run(scenarios, BASE_SIGNALS)
        for r in results:
            assert r.passed is False

    def test_empty_scenario_list(self):
        runner = ScenarioRunner(strategy=simple_strategy)
        results = runner.run([], BASE_SIGNALS)
        assert results == []

    def test_details_contains_stressed_signals(self):
        runner = ScenarioRunner(strategy=simple_strategy)
        scenarios = self._make_scenarios(1)
        results = runner.run(scenarios, BASE_SIGNALS)
        assert "stressed_signals" in results[0].details
        assert "base_signals" in results[0].details


# ---------------------------------------------------------------------------
# SimulationGate
# ---------------------------------------------------------------------------


class TestSimulationGate:
    def _make_run_results(
        self,
        resiliences: list[float],
        severities: list[float] | None = None,
        pass_threshold: float = 0.30,
    ) -> list[RunResult]:
        if severities is None:
            severities = [0.5] * len(resiliences)
        results = []
        for i, (res, sev) in enumerate(zip(resiliences, severities, strict=True)):
            results.append(
                RunResult(
                    scenario_id=f"s{i}",
                    scenario_name=f"Scenario {i}",
                    severity=sev,
                    raw_output={},
                    resilience_score=res,
                    passed=res >= pass_threshold,
                )
            )
        return results

    def test_gate_passes_when_all_criteria_met(self):
        gate = SimulationGate(
            min_overall_resilience=0.30,
            min_worst_case=0.15,
            min_pass_rate=0.60,
            min_severe_pass_rate=0.50,
        )
        results = self._make_run_results(
            resiliences=[0.6, 0.5, 0.7, 0.4, 0.55],
            severities=[0.5, 0.5, 0.5, 0.5, 0.5],
        )
        report = gate.evaluate("test_strat", results)
        assert report.gate_passed is True
        assert "passed" in report.gate_reason.lower()

    def test_gate_fails_low_overall_resilience(self):
        gate = SimulationGate(min_overall_resilience=0.80)
        results = self._make_run_results(resiliences=[0.3, 0.2, 0.4])
        report = gate.evaluate("test_strat", results)
        assert report.gate_passed is False
        assert "overall_resilience" in report.gate_reason

    def test_gate_fails_worst_case(self):
        gate = SimulationGate(min_worst_case=0.50)
        results = self._make_run_results(resiliences=[0.9, 0.8, 0.1])
        report = gate.evaluate("test_strat", results)
        assert report.gate_passed is False
        assert "worst_case" in report.gate_reason

    def test_gate_fails_pass_rate(self):
        gate = SimulationGate(min_pass_rate=0.90, min_worst_case=0.0)
        results = self._make_run_results(resiliences=[0.1, 0.1, 0.1, 0.8, 0.8])
        report = gate.evaluate("test_strat", results)
        assert report.gate_passed is False
        assert "pass_rate" in report.gate_reason

    def test_gate_fails_severe_pass_rate(self):
        gate = SimulationGate(
            min_overall_resilience=0.0,
            min_worst_case=0.0,
            min_pass_rate=0.0,
            min_severe_pass_rate=0.80,
            severe_threshold=0.80,
        )
        results = self._make_run_results(
            resiliences=[0.5, 0.5, 0.1, 0.1],
            severities=[0.5, 0.5, 0.85, 0.90],
            pass_threshold=0.30,
        )
        report = gate.evaluate("test_strat", results)
        assert report.gate_passed is False
        assert "severe_pass_rate" in report.gate_reason

    def test_gate_empty_results(self):
        gate = SimulationGate()
        report = gate.evaluate("empty_strat", [])
        assert report.gate_passed is False
        assert "No scenario results" in report.gate_reason

    def test_report_fields(self):
        gate = SimulationGate(min_overall_resilience=0.0, min_worst_case=0.0)
        results = self._make_run_results(resiliences=[0.5, 0.6, 0.7])
        report = gate.evaluate("strat_x", results)
        assert report.strategy_id == "strat_x"
        assert len(report.run_results) == 3
        assert 0.0 <= report.overall_resilience <= 1.0
        assert report.worst_scenario
        assert isinstance(report.gate_passed, bool)

    def test_run_and_evaluate_convenience(self):
        gate = SimulationGate(
            min_overall_resilience=0.0,
            min_worst_case=0.0,
            min_pass_rate=0.0,
        )
        gen = SyntheticScenarioGenerator(seed=42)
        scenarios = gen.generate(BASE_SIGNALS, n_scenarios=5)
        report = gate.run_and_evaluate(
            strategy_id="conv_test",
            strategy=simple_strategy,
            scenarios=scenarios,
            base_signals=BASE_SIGNALS,
        )
        assert report.strategy_id == "conv_test"
        assert len(report.run_results) == 5

    def test_worst_scenario_is_lowest_resilience(self):
        gate = SimulationGate(min_overall_resilience=0.0, min_worst_case=0.0)
        results = self._make_run_results(resiliences=[0.9, 0.1, 0.7])
        report = gate.evaluate("strat", results)
        assert report.worst_scenario == "s1"
        assert report.worst_resilience == pytest.approx(0.1)

    def test_no_severe_scenarios_passes_severe_gate(self):
        """When no severe scenarios exist, severe pass rate gate should pass."""
        gate = SimulationGate(
            min_overall_resilience=0.0,
            min_worst_case=0.0,
            min_pass_rate=0.0,
            min_severe_pass_rate=0.99,
            severe_threshold=0.80,
        )
        results = self._make_run_results(
            resiliences=[0.5, 0.5],
            severities=[0.5, 0.5],
        )
        report = gate.evaluate("strat", results)
        # No severe scenarios so severe gate should not block
        assert report.gate_passed is True
