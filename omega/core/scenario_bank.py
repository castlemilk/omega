"""
omega.core.scenario_bank
~~~~~~~~~~~~~~~~~~~~~~~~
Ring 2 infrastructure: historical scenario storage, synthetic scenario
generation, scenario-based resilience testing, and the SimulationGate
go/no-go decision before a strategy goes live.

Classes
-------
HistoricalScenarioBank
    Stores named, dated market scenarios (flash crash, squeeze, regime shift,
    etc.) and retrieves them by tag or severity range.

SyntheticScenarioGenerator
    Creates stress-test scenarios by perturbing real price/signal data with
    controlled shocks, vol multipliers, and correlation breakdowns.

ScenarioRunner
    Runs a callable strategy against a list of scenarios and measures
    resilience via a configurable scoring function.

SimulationGate
    Aggregates ScenarioRunner results and returns a go / no-go decision plus
    an explanation before a strategy is promoted to live trading.
"""

from __future__ import annotations

import logging
import random
import typing
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from omega.core.adversarial import Scenario

logger = logging.getLogger("omega.core.scenario_bank")


# ---------------------------------------------------------------------------
# Supplementary dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ScenarioRecord:
    """A scenario stored in the bank, with metadata."""

    scenario: Scenario
    tags: list[str]
    source: str  # "historical" | "synthetic" | "user"
    created_at: datetime = field(default_factory=datetime.utcnow)
    notes: str = ""


@dataclass
class RunResult:
    """Result of running a single scenario through a strategy."""

    scenario_id: str
    scenario_name: str
    severity: float
    raw_output: Any  # whatever the strategy callable returns
    resilience_score: float  # 0 (catastrophic) → 1 (perfect)
    passed: bool  # True if resilience_score >= gate threshold
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationReport:
    """Aggregated report from ScenarioRunner covering all scenarios."""

    strategy_id: str
    run_results: list[RunResult]
    overall_resilience: float  # mean resilience across all scenarios
    worst_scenario: str  # scenario_id of lowest resilience run
    worst_resilience: float
    gate_passed: bool
    gate_reason: str


# ---------------------------------------------------------------------------
# HistoricalScenarioBank
# ---------------------------------------------------------------------------


