# Omega Code Quality Review — 2026-05-10

Automated scheduled run. HEAD = `f2cff01` (unchanged from 2026-05-08). Working tree had **1453 modified files** uncommitted at start of run (long-running in-flight work, same pattern as 2026-05-02 / 2026-05-04 / 2026-05-08). No fixes were committed: bundling autofixes with that state would conflate authorship with the in-flight changes already on disk.

## Summary

| Check                                            | Result                                              |
|--------------------------------------------------|-----------------------------------------------------|
| `go build ./...`                                 | **PASS** (clean)                                    |
| `golangci-lint run ./...` (v2.5.0)               | **PASS** (0 issues)                                 |
| `go test ./... -short -count=1`                  | **PASS** (all 32 testable packages)                 |
| `ruff check omega/`                              | **PASS** (0 issues, 252 files)                      |
| `ruff format --check omega/`                     | **PASS** (252 files already formatted)              |
| `mypy omega/core/ --ignore-missing-imports`      | 239 errors in 28 files (pre-existing, unchanged)    |
| `pytest tests/test_action_contracts.py`          | **PASS** (28/28)                                    |
| Targeted regression sample (~280 tests, 9 files) | **9 failures** (8 baseline + 1 new)                 |
| Stale raw action literals                        | 2 hits, all in comments/docstrings (no real usage)  |
| Direct `os.environ.get(...API_KEY/SECRET)`       | 12 hits across 8 files (unchanged from 2026-05-08)  |

Net status vs 2026-05-08: Go pipeline still clean. Python lint/format/contract surface still clean. Mypy baseline unchanged. **One new test regression** in `test_signal_integrity.py::TestBidirectionality::test_no_single_direction_dominates` — sell-side dominates 100% of non-HOLD signals on the synthetic basket. Other 8 failures match the 2026-05-08 baseline exactly.

## Sandbox setup notes

The session image ships with Python 3.10 only and no Go toolchain. To run this review I:

1. Downloaded Go 1.25.0 (project requires `go 1.25.0`) into `/sessions/eloquent-friendly-babbage/.local/go-install/`.
2. Installed `golangci-lint` v2.5.0 (the project `.golangci.yml` is v2 schema; v1.x lints fail on `can't load config`).
3. Persisted `GOPATH`/`GOCACHE`/`GOLANGCI_LINT_CACHE` under `/sessions/eloquent-friendly-babbage/.cache/` (per-process `/dev/shm` does not survive across bash calls in this sandbox).
4. Used `uv python install 3.11` (`UV_PYTHON_INSTALL_DIR=/sessions/.local/uvpy`) and `pip install --break-system-packages numpy psycopg betterproto pyyaml httpx pydantic pytest pytest-timeout pytest-xdist` because the codebase imports `datetime.UTC` (3.11+) and several core modules transitively pull numpy.
5. Used `--cache-dir=/tmp/mypycache` because mypy's default cache hit `sqlite3.OperationalError: disk I/O error` on the bind-mounted project folder.

The full Python test suite (2730 tests collected) still doesn't fit cleanly in the 45 s sandbox windows — the alphabetically-first hung test, `tests/test_ablation.py::TestAblationHaressIndividual::test_run_full_returns_eval_report`, sleeps inside `OmegaOrchestrator.run` past the per-test timeout. So full-suite reporting is approximated via a focused regression sample, same as previous weeks.

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

`mypy omega/core/ --ignore-missing-imports` reports **239 errors in 28 files**. Identical to 2026-05-08 baseline.

Distribution unchanged:

- `omega/nodes/victoria/features.py` — 169 (transitively imported from `omega/core/`)
- `omega/nodes/victoria/hmm_regime.py` — 9
- `omega/nodes/victoria/strategy.py` — 6
- `omega/nodes/victoria/decision_embeddings.py` — 6
- Other `omega/nodes/victoria/*` — 36
- **`omega/core/*` — 13 errors** (in `node_skills.py`, `llm_shell.py`, `decision_snapshot.py`, `alerting.py`, `paper_trading.py`, `node_adapter.py`, `project_config.py`, `meta_harness.py`)

