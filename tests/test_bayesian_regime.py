"""tests/test_bayesian_regime.py
Unit tests for the V147 BayesianRegimeDetector.
"""
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import pytest

from omega.nodes.victoria.bayesian_regime import (
    REGIMES,
    BayesianRegimeDetector,
    RegimePosterior,
    RegimePrior,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_detector(tmp_path: Path) -> BayesianRegimeDetector:
    return BayesianRegimeDetector(state_file=tmp_path / "bayesian_regime_state.json")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_uniform_prior_gives_equal_posteriors(tmp_path: Path) -> None:
    """With no likelihood updates, an empty signal dict → near-uniform posterior."""
    detector = _make_detector(tmp_path)
    posterior = detector.compute_posterior({})

    for regime in REGIMES:
        assert abs(posterior.probs[regime] - 0.25) < 1e-9, (
            f"Expected ~0.25 for {regime}, got {posterior.probs[regime]}"
        )


def test_update_shifts_distribution(tmp_path: Path) -> None:
    """After crisis updates with high signal values, crisis log-likelihood increases."""
    detector = _make_detector(tmp_path)
    signal_values = {
        "momentum_signal": 0.9,
        "rsi_signal": 0.85,
        "macd_signal": 0.8,
    }

    # Provide 10 crisis observations with consistently high signals
    for _ in range(10):
        detector.update_likelihood("crisis", signal_values)

    # With non-zero signal values in the crisis cluster, crisis should now have
    # higher log-likelihood than the other regimes for these inputs.
    crisis_ll = detector._likelihood.log_likelihood("crisis", signal_values)
    normal_ll = detector._likelihood.log_likelihood("normal", signal_values)
    high_vol_ll = detector._likelihood.log_likelihood("high_vol", signal_values)

    # crisis has 10 observations and should fit better than uninformative prior regimes
    assert crisis_ll > normal_ll, f"Crisis LL {crisis_ll:.4f} should beat normal LL {normal_ll:.4f}"
    assert crisis_ll > high_vol_ll, f"Crisis LL {crisis_ll:.4f} should beat high_vol LL {high_vol_ll:.4f}"


def test_long_affinity_positive_in_trending(tmp_path: Path) -> None:
    """When trending=0.8, long_affinity > 0."""
    posterior = RegimePosterior(
        probs={"crisis": 0.05, "high_vol": 0.05, "normal": 0.10, "trending": 0.80}
    )
    assert posterior.long_affinity() > 0, (
        f"Expected positive long_affinity, got {posterior.long_affinity()}"
    )
    # trending(0.8) + normal(0.10) - crisis(0.05) = 0.85
    assert abs(posterior.long_affinity() - 0.85) < 1e-9


def test_short_affinity_positive_in_crisis(tmp_path: Path) -> None:
    """When crisis=0.8, short_affinity > 0."""
    posterior = RegimePosterior(
        probs={"crisis": 0.80, "high_vol": 0.10, "normal": 0.05, "trending": 0.05}
    )
    assert posterior.short_affinity() > 0, (
        f"Expected positive short_affinity, got {posterior.short_affinity()}"
    )
    # crisis(0.8) + high_vol(0.10) - trending(0.05) = 0.85
    assert abs(posterior.short_affinity() - 0.85) < 1e-9


def test_state_persistence(tmp_path: Path) -> None:
    """save_state() / _load_state() preserves n_updates and likelihood stats."""
    detector = _make_detector(tmp_path)

    # Run 5 crisis updates
    sig = {"momentum_signal": 0.7, "rsi_signal": 0.6}
    for _ in range(5):
        detector.update_likelihood("crisis", sig)

    assert detector._n_updates == 5
    detector.save_state()

    # Load a fresh instance from the same file
    detector2 = _make_detector(tmp_path)
    assert detector2._n_updates == 5

    # Likelihood stats for crisis/momentum_signal should be restored
    orig_stats = detector._likelihood._stats["crisis"]["momentum_signal"]
    restored_stats = detector2._likelihood._stats["crisis"]["momentum_signal"]
    assert orig_stats[0] == restored_stats[0], "n mismatch"
    assert abs(orig_stats[1] - restored_stats[1]) < 1e-9, "mean mismatch"
    assert abs(orig_stats[2] - restored_stats[2]) < 1e-9, "M2 mismatch"


def test_dominant_property(tmp_path: Path) -> None:
    """RegimePosterior.dominant returns the highest-probability regime."""
    posterior = RegimePosterior(
        probs={"crisis": 0.1, "high_vol": 0.2, "normal": 0.3, "trending": 0.4}
    )
    name, prob = posterior.dominant
    assert name == "trending"
    assert abs(prob - 0.4) < 1e-9


def test_prior_from_llm_peaks_correctly(tmp_path: Path) -> None:
    """from_llm_assessment sets a peaked prior and normalises."""
    prior = RegimePrior()
    prior.from_llm_assessment("crisis", confidence=0.7)
    assert abs(prior.probs["crisis"] - 0.7) < 1e-9
    remaining = (1.0 - 0.7) / 3
    for r in ("high_vol", "normal", "trending"):
        assert abs(prior.probs[r] - remaining) < 1e-9
    assert abs(sum(prior.probs.values()) - 1.0) < 1e-9


def test_compute_posterior_with_llm_prior(tmp_path: Path) -> None:
    """Custom peaked prior shifts posterior toward the signalled regime."""
    detector = _make_detector(tmp_path)

    crisis_prior = RegimePrior()
    crisis_prior.from_llm_assessment("crisis", confidence=0.9)

    posterior = detector.compute_posterior({}, prior=crisis_prior)
    # With no likelihood data all regimes have equal LL → prior dominates
    name, prob = posterior.dominant
    assert name == "crisis"
    assert prob > 0.7
