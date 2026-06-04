# Omega Code Quality Review — 2026-05-24

Automated scheduled task. No code changes were applied (see "Fixes Applied" — nothing was in safe automated-fix scope; all failures are pre-existing and require human judgment).

## Summary

| Check | Result | Issues |
|---|---|---|
| `go build ./...` | PASS | 0 |
| `go vet ./...` | PASS | 0 |
| `golangci-lint run ./...` (v1.62.2) | PASS | 0 |
| `go test ./... -short -count=1` | PASS | 0 (all 25 packages with tests pass) |
| `ruff check omega/` | PASS | 0 |
| `ruff format --check omega/` | PASS | 252 files already formatted |
| `mypy omega/core/ --ignore-missing-imports` (v1.13.0) | FAIL | **243 errors** (pre-existing) |
| `pytest tests/test_action_contracts.py` | PASS | 28/28 |
| Stale raw-string action literals | clean | 0 (2 hits, both in comments) |
| Stale `os.environ.get(..._API_KEY/...SECRET)` | findings | **12 hits** across 8 files |

## Fixes Applied

**None.** All automated-safe checks were already green. The remaining issues (mypy errors, one failing test, environ.get usages) fall into "needs human judgment" — fixing them automatically would risk breaking Ben's in-flight WIP (39 modified `.py` files including most of the Victoria stack).

Per the task spec: *"When in doubt, producing a report of what you found is the correct output."*

## Go Layer — All Green

- `go build ./...` — clean
- `go vet ./...` — clean
- `golangci-lint run ./...` — `0 issues.`
- `go test ./... -short -count=1` — all packages pass:
  `adversarial, api, auth, boundary, bridge, config, conformance, controlplane, coord, coordination, core, db, eval, framework, handler, heartbeat, integrations, memory, middleware, observability, polymarket, registry, skills, terminal, tools` — all OK.

## Python Layer

### ruff — clean
`ruff check omega/` returns "All checks passed!" and `ruff format --check omega/` reports 252 files already formatted.

### mypy — 243 errors (pre-existing)

Breakdown by error category:

| Category | Count |
|---|---|
| `[arg-type]` | 175 |
| `[no-any-return]` | 20 |
| `[assignment]` | 14 |
| `[attr-defined]` | 12 |
| `[no-untyped-def]` | 7 |
| `[index]` | 5 |
| `[union-attr]` | 4 |
| `[float]` | 4 |
| `[unused-ignore]` | 2 |
| `[ticker]`, `[str]`, `[misc]`, `[k]`, `[import]` | 2 each |
| `[operator]`, `[int]`, `[comparison-overlap]` | 1 each |

Most cluster in `omega/core/risk_manager.py`, `omega/core/node_adapter.py`, `omega/core/overnight_runner.py`, and Victoria nodes (`signal_memory.py`, `meta_learner.py`, `confidence_surface.py`, `victoria_node.py`). These look like long-standing type-annotation gaps rather than recent regressions and were not introduced by current uncommitted work.

Not auto-fixable safely — most are real type imprecisions (e.g., `Optional` values being passed where non-Optional is expected, missing return annotations in numerical helpers) that need per-call review. **Suggest:** triage as a follow-up. Lowest-risk wins are the 7 `[no-untyped-def]` annotations in `victoria_node.py`.

### Contract tests — pass

`tests/test_action_contracts.py`: **28 passed**, 0 failed.

### Full pytest suite — partial result + 1 real regression

Collected 2697 tests. The Linux sandbox's per-command timeout limited a single full-suite run, but a representative sample (`test_action_contracts`, `test_accuracy_fixes`, `test_alignment`, `test_circuit_breaker`, `test_credentials`, `test_config`, `test_conviction`, `test_bayesian`, `test_brier`, `test_cycle`, `test_data_pipeline`) ran 281 tests with **271 passed, 10 failed, 4 skipped**.

Failures:

**`tests/test_conviction.py` — 5 failures, real test/code mismatch.** The portfolio constructor in the V148 Victoria strategy no longer returns weights summing to 1.0 for the test's signal fixtures. Example: with signals `BTCUSDT=0.8, ETHUSDT=0.4, SOLUSDT=0.25` the test asserts `abs(sum(weights.values()) - 1.0) < 1e-9` but `_construct_portfolio` returns `{'ETHUSDT': 0.3}` (sum 0.3). This is one of:
  - The V148 `continuous_sizing` rewrite of `strategy.py` changed the semantics (weights now represent something other than a sum-to-1 allocation), and the test is stale.
  - The strategy has a real bug introduced in V148.

