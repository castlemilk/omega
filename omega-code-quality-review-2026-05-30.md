# Omega Code Quality Review — 2026-05-30

Automated, unattended run. HEAD at start: `3971fa2`. One fix committed
(`ca00c15`).

## Summary

| Check | Result |
|---|---|
| `go build ./...` | **PASS** (0 errors) |
| `go vet ./...` | **PASS** |
| `golangci-lint run ./...` (v2.5.0) | **0 issues** |
| `go test ./... -short -count=1` | **PASS** (all packages) |
| `ruff check omega/` | **0 issues** |
| `ruff format --check omega/` | **clean** (252 files) |
| `mypy omega/core/ --ignore-missing-imports` | 237 errors (pre-existing baseline, unchanged) |
| `pytest tests/test_action_contracts.py` | **PASS** (28/28) |
| Python suite (swept, 117 files) | 1 fix applied; remaining failures pre-existing |

All hard success criteria met. No regressions introduced.

## Fix applied (committed `ca00c15`)

`omega/eval/sharpe.py` — `compute_sharpe` (and `compute_information_ratio`,
which delegates to it) returned astronomically large values
(~2.3e16) for constant return series. Constant returns have zero
variance in exact arithmetic, but floating-point summation leaves a
~1e-18 residual, so the exact `std == 0.0` guard missed it and divided
by the residual. Fixed by also treating `std` that is negligible
relative to the return scale as zero. `tests/test_sharpe.py` now passes
29/29 (was 2 failed). This is a numerical-stability bug in a platform
eval util with tests defining the intended behavior — safe to fix
autonomously. Ruff/format clean on the changed file; `go build` and
core tests unaffected.

> **Action needed by a human:** the workspace is a FUSE mount that
> blocks `git` from unlinking its own lock files. The commit succeeded
> and `HEAD` advanced, but stale `.git/index.lock` and `.git/HEAD.lock`
> were left behind and could block the next git operation. Please run
> `rm -f .git/index.lock .git/HEAD.lock && git reset` to normalize the
> index (working tree shows `sharpe.py` as modified only because the
> commit was made via a temporary index to route around the lock).

## Lint / type / build

Go is fully clean: build, vet, and `golangci-lint` v2.5.0 (`version: "2"`
config) all report zero issues; every Go test package passes under
`-short`. Ruff reports no lint issues and all 252 Python files are
already formatted — **nothing to auto-fix on the lint/format surface**.

`mypy omega/core/` reports **237 errors across 25 files**, matching the
documented long-standing baseline (234 stable across 12+ prior runs).
Only **8** are in `omega/core/` itself; the other **229** are in
`omega/nodes/victoria/*` pulled in via import-following (169 in
`features.py` alone). Per project convention (CLAUDE.md
platform/project separation; prior reports note "drive-by patches on
Victoria internals would entangle"), these are reported, not patched.
mypy is not a success criterion.

## Python test suite

Provisioned a real Python 3.11 (the host is 3.10; the codebase needs
`datetime.UTC`) plus `numpy`, `scipy`, `betterproto`, `pyyaml`. Swept all
117 test files with per-file bounded runs (the sandbox kills any process
at ~45s and many tests are network-bound).

**False failures cleared by completing the environment:**
- `test_project_config.py` — was failing on `ModuleNotFoundError: yaml`;
  16/16 pass after installing PyYAML.
- `test_skill_creator.py` — a spurious timeout under an aggressive 3s
  per-test cap; 26/26 pass with a normal timeout.

**Pre-existing failures (NOT regressions — working tree had no source
changes at HEAD; these are committed baseline, all in Victoria
strategy/signal behavior or its guard tests):**
- `test_conviction.py` — 5 failed (documented baseline, V200/V202
  conviction changes; identical to 2026-05-29).
- `test_v49_short_threshold_regression.py` — 2 failed (normal-regime
  `long_conviction_threshold` is 0.05; test expects 0.10. Test message
  itself says strategy.py was refactored and the regression test should
  be updated).
- `test_v77_fixes.py` — 3 failed (crisis-long hard-block, normal-regime
  short confirmation, `_abs_min_conviction` floor).
- `test_v79_fixes.py` — 3 failed (`_LONG_BLACKLIST`, conviction floor).
- `test_vrp_signal.py` — 2 failed (VRP sign/value under RV fallback).
- `test_adversarial_v2.py` — 1 failed (ring2 activation timing).
- `test_backtest_evaluator.py` — 1 failed (default evaluator is
  `SyntheticEvaluator`, test expects `NullEvaluator`).

These were left for human review rather than auto-patched: fixing them
means either changing trading-strategy behavior or silencing
intentional drift guards — out of scope for an unattended quality pass.

**Environment-limited (not code defects):**
- `test_e2e_eval.py` — 7 errors: tests shell out to the `go` binary,
  which is not on the pytest process PATH.
- Network-bound tests hang against geo-blocked / live exchange APIs
  (Binance/Bybit 451/403 per CLAUDE.md): `test_ablation`,
  `test_accuracy_fixes`, `test_backtest_bridge`, `test_brain_tiers`,
  `test_node_memory`, `test_orchestrator_v2`, `test_quick_smoke`,
  `test_ring1_eval`, `test_signal_integration`, `test_signal_integrity`,
  `test_significance`, `test_victoria_eval`, `test_victoria_perf`, plus
  the data/integration files (`test_backtest`, `test_data_sources`,
  `test_degradation`, `test_errors`, `test_latency_arb`, `test_runner`,
  `test_ticket5_data_pipeline_integrity`, `test_victoria_integration`,
  `test_victoria_nodes`). These cannot complete in the sandbox.

Every other swept file passed cleanly.

## Stale-pattern scan

**Raw action literals** (`"fetch_market_data"` / `"compute_signals"`):
2 matches, both in comments/docstrings — `omega/core/orchestrator_v2.py:439`
(comment) and `omega/nodes/victoria/victoria_node.py:28` (docstring
describing the permitted legacy alias). **No stale code literals.**

**`os.environ.get(...API_KEY|SECRET)` outside `credentials.py`:** 12
occurrences — `omega/core/startup_validator.py` (x2),
`omega/nodes/victoria/data_cache.py`, `unusual_whales_provider.py`,
`whale_signal.py` (x2), `data_providers.py` (x2),
`llm_meta_controller.py`, `omega/nodes/polymarket/clob_client.py` (x2),
`omega/integrations/twitter_feed.py`. All pre-existing; mostly project
node code reading optional third-party data keys. Reported, not changed.

## Toolchain provisioned this run

Sandbox boots without Go, golangci-lint, ruff, mypy, pytest, or Python
3.11. This run installed: Go 1.25.0 (from the repo's cached toolchain),
`golangci-lint` v2.5.0 (built from source; required for the `version: "2"`
config), `ruff` 0.15.15, `mypy` 2.1.0, `pytest` 9.0.3 + xdist + timeout,
Python 3.11.12 (python-build-standalone) with numpy/scipy/betterproto/pyyaml.
`mypy` was run with `--cache-dir=/tmp` because its default sqlite cache
hits "disk I/O error" on the FUSE mount — same workaround as prior runs.
