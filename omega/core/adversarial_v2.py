"""
omega.core.adversarial_v2
~~~~~~~~~~~~~~~~~~~~~~~~~
Enhanced adversarial layer that builds on Ring 1 (ensemble disagreement) and
activates Ring 2 (scenario bank) via four new components:

AdaptiveThresholdManager
    Auto-tunes the Ring 1 disagreement threshold based on rolling false positive
    rate.  Raises the threshold when too many benign flags are occurring; lowers
    it when real disagreements are being missed.

DisagreementAttributor
    Given a DisagreementResult, identifies WHICH variant(s) are outliers using
    a z-score approach on pairwise distances.  Returns outlier variant IDs and
    confidence scores.

FalsePositiveTracker
    Tracks whether flagged disagreements turned out to be genuine (i.e., the
    strategy actually under-performed) or false alarms.  Maintains a rolling
    false positive rate used by the AdaptiveThresholdManager.

AdversarialPressureV2
    Extends AdversarialPressure with:
      - Adaptive threshold tuning (via AdaptiveThresholdManager).
      - Outlier attribution per flagged cycle (via DisagreementAttributor).
      - False positive tracking (via FalsePositiveTracker).
      - Ring 2 activation logic tied to scenario bank results.
"""

from __future__ import annotations

import logging
import math
import statistics
from collections import deque
from dataclasses import dataclass
from typing import Any

from omega.core.adversarial import (
    AdversarialPressure,
    AdversarialReport,
    DisagreementResult,
)
from omega.core.scenario_bank import (
    HistoricalScenarioBank,
    SimulationGate,
    SimulationReport,
    SyntheticScenarioGenerator,
)

logger = logging.getLogger("omega.core.adversarial_v2")


# ---------------------------------------------------------------------------
# AdaptiveThresholdManager
# ---------------------------------------------------------------------------


@dataclass
class ThresholdAdjustment:
    """Record of a single threshold adjustment event."""

    cycle: int
    old_threshold: float
    new_threshold: float
    reason: str
    false_positive_rate: float


