"""
omega.core.memory_v2
~~~~~~~~~~~~~~~~~~~~
Extended MemoryKernel with regime-awareness, catastrophic forgetting prevention,
and contradictory evidence handling.

New components
--------------
  BOCPDRegimeDetector        : Bayesian Online Changepoint Detection via Normal-Gamma
                               conjugate prior; labels regimes as normal/trending/volatile/crash.
  RegimeTaggedSemanticStore  : Stores/retrieves SemanticMemory objects tagged with regime context.
  EWCProtection              : Elastic Weight Consolidation to prevent catastrophic forgetting
                               when the system transitions between regimes.
  DempsterShaferFusion       : Dempster-Shafer evidence theory for combining contradictory
                               multi-source signals.
  ContradictionResolver      : High-level orchestrator that combines BOCPD regime context,
                               AGM entrenchment, and DS fusion into a single Resolution.
  MemoryKernelV2             : Subclass of MemoryKernel wiring all of the above together.

Design notes
------------
- Pure Python stdlib: no numpy, scipy, torch, or third-party packages.
- All statistical operations use Welford's online algorithm for numerical stability.
- Dempster-Shafer uses frozensets for power-set hypothesis tracking.
- Student-t PDF is approximated via the kernel-form (1 + z²/df)^(-(df+1)/2); only
  *relative* probabilities matter because all values are renormalised at every step.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from typing import Any

from omega.core.memory import MemoryKernel, SemanticMemory

logger = logging.getLogger("omega.core.memory_v2")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _student_t_pdf(x: float, df: float, loc: float, scale: float) -> float:
    """
    Unnormalised Student-t kernel: (1 + ((x-loc)/scale)^2 / df)^(-(df+1)/2).

    Only relative probabilities are needed for the run-length normalisation step,
    so the normalisation constant is omitted for efficiency.
    """
    z = (x - loc) / max(scale, 1e-10)
    return (1.0 + z * z / max(df, 1.0)) ** (-(df + 1.0) / 2.0)


# ---------------------------------------------------------------------------
# BOCPDRegimeDetector
# ---------------------------------------------------------------------------

@dataclass
class RegimeState:
    """Snapshot of the detector's belief about the current market regime."""
    regime_id: str           # UUID; changes whenever a changepoint is detected
    changepoint_prob: float  # P(run_length == 0) after the latest update
    regime_start_cycle: int
    mean_estimate: float
    variance_estimate: float
    observations_in_regime: int
    label: str               # "normal" | "trending" | "volatile" | "crash"


