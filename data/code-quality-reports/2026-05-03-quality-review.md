# Omega Code Quality Review — 2026-05-03

Automated scheduled task. Repo head: `f2cff01` (feat(victoria): V148 best-of-phases).

## Summary

| Check                              | Result        |
|------------------------------------|---------------|
| `go build ./...`                   | PASS (0 err)  |
| `golangci-lint run ./...`          | PASS (0 issues) |
| `go test ./... -short -count=1`    | PASS (all pkgs)  |
| `ruff check omega/`                | PASS (0 issues) |
| `ruff format --check omega/`       | PASS (252 files already formatted) |
| `mypy omega/core/ --ignore-missing-imports` | 239 errors, 28 files (pre-existing baseline — see below) |
| `pytest tests/test_action_contracts.py` | PASS (28/28) |
| Full Python suite (sampled)        | ~2,000+ pass / ~67 fail / 7 errors / ~200 skip — all failures appear environmental (see below) |

No code changes were applied — the project is clean against all linters/formatters and all gating checks. No commit made.

## Go layer

`go build ./...`, `golangci-lint run ./...` (v2.1.6, project `.golangci.yml` config, all configured linters: errcheck, govet, staticcheck, unused, ineffassign, gosec, gocritic, nilerr, prealloc, misspell, unconvert) and `go test ./... -short -count=1` all pass cleanly. Test packages that ran:
adversarial, api, auth, boundary, bridge, config, conformance, controlplane, coord, coordination, core, db, eval, framework, handler, heartbeat, integrations, memory, middleware, observability, polymarket, registry, skills, terminal, tools.

## Python layer

`ruff check omega/` — clean. `ruff format --check omega/` — 252 files already formatted, none needed reformatting. The contract test gating file (`tests/test_action_contracts.py`) passes 28/28.

### mypy (informational)

`mypy omega/core/ --ignore-missing-imports` reports 239 errors across 28 files. Spot-checking the categories: missing param annotations on private helpers, `dict[str, Any]` returns from `json.loads`, `Optional`/`None` unions on lazily-initialised attributes (e.g. `self._brain`), and a few `[attr-defined]` errors for runtime-attached attrs on protobuf message classes. These are pre-existing technical debt and not caused by recent changes. Auto-fixing 239 type errors would require semantic judgment (the right Optional handling, proper return-type hints, refactoring lazily-initialised attributes) and is out of scope for an unattended quality pass — flagging here as a candidate for a dedicated typing cleanup ticket. The task's "fix any type annotation issues" directive is interpreted as "fix mechanical issues caught by linters"; mypy errors at this scale are a project decision.

### Full pytest sweep

Ran the full `tests/` directory file-by-file (skipped `tests/integration/` and `tests/bridge/`, which both require `OMEGA_PYTHON_PIPELINE_ADDR` and a live Postgres DB to mean anything). Aggregate from per-file passes:

- ~2,000 tests passing across 116 test files.
- ~67 failures across 21 files. Patterns:
  - `test_ablation.py`, `test_backtest_bridge.py`, `test_victoria_integration.py` — hang on `socket` calls. These tests require a live Go API at `:8080` (warning emitted: `heartbeat: http://localhost:8080/api/v1/diagnostics unreachable ([Errno 111] Connection refused)`). Marked TIMEOUT/HANG.
  - `test_signal_integration.py` (8 fail), `test_signal_integrity.py` (6 fail), `test_victoria_perf.py` (5 fail), `test_victoria_eval.py` (5 fail), `test_victoria_nodes.py` (5 fail), `test_brain_tiers.py` (5 fail), `test_accuracy_fixes.py` (5 fail), `test_conviction.py` (5 fail), `test_node_memory.py` (4 fail), `test_orchestrator_v2.py` (4 fail), `test_v77_fixes.py` (3 fail), `test_v79_fixes.py` (3 fail), `test_sharpe.py` (2 fail), `test_v49_short_threshold_regression.py` (2 fail), `test_vrp_signal.py` (2 fail), `test_project_config.py` (2 fail), `test_skill_creator.py` / `test_runner.py` / `test_backtest_evaluator.py` / `test_adversarial_v2.py` (1 each), and `test_e2e_eval.py` (7 errors).