class AdaptiveThresholdManager:
    """
    Auto-tunes the Ring 1 disagreement threshold based on observed false
    positive rate over a rolling window.

    Strategy
    --------
    - If FP rate > fp_rate_high_watermark → threshold is too sensitive →
      raise it by step_size (up to max_threshold).
    - If FP rate < fp_rate_low_watermark AND flag_rate < min_flag_rate →
      threshold may be too lenient → lower it by step_size (down to min_threshold).
    - Adjustments happen at most once per adjustment_interval cycles.

    Usage::

        mgr = AdaptiveThresholdManager(initial_threshold=0.2)
        mgr.update(cycle=5, false_positive_rate=0.30, flag_rate=0.40)
        threshold = mgr.current_threshold
    """

    def __init__(
        self,
        initial_threshold: float = 0.20,
        min_threshold: float = 0.05,
        max_threshold: float = 0.60,
        step_size: float = 0.02,
        fp_rate_high_watermark: float = 0.30,  # FP rate above this → raise threshold
        fp_rate_low_watermark: float = 0.05,  # FP rate below this → consider lowering
        min_flag_rate: float = 0.05,  # min desired flag rate before lowering
        adjustment_interval: int = 10,  # min cycles between adjustments
        window_size: int = 50,  # rolling window for FP rate
    ) -> None:
        self.current_threshold = initial_threshold
        self.min_threshold = min_threshold
        self.max_threshold = max_threshold
        self.step_size = step_size
        self.fp_rate_high_watermark = fp_rate_high_watermark
        self.fp_rate_low_watermark = fp_rate_low_watermark
        self.min_flag_rate = min_flag_rate
        self.adjustment_interval = adjustment_interval
        self.window_size = window_size

        self._last_adjustment_cycle: int = -adjustment_interval
        self._adjustment_history: list[ThresholdAdjustment] = []
        self._fp_window: deque[float] = deque(maxlen=window_size)
        self._flag_window: deque[bool] = deque(maxlen=window_size)

    def record_observation(
        self,
        flagged: bool,
        was_false_positive: bool | None = None,
    ) -> None:
        """
        Record one cycle's flag observation.

        was_false_positive: True if the flag was a false alarm (determined
        retrospectively via FalsePositiveTracker); None if not yet known.
        """
        self._flag_window.append(flagged)
        if was_false_positive is not None:
            self._fp_window.append(1.0 if was_false_positive else 0.0)

    def update(
        self,
        cycle: int,
        false_positive_rate: float,
        flag_rate: float,
    ) -> ThresholdAdjustment | None:
        """
        Evaluate current performance and adjust threshold if needed.

        Returns a ThresholdAdjustment record if an adjustment was made, else None.
        """
        if cycle - self._last_adjustment_cycle < self.adjustment_interval:
            return None

        old = self.current_threshold
        new = old
        reason = ""

        if false_positive_rate > self.fp_rate_high_watermark:
            new = min(self.max_threshold, old + self.step_size)
            reason = (
                f"FP rate {false_positive_rate:.2%} > high watermark "
                f"{self.fp_rate_high_watermark:.2%} — raising threshold"
            )
        elif false_positive_rate < self.fp_rate_low_watermark and flag_rate < self.min_flag_rate:
            new = max(self.min_threshold, old - self.step_size)
            reason = (
                f"FP rate {false_positive_rate:.2%} < low watermark and "
                f"flag_rate {flag_rate:.2%} < min {self.min_flag_rate:.2%} — "
                "lowering threshold"
            )

        if new == old:
            return None

        self.current_threshold = new
        self._last_adjustment_cycle = cycle
        adj = ThresholdAdjustment(
            cycle=cycle,
            old_threshold=old,
            new_threshold=new,
            reason=reason,
            false_positive_rate=false_positive_rate,
        )
        self._adjustment_history.append(adj)
        logger.info(
            "AdaptiveThreshold [cycle=%d]: %.4f → %.4f (%s)",
            cycle,
            old,
            new,
            reason,
        )
        return adj

    def adjustment_history(self) -> list[ThresholdAdjustment]:
        return list(self._adjustment_history)

    def rolling_flag_rate(self) -> float:
        if not self._flag_window:
            return 0.0
        return sum(self._flag_window) / len(self._flag_window)


# ---------------------------------------------------------------------------
# DisagreementAttributor
# ---------------------------------------------------------------------------


@dataclass
class AttributionResult:
    """Which variant is the outlier and how confident we are."""

    outlier_variants: list[str]  # most likely outlier variant IDs
    outlier_scores: dict[str, float]  # variant_id → outlier score (higher = more outlier)
    method: str
    confidence: float  # 0 → 1


