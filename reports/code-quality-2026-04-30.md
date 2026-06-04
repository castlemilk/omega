# Code Quality Review — 2026-04-30

Automated run of `omega-code-quality-review`. The user is not present.

## TL;DR

- **Ruff lint**: clean (0 issues across `omega/`)
- **Ruff format**: clean (252 files already formatted)
- **Contract tests** (`tests/test_action_contracts.py`): 28/28 pass
- **Mypy** (`omega/core/`, `--follow-imports=silent --ignore-missing-imports`): 13 pre-existing errors in 8 files. None introduced by tracked source changes (no diff in `omega/core/*.py` since HEAD). Not auto-fixed — see "Why no fixes were committed" below.
- **Stale code patterns**: 0 raw action literals in production code. 12 `os.environ.get` call sites for `*_API_KEY`/`*_API_SECRET` outside `credentials.py`.
- **Go quality checks** (`go build`, `golangci-lint`, `go test`): **not run** — no Go toolchain in this sandbox (no `apt` access either; only `uv` for Python).
- **Full Python test suite**: collected (2730 tests). The sandbox lacks the heavy optional deps (scipy/sklearn/etc.), Postgres, and network egress, so a clean pass/fail signal isn't possible from here. The named gating test (`test_action_contracts.py`) passes.
- **Commits**: none. No fixes were applied — see below.

## Sandbox constraints discovered

This run executed in a Linux sandbox without `apt` or Go installed. `uv` was available, so Python 3.11 + ruff/mypy/pytest/numpy/psycopg/betterproto were installed at runtime. The Go and full-suite checks listed in the task spec could not be exercised end-to-end here. If the scheduled task is intended to run autonomously, the runner needs:

- `go` and `golangci-lint` on `PATH`
- Python 3.11 with project extras (`pip install -e '.[dev,math,telemetry]'`)
- Either a running Postgres reachable via `DATABASE_URL`, or the integration-tagged tests must be excluded with `-m 'not integration'`

## Ruff (omega/)

```
ruff check omega/        →  All checks passed!
ruff format --check omega/  →  252 files already formatted
```

Nothing to fix.

## Mypy (omega/core/, --follow-imports=silent)

13 errors in 8 files. All pre-existing (no source changes in `omega/core/*.py` since the last commit on `main`). Listed by file:

| File | Line | Error |
|---|---|---|
| `omega/core/node_skills.py` | 360 | Non-overlapping equality check |
| `omega/core/llm_shell.py` | 194 | Returning Any from typed function |
| `omega/core/decision_snapshot.py` | 318 | Function missing return type annotation (`iter_snapshots`) |
| `omega/core/alerting.py` | 251 | Argument 1 to `float()` has incompatible type |
| `omega/core/paper_trading.py` | 150 | Returning Any from typed function |
| `omega/core/node_adapter.py` | 391, 393 | `union-attr` on `Any \| None` |
| `omega/core/project_config.py` | 265 | `DataIngestionNode` has no attribute `_tickers` |
| `omega/core/project_config.py` | 341 | `StrategyNode` has no attribute `_min_conviction` |
| `omega/core/project_config.py` | 348 | `omega.core.paper_trading` has no attribute `PaperTradingExecutorNode` |
| `omega/core/meta_harness.py` | 351 | Returning Any from `dict[str, Any]`-typed function |
| `omega/core/meta_harness.py` | 357 | Returning Any from `int`-typed function |
| `omega/core/meta_harness.py` | 702 | `union-attr`: `self._brain.consult` may be None |

The `attr-defined` errors on `project_config.py` and `node_adapter.py` and the `union-attr` on `meta_harness.py:702` reflect real runtime invariants (the assignments are gated by isinstance/None checks not visible to mypy). Annotating these correctly is a behavior-touching change. The cheaper fixes (`iter_snapshots` return annotation, `cast()` for the Any-return cases) are straightforward but still touch eight files; doing so without a human-reviewed PR risks getting tangled with the 34 already-uncommitted files in the working tree.

**Recommendation**: open a follow-up ticket "Mypy debt cleanup in omega/core/" rather than have the scheduled job apply 13 small typing changes silently.

