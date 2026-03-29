"""
omega.core.task_scheduler
~~~~~~~~~~~~~~~~~~~~~~~~~~
Cron-based task scheduler with persistent state and timezone awareness.

Features
--------
- Cron expressions (5-field: minute hour day month weekday)
- One-shot tasks (run once at a specific UTC datetime)
- Deduplication: a cron task runs at most once per minute window
- JSON-backed persistence for task metadata (callables are NOT persisted
  and must be re-registered after a process restart)
- Timezone-aware scheduling via ``zoneinfo``
- Graceful error handling: a failing task logs the exception but does
  not stop the scheduler

Usage::

    from omega.core.task_scheduler import TaskScheduler

    scheduler = TaskScheduler(state_file="data/scheduler_state.json")

    # Daily self-repair at 03:00 UTC
    scheduler.add_cron(
        "daily_self_repair",
        "0 3 * * *",
        lambda: SelfRepairLoop().check_and_repair(),
    )

    # One-shot snapshot
    from datetime import datetime, timezone
    scheduler.add_one_shot(
        "end_of_month_snapshot",
        datetime(2026, 3, 31, 23, 59, tzinfo=timezone.utc),
        take_snapshot,
    )

    # Call scheduler.tick() from your main loop (or a background thread)
    scheduler.tick()
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("omega.core.task_scheduler")

_DEFAULT_STATE_FILE = "data/scheduler_state.json"


# ── Cron expression parsing ────────────────────────────────────────────────────


class CronExpression:
    """
    Minimal 5-field cron parser: ``minute hour day month weekday``.

    Supports:
    - ``*``     : any value
    - ``5``     : exact value
    - ``*/5``   : every 5 (step)
    - ``0-30``  : range (inclusive)

    Raises ValueError for malformed expressions.
    """

    def __init__(self, expr: str) -> None:
        parts = expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Cron expression must have 5 fields (got {len(parts)}): {expr!r}")
        self._expr = expr
        self._minute = _parse_field(parts[0], 0, 59)
        self._hour = _parse_field(parts[1], 0, 23)
        self._day = _parse_field(parts[2], 1, 31)
        self._month = _parse_field(parts[3], 1, 12)
        self._weekday = _parse_field(parts[4], 0, 6)  # 0=Sunday

    def matches(self, dt: datetime) -> bool:
        """Return True if ``dt`` matches this cron expression."""
        # Python weekday(): Monday=0. Convert to Sunday=0.
        sunday_based = (dt.weekday() + 1) % 7
        return (
            dt.minute in self._minute
            and dt.hour in self._hour
            and dt.day in self._day
            and dt.month in self._month
            and sunday_based in self._weekday
        )

    def __str__(self) -> str:
        return self._expr


def _parse_field(field: str, low: int, high: int) -> set[int]:
    """Parse a single cron field into a set of matching integers."""
    if field == "*":
        return set(range(low, high + 1))
    if "/" in field:
        base, step_str = field.split("/", 1)
        step = int(step_str)
        start = low if base == "*" else int(base)
        return set(range(start, high + 1, step))
    if "-" in field:
        a, b = field.split("-", 1)
        return set(range(int(a), int(b) + 1))
    return {int(field)}


# ── Task data structures ───────────────────────────────────────────────────────


@dataclass
class ScheduledTask:
    """Internal representation of a scheduled task."""

    name: str
    task_type: str  # "cron" | "one_shot"
    cron: str  # cron expression (empty for one_shot)
    run_at_iso: str  # ISO-8601 UTC datetime (empty for cron)
    tz: str  # timezone name (e.g. "UTC", "US/Eastern")
    last_run_iso: str = ""
    run_count: int = 0


# ── Scheduler ─────────────────────────────────────────────────────────────────


class TaskScheduler:
    """
    Cron-based task scheduler.

    Callables are registered in memory; metadata (name, cron, last_run)
    is persisted to ``state_file`` as JSON.

    After a process restart, call ``load()`` to restore task metadata, then
    re-register callables via ``add_cron()`` / ``add_one_shot()`` — the
    load merges metadata so ``last_run_iso`` and ``run_count`` are preserved.
    """

    def __init__(self, state_file: str = _DEFAULT_STATE_FILE) -> None:
        self._state_file = state_file
        self._tasks: dict[str, ScheduledTask] = {}
        self._fns: dict[str, Callable] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def add_cron(
        self,
        name: str,
        cron_expr: str,
        fn: Callable,
        tz: str = "UTC",
    ) -> str:
        """
        Register a cron task.  Validates the cron expression immediately.
        Returns the task name.
        """
        CronExpression(cron_expr)  # validate
        existing = self._tasks.get(name)
        self._tasks[name] = ScheduledTask(
            name=name,
            task_type="cron",
            cron=cron_expr,
            run_at_iso="",
            tz=tz,
            last_run_iso=existing.last_run_iso if existing else "",
            run_count=existing.run_count if existing else 0,
        )
        self._fns[name] = fn
        logger.debug("TaskScheduler: registered cron task '%s' (%s %s)", name, cron_expr, tz)
        return name

    def add_one_shot(
        self,
        name: str,
        run_at: datetime,
        fn: Callable,
    ) -> str:
        """
        Register a one-shot task that runs once at ``run_at`` (UTC).
        Returns the task name.
        """
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=UTC)
        self._tasks[name] = ScheduledTask(
            name=name,
            task_type="one_shot",
            cron="",
            run_at_iso=run_at.isoformat(),
            tz="UTC",
        )
        self._fns[name] = fn
        logger.debug(
            "TaskScheduler: registered one-shot task '%s' at %s",
            name,
            run_at.isoformat(),
        )
        return name

    def remove(self, name: str) -> None:
        """Remove a task by name. No-op if not found."""
        self._tasks.pop(name, None)
        self._fns.pop(name, None)

    # ── Tick ──────────────────────────────────────────────────────────────────

    def tick(self, now: datetime | None = None) -> list[str]:
        """
        Check all tasks against ``now`` and run any that are due.

        ``now`` defaults to the current UTC time.  Pass an explicit value
        for deterministic testing.

        Returns list of task names that were attempted (including failed ones).
        """
        if now is None:
            now = datetime.now(UTC)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        attempted: list[str] = []

        for name, task in list(self._tasks.items()):
            fn = self._fns.get(name)
            if fn is None:
                continue

            should_run = False

            if task.task_type == "cron":
                dt_in_tz = _to_tz(now, task.tz)
                cron = CronExpression(task.cron)
                if cron.matches(dt_in_tz):
                    last_run = _parse_iso(task.last_run_iso)
                    if last_run is None or _minute_bucket(now) != _minute_bucket(last_run):
                        should_run = True

            elif task.task_type == "one_shot":
                if not task.last_run_iso:
                    run_at = _parse_iso(task.run_at_iso)
                    if run_at and now >= run_at:
                        should_run = True

            if should_run:
                attempted.append(name)
                try:
                    fn()
                    task.last_run_iso = now.isoformat()
                    task.run_count += 1
                    logger.info("TaskScheduler: ran task '%s' (count=%d)", name, task.run_count)
                except Exception as exc:
                    task.last_run_iso = now.isoformat()
                    task.run_count += 1
                    logger.error(
                        "TaskScheduler: task '%s' raised %s: %s",
                        name,
                        type(exc).__name__,
                        exc,
                    )

        return attempted

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str | None = None) -> None:
        """Persist task metadata (not callables) to JSON."""
        fpath = Path(path or self._state_file)
        fpath.parent.mkdir(parents=True, exist_ok=True)
        data = {name: asdict(task) for name, task in self._tasks.items()}
        fpath.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.debug("TaskScheduler: saved state to %s", fpath)

    def load(self, path: str | None = None) -> None:
        """
        Load task metadata from JSON.  Merges into existing tasks
        (preserves last_run_iso and run_count for already-registered tasks).
        """
        fpath = Path(path or self._state_file)
        if not fpath.exists():
            return
        try:
            data: dict[str, Any] = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("TaskScheduler: could not load state from %s: %s", fpath, exc)
            return
        for name, task_dict in data.items():
            if name not in self._tasks:
                self._tasks[name] = ScheduledTask(**task_dict)
            else:
                self._tasks[name].last_run_iso = task_dict.get("last_run_iso", "")
                self._tasks[name].run_count = task_dict.get("run_count", 0)
        logger.debug("TaskScheduler: loaded state from %s (%d tasks)", fpath, len(data))

    # ── Introspection ─────────────────────────────────────────────────────────

    def list_tasks(self) -> list[dict[str, Any]]:
        """Return a list of task metadata dicts."""
        return [asdict(t) for t in self._tasks.values()]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _to_tz(dt: datetime, tz_name: str) -> datetime:
    """Convert ``dt`` to the named timezone. Falls back to UTC on error."""
    try:
        from zoneinfo import ZoneInfo

        return dt.astimezone(ZoneInfo(tz_name))
    except Exception:
        return dt.astimezone(UTC)


def _parse_iso(iso: str) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def _minute_bucket(dt: datetime) -> str:
    """Return a string key representing the UTC minute bucket."""
    utc = dt.astimezone(UTC)
    return utc.strftime("%Y%m%d%H%M")
