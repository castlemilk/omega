#!/usr/bin/env python3
"""V255.D-extended — per-symbol distributional read of the funding-carry book.

Reads the two ``v255c_trades.csv`` ledgers emitted by ``v255c_scorer`` (one under
``--basis-source zero``, one under ``--basis-source frozen``) and reports, per
symbol: N, mean/median net PnL, win rate, profit factor, annualized net, and the
zero→frozen median delta. Read-only over the scorer's own CSV output — touches no
strategy code and no scorer logic. The scorer applies REAL basis only to symbols
with a frozen mark+index pair, so the frozen ledger's per-symbol median is the
real-basis number for the covered names and identical to zero for the rest.

Usage:
  python3 scripts/v255d_per_symbol_basis.py \
    --zero  <dir>/zero/v255c_trades.csv \
    --frozen <dir>/frozen/v255c_trades.csv \
    [--out-json <path>]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict

HOLD_DAYS = 7  # V255.C HoldScaledParams default (level-scaled 7d hold)


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _profit_factor(pnls: list[float]) -> float:
    gains = math.fsum(p for p in pnls if p > 0)
    losses = -math.fsum(p for p in pnls if p < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def _load(path: str) -> dict[str, list[dict]]:
    """symbol -> list of trade rows (pnl_usd, notional_usd, funding_ret proxy)."""
    by_sym: dict[str, list[dict]] = defaultdict(list)
    with open(path) as fh:
        for row in csv.DictReader(fh):
            by_sym[row["symbol"]].append(
                {
                    "pnl": float(row["pnl_usd"]),
                    "notional": float(row["notional_usd"]),
                }
            )
    return by_sym


def _sym_stats(rows: list[dict]) -> dict:
    pnls = [r["pnl"] for r in rows]
    n = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    # annualized net return: mean per-trade (pnl/notional) * 365/hold_days
    rets = [r["pnl"] / r["notional"] for r in rows if r["notional"]]
    mean_ret = math.fsum(rets) / len(rets) if rets else 0.0
    return {
        "n": n,
        "mean": round(math.fsum(pnls) / n, 4) if n else 0.0,
        "median": round(_median(pnls), 4),
        "total": round(math.fsum(pnls), 2),
        "win_rate": round(wins / n, 4) if n else 0.0,
        "profit_factor": round(_profit_factor(pnls), 4),
        "annualized_net_pct": round(mean_ret * (365.0 / HOLD_DAYS) * 100.0, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zero", required=True)
    ap.add_argument("--frozen", required=True)
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args()

    zero = _load(args.zero)
    frozen = _load(args.frozen)
    syms = sorted(set(zero) | set(frozen))

    report = {}
    print(f"{'SYMBOL':9} {'N':>4} {'z_med':>9} {'f_med':>9} {'Δmed':>9} "
          f"{'f_WR':>6} {'f_PF':>7} {'f_ann%':>8}")
    for s in syms:
        zs = _sym_stats(zero.get(s, []))
        fs = _sym_stats(frozen.get(s, []))
        dmed = round(fs["median"] - zs["median"], 4)
        report[s] = {"zero": zs, "frozen": fs, "median_delta_frozen_minus_zero": dmed}
        print(f"{s:9} {fs['n']:>4} {zs['median']:>9.4f} {fs['median']:>9.4f} "
              f"{dmed:>9.4f} {fs['win_rate']:>6.3f} {fs['profit_factor']:>7.3f} "
              f"{fs['annualized_net_pct']:>8.2f}")

    # pooled
    all_zero = [r["pnl"] for rows in zero.values() for r in rows]
    all_frozen = [r["pnl"] for rows in frozen.values() for r in rows]
    pooled = {
        "n": len(all_frozen),
        "zero_median": round(_median(all_zero), 4),
        "frozen_median": round(_median(all_frozen), 4),
    }
    print(f"\nPOOLED n={pooled['n']}  zero_median={pooled['zero_median']}  "
          f"frozen_median={pooled['frozen_median']}")
    report["_pooled"] = pooled

    if args.out_json:
        with open(args.out_json, "w") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        print(f"\nwrote {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
