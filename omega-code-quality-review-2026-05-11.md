# Omega Code Quality Review — 2026-05-11

Automated scheduled run. HEAD = `f2cff01` (unchanged from 2026-05-10 / 2026-05-08). Working tree had **34 uncommitted modified files** at start of run (long-running in-flight work). No fixes were committed: the Go pipeline, ruff lint, ruff format, and contract tests are all clean — there was nothing to fix automatically, and bundling unrelated commits with the existing in-flight state would conflate authorship.

## Summary

| Check                                            | Result                                              |
|--------------------------------------------------|-----------------------------------------------------|
| `go build ./...`                                 | **PASS** (clean)                                    |
| `golangci-lint run ./...` (v2.5.0)               | **PASS** (0 issues)                                 |
| `go test ./... -short -count=1`                  | **PASS** (all 32 testable packages)                 |
| `ruff check omega/`                              | **PASS** (0 issues, 252 files)                      |
| `ruff format --check omega/`                     | **PASS** (252 files already formatted)              |
| `mypy omega/core/ --ignore-missing-imports`      | 239 errors in 28 files (unchanged baseline)         |
| `pytest tests/test_action_contracts.py`          | **PASS** (28/28)                                    |
| Targeted regression sample (~250 tests, 9 files) | **9 failures** (4 baseline + 5 new V148 regressions)|
| Stale raw action literals                        | 2 hits, all in comments/docstrings (no real usage)  |
| Direct `os.environ.get(...API_KEY/SECRET)`       | 12 hits across 8 files (unchanged from 2026-05-10)  |

Net status vs 2026-05-10: Go pipeline still clean. Python lint/format/contract surface still clean. Mypy baseline unchanged. **Last week's regression resolved** — `test_no_single_direction_dominates` now passes. **Five new test regressions** in `test_signal_integrity.py` (threshold mismatches from the V148 best-of-phases commit on May 9). Four baseline failures (`test_adversarial_v2`, `test_backtest_evaluator`, two in `test_feedback_loop`) are unchanged from the 2026-05-10 baseline.

## Sandbox setup notes

The session image ships with Python 3.10 only and no Go toolchain. To run this review I:

1. Downloaded Go 1.25.0 (project requires `go 1.25.0`) into `/tmp/go/`.
2. Installed `golangci-lint` v2.5.0 (the project `.golangci.yml` is v2 schema; the v2.0.x release I tried first was built with Go 1.24 and rejected the 1.25 go.mod with `the Go language version (go1.24) used to build golangci-lint is lower than the targeted Go version (1.25.0)`).
3. Persisted `GOPATH`/`GOCACHE`/`GOLANGCI_LINT_CACHE` under `/tmp/` to avoid filling the bind-mounted `/sessions` volume (which started at 96% capacity).
4. Used `uv python install 3.11` (`UV_PYTHON_INSTALL_DIR=/tmp/uvpy`) and `pip install --break-system-packages numpy psycopg betterproto pyyaml httpx pydantic pytest pytest-timeout pytest-xdist` because the codebase imports `datetime.UTC` (3.11+). All 8 contract tests fail under 3.10 with `ImportError: cannot import name 'UTC' from 'datetime'`.
5. Used `--cache-dir=/tmp/mypy_cache` because mypy's default cache hit `sqlite3.OperationalError: disk I/O error` on the bind-mounted project folder under the existing `.mypy_cache/` directory.

The full Python test suite (2730 tests collected) still doesn't fit cleanly in the 45 s sandbox windows. Full-suite reporting is approximated via a focused regression sample of nine test files: `test_action_contracts.py`, `test_v49_gates.py`, `test_node.py`, `test_signal_integrity.py`, `test_meta_harness.py`, `test_orchestrator.py`, `test_adversarial_v2.py`, `test_backtest_evaluator.py`, `tests/integration/test_feedback_loop.py`.

## Go quality

Clean across the board.

`go build ./...` — passes after the initial module download. No errors, no warnings.

`golangci-lint run ./...` — **0 issues** with the full enabled linter set (errcheck, govet, staticcheck, unused, ineffassign, gosec, gocritic, nilerr, prealloc, misspell, unconvert). The `.golangci.yml` config loaded cleanly under v2.5.0.

`go test ./... -short -count=1` — all 32 testable packages PASS:

