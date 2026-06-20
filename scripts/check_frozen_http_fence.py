#!/usr/bin/env python3
"""V227 observability delta — non-urllib HTTP frozen-fence static tripwire.

Fails (exit 1) if any Victoria signal module imports a non-urllib HTTP client
(``yfinance`` / ``requests`` / ``httpx`` / ``curl_cffi`` / ``aiohttp``) but its
``compute`` method does NOT carry an ``OMEGA_FROZEN_CACHE`` freeze fence.

Why this exists
---------------
The V215 frozen-backtest HTTP guard patches
``urllib.request.OpenerDirector.open`` — airtight for urllib, which the guard's
own comment asserted was "the only HTTP mechanism in the Victoria layer". That
assertion was FALSE: ``signals/spy_signal.py`` and ``signals/vix_signal.py`` use
``yfinance``, which fetches via ``curl_cffi`` (and ``requests``) — neither of
which routes through urllib. So in a frozen backtest those signals silently hit
LIVE Yahoo Finance and returned wall-clock-dependent data.

That was the V226 recent-OFF determinism FAIL ($1,621.99 spread): same-seed
replicates run ~40 min apart fetched different live SPY momentum, flapping
``spy_signal`` in/out of the per-ticker composite (cycle-83 NEARUSDT:
-0.1833 present in r1, absent in r2) → conviction crossed threshold → NEARUSDT
entry cycle 95↔93. The V215 urllib guard's HTTP-leak log was blind to it (zero
yahoo hosts logged) precisely because curl_cffi bypasses urllib.

The fix is a per-signal ``if os.environ.get("OMEGA_FROZEN_CACHE") == "1":
return 0.0`` fence (curl_cffi can't be patched the way urllib was). This checker
makes the *absence* of that fence a loud preflight failure for the whole class:
any future signal that pulls a non-urllib HTTP client must fence frozen mode.

It is AST-based so it never false-positives on the client name inside a comment
or docstring — only real ``import`` statements are flagged.

Usage
-----
    python3 scripts/check_frozen_http_fence.py   # exit 0 clean, 1 on violation

Wired as a preflight gate in ``scripts/check_determinism.sh``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directory whose signal modules may pull live market data.
SIGNALS_DIR = ROOT / "omega/nodes/victoria/signals"

# HTTP clients that bypass the V215 urllib OpenerDirector.open guard.
NON_URLLIB_HTTP = {"yfinance", "requests", "httpx", "curl_cffi", "aiohttp"}

FENCE_MARKER = "OMEGA_FROZEN_CACHE"


def _imports_non_urllib_http(tree: ast.AST) -> set[str]:
    """Return the set of non-urllib HTTP clients imported by the module."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in NON_URLLIB_HTTP:
                    found.add(root)
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in NON_URLLIB_HTTP:
                found.add(root)
    return found


def _has_frozen_fence(src: str) -> bool:
    """True if the module references the OMEGA_FROZEN_CACHE freeze fence."""
    return FENCE_MARKER in src


def main() -> int:
    if not SIGNALS_DIR.exists():
        print(f"  skip (absent): {SIGNALS_DIR.relative_to(ROOT)}")
        print("PASS: signals dir absent — nothing to check.")
        return 0

    total = 0
    scanned = 0
    for p in sorted(SIGNALS_DIR.glob("*.py")):
        if p.name.startswith("__"):
            continue
        src = p.read_text()
        tree = ast.parse(src, filename=str(p))
        clients = _imports_non_urllib_http(tree)
        if not clients:
            continue
        scanned += 1
        rel = p.relative_to(ROOT)
        if _has_frozen_fence(src):
            print(f"  ok: {rel} (HTTP via {sorted(clients)}, frozen-fenced)")
        else:
            print(
                f"VIOLATION {rel}: imports non-urllib HTTP {sorted(clients)} "
                f"but has no `{FENCE_MARKER}` freeze fence"
            )
            total += 1

    print(f"check_frozen_http_fence: scanned {scanned} HTTP signal module(s), {total} violation(s)")
    if total:
        print(
            "FAIL: a signal module pulls a non-urllib HTTP client (curl_cffi/"
            "requests/etc.) that bypasses the V215 urllib guard, with no "
            "OMEGA_FROZEN_CACHE fence. In frozen backtest it hits LIVE data and "
            "leaks wall-clock non-determinism (V226 spy_signal channel). Add "
            "`if os.environ.get(\"OMEGA_FROZEN_CACHE\") == \"1\": return 0.0` at "
            "the top of compute()."
        )
        return 1
    print("PASS: every non-urllib-HTTP signal module is frozen-fenced.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
