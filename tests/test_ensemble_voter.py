"""Tests for omega/nodes/victoria/ensemble_voter.py (V146)."""
from __future__ import annotations

import pytest

from omega.nodes.victoria.ensemble_voter import EnsembleResult, EnsembleVoter, Vote


@pytest.fixture()
def voter() -> EnsembleVoter:
    return EnsembleVoter(noise_threshold=0.05)


# ---------------------------------------------------------------------------
# test_all_long_votes_gives_long
# ---------------------------------------------------------------------------

def test_all_long_votes_gives_long(voter: EnsembleVoter) -> None:
    """All positive signals → long with agreement_ratio == 1.0."""
    votes = [
        Vote("long", 0.8, "momentum_signal"),
        Vote("long", 0.6, "rsi_signal"),
        Vote("long", 0.9, "macd_signal"),
    ]
    result = voter.aggregate(votes)

    assert result.direction == "long"
    assert result.agreement_ratio == pytest.approx(1.0)
    assert result.long_votes == 3
    assert result.short_votes == 0
    assert result.n_abstain == 0
    assert result.conviction > 0.0
    assert result.composite > 0.0


# ---------------------------------------------------------------------------
# test_majority_wins
# ---------------------------------------------------------------------------

def test_majority_wins(voter: EnsembleVoter) -> None:
    """3 long + 2 short → long direction, agreement = 3/5 = 0.6."""
    votes = [
        Vote("long", 0.7, "a"),
        Vote("long", 0.5, "b"),
        Vote("long", 0.8, "c"),
        Vote("short", 0.9, "d"),
        Vote("short", 0.6, "e"),
    ]
    result = voter.aggregate(votes)

    assert result.direction == "long"
    assert result.agreement_ratio == pytest.approx(3 / 5)
    assert result.long_votes == 3
    assert result.short_votes == 2
    assert result.n_votes == 5
    assert result.n_abstain == 0
    # conviction = agreement_ratio × max_confidence_of_majority = 0.6 × 0.8
    assert result.conviction == pytest.approx(0.6 * 0.8)
    assert result.composite > 0.0


# ---------------------------------------------------------------------------
# test_abstain_excluded
# ---------------------------------------------------------------------------

def test_abstain_excluded(voter: EnsembleVoter) -> None:
    """Abstaining votes don't count toward agreement ratio."""
    votes = [
        Vote("long", 0.7, "a"),
        Vote("long", 0.6, "b"),
        Vote("abstain", 0.0, "c"),
        Vote("abstain", 0.0, "d"),
    ]
    result = voter.aggregate(votes)

    assert result.direction == "long"
    assert result.n_votes == 4
    assert result.n_abstain == 2
    # agreement_ratio is 2 non-abstaining, both long → 2/2 = 1.0
    assert result.agreement_ratio == pytest.approx(1.0)
    assert result.long_votes == 2
    assert result.short_votes == 0


# ---------------------------------------------------------------------------
# test_noise_threshold
# ---------------------------------------------------------------------------

def test_noise_threshold(voter: EnsembleVoter) -> None:
    """Values below noise_threshold (0.05) should become abstain votes."""
    low_vote = voter.signal_to_vote("tiny_signal", 0.03)
    assert low_vote.direction == "abstain"
    assert low_vote.confidence == pytest.approx(0.0)

    # Exactly at threshold: 0.05 → still abstain (|value| < threshold, not <=)
    at_threshold = voter.signal_to_vote("at_threshold", 0.05)
    # 0.05 is NOT strictly less than 0.05, so it should be long
    assert at_threshold.direction == "long"

    above_vote = voter.signal_to_vote("above_threshold", 0.10)
    assert above_vote.direction == "long"
    assert above_vote.confidence > 0.0


# ---------------------------------------------------------------------------
# test_composite_backward_compat
# ---------------------------------------------------------------------------

def test_composite_backward_compat(voter: EnsembleVoter) -> None:
    """composite is positive for long result, negative for short, zero for abstain."""
    # Long case
    long_votes = [Vote("long", 0.8, "x"), Vote("long", 0.6, "y")]
    long_result = voter.aggregate(long_votes)
    assert long_result.composite > 0.0
    assert long_result.composite == pytest.approx(long_result.conviction)

    # Short case
    short_votes = [Vote("short", 0.8, "x"), Vote("short", 0.6, "y")]
    short_result = voter.aggregate(short_votes)
    assert short_result.composite < 0.0
    assert short_result.composite == pytest.approx(-short_result.conviction)

    # Abstain case (all votes abstain)
    abstain_votes = [Vote("abstain", 0.0, "x")]
    abstain_result = voter.aggregate(abstain_votes)
    assert abstain_result.composite == pytest.approx(0.0)
    assert abstain_result.direction == "abstain"
    assert abstain_result.conviction == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# test_from_signal_dict
# ---------------------------------------------------------------------------

def test_from_signal_dict(voter: EnsembleVoter) -> None:
    """from_signal_dict picks up _signal keys and builds votes correctly."""
    sig = {
        "momentum_signal": 0.3,
        "rsi_signal": 0.2,
        "macd_signal": -0.1,
        "composite": 0.15,   # existing weighted sum — should be ignored when signals present
        "_regime": "normal",  # non-signal key — should be ignored
    }
    result = voter.from_signal_dict(sig)

    # 2 long (momentum, rsi) vs 1 short (macd) → long majority
    assert result.direction == "long"
    assert result.n_votes == 3
    assert result.long_votes == 2
    assert result.short_votes == 1


def test_from_signal_dict_fallback_to_composite(voter: EnsembleVoter) -> None:
    """When no _signal keys found, falls back to the composite value."""
    sig = {"composite": 0.4, "_regime": "bull"}
    result = voter.from_signal_dict(sig)
    # Should succeed (1 vote from composite) and be long
    assert result.direction == "long"
    assert result.n_votes == 1


def test_empty_votes_returns_abstain(voter: EnsembleVoter) -> None:
    """Aggregating empty list returns abstain result."""
    result = voter.aggregate([])
    assert result.direction == "abstain"
    assert result.conviction == pytest.approx(0.0)
    assert result.composite == pytest.approx(0.0)
    assert result.n_votes == 0
    assert result.n_abstain == 0