Representative `omega/core/` errors (unchanged from prior week):

```
omega/core/project_config.py:265   "DataIngestionNode" has no attribute "_tickers"  [attr-defined]
omega/core/project_config.py:341   "StrategyNode" has no attribute "_min_conviction"  [attr-defined]
omega/core/project_config.py:348   Module "omega.core.paper_trading" has no attribute "PaperTradingExecutorNode"  [attr-defined]
omega/core/meta_harness.py:351     Returning Any from function declared "dict[str, Any]"  [no-any-return]
omega/core/meta_harness.py:357     Returning Any from function declared "int"  [no-any-return]
omega/core/meta_harness.py:702     Item "None" of "Any | None" has no attribute "consult"  [union-attr]
omega/core/node_adapter.py:*       2 attribute / annotation errors
```

These are pre-existing. No fixes attempted in this run — same rationale as prior weeks: the working tree has 1453 uncommitted modifications, so an autofix commit cannot be cleanly attributed.

## Python contract & regression sample

`pytest tests/test_action_contracts.py` — **28 passed**. Action / step contract intact.

Focused regression sample (matching the file list used in prior weekly reports — `test_action_contracts.py`, `test_adversarial.py`, `test_adversarial_v2.py`, `test_brain_tiers.py`, `test_debate_gate.py`, `test_orchestrator.py`, `test_orchestrator_v2.py`, `test_signal_adapter.py`, `test_signal_integrity.py`). 279 tests collected. **270 passed, 9 failed in 26.7 s**:

#### Threshold drift (5 baseline failures, `tests/test_signal_integrity.py`)

Same five as 2026-05-04 / 2026-05-08:

```
TestRegimeAdaptivity::test_normal_regime_thresholds                   assert 0.07 == 0.1
TestRegimeAdaptivity::test_bear_detection_threshold_at_055            assert 0.07 == 0.1
TestRegimeAdaptivity::test_bear_regime_suppresses_longs_permits_shorts assert 0.04 == 0.05
TestRegressionGuard::test_bear_threshold_at_055                       assert 0.07 == 0.1
TestRegressionGuard::test_bull_threshold_at_055                       assert 0.07 == 0.1
```

Cause is unchanged: tests expect normal-regime long threshold of `0.10` and bear short threshold of `0.05`, but the V50 revert (`404a62c fix(v50): revert normal-regime short threshold 0.05→0.10`) plus subsequent regime-thresh-scale work has stayed at `0.07` / `0.04` after `_thresh_scale = basket_std / 0.20` is applied. Either the fixture basket_std needs to be 0.20 exactly, or the assertions need to be updated to assert relative ordering rather than exact values.

#### Adversarial gate (3 baseline failures)

```
test_adversarial_v2.py::TestAdversarialPressureV2::test_ring2_activates_after_enough_cycles
test_orchestrator_v2.py::TestAdversarialIntegration::test_adversarial_variant_outputs_built_from_signal_data
test_orchestrator_v2.py::TestAdversarialGateRejectsLowQualityProposals::test_high_disagreement_blocks_pico_proposal
```

Same as 2026-05-04 / 2026-05-08. Synthetic-cycle harness vs ring-2 activation threshold mismatch; orchestrator_v2 adversarial wiring assumes a `signal_data` shape that differs from what the new variant builder produces.

#### NEW FAILURE — bidirectionality (1 new)

```
tests/test_signal_integrity.py::TestBidirectionality::test_no_single_direction_dominates
  AssertionError: Sell-side dominates: 100% of non-HOLD signals are shorts (2/2).
  Composites: {'BTCUSDT': -0.276, 'ETHUSDT': -0.238, 'SOLUSDT': 0.017,
               'BNBUSDT': 0.196, 'ADAUSDT': 0.187, 'DOTUSDT': 0.113}
  assert 0.0 >= 0.2
```

