"""
V252 smoke tests A + B — scheduler timing + crash-safe checkpoint.

Deterministic and network-free: a :class:`FakeClock` drives the scheduler's
injected ``now_fn``/``sleep_fn`` so simulated days pass instantly and no real
wall-clock sleep occurs. The production daemon always uses the real clock; the
fake reaches ONLY the test wiring (V252 guardrail: no fake clock in prod paths).

Test A — 3-day forward simulation:
  * ticks fire at the correct UTC target each day (drift < 60 s, non-accumulating
    under injected slew: constant wakeup latency + a forward and a backward clock
    jump simulating NTP correction / container clock skew),
  * one MD5-verified checkpoint written per day,
  * PnL log has exactly 3 strictly-monotonic entries,
  * no drift alert fired, no frozen-path use.

Test B — crash + restart mid-cycle:
  * a clean 3-day run is the reference,
  * a second run crashes mid-cycle on day 3 (before the checkpoint is written),
  * restart-from-checkpoint re-runs day 3 and reproduces the clean run's day-3
    checkpoint BYTE-IDENTICALLY (positions/equity/signals),
  * no duplicate PnL lines, no orphaned tmp/lock files.
  * Plus the checkpoint-written-but-log-not-appended crash window is reconciled
    on boot (no gap, no duplicate).
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from omega.live_paper.checkpoint import Checkpoint  # noqa: E402
from omega.live_paper.config import SchedulerConfig  # noqa: E402
from omega.live_paper.runner import LivePaperRunner, make_fixture_cycle  # noqa: E402
from omega.live_paper.scheduler import DailyScheduler  # noqa: E402


class FakeClock:
    """Controllable UTC clock. ``sleep`` advances virtual time (no real sleep).

    ``latency`` models per-wakeup scheduler jitter; ``jumps`` maps a virtual
    absolute datetime → a one-time delta applied the first time ``sleep`` crosses
    it (simulating an NTP correction / container clock jump).
    """

    def __init__(self, start: datetime, *, latency: float = 0.0,
                 jumps: list[tuple[datetime, float]] | None = None) -> None:
        self._now = start
        self.latency = latency
        self._jumps = sorted(jumps or [], key=lambda x: x[0])

    def now(self) -> datetime:
        return self._now

    def sleep(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds + self.latency)
        # Apply any scripted clock jump whose trigger time we've now passed.
        remaining = []
        for trigger, delta in self._jumps:
            if self._now >= trigger:
                self._now = self._now + timedelta(seconds=delta)
            else:
                remaining.append((trigger, delta))
        self._jumps = remaining


def _cfg() -> SchedulerConfig:
    # Big sleep chunk keeps the simulated day to ~24 wakeups; 04:05 UTC default.
    return SchedulerConfig(tick_utc="04:05:00", drift_alert_seconds=60.0,
                           max_sleep_chunk_seconds=3600.0, checkpoint_keep_days=14)


def _make_runner(clock: FakeClock, tmp: Path, records: list[dict]) -> LivePaperRunner:
    sched = DailyScheduler(_cfg(), now_fn=clock.now, sleep_fn=clock.sleep,
                           log_sink=records.append)
    ckpt = Checkpoint(tmp / "checkpoint", keep_days=14)
    runner = LivePaperRunner(
        sched, ckpt, make_fixture_cycle(),
        initial_capital=100_000.0,
        pnl_log_path=tmp / "logs" / "pnl_curve.jsonl",
        install_signals=False,  # tests must not touch process-global signal state
    )
    return runner


def _read_pnl(tmp: Path) -> list[dict]:
    p = tmp / "logs" / "pnl_curve.jsonl"
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]


# ── Test A ────────────────────────────────────────────────────────────────────


def run_test_a(tmp: Path) -> dict:
    # Start at 03:00 UTC on day 1 — before the 04:05 tick. Inject slew: 2s wakeup
    # latency every chunk, +8s forward NTP jump partway through day 2, -5s backward
    # correction partway through day 3.
    start = datetime(2026, 8, 1, 3, 0, 0, tzinfo=UTC)
    jumps = [
        (datetime(2026, 8, 2, 2, 0, 0, tzinfo=UTC), +8.0),
        (datetime(2026, 8, 3, 2, 0, 0, tzinfo=UTC), -5.0),
    ]
    clock = FakeClock(start, latency=2.0, jumps=jumps)
    records: list[dict] = []
    runner = _make_runner(clock, tmp, records)
    completed = runner.run(max_cycles=3)

    ticks = [r for r in records if r.get("event") == "scheduler_tick"]
    alerts = [r for r in records if r.get("event") == "scheduler_drift_alert"]
    ckpts = sorted((tmp / "checkpoint").glob("*.json"))
    all_verified = all(
        __import__("omega.live_paper.feeds", fromlist=["verify_cache"]).verify_cache(p)
        for p in ckpts
    )
    pnl = _read_pnl(tmp)
    ts_list = [r["cycle_ts"] for r in pnl]
    monotonic = all(ts_list[i] < ts_list[i + 1] for i in range(len(ts_list) - 1))
    drifts = [t["drift_seconds"] for t in ticks]
    max_abs_drift = max(abs(d) for d in drifts) if drifts else 0.0

    result = {
        "cycles_completed": completed,
        "n_ticks": len(ticks),
        "tick_targets": [t["target_utc"] for t in ticks],
        "drifts_s": drifts,
        "max_abs_drift_s": max_abs_drift,
        "drift_alerts": len(alerts),
        "n_checkpoints": len(ckpts),
        "checkpoints_md5_verified": all_verified,
        "n_pnl_lines": len(pnl),
        "pnl_monotonic": monotonic,
        "pnl_cycle_ts": ts_list,
    }
    # Assertions (falsifier gates).
    assert completed == 3, result
    assert len(ticks) == 3, result
    assert [t["target_utc"] for t in ticks] == [
        "2026-08-01T04:05:00+00:00", "2026-08-02T04:05:00+00:00", "2026-08-03T04:05:00+00:00",
    ], result
    assert max_abs_drift < 60.0, f"drift exceeded 60s: {result}"
    # Non-accumulation: day-3 drift is not materially larger than day-1 drift.
    assert abs(drifts[-1]) <= abs(drifts[0]) + 15.0, f"drift accumulated: {result}"
    assert len(alerts) == 0, result
    assert len(ckpts) == 3 and all_verified, result
    assert len(pnl) == 3 and monotonic, result
    return result


# ── Test B ────────────────────────────────────────────────────────────────────


class _CrashOnDateError(Exception):
    pass


def _crashing_cycle(crash_date_iso: str):
    base = make_fixture_cycle()

    def _cycle(ctx):
        if ctx.cycle_date.isoformat() == crash_date_iso:
            raise _CrashOnDateError(crash_date_iso)  # simulate SIGKILL mid-cycle
        return base(ctx)

    return _cycle


def run_test_b(tmp: Path) -> dict:
    from omega.live_paper.feeds import verify_cache

    # ── reference: a clean 3-day run ────────────────────────────────────────────
    ref = tmp / "clean"
    clock = FakeClock(datetime(2026, 8, 1, 3, 0, 0, tzinfo=UTC), latency=1.0)
    _make_runner(clock, ref, []).run(max_cycles=3)
    ref_day3 = (ref / "checkpoint" / "2026-08-03.json").read_bytes()
    ref_pnl = _read_pnl(ref)

    # ── crash run: same dates, but crash mid-cycle on day 3 (before checkpoint) ──
    crash = tmp / "crash"
    clock2 = FakeClock(datetime(2026, 8, 1, 3, 0, 0, tzinfo=UTC), latency=1.0)
    sched = DailyScheduler(_cfg(), now_fn=clock2.now, sleep_fn=clock2.sleep, log_sink=lambda r: None)
    ckpt = Checkpoint(crash / "checkpoint", keep_days=14)
    r1 = LivePaperRunner(sched, ckpt, _crashing_cycle("2026-08-03"),
                         pnl_log_path=crash / "logs" / "pnl_curve.jsonl", install_signals=False)
    crashed = False
    try:
        r1.run(max_cycles=3)
    except _CrashOnDateError:
        crashed = True
    ck = Checkpoint(crash / "checkpoint")
    latest_after_crash = ck.latest_path()
    pnl_after_crash = _read_pnl(crash)
    orphan_tmps = list((crash / "checkpoint").glob("*.tmp*"))

    # ── restart: fresh objects resume from checkpoint, day 3 re-runs cleanly ─────
    clock3 = FakeClock(datetime(2026, 8, 3, 3, 30, 0, tzinfo=UTC), latency=1.0)  # boot on day 3
    sched2 = DailyScheduler(_cfg(), now_fn=clock3.now, sleep_fn=clock3.sleep, log_sink=lambda r: None)
    ckpt2 = Checkpoint(crash / "checkpoint", keep_days=14)
    r2 = LivePaperRunner(sched2, ckpt2, make_fixture_cycle(),
                         pnl_log_path=crash / "logs" / "pnl_curve.jsonl", install_signals=False)
    r2.run(max_cycles=1)  # just day 3

    crash_day3 = (crash / "checkpoint" / "2026-08-03.json").read_bytes()
    crash_pnl = _read_pnl(crash)
    crash_ts = [r["cycle_ts"] for r in crash_pnl]

    byte_identical = crash_day3 == ref_day3
    no_dupes = len(crash_ts) == len(set(crash_ts))
    monotonic = all(crash_ts[i] < crash_ts[i + 1] for i in range(len(crash_ts) - 1))
    day3_verified = verify_cache(crash / "checkpoint" / "2026-08-03.json")

    result = {
        "crashed_mid_cycle": crashed,
        "latest_checkpoint_after_crash": latest_after_crash.stem if latest_after_crash else None,
        "pnl_lines_after_crash": len(pnl_after_crash),
        "orphan_tmp_files": len(orphan_tmps),
        "day3_byte_identical_to_clean": byte_identical,
        "n_pnl_lines_after_restart": len(crash_pnl),
        "pnl_no_duplicates": no_dupes,
        "pnl_monotonic": monotonic,
        "day3_checkpoint_md5_verified": day3_verified,
        "ref_day3_equity": json.loads(ref_day3)["equity"],
        "restart_day3_equity": json.loads(crash_day3)["equity"],
    }
    # Assertions (falsifier gates).
    assert crashed, result
    assert latest_after_crash is not None and latest_after_crash.stem == "2026-08-02", result
    assert len(orphan_tmps) == 0, result  # atomic write leaves no temp turds
    assert byte_identical, f"restart checkpoint != clean run: {result}"
    assert len(crash_pnl) == 3 and no_dupes and monotonic, result
    assert day3_verified, result
    assert [r["cycle_ts"] for r in crash_pnl] == [r["cycle_ts"] for r in ref_pnl], result
    return result


def run_test_b_reconcile(tmp: Path) -> dict:
    """Crash window #2: checkpoint written but PnL line NOT yet appended → boot reconciles."""
    from omega.live_paper.feeds import verify_cache  # noqa: F401

    d = tmp / "recon"
    clock = FakeClock(datetime(2026, 8, 1, 3, 0, 0, tzinfo=UTC), latency=1.0)
    _make_runner(clock, d, []).run(max_cycles=2)
    # Simulate crash-between-save-and-append: truncate the PnL log to drop day-2's
    # line, leaving the day-2 checkpoint (with its pnl_record) intact.
    pnl_path = d / "logs" / "pnl_curve.jsonl"
    lines = [ln for ln in pnl_path.read_text().splitlines() if ln.strip()]
    pnl_path.write_text(lines[0] + "\n")  # keep only day-1 line
    # Boot a fresh runner → it must reconcile day-2's line back from the checkpoint.
    clock2 = FakeClock(datetime(2026, 8, 3, 3, 0, 0, tzinfo=UTC), latency=1.0)
    sched = DailyScheduler(_cfg(), now_fn=clock2.now, sleep_fn=clock2.sleep, log_sink=lambda r: None)
    ckpt = Checkpoint(d / "checkpoint", keep_days=14)
    runner = LivePaperRunner(sched, ckpt, make_fixture_cycle(),
                             pnl_log_path=pnl_path, install_signals=False)
    runner.run(max_cycles=0)  # boot-only; no new cycle
    pnl = _read_pnl(d)
    ts = [r["cycle_ts"] for r in pnl]
    result = {
        "pnl_lines_after_reconcile": len(pnl),
        "dates": [r["cycle_date"] for r in pnl],
        "monotonic": all(ts[i] < ts[i + 1] for i in range(len(ts) - 1)),
        "no_duplicates": len(ts) == len(set(ts)),
    }
    assert len(pnl) == 2, result  # day-2 line reconciled back
    assert result["monotonic"] and result["no_duplicates"], result
    assert result["dates"] == ["2026-08-01", "2026-08-02"], result
    return result


# ── pytest entrypoints ──────────────────────────────────────────────────────────


def test_a_three_day_forward(tmp_path):
    run_test_a(tmp_path)


def test_b_crash_restart(tmp_path):
    run_test_b(tmp_path)


def test_b_reconcile_pnl_gap(tmp_path):
    run_test_b_reconcile(tmp_path)


if __name__ == "__main__":
    import tempfile

    for name, fn in (("A", run_test_a), ("B", run_test_b), ("B-reconcile", run_test_b_reconcile)):
        with tempfile.TemporaryDirectory() as td:
            res = fn(Path(td))
            print(f"=== Test {name} ===")
            print(json.dumps(res, indent=2))
            print()
