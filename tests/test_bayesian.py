"""Tests for omega.math.bayesian — Bayesian signal aggregator."""

from __future__ import annotations

import math

import numpy as np
import pytest

from omega.math.bayesian import (
    aggregate_signals,
    bayesian_update,
    entropy,
    log_odds,
    log_odds_to_prob,
    posterior_summary,
)

# ---------------------------------------------------------------------------
# log_odds / log_odds_to_prob
# ---------------------------------------------------------------------------


class TestLogOdds:
    def test_half_probability_zero_log_odds(self):
        assert log_odds(0.5) == pytest.approx(0.0)

    def test_log_odds_positive_for_p_above_half(self):
        assert log_odds(0.9) > 0

    def test_log_odds_negative_for_p_below_half(self):
        assert log_odds(0.1) < 0

    def test_symmetry(self):
        """log_odds(p) == -log_odds(1-p)."""
        assert log_odds(0.3) == pytest.approx(-log_odds(0.7))

    def test_known_value(self):
        """log_odds(0.9) = log(9) ≈ 2.1972."""
        assert log_odds(0.9) == pytest.approx(math.log(9.0))

    def test_clamps_at_zero(self):
        """p=0 should not raise; should return very large negative."""
        result = log_odds(0.0)
        assert result < -30

    def test_clamps_at_one(self):
        """p=1 should not raise; should return very large positive."""
        result = log_odds(1.0)
        assert result > 30

    def test_roundtrip(self):
        """log_odds_to_prob(log_odds(p)) ≈ p."""
        for p in [0.1, 0.3, 0.5, 0.7, 0.9]:
            assert log_odds_to_prob(log_odds(p)) == pytest.approx(p, rel=1e-6)


class TestLogOddsToProb:
    def test_zero_log_odds_is_half(self):
        assert log_odds_to_prob(0.0) == pytest.approx(0.5)

    def test_positive_log_odds_above_half(self):
        assert log_odds_to_prob(2.0) > 0.5

    def test_negative_log_odds_below_half(self):
        assert log_odds_to_prob(-2.0) < 0.5

    def test_extreme_positive_clamps(self):
        result = log_odds_to_prob(1000.0)
        assert 0 < result <= 1.0

    def test_extreme_negative_clamps(self):
        result = log_odds_to_prob(-1000.0)
        assert 0 <= result < 1.0

    def test_symmetry(self):
        """log_odds_to_prob(lo) + log_odds_to_prob(-lo) == 1."""
        for lo in [0.5, 1.0, 2.5]:
            assert log_odds_to_prob(lo) + log_odds_to_prob(-lo) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# bayesian_update
# ---------------------------------------------------------------------------


class TestBayesianUpdate:
    def test_uninformative_lr_no_change(self):
        """LR = 1.0 should leave prior unchanged."""
        prior = 0.7
        result = bayesian_update(prior, [1.0, 1.0, 1.0])
        assert result == pytest.approx(prior, rel=1e-6)

    def test_strong_confirming_evidence(self):
        """High LR values should push posterior toward 1."""
        result = bayesian_update(0.5, [10.0, 10.0])
        assert result > 0.95

    def test_strong_disconfirming_evidence(self):
        """Low LR values (< 1) should push posterior toward 0."""
        result = bayesian_update(0.5, [0.1, 0.1])
        assert result < 0.05

    def test_empty_evidence_returns_prior(self):
        assert bayesian_update(0.3, []) == pytest.approx(0.3, rel=1e-6)

    def test_known_manual_calculation(self):
        """Prior=0.5, LR=3: posterior = 3/(3+1) = 0.75."""
        result = bayesian_update(0.5, [3.0])
        assert result == pytest.approx(0.75, rel=1e-4)

    def test_sequential_update_commutative(self):
        """Order of independent evidence should not matter."""
        r1 = bayesian_update(0.4, [2.0, 3.0])
        r2 = bayesian_update(0.4, [3.0, 2.0])
        assert r1 == pytest.approx(r2)

    def test_zero_lr_raises(self):
        with pytest.raises(ValueError, match="likelihood ratios must be > 0"):
            bayesian_update(0.5, [0.0])

    def test_negative_lr_raises(self):
        with pytest.raises(ValueError, match="likelihood ratios must be > 0"):
            bayesian_update(0.5, [-1.0])

    def test_result_in_unit_interval(self):
        """Posterior must always be in (0, 1)."""
        for lr in [0.001, 0.1, 1.0, 10.0, 1000.0]:
            result = bayesian_update(0.5, [lr])
            assert 0 < result < 1


# ---------------------------------------------------------------------------
# aggregate_signals
# ---------------------------------------------------------------------------


