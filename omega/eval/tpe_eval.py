"""
omega.eval.tpe_eval
~~~~~~~~~~~~~~~~~~~~
TPE convergence evaluation.

Runs TPE optimization for N trials, records score per trial, and compares
against a random search baseline.  Measures:

- convergence_curve()       : best score seen at each trial
- regret_curve()            : cumulative regret vs oracle (best achievable)
- trials_to_convergence()   : trials until improvement < epsilon
- beats_random()            : statistical test vs random baseline

Usage::

    from omega.eval.tpe_eval import TPEEvaluator

    ev = TPEEvaluator(n_trials=100, seed=42)
    ev.run()
    print(ev.convergence_curve())
    print(ev.trials_to_convergence(epsilon=0.01))
    print(ev.beats_random(confidence=0.95))
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from typing import Any

from omega.core.bayesian_optimizer import (
    ContinuousParam,
    DiscreteParam,
    Param,
    TreeParzenEstimator,
)
from omega.core.improvement_engine import SyntheticEvaluator

logger = logging.getLogger("omega.eval.tpe_eval")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TrialRecord:
    """Single trial outcome."""

    trial_index: int
    params: dict[str, Any]
    score: float
    best_so_far: float
    method: str  # "tpe" or "random"


@dataclass
class TPEEvalReport:
    """Full TPE evaluation report."""

    n_trials: int
    tpe_trials: list[TrialRecord]
    random_trials: list[TrialRecord]
    tpe_best_score: float
    random_best_score: float
    tpe_beats_random: bool
    p_value: float  # approximate one-sided p-value

    def __str__(self) -> str:
        return (
            f"TPEEvalReport(\n"
            f"  n_trials={self.n_trials}\n"
            f"  tpe_best={self.tpe_best_score:.6f}, "
            f"random_best={self.random_best_score:.6f}\n"
            f"  tpe_beats_random={self.tpe_beats_random}, "
            f"p_value={self.p_value:.4f}\n"
            f")"
        )


# ---------------------------------------------------------------------------
# TPEEvaluator
# ---------------------------------------------------------------------------


class TPEEvaluator:
    """
    Evaluate TPE convergence vs random search.

    Parameters
    ----------
    n_trials         : Number of trials for each method.
    param_space      : List of Param definitions (uses default if None).
    target_params    : Optimal parameter values (used by SyntheticEvaluator).
    noise            : Noise level injected by SyntheticEvaluator.
    n_startup_trials : TPE warm-up trials before switching to EI-guided search.
    seed             : RNG seed for reproducibility.
    """

    def __init__(
        self,
        n_trials: int = 100,
        param_space: list[Param] | None = None,
        target_params: dict[str, float] | None = None,
        noise: float = 0.05,
        n_startup_trials: int = 10,
        seed: int = 42,
    ) -> None:
        self._n_trials = n_trials
        self._noise = noise
        self._n_startup = n_startup_trials
        self._seed = seed

        self._param_space: list[Param] = param_space or [
            ContinuousParam("lr", 1e-5, 1e-1, log_scale=True),
            ContinuousParam("momentum", 0.5, 0.99),
            DiscreteParam("batch_size", 16, 512),
        ]
        self._target_params = target_params or {"lr": 1e-3, "momentum": 0.9, "batch_size": 64}

        self._tpe_trials: list[TrialRecord] = []
        self._random_trials: list[TrialRecord] = []
        self._ran = False

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> TPEEvalReport:
        """Run both TPE and random search, populate internal trial history."""
        self._tpe_trials = self._run_tpe()
        self._random_trials = self._run_random()
        self._ran = True

        tpe_best = max(t.score for t in self._tpe_trials) if self._tpe_trials else -math.inf
        rand_best = max(t.score for t in self._random_trials) if self._random_trials else -math.inf

        beats, p_val = self._statistical_test(self._tpe_trials, self._random_trials)

        report = TPEEvalReport(
            n_trials=self._n_trials,
            tpe_trials=self._tpe_trials,
            random_trials=self._random_trials,
            tpe_best_score=round(tpe_best, 8),
            random_best_score=round(rand_best, 8),
            tpe_beats_random=beats,
            p_value=round(p_val, 6),
        )
        logger.info(
            "TPEEvaluator: tpe_best=%.6f random_best=%.6f beats_random=%s p=%.4f",
            tpe_best,
            rand_best,
            beats,
            p_val,
        )
        return report

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def convergence_curve(self) -> list[float]:
        """
        Return the best score seen at each TPE trial (monotonically non-decreasing).
        """
        self._assert_ran()
        return [t.best_so_far for t in self._tpe_trials]

    def random_convergence_curve(self) -> list[float]:
        """Best score seen at each random-search trial."""
        self._assert_ran()
        return [t.best_so_far for t in self._random_trials]

    def regret_curve(self) -> list[float]:
        """
        Cumulative regret vs oracle (best achievable score).

        regret[i] = oracle_score - best_tpe_score_at_trial_i

        The oracle score is estimated as the maximum TPE score observed
        (upper bound on what is achievable within the param space given
        the synthetic evaluator).
        """
        self._assert_ran()
        if not self._tpe_trials:
            return []
        oracle = max(t.score for t in self._tpe_trials)
        cumulative_regret = 0.0
        curve = []
        for t in self._tpe_trials:
            regret_i = oracle - t.best_so_far
            cumulative_regret += regret_i
            curve.append(cumulative_regret)
        return curve

    def trials_to_convergence(self, epsilon: float = 0.01) -> int:
        """
        Return the trial index at which improvement per trial drops below epsilon.

        "Convergence" = the moving improvement rate over a window of 5 trials
        is less than epsilon.

        Returns n_trials if convergence is never reached.
        """
        self._assert_ran()
        curve = self.convergence_curve()
        if len(curve) < 2:
            return self._n_trials

        window = 5
        for i in range(window, len(curve)):
            recent_improvement = curve[i] - curve[i - window]
            if abs(recent_improvement) < epsilon:
                return i

        return self._n_trials

    def beats_random(self, confidence: float = 0.95) -> bool:
        """
        Return True if TPE beats random search at the given confidence level.

        Uses a simple one-sided t-test approximation (no scipy dependency).
        """
        self._assert_ran()
        _, p_val = self._statistical_test(self._tpe_trials, self._random_trials)
        return p_val < (1 - confidence)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_tpe(self) -> list[TrialRecord]:
        evaluator = SyntheticEvaluator(
            target_params=self._target_params,
            noise=self._noise,
            seed=self._seed,
        )
        tpe = TreeParzenEstimator(
            param_space=self._param_space,
            n_startup_trials=self._n_startup,
            seed=self._seed,
        )

        trials: list[TrialRecord] = []
        best_so_far = -math.inf

        for i in range(self._n_trials):
            params = tpe.suggest()
            score, _ = evaluator.evaluate("tpe_node", params)
            tpe.observe(params, score)

            if score > best_so_far:
                best_so_far = score

            trials.append(
                TrialRecord(
                    trial_index=i,
                    params=params,
                    score=score,
                    best_so_far=best_so_far,
                    method="tpe",
                )
            )

        return trials

    def _run_random(self) -> list[TrialRecord]:
        evaluator = SyntheticEvaluator(
            target_params=self._target_params,
            noise=self._noise,
            seed=self._seed + 999,  # different seed for fair comparison
        )
        rng = random.Random(self._seed + 999)

        trials: list[TrialRecord] = []
        best_so_far = -math.inf

        for i in range(self._n_trials):
            params = self._random_sample(rng)
            score, _ = evaluator.evaluate("random_node", params)

            if score > best_so_far:
                best_so_far = score

            trials.append(
                TrialRecord(
                    trial_index=i,
                    params=params,
                    score=score,
                    best_so_far=best_so_far,
                    method="random",
                )
            )

        return trials

    def _random_sample(self, rng: random.Random) -> dict[str, Any]:
        """Uniformly sample the parameter space."""
        return {p.name: p.sample(rng) for p in self._param_space}

    @staticmethod
    def _statistical_test(
        tpe_trials: list[TrialRecord],
        random_trials: list[TrialRecord],
    ) -> tuple[bool, float]:
        """
        One-sided Welch's t-test approximation (no scipy).

        Tests H0: mean(tpe_scores) <= mean(random_scores)
        Returns (tpe_is_better, p_value).
        """
        tpe_scores = [t.score for t in tpe_trials]
        rand_scores = [t.score for t in random_trials]

        if len(tpe_scores) < 2 or len(rand_scores) < 2:
            return False, 1.0

        mean_tpe = sum(tpe_scores) / len(tpe_scores)
        mean_rand = sum(rand_scores) / len(rand_scores)

        var_tpe = sum((x - mean_tpe) ** 2 for x in tpe_scores) / (len(tpe_scores) - 1)
        var_rand = sum((x - mean_rand) ** 2 for x in rand_scores) / (len(rand_scores) - 1)

        se = math.sqrt(var_tpe / len(tpe_scores) + var_rand / len(rand_scores))
        if se == 0:
            return mean_tpe > mean_rand, (0.0 if mean_tpe > mean_rand else 1.0)

        t_stat = (mean_tpe - mean_rand) / se

        # Approximate p-value from t-statistic using normal distribution
        # (valid for large n; fine for our evaluation purposes)
        p_val = _approx_one_sided_p(t_stat)

        return mean_tpe > mean_rand and p_val < 0.05, p_val

    def _assert_ran(self) -> None:
        if not self._ran:
            raise RuntimeError("Call run() before accessing results.")


# ---------------------------------------------------------------------------
# Normal CDF approximation (no scipy)
# ---------------------------------------------------------------------------


def _approx_one_sided_p(t: float) -> float:
    """
    Approximate one-sided p-value for a t-statistic.
    Uses Abramowitz & Stegun approximation to the normal CDF.
    Returns P(T > t) under H0.
    """
    # Approximation valid for |z| <= 7
    z = t
    # P(Z > z) where Z ~ N(0,1)
    if z < 0:
        return 1.0 - _approx_one_sided_p(-z)
    # Rational approximation
    b1 = 0.319381530
    b2 = -0.356563782
    b3 = 1.781477937
    b4 = -1.821255978
    b5 = 1.330274429
    p = 0.2316419
    t_val = 1.0 / (1.0 + p * z)
    poly = t_val * (b1 + t_val * (b2 + t_val * (b3 + t_val * (b4 + t_val * b5))))
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    return pdf * poly
