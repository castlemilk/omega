# Omega Code Quality Review — 2026-05-08

Automated scheduled run. HEAD = `f2cff01`. Working tree had **1448 modified files** uncommitted at start of run (long-running in-flight work, same pattern as 2026-05-02 / 2026-05-04). No fixes were committed: bundling autofixes with that state would have conflated authorship with the in-flight changes already on disk.

## Summary

| Check                                      | Result                                              |
|--------------------------------------------|-----------------------------------------------------|
| `go build ./...`                           | **PASS** (clean)                                    |
| `golangci-lint run ./...` (v2.5.0)         | **PASS** (0 issues)                                 |
| `go test ./... -short -count=1`            | **PASS** (all 32 testable packages)                 |
| `ruff check omega/`                        | **PASS** (0 issues, 252 files)                      |
| `ruff format --check omega/`               | **PASS** (252 files already formatted)              |
| `mypy omega/core/ --ignore-missing-imports`| 239 errors (13 in `omega/core/`, pre-existing)      |
| `pytest tests/test_action_contracts.py`    | **PASS** (28/28)                                    |
| Targeted regression sample (~370 tests, 11 files) | **8 failures** (all match 2026-05-04 baseline) |
| Stale raw action literals                  | 2 hits, all in comments/docstrings (no real usage)  |
| Direct `os.environ.get(...API_KEY/SECRET)` | 12 hits across 8 files (unchanged from 2026-05-04)  |

Net status vs 2026-05-04: **Go pipeline now runnable in sandbox** (was blocked on disk last week, now resolved via tmpfs caches). Python lint/format/contract surface still clean. 8 documented test regressions persist on HEAD (no new ones). No new mypy errors.

## Sandbox setup notes

The session image ships with Python 3.10 only and no Go toolchain. To run this review I:

