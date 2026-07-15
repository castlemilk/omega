# V253 — Live-Paper Soak Provisioning Runbook (OPERATOR)

**Date:** 2026-07-14 · **Author:** claude (Opus 4.8) · **Type:** operator runbook (no strategy code)
**Companion to:** [`V253.md`](V253.md) (pre-registration + falsifiers) ·
[`V252.md`](V252.md) (scheduler/checkpoint infra) · [`V253_MATIC_POL_REMAP.md`](V253_MATIC_POL_REMAP.md)

> This is the **executable expansion** of the V253 provisioning checklist. Every
> step here runs **on the live host**, by the user, with host access. This document
> does not execute any of them — it is a checklist to follow at the host.
>
> **The single gate at the end:** the daemon refuses to loop unless
> `SCHEDULER_ENABLED=1` (`scripts/live_paper_daemon.py:60`, default OFF). Do **not**
> flip that until steps 1–7 are all ✅ and the 7-day burn-in (step 8) is clean.

## Conventions used below

- **Host assumption:** the `gamma-systems-2` volume is a macOS mount
  (`/Volumes/gamma-systems-2/...`), so the recommended supervisor is **launchd**.
  A **systemd** unit is provided in step 7 for a Linux host — pick one.
- All env is read at process start (`SchedulerConfig.from_env()`,
  `LivePaperConfig`, `os.environ.get("FRED_API_KEY", ...)`). There is **no** dotenv
  loader in the daemon path — env must be present in the supervisor's environment
  (launchd `EnvironmentVariables` / systemd `Environment=` / your shell rc if you
  run it by hand). This is why the plist/unit below set env inline.
- Canonical output root: `OMEGA_AUDIT_OUTPUT_DIR=/Volumes/gamma-systems-2/omega-victoria-data`.
  Everything the daemon writes lands under `$OMEGA_AUDIT_OUTPUT_DIR/live_paper/`
  (`_default_output_dir()` in `omega/live_paper/config.py`): `cache/`, `logs/`,
  `checkpoint/`.
