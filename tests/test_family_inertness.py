"""V279 G1: the signal-family liveness report works in BOTH directions.

Phase 0 found all four `cross_asset` members identically 0.0 in frozen backtests, never
injected, contributing nothing to the standing baseline — and it took a four-step probe,
because the V213 startup banner reports flag *wiring*, not a correctly-declared signal
whose *value* is zero.

A report that can only ever say INERT would be worse than none: it would launder a bug
as a finding. These tests pin both directions.
"""

from __future__ import annotations

import logging

import pytest

from omega.nodes.victoria.adaptive_combiner import AdaptiveCombiner
from omega.nodes.victoria.signal_generation import SignalGenerationNode


def _report(signals: dict, caplog: pytest.LogCaptureFixture) -> str:
    node = SignalGenerationNode.__new__(SignalGenerationNode)  # no __init__ side effects
    with caplog.at_level(logging.INFO, logger="omega.nodes.victoria.signal_generation"):
        node._report_family_inertness(signals)
    return caplog.text


def test_family_with_no_live_member_is_marked_inert(caplog) -> None:
    """The Phase 0 case: every member absent or 0.0 on every ticker."""
    members = AdaptiveCombiner.SIGNAL_FAMILIES["cross_asset"]
    signals = {
        "ETHUSDT": dict.fromkeys(members, 0.0),
        "SOLUSDT": {},  # absent entirely — the real frozen-run shape
    }
    text = _report(signals, caplog)
    assert "cross_asset" in text
    line = next(ln for ln in text.splitlines() if "cross_asset" in ln)
    assert "INERT" in line, f"all-zero family not marked INERT: {line!r}"


def test_family_with_a_live_member_is_not_marked_inert(caplog) -> None:
    """The direction that makes the report falsifiable rather than decorative."""
    signals = {
        "ETHUSDT": {"sma_crossover": 0.42},  # `momentum` family
        "SOLUSDT": {"sma_crossover": 0.0},
    }
    text = _report(signals, caplog)
    line = next(ln for ln in text.splitlines() if "momentum" in ln)
    assert "INERT" not in line, f"family with a live member marked INERT: {line!r}"
    assert "sma_crossover" in line and "1/" in line


def test_report_fires_only_once_per_process(caplog) -> None:
    """It is a startup banner, not a per-cycle log — 60 cycles must not emit 60 reports."""
    node = SignalGenerationNode.__new__(SignalGenerationNode)
    signals = {"ETHUSDT": {"sma_crossover": 0.42}}
    with caplog.at_level(logging.INFO, logger="omega.nodes.victoria.signal_generation"):
        node._report_family_inertness(signals)
        first = caplog.text.count("V279 signal-family liveness")
        node._report_family_inertness(signals)
        node._report_family_inertness(signals)
        assert caplog.text.count("V279 signal-family liveness") == first == 1


def test_report_never_raises(caplog) -> None:
    """Observability that can break a run is worse than no observability."""
    node = SignalGenerationNode.__new__(SignalGenerationNode)
    with caplog.at_level(logging.INFO, logger="omega.nodes.victoria.signal_generation"):
        node._report_family_inertness({"ETHUSDT": None})       # malformed ticker entry
        node2 = SignalGenerationNode.__new__(SignalGenerationNode)
        node2._report_family_inertness({})                      # no tickers at all