class HistoricalScenarioBank:
    """
    Stores known market scenarios and retrieves them by tag or severity.

    Pre-loaded with canonical scenarios at construction.

    Usage::

        bank = HistoricalScenarioBank()
        crashes = bank.get_by_tag("crash")
        severe  = bank.get_by_severity(min_severity=0.8)
        bank.add(record)
    """

    def __init__(self) -> None:
        self._records: dict[str, ScenarioRecord] = {}
        self._load_canonical()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, record: ScenarioRecord) -> None:
        """Add a scenario record, keyed by scenario_id."""
        sid = record.scenario.scenario_id
        self._records[sid] = record
        logger.debug("ScenarioBank: added '%s' (tags=%s)", sid, record.tags)

    def get(self, scenario_id: str) -> ScenarioRecord | None:
        return self._records.get(scenario_id)

    def get_by_tag(self, tag: str) -> list[ScenarioRecord]:
        return [r for r in self._records.values() if tag in r.tags]

    def get_by_severity(
        self, min_severity: float = 0.0, max_severity: float = 1.0
    ) -> list[ScenarioRecord]:
        return [
            r
            for r in self._records.values()
            if min_severity <= r.scenario.severity <= max_severity
        ]

    def all_scenarios(self) -> list[Scenario]:
        return [r.scenario for r in self._records.values()]

    def all_records(self) -> list[ScenarioRecord]:
        return list(self._records.values())

    def __len__(self) -> int:
        return len(self._records)

    # ------------------------------------------------------------------
    # Canonical scenario loader
    # ------------------------------------------------------------------

    def _load_canonical(self) -> None:
        """Pre-populate the bank with well-known historical scenarios."""
        canonical: list[tuple[Scenario, list[str], str]] = [
            (
                Scenario(
                    scenario_id="hist_2010_flash_crash",
                    name="2010 Flash Crash",
                    description=(
                        "6 May 2010 — DJIA lost ~9% intraday then recovered most "
                        "losses within minutes.  Triggered by large E-mini futures sell."
                    ),
                    market_shocks={
                        "BTCUSDT": -0.09,
                        "ETHUSDT": -0.12,
                        "SOLUSDT": -0.15,
                        "BNBUSDT": -0.11,
                    },
                    vol_multiplier=4.5,
                    correlation_breakdown=False,
                    severity=0.80,
                ),
                ["crash", "flash", "historical", "intraday"],
                "historical",
            ),
            (
                Scenario(
                    scenario_id="hist_2020_covid_crash",
                    name="COVID Crash 2020",
                    description=(
                        "March 2020: global markets dropped 30-40% as pandemic declared. "
                        "Correlations jumped to ~1.0 across all asset classes."
                    ),
                    market_shocks={
                        "BTCUSDT": -0.50,
                        "ETHUSDT": -0.55,
                        "SOLUSDT": -0.60,
                        "BNBUSDT": -0.48,
                    },
                    vol_multiplier=6.0,
                    correlation_breakdown=False,
                    severity=0.95,
                ),
                ["crash", "pandemic", "historical", "2020", "high-severity"],
                "historical",
            ),
            (
                Scenario(
                    scenario_id="hist_2022_luna_collapse",
                    name="LUNA/UST Collapse 2022",
                    description=(
                        "May 2022: LUNA lost >99% in 72 hours; UST de-pegged. "
                        "Contagion hit all crypto assets; BTC dropped 30%."
                    ),
                    market_shocks={
                        "BTCUSDT": -0.30,
                        "ETHUSDT": -0.35,
                        "SOLUSDT": -0.40,
                        "BNBUSDT": -0.28,
                        "ADAUSDT": -0.38,
                    },
                    vol_multiplier=5.0,
                    correlation_breakdown=False,
                    severity=0.90,
                ),
                ["crash", "defi", "contagion", "historical", "2022"],
                "historical",
            ),
            (
                Scenario(
                    scenario_id="hist_2021_may_squeeze",
                    name="May 2021 Short Squeeze",
                    description=(
                        "May 2021: BTC dropped 50% from ATH amid China mining ban "
                        "fears and Elon Musk tweets; massive liquidations cascade."
                    ),
                    market_shocks={
                        "BTCUSDT": -0.50,
                        "ETHUSDT": -0.45,
                        "SOLUSDT": -0.42,
                        "BNBUSDT": -0.48,
                    },
                    vol_multiplier=4.0,
                    correlation_breakdown=False,
                    severity=0.88,
                ),
                ["squeeze", "liquidation", "historical", "2021"],
                "historical",
            ),
            (
                Scenario(
                    scenario_id="hist_2018_crypto_winter",
                    name="Crypto Winter 2018",
                    description=(
                        "2018 bear market: BTC fell from ~20k to ~3k (-85%), "
                        "most altcoins lost 90%+. Prolonged regime shift."
                    ),
                    market_shocks={
                        "BTCUSDT": -0.85,
                        "ETHUSDT": -0.94,
                        "SOLUSDT": -0.90,
                        "BNBUSDT": -0.88,
                        "ADAUSDT": -0.95,
                    },
                    vol_multiplier=2.5,
                    correlation_breakdown=False,
                    severity=0.97,
                ),
                ["bear", "regime-shift", "prolonged", "historical", "2018"],
                "historical",
            ),
            (
                Scenario(
                    scenario_id="hist_2021_nft_mania",
                    name="NFT/Alt Mania 2021 Q1",
                    description=(
                        "Early 2021: BTC dominance fell as capital rotated to alts; "
                        "ETH +400%, SOL +3000%.  Tests momentum-chasing risk."
                    ),
                    market_shocks={
                        "BTCUSDT": 0.80,
                        "ETHUSDT": 4.00,
                        "SOLUSDT": 30.00,
                        "BNBUSDT": 10.00,
                        "ADAUSDT": 5.00,
                    },
                    vol_multiplier=3.5,
                    correlation_breakdown=True,
                    severity=0.70,
                ),
                ["bull", "mania", "rotation", "historical", "2021"],
                "historical",
            ),
            (
                Scenario(
                    scenario_id="hist_2022_ftx_collapse",
                    name="FTX Collapse 2022",
                    description=(
                        "November 2022: FTX declared bankruptcy; BTC -25% in 48 h. "
                        "Trust collapse in centralised exchanges."
                    ),
                    market_shocks={
                        "BTCUSDT": -0.25,
                        "ETHUSDT": -0.28,
                        "SOLUSDT": -0.60,
                        "BNBUSDT": -0.20,
                    },
                    vol_multiplier=4.5,
                    correlation_breakdown=False,
                    severity=0.87,
                ),
                ["crash", "exchange", "contagion", "historical", "2022"],
                "historical",
            ),
        ]

        for scenario, tags, source in canonical:
            record = ScenarioRecord(
                scenario=scenario,
                tags=tags,
                source=source,
                notes="Pre-loaded canonical historical scenario.",
            )
            self._records[scenario.scenario_id] = record

        logger.info(
            "HistoricalScenarioBank: loaded %d canonical scenarios",
            len(self._records),
        )


