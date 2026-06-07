#!/usr/bin/env python3
"""
V214 determinism bisect tool — diff two per-cycle signal fingerprints.

Consumes the `{version}_signal_fingerprint.jsonl` files emitted by
run_training.py (observability delta #4) for two same-seed replicates and
reports the FIRST cycle where the fingerprint hash diverges, then the exact
signals whose values differ at that cycle and the magnitude of each drift.

This is the discriminator the V207–V213 determinism hunt lacked: instead of
hand-bisecting cycle-1 artifacts, point it at two failing replicates and it
names the channel.

Usage:
    python3 scripts/fingerprint_diff.py A.jsonl B.jsonl
    python3 scripts/fingerprint_diff.py \
        data/v214_check_trend_r1_signal_fingerprint.jsonl \
        data/v214_check_trend_r2_signal_fingerprint.jsonl
"""
from __future__ import annotations

import json
import sys


def _load(path: str) -> dict[int, dict]:
    out: dict[int, dict] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            out[int(rec["cycle"])] = rec
    return out


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    a_path, b_path = sys.argv[1], sys.argv[2]
    a = _load(a_path)
    b = _load(b_path)

    common = sorted(set(a) & set(b))
    if not common:
        print("NO COMMON CYCLES — files do not overlap")
        return 1

    print(f"A = {a_path}  ({len(a)} cycles)")
    print(f"B = {b_path}  ({len(b)} cycles)")
    print(f"common cycles: {common[0]}..{common[-1]} ({len(common)})")

    first_div = None
    for c in common:
        if a[c]["fp"] != b[c]["fp"]:
            first_div = c
            break

    if first_div is None:
        print("\nIDENTICAL: all common-cycle fingerprints match. "
              "If PnL/trades still differ, the channel is DOWNSTREAM of signal "
              "computation (sizing/exit/attribution), not a signal value.")
        return 0

    print(f"\n*** FIRST DIVERGENCE AT CYCLE {first_div} ***")
    print(f"  A.regime={a[first_div].get('regime')}  B.regime={b[first_div].get('regime')}")
    av = a[first_div].get("values", {})
    bv = b[first_div].get("values", {})
    keys = sorted(set(av) | set(bv))
    diffs: list[tuple[str, float, float, float]] = []
    for k in keys:
        x = av.get(k)
        y = bv.get(k)
        if x != y:
            try:
                delta = abs(float(x) - float(y))
            except (TypeError, ValueError):
                delta = float("nan")
            diffs.append((k, x, y, delta))

    if not diffs:
        print("  (fp differs but no scalar value differs — key-set drift?)")
        print(f"  A keys={sorted(av)}\n  B keys={sorted(bv)}")
        return 0

    diffs.sort(key=lambda t: (t[3] != t[3], -t[3]))  # nan last, then desc magnitude
    print(f"  {len(diffs)} signal(s) diverged at cycle {first_div} "
          f"(largest drift first — that is the channel root):")
    for k, x, y, delta in diffs:
        print(f"    {k:32s}  A={x!r:>18}  B={y!r:>18}  |Δ|={delta:.3e}")

    # How long does each diverged signal stay split? helps tell a one-cycle
    # boundary crossing from a persistent fork.
    print("\n  divergence persistence (cycles where each stays split):")
    for k, *_ in diffs[:5]:
        split = sum(
            1 for c in common
            if c >= first_div and a[c].get("values", {}).get(k) != b[c].get("values", {}).get(k)
        )
        print(f"    {k:32s}  split in {split}/{sum(1 for c in common if c >= first_div)} cycles from {first_div}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
