#!/usr/bin/env python3
"""Calibrate per-signal Information Coefficient (IC) from activation traces.

For each signal that fired in any historical trade:
  - Collect (raw_value × direction_alignment, exit_pnl) pairs across all trades
  - Compute Spearman rank correlation = IC
  - Also compute per-regime IC (normal / crisis / high_vol)
  - Write to data/signal_ic_history.json in the schema the strategy reads

The activation_traces are written by the activation_tracing feature flag and
contain `activations: [{name, raw_value, direction_alignment, ...}]` plus
`outcome.exit_pnl` and `regime.label` per closed trade.

Output format (matches what AdaptiveCombiner / SignalDecayDetector expect):
  {
    "updated_at": "<iso>",
    "signals": {
      "sma_long":   {"ic": 0.12, "n": 1437, "regime_ic": {"normal": 0.15, "crisis": -0.05, "high_vol": 0.08}},
      ...
    }
  }

Usage:
  python3 scripts/calibrate_signal_ic.py [--limit-files N] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACE_DIR = ROOT / "data" / "activation_traces"
DEFAULT_OUT = ROOT / "data" / "signal_ic_history.json"


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation. Returns 0.0 if degenerate (n<3, no variance)."""
    n = len(xs)
    if n < 3:
        return 0.0
    # Rank xs and ys
    def _rank(arr: list[float]) -> list[float]:
        idx = sorted(range(n), key=lambda i: arr[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and arr[idx[j + 1]] == arr[idx[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0  # 1-indexed average rank for ties
            for k in range(i, j + 1):
                ranks[idx[k]] = avg
            i = j + 1
        return ranks
    rx = _rank(xs)
    ry = _rank(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((r - mx) ** 2 for r in rx))
    dy = math.sqrt(sum((r - my) ** 2 for r in ry))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-files", type=int, default=0, help="Process only N trace files (0=all)")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    if not TRACE_DIR.exists():
        print(f"trace dir missing: {TRACE_DIR}", file=sys.stderr)
        return 1

    files = sorted(TRACE_DIR.glob("*.jsonl"))
    if args.limit_files > 0:
        files = files[: args.limit_files]
    print(f"Processing {len(files)} trace files…")

    # Aggregate per-signal pairs
    overall: dict[str, list[tuple[float, float]]] = defaultdict(list)
    by_regime: dict[str, dict[str, list[tuple[float, float]]]] = defaultdict(lambda: defaultdict(list))

    rows = 0
    for f in files:
        try:
            with open(f) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    pnl = d.get("outcome", {}).get("exit_pnl")
                    if pnl is None:
                        continue
                    try:
                        pnl = float(pnl)
                    except (TypeError, ValueError):
                        continue
                    regime = (d.get("regime") or {}).get("label", "unknown")
                    direction = d.get("direction", "long")
                    dir_sign = 1.0 if direction == "long" else -1.0
                    for a in (d.get("activations") or []):
                        name = a.get("name")
                        if not name:
                            continue
                        try:
                            raw = float(a.get("raw_value"))
                        except (TypeError, ValueError):
                            continue
                        # Direction-aligned signal value: a positive raw_value should
                        # predict positive PnL when long, negative PnL when short.
                        # Multiply raw by direction sign to standardize.
                        x = raw * dir_sign
                        overall[name].append((x, pnl))
                        by_regime[name][regime].append((x, pnl))
                        rows += 1
        except Exception as exc:
            print(f"  skipped {f.name}: {exc}", file=sys.stderr)

    print(f"Collected {rows} (signal, trade) pairs across {len(overall)} unique signals.")

    # Schema must match SignalDecayDetector._SignalRecord (see signal_decay.py:122):
    # each signal entry needs an `obs` array of (signal_val, forward_return) pairs
    # so detector.ic() can recompute Pearson r on load.
    out: dict = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "n_traces_processed": len(files),
        "n_pairs": rows,
        "signals": {},
    }
    # _WINDOW in signal_decay.py is 20; provide up to 20 representative obs.
    _WINDOW = 20
    for name, pairs in overall.items():
        if len(pairs) < 10:
            continue
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        ic = _spearman(xs, ys)
        # Subsample to _WINDOW pairs preserving correlation structure (uniform stride).
        n = len(pairs)
        if n > _WINDOW:
            stride = max(1, n // _WINDOW)
            sample = [pairs[i] for i in range(0, n, stride)][:_WINDOW]
        else:
            sample = list(pairs)
        regime_ics: dict[str, dict] = {}
        for reg, rpairs in by_regime[name].items():
            if len(rpairs) >= 5:
                rx = [p[0] for p in rpairs]
                ry = [p[1] for p in rpairs]
                regime_ics[reg] = {
                    "ic": round(_spearman(rx, ry), 4),
                    "n": len(rpairs),
                }
        # SignalDecayDetector status thresholds: active >= 0.05, anti-predictive < -0.05
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

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {out_path}")

    # Print ranking
    ranked = sorted(out["signals"].items(), key=lambda kv: -abs(kv[1]["ic"]))
    print()
    print(f"{'rank':>4}  {'signal':<32}  {'ic':>9}  {'n':>7}  status")
    for i, (name, s) in enumerate(ranked, start=1):
        print(f"{i:>4}  {name:<32}  {s['ic']:>+9.4f}  {s['n_total_pairs']:>7}  {s['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
