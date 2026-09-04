import json
from datetime import datetime, timezone

import pytest

from omega.core.task_scheduler import CronExpression, TaskScheduler

# ── CronExpression parsing ─────────────────────────────────────────────────────

def test_cron_wildcard_always_matches():
    cron = CronExpression("* * * * *")
    dt = datetime(2026, 3, 29, 14, 30, tzinfo=timezone.utc)
    assert cron.matches(dt)


def test_cron_specific_minute_matches():
    cron = CronExpression("30 * * * *")
    assert cron.matches(datetime(2026, 3, 29, 14, 30, tzinfo=timezone.utc))
    assert not cron.matches(datetime(2026, 3, 29, 14, 31, tzinfo=timezone.utc))


def test_cron_daily_at_2am():
    cron = CronExpression("0 2 * * *")
    assert cron.matches(datetime(2026, 3, 29, 2, 0, tzinfo=timezone.utc))
    assert not cron.matches(datetime(2026, 3, 29, 2, 1, tzinfo=timezone.utc))
    assert not cron.matches(datetime(2026, 3, 29, 3, 0, tzinfo=timezone.utc))


def test_cron_invalid_expression_raises():
    with pytest.raises(ValueError):
        CronExpression("* * *")  # only 3 fields


# ── TaskScheduler ─────────────────────────────────────────────────────────────

def test_add_cron_and_tick_runs_task():
    scheduler = TaskScheduler()
    ran = []
    scheduler.add_cron("test_job", "* * * * *", lambda: ran.append(1))
    scheduler.tick(datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc))
    assert ran == [1]


def test_tick_does_not_run_task_twice_in_same_minute():
    scheduler = TaskScheduler()
    ran = []
    scheduler.add_cron("dedup_job", "* * * * *", lambda: ran.append(1))
    dt = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
    scheduler.tick(dt)
    scheduler.tick(dt)  # same minute — should not re-run
    assert len(ran) == 1


def test_tick_runs_task_in_next_minute():
    scheduler = TaskScheduler()
    ran = []
    scheduler.add_cron("next_min", "* * * * *", lambda: ran.append(1))
    dt1 = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
    dt2 = datetime(2026, 3, 29, 10, 1, tzinfo=timezone.utc)
    scheduler.tick(dt1)
    scheduler.tick(dt2)
    assert len(ran) == 2


def test_add_one_shot_runs_once():
    scheduler = TaskScheduler()
    ran = []
    run_at = datetime(2026, 3, 29, 15, 0, tzinfo=timezone.utc)
    scheduler.add_one_shot("snapshot", run_at, lambda: ran.append(1))
    scheduler.tick(datetime(2026, 3, 29, 14, 59, tzinfo=timezone.utc))
    assert ran == []
    scheduler.tick(run_at)
    assert ran == [1]
    scheduler.tick(datetime(2026, 3, 29, 15, 1, tzinfo=timezone.utc))
    assert ran == [1]  # did not re-run


def test_save_and_load_preserves_tasks(tmp_path):
    state_file = str(tmp_path / "state.json")
    scheduler = TaskScheduler(state_file=state_file)
    scheduler.add_cron("persistent_job", "0 6 * * *", lambda: None)
    scheduler.save()

    scheduler2 = TaskScheduler(state_file=state_file)
    scheduler2.load()
    tasks = scheduler2.list_tasks()
    assert any(t["name"] == "persistent_job" for t in tasks)


def test_list_tasks_returns_metadata():
    scheduler = TaskScheduler()
    scheduler.add_cron("my_task", "0 2 * * *", lambda: None, tz="UTC")
    tasks = scheduler.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["name"] == "my_task"
    assert tasks[0]["cron"] == "0 2 * * *"
    assert tasks[0]["tz"] == "UTC"


def test_remove_task():
    scheduler = TaskScheduler()
    scheduler.add_cron("removable", "* * * * *", lambda: None)
    scheduler.remove("removable")
    assert scheduler.list_tasks() == []


def test_task_exception_does_not_crash_scheduler():
    scheduler = TaskScheduler()

    def bad_fn():
        raise RuntimeError("task failure")

    scheduler.add_cron("bad_task", "* * * * *", bad_fn)
    dt = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
    ran = scheduler.tick(dt)
    assert "bad_task" in ran  # it was attempted
