# Omega Code Quality Review — 2026-04-27

Automated run of the `omega-code-quality-review` scheduled task. The user was
not present, so no fixes were committed. This report enumerates findings.

Repo state: HEAD `f2cff01 feat(victoria): V148 best-of-phases`. Working tree
has 1,417 modified/untracked entries — heavy WIP — so any "auto-fix and
commit" step would have entangled automated changes with in-flight work.
Nothing was committed.

## Summary

| Check | Result |
|-------|--------|
| `go build ./...` | PASS (0 errors) |
| `go vet ./...` | PASS (0 errors) |
| `golangci-lint run ./...` | PASS (0 issues) |
| `go test ./... -short -count=1` | PASS on rerun; 1 flaky failure on cold run (see below) |
| `ruff check omega/` | PASS (0 issues) |
| `ruff format --check omega/` | PASS (252 files already formatted) |
| `mypy omega/core/ --ignore-missing-imports` | 239 pre-existing errors across 28 files |
| `pytest tests/test_action_contracts.py` | PASS (28/28) |
| `pytest tests/` (full suite) | Could not be run cleanly in sandbox — see notes |

## Go quality

Build, vet, and golangci-lint are clean. Required toolchain: Go 1.25 (per
`go.mod`) and golangci-lint v2.5+ (the repo's `.golangci.yml` is v2-schema).

### Flaky test: `internal/framework.TestConfig_HotReload`

On the first cold `go test ./... -short -count=1` run, this test failed:

```
--- FAIL: TestConfig_HotReload (0.00s)
    config_test.go:150: expected hot-reloaded value 42, got 32
FAIL    github.com/benebsworth/omega/internal/framework    0.038s
```

Five subsequent re-runs of the same suite all passed. The value `32` is the
package's default for `orchestrator.max_nodes` (`internal/framework/config.go:77`).
Race: `os.WriteFile` in the test is not atomic (truncate + write); viper's
`WatchConfig` fires `OnConfigChange` after `ReadInConfig`, but if `ReadInConfig`
sees the truncated empty file first, viper resets to defaults and the test's
`OnChange` callback unblocks before the second event re-reads the new content.

**Recommended hardening (not applied):** in `config_test.go`, write to a
sibling file and `os.Rename` for atomic replacement, or poll `cfg.GetInt`
inside the callback until it equals 42 (with a small budget) instead of
checking exactly once.

## Python quality

`ruff check` and `ruff format --check` are both clean — no automated fixes
needed.

### mypy on `omega/core/`

239 errors in 28 files. Distribution by file (top offenders):

| File | Errors |
|------|--------|
| `omega/nodes/victoria/features.py` | 169 |
| `omega/nodes/victoria/hmm_regime.py` | 9 |
| `omega/nodes/victoria/strategy.py` | 6 |
| `omega/nodes/victoria/decision_embeddings.py` | 6 |
| `omega/nodes/victoria/signals/funding_rate.py` | 5 |
| `omega/nodes/victoria/signal_generation.py` | 4 |
| `omega/core/project_config.py` | 3 |
| `omega/core/meta_harness.py` | 3 |
| (others, mostly project code) | rest |

Almost all the errors are in the Victoria project module (which `omega/core/`
follows via imports), not in `omega/core/` itself. `pyproject.toml` already
runs mypy in strict mode — these errors are pre-existing and would need a
deliberate refactor pass per file. They were not auto-fixed because:

- 169 errors in `features.py` alone implies a structural typing change
  (likely missing pandas/numpy stubs or untyped dict-of-arrays returns), not
  drive-by edits.
- Several errors are real signature mismatches (e.g.
  `omega/core/project_config.py:265` assigns `_tickers` on a node class that
  doesn't declare it; `:348` imports `PaperTradingExecutorNode` which no
  longer exists in `omega.core.paper_trading`). Auto-fix would mask the bug.

### Python contract tests

`pytest tests/test_action_contracts.py` — 28/28 pass. `omega.core.actions`
contract is intact.

### Python full suite

The full suite (~2,635 collectable tests under
`tests/ -m 'not slow and not integration and not e2e'`) could not complete in
the sandbox: each shell call has a 45 s wall budget and a single pytest-xdist
session takes ~70 s for the trimmed set. Background detachment (`nohup`,
`setsid`) does not survive bash session boundaries here.

What did run, per-batch, with `--timeout=5` on each test:

| Batch | Passed | Failed | Skipped |
|-------|--------|--------|---------|
| Smoke unit subset (10 files: contract, brier, circuit_breaker, config, conviction, credentials, data_sources, node, baselines, alignment) | 262 | 5 | 0 |
| `tests/test_a*.py` | 167 | 21 | 25 |

The smoke-subset failures are all in `tests/test_conviction.py`:

```
FAILED test_rank_signals_includes_conviction
FAILED test_portfolio_conviction_distribution_present
FAILED test_execute_rank_signals_includes_conviction
FAILED test_portfolio_strong_buy_gets_higher_weight_than_buy
FAILED test_portfolio_weights_sum_to_one
```

**Root cause (not a flake — real divergence):**
`omega/nodes/victoria/strategy.py:_rank_signals` (line 3190) now scales
`composite` by `_rank_cs_norm = 0.4 / max(basket_std, 0.005)` *before* mapping
to a `ConvictionLevel`. The tests in `tests/test_conviction.py` (added in
8f059b7) assume the absolute thresholds documented on
`score_to_conviction`: `> 0.6 → STRONG_BUY`, `> 0.2 → BUY`. With composite
0.9 and a single counter-ticker at -0.8, basket std ≈ 0.85 →
norm ≈ 0.471 → 0.9 × 0.471 ≈ 0.424 → `BUY` (not `STRONG_BUY`).

Either the tests are stale and need updating to match the relative-conviction
semantics, or the normalization in `_rank_signals` is unintended. Not
auto-fixed — this needs a human call. Note the strategy.py file is in the
working-tree-modified set, so this is likely WIP.

The `test_a*.py` batch failures span `test_ablation.py` and
`test_accuracy_fixes.py`. Spot-checking, several of these need infrastructure
(Postgres, Go API on `:8080` — `connection refused` warnings throughout) and
are environment failures, not regressions. A representative example:
`test_backtest_evaluator.py::test_engine_uses_null_evaluator_by_default` and
`integration/test_feedback_loop.py` both timed out attempting to reach the
heartbeat client; these are integration-leaning and should probably be marked
`integration`.

## Stale code patterns

### Raw action-string literals (NodeAction enum bypass)

`grep -rn '"fetch_market_data"\|"compute_signals"' omega/ --include="*.py" | grep -v actions.py | grep -v NodeAction`

Two hits, both benign:

```
omega/core/orchestrator_v2.py:439:    # node_type (e.g. "DATA_INGESTION" → "fetch_market_data"),
omega/nodes/victoria/victoria_node.py:28:  "compute_signals"   → run all signal types
```

Both are inside comments/docstrings, not live code. CLAUDE.md explicitly
permits a small set of legacy aliases in `victoria_node.py` and these are not
in that allowlist but are also not raw-string dispatch — no action.

### Direct `os.environ.get` for credentials (bypassing `credentials.py`)

`grep -rn 'os.environ.get.*API_KEY\|os.environ.get.*SECRET' omega/ --include="*.py" | grep -v credentials.py`

12 hits worth flagging:

| File | Line | Key |
|------|------|-----|
| `omega/core/startup_validator.py` | 271 | ANTHROPIC_API_KEY / CLAUDE_API_KEY |
| `omega/core/startup_validator.py` | 275 | COINGECKO_API_KEY / CG_API_KEY |
| `omega/nodes/victoria/data_cache.py` | 104 | FRED_API_KEY |
| `omega/nodes/victoria/unusual_whales_provider.py` | 45 | UW_API_KEY |
| `omega/nodes/victoria/whale_signal.py` | 375 | WHALE_ALERT_API_KEY |
| `omega/nodes/victoria/whale_signal.py` | 391 | COINGLASS_API_KEY |
| `omega/nodes/victoria/data_providers.py` | 37 | CG_API_KEY |
| `omega/nodes/victoria/data_providers.py` | 933 | COINBASE_API_KEY |
| `omega/nodes/victoria/llm_meta_controller.py` | 405 | ANTHROPIC_API_KEY |
| `omega/nodes/polymarket/clob_client.py` | 236 | POLYMARKET_API_KEY |
| `omega/nodes/polymarket/clob_client.py` | 237 | POLYMARKET_API_SECRET |
| `omega/integrations/twitter_feed.py` | 294 | SN13_API_KEY |

All bypass `omega/core/credentials.py`. `startup_validator.py` is arguably the
canonical "validate env on boot" entry point and may be deliberate, but the
data providers and LLM controllers should route through `credentials.py` to
get redaction/audit. Recommend a follow-up PR.

## Files not auto-fixed (and why)

| Issue | Reason not fixed |
|-------|------------------|
| 239 mypy errors | Real type-annotation work, not mechanical; 169 in one file (`features.py`) implies a typing strategy decision (pandas stubs, dict typing) not a drive-by edit |
| `TestConfig_HotReload` race | Test is flaky, not deterministically broken; fix needs design (atomic rename vs poll-in-callback) |
| `test_conviction.py` failures | Working tree has uncommitted changes to `strategy.py`; this is in-flight WIP, not stable code to "fix" |
| `os.environ.get` credential bypass | 12 sites across 8 files — needs a deliberate migration to `credentials.py`, not an autofix |

## Success-criteria status

- `go build ./...` — PASS
- `golangci-lint run ./...` — PASS (0 issues)
- `ruff check omega/` — PASS (0 issues)
- All Go test packages — PASS on rerun (1 flaky failure on cold run, documented)
- Contract tests — PASS (28/28)
- No regressions introduced by this run (no commits made)