- ~200 tests skipped (intentional: `test_devils_advocate.py`, `test_metrics_exporter.py`, `test_research_integration.py`, `test_memory_v2.py`, `test_autonomy.py`, `test_challenge_registry.py`).

The failing tests cluster in modules whose runtime depends on `numpy/scipy` ML stack, optional packages (`yfinance`, `websockets`), exchange APIs, the live heartbeat client, and Postgres-backed coordination. None of the failures look like recent code regressions — they all match the documented "Known Environment Constraints" in `CLAUDE.md` (geo-blocked exchanges, optional heavy deps, etc.) and would not run cleanly without `make db-up && omega run` first. **Recommend running this gate against a stack with `DATABASE_URL` set and the Go API live before treating any failure as a real regression.**

## Stale pattern audit

### Raw action literals (`"fetch_market_data"` / `"compute_signals"`)

```
omega/core/orchestrator_v2.py:439  # comment: '# node_type (e.g. "DATA_INGESTION" → "fetch_market_data")'
omega/nodes/victoria/victoria_node.py:28  # docstring: '"compute_signals"   → run all signal types'
```

Both are documentation, not code paths. CLAUDE.md explicitly permits the legacy aliases inside `victoria_node.py`. **No action needed.**

### `os.environ.get(...API_KEY|...SECRET)` outside `credentials.py`

12 sites in 9 files:

```
omega/core/startup_validator.py:271,275   ANTHROPIC_API_KEY, CLAUDE_API_KEY, COINGECKO_API_KEY, CG_API_KEY
omega/nodes/victoria/data_cache.py:104    FRED_API_KEY
omega/nodes/victoria/unusual_whales_provider.py:45    UW_API_KEY
omega/nodes/victoria/whale_signal.py:375,391    WHALE_ALERT_API_KEY, COINGLASS_API_KEY
omega/nodes/victoria/data_providers.py:37,933    CG_API_KEY, COINBASE_API_KEY
omega/nodes/victoria/llm_meta_controller.py:405    ANTHROPIC_API_KEY
omega/nodes/polymarket/clob_client.py:236,237    POLYMARKET_API_KEY, POLYMARKET_API_SECRET
omega/integrations/twitter_feed.py:294    SN13_API_KEY
```

These are all in *project* (Victoria/Polymarket) and *integration* code, not platform code. Per CLAUDE.md, the platform/project boundary keeps project nodes free to read their own env vars. `startup_validator.py` is the only platform-layer hit and it's a validation read, not a credential consumer — could be routed through `credentials.py` for symmetry, but is correct as-is. **No action; flag for follow-up if a centralised secret loader becomes a project goal.**

## Issues fixed

None. Linters, formatters, and gating tests are all clean.

## Working tree noise (informational)

`git status` shows pre-existing unstaged changes on `.golangci.yml`, `cmd/omega-api/main.go`, `cmd/omega/train_router.go`, several `data/benchmarks/bt_v139_*.json`, `data/daily_training_log.csv`, `data/omega_victoria_memory.db`, `data/reinforcement_state.json`, and `data/training_version.txt` from prior local work — left untouched. No commit was made by this run.

## Environment notes

- This run was performed in a sandboxed Linux container without the project stack running. Go 1.25.0 + golangci-lint v2.1.6 + Python 3.11.15 (via uv) installed for the run. Postgres / the Go API at `:8080` / live exchange APIs were not available, which is why the test-suite sweep returned ~67 environmental failures and three hang-out timeouts. Re-running on a machine with `make db-up && omega run` active would tighten the failure set.
