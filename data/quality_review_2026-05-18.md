# Omega Code Quality Review — 2026-05-18

Automated run of `omega-code-quality-review` scheduled task.
Branch: `main` @ `f2cff01` (feat(victoria): V148 best-of-phases — meta_learner_exit_only + continuous_sizing).

## TL;DR

- **ruff check / ruff format omega/**: clean (0 issues, 252 files already formatted).
- **mypy omega/core/**: 234 errors total, 8 in `omega/core/` proper, 226 in `omega/nodes/victoria/` (169 in `features.py`). All pre-existing — typed as `Any`/numpy-heavy code.
- **Contract tests** (`tests/test_action_contracts.py`): 28/28 pass.
- **Other Python tests**: 446 unit tests exercised in curated batches → 13 real failures (V148 threshold drift in `test_conviction.py` + `test_signal_integrity.py`); 2 environment-only failures.
- **Go build / golangci-lint / go test**: blocked — sandbox does not have enough writable disk + bindfs blocks build-cache ops.
- **No code changes committed.** No fixes were applied automatically; doing so would have either masked real failures or committed unrelated pre-existing dirty state on `main` under a misleading message.

## 1. Environment notes

| Tool | Status | Notes |
|---|---|---|
| Go 1.25.3 / golangci-lint 2.6.0 | available at `/tmp/go/bin` | build fails — see §2 |
| Python 3.11.15 | `/tmp/uvpy/...` | system Python is 3.10 which can't run polymarket code (`from datetime import UTC` is 3.11+) |
| ruff 0.15.13 | installed | |
| mypy 1.20.2 | installed | needed `--cache-dir` outside the bindfs `/tmp` (was returning `OperationalError: unable to open database file`) |
| pytest 9.0.3 + xdist + timeout | installed | bash session has ~40s CPU budget — full 2730-test suite cannot complete in one process |

## 2. Go build / lint / test (BLOCKED)

`go build ./...` fails before completing because:

- `/sessions` (writable) only has ~600 MB free; a fresh Go build cache for this project needs roughly 2 GB.
- Putting `GOCACHE`/`GOMODCACHE` on the omega bindfs mount (which has 34 GB free) doesn't work: bindfs returns `Operation not permitted` on `unlink`/`remove`, which Go needs for `.partial` cleanup, atomic renames, and trim operations.
- An existing `bin/omega` binary dated 2026-03-25 confirms the host machine builds fine; this is purely a sandbox limitation.

**Action**: re-run Go checks on the host or in a less constrained environment. No Go-layer issues identified in this run, but also nothing verified.

## 3. Python lint & format

```
ruff check omega/             ->  All checks passed!  (0 issues)
ruff format --check omega/    ->  252 files already formatted
```

## 4. mypy omega/core/ --ignore-missing-imports

```
Found 234 errors in 25 files (checked 74 source files)
```

Error category breakdown:

```
173 [arg-type]      (mostly numpy float64 vs float in victoria/features.py)
 19 [no-any-return]
 12 [attr-defined]
 11 [assignment]
  7 [no-untyped-def]
  4 [index]
  4 [float]
  3 [union-attr]
  2 [unused-ignore]
  2 [misc]
  2 [import]
  ... (rest scattered)
```

Top offending files:

```
169  omega/nodes/victoria/features.py
  9  omega/nodes/victoria/hmm_regime.py
  6  omega/nodes/victoria/strategy.py
  6  omega/nodes/victoria/decision_embeddings.py
  5  omega/nodes/victoria/signals/funding_rate.py
  ...
  3  omega/core/project_config.py
  1  omega/core/node_skills.py
  1  omega/core/alerting.py
  2  omega/core/node_adapter.py
  1  omega/core/meta_harness.py
```

The 8 errors actually in `omega/core/`:

| file:line | category | summary |
|---|---|---|
| `node_skills.py:360` | comparison-overlap | non-overlapping equality vs `SignalLifecycle.RETIRED` (the literal type excludes the comparison value) |
| `alerting.py:251` | arg-type | `float(sig_val.get("value", sig_val.get("composite", 1.0)))` — `dict.get` return is `Any \| None`, mypy needs an `assert is not None` or `or 0.0` fallback |
| `node_adapter.py:391` & `:393` | union-attr | `self._layer` typed `Any \| None`, `.fetch_with_failover` / `.get_health_status` called without narrowing |
| `project_config.py:265` | attr-defined | dynamic `node._tickers = ...` on `DataIngestionNode` — internal attr, not in class def |
| `project_config.py:341` | attr-defined | same pattern for `StrategyNode._min_conviction` |
| `project_config.py:348` | attr-defined | `from omega.core.paper_trading import PaperTradingExecutorNode` — class may have moved/been renamed |
| `meta_harness.py:703` | union-attr | `self._brain.consult(...)` without `is not None` check |

These are pre-existing typing gaps in `Any`-typed code paths; none are runtime bugs. **Not auto-fixed** — fixing requires either tightening attribute types (potentially behaviour-changing) or scattering `assert is not None` / `cast()` calls, both of which carry regression risk on a self-mutating production system.

The 226 errors under `omega/nodes/victoria/` are project code (per CLAUDE.md: Victoria is a project, not platform), heavily numpy-typed, and are an ongoing typing-debt item rather than a regression.

## 5. Contract tests

```
tests/test_action_contracts.py     28 passed in 0.19s
```

All `NodeAction` / `StepType` / `STEP_TO_ACTION` contracts pass under Python 3.11.

## 6. Full pytest suite

**Sandbox constraint**: each bash invocation has roughly a 40-second CPU budget before the session is killed. The full 2730-test suite cannot complete in one process. Curated batches were run instead.

### Batches actually exercised

| Batch | Pass | Fail | Notes |
|---|---:|---:|---|
| `tests/test_action_contracts.py` | 28 | 0 | |
| `tests/baseline/` (5 files) | 39 | 0 | adversarial / cost / MVA / regime / spread |
| Curated unit batch A (13 files) | 358 | 5 | failures in `test_conviction.py` |
| Curated unit batch B (14 files) | 312 | 8 | 6 in `test_signal_integrity.py`, 1 SSL timeout in `test_sharpe.py`, 1 carries over |
| `tests/test_ablation.py` (partial) | 6 | 1 | `test_run_full_returns_eval_report` needs the Go API on `localhost:8080` |

### Real test failures (13)

#### `tests/test_conviction.py` — 5 failures

All five trace to the same root cause: `StrategyNode._rank_signals` now applies a basket-relative normalization (`_rank_cs_norm = 0.4 / max(_std, 0.005)`) before calling `score_to_conviction`. The tests pass raw composites (0.8, 0.3, 0.0, -0.5, -0.9) and assert that 0.8 -> `STRONG_BUY`, but after the normalization (`0.8 * ~0.67 ~= 0.54`) it falls in the `BUY` band.

- `test_rank_signals_includes_conviction` — `'BUY' != 'STRONG_BUY'`
- `test_portfolio_conviction_distribution_present` — `assert 2 == 1`
- `test_portfolio_strong_buy_gets_higher_weight_than_buy` — weights flipped vs expected
- `test_portfolio_weights_sum_to_one` — only one ticker survives the filter, weights sum to 0.3
- `test_execute_rank_signals_includes_conviction` — same as #1

**Action required (manual)**: either (a) update test fixtures to use composites that survive the rank-normalization (likely the intended fix, since the normalization is a deliberate post-V49 change), or (b) revert the normalization in `_rank_signals` if it was unintended. Touching this from an automated run would risk masking a real regression.

#### `tests/test_signal_integrity.py` — 6 failures

Threshold drift between code and tests:

- `TestRegressionGuard::test_bear_threshold_at_055` — `_long_conviction_threshold` is 0.07; test expects 0.10.
- `TestRegressionGuard::test_bull_threshold_at_055` — same: 0.07 vs 0.10.
- `TestRegimeAdaptivity::test_normal_regime_thresholds` — same band.
- `TestRegimeAdaptivity::test_bear_regime_suppresses_longs_permits_shorts`
- `TestRegimeAdaptivity::test_bear_detection_threshold_at_055`
- `TestPnLDirectionSanity::test_10_cycle_direction_diversity`

CLAUDE.md still documents the V49 thresholds (`long=0.10, short=0.05` in NORMAL); the code has moved to 0.07 somewhere between V49 and V148. Either the docs+tests are stale, or V148 introduced a regression vs the V49 hard gate. The V49 gates docstring in `omega/eval/v49_gates.py` is the source of truth — review there before deciding.

**Action required (manual)**: reconcile `_long_conviction_threshold` value against `omega/eval/v49_gates.py` (PnL floor / regime parity gates), then update either the threshold or the assertions + CLAUDE.md.

#### `tests/test_sharpe.py::TestInformationRatio::test_outperforming_benchmark` — 1 failure

Hits SSL handshake during the test; pytest-timeout fires at 6.0s. The test is reaching out to a live host. **Environment-only failure** in this sandbox; not a code defect.

### Tests not exercised (environmental dependencies)

- `tests/integration/*` — needs `TEST_DATABASE_URL` (per CLAUDE.md `make test-integration`).
- `tests/bridge/*` — needs the pipeline server / port binding (`test_pipeline_server.py` and `test_pipeline_integration.py`).
- `tests/test_ablation.py::TestAblationHaressIndividual` — needs Go API on `http://localhost:8080/api/v1/diagnostics` (heartbeat).
- Long-running training / replay tests under `slow` and `integration` markers were excluded.

## 7. Stale-pattern scan

**Raw action literals** (`"fetch_market_data"` / `"compute_signals"` outside `actions.py` and `NodeAction` references):

```
omega/core/orchestrator_v2.py:439     # inside a comment, not runtime
omega/nodes/victoria/victoria_node.py:28  # docstring; CLAUDE.md explicitly permits legacy aliases here
```

No real violations.

**`os.environ.get(...API_KEY|SECRET...)` outside `credentials.py`** (12 hits):

```
omega/core/startup_validator.py:271   ANTHROPIC_API_KEY / CLAUDE_API_KEY  (presence-check, legitimate)
omega/core/startup_validator.py:275   COINGECKO_API_KEY / CG_API_KEY      (presence-check, legitimate)
omega/nodes/victoria/data_cache.py:104                    FRED_API_KEY
omega/nodes/victoria/unusual_whales_provider.py:45        UW_API_KEY
omega/nodes/victoria/whale_signal.py:375                  WHALE_ALERT_API_KEY
omega/nodes/victoria/whale_signal.py:391                  COINGLASS_API_KEY
omega/nodes/victoria/data_providers.py:37                 CG_API_KEY
omega/nodes/victoria/data_providers.py:933                COINBASE_API_KEY
omega/nodes/victoria/llm_meta_controller.py:405           ANTHROPIC_API_KEY
omega/nodes/polymarket/clob_client.py:236                 POLYMARKET_API_KEY
omega/nodes/polymarket/clob_client.py:237                 POLYMARKET_API_SECRET
omega/integrations/twitter_feed.py:294                    SN13_API_KEY
```

`startup_validator` is legitimate (it's specifically checking presence of env vars). The other 10 are in **project** code (`omega/nodes/victoria/`, `omega/nodes/polymarket/`, `omega/integrations/`). Per CLAUDE.md, project code is allowed flexibility, but routing all secret reads through `omega/core/credentials.py` would still be a useful tidy-up. Tracked as a follow-up — not auto-applied because the migration touches 10 files across two projects and an integration module.

## 8. Repository state caveat

`git status` on entry showed substantial pre-existing modifications across `internal/`, `cmd/`, `omega/core/`, `omega/nodes/victoria/`, `omega/eval/`, plus untracked `__pycache__` for `cpython-3.14`. None of these were produced by this run. The task spec says to `git commit -m "chore: automated code quality fixes"` after applying fixes, but doing so here would attribute someone else's in-progress changes to an automated quality pass — refused. **No commits made.**

## 9. Success criteria scorecard

| Criterion | Status |
|---|---|
| `go build ./...` passes | NOT RUN — sandbox disk/bindfs constraints |
| `golangci-lint run ./...` returns 0 issues | NOT RUN — same |
| `ruff check omega/` returns 0 issues | **PASS** |
| All Go test packages pass | NOT RUN — same |
| Contract tests pass | **PASS** (28/28) |
| No regressions in Python test suite | UNVERIFIED — full suite couldn't run in one process; 13 pre-existing failures observed in curated batches |

## 10. Recommended follow-ups (manual review)

1. Reconcile `_long_conviction_threshold` (currently 0.07) with `omega/eval/v49_gates.py` and decide: revert threshold to 0.10 or update tests + CLAUDE.md.
2. Update `tests/test_conviction.py` fixtures to account for the basket-relative normalization in `_rank_signals` (or document the new contract).
3. Re-run `make quality` on the host machine to fill in the Go-side gaps.
4. Optional cleanup: route the 10 project-code `os.environ.get(...API_KEY)` reads through `omega.core.credentials` for consistency.