class DisagreementAttributor:
    """
    Given a DisagreementResult, identifies WHICH variant(s) are outliers.

    Method: z-score on each variant's mean pairwise distance to all others.
    A variant with a high mean pairwise distance is likely the outlier.

    Usage::

        attributor = DisagreementAttributor(z_score_threshold=1.5)
        result = attributor.attribute(disagreement_result)
        print(result.outlier_variants)
    """

    def __init__(self, z_score_threshold: float = 1.5) -> None:
        self.z_score_threshold = z_score_threshold

    @staticmethod
    def _euclidean(a: dict[str, float], b: dict[str, float]) -> float:
        shared = set(a) & set(b)
        if not shared:
            return 0.0
        return math.sqrt(sum((a[k] - b[k]) ** 2 for k in shared)) / max(1, len(shared))

    def attribute(self, result: DisagreementResult) -> AttributionResult:
        """
        Attribute disagreement to specific variant(s) using z-scores on
        mean pairwise distance.
        """
        outputs = result.outputs
        variant_ids = list(outputs.keys())

        if len(variant_ids) < 2:
            return AttributionResult(
                outlier_variants=[],
                outlier_scores={},
                method="z_score_pairwise",
                confidence=0.0,
            )

        # Compute mean pairwise distance for each variant
        mean_distances: dict[str, float] = {}
        for vid in variant_ids:
            dists = [
                self._euclidean(outputs[vid], outputs[other])
                for other in variant_ids
                if other != vid
            ]
            mean_distances[vid] = sum(dists) / len(dists) if dists else 0.0

        dist_values = list(mean_distances.values())

        if len(dist_values) < 2:
            # Can't compute z-scores with < 2 values
            outlier = max(mean_distances, key=mean_distances.get)  # type: ignore[arg-type]
            return AttributionResult(
                outlier_variants=[outlier],
                outlier_scores=mean_distances,
                method="z_score_pairwise",
                confidence=0.5,
            )

        mean_d = statistics.mean(dist_values)
        stdev_d = statistics.stdev(dist_values) if len(dist_values) > 1 else 0.0

        z_scores: dict[str, float] = {}
        for vid, d in mean_distances.items():
            z_scores[vid] = (d - mean_d) / stdev_d if stdev_d > 0 else 0.0

        outliers = [vid for vid, z in z_scores.items() if z > self.z_score_threshold]

        # Confidence: ratio of max z-score to threshold
        max_z = max(z_scores.values(), default=0.0)
        confidence = min(1.0, max_z / (self.z_score_threshold * 2)) if max_z > 0 else 0.0

        if not outliers and result.flagged:
            # Fallback: just return the highest-z variant
            outliers = [max(z_scores, key=z_scores.get)]  # type: ignore[arg-type]

        logger.debug(
            "DisagreementAttributor: outliers=%s z_scores=%s confidence=%.3f",
            outliers,
            {k: f"{v:.3f}" for k, v in z_scores.items()},
            confidence,
        )

        return AttributionResult(
            outlier_variants=outliers,
            outlier_scores=mean_distances,
            method="z_score_pairwise",
            confidence=confidence,
        )


# ---------------------------------------------------------------------------
# FalsePositiveTracker
# ---------------------------------------------------------------------------


@dataclass
class FPObservation:
    """A single flag + outcome pair for FP tracking."""

    cycle: int
    flagged: bool
    outcome_known: bool
    was_false_positive: bool | None  # set retrospectively


class FalsePositiveTracker:
    """
    Tracks whether Ring 1 flags were genuine (i.e., strategy actually degraded)
    or false positives.

    Outcomes are registered retrospectively by calling ``record_outcome``.
    The tracker maintains a rolling false positive rate for use by
    AdaptiveThresholdManager.

    Usage::

        tracker = FalsePositiveTracker(window=100)
        tracker.record_flag(cycle=5, flagged=True)
        tracker.record_outcome(cycle=5, was_false_positive=False)
        fp_rate = tracker.false_positive_rate()
    """

    def __init__(self, window: int = 100) -> None:
        self.window = window
        self._observations: dict[int, FPObservation] = {}
        self._resolved: deque[bool] = deque(maxlen=window)  # True = FP, False = TP

    def record_flag(self, cycle: int, flagged: bool) -> None:
        """Record that a flag (or non-flag) occurred at this cycle."""
        self._observations[cycle] = FPObservation(
            cycle=cycle,
            flagged=flagged,
            outcome_known=False,
            was_false_positive=None,
        )

    def record_outcome(self, cycle: int, was_false_positive: bool) -> None:
        """
        Record the retrospective outcome for a previously flagged cycle.

        was_false_positive=True  → Ring 1 flagged but no real problem occurred.
        was_false_positive=False → Ring 1 flagged AND the strategy degraded (true positive).
        """
        obs = self._observations.get(cycle)
        if obs is None:
            logger.warning("FalsePositiveTracker: no observation for cycle %d; ignoring.", cycle)
            return
        if not obs.flagged:
            logger.debug(
                "FalsePositiveTracker: cycle %d was not flagged; outcome irrelevant.",
                cycle,
            )
            return

        obs.outcome_known = True
        obs.was_false_positive = was_false_positive
        self._resolved.append(was_false_positive)

        logger.debug(
            "FalsePositiveTracker: cycle=%d was_false_positive=%s fp_rate=%.3f",
            cycle,
            was_false_positive,
            self.false_positive_rate(),
        )

    def false_positive_rate(self) -> float:
        """Rolling FP rate over the last ``window`` resolved flags."""
        if not self._resolved:
            return 0.0
        return sum(self._resolved) / len(self._resolved)

    def flag_rate(self, recent_n: int | None = None) -> float:
        """Fraction of cycles where flagged=True in the last recent_n observations."""
        obs_list = list(self._observations.values())
        if recent_n is not None:
            obs_list = obs_list[-recent_n:]
        if not obs_list:
            return 0.0
        return sum(1 for o in obs_list if o.flagged) / len(obs_list)

    def pending_outcomes(self) -> list[int]:
        """Return cycle IDs of flags that do not yet have an outcome recorded."""
        return [
            cycle
            for cycle, obs in self._observations.items()
            if obs.flagged and not obs.outcome_known
        ]

    def summary(self) -> dict[str, Any]:
        total = len(self._observations)
        flagged = sum(1 for o in self._observations.values() if o.flagged)
        resolved = len(self._resolved)
        return {
            "total_cycles_observed": total,
            "total_flagged": flagged,
            "resolved_flags": resolved,
            "false_positive_rate": self.false_positive_rate(),
            "pending_outcomes": len(self.pending_outcomes()),
        }