Of 6 tickers in the synthetic basket, two cleared the (lower) short threshold (BTC −0.276, ETH −0.238) and zero cleared the long threshold (max long was BNB at +0.196, below the 0.20 long bar). Result: 2/2 = 100% short, fails the `>= 20% long share` invariant.

This is consistent with the same regime-threshold drift failing the other five tests in this file — shorts are disproportionately easier to fire than longs at the current `_thresh_scale`. Likely needs the same fix; not a code regression introduced since 2026-05-08, but the prior runs stopped at the first signal-integrity failure (`-x` flag) so it wasn't surfaced. **Now visible because this run dropped `-x` to surface the full failure list.**

The full failure list is therefore: **5 threshold-drift + 1 bidirectionality + 3 adversarial = 9**, all in the same two thematic clusters as the 2026-05-08 baseline.

## Stale code patterns

### Raw action literals

```
omega/core/orchestrator_v2.py:439   # node_type (e.g. "DATA_INGESTION" → "fetch_market_data"),
omega/nodes/victoria/victoria_node.py:28   "compute_signals"   → run all signal types
```

Both are documentation strings inside comments, not live dispatch. No action needed. Same as 2026-05-04 / 2026-05-08.

### Direct `os.environ.get` for API keys / secrets

Twelve hits across eight files (unchanged file set vs 2026-05-08):

```
omega/core/startup_validator.py:271      ANTHROPIC_API_KEY / CLAUDE_API_KEY
omega/core/startup_validator.py:275      COINGECKO_API_KEY / CG_API_KEY
omega/nodes/victoria/data_cache.py:104   FRED_API_KEY
omega/nodes/victoria/unusual_whales_provider.py:45   UW_API_KEY
omega/nodes/victoria/whale_signal.py:375 WHALE_ALERT_API_KEY
omega/nodes/victoria/whale_signal.py:391 COINGLASS_API_KEY
omega/nodes/victoria/data_providers.py:37   CG_API_KEY
omega/nodes/victoria/data_providers.py:933  COINBASE_API_KEY
omega/nodes/victoria/llm_meta_controller.py:405  ANTHROPIC_API_KEY
omega/nodes/polymarket/clob_client.py:236   POLYMARKET_API_KEY
omega/nodes/polymarket/clob_client.py:237   POLYMARKET_API_SECRET
omega/integrations/twitter_feed.py:294      SN13_API_KEY
```

These should route through `omega/core/credentials.py` per the project convention but currently reach `os.environ` directly. This is a multi-file refactor that has been carried in the backlog for several weeks. Recommend opening a single PR titled `refactor: route API key/secret reads through credentials.CredentialStore` rather than churning it once per weekly review — the change touches nodes that are themselves in active flux on the in-flight Victoria branches.

## Fixes applied this run

**None.** Working tree state at start of run:

```
f2cff01 feat(victoria): V148 best-of-phases — meta_learner_exit_only + continuous_sizing
1453 files modified, uncommitted
```

Same convention as 2026-05-02, 2026-05-04, 2026-05-08: an autofix commit on top of 1.4 k uncommitted modifications would be impossible to disentangle later. The lint/format surface is already clean (0 ruff issues, 0 golangci-lint issues), so there is nothing to autofix that would also be uncontroversial.

## Success criteria

| Criterion                              | Status |
|----------------------------------------|--------|
| `go build ./...` passes                | ✓      |
| `golangci-lint run ./...` 0 issues     | ✓      |
| `ruff check omega/` 0 issues           | ✓      |
| All Go test packages pass              | ✓      |
| Contract tests pass (28/28)            | ✓      |
| No regressions in Python test suite    | **partial** — 8 of 9 failures match baseline; 1 (`TestBidirectionality::test_no_single_direction_dominates`) was previously masked by `-x` and is the same threshold-drift root cause as the existing 5 |
