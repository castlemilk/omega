# Live-Paper Daemon State Audit

**Audit run:** 2026-07-25 15:49 AEST (10:00 UTC-ish) · observation only, no restart/kill/mutation
**Trigger:** Parallel V262 task (Opus 5) reported PID 53422 not alive and checkpoint dir "doesn't exist", contradicting hours of prior status reports of a live daemon with 2 open positions.

---

## Definitive answer

**No live-paper daemon is running right now. None.** It has been dead since **2026-07-17 22:38:32 AEST (~7.7 days)**.

- `ps -p 53422` → dead. `ps -p 68916` / `ps -p 38468` → dead.
- `ps auxww | grep -E "live_paper|omega"` → nothing.
- `pgrep -f live_paper_daemon` / `pgrep -f "omega.live_paper"` → no matches.
- `pgrep -fl python | grep -iE omega|victoria|live_paper|daemon` → none.

The gamma mount **is** reachable — the parallel task's "doesn't exist" finding was a **path error**, not a missing mount (see below).

---

## Root cause: the Mac rebooted, and nothing restarts the daemon on boot

```
daemon last log line : 2026-07-17 22:38:32 AEST  scheduler_shutdown_signal signum=15 (SIGTERM)
system boot          : 2026-07-17 22:47:11 AEST  (kern.boottime / who -b)
```

The SIGTERM at 22:38:32 is the **OS shutdown sequence** terminating processes; the machine came back up at 22:47:11, ~9 minutes later. The daemon handled the TERM gracefully (that's what the scheduler's shutdown handler is for) and exited cleanly. **It was never relaunched after boot** — there is no launchd/login-item/cron auto-restart wired up. `SCHEDULER_ENABLED` is still a manual flip per the V253 runbook, so this is expected behavior, not a crash.

Not OOM, not a segfault, no core dump. A clean, reboot-driven shutdown followed by no auto-start.

---

## Why the parallel task saw "doesn't exist"

The checkpoint/pid/logs live one level deeper than the reported path:

- Reported: `…/live_paper_v253_smoke_v2/`
- Actual:   `…/live_paper_v253_smoke_v2/live_paper/{checkpoint,logs}/`

`ls …/live_paper_v253_smoke_v2/daemon.pid` → No such file (correct — it's at `…/live_paper_v253_smoke_v2/live_paper/logs/daemon.pid`, which contains the stale `53422`). So the mount was fine; the probe path was one directory too shallow. Both facts ("PID not alive" AND "that exact path has no daemon.pid") are individually true but the daemon **did** run and **did** persist state.

---

## Restart history — each restart DID leave a live process (they were not silently dying)

From `logs/daemon.out` (124 lines, 4 start banners). Times AEST (UTC+10):

| PID    | Start (AEST)        | End (AEST)          | Cycles | Notes |
|--------|---------------------|---------------------|--------|-------|
| 20144  | 2026-07-14 12:49:51 | 2026-07-15 11:01:17 | —      | SIGTERM (deliberate restart) |
| 68916  | 2026-07-15 11:01:39 | 2026-07-15 18:06:25 | 1      | Fired 07-15 tick → **opened 2 positions** (ARBUSDT, POLUSDT). SIGTERM. |
| 38468  | 2026-07-15 18:07:09 | 2026-07-15 20:17:12 | 0      | Resumed 2 open positions, no tick, SIGTERM. |
| 53422  | 2026-07-15 20:18:02 | 2026-07-17 22:38:32 | 2      | Ran 07-16 + 07-17 ticks. **Killed by the 22:47 reboot.** Never restarted. |

Every restart was a graceful SIGTERM→relaunch, not a silent death. The chain `68916 → 38468 → 53422` all left live processes. Only the final one (53422) died to the reboot and was not brought back.

---

## State preserved (fully recoverable)

Checkpoints present: `2026-07-14/15/16/17.json` (+ `.md5`). Latest = **`2026-07-17.json`**, equity **$99,433.31**, realised PnL **−$616.93**.

The "2 open positions (ARBUSDT + POLUSDT)" narrative is **stale**. The original two (opened 07-15) both hit stop-loss and closed:

- ARBUSDT closed 07-16, `stop_loss(roi=-0.032)`, pnl **−$342.49**
- POLUSDT closed 07-17, `stop_loss(roi=-0.031)`, pnl **−$274.44**

As of the last checkpoint (07-17) there are **3 open positions**, not 2 — fresh trades opened after the originals closed:

| Symbol  | Side | Entry    | Size     | exit_at_cycle | Opened (UTC)        | Unreal PnL |
|---------|------|----------|----------|---------------|---------------------|------------|
| ARBUSDT | long | 0.0877   | 5507.91  | 8             | 2026-07-16 02:55:11 | +$50.24 |
| ETHUSDT | long | 1844.24  | 3265.32  | 9             | 2026-07-17 02:55:08 | $0.00 |
| POLUSDT | long | 0.08189  | 7506.71  | 9             | 2026-07-17 02:55:08 | $0.00 |

`pnl_curve.jsonl` (4 rows, 07-14 → 07-17): equity 100000 → 100000 → 99497.95 → 99433.31.

### Regime wire — works from the 07-15 20:18 restart onward
- 07-14 & 07-15 cycles: `regime="unknown"` — `hmmlearn not available — using numpy GMM fallback`.
- 07-16 cycle (PID 53422, post-restart with hmmlearn 0.3.3 landed): `hmm_regime fitted (hmmlearn)`, `regime="bull"` `regime_source="hmm"` (bull 0.744).
- 07-17 cycle: `regime="sideways"` `regime_source="hmm"` (sideways 0.780, bull 0.220).

So the "regime wire confirmed working" claim is correct **for 07-16 onward** — but the two originally-reported positions were opened on the 07-15 cycle, which ran under `regime="unknown"` (GMM fallback, hmmlearn not yet loaded that cycle).

---

## Reconciliation with prior reports

| Prior claim | Reality |
|---|---|
| Daemon PID 53422 running | **False now.** 53422 ran until the 07-17 22:47 reboot, then dead ~7.7 days. |
| 2 open positions ARBUSDT + POLUSDT from 07-15 02:55 | **Stale.** Both closed at stop-loss (07-16, 07-17). Last checkpoint has 3 fresh positions (ARB/ETH/POL). |
| Checkpoint dir doesn't exist | **False** — path was one level too shallow; state is intact through 07-17. |
| Regime wire working | **True from 07-16**; the 07-15 entries ran under GMM "unknown". |
| origin/main at 50de4677 (V262) | **Confirmed.** |

---

## Recommendation

**Safe to restart — no diagnosis needed first. Clean reboot-driven shutdown, state fully intact.**

The checkpoint chain is complete and byte-verifiable (`.md5` alongside each). A restart will `checkpoint_loaded` from `2026-07-17.json`, resume the 3 open positions, and continue the daily 02:55 UTC schedule. No corruption, no partial write, no crash to untangle.

Two things for the user to decide before flipping it back on:
1. **The ~7.7-day gap** — 07-18 through 07-25 cycles were missed. A resume from 07-17 will not backfill those days; the soak's calendar continuity is broken for that window. Decide whether to (a) resume-and-note-the-gap, or (b) restart the smoke clean.
2. **Auto-restart on boot** — the reboot exposed that nothing relaunches the daemon. If the 90-day soak is to survive reboots unattended, wire a launchd agent (or equivalent) rather than a manual foreground start. Until then, every reboot silently ends the soak.

**Do not** rely on the stale `daemon.pid` (still says 53422) as a liveness signal — it survives the process.
