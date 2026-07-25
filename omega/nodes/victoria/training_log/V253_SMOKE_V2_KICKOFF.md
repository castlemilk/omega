# V253-smoke v2 — 24-hour live-paper run WITH ENTRY WIRE (KICKOFF)

**Launched:** 2026-07-14T02:49:51Z (daemon boot) · first cycle 2026-07-14T02:55:00Z
**Supersedes:** `V253_SMOKE_KICKOFF.md` (runtime-only, no entry path).
**Purpose:** Deliver the user's actual ask — *paper-money trades on live market
data over 24 h*. This run wires the full **SignalGeneration → StrategyNode →
proposals → PaperTradingEngine.execute_proposals** entry path into the V252
forward cycle, so each daily tick can genuinely open/close paper positions. The
prior smoke could only mark-to-market an empty book (0 trades guaranteed, by
design). This one runs the strategy every cycle.

> **Live-paper only.** Simulated fills, no exchange orders, no funds, no broker.

---

## Deliverable 1 — Old daemon killed, new daemon up

| | Old (runtime-only) | New (entry-wired) |
|---|---|---|
| **PID** | 32929 → **killed** (SIGTERM, graceful after cycle, checkpoint preserved) | **20144** (nohup, disowned) |
| Entry path | none (mark-to-market only) | **SignalGeneration → StrategyNode → execute_proposals** |
| Output dir | `…/live_paper_v253_smoke/` | `…/live_paper_v253_smoke_v2/live_paper/` |
| Tick | 02:25:58 UTC | **02:55:00 UTC** (≈5 min after launch → prompt first cycle) |

Old daemon's final checkpoint snapshotted to `harness/v253_smoke_v2/preflight_snapshot/`
before kill (nothing lost; it can be resumed from committed code any time).

---

## Deliverable 2 — Entry wire (shipped)

**Commit `9e5087c`** — `feat(live-paper): wire entry path into V253 forward cycle`.

- **Only `omega/live_paper/runner.py` changed.** `strategy.py`,
  `signal_generation.py`, `features.py`, `reasoning_layer.py`,
  `paper_trading.py` all **untouched** — the engine/nodes are *called, never
  modified*.
- `make_forward_cycle` now mirrors the backtest per-cycle sequence
  (`backtest.py` L217-268) **verbatim**: fetch trailing daily-close **window** per
  symbol → `SignalGenerationNode.execute(COMPUTE_SIGNALS)` →
  `StrategyNode.execute(CONSTRUCT_PORTFOLIO)` → build proposals →
  `execute_proposals` (or `mark_to_market` when no proposals).
- Nodes read feature flags from **`VICTORIA_FEATURES`** (identical env contract to
  `run_training.py`); the daemon is launched with the V240-selective baseline.
- Exit timing pinned to `_FORWARD_HOLD_CYCLES=5` (same technique as the backtest's
  `_BT_HOLD_CYCLES` pin) → a cycle is **idempotent** on `(feeds, prior state)`.
- Strategy modules imported **lazily inside the cycle**, so the runner module
  itself stays strategy-free (fixture/retrospective paths never import them).

---

## Deliverable 3 — Verification BEFORE relaunch (hard gate)

### (a) V251 sentinel reconciliation — **PASS, $0.00 × 3**

`scripts/v252_reconcile_smoke.py` replays the 3 sentinel windows through the
UNCHANGED `make_retrospective_cycle` (the only path that produces those numbers —
a 60-cycle backtest shell-out, NOT the forward cycle):

| window | regime | V251 | replay | Δ | trades |
|---|---|---|---|---|---|
| snap_wf_20240310 | crisis | $1,149.76 | $1,149.76 | **$0.00** | 9 |
| snap_wf_20230912 | trend | $4,679.67 | $4,679.67 | **$0.00** | 6 |
| snap_wf_20250305 | recent | $771.98 | $771.98 | **$0.00** | 13 |

⇒ The entry wire did **not** perturb backtest byte-identity. Reconciliation
preserved.