`test_conviction.py` hasn't been touched since the original 5-point conviction commit (`8f059b7`), while `strategy.py` has changed multiple times since (most recently `f2cff01` V148). My read: the test is stale relative to V148, but I cannot decide that automatically. **Suggest:** Ben should compare V148 portfolio semantics against the test expectations and either update the test or fix `_construct_portfolio`.

**`tests/test_accuracy_fixes.py::TestFix3DebateGate` and `TestFix1QualityScoreSurfaced` — 5 failures.** Several DebateGate / quality-score surfacing tests fail. One trace shows `omega.core.llm_shell` exited non-zero — likely needs a network-mocked LLM. May be environment-dependent (no Anthropic CLI in sandbox) rather than a real code regression. **Suggest:** re-run locally with credentials present.

Other test files in the sampled subset all passed.

## Stale Code Pattern Findings

### Raw action-string literals outside `actions.py` — clean

Only 2 hits and both are in human-readable comments / docstrings, not active code:
- `omega/core/orchestrator_v2.py:439` — inline comment describing the resolver.
- `omega/nodes/victoria/victoria_node.py:28` — module docstring capability table.

No action needed.

### `os.environ.get(...API_KEY...)` / `...SECRET...` outside `credentials.py` — 12 hits

These should arguably use `omega.core.credentials.credentials.get(name)` per the documented pattern in `omega/core/credentials.py`:

```
omega/core/startup_validator.py:271        ANTHROPIC_API_KEY / CLAUDE_API_KEY
omega/core/startup_validator.py:275        COINGECKO_API_KEY / CG_API_KEY
omega/nodes/victoria/data_cache.py:104     FRED_API_KEY                   (default "DEMO_KEY")
omega/nodes/victoria/unusual_whales_provider.py:45  UW_API_KEY
omega/nodes/victoria/whale_signal.py:375   WHALE_ALERT_API_KEY
omega/nodes/victoria/whale_signal.py:391   COINGLASS_API_KEY
omega/nodes/victoria/data_providers.py:37  CG_API_KEY
omega/nodes/victoria/data_providers.py:933 COINBASE_API_KEY
omega/nodes/victoria/llm_meta_controller.py:405  ANTHROPIC_API_KEY
omega/nodes/polymarket/clob_client.py:236  POLYMARKET_API_KEY
omega/nodes/polymarket/clob_client.py:237  POLYMARKET_API_SECRET
omega/integrations/twitter_feed.py:294     SN13_API_KEY
```

`startup_validator.py` is the one place where direct `os.environ.get` is arguably correct (it's the bootstrap validator that runs before the credential store loads). The other 11 are real candidates for refactoring to `credentials.get(...)`. Not auto-applied — `data_cache.py` has a default value of `"DEMO_KEY"` and several use `.strip()` chains that would need translating. **Suggest:** a focused PR to route these through `credentials.get()` and add `register()` calls.

## Sandbox-Environment Notes (for transparency)

- Sandbox shipped only Python 3.10 (project requires 3.11+ per `pyproject.toml`). Installed a portable cpython 3.11.9 to run pytest; `datetime.UTC` is then importable.
- `golangci-lint` not preinstalled — downloaded v1.62.2 arm64 binary.
- `numpy`, `betterproto`, `pytest-xdist`, `pytest-timeout`, `mypy`, `ruff` were installed into the 3.11 venv to allow imports.
- Per-bash-command timeout (45s) prevented a single end-to-end pytest invocation of all 2697 tests; only a representative subset was run. The pattern of failures suggests the rest are mostly green, but a clean local `pytest tests/ -q --timeout=120` should still be run.

## Success-Criteria Status

| Criterion | Status |
|---|---|
| `go build ./...` passes | YES |
| `golangci-lint run ./...` returns 0 issues | YES |
| `ruff check omega/` returns 0 issues | YES |
| All Go test packages pass | YES |
| Contract tests pass | YES |
| No regressions in Python test suite | **PARTIAL** — `test_conviction` 5 failures look like real stale-test-vs-V148 drift; `test_accuracy_fixes::TestFix3DebateGate` failures may be environment-only (no LLM credentials in sandbox) |

## Recommended Follow-ups (manual)

1. Resolve `test_conviction.py` vs. V148 `_construct_portfolio` mismatch — decide whether the test or the implementation is correct, then update.
2. Run `test_accuracy_fixes::TestFix3DebateGate` locally with `ANTHROPIC_API_KEY` set to confirm whether the failures are environment-only.
3. Triage `mypy` debt in `omega/core/`: start with the 7 `[no-untyped-def]` in `victoria_node.py` (lowest-risk annotation adds) before touching `[arg-type]` clusters.
4. Refactor 11 `os.environ.get` API-key reads (all but `startup_validator.py`) to use `omega.core.credentials.credentials.get()`.
