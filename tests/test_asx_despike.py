"""The #582 spike filter.

Upstream serves FOREIGN-exchange prices for ASX tickers sharing a symbol —
ASX:AMD (Arrow Minerals, ~$0.02) prints $214.99, which is NASDAQ's AMD, for one
session and then reverts. The filter's whole subtlety is that it keys on
REVERSION rather than magnitude, because a share consolidation is also a >10x
move and must survive.
"""

from __future__ import annotations

from omega.nodes.asx.panel import ApiPriceSource


def _rows(prices: list[float]) -> list[tuple[str, float, float]]:
    return [(f"2025-12-{i + 1:02d}", p, 1e6) for i, p in enumerate(prices)]


def test_isolated_spike_is_dropped() -> None:
    """The AMD case: one session of a foreign price, then back."""
    kept, dropped = ApiPriceSource._despike(_rows([0.02, 0.02, 214.99, 0.02, 0.02]))
    assert dropped == 1
    assert 214.99 not in [p for _, p, _ in kept]


def test_consolidation_is_kept() -> None:
    """A permanent level shift is a real corporate action, not a bad print.

    This is the case a magnitude-only filter would silently delete.
    """
    kept, dropped = ApiPriceSource._despike(_rows([0.02, 0.02, 5.0, 5.1, 4.9]))
    assert dropped == 0
    assert len(kept) == 5


def test_isolated_crash_is_dropped() -> None:
    kept, dropped = ApiPriceSource._despike(_rows([10.0, 10.0, 0.01, 10.0, 10.0]))
    assert dropped == 1
    assert 0.01 not in [p for _, p, _ in kept]


def test_ordinary_volatility_survives() -> None:
    """A filter that trims real moves would flatter the strategy."""
    _, dropped = ApiPriceSource._despike(_rows([1.0, 1.4, 0.7, 1.2, 0.9, 1.5]))
    assert dropped == 0


def test_short_series_untouched() -> None:
    rows = _rows([1.0, 50.0])
    kept, dropped = ApiPriceSource._despike(rows)
    assert dropped == 0
    assert kept == rows