class TestAggregateSignals:
    def test_equal_weights_returns_weighted_mean(self):
        """With equal Brier scores, result should reflect signal average."""
        signals = [0.7, 0.8]
        bs = [0.05, 0.05]
        result = aggregate_signals(signals, bs, prior=0.5)
        # Consensus = 0.75, then Bayesian update from 0.5
        assert result > 0.5

    def test_better_calibrated_source_dominates(self):
        """Lower BS (better) signal should dominate higher BS signal."""
        # Signal A says 0.9 with BS=0.01 (excellent); B says 0.2 with BS=0.4 (poor)
        result_a_dominant = aggregate_signals([0.9, 0.2], [0.01, 0.4], prior=0.5)
        # Signal B says 0.9 with BS=0.4 (poor); A says 0.2 with BS=0.01 (excellent)
        result_b_dominant = aggregate_signals([0.2, 0.9], [0.01, 0.4], prior=0.5)
        # When the excellent model says 0.2 (index 0 in second case), posterior should be lower
        assert result_b_dominant < result_a_dominant

    def test_empty_signals_returns_prior(self):
        assert aggregate_signals([], [], prior=0.6) == pytest.approx(0.6, rel=1e-4)

    def test_prior_influence(self):
        """Weak signals should leave prior partially intact."""
        low_info = aggregate_signals([0.52], [0.249], prior=0.3)
        high_info = aggregate_signals([0.9], [0.01], prior=0.3)
        # Strong signal should pull further from prior
        assert abs(high_info - 0.3) > abs(low_info - 0.3)

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="same length"):
            aggregate_signals([0.5, 0.6], [0.1])

    def test_zero_brier_score_raises(self):
        with pytest.raises(ValueError, match="Brier scores must be > 0"):
            aggregate_signals([0.5], [0.0])

    def test_negative_brier_score_raises(self):
        with pytest.raises(ValueError, match="Brier scores must be > 0"):
            aggregate_signals([0.5], [-0.1])

    def test_signal_at_boundary_raises(self):
        with pytest.raises(ValueError, match="signals must be in"):
            aggregate_signals([0.0], [0.1])

    def test_signal_at_one_raises(self):
        with pytest.raises(ValueError, match="signals must be in"):
            aggregate_signals([1.0], [0.1])

    def test_result_in_unit_interval(self):
        """Posterior must always be in (0, 1)."""
        for s in [0.1, 0.3, 0.5, 0.7, 0.9]:
            result = aggregate_signals([s], [0.1], prior=0.5)
            assert 0 < result < 1


# ---------------------------------------------------------------------------
# entropy
# ---------------------------------------------------------------------------


class TestEntropy:
    def test_half_probability_max_entropy(self):
        assert entropy(0.5) == pytest.approx(1.0)

    def test_certainty_zero_entropy(self):
        assert entropy(0.0) == pytest.approx(0.0)
        assert entropy(1.0) == pytest.approx(0.0)

    def test_symmetry(self):
        """H(p) == H(1-p)."""
        assert entropy(0.3) == pytest.approx(entropy(0.7))

    def test_monotone_toward_half(self):
        """Entropy increases as p approaches 0.5 from 0."""
        assert entropy(0.1) < entropy(0.3) < entropy(0.49) < entropy(0.5)

    def test_known_value(self):
        """H(0.25) = -(0.25*log2(0.25) + 0.75*log2(0.75))."""
        expected = -(0.25 * math.log2(0.25) + 0.75 * math.log2(0.75))
        assert entropy(0.25) == pytest.approx(expected)

    def test_output_in_zero_one(self):
        for p in np.linspace(0.01, 0.99, 20):
            assert 0 <= entropy(float(p)) <= 1.0


# ---------------------------------------------------------------------------
# posterior_summary
# ---------------------------------------------------------------------------


class TestPosteriorSummary:
    def test_keys_present(self):
        result = posterior_summary(0.5, [2.0, 3.0])
        assert set(result.keys()) == {"posterior", "log_odds", "entropy", "n_signals"}

    def test_n_signals_count(self):
        result = posterior_summary(0.5, [2.0, 3.0, 1.5])
        assert result["n_signals"] == 3

    def test_log_odds_consistent_with_posterior(self):
        """log_odds field should match log_odds(posterior)."""
        result = posterior_summary(0.5, [2.0, 3.0])
        expected_lo = log_odds(result["posterior"])
        assert result["log_odds"] == pytest.approx(expected_lo, rel=1e-6)

    def test_entropy_consistent_with_posterior(self):
        """entropy field should match entropy(posterior)."""
        result = posterior_summary(0.5, [2.0, 3.0])
        from omega.math.bayesian import entropy as ent

        assert result["entropy"] == pytest.approx(ent(result["posterior"]), rel=1e-6)

    def test_uses_bayesian_update_without_brier(self):
        """Without brier_scores, evidence_list should be treated as LRs."""
        result = posterior_summary(0.5, [3.0])
        expected = bayesian_update(0.5, [3.0])
        assert result["posterior"] == pytest.approx(expected)

    def test_uses_aggregate_signals_with_brier(self):
        """With brier_scores, should route through aggregate_signals."""
        result = posterior_summary(0.5, [0.7, 0.8], brier_scores=[0.05, 0.02])
        expected = aggregate_signals([0.7, 0.8], [0.05, 0.02], prior=0.5)
        assert result["posterior"] == pytest.approx(expected)

    def test_empty_evidence_with_lr_mode(self):
        result = posterior_summary(0.4, [])
        assert result["posterior"] == pytest.approx(0.4, rel=1e-4)

    def test_certain_outcome_low_entropy(self):
        """Strong evidence should yield low entropy in summary."""
        result = posterior_summary(0.5, [100.0, 100.0, 100.0])
        assert result["entropy"] < 0.1

    def test_uncertain_outcome_high_entropy(self):
        """Weak / mixed evidence should yield high entropy."""
        result = posterior_summary(0.5, [1.0])
        assert result["entropy"] == pytest.approx(1.0, abs=0.01)
