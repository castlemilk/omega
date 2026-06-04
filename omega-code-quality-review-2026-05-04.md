# Omega Code Quality Review — 2026-05-04

Automated scheduled run. Working tree had **1444 modified files** uncommitted at start of run (long-running in-flight work, same pattern as 2026-05-02). No fixes were committed: bundling autofixes with that state would have conflated authorship with the in-flight changes already on disk.

## Summary

| Check                          | Result                                              |
|--------------------------------|-----------------------------------------------------|
| `go build ./...`               | NOT RUN — sandbox out of disk                       |
| `golangci-lint run ./...`      | NOT RUN — sandbox out of disk                       |
| `go test ./... -short -count=1`| NOT RUN — sandbox out of disk                       |
| `ruff check omega/`            | PASS (0 issues)                                     |
| `ruff format --check omega/`   | PASS (252 files already formatted)                  |
| `mypy omega/core/ --ignore-missing-imports` | 239 errors (13 in `omega/core/`, pre-existing) |
| `pytest tests/test_action_contracts.py` | PASS (28/28)                            |
| Targeted regression sample (~180 tests across 9 files) | **8 failures (1 pre-existing, 7 newly observed)** |
| Stale raw action literals      | 2 hits, all in comments/docstrings                  |
| Direct `os.environ.get(...API_KEY/SECRET)` | 12 hits across 8 files                  |

## Go quality

Could not run any Go check this session. The sandbox has 770 MB free, and downloading the Go module graph for this project (Connect-RPC, gRPC, OTel, pgx, Anthropic SDK, prometheus, etc.) plus a single `go build ./...` exhausted the device with `no space left on device` errors mid-build. `golangci-lint` is even larger and was not attempted.

This is the same disk pressure observed on 2026-05-02 (which managed `go build`/`go vet`/`go test` only by skipping golangci-lint). The Go toolchain itself unpacked successfully (1.23.4 linux/arm64 — sandbox is aarch64), so the limitation is purely scratch-space, not toolchain availability.

**Recommend running Go checks locally on host** — the host's Mac has plenty of disk and a populated `GOMODCACHE`, so the same checks should complete in under a minute.

## Python lint and format

`ruff check omega/` and `ruff format --check omega/` both pass cleanly. No autofix needed. 252 source files inspected.

## Python type check

`python3 -m mypy omega/core/ --ignore-missing-imports` reports **239 errors in 28 files** — identical baseline to 2026-05-02. **Not autofixed** for the same reasons as last run (transitively-imported project code dominates, fixes touch platform integration points, working tree already heavily modified).

Distribution unchanged from 2026-05-02:
- `omega/nodes/victoria/features.py` — 169 (transitively imported)
- `omega/nodes/victoria/hmm_regime.py` — 9
- `omega/nodes/victoria/strategy.py` — 6
- `omega/nodes/victoria/decision_embeddings.py` — 6
- Other `omega/nodes/victoria/*` — 36
- `omega/core/*` — **13 errors** (in `node_skills.py`, `llm_shell.py`, `decision_snapshot.py`, `alerting.py`, `paper_trading.py`, `node_adapter.py`, `project_config.py`, `meta_harness.py`)

Representative `omega/core/` errors:

```
omega/core/node_skills.py:360  Non-overlapping equality check  [comparison-overlap]
omega/core/node_adapter.py:391-393  Item "None" of "Any | None" has no attribute  [union-attr]
omega/core/project_config.py:265  "DataIngestionNode" has no attribute "_tickers"  [attr-defined]
omega/core/project_config.py:341  "StrategyNode" has no attribute "_min_conviction"  [attr-defined]
omega/core/project_config.py:348  Module "omega.core.paper_trading" has no attribute "PaperTradingExecutorNode"
omega/core/meta_harness.py:702  Item "None" of "Any | None" has no attribute "consult"  [union-attr]
```

## Tests

