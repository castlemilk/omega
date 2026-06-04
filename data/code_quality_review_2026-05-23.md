# Omega Code Quality Review — 2026-05-23

Automated quality pass against `~/projects/omega` (branch `main`, HEAD `f2cff01`).

## TL;DR

- **Go: clean.** `go build`, `go vet`, `golangci-lint run`, and `go test ./... -short -count=1` all pass. 25 test packages OK, 0 failures, 0 lint issues.
- **Python lint/format: clean.** `ruff check omega/` and `ruff format --check omega/` both pass (252 files already formatted, 0 lint issues).
- **Python types: 8 pre-existing errors** in `omega/core/` under strict-mode `mypy`. Not regressions. Not auto-fixed (each requires per-call judgement).
- **Python tests: cannot validate in this sandbox.** The sandbox runs Python 3.10; the project requires 3.11+ (`from datetime import UTC` is used widely). All contract-test failures observed here are import-time failures from the version mismatch. Re-run on the host machine to validate.
- **Stale patterns: 12 direct env-var credential reads** that bypass `omega.core.credentials`. Worth a follow-up cleanup PR.

No commits were made — see "Why no commit" at the end.

---

## 1. Go quality checks

Toolchain: project-pinned `go1.25.0 linux/arm64`, `golangci-lint v2.6.1`.

| Check | Result |
|---|---|
| `go build ./...` | PASS (0 errors) |
| `go vet ./...` | PASS (0 errors) |
| `golangci-lint run ./...` | PASS (0 issues) |
| `go test ./... -short -count=1` | PASS — 25 packages `ok`, 0 `FAIL` |

Test packages that ran clean: `adversarial`, `api`, `auth`, `boundary`, `bridge`, `config`, `conformance`, `controlplane`, `coord`, `coordination`, `core`, `db`, `eval`, `framework`, `handler`, `heartbeat`, `integrations`, `memory`, `middleware`, `observability`, `polymarket`, `registry`, `skills`, `terminal`, `tools`.

### Minor finding — `.golangci.yml` schema is mixed v1/v2

`golangci-lint config verify` reports:

```
jsonschema: "issues" does not validate with .../additionalProperties: additional properties 'exclude-rules' not allowed
jsonschema: "" does not validate with .../additionalProperties: additional properties 'linters-settings' not allowed
```

The file is declared `version: "2"` but still uses the v1 keys `linters-settings` and `issues.exclude-rules`. The v2 binary tolerates them at runtime (the run reported 0 issues with the correct linter set enabled — `errcheck`, `gocritic`, `gosec`, `govet`, `ineffassign`, `misspell`, `nilerr`, `prealloc`, `staticcheck`, `unconvert`, `unused`), so this is a strict-validation warning rather than a runtime breakage. Worth migrating to v2 keys (`linters.settings`, `linters.exclusions.rules`) on the next config touch.

---

## 2. Python quality checks

Tooling: `ruff 0.15.14`, `mypy 1.20.2`, `pytest 8.4.2`.

| Check | Result |
|---|---|
| `ruff check omega/` | PASS — All checks passed |
| `ruff format --check omega/` | PASS — 252 files already formatted |
| `mypy omega/core/ --ignore-missing-imports` | 8 errors in 5 files (pre-existing) |
| `pytest tests/test_action_contracts.py` | Cannot validate in sandbox (Python 3.10 vs required 3.11+) |

### mypy errors in `omega/core/` (8)

Run with `--follow-imports=silent` to isolate `omega/core/` errors from the 226 errors that leak in via `omega/nodes/victoria/` imports (those are out of scope for this command).

