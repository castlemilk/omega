# Omega Code Quality Review — 2026-05-22

Automated run of `omega-code-quality-review` scheduled task.

## Summary

| Check | Result |
|---|---|
| `go build ./...` | PASS (exit 0) |
| `golangci-lint run ./...` | PASS (0 issues) |
| `go test ./... -short -count=1` | PASS (all 26 testable packages) |
| `ruff check omega/` | PASS (All checks passed) |
| `ruff format --check omega/` | PASS (252 files already formatted) |
| `mypy omega/core/ --ignore-missing-imports` | 234 pre-existing errors (see below) |
| `pytest tests/test_action_contracts.py` | PASS (28/28) |
| Full `pytest tests/ -q --timeout=120` | Partial run — sandbox time-limited |
| Raw action-literal grep | Clean (matches were comments only) |
| Unscoped `os.environ.get` API_KEY/SECRET grep | 12 pre-existing matches outside `credentials.py` |

Nothing was committed: ruff and golangci-lint had no issues to fix, and the mypy / pytest items below are pre-existing tech debt rather than regressions introduced by code changes (the working tree was already dirty with ~1500 unstaged lines when this task ran).

## Environment notes

The sandbox shipped with Python 3.10 only; the project requires 3.11+. I installed a local 3.11.9 toolchain to run pytest and mypy. Go 1.25.0 and `golangci-lint` 2.5.0 came from the repo cache.

## Go

`go build ./...` and `golangci-lint run ./...` both clean. `go test ./... -short -count=1` reported `ok` for every package with test files — `internal/{adversarial,api,auth,boundary,bridge,config,conformance,controlplane,coord,coordination,core,db,eval,framework,handler,heartbeat,integrations,memory,middleware,observability,polymarket,registry,skills,terminal,tools}` — no failures, no flakes. Packages without test files were skipped silently as expected.

## Python — ruff

`ruff check omega/` → "All checks passed!". `ruff format --check omega/` → "252 files already formatted". Nothing to fix.

## Python — mypy

`mypy omega/core/ --ignore-missing-imports` reports **234 errors across 25 files**. Breakdown by file:

```
169  omega/nodes/victoria/features.py
  9  omega/nodes/victoria/hmm_regime.py
  6  omega/nodes/victoria/strategy.py
  6  omega/nodes/victoria/decision_embeddings.py
  5  omega/nodes/victoria/signals/funding_rate.py
  4  omega/nodes/victoria/signal_generation.py
  3  omega/nodes/victoria/signals/{yield_curve,geopolitical,dxy_signal}.py
  3  omega/nodes/victoria/llm_meta_controller.py
  3  omega/core/project_config.py
  2  omega/nodes/victoria/{ws_feeds,victoria_node,signal_memory,ml_combiner,meta_learner}.py
  2  omega/core/node_adapter.py
  1  omega/nodes/victoria/{whale_flow,market_manifold,decision_trace,confidence_surface,activation_trace}.py
  1  omega/core/{node_skills,meta_harness,alerting}.py
```

Only 8 of the 234 are inside `omega/core/` itself — the rest are reachable via imports from omega/nodes/victoria/. These look like pre-existing tech debt (e.g., `_TradeReinforcer = None` reassignments, `_last_confluence.get()` Optional-narrowing, missing return annotations on lazy-property helpers). I did not auto-fix them: the volume is too large to apply safely in an automated pass without a reviewer, and they're not in the task's stated success criteria.

Recommend a dedicated mypy cleanup task that walks `omega/nodes/victoria/features.py` first (single file = 72% of the total).

## Python — contract tests

`pytest tests/test_action_contracts.py` → **28 passed in 0.60s**.

## Python — full suite

`pytest tests/ -q --timeout=120 -n auto` could not complete inside the sandbox's per-shell wall clock (45 s). A partial run (≈48 % completed before timeout) reported:

- ~1146 PASS lines emitted before truncation
- 7 ERRORS in `tests/test_e2e_eval.py` (e2e tests that require the Go server on :8080 — environmental, not a code regression)
- 4 FAILURES distributed across `tests/test_backtest_bridge.py`, `tests/test_node_memory.py`, `tests/test_ablation.py`

Re-running those four files **sequentially without xdist** yielded **153 passed in 1.44s** — every one of them passes when run alone. The failures under parallel execution look like fixture pollution (shared SQLite `state.db` / `memory.db` between workers), not source-code regressions. Suggest investigating `conftest.py` for per-worker DB isolation in a follow-up.

## Stale pattern scan

### Raw action literals

```
omega/core/orchestrator_v2.py:439:    # node_type (e.g. "DATA_INGESTION" → "fetch_market_data"),
omega/nodes/victoria/victoria_node.py:28: "compute_signals"   → run all signal types
```

Both are **comments / docstrings**, not raw code literals. Clean.

### Unscoped `os.environ.get(...API_KEY|SECRET)`

12 call sites outside `omega/core/credentials.py`:

```
omega/core/startup_validator.py:271     ANTHROPIC_API_KEY / CLAUDE_API_KEY
omega/core/startup_validator.py:275     COINGECKO_API_KEY / CG_API_KEY
omega/nodes/victoria/data_cache.py:104  FRED_API_KEY
omega/nodes/victoria/unusual_whales_provider.py:45  UW_API_KEY
omega/nodes/victoria/whale_signal.py:375           WHALE_ALERT_API_KEY
omega/nodes/victoria/whale_signal.py:391           COINGLASS_API_KEY
omega/nodes/victoria/data_providers.py:37          CG_API_KEY
omega/nodes/victoria/data_providers.py:933         COINBASE_API_KEY
omega/nodes/victoria/llm_meta_controller.py:405    ANTHROPIC_API_KEY
omega/nodes/polymarket/clob_client.py:236-237      POLYMARKET_API_KEY / API_SECRET
omega/integrations/twitter_feed.py:294             SN13_API_KEY
```

These ought to be routed through `omega.core.credentials.credentials.get(...)` per the docstring at the top of `credentials.py`. Migrating them is a small mechanical refactor — recommend filing it as a follow-up ticket rather than bundling into a quality sweep.

## Recommendations / follow-ups

1. Carve mypy clean-up into a dedicated task starting with `omega/nodes/victoria/features.py` (169/234 errors).
2. Investigate xdist worker isolation for `test_e2e_eval`, `test_backtest_bridge`, `test_node_memory`, `test_ablation` — likely a shared `state.db`/`memory.db` between workers.
3. Migrate the 12 `os.environ.get` API-key/secret sites to `credentials.get(...)`.
4. The working tree had ~1500 lines of unstaged edits when this ran; whoever is mid-work on the repo should consider committing or stashing so future automated runs start from a known state.
