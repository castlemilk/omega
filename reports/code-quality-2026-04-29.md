# Omega Code Quality Review — 2026-04-29

Automated run of the `omega-code-quality-review` scheduled task. The user
was not present, so no fixes were committed. This report enumerates findings.

Repo state: HEAD `f2cff01 feat(victoria): V148 best-of-phases —
meta_learner_exit_only + continuous_sizing` on `main`. Working tree has
**1,421 modified/untracked entries** — heavy WIP — so any auto-fix-and-commit
step would have entangled automated changes with in-flight work. Nothing
was committed.

## Summary

| Check | Result |
|-------|--------|
| `go build ./...` | PASS (0 errors) |
| `go vet ./...` | PASS (0 errors) |
| `golangci-lint run ./...` | PASS (0 issues) |
| `go test ./... -short -count=1` | PASS (all packages) |
| `ruff check omega/` | PASS (0 issues) |
| `ruff format --check omega/` | PASS (252 files already formatted) |
| `mypy omega/core/ --ignore-missing-imports` | 239 pre-existing errors across 28 files (unchanged from 2026-04-27) |
| `pytest tests/test_action_contracts.py` | PASS (28/28) |
| `pytest tests/` (full suite) | Could not be run cleanly in sandbox — see notes |

**Result:** all required success criteria pass. No automated fixes were
needed for ruff or formatting.

## Go quality

`go build`, `go vet`, `golangci-lint`, and `go test ./... -short` all clean.
Required toolchain: Go 1.25 (per `go.mod`) + golangci-lint v2.5 (the repo's
`.golangci.yml` is v2-schema). Both were provisioned in the sandbox for
this run.

`go test ./... -short -count=1` — all 26 test packages report `ok`. The
flaky `internal/framework.TestConfig_HotReload` flagged on 2026-04-27 did
not reproduce on this run.

## Python quality

`ruff check` and `ruff format --check` are both clean — no automated fixes
needed.

### mypy on `omega/core/` (with project follow-imports)

239 errors in 28 files — **identical count to the 2026-04-27 baseline**.
Distribution by file (top offenders):

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
| `omega/nodes/victoria/llm_meta_controller.py` | 3 |
| `omega/nodes/victoria/signals/yield_curve.py` | 3 |
| `omega/nodes/victoria/signals/geopolitical.py` | 3 |
| `omega/nodes/victoria/signals/dxy_signal.py` | 3 |
| (others, 1–2 each) | rest |

Almost all errors are in the Victoria project module (which `omega/core/`
follows via imports), not in `omega/core/` itself. `pyproject.toml` already
runs mypy in strict mode — these errors are pre-existing and would need a
deliberate refactor pass per file. They were **not auto-fixed** because:

- 169 errors in `features.py` alone implies a structural typing change
  (likely missing pandas/numpy stubs or untyped dict-of-arrays returns),
  not drive-by edits.
- The error count is unchanged from the previous successful baseline,
  meaning no new typing regressions were introduced by recent commits.
- Working-tree has unstaged changes across 10+ Victoria files, so any
  automated mypy fix would mix with in-flight work.

### Contract tests

`pytest tests/test_action_contracts.py -q` → **28 passed, 0 failed**. The
action/step routing contract is intact. No raw string literals of action
names were detected outside `omega/core/actions.py`.

### Full test suite

The sandbox runs Python 3.10 by default; the codebase requires Python 3.11+
(uses `datetime.UTC`, introduced in 3.11). A 3.11 venv with `numpy`,
`scipy`, `pandas`, `psycopg`, `betterproto`, `pyyaml`, `requests`,
`aiohttp`, `websockets`, and `pyarrow` was provisioned for this run. Most
unit tests pass against that environment.

A clean full-suite `pytest tests/ -q --timeout=120` could not be completed
in-sandbox in the available time budget — 2,730 tests collected, many of
which exercise paths that require Postgres/SQLite migrations,
exchange-network access, or the host `claude` LLM CLI shell. A representative
sample (`test_action_contracts.py`, `test_node.py`, `test_node_memory.py`,
`test_node_registry.py`, `test_wavelet_signal.py`, `test_signal_adapter.py`,
`test_signal_integrity.py`, `test_signal_retirement.py`,
`test_signals_advanced.py` — 229 tests) was run, with the following
result: **226 passed, 3 failed.**

#### Test failures: env-dependent, not regressions

`tests/test_node_memory.py::TestVictoriaNodeReflectNoBrain`:
- `test_high_quality_lesson`
- `test_low_quality_lesson`
- `test_multiple_cycles_stored`

Root cause: these tests assume the Victoria node's reflection path will
take the **rule-based fallback** (no LLM brain) and assert specific
keywords (`"weak"`, `"skip"`, `"high quality"`, etc.) appear in the
returned lesson string. In `victoria_node.reflect_on_cycle`
(omega/nodes/victoria/victoria_node.py:740-810) the LLM gate is:

