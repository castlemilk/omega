# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

Omega is a self-improving node orchestration framework with a **three-layer architecture**:

- **Python layer** (`omega/`) — domain nodes, signal computation, ML, the heartbeat/orchestrator loop. Entry point: `python -m omega.bridge.pipeline_server` on port 9090.
- **Go layer** (`cmd/omega-api`, `internal/`) — Connect-RPC server on port 8080. Reads shared Postgres/SQLite state and exposes `OrchestratorService` to the dashboard. All new platform features (memory, scheduler, health/repair, coordination) default to Go.
- **React dashboard** (`dashboard/`, `web/dashboard/`) — Vite + Connect-ES client on port 5173.

The Go API never calls Python directly in-process; Python and Go communicate via shared storage (Postgres `DATABASE_URL`, SQLite `state.db`/`memory.db`) and the pipeline HTTP bridge at `OMEGA_PYTHON_PIPELINE_ADDR`.

## Platform vs Project Separation (critical)

- `omega/core/`, `omega/bridge/`, `omega/nodes/` base classes are **platform** — must stay project-agnostic.
- `omega/nodes/victoria/`, `omega/nodes/polymarket/`, etc. are **projects** — domain-specific.
- **Never import project code from platform code.** Projects register via YAML in `projects/` (e.g., `projects/victoria.yaml`).
- Core platform (memory, scheduler, health/repair, coordination) **must be Go**. Python is reserved for ML/signal computation (numpy/scipy) and project signal nodes like Victoria.

## Data Models & RPC

- **Always use protobuf** for data models. Protos live in `proto/omega/v1/`.
- `make proto` regenerates Go bindings via `buf generate`.
- `make proto-python` regenerates Python bindings into `gen/python/omega/v1.py` (betterproto). **Never hand-write proto classes**; import from the generated file.
- Go ↔ React uses **Connect-RPC** (Connect-ES on the frontend). Never stand up a Python HTTP API — the Python layer only exposes the pipeline bridge.

## Action / Step Contract (see CONTRIBUTING.md)

Action names, step types, and capabilities **must** use the enums in `omega/core/actions.py` — never raw string literals.

```python
from omega.core.actions import NodeAction
inp = NodeInput(action=NodeAction.FETCH_MARKET_DATA.value, ...)
```

Dispatch flow: Go `ExecuteStepRequest.node_type` → `resolve_action(node_type)` → `NodeAction` → `NodeInput`. `resolve_action` is the single translation point; do not add ad-hoc `.lower()` fallbacks. When adding a routing entry, add to `StepType` and `STEP_TO_ACTION` first. Contract tests in `tests/test_action_contracts.py` must pass.

Legacy aliases (`"riskcheck"`, `"signalresearch"`, `"riskmanagement"`) in `victoria_node.py` are the only permitted raw strings and must not be expanded.

## Common Commands

### Full dev stack

```bash
make db-up                  # Start Postgres (docker compose)
export DATABASE_URL=postgres://omega:omega@localhost:5432/omega?sslmode=disable
omega run                   # Bridge (9090) + Go API (8080) + React (5173)
# or:
make dev                    # Same, via Makefile (no prefixed output)
make dev-down               # Tear down
```

Install the CLI: `go install ./cmd/omega`.

Docker compose service name is `omega-postgres` (not `postgres`):
```bash
docker compose up -d omega-postgres
```

### Build / test / lint

```bash
make build                  # go build ./...
make test                   # all Go tests
make test-db                # Postgres-backed tests in internal/db
make test-integration       # requires TEST_DATABASE_URL
make py-test                # pytest tests/
pytest tests/test_node.py   # single Python test file
go test ./internal/handler/... -run TestName -v   # single Go test

make lint                   # ruff + go vet + golangci-lint + eslint (both dashboards)
make typecheck              # mypy + tsc (both dashboards)
make format                 # ruff format + gofumpt + prettier
make coverage               # Python + Go coverage
make quality                # full CI pipeline (scripts/ci.sh)
```

### Proto / training / frontend

```bash
make proto                  # Go bindings (buf generate)
make proto-python           # Python bindings into gen/python/
make train-router           # Offline-train AttentionRouter from coordination_outcomes
make fe-install && make fe-build
```

