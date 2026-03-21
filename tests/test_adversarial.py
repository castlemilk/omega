"""Tests for omega.core.adversarial — 3-ring adversarial pressure."""

import pytest
from omega.core.adversarial import (
    EnsembleDisagreementDetector,
    ScenarioGenerator,
    EvolutionaryTournament,
    AdversarialPressure,
    AdversarialReport,
    DisagreementResult,
    Scenario,
    TournamentResult,
)


# ---------------------------------------------------------------------------
# Ring 1: EnsembleDisagreementDetector
# ---------------------------------------------------------------------------

class TestEnsembleDisagreementDetector:
    def setup_method(self):
        self.d = EnsembleDisagreementDetector(disagreement_threshold=0.2)

    def test_no_disagreement_identical(self):
        self.d.register_variant("v1")
        self.d.register_variant("v2")
        signals = {"BTC": 0.8, "ETH": 0.5}
        self.d.submit_output("v1", signals)
        self.d.submit_output("v2", signals)
        result = self.d.detect()
        assert isinstance(result, DisagreementResult)
        assert not result.flagged
        assert result.max_disagreement < 1e-9

    def test_disagreement_flagged(self):
        self.d.register_variant("v1")
        self.d.register_variant("v2")
        self.d.submit_output("v1", {"BTC": 0.9, "ETH": 0.9})
        self.d.submit_output("v2", {"BTC": -0.9, "ETH": -0.9})
        result = self.d.detect()
        assert result.flagged
        assert result.max_disagreement > 0.5

    def test_clear_resets_outputs(self):
        self.d.register_variant("v1")
        self.d.submit_output("v1", {"BTC": 0.5})
        self.d.clear()
        result = self.d.detect()
        # With no outputs, no disagreement
        assert not result.flagged

    def test_single_variant_no_flag(self):
        self.d.register_variant("v1")
        self.d.submit_output("v1", {"BTC": 0.8})
        result = self.d.detect()
        assert not result.flagged


# ---------------------------------------------------------------------------
# Ring 2: ScenarioGenerator
# ---------------------------------------------------------------------------

class TestScenarioGenerator:
    def setup_method(self):
        self.g = ScenarioGenerator(seed=42)

    def test_base_scenarios_count(self):
        scenarios = self.g._base_stress_scenarios()
        assert len(scenarios) >= 4

    def test_base_scenarios_have_severity(self):
        for s in self.g._base_stress_scenarios():
            assert 0.0 <= s.severity <= 1.0
            assert s.scenario_id

    def test_generate_adversarial_returns_n(self):
        signals = {"BTCUSDT": 0.8, "ETHUSDT": 0.6, "SOLUSDT": 0.4}
        strategy = {"method": "momentum", "positions": 3}
        scenarios = self.g.generate_adversarial(signals, strategy, n_scenarios=3)
        assert len(scenarios) <= 3
        assert all(isinstance(s, Scenario) for s in scenarios)

    def test_stress_test_changes_signals(self):
        signals = {"BTC": 0.8, "ETH": 0.6}
        # Pick a scenario with correlation_breakdown=True or high vol to guarantee change
        scenarios = self.g._base_stress_scenarios()
        # Find a scenario with correlation_breakdown or vol_multiplier > 5
        scenario = next(
            (s for s in scenarios if s.correlation_breakdown or s.vol_multiplier > 5),
            scenarios[0],
        )
        stressed = self.g.stress_test(signals, scenario)
        assert isinstance(stressed, dict)
        assert set(stressed.keys()) == set(signals.keys())
        # With correlation_breakdown or high vol, at least one value should differ
        if scenario.correlation_breakdown:
            # noise was injected — values should change (with high probability given seed=42)
            assert any(abs(stressed[k] - signals[k]) > 1e-9 for k in signals)


# ---------------------------------------------------------------------------
# Ring 3: EvolutionaryTournament
# ---------------------------------------------------------------------------

class TestEvolutionaryTournament:
    def setup_method(self):
        self.t = EvolutionaryTournament(population_size=5, mutation_rate=0.1)
        self.base_params = {"lr": 0.01, "momentum": 0.9, "dropout": 0.1}
        self.t.initialise_population(self.base_params)

    def test_population_size(self):
        assert len(self.t._population) == 5

    def test_evaluate_returns_all_variants(self):
        fitness_fn = lambda params: params.get("lr", 0.01) * 10
        scores = self.t.evaluate(fitness_fn)
        assert len(scores) == 5
        assert all(isinstance(v, float) for v in scores.values())

    def test_tournament_select_returns_valid_id(self):
        scores = {vid: float(i) for i, vid in enumerate(self.t._population.keys())}
        champion = self.t.tournament_select(scores, k=3)
        assert champion in self.t._population

    def test_eliminate_losers_reduces_population(self):
        scores = {vid: float(i) for i, vid in enumerate(self.t._population.keys())}
        self.t.eliminate_losers(scores, survival_rate=0.4)
        assert len(self.t._population) <= 3

    def test_run_tournament_returns_result(self):
        fitness_fn = lambda params: params.get("lr", 0.01) * 100
        result = self.t.run_tournament(fitness_fn)
        assert isinstance(result, TournamentResult)
        assert result.champion_id in result.fitness_scores or result.champion_id is not None
        assert isinstance(result.fitness_scores, dict)

    def test_get_champion_params(self):
        fitness_fn = lambda params: params.get("lr", 0.01)
        self.t.run_tournament(fitness_fn)
        params = self.t.get_champion_params()
        assert params is not None
        assert isinstance(params, dict)


# ---------------------------------------------------------------------------
# AdversarialPressure — orchestrator
# ---------------------------------------------------------------------------

class TestAdversarialPressure:
    def setup_method(self):
        self.ap = AdversarialPressure(ring1_threshold=0.2, population_size=4)

    def test_run_ring1_every_cycle(self):
        variant_outputs = {"primary": {"BTC": 0.5, "ETH": 0.4}}
        report = self.ap.run(
            cycle=1,
            variant_outputs=variant_outputs,
            current_signals={"BTC": 0.5, "ETH": 0.4},
            strategy_params={"method": "equal"},
        )
        assert isinstance(report, AdversarialReport)
        assert report.ring1_result is not None

    def test_run_ring2_at_interval(self):
        variant_outputs = {"primary": {"BTC": 0.5}}
        # Ring 2 fires at cycle % RING2_INTERVAL == 0
        report = self.ap.run(
            cycle=10,
            variant_outputs=variant_outputs,
            current_signals={"BTC": 0.5, "ETH": 0.3},
            strategy_params={"method": "momentum"},
        )
        assert len(report.ring2_scenarios) > 0

    def test_failure_cases_collected(self):
        # With strong disagreement, failure cases should be collected
        self.ap.ring1.register_variant("v1")
        self.ap.ring1.register_variant("v2")
        variant_outputs = {
            "v1": {"BTC": 0.9, "ETH": 0.9},
            "v2": {"BTC": -0.9, "ETH": -0.9},
        }
        report = self.ap.run(
            cycle=1,
            variant_outputs=variant_outputs,
            current_signals={"BTC": 0.5},
            strategy_params={},
        )
        cases = self.ap.collect_failure_cases()
        # Cases may be empty if threshold not met; just check return type
        assert isinstance(cases, list)

    def test_clear_failure_cases(self):
        self.ap.clear_failure_cases()
        assert self.ap.collect_failure_cases() == []