> **Why the forward path isn't the sentinel path.** The sentinels are the SUM over
> a **60-cycle windowed backtest** of a frozen snapshot. The forward cycle marks
> **one live day**. They are categorically different computations — the forward
> cycle cannot (and is not meant to) reproduce a 60-cycle aggregate. "Preserve
> V251 reconciliation" means *don't break the retrospective replay*, which is what
> the $0.00 × 3 above proves.

### (b) Forward-wire self-checks — **PASS**

`harness/v253_smoke_v2/verify_forward_wire.py` (monkeypatched feeds, no network):
- **Idempotency:** two cycles on identical feeds + prior state → **byte-identical**
  positions / equity / realised PnL. ✅
- **End-to-end fills:** on a controlled trending window the wire produced
  **6 proposals → 3 fills** (ETH/NEAR/SOL). ✅ — proves the strategy step runs and
  *can* open paper positions.

---

## Deliverable 4 — First live cycle (executed + verified)

**Cycle `2026-07-14T02:55:00.005Z`** — fired unattended by the daemon:

| Check | Result |
|---|---|
| Scheduler drift | **0.005 s** (threshold 60 s) ✅ |
| Feeds fetched | **10/10 OK** — `feeds_blocked: []` ✅ (live: F&G=22, VIX=17.16, 10y-2y=68.8bp, Binance klines) |
| **Signals computed** | `signals_ok: true` ✅ — the entry path RAN (old smoke never did) |
| **Strategy executed** | `strategy_ok: true` ✅ (V223 IC-gate + V45 relative thresholds logged) |
| Proposals | **0** — no live conviction breach this cycle |
| Paper fills | **0** (no proposals → mark-to-market only) |
| Checkpoint | `2026-07-14.json`, MD5 `83ac298fdec3f33b72e28fb76bec53a1` — **sidecar match** ✅ |
| Equity | `$100,000 → $100,000` (flat — no fills) |
| Audit | `v253_weekly_audit.py`: 1 cycle, no cadence/checkpoint gaps, drift within band ✅ |

**0 fills here is expected, not a bug:** it means the strategy ran and *chose not
to trade* on this cycle's live signal. That is a real strategy decision now — under
the old smoke there was no strategy at all.

---

## Deliverable 5 — 24-hour monitoring handoff

```bash
SMOKE=/Volumes/gamma-systems-2/omega-victoria-data/live_paper_v253_smoke_v2
```

**Is the daemon alive?**
```bash
ps -p "$(cat "$SMOKE/live_paper/logs/daemon.pid")" -o pid,stat,etime,command
```

**Watch the log:**
```bash
tail -f "$SMOKE/live_paper/logs/daemon.out"
```

**Read-only audit anytime:**
```bash
python3 scripts/v253_weekly_audit.py \
  --pnl-log "$SMOKE/live_paper/logs/pnl_curve.jsonl" \
  --checkpoint-dir "$SMOKE/live_paper/checkpoint"
```

**Abort cleanly (checkpoint authoritative; resumes idempotently):**
```bash
kill -TERM "$(cat "$SMOKE/live_paper/logs/daemon.pid")"
```

### What to expect over 24 h
- **1–2 scheduler ticks.** First (02:55:00 UTC 2026-07-14) done; next 02:55:00 UTC
  2026-07-15 (≈24 h, window edge).
- Each tick: fetch 10-name universe from Binance → compute signals → run strategy →
  maybe open/close paper positions → checkpoint → append one PnL line.
- **0 fills on a given cycle is normal** (strategy declined). Equity moves only when
  a paper position opens and later closes.

### What to look for
- **The first REAL fill** — a PnL line with `fills_opened > 0` / non-empty
  `trade_symbols`, then later a `closed_this_cycle > 0` with a non-zero
  `realised_pnl`. *That* is "a paper trade actually happened."
- Anomalies: `Traceback`/`ERROR` in `daemon.out` or PID gone → died;
  `feeds_blocked` non-empty → a Binance fetch failed; `forward_entry_error` event →
  strategy raised (wire catches it, logs, continues with 0 proposals);
  `CheckpointCorruption` on boot → MD5 mismatch (daemon refuses by design).