class BOCPDRegimeDetector:
    """
    Bayesian Online Changepoint Detection using a Normal-Gamma conjugate prior.

    For each possible run length r the detector maintains sufficient statistics
    (n, mean, M2) from Welford's algorithm.  Predictive probabilities are
    evaluated with an unnormalised Student-t kernel; the run-length distribution
    is re-normalised after each observation.

    Reference: Adams & MacKay (2007) "Bayesian Online Changepoint Detection".
    """

    def __init__(
        self,
        hazard_rate: float = 0.05,
        prior_mean: float = 0.0,
        prior_var: float = 1.0,
    ) -> None:
        self._hazard = hazard_rate          # P(changepoint at each step)
        self._prior_mean = prior_mean
        self._prior_var = prior_var

        # run-length distribution: {run_length: probability}
        self._run_probs: dict[int, float] = {0: 1.0}

        # sufficient statistics per run length: {run_length: (n, mean, M2)}
        self._stats: dict[int, tuple[int, float, float]] = {}

        # current regime book-keeping
        self._regime_id = str(uuid.uuid4())
        self._regime_start_cycle = 0
        self._cycle = 0
        self._regime_mean = prior_mean
        self._regime_var = prior_var
        self._regime_n = 0

    # ------------------------------------------------------------------ public

    def update(self, observation: float) -> RegimeState:
        """Process one observation and return the updated RegimeState."""
        self._cycle += 1
        new_probs: dict[int, float] = {}
        new_stats: dict[int, tuple[int, float, float]] = {}

        total_mass = 0.0

        # --- growth probabilities: existing run lengths grow by 1 ------------
        for rl, prob in self._run_probs.items():
            pred = self._predictive_prob(rl, observation)
            grown_rl = rl + 1
            new_p = prob * pred * (1.0 - self._hazard)
            new_probs[grown_rl] = new_probs.get(grown_rl, 0.0) + new_p
            total_mass += new_p

            # update sufficient stats for the grown run length
            prev_stats = self._stats.get(rl, (0, self._prior_mean, 0.0))
            n, mu, M2 = prev_stats
            n_new = n + 1
            delta = observation - mu
            mu_new = mu + delta / n_new
            delta2 = observation - mu_new
            M2_new = M2 + delta * delta2
            new_stats[grown_rl] = (n_new, mu_new, M2_new)

        # --- changepoint probability: run length resets to 0 -----------------
        # Sum over all run lengths weighted by hazard * their current prob
        cp_mass = sum(
            prob * self._hazard * self._predictive_prob(rl, observation)
            for rl, prob in self._run_probs.items()
        )
        new_probs[0] = new_probs.get(0, 0.0) + cp_mass
        total_mass += cp_mass
        # stats for run_length=0 restart fresh with the new observation
        new_stats[0] = (1, observation, 0.0)

        # --- normalise -------------------------------------------------------
        if total_mass > 0.0:
            for rl in new_probs:
                new_probs[rl] /= total_mass
        else:
            # degenerate: reset to uniform over the new run length
            new_probs = {0: 1.0}
            new_stats = {0: (1, observation, 0.0)}

        self._run_probs = new_probs
        self._stats = new_stats

        # --- detect changepoint ----------------------------------------------
        cp_prob = new_probs.get(0, 0.0)
        changepoint_detected = cp_prob > 0.5

        if changepoint_detected:
            logger.info(
                "BOCPD: changepoint detected at cycle %d (P=%.3f), new regime",
                self._cycle, cp_prob,
            )
            self._regime_id = str(uuid.uuid4())
            self._regime_start_cycle = self._cycle
            self._regime_n = 1
            self._regime_mean = observation
            self._regime_var = self._prior_var
        else:
            # Welford update for the within-regime running mean/var
            self._regime_n += 1
            delta = observation - self._regime_mean
            self._regime_mean += delta / self._regime_n
            delta2 = observation - self._regime_mean
            # accumulate M2, then derive variance estimate
            if not hasattr(self, "_regime_M2"):
                self._regime_M2 = 0.0
            self._regime_M2 += delta * delta2
            self._regime_var = (
                self._regime_M2 / self._regime_n if self._regime_n > 1 else self._prior_var
            )

        label = self._label_regime(self._regime_mean, self._regime_var)
        return RegimeState(
            regime_id=self._regime_id,
            changepoint_prob=cp_prob,
            regime_start_cycle=self._regime_start_cycle,
            mean_estimate=self._regime_mean,
            variance_estimate=self._regime_var,
            observations_in_regime=self._regime_n,
            label=label,
        )

    def current_regime(self) -> RegimeState:
        """Return the current regime state without consuming a new observation."""
        label = self._label_regime(self._regime_mean, self._regime_var)
        return RegimeState(
            regime_id=self._regime_id,
            changepoint_prob=self._run_probs.get(0, 0.0),
            regime_start_cycle=self._regime_start_cycle,
            mean_estimate=self._regime_mean,
            variance_estimate=self._regime_var,
            observations_in_regime=self._regime_n,
            label=label,
        )

    # ------------------------------------------------------------------ private

    def _predictive_prob(self, run_length: int, observation: float) -> float:
        """
        Student-t predictive density for a given run length using accumulated
        sufficient statistics.  Falls back to the prior when no stats exist.
        """
        stats = self._stats.get(run_length)
        if stats is None or stats[0] == 0:
            # prior predictive: Student-t(df=1, loc=prior_mean, scale=sqrt(prior_var))
            return _student_t_pdf(
                observation,
                df=1.0,
                loc=self._prior_mean,
                scale=math.sqrt(self._prior_var),
            )
        n, mu, M2 = stats
        # sample variance estimate
        s2 = M2 / max(n, 1)
        # predictive scale: sqrt(s2 * (1 + 1/n))
        scale = math.sqrt(max(s2, 1e-10) * (1.0 + 1.0 / max(n, 1)))
        return _student_t_pdf(observation, df=float(n), loc=mu, scale=scale)

    def _label_regime(self, mean: float, var: float) -> str:
        """Map (mean, variance) to a human-readable regime label."""
        if mean < -0.05:
            return "crash"
        if var > 0.1:
            return "volatile"
        if abs(mean) > 0.02:
            return "trending"
        if abs(mean) < 0.01 and var < 0.05:
            return "normal"
        return "normal"


# ---------------------------------------------------------------------------
# SlidingWindowRegimeDetector  (default; simpler than BOCPD)
# ---------------------------------------------------------------------------

