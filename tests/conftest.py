"""Session-wide test isolation for the frozen substrate.

`data/macro_cache.db` and the Victoria memory DBs are COMMITTED files under
`data/.cache_manifest.json`. Anything that opened them with no explicit path wrote
them in place, so a full `pytest tests/` run dirtied the working tree and
`test_cache_manifest.py` failed afterwards until someone ran `git restore`.

That is worse than having no guard: a check that fires after every test run stops
being read. It cost two `git restore` cycles in one session before the cause was
found, and the guard exists precisely because this file drifted silently once.

Redirecting at the session level rather than per-test is deliberate — relying on
each test to remember is how the leak happened in the first place.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolate_frozen_substrate(tmp_path_factory: pytest.TempPathFactory):
    """Point every cache the suite might open at a throwaway directory."""
    scratch = tmp_path_factory.mktemp("omega-substrate")

    # SEED the scratch copies from the committed originals rather than starting
    # empty. Isolation is about where writes LAND, not about throwing away the
    # reads: an empty macro cache makes every lookup miss and fall through to a
    # live yfinance fetch, which took signal generation from 1.5s to 3.8s and made
    # the suite depend on an external service being up. Copying keeps the cache
    # warm and still leaves the committed file untouched.
    root = Path(__file__).resolve().parents[1]
    for name in ("macro_cache.db", "omega_victoria_memory.db"):
        src = root / "data" / name
        if src.is_file():
            shutil.copy2(src, scratch / name)

    previous = {}
    for var, name in (
        ("OMEGA_MACRO_CACHE_PATH", "macro_cache.db"),
        ("OMEGA_MEMORY_DB_PATH", "omega_victoria_memory.db"),
        ("OMEGA_STATE_DB_PATH", "omega_victoria_state.db"),
    ):
        previous[var] = os.environ.get(var)
        os.environ[var] = str(scratch / name)
    yield scratch
    for var, old in previous.items():
        if old is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = old


def _content_md5(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _asserted_substrate(root: Path) -> list[Path]:
    """The committed cache files the manifest actually asserts.

    Read from `data/.cache_manifest.json` rather than hardcoded, so this guard
    and the thing it protects cannot disagree. `volatile_files` is deliberately
    excluded: the manifest records those and never asserts them, because the run
    is expected to rewrite them (V277 1b). `omega_victoria_memory.db` is one, so
    flagging it here was raising an alarm the manifest itself does not raise.
    """
    manifest = root / "data" / ".cache_manifest.json"
    try:
        entries = json.loads(manifest.read_text())["files"]
    except (OSError, KeyError, ValueError):
        return []
    return [p for rel in entries if (p := root / rel).is_file()]


def pytest_configure(config: pytest.Config) -> None:
    """Record the committed substrate's fingerprint in EVERY process.

    Content md5, not mtime+size. mtime moves for reasons that are not drift —
    a WAL checkpoint that restores identical bytes, or SQLite opening the file
    read-write and touching it — and a guard that fires on those is a guard that
    gets ignored. md5 is also exactly what the manifest asserts, so a report here
    means `test_cache_manifest.py` would fail too.
    """
    root = Path(__file__).resolve().parents[1]
    config._omega_substrate = {  # type: ignore[attr-defined]
        p: _content_md5(p) for p in _asserted_substrate(root)
    }


def pytest_sessionfinish(session, exitstatus):
    """Fail the run if the committed substrate moved.

    A session-scoped FIXTURE was the obvious place for this and is the wrong one:
    under xdist it runs per worker, each worker takes its own baseline, and a
    worker that did not write sees no change — so the drift went unreported while
    it was actually happening. pytest_sessionfinish runs in the controller as well
    as the workers, so the controller sees the whole run's effect.

    The env overrides above only help code that consults them; this catches
    anything that hardcodes the path, which is how both known offenders behaved.
    """
    recorded = getattr(session.config, "_omega_substrate", {})
    moved = [p.name for p, before in recorded.items() if p.is_file() and _content_md5(p) != before]
    if moved:
        # Reported rather than raised: a late raise here can mask the real results.
        session.config.stash  # noqa: B018  (touch, so a bad stash surfaces early)
        print(
            "\n\nSUBSTRATE DRIFT: the test run wrote committed files: "
            + ", ".join(sorted(set(moved)))
            + "\nSomething bypassed OMEGA_MACRO_CACHE_PATH / OMEGA_MEMORY_DB_PATH. "
            "Find it rather than running `git restore` — the manifest guard is only "
            "useful while it means something.\n"
        )
        if exitstatus == 0:
            session.exitstatus = 1