| File:line | Code | Issue |
|---|---|---|
| `omega/core/node_skills.py:360` | `comparison-overlap` | `if ev.current_state != SignalLifecycle.RETIRED:` — mypy can prove `current_state` is never `RETIRED` based on its declared `Literal` union. Either the type should include `RETIRED`, or the check is dead defensive code that can be removed. |
| `omega/core/alerting.py:251` | `arg-type` | `float(sig_val.get("value", sig_val.get("composite", 1.0)))` — `dict.get()` can return `None`; wrap with a None-guard or assert. |
| `omega/core/node_adapter.py:391` | `union-attr` | `self._layer.fetch_with_failover(...)` — `self._layer` is `Any | None`; needs a None check before the call. |
| `omega/core/node_adapter.py:393` | `union-attr` | `self._layer.get_health_status()` — same `self._layer` Optional-access pattern. |
| `omega/core/project_config.py:265` | `attr-defined` | `node._tickers = list(tickers)` — `DataIngestionNode` has no declared `_tickers`. Add an annotation on the class or use a setter. |
| `omega/core/project_config.py:341` | `attr-defined` | `node._min_conviction = ...` — same dynamic-attr-set pattern on `StrategyNode`. |
| `omega/core/project_config.py:348` | `attr-defined` | `from omega.core.paper_trading import PaperTradingExecutorNode` — module has no `PaperTradingExecutorNode` export. Either the symbol moved or the import is dead. |
| `omega/core/meta_harness.py:703` | `union-attr` | `self._brain.consult(...)` — `self._brain` is `Any | None`; needs None guard. |

These are real tech-debt items but each one needs reading the surrounding control flow (some may be dead code, some need annotations, some need None guards). Not safe to apply as a blind batch in autonomous mode — see the "Why no commit" section.

### Why the `mypy omega/core/` report shows 234 errors without `--follow-imports=silent`

Running the literal command in the task spec returned 234 errors across 25 files. 226 of those are in `omega/nodes/victoria/*` and other project (not platform) code, dragged in transitively. With `--follow-imports=silent` the result collapses to the 8 platform-only errors listed above. Worth changing the recurring task's mypy invocation to include `--follow-imports=silent` so the signal is project-scoped.

### Contract tests (`tests/test_action_contracts.py`)

Result: **7 failed, 21 passed** in this sandbox. **All 7 failures are environment-only**, identical traceback:

```
omega/nodes/polymarket/clob_client.py:63: in <module>
    from datetime import UTC, datetime
E   ImportError: cannot import name 'UTC' from 'datetime' (/usr/lib/python3.10/datetime.py)
```

`datetime.UTC` was added in Python 3.11. The project sets `requires-python = ">=3.11"` and `tool.mypy.python_version = "3.11"`. The sandbox has 3.10.12, with no 3.11 binary installed and no sudo to `apt install python3.11`. These tests should pass on the host machine.

The 21 contract tests that did pass exercise the action/step contract on enums, dispatch routing, and capability declarations for nodes that don't touch the polymarket module.

---

## 3. Full Python test suite (`pytest tests/ -q --timeout=120`)

The suite collects 1626 items. Under the project default config (`pytest-xdist -n auto`, 4 workers) the run completed with approximately:

- ~1280 passed
- ~171 failed
- ~180 skipped

Under sequential collection (`pytest tests/`, no xdist) the result is **46 collection errors** — every test module that transitively imports `omega.nodes.victoria.strategy` fails at import because of the same `from datetime import UTC` line. With xdist the failures distribute across workers and are reported as test failures rather than collection errors, but the underlying cause is identical.

**Conclusion: the Python test suite cannot be meaningfully validated from this sandbox.** A re-run on the host (which has Python 3.11+) is required to determine real pass/fail counts and any regressions.

---

## 4. Stale code patterns

### Raw string action literals

Search: `grep -rn '"fetch_market_data"\|"compute_signals"' omega/ --include="*.py" | grep -v actions.py | grep -v NodeAction`

Hits (2):

1. `omega/core/orchestrator_v2.py:439` — inside a comment (`# node_type (e.g. "DATA_INGESTION" → "fetch_market_data"),`).
2. `omega/nodes/victoria/victoria_node.py:28` — inside a docstring (`"compute_signals" → run all signal types`).

