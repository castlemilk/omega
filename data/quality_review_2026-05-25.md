# Omega Code Quality Review — 2026-05-25

Automated scheduled run. The user was not present, so I executed autonomously and produced a report rather than committing fixes.

## TL;DR

- **Python lint/format: clean.** `ruff check omega/` and `ruff format --check omega/` both pass (252 files formatted, 0 lint issues).
- **No automated fixes applied.** The repo is already clean on the surfaces an automated pass can safely touch. The 234 mypy errors in `omega/core/` and the open test failure described below need human design decisions, not blind edits.
- **One real test failure** worth a human look: `tests/test_adversarial_v2.py::TestAdversarialPressureV2::test_ring2_activates_after_enough_cycles` — `ring2_activated` is `False` at cycle 20 when the test expects `True`.
- **Go pipeline was blocked** by the sandbox (no Go toolchain on `PATH`; the in-repo `.gomod` cache is read-only and missing some sub-packages). The Python suite is partially blocked because the sandbox has Python 3.10 but the project requires 3.11+.

## Step-by-step results

### 1. Go quality checks — BLOCKED (environment)

`go build ./...`, `golangci-lint run ./...`, and `go test ./... -short` could not be run.

- No system Go on `PATH`. The in-repo `.gomod/golang.org/toolchain@v0.0.1-go1.25.0.linux-arm64/bin/go` binary exists and runs, but:
  - The module cache at `.gomod/pkg/mod` is mounted read-only — `go build` errors with `remove …/.partial: operation not permitted` whenever it tries to materialize a download stub.
  - Several extracted module dirs are incomplete in the cache (e.g. `golang.org/x/sync@v0.20.0` exists but has no `errgroup/` subdir; same shape for `spf13/cobra`, `spf13/viper`, `google.golang.org/protobuf`, `golang-jwt/jwt`, `gopkg.in/yaml.v3`, etc.).

This needs to run on the user's local machine where `make build` and `make lint` already work, or in a sandbox with full network + writable `GOMODCACHE`.

### 2. Python quality checks