# ---------------------------------------------------------------------------
# Ring 2 activation logic helpers
# ---------------------------------------------------------------------------


@dataclass
class Ring2ActivationStatus:
    """Tracks Ring 2 simulation gate results for activation decisions."""

    activated: bool
    last_gate_cycle: int
    last_gate_passed: bool | None
    consecutive_gate_passes: int
    consecutive_gate_fails: int
    total_evaluations: int


class Ring2ActivationController:
    """
    Decides whether Ring 2 scenario simulation should gate further execution.

    Ring 2 is activated (simulation gate applied) when:
    - Ring 1 has been validated (min_ring1_cycles run, min flag rate observed)
    - OR the strategy flag rate exceeds a threshold

    When Ring 2 is active, the SimulationGate result is included in the report
    and can block strategy promotion.
    """

    def __init__(
        self,
        min_ring1_cycles: int = 20,
        min_ring1_flag_rate: float = 0.05,
        gate: SimulationGate | None = None,
    ) -> None:
        self.min_ring1_cycles = min_ring1_cycles
        self.min_ring1_flag_rate = min_ring1_flag_rate
        self.gate = gate or SimulationGate()
        self._status = Ring2ActivationStatus(
            activated=False,
            last_gate_cycle=-1,
            last_gate_passed=None,
            consecutive_gate_passes=0,
            consecutive_gate_fails=0,
            total_evaluations=0,
        )

    def should_activate(
        self,
        ring1_cycles_run: int,
        ring1_flag_rate: float,
    ) -> bool:
        activated = (
            ring1_cycles_run >= self.min_ring1_cycles
            and ring1_flag_rate >= self.min_ring1_flag_rate
        )
        self._status.activated = activated
        return activated

    def record_gate_result(self, cycle: int, passed: bool) -> None:
        self._status.last_gate_cycle = cycle
        self._status.last_gate_passed = passed
        self._status.total_evaluations += 1
        if passed:
            self._status.consecutive_gate_passes += 1
            self._status.consecutive_gate_fails = 0
        else:
            self._status.consecutive_gate_fails += 1
            self._status.consecutive_gate_passes = 0

    @property
    def status(self) -> Ring2ActivationStatus:
        return self._status


# ---------------------------------------------------------------------------
# AdversarialPressureV2
# ---------------------------------------------------------------------------


@dataclass
class AdversarialReportV2:
    """Enhanced report including attribution, threshold adjustments, and Ring 2 gate."""

    base_report: AdversarialReport
    attribution: AttributionResult | None
    threshold_adjustment: ThresholdAdjustment | None
    fp_summary: dict[str, Any]
    ring2_sim_report: SimulationReport | None
    ring2_activated: bool
    current_threshold: float


