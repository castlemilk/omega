# V253-smoke — 24-hour live-paper runtime validation (KICKOFF)

**Launched:** 2026-07-14T02:19:58Z (daemon boot) · first cycle 2026-07-14T02:25:58Z
**Purpose:** Wall-clock RUNTIME validation of the V250 feeds + V252 scheduler/checkpoint
stack — a shortened stand-in for the V253 90-day soak. Proves feeds fetch, the daemon
ticks unattended, checkpoints are atomic + MD5-verified, and nothing crashes.

> ⚠️ **This is NOT a PnL measurement.** A 24-hour window on a *daily-bar* strategy gives
> **at most 1–2 scheduler ticks**. Real PnL needs many days. Every number below is a
> runtime signal, not a strategy result.
>
> ⚠️ **The V252 forward cycle does not open positions.** Per `omega/live_paper/runner.py`
> (`make_forward_cycle`, docstring L313-316), position *entry* — the full
> SignalGeneration → StrategyNode → proposal path — **is wired in V253, not V252**. The
> shipped forward cycle rehydrates prior positions, fetches OHLCV, and marks-to-market.
> On a clean start with no positions it fetches feeds, marks an empty portfolio, and
> returns **zero trades — guaranteed, every cycle**. So "0 trades / equity flat at
> $100,000" here is the **expected, correct** outcome, not a strategy that chose to sit
> out. This smoke validates the *runtime*; it cannot validate entry (that code isn't
> shipped yet).

---

## Deliverable 1 — Preflight / provisioning

| Component | Status | Notes |
|---|---|---|
| `scripts/prepare_session.sh` | ✅ clean | HEAD `169400b`, branch `main` |
| `git pull origin main` | ✅ up-to-date | V252 + V253 code already on tree |
| **Binance OHLCV** (only feed the forward cycle uses) | ✅ **reachable** | real-code probe: 235 ms, BTC 2026-07-14 close $62,503.44, 10 bars. **Not geo-blocked from this host.** |
| Gamma volume `/Volumes/gamma-systems-2/` | ✅ writable | 1.2 Ti free (38 % used) |
| Module import (`omega.live_paper.*`) | ✅ OK | |
| Daemon dry-run (`--max-cycles 0`) | ✅ boots + exits 0 | clean-start wiring validated |
| `FRED_API_KEY` | ⚠️ **unset** | yield-curve/VIX/DXY FRED path unavailable — **but the V252 forward cycle never calls these pollers**, so it does not gate this smoke. Relevant only once entry (V253) is wired. |
| GDELT egress | ⚠️ HTTP 429 (rate-limited, reachable) | Same as FRED — **not called by the forward cycle**; non-blocking here. |

**No critical dependency broken.** The only feed the forward cycle consumes (Binance
klines) is reachable, so the smoke proceeded.

---

## Deliverable 2 — Daemon (running, detached)

| | |
|---|---|
| **PID** | **32929** (nohup, disowned — survives shell exit) |
| **Mode** | `forward` (real V250 live feeds → PaperTradingEngine mark-to-market) |
| **Launch cmd** | `scripts/live_paper_daemon.sh --mode forward` (committed V252 wrapper) |
| **Log** | `/Volumes/gamma-systems-2/omega-victoria-data/live_paper_v253_smoke/live_paper/logs/daemon.out` |
| **PID file** | `…/live_paper_v253_smoke/live_paper/logs/daemon.pid` |
| **Checkpoints** | `…/live_paper_v253_smoke/live_paper/checkpoint/{date}.json` (+ `.md5`) |
| **PnL log** | `…/live_paper_v253_smoke/live_paper/logs/pnl_curve.jsonl` |
| **Tick** | `02:25:58 UTC` daily |

### Runtime configuration (env vars only — NO committed config edited)

```
OMEGA_AUDIT_OUTPUT_DIR=/Volumes/gamma-systems-2/omega-victoria-data/live_paper_v253_smoke
SCHEDULER_ENABLED=1
LIVE_PAPER_ENABLED=1
OMEGA_FROZEN_CACHE=0            # live mode, not frozen
SCHEDULER_TICK_UTC=02:25:58     # see rationale below
DATABASE_URL=postgres://omega:omega@localhost:5432/omega?sslmode=disable
```

> **Note on env-var names:** the task brief suggested `OMEGA_LIVE_PAPER_DIR`, but the
> committed V252 code reads **`OMEGA_AUDIT_OUTPUT_DIR`** (→ appends `/live_paper`). I used
> the real contract. All artifacts therefore live under `…/live_paper_v253_smoke/live_paper/`.

