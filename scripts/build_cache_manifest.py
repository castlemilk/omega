#!/usr/bin/env python3
"""
V219 — build data/.cache_manifest.json: an md5 manifest of every frozen cache
file the eval depends on, verified at training startup (OMEGA_FROZEN_CACHE=1).

Why: V218 found that V217's "6/6 hermetic" eval was reproducible within a session
but NOT from committed state — it rode an uncommitted macro_cache.db + a
session-specific funding cache. The manifest is the tripwire: at cycle 0 the run
hashes each listed file and aborts if any byte drifted from the committed hash, so
a corrupted/stale/uncommitted substrate can never silently produce a "baseline."

This script also EXPORTS data/frozen_funding_cache.json — a human-readable,
manifest-tracked transparency snapshot of the funding rates that live inside
macro_cache.db's funding_rate_cache table. NOTE: the JSON is NOT an authoritative
read path. The signals read funding from the DB (MacroDataCache.get_funding_rate);
committing macro_cache.db already freezes funding (its read has no date filter, so
it never expires). The JSON exists for transparency + so the manifest has a
distinct funding artifact to verify. Keeping a single DB read path (no parallel
JSON reader) avoids introducing a second, drift-prone source — deliberate, see
V219.md.

Re-run after any deliberate substrate change (repair_macro_cache.py,
freeze_advanced_snapshot.py):
    python3 scripts/build_cache_manifest.py
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MACRO_DB = DATA / "macro_cache.db"
FUNDING_JSON = DATA / "frozen_funding_cache.json"
ADVANCED_JSON = DATA / "frozen_advanced_signals.json"
MANIFEST = DATA / ".cache_manifest.json"

# Files whose md5 is verified at startup. Paths are repo-relative (manifest is
# portable across checkouts).
_FROZEN_FILES = [
    "data/macro_cache.db",
    "data/frozen_funding_cache.json",
    "data/frozen_advanced_signals.json",
    # V277: the determinism harness snapshots this as run state and it is provably
    # STABLE across a run (md5 unchanged over a full 3-cell pass). Asserted.
    "data/omega_victoria_state.db",
]

# V277 — RECORDED but never asserted. check_determinism.sh snapshots these as state
# and run_training.py:179-181 declares them "STABLE/COMMITTED INPUTS", but a probe
# over one 3-cell pass shows every run REWRITES them:
#     data/omega_victoria_memory.db   5e34299... -> b272ad5...
#     data/signal_ic_history.json     a0e52d5... -> 3b9633c...
# (signal_decay.py:82 persists the IC history; the semantic-memory store writes the
# memory DB via run_training.py:314.) Asserting them would abort every run after the
# first — the V219 tripwire firing on its own exhaust. Recording the hash still turns
# an invisible drift into a visible one, which is the value V219 actually delivered.
# See training_log/V277.md §1b.
_VOLATILE_FILES = [
    "data/omega_victoria_memory.db",
    "data/signal_ic_history.json",
]


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _export_funding() -> int:
    """Export funding_rate_cache rows from macro_cache.db to frozen_funding_cache.json."""
    conn = sqlite3.connect(str(MACRO_DB))
    try:
        rows = conn.execute(
            "SELECT symbol, rate, fetched_at FROM funding_rate_cache ORDER BY symbol"
        ).fetchall()
    finally:
        conn.close()
    payload = {
        "_note": (
            "Transparency snapshot of funding_rate_cache in macro_cache.db. "
            "NOT an authoritative read path — signals read funding from the DB "
            "via MacroDataCache.get_funding_rate. See V219.md."
        ),
        "rates": {r[0]: {"rate": r[1], "fetched_at": r[2]} for r in rows},
    }
    # Deterministic serialization (sorted keys) so the md5 is stable.
    FUNDING_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return len(rows)


def main() -> int:
    if not MACRO_DB.exists():
        print(f"FATAL: {MACRO_DB} missing", file=sys.stderr)
        return 1

    n_funding = _export_funding()
    print(f"Exported {n_funding} funding rows -> {FUNDING_JSON.relative_to(ROOT)}")
    if n_funding == 0:
        print("WARNING: funding_rate_cache is EMPTY — the funding tripwire will fire.",
              file=sys.stderr)

    manifest = {
        "_note": "md5 manifest of frozen eval caches; verified at startup when "
                 "OMEGA_FROZEN_CACHE=1. Mismatch => abort the run. "
                 "Rebuild with scripts/build_cache_manifest.py.",
        "_volatile_note": "volatile_files are RECORDED, never asserted: the run "
                          "rewrites them (V277 §1b). Drift is reported as a WARNING "
                          "at startup, never an abort.",
        "files": {},
        "volatile_files": {},
    }
    for rel in _FROZEN_FILES:
        p = ROOT / rel
        if not p.exists():
            print(f"FATAL: frozen file missing: {rel}", file=sys.stderr)
            return 1
        manifest["files"][rel] = _md5(p)

    for rel in _VOLATILE_FILES:
        p = ROOT / rel
        if not p.exists():
            print(f"WARNING: volatile file missing (recorded as absent): {rel}",
                  file=sys.stderr)
            continue
        manifest["volatile_files"][rel] = _md5(p)

    # Stamp generated_at LAST and outside the verified set (the manifest hashes
    # the listed files, never itself).
    manifest["generated_at"] = datetime.now(UTC).isoformat()
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print(f"\nWrote {MANIFEST.relative_to(ROOT)}:")
    for rel, md5 in sorted(manifest["files"].items()):
        print(f"  {md5}  {rel}   [asserted]")
    for rel, md5 in sorted(manifest["volatile_files"].items()):
        print(f"  {md5}  {rel}   [recorded, not asserted]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
