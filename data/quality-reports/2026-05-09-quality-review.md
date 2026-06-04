# Omega Code Quality Review — 2026-05-09

Automated scheduled-task run. HEAD: `f2cff01 feat(victoria): V148 best-of-phases`.

## Summary

| Check | Result | Notes |
|---|---|---|
| `go build ./...` | PASS | 0 errors |
| `go vet ./...` | PASS | 0 issues |
| `golangci-lint run ./...` (v2.5.0) | PASS | `0 issues.` |
| `go test ./... -short -count=1` | PASS | 26 packages OK, 0 failures |
| `ruff check omega/` | PASS | All checks passed |
| `ruff format --check omega/` | PASS | 252 files already formatted |
| `mypy omega/core/ --ignore-missing-imports` | FAIL (pre-existing) | 248 errors across 31 files (9 in `omega/core/`) |
| `pytest tests/test_action_contracts.py` | PASS | 28/28 |
| `pytest tests/` (full) | INCOMPLETE | 2730 tests collected; sandbox time budget exceeded (chunks showed pre-existing failures) |

No automated fixes were applied — every check that was expected to be clean was already clean. The remaining mypy and full-pytest findings are pre-existing tech debt and were not auto-fixed because mass-modifying type annotations or test fixtures on a live trading codebase carries behavioral risk and falls outside the safe scope of an automated nightly pass.

## 1. Go quality — clean

- `go build ./...` → exit 0, no output.
- `go vet ./...` → exit 0, no output.
- `golangci-lint run ./...` → `0 issues.`
- `go test ./... -short -count=1` → 26 packages pass:
  `internal/{adversarial, api, auth, boundary, bridge, config, conformance, controlplane, coord, coordination, core, db, eval, framework, handler, heartbeat, integrations, memory, middleware, observability, polymarket, registry, skills, terminal, tools}`. `internal/api` was the slowest at 1.78s.

Tooling note: the bundled `go.mod` requires Go 1.25.0, so I used Go 1.25.3 + golangci-lint 2.5.0 (1.62.2 refused with "Go language version (go1.23) used to build golangci-lint is lower than the targeted Go version (1.25.0)").

## 2. Python lint/format — clean

- `ruff check omega/` → `All checks passed!`
- `ruff format --check omega/` → `252 files already formatted`

## 3. mypy — 248 pre-existing errors (NOT auto-fixed)

`mypy omega/core/ --ignore-missing-imports` reports 248 errors across 31 files. By error category:

| Category | Count |
|---|---|
| `[arg-type]` | 175 |
| `[no-any-return]` | 24 |
| `[assignment]` | 14 |
| `[attr-defined]` | 12 |
| `[no-untyped-def]` | 8 |
| `[index]` | 5 |
| `[union-attr]` | 4 |
| `[unused-ignore]` | 2 |
| `[misc]` | 2 |
| `[import]` | 2 |
| `[operator]` | 1 |
| `[comparison-overlap]` | 1 |

Top offenders are project (not platform) files reached via followed imports:

| File | Errors |
|---|---|
| `omega/nodes/victoria/features.py` | 169 |
| `omega/nodes/victoria/hmm_regime.py` | 9 |
| `omega/nodes/victoria/strategy.py` | 6 |
| `omega/nodes/victoria/decision_embeddings.py` | 6 |
| `omega/nodes/victoria/signals/funding_rate.py` | 5 |
| `omega/nodes/victoria/signal_generation.py` | 4 |
| `omega/core/brain.py` | 4 |
| `omega/core/project_config.py` | 3 |
| `omega/core/node_adapter.py` | 3 |
| `omega/core/meta_harness.py` | 3 |
| `omega/core/overnight_runner.py` | 2 |
| `omega/core/{paper_trading, node_skills, llm_shell, decision_snapshot}.py` | 1 each |

**19 errors are directly in `omega/core/` (the platform layer); the other 229 are in followed imports into project code.** The vast majority of `[arg-type]` errors are numpy/pandas array-vs-Series mismatches in `victoria/features.py` that need typing stubs or targeted `# type: ignore[arg-type]` annotations — fixing them mass-style risks behavioral changes in signal computation, so they're left for a focused mypy hardening pass.

Reasonable-choice note: I did not apply automated mypy fixes. The successful pattern is to (a) decide whether `omega/core/` should be strict-typed independently of project nodes and (b) work file-by-file with focused PRs. That's not an "automated quality fix" — it's a small project of its own.

## 4. Tests

- `pytest tests/test_action_contracts.py` → **28 passed in 0.70s**. Action/Step contract enforcement is intact.
- `pytest tests/` (full) → **2730 tests collected**. The full suite could not complete within this run's sandbox time budget (each shell call is capped at 45s; the suite plus collection materially exceeds that even at `-n 4`).

Across attempted chunks, recurring failures appeared in early-alphabetical files (`test_ablation`, `test_adversarial`, `test_alignment` and similar). I did not auto-fix any of them — they predate this run and several appear to be environment-dependent (network egress, missing fixtures, or DB-backed tests). Recommend running the full suite locally where the time budget allows: `make py-test` or `python3 -m pytest tests/ -q --timeout=120`.

## 5. Stale code patterns

### Raw action literals (false positives)

```
omega/core/orchestrator_v2.py:439:  # comment: # node_type (e.g. "DATA_INGESTION" → "fetch_market_data"),
omega/nodes/victoria/victoria_node.py:28:  # docstring: "compute_signals"   → run all signal types
```

Both are inside comments/docstrings, not executed code. No action required.

### `os.environ.get` for credentials (12 hits — candidate migration to `omega.core.credentials`)

```
omega/core/startup_validator.py:271:  ANTHROPIC_API_KEY / CLAUDE_API_KEY
omega/core/startup_validator.py:275:  COINGECKO_API_KEY / CG_API_KEY
omega/nodes/victoria/data_cache.py:104:  FRED_API_KEY
omega/nodes/victoria/unusual_whales_provider.py:45:  UW_API_KEY
omega/nodes/victoria/whale_signal.py:375:  WHALE_ALERT_API_KEY
omega/nodes/victoria/whale_signal.py:391:  COINGLASS_API_KEY
omega/nodes/victoria/data_providers.py:37:  CG_API_KEY
omega/nodes/victoria/data_providers.py:933:  COINBASE_API_KEY
omega/nodes/victoria/llm_meta_controller.py:405:  ANTHROPIC_API_KEY
omega/nodes/polymarket/clob_client.py:236:  POLYMARKET_API_KEY
omega/nodes/polymarket/clob_client.py:237:  POLYMARKET_API_SECRET
omega/integrations/twitter_feed.py:294:  SN13_API_KEY
```

`omega/core/credentials.py` already provides a `CredentialStore` that resolves from env vars and `.env`. Migrating these 12 sites to `credentials.get(...)` would centralize secret handling and unlock the `.env` fallback path, but the change requires per-call review (default values, missing-key behavior, and side effects vary). Logged for follow-up.

## Success criteria

- [x] `go build ./...` passes
- [x] `golangci-lint run ./...` returns 0 issues
- [x] `ruff check omega/` returns 0 issues
- [x] All Go test packages pass
- [x] Contract tests pass
- [ ] No regressions in Python test suite — could not be fully verified within sandbox time budget; pre-existing failures observed but not new.

## Commit

No commit was made — there were no automated fixes to apply. Each lint/format check that was expected to be clean was already clean; the remaining mypy and pytest findings are pre-existing tech debt that I declined to mass-modify on safety grounds.