```
ok  internal/adversarial    internal/api    internal/auth     internal/boundary
   internal/bridge       internal/config   internal/conformance   internal/controlplane
   internal/coord        internal/coordination   internal/core   internal/db
   internal/eval         internal/framework   internal/handler   internal/heartbeat
   internal/integrations internal/memory   internal/middleware    internal/observability
   internal/polymarket   internal/registry  internal/skills    internal/terminal
   internal/tools
```

(Plus 11 packages with no test files — `cmd/eval-health`, `cmd/eval-runner`, `cmd/omega`, `cmd/omega-api`, `dashboard/node_modules/flatted/...`, `gen/go/omega/v1`, `gen/go/omega/v1/omegav1connect`, `internal/brain`, `internal/errors`, `internal/integrations/connectors`, `internal/projectseed`, `internal/telemetry`, `internal/testing`, `web/dashboard/node_modules/flatted/...`.)

## Python lint and format

`ruff check omega/` and `ruff format --check omega/` both clean. **252 files inspected**. No autofix needed.

## Python type check

`mypy omega/core/ --ignore-missing-imports` reports **239 errors in 28 files**. Identical to the 2026-05-10 / 2026-05-08 baseline.

Distribution unchanged:

- `omega/nodes/victoria/features.py` — 169 (transitively imported from `omega/core/`)
- `omega/nodes/victoria/hmm_regime.py` — 9
- `omega/nodes/victoria/strategy.py` — 6
- `omega/nodes/victoria/decision_embeddings.py` — 6
- `omega/nodes/victoria/signals/funding_rate.py` — 5
- `omega/nodes/victoria/signal_generation.py` — 4
- `omega/nodes/victoria/signals/yield_curve.py` — 3
- `omega/nodes/victoria/signals/geopolitical.py` — 3
- `omega/nodes/victoria/signals/dxy_signal.py` — 3
- `omega/nodes/victoria/llm_meta_controller.py` — 3
- Other `omega/nodes/victoria/*` — 12
- **`omega/core/*` — 8 errors** (3 in `project_config.py`, 3 in `meta_harness.py`, 1 each in `node_adapter.py`, `paper_trading.py`, `node_skills.py`, `llm_shell.py`, `decision_snapshot.py`, `alerting.py`)

Representative `omega/core/` errors (unchanged from prior weeks):

```
omega/core/project_config.py:265   "DataIngestionNode" has no attribute "_tickers"  [attr-defined]
omega/core/project_config.py:341   "StrategyNode" has no attribute "_min_conviction"  [attr-defined]
omega/core/project_config.py:348   Module "omega.core.paper_trading" has no attribute "PaperTradingExecutorNode"  [attr-defined]
omega/core/meta_harness.py:351     Returning Any from function declared "dict[str, Any]"  [no-any-return]
omega/core/meta_harness.py:357     Returning Any from function declared "int"  [no-any-return]
omega/core/meta_harness.py:702     Item "None" of "Any | None" has no attribute "consult"  [union-attr]
```

The bulk (169 errors) live in `omega/nodes/victoria/features.py` and are walked through during `omega/core/` transitive imports. Fixing those properly is a Victoria refactor (annotate pandas Series / numpy returns, narrow `Any | None` unions) that has been deferred as design work, not lint cleanup. **Not actionable in this automated pass.**

## Contract tests

`pytest tests/test_action_contracts.py -q` — **28/28 PASS** under Python 3.11. Under sandbox-default 3.10, all 8 capability tests fail with `ImportError: cannot import name 'UTC' from 'datetime'` — this is an environment issue, not a real regression. The project requires Python 3.11+ (see `pyproject.toml`).

## Targeted regression sample

Ran 9 test files (~250 tests) with `--timeout=15 -p no:cacheprovider`. Results: **9 failures**.

### Five new failures — `test_signal_integrity.py` (threshold mismatches from V148)

All five assert against documented thresholds in CLAUDE.md (`long=0.10`, `short=0.05` in NORMAL regime) but observe `_long_conviction_threshold=0.07`:

```
tests/test_signal_integrity.py::TestRegimeAdaptivity::test_normal_regime_thresholds
  assert 0.07 == 0.1
tests/test_signal_integrity.py::TestRegimeAdaptivity::test_bear_regime_suppresses_longs_permits_shorts
  Bear short threshold=0.04 (expected 0.05 — permissive shorts in bear market)
tests/test_signal_integrity.py::TestRegimeAdaptivity::test_bear_detection_threshold_at_055
  Bear regime triggering below 0.55 threshold — over-sensitive
tests/test_signal_integrity.py::TestRegressionGuard::test_bear_threshold_at_055
  Bear activating below 0.55
tests/test_signal_integrity.py::TestRegressionGuard::test_bull_threshold_at_055
  Bull activating below 0.55
```