class SlidingWindowRegimeDetector:
    """
    Regime detector based on realized volatility quantiles over a sliding window.

    Simpler than BOCPD: no i.i.d. assumption, directly interpretable, and
    computationally O(window) per update.

    Labels:
      - "crash"    : mean below crash_threshold (default -0.05)
      - "volatile" : realized volatility above vol_threshold (default 0.05)
      - "trending" : |mean| above trend_threshold (default 0.02)
      - "normal"   : everything else

    Set ``advanced_bocpd=True`` on MemoryKernelV2 to use BOCPDRegimeDetector instead.
    """

    def __init__(
        self,
        window: int = 30,
        crash_threshold: float = -0.05,
        vol_threshold: float = 0.05,
        trend_threshold: float = 0.02,
    ) -> None:
        self._window = window
        self._crash_threshold = crash_threshold
        self._vol_threshold = vol_threshold
        self._trend_threshold = trend_threshold
        self._observations: list[float] = []
        self._cycle = 0
        self._regime_id = str(uuid.uuid4())
        self._regime_start_cycle = 0
        self._last_label: str = "normal"

    def update(self, observation: float) -> RegimeState:
        """Process one observation and return the updated RegimeState."""
        self._cycle += 1
        self._observations.append(observation)
        if len(self._observations) > self._window:
            self._observations = self._observations[-self._window:]

        mean, var = self._rolling_stats()
        vol = math.sqrt(var)
        label = self._label(mean, vol)

        # Detect regime change (label changed)
        changepoint_prob = 0.0
        if label != self._last_label:
            self._regime_id = str(uuid.uuid4())
            self._regime_start_cycle = self._cycle
            changepoint_prob = 0.8
            logger.info(
                "SlidingWindow: regime change %s → %s at cycle %d",
                self._last_label, label, self._cycle,
            )
        self._last_label = label

        return RegimeState(
            regime_id=self._regime_id,
            changepoint_prob=changepoint_prob,
            regime_start_cycle=self._regime_start_cycle,
            mean_estimate=mean,
            variance_estimate=var,
            observations_in_regime=self._cycle - self._regime_start_cycle,
            label=label,
        )

    def current_regime(self) -> RegimeState:
        """Return the current regime state without consuming a new observation."""
        mean, var = self._rolling_stats()
        vol = math.sqrt(var)
        return RegimeState(
            regime_id=self._regime_id,
            changepoint_prob=0.0,
            regime_start_cycle=self._regime_start_cycle,
            mean_estimate=mean,
            variance_estimate=var,
            observations_in_regime=self._cycle - self._regime_start_cycle,
            label=self._last_label,
        )

    def _rolling_stats(self) -> tuple[float, float]:
        """Return (mean, variance) of current window using Welford's algorithm."""
        n = len(self._observations)
        if n == 0:
            return 0.0, 0.0
        mean = sum(self._observations) / n
        if n == 1:
            return mean, 0.0
        var = sum((x - mean) ** 2 for x in self._observations) / n
        return mean, var

    def _label(self, mean: float, vol: float) -> str:
        if mean < self._crash_threshold:
            return "crash"
        if vol > self._vol_threshold:
            return "volatile"
        if abs(mean) > self._trend_threshold:
            return "trending"
        return "normal"


# ---------------------------------------------------------------------------
# RegimeTaggedSemanticStore
# ---------------------------------------------------------------------------

class RegimeTaggedSemanticStore:
    """
    Thin wrapper around MemoryKernel.store_semantic / retrieve_semantic that
    automatically injects regime-context tags so memories can be recalled by
    the regime in which they were formed.
    """

    def __init__(self, kernel: MemoryKernel) -> None:
        self._kernel = kernel

    def store_with_regime(
        self,
        concept: str,
        content: str,
        confidence: float,
        regime_id: str,
        regime_label: str,
        tags: list[str] | None = None,
        namespace: str = "global",
    ) -> str:
        """Store a semantic memory annotated with regime context."""
        regime_tags = [
            f"regime:{regime_id[:8]}",
            f"regime_type:{regime_label}",
        ]
        all_tags = (tags or []) + regime_tags
        return self._kernel.store_semantic(
            concept=concept,
            content=content,
            confidence=confidence,
            tags=all_tags,
            namespace=namespace,
        )

    def retrieve_for_regime(
        self,
        regime_label: str,
        concept: str | None = None,
        limit: int = 5,
        namespace: str | None = None,
    ) -> list[SemanticMemory]:
        """
        Retrieve semantic memories that were stored under a particular regime label.
        Uses tag filtering: ``regime_type:{regime_label}``.
        """
        tag_filter = [f"regime_type:{regime_label}"]
        return self._kernel.retrieve_semantic(
            concept=concept,
            tags=tag_filter,
            limit=limit,
            namespace=namespace,
        )


# ---------------------------------------------------------------------------
# EWCProtection
# ---------------------------------------------------------------------------

