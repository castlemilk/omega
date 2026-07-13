"""
omega.live_paper
~~~~~~~~~~~~~~~~~
V250 — Victoria live-**paper** data-feed harness (data-feed layer only).

Scope: real-time / retrospective market-data ingestion mirroring the frozen
``SeriesProvider`` seam. NO strategy code, NO broker, NO orders, NO funds.
Master-gated OFF via ``LIVE_PAPER_ENABLED`` (see ``config.LivePaperConfig``).

Deferred to later versions (LIVE_PAPER_SCOPE.md §7): scheduler (V252),
crash-safe checkpoint (V252), backtest reconciliation gate (V251).
"""

from omega.live_paper.config import SELECTIVE_UNIVERSE, LivePaperConfig
from omega.live_paper.feeds import (
    AsOf,
    FeedResult,
    FrozenPathViolation,
    as_of_pick,
    assert_live_source,
    series_doc,
    verify_cache,
    write_cache,
)

__all__ = [
    "SELECTIVE_UNIVERSE",
    "AsOf",
    "FeedResult",
    "FrozenPathViolation",
    "LivePaperConfig",
    "as_of_pick",
    "assert_live_source",
    "series_doc",
    "verify_cache",
    "write_cache",
]
