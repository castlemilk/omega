# Omega Code Quality Review — 2026-05-08

Automated scheduled run. Branch: `main`. Working tree was already dirty
(1,449 entries — mostly training artifacts, `__pycache__`, and a Victoria
in-flight refactor); no fixes were committed in this pass to avoid
entangling them with that pre-existing work.

## Sandbox constraints (relevant)

The scheduled-task sandbox has only Python 3.10 and is missing Go,
`golangci-lint`, `mypy` (binary), `pytest-xdist` etc. by default. The
Omega codebase requires Python 3.11+ (uses `from datetime import UTC`),
so the bulk of the test suite cannot run here. Tools were installed via
`pip --break-system-packages` where possible. The Go pipeline could not
be evaluated at all from this environment.

## Step 1 — Go quality checks

| Check | Result |
| --- | --- |
| `go build ./...` | Skipped — Go toolchain not available in sandbox |
| `golangci-lint run ./...` | Skipped — toolchain not available |
| `go test ./... -short -count=1` | Skipped — toolchain not available |

These need to be re-run from the developer machine (or a CI image with
Go installed).

## Step 2 — Python quality checks

| Check | Result |
| --- | --- |
| `ruff check omega/` | All checks passed (0 issues) |
| `ruff format --check omega/` | 252 files already formatted (0 changes) |
| `mypy omega/core/ --ignore-missing-imports` | 239 errors across 28 files (74 source files checked) |
| `pytest tests/test_action_contracts.py -q` | Cannot execute — Python 3.10 sandbox lacks `datetime.UTC` |

### mypy error breakdown

```
173 [arg-type]
 23 [no-any-return]
 12 [attr-defined]
 11 [assignment]
  8 [no-untyped-def]
  4 [index]
  4 [float]
  3 [union-attr]
  2 [unused-ignore]
  2 [ticker]
  2 [str]
  2 [misc]
  2 [import]
  1 [k]
  1 [int]
  1 [comparison-overlap]
```

Representative samples:

- `omega/nodes/victoria/signal_generation.py:118` — `_ActivationTracer = None`
  vs `type[ActivationTracer]` (assignment).
- `omega/nodes/victoria/victoria_node.py:255,260` — `_reinforcer` and
  `_tracer` are missing return type annotations.
- `omega/core/project_config.py:265,341` — `node._tickers` /
  `node._min_conviction` set on objects whose declared type doesn't
  expose those attributes.
- `omega/core/project_config.py:348` — imports
  `PaperTradingExecutorNode` from `omega.core.paper_trading`, but the
  module no longer exports that name (`attr-defined`).
- `omega/core/meta_harness.py:702` — `self._brain.consult(...)` called
  without narrowing `Optional[Brain]`.

These are pre-existing issues, not introduced by this run. The volume
(239 errors, dominated by `arg-type`) makes auto-fixing risky in an
unattended task — silent fixes here could change runtime semantics.
**Recommended: convert this into a tracked debt item and fix
incrementally per file rather than en masse.**

## Step 3 — Fixes applied

None committed. Rationale:

1. `ruff check` and `ruff format --check` were both clean, so there
   was nothing to auto-fix from the lint pass.
2. mypy errors are pre-existing and non-trivial; auto-rewriting
   types/annotations across 28 files unattended would be reckless.
3. The working tree is heavily dirty with in-flight Victoria changes
   and training artifacts (1,449 entries). A "chore: automated code
   quality fixes" commit produced from inside that state would
   inevitably grab unrelated diffs.

No `git commit` was issued.

## Step 4 — Full Python test suite

`pytest tests/ -q --timeout=120` could not run: tests fail at import
time because the codebase uses `from datetime import UTC` (Python
3.11+) and the sandbox is on Python 3.10. This is an **environment
issue, not a regression**. The exact failure:

```
omega/nodes/victoria/strategy.py:145: in <module>
    from datetime import UTC, datetime
E   ImportError: cannot import name 'UTC' from 'datetime'
```

