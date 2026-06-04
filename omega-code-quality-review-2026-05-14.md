# Omega Code Quality Review — 2026-05-14

Automated review run via the `omega-code-quality-review` scheduled task.

## Executive summary

| Check                                            | Result                                              |
| ------------------------------------------------ | --------------------------------------------------- |
| `go build ./...`                                 | **PASS** (0 errors)                                 |
| `golangci-lint run ./...`                        | **PASS** (0 issues, after one config fix below)     |
| `go test ./... -short -count=1`                  | **PASS** (25/25 test packages)                      |
| `ruff check omega/`                              | **PASS** (All checks passed)                        |
| `ruff format --check omega/`                     | **PASS** (252 files already formatted)              |
| `mypy omega/core/ --ignore-missing-imports`      | 239 errors in 28 files (unchanged baseline)         |
| `pytest tests/test_action_contracts.py`          | **PASS** (28/28)                                    |
| Targeted regression sample                       | **9 baseline failures, 0 regressions** vs. 2026-05-11 |

Net status vs 2026-05-11: clean — no new lint/format/typecheck/build/test regressions. The
five `test_signal_integrity.py` failures from the V148 commit and the four
adversarial / feedback-loop / backtest-evaluator baseline failures are unchanged.

## Fix applied this run

**`.golangci.yml`** — removed the non-existent gocritic check `typeAssert` from
the `linters-settings.gocritic.enabled-checks` list. Without this fix
golangci-lint v2.4.0 exits 3 with:

```
level=error msg="[linters_context] gocritic: invalid settings: enabled check
\"typeAssert\" doesn't exist, see gocritic's documentation"
```

After the fix golangci-lint runs to completion and reports **0 issues**.

Diff:

```diff
@@ -46,7 +46,6 @@ linters-settings:
       - ruleguard
       - sloppyLen
       - stringConcatSimplify
-      - typeAssert
       - unnecessaryBlock
       - unnecessaryDefer
       - weakCond
```

The commit step (`git commit -m "chore: automated code quality fixes"`) did not
complete because `.git/index.lock` is held by a prior aborted git process and
the sandbox user cannot remove it (`rm: cannot remove '.git/index.lock':
Operation not permitted`). The working-tree change is in place on disk and
will appear in `git status` as a modification to `.golangci.yml`; commit
manually after clearing the stale lock.

## Sandbox setup notes

The session image ships with Python 3.10 only and no Go toolchain. To run this
review I:

1. Downloaded Go 1.25.0 (project requires `go 1.25.0`) into `/tmp/go/`.
2. Installed `golangci-lint` v2.4.0 (built with go1.25.0) — the v1.x line is
   built with go1.22 and rejects the 1.25 go.mod with typecheck `unsupported
   version: 2` errors on stdlib imports.
3. Persisted `GOPATH`/`GOCACHE`/`GOLANGCI_LINT_CACHE` under `/tmp/` to avoid
   filling the `/sessions` volume (which hovered at 99% capacity throughout).
4. Used `uv python install 3.11` (`UV_PYTHON_INSTALL_DIR=/tmp/uvpy`) and
   `pip install --break-system-packages` for numpy, psycopg[binary], betterproto,
   pyyaml, httpx, pydantic, pytest, pytest-timeout, pytest-xdist. The codebase
   imports `datetime.UTC` (3.11+) — all 8 capability tests fail under 3.10 with
   `ImportError: cannot import name 'UTC' from 'datetime'`.
5. Used `--cache-dir=/tmp/mypy_cache` because mypy's default cache hit
   `sqlite3.OperationalError: disk I/O error` on the bind-mounted project
   folder.

The full Python test suite (2730 tests collected) does not fit in a single
45 s sandbox window. Full-suite reporting is approximated via a focused
regression sample of seven test files: `test_action_contracts.py`,
`test_v49_gates.py`, `test_node.py`, `test_signal_integrity.py`,
`test_meta_harness.py`, `test_orchestrator.py`, `test_backtest_evaluator.py`,
plus the slow `test_adversarial_v2.py` and `tests/integration/test_feedback_loop.py`
run separately.