### Honest caveat (fill frequency)
The live poller returns a **thin ~10-bar** daily-close window (`feeds.fetch_ohlcv`
`limit=10`), and macro feeds run on `DEMO_KEY` (no `FRED_API_KEY`). Signal
indicators are therefore shallow, so live cycles may frequently produce 0
proposals — the wire is *proven* to fill when signals breach (Deliverable 3b), but
a breach may not occur within 1–2 live cycles. **Follow-up to raise fill rate
(out of scope here): deepen the live OHLCV window** (`limit` → ≥40) and provision
`FRED_API_KEY`. Neither touches strategy code.

---

## Guardrails honored
- ✅ Only `runner.py` changed. No strategy/signal/engine/features/reasoning code edited.
- ✅ Live-**paper** only. No broker, no orders, no funds.
- ✅ Sentinel reconciliation re-verified bit-exact ($0.00 × 3) **before** relaunch.
- ✅ Forward wire proven idempotent + able to fill before relaunch.
- ✅ Frozen-path guard (`assert_live_source`) intact — live pollers never read frozen.

---

## Addendum — Poller bumped to 60-bar window (2026-07-14 03:43 UTC)

**Poller bumped to 60-bar window at 03:43 UTC, daemon restarted, new PID 81481.**

The "Honest caveat" follow-up above (deepen the live OHLCV window `limit` → ≥40)
was executed. The live OHLCV poller window was deepened **10 → 60 bars** to match
the backtest signal-window depth, so per-name signal indicators see enough history
to produce proposals.

- **Change (poller config only, no strategy code):** promoted the inline
  `limit=10` in `feeds._binance_klines_close` to a named constant
  `LIVE_PAPER_OHLCV_WINDOW = 60` in `omega/live_paper/config.py`, referenced from
  the poller. Two files: `config.py` (+constant), `feeds.py` (import + default).
  `strategy.py`/`signal_generation.py`/`features.py`/`paper_trading.py`/
  `reasoning_layer.py` all **untouched**.
- **Sentinel reconciliation (hard gate) — PASS, $0.00 × 3, surfaced BEFORE
  restart:** crisis $1,149.76 / trend $4,679.67 / recent $771.98, all Δ=$0.00 vs
  V251 (`scripts/v252_reconcile_smoke.py`). The bump is structurally unreachable
  from the frozen backtest path (`_binance_klines_close` ← `fetch_ohlcv` ← live
  forward cycle + smoke only; the eval reads frozen snapshots and never imports
  `omega.live_paper.feeds`), so byte-identity is preserved — now proven empirically
  too.
- **60-bar depth verified end-to-end (standalone one-shot, no checkpoint write):**
  all 10 universe symbols return exactly **60 bars** (min 60, all ≥60), and the
  forward cycle produced **6 proposals → 2 fills** (ARBUSDT, POLUSDT) — vs **0
  proposals** on the ~10-bar first cycle (Deliverable 4). The deeper history is
  exactly what unblocks proposals.
- **Daemon restart:** PID 20144 → `kill -TERM` (graceful, `runner_shutdown
  cycles:1`, checkpoint `2026-07-14.json` preserved) → relaunched as **PID 81481**
  (same output dir → history continues; `checkpoint_loaded last_completed_date=
  2026-07-14`, `runner_resumed`). Same tick **02:55:00 UTC**, `enabled=True`,
  V240-selective `VICTORIA_FEATURES`.
- **First real daemon cycle:** the scheduler idempotency guard (no same-day
  double-run) advances to the day after `last_completed`, so the next daemon cycle
  fires **2026-07-15 02:55 UTC** (before the 03:15Z audit) — the first cycle to run
  the strategy on the 60-bar window inside the daemon loop. Materially higher
  chance of live fills than the ~10-bar first cycle.

> `FRED_API_KEY` still unset (macro on `DEMO_KEY`) — the other half of the
> fill-rate follow-up, deferred (host-provisioning, not a code change).

---

## Addendum — `FRED_API_KEY` provisioned, daemon restarted (2026-07-15 01:01 UTC)

The second half of the fill-rate follow-up (host-provisioning, no code change) is
now done: a real `FRED_API_KEY` was set so the macro FRED path (yield_curve /
VIX / DXY) resolves live instead of degrading on `DEMO_KEY`.

