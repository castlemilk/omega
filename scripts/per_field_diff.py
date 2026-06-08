#!/usr/bin/env python3
"""
V217 determinism bisect tool — diff two per-field full-precision fingerprints.

Consumes the `{version}_per_field_fingerprint.jsonl` files emitted by
run_training.py (observability delta V217 #1) for two same-seed replicates and
reports the FIRST (cycle, signal_name) whose IEEE-754 bits diverge — i.e. the
exact field carrying the determinism channel.

This succeeds where `fingerprint_diff.py` dead-ends. That tool compares the
rounded-to-12 `values` dump, so a sub-12th-bit drift shows up only as the opaque
whole-dict `fp` hash differing with "no scalar value differs" (the V216 third
channel). The per-field artifact stores `struct.pack('!d', v).hex()` per field, so
a drift in ANY bit of ANY field is named here by construction.

Usage:
    python3 scripts/per_field_diff.py A.jsonl B.jsonl
    python3 scripts/per_field_diff.py \
        data/v217_off_recent_r1_per_field_fingerprint.jsonl \
        data/v217_off_recent_r2_per_field_fingerprint.jsonl
"""
from __future__ import annotations

import json
import struct
import sys


def _load(path: str) -> dict[tuple[int, str], str]:
    """(cycle, signal_name) -> value_hex."""
    out: dict[tuple[int, str], str] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            out[(int(rec["cycle"]), str(rec["signal_name"]))] = str(rec["value_hex"])
    return out


def _decode(hex_str: str) -> float:
    try:
        return struct.unpack("!d", bytes.fromhex(hex_str))[0]
    except Exception:
        return float("nan")


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    a_path, b_path = sys.argv[1], sys.argv[2]
    a = _load(a_path)
    b = _load(b_path)

    a_cycles = {c for c, _ in a}
    b_cycles = {c for c, _ in b}
    common_cycles = sorted(a_cycles & b_cycles)
    if not common_cycles:
        print("NO COMMON CYCLES — files do not overlap")
        return 1

    print(f"A = {a_path}  ({len(a)} field-rows, cycles {min(a_cycles)}..{max(a_cycles)})")
    print(f"B = {b_path}  ({len(b)} field-rows, cycles {min(b_cycles)}..{max(b_cycles)})")
    print(f"common cycles: {common_cycles[0]}..{common_cycles[-1]} ({len(common_cycles)})")

    # First divergent (cycle, signal_name), scanning cycles in order then names.
    first_div: tuple[int, str] | None = None
    keyset_drift: list[tuple[int, str, str]] = []  # (cycle, name, which-side-only)
    for c in common_cycles:
        names_a = {n for (cc, n) in a if cc == c}
        names_b = {n for (cc, n) in b if cc == c}
        only_a = names_a - names_b
        only_b = names_b - names_a
        for n in sorted(only_a):
            keyset_drift.append((c, n, "A-only"))
        for n in sorted(only_b):
            keyset_drift.append((c, n, "B-only"))
        for n in sorted(names_a & names_b):
            if a[(c, n)] != b[(c, n)]:
                first_div = (c, n)
                break
        if first_div is not None:
            break

    if keyset_drift and (first_div is None or keyset_drift[0][0] <= first_div[0]):
        c, n, side = keyset_drift[0]
        print(f"\n*** KEY-SET DRIFT at cycle {c}: {n} present {side} only ***")
        print("  A field present in one run but not the other — a signal appears/"
              "vanishes between replicates (upstream availability channel).")
        # fall through to also report first value divergence if earlier/equal

    if first_div is None:
        if keyset_drift:
            return 0
        print("\nIDENTICAL: every common (cycle, field) value_hex matches bit-for-bit. "
              "The signal layer is HERMETIC. If PnL/trades still differ, the channel is "
              "DOWNSTREAM of signal computation (sizing/exit/attribution).")
        return 0

    c, n = first_div
    av, bv = a[(c, n)], b[(c, n)]
    af, bf = _decode(av), _decode(bv)
    delta = abs(af - bf)
    print(f"\n*** FIRST DIVERGENT FIELD: cycle {c}, signal '{n}' ***")
    print(f"  A.value_hex = {av}   ({af!r})")
    print(f"  B.value_hex = {bv}   ({bf!r})")
    print(f"  |Δ| = {delta:.3e}   <-- THIS (cycle, signal) is the channel root")

    # How long does this field stay split? one-cycle boundary vs persistent fork.
    later = [c2 for c2 in common_cycles if c2 >= c]
    split = sum(1 for c2 in later if a.get((c2, n)) != b.get((c2, n)))
    print(f"\n  '{n}' stays split in {split}/{len(later)} cycles from {c}.")

    # All fields diverging at the first divergent cycle (full picture of that cycle).
    same_cycle = sorted(
        nm for (cc, nm) in (set(a) & set(b)) if cc == c and a[(cc, nm)] != b[(cc, nm)]
    )
    if len(same_cycle) > 1:
        print(f"\n  {len(same_cycle)} fields diverge at cycle {c}: {same_cycle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
