"""omega.core.improvement_scheduler
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Schedules when improvement trials happen across nodes.

Responsibilities:
- Maintains a priority queue of (next_run_time, node_id)
- Applies cool-down after failed improvements
- Respects per-node improvement frequency settings
- Exposes `due_nodes()` so the orchestrator can pull work
"""

from __future__ import annotations

import heapq
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("omega.core.improvement_scheduler")

# ---------------------------------------------------------------------------
# Schedule entry
# ---------------------------------------------------------------------------


@dataclass(order=True)
class ScheduleEntry:
    next_run_at: float
    node_id: str = field(compare=False)
    priority: float = field(default=0.0, compare=False)  # higher = more urgent
    consecutive_failures: int = field(default=0, compare=False)
    last_run_at: float | None = field(default=None, compare=False)
    last_score: float | None = field(default=None, compare=False)


# ---------------------------------------------------------------------------
# NodeScheduleConfig
# ---------------------------------------------------------------------------


@dataclass
class NodeScheduleConfig:
    """Per-node scheduling parameters."""

    node_id: str
    interval_seconds: float = 3600.0  # how often to run improvement
    cooldown_seconds: float = 300.0  # cooldown after failure
    max_consecutive_failures: int = 5  # suspend after this many
    priority: float = 1.0  # relative priority (higher = first)
    enabled: bool = True


# ---------------------------------------------------------------------------
# ImprovementScheduler
# ---------------------------------------------------------------------------