Frontend lives in **two places**: `dashboard/` (primary) and `web/dashboard/` — lint/typecheck targets run both.

## Victoria Training

### Running training

```bash
python3 scripts/run_training.py --version v49 --cycles 200 --sleep 10
```

Version auto-increments from `data/training_version.txt` if `--version` is omitted. Requires `DATABASE_URL` (Postgres) and network access for exchange APIs.

### Training artifacts

Each run produces:
- `data/{version}_results.json` — aggregate stats (PnL, trades, win rate, observability metrics)
- `data/{version}_trades.csv` — per-trade log: `cycle,timestamp,symbol,side,size,entry_price,exit_price,pnl,slippage,hold_cycles,conviction,regime,sit_out_reason`
- `data/{version}_progress.json` — periodic snapshots during the run
- `data/{version}_gate_result.json` — standing-baseline gate verdict (always written; see below)
- `/tmp/{version}_metrics.jsonl` — per-cycle JSONL metrics (not committed)

### Standing-baseline gates (`omega/eval/standing_gates.py`)

Gates are **post-run evaluation only** — they read the artifacts a finished run
wrote and produce one file. Nothing in the gate path can influence trading,
sizing or signals.

**The numbers come from the training journal, not from the previous run.** Every
pre-registration since V240 carries a "Standing baseline (MUST NOT MOVE)" line —
currently `omega/nodes/victoria/training_log/V271.md:6`: **crisis +$599 / trend
+$2,997 / recent +$30**. Those numbers are transcribed, with citations, into
`data/standing_baseline.json` (committed **config**, not run output — the one
file under `data/` that is hand-maintained). Moving the standing baseline is a
journal act with its own pre-registration; editing that file to make a run pass
is the thing the gate exists to prevent.

Each run is mapped to a regime **family** (`crisis` / `trend` / `recent`) from
its `provenance.snapshot` (via `data/walk_forward_manifest.json`, authoritative)
or, failing that, from the cell label (`family_patterns` in the config). The
substrate wins over the name; a conflict is recorded, not hidden.

#### Two numbers, two jobs (revised 2026-08-19)

`per_cell_floor_usd` — **the bar**, `0.0` for all three families. A cell that
lost money fails; nothing else does. Configurable per family (raising it is a
journal act).

`campaign_mean_usd` — the journal's +$599 / +$2,997 / +$30, **advisory only,
never a bar**. They are the MEAN of a per-regime walk-forward distribution
(crisis n=12, trend n=10, recent n=10) and those distributions are heavily
right-skewed: crisis's median window is **+$65** against its +$599 mean;
recent's is **-$644** against +$30. Failing every cell below the mean would fail
most legitimate crisis cells and nearly every legitimate recent one — an alarm
that cries wolf until nobody reads it. So a cell at or above its floor but below
its family's campaign mean **passes**, and its `cell_pnl_floor` gate carries
`advisory: "below_campaign_mean"` plus `campaign_mean_margin_usd`. The advisory
rides in `notes`, never in `failures`, and does not move the verdict. The
Foreman board renders it as an amber note on a PASS tile, not as a failure tint.

**Grid-level aggregation lives in `omega/eval/grid_ruler.py`** — see
"Campaign ruler" below. The campaign mean is a *grid*-level ruler and this
module (a per-cell one) deliberately never gates on it.

Gates evaluated:

| Gate | Assertion |
|---|---|
| `cell_pnl_floor` | candidate PnL ≥ the family's `per_cell_floor_usd` ($0 — did this cell lose money). Reports the campaign mean alongside, and raises the `below_campaign_mean` advisory on a pass that sits under it. |
| `trade_count_floor` | ≥ 20 closed trades (prevents "win by sitting out") |
| `drawdown_ceiling` | only when `observability.max_drawdown_usd` is present — otherwise `not_evaluated` |

Plus a `sibling_comparison` block against the N-1 cell, which is **informational
only**: it exists to detect a run that reproduced a prior run, and never decides
a pass or a fail.

**Verdict vocabulary** (a first-class `verdict` field, not inferred from
`passed`), in precedence order:

