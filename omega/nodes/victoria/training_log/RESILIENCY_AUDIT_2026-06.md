# Resiliency audit — session-to-session continuity & eval reliability (2026-06)

**Date:** 2026-06-20
**Author:** claude
**Context:** The V222, V224, V226, V227 orchestrating sessions all died to laptop
restarts mid-iteration. Background `nohup` grids **survive** (the training
processes are robust), but the **orchestrating Claude session dies**, and each
recovery has cost 1-3h of re-discovery (which cells ran, what step we were at,
what the next action was). This audit finds NOVEL methods to harden the
*session/orchestration* layer — the part the existing machinery does NOT cover.

## What already exists (so we don't duplicate)

The **training-cycle layer is robust**; the **session/grid-orchestration layer is
fragile**. Inventory:

| Concern | Exists today | File |
|---|---|---|
| Per-cycle progress | `data/{ver}_progress.json` (rewritten every log_interval), `/tmp/{ver}_metrics.jsonl` (append, per-cycle) | `run_training.py:1617`, `:1478` |
| Replicate liveness | PID file + post-run `kill -0` cleanup | `check_determinism.sh:40,162` |
| Grid status (manual) | read-only PID/summary inspector | `scripts/v218_matrix_status.sh` |
| Git-lock recovery | kills stray git, removes stale locks, hardens fsmonitor | `scripts/prepare_session.sh` |
| Exit cleanup | `try/finally` flushes file handles (runs on SIGTERM via Python) | `run_training.py:1655` |
| Cache integrity | `.cache_manifest.json` md5s, verified at startup; abort on drift | `run_training.py:_v219_substrate_preflight`, `build_cache_manifest.py` |
| Wall-clock / HTTP tripwires | AST preflights wired into the determinism gate | `check_no_wallclock.py`, `check_frozen_http_fence.py` |
| Cell identity | asserts run matches its label (skew/IC/gate) | `assert_cell_identity.py` |
| Magnitude-FAIL auto-diff | auto trade_field_diff on FAIL ∧ trade_Δ=0 ∧ N≥2 | `check_determinism.sh:140` |
| Single-chain orchestrator | `overnight_loop.py` (polls vN, applies adjustments, launches vN+1) | `scripts/overnight_loop.py` |

**The gap is structural, not cyclic:** nothing persists "where the *orchestrator*
is," nothing resumes a killed *run* from cycle N (only forensic snapshots exist),
nothing detects a dead orchestrator and relaunches, and `results.json` did not (until
this audit) record the git/cache substrate it was produced from.

---

## The eight proposals

For each: **mechanism**, **effort** (S ≤ ~1h, M ≤ ~half-day, L ≥ ~1 day), **payoff**
(V### iterations saved / pain removed), **ship-now vs queue**.

### #1 — Checkpointing / resume-from-cycle
**Mechanism:** write each replicate's engine state (`open_trades`, `closed_trades`,
`realised_pnl`, RNG/`_signal_history` state, current cycle) to
`data/v###_checkpoint_<cell>_<replicate>.json` every N cycles; add
`--resume-from-checkpoint` to `run_training.py` that restores it and skips to cycle
N+1. **Effort: L** — the hard part is faithfully serializing & restoring *engine
state* (open positions, rolling signal history, RNG) such that the resumed run is
**byte-identical** to an un-killed one. Anything less re-opens a determinism channel
(the whole V211→V221 arc). **Payoff:** ~0.5-1 iteration saved per restart, but **high
risk** — a subtly-wrong restore silently corrupts the determinism guarantee that
took 11 versions to earn. **Queue (P3, high-risk).** Only worth it if restarts become
more frequent than ~1/grid; the cheaper #2/#4 recover *most* of the value at far
lower risk.

### #2 — Dead-orchestrator detection + auto-restart
**Mechanism:** `scripts/v###_supervisor.sh` launched under its own `nohup`,
independent of the Claude session. It watches the grid orchestrator PID; if the PID
is dead AND not all `summary.json` cells exist, it relaunches the grid (which is
idempotent per-cell: completed cells' results already on disk are skipped/overwritten
identically). Distinguishes "killed" from "completed" via a sentinel file
(`data/v###_grid.done`) written on clean exit + the orchestrator's exit code.
**Effort: M.** **Payoff:** ~1-2 iterations saved per restart-heavy stretch — the grid
self-heals instead of waiting for a human to notice. **Queue (P1)** — highest-value
queued item; pairs naturally with #3 (the supervisor updates the same manifest). Not
shipped now only because it needs a short idempotency audit of `check_determinism.sh`
re-entry (does re-running a half-done cell clobber a good summary?).

