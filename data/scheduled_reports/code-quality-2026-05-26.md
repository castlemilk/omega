# Omega Code Quality Review — 2026-05-26

**Status: BLOCKED — sandbox infrastructure failure**

## Blocker

The Cowork sandboxed shell (`mcp__workspace__bash`) failed for every command
attempted during this run with the following error:

```
bash failed on resume, create, and re-resume.
resume: RPC error: ensure user: useradd failed: fork/exec /usr/sbin/useradd:
input/output error
```

This is an infrastructure-level failure (the underlying Linux VM cannot create
the workspace user) — it cannot be worked around from inside the session.
Because of this, none of the dynamic checks in the task could run:

- `go build ./...`
- `golangci-lint run ./...`
- `go test ./... -short -count=1`
- `ruff check omega/`
- `ruff format --check omega/`
- `mypy omega/core/ --ignore-missing-imports`
- `python3 -m pytest tests/test_action_contracts.py`
- `python3 -m pytest tests/ -q --timeout=120`

No fixes were applied and no commit was made. Re-run this task once the
sandbox is healthy.

## Static analysis (file tools only)

These checks did not need the shell, so they were completed.

### 1. Raw action-string literals

```
grep '"fetch_market_data"|"compute_signals"' under omega/, excluding actions.py
```

Result: **no offending raw literals**. The only matches are:

- `omega/core/actions.py:41-42` — the `NodeAction` enum definitions
  themselves (expected; excluded per task instructions).
- `omega/core/orchestrator_v2.py:439` — inside a code comment describing
  the resolution mapping.
- `omega/nodes/victoria/victoria_node.py:28` — inside a docstring listing
  legacy action aliases.

No runtime code constructs `NodeInput` with raw `"fetch_market_data"` or
`"compute_signals"` strings — the contract is intact.

### 2. `os.environ.get` for API keys / secrets

The task asked for callers that should be using `omega.core.credentials.credentials.get(...)`
instead of `os.environ.get(...)` directly. Matches found (10):

| File | Line | Variable |
|---|---|---|
| omega/integrations/twitter_feed.py | 294 | SN13_API_KEY |
| omega/nodes/polymarket/clob_client.py | 236 | POLYMARKET_API_KEY |
| omega/nodes/polymarket/clob_client.py | 237 | POLYMARKET_API_SECRET |
| omega/nodes/victoria/llm_meta_controller.py | 405 | ANTHROPIC_API_KEY |
| omega/core/startup_validator.py | 271 | ANTHROPIC_API_KEY / CLAUDE_API_KEY |
| omega/core/startup_validator.py | 275 | COINGECKO_API_KEY / CG_API_KEY |
| omega/nodes/victoria/data_providers.py | 37 | CG_API_KEY |
| omega/nodes/victoria/data_providers.py | 933 | COINBASE_API_KEY |
| omega/nodes/victoria/whale_signal.py | 375 | WHALE_ALERT_API_KEY |
| omega/nodes/victoria/whale_signal.py | 391 | COINGLASS_API_KEY |
| omega/nodes/victoria/data_cache.py | 104 | FRED_API_KEY |
| omega/nodes/victoria/unusual_whales_provider.py | 45 | UW_API_KEY |

`omega/core/credentials.py` exists and provides
`credentials.get(name) -> str | None` with env + `.env` fallback, plus a
registration mechanism. The matches above are not bugs per se, but they
bypass that registry, which means:

- Missing credentials aren't centrally surfaced in startup diagnostics.
- `startup_validator.py` itself reads keys directly (lines 271, 275) — a
  natural exception, but worth confirming intentional.
- The remaining 8 call sites in `nodes/victoria/*`, `nodes/polymarket/*`,
  and `integrations/twitter_feed.py` are reasonable candidates for
  migration to `credentials.get(...)`.

No fix was applied automatically because (a) the dynamic test suite cannot
be run to verify regressions, and (b) the task description allows reporting
when in doubt.

## What still needs to happen on the next healthy run

1. Re-run the full task. If the shell is healthy, all six numbered steps
   from the SKILL.md run normally.
2. If the credentials migration above is desired, it should be done in a
   single PR with `make py-test` green and the contract tests passing.