## Contract tests

```
python3.11 -m pytest tests/test_action_contracts.py -q
............................                                              [100%]
28 passed in 0.17s
```

The `NodeAction` enum / `STEP_TO_ACTION` table / Victoria capability registration contract tests all pass. No drift detected.

## Stale code patterns

### Raw action literals
```
grep '"fetch_market_data"\|"compute_signals"' omega/ --include="*.py"
  | grep -v actions.py | grep -v NodeAction
```

Two hits, both in **comments / docstrings only**, no behavior:
- `omega/core/orchestrator_v2.py:439` — comment explaining the lookup (`# node_type (e.g. "DATA_INGESTION" → "fetch_market_data"),`)
- `omega/nodes/victoria/victoria_node.py:28` — module docstring (`"compute_signals"   → run all signal types`)

No production code uses raw action literals. The action-contract enforcement is holding.

### `os.environ.get` for API keys / secrets

12 call sites outside `omega/core/credentials.py`:

```
omega/integrations/twitter_feed.py:294               SN13_API_KEY
omega/nodes/polymarket/clob_client.py:236            POLYMARKET_API_KEY
omega/nodes/polymarket/clob_client.py:237            POLYMARKET_API_SECRET
omega/core/startup_validator.py:271                  ANTHROPIC_API_KEY / CLAUDE_API_KEY
omega/core/startup_validator.py:275                  COINGECKO_API_KEY / CG_API_KEY
omega/nodes/victoria/data_cache.py:104               FRED_API_KEY (default "DEMO_KEY")
omega/nodes/victoria/llm_meta_controller.py:405      ANTHROPIC_API_KEY
omega/nodes/victoria/data_providers.py:37            CG_API_KEY (module-level)
omega/nodes/victoria/data_providers.py:933           COINBASE_API_KEY
omega/nodes/victoria/unusual_whales_provider.py:45   UW_API_KEY (module-level)
omega/nodes/victoria/whale_signal.py:375             WHALE_ALERT_API_KEY
omega/nodes/victoria/whale_signal.py:391             COINGLASS_API_KEY
```

`omega/core/credentials.py` exposes a `credentials.get(name)` helper that reads env + `.env` and returns None with a structured warning for missing optional creds. These 12 sites bypass it. `startup_validator.py` is the only one with a credible reason (it is *the* validator, intentionally raw); the rest are candidates for migration. Two are also evaluated at import time (`data_providers.py:37`, `unusual_whales_provider.py:45`), which means changing env after import is a no-op — separate latent issue.

**Not auto-migrated**. These are behavioral surface-area changes (`credentials.get` warns, returns `None` instead of `""`, and may have different `.env`-merge semantics from a literal `os.environ.get`). Migrate manually with a small audit per call site.

## Why no fixes were committed

The spec's success criteria are "0 issues". The auto-fixable categories already have 0 issues — ruff and format are clean and contract tests pass. The remaining findings (mypy debt, env-var migration) all require human judgment and would touch behavior. Applying them in an unattended commit alongside the 34 files of uncommitted human work-in-progress would entangle the diff and risk silent regressions. No `chore: automated code quality fixes` commit was made because there are no fixes.

## Suggested follow-ups (manual)

1. Install Go + Python 3.11 + project extras in the scheduled-task runner so steps 1, 4 actually exercise.
2. Open a ticket: "Mypy debt in omega/core/" with the 13 errors above. Most are 1–2 line fixes; a few (`project_config._tickers`/`_min_conviction`, `paper_trading.PaperTradingExecutorNode`) need the underlying class to declare the attribute or the import to point at the correct symbol.
3. Open a ticket: "Migrate omega/nodes/* and omega/integrations/* off bare `os.environ.get` for secrets onto `credentials.get`". Especially the two module-level reads.
4. Consider gating `addopts = "-n auto"` in `pyproject.toml` behind an env var — sandboxes without xdist die instantly because pytest reads the option before plugins discover.

---
*Generated by autonomous scheduled task `omega-code-quality-review`.*
