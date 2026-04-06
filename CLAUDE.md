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
- `data/{version}_gate_result.json` — hard gate pass/fail report (V49+)
- `/tmp/{version}_metrics.jsonl` — per-cycle JSONL metrics (not committed)

### Hard gates (`omega/eval/v49_gates.py`)

Every training run automatically checks six gates against the previous version:
1. PnL floor (v_new >= v_prev)
2. Regime parity (non-negative in every regime: `crisis`, `high_vol`, `normal`)
3. Drawdown ceiling
4. Trade count floor (>= 20)
5. Signal integrity tests
6. Auto-apply audit (meta-analyst safety)

Gate failure writes `data/{version}_gate_result.json` with specific failure reasons. The run is NOT automatically merged on failure.

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