- **`FAIL`** — at least one evaluated gate failed.
- **`NO_BASELINE`** — the cell's family could not be resolved, so no per-cell
  floor applies. Loud, and the file is still written. This is **not** a pass.
- **`NO_OP`** — the run used a frozen cache and reproduced its N-1 sibling
  exactly (identical trade fingerprint — timestamp column dropped — or identical
  trade count and PnL). It measured nothing new.
- **`PASS`** — every evaluated gate passed. May carry advisories (see above);
  an advisory is never a failure.
- **`ERROR`** — gate evaluation itself raised. Written by `run_training.py`; the
  training run survives, but the failure is a record, never a silence.

Per-gate status is `pass` / `fail` / **`not_evaluated`**. A gate whose input
block is absent reports `not_evaluated` and **never** `pass`.

`data/{version}_gate_result.json` is written for **every** verdict.

### Campaign ruler (`omega/eval/grid_ruler.py`)

The **grid**-level layer: it gates the standing baseline itself, where
`standing_gates.py` only gates one cell. Spec:
`omega/nodes/victoria/training_log/V247_RULER.md` (Phase 0 — the instrument) and
`V247_RULER_CANDIDATES.md` (Phase 1 — candidate β, adopted as PRIMARY).

```bash
python3 scripts/run_grid_ruler.py --run v246_wf            # writes data/v246_wf_grid_verdict.json
python3 scripts/run_grid_ruler.py --run v246_wf --coupling low --no-write
```

**Run it ONCE, after a whole grid finishes — never per cell.** It is
deliberately NOT wired into `run_training.py`, which is invoked per cell and has
no concept of the set; the natural future hook is the last line of a grid runner
(`scripts/v2*_wf_grid.sh`, `scripts/walk_forward_grid.sh`). Read-only apart from
the one verdict file it writes.

**The instrument** is a **paired per-window Δ** (candidate − standing baseline,
same window), aggregated per regime family and pooled over all 32 manifest
windows — V247_RULER.md §1. The OFF-arm *level* spread is explicitly not the
ruler ("it can never be the gate"). The standing baseline's 32 per-window values
are committed in `data/standing_baseline.json` under `distributions` (transcribed
from the four committed grids; their means reproduce +$599 / +$2,997 / +$30 to
the cent).

**The bar** is one-sided **no-regression**: a family FAILS iff its mean-Δ is
below −MDE, where MDE = 2.801585·sd/√n (α=0.05, 80% power). §7's standing
thresholds — **$1,043 recent / $1,565 crisis / $4,118 trend** at current n, and
**$1,425 pooled** (median-sd) / **$875** low-coupling / **$633** near-inert —
are reproduced by that formula from the Δ-sd table in the config. A regression
*inside* the MDE is unfalsifiable per §7, so it is neither a FAIL nor a silence:
it rides as the `regression_within_noise` advisory. The MDE is recomputed at the
grid's **actual** n, so a short grid gets a correspondingly wider bar.

**Coupling class** (`--coupling median|inert|low|heavy`) selects the Δ-sd row;
§7 requires a pre-registration to declare one. Undeclared ⇒ the mechanism-
agnostic `median` row, which is the widest (hence slowest to shout FAIL).

**Not gated, only reported:** candidate β's *acceptance* bar (pooled mean-Δ ≥ a
pre-registered $ number with a bootstrap CI excluding 0), its −1·SE recent floor,
and its dual-tail Δ-p25 / level-p25 clause. β fixes exact $ bars in the pre-reg
*before* a run, so a standing scorer must not invent one. All the numbers those
gates need are in the verdict file; `grid_ruler.gate_advisory_recent_floor` in
the config turns the recent floor into a real failure when a pre-reg adopts it.

**Verdict vocabulary** (precedence `ERROR` > `FAIL` > `INSUFFICIENT_GRID` >
`PASS`), written to `data/{run_label}_grid_verdict.json`:

- **`FAIL`** — a family's mean-Δ is below −MDE, pooled or per-regime.
- **`INSUFFICIENT_GRID`** — the run does not cover the 32 manifest windows (or
  the config has no per-window values). Loud, names the missing window ids per
  family, and is **never** a pass.
