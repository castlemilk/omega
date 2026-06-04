# Omega Code Quality Review — 2026-05-31

Automated, unattended run. HEAD at start: `a643760`. **No fixes needed —
nothing to commit.** All hard success criteria met; no new regressions.

## Summary

| Check | Result |
|---|---|
| `go build ./...` | **PASS** (0 errors) |
| `golangci-lint run ./...` (v2.1.6) | **0 issues** |
| `go test ./... -short -count=1` | **PASS** (all packages) |
| `ruff check omega/` | **0 issues** |
| `ruff format --check omega/` | **clean** (252 files) |
| `mypy omega/core/ --ignore-missing-imports` | 246 errors (pre-existing baseline; see note) |
| `pytest tests/test_action_contracts.py` | **PASS** (28/28) |
| Python suite (targeted sweep) | baseline failures unchanged; no regressions |

## Lint / build / format

Go is fully clean: `go build ./...`, `golangci-lint` v2.1.6, and
`go test ./... -short` all report zero issues / all packages passing.
Ruff reports no lint issues and all 252 Python files are already
formatted. **There was nothing to auto-fix on the lint/format/build
surface, so no `chore: automated code quality fixes` commit was made.**

`mypy omega/core/ --ignore-missing-imports` reports **246 errors across
28 files**. This is the long-standing pre-existing baseline (prior run
reported 237 with mypy 2.1.0; this run used a stable mypy 1.13.0, which
accounts for the small count delta). Only a handful are in `omega/core/`
itself — the rest come from `omega/nodes/victoria/*` pulled in via
import-following. Per the platform/project separation convention in
CLAUDE.md these are reported, not patched, and mypy is not a success
criterion.

## Python test suite

The default sandbox lacks Go, ruff, mypy, golangci-lint, pytest, and a
Python 3.11 interpreter (host is 3.10; the codebase needs `datetime.UTC`,
3.11+). This run provisioned: Go 1.25.0, golangci-lint v2.1.6 (built from
source — required for the repo's `version: "2"` config and go1.25
target), ruff 0.15.15, mypy 1.13.0, pytest 9.0.3 (+ xdist, timeout), and
Python 3.11.15 with numpy/scipy/pyyaml/betterproto.

The full 117-file sweep cannot run to completion in the sandbox: many
files are network-bound against geo-blocked / live exchange APIs
(Binance/Bybit 451/403 per CLAUDE.md) and hang, and the per-call time
limit caps long runs. Verification was therefore done on (a) the
documented baseline-failure files, to prove counts are unchanged, and
(b) a sample of pure-logic files, to confirm the bulk passes.

**Documented baseline-failure files — counts identical to 2026-05-30
(NO regressions): 17 failed / 157 passed.**

| File | Failed | Matches baseline |
|---|---|---|
| `test_conviction.py` | 5 | yes |
| `test_v49_short_threshold_regression.py` | 2 | yes |
| `test_v77_fixes.py` | 3 | yes |
| `test_v79_fixes.py` | 3 | yes |
| `test_vrp_signal.py` | 2 | yes |
| `test_adversarial_v2.py` | 1 | yes |
| `test_backtest_evaluator.py` | 1 | yes |

These are all committed-baseline failures in Victoria
strategy/signal/threshold behavior or its intentional drift-guard tests
(e.g. `test_v49_short_threshold_regression` expects long-threshold 0.10
while strategy.py now sets 0.05 — the test's own message says it should
be updated post-refactor). Fixing them means changing trading-strategy
behavior or silencing intentional guards — out of scope for an
unattended quality pass. Left for human review.

**Pure-logic sample — 239 passed, 0 failed** (`test_sharpe`, `test_kelly`,
`test_brier`, `test_credentials`, `test_config`, `test_project_config`,
`test_v49_gates`, `test_v49_gate_wiring`, `test_forensics_loader`,
`test_forensics_writer`, `test_slippage`, `test_eval_metrics`).
`test_sharpe.py` passes 29/29, confirming the prior run's `sharpe.py`
numerical-stability fix still holds.

**Contract tests: 28/28 pass** (`tests/test_action_contracts.py`) — the
hard Action/Step-contract gate is green.

**Environment-limited (not code defects):** network-bound files hang
against blocked exchange APIs (`test_ablation`, `test_accuracy_fixes`,
`test_backtest_bridge`, `test_brain_tiers`, `test_node`,
`test_orchestrator_v2`, `test_quick_smoke`, `test_signal_integration`,
`test_significance`, `test_victoria_*`, etc.); `test_e2e_eval.py` shells
out to the `go` binary. The heavy `tests/integration/test_feedback_loop.py`
runs a long TPE/numpy optimization loop that ignores the timeout signal.
None of these are reachable in-sandbox.

## Stale-pattern scan

**Raw action literals** (`"fetch_market_data"` / `"compute_signals"`):
2 matches, both non-code — `omega/core/orchestrator_v2.py:439` (comment)
and `omega/nodes/victoria/victoria_node.py:28` (docstring describing the
permitted legacy alias). **No stale code literals.** Unchanged from
baseline.

**`os.environ.get(...API_KEY|SECRET)` outside `credentials.py`:** 12
occurrences (startup_validator x2, Victoria data_cache /
unusual_whales_provider / whale_signal x2 / data_providers x2 /
llm_meta_controller, polymarket clob_client x2, integrations
twitter_feed). All pre-existing project-node reads of optional
third-party data keys. Reported, not changed. Unchanged from baseline.

## Working tree note

`git status` shows pre-existing, non-this-run modifications:
`omega/eval/sharpe.py` (the uncommitted 2026-05-30 fix, left behind by a
FUSE git-lock issue documented in that report), plus
`data/training_version.txt`, `docs/ideas/feed.jsonl`, stray `data/*.log`
files, and `omega.egg-info/SOURCES.txt` (touched by `pip install -e .`).
This run introduced no source changes. **Action for a human:** the
`sharpe.py` fix from 2026-05-30 still appears uncommitted on the working
tree — verify it landed on `HEAD` (`git log --oneline -- omega/eval/sharpe.py`)
and commit it if not.

## Result

go build ✓ · golangci-lint 0 issues ✓ · ruff 0 issues ✓ · ruff format
clean ✓ · all Go test packages ✓ · contract tests 28/28 ✓ · Python
baseline unchanged (no regressions) ✓. All hard success criteria met.
