"""omega.core.bayesian_optimizer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pure Python TPE (Tree-structured Parzen Estimator) implementation.

TPE splits observed trials into "good" and "bad" sets based on a quantile
threshold, fits kernel density estimates (KDE) over each set, then suggests
the next parameters by maximising l(x)/g(x): the ratio of the good KDE to
the bad KDE — a well-known proxy for Expected Improvement.

No external dependencies: stdlib only (math, random, statistics).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Parameter space definitions
# ---------------------------------------------------------------------------


class ParamType(Enum):
    CONTINUOUS = "continuous"
    DISCRETE = "discrete"
    CATEGORICAL = "categorical"


@dataclass
class ContinuousParam:
    name: str
    low: float
    high: float
    log_scale: bool = False
    param_type: ParamType = field(default=ParamType.CONTINUOUS, init=False)

    def sample(self, rng: random.Random) -> float:
        if self.log_scale:
            return math.exp(rng.uniform(math.log(self.low), math.log(self.high)))
        return rng.uniform(self.low, self.high)

    def clip(self, value: float) -> float:
        return max(self.low, min(self.high, float(value)))


@dataclass
class DiscreteParam:
    name: str
    low: int
    high: int  # inclusive
    param_type: ParamType = field(default=ParamType.DISCRETE, init=False)

    def sample(self, rng: random.Random) -> int:
        return rng.randint(self.low, self.high)

    def clip(self, value: float) -> int:
        return max(self.low, min(self.high, round(value)))


@dataclass
class CategoricalParam:
    name: str
    choices: list[Any]
    param_type: ParamType = field(default=ParamType.CATEGORICAL, init=False)

    def sample(self, rng: random.Random) -> Any:
        return rng.choice(self.choices)


Param = ContinuousParam | DiscreteParam | CategoricalParam


# ---------------------------------------------------------------------------
# Math utilities (stdlib only)
# ---------------------------------------------------------------------------


def _mean(data: list[float]) -> float:
    return sum(data) / len(data) if data else 0.0


def _std(data: list[float]) -> float:
    if len(data) < 2:
        return 1.0
    m = _mean(data)
    var = sum((x - m) ** 2 for x in data) / (len(data) - 1)
    return math.sqrt(var) if var > 0 else 1.0


def _silverman_bandwidth(data: list[float]) -> float:
    """Silverman's rule-of-thumb bandwidth for 1-D Gaussian KDE."""
    n = len(data)
    if n < 2:
        return 1.0
    std = _std(data)
    return float(1.06 * std * (n**-0.2))


def _log_normal_pdf(x: float, mu: float, sigma: float) -> float:
    """Log of Gaussian PDF N(x; mu, sigma)."""
    return -0.5 * ((x - mu) / sigma) ** 2 - math.log(sigma * math.sqrt(2 * math.pi))


def _log_kde_continuous(x: float, data: list[float], bw: float) -> float:
    """Log-density of a Gaussian KDE at point x given bandwidth bw."""
    if not data:
        return -math.inf
    # log-sum-exp for numerical stability
    log_probs = [_log_normal_pdf(x, xi, bw) for xi in data]
    max_lp = max(log_probs)
    lse = max_lp + math.log(sum(math.exp(lp - max_lp) for lp in log_probs))
    return lse - math.log(len(data))


def _kde_categorical(
    x: Any, data: list[Any], choices: list[Any], prior_weight: float = 1.0
) -> float:
    """Smoothed categorical probability via pseudo-count prior."""
    counts: dict[Any, float] = {c: prior_weight for c in choices}
    for d in data:
        if d in counts:
            counts[d] += 1.0
    total = sum(counts.values())
    return counts.get(x, prior_weight) / total


# ---------------------------------------------------------------------------
# TreeParzenEstimator
# ---------------------------------------------------------------------------