class EWCProtection:
    """
    Elastic Weight Consolidation (EWC) regulariser.

    Prevents catastrophic forgetting when the system adapts to a new regime by
    penalising large deviations from previously learned parameter values,
    weighted by the Fisher information diagonal (a proxy for parameter importance).

    Reference: Kirkpatrick et al. (2017) "Overcoming catastrophic forgetting in
    neural networks".
    """

    def __init__(self, lambda_ewc: float = 0.4) -> None:
        self._lambda = lambda_ewc
        # task_id → anchor parameter dict (θ*)
        self._anchors: dict[str, dict[str, float]] = {}
        # task_id → Fisher diagonal estimate {param_name: F_i}
        self._fisher: dict[str, dict[str, float]] = {}
        # consolidated snapshot (multi-task average)
        self._consolidated_anchor: dict[str, float] = {}
        self._consolidated_fisher: dict[str, float] = {}

    def snapshot_params(self, params: dict[str, float], task_id: str) -> None:
        """Record current params as the anchor for *task_id*."""
        self._anchors[task_id] = dict(params)
        logger.debug("EWC: snapshotted %d params for task '%s'", len(params), task_id)

    def estimate_fisher(
        self,
        param_gradients_samples: list[dict[str, float]],
        task_id: str | None = None,
    ) -> dict[str, float]:
        """
        Approximate the diagonal Fisher information matrix.

        F_i ≈ mean( grad_i² ) across all gradient samples.
        If *task_id* is provided, the result is also stored internally so that
        `ewc_penalty()` and `should_regularise()` can use it directly.
        Returns a dict {param_name: fisher_value}.
        """
        if not param_gradients_samples:
            return {}

        # Accumulate sum of squared gradients
        accum: dict[str, float] = {}
        counts: dict[str, int] = {}
        for sample in param_gradients_samples:
            for pname, grad in sample.items():
                accum[pname] = accum.get(pname, 0.0) + grad * grad
                counts[pname] = counts.get(pname, 0) + 1

        fisher = {
            pname: accum[pname] / counts[pname]
            for pname in accum
        }
        if task_id is not None:
            self._fisher[task_id] = fisher
        return fisher

    def ewc_penalty(
        self,
        current_params: dict[str, float],
        task_id: str,
    ) -> float:
        """
        Compute the EWC regularisation penalty:
            L_ewc = (lambda / 2) * Σ_i  F_i * (θ_i - θ*_i)²

        Returns 0.0 if no Fisher estimate exists for *task_id*.
        """
        if task_id not in self._fisher or task_id not in self._anchors:
            return 0.0

        fisher = self._fisher[task_id]
        anchor = self._anchors[task_id]
        penalty = 0.0
        for pname, theta_star in anchor.items():
            f_i = fisher.get(pname, 0.0)
            theta_i = current_params.get(pname, theta_star)
            penalty += f_i * (theta_i - theta_star) ** 2

        return (self._lambda / 2.0) * penalty

    def consolidate(self, new_task_id: str) -> None:
        """
        After learning on *new_task_id* completes, merge the current anchor and
        Fisher into the consolidated representation so future tasks can regularise
        against the accumulated knowledge.
        """
        if new_task_id not in self._anchors:
            logger.warning("EWC consolidate: no anchor found for task '%s'", new_task_id)
            return

        # Simple parameter-averaging consolidation across all known tasks
        all_task_ids = list(self._anchors.keys())
        if not all_task_ids:
            return

        param_names: set = set()
        for tid in all_task_ids:
            param_names.update(self._anchors[tid].keys())
            if tid in self._fisher:
                param_names.update(self._fisher[tid].keys())

        consolidated_anchor: dict[str, float] = {}
        consolidated_fisher: dict[str, float] = {}

        for pname in param_names:
            anchor_vals = [
                self._anchors[tid][pname]
                for tid in all_task_ids
                if pname in self._anchors.get(tid, {})
            ]
            fisher_vals = [
                self._fisher[tid][pname]
                for tid in all_task_ids
                if pname in self._fisher.get(tid, {})
            ]
            if anchor_vals:
                consolidated_anchor[pname] = sum(anchor_vals) / len(anchor_vals)
            if fisher_vals:
                # Use the maximum Fisher value (most conservative regularisation)
                consolidated_fisher[pname] = max(fisher_vals)

        self._consolidated_anchor = consolidated_anchor
        self._consolidated_fisher = consolidated_fisher
        logger.info(
            "EWC consolidated %d tasks, %d params tracked",
            len(all_task_ids),
            len(param_names),
        )

    def should_regularise(self, task_id: str) -> bool:
        """Return True if we have an anchor snapshot for *task_id*.

        Having a snapshot means we have already learned this task and should
        regularise against it. A Fisher estimate for the task further sharpens
        the penalty but is not required for regularisation to be active.
        """
        return task_id in self._anchors

    def store_fisher(self, task_id: str, fisher: dict[str, float]) -> None:
        """Associate a pre-computed Fisher diagonal with *task_id*."""
        self._fisher[task_id] = dict(fisher)


# ---------------------------------------------------------------------------
# DempsterShaferFusion
# ---------------------------------------------------------------------------

