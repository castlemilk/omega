"""omega.core.convergence
~~~~~~~~~~~~~~~~~~~~~~~~
Convergence diagnostics for the TPE optimisation loop.

All functions are pure (no side effects, no external deps) so they can be
used standalone or wired into ImprovementEngine.

API
---
ConvergenceDiagnostics
    .improvement_rate(scores, window)        → float
    .has_plateaued(scores, epsilon, window)  → bool
    .regret(scores, oracle_score)            → List[float]
    .beats_random(tpe_scores, random_scores, confidence) → Tuple[bool, float]
"""

from __future__ import annotations

import math
from collections.abc import Sequence

# ---------------------------------------------------------------------------
# Module-level functions (functional style)
# ---------------------------------------------------------------------------


def improvement_rate(scores: Sequence[float], window: int = 20) -> float:
    """
    Mean score improvement per trial over the last ``window`` trials.

    Positive → the optimiser is still improving.
    Near zero → converged or plateaued.
    Negative → scores are degrading (possible overfitting / noise).

    Returns 0.0 when fewer than 2 scores are available.
    """
    if len(scores) < 2:
        return 0.0
    window_scores = list(scores[-window:])
    if len(window_scores) < 2:
        return 0.0
    # Mean first-differences
    diffs = [window_scores[i] - window_scores[i - 1] for i in range(1, len(window_scores))]
    return sum(diffs) / len(diffs)


def has_plateaued(
    scores: Sequence[float],
    epsilon: float = 0.01,
    window: int = 20,
) -> bool:
    """
    Return True when the mean improvement per trial over the last ``window``
    trials is below ``epsilon`` in absolute value.

    Requires at least ``window`` observations before declaring convergence.
    """
    if len(scores) < window:
        return False
    rate = improvement_rate(scores, window)
    return abs(rate) < epsilon


def regret(
    scores: Sequence[float],
    oracle_score: float,
) -> list[float]:
    """
    Cumulative regret: how far below the oracle (best possible) score we are
    at each trial.

    regret[i] = sum_{t=0}^{i} (oracle - scores[t])

    A well-converging optimiser has regret growing sub-linearly.
    """
    cumulative = 0.0
    result: list[float] = []
    for s in scores:
        cumulative += oracle_score - s
        result.append(cumulative)
    return result


def beats_random(
    tpe_scores: Sequence[float],
    random_scores: Sequence[float],
    confidence: float = 0.95,
) -> tuple[bool, float]:
    """
    Test whether TPE significantly outperforms random search.

    Uses a one-sided Welch t-test (unequal variances).

    Returns
    -------
    (significant, p_value)
        significant: True when TPE mean > random mean at the given confidence.
        p_value: two-tailed p-value from the t-distribution approximation.
    """
    if len(tpe_scores) < 2 or len(random_scores) < 2:
        return False, 1.0

    n1, n2 = len(tpe_scores), len(random_scores)
    m1 = sum(tpe_scores) / n1
    m2 = sum(random_scores) / n2

    s1_sq = sum((x - m1) ** 2 for x in tpe_scores) / (n1 - 1)
    s2_sq = sum((x - m2) ** 2 for x in random_scores) / (n2 - 1)

    se_sq = s1_sq / n1 + s2_sq / n2
    if se_sq <= 0:
        # Zero variance — check means directly
        return m1 > m2, 0.0 if m1 > m2 else 1.0

    t_stat = (m1 - m2) / math.sqrt(se_sq)

    # Welch-Satterthwaite degrees of freedom
    numerator = se_sq**2
    denominator = (s1_sq / n1) ** 2 / (n1 - 1) + (s2_sq / n2) ** 2 / (n2 - 1)
    df = numerator / denominator if denominator > 0 else min(n1, n2) - 1
    df = max(df, 1.0)

    # Two-tailed p-value via incomplete beta function approximation
    p_value = _t_pvalue_two_tailed(t_stat, df)

    # One-sided: TPE mean > random mean at confidence level
    significant = (m1 > m2) and (p_value / 2 < (1.0 - confidence))
    return significant, p_value


# ---------------------------------------------------------------------------
# ConvergenceDiagnostics class (stateful wrapper)
# ---------------------------------------------------------------------------


class ConvergenceDiagnostics:
    """
    Stateful convergence tracker for an optimisation run.

    Usage::

        diag = ConvergenceDiagnostics()
        diag.record(score)
        if diag.has_converged():
            engine.stop()
    """

    def __init__(self, epsilon: float = 0.01, window: int = 20) -> None:
        self._epsilon = epsilon
        self._window = window
        self._scores: list[float] = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, score: float) -> None:
        """Append a trial score."""
        self._scores.append(score)

    def reset(self) -> None:
        """Clear all recorded scores."""
        self._scores.clear()

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def improvement_rate(self, window: int | None = None) -> float:
        return improvement_rate(self._scores, window or self._window)

    def has_converged(self, epsilon: float | None = None, window: int | None = None) -> bool:
        return has_plateaued(
            self._scores,
            epsilon=epsilon or self._epsilon,
            window=window or self._window,
        )

    def regret(self, oracle_score: float) -> list[float]:
        return regret(self._scores, oracle_score)

    def beats_random(
        self,
        random_scores: Sequence[float],
        confidence: float = 0.95,
    ) -> tuple[bool, float]:
        return beats_random(self._scores, random_scores, confidence)

    @property
    def scores(self) -> list[float]:
        return list(self._scores)

    @property
    def n_trials(self) -> int:
        return len(self._scores)

    @property
    def best_score(self) -> float:
        return max(self._scores) if self._scores else -math.inf

    @property
    def mean_score(self) -> float:
        if not self._scores:
            return 0.0
        return sum(self._scores) / len(self._scores)


# ---------------------------------------------------------------------------
# Internal stats helpers (stdlib only)
# ---------------------------------------------------------------------------


def _t_pvalue_two_tailed(t: float, df: float) -> float:
    """
    Approximate two-tailed p-value for a t-statistic with ``df`` degrees of
    freedom.

    Uses the regularised incomplete beta function approximation from Abramowitz
    & Stegun (26.7.8).  Accurate to ≈ 2 decimal places for the p-value, which
    is sufficient for convergence heuristics.
    """
    x = df / (df + t * t)
    # Regularised incomplete beta I(x; df/2, 0.5)
    p = _regularised_incomplete_beta(x, df / 2.0, 0.5)
    # Two-tailed
    return min(1.0, max(0.0, p))


def _regularised_incomplete_beta(x: float, a: float, b: float) -> float:
    """
    Regularised incomplete beta function I_x(a, b) via continued fraction.

    Uses Lentz's method (Numerical Recipes §6.4).
    """
    if x < 0.0 or x > 1.0:
        raise ValueError(f"x={x} out of [0, 1]")
    if x == 0.0:
        return 0.0
    if x == 1.0:
        return 1.0

    # Use the symmetry relation for numerical stability
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - _regularised_incomplete_beta(1.0 - x, b, a)

    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1.0 - x) * b - lbeta)

    # Continued fraction via Lentz
    cf = _betacf(x, a, b)
    return front * cf / a


def _betacf(x: float, a: float, b: float, max_iter: int = 200, tol: float = 3e-7) -> float:
    """Continued fraction for incomplete beta (Numerical Recipes)."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d

    for m in range(1, max_iter + 1):
        m2 = 2 * m
        # Even step
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        # Odd step
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < tol:
            break

    return h