- Throughout, `REPO=~/projects/omega` (adjust to the host's checkout path).

---

## Step 1 — `FRED_API_KEY`

**What it's for.** The DXY (`DTWEXBGS`), VIX (`VIXCLS`), and yield-curve
(`DGS2`/`DGS10`) macro feeds (`omega/nodes/victoria/macro_signals.py`,
`omega/live_paper/feeds.py` MACRO_POLLERS). Without a key the code falls back to
`DEMO_KEY` (30 requests/day — `data_cache.py:104`), which throttles fast and
degrades those three signals to stale/zero-confidence.

**1a. Preconditions**
- A web browser to register (one-time, free, instant).
- The key will be a 32-char lowercase-hex string.

**1b. Obtain the key**
- Go to <https://fred.stlouisfed.org/docs/api/api_key.html>, sign in / create a
  free St. Louis Fed account, click **Request API Key**, fill the short form.
- Copy the 32-char key.

**1c. Set it (pick ONE location — recommend the launchd plist in step 7)**

The codebase reads it straight from the process environment
(`os.getenv("FRED_API_KEY")`, `macro_signals.py:378`; `data_cache.py:104`), with a
secondary fallback to `OmegaConfig.fred_api_key`. So any of these work — put it
where the **supervisor** will see it:

- **launchd (recommended, macOS):** in the `EnvironmentVariables` dict of the plist
  in step 7. This is the load-bearing location for the unattended soak.
- **systemd (Linux):** an `Environment=FRED_API_KEY=...` line, or better an
  `EnvironmentFile=` (step 7).
- **Interactive / burn-in only:** `export FRED_API_KEY=...` in the shell you launch
  the daemon from. Do **not** rely on this for the 90-day soak — a login shell's rc
  is not sourced by launchd/systemd.

**1d. Verify (smoke fetch from Python)**
```bash
cd "$REPO"
FRED_API_KEY=<your_key> python3 - <<'PY'
import os
from omega.nodes.victoria.data_cache import MacroDataCache
assert os.environ.get("FRED_API_KEY","DEMO_KEY") != "DEMO_KEY", "key not in env"
c = MacroDataCache()                      # no DEMO_KEY warning should print
vals = c.get_values("VIXCLS", lookback_days=10)
print("VIXCLS last 10:", vals[-10:])
assert len(vals) >= 3, "FRED returned too few observations — key or egress problem"
print("FRED OK")
PY
```
**Success looks like:** no `FRED_API_KEY not set — using DEMO_KEY` warning, a
non-empty `VIXCLS last 10: [...]` list, and `FRED OK`.

**Failure modes & rollback**
- `... using DEMO_KEY` warning ⇒ key not actually in the process env; re-check the
  location. The soak can technically run degraded on `DEMO_KEY`, but **falsifier #4**
  (regime classifier can't label the window) becomes likely because the macro
  series will be stale. Treat a missing key as a **blocker**, not a warning.
- `HTTP 400`/`403` ⇒ malformed or unactivated key. Re-copy from the FRED dashboard.
- Rollback: unset the key and the code degrades gracefully (no crash) — but do not
  start the soak in that state.

---

## Step 2 — GDELT egress

**What it's for.** The `gdelt_tone_geopolitical` info feed
(`feeds.py` → `fetch_gdelt`, hits `api.gdeltproject.org/api/v2/doc/doc`). GDELT was
**absent** in earlier frozen runs (V238), so the live path is the first time it's
exercised — the host must have egress.

**2a. Preconditions**
- `curl` present. Outbound HTTPS from the host (corporate firewalls often block).

**2b. Test egress**

Two endpoints matter — the **reachability probe** from the V253 checklist and the
**actual feed endpoint** the daemon calls. Test both:
```bash
# Reachability probe (the checklist item):
curl -sS -I --max-time 20 https://data.gdeltproject.org/gdeltv2/masterfilelist.txt | head -1
# Actual live feed endpoint (what fetch_gdelt() hits):
curl -sS -I --max-time 20 "https://api.gdeltproject.org/api/v2/doc/doc?query=bitcoin&mode=tonechart&format=json" | head -1
```
**Success looks like:** each returns `HTTP/2 200` (or `HTTP/1.1 200 OK`). A `200`
on **both** = ✅.

**2c. Verify through the code path (optional but recommended)**
```bash
cd "$REPO"
python3 - <<'PY'
from datetime import date
from omega.live_paper.config import LivePaperConfig
from omega.live_paper import feeds
r = feeds.fetch_gdelt(LivePaperConfig(), date.today())
print("gdelt ok=%s ms=%.0f note=%s" % (r.ok, getattr(r, "elapsed_ms", -1), getattr(r, "note", "")))
PY
```
**Success:** `ok=True`. `ok=False` with an egress note is a soft-fail (GDELT is a
secondary feed) — but log it; >5 consecutive missing days trips **falsifier #2**.

**Failure modes & remediation**
- **Timeout / connection refused** ⇒ corporate firewall blocking outbound HTTPS.
  Remediation: allowlist `*.gdeltproject.org` egress, or run the host outside the
  restricted network.
- **DNS failure** (`Could not resolve host`) ⇒ split-horizon DNS or no resolver;
  fix `/etc/resolv.conf` or the host's DNS.
- **Cert error** (`SSL certificate problem`) ⇒ MITM proxy with a custom CA; install
  the corporate CA bundle or set `CURL_CA_BUNDLE` for the probe (do **not** disable
  verification in the daemon).
- Rollback: GDELT is non-fatal to the soak. If egress can't be fixed, proceed but
  record GDELT as a known-missing feed; the classifier's other series must then
  carry the label (watch falsifier #4 at day-90 close).

---

## Step 3 — `MATIC→POL` remap  ✅ (already done)

**Status:** DONE this session (`355699e`, `V253_MATIC_POL_REMAP.md`). No operator
action. The forward live universe fetches `POLUSDT` (1:1 successor to delisted
`MATIC`, `config.py:_UNIVERSE_ALL`); the frozen backtest is byte-identical because
`ReplayIngestionNode` reads snapshot keys, not this tuple. Nothing to verify at the
host beyond noting the box is checked.

---

## Step 4 — `gamma-systems-2` mount + ≥100 GB free

**What it's for.** All soak artifacts (logs, per-cycle PnL JSONL, daily
checkpoints, the eventual quarterly freeze) route under
`$OMEGA_AUDIT_OUTPUT_DIR/live_paper/`, off the host root disk — the ENOSPC lesson
(RESILIENCY_AUDIT_2026-06).

**4a. Verify the mount is present and writable**
```bash
MNT=/Volumes/gamma-systems-2
test -d "$MNT" && echo "mounted" || echo "NOT MOUNTED"
OUT="$MNT/omega-victoria-data/live_paper"
mkdir -p "$OUT" && touch "$OUT/.writetest" && rm "$OUT/.writetest" && echo "writable"
```
**Success:** `mounted` and `writable`.

**4b. Check free space (need ≥100 GB)**
```bash
df -h /Volumes/gamma-systems-2
```
**Success:** the `Avail` column ≥ 100G.

**Sizing math — how much does the soak actually need?**
- The daemon runs **one cycle/day** (daily bars). Per-cycle writes are tiny:
  - `logs/pnl_curve.jsonl` — a handful of JSON lines/day (few KB/day).
  - `checkpoint/` — one atomic checkpoint/day, pruned to `checkpoint_keep_days=14`
    (`SchedulerConfig`), each on the order of tens of KB.
  - `logs/daemon.out` — INFO logs; a few MB/day depending on feed verbosity.
  - `cache/` — feed caches (macro series + OHLCV), bounded, low tens of MB total.
- **Realistic estimate:** ~5–20 MB/day ⇒ **~0.5–2 GB over the full 90 days**, plus
  the quarterly freeze snapshot (tens of MB). The **100 GB floor is a generous
  safety margin**, not a tight fit — its real purpose is to guarantee the daemon
  never hits ENOSPC mid-cycle (which would corrupt a checkpoint write). If the
  volume is shared with other omega data, 100 GB headroom absorbs that too.

**Failure modes & rollback**
- `NOT MOUNTED` ⇒ remount the volume; a missing mount silently falls back to the
  repo-local `data/live_paper/` (`_default_output_dir()`), which is **wrong for prod**
  (fills the host disk, pollutes the git tree). Fix the mount before starting.
- `<100G Avail` ⇒ free space or attach a larger volume before the soak.

---

## Step 5 — `SCHEDULER_TICK_UTC`

**What it's for.** The daily fire time (`SchedulerConfig.tick_utc`, default
`"04:05:00"`). Validated at construction (`_parse_hms`), so a malformed value fails
loud at startup.

**Recommendation: keep the default `04:05:00` UTC.** Rationale:
- Crypto daily bars close at **00:00 UTC**. FRED/exchange bars for the prior day
  settle in the following hours. `04:05 UTC` gives a **~4h buffer** for
  late-arriving data before the cycle reads it — avoids as-of gaps that would
  degrade the macro feeds or trip falsifier #2.

**Alternatives (only if you have a reason):**
- If you want the daemon's daily activity to land at a **log-friendly local time**,
  pick a UTC time that maps to your timezone — but never earlier than ~02:00 UTC
  (bars not settled) and keep it before the next 00:00 UTC bar. Examples:
  - US Pacific operator wanting ~9pm local: `SCHEDULER_TICK_UTC=05:00:00`.
  - Sydney operator wanting mid-morning local: `04:05:00` UTC ≈ 14:05–15:05 AEST —
    the default already lands in local daytime; leave it.
- Do **not** pick a time in the 00:00–02:00 UTC window — bars may not be settled and
  you invite stale-feed drift.

**Verify** (env parses; no daemon run needed):
```bash
cd "$REPO"
SCHEDULER_TICK_UTC=04:05:00 python3 -c \
 "from omega.live_paper.config import SchedulerConfig as S; c=S.from_env(); print('tick', c.tick_utc, c.tick_hms)"
```
**Success:** prints `tick 04:05:00 (4, 5, 0)`. A malformed value raises `ValueError`
here (that's the intended fail-loud) — fix it before wiring the supervisor.

**Rollback:** unset the var → default `04:05:00`.

---

## Step 6 — Log rotation

**What it's for.** `$OMEGA_LIVE_PAPER_DIR/logs/` accumulates `daemon.out`,
`pnl_curve.jsonl`, and daily logs over 90 days. Rotate daily, keep 90 days.

**Important:** `pnl_curve.jsonl` is the **soak's primary data artifact** and is
**append-only, read by the weekly audit** (`v253_weekly_audit.py`). Do **NOT**
rotate/truncate `pnl_curve.jsonl` — rotate only the noisy `daemon.out`. Rotating
the PnL log would break the equity-curve reconstruction.

**6a. logrotate config** (`/etc/logrotate.d/omega-live-paper`, Linux; on macOS use
`newsyslog` — see 6b):
```
/Volumes/gamma-systems-2/omega-victoria-data/live_paper/logs/daemon.out {
    daily
    rotate 90
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
}
```
`copytruncate` matters: the daemon holds `daemon.out` open (nohup redirect), so
rotate-in-place by truncation rather than rename to avoid losing the file handle.

**6b. macOS newsyslog alternative** (`/etc/newsyslog.d/omega-live-paper.conf`):
```
# logfilename                                                                   [owner:group]   mode  count  size  when  flags
/Volumes/gamma-systems-2/omega-victoria-data/live_paper/logs/daemon.out         :               644   90     *     $D0   GZ
```

**Verify:**
```bash
# Linux:
logrotate -d /etc/logrotate.d/omega-live-paper   # dry-run, prints what it would do
# macOS:
newsyslog -nv                                     # dry-run
```
**Success:** the dry-run lists `daemon.out` as a rotation target with no errors and
does **not** mention `pnl_curve.jsonl`.

**Rollback:** remove the config file; nothing else depends on it.

---

## Step 7 — Supervisor

**What it's for.** Keep the daemon alive across host reboots and crashes for 90+
days. `scripts/live_paper_daemon.sh` is the entrypoint; it PID-guards against a
second writer and `nohup`s the Python daemon.

**Comparison — pick by host OS:**

| Option | Restart on crash | Restart on reboot | Env injection | Verdict |
|---|---|---|---|---|
| `nohup` (bare `live_paper_daemon.sh`) | ✗ | ✗ | shell only | **burn-in only**, not the soak |
| **launchd** (macOS) | ✓ (`KeepAlive`) | ✓ | `EnvironmentVariables` | **recommended for the gamma-mac host** |
| **systemd** (Linux) | ✓ (`Restart=`) | ✓ | `Environment=`/`EnvironmentFile=` | **recommended for a Linux host** |
| docker | ✓ | ✓ | env file | overkill; the daemon needs the gamma mount + host egress, adds mount/network friction for no isolation win |

**7a. launchd — `com.omega.live_paper.plist` (macOS host).**
Provided for reference — **do NOT install it from this session.** The user installs
it at the host: save to `~/Library/LaunchAgents/com.omega.live_paper.plist`, edit
the paths/key, then `launchctl load -w ~/Library/LaunchAgents/com.omega.live_paper.plist`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.omega.live_paper</string>

    <!-- Run the daemon python directly (NOT the .sh wrapper — launchd IS the
         supervisor, so we don't want nohup/disown backgrounding underneath it). -->
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/USER/projects/omega/scripts/live_paper_daemon.py</string>
        <string>--mode</string>
        <string>forward</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/USER/projects/omega</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>SCHEDULER_ENABLED</key>          <string>1</string>
        <key>SCHEDULER_TICK_UTC</key>         <string>04:05:00</string>
        <key>LIVE_PAPER_ENABLED</key>         <string>1</string>
        <key>OMEGA_AUDIT_OUTPUT_DIR</key>     <string>/Volumes/gamma-systems-2/omega-victoria-data</string>
        <key>FRED_API_KEY</key>               <string>REPLACE_WITH_32CHAR_KEY</string>
        <key>PATH</key>                       <string>/opt/homebrew/bin:/usr/bin:/bin</string>
    </dict>

    <!-- Keep alive across crashes AND host reboots. -->
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>

    <!-- Don't hammer-restart on a hard crash loop. -->
    <key>ThrottleInterval</key>
    <integer>30</integer>

    <key>StandardOutPath</key>
    <string>/Volumes/gamma-systems-2/omega-victoria-data/live_paper/logs/launchd.out</string>
    <key>StandardErrorPath</key>
    <string>/Volumes/gamma-systems-2/omega-victoria-data/live_paper/logs/launchd.err</string>
</dict>
</plist>
```
Notes:
- **`SCHEDULER_ENABLED=1` is baked into the plist** — so **do not load `-w` this
  plist until steps 1–6 pass AND the burn-in (step 8) is clean.** For the burn-in,
  run the `.sh` wrapper by hand with `--mode fixture` instead (step 8).
- launchd is the supervisor, so point `ProgramArguments` at the **python script
  directly**, not `live_paper_daemon.sh` (the `.sh` backgrounds+disowns, which would
  make launchd think the job exited). The `.sh` PID-guard is for manual/nohup use.
- Replace `/Users/USER/...` and the FRED key. Keep `<string>` values quoted exactly.

**7b. systemd — `omega-live-paper.service` (Linux host).**
Save to `/etc/systemd/system/omega-live-paper.service`, then
`sudo systemctl daemon-reload && sudo systemctl enable --now omega-live-paper` —
**only after** steps 1–6 + burn-in.

```ini
[Unit]
Description=Omega Victoria live-paper soak daemon (V253)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=omega
WorkingDirectory=/home/omega/projects/omega
# Secrets/env out-of-tree; FRED_API_KEY lives here (chmod 600), not in the unit.
EnvironmentFile=/etc/omega/live_paper.env
Environment=SCHEDULER_ENABLED=1
Environment=SCHEDULER_TICK_UTC=04:05:00
Environment=LIVE_PAPER_ENABLED=1
Environment=OMEGA_AUDIT_OUTPUT_DIR=/mnt/gamma-systems-2/omega-victoria-data
ExecStart=/usr/bin/python3 scripts/live_paper_daemon.py --mode forward
Restart=on-failure
RestartSec=30
StandardOutput=append:/mnt/gamma-systems-2/omega-victoria-data/live_paper/logs/systemd.out
StandardError=append:/mnt/gamma-systems-2/omega-victoria-data/live_paper/logs/systemd.err

[Install]
WantedBy=multi-user.target
```
`/etc/omega/live_paper.env` (chmod 600):
```
FRED_API_KEY=REPLACE_WITH_32CHAR_KEY
```

**Verify (either supervisor), once loaded for the real soak:**
```bash
# macOS:
launchctl list | grep com.omega.live_paper        # non-zero PID, exit code 0
# Linux:
systemctl status omega-live-paper --no-pager       # active (running)
# Both: confirm the LISTEN-free daemon is actually the one you started:
pgrep -fl live_paper_daemon.py
```
**Success:** exactly one `live_paper_daemon.py --mode forward` process, owned by the
supervisor. Two processes ⇒ the `.sh` PID-guard was bypassed; kill the stray (one
writer per checkpoint dir, or checkpoints corrupt).

**Rollback:** `launchctl unload -w ...` / `systemctl disable --now omega-live-paper`.
The last atomic checkpoint is preserved (see abort checklist).

---

## Step 8 — 7-day burn-in (MUST precede the flip)

**What it's for.** The V252 exit criterion: prove the scheduler+checkpoint runs
unattended for 7 days with **zero network** and no drift/gaps, **before** exposing
it to live feeds. Runs the deterministic **fixture** cycle, not `forward`.

**8a. Start the burn-in (fixture, `--allow-disabled` so you don't flip the real gate)**
```bash
cd "$REPO"
SCHEDULER_ENABLED=0 OMEGA_AUDIT_OUTPUT_DIR=/Volumes/gamma-systems-2/omega-victoria-data \
  bash scripts/live_paper_daemon.sh --mode fixture --allow-disabled
```
`--allow-disabled` lets the daemon loop while `SCHEDULER_ENABLED` stays `0` — the
burn-in must **not** flip the production gate. Confirm it started:
```bash
cat /Volumes/gamma-systems-2/omega-victoria-data/live_paper/logs/daemon.pid
pgrep -fl live_paper_daemon.py
```

**8b. What to watch, daily, for 7 days**
- `python3 scripts/v253_weekly_audit.py` at day 7 (or ad-hoc) — expect **zero
  cadence gaps**, **zero checkpoint gaps**, and no drift alert (fixture PnL is
  deterministic, so the curve should be flat/expected).
- `tail -f .../logs/daemon.out` — one INFO cycle line per tick, drift within
  `SCHEDULER_DRIFT_ALERT_SECONDS` (default 60s). Any `drift` WARN over threshold is
  a **halt** trigger.
- Kill-and-restart test (do once, ~day 3): `kill -9 $(cat .../daemon.pid)`, restart
  via the `.sh`, confirm the audit shows the cycle count resumed **byte-identically**
  from the last checkpoint (V252 Test B is the standing proof; a real mismatch is a
  checkpoint-integrity bug → **halt, do not proceed to the soak**).

**8c. Burn-in success = flip criteria**
All of: 7 days elapsed · zero cadence gaps · zero checkpoint gaps · restart resumed
byte-identically · no over-threshold drift WARN. **Only then** proceed to step 9.

---

## Step 9 — Flip to the 90-day soak

**Preconditions:** steps 1–8 all ✅.

1. Stop the burn-in daemon cleanly (see abort checklist — preserve its checkpoint or
   start the soak in a **fresh** output dir; do not mix fixture and forward
   checkpoints in the same `checkpoint/`).
2. Install & load the supervisor (step 7) with `--mode forward` and
   `SCHEDULER_ENABLED=1` baked in.
3. Confirm the first live tick:
   ```bash
   tail -n 20 /Volumes/gamma-systems-2/omega-victoria-data/live_paper/logs/daemon.out
   python3 scripts/v253_weekly_audit.py
   ```
   Expect `mode=forward ... enabled=True` in the startup line and a first
   `pnl_curve.jsonl` entry after the first `04:05 UTC` tick.

**Day-1 → Day-7 checkpoints (catch subtle drift early — check daily):**

| Day | Check | Halt trigger |
|---|---|---|
| 1 | First `forward` cycle logged; `feeds_blocked` count in the cycle line is 0–1 (OHLCV + macro all fetched). | OHLCV blocked, or ≥3 feeds blocked on day 1 (egress regression). |
| 2 | `v253_weekly_audit.py` shows exactly 1 cadence step (1 calendar day). | Cadence gap >1 already (missed tick). |
| 3 | Checkpoint dir has 3 daily checkpoints, no orphans (audit "checkpoint gaps" = 0). | Any checkpoint/log mismatch. |
| 4 | Per-cycle PnL magnitude within the pre-registered band (σ≈$499/cycle; a single cycle far outside ±3σ is worth a look). | Cumulative \|drift\| approaching 5·SE (band ≈ $263/cycle). |
| 5 | GDELT/FRED feeds still `ok=True` (spot-check `daemon.out` for feed WARNs). | Any feed missing ≥5 consecutive days (falsifier #2). |
| 6 | Disk: `df -h /Volumes/gamma-systems-2` still ≫100 GB free; log rotation fired once. | Free space trending toward the floor. |
| 7 | Full weekly audit clean; compare week-1 equity curve against the pre-reg mean. | 5·SE drift alert (falsifier #3 → investigate the **instrument**, not the strategy). |

From week 2 on, drop to the **weekly** cadence in [`V253.md`](V253.md) §"90-day soak
protocol" (weekly audit, monthly reconciliation, day-90 freeze-and-label).

---

## Anti-Goodhart reminder (load-bearing)

The soak is a **MEASUREMENT**. **Do not touch strategy code during the 90 days.** A
>2·SE live-vs-backtest divergence or a 5·SE drift alert is a **FINDING to
investigate** (feed drift? as-of/bar-alignment? code-path divergence?) — never a
strategy edit. Every parked flag (V241/V244/V245/V246/V248) stays **OFF**. See
[`V253.md`](V253.md) §"Anti-Goodhart guard".

---

## Abort checklist — halting V253 partway while preserving state

If you must halt mid-soak (drift finding, host maintenance, falsifier tripped),
preserve everything for later diagnosis. **Never** `git clean`/delete the output
dir.

1. **Stop the supervisor (graceful, not `kill -9` if avoidable):**
   ```bash
   # macOS:  launchctl unload -w ~/Library/LaunchAgents/com.omega.live_paper.plist
   # Linux:  sudo systemctl stop omega-live-paper
   # Manual: kill $(cat $OMEGA_AUDIT_OUTPUT_DIR/live_paper/logs/daemon.pid)   # SIGTERM, lets the cycle finish
   ```
   A clean stop lets the in-flight cycle finish its atomic checkpoint. A `kill -9`
   mid-cycle is *safe* (the checkpoint is atomic — restart replays from the last
   good one) but avoid it when you can.
2. **Snapshot the state read-only, timestamped by the user (scripts can't call
   `date` for you here — run it at the host):**
   ```bash
   TS=$(date -u +%Y%m%dT%H%M%SZ)
   OUT=$OMEGA_AUDIT_OUTPUT_DIR/live_paper
   cp -a "$OUT/checkpoint" "$OUT/checkpoint.halt-$TS"
   cp    "$OUT/logs/pnl_curve.jsonl" "$OUT/logs/pnl_curve.halt-$TS.jsonl"
   ```
3. **Capture the diagnostic read** so the finding is reproducible:
   ```bash
   python3 scripts/v253_weekly_audit.py --json > "$OUT/logs/audit.halt-$TS.json"
   ```
4. **Confirm the daemon is actually down** (no stray writer):
   ```bash
   pgrep -fl live_paper_daemon.py   # expect NOTHING
   ```
5. **Record why** in a one-line note next to the snapshot (which falsifier, what you
   saw). Do **not** edit strategy code as part of the halt.
6. **Resuming later:** re-point the supervisor at the preserved `checkpoint/` (not
   the `.halt-*` copy) and reload. The runner reloads the last atomic checkpoint and
   resumes idempotently (V252 Test B). If you started fresh instead, the 90-day
   window restarts — the halted window does **not** count toward recent-N unless it
   reached a full, labellable 90 days.

---

## One-glance checklist

| # | Item | Gate | Verify cmd (summary) |
|---|---|---|---|
| 1 | `FRED_API_KEY` set | blocker | Python `MacroDataCache().get_values("VIXCLS")` non-empty, no DEMO_KEY warn |
| 2 | GDELT egress | soft (feed) | `curl -I` both endpoints → 200; `fetch_gdelt` ok=True |
| 3 | MATIC→POL remap | ✅ done | n/a (`355699e`) |
| 4 | gamma mount ≥100 GB | blocker | `df -h`, writable touch test |
| 5 | `SCHEDULER_TICK_UTC` | default OK | `SchedulerConfig.from_env().tick_hms` parses |
| 6 | Log rotation | required | `logrotate -d` / `newsyslog -nv` dry-run, excludes pnl_curve |
| 7 | Supervisor (launchd/systemd) | blocker | one `--mode forward` proc under supervisor |
| 8 | 7-day burn-in clean | **gate to flip** | weekly audit: 0 gaps, restart byte-identical |
| 9 | Flip `SCHEDULER_ENABLED=1` | — | `enabled=True` in daemon.out, first pnl entry |

---

## Auditing the live daemon — scheduled-task sandbox limitation

**Scheduled tasks (the `scheduled-tasks` MCP / cron) run in an isolated sandbox
WITHOUT filesystem access to `/Users/benebsworth/projects/omega` or
`/Volumes/gamma-systems-2/`.** A scheduled task therefore **cannot** read the
daemon's checkpoint/pnl output, the repo's training artifacts, or run the weekly
audit against the live paths — it will fail on "no such file / permission denied",
not produce a real audit.

- **To audit the running daemon, use a host-side `start_code_task`** (a Claude Code
  task on the host), **not a scheduled task.** The host task has the working
  directory + gamma volume mounted, so `scripts/v253_weekly_audit.py` and
  `ps eww <pid>` / checkpoint reads work normally.
- **If a scheduled/cron audit is genuinely required** (e.g. unattended weekly
  cadence), it must first be **granted folder access** to those two specific paths
  (`/Users/benebsworth/projects/omega` and `/Volumes/gamma-systems-2/`); until that
  grant exists, the recurring audit belongs in a host-side task instead.
- Rule of thumb: **anything that touches the repo or the gamma volume ⇒ host-side
  task; only network-only / self-contained work is safe to schedule.**