### #3 — Session-continuity manifest ✅ **SHIPPED**
**Mechanism:** `data/SESSION_STATE.json` recording `version`, `step`, `next_action`,
`last_commit`, `updated_at`, live grid PIDs, and a grid-log tail; surfaced
automatically at the top of every session by `prepare_session.sh`. **Effort: S.**
**Payoff:** removes the single biggest recovery cost — re-deriving "where were we."
Every V### recovery prompt we hand-wrote (V222/V224/V226/V227) is replaced by one file
the mandatory preflight prints. **Shipped this version** (see below).

### #4 — OS-level signal handler (SIGTERM/SIGHUP flush)
**Mechanism:** register `signal.signal(SIGTERM/SIGHUP, …)` + `atexit` in
`run_training.py` to flush the latest progress/checkpoint to disk before exit. macOS
restart sends SIGTERM to user processes first; catching it snapshots in-flight state.
**Effort: S-M.** **Payoff:** complements #1 (without a resume reader the flush is only
forensic) — but **on its own** it upgrades the progress snapshot from "last
log_interval boundary" to "the exact cycle the kill hit," which sharpens any manual
recovery. The current `try/finally` already runs on SIGTERM for *file-handle* cleanup,
but does NOT force a progress write. **Queue (P2)** — cheap, low-risk, high-clarity;
ship alongside #1 or #2 so the flushed state has a consumer.

### #5 — Run-artifact provenance manifest ✅ **SHIPPED**
**Mechanism:** embed a `"provenance"` block in every `results.json`: git SHA +
dirty-flag, frozen-cache md5s (the V219 manifest), resolved feature flags, snapshot
path, frozen/R3 env, and cell label. **Effort: S.** **Payoff:** catches the
**V218-class** failure — V217 claimed a hermetic baseline that silently depended on an
*uncommitted* macro cache, unreproducible from a clean checkout. With provenance
embedded, every result self-certifies "this PnL came from commit X + cache md5s Y";
a `git_dirty:true` or drifted md5 is visible without re-deriving it. Easily ~1-2
iterations saved per occurrence (V218 burned a whole version on exactly this).
**Shipped this version** (see below).

### #6 — Pre-grid sanity test (1-cell × 1-cycle wiring smoke)
**Mechanism:** institutionalize the V227 informal practice — before launching the
full 6-cell × N=2 × 200-cycle grid, run a 1-cell × ~5-cycle stack-ON smoke that
asserts the new code path actually fires (skew_on/ic_on counters > 0, AST preflights
green) and aborts the grid launch on failure. **Effort: S.** **Payoff:** catches
integration bugs (silent-inert flag, syntax error, mis-wired env) in ~1 min instead of
40 min into the first cell — saves a partial-grid re-run, ~0.3 iteration each time a
wiring bug slips. **Queue (P2)** — would have been shipped here, but V228's smoke (run
manually this session, `data/v228_smoke_*`) already served the purpose; formalize as
`scripts/pre_grid_smoke.sh` next version.

### #7 — Multi-snapshot determinism canary (held-out 4th snapshot)
**Mechanism:** at the start of every grid, run a 10-cycle hermetic check on a **4th
held-out snapshot** (e.g. `snap_crisis_2020q1`, the V218.E window). If it FAILs, the
eval substrate has drifted — abort before burning the full grid. **Effort: M.**
**Payoff:** would have caught the V216/V219/V220 channel resurfacings *before* a 12-run
grid measured noise instead of signal — ~1 iteration per latent-channel surprise.
**Queue (P2).** Slight tension: a held-out snapshot the strategy never trains on is
the cleanest canary, but adds ~2 min/grid; worth it given how often a new channel has
surfaced mid-grid (V216, V219, V220, V226).