class ImprovementScheduler:
    """
    Priority queue-based scheduler for improvement trials.

    Usage::

        scheduler = ImprovementScheduler()
        scheduler.register("node-a", NodeScheduleConfig("node-a", interval_seconds=1800))
        scheduler.register("node-b", NodeScheduleConfig("node-b", interval_seconds=3600))

        while True:
            due = scheduler.due_nodes()
            for node_id in due:
                # run improvement trial
                success = run_improvement(node_id)
                scheduler.record_outcome(node_id, success=success)
            time.sleep(60)
    """

    def __init__(self, clock: Any = None) -> None:
        """
        clock: optional callable returning current time (float seconds).
        Defaults to time.time. Inject a mock in tests.
        """
        self._clock = clock or time.time
        self._configs: dict[str, NodeScheduleConfig] = {}
        self._entries: dict[str, ScheduleEntry] = {}
        self._heap: list[ScheduleEntry] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        node_id: str,
        config: NodeScheduleConfig | None = None,
        run_immediately: bool = False,
    ) -> None:
        """Register a node with its scheduling configuration."""
        cfg = config or NodeScheduleConfig(node_id=node_id)
        self._configs[node_id] = cfg

        now = self._clock()
        next_run = now if run_immediately else now + cfg.interval_seconds
        entry = ScheduleEntry(
            next_run_at=next_run,
            node_id=node_id,
            priority=cfg.priority,
        )
        self._entries[node_id] = entry
        heapq.heappush(self._heap, entry)
        logger.debug("Registered node %s, next run in %.0fs", node_id, next_run - now)

    def unregister(self, node_id: str) -> None:
        """Remove a node from the scheduler (takes effect at next rebuild)."""
        self._configs.pop(node_id, None)
        self._entries.pop(node_id, None)
        self._rebuild_heap()

    def update_config(self, node_id: str, **kwargs: Any) -> None:
        """Update scheduling config fields for a node."""
        if node_id not in self._configs:
            raise KeyError(f"Node {node_id!r} not registered")
        cfg = self._configs[node_id]
        for k, v in kwargs.items():
            setattr(cfg, k, v)

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def due_nodes(self) -> list[str]:
        """Return node_ids whose next_run_at is <= now, ordered by priority."""
        now = self._clock()
        due: list[tuple[float, str]] = []

        while self._heap and self._heap[0].next_run_at <= now:
            entry = heapq.heappop(self._heap)
            node_id = entry.node_id

            # Skip stale heap entries (node was re-scheduled)
            current = self._entries.get(node_id)
            if current is None or current is not entry:
                continue

            cfg = self._configs.get(node_id)
            if cfg is None or not cfg.enabled:
                continue

            # Suspend nodes with too many consecutive failures
            if entry.consecutive_failures >= cfg.max_consecutive_failures:
                logger.warning(
                    "Node %s suspended after %d consecutive failures",
                    node_id,
                    entry.consecutive_failures,
                )
                continue

            due.append((-entry.priority, node_id))

        # Sort by descending priority (most urgent first)
        due.sort()
        return [node_id for _, node_id in due]

    def record_outcome(
        self,
        node_id: str,
        success: bool,
        score: float | None = None,
    ) -> None:
        """
        Record the outcome of an improvement trial and reschedule.

        On failure: applies cooldown before next run.
        On success: resets failure counter and schedules normally.
        """
        cfg = self._configs.get(node_id)
        if cfg is None:
            logger.warning("record_outcome called for unregistered node %s", node_id)
            return

        now = self._clock()
        entry = self._entries.get(node_id)
        if entry is None:
            entry = ScheduleEntry(next_run_at=now, node_id=node_id, priority=cfg.priority)
            self._entries[node_id] = entry

        entry.last_run_at = now
        entry.last_score = score

        if success:
            entry.consecutive_failures = 0
            delay = cfg.interval_seconds
            logger.debug("Node %s succeeded, next run in %.0fs", node_id, delay)
        else:
            entry.consecutive_failures += 1
            # Exponential back-off with cap
            backoff = min(
                cfg.cooldown_seconds * (2 ** min(entry.consecutive_failures - 1, 5)),
                cfg.interval_seconds * 4,
            )
            delay = backoff
            logger.info(
                "Node %s failed (attempt %d), cooldown %.0fs",
                node_id,
                entry.consecutive_failures,
                delay,
            )

        entry.next_run_at = now + delay
        heapq.heappush(self._heap, entry)

    def reset_failures(self, node_id: str) -> None:
        """Manually clear the failure counter and reschedule immediately."""
        entry = self._entries.get(node_id)
        if entry:
            entry.consecutive_failures = 0
            entry.next_run_at = self._clock()
            heapq.heappush(self._heap, entry)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def schedule_status(self) -> list[dict[str, Any]]:
        """Return a summary of all registered nodes' schedule status."""
        now = self._clock()
        result = []
        for node_id, entry in self._entries.items():
            cfg = self._configs.get(node_id)
            result.append(
                {
                    "node_id": node_id,
                    "next_run_in_seconds": max(0.0, entry.next_run_at - now),
                    "consecutive_failures": entry.consecutive_failures,
                    "last_run_at": entry.last_run_at,
                    "last_score": entry.last_score,
                    "enabled": cfg.enabled if cfg else False,
                    "suspended": (
                        entry.consecutive_failures >= cfg.max_consecutive_failures
                        if cfg
                        else False
                    ),
                    "priority": entry.priority,
                }
            )
        # Sort by next_run_at ascending
        result.sort(key=lambda r: float(r["next_run_in_seconds"]))  # type: ignore[arg-type]
        return result

    def next_due(self) -> tuple[str, float] | None:
        """Return (node_id, seconds_until_due) for the next scheduled node."""
        if not self._heap:
            return None
        entry = self._heap[0]
        now = self._clock()
        return entry.node_id, max(0.0, entry.next_run_at - now)

    def registered_nodes(self) -> list[str]:
        return list(self._configs.keys())

    def is_suspended(self, node_id: str) -> bool:
        entry = self._entries.get(node_id)
        cfg = self._configs.get(node_id)
        if not entry or not cfg:
            return False
        return entry.consecutive_failures >= cfg.max_consecutive_failures

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rebuild_heap(self) -> None:
        """Rebuild the heap from current entries (O(n))."""
        self._heap = [e for nid, e in self._entries.items() if nid in self._configs]
        heapq.heapify(self._heap)