# ---------------------------------------------------------------------------
# SyntheticScenarioGenerator
# ---------------------------------------------------------------------------


class SyntheticScenarioGenerator:
    """
    Creates stress-test scenarios by perturbing real market data.

    Perturbation modes
    ------------------
    amplitude_scaling   — multiply all signals by a factor (bull/bear shocks)
    tail_shock          — apply a fat-tail shock to the highest-signal asset
    correlation_nuke    — break all correlations by injecting independent noise
    regime_flip         — invert all signal directions (regime change test)
    vol_explosion       — keep shocks at zero but multiply vol dramatically

    Usage::

        gen = SyntheticScenarioGenerator(seed=42)
        scenarios = gen.generate(
            base_signals={"BTCUSDT": 0.8, "ETHUSDT": 0.6},
            n_scenarios=10,
            modes=["amplitude_scaling", "tail_shock", "regime_flip"],
        )
    """

    _ALL_MODES: typing.ClassVar[list[str]] = [
        "amplitude_scaling",
        "tail_shock",
        "correlation_nuke",
        "regime_flip",
        "vol_explosion",
    ]

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    def generate(
        self,
        base_signals: dict[str, float],
        n_scenarios: int = 10,
        modes: list[str] | None = None,
    ) -> list[Scenario]:
        """
        Generate n_scenarios synthetic scenarios from base_signals.

        Each scenario is created by randomly choosing one perturbation mode
        and applying it.  Returns scenarios sorted by severity descending.
        """
        if not base_signals:
            logger.warning("SyntheticScenarioGenerator: empty base_signals")
            return []

        selected_modes = modes if modes else self._ALL_MODES
        scenarios: list[Scenario] = []

        for _ in range(n_scenarios):
            mode = self._rng.choice(selected_modes)
            scenario = self._apply_mode(mode, base_signals)
            scenarios.append(scenario)

        scenarios.sort(key=lambda s: s.severity, reverse=True)
        logger.debug("SyntheticScenarioGenerator: generated %d scenarios", len(scenarios))
        return scenarios

    def perturb(
        self,
        base_signals: dict[str, float],
        mode: str,
        intensity: float = 1.0,
    ) -> Scenario:
        """Generate exactly one scenario with a specific mode and intensity."""
        return self._apply_mode(mode, base_signals, intensity=intensity)

    # ------------------------------------------------------------------
    # Mode implementations
    # ------------------------------------------------------------------

    def _apply_mode(
        self,
        mode: str,
        base: dict[str, float],
        intensity: float | None = None,
    ) -> Scenario:
        sid = f"synth_{mode}_{uuid.uuid4().hex[:6]}"
        rng = self._rng

        if mode == "amplitude_scaling":
            factor = rng.uniform(-0.40, -0.10) if intensity is None else -intensity * 0.30
            shocks = {t: factor for t in base}
            severity = min(1.0, abs(factor) + 0.30)
            return Scenario(
                scenario_id=sid,
                name=f"Amplitude Scaling ({factor:+.0%})",
                description=f"All signals scaled by {factor:+.1%}.",
                market_shocks=shocks,
                vol_multiplier=1.5 + rng.uniform(0, 1.0),
                correlation_breakdown=False,
                severity=severity,
            )

        elif mode == "tail_shock":
            # Largest positive signal gets a big negative shock
            sorted_tickers = sorted(base.items(), key=lambda kv: kv[1], reverse=True)
            top_ticker = sorted_tickers[0][0] if sorted_tickers else next(iter(base.keys()))
            shock_mag = -(0.35 + rng.uniform(0, 0.30)) if intensity is None else -intensity
            shocks = {t: (shock_mag if t == top_ticker else shock_mag * 0.3) for t in base}
            severity = min(1.0, abs(shock_mag) + 0.25)
            return Scenario(
                scenario_id=sid,
                name=f"Tail Shock on {top_ticker}",
                description=f"Fat-tail shock of {shock_mag:.0%} on {top_ticker}.",
                market_shocks=shocks,
                vol_multiplier=3.0 + rng.uniform(0, 2.0),
                correlation_breakdown=False,
                severity=severity,
            )

        elif mode == "correlation_nuke":
            shocks = {t: rng.uniform(-0.10, 0.10) for t in base}
            return Scenario(
                scenario_id=sid,
                name="Correlation Nuke",
                description="All inter-asset correlations collapse; independent random shocks.",
                market_shocks=shocks,
                vol_multiplier=2.0 + rng.uniform(0, 1.0),
                correlation_breakdown=True,
                severity=0.65 + rng.uniform(0, 0.15),
            )

        elif mode == "regime_flip":
            shocks = {t: -sig * 0.5 for t, sig in base.items()}
            return Scenario(
                scenario_id=sid,
                name="Regime Flip",
                description="All signal directions invert — regime change stress test.",
                market_shocks=shocks,
                vol_multiplier=2.5,
                correlation_breakdown=False,
                severity=0.75,
            )

        elif mode == "vol_explosion":
            multiplier = 5.0 + rng.uniform(0, 5.0) if intensity is None else intensity * 8.0
            shocks = {t: 0.0 for t in base}
            return Scenario(
                scenario_id=sid,
                name=f"Vol Explosion (x{multiplier:.1f})",
                description=f"Volatility explodes {multiplier:.1f}x; no directional shock.",
                market_shocks=shocks,
                vol_multiplier=multiplier,
                correlation_breakdown=True,
                severity=min(1.0, 0.50 + multiplier * 0.04),
            )

        else:
            logger.warning("Unknown perturbation mode '%s'; returning zero-shock", mode)
            return Scenario(
                scenario_id=sid,
                name=f"Unknown Mode: {mode}",
                description="No-op scenario due to unknown mode.",
                market_shocks={t: 0.0 for t in base},
                vol_multiplier=1.0,
                correlation_breakdown=False,
                severity=0.0,
            )