class AdversarialPressureV2:
    """
    Enhanced adversarial pressure orchestrator extending AdversarialPressure.

    New capabilities
    ----------------
    - AdaptiveThresholdManager: Ring 1 threshold auto-tunes every N cycles.
    - DisagreementAttributor: identifies outlier variants on every flagged cycle.
    - FalsePositiveTracker: tracks flag accuracy over time.
    - Ring 2 activation logic: scenario bank gate runs when Ring 1 validated.

    Usage::

        ap = AdversarialPressureV2(ring1_threshold=0.2, population_size=10)
        ap.ring3.initialise_population(base_params)

        report = ap.run_v2(
            cycle=cycle_number,
            variant_outputs={"v_a": {...}, "v_b": {...}},
            current_signals={"BTCUSDT": 0.8, ...},
            strategy_params={"threshold": 0.5},
            fitness_fn=my_fitness_fn,
            strategy_callable=my_strategy,   # for Ring 2 simulation gate
        )

        # Register outcome after N cycles to feed adaptive threshold
        ap.register_outcome(cycle=5, was_false_positive=True)
    """

    RING2_SIM_INTERVAL: int = 20  # cycles between Ring 2 simulation gate runs

    def __init__(
        self,
        ring1_threshold: float = 0.20,
        population_size: int = 10,
        active_rings: list[int] | None = None,
        # Adaptive threshold params
        min_threshold: float = 0.05,
        max_threshold: float = 0.60,
        threshold_step: float = 0.02,
        fp_high_watermark: float = 0.30,
        fp_low_watermark: float = 0.05,
        adjustment_interval: int = 10,
        # Attribution params
        outlier_z_threshold: float = 1.5,
        # Ring 2 activation
        min_ring1_cycles_for_ring2: int = 20,
        min_ring1_flag_rate_for_ring2: float = 0.05,
        # Scenario bank seed
        scenario_seed: int | None = None,
    ) -> None:
        self._base = AdversarialPressure(
            ring1_threshold=ring1_threshold,
            population_size=population_size,
            active_rings=active_rings if active_rings is not None else [1],
        )

        self.threshold_mgr = AdaptiveThresholdManager(
            initial_threshold=ring1_threshold,
            min_threshold=min_threshold,
            max_threshold=max_threshold,
            step_size=threshold_step,
            fp_rate_high_watermark=fp_high_watermark,
            fp_rate_low_watermark=fp_low_watermark,
            adjustment_interval=adjustment_interval,
        )
        self.attributor = DisagreementAttributor(z_score_threshold=outlier_z_threshold)
        self.fp_tracker = FalsePositiveTracker(window=100)

        self._scenario_bank = HistoricalScenarioBank()
        self._synth_gen = SyntheticScenarioGenerator(seed=scenario_seed)
        self._sim_gate = SimulationGate()
        self._ring2_ctrl = Ring2ActivationController(
            min_ring1_cycles=min_ring1_cycles_for_ring2,
            min_ring1_flag_rate=min_ring1_flag_rate_for_ring2,
            gate=self._sim_gate,
        )

        # Expose inner rings for external access
        self.ring1 = self._base.ring1
        self.ring2 = self._base.ring2
        self.ring3 = self._base.ring3
        self.active_rings = self._base.active_rings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_v2(
        self,
        cycle: int,
        variant_outputs: dict[str, dict[str, float]],
        current_signals: dict[str, float],
        strategy_params: dict[str, Any],
        fitness_fn: Any = None,
        strategy_callable: Any = None,
    ) -> AdversarialReportV2:
        """
        Full enhanced adversarial cycle.

        1. Sync Ring 1 threshold from adaptive manager.
        2. Run base AdversarialPressure cycle (all active rings).
        3. If Ring 1 flagged: attribute outliers, update FP tracker.
        4. Adjust threshold based on FP rate.
        5. If Ring 2 activation criteria met and on interval: run simulation gate.
        """
        # Sync threshold
        self._base.ring1.disagreement_threshold = self.threshold_mgr.current_threshold

        # Base run
        base_report = self._base.run(
            cycle=cycle,
            variant_outputs=variant_outputs,
            current_signals=current_signals,
            strategy_params=strategy_params,
            fitness_fn=fitness_fn,
        )

        # Attribution on flag
        attribution: AttributionResult | None = None
        if base_report.ring1_result and base_report.ring1_result.flagged:
            attribution = self.attributor.attribute(base_report.ring1_result)
            logger.info(
                "AdversarialV2 [cycle=%d]: Ring 1 flagged — outliers=%s confidence=%.3f",
                cycle,
                attribution.outlier_variants,
                attribution.confidence,
            )

        # Record flag in FP tracker
        self.fp_tracker.record_flag(
            cycle=cycle,
            flagged=bool(base_report.ring1_result and base_report.ring1_result.flagged),
        )

        # Adaptive threshold update
        threshold_adjustment: ThresholdAdjustment | None = None
        fp_rate = self.fp_tracker.false_positive_rate()
        flag_rate = self.fp_tracker.flag_rate(recent_n=50)
        threshold_adjustment = self.threshold_mgr.update(
            cycle=cycle,
            false_positive_rate=fp_rate,
            flag_rate=flag_rate,
        )

        # Ring 2 simulation gate (if activated and on interval)
        ring2_sim_report: SimulationReport | None = None
        ring2_activated = self._ring2_ctrl.should_activate(
            ring1_cycles_run=self._base._ring1_cycles_run,
            ring1_flag_rate=flag_rate,
        )

        if (
            ring2_activated
            and strategy_callable is not None
            and cycle % self.RING2_SIM_INTERVAL == 0
        ):
            ring2_sim_report = self._run_ring2_gate(
                cycle=cycle,
                strategy_callable=strategy_callable,
                current_signals=current_signals,
            )
            if ring2_sim_report is not None:
                self._ring2_ctrl.record_gate_result(
                    cycle=cycle,
                    passed=ring2_sim_report.gate_passed,
                )

        return AdversarialReportV2(
            base_report=base_report,
            attribution=attribution,
            threshold_adjustment=threshold_adjustment,
            fp_summary=self.fp_tracker.summary(),
            ring2_sim_report=ring2_sim_report,
            ring2_activated=ring2_activated,
            current_threshold=self.threshold_mgr.current_threshold,
        )

    def register_outcome(self, cycle: int, was_false_positive: bool) -> None:
        """
        Register retrospective outcome for a previously flagged cycle.

        Call this after N cycles have elapsed and you can evaluate whether the
        flag at ``cycle`` was genuine or a false alarm.
        """
        self.fp_tracker.record_outcome(cycle=cycle, was_false_positive=was_false_positive)

    def collect_failure_cases(self) -> list[dict]:
        """Delegate to the base AdversarialPressure failure case buffer."""
        return self._base.collect_failure_cases()

    def clear_failure_cases(self) -> None:
        self._base.clear_failure_cases()

    def validate_ring1(
        self,
        min_cycles: int = 10,
        min_flag_rate: float = 0.05,
    ) -> bool:
        return self._base.validate_ring1(min_cycles=min_cycles, min_flag_rate=min_flag_rate)

    @property
    def ring2_status(self) -> Ring2ActivationStatus:
        return self._ring2_ctrl.status

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_ring2_gate(
        self,
        cycle: int,
        strategy_callable: Any,
        current_signals: dict[str, float],
    ) -> SimulationReport | None:
        """Run historical + synthetic scenarios through the simulation gate."""
        try:
            # Collect scenarios: top 5 historical by severity + 5 synthetic
            historical = sorted(
                self._scenario_bank.all_scenarios(),
                key=lambda s: s.severity,
                reverse=True,
            )[:5]

            synthetic = self._synth_gen.generate(
                base_signals=current_signals,
                n_scenarios=5,
            )
            all_scenarios = historical + synthetic

            report = self._sim_gate.run_and_evaluate(
                strategy_id=f"ring2_gate_cycle_{cycle}",
                strategy=strategy_callable,
                scenarios=all_scenarios,
                base_signals=current_signals,
            )

            logger.info(
                "AdversarialV2 Ring2Gate [cycle=%d]: passed=%s overall_resilience=%.3f",
                cycle,
                report.gate_passed,
                report.overall_resilience,
            )
            return report

        except Exception as exc:
            logger.warning("AdversarialV2 Ring2Gate [cycle=%d]: exception — %s", cycle, exc)
            return None