class DempsterShaferFusion:
    """
    Dempster-Shafer evidence theory for combining contradictory multi-source signals.

    The frame of discernment Θ is provided at construction time.  Evidence sources
    assign basic probability masses (BPAs) to subsets of Θ.  The Dempster
    combination rule merges all sources, with the conflict term K tracked for
    diagnostics.

    Keys in mass functions are either single hypothesis strings (from the frame) or
    frozensets of hypothesis strings (for partial evidence / disjunctive sets).
    The special key ``"__uncertainty__"`` represents Θ itself (total ignorance).
    """

    _UNCERTAINTY_KEY = "__uncertainty__"

    def __init__(self, frame: list[str]) -> None:
        self._frame = list(frame)
        # Pre-compute power set (as frozensets) for intersection logic
        self._power_set: list[frozenset[str]] = self._build_power_set(self._frame)
        # source_id → {subset: mass}
        self._evidence: dict[str, dict[frozenset[str], float]] = {}

    # ------------------------------------------------------------------ public

    def add_evidence(self, source: str, masses: dict[str, float]) -> None:
        """
        Register a BPA from *source*.

        *masses* values may be keyed by:
          - a single hypothesis string e.g. ``"bull"``
          - a frozenset of hypothesis strings e.g. ``frozenset({"bull", "neutral"})``
          - ``"__uncertainty__"`` to assign mass to the whole frame

        Remaining probability mass (1 - sum(masses)) is automatically assigned
        to ``__uncertainty__`` (the vacuous BPA).
        """
        normalised: dict[frozenset[str], float] = {}
        total = 0.0

        for key, mass in masses.items():
            if mass <= 0.0:
                continue
            fkey = self._normalise_key(key)
            normalised[fkey] = normalised.get(fkey, 0.0) + mass
            total += mass

        # Remaining mass → uncertainty (whole frame)
        remainder = 1.0 - total
        if remainder > 1e-9:
            uncertainty_key = frozenset(self._frame)
            normalised[uncertainty_key] = normalised.get(uncertainty_key, 0.0) + remainder

        self._evidence[source] = normalised
        logger.debug("DS: added evidence from source '%s' (%d focal elements)", source, len(normalised))

    _CONFLICT_FALLBACK_THRESHOLD: float = 0.3

    def combine(self) -> dict[str, float]:
        """
        Combine all registered evidence sources using Dempster's rule.

        Before combining, computes pairwise conflict.  If conflict > 0.3,
        falls back to confidence-weighted averaging (more robust under high
        contradiction) and logs a warning.

        Returns a dict {hypothesis_string_or_frozenset: combined_mass}.
        Single-element frozensets are returned as plain strings for readability.
        """
        sources = list(self._evidence.values())
        if not sources:
            return {h: 1.0 / len(self._frame) for h in self._frame}

        # Check conflict before full combination
        conflict = self._compute_conflict()
        if conflict > self._CONFLICT_FALLBACK_THRESHOLD and len(sources) > 1:
            logger.warning(
                "DS: high conflict (K=%.3f > %.1f), falling back to "
                "confidence-weighted averaging",
                conflict,
                self._CONFLICT_FALLBACK_THRESHOLD,
            )
            return self._confidence_weighted_average()

        # Low-conflict path: standard Dempster combination
        combined = sources[0]
        for source in sources[1:]:
            combined = self._dempster_combine(combined, source)

        # Convert frozensets to readable keys
        result: dict[str, float] = {}
        for fkey, mass in combined.items():
            if mass < 1e-12:
                continue
            if len(fkey) == 1:
                result[next(iter(fkey))] = mass
            elif fkey == frozenset(self._frame):
                result[self._UNCERTAINTY_KEY] = mass
            else:
                result[str(sorted(fkey))] = mass

        return result

    def belief(self, hypothesis: str) -> float:
        """
        Bel(A) = Σ_{B ⊆ A} m(B)

        Lower bound on the degree of belief in *hypothesis*.
        """
        combined = self._combine_raw()
        a = frozenset([hypothesis])
        return sum(
            mass
            for fkey, mass in combined.items()
            if fkey and fkey.issubset(a)
        )

    def plausibility(self, hypothesis: str) -> float:
        """
        Pl(A) = Σ_{B ∩ A ≠ ∅} m(B)

        Upper bound on the degree of belief in *hypothesis*.
        """
        combined = self._combine_raw()
        a = frozenset([hypothesis])
        return sum(
            mass
            for fkey, mass in combined.items()
            if fkey and fkey & a  # non-empty intersection
        )

    def most_likely(self) -> str:
        """Return the single hypothesis with the highest plausibility."""
        if not self._frame:
            return ""
        return max(self._frame, key=lambda h: self.plausibility(h))

    def conflict_level(self) -> float:
        """
        Return the Dempster conflict coefficient K — the total mass assigned to
        the empty set during combination.  High K (→ 1) indicates strong
        contradiction between evidence sources.
        """
        return self._compute_conflict()

    def reset(self) -> None:
        """Clear all registered evidence sources."""
        self._evidence.clear()

    # ------------------------------------------------------------------ private

    def _confidence_weighted_average(self) -> dict[str, float]:
        """
        Fallback combiner for high-conflict situations.

        For each hypothesis in the frame, compute the weighted average of
        single-hypothesis masses across all sources.  Source weight = total
        non-uncertainty mass (a proxy for confidence/commitment).
        """
        # Compute per-source confidence weight (total committed mass)
        source_confidence: dict[str, float] = {}
        uncertainty_key = frozenset(self._frame)
        for src, masses in self._evidence.items():
            committed = sum(
                mass for fkey, mass in masses.items()
                if fkey != uncertainty_key
            )
            source_confidence[src] = max(committed, 1e-10)

        total_confidence = sum(source_confidence.values()) or 1.0

        # Weighted average of single-hypothesis masses per hypothesis
        result: dict[str, float] = {h: 0.0 for h in self._frame}
        for src, masses in self._evidence.items():
            w = source_confidence[src] / total_confidence
            for fkey, mass in masses.items():
                if len(fkey) == 1:
                    h = next(iter(fkey))
                    if h in result:
                        result[h] += w * mass

        # Assign remaining mass to uncertainty
        total_assigned = sum(result.values())
        remainder = max(0.0, 1.0 - total_assigned)
        if remainder > 1e-9:
            result[self._UNCERTAINTY_KEY] = remainder

        return result

    @staticmethod
    def _build_power_set(elements: list[str]) -> list[frozenset[str]]:
        """Generate the power set of *elements* as a list of frozensets."""
        result: list[frozenset[str]] = [frozenset()]
        for elem in elements:
            result = result + [s | frozenset([elem]) for s in result]
        return result

    def _normalise_key(self, key: Any) -> frozenset[str]:
        """Convert a user-supplied mass key to a canonical frozenset."""
        if isinstance(key, frozenset):
            return key
        if key == self._UNCERTAINTY_KEY:
            return frozenset(self._frame)
        if isinstance(key, str):
            return frozenset([key])
        # Assume iterable
        return frozenset(key)

    def _dempster_combine(
        self,
        m1: dict[frozenset[str], float],
        m2: dict[frozenset[str], float],
    ) -> dict[frozenset[str], float]:
        """
        Core Dempster combination: m12(A) = Σ_{B∩C=A} m1(B)*m2(C) / (1 - K).
        Returns the normalised combined BPA.
        """
        raw: dict[frozenset[str], float] = {}
        conflict_mass = 0.0

        for b, mb in m1.items():
            for c, mc in m2.items():
                intersection = b & c
                prod = mb * mc
                if not intersection:
                    conflict_mass += prod
                else:
                    raw[intersection] = raw.get(intersection, 0.0) + prod

        # Normalise by (1 - K)
        norm_factor = 1.0 - conflict_mass
        if norm_factor < 1e-10:
            # Total conflict — return vacuous BPA
            logger.warning(
                "DS: total conflict (K≈1) between evidence sources; returning vacuous BPA"
            )
            return {frozenset(self._frame): 1.0}

        return {fkey: mass / norm_factor for fkey, mass in raw.items()}

    def _combine_raw(self) -> dict[frozenset[str], float]:
        """Internal: combine all sources and return frozenset-keyed result."""
        sources = list(self._evidence.values())
        if not sources:
            # vacuous
            return {frozenset(self._frame): 1.0}
        combined = sources[0]
        for source in sources[1:]:
            combined = self._dempster_combine(combined, source)
        return combined

    def _compute_conflict(self) -> float:
        """Compute the overall conflict K across all evidence sources."""
        sources = list(self._evidence.values())
        if len(sources) < 2:
            return 0.0

        combined = sources[0]
        total_conflict = 0.0

        for source in sources[1:]:
            k = 0.0
            for b, mb in combined.items():
                for c, mc in source.items():
                    if not (b & c):
                        k += mb * mc
            total_conflict = k + total_conflict * (1.0 - k)  # accumulated conflict
            norm_factor = 1.0 - k
            if norm_factor > 1e-10:
                new_combined: dict[frozenset[str], float] = {}
                for b, mb in combined.items():
                    for c, mc in source.items():
                        intersection = b & c
                        if intersection:
                            new_combined[intersection] = new_combined.get(intersection, 0.0) + mb * mc / norm_factor
                combined = new_combined
            else:
                combined = {frozenset(self._frame): 1.0}

        return min(total_conflict, 1.0)


