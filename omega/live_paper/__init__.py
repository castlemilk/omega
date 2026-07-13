"""
omega.live_paper
~~~~~~~~~~~~~~~~~
V250 — Victoria live-**paper** data-feed harness (data-feed layer only).

Scope: real-time / retrospective market-data ingestion mirroring the frozen
``SeriesProvider`` seam. NO strategy code, NO broker, NO orders, NO funds.
Master-gated OFF via ``LIVE_PAPER_ENABLED`` (see ``config.LivePaperConfig``).

V252 adds the runner layer: scheduler (daily UTC tick), crash-safe checkpoint,
and the composing runner. V251 shipped the backtest reconciliation gate.
"""

from omega.live_paper.checkpoint import Checkpoint, CheckpointCorruption, CheckpointState
from omega.live_paper.config import (
    SELECTIVE_UNIVERSE,
    LivePaperConfig,
    SchedulerConfig,
    checkpoint_dir,
)
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
from omega.live_paper.runner import (
    CycleContext,
    CycleResult,
    LivePaperRunner,
    make_fixture_cycle,
    make_forward_cycle,
    make_retrospective_cycle,
)
from omega.live_paper.scheduler import DailyScheduler, TickInfo

__all__ = [
    "SELECTIVE_UNIVERSE",
    "AsOf",
    "Checkpoint",
    "CheckpointCorruption",
    "CheckpointState",
    "CycleContext",
    "CycleResult",
    "DailyScheduler",
    "FeedResult",
    "FrozenPathViolation",
    "LivePaperConfig",
    "LivePaperRunner",
    "SchedulerConfig",
    "TickInfo",
    "as_of_pick",
    "assert_live_source",
    "checkpoint_dir",
    "make_fixture_cycle",
    "make_forward_cycle",
    "make_retrospective_cycle",
    "series_doc",
    "verify_cache",
    "write_cache",
]