- **`PASS`** — no family regressed beyond its MDE. May carry advisories.
- **`ERROR`** — ruler evaluation itself raised.

The Foreman Gates view renders it as a compact "Campaign ruler" card
(`/api/v1/training/grid-ruler?run=…`).

#### `omega/eval/v49_gates.py` — RETIRED IN PLACE (2026-08-18)

Still importable and still tested, kept for reading historical gate files; **no
longer called by `run_training.py`**. It compared a run to its N-1 sibling cell
by exact-suffix label decrement, which by 2026-08-18 was:

- resolving **nothing** for 39 of the 51 most recent cell labels (renamed cells)
  → a logged warning and **no gate file at all**;
- comparing deterministic replays **to themselves** when it did resolve (18 gate
  files in `data/` carry identical baseline and candidate summaries);
- running three gates that could not fail — `signal_integrity` and
  `auto_apply_audit` returned True when their input block was absent (it always
  was), and `max_drawdown` defaulted to `0.0` so `drawdown_ceiling` compared
  `0.0 <= 0.0` forever. Only `pnl_floor` and `trade_count_floor` were real.

Do not resurrect the "six hard gates on every run" claim; it described a
mechanism that had stopped running.

### Forensics tool

Compare two training runs:
```bash
python3 -m omega.tools.forensics.run_diff \
  --baseline-results data/v48_results.json \
  --baseline-trades data/v48_trades.csv \
  --target-results data/v49_results.json \
  --target-trades data/v49_trades.csv \
  --out-json data/v48-v49-forensics.json \
  --out-md docs/training/v48-v49-forensics.md
```

Produces per-symbol PnL deltas, conviction histogram comparison, skipped trades list, top-3 ranked hypotheses, and per-regime breakdown.

### Conviction filter pipeline (`strategy.py:_passes_conviction_filters`)

Filters applied per ticker per cycle, in order:
1. **Time filter** — no new trades within 2 cycles of last trade
2. **Agreement ratio** — >= threshold of sub-signals agree on direction (0.0 in normal = disabled; 0.7 in high_vol)
3. **Weighted conviction** — IC-weighted composite exceeds regime-adaptive threshold
4. **Regime/vol gate** — higher bar in high-vol regime (1.25x multiplier)

Regime-adaptive thresholds (set in `_apply_regime_adaptive_thresholds`):
- **CRISIS/BEAR** (bear_prob >= 0.55): long=0.20 (suppressed), short=0.05 (permissive)
- **BULL** (bull_prob >= 0.55): long=0.05 (permissive), short=0.20 (suppressed)
- **NORMAL** (else): long=0.10, short=0.05 (V49 fix)

All thresholds are further scaled by `_thresh_scale = basket_std / 0.20`.

**Regime labels in the data are `crisis`, `high_vol`, `normal`** — NOT bull/bear/chop.

## Git Worktree Conventions

- Use isolated worktrees for feature work: `git worktree add -b <branch> ../<name> main`
- Merge via **cherry-pick**, not full merge (avoids divergence on long-lived branches)
- Consolidate worktrees every 4-5 tasks
- After cherry-pick, verify files on main, then `git worktree remove` + `git branch -d`
- Untracked data files (`data/v*_*.json`, `data/v*_*.csv`) do NOT propagate to worktrees — copy them manually if needed

## Frontend Conventions

- **Always use shadcn** for React components.
- Connect-ES client talks to Go API at `:8080`; keep the proto as the source of truth.

## Observability

- OTel stack: `make otel-up` → collector on 4317/4318, Tempo on 3200, Grafana on 3001 (admin/omega).
- SQLite `state.db` stores nodes, traces, issues, costs, improvements. `memory.db` stores episodic/semantic/working memory.

## Known Environment Constraints

- Exchange APIs: Binance/Bybit are geo-blocked from the US (451/403). Coinbase + Kraken work from US with real volume. CoinGecko works but provides no volume. CryptoCompare is the 6th-tier fallback. See `docs/DATA_SOURCES.md`.
- Python is 3.11+; core runtime deps are intentionally minimal (`psycopg`, `betterproto`). Heavy deps (numpy, OTel) are optional extras.