Root cause: the V148 best-of-phases commit (`f2cff01`, May 9) introduced new threshold branches in `omega/nodes/victoria/strategy.py` (lines 1074 / 1088 / 1156-1157 set `self._long_conviction_threshold = 0.07` and apply 0.80x scaling), but did not update either the regression tests or the regime-threshold table in `CLAUDE.md` (which still documents `long=0.10, short=0.05` for NORMAL). These are real divergences between code, tests, and documentation. Recommended follow-up (NOT applied here — both options are strategy decisions, not lint cleanup):

1. If 0.07 is the intended V148 threshold: update `tests/test_signal_integrity.py` to assert the new values and update CLAUDE.md.
2. If 0.10 was supposed to be preserved: revert the threshold changes in `strategy.py` and document the V148 sizing/exit-only changes separately.

Last week's new regression `test_signal_integrity.py::TestBidirectionality::test_no_single_direction_dominates` **now passes** — the V148 changes appear to have rebalanced the long/short signal mix on the synthetic basket.

### Four baseline failures (unchanged from 2026-05-10)

```
tests/test_adversarial_v2.py::TestAdversarialPressureV2::test_ring2_activates_after_enough_cycles
tests/test_backtest_evaluator.py::TestImprovementEngineWithBacktestEvaluator::test_engine_uses_null_evaluator_by_default
tests/integration/test_feedback_loop.py::test_feedback_loop_params_change_over_time
tests/integration/test_feedback_loop.py::test_bad_signal_causes_flag_causes_improvement
```

Same fingerprints as 2026-05-08 / 2026-05-10. The integration feedback-loop tests connect to `http://localhost:8080` and warn `heartbeat: ... Connection refused` because the Go API isn't running in the sandbox.

## Stale code patterns

### Raw action literals — 2 hits (both safe)

```
omega/core/orchestrator_v2.py:439:   # node_type (e.g. "DATA_INGESTION" → "fetch_market_data"),
omega/nodes/victoria/victoria_node.py:28:  "compute_signals"   → run all signal types
```

Both are comments/docstrings explaining the action contract — not production string literals. Identical to the 2026-05-10 finding. No fix needed.

### Direct `os.environ.get(API_KEY/SECRET)` — 12 hits across 8 files (unchanged)

```
omega/core/startup_validator.py            (2: ANTHROPIC_API_KEY, COINGECKO_API_KEY)
omega/nodes/victoria/data_cache.py         (1: FRED_API_KEY)
omega/nodes/victoria/unusual_whales_provider.py (1: UW_API_KEY)
omega/nodes/victoria/whale_signal.py       (2: WHALE_ALERT_API_KEY, COINGLASS_API_KEY)
omega/nodes/victoria/data_providers.py     (2: CG_API_KEY, COINBASE_API_KEY)
omega/nodes/victoria/llm_meta_controller.py (1: ANTHROPIC_API_KEY)
omega/nodes/polymarket/clob_client.py      (2: POLYMARKET_API_KEY, POLYMARKET_API_SECRET)
omega/integrations/twitter_feed.py         (1: SN13_API_KEY)
```

Same set as 2026-05-10 — these bypass the `omega/core/credentials.py` lookup and should be migrated. Tracked tech debt; not actionable in this automated pass without coordination with the credentials registry.

## Action items

Nothing fixable automatically remains. Recommended manual follow-ups:

1. **Resolve V148 threshold/test/doc divergence** in `tests/test_signal_integrity.py` and `omega/nodes/victoria/strategy.py` (5 test failures). Decide whether 0.07 is the new floor or whether to revert.
2. **Migrate the 12 `os.environ.get(API_KEY|SECRET)` sites** to use `omega.core.credentials`.
3. **Chip away at the 8 mypy errors in `omega/core/`** — these are tractable in isolation (3 `attr-defined` on dynamically-set node attributes in `project_config.py`, 3 `Any`-return / `None`-attribute in `meta_harness.py`, 2 more single-issue files).
4. **Reconnect the four feedback-loop / adversarial baseline failures** to either a running Go API in CI or stub them out.