To re-validate, run from the developer machine:

```
python3 -m pytest tests/ -q --timeout=120
```

## Step 5 — Stale code patterns

### Raw string action literals

`grep -rn '"fetch_market_data"\|"compute_signals"' omega/ --include="*.py"`:

| File:line | Kind |
| --- | --- |
| `omega/core/actions.py:41` | `NodeAction.FETCH_MARKET_DATA = "fetch_market_data"` (canonical enum, expected) |
| `omega/core/actions.py:42` | `NodeAction.COMPUTE_SIGNALS = "compute_signals"` (canonical enum, expected) |
| `omega/core/orchestrator_v2.py:439` | Inside a comment — not a real literal |
| `omega/nodes/victoria/victoria_node.py:28` | Inside a docstring — not a real literal |

**Verdict: clean.** No raw-string action literals are being used as
runtime values. The CONTRIBUTING.md constraint is intact.

### `os.environ.get(...API_KEY|SECRET...)` outside `credentials.py`

12 hits across 9 files; `omega/core/credentials.py` provides a
`CredentialStore` that is the intended single resolver but several
modules still bypass it:

| File:line | Variable |
| --- | --- |
| `omega/integrations/twitter_feed.py:294` | `SN13_API_KEY` |
| `omega/core/startup_validator.py:271` | `ANTHROPIC_API_KEY` / `CLAUDE_API_KEY` |
| `omega/core/startup_validator.py:275` | `COINGECKO_API_KEY` / `CG_API_KEY` |
| `omega/nodes/polymarket/clob_client.py:236-237` | `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET` |
| `omega/nodes/victoria/llm_meta_controller.py:405` | `ANTHROPIC_API_KEY` |
| `omega/nodes/victoria/data_cache.py:104` | `FRED_API_KEY` |
| `omega/nodes/victoria/data_providers.py:37` | `CG_API_KEY` |
| `omega/nodes/victoria/data_providers.py:933` | `COINBASE_API_KEY` |
| `omega/nodes/victoria/unusual_whales_provider.py:45` | `UW_API_KEY` |
| `omega/nodes/victoria/whale_signal.py:375` | `WHALE_ALERT_API_KEY` |
| `omega/nodes/victoria/whale_signal.py:391` | `COINGLASS_API_KEY` |

**Recommended follow-up:** migrate each of these to
`credentials.get(...)` (and call `credentials.register(...)` once
during node init) so the credential audit surface is unified. Low risk
file-by-file; not appropriate as a single sweeping commit.

## Step 6 — Summary

| Metric | Value |
| --- | --- |
| Lint issues found (Python ruff) | 0 |
| Lint issues fixed (Python ruff) | 0 (none needed) |
| Format diffs | 0 |
| Mypy errors (pre-existing) | 239 across 28 files |
| Tests run | 0 (env unable to import codebase) |
| Test pass rate | n/a |
| Regressions introduced | 0 |
| Raw-string action literals | 0 (only enum definitions + comment/docstring mentions) |
| `os.environ.get(...API_KEY|SECRET...)` outside `credentials.py` | 12 (cleanup recommended) |

## Success-criteria check

| Criterion | Status |
| --- | --- |
| `go build ./...` passes | Not verified (no Go in sandbox) |
| `golangci-lint run ./...` returns 0 issues | Not verified (no Go in sandbox) |
| `ruff check omega/` returns 0 issues | PASS |
| All Go test packages pass | Not verified (no Go in sandbox) |
| Contract tests pass | Not verified (Python 3.10 sandbox can't import) |
| No regressions in Python test suite | No regressions introduced (no fixes committed) |

## Recommendation

Re-run this task on a developer machine (Python 3.11+, Go installed)
to cover the steps that were skipped here. The Python lint surface is
already clean; the next debt items to attack are the 239 mypy errors
in `omega/core/` and the 12 raw-`os.environ` credential reads.
