#!/usr/bin/env python3
"""V240 Track A — per-ticker forensics on the V239 universe flip.

Reads the V239 walk-forward grid artifacts (distribution.json + per-cell
trades.csv) and answers: is there a SELECTIVE re-include subset of the 9
previously-blacklisted names whose trade-log-reconstructed deltas pass the
V239 pre-reg bar (pooled mean-D > -300 AND every regime mean-D > -500)?

Reconstruction caveat: dropping a ticker's trades from the full-arm log
ignores interaction effects (budget/N reallocation, cross-sectional demean).
Any passing subset must be confirmed with a real grid before shipping.

Usage:
  python3 scripts/v240_universe_forensics.py \
    [--audit-dir /Volumes/gamma-systems-2/omega-victoria-data] \
    [--out-json data/v240_universe_forensics.json]
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
from collections import defaultdict
from pathlib import Path

REINCLUDED = [
    "BTCUSDT", "DOTUSDT", "MATICUSDT", "XRPUSDT", "SOLUSDT",
    "AVAXUSDT", "LINKUSDT", "BNBUSDT", "SUIUSDT",
]

POOLED_FLOOR = -300.0
REGIME_FLOOR = -500.0


def load_rows(audit: Path) -> list[dict]:
    dist = json.loads((audit / "v239_wf" / "distribution.json").read_text())
    return dist["rows"]


def cell_trades(audit: Path, window: str, config: str, regime: str) -> list[dict]:
    stem = f"v239wf_{window}_{config}_{regime}"
    cell = audit / f"{stem}_determinism"
    path = cell / f"{stem}_r1_trades.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open() as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--audit-dir",
        default=os.environ.get(
            "OMEGA_AUDIT_OUTPUT_DIR", "/Volumes/gamma-systems-2/omega-victoria-data"
        ),
    )
    ap.add_argument("--out-json", default="data/v240_universe_forensics.json")
    args = ap.parse_args()
    audit = Path(args.audit_dir)

    rows = load_rows(audit)
    windows: dict[str, dict] = {}
    for r in rows:
        w = windows.setdefault(
            r["window"], {"regime": r["regime"], "window": r["window"]}
        )
        w[r["config"]] = r["pnl"]

    # Per-window per-ticker PnL of the re-included names in the full arm,
    # plus a consistency check that trades.csv sums to the recorded cell PnL.
    per_ticker_regime = defaultdict(lambda: defaultdict(float))
    per_ticker_trades = defaultdict(int)
    window_removable: dict[str, dict[str, float]] = {}
    max_sum_err = 0.0
    for w in windows.values():
        trades = cell_trades(audit, w["window"], "universe_full", w["regime"])
        total = sum(float(t["pnl"]) for t in trades)
        max_sum_err = max(max_sum_err, abs(total - w["universe_full"]))
        removable = defaultdict(float)
        for t in trades:
            sym = t["symbol"]
            if sym in REINCLUDED:
                removable[sym] += float(t["pnl"])
                per_ticker_regime[sym][w["regime"]] += float(t["pnl"])
                per_ticker_trades[sym] += 1
        window_removable[w["window"]] = dict(removable)

    regimes = sorted({w["regime"] for w in windows.values()})

    def evaluate(keep: frozenset[str]) -> dict:
        deltas = defaultdict(list)
        for w in windows.values():
            drop_pnl = sum(
                p for s, p in window_removable[w["window"]].items() if s not in keep
            )
            delta = (w["universe_full"] - drop_pnl) - w["universe_legacy"]
            deltas[w["regime"]].append(delta)
        regime_means = {
            reg: sum(v) / len(v) for reg, v in deltas.items()
        }
        pooled = [d for v in deltas.values() for d in v]
        pooled_mean = sum(pooled) / len(pooled)
        passes = pooled_mean > POOLED_FLOOR and all(
            m > REGIME_FLOOR for m in regime_means.values()
        )
        return {
            "keep": sorted(keep),
            "pooled_mean": round(pooled_mean, 2),
            "regime_means": {k: round(v, 2) for k, v in regime_means.items()},
            "passes_prereg_bar": passes,
            "pooled_positive": pooled_mean > 0,
        }

    # Exhaustive search over all 2^9 keep-subsets.
    results = []
    for k in range(len(REINCLUDED) + 1):
        for combo in itertools.combinations(REINCLUDED, k):
            results.append(evaluate(frozenset(combo)))

    passing = [r for r in results if r["passes_prereg_bar"] and r["pooled_positive"]]
    # Rank by worst-regime headroom above the -500 floor, then pooled mean.
    def headroom(r: dict) -> float:
        return min(r["regime_means"].values()) - REGIME_FLOOR

    passing.sort(key=lambda r: (headroom(r), r["pooled_mean"]), reverse=True)

    ticker_table = sorted(
        (
            {
                "symbol": s,
                "trades": per_ticker_trades[s],
                **{reg: round(per_ticker_regime[s].get(reg, 0.0), 2) for reg in regimes},
                "total": round(sum(per_ticker_regime[s].values()), 2),
            }
            for s in REINCLUDED
        ),
        key=lambda x: x.get("crisis", 0.0),
    )

    out = {
        "version": "v240_universe_forensics",
        "n_windows": len(windows),
        "trade_sum_max_abs_err_vs_cell_pnl": round(max_sum_err, 4),
        "full_flip_baseline": evaluate(frozenset(REINCLUDED)),
        "legacy_baseline": evaluate(frozenset()),
        "per_ticker": ticker_table,
        "n_subsets_evaluated": len(results),
        "n_passing": len(passing),
        "top_passing": passing[:15],
        "best_by_pooled": sorted(
            passing, key=lambda r: r["pooled_mean"], reverse=True
        )[:5],
    }
    Path(args.out_json).write_text(json.dumps(out, indent=2))

    print(f"windows={len(windows)}  sum-check max err=${max_sum_err:.2f}")
    print("\nPer-ticker PnL in universe_full arm (sorted by crisis):")
    hdr = ["symbol", "trades", *regimes, "total"]
    print("  " + "  ".join(f"{h:>10}" for h in hdr))
    for row in ticker_table:
        print("  " + "  ".join(f"{row.get(h, 0):>10}" for h in hdr))
    print(f"\nfull flip:   {out['full_flip_baseline']}")
    print(f"subsets passing bar (pooled>0 too): {len(passing)}/{len(results)}")
    for r in passing[:10]:
        print(
            f"  keep={','.join(x.replace('USDT','') for x in r['keep']) or '(none)'}"
            f"  pooled={r['pooled_mean']:+.0f}  regimes={r['regime_means']}"
        )


if __name__ == "__main__":
    main()