```python
brain = self.brain  # NoBrain by default
if brain is not None and brain.is_available() and not isinstance(brain, type):
    raw = brain.consult(prompt, tier=ModelTier.QUICK)
    ...
```

In the sandbox, `brain.is_available()` returns True because the `claude`
CLI is on the user's real machine (the test was authored against a host
where the CLI exists). The CLI subprocess hangs/errors, and the brain
returns a non-empty fallback like *"Insufficient signal strength and
coverage prevent reliable trading decisions; more data needed."* — which
doesn't contain the keywords the tests expect.

This is **environmental**, not a code regression: the tests are not
genuinely "no-brain" tests — they only short-circuit when
`brain.is_available()` returns False. On a developer machine without
`claude` installed (or with the CLI flag turned off) they pass; in any
environment where `claude` is partially installed but unable to respond,
they fail with this exact symptom. **Recommended (not applied)**: harden
the test fixture by stubbing `self.node.brain = None` (or a dummy whose
`is_available()` returns False) so the assertions actually exercise the
rule-based fallback they're documenting.

No regressions introduced by uncommitted Victoria changes — the failures
reproduce on clean HEAD with the same env.

## Stale code patterns (per task spec)

### Raw string action literals
```
grep -rn '"fetch_market_data"\|"compute_signals"' omega/ \
  | grep -v actions.py | grep -v NodeAction
```
Result: **2 hits, both in comments/docstrings** (orchestrator_v2.py:439
explanatory comment; victoria_node.py:28 module docstring listing the
action names). No live code uses raw literals — all dispatch goes through
`NodeAction` enum.

### `os.environ.get` for credentials
```
grep -rn 'os.environ.get.*API_KEY\|os.environ.get.*SECRET' omega/ \
  | grep -v credentials.py
```
Result: **12 hits** across 9 files. These are **pre-existing** call sites
that bypass `omega.core.credentials.CredentialStore`:

| File | Line | Var |
|------|------|-----|
| `omega/integrations/twitter_feed.py` | 294 | `SN13_API_KEY` |
| `omega/nodes/polymarket/clob_client.py` | 236, 237 | `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET` |
| `omega/core/startup_validator.py` | 271, 275 | `ANTHROPIC_API_KEY`, `COINGECKO_API_KEY`, etc. |
| `omega/nodes/victoria/llm_meta_controller.py` | 405 | `ANTHROPIC_API_KEY` |
| `omega/nodes/victoria/data_cache.py` | 104 | `FRED_API_KEY` |
| `omega/nodes/victoria/whale_signal.py` | 375, 391 | `WHALE_ALERT_API_KEY`, `COINGLASS_API_KEY` |
| `omega/nodes/victoria/unusual_whales_provider.py` | 45 | `UW_API_KEY` |
| `omega/nodes/victoria/data_providers.py` | 37, 933 | `CG_API_KEY`, `COINBASE_API_KEY` |

**Recommended (not applied)**: replace each with
`credentials.get("VAR_NAME")`. The mechanical refactor is one-line per
site, but startup_validator.py:271 specifically *expects* to read raw env
state — so the migration needs review per call site, not a blanket sed.
This is the same finding as 2026-04-27 — no progress since.

## What was fixed

Nothing. No automated fixes were warranted:

- ruff: 0 issues to fix.
- ruff format: 0 files to reformat.
- golangci-lint: 0 issues.
- Go build/vet/test: clean.
- mypy: 239 errors that require structural refactoring, not drive-by
  fixes — and the WIP working tree (1,421 entries) makes any commit
  risky.

## Recommended follow-up

1. **Harden `TestVictoriaNodeReflectNoBrain`** to actually run without a
   brain — set `self.node.brain = None` in `setup_method`, or assert
   `is_available()` is False before exercising the fallback path. This
   removes a recurring sandbox-only failure that masks any real
   regression in the fallback lesson generator.
2. **Migrate the 12 stale `os.environ.get` credential reads** to
   `omega.core.credentials.credentials.get(...)`. Mechanical, one-line
   per site, with light review at startup_validator.py.
3. **Tackle `omega/nodes/victoria/features.py`** mypy errors as a focused
   pass — 169 of the 239 errors live here. Adding `from __future__ import
   annotations` plus typed return signatures on the dict-of-arrays helpers
   should knock most of these out.
4. **Reduce working-tree noise** — 1,421 entries (largely autogenerated
   `data/`, `__pycache__/`, and protobuf artifacts) make automated
   commits unsafe. Either commit/discard the in-flight Victoria work or
   add the autogenerated paths to `.gitignore`.