- **Key set** in `harness/.env` (gitignored — `.gitignore:68`, `git check-ignore`
  confirmed). The key value is **not** recorded here or anywhere in-tree. No prior
  key existed (no entry in `harness/.env`, shell rc, or the old daemon's env) — this
  is a first-time provision, not a rotation.
- **No dotenv autoload** in the runner (`os.environ.get` only), so the key was
  injected by sourcing `harness/.env` into the launch shell before `nohup`.
- **Daemon restarted** to pick up the key from its boot env (Python snapshots env
  at start): old **PID 81481** → `kill -TERM` (graceful — `scheduler_shutdown_signal
  signum 15` → `runner_shutdown cycles:0` → clean exit, no in-flight cycle lost) →
  relaunched via `scripts/live_paper_daemon.sh --mode forward` as **PID 68916**.
  Same output dir → `checkpoint_loaded last_completed_date=2026-07-14`,
  `runner_resumed` (history continues), same tick **02:55:00 UTC**, `enabled=True`,
  V240-selective `VICTORIA_FEATURES` reproduced
  (`universe_selective_enabled` + adopted-baseline defaults).
- **FRED live-fetch smoke — PASS (provider=fred, no failover, no DEMO):** in the
  daemon's launch env, `fetch_vix`/`fetch_dxy`/`fetch_yield_curve` all resolve via
  FRED — VIX 17.16, DXY 120.50, **10y-2y spread 0.36** (DGS10-DGS2, latest
  2026-07-13). yield_curve previously unreachable on `DEMO_KEY` (400).
- **Next daemon tick 2026-07-15 02:55 UTC** will run the strategy with the macro
  FRED feeds live; the 03:15Z audit will now see yield_curve/VIX/DXY as working
  feeds rather than blocked/degraded.

---

## Addendum — `hmmlearn 0.3.3` picked up via graceful restart (2026-07-15 08:07 UTC)

`hmmlearn 0.3.3` was installed into the daemon's Homebrew Python 3.14
site-packages. `omega.nodes.victoria.hmm_regime` selects its backend at
**module-import time** (`try: from hmmlearn import hmm`), so only a fresh process
picks it up. The daemon was restarted to load it, preserving the open book.

- **Graceful restart (checkpoint-preserved):** old **PID 68916** → `kill -TERM`
  (`scheduler_shutdown_signal signum 15` → `runner_shutdown cycles:1` → clean exit,
  no in-flight cycle lost, PID gone in 13 s) → relaunched via
  `scripts/live_paper_daemon.sh --mode forward` as **PID 38468**. Same output dir,
  same tick **02:55:00 UTC**, `enabled=True`, launch env reproduced: `harness/.env`
  sourced (real `FRED_API_KEY` + `DATABASE_URL`), `OMEGA_AUDIT_OUTPUT_DIR` =
  `…/live_paper_v253_smoke_v2`, V240-selective `VICTORIA_FEATURES`
  (`crisis_skew_enabled` + `crisis_skew_regime_gate_enabled` + dd 0.12 +
  `universe_selective_enabled`, all else the adopted defaults —
  matches `scripts/v252_reconcile_smoke.py`).
- **Position preservation — CONFIRMED, zero loss.** Checkpoint `2026-07-15.json`
  MD5 **`245f5ee0961e39f9044abc3345611036`** byte-identical before → after restart
  (backed up to `/tmp/omega_ckpt_backup_2026-07-15.json`). Runner logged
  `runner_resumed from_date=2026-07-15 equity=100000.0 open_positions=2`. Both
  positions intact: **ARBUSDT** (long, entry 0.0906, size 10 699.93, db_id 75088)
  + **POLUSDT** (long, entry 0.08447, size 8985.30, db_id 75089), both
  `cycle_opened=2` / **`exit_at_cycle=7`** (hold schedule preserved via the
  checkpoint + the `_FORWARD_HOLD_CYCLES=5` code pin). `closed_trades: []` — nothing
  force-closed. `cycle_n=2` unchanged.
- **hmmlearn now ACTIVE (verified):** in the daemon's Python,
  `hmm_regime._HMMLEARN_AVAILABLE = True`, `GaussianHMM` reachable, and the
  import-time `"hmmlearn not available — using numpy GMM fallback"` warning **no
  longer fires** (it was present on the 07-15 cycle under PID 68916). The daemon
  will fit the real 3-state `GaussianHMM` instead of the numpy GMM from the next
  cycle on.

### Regime classification status: **STILL `"unknown"` — and hmmlearn does NOT change that (architectural, not a missing-dep issue)**

The premise "hmmlearn → real regime instead of `unknown`" does **not** hold for the
live-paper path. Traced + empirically confirmed:

- The pnl_record / checkpoint `regime` comes from **`runner.py:399`**
  `regime = str(signals.get("_regime", "unknown"))`, where `signals` is the result
  of **`SignalGenerationNode.execute(COMPUTE_SIGNALS)`** (the lightweight node the
  live-paper `make_forward_cycle` calls directly).
- `signals["_regime"]` is set **only** in the full `victoria_node` DAG
  (`victoria_node.py:1471` / `:2297`), where it derives from the **Wasserstein**
  regime detector (`victoria_node.py:1267 regime = _w_result.regime`) + VRP mapping
  — **not** the HMM. `SignalGenerationNode` never emits `_regime` (empirically:
  its result dict has zero `_`-prefixed meta keys), so the runner's `.get` always
  falls through to `"unknown"`.
- The **HMM detector** (the thing hmmlearn accelerates) is a separate Wave-1
  *signal* inside `victoria_node`'s DAG emitting **`bull`/`bear`/`sideways`** — a
  different taxonomy from the strategy regime, and also never invoked by the
  live-paper path.

⇒ **The next cycle will still log `regime="unknown"`.** hmmlearn is now correctly
active (fallback gone), which is the right thing to have fixed, but it is not the
lever for this field. Making the live-paper cycle emit a real regime label would
require routing it through the full `victoria_node` DAG (or attaching a regime in
the runner) — a **strategy/runner code change, out of scope here** (guardrail: no
strategy code touched). Filed as the real follow-up.

**Guardrails honored:** no strategy/signal/engine code touched (restart + env only),
live-**paper** only (no broker/orders/funds), open book preserved byte-identical.

---

## Addendum — regime wire SHIPPED, `regime="unknown"` RESOLVED (2026-07-15 10:18 UTC)

The follow-up filed above ("attach a regime in the runner") is now **done**. The
live-paper cycle emits a real HMM regime label instead of `"unknown"`.

- **Commit:** `b699dcd` — `feat(live-paper): wire real regime into make_forward_cycle (V253)`.
  Runner-only change (guardrail honored: **no** edits to `strategy.py`,
  `signal_generation.py`, `features.py`, `paper_trading.py`, or the Wasserstein/HMM
  detector code — the standalone `HMMRegimeDetector` in `hmm_regime.py` is imported
  and called, never modified).
- **What it does.** In `make_forward_cycle`, after the OHLCV fetch: (a) fetch a
  **BTCUSDT** close window explicitly (the V240-selective live universe blacklists
  BTC from *trading*, so `market_data` has no BTC — this fetch is **regime-only**,
  never enters `market_data`/proposals, BTC stays untraded); (b) fit the 3-state
  Gaussian HMM (`hmmlearn` 0.3.3, `random_state=42`) on it and inject
  `signals["_regime"]` + `signals["_regime_hmm"]` (`setdefault`, additive) so
  `StrategyNode._apply_regime_adaptive_thresholds` reads a real
  `{bull,bear,sideways}` label; (c) surface `regime_source` + `regime_probs` in the
  pnl log. This is why the earlier "hmmlearn isn't the lever" diagnosis was correct —
  the lever is the *runner attaching a regime*, which is what this commit adds. It
  routes the HMM detector (`bull`/`bear`/`sideways`), **not** the full DAG's VRP+
  Wasserstein consolidated label; a deliberate, minimal wire.

- **Determinism gate — V251 sentinels $0.0000 arm-Δ ×3 (re-run twice, after each
  runner edit):** crisis `snap_wf_20240310` $1,149.76, trend `snap_wf_20230912`
  $4,679.67, recent `snap_wf_20250305` $771.98 — all MATCH, verdict PASS.
  `make_forward_cycle` is not on the retrospective/backtest path (V251 replays via
  `make_retrospective_cycle` → `run_training.py --backtest-snapshot`), so the wire
  cannot perturb backtest fidelity — confirmed empirically.

- **Graceful restart (checkpoint-preserved):** old **PID 38468** → `kill -TERM`
  (`scheduler_shutdown_signal signum 15` → `runner_shutdown cycles:0`, idle-wait,
  no in-flight cycle lost, exited ~1 s) → relaunched via
  `scripts/live_paper_daemon.sh --mode forward` as **PID 53422** (restart
  **2026-07-15T10:18:02Z**). Same output dir (`…/live_paper_v253_smoke_v2`), same
  tick **02:55:00 UTC**, `enabled=True`, same launch env (`harness/.env` sourced +
  V240-selective `VICTORIA_FEATURES`, matching `scripts/v252_reconcile_smoke.py`).
- **Position preservation — CONFIRMED, zero loss.** Checkpoint `2026-07-15.json`
  MD5 **`245f5ee0961e39f9044abc3345611036`** byte-identical before → after restart
  (backup `/tmp/omega_ckpt_backup_2026-07-15_regimewire.json`). Runner logged
  `runner_resumed from_date=2026-07-15 equity=100000.0 open_positions=2` — both
  **ARBUSDT** + **POLUSDT** intact, `exit_at_cycle=7` preserved.
- **Regime classification — CONFIRMED WORKING (daemon-path proof).** A one-shot
  `--max-cycles 1` run through the **full daemon entrypoint** (scheduler → checkpoint
  → runner → cycle → pnl log) in a scratch dir emitted the pnl line:
  `regime="sideways"`, `regime_source="hmm"` (fitted `GaussianHMM`, **not** the numpy
  fallback — verified `isinstance(model, hmmlearn.hmm.GaussianHMM)`),
  `regime_probs={bull 0.333, bear 0.0, sideways 0.667}`, `signals_ok`+`strategy_ok`
  true — vs. the prod daemon's prior lines that logged `regime="unknown"` with no
  regime fields. The current market read (BTC sideways-to-mildly-bull) is consistent
  with VIX 17 / F&G 22. The running prod daemon (PID 53422, identical code) will emit
  the real regime on its **next scheduled cycle, 2026-07-16 02:55:00 UTC**.

**Guardrails honored (regime wire):** only `runner.py` touched; live-**paper** only
(no broker/orders/funds); V251 backtest fidelity preserved ($0.0000 ×3); open book
preserved byte-identical (MD5 unchanged, 2 positions resumed).

---

## Addendum — reboot outage + daemon recovery from the 07-17 checkpoint (2026-07-25 07:16 UTC)

The soak daemon was **DEAD for 7.7 days**. A host reboot killed it and nothing
brought it back: `nohup` survives a logout but not a shutdown, and no supervisor
was installed at the time. Recovery below is **resume-and-note**, not backfill —
the lost cycles stay lost, on the record.

### The outage

- **Last good cycle:** `2026-07-17 02:55:00 UTC` — checkpoint `2026-07-17.json`,
  MD5 **`0e687729471458f9aed1c9ac949e7943`**, equity **$99,433.31**, realised
  **−$616.93**, 3 open positions.
- **Death:** `2026-07-17T22:38:32+1000` — `scheduler_shutdown_signal signum 15`
  → `graceful shutdown after current cycle`. The **OS shutdown sent SIGTERM**, so
  the daemon exited *cleanly*; no cycle was lost mid-flight and no state was
  corrupted. The Mac rebooted at **22:47 AEST**.
- **Nothing restarted it.** All prior daemon PIDs (20144 / 68916 / 38468 / 53422)
  are dead; `logs/daemon.pid` still read **53422** (stale — `kill -0` = no such
  process). Removed before relaunch.
- **Missing window: 2026-07-18 → 2026-07-25 inclusive — 8 scheduled ticks,
  ~7.7 days.**

### What the gap costs (honest accounting)

The strategy resumed **from the state as of 2026-07-17**, *not* from the state it
would have had if it had been running. Concretely:

- The 8 cycles that would have fired never fired. Any entries, exits, stop-loss
  closes or mark-to-market moves in that window **do not exist and cannot be
  reconstructed** — the live-paper path is a forward-only feed, not a replayable
  snapshot.
- The 3 open positions were carried across the gap at their **07-17 entry marks**
  with their **07-17 `exit_at_cycle` hold schedules** (cycle-indexed, not
  date-indexed), so they resume as if no time passed. They are now stale relative
  to real price action.
- **The soak's recent-N accrual pauses at the 07-17 count** — the gap contributes
  0 windows toward the `recent-N >= 20` resume gate.
- The scheduler **does not backfill**: `DailyScheduler.next_target` picks
  `max(tomorrow, last_completed+1)` and returns a single future instant — there is
  no catch-up loop, so no synthetic cycles were fabricated against today's feeds.
  Verified: next target **2026-07-26 02:55:00 UTC**.

### Recovery (Part A)

- **Preflight:** `prepare_session.sh` clean (`2248c4e`, branch main); gamma mount
  reachable; checkpoint `2026-07-17.json` MD5-verified against its `.md5` sidecar
  (match); `ps` showed **no** surviving live_paper process; stale `daemon.pid`
  removed; checkpoint backed up to
  `/tmp/omega_ckpt_backup_2026-07-17_prereboot.json`.
- **Relaunch:** `scripts/live_paper_daemon.sh --mode forward`, launch env
  reproduced exactly as the last known-good start — `harness/.env` sourced (real
  `FRED_API_KEY` (32 chars) + `DATABASE_URL`), `OMEGA_AUDIT_OUTPUT_DIR` =
  `…/live_paper_v253_smoke_v2`, `LIVE_PAPER_ENABLED=1`, `SCHEDULER_ENABLED=1`,
  `SCHEDULER_TICK_UTC=02:55:00`, V240-selective `VICTORIA_FEATURES`
  (`crisis_skew_enabled` + `crisis_skew_regime_gate_enabled` + dd 0.12 +
  `universe_selective_enabled`, all else adopted defaults — matches
  `scripts/v252_reconcile_smoke.py`). New **PID 31927**
  (start `2026-07-25T07:16:35Z`).
- **Resume — CONFIRMED:** `checkpoint_loaded last_completed_date=2026-07-17
  equity=99433.31` → `runner_resumed from_date=2026-07-17 equity=99433.31
  open_positions=3`. All three recovered:

  | symbol | side | entry | size | opened | exit_at_cycle |
  |---|---|---|---|---|---|
  | ARBUSDT | long | 0.0877 | 5 507.91 | 2026-07-16 | 8 |
  | ETHUSDT | long | 1844.24 | 3 265.32 | 2026-07-17 | 9 |
  | POLUSDT | long | 0.08189 | 7 506.71 | 2026-07-17 | 9 |

- **Live-cycle proof (scratch dir, prod checkpoint untouched):** a one-shot
  `--max-cycles 1 --mode forward` through the full daemon entrypoint returned
  `feeds_blocked=[]`, `signals_ok=true`, `strategy_ok=true`,
  `regime="bull" regime_source="hmm"` (hmmlearn `GaussianHMM` fitted,
  `fit_quality=2.4221`), **4 proposals → 3 fills**, checkpoint written and its MD5
  re-verified against the sidecar. FRED resolves live (DGS2 4.37 / DGS10 4.71 @
  2026-07-23, DXY 120.53, VIX 18.58) — no `DEMO_KEY` degradation. Prod checkpoint
  MD5 `0e6877…7943` **unchanged** by the probe; scratch dir deleted after.
- **One writer:** `pgrep -fl live_paper_daemon.py` → exactly one process (31927).

**Guardrails honored:** zero strategy code touched (operational recovery only);
live-**paper** only, no broker/orders/funds; checkpoint state preserved, never
wiped; single daemon process.