1. Downloaded Go 1.25.4 (project requires `go 1.25.0`) into `/tmp/go`.
2. Installed `golangci-lint` v2.5.0 (the project `.golangci.yml` is v2 schema; v1.x lints fail on `can't load config`).
3. Used `/dev/shm` (2 GB tmpfs) for `GOCACHE` and `GOLANGCI_LINT_CACHE` after `/sessions` filled up (only 28 MB free at peak — the project's go.mod graph plus build cache is too large for the session disk).
4. Used `uv python install 3.11` (`UV_PYTHON_INSTALL_DIR=/dev/shm/uvpy`) and `pip install --break-system-packages numpy psycopg betterproto pyyaml httpx pydantic pytest pytest-timeout pytest-xdist` because the codebase imports `datetime.UTC` (3.11+) and several core modules transitively pull numpy.
5. Used `MYPY_CACHE_DIR=/dev/shm/mypy_cache` because mypy's default cache hit `sqlite3.OperationalError: disk I/O error` from disk pressure.

The full Python test suite (2730 tests collected) still doesn't fit cleanly in the 45 s sandbox windows — the alphabetically-first hung test, `tests/test_ablation.py::TestAblationHaressIndividual::test_run_full_returns_eval_report`, sleeps inside `OmegaOrchestrator.run` past the per-test timeout. So full-suite reporting is approximated via a focused regression sample, same as previous weeks.

## Go quality

Clean across the board.

`go build ./...` — passes after one round of module download. No errors, no warnings.

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

(Plus 7 packages with no test files — `cmd/eval-health`, `cmd/eval-runner`, `cmd/omega`, `cmd/omega-api`, `gen/go/...`, `internal/brain`, `internal/errors`, `internal/projectseed`, `internal/telemetry`, `internal/testing`, `internal/integrations/connectors`.)

## Python lint and format

`ruff check omega/` and `ruff format --check omega/` both clean. **252 files inspected**. No autofix needed.

## Python type check

`mypy omega/core/ --ignore-missing-imports` reports **239 errors in 28 files**. Identical to 2026-05-04 baseline.

Distribution unchanged:

- `omega/nodes/victoria/features.py` — 169 (transitively imported from `omega/core/`)
- `omega/nodes/victoria/hmm_regime.py` — 9
- `omega/nodes/victoria/strategy.py` — 6
- `omega/nodes/victoria/decision_embeddings.py` — 6
- Other `omega/nodes/victoria/*` — 36
- **`omega/core/*` — 13 errors** (in `node_skills.py`, `llm_shell.py`, `decision_snapshot.py`, `alerting.py`, `paper_trading.py`, `node_adapter.py`, `project_config.py`, `meta_harness.py`)

Representative `omega/core/` errors (unchanged):

```
omega/core/node_skills.py:360       Non-overlapping equality check  [comparison-overlap]
omega/core/llm_shell.py:194         Returning Any from declared float
omega/core/decision_snapshot.py:318 Function missing return type annotation
omega/core/alerting.py:251          Argument 1 to "float" has incompatible type
omega/core/paper_trading.py:150     Returning Any from declared float
omega/core/node_adapter.py:391-393  Item "None" of "Any | None" has no attribute  [union-attr]
omega/core/project_config.py:265    "DataIngestionNode" has no attribute "_tickers"  [attr-defined]
omega/core/project_config.py:341    "StrategyNode" has no attribute "_min_conviction"  [attr-defined]
omega/core/project_config.py:348    Module "omega.core.paper_trading" has no attribute "PaperTradingExecutorNode"
omega/core/meta_harness.py:351,357  Returning Any from declared dict/int
omega/core/meta_harness.py:702      Item "None" of "Any | None" has no attribute "consult"
```

Not autofixed (same reasoning as 2026-05-04): the dominant 169 are transitively imported `victoria/features.py` issues that touch the platform/project boundary, and the 13 in `omega/core/` are real platform integration points where the brittle `_tickers` / `_min_conviction` private-attribute access in `project_config.py` is a refactor question, not a type-annotation typo. The `PaperTradingExecutorNode` import has been broken for at least three weekly runs and warrants a deliberate fix (rename, removal, or shim) outside an automated quality pass.

## Tests

### Contract tests
`pytest tests/test_action_contracts.py` — **28 passed**. Action / step contract intact.

### Targeted regression sample
Files: `test_action_contracts.py`, `test_adversarial.py`, `test_adversarial_v2.py`, `test_brain_tiers.py`, `test_debate_gate.py`, `test_orchestrator.py`, `test_orchestrator_v2.py`, `test_signal_adapter.py`, `test_signal_integrity.py`. Approximately 370 tests collected, **8 failed** — all match the 2026-05-04 baseline:

#### Threshold drift (5 failures, `tests/test_signal_integrity.py`)
```
TestRegimeAdaptivity::test_normal_regime_thresholds
TestRegimeAdaptivity::test_bear_regime_suppresses_longs_permits_shorts
TestRegimeAdaptivity::test_bear_detection_threshold_at_055
TestRegressionGuard::test_bull_threshold_at_055
TestRegressionGuard::test_bear_threshold_at_055
```

Same root cause as last two weekly runs: implementation has `_long_conviction_threshold = 0.07` (V88 drift) and `_short_conviction_threshold = 0.04` (bear regime) where tests + `CLAUDE.md` document `0.10` / `0.05`. Fresh failure output:

```
assert 0.07 == 0.1
  +  where 0.07 = StrategyNode._long_conviction_threshold
test_signal_integrity.py:541: assert 0.07 == 0.1

AssertionError: Bear short threshold=0.04 (expected 0.05 — permissive shorts in bear market)
  assert 0.04 == 0.05
  +  where 0.04 = StrategyNode._short_conviction_threshold
```

The `CLAUDE.md` contract is unambiguous: `**NORMAL** (else): long=0.10, short=0.05 (V49 fix)`. Code-vs-test-vs-docs drift through V88 → V94 → V95 has not been reconciled. **Not autofixed** — this is a policy question (which side is correct?) requiring human judgment.

#### Adversarial (3 failures, pre-existing)
```
tests/test_orchestrator_v2.py::TestAdversarialIntegration::test_adversarial_variant_outputs_built_from_signal_data
tests/test_orchestrator_v2.py::TestAdversarialGateRejectsLowQualityProposals::test_high_disagreement_blocks_pico_proposal
tests/test_adversarial_v2.py::TestAdversarialPressureV2::test_ring2_activates_after_enough_cycles
```

Both `test_orchestrator_v2` failures are gate-vs-pass mismatches where Ring 1 fires (max_disagreement ≥ 0.9, well above the 0.2 threshold) but the proposal still executes a trade — the adversarial gate is observing high disagreement but not blocking the pico proposal. The Ring 2 activation test continues to assert `False is True` for `ring2_activated` after 20 cycles. Same root cause traced last week to commit `7a22358 feat(adversarial): Ring 2 scenario bank and adaptive thresholds`.

### Why fixes were not auto-applied
Same as 2026-05-04:

1. The threshold mismatch is a **policy decision**, not a typo. Tests, code, and `CLAUDE.md` disagree; aligning any two requires picking which is correct.
2. The adversarial gate failures need real investigation, not annotation fixes — the gate is firing but its decision is being lost downstream, and silencing the test would remove signal that the gate isn't actually blocking.
3. Bundling fixes into a `chore: automated code quality fixes` commit on top of 1448 already-modified files would have conflated authorship.

### Full-suite reach
Approximate full-suite run was attempted via `pytest tests/` with `-x` and per-test timeout of 10s. It stopped at `tests/test_ablation.py::TestAblationHaressIndividual::test_run_full_returns_eval_report` after 18.5 s with a `time.sleep(wait)` timeout in `omega/core/orchestrator_v2.py:851` (`OmegaOrchestrator.run` polling loop). 67 tests passed, 1 timed out. This isn't a code regression — it's a test that needs a `max_cycles` parameter or fake clock and currently won't terminate in unit-test time. Worth filing separately.

## Stale patterns

### Raw action literals
`grep -rn '"fetch_market_data"\|"compute_signals"' omega/ --include="*.py" | grep -v actions.py | grep -v NodeAction`:

```
omega/core/orchestrator_v2.py:439:    # node_type (e.g. "DATA_INGESTION" → "fetch_market_data"),
omega/nodes/victoria/victoria_node.py:28:  "compute_signals"   → run all signal types
```

Both hits are in comments / module docstrings — **no real raw-literal usage**. OK as-is. Identical to 2026-05-02 and 2026-05-04.

### Direct env-var access for API keys / secrets
`grep -rn 'os.environ.get.*API_KEY\|os.environ.get.*SECRET' omega/ --include="*.py" | grep -v credentials.py` — **12 hits across 8 files**, identical to 2026-05-04:

```
omega/core/startup_validator.py:271,275
omega/nodes/victoria/data_cache.py:104                 (FRED_API_KEY)
omega/nodes/victoria/unusual_whales_provider.py:45     (UW_API_KEY)
omega/nodes/victoria/whale_signal.py:375,391           (WHALE_ALERT_API_KEY, COINGLASS_API_KEY)
omega/nodes/victoria/data_providers.py:37,933          (CG_API_KEY, COINBASE_API_KEY)
omega/nodes/victoria/llm_meta_controller.py:405        (ANTHROPIC_API_KEY)
omega/nodes/polymarket/clob_client.py:236,237          (POLYMARKET_API_KEY/SECRET)
omega/integrations/twitter_feed.py:294                 (SN13_API_KEY)
```

These bypass `omega/credentials.py`. Tracked but not autofixed in a quality pass — the call sites have varied fallback semantics (`"DEMO_KEY"`, blank string, `None`) that need per-site decisions about whether the credential is required vs optional.

## Carry-over recommendations

Open items from previous reviews still applicable:

1. **Reconcile threshold drift** — pick one of {tests + CLAUDE.md (0.10 / 0.05), implementation (0.07 / 0.04)} and update the other two. 5 tests will turn green either way.
2. **Adversarial gate downstream wiring** — `Ring 1 fired` warns at max_disagreement ≥ 0.9 but the gate doesn't block the trade. Worth bisecting from `7a22358`.
3. **Fix `omega/core/paper_trading.PaperTradingExecutorNode` import** — referenced by `omega/core/project_config.py:348` but no longer exported.
4. **Migrate the 12 `os.environ.get(...API_KEY/SECRET)` call sites** to `omega/credentials.py`.
5. **Bound `OmegaOrchestrator.run` for unit testing** — the abalation harness test cannot terminate without a `max_cycles` argument or a fake clock.
6. **Land an isolated commit for the 1448 modified-tree files** — they have been carried for 4+ weekly runs and prevent any automated `chore: ...` commit from this scheduled job.

## Success criteria check

- ✅ `go build ./...` passes
- ✅ `golangci-lint run ./...` returns 0 issues
- ✅ `ruff check omega/` returns 0 issues
- ✅ All Go test packages pass
- ✅ Contract tests pass (28/28)
- ⚠ No regressions in Python test suite — **8 known failures persist** (5 threshold drift + 3 adversarial), unchanged from 2026-05-04. No newly observed regressions on HEAD `f2cff01` vs HEAD on 2026-05-04.
