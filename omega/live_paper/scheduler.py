"""
omega.live_paper.scheduler
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
V252 — daily UTC scheduler for the Victoria live-**paper** harness.

Pure runner-layer infra. Touches NO strategy code, drives NO broker. The
scheduler decides *when* a cycle fires; the caller supplies *what* the cycle
does (a plain callable). This separation is what keeps the strategy path
byte-identical to V251's replay — the scheduler only wraps it in wall-clock.

Design contracts (LIVE_PAPER_SCOPE.md §3.3/§3.4, V252 pre-reg):

- **Absolute-target ticking (no drift accumulation).** Each day's target is the
  fixed ``HH:MM:SS`` UTC time for that calendar date, computed independently of
  when the previous cycle actually fired. Drift therefore cannot accumulate
  across days — it is bounded by one sleep-chunk, not by cycle count.
- **Slew-tolerant sleep.** ``sleep_until`` sleeps in bounded chunks and re-reads
  the clock every wake, so an NTP correction or container clock jump is caught
  within one chunk instead of over/under-shooting a single giant sleep.
- **Idempotent per day.** The scheduler consults a ``last_completed_date``
  callback; a restart after today's cycle already ran advances straight to
  tomorrow's target (no double-run). A restart mid-cycle (date not yet marked
  complete) re-runs today's target — the crash-recovery path.
- **Signal-driven shutdown.** ``SIGTERM``/``SIGINT`` request a graceful stop
  *after the current cycle completes*; ``SIGKILL`` is uncatchable by design and
  is handled by checkpoint reload on the next boot, not here.
- **Injected clock.** ``now_fn``/``sleep_fn`` default to real wall-clock and are
  overridden ONLY in tests (no fake clock ever reaches a production path).
"""

from __future__ import annotations

import json
import logging
import signal
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from omega.live_paper.config import SchedulerConfig

logger = logging.getLogger("omega.live_paper.scheduler")

# Injected-clock seams. `now_fn` returns a tz-aware UTC datetime; `sleep_fn`
# sleeps `seconds`. Defaults are real; tests pass fakes so no fake clock is ever
# reachable from the daemon's production wiring.
NowFn = Callable[[], datetime]
SleepFn = Callable[[float], None]


def _real_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class TickInfo:
    """One resolved tick: its target time, when it actually fired, and the drift."""

    target_utc: datetime
    fired_utc: datetime
    drift_seconds: float
    cycle_date: date  # the UTC calendar date this tick trades for

    def as_log(self) -> dict[str, Any]:
        return {
            "event": "scheduler_tick",
            "cycle_date": self.cycle_date.isoformat(),
            "target_utc": self.target_utc.isoformat(),
            "fired_utc": self.fired_utc.isoformat(),
            "drift_seconds": round(self.drift_seconds, 3),
        }


class DailyScheduler:
    """Fires once per UTC day at a fixed wall-clock time, drift-tolerant.

    The scheduler is stateless about *cycle results* — it only knows the target
    time and asks a callback for the last completed date. That keeps it a pure
    timing primitive that the runner composes with the checkpoint.
    """

    def __init__(
        self,
        cfg: SchedulerConfig | None = None,
        *,
        now_fn: NowFn = _real_now,
        sleep_fn: SleepFn | None = None,
        log_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.cfg = cfg or SchedulerConfig.from_env()
        self._now = now_fn
        # Import time lazily so a fake clock in tests never forces real sleeps.
        if sleep_fn is None:
            import time as _time

            sleep_fn = _time.sleep
        self._sleep = sleep_fn
        self._log_sink = log_sink
        self._shutdown_requested = False

    # ── target computation ──────────────────────────────────────────────────────

    def _tick_time(self) -> time:
        h, m, s = self.cfg.tick_hms
        return time(h, m, s, tzinfo=UTC)

    def target_for_date(self, d: date) -> datetime:
        """The absolute UTC firing instant for calendar date ``d``."""
        return datetime.combine(d, self._tick_time())

    def next_target(self, now: datetime, last_completed: date | None) -> datetime:
        """Next tick strictly in the future, honoring idempotency.

        - If today's tick time is still ahead and today isn't already completed,
          today is the target.
        - If today's tick time has passed (or today is already completed),
          the target is tomorrow's tick time.
        - A ``last_completed`` >= today forces the target to the day AFTER
          ``last_completed`` (prevents a same-day double-run after a restart).
        """
        today = now.date()
        candidate = self.target_for_date(today)
        if now < candidate and (last_completed is None or last_completed < today):
            target_date = today
        else:
            target_date = today + timedelta(days=1)
        # Never schedule a date at/behind the last completed one.
        if last_completed is not None and target_date <= last_completed:
            target_date = last_completed + timedelta(days=1)
        return self.target_for_date(target_date)

    # ── slew-tolerant sleep ─────────────────────────────────────────────────────

    def sleep_until(self, target: datetime) -> None:
        """Sleep until ``target``, re-reading the clock each bounded chunk.

        Returns early if a shutdown was requested. Robust to clock slew: because
        the remaining interval is recomputed against the absolute ``target`` on
        every wake, a forward jump is caught within one chunk and a backward jump
        cannot cause an unbounded oversleep.
        """
        chunk = max(0.01, float(self.cfg.max_sleep_chunk_seconds))
        while not self._shutdown_requested:
            remaining = (target - self._now()).total_seconds()
            if remaining <= 0:
                return
            self._sleep(min(chunk, remaining))

    # ── one tick ─────────────────────────────────────────────────────────────────

    def wait_next(self, last_completed: date | None) -> TickInfo | None:
        """Block until the next tick fires; return its :class:`TickInfo`.

        Returns ``None`` if a shutdown was requested before the tick fired.
        """
        now = self._now()
        target = self.next_target(now, last_completed)
        self.sleep_until(target)
        if self._shutdown_requested and self._now() < target:
            return None
        fired = self._now()
        drift = (fired - target).total_seconds()
        info = TickInfo(
            target_utc=target,
            fired_utc=fired,
            drift_seconds=drift,
            cycle_date=target.date(),
        )
        self._emit(info.as_log())
        if abs(drift) > self.cfg.drift_alert_seconds:
            self._emit(
                {
                    "event": "scheduler_drift_alert",
                    "cycle_date": info.cycle_date.isoformat(),
                    "drift_seconds": round(drift, 3),
                    "threshold_seconds": self.cfg.drift_alert_seconds,
                }
            )
            logger.warning(
                "scheduler drift %.1fs exceeds %.0fs threshold on %s",
                drift,
                self.cfg.drift_alert_seconds,
                info.cycle_date,
            )
        return info

    # ── signals ──────────────────────────────────────────────────────────────────

    def install_signal_handlers(self) -> None:
        """Install SIGTERM/SIGINT → graceful shutdown-after-current-cycle."""

        def _handler(signum: int, _frame: Any) -> None:  # pragma: no cover - signal path
            self._shutdown_requested = True
            self._emit({"event": "scheduler_shutdown_signal", "signum": int(signum)})
            logger.info("scheduler received signal %s — graceful shutdown after current cycle", signum)

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)

    def request_shutdown(self) -> None:
        """Programmatic graceful-stop request (used by tests and the runner)."""
        self._shutdown_requested = True

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    # ── logging ──────────────────────────────────────────────────────────────────

    def _emit(self, record: dict[str, Any]) -> None:
        if self._log_sink is not None:
            self._log_sink(record)
        else:
            logger.info(json.dumps(record, sort_keys=True))