# ---------------------------------------------------------------------------
# ContradictionResolver
# ---------------------------------------------------------------------------

@dataclass
class Resolution:
    """The output of ContradictionResolver.resolve()."""
    conclusion: str                   # most likely outcome
    confidence: float                 # 0→1
    conflict_level: float             # DS conflict K
    regime_context: str               # current regime label
    evidence_summary: dict[str, float]  # source → evidence strength
    used_entrenchment: bool           # whether AGM belief revision fired


class ContradictionResolver:
    """
    Orchestrates regime detection, AGM entrenchment, and Dempster-Shafer fusion
    to produce a single consolidated Resolution from a set of (possibly
    contradictory) observations.
    """

    _DEFAULT_FRAME = ["bull", "bear", "neutral", "volatile"]

    def __init__(
        self,
        regime_detector: BOCPDRegimeDetector,
        ds_frame: list[str] | None = None,
    ) -> None:
        self._detector = regime_detector
        self._frame = ds_frame or self._DEFAULT_FRAME
        self._ds = DempsterShaferFusion(self._frame)

    # ------------------------------------------------------------------ public

    def resolve(self, observations: list[dict]) -> Resolution:
        """
        Produce a Resolution from a list of observations.

        Each observation dict must have:
            ``source``  : str  — identifier of the evidence source
            ``value``   : float — numeric signal value
            ``signal``  : str  — one of the DS frame hypotheses (or closest match)

        Steps:
            1. Determine current regime.
            2. Compute evidence strength = |value| for each observation.
            3. Normalise strengths so they sum to 1.
            4. Detect high-conflict scenario; if K > 0.5 apply AGM entrenchment
               (down-weight least-entrenched / oldest sources).
            5. Build DS mass functions from (possibly re-weighted) evidence.
            6. Combine and return Resolution.
        """
        if not observations:
            regime = self._detector.current_regime()
            return Resolution(
                conclusion="neutral",
                confidence=0.0,
                conflict_level=0.0,
                regime_context=regime.label,
                evidence_summary={},
                used_entrenchment=False,
            )

        regime = self._detector.current_regime()

        # --- Step 1: evidence strengths --------------------------------------
        strengths: dict[str, float] = {
            obs["source"]: abs(obs.get("value", 0.0))
            for obs in observations
        }
        total_strength = sum(strengths.values()) or 1.0
        normalised: dict[str, float] = {
            src: s / total_strength for src, s in strengths.items()
        }

        # --- Step 2: preliminary DS combine to check conflict ----------------
        self._ds.reset()
        for obs in observations:
            src = obs["source"]
            sig = self._sanitise_signal(obs.get("signal", "neutral"))
            mass = normalised[src]
            self._ds.add_evidence(src, {sig: mass})

        conflict = self._ds.conflict_level()
        used_entrenchment = False

        # --- Step 3: AGM entrenchment if conflict is high --------------------
        if conflict > 0.5:
            used_entrenchment = True
            logger.info(
                "ContradictionResolver: high conflict (K=%.3f), applying AGM entrenchment",
                conflict,
            )
            # Older sources are less entrenched; treat list index as proxy for recency
            # (later elements are assumed more recent / higher entrenchment).
            n = len(observations)
            self._ds.reset()
            for idx, obs in enumerate(observations):
                src = obs["source"]
                sig = self._sanitise_signal(obs.get("signal", "neutral"))
                # entrenchment weight: later observations get full weight,
                # earlier ones are discounted proportionally.
                entrenchment = (idx + 1) / n  # ∈ (0, 1]
                base_mass = normalised[src] * entrenchment
                # re-normalise so all masses still sum to ≤ 1 per source
                self._ds.add_evidence(src, {sig: min(base_mass, 0.95)})

            conflict = self._ds.conflict_level()

        # --- Step 4: extract result ------------------------------------------
        conclusion = self._ds.most_likely()
        # confidence = plausibility of conclusion minus conflict penalty
        raw_confidence = self._ds.plausibility(conclusion)
        confidence = max(0.0, raw_confidence * (1.0 - conflict * 0.5))

        return Resolution(
            conclusion=conclusion,
            confidence=min(1.0, confidence),
            conflict_level=conflict,
            regime_context=regime.label,
            evidence_summary=normalised,
            used_entrenchment=used_entrenchment,
        )

    # ------------------------------------------------------------------ private

    def _sanitise_signal(self, signal: str) -> str:
        """Map a raw signal string to the nearest hypothesis in the DS frame."""
        if signal in self._frame:
            return signal
        signal_lower = signal.lower()
        for h in self._frame:
            if h in signal_lower or signal_lower in h:
                return h
        return "neutral" if "neutral" in self._frame else self._frame[-1]


