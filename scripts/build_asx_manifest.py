#!/usr/bin/env python3
"""Hash manifest for the frozen ASX substrate.

The v3 panel is 128MB — too large to commit, and reproducible in ~15 minutes from
`asx_build_universe.py`. But "reproducible" is not "verified": V296-V304 were all
computed on this substrate, and without a hash there is no way to know whether a
later rebuild produced the same bytes.

So the same trade the campaign already makes for the macro cache (V219/V277): the
DATA is gitignored, the MANIFEST is committed. A rebuild that differs is then a
loud failure rather than a silent one, which is the whole point of a frozen
substrate.

Per-file hashes rather than one aggregate, so a drift names the file that moved.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V3 = ROOT / "data" / "frozen_series" / "asx" / "v3"
OUT = V3.parent / "v3.manifest.json"


def digest(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build() -> dict:
    groups: dict[str, dict] = {}
    for sub in ("shorts", "prices", "universe"):
        d = V3 / sub
        if not d.is_dir():
            continue
        files = sorted(p for p in d.iterdir() if p.is_file())
        per = {p.name: digest(p) for p in files}
        # A single rollup over the sorted per-file digests: one value to compare
        # when you only need "did anything move at all".
        roll = hashlib.md5(
            "".join(f"{n}:{h}" for n, h in sorted(per.items())).encode()
        ).hexdigest()
        groups[sub] = {"files": len(per), "rollup": roll, "digests": per}
    return groups


def verify(man: dict) -> list[str]:
    problems = []
    cur = build()
    for sub, rec in man.get("groups", {}).items():
        if sub not in cur:
            problems.append(f"{sub}: MISSING from the working tree")
            continue
        if cur[sub]["rollup"] != rec["rollup"]:
            got, want = cur[sub]["digests"], rec["digests"]
            for name in sorted(set(got) | set(want)):
                if got.get(name) != want.get(name):
                    problems.append(
                        f"{sub}/{name}: {got.get(name, 'ABSENT')} != {want.get(name, 'ABSENT')}"
                    )
    return problems


def main() -> int:
    if "--verify" in sys.argv:
        if not OUT.is_file():
            print(f"no manifest at {OUT}", file=sys.stderr)
            return 1
        man = json.loads(OUT.read_text())
        problems = verify(man)
        if problems:
            print(f"SUBSTRATE DRIFT — {len(problems)} file(s) differ:")
            for p in problems[:20]:
                print(f"  {p}")
            if len(problems) > 20:
                print(f"  ... and {len(problems) - 20} more")
            return 1
        tot = sum(g["files"] for g in man["groups"].values())
        print(f"substrate verified: {tot:,} files match the manifest")
        return 0

    groups = build()
    OUT.write_text(
        json.dumps(
            {
                "built_on": "2026-09-03",
                "note": "The v3 panel is gitignored (128MB) and rebuilt by "
                        "scripts/asx_build_universe.py. This manifest is what makes a "
                        "rebuild verifiable rather than merely repeatable — V296-V304 "
                        "were computed on exactly these bytes.",
                "groups": groups,
            },
            indent=1,
            sort_keys=True,
        )
        + "\n"
    )
    tot = sum(g["files"] for g in groups.values())
    print(f"wrote {OUT.relative_to(ROOT)}: {tot:,} files")
    for sub, g in sorted(groups.items()):
        print(f"  {sub:>9}: {g['files']:>5} files  rollup={g['rollup'][:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