**No actual code uses raw action strings.** Both hits are documentation references. Contract is intact — all dispatch goes through `omega.core.actions.NodeAction`.

### Direct env reads that should use `omega.core.credentials`

Search: `grep -rn 'os.environ.get.*API_KEY\|os.environ.get.*SECRET' omega/ --include="*.py" | grep -v credentials.py`

Hits (12):

| File:line | Variable |
|---|---|
| `omega/core/startup_validator.py:271` | `ANTHROPIC_API_KEY` / `CLAUDE_API_KEY` |
| `omega/core/startup_validator.py:275` | `COINGECKO_API_KEY` / `CG_API_KEY` |
| `omega/nodes/victoria/data_cache.py:104` | `FRED_API_KEY` |
| `omega/nodes/victoria/unusual_whales_provider.py:45` | `UW_API_KEY` |
| `omega/nodes/victoria/whale_signal.py:375` | `WHALE_ALERT_API_KEY` |
| `omega/nodes/victoria/whale_signal.py:391` | `COINGLASS_API_KEY` |
| `omega/nodes/victoria/data_providers.py:37` | `CG_API_KEY` |
| `omega/nodes/victoria/data_providers.py:933` | `COINBASE_API_KEY` |
| `omega/nodes/victoria/llm_meta_controller.py:405` | `ANTHROPIC_API_KEY` |
| `omega/nodes/polymarket/clob_client.py:236` | `POLYMARKET_API_KEY` |
| `omega/nodes/polymarket/clob_client.py:237` | `POLYMARKET_API_SECRET` |
| `omega/integrations/twitter_feed.py:294` | `SN13_API_KEY` |

`omega/core/credentials.py` exists and provides a typed central store (`from omega.core.credentials import credentials; credentials.get("...")`). These 12 sites should be migrated. Worth a follow-up PR — none are platform code, all are project (victoria / polymarket / twitter) integrations.

`omega/core/startup_validator.py` is a special case: it's deliberately checking which env vars are present at boot. It could still route through `credentials.get` to centralise the discovery, but the semantics are fine as-is.

---

## Why no commit

The task plan calls for committing fixes under `chore: automated code quality fixes`. No commit was created because no fixes were applied. The reasoning:

- **Lint and format are already clean** (Go and Python both at 0 issues). Nothing to fix.
- **Go tests all pass.** Nothing to fix.
- **mypy errors are not safe to auto-fix from a sandboxed agent run.** Each of the 8 platform-side errors needs a code-reading judgement (is this dead defensive code? a missing annotation? a missing None guard? a stale import?). Sprinkling `# type: ignore` or speculative `assert x is not None` lines would silence mypy without addressing the underlying intent, and would be hard to review.
- **Python tests can't be validated.** The sandbox is Python 3.10 and the project requires 3.11+. Committing any Python change without being able to run the test suite would be irresponsible.

Pre-existing state (lint-clean, build-clean, tests-passing for Go) was preserved. The findings above are the deliverable.

---

## Recommended follow-ups (separate PRs)

1. **`.golangci.yml` v2 schema migration** — move `linters-settings` → `linters.settings`, `issues.exclude-rules` → `linters.exclusions.rules`. Silences `golangci-lint config verify`.
2. **Resolve the 8 `omega/core/` mypy errors.** Group by file; review each in context. `project_config.py:348` (the dead `PaperTradingExecutorNode` import) is the most concerning — looks like it may raise at runtime if that codepath is reached.
3. **Credential reads migration.** Move the 12 direct `os.environ.get` sites onto `omega.core.credentials`.
4. **Tighten the scheduled mypy command** to `mypy omega/core/ --ignore-missing-imports --follow-imports=silent` so the platform-only signal isn't drowned out by 226 errors from `omega/nodes/victoria/`.

---

*Generated by automated code quality review run on 2026-05-23.*