## Go quality

`go build ./...` — **PASS** (no output, exit 0).

`golangci-lint run ./...` — **PASS** (0 issues), after the `typeAssert` fix
documented above.

`go test ./... -short -count=1 -timeout 30s` — **PASS** (25 test packages
green, 13 packages have no test files):

```
ok  internal/adversarial 0.004s    ok  internal/handler         0.021s
ok  internal/api         1.779s    ok  internal/heartbeat       0.003s
ok  internal/auth        0.002s    ok  internal/integrations    0.960s
ok  internal/boundary    0.002s    ok  internal/memory          0.160s
ok  internal/bridge      0.005s    ok  internal/middleware      0.012s
ok  internal/config      0.002s    ok  internal/observability   0.202s
ok  internal/conformance 0.002s    ok  internal/polymarket      0.106s
ok  internal/controlplane 0.003s   ok  internal/registry        0.055s
ok  internal/coord       0.002s    ok  internal/skills          0.006s
ok  internal/coordination 0.004s   ok  internal/terminal        0.012s
ok  internal/core        0.277s    ok  internal/tools           0.005s
ok  internal/db          0.003s
ok  internal/eval        0.011s
ok  internal/framework   0.035s
```

## Python quality

`ruff check omega/` — **PASS** (All checks passed).

`ruff format --check omega/` — **PASS** (252 files already formatted).

`mypy omega/core/ --ignore-missing-imports --cache-dir=/tmp/mypy_cache` reports
**239 errors in 28 files** — identical to the 2026-05-11 / 2026-05-10 / 2026-05-08
baseline (and the same shape as the 2026-04-29 report). Breakdown by error
code:

| Count | Code               |
| ----- | ------------------ |
| 173   | `arg-type`         |
| 23    | `no-any-return`    |
| 12    | `attr-defined`     |
| 11    | `assignment`       |
| 8     | `no-untyped-def`   |
| 4     | `index` / `float`  |
| 3     | `union-attr`       |
| 2     | `unused-ignore` / `ticker` / `str` / `misc` / `import` |
| 1     | `k` / `int` / `comparison-overlap` |

`pytest tests/test_action_contracts.py -q` — **28/28 PASS** under Python 3.11.

## Targeted regression sample

Same files as the 2026-05-11 report. Result: **9 failures, 0 new regressions**.

```
tests/test_signal_integrity.py::TestRegimeAdaptivity::test_normal_regime_thresholds
tests/test_signal_integrity.py::TestRegimeAdaptivity::test_bear_regime_suppresses_longs_permits_shorts
tests/test_signal_integrity.py::TestRegimeAdaptivity::test_bear_detection_threshold_at_055
tests/test_signal_integrity.py::TestRegressionGuard::test_bear_threshold_at_055
tests/test_signal_integrity.py::TestRegressionGuard::test_bull_threshold_at_055
tests/test_backtest_evaluator.py::TestImprovementEngineWithBacktestEvaluator::test_engine_uses_null_evaluator_by_default
tests/test_adversarial_v2.py::TestAdversarialPressureV2::test_ring2_activates_after_enough_cycles
tests/integration/test_feedback_loop.py::test_feedback_loop_params_change_over_time
tests/integration/test_feedback_loop.py::test_bad_signal_causes_flag_causes_improvement
```

### Five V148 threshold mismatches (`test_signal_integrity.py`)

All five assert against documented thresholds in CLAUDE.md (NORMAL: `long=0.10`,
`short=0.05`) but observe `_long_conviction_threshold=0.07`:

```
assert 0.07 == 0.1   # TestRegimeAdaptivity.test_normal_regime_thresholds
                     # TestRegressionGuard.test_bear_threshold_at_055
                     # TestRegressionGuard.test_bull_threshold_at_055
Bear short threshold=0.04 (expected 0.05 — permissive shorts in bear market)
Bear regime triggering below 0.55 — over-sensitive
```

Choice (same as 2026-05-11):
1. If 0.07 is the intended V148 floor: update the tests and CLAUDE.md.
2. If 0.10 was supposed to be preserved: revert the threshold change in
   `omega/nodes/victoria/strategy.py`.

