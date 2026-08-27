"""V277: the substrate manifest covers the state files the harness snapshots.

`scripts/check_determinism.sh` snapshots four files as a run's state. Before V277 the
V219 manifest asserted exactly one of them (`macro_cache.db`), so the tripwire that
caught the `cfb4a43d` drift was blind to the rest -- and that same commit mutated
`omega_victoria_memory.db` with nothing reporting it.

V277 asserts what is provably stable and RECORDS what is provably volatile. These tests
pin that split, because getting it backwards is a self-inflicted outage: two of the
files are rewritten by every run, and asserting them would abort every run after the
first (V277.md §1b).
"""

from __future__ import annotations

import json
import pathlib

_REPO = pathlib.Path(__file__).resolve().parents[1]
_MANIFEST = _REPO / "data" / ".cache_manifest.json"


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text())


def test_state_db_is_asserted() -> None:
    """`omega_victoria_state.db` is snapshotted as run state and is stable -> asserted.

    Stability was measured, not assumed: md5 before/after a full 3-cell pass is
    unchanged (V277.md §1b).
    """
    files = _manifest()["files"]
    assert "data/omega_victoria_state.db" in files, (
        "omega_victoria_state.db dropped out of the asserted set; the V277 blind spot "
        "has reopened. See training_log/V277.md §2."
    )


def test_run_mutated_files_are_never_asserted() -> None:
    """The footgun guard -- the one that makes V277 safe rather than an outage.

    `omega_victoria_memory.db` and `signal_ic_history.json` are rewritten by every run
    (`signal_decay.py:82`; the semantic-memory store via `run_training.py:314`).
    Promoting either into `files` makes the startup tripwire abort on its own exhaust:
    the first run would pass and every subsequent one would fail until someone
    rebuilt the manifest by hand.
    """
    m = _manifest()
    volatile = {"data/omega_victoria_memory.db", "data/signal_ic_history.json"}

    wrongly_asserted = sorted(volatile & set(m["files"]))
    assert wrongly_asserted == [], (
        f"run-mutated files promoted to the ASSERTED set: {wrongly_asserted}. Every run "
        "after the first would abort at the cache-manifest preflight. They belong in "
        "volatile_files. See training_log/V277.md §1b."
    )

    missing = sorted(volatile - set(m.get("volatile_files") or {}))
    assert missing == [], (
        f"volatile state files not recorded at all: {missing}. Recording is what makes "
        "their drift visible instead of silent."
    )


def test_asserted_and_volatile_sets_are_disjoint() -> None:
    """A file in both sets would be asserted in practice -- the abort wins."""
    m = _manifest()
    overlap = sorted(set(m["files"]) & set(m.get("volatile_files") or {}))
    assert overlap == [], f"file listed as both asserted and volatile: {overlap}"


def test_every_manifest_entry_exists_and_matches() -> None:
    """Both sets name real files, and the committed hashes are the committed bytes.

    Volatile entries are checked too: at a clean checkout they must match, since the
    recorded value IS the committed state. (After a run they legitimately drift -- that
    is the point of the split -- so this test asserts the repo's committed state, which
    is what CI and a fresh clone see.)
    """
    import hashlib

    m = _manifest()
    problems: list[str] = []
    for section in ("files", "volatile_files"):
        for rel, want in sorted((m.get(section) or {}).items()):
            path = _REPO / rel
            if not path.exists():
                problems.append(f"{section}:{rel} MISSING")
                continue
            h = hashlib.md5()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            if h.hexdigest() != want:
                problems.append(f"{section}:{rel} {h.hexdigest()} != {want}")

    assert problems == [], (
        f"manifest does not describe the working tree: {problems}. If this is a dirty "
        "tree after a training run, the volatile_files entries are expected to drift -- "
        "restore with `git restore --source=HEAD --worktree data/` before trusting it."
    )
