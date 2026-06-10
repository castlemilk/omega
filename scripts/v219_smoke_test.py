#!/usr/bin/env python3
"""
V219 — smoke test for the frozen-cache substrate tripwires.

Validates `_v219_substrate_preflight` in run_training.py against a healthy
substrate and four corruption scenarios, each operating on a TEMP COPY of the
data caches (the committed files are never touched). Confirms:

  1. healthy substrate           -> PASS (no exit)
  2. manifest md5 mismatch        -> exit 1  (any byte drift caught)
  3. all-__failed__ macro cache   -> exit 1  "MACRO INERT"
  4. empty funding_rate_cache     -> exit 1  "FUNDING INERT"
  5. missing manifest             -> exit 1

Run:
    PYTHONHASHSEED=42 python3 scripts/v219_smoke_test.py

(PYTHONHASHSEED=42 + no --frozen-cache in argv keeps run_training's import-time
re-exec from firing.)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

os.environ["OMEGA_FROZEN_CACHE"] = "1"  # activate the preflight (checked at call time)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import omega.nodes.victoria.data_cache as dc  # noqa: E402
import scripts.run_training as rt  # noqa: E402

log = logging.getLogger("v219_smoke")
logging.basicConfig(level=logging.INFO, format="%(message)s")

_FILES = [
    "data/macro_cache.db",
    "data/frozen_funding_cache.json",
    "data/frozen_advanced_signals.json",
    "data/.cache_manifest.json",
]


def _md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _rebuild_manifest(tmp: Path) -> None:
    """Recompute .cache_manifest.json for the (possibly corrupted) tmp copy +
    re-export funding json so the manifest matches — simulates someone freezing
    and committing an inert cache (so checks 3/4 are reached past the md5 gate)."""
    db = tmp / "data" / "macro_cache.db"
    conn = sqlite3.connect(str(db))
    rows = conn.execute("SELECT symbol, rate, fetched_at FROM funding_rate_cache "
                        "ORDER BY symbol").fetchall()
    conn.close()
    payload = {"_note": "smoke", "rates": {r[0]: {"rate": r[1], "fetched_at": r[2]} for r in rows}}
    (tmp / "data" / "frozen_funding_cache.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n")
    files = {rel: _md5(tmp / rel) for rel in _FILES if rel != "data/.cache_manifest.json"}
    (tmp / "data" / ".cache_manifest.json").write_text(
        json.dumps({"_note": "smoke", "files": files}, indent=2, sort_keys=True) + "\n")


def _setup_tmp() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="v219_smoke_"))
    (tmp / "data").mkdir()
    for rel in _FILES:
        shutil.copy2(ROOT / rel, tmp / rel)
    return tmp


def _run_preflight() -> tuple[str, object]:
    try:
        rt._v219_substrate_preflight(log)
        return ("pass", None)
    except SystemExit as e:
        return ("exit", e.code)


def _patch(tmp: Path | None) -> None:
    """Point run_training + data_cache at tmp (or restore reals when tmp is None)."""
    if tmp is None:
        rt.ROOT = ROOT
        rt.DATA_DIR = ROOT / "data"
        dc._default_db_path = _ORIG_DEFAULT_DB
    else:
        rt.ROOT = tmp
        rt.DATA_DIR = tmp / "data"
        dc._default_db_path = lambda: tmp / "data" / "macro_cache.db"


_ORIG_DEFAULT_DB = dc._default_db_path
results: list[tuple[str, bool, str]] = []


def check(name: str, got: tuple[str, object], want_pass: bool) -> None:
    is_pass = got[0] == "pass"
    ok = is_pass == want_pass
    detail = "PASS" if is_pass else f"exit({got[1]})"
    results.append((name, ok, detail))
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}: got {detail}, "
          f"expected {'PASS' if want_pass else 'exit(1)'}")


def main() -> int:
    # 1. healthy (real committed substrate)
    print("Scenario 1: healthy substrate (real files)")
    _patch(None)
    check("healthy", _run_preflight(), want_pass=True)

    # 2. manifest mismatch — corrupt one byte, keep old manifest
    print("Scenario 2: manifest md5 mismatch")
    tmp = _setup_tmp()
    with open(tmp / "data" / "macro_cache.db", "ab") as f:
        f.write(b"\x00")  # append a byte -> md5 drifts, manifest unchanged
    _patch(tmp)
    check("manifest_mismatch", _run_preflight(), want_pass=False)
    shutil.rmtree(tmp, ignore_errors=True)

    # 3. MACRO INERT — all series __failed__, manifest rebuilt to match
    print("Scenario 3: all-__failed__ macro cache (MACRO INERT)")
    tmp = _setup_tmp()
    conn = sqlite3.connect(str(tmp / "data" / "macro_cache.db"))
    conn.execute("DELETE FROM macro_cache")
    for s in dc.MACRO_SERIES:
        conn.execute("INSERT INTO macro_cache (series_id, date, value, fetched_at) "
                     "VALUES (?, '__failed__', 0.0, '2026-06-09T00:00:00+00:00')", (s,))
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.commit()
    conn.close()
    _rebuild_manifest(tmp)
    _patch(tmp)
    check("macro_inert", _run_preflight(), want_pass=False)
    _patch(None)
    shutil.rmtree(tmp, ignore_errors=True)

    # 4. FUNDING INERT — empty funding table, manifest rebuilt to match
    print("Scenario 4: empty funding_rate_cache (FUNDING INERT)")
    tmp = _setup_tmp()
    conn = sqlite3.connect(str(tmp / "data" / "macro_cache.db"))
    conn.execute("DELETE FROM funding_rate_cache")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.commit()
    conn.close()
    _rebuild_manifest(tmp)
    _patch(tmp)
    check("funding_inert", _run_preflight(), want_pass=False)
    _patch(None)
    shutil.rmtree(tmp, ignore_errors=True)

    # 5. missing manifest
    print("Scenario 5: missing manifest")
    tmp = _setup_tmp()
    (tmp / "data" / ".cache_manifest.json").unlink()
    _patch(tmp)
    check("missing_manifest", _run_preflight(), want_pass=False)
    shutil.rmtree(tmp, ignore_errors=True)

    _patch(None)
    n_fail = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{'='*50}")
    print(f"V219 smoke test: {len(results) - n_fail}/{len(results)} scenarios OK")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
