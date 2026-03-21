"""Tests for omega.core.bayesian_optimizer — TPE implementation."""

from __future__ import annotations

import itertools
import statistics

import pytest

from omega.core.bayesian_optimizer import (
    CategoricalParam,
    ContinuousParam,
    DiscreteParam,
    TreeParzenEstimator,
    _kde_categorical,
    _log_kde_continuous,
    _silverman_bandwidth,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_space():
    return [
        ContinuousParam("lr", low=1e-5, high=1e-1),
        DiscreteParam("depth", low=1, high=10),
        CategoricalParam("optimizer", choices=["adam", "sgd", "rmsprop"]),
    ]


# ---------------------------------------------------------------------------
# Unit: parameter types
# ---------------------------------------------------------------------------


class TestParamTypes:
    def test_continuous_sample_in_range(self):
        import random

        p = ContinuousParam("x", low=0.0, high=1.0)
        rng = random.Random(42)
        for _ in range(100):
            v = p.sample(rng)
            assert 0.0 <= v <= 1.0

    def test_continuous_log_scale_sample(self):
        import random

        p = ContinuousParam("lr", low=1e-5, high=1.0, log_scale=True)
        rng = random.Random(7)
        samples = [p.sample(rng) for _ in range(200)]
        # Median should be below arithmetic midpoint (log-uniform)
        assert statistics.median(samples) < 0.5

    def test_continuous_clip(self):
        p = ContinuousParam("x", low=0.0, high=1.0)
        assert p.clip(1.5) == 1.0
        assert p.clip(-0.5) == 0.0
        assert p.clip(0.5) == pytest.approx(0.5)

    def test_discrete_sample_in_range(self):
        import random

        p = DiscreteParam("n", low=1, high=5)
        rng = random.Random(0)
        values = {p.sample(rng) for _ in range(200)}
        assert values == {1, 2, 3, 4, 5}

    def test_discrete_clip(self):
        p = DiscreteParam("n", low=1, high=5)
        assert p.clip(0) == 1
        assert p.clip(6) == 5
        assert p.clip(3.7) == 4

    def test_categorical_sample_within_choices(self):
        import random

        p = CategoricalParam("mode", choices=["a", "b", "c"])
        rng = random.Random(0)
        for _ in range(50):
            assert p.sample(rng) in ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Unit: KDE helpers
# ---------------------------------------------------------------------------


class TestKDEHelpers:
    def test_silverman_bandwidth_positive(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        bw = _silverman_bandwidth(data)
        assert bw > 0

    def test_silverman_bandwidth_single_point(self):
        bw = _silverman_bandwidth([1.0])
        assert bw == 1.0

    def test_silverman_bandwidth_zero_std(self):
        bw = _silverman_bandwidth([3.0, 3.0, 3.0])
        assert bw > 0  # should not be 0

    def test_log_kde_higher_density_near_cluster(self):
        data = [0.0, 0.1, -0.1, 0.05, -0.05]
        bw = _silverman_bandwidth(data)
        log_near = _log_kde_continuous(0.0, data, bw)
        log_far = _log_kde_continuous(10.0, data, bw)
        assert log_near > log_far

    def test_kde_categorical_sums_near_one(self):
        choices = ["a", "b", "c"]
        data = ["a", "a", "b", "c"]
        total = sum(_kde_categorical(c, data, choices) for c in choices)
        assert total == pytest.approx(1.0, abs=1e-6)

    def test_kde_categorical_unseen_nonzero(self):
        choices = ["a", "b", "c"]
        data = ["a", "a"]
        # "c" was never observed but prior_weight should give non-zero prob
        assert _kde_categorical("c", data, choices) > 0


# ---------------------------------------------------------------------------
# TreeParzenEstimator: startup behaviour
# ---------------------------------------------------------------------------


class TestTPEStartup:
    def test_suggest_returns_valid_keys(self):
        tpe = TreeParzenEstimator(_simple_space(), seed=0)
        for _ in range(5):
            s = tpe.suggest()
            assert set(s.keys()) == {"lr", "depth", "optimizer"}

    def test_suggest_types_correct(self):
        tpe = TreeParzenEstimator(_simple_space(), seed=1)
        for _ in range(15):
            s = tpe.suggest()
            assert isinstance(s["lr"], float)
            assert isinstance(s["depth"], int)
            assert s["optimizer"] in ["adam", "sgd", "rmsprop"]

    def test_n_trials_increments(self):
        tpe = TreeParzenEstimator(_simple_space(), seed=2)
        assert tpe.n_trials() == 0
        for i in range(5):
            p = tpe.suggest()
            tpe.observe(p, float(i))
        assert tpe.n_trials() == 5

    def test_best_params_initially_none(self):
        tpe = TreeParzenEstimator(_simple_space(), seed=3)
        assert tpe.best_params() is None
        assert tpe.best_score() is None


# ---------------------------------------------------------------------------
# TreeParzenEstimator: learning behaviour
# ---------------------------------------------------------------------------


class TestTPELearning:
    def _run_tpe_on_bowl(self, n_trials: int = 60) -> float:
        """
        Optimise a simple quadratic: score = -(x-0.3)^2 + noise
        Return best x found by TPE.
        """
        import random

        space: list[ContinuousParam | DiscreteParam | CategoricalParam] = [
            ContinuousParam("x", low=0.0, high=1.0)
        ]
        tpe = TreeParzenEstimator(space, n_startup_trials=5, seed=42)
        rng = random.Random(99)

        for _ in range(n_trials):
            p = tpe.suggest()
            x = p["x"]
            score = -((x - 0.3) ** 2) + rng.gauss(0, 0.01)
            tpe.observe(p, score)

        best = tpe.best_params()
        assert best is not None
        return float(best["x"])

    def test_tpe_converges_toward_optimum(self):
        best_x = self._run_tpe_on_bowl(n_trials=80)
        # Should land within 0.15 of the true optimum 0.3
        assert abs(best_x - 0.3) < 0.15, f"TPE converged to {best_x}, expected ~0.3"

    def test_best_score_improves_with_more_trials(self):
        space = [ContinuousParam("x", low=0.0, high=1.0)]
        tpe = TreeParzenEstimator(space, n_startup_trials=5, seed=11)
        scores = []
        for _i in range(50):
            p = tpe.suggest()
            x = p["x"]
            score = -((x - 0.5) ** 2)
            tpe.observe(p, score)
            scores.append(tpe.best_score())

        # Best score should be monotonically non-decreasing
        for a, b in itertools.pairwise(scores):
            assert b >= a - 1e-10

    def test_ei_higher_near_good_region(self):
        space = [ContinuousParam("x", low=0.0, high=1.0)]
        tpe = TreeParzenEstimator(space, n_startup_trials=3, seed=5)

        # Observe: x≈0.9 is always good, x≈0.1 is always bad
        for _ in range(20):
            tpe.observe({"x": 0.9 + 0.01 * _ % 3}, 1.0)
        for _ in range(20):
            tpe.observe({"x": 0.1 + 0.01 * _ % 3}, -1.0)

        ei_good = tpe.expected_improvement({"x": 0.9})
        ei_bad = tpe.expected_improvement({"x": 0.1})
        assert ei_good > ei_bad

    def test_fit_replaces_history(self):
        space = [ContinuousParam("x", low=0.0, high=1.0)]
        tpe = TreeParzenEstimator(space, seed=0)
        tpe.observe({"x": 0.5}, 1.0)
        assert tpe.n_trials() == 1
        tpe.fit([])
        assert tpe.n_trials() == 0

    def test_fit_warm_start(self):
        space = [ContinuousParam("x", low=0.0, high=1.0)]
        # scores: 0.0, 1.0, ... 14.0  — max is 14.0
        trials = [({"x": float(i) / 10}, float(i)) for i in range(15)]
        tpe = TreeParzenEstimator(space, n_startup_trials=5, seed=0)
        tpe.fit(trials)
        assert tpe.n_trials() == 15
        assert tpe.best_score() == pytest.approx(14.0)


# ---------------------------------------------------------------------------
# TreeParzenEstimator: edge cases
# ---------------------------------------------------------------------------


class TestTPEEdgeCases:
    def test_single_param_categorical(self):
        space = [CategoricalParam("mode", choices=["a", "b", "c"])]
        tpe = TreeParzenEstimator(space, n_startup_trials=3, seed=0)
        for _ in range(30):
            p = tpe.suggest()
            tpe.observe(p, 1.0 if p["mode"] == "a" else -1.0)
        # After sufficient trials, "a" should dominate suggestions
        suggestions = [tpe.suggest()["mode"] for _ in range(50)]
        assert suggestions.count("a") > suggestions.count("b")

    def test_discrete_stays_in_bounds(self):
        space = [DiscreteParam("k", low=2, high=8)]
        tpe = TreeParzenEstimator(space, n_startup_trials=3, seed=0)
        for _i in range(60):
            p = tpe.suggest()
            assert 2 <= p["k"] <= 8
            tpe.observe(p, float(p["k"]))  # higher k is better

    def test_mixed_space_no_crash(self):
        space = [
            ContinuousParam("alpha", low=0.0, high=1.0),
            DiscreteParam("layers", low=1, high=5),
            CategoricalParam("act", choices=["relu", "tanh"]),
        ]
        tpe = TreeParzenEstimator(space, seed=0)
        for i in range(40):
            p = tpe.suggest()
            tpe.observe(p, float(i % 5))

    def test_all_same_score(self):
        """TPE should not crash when all scores are equal."""
        space = [ContinuousParam("x", low=0.0, high=1.0)]
        tpe = TreeParzenEstimator(space, seed=0)
        for _ in range(20):
            p = tpe.suggest()
            tpe.observe(p, 0.5)
        # Should still return a valid suggestion
        p = tpe.suggest()
        assert 0.0 <= p["x"] <= 1.0