| Check | Result |
| --- | --- |
| `ruff check omega/` | **PASS** — All checks passed |
| `ruff format --check omega/` | **PASS** — 252 files already formatted |
| `mypy omega/core/ --ignore-missing-imports` | **234 errors in 25 files** (pre-existing) |
| `pytest tests/test_action_contracts.py` | **8 failed / 20 passed** — all 8 failures are `ImportError: cannot import name 'UTC' from 'datetime'` (Python 3.10 vs project's 3.11+ requirement) |

The 234 mypy errors are real but they're the kind that don't yield to mechanical fixes:

- numpy ndarray shape narrowing (`ndarray[tuple[int, ...], dtype[float64]]` vs `ndarray[tuple[int], dtype[float64]]` in `hmm_regime.py`)
- `TypedDict` vs `dict[str, Sequence[str]]` assignments in `strategy.py` (lines 2186, 2459)
- `ConfluenceResult | None` assigned to non-optional in `strategy.py:2680/2712`
- "Cannot assign to a type" patterns in `signal_generation.py` (fallback `_TradeReinforcer = None` after the import)
- `attr-defined` errors in `project_config.py` for `_tickers`, `_min_conviction`, `PaperTradingExecutorNode`
- `union-attr` in `meta_harness.py:703` where `self._brain.consult(...)` is called on `Brain | None`

Each one of these is a 1–3 line decision (`assert x is not None`, `cast`, define a `TypedDict`, etc.) but blind edits would risk altering runtime behaviour. Recommend opening a focused PR.

### 3. Fixes applied

**None.** No automated fixes were applicable — see above for why.

### 4. Full Python test suite — PARTIAL (environment)

Couldn't run the full 1,610-test suite end-to-end inside the sandbox:

- Sandbox is Python 3.10.12; the project requires 3.11+ (uses `from datetime import UTC`).
- 43 of the 116 test files fail at *collection time* because importing any module under `omega/nodes/victoria/`, `omega/nodes/polymarket/`, `omega/eval/`, etc. triggers the `UTC` import.

A representative sample I did run (11 test files, ~29 s):

- **260 passed**
- **6 failed** (5 are the same Python-3.10 `UTC` import error; 1 is a real assertion failure — see below)
- **44 skipped**
- **1 collection error** (`tests/test_baselines.py`)

### 5. Stale code patterns

**Raw action literals:** no real hits.

- `omega/core/orchestrator_v2.py:439` — comment showing the translation example `"DATA_INGESTION" → "fetch_market_data"`.
- `omega/nodes/victoria/victoria_node.py:28` — module docstring listing capabilities.

Both are documentation, not code, and don't violate the contract. The grep can probably be tightened to exclude `#` and `"""` lines on the next pass.

**`os.environ.get(...)` reading API keys/secrets outside `credentials.py`** — 12 hits across 8 files:

- `omega/core/startup_validator.py` (271, 275) — `ANTHROPIC_API_KEY`/`CLAUDE_API_KEY`, `COINGECKO_API_KEY`/`CG_API_KEY`
- `omega/nodes/victoria/data_cache.py:104` — `FRED_API_KEY`
- `omega/nodes/victoria/unusual_whales_provider.py:45` — `UW_API_KEY`
- `omega/nodes/victoria/whale_signal.py` (375, 391) — `WHALE_ALERT_API_KEY`, `COINGLASS_API_KEY`
- `omega/nodes/victoria/data_providers.py` (37, 933) — `CG_API_KEY`, `COINBASE_API_KEY`
- `omega/nodes/victoria/llm_meta_controller.py:405` — `ANTHROPIC_API_KEY`
- `omega/nodes/polymarket/clob_client.py` (236, 237) — `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`
- `omega/integrations/twitter_feed.py:294` — `SN13_API_KEY`

These should migrate to `omega/core/credentials.py`. Not done here because that's a refactor with semantic implications (`.strip()`, default `"DEMO_KEY"`, fall-through aliases like `ANTHROPIC_API_KEY or CLAUDE_API_KEY`), and the task didn't ask for that specific migration.

## Real failure found

```
tests/test_adversarial_v2.py::TestAdversarialPressureV2::test_ring2_activates_after_enough_cycles

assert report.ring2_activated is True
       (got False at cycle 20 with min_ring1_cycles_for_ring2=10,
        min_ring1_flag_rate_for_ring2=0.01, variants set to agree=False)
```

The test runs 10 cycles with disagreement, then calls cycle 20 expecting Ring 2 to be activated by the cycle-interval gate. Ring 2 doesn't activate. Possible causes (not investigated):

- Ring 1 reports `flagged=False` despite `agree=False` — the `_make_variant_outputs(agree=False)` fixture may not produce enough divergence to clear the disagreement threshold, so the flag rate stays below `0.01`.
- The cycle-interval check expects `cycle == RING2_SIM_INTERVAL` exactly but the actual constant differs.

Worth a human eye on `omega/core/adversarial_v2.py` (or wherever `AdversarialPressureV2.run_v2` lives) — could be a real regression in Ring 2 gating, or a stale test fixture.

## Success-criteria scorecard

| Criterion | Status |
| --- | --- |
| `go build ./...` passes | Not run (no Go in sandbox) |
| `golangci-lint run ./...` returns 0 issues | Not run |
| `ruff check omega/` returns 0 issues | **PASS** |
| All Go test packages pass | Not run |
| Contract tests pass | FAIL in sandbox (Python 3.10); needs re-run on a 3.11+ host |
| No regressions in Python test suite | 1 real failure flagged (`test_ring2_activates_after_enough_cycles`); rest of sampled tests pass |

## Recommendations

1. Re-run this scheduled task on a host with Go 1.25 and Python 3.11+ on `PATH` so the Go pipeline and the full Python suite can actually execute.
2. Investigate `test_ring2_activates_after_enough_cycles` — likely either a real Ring 2 gating regression or a stale test fixture.
3. Open a targeted PR to address the 234 mypy errors in `omega/core/` in small batches by error kind (numpy types, TypedDict, optional unwrapping, attr-defined).
4. File a follow-up to migrate the 12 `os.environ.get` credential reads into `omega/core/credentials.py`.
