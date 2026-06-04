# Omega Code Quality Review — 2026-06-03

Automated scheduled run. Summary up front: the **Python lint/format/contract checks pass cleanly** (one file auto-formatted), but the **Go toolchain checks could not be executed** and the **commit could not be written**, both due to hard sandbox-environment limits described below. Type-check and full-suite results carry environment caveats.

## Headline results

| Check | Result |
|---|---|
| `go build ./...` | **Blocked** — could not run (toolchain/disk, see below) |
| `golangci-lint run ./...` | **Blocked** — could not run |
| `go test ./... -short` | **Blocked** — could not run |
| `ruff check omega/` | **Pass** — 0 issues |
| `ruff format omega/` | **1 file reformatted** (applied) |
| `mypy omega/core/` | 240 pre-existing errors (not regressions; not auto-fixed) |
| Contract tests (`test_action_contracts.py`) | **Pass** — 28/28 |
| Full `pytest tests/` | 2730 collected; mixed (see caveats) |
| Commit of fixes | **Blocked** — `.git/index.lock` not removable |

## What was fixed

`ruff format` reformatted one file, **`omega/nodes/victoria/strategy.py`** — a single line-length wrap of a `sorted(...)` call (lines ~3022–3024), whitespace-only, no behavioral change. The change is saved in the working tree. `ruff check omega/` reported zero lint issues, so nothing else needed fixing on the Python lint side.

## Environment blockers (not code problems)

The sandbox this scheduled task runs in does **not** have the project's dev toolchain preinstalled, and its disk is effectively exhausted:

- The shared `/` filesystem sat at ~91% on entry, and roughly **720 MB is locked in orphaned Go module/build caches owned by another user** (`nobody`, from a prior session) that I have no permission to delete.
- I bootstrapped Python 3.11.9, ruff, mypy, pytest, and even the Go 1.25 toolchain from scratch. The **Go build downloaded its module graph but ran the disk to 100% before linking**, and `golangci-lint` (which must compile the full package set) needs more headroom still. With only ~90–440 MB reclaimable, the Go layer cannot be built or linted here. This is purely a resource limit — it says nothing about whether the Go code is healthy.
- The sandbox's default Python was 3.10; the project requires 3.11+ (`from datetime import UTC`). I installed a standalone 3.11 so the Python results below are valid, but note they still differ from CI in optional-dependency coverage (no scipy/pywt/OTel installed).

## Type check (`mypy omega/core/ --ignore-missing-imports`, Python 3.11)

240 errors across 25 files. These are a **pre-existing baseline, not regressions** — the only file this run touched was a whitespace reformat that cannot introduce type errors. The distribution is dominated by `[arg-type]` (175), with `[no-any-return]` (17), `[attr-defined]` (12), and `[assignment]` (11) trailing. A large share of the `arg-type` volume is consistent with environment skew (missing typed optional deps, strict settings) rather than genuine defects.

I deliberately did **not** auto-rewrite these. Mass-editing 240 strict-mode errors across 25 files autonomously would be high-risk, many reflect intentional dynamic patterns (optional imports set to `None`, dynamic node attribute assignment), and mypy is not among this task's success criteria. Recommend triaging on a real 3.11 CI environment.

## Full test suite (`pytest tests/`)

2730 tests collected cleanly (no import/collection errors). Exact full totals could not be captured because a handful of tests make **live network calls to exchange APIs and hang**, and the sandbox hard-kills any shell call at 45 s (and kills background processes with their parent). Running in chunks, the large majority pass. A representative ~38-file batch returned **808 passed, 24 failed, 27 skipped, 7 errors**.

Failures sort into two buckets:

- **Environmental (not real defects):** e2e tests fail with `FileNotFoundError` because no Go API server is running; exchange/network tests (`test_ablation`, `test_backtest_bridge`) hang with no connectivity; some paths need Postgres `DATABASE_URL` or optional deps that aren't installed here.
- **Real assertion failures worth a look:** **`tests/test_conviction.py` — 5 failures** around conviction-strength labeling and portfolio weighting, e.g. `assert 'BUY' == 'STRONG_BUY'`, `assert 0 > 0.3`, and `STRONG_BUY` not receiving higher weight than `BUY`. These reproduce under a clean Python 3.11 with numpy present and are independent of the formatting change. Note the working tree already carried uncommitted edits to `omega/eval/sharpe.py` and `data/training_version.txt` before this run; the conviction failures may relate to in-flight strategy work. **Recommend investigating `test_conviction` on the dev machine.**

## Stale-pattern scan

- **Raw action string literals:** the only matches for `"fetch_market_data"` / `"compute_signals"` are in a **comment** (`orchestrator_v2.py:439`) and a **docstring** (`victoria_node.py:28`). No stale literals in executable code — clean.
- **`os.environ.get(...API_KEY/SECRET)` bypassing `credentials.py`:** 13 occurrences, mostly in project nodes — `startup_validator.py` (ANTHROPIC/CLAUDE/COINGECKO/CG), `data_cache.py` (FRED), `unusual_whales_provider.py`, `whale_signal.py` (WHALE_ALERT, COINGLASS), `data_providers.py` (CG, COINBASE), `llm_meta_controller.py` (ANTHROPIC), `polymarket/clob_client.py` (POLYMARKET key+secret), `integrations/twitter_feed.py` (SN13). Reported only — not auto-changed, since rerouting credential loading is behavioral and out of scope for an automated formatting pass.

## Commit status

The fix is in the working tree but **was not committed**. A stale, zero-byte `.git/index.lock` (mine, ~14 min old, no git process running) blocks commits, and the fuse-mounted repo returns **`Operation not permitted`** on `rm`, so I cannot clear it. The earlier presence of another session's path in test output suggests a **concurrent run may hold the lock** — committing mid-flight would be unsafe regardless. To finish: remove `.git/index.lock` manually, then `git add omega/nodes/victoria/strategy.py && git commit -m "chore: automated code quality fixes"`.

## Recommended follow-ups

1. Run Go `build` / `golangci-lint` / `test -short` on the dev machine or a CI runner with the toolchain and adequate disk — they could not be exercised here.
2. Investigate the 5 `test_conviction` failures (STRONG_BUY weighting).
3. Clear the stale `.git/index.lock` and commit the strategy.py formatting fix.
4. Consider provisioning the scheduled-task sandbox with the project toolchain (Go 1.25, ruff, mypy, Python 3.11) and more disk so future automated runs can complete end-to-end.