# ---------------------------------------------------------------------------
# ScenarioRunner
# ---------------------------------------------------------------------------


class ScenarioRunner:
    """
    Runs a strategy callable against a list of scenarios and scores resilience.

    The strategy callable signature::

        strategy(signals: dict[str, float], scenario: Scenario) -> dict[str, float]

    It receives the *stressed* signals and the scenario metadata, and returns
    an output signal dict.  A resilience_scorer callable then maps that output
    to a float in [0, 1].

    Default resilience_scorer: mean absolute output signal (higher = better).
    A strategy that returns all zeros under stress scores 0.

    Usage::

        def my_strategy(signals, scenario):
            return {t: max(0.0, s) for t, s in signals.items()}

        runner = ScenarioRunner(strategy=my_strategy)
        results = runner.run(scenarios, base_signals={"BTC": 0.8, "ETH": 0.6})
    """

    def __init__(
        self,
        strategy: Callable[[dict[str, float], Scenario], dict[str, float]],
        resilience_scorer: Callable[[dict[str, float], Scenario], float] | None = None,
        pass_threshold: float = 0.30,
        seed: int | None = None,
    ) -> None:
        self.strategy = strategy
        self.resilience_scorer = resilience_scorer or self._default_scorer
        self.pass_threshold = pass_threshold
        self._rng = random.Random(seed)
        self._stress_gen = SyntheticScenarioGenerator(seed=seed)

    @staticmethod
    def _default_scorer(output: dict[str, float], scenario: Scenario) -> float:
        """
        Default: mean absolute value of output signals.

        A strategy that preserves signal magnitude under stress scores well.
        A strategy that collapses to zero scores 0.
        """
        if not output:
            return 0.0
        mean_abs = sum(abs(v) for v in output.values()) / len(output)
        return min(1.0, mean_abs)

    def _apply_stress(
        self,
        base_signals: dict[str, float],
        scenario: Scenario,
    ) -> dict[str, float]:
        """Apply scenario shocks to base signals to produce stressed signals."""
        stressed: dict[str, float] = {}
        for ticker, sig in base_signals.items():
            shock = scenario.market_shocks.get(ticker, 0.0)
            val = sig * (1.0 + shock)
            if scenario.correlation_breakdown:
                val += self._rng.uniform(-0.10, 0.10)
            val *= min(1.0, 1.0 / max(1.0, scenario.vol_multiplier * 0.2))
            stressed[ticker] = max(-1.0, min(1.0, val))
        return stressed

    def run(
        self,
        scenarios: list[Scenario],
        base_signals: dict[str, float],
    ) -> list[RunResult]:
        """
        Run the strategy against each scenario and return RunResult per scenario.
        """
        results: list[RunResult] = []

        for scenario in scenarios:
            stressed = self._apply_stress(base_signals, scenario)

            try:
                output = self.strategy(stressed, scenario)
            except Exception as exc:
                logger.warning(
                    "ScenarioRunner: strategy raised on scenario '%s': %s",
                    scenario.scenario_id,
                    exc,
                )
                output = {}

            resilience = self.resilience_scorer(output, scenario)
            passed = resilience >= self.pass_threshold

            results.append(
                RunResult(
                    scenario_id=scenario.scenario_id,
                    scenario_name=scenario.name,
                    severity=scenario.severity,
                    raw_output=output,
                    resilience_score=resilience,
                    passed=passed,
                    details={
                        "stressed_signals": stressed,
                        "base_signals": dict(base_signals),
                        "pass_threshold": self.pass_threshold,
                    },
                )
            )

            logger.debug(
                "ScenarioRunner: scenario='%s' severity=%.2f resilience=%.4f passed=%s",
                scenario.name,
                scenario.severity,
                resilience,
                passed,
            )

        return results


