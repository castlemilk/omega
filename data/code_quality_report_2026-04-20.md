# Omega Code Quality Review — 2026-04-20

Automated scheduled run of `omega-code-quality-review`.

## Summary

| Check | Result | Notes |
|---|---|---|
| `go build ./...` | PASS | 0 errors |
| `golangci-lint run ./...` (v2.5.0) | PASS | 0 issues |
| `go test ./... -short -count=1` | PASS | All packages with tests passed |
| `ruff check omega/` | PASS after fixes | 56 → 0 (46 auto-fixed, 10 manually) |
| `ruff format --check omega/` | PASS after fixes | 6 files reformatted |
| `mypy omega/core/ --ignore-missing-imports` | 19 pre-existing errors | Not introduced by this run |
| `pytest tests/test_action_contracts.py` | PASS | 28 passed |
| `pytest tests/` (full) | NOT COMPLETED | sandbox shell timed out / locked |
| Stale action-literal grep | Clean | Only legitimate uses |
| Stale `os.environ.get(API_KEY|SECRET)` grep | 12 hits | Documented below |

## 1. Go quality

### `go build ./...`
Clean build, exit 0. Modules downloaded automatically (`go1.25.0` toolchain pulled by go.mod).

### `golangci-lint run ./...`
golangci-lint v2.5.0 (matches `version: "2"` in `.golangci.yml`).
Result: `0 issues.`

Linters enabled in config: errcheck, govet, staticcheck, unused, ineffassign, gosec, gocritic, nilerr, prealloc, misspell, unconvert.

### `go test ./... -short -count=1`
All test packages passed. Notable: `internal/api`, `internal/integrations`, `internal/observability`, `internal/memory`, `internal/core` all green. No flakes observed in the short run.

## 2. Python quality

### Initial `ruff check omega/`: 56 errors

| Rule | Count | Action |
|---|---|---|
| UP006 (PEP 585 builtin generics) | 23 | Auto-fixed |
| N806 (uppercase var in function) | 11 | Manually renamed |
| UP035 (deprecated import) | 5 | Auto-fixed |
| UP045 (PEP 604 Optional) | 5 | Auto-fixed |
| UP037 (quoted annotation) | 4 | Auto-fixed |
| F401 (unused import) | 2 | Auto-fixed |
| I001 (unsorted imports) | 2 | Auto-fixed |
| F841 (unused variable) | 1 | Manually removed |
| RUF012 (mutable class default) | 1 | `ClassVar` annotation |
| SIM102 (collapsible if) | 1 | Combined with `and` |
| UP017 (datetime.timezone.utc → UTC) | 1 | Auto-fixed |

After fixes: `All checks passed!` (0 issues).

### Manual fixes applied
* `omega/nodes/victoria/bayesian_regime.py` — renamed Welford `M2` → `m2`; added `from typing import ClassVar`; annotated `_DEFAULT_SIGNAL_NAMES: ClassVar[list[str]]`.
* `omega/nodes/victoria/confidence_surface.py` — renamed `original_T` → `original_temperature`; renamed loop variable `T` → `temp`.
* `omega/nodes/victoria/llm_meta_controller.py` — renamed `ml_T`/`llm_T`/`blended_T` → `ml_temp`/`llm_temp`/`blended_temp` (semantics preserved, all use sites updated together).
* `omega/nodes/victoria/meta_learner.py` — renamed `old_T` → `old_temp`; removed unused `old_center` assignment.
* `omega/nodes/victoria/strategy.py` — collapsed nested `if self._llm_meta_ctrl is not None: if ...should_call(...)` into a single `if (... and ...)` block; re-indented body.

### `ruff format`
Originally 6 files needed reformatting; ran `ruff format omega/`. After format: `252 files already formatted` and re-running `ruff check omega/` still shows 0 issues.

### `mypy omega/core/ --ignore-missing-imports`
19 errors across 9 files. **All are pre-existing** — none of the touched files (under `omega/nodes/victoria/`) are in `omega/core/`, so this run did not introduce any of them. Highlights for follow-up:

