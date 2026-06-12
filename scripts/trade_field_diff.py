#!/usr/bin/env python3
"""
V221 determinism bisect tool — diff two same-seed trade ledgers at the
TRADE level (observability delta #13).

`scripts/per_field_diff.py` fingerprints the *signal* layer
(`(cycle, signal_name) -> value_hex`). When the signal layer is hermetic but
PnL still diverges across same-seed replicates — the V220 finding: trade count
locked 26/26, yet `trend_OFF` PnL spans $697→$3,549 — the channel lives
DOWNSTREAM of signals, in **position sizing / exit-price / PnL accounting**.
This tool fingerprints that layer.

For each trade row it hex-encodes every numeric ledger field via
`struct.pack('!d', float(v)).hex()` (IEEE-754 bit-exact), keyed by
`(cycle, symbol, side, occurrence)`. It then reports the FIRST divergent
`(trade, field)` — the exact sizing/exit field carrying the magnitude channel.

Wall-clock fields (`timestamp`, `entry_ts`, `exit_ts`) are EXCLUDED from the
divergence scan by construction — they differ between replicates by design
(each replicate runs at its own wall-clock) and are not a determinism defect.

Usage:
    # Diff two trade CSVs, print the first divergent (trade, field):
    python3 scripts/trade_field_diff.py A_trades.csv B_trades.csv

    # Also emit per_trade_fingerprint.jsonl for each run under an audit dir:
    python3 scripts/trade_field_diff.py A_trades.csv B_trades.csv \
        --emit-dir data/v221_audit --label-a r1 --label-b r2
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import struct
import sys

# Numeric ledger fields fingerprinted, in canonical scan order. Wall-clock
# columns (timestamp / *_ts) are deliberately omitted — they differ by design.
# Text columns (symbol, side, regime, sit_out_reason) are part of the KEY or
# are categorical, not magnitude channels.
NUMERIC_FIELDS = [
    "size",
    "entry_price",
    "exit_price",
    "pnl",
    "slippage",
    "conviction",
    "hold_cycles",
    "mae",
    "mfe",
    "win_capture",
    "loss_capture",
    "exit_score",
    # Forward-compatible aliases (emitted by newer ledgers); skipped if absent.
    "position_size_quote",
    "position_size_base",
    "slippage_bps",
    "fees",
    "pnl_usd",
]

# Key columns identifying a trade across replicates (NOT wall-clock).
KEY_FIELDS = ["cycle", "symbol", "side"]

TradeKey = tuple  # (cycle:int, symbol:str, side:str, occurrence:int)


def _hex(v: str) -> str | None:
    """IEEE-754 bit-exact hex of a float field; None for empty/non-numeric."""
    s = (v or "").strip()
    if s == "":
        return None
    try:
        return struct.pack("!d", float(s)).hex()
    except (ValueError, struct.error):
        return None


def _load(path: str) -> tuple[dict[TradeKey, dict[str, str]], list[TradeKey]]:
    """Return (key -> {field: value_hex}, ordered keys). Occurrence disambiguates
    duplicate (cycle, symbol, side) rows within one run (e.g. two same-cycle fills)."""
    rows: dict[TradeKey, dict[str, str]] = {}
    order: list[TradeKey] = []
    seen: dict[tuple, int] = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        present = [c for c in NUMERIC_FIELDS if c in (reader.fieldnames or [])]
        for r in reader:
            try:
                cycle = int(r["cycle"])
            except (KeyError, ValueError):
                continue
            base = (cycle, r.get("symbol", ""), r.get("side", ""))
            occ = seen.get(base, 0)
            seen[base] = occ + 1
            key: TradeKey = (*base, occ)
            fp = {col: h for col in present if (h := _hex(r.get(col, ""))) is not None}
            rows[key] = fp
            order.append(key)
    return rows, order


def _emit_fingerprint(path: str, out_path: str) -> int:
    rows, order = _load(path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        for key in order:
            cycle, symbol, side, occ = key
            rec = {
                "cycle": cycle,
                "symbol": symbol,
                "side": side,
                "occurrence": occ,
                "fields": rows[key],
            }
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    return len(order)


def _decode(h: str) -> float:
    try:
        return struct.unpack("!d", bytes.fromhex(h))[0]
    except (ValueError, struct.error):
        return float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("a_csv")
    ap.add_argument("b_csv")
    ap.add_argument("--emit-dir", default=None,
                    help="If set, write per_trade_fingerprint.jsonl for each run "
                         "under <emit-dir>/<label>/.")
    ap.add_argument("--label-a", default="r1")
    ap.add_argument("--label-b", default="r2")
    args = ap.parse_args()

    a, a_order = _load(args.a_csv)
    b, b_order = _load(args.b_csv)

    if args.emit_dir:
        na = _emit_fingerprint(
            args.a_csv, os.path.join(args.emit_dir, args.label_a, "per_trade_fingerprint.jsonl"))
        nb = _emit_fingerprint(
            args.b_csv, os.path.join(args.emit_dir, args.label_b, "per_trade_fingerprint.jsonl"))
        print(f"emitted {na} rows -> {args.emit_dir}/{args.label_a}/per_trade_fingerprint.jsonl")
        print(f"emitted {nb} rows -> {args.emit_dir}/{args.label_b}/per_trade_fingerprint.jsonl")

    print(f"A = {args.a_csv}  ({len(a)} trades)")
    print(f"B = {args.b_csv}  ({len(b)} trades)")

    only_a = [k for k in a_order if k not in b]
    only_b = [k for k in b_order if k not in a]
    if only_a or only_b:
        print(f"\n*** TRADE-SET DRIFT: {len(only_a)} A-only, {len(only_b)} B-only ***")
        for k in only_a[:5]:
            print(f"  A-only: cycle {k[0]} {k[1]} {k[2]} (occ {k[3]})")
        for k in only_b[:5]:
            print(f"  B-only: cycle {k[0]} {k[1]} {k[2]} (occ {k[3]})")
        print("  (trade COUNT or membership differs — an entry/exit decision flipped, "
              "not a pure magnitude channel.)")

    # First divergent (trade, field), scanning A's trade order then field order.
    common = [k for k in a_order if k in b]
    first: tuple[TradeKey, str] | None = None
    for k in common:
        fa, fb = a[k], b[k]
        for col in NUMERIC_FIELDS:
            if col in fa and col in fb and fa[col] != fb[col]:
                first = (k, col)
                break
        if first:
            break

    if first is None:
        if not (only_a or only_b):
            print("\nIDENTICAL: every common trade's numeric fields match bit-for-bit. "
                  "The trade ledger is HERMETIC.")
        return 0

    k, col = first
    av, bv = a[k][col], b[k][col]
    af, bf = _decode(av), _decode(bv)
    cycle, symbol, side, occ = k
    print(f"\n*** FIRST DIVERGENT TRADE FIELD: cycle {cycle}, {symbol} {side} "
          f"(occ {occ}), field '{col}' ***")
    print(f"  A.{col}_hex = {av}   ({af!r})")
    print(f"  B.{col}_hex = {bv}   ({bf!r})")
    print(f"  |Δ| = {abs(af - bf):.6g}   <-- THIS (trade, field) is the channel root")

    # Which fields diverge on THIS trade (full picture of the first split row).
    diverged = [c for c in NUMERIC_FIELDS
                if c in a[k] and c in b[k] and a[k][c] != b[k][c]]
    print(f"\n  {len(diverged)} field(s) diverge on this trade: {diverged}")

    # Are the entry/exit PRICES stable on this trade? (sizing vs exit-price triage)
    for px in ("entry_price", "exit_price"):
        if px in a[k] and px in b[k]:
            same = a[k][px] == b[k][px]
            print(f"  {px}: {'IDENTICAL' if same else 'DIVERGENT'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