# ---------------------------------------------------------------------------
# SimulationGate
# ---------------------------------------------------------------------------


class SimulationGate:
    """
    Go/no-go gate before a strategy is promoted to live trading.

    Aggregates ScenarioRunner results and decides whether the strategy has
    demonstrated sufficient resilience across all scenarios.

    Gate criteria (all must pass)
    ------------------------------
    1. overall_resilience >= min_overall_resilience
    2. No single scenario resilience < min_worst_case
    3. pass_rate (fraction of scenarios passed) >= min_pass_rate
    4. High-severity scenarios (severity >= 0.8) must pass at rate
       >= min_severe_pass_rate

    Usage::

        gate = SimulationGate(
            min_overall_resilience=0.40,
            min_worst_case=0.15,
            min_pass_rate=0.70,
            min_severe_pass_rate=0.50,
        )
        runner = ScenarioRunner(strategy=my_strategy)
        results = runner.run(scenarios, base_signals)
        report = gate.evaluate(strategy_id="my_strategy_v1", run_results=results)
        if report.gate_passed:
            promote_to_live()
    """

    def __init__(
        self,
        min_overall_resilience: float = 0.40,
        min_worst_case: float = 0.15,
        min_pass_rate: float = 0.70,
        min_severe_pass_rate: float = 0.50,
        severe_threshold: float = 0.80,
    ) -> None:
        self.min_overall_resilience = min_overall_resilience
        self.min_worst_case = min_worst_case
        self.min_pass_rate = min_pass_rate
        self.min_severe_pass_rate = min_severe_pass_rate
        self.severe_threshold = severe_threshold

    def evaluate(
        self,
        strategy_id: str,
        run_results: list[RunResult],
    ) -> SimulationReport:
        """
        Evaluate strategy resilience across all run results.

        Returns a SimulationReport with gate_passed=True iff all criteria met.
        """
        if not run_results:
            return SimulationReport(
                strategy_id=strategy_id,
                run_results=[],
                overall_resilience=0.0,
                worst_scenario="none",
                worst_resilience=0.0,
                gate_passed=False,
                gate_reason="No scenario results to evaluate.",
            )

        resilience_scores = [r.resilience_score for r in run_results]
        overall = sum(resilience_scores) / len(resilience_scores)

        worst = min(run_results, key=lambda r: r.resilience_score)
        worst_resilience = worst.resilience_score

        pass_rate = sum(1 for r in run_results if r.passed) / len(run_results)

        severe_results = [r for r in run_results if r.severity >= self.severe_threshold]
        severe_pass_rate = (
            sum(1 for r in severe_results if r.passed) / len(severe_results)
            if severe_results
            else 1.0
        )

        # Evaluate gate criteria
        failures: list[str] = []

        if overall < self.min_overall_resilience:
            failures.append(f"overall_resilience={overall:.3f} < {self.min_overall_resilience}")
        if worst_resilience < self.min_worst_case:
            failures.append(
                f"worst_case_resilience={worst_resilience:.3f} < {self.min_worst_case}"
                f" (scenario='{worst.scenario_name}')"
            )
        if pass_rate < self.min_pass_rate:
            failures.append(f"pass_rate={pass_rate:.2%} < {self.min_pass_rate:.2%}")
        if severe_results and severe_pass_rate < self.min_severe_pass_rate:
            failures.append(
                f"severe_pass_rate={severe_pass_rate:.2%} < {self.min_severe_pass_rate:.2%}"
                f" ({len(severe_results)} severe scenarios)"
            )

        gate_passed = len(failures) == 0
        gate_reason = (
            "All gate criteria passed." if gate_passed else "Gate failed: " + "; ".join(failures)
        )

        log_fn = logger.info if gate_passed else logger.warning
        log_fn(
            "SimulationGate [%s]: passed=%s overall=%.3f worst=%.3f "
            "pass_rate=%.2f severe_pass_rate=%.2f",
            strategy_id,
            gate_passed,
            overall,
            worst_resilience,
            pass_rate,
            severe_pass_rate,
        )

        return SimulationReport(
            strategy_id=strategy_id,
            run_results=run_results,
            overall_resilience=overall,
            worst_scenario=worst.scenario_id,
            worst_resilience=worst_resilience,
            gate_passed=gate_passed,
            gate_reason=gate_reason,
        )

    def run_and_evaluate(
        self,
        strategy_id: str,
        strategy: Callable[[dict[str, float], Scenario], dict[str, float]],
        scenarios: list[Scenario],
        base_signals: dict[str, float],
        pass_threshold: float = 0.30,
        resilience_scorer: Callable | None = None,
    ) -> SimulationReport:
        """
        Convenience method: create a ScenarioRunner, run it, then evaluate.
        """
        runner = ScenarioRunner(
            strategy=strategy,
            pass_threshold=pass_threshold,
            resilience_scorer=resilience_scorer,
        )
        results = runner.run(scenarios, base_signals)
        return self.evaluate(strategy_id=strategy_id, run_results=results)
