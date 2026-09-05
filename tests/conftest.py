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

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolate_frozen_substrate(tmp_path_factory: pytest.TempPathFactory):
    """Point every cache the suite might open at a throwaway directory."""
    scratch = tmp_path_factory.mktemp("omega-substrate")
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


@pytest.fixture(scope="session", autouse=True)
def _fail_if_substrate_dirtied(_isolate_frozen_substrate):
    """Catch a leak the redirect above does not cover.

    The env override only helps code that consults it. Anything hardcoding the
    committed path still writes it, and would otherwise be found the same way it
    was last time — by a manifest failure hours later, in a different context.
    """
    root = Path(__file__).resolve().parents[1]
    watched = [
        root / "data" / "macro_cache.db",
        root / "data" / "omega_victoria_memory.db",
    ]
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in watched if p.is_file()}
    yield
    moved = [
        p.name
        for p in watched
        if p.is_file() and before.get(p) and (p.stat().st_mtime_ns, p.stat().st_size) != before[p]
    ]
    if moved:
        pytest.fail(
            "the test run wrote committed substrate: "
            + ", ".join(moved)
            + ". Something is bypassing OMEGA_MACRO_CACHE_PATH — find it rather than "
            "running `git restore`, or the manifest guard goes back to crying wolf."
        )
