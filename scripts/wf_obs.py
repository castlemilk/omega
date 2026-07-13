#!/usr/bin/env python3
"""V247 Phase 2 — walk-forward observability instruments.

Two instruments queued by REFLECTION_V246 §6, shipped as a reusable module
so every future v###_wf_aggregate.py imports them instead of re-deriving:

1. dual_tail(rows, off, on)
   Per regime (+ pooled), reports BOTH the Δ-distribution p25 (differential
   tail — what the V245/V246 falsifiers gated on) AND the level p25 of each
   arm (absolute tail — what "the tail must not worsen" colloquially means).
   V245 + V246 both had Δ-p25 negative while level-p25 tightened; the
   divergence is signal. Future pre-regs must name which one they gate on.

2. reentry_coupling(pairs, window_bars)
   Per window, joins the ON/OFF trade ledgers on the OPEN key
   (entry_cycle = cycle - hold_cycles, symbol, side) and counts trades that
   exist in only one arm — the capital-coupling channel V246's per-trade
   replay scorer could not see (343→327 trades went unnoticed until the
   verdict). Also counts strict re-entries: an ON-only entry within
   `window_bars` bars after an ON exit of the same symbol that has no
   OFF-arm exit at that cycle ("an exit that wouldn't have fired on OFF
   freed the capital").

CLI (read-only; writes nothing):
  python3 scripts/wf_obs.py dual-tail --distribution <dir/distribution.json> \
      --off universe_selective --on exit_adapt
  python3 scripts/wf_obs.py reentry --manifest data/walk_forward_manifest.json \
      --on-template  '<audit>/v246wf_{window}_exit_adapt_{regime}_r1_trades.csv' \
      --off-template '<audit>/v240wf_{window}_universe_selective_{regime}_r1_trades.csv' \
      --window-bars 8
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

REGIMES = ("recent", "trend", "crisis", "pooled")


def pctl(sorted_xs: list[float], q: float) -> float:
    n = len(sorted_xs)
    if n == 0:
        return float("nan")
    if n == 1:
        return sorted_xs[0]
    pos = q / 100.0 * (n - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


# ---------------------------------------------------------------- dual tail

def dual_tail(rows: list[dict], off: str, on: str) -> dict[str, dict]:
    """rows = distribution.json['rows']. Returns per-regime dual-tail stats."""
    offm: dict[str, dict[str, float]] = {r: {} for r in REGIMES}
    onm: dict[str, dict[str, float]] = {r: {} for r in REGIMES}
    for r in rows:
        tgt = offm if r["config"] == off else onm if r["config"] == on else None
        if tgt is None:
            continue
        tgt[r["regime"]][r["window"]] = r["pnl"]
        tgt["pooled"][r["window"]] = r["pnl"]

    out: dict[str, dict] = {}
    for reg in REGIMES:
        common = sorted(set(offm[reg]) & set(onm[reg]))
        if not common:
            continue
        offs = sorted(offm[reg][w] for w in common)
        ons = sorted(onm[reg][w] for w in common)
        deltas = sorted(onm[reg][w] - offm[reg][w] for w in common)
        lvl_off = pctl(offs, 25)
        lvl_on = pctl(ons, 25)
        out[reg] = {
            "n": len(common),
            "delta_mean": math.fsum(deltas) / len(deltas),
            "delta_p25": pctl(deltas, 25),
            "level_p25_off": lvl_off,
            "level_p25_on": lvl_on,
            "level_p25_change": lvl_on - lvl_off,
            "diverges": (pctl(deltas, 25) < 0) != (lvl_on - lvl_off < 0),
        }
    return out


def format_dual_tail(stats: dict[str, dict]) -> str:
    lines = [
        "| regime | n | Δ mean | Δ-p25 (differential tail) | level-p25 OFF | level-p25 ON | level-p25 change | tails diverge? |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for reg in REGIMES:
        if reg not in stats:
            continue
        s = stats[reg]
        lines.append(
            f"| {reg} | {s['n']} | {s['delta_mean']:+,.0f} | {s['delta_p25']:+,.0f} "
            f"| {s['level_p25_off']:+,.0f} | {s['level_p25_on']:+,.0f} "
            f"| {s['level_p25_change']:+,.0f} | {'YES' if s['diverges'] else 'no'} |"
        )
    return "\n".join(lines)


# --------------------------------------------------------- re-entry coupling

def _load_trades(path: str | Path) -> list[dict]:
    with open(path) as f:
        rows = []
        for r in csv.DictReader(f):
            r["_entry_cycle"] = int(float(r["cycle"])) - int(float(r["hold_cycles"]))
            r["_exit_cycle"] = int(float(r["cycle"]))
            rows.append(r)
        return rows


def _open_keys(trades: list[dict]) -> dict[tuple, dict]:
    return {(t["_entry_cycle"], t["symbol"], t["side"]): t for t in trades}


def reentry_coupling_window(
    on_trades: list[dict], off_trades: list[dict], window_bars: int = 8
) -> dict:
    on_k, off_k = _open_keys(on_trades), _open_keys(off_trades)
    on_only = [on_k[k] for k in set(on_k) - set(off_k)]
    off_only = [off_k[k] for k in set(off_k) - set(on_k)]
    off_exits = {(t["_exit_cycle"], t["symbol"]) for t in off_trades}
    reentries = 0
    for t in on_only:
        for prior in on_trades:
            if (
                prior["symbol"] == t["symbol"]
                and prior["_exit_cycle"] <= t["_entry_cycle"] <= prior["_exit_cycle"] + window_bars
                and (prior["_exit_cycle"], prior["symbol"]) not in off_exits
            ):
                reentries += 1
                break
    return {
        "n_on": len(on_trades),
        "n_off": len(off_trades),
        "matched_open": len(set(on_k) & set(off_k)),
        "on_only": len(on_only),
        "off_only": len(off_only),
        "reentries_within_bars": reentries,
        "coupling_frac": (len(on_only) + len(off_only))
        / max(1, len(on_trades) + len(off_trades)),
    }


def format_reentry(per_window: dict[str, dict], window_bars: int) -> str:
    lines = [
        f"| window | regime | ON | OFF | matched(open-key) | ON-only | OFF-only | re-entries ≤{window_bars} bars | coupling frac |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    tot = {"n_on": 0, "n_off": 0, "matched_open": 0, "on_only": 0, "off_only": 0,
           "reentries_within_bars": 0}
    for wid, (reg, s) in sorted(per_window.items()):
        for k in tot:
            tot[k] += s[k]
        lines.append(
            f"| {wid} | {reg} | {s['n_on']} | {s['n_off']} | {s['matched_open']} "
            f"| {s['on_only']} | {s['off_only']} | {s['reentries_within_bars']} "
            f"| {s['coupling_frac']:.2f} |"
        )
    frac = (tot["on_only"] + tot["off_only"]) / max(1, tot["n_on"] + tot["n_off"])
    lines.append(
        f"| **TOTAL** | | {tot['n_on']} | {tot['n_off']} | {tot['matched_open']} "
        f"| {tot['on_only']} | {tot['off_only']} | {tot['reentries_within_bars']} "
        f"| {frac:.2f} |"
    )
    return "\n".join(lines)


# ------------------------------------------------------------------- CLI

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    dt = sub.add_parser("dual-tail")
    dt.add_argument("--distribution", required=True)
    dt.add_argument("--off", default="universe_selective")
    dt.add_argument("--on", required=True)

    re_ = sub.add_parser("reentry")
    re_.add_argument("--manifest", default="data/walk_forward_manifest.json")
    re_.add_argument("--on-template", required=True,
                     help="path template with {window} and {regime} placeholders")
    re_.add_argument("--off-template", required=True)
    re_.add_argument("--window-bars", type=int, default=8)

    args = ap.parse_args()

    if args.cmd == "dual-tail":
        rows = json.loads(Path(args.distribution).read_text())["rows"]
        print(format_dual_tail(dual_tail(rows, args.off, args.on)))
    else:
        manifest = json.loads(Path(args.manifest).read_text())
        per_window: dict[str, tuple[str, dict]] = {}
        missing = []
        for w in manifest["windows"]:
            wid, reg = w["id"], w["regime"]
            on_p = Path(args.on_template.format(window=wid, regime=reg))
            off_p = Path(args.off_template.format(window=wid, regime=reg))
            if not on_p.exists() or not off_p.exists():
                missing.append(wid)
                continue
            per_window[wid] = (
                reg,
                reentry_coupling_window(
                    _load_trades(on_p), _load_trades(off_p), args.window_bars
                ),
            )
        print(format_reentry(per_window, args.window_bars))
        if missing:
            print(f"\nWARN: {len(missing)} windows missing ledgers: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
