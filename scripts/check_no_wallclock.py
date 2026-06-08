#!/usr/bin/env python3
"""V216 observability delta #8 — sizing-layer wall-clock static tripwire.

Fails (exit 1) if any sizing-path module reads real wall-clock
(``datetime.now`` / ``datetime.utcnow`` / ``time.time``) without an explicit
``# wallclock-ok: <reason>`` annotation on the call's source line(s).

Why this exists
---------------
The V215 determinism FAIL was a wall-clock read in
``core/risk_manager.py``'s ``time_risk_multiplier`` (and the ``strategy.py`` damp
window) that no instrument caught until a hand-written 4-replicate diff localized
it — after V207–V214 had already burned iterations chasing wall-clock channels.
This checker would have failed at *preflight*: any new unguarded wall-clock read
in the sizing path is rejected loudly before a run starts.

It is AST-based (not grep) so it never false-positives on the string
``datetime.now`` inside comments or docstrings — only real call expressions are
flagged. Each legitimate call (the ``now is None`` live fallback in
``time_risk_multiplier``; the V216 ``_bar_now or datetime.now(UTC)`` fences; pure
trace/metadata timestamps) carries a ``# wallclock-ok: <reason>`` annotation, so
the diff between "fenced" and "leaking" is explicit in the source.

Usage
-----
    python3 scripts/check_no_wallclock.py            # exit 0 clean, 1 on violation

Wired as a preflight gate in ``scripts/check_determinism.sh``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Sizing-path modules whose wall-clock reads can leak into trade sizing/selection
# and break frozen-backtest determinism. (omega/nodes/victoria/risk_manager.py is
# listed for forward-compat — it does not currently exist and is skipped if absent.)
MODULES = [
    "omega/nodes/victoria/strategy.py",
    "omega/nodes/victoria/risk_manager.py",
    "omega/core/risk_manager.py",
]

ANNOTATION = "# wallclock-ok"


def _leaf_name(node: ast.expr) -> str | None:
    """Return the leaf identifier of a Name or Attribute value chain."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_wallclock_call(call: ast.Call) -> bool:
    """True if `call` is datetime.now()/datetime.utcnow()/time.time()."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    base_leaf = _leaf_name(func.value)
    if func.attr in {"now", "utcnow"}:
        return base_leaf == "datetime"
    if func.attr == "time":
        return base_leaf == "time"
    return False


def _scan(path: Path) -> list[tuple[int, str]]:
    """Return [(lineno, source_line)] of unannotated wall-clock calls."""
    src = path.read_text()
    lines = src.splitlines()
    tree = ast.parse(src, filename=str(path))
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_wallclock_call(node):
            start = node.lineno
            end = getattr(node, "end_lineno", start) or start
            span = "\n".join(lines[start - 1 : end])
            if ANNOTATION in span:
                continue
            violations.append((start, lines[start - 1].strip()))
    return violations


def main() -> int:
    total = 0
    scanned = 0
    for rel in MODULES:
        p = ROOT / rel
        if not p.exists():
            print(f"  skip (absent): {rel}")
            continue
        scanned += 1
        viols = _scan(p)
        if viols:
            for lineno, code in viols:
                print(f"VIOLATION {rel}:{lineno}: unguarded wall-clock read → {code}")
                total += 1
        else:
            print(f"  ok: {rel}")
    print(f"check_no_wallclock: scanned {scanned} module(s), {total} violation(s)")
    if total:
        print(
            "FAIL: a sizing-path module reads real wall-clock without a "
            "`# wallclock-ok: <reason>` annotation. In frozen backtest this leaks "
            "non-determinism into trade sizing (V215 channel). Thread bar-time "
            "(see strategy._backtest_now_ts) or annotate if the read is provably "
            "sizing-independent."
        )
        return 1
    print("PASS: no unguarded wall-clock reads in the sizing path.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
