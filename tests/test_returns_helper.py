"""`_returns` must survive a hole in an OHLCV series.

Found via test_malformed_ohlcv_does_not_raise, which caught it only indirectly —
as "CrossAssetSignal.compute() raised". These pin the helper itself, so the next
regression names the actual cause instead of a symptom two frames up.

The original guard was `prices[i - 1] != 0`, which lets None straight through
(`None != 0` is True) and then raises on the subtraction. A None in a price series
is routine: a venue gaps a candle, a merge leaves a hole.
"""

from __future__ import annotations

import math

import pytest

from omega.nodes.victoria.signals_advanced import _returns


def test_clean_series() -> None:
    assert _returns([100.0, 110.0, 99.0]) == pytest.approx([0.10, -0.10])


def test_none_does_not_raise_and_is_skipped() -> None:
    """The exact crash: TypeError: unsupported operand for -: 'float' and 'NoneType'."""
    out = _returns([100.0, None, 110.0, 121.0])  # type: ignore[list-item]
    assert out == pytest.approx([0.10])  # only the 110 -> 121 pair is computable


def test_missing_endpoint_is_dropped_not_defaulted() -> None:
    """A dropped pair, not a 0.0 return.

    Substituting 0.0 would assert the price did not move when the truth is that we
    do not know, and would bias every downstream correlation toward zero.
    """
    assert _returns([100.0, None, 100.0]) == []  # type: ignore[list-item]


def test_zero_divisor_skipped() -> None:
    assert _returns([0.0, 100.0, 110.0]) == pytest.approx([0.10])


def test_nan_skipped() -> None:
    out = _returns([100.0, math.nan, 110.0, 121.0])
    assert out == pytest.approx([0.10])
    assert all(not math.isnan(x) for x in out)


def test_all_unusable_returns_empty() -> None:
    assert _returns([None, None]) == []  # type: ignore[list-item]
    assert _returns([]) == []
    assert _returns([100.0]) == []


def test_bools_are_not_prices() -> None:
    """bool is a subclass of int, so a stray True would otherwise compute as 1.0."""
    assert _returns([True, 100.0]) == []  # type: ignore[list-item]