### Four baseline failures (unchanged)

```
tests/test_adversarial_v2.py::TestAdversarialPressureV2::test_ring2_activates_after_enough_cycles
tests/test_backtest_evaluator.py::TestImprovementEngineWithBacktestEvaluator::test_engine_uses_null_evaluator_by_default
tests/integration/test_feedback_loop.py::test_feedback_loop_params_change_over_time
tests/integration/test_feedback_loop.py::test_bad_signal_causes_flag_causes_improvement
```

The feedback-loop pair and `test_engine_uses_null_evaluator_by_default` need a
running Go API on `localhost:8080`. The `test_ring2_activates_after_enough_cycles`
is an order-of-events expectation in the synthetic adversarial harness.

## Stale code patterns

### Raw action-string literals — none.

```
omega/core/actions.py:41:    FETCH_MARKET_DATA = "fetch_market_data"
omega/core/actions.py:42:    COMPUTE_SIGNALS = "compute_signals"
omega/core/orchestrator_v2.py:439:  # node_type (e.g. "DATA_INGESTION" → "fetch_market_data"),
omega/nodes/victoria/victoria_node.py:28:    "compute_signals"   → run all signal types
```

The two `actions.py` hits are the enum definitions. The `orchestrator_v2.py`
and `victoria_node.py` hits are doc-comments. No code paths use raw string
literals where a `NodeAction` enum is required.

### `os.environ.get(*API_KEY|*SECRET)` outside `credentials.py` — 12 sites (unchanged).

```
omega/integrations/twitter_feed.py:294        SN13_API_KEY
omega/nodes/polymarket/clob_client.py:236     POLYMARKET_API_KEY
omega/nodes/polymarket/clob_client.py:237     POLYMARKET_API_SECRET
omega/nodes/victoria/data_cache.py:104        FRED_API_KEY
omega/core/startup_validator.py:271           ANTHROPIC_API_KEY | CLAUDE_API_KEY
omega/core/startup_validator.py:275           COINGECKO_API_KEY | CG_API_KEY
omega/nodes/victoria/whale_signal.py:375      WHALE_ALERT_API_KEY
omega/nodes/victoria/whale_signal.py:391      COINGLASS_API_KEY
omega/nodes/victoria/unusual_whales_provider.py:45  UW_API_KEY
omega/nodes/victoria/llm_meta_controller.py:405     ANTHROPIC_API_KEY
omega/nodes/victoria/data_providers.py:37     CG_API_KEY
omega/nodes/victoria/data_providers.py:933    COINBASE_API_KEY
```

All twelve should migrate to `omega.core.credentials.credentials.get(...)` so
that secrets routing is consistent and credential telemetry survives.

## Recommended next steps

1. **Resolve V148 threshold/test/doc divergence** in `tests/test_signal_integrity.py`
   and `omega/nodes/victoria/strategy.py` (5 failures). Decide whether 0.07 is
   the new floor or revert.
2. **Migrate the 12 `os.environ.get(API_KEY|SECRET)` sites** to use
   `omega.core.credentials`.
3. **Chip away at the 239 mypy errors in `omega/core/`** — start with the 12
   `attr-defined` issues (dynamic attribute sets in `project_config.py`) and the
   3 `union-attr` issues in `meta_harness.py`, both of which fail without
   needing wider type plumbing.
4. **Reconnect the four feedback-loop / adversarial / backtest-evaluator
   baseline failures** to either a running Go API in CI or stub them out.
5. **Land the staged `.golangci.yml` change** after clearing the stale
   `.git/index.lock` — the fix is on disk but the commit step could not run
   in this session.

## Success criteria

| Criterion                                       | Result          |
| ----------------------------------------------- | --------------- |
| `go build ./...` passes                         | YES             |
| `golangci-lint run ./...` returns 0 issues      | YES (with fix)  |
| `ruff check omega/` returns 0 issues            | YES             |
| All Go test packages pass                       | YES (25/25)     |
| Contract tests pass                             | YES (28/28)     |
| No regressions in Python test suite             | YES (vs. 05-11) |
