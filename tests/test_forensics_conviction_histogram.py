"""Tests for conviction band histogram."""
from pathlib import Path

import pytest

from omega.tools.forensics.conviction_histogram import (
    ConvictionHistogram,
    compute_histogram,
)
from omega.tools.forensics.loader import load_run

FIXTURES = Path(__file__).parent / "fixtures" / "forensics"


def test_histogram_reports_trade_and_hold_bands():
    v35 = load_run(
        FIXTURES / "mini_v35_results.json",
        FIXTURES / "mini_v35_trades.csv",
    )
    hist = compute_histogram(v35, hold_threshold=0.20)
    # v35 trades have convictions: 0.35, 0.28, 0.31, 0.22, 0.19, 0.18
    # trade band (>= 0.20): 4 trades; hold band (< 0.20): 2 trades
    assert isinstance(hist, ConvictionHistogram)
    assert hist.trade_band_count == 4
    assert hist.hold_band_count == 2
    assert hist.hold_band_pct == pytest.approx(2 / 6)
    assert hist.trade_band_pct == pytest.approx(4 / 6)


def test_histogram_empty_trades_returns_zero_pcts():
    v48 = load_run(
        FIXTURES / "mini_v48_results.json",
        FIXTURES / "mini_v48_trades.csv",
    )
    # Override trades list to empty
    v48.trades = []
    hist = compute_histogram(v48, hold_threshold=0.20)
    assert hist.trade_band_count == 0
    assert hist.hold_band_count == 0
    assert hist.trade_band_pct == 0.0
    assert hist.hold_band_pct == 0.0