### Contract tests
`pytest tests/test_action_contracts.py` — **28 passed**. Action / step contract is intact.

### Targeted regression sample
The 2730-test full suite still doesn't fit in 45-second sandbox windows. I ran a focused subset of files most likely to surface regressions: `test_action_contracts.py`, `test_adversarial.py`, `test_adversarial_v2.py`, `test_brain_tiers.py`, `test_debate_gate.py`, `test_orchestrator.py`, `test_orchestrator_v2.py`, `test_signal_adapter.py`, `test_signal_integrity.py`. Roughly 180 tests, **8 failed**:

#### Pre-existing (also failed on 2026-05-02)
```
FAILED tests/test_adversarial_v2.py::TestAdversarialPressureV2::test_ring2_activates_after_enough_cycles
  assert False is True
   +  where False = AdversarialReportV2(...).ring2_activated
```
Same Ring 2 activation gating bug — likely tied to commit `7a22358 feat(adversarial): Ring 2 scenario bank and adaptive thresholds`.

#### Newly observed regressions on HEAD
These were not flagged on 2026-05-02 because the prior run only sampled `test_adversarial_v2.py`. They are real failures on HEAD (verified — `git show HEAD:omega/nodes/victoria/strategy.py` produces the same threshold value as the working tree, so they are not caused by uncommitted changes):

```
FAILED tests/test_signal_integrity.py::TestRegimeAdaptivity::test_normal_regime_thresholds
FAILED tests/test_signal_integrity.py::TestRegimeAdaptivity::test_bear_regime_suppresses_longs_permits_shorts
FAILED tests/test_signal_integrity.py::TestRegimeAdaptivity::test_bear_detection_threshold_at_055
FAILED tests/test_signal_integrity.py::TestRegressionGuard::test_bull_threshold_at_055
FAILED tests/test_signal_integrity.py::TestRegressionGuard::test_bear_threshold_at_055
```

All five fail on the same drift: `_long_conviction_threshold` for the normal regime is **0.07** in the implementation but the tests (and `CLAUDE.md`) say **0.10**. The change is documented in the inline comment block at `omega/nodes/victoria/strategy.py:1064-1088` (V88 → 0.07 to capture post-crash ETH recovery longs, repeatedly reverted/re-applied through V94/V95). The `_short_conviction_threshold` for normal regime is also **0.07** in code but **0.05** in tests/docs (V94/V95 history).

This is genuine code-vs-test-vs-docs drift. The tests encode the *documented* behavior in `CLAUDE.md`:

> **NORMAL** (else): long=0.10, short=0.05 (V49 fix)

The implementation has drifted from that contract through V88/V94/V95 iterations without test or doc updates.

```
FAILED tests/test_orchestrator_v2.py::TestAdversarialIntegration::test_adversarial_variant_outputs_built_from_signal_data
FAILED tests/test_orchestrator_v2.py::TestAdversarialGateRejectsLowQualityProposals::test_high_disagreement_blocks_pico_proposal
```

Two adversarial-integration failures — likely related to the same Ring 2 / adversarial gating regression as `test_ring2_activates_after_enough_cycles` (commit `7a22358`).

### Why fixes were not auto-applied
Per the task's "fix issues found automatically" step, I deliberately did not modify tests or implementation:

1. The threshold mismatch is a **policy decision**, not a typo. The implementation and the documented contract disagree; aligning tests with code (or vice versa) requires human judgment about which is correct.
2. `CLAUDE.md` is the source of truth for documented behavior, and changing tests to match drifted code would silently retire that contract.
3. The working tree already has 1444 modified files; bundling fixes into a `chore: automated code quality fixes` commit would have conflated authorship.

## Stale patterns

### Raw action literals
`grep -rn '"fetch_market_data"\|"compute_signals"' omega/ --include="*.py" | grep -v actions.py | grep -v NodeAction`:

