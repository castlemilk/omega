# V253-smoke v2 — 24hr Live-Paper Audit

**Audit run:** 2026-07-15 ~03:17 UTC (host, gamma mount reachable)
**Output dir:** `/Volumes/gamma-systems-2/omega-victoria-data/live_paper_v253_smoke_v2/live_paper/`
**origin/main:** `1a7f291`

---

## Verdict

- **RUNTIME_OK** — daemon alive, checkpoints consistent, drift sub-second, FRED live-resolving.
- **TRADED** — 2 fills opened on the 2026-07-15 02:55 UTC cycle (ARBUSDT, POLUSDT). This is the "did paper trades actually happen" answer: **YES.**

> Note on daemon identity: PID **68916** is the *third* daemon incarnation, launched **2026-07-15T01:01:39Z** — not the 2026-07-14 03:45 launch stated in the kickoff. The daemon was gracefully restarted twice (SIGTERM/signum=15) during the window to provision `FRED_API_KEY`. State was preserved across both restarts via checkpoint resume. No cycles were lost (V252 crash-safe resume worked as designed).

---

## 1. Daemon liveness — ALIVE

```
daemon.pid       = 68916  (pidfile mtime 2026-07-15 11:01:40 AEST = 01:01 UTC)
ps -p 68916      = S, elapsed ~02:15, python@3.14, reparented to launchd (PPID 1)
```

Live. The short elapsed (~2h15m at audit time) is consistent with the restart at 01:01 UTC, not a crash.

**Daemon timeline (from `daemon.out`):**
| Run | PID | Start (UTC) | End | Cycles | FRED |
|-----|-----|-------------|-----|--------|------|
| 1 | 20144 | 2026-07-14 02:49:51 | SIGTERM 03:40 | 1 (07-14) | ❌ DEMO_KEY |
| 2 | 81481 | 2026-07-14 03:43:39 | SIGTERM 07-15 01:01 | 0 | (resumed) |
| 3 (current) | **68916** | 2026-07-15 01:01:39 | alive | 1 (07-15) | ✅ live |

Run 2 spanned ~21h but its next scheduled tick (07-15 02:55) hadn't fired before it was killed at 01:01 UTC to pick up the FRED key → 0 cycles. Run 3 fired the 07-15 tick and opened trades.

## 2. Cycle count — 2

`wc -l pnl_curve.jsonl` = **2** (2026-07-14, 2026-07-15). One clean-start cycle + one live entry cycle.

## 3. Feed health — OK; FRED CONFIRMED LIVE

Latest cycle (07-15, run 3), `feeds_blocked: []`, `signals_ok: true`:

| Feed | Status | Detail |
|------|--------|--------|
| fear_greed | OK | latest=25, 30d_mean=20.1, signal=-0.706 |
| VIX (FRED) | OK | vix=16.50 z=-0.54, final=0.000 (neutral) |
| yield_curve (FRED) | OK | r10=4.620 r2=4.260 spread=36.0bp, final=0.000 (neutral) |
| DXY (FRED DTWEXBGS) | OK | refreshed 116 obs, latest 2026-07-10=120.5046 |

**FRED provisioning CONFIRMED.** Run 3 log shows `MacroDataCache: refreshed DGS2 / DGS10 / DTWEXBGS` with **no `DEMO_KEY` warning**. Contrast run 1 (07-14) which logged `FRED_API_KEY not set — using DEMO_KEY (30 req/day limit)`. The three FRED-backed feeds (yield_curve, VIX, DXY) now resolve via the live provider. No staleness/failover/error lines for any feed in run 3.

Macro signals output `final=0.000` — that is a *neutral* reading (data resolved fine), not an error.

## 4. Trades — THE ANSWER: 2 fills opened

Cycle 2026-07-15 02:55 UTC:
- **proposals_n: 6 → fills_opened: 2**
- **Symbols:** ARBUSDT, POLUSDT (both `long`)
- **Realized PnL delta:** $0.00 (positions just opened)
- **Equity:** $100,000 → **$100,000** (unrealized $0.00)

Open positions (from checkpoint):
| Symbol | Side | Entry | Size | Weight | opened_at | exit_at_cycle |
|--------|------|-------|------|--------|-----------|---------------|
| ARBUSDT | long | 0.0906 | 10,699.93 | 10.70% | 2026-07-15T02:55:12Z | 7 |
| POLUSDT | long | 0.08447 | 8,985.30 | 8.99% | 2026-07-15T02:55:12Z | 7 |

RiskManager scaled the book: `exposure 100.0% > cap 30.0% — scaled down by 0.300`. Sizing reflects the 30% exposure cap.

**Day-1 vs Day-2:** cycle 1 (07-14) had `proposals_n: 0` — the OHLCV poller had not yet accumulated the 60-bar window on a clean start. By day 2 the window filled → 6 proposals → 2 fills. The `1a7f291`/`36cd1a2`/`9e5087c` changes (entry path wired + 60-bar poller) are exercised and working.

**POLUSDT presence confirms the MATIC→POL forward-universe remap is live** in the paper feed (per V253 P0).

## 5. Checkpoint integrity — VERIFIED

- `md5 2026-07-15.json` = `245f5ee0961e39f9044abc3345611036` == stored `.md5`. ✅
- Positions consistent: checkpoint `open_positions` (2) == `fills_opened` (2) == pnl `open_n` (2), same symbols.
- `last_completed_date: 2026-07-15`, `seed_state.cycle_n: 2`, `schema_version: 1`.
- Audit script: `checkpoint gaps: none (log ↔ checkpoint consistent)`.

## 6. Drift — OK

| Cycle | drift_seconds |
|-------|---------------|
| 2026-07-14 | 0.005 |
| 2026-07-15 | 0.002 |

No cycle exceeded 60s (both sub-10ms vs the 02:55 UTC target). Audit script: `cum $0 vs expected $7 (dev $-7, 5·SE band $1,764) [ok]`.

## 7. Weekly audit script — verbatim

```
=== V253 weekly live-paper soak audit ===
  cycles: 2  (2026-07-14 → 2026-07-15)
  equity: $100,000 → $100,000 (min $100,000 / max $100,000)
  curve : ▁▁
  cadence gaps: 0  (max consecutive missing = 0d)
  checkpoint gaps: none (log ↔ checkpoint consistent)
  drift : cum $0 vs expected $7 (dev $-7, 5·SE band $1,764)  [ok]
          within 5·SE of pre-registered mean
```
(invoked with `--pnl-log … --checkpoint-dir …`; the doc's `--dir` form is not a valid flag.)

---

## Notes / observations

- **regime = "unknown"** on both cycles: `hmmlearn not available — using numpy GMM fallback` + low history (`cycle_idx=1`, `dd_max=0.0463`). The regime classifier isn't producing a label this early in a forward run — worth watching as history accrues, but not blocking (thresholds fall back to V45 relative: long/short 0.0692, wc 0.0988).
- **IC gate OFF** (`n_pooled_ics=0 n_regime_ics=0`) — expected for a fresh forward run with no accumulated ICs yet.
- The two restarts were operational (FRED key provisioning), not failures; V252 checkpoint resume preserved state byte-consistently across both.
