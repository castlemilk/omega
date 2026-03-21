"""
omega.core.adversarial
~~~~~~~~~~~~~~~~~~~~~~~
Three-Rings adversarial pressure architecture for the Omega system.

Ring 1 — EnsembleDisagreementDetector (every cycle)
    Runs multiple strategy variants in parallel and flags disagreement when
    pairwise Euclidean distance between their outputs exceeds a threshold.

Ring 2 — ScenarioGenerator (every N cycles)
    Generates adversarial market stress scenarios calibrated to break the
    current strategy, then stress-tests signals against those scenarios.

Ring 3 — EvolutionaryTournament (every N cycles)
    Maintains a population of strategy parameter variants, runs tournament
    selection, eliminates losers, and spawns mutations from the champion.

AdversarialPressure orchestrates all three rings and accumulates failure
cases for consumption by the improvement loop.
"""

from __future__ import annotations

import json
import logging
import math
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("omega.core.adversarial")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DisagreementResult:
    """Output of Ring 1 ensemble disagreement detection."""

    flagged: bool
    max_disagreement: float
    disagreeing_variants: List[str]
    outputs: Dict[str, Any]  # variant_id → output


@dataclass
class Scenario:
    """A single adversarial market stress scenario."""

    scenario_id: str
    name: str
    description: str
    market_shocks: Dict[str, float]  # ticker → shock multiplier
    vol_multiplier: float
    correlation_breakdown: bool
    severity: float  # 0 → 1


@dataclass
class TournamentResult:
    """Output of Ring 3 evolutionary tournament."""

    champion_id: str
    champion_params: Dict[str, Any]
    eliminated: List[str]
    fitness_scores: Dict[str, float]
    generation: int


@dataclass
class AdversarialReport:
    """Consolidated output from one full adversarial pressure cycle."""

    cycle: int
    ring1_result: Optional[DisagreementResult]
    ring2_scenarios: List[Scenario]
    ring3_result: Optional[TournamentResult]
    failure_cases: List[Dict]  # for feeding back into improvement loop


# ---------------------------------------------------------------------------
# Ring 1: EnsembleDisagreementDetector
# ---------------------------------------------------------------------------


class EnsembleDisagreementDetector:
    """
    Runs multiple strategy variants and detects when their outputs diverge
    beyond an acceptable threshold.

    Usage::

        detector = EnsembleDisagreementDetector(disagreement_threshold=0.2)
        detector.register_variant("v_a", "aggressive")
        detector.register_variant("v_b", "conservative")
        detector.submit_output("v_a", {"BTC": 0.8, "ETH": 0.6})
        detector.submit_output("v_b", {"BTC": 0.2, "ETH": 0.1})
        result = detector.detect()
        detector.clear()
    """

    def __init__(self, disagreement_threshold: float = 0.2) -> None:
        self.disagreement_threshold = disagreement_threshold
        self._variants: Dict[str, str] = {}          # variant_id → description
        self._outputs: Dict[str, Dict[str, float]] = {}  # variant_id → output

    def register_variant(self, variant_id: str, description: str = "") -> None:
        """Register a variant slot; outputs are submitted later."""
        self._variants[variant_id] = description
        logger.debug("Registered variant '%s': %s", variant_id, description)

    def submit_output(self, variant_id: str, output: Dict[str, float]) -> None:
        """Submit a variant's output (numeric dict of signal values)."""
        if variant_id not in self._variants:
            logger.warning(
                "submit_output called for unregistered variant '%s'; auto-registering.",
                variant_id,
            )
            self._variants[variant_id] = ""
        self._outputs[variant_id] = output

    def _normalised_distance(
        self, a: Dict[str, float], b: Dict[str, float]
    ) -> float:
        """
        Pairwise Euclidean distance between two signal dicts, normalised by
        the number of shared keys.

        normalised_distance = sqrt(Σ(a[k]-b[k])^2) / max(1, len(keys))
        """
        shared_keys = set(a.keys()) & set(b.keys())
        if not shared_keys:
            return 0.0
        squared_sum = sum((a[k] - b[k]) ** 2 for k in shared_keys)
        return math.sqrt(squared_sum) / max(1, len(shared_keys))

    def detect(self) -> DisagreementResult:
        """
        Compute pairwise normalised Euclidean distance between all variant
        outputs.  Flag if any pairwise distance exceeds the threshold.
        """
        variant_ids = list(self._outputs.keys())
        max_disagreement = 0.0
        disagreeing_variants: List[str] = []

        for i in range(len(variant_ids)):
            for j in range(i + 1, len(variant_ids)):
                vid_a = variant_ids[i]
                vid_b = variant_ids[j]
                dist = self._normalised_distance(
                    self._outputs[vid_a], self._outputs[vid_b]
                )
                if dist > max_disagreement:
                    max_disagreement = dist
                if dist > self.disagreement_threshold:
                    if vid_a not in disagreeing_variants:
                        disagreeing_variants.append(vid_a)
                    if vid_b not in disagreeing_variants:
                        disagreeing_variants.append(vid_b)

        flagged = max_disagreement > self.disagreement_threshold

        if flagged:
            logger.warning(
                "Ring 1: disagreement flagged — max_distance=%.4f (threshold=%.4f), "
                "variants=%s",
                max_disagreement,
                self.disagreement_threshold,
                disagreeing_variants,
            )
        else:
            logger.debug(
                "Ring 1: no disagreement — max_distance=%.4f", max_disagreement
            )

        return DisagreementResult(
            flagged=flagged,
            max_disagreement=max_disagreement,
            disagreeing_variants=disagreeing_variants,
            outputs=dict(self._outputs),
        )

    def clear(self) -> None:
        """Clear submitted outputs for next cycle."""
        self._outputs.clear()