```
omega/core/orchestrator_v2.py:439:                # node_type (e.g. "DATA_INGESTION" → "fetch_market_data"),
omega/nodes/victoria/victoria_node.py:28:  "compute_signals"   → run all signal types
```

Both hits are in comments / module docstrings — **no real raw-literal usage**. OK as-is. Same as 2026-05-02.

### Direct env-var access for API keys / secrets
`grep -rn 'os.environ.get.*API_KEY\|os.environ.get.*SECRET' omega/ --include="*.py" | grep -v credentials.py` — **12 hits across 8 files**, identical to 2026-05-02:

```
omega/core/startup_validator.py:271,275           ANTHROPIC_API_KEY, CLAUDE_API_KEY, COINGECKO_API_KEY, CG_API_KEY
omega/nodes/victoria/data_cache.py:104            FRED_API_KEY
omega/nodes/victoria/unusual_whales_provider.py:45  UW_API_KEY
omega/nodes/victoria/whale_signal.py:375,391      WHALE_ALERT_API_KEY, COINGLASS_API_KEY
omega/nodes/victoria/data_providers.py:37,933     CG_API_KEY, COINBASE_API_KEY
omega/nodes/victoria/llm_meta_controller.py:405   ANTHROPIC_API_KEY
omega/nodes/polymarket/clob_client.py:236,237     POLYMARKET_API_KEY, POLYMARKET_API_SECRET
omega/integrations/twitter_feed.py:294            SN13_API_KEY
```

No change since last run. These bypass `credentials.py` and would benefit from migration if a centralized secret abstraction exists, but each call site has different fallback semantics — not auto-migrated.

## Fixes applied

**None.** All issues found are either pre-existing tech debt, blocked by sandbox limits, or require human judgment about whether tests, code, or docs are the source of truth.

## Environment notes

- Python 3.11.15 installed via `uv` to satisfy the project's `from datetime import UTC` requirement; sandbox default is 3.10.
- Test deps installed into a `/tmp/venv` virtual environment: `pytest`, `pytest-xdist`, `pytest-timeout`, `numpy`, `betterproto`, `psycopg[binary]`.
- Go could not be exercised — 770 MB free in the sandbox, insufficient for the project's module graph.
- Project source files were **not** modified by this run.

## Recommendations

1. **Reconcile normal-regime conviction thresholds** between `strategy.py:1074,1088`, `tests/test_signal_integrity.py`, and `CLAUDE.md`. Either the V88/V94/V95 changes were intentional (update tests + docs to 0.07/0.07) or they're a regression (revert to 0.10/0.05). Five tests block on this single decision.
2. **Investigate Ring 2 activation gating** — `test_ring2_activates_after_enough_cycles` and the two `test_orchestrator_v2.py` adversarial failures are most likely a single regression in the Ring 2 → debate gate path introduced by `7a22358`.
3. **Run Go checks locally on host** — sandbox storage cannot accommodate the module graph; `make build` / `make test` / `golangci-lint run ./...` should run in under a minute on the host's populated `GOMODCACHE`.
4. **Triage 1444-file working-tree backlog.** This is the second consecutive automated review where uncommitted changes blocked any fix-and-commit work. The longer the backlog grows, the harder it becomes to safely apply tooling fixes.
5. **Consider migrating** the 12 direct `os.environ.get(...API_KEY/SECRET)` call sites to a `credentials.py`-style abstraction if one exists.

## Success criteria

| Criterion                                       | Status                              |
|-------------------------------------------------|-------------------------------------|
| `go build ./...` passes                         | Not run (sandbox disk)              |
| `golangci-lint run ./...` returns 0 issues      | Not run (sandbox disk)              |
| `ruff check omega/` returns 0 issues            | PASS                                |
| All Go test packages pass                       | Not run (sandbox disk)              |
| Contract tests pass                             | PASS (28/28)                        |
| No regressions in Python test suite             | **FAIL — 7 newly observed failures, plus the 1 pre-existing** |