class TreeParzenEstimator:
    """
    TPE implementation for hyperparameter optimisation.

    Parameters
    ----------
    param_space:
        List of Param definitions that describe the search space.
    gamma:
        Quantile threshold splitting good/bad trials (default 0.25 → top 25%).
    n_startup_trials:
        Number of random trials before TPE kicks in.
    seed:
        Optional random seed for reproducibility.
    """

    def __init__(
        self,
        param_space: list[Param],
        gamma: float = 0.25,
        n_startup_trials: int = 10,
        seed: int | None = None,
    ) -> None:
        self.param_space = {p.name: p for p in param_space}
        self.gamma = gamma
        self.n_startup_trials = n_startup_trials
        self._rng = random.Random(seed)

        # Observations: list of (params_dict, score)
        self._trials: list[tuple[dict[str, Any], float]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(self, trials: list[tuple[dict[str, Any], float]]) -> None:
        """Replace internal observation history with the given trials."""
        self._trials = list(trials)

    def observe(self, params: dict[str, Any], score: float) -> None:
        """Record the outcome of a trial. Higher score = better."""
        self._trials.append((params, score))

    def suggest(self) -> dict[str, Any]:
        """
        Suggest the next parameter configuration.

        Falls back to random sampling when fewer than n_startup_trials have
        been observed.
        """
        if len(self._trials) < self.n_startup_trials:
            return self._random_sample()

        good, bad = self._split_trials()
        return {
            name: self._suggest_param(name, param, good, bad)
            for name, param in self.param_space.items()
        }

    def expected_improvement(self, params: dict[str, Any]) -> float:
        """
        l(x)/g(x) ratio as EI proxy; higher is better.
        Returns 0 when insufficient data.
        """
        if len(self._trials) < self.n_startup_trials:
            return 0.0

        good, bad = self._split_trials()
        log_ratio = 0.0

        for name, param in self.param_space.items():
            x = params.get(name)
            if x is None:
                continue
            log_l = self._log_density(x, name, param, [t[name] for t in good if name in t])
            log_g_vals = [t[name] for t in bad if name in t]
            log_g = self._log_density(x, name, param, log_g_vals) if log_g_vals else 0.0
            log_ratio += log_l - log_g

        return math.exp(min(log_ratio, 700))

    def best_params(self) -> dict[str, Any] | None:
        if not self._trials:
            return None
        return max(self._trials, key=lambda t: t[1])[0]

    def best_score(self) -> float | None:
        if not self._trials:
            return None
        return max(t[1] for t in self._trials)

    def n_trials(self) -> int:
        return len(self._trials)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _random_sample(self) -> dict[str, Any]:
        return {name: p.sample(self._rng) for name, p in self.param_space.items()}

    def _split_trials(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        sorted_trials = sorted(self._trials, key=lambda t: t[1], reverse=True)
        n_good = max(1, math.ceil(self.gamma * len(sorted_trials)))
        good = [t[0] for t in sorted_trials[:n_good]]
        bad = [t[0] for t in sorted_trials[n_good:]] or [t[0] for t in sorted_trials]
        return good, bad

    def _suggest_param(
        self,
        name: str,
        param: Param,
        good: list[dict[str, Any]],
        bad: list[dict[str, Any]],
    ) -> Any:
        n_candidates = max(24, int(math.sqrt(len(self._trials))) * 4)
        good_vals = [t[name] for t in good if name in t]
        bad_vals = [t[name] for t in bad if name in t]

        if not good_vals:
            return param.sample(self._rng)

        best_val = None
        best_ratio = -math.inf

        for _ in range(n_candidates):
            if self._rng.random() < 0.5 and good_vals:
                candidate = self._perturb(param, self._rng.choice(good_vals))
            else:
                candidate = param.sample(self._rng)

            log_l = self._log_density(candidate, name, param, good_vals)
            log_g = self._log_density(candidate, name, param, bad_vals) if bad_vals else 0.0
            ratio = log_l - log_g

            if ratio > best_ratio:
                best_ratio = ratio
                best_val = candidate

        return best_val if best_val is not None else param.sample(self._rng)

    def _perturb(self, param: Param, value: Any) -> Any:
        if isinstance(param, ContinuousParam):
            span = (param.high - param.low) * 0.15
            return param.clip(float(value) + self._rng.gauss(0, span))
        if isinstance(param, DiscreteParam):
            span = max(1, (param.high - param.low) // 6)
            return param.clip(int(value) + self._rng.randint(-span, span))
        return value  # categorical: no perturbation

    def _log_density(
        self,
        x: Any,
        name: str,
        param: Param,
        vals: list[Any],
    ) -> float:
        if not vals:
            return 0.0

        if isinstance(param, CategoricalParam):
            p = _kde_categorical(x, vals, param.choices)
            return math.log(max(p, 1e-10))

        float_vals = [float(v) for v in vals]
        bw = _silverman_bandwidth(float_vals)
        return _log_kde_continuous(float(x), float_vals, bw)
