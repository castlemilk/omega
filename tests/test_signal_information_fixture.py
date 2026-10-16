"""Fast regressions for the nightly OHLCV bidirectionality input contract."""

import math
from unittest.mock import Mock

import pytest

from omega.nodes.victoria import signal_generation
from omega.nodes.victoria.ml_combiner import SignalCombiner
from omega.nodes.victoria.signal_decay import SignalDecayDetector
from omega.nodes.victoria.signals.fear_greed import FearGreedSignal
from tests.test_signal_integrity import TestBidirectionality as BidirectionalityChecks
from tests.test_signal_integrity import _build_signals, _get_composites


@pytest.mark.parametrize("external_sentiment", [-1.0, 0.25, 1.0])
def test_direction_guard_is_independent_of_external_state(
    external_sentiment: float,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Ambient feeds, learned files, and feature flags cannot redefine this scenario."""
    sentiment = Mock(return_value=external_sentiment)
    learned_file = Mock(side_effect=AssertionError("unexpected learned-state read"))
    series = Mock(side_effect=AssertionError("unexpected frozen-series read"))
    monkeypatch.setattr(FearGreedSignal, "compute", sentiment)
    monkeypatch.setattr(SignalCombiner, "load", learned_file)
    monkeypatch.setattr(SignalDecayDetector, "load", learned_file)
    monkeypatch.setattr(signal_generation, "_get_series_provider", series)
    monkeypatch.setenv("VICTORIA_FEATURES", '{"frozen_series_enabled": true}')

    # Enter after arranging hostile ambient state, just as pytest enters the
    # fixture on the nightly class. This still runs its original 20-80% assertion.
    request.getfixturevalue("neutral_signal_information")
    BidirectionalityChecks().test_no_single_direction_dominates()

    sentiment.assert_not_called()
    learned_file.assert_not_called()
    series.assert_not_called()


@pytest.mark.usefixtures("neutral_signal_information")
def test_non_neutral_overlay_still_trips_original_direction_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neutralizing the fixture must not mask a regression in the directional gate.

    This declared synthetic overlay illustrates the CI failure mechanism; it is
    not claimed to be a recovered response from the hosted run's live provider.
    """
    monkeypatch.setattr(FearGreedSignal, "compute", Mock(return_value=0.25))
    composites = _get_composites(_build_signals())
    assert math.fsum(composites.values()) / len(composites) == pytest.approx(0.0, abs=1e-15)
    assert any(value > 0 for value in composites.values())
    assert any(value < 0 for value in composites.values())
    with pytest.raises(AssertionError, match=r"Sell-side dominates:.*\(2/2\)"):
        BidirectionalityChecks().test_no_single_direction_dominates()