### #8 — Wedge detection in the dispatch orchestrator (the Workflow-wedge class)
**Mechanism:** the Workflow tool wedged and killed the V226 + V227-first-attempt
sessions (>10 min no return). A watchdog heuristic — "no Bash activity for >5 min AND
no Workflow return AND no human message → self-abort and fall back to single-agent" —
would bound that loss. **Effort: L** and **mostly outside the repo** (it's a property
of the dispatch harness, not Victoria code). **Payoff:** real (two sessions lost), but
the cheap mitigation already in force is procedural: the operator's standing rule
"abandon Workflow after 10 min, go single-agent" (used successfully this session — the
Plan+Explore scouting ran as parallel `Agent` calls, not the Workflow wrapper).
**Queue (P3, mostly out-of-repo)** — document the procedural rule; a real watchdog is a
harness feature request, not a Victoria deliverable.

---

## Shipped this version (the 2 picks)

Per the default picks — **#5 (provenance, extends V219's manifest pattern)** + **#3
(session continuity, directly attacks the laptop-restart pain)**:

### #5 — provenance manifest → `results.json["provenance"]`
- `scripts/run_training.py`: new module-level `_run_provenance(version, snapshot,
  active_flags)` (best-effort, never raises — provenance is metadata, not compute) and
  a `"provenance"` block wired into the `results` dict.
- Records: `git_sha`, `git_dirty`, `cache_manifest` (the V219 file→md5 map) +
  `cache_manifest_md5`, resolved `features` (active flags), `snapshot`, `frozen_cache`,
  `r3_ics`, `cell_label`.
- **Determinism-safe:** `check_determinism.sh` reads only `total_pnl_usd`/
  `total_closed`, never the whole file (the existing `run.date` timestamp already
  varies across replicates without affecting the verdict). Verified: 2-cycle smoke
  shows the block populated (`git_dirty:true` correctly flagged the dirty tree) with
  PnL/trades intact.

### #3 — session-continuity manifest → `data/SESSION_STATE.json`
- `scripts/session_state.py`: `update`/`show` CLI. `update` merges
  `version`/`step`/`next_action`/`notes`, auto-stamps `last_commit` (git short SHA) +
  `updated_at`, and records live grid PIDs (from a pidfile) + a grid-log tail. `show`
  re-checks PID liveness on read.
- `scripts/prepare_session.sh`: appended a `session_state.py show` call so the manifest
  is the **first thing surfaced** in every session (the preflight is the mandatory
  first bash call). A post-restart task now reads one file — "v228 is at step N, next
  is X, last commit Y, grid ALIVE [pid]" — instead of re-deriving it.
- Metadata only; zero determinism impact.

## Queue (priority order for V229+)

| Pri | Item | Effort | Why not now |
|---|---|---|---|
| **P1** | #2 dead-orchestrator supervisor (`nohup` watchdog + auto-restart) | M | needs a `check_determinism.sh` re-entry idempotency audit; pairs with #3's manifest |
| **P2** | #4 SIGTERM/SIGHUP progress flush | S-M | cheap, but wants a resume consumer (#1) to realize full value |
| **P2** | #6 pre-grid smoke as `scripts/pre_grid_smoke.sh` | S | done ad-hoc in V227/V228; formalize |
| **P2** | #7 4th held-out snapshot determinism canary | M | adds ~2 min/grid; high value given channel-resurfacing history |
| **P3** | #1 checkpoint/resume-from-cycle | L | **determinism risk** — a wrong engine-state restore silently corrupts the 11-version hermetic guarantee |
| **P3** | #8 dispatch-wedge watchdog | L | mostly a harness feature, not Victoria; procedural rule (10-min Workflow abandon) already mitigates |

## Observability-gap reflection (what would have caught the pain sooner)

The recurring pain — "session died, where were we?" — had **no instrument** until #3.
The next blind spot after shipping #3+#5: a grid that *finished* while the session was
dead leaves no signal that it's done and ready to finalize. #2's sentinel file
(`v###_grid.done`) closes that — it's why #2 is P1. The second blind spot: #5 records
provenance but nothing *checks* it on read; a follow-up could have `assert_cell_identity.py`
also assert `provenance.git_dirty == false` for any cell whose result is promoted to a
high-water (catching a dirty-tree number before it enters the README table).
