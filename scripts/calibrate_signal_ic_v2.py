#!/usr/bin/env python3
"""V171: rebuild IC calibrator at TOP-LEVEL signal granularity.

V169/V170 calibrator was wrong: it walked `data/activation_traces/*.jsonl` whose
`activations[]` are sub-signal components (sma_long, sma_short, momentum_short,
return_1d, etc.). The strategy's `_compute_weighted_conviction` only iterates
TOP-LEVEL signals where `k.endswith("_signal") or k == "sma_crossover"` — names
like `sma_crossover`, `breakout_signal`, `fear_greed_signal`, `adx_signal`.

This script reads `data/*_signal_contribs.jsonl` instead — each row is one
closed trade with `signal_traces: [{name, value, weight}]` at the top-level
signal level (matches what the composite path iterates) plus `pnl` and
`symbol` / `cycle` / `side`. Joins with `data/*_trades.csv` on (cycle, symbol,
side) for the regime label.

Output: `data/signal_ic_history.json` with the same SignalDecayDetector schema
as before, but using top-level signal names. Strategy's `_signal_ics` lookup
will now actually match.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEFAULT_OUT = DATA / "signal_ic_history.json"


def _spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    def rank(arr):
        idx = sorted(range(n), key=lambda i: arr[i])
        out = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and arr[idx[j + 1]] == arr[idx[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[idx[k]] = avg
            i = j + 1
        return out
    rx, ry = rank(xs), rank(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((r - mx) ** 2 for r in rx))
    dy = math.sqrt(sum((r - my) ** 2 for r in ry))
    return num / (dx * dy) if dx > 0 and dy > 0 else 0.0


def _load_trade_regimes(version: str) -> dict[tuple, str]:
    """Build (cycle, symbol, side) → regime map from {version}_trades.csv."""
    p = DATA / f"{version}_trades.csv"
    if not p.exists():
        return {}
    out: dict[tuple, str] = {}
    with open(p) as f:
        for r in csv.DictReader(f):
            try:
                key = (int(r["cycle"]), r["symbol"], r["side"])
                out[key] = r.get("regime", "unknown") or "unknown"
            except (KeyError, ValueError):
                continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--limit-files", type=int, default=0)
    args = ap.parse_args()

    files = sorted(p for p in DATA.glob("*_signal_contribs.jsonl") if p.stat().st_size > 0)
    if args.limit_files > 0:
        files = files[: args.limit_files]
    print(f"Processing {len(files)} signal_contribs files…")

    overall: dict[str, list[tuple[float, float]]] = defaultdict(list)
    by_regime: dict[str, dict[str, list[tuple[float, float]]]] = defaultdict(lambda: defaultdict(list))
    rows = 0

    for f in files:
        version = f.name.replace("_signal_contribs.jsonl", "")
        regime_map = _load_trade_regimes(version)
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                pnl = d.get("pnl")
                if pnl is None:
                    continue
                try:
                    pnl = float(pnl)
                except (TypeError, ValueError):
                    continue
                cyc = d.get("cycle")
                sym = d.get("symbol")
                side = d.get("side", "long")
                regime = "unknown"
                if cyc is not None and sym:
                    try:
                        regime = regime_map.get((int(cyc), sym, side), "unknown")
                    except (TypeError, ValueError):
                        pass
                # Direction-aligned signal value: long → +1, short → -1
                dir_sign = 1.0 if side == "long" else -1.0
                for t in d.get("signal_traces") or []:
                    name = t.get("name")
                    raw = t.get("value")
                    if not name or raw is None:
                        continue
                    try:
                        x = float(raw) * dir_sign
                    except (TypeError, ValueError):
                        continue
                    overall[name].append((x, pnl))
                    if regime != "unknown":
                        by_regime[name][regime].append((x, pnl))
                    rows += 1

    print(f"Collected {rows} pairs across {len(overall)} top-level signals.")

    out: dict = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "n_files_processed": len(files),
        "n_pairs": rows,
        "calibrator_version": "v2_top_level",
        "signals": {},
    }
    _WINDOW = 20
    for name, pairs in overall.items():
        if len(pairs) < 5:
            continue
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        ic = _spearman(xs, ys)
        n = len(pairs)
        if n > _WINDOW:
            stride = max(1, n // _WINDOW)
            sample = [pairs[i] for i in range(0, n, stride)][:_WINDOW]
        else:
            sample = list(pairs)
        regime_ics: dict[str, dict] = {}
        for reg, rpairs in by_regime[name].items():
            if len(rpairs) >= 5:
                regime_ics[reg] = {
                    "ic": round(_spearman([p[0] for p in rpairs], [p[1] for p in rpairs]), 4),
                    "n": len(rpairs),
                }
        status = (
            "anti-predictive" if ic < -0.05 else
            "decaying" if ic < 0.0 else
            "weak" if ic < 0.05 else
            "active"
        )
        out["signals"][name] = {
            "ic": round(ic, 4),
            "n_obs": len(sample),
            "n_total_pairs": len(pairs),
            "status": status,
            "regime_ic": regime_ics,
            "obs": [[round(s, 6), round(r, 6)] for s, r in sample],
        }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {args.out}")

    ranked = sorted(out["signals"].items(), key=lambda kv: -abs(kv[1]["ic"]))
    print()
    print(f"{'rank':>4}  {'signal':<30}  {'ic':>8}  {'n':>6}  {'status':<16}  per-regime ICs")
    for i, (name, s) in enumerate(ranked, start=1):
        rgi = s.get("regime_ic", {})
        rg_str = ", ".join(f"{r}={v['ic']:+.3f}(n={v['n']})" for r, v in sorted(rgi.items()))
        print(f"{i:>4}  {name:<30}  {s['ic']:>+8.4f}  {s['n_total_pairs']:>6}  {s['status']:<16}  {rg_str}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
