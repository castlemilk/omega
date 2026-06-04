# Omega — Automated Code Quality Review

**Run date:** 2026-05-27
**Branch:** main
**Mode:** Scheduled, autonomous (no user present)

## Summary

| Check                          | Result        | Notes                                            |
|--------------------------------|---------------|--------------------------------------------------|
| `go build ./...`               | PASS (exit 0) | No errors.                                       |
| `golangci-lint run ./...`      | PASS (exit 0) | **0 issues** (v2.5.0, matches Go 1.25 toolchain).|
| `go test ./... -short -count=1`| PASS (exit 0) | All 26 Go packages with tests pass.              |
| `ruff check omega/`            | PASS (exit 0) | All checks passed.                               |
| `ruff format --check omega/`   | PASS (exit 0) | 252 files already formatted.                     |
| `mypy omega/core/`             | 231 errors    | Pre-existing baseline (see Mypy section).        |
| Contract tests                 | PASS          | 28 passed (`tests/test_action_contracts.py`).    |
| Full pytest suite              | Partial       | Sandbox lacks live Go API / Postgres; details below. |

**Lint issues found and fixed:** 0 (Go) + 0 (Python). The codebase is clean for `ruff` and `golangci-lint` — no edits were applied, so no `chore: automated code quality fixes` commit was needed.

## Environment notes

The scheduled-task sandbox is an isolated ARM64 Ubuntu 22.04 container. It does not have the project's full runtime stack:

- **Go 1.25.0** was sourced from the project's vendored `.gomod/golang.org/toolchain@v0.0.1-go1.25.0.linux-arm64/`.
- **`golangci-lint` v2.5.0** was downloaded (the older `v1.62.x`/`v1.64.x` releases reject `go 1.25` config files with "Go language version used to build golangci-lint is lower than the targeted Go version").
- **Python 3.11.15** was installed via `uv python install 3.11`; the system default `python3` is 3.10, which fails on `from datetime import UTC` (added in 3.11).
- **No Postgres, no Go API on :8080, no Python bridge on :9090.** Any test that exercises the heartbeat client, orchestrator loop, or DB fails with `Connection refused` and is then reaped by `pytest-timeout`.

## Go

```
go build ./...                         → exit 0 (clean)
golangci-lint run ./...                → 0 issues
go test ./... -short -count=1          → all 26 test packages PASS
```

No Go issues found, no edits required.

## Python

### Lint / format

```
ruff check omega/                      → All checks passed
ruff format --check omega/             → 252 files already formatted
```

### Mypy (`omega/core/` with `--ignore-missing-imports`)

Mypy followed imports out of `omega/core/` and reported **231 errors across 25 files**. The vast majority are pre-existing in `omega/nodes/victoria/` (project code, not platform):

| File                                          | Errors |
|-----------------------------------------------|-------:|
| `omega/nodes/victoria/features.py`            |    169 |
| `omega/nodes/victoria/strategy.py`            |      6 |
| `omega/nodes/victoria/decision_embeddings.py` |      6 |
| `omega/nodes/victoria/signals/funding_rate.py`|      5 |
| `omega/nodes/victoria/hmm_regime.py`          |      5 |
| `omega/nodes/victoria/signal_generation.py`   |      4 |
| (16 other files)                              |     29 |
| **`omega/core/` itself**                      |    **7** |
| **Total**                                     |  **231** |

Error categories (top): `[arg-type]` 173, `[no-any-return]` 19, `[attr-defined]` 12, `[assignment]` 11, `[no-untyped-def]` 7, `[union-attr]` 3.

The 7 errors actually in `omega/core/` are dynamic-attribute / optional-attr patterns:

- `omega/core/node_skills.py:360` — non-overlapping equality check
- `omega/core/alerting.py:251` — `float()` arg may be `None`
- `omega/core/node_adapter.py:391,393` — calls on `Optional` attr
- `omega/core/project_config.py:265,341,348` — pokes private attrs (`_tickers`, `_min_conviction`) and an attribute (`PaperTradingExecutorNode`) that is no longer exported from `omega.core.paper_trading`
- `omega/core/meta_harness.py:703` — calls `consult` on `Optional[Brain]`