# ---------------------------------------------------------------------------
# Ring 2: ScenarioGenerator
# ---------------------------------------------------------------------------


class ScenarioGenerator:
    """
    Generates adversarial market stress scenarios for Ring 2.

    Base scenarios are canonical (flash crash, vol spike, etc.).
    Adversarial scenarios are calibrated to target the specific assets and
    parameters of the current strategy.

    Usage::

        gen = ScenarioGenerator(seed=42)
        scenarios = gen.generate_adversarial(
            current_signals={"BTCUSDT": 0.9, "ETHUSDT": 0.7},
            strategy_params={"max_position": 0.3},
            n_scenarios=5,
        )
        stressed = gen.stress_test(signals, scenarios[0])
    """

    # Common tickers used in base scenarios
    _DEFAULT_TICKERS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT"]

    def __init__(self, seed: Optional[int] = None) -> None:
        self._rng = random.Random(seed)

    def _base_stress_scenarios(self) -> List[Scenario]:
        """Return ~6 canonical market stress scenarios."""
        tickers = self._DEFAULT_TICKERS

        return [
            # 1. Flash crash
            Scenario(
                scenario_id="base_flash_crash",
                name="Flash Crash",
                description=(
                    "Rapid liquidity withdrawal: BTC drops 30%, alts drop 20%, "
                    "volatility triples."
                ),
                market_shocks={
                    **{"BTCUSDT": -0.30},
                    **{t: -0.20 for t in tickers if t != "BTCUSDT"},
                },
                vol_multiplier=3.0,
                correlation_breakdown=False,
                severity=0.85,
            ),
            # 2. Volatility spike
            Scenario(
                scenario_id="base_vol_spike",
                name="Volatility Spike",
                description=(
                    "Volatility explodes 5×; correlations break down across the board."
                ),
                market_shocks={t: 0.0 for t in tickers},
                vol_multiplier=5.0,
                correlation_breakdown=True,
                severity=0.75,
            ),
            # 3. Correlation breakdown
            Scenario(
                scenario_id="base_corr_breakdown",
                name="Correlation Breakdown",
                description=(
                    "All pairwise correlations collapse toward zero; "
                    "diversification assumptions fail."
                ),
                market_shocks={t: 0.0 for t in tickers},
                vol_multiplier=1.5,
                correlation_breakdown=True,
                severity=0.65,
            ),
            # 4. Liquidity crisis
            Scenario(
                scenario_id="base_liquidity_crisis",
                name="Liquidity Crisis",
                description=(
                    "Universal 15% price drop as market makers withdraw; "
                    "spreads widen dramatically."
                ),
                market_shocks={t: -0.15 for t in tickers},
                vol_multiplier=2.0,
                correlation_breakdown=False,
                severity=0.70,
            ),
            # 5. Bull run
            Scenario(
                scenario_id="base_bull_run",
                name="Bull Run",
                description=(
                    "BTC rallies 40%, alts rally 60% — tests whether strategy "
                    "captures upside or lags."
                ),
                market_shocks={
                    **{"BTCUSDT": 0.40},
                    **{t: 0.60 for t in tickers if t != "BTCUSDT"},
                },
                vol_multiplier=1.8,
                correlation_breakdown=False,
                severity=0.55,
            ),
            # 6. Black swan
            Scenario(
                scenario_id="base_black_swan",
                name="Black Swan",
                description=(
                    "Catastrophic 50% BTC drop with correlations jumping to 1.0; "
                    "no refuge assets."
                ),
                market_shocks={t: -0.50 for t in tickers},
                vol_multiplier=8.0,
                correlation_breakdown=False,  # correlations collapse TO 1.0 (all move together)
                severity=0.99,
            ),
        ]

    def generate_adversarial(
        self,
        current_signals: Dict[str, float],
        strategy_params: Dict[str, Any],
        n_scenarios: int = 5,
    ) -> List[Scenario]:
        """
        Generate N adversarial scenarios calibrated to stress the current strategy.

        - Detects which assets the strategy is overweight in (highest signal scores).
        - Generates targeted stress scenarios for those assets.
        - Merges with base scenarios and returns the top N by severity.
        """
        base = self._base_stress_scenarios()
        targeted: List[Scenario] = []

        if current_signals:
            # Sort tickers by signal strength descending (overweight assets)
            sorted_signals = sorted(
                current_signals.items(), key=lambda kv: kv[1], reverse=True
            )
            # Target the top-2 overweight assets
            top_assets = [ticker for ticker, _ in sorted_signals[:2]]

            for asset in top_assets:
                # Targeted crash on the overweight asset
                shock_magnitude = -(
                    0.25 + self._rng.uniform(0.05, 0.20)
                )
                shocks: Dict[str, float] = {}
                for ticker in current_signals:
                    shocks[ticker] = (
                        shock_magnitude if ticker == asset
                        else shock_magnitude * 0.4
                    )
                targeted.append(
                    Scenario(
                        scenario_id=f"targeted_{asset.lower()}_{uuid.uuid4().hex[:6]}",
                        name=f"Targeted Crash: {asset}",
                        description=(
                            f"Adversarial scenario targeting current overweight position "
                            f"in {asset} with a {abs(shock_magnitude):.0%} shock."
                        ),
                        market_shocks=shocks,
                        vol_multiplier=2.5 + self._rng.uniform(0, 1.5),
                        correlation_breakdown=self._rng.random() > 0.5,
                        severity=min(0.95, 0.60 + abs(shock_magnitude)),
                    )
                )

            # Generate a scenario that inverts the entire signal direction
            inverted_shocks = {
                ticker: -signal * 0.3
                for ticker, signal in current_signals.items()
            }
            targeted.append(
                Scenario(
                    scenario_id=f"signal_inversion_{uuid.uuid4().hex[:6]}",
                    name="Signal Inversion",
                    description=(
                        "All current signals invert — tests robustness to regime change."
                    ),
                    market_shocks=inverted_shocks,
                    vol_multiplier=2.0,
                    correlation_breakdown=False,
                    severity=0.72,
                )
            )

        all_scenarios = base + targeted
        # Sort by severity descending, take top N
        all_scenarios.sort(key=lambda s: s.severity, reverse=True)
        return all_scenarios[:n_scenarios]

    def stress_test(
        self,
        signals: Dict[str, float],
        scenario: Scenario,
    ) -> Dict[str, float]:
        """
        Apply scenario shocks to signals and return stressed signals.

        For each ticker in signals:
          - If in market_shocks: stressed_signal = signal * (1 + shock)
          - If correlation_breakdown: add small random noise to each signal
          - Result is clamped to [-1.0, 1.0]
        """
        stressed: Dict[str, float] = {}
        for ticker, signal_val in signals.items():
            shock = scenario.market_shocks.get(ticker, 0.0)
            new_val = signal_val * (1.0 + shock)

            # Correlation breakdown: inject noise to decorrelate signals
            if scenario.correlation_breakdown:
                noise = self._rng.uniform(-0.15, 0.15)
                new_val += noise

            # Scale by vol multiplier effect on signal magnitude
            new_val *= min(1.0, 1.0 / max(1.0, scenario.vol_multiplier * 0.2))

            # Clamp to [-1, 1]
            new_val = max(-1.0, min(1.0, new_val))
            stressed[ticker] = new_val

        logger.debug(
            "Ring 2: stress_test scenario='%s' severity=%.2f on %d tickers",
            scenario.name,
            scenario.severity,
            len(signals),
        )
        return stressed