* `omega/core/node_skills.py:360` — comparison-overlap on `SignalLifecycle` enum.
* `omega/core/decision_snapshot.py:318` — missing return type annotation on `iter_snapshots`.
* `omega/core/paper_trading.py:150` — `Returning Any` from `float`-typed function.
* `omega/core/llm_shell.py:194` — `Returning Any` from `dict | None`-typed function.
* `omega/core/brain.py:759/909/912/915` — `str | None` not narrowed before string ops / assignment to `str`-typed slot.
* `omega/core/node_adapter.py:232/391/393` — `Returning Any` and `None` attribute access on optional `_layer`.
* `omega/core/project_config.py:265/341/348` — `_tickers`/`_min_conviction` attr-defined on dynamic node objects; `PaperTradingExecutorNode` symbol missing.
* `omega/core/overnight_runner.py:410/411` — `MetricsCollector`/`SystemAnalyzer` expect concrete `PostgresBackend`; passed abstract `StateBackend`.
* `omega/core/meta_harness.py:351/357/702` — `Returning Any` and `None` attr access on `_brain`.

These were left unmodified because each requires either a small structural decision (how to widen the parameter type, where to put the `assert ... is not None`, or whether to declare the attribute on the dataclass) and the scheduled-task safety guidance is to report rather than guess. Recommend opening a focused PR.

### Contract tests
`pytest tests/test_action_contracts.py -q` → **28 passed in 1.04s**. All node action / step contracts pass.

(Note: ran under Python 3.11.15 installed via `uv` because the sandbox's system Python is 3.10; `from datetime import UTC` requires 3.11+ as documented in `CLAUDE.md`.)

### Full test suite
`pytest tests/ --timeout=120` was started but the sandbox shell session became unresponsive partway through and never returned a result. The contract subset passed; broader coverage could not be confirmed in this run. Recommend re-running the full suite locally or in CI.

## 3. Stale code patterns

### Raw action literals (`fetch_market_data`, `compute_signals`)
Search: `grep -rn '"fetch_market_data"\|"compute_signals"' omega/ --include="*.py" | grep -v actions.py | grep -v NodeAction`

Hits (after exclusions):
* `omega/core/orchestrator_v2.py:439` — comment only.
* `omega/nodes/victoria/victoria_node.py:28` — docstring only.

No actual raw-literal action dispatch outside the permitted legacy aliases. **Clean.**

### Bare `os.environ.get(...API_KEY|SECRET)`
Search: `grep -rn 'os.environ.get.*API_KEY\|os.environ.get.*SECRET' omega/ --include="*.py" | grep -v credentials.py`

12 hits to migrate to `omega/core/credentials.py`:

```
omega/nodes/polymarket/clob_client.py:236         POLYMARKET_API_KEY
omega/nodes/polymarket/clob_client.py:237         POLYMARKET_API_SECRET
omega/integrations/twitter_feed.py:294            SN13_API_KEY
omega/core/startup_validator.py:271               ANTHROPIC_API_KEY / CLAUDE_API_KEY
omega/core/startup_validator.py:275               COINGECKO_API_KEY / CG_API_KEY
omega/nodes/victoria/data_cache.py:104            FRED_API_KEY
omega/nodes/victoria/unusual_whales_provider.py:45 UW_API_KEY
omega/nodes/victoria/llm_meta_controller.py:227   ANTHROPIC_API_KEY
omega/nodes/victoria/data_providers.py:37         CG_API_KEY
omega/nodes/victoria/data_providers.py:933        COINBASE_API_KEY
omega/nodes/victoria/whale_signal.py:375          WHALE_ALERT_API_KEY
omega/nodes/victoria/whale_signal.py:391          COINGLASS_API_KEY
```

Recommend a follow-up sweep to route all of these through `omega/core/credentials.py` (which exists) for consistent secret loading and redaction.

## 4. Commit status

Lint/format fixes were applied directly to the working tree (5 files in `omega/nodes/victoria/`). The scheduled task asks for a `chore: automated code quality fixes` commit; this could not be performed in the current run because the sandbox shell became unresponsive after the long pytest invocation. The fixes are present in the working tree and ready to commit:

```
git add omega/nodes/victoria/bayesian_regime.py \
        omega/nodes/victoria/confidence_surface.py \
        omega/nodes/victoria/llm_meta_controller.py \
        omega/nodes/victoria/meta_learner.py \
        omega/nodes/victoria/strategy.py
git commit -m "chore: automated code quality fixes"
```

## 5. Success criteria

| Criterion | Status |
|---|---|
| `go build ./...` passes | ✅ |
| `golangci-lint run ./...` 0 issues | ✅ |
| `ruff check omega/` 0 issues | ✅ (after fixes) |
| All Go test packages pass | ✅ (`-short`) |
| Contract tests pass | ✅ (28/28) |
| No regressions in Python test suite | ⚠️  Full suite did not finish in this run; subset (contract tests) clean. Re-run recommended. |