**No fixes applied.** These are long-standing patterns. Auto-rewriting 25 files (especially `victoria/features.py`'s 169 numpy/pandas type sites) carries real risk of changing runtime semantics in a trading system; this is not appropriate for an unattended scheduled run. The `project_config.py:348` reference to `PaperTradingExecutorNode` looks like a genuine stale import worth a human follow-up.

### Contract tests

```
PYTHONPATH=gen/python:. python3.11 -m pytest tests/test_action_contracts.py -q
→ 28 passed in 0.59s
```

All action-contract tests pass under Python 3.11.

### Full pytest suite

`pytest --co` reports **2,730 tests collected.** The full suite cannot run cleanly in the sandbox: any test that boots `omega.core.orchestrator_v2.run(...)` blocks in `time.sleep(wait)` while the heartbeat client retries an unreachable `http://localhost:8080/api/v1/diagnostics` (the Go API is not running here), then trips `pytest-timeout`.

Sampled pure-unit batches that don't need infra:

| Batch                                                                                    | Result                              |
|------------------------------------------------------------------------------------------|-------------------------------------|
| action_contracts + alignment + baselines + bayesian + bayesian_optimizer + brier + challenge_registry + attention_router | **210 passed, 19 skipped**          |
| brain_tiers                                                                              | 4 failed (network — need Anthropic API)    |
| ablation / accuracy_fixes / adversarial / adversarial_v2                                 | failing — orchestrator needs Go API |
| integration/ + bridge/                                                                   | failing — need DB + Go API + bridge |
| circuit_breaker + config + convergence + conviction + credentials + data_splitter + debate_gate + degradation + deterministic_compiler + devils_advocate + dynamic_weights + ensemble_voter + errors + eval_metrics + evaluator + exit_controller + forensics_* + kelly + logging | **400 passed, 43 skipped, 5 failed** |

#### Real (non-environmental) regressions found

`tests/test_conviction.py` — **5 genuine assertion failures**, not timeouts:

- `test_rank_signals_includes_conviction` — expects composite=0.8 → `STRONG_BUY`; gets `BUY`.
- `test_portfolio_conviction_distribution_present` — expects 1× STRONG_BUY/BUY/HOLD; only `BUY` appears.
- `test_portfolio_strong_buy_gets_higher_weight_than_buy` — both tickers receive weight 0 / 0.3 instead of distinct STRONG_BUY > BUY weights.
- `test_portfolio_weights_sum_to_one` — weights sum to 0.3, not 1.0.
- `test_execute_rank_signals_includes_conviction` — composite=0.9 → `BUY` instead of `STRONG_BUY`.

**Root cause (likely).** `StrategyNode._rank_signals` (`omega/nodes/victoria/strategy.py:3190`) applies a cross-sectional normalisation factor `_rank_cs_norm = 0.4 / max(basket_std, 0.005)` to the composite before calling `score_to_conviction`. For the test input `{0.8, 0.3, 0.0, -0.5, -0.9}` (basket std ≈ 0.595) the scaled value of 0.8 is ≈ 0.54, below the STRONG_BUY threshold of 0.6. The cross-sectional demeaning was added with the V49+ signal-generation work (cf. comment block at lines 314-326); the conviction tests appear to predate it. This is a **test/implementation drift**, not a runtime bug — either the tests need to be updated to feed already-normalised composites, or `_rank_signals` should expose a "no normalisation" mode for the test contract. **Not auto-fixed** — picking which side is canonical changes downstream sizing behaviour and is a human call.

### Stale-pattern checks

```
grep -rn '"fetch_market_data"\|"compute_signals"' omega/ --include="*.py" | grep -v actions.py | grep -v NodeAction
```

Two matches, both **non-issues** (they are explanatory comments, not action-name string literals):

- `omega/core/orchestrator_v2.py:439` — comment `# node_type (e.g. "DATA_INGESTION" → "fetch_market_data"),`
- `omega/nodes/victoria/victoria_node.py:28` — module docstring `"compute_signals"   → run all signal types`

```
grep -rn 'os.environ.get.*API_KEY\|os.environ.get.*SECRET' omega/ --include="*.py" | grep -v credentials.py
```

**12 matches** of direct env-var reads that bypass `omega.core.credentials.credentials.get(...)`:

| File | Line | Key |
|------|-----:|-----|
| `omega/core/startup_validator.py` | 271 | `ANTHROPIC_API_KEY` / `CLAUDE_API_KEY` |
| `omega/core/startup_validator.py` | 275 | `COINGECKO_API_KEY` / `CG_API_KEY` |
| `omega/nodes/victoria/data_cache.py` | 104 | `FRED_API_KEY` |
| `omega/nodes/victoria/unusual_whales_provider.py` | 45 | `UW_API_KEY` (module-load) |
| `omega/nodes/victoria/whale_signal.py` | 375 | `WHALE_ALERT_API_KEY` |
| `omega/nodes/victoria/whale_signal.py` | 391 | `COINGLASS_API_KEY` |
| `omega/nodes/victoria/data_providers.py` | 37 | `CG_API_KEY` (module-load) |
| `omega/nodes/victoria/data_providers.py` | 933 | `COINBASE_API_KEY` (module-load) |
| `omega/nodes/victoria/llm_meta_controller.py` | 405 | `ANTHROPIC_API_KEY` |
| `omega/nodes/polymarket/clob_client.py` | 236 | `POLYMARKET_API_KEY` |
| `omega/nodes/polymarket/clob_client.py` | 237 | `POLYMARKET_API_SECRET` |
| `omega/integrations/twitter_feed.py` | 294 | `SN13_API_KEY` |

**Not auto-fixed.** Migrating these to `credentials.get(...)` is safe in spirit, but three of them (`unusual_whales_provider.py:45`, `data_providers.py:37,933`) run at module-import time, so changing them shifts when credential resolution happens and can affect import ordering / `.env` loading. The `startup_validator.py` calls are arguably fine since that file's job is to validate raw env presence. Recommend a follow-up PR that migrates these one by one with per-file review.

## Success-criteria scorecard

| Criterion                                                       | Status |
|-----------------------------------------------------------------|--------|
| `go build ./...` passes                                         | ✅     |
| `golangci-lint run ./...` returns 0 issues                       | ✅     |
| `ruff check omega/` returns 0 issues                             | ✅     |
| All Go test packages pass                                        | ✅     |
| Contract tests pass                                              | ✅     |
| No regressions in Python test suite                              | ⚠️ See "real regressions" — `test_conviction.py` × 5; pre-existing drift, not new today. Cannot fully verify because the sandbox cannot host the Go API + Postgres the integration tests need. |

## Recommendations (for a human follow-up)

1. **Resolve `test_conviction.py` drift** — decide whether `_rank_signals` should normalise before converting to conviction; update the tests or the rank path accordingly.
2. **`omega/core/project_config.py:348`** — `PaperTradingExecutorNode` is no longer exported from `omega.core.paper_trading`; this is a likely real bug, not a typing nit.
3. **Credentials migration** — open a focused PR moving the 12 direct env reads to `credentials.get(...)`, paying attention to module-load timing in `data_providers.py` / `unusual_whales_provider.py`.
4. **Mypy baseline** — consider committing a `# type: ignore[arg-type]` cleanup pass for `omega/nodes/victoria/features.py` (169 errors, almost all numpy/pandas dtype mismatches) so the noise stops drowning the real `omega/core/` findings.

## Files written

- `data/code_quality_report_2026-05-27.md` (this report)

No source files were modified. No commit was created.