# ---------------------------------------------------------------------------
# MemoryKernelV2
# ---------------------------------------------------------------------------

class MemoryKernelV2(MemoryKernel):
    """
    Extended MemoryKernel with regime-awareness, catastrophic forgetting
    prevention, and contradictory evidence handling.

    By default uses SlidingWindowRegimeDetector (simpler, no i.i.d. assumption).
    Set ``advanced_bocpd=True`` to switch to BOCPDRegimeDetector.

    EWC is opt-in (``ewc_enabled=False`` by default) because Fisher information
    estimation is questionable for LLM-backed nodes.  Default memory management
    uses the base MemoryKernel's exponential decay / consolidation path.

    Adds:
      - ``update_regime(observation)``           — feed regime detector
      - ``store_episode_v2(...)``                — regime-tagged episode storage
      - ``get_regime_context()``                 — current regime as plain dict
      - ``resolve_contradictions(observations)`` — delegate to ContradictionResolver
      - ``consolidate_regime_memory(namespace)`` — regime-aware consolidation
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        ewc_enabled: bool = False,
        advanced_bocpd: bool = False,
    ) -> None:
        super().__init__(db_path=db_path)
        self.ewc_enabled = ewc_enabled
        # Regime detector: sliding window by default, BOCPD if advanced_bocpd=True
        if advanced_bocpd:
            self.regime_detector: Any = BOCPDRegimeDetector()
        else:
            self.regime_detector = SlidingWindowRegimeDetector()
        self.regime_store = RegimeTaggedSemanticStore(self)
        self.ewc = EWCProtection() if ewc_enabled else None
        self.resolver = ContradictionResolver(self.regime_detector)
        self._current_regime: RegimeState | None = None
        logger.info(
            "MemoryKernelV2 initialised (db=%s, ewc=%s, bocpd=%s)",
            db_path, ewc_enabled, advanced_bocpd,
        )

    # ------------------------------------------------------------------ regime

    def update_regime(self, observation: float) -> RegimeState:
        """
        Feed *observation* into the BOCPD detector and update the current regime.

        On a detected changepoint (P > 0.5):
          - logs the transition
          - snapshots EWC params (working memory snapshot as surrogate params)
        """
        prev_regime_id = (
            self._current_regime.regime_id if self._current_regime else None
        )
        new_regime = self.regime_detector.update(observation)
        self._current_regime = new_regime

        if new_regime.changepoint_prob > 0.5 and new_regime.regime_id != prev_regime_id:
            logger.info(
                "MemoryKernelV2: regime transition → %s (cycle=%d, P_cp=%.3f)",
                new_regime.label,
                new_regime.regime_start_cycle,
                new_regime.changepoint_prob,
            )
            # Snapshot working memory as EWC params only when EWC is enabled
            if self.ewc_enabled and self.ewc is not None and prev_regime_id:
                working = self.working_snapshot()
                numeric_params = {
                    k: float(v)
                    for k, v in working.items()
                    if isinstance(v, (int, float))
                }
                if numeric_params:
                    self.ewc.snapshot_params(numeric_params, task_id=prev_regime_id)

        return new_regime

    def store_episode_v2(
        self,
        event_type: str,
        content: dict[str, Any],
        tags: list[str] | None = None,
        importance: float = 1.0,
        cycle: int | None = None,
        namespace: str = "global",
    ) -> str:
        """
        Like :meth:`MemoryKernel.store_episode` but automatically injects
        regime-context tags (``regime:<id_prefix>`` and ``regime_type:<label>``).
        """
        regime = self._current_regime or self.regime_detector.current_regime()
        regime_tags = [
            f"regime:{regime.regime_id[:8]}",
            f"regime_type:{regime.label}",
        ]
        all_tags = (tags or []) + regime_tags
        return self.store_episode(
            event_type=event_type,
            content=content,
            tags=all_tags,
            importance=importance,
            cycle=cycle,
            namespace=namespace,
        )

    def get_regime_context(self) -> dict[str, Any]:
        """Return the current regime state as a plain dictionary."""
        regime = self._current_regime or self.regime_detector.current_regime()
        return {
            "regime_id": regime.regime_id,
            "changepoint_prob": regime.changepoint_prob,
            "regime_start_cycle": regime.regime_start_cycle,
            "mean_estimate": regime.mean_estimate,
            "variance_estimate": regime.variance_estimate,
            "observations_in_regime": regime.observations_in_regime,
            "label": regime.label,
        }

    # ------------------------------------------------------------------ contradiction resolution

    def resolve_contradictions(self, observations: list[dict]) -> Resolution:
        """Delegate contradiction resolution to :class:`ContradictionResolver`."""
        return self.resolver.resolve(observations)

    # ------------------------------------------------------------------ consolidation

    def consolidate_regime_memory(self, namespace: str | None = None) -> list[str]:
        """
        Regime-aware consolidation.

        Calls the parent :meth:`MemoryKernel.consolidate` then enhances any new
        semantic memories with a regime tag so they can be retrieved later by
        regime label.

        Returns the list of concept names that were updated/created.
        """
        updated_concepts = self.consolidate(namespace=namespace)

        if not updated_concepts:
            return updated_concepts

        regime = self._current_regime or self.regime_detector.current_regime()
        store_ns = namespace or "global"

        for concept in updated_concepts:
            # Retrieve the just-written semantic memory to get its content/confidence
            memories = self.retrieve_semantic(concept=concept, limit=1, namespace=store_ns)
            if not memories:
                continue
            mem = memories[0]
            # Re-store with regime tags appended (store_semantic will reinforce if exists)
            regime_tags = [
                f"regime:{regime.regime_id[:8]}",
                f"regime_type:{regime.label}",
            ]
            existing_tags = [
                t for t in mem.tags
                if not t.startswith("regime:")
                and not t.startswith("regime_type:")
            ]
            self.store_semantic(
                concept=concept,
                content=mem.content,
                confidence=mem.confidence,
                tags=existing_tags + regime_tags,
                namespace=store_ns,
            )

        logger.info(
            "MemoryKernelV2: regime-enhanced %d consolidated concepts (regime=%s)",
            len(updated_concepts),
            regime.label,
        )
        return updated_concepts
