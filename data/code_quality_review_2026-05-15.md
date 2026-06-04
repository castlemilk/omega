# Omega Code Quality Review — 2026-05-15

Automated scheduled run. Repo: `~/projects/omega`.

## TL;DR

- Python linters and formatters: **clean** (0 issues).
- Python contract tests: **28/28 pass** (`tests/test_action_contracts.py`).
- Curated Python core slice: **150/150 pass**.
- Go toolchain: **not available in this sandbox** — go build / golangci-lint / go test could not be executed here. Re-run on a host with Go installed.
- Full 2719-test Python suite: cannot run to completion in this sandbox (depends on the Go API on `:8080` and external data services). No code regressions surfaced in what did run.
- **No automated fixes were applied** — `ruff check` and `ruff format` both reported clean state, so there was nothing to commit.

## Step-by-step results

### 1. Go quality checks — SKIPPED (environment)

`go` is not on PATH in this sandbox (`bash: go: command not found`). The following must be re-run on a Go-equipped host:

```
go build ./...
golangci-lint run ./...
go test ./... -short -count=1
```

Cannot certify status from this run.

### 2. Python lint / format / type checks

| Check                                  | Result    | Notes |
|----------------------------------------|-----------|-------|
| `ruff check omega/`                    | clean     | All checks passed |
| `ruff format --check omega/`           | clean     | 252 files already formatted |
| `mypy omega/core/ --ignore-missing-imports` | 13 errors (omega/core/ only) | Pre-existing; see below |

mypy errors in `omega/core/` (13, all pre-existing):

- `node_skills.py:360` — non-overlapping equality check
- `llm_shell.py:194` — `Returning Any from function declared to return str` (needs cast)
- `decision_snapshot.py:318` — missing return type annotation
- `alerting.py:251` — `float()` argument type mismatch
- `paper_trading.py:150` — `Returning Any`
- `node_adapter.py:391, 393` — `Item "None" of "Any | None" has no attribute …`
- `project_config.py:265` — `DataIngestionNode` has no attribute `_tickers`
- `project_config.py:341` — `StrategyNode` has no attribute `_min_conviction`
- `project_config.py:348` — `omega.core.paper_trading` has no attribute `PaperTradingExecutorNode`
- `meta_harness.py:351, 357` — `Returning Any` from `dict[str, Any]` / `int`
- `meta_harness.py:702` — `Item "None"` on `self._brain`

None of these are new — `mypy` was not previously in CI for this directory. Recommended follow-up: add explicit `cast()` calls and `if x is None: return` guards. Did **not** auto-fix because each fix is a behavior contract change that needs the Go API up to test end-to-end; better as a focused PR with the full suite running.

Following imports out of `omega/core/` exposes ~226 additional pre-existing errors in `omega/nodes/victoria/` (ndarray typing under numpy, optional-None handling). These are out of scope of the omega/core/ target.

### 3. Python contract tests

`pytest tests/test_action_contracts.py -q` → **28 passed, 0 failed** (Python 3.11.15).

### 4. Auto-fix pass

`ruff check --fix omega/` made no changes (already clean). `ruff format omega/` made no changes. **Nothing to commit.**

### 5. Broader Python test suite

Full `pytest tests/ --timeout=120` (2719 tests) does not complete in this sandbox:

- Workers hang on tests that call `http://localhost:8080/api/v1/diagnostics` (Go API not running here).
- Some tests hit live FRED/exchange endpoints and time out.

Curated runs that DID complete cleanly:

| Slice | Result |
|-------|--------|
| `test_action_contracts test_credentials test_config test_errors test_node test_brain_tiers` | **150 passed** in 13.2s |
| `tests/` minus `integration/`, `bridge/`, `baseline/` (first 47%, stopped at -x) | **353 passed, 44 skipped, 3 failed** before hitting heartbeat-to-:8080 hangs |

The 3 failures observed before the stop:

- `test_conviction.py::test_rank_signals_includes_conviction` — assertion failure (worth a human look; not obviously environmental)
- `test_ablation.py::TestAblationHaressIndividual::test_run_full_returns_eval_report` — timeout / orchestrator hung waiting on heartbeat to :8080
- `test_backtest_bridge.py::TestOmegaBacktestBridgeBasic::test_returns_backtest_result` — needs the Python pipeline bridge running

Two are clearly environmental. **The `test_rank_signals_includes_conviction` failure should be investigated** on a developer machine — but with no source changes from this run, it is not a regression I introduced.

### 6. Stale code patterns

**a) Raw action-string literals (excluding `actions.py` / `NodeAction`):**

```
omega/core/orchestrator_v2.py:439:    # node_type (e.g. "DATA_INGESTION" → "fetch_market_data"),  # comment
omega/nodes/victoria/victoria_node.py:28: "compute_signals"  → run all signal types          # docstring
```

Both are in comments/docstrings, **not in executable code**. No raw-string regression — the action-enum contract is intact.

**b) `os.environ.get(...API_KEY|SECRET...)` bypassing `omega.core.credentials`:**

12 hits across:

- `omega/core/startup_validator.py:271, 275` — `ANTHROPIC_API_KEY`, `CLAUDE_API_KEY`, `COINGECKO_API_KEY`, `CG_API_KEY`
- `omega/nodes/victoria/data_cache.py:104` — `FRED_API_KEY`
- `omega/nodes/victoria/unusual_whales_provider.py:45` — `UW_API_KEY`
- `omega/nodes/victoria/whale_signal.py:375, 391` — `WHALE_ALERT_API_KEY`, `COINGLASS_API_KEY`
- `omega/nodes/victoria/data_providers.py:37, 933` — `CG_API_KEY`, `COINBASE_API_KEY`
- `omega/nodes/victoria/llm_meta_controller.py:405` — `ANTHROPIC_API_KEY`
- `omega/nodes/polymarket/clob_client.py:236, 237` — `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`
- `omega/integrations/twitter_feed.py:294` — `SN13_API_KEY`

Recommended migration: each call site should use `from omega.core.credentials import credentials` and `credentials.get("X_API_KEY")`. Did not auto-refactor — would need test coverage that ran end-to-end. Reasonable next step is a single PR converting all 12 sites at once with a unit test asserting the credentials store is consulted.

## Success-criteria check

| Criterion                              | Status |
|----------------------------------------|--------|
| `go build ./...` passes                | **unverified** (no Go in sandbox) |
| `golangci-lint run` returns 0 issues   | **unverified** (no Go in sandbox) |
| `ruff check omega/` returns 0 issues   | **pass** |
| All Go test packages pass              | **unverified** (no Go in sandbox) |
| Contract tests pass                    | **pass** (28/28) |
| No regressions in Python suite         | **no regressions introduced** (no source changes made) |

## Recommendations

1. Re-run the Go portion on a developer machine to close the unverified items.
2. Investigate `tests/test_conviction.py::test_rank_signals_includes_conviction` — does not look obviously environmental.
3. Plan a focused PR to migrate the 12 `os.environ.get(...API_KEY...)` call sites to `omega.core.credentials`.
4. Optional: add the 13 `mypy omega/core/` errors to a tracked issue and address as a tightening pass.

— scheduled run, 2026-05-15