**Tick-time rationale (a genuine choice, decided + documented per guardrails):** the
canonical tick is `04:05 UTC` (a buffer for late daily bars). At launch (02:19 UTC) the
next 04:05 was ~1h46m out. I set the tick to **`02:25:58` (~6 min ahead)** so the smoke
captured a **confirmed real cycle promptly** instead of waiting nearly two hours. This is
safe because the forward cycle only consumes **Binance klines**, which are available
continuously (the 02:15 probe already returned the 2026-07-14 bar) — the 04:05 daily-bar
settle buffer isn't needed for this feed. Consequence: the **next** natural tick is
2026-07-15 `02:25:58 UTC` (~24 h after the first), landing right at the edge of the 24 h
window — so a second cycle may or may not fall inside it. The first (already-completed)
cycle already satisfies the "≥1 real cycle" success criterion.

---

## Deliverable 3 — First real cycle (executed + verified)

Pre-launch, a **throwaway bounded `--max-cycles 1` run** (in `/tmp`, since deleted)
validated the full forward path end-to-end before committing to the unbounded nohup —
PASS (0.006 s drift, MD5 match, no exception). Then the real detached daemon fired its
own first cycle:

**Cycle `2026-07-14T02:25:58.002365+00:00`** — fired unattended by the daemon:

| Check | Result |
|---|---|
| Scheduler drift | **0.002 s** (threshold 60 s) ✅ |
| Feeds fetched | **all 10 / 10 OK** — `feeds_blocked: []` ✅ |
| Universe | selective 10-name (`ETH SOL BNB XRP ADA AVAX POL NEAR SUI ARB`; `BTC DOT LINK` blacklisted) |
| Signals / entry | not wired in V252 forward cycle (see banner) — no proposals by design |
| Paper fills | **0** (expected — empty portfolio, no entry) |
| Checkpoint | `2026-07-14.json` written, MD5 `998aec1b3a5374dcb2a18640a5be30f4` — **sidecar match verified** ✅ |
| PnL log line | appended, monotonic ✅ |
| Equity | `$100,000 → $100,000` (flat — no positions) |
| Exceptions | **none**; daemon still alive after the cycle ✅ |

`v253_weekly_audit.py` against the smoke dir: `cycles: 1`, no cadence gaps, checkpoint ↔
log consistent, drift within band. ✅

---

## Deliverable 4 — 24-hour monitoring handoff

Export once per shell for the commands below:
```bash
SMOKE=/Volumes/gamma-systems-2/omega-victoria-data/live_paper_v253_smoke
```

**Is the daemon alive?**
```bash
ps -p "$(cat "$SMOKE/live_paper/logs/daemon.pid")" -o pid,stat,etime,command
```

**Watch the log in real time:**
```bash
tail -f "$SMOKE/live_paper/logs/daemon.out"
```

**Run the audit anytime (read-only):**
```bash
python3 scripts/v253_weekly_audit.py \
  --pnl-log "$SMOKE/live_paper/logs/pnl_curve.jsonl" \
  --checkpoint-dir "$SMOKE/live_paper/checkpoint"
```

**Abort cleanly (state persists in checkpoint; resumes on next launch):**
```bash
kill -TERM "$(cat "$SMOKE/live_paper/logs/daemon.pid")"
```
SIGTERM requests a graceful stop **after the current cycle**; the last checkpoint is
authoritative, so a later relaunch resumes idempotently (no double-run, no gap).

### What to expect over 24 h
- **1–2 scheduler ticks.** The first (02:25:58 UTC 2026-07-14) is already done. A second
  is scheduled for 02:25:58 UTC 2026-07-15 — at the window edge, so it may or may not land
  inside the 24 h.
- Each tick fetches the 10-name universe from Binance, marks-to-market, checkpoints, and
  appends one PnL line.
- **0 trades and flat equity are the correct, expected result** (entry not wired — V253).

### What to look for (anomalies)
- Any `Traceback` / `ERROR` in `daemon.out`, or the PID disappearing → daemon died.
- `feeds_blocked` non-empty in a PnL line → a Binance fetch failed that cycle.
- `scheduler_drift_alert` events → tick drift > 60 s (clock/NTP issue).
- `CheckpointCorruption` on boot → MD5 mismatch (the daemon refuses to proceed by design).
- A cadence gap or `checkpoint ↔ log` inconsistency in the audit output.

### Tomorrow's audit
Re-run the audit command above. Expect 1–2 cycles, equity ≈ flat, zero gaps, no drift
alerts. If a second cycle landed, confirm its `feeds_blocked: []` and MD5 match. Then
decide whether the runtime is trustworthy enough to graduate to the full V253 90-day soak
(which additionally requires wiring entry, `FRED_API_KEY`, and GDELT egress — none of
which this V252 runtime smoke exercises).

---

## Guardrails honored
- ✅ No strategy code touched. No live broker. No real capital. Live-**paper** only.
- ✅ No V252-committed code edited — configured entirely via env vars.
- ✅ Validated the forward path in a throwaway bounded run before the unbounded launch.