# ---------------------------------------------------------------------------
# Ring 3: EvolutionaryTournament
# ---------------------------------------------------------------------------


class EvolutionaryTournament:
    """
    Maintains a population of strategy parameter variants and evolves them
    via tournament selection and mutation.

    Usage::

        tournament = EvolutionaryTournament(population_size=10, mutation_rate=0.1)
        tournament.initialise_population(base_params={"threshold": 0.5, "window": 20})
        result = tournament.run_tournament(fitness_fn=my_fitness)
        champion = tournament.get_champion_params()
    """

    def __init__(
        self, population_size: int = 10, mutation_rate: float = 0.1
    ) -> None:
        self.population_size = population_size
        self.mutation_rate = mutation_rate
        self._population: Dict[str, Dict[str, Any]] = {}  # variant_id → params
        self._fitness_history: Dict[str, List[float]] = {}
        self._generation = 0

    def _new_variant_id(self) -> str:
        return f"v_{uuid.uuid4().hex[:8]}"

    def _mutate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return a mutated copy of params.

        Float values are multiplied by a factor in
        [1 - mutation_rate, 1 + mutation_rate].
        Int values are mutated as floats then rounded.
        Other types are passed through unchanged.
        """
        mutated: Dict[str, Any] = {}
        for key, val in params.items():
            if isinstance(val, bool):
                # Flip with low probability
                mutated[key] = (
                    not val
                    if random.random() < self.mutation_rate * 0.5
                    else val
                )
            elif isinstance(val, int):
                factor = random.uniform(
                    1.0 - self.mutation_rate, 1.0 + self.mutation_rate
                )
                mutated[key] = max(1, round(val * factor))
            elif isinstance(val, float):
                factor = random.uniform(
                    1.0 - self.mutation_rate, 1.0 + self.mutation_rate
                )
                mutated[key] = val * factor
            else:
                mutated[key] = val
        return mutated

    def initialise_population(self, base_params: Dict[str, Any]) -> None:
        """
        Create population_size variants by randomly mutating base_params.
        The base_params themselves are included as the first variant.
        """
        self._population.clear()
        self._fitness_history.clear()

        # First member is the base (un-mutated) variant
        base_id = self._new_variant_id()
        self._population[base_id] = dict(base_params)

        for _ in range(self.population_size - 1):
            vid = self._new_variant_id()
            self._population[vid] = self._mutate_params(base_params)

        logger.info(
            "Ring 3: initialised population of %d variants", len(self._population)
        )

    def evaluate(
        self, fitness_fn: Callable[[Dict], float]
    ) -> Dict[str, float]:
        """
        Call fitness_fn for each variant in the population.
        Returns {variant_id: fitness_score}.
        """
        scores: Dict[str, float] = {}
        for vid, params in self._population.items():
            try:
                score = fitness_fn(params)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Ring 3: fitness_fn raised for variant '%s': %s", vid, exc
                )
                score = 0.0
            scores[vid] = score
            self._fitness_history.setdefault(vid, []).append(score)

        logger.debug(
            "Ring 3: evaluated %d variants; best=%.4f worst=%.4f",
            len(scores),
            max(scores.values(), default=0.0),
            min(scores.values(), default=0.0),
        )
        return scores

    def tournament_select(
        self, fitness_scores: Dict[str, float], k: int = 3
    ) -> str:
        """
        k-tournament selection: randomly pick k variants, return the best.
        Falls back to the global best if the population is smaller than k.
        """
        candidates = list(fitness_scores.keys())
        k = min(k, len(candidates))
        selected = random.sample(candidates, k)
        return max(selected, key=lambda vid: fitness_scores[vid])

    def eliminate_losers(
        self, fitness_scores: Dict[str, float], survival_rate: float = 0.5
    ) -> None:
        """
        Keep the top survival_rate fraction of variants; eliminate the rest.
        At least one variant is always preserved.
        """
        if not fitness_scores:
            return

        n_keep = max(1, round(len(fitness_scores) * survival_rate))
        sorted_variants = sorted(
            fitness_scores.items(), key=lambda kv: kv[1], reverse=True
        )
        survivors = {vid for vid, _ in sorted_variants[:n_keep]}
        eliminated = [vid for vid in list(self._population) if vid not in survivors]

        for vid in eliminated:
            del self._population[vid]
            self._fitness_history.pop(vid, None)

        logger.debug(
            "Ring 3: eliminated %d variants, %d survivors",
            len(eliminated),
            len(self._population),
        )

    def spawn_variants(self, parent_id: str) -> List[str]:
        """
        Mutate the winner to create 2 new child variants.
        Returns the list of new variant IDs.
        """
        if parent_id not in self._population:
            logger.warning(
                "spawn_variants: parent '%s' not in population; skipping.", parent_id
            )
            return []

        parent_params = self._population[parent_id]
        new_ids: List[str] = []

        for _ in range(2):
            child_id = self._new_variant_id()
            self._population[child_id] = self._mutate_params(parent_params)
            new_ids.append(child_id)

        logger.debug(
            "Ring 3: spawned %d children from parent '%s'", len(new_ids), parent_id
        )
        return new_ids

    def run_tournament(
        self, fitness_fn: Callable[[Dict], float]
    ) -> TournamentResult:
        """
        Run a full tournament cycle:
          1. Evaluate all variants with fitness_fn.
          2. Select champion via tournament selection.
          3. Eliminate bottom 50%.
          4. Spawn 2 new variants from the champion.

        Returns TournamentResult with champion info.
        """
        if not self._population:
            raise ValueError(
                "Population is empty — call initialise_population() first."
            )

        self._generation += 1
        fitness_scores = self.evaluate(fitness_fn)

        champion_id = self.tournament_select(fitness_scores, k=min(3, len(fitness_scores)))
        champion_params = dict(self._population[champion_id])

        # Record which variants will be eliminated before removing them
        n_keep = max(1, round(len(fitness_scores) * 0.5))
        sorted_variants = sorted(
            fitness_scores.items(), key=lambda kv: kv[1], reverse=True
        )
        eliminated_ids = [vid for vid, _ in sorted_variants[n_keep:]]

        self.eliminate_losers(fitness_scores, survival_rate=0.5)
        self.spawn_variants(champion_id)

        logger.info(
            "Ring 3: generation=%d champion='%s' fitness=%.4f eliminated=%d",
            self._generation,
            champion_id,
            fitness_scores.get(champion_id, 0.0),
            len(eliminated_ids),
        )

        return TournamentResult(
            champion_id=champion_id,
            champion_params=champion_params,
            eliminated=eliminated_ids,
            fitness_scores=fitness_scores,
            generation=self._generation,
        )

    def get_champion_params(self) -> Optional[Dict[str, Any]]:
        """
        Return the params of the highest-fitness variant based on cumulative
        fitness history.  Returns None if no variants are registered.
        """
        if not self._population:
            return None

        best_id: Optional[str] = None
        best_score = float("-inf")

        for vid in self._population:
            history = self._fitness_history.get(vid, [])
            avg = sum(history) / len(history) if history else 0.0
            if avg > best_score:
                best_score = avg
                best_id = vid

        if best_id is None:
            # Fall back to any variant
            best_id = next(iter(self._population))

        return dict(self._population[best_id])


# ---------------------------------------------------------------------------
# AdversarialPressure — orchestrator
# ---------------------------------------------------------------------------


class AdversarialPressure:
    """
    Orchestrates the Three-Rings adversarial pressure architecture.

    Ring 1 (EnsembleDisagreementDetector) runs every cycle.
    Ring 2 (ScenarioGenerator) runs every RING2_INTERVAL cycles.
    Ring 3 (EvolutionaryTournament) runs every RING3_INTERVAL cycles when
        a fitness_fn is supplied.

    Failure cases from all rings are accumulated and can be retrieved for
    injection into the improvement loop.

    Usage::

        ap = AdversarialPressure(ring1_threshold=0.2, population_size=10)
        ap.ring3.initialise_population(base_params)

        report = ap.run(
            cycle=cycle_number,
            variant_outputs={"v_a": {...}, "v_b": {...}},
            current_signals={"BTCUSDT": 0.8, ...},
            strategy_params={"threshold": 0.5},
            fitness_fn=my_fitness_fn,
        )
        failures = ap.collect_failure_cases()
    """

    RING2_INTERVAL: int = 10   # cycles between scenario generation runs
    RING3_INTERVAL: int = 50   # cycles between evolutionary tournament runs

    def __init__(
        self,
        ring1_threshold: float = 0.2,
        population_size: int = 10,
    ) -> None:
        self.ring1 = EnsembleDisagreementDetector(
            disagreement_threshold=ring1_threshold
        )
        self.ring2 = ScenarioGenerator()
        self.ring3 = EvolutionaryTournament(population_size=population_size)
        self._failure_cases: List[Dict] = []

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(
        self,
        cycle: int,
        variant_outputs: Dict[str, Dict[str, float]],
        current_signals: Dict[str, float],
        strategy_params: Dict[str, Any],
        fitness_fn: Optional[Callable] = None,
    ) -> AdversarialReport:
        """
        Execute all three rings as appropriate for the given cycle.

        Ring 1: always runs.
        Ring 2: runs when cycle % RING2_INTERVAL == 0.
        Ring 3: runs when cycle % RING3_INTERVAL == 0 AND fitness_fn is provided.

        Returns an AdversarialReport containing results from each active ring
        and any new failure cases collected this cycle.
        """
        # ---- Ring 1 ------------------------------------------------
        ring1_result = self._run_ring1(
            cycle=cycle,
            variant_outputs=variant_outputs,
        )

        # ---- Ring 2 ------------------------------------------------
        ring2_scenarios: List[Scenario] = []
        if cycle % self.RING2_INTERVAL == 0:
            ring2_scenarios = self._run_ring2(
                cycle=cycle,
                current_signals=current_signals,
                strategy_params=strategy_params,
            )

        # ---- Ring 3 ------------------------------------------------
        ring3_result: Optional[TournamentResult] = None
        if cycle % self.RING3_INTERVAL == 0 and fitness_fn is not None:
            ring3_result = self._run_ring3(
                cycle=cycle,
                fitness_fn=fitness_fn,
            )

        # Collect failure cases generated this cycle
        cycle_failures = self._collect_cycle_failures(
            cycle=cycle,
            ring1_result=ring1_result,
            ring2_scenarios=ring2_scenarios,
            current_signals=current_signals,
            ring3_result=ring3_result,
        )
        self._failure_cases.extend(cycle_failures)

        return AdversarialReport(
            cycle=cycle,
            ring1_result=ring1_result,
            ring2_scenarios=ring2_scenarios,
            ring3_result=ring3_result,
            failure_cases=cycle_failures,
        )

    # ------------------------------------------------------------------
    # Internal ring runners
    # ------------------------------------------------------------------

    def _run_ring1(
        self,
        cycle: int,
        variant_outputs: Dict[str, Dict[str, float]],
    ) -> DisagreementResult:
        """Submit all variant outputs to Ring 1 and detect disagreement."""
        self.ring1.clear()
        for variant_id, output in variant_outputs.items():
            if variant_id not in self.ring1._variants:
                self.ring1.register_variant(variant_id)
            self.ring1.submit_output(variant_id, output)

        result = self.ring1.detect()
        logger.debug(
            "Ring 1 [cycle=%d]: flagged=%s max_disagreement=%.4f",
            cycle,
            result.flagged,
            result.max_disagreement,
        )
        return result

    def _run_ring2(
        self,
        cycle: int,
        current_signals: Dict[str, float],
        strategy_params: Dict[str, Any],
    ) -> List[Scenario]:
        """Generate adversarial scenarios and stress-test current signals."""
        logger.info("Ring 2 [cycle=%d]: generating adversarial scenarios", cycle)
        scenarios = self.ring2.generate_adversarial(
            current_signals=current_signals,
            strategy_params=strategy_params,
            n_scenarios=5,
        )
        logger.info(
            "Ring 2 [cycle=%d]: generated %d scenarios (top severity=%.2f)",
            cycle,
            len(scenarios),
            scenarios[0].severity if scenarios else 0.0,
        )
        return scenarios

    def _run_ring3(
        self,
        cycle: int,
        fitness_fn: Callable,
    ) -> Optional[TournamentResult]:
        """Run evolutionary tournament if population is initialised."""
        if not self.ring3._population:
            logger.warning(
                "Ring 3 [cycle=%d]: population not initialised, skipping tournament.",
                cycle,
            )
            return None

        logger.info(
            "Ring 3 [cycle=%d]: running tournament on %d variants",
            cycle,
            len(self.ring3._population),
        )
        result = self.ring3.run_tournament(fitness_fn)
        logger.info(
            "Ring 3 [cycle=%d]: champion='%s' generation=%d",
            cycle,
            result.champion_id,
            result.generation,
        )
        return result

    # ------------------------------------------------------------------
    # Failure case collection
    # ------------------------------------------------------------------

    def _collect_cycle_failures(
        self,
        cycle: int,
        ring1_result: Optional[DisagreementResult],
        ring2_scenarios: List[Scenario],
        current_signals: Dict[str, float],
        ring3_result: Optional[TournamentResult],
    ) -> List[Dict]:
        """
        Derive failure cases from this cycle's ring outputs.

        Ring 1 failure: ensemble disagreement flagged.
        Ring 2 failure: each scenario with severity > 0.8 that produces a
            stressed signal mean below -0.3.
        Ring 3 failure: champion fitness below a minimum threshold.
        """
        failures: List[Dict] = []

        # Ring 1 failure cases
        if ring1_result is not None and ring1_result.flagged:
            failures.append(
                {
                    "source": "ring1",
                    "description": (
                        f"Ensemble disagreement detected: max_distance="
                        f"{ring1_result.max_disagreement:.4f}, "
                        f"disagreeing_variants={ring1_result.disagreeing_variants}"
                    ),
                    "context": {
                        "max_disagreement": ring1_result.max_disagreement,
                        "disagreeing_variants": ring1_result.disagreeing_variants,
                        "outputs": {
                            vid: dict(out)
                            for vid, out in ring1_result.outputs.items()
                        },
                    },
                    "cycle": cycle,
                }
            )

        # Ring 2 failure cases — high severity scenarios that devastate signals
        for scenario in ring2_scenarios:
            if scenario.severity < 0.8 or not current_signals:
                continue
            stressed = self.ring2.stress_test(current_signals, scenario)
            stressed_mean = (
                sum(stressed.values()) / len(stressed) if stressed else 0.0
            )
            if stressed_mean < -0.3:
                failures.append(
                    {
                        "source": "ring2",
                        "description": (
                            f"Scenario '{scenario.name}' (severity={scenario.severity:.2f}) "
                            f"devastates strategy signals (stressed_mean={stressed_mean:.4f})"
                        ),
                        "context": {
                            "scenario_id": scenario.scenario_id,
                            "scenario_name": scenario.name,
                            "severity": scenario.severity,
                            "stressed_signals": stressed,
                            "original_signals": dict(current_signals),
                        },
                        "cycle": cycle,
                    }
                )

        # Ring 3 failure cases — poor champion fitness
        if ring3_result is not None:
            best_fitness = ring3_result.fitness_scores.get(
                ring3_result.champion_id, 0.0
            )
            if best_fitness < 0.1:
                failures.append(
                    {
                        "source": "ring3",
                        "description": (
                            f"Evolutionary tournament champion fitness too low: "
                            f"{best_fitness:.4f} (generation={ring3_result.generation})"
                        ),
                        "context": {
                            "champion_id": ring3_result.champion_id,
                            "champion_params": ring3_result.champion_params,
                            "champion_fitness": best_fitness,
                            "generation": ring3_result.generation,
                            "all_scores": ring3_result.fitness_scores,
                        },
                        "cycle": cycle,
                    }
                )

        if failures:
            logger.info(
                "AdversarialPressure [cycle=%d]: collected %d failure cases",
                cycle,
                len(failures),
            )

        return failures

    # ------------------------------------------------------------------
    # Failure case management
    # ------------------------------------------------------------------

    def collect_failure_cases(self) -> List[Dict]:
        """
        Return all accumulated failure cases for consumption by the
        improvement loop.  Does NOT clear the buffer; call
        clear_failure_cases() explicitly when done.
        """
        return list(self._failure_cases)

    def clear_failure_cases(self) -> None:
        """Clear the accumulated failure cases buffer."""
        self._failure_cases.clear()
        logger.debug("AdversarialPressure: failure cases buffer cleared")
