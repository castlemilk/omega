#!/usr/bin/env python3
"""V244 $0 offline calibration — corr-spike drop-only cap counterfactual scorer.

Scores the pre-registered (tau, s) sweep on the EXISTING V240 confirm ledgers
(32 windows, universe_selective, certified deterministic) against the frozen
walk-forward OHLCV snapshots. No training run is launched.

Detector (primary, matches the implementable mechanism): trailing 7-bar mean
pairwise Pearson correlation of daily close returns across the ACTIVE
(selective) universe, evaluated at each trade's entry bar
(entry_bar = cycle - hold_cycles + 28, validated V236). fsum-fenced.

Sensitivity (launch-prompt proxy): window-level mean pairwise correlation over
the full window; cap applies to every trade in windows above tau_w.

Counterfactual: pnl' = pnl * s for capped trades (drop-only cap is linear in
size on these ledgers). Outputs per-regime mean/p25/p50/p75 deltas per cell.

Usage: python3 scripts/v244_offline_calibration.py \
          --audit-root /Volumes/gamma-systems-2/omega-victoria-data \
          --out-json <path>
"""

import argparse
import csv
import json
import math
import os
import sys
from statistics import fsum  # alias clarity; math.fsum used below

BLACKLIST = {"BTCUSDT", "DOTUSDT", "LINKUSDT"}
LOOKBACK = 7
TAU_PCTS = [60, 70, 80, 90]
SCALES = [0.5, 0.7, 0.9]
ENTRY_OFFSET = 28  # entry_bar = cycle - hold_cycles + 28 (V236-validated)


def percentile(sorted_vals, p):
    """Linear-interpolation percentile on a pre-sorted list (numpy-style)."""
    if not sorted_vals:
        return float("nan")
    k = (len(sorted_vals) - 1) * p / 100.0
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def pearson(xs, ys):
    n = len(xs)
    mx = math.fsum(xs) / n
    my = math.fsum(ys) / n
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    sxx = math.fsum(a * a for a in dx)
    syy = math.fsum(a * a for a in dy)
    if sxx == 0.0 or syy == 0.0:
        return None  # degenerate variance: exclude pair (V221 discipline)
    return math.fsum(a * b for a, b in zip(dx, dy)) / math.sqrt(sxx * syy)


def mean_pairwise_corr(returns_by_sym, lo, hi):
    """Mean pairwise corr of returns[lo:hi] across symbols; None if <2 pairs."""
    syms = sorted(returns_by_sym)
    corrs = []
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            c = pearson(returns_by_sym[syms[i]][lo:hi], returns_by_sym[syms[j]][lo:hi])
            if c is not None:
                corrs.append(c)
    if not corrs:
        return None
    return math.fsum(corrs) / len(corrs)


def load_window(snap_path):
    snap = json.load(open(snap_path))
    rets = {}
    for sym in snap["_symbols"]:
        if sym in BLACKLIST or sym not in snap:
            continue
        closes = snap[sym]["close"]
        rets[sym] = [0.0] + [
            (closes[t] / closes[t - 1] - 1.0) if closes[t - 1] else 0.0
            for t in range(1, len(closes))
        ]
    return rets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit-root", default=os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", "data"))
    ap.add_argument("--manifest", default="data/walk_forward_manifest.json")
    ap.add_argument("--out-json", required=True)
    args = ap.parse_args()

    manifest = json.load(open(args.manifest))["windows"]
    windows = []
    pooled_detector_vals = []

    for w in manifest:
        wid = w["id"]
        regime = w["regime"]
        cell = os.path.join(
            args.audit_root, f"v240wf_{wid}_universe_selective_{regime}_determinism"
        )
        trades_csv = os.path.join(cell, f"v240wf_{wid}_universe_selective_{regime}_r1_trades.csv")
        if not os.path.exists(trades_csv):
            print(f"FATAL: missing ledger {trades_csv}", file=sys.stderr)
            sys.exit(2)
        rets = load_window(w["path"])
        n_bars = max(len(r) for r in rets.values())
        cycles = max(1, min(200, w["min_bars"] - 31))

        # Detector series over entry-capable bars.
        det = {}
        for b in range(ENTRY_OFFSET, min(n_bars, ENTRY_OFFSET + cycles)):
            c = mean_pairwise_corr(rets, b - LOOKBACK + 1, b + 1)
            if c is not None:
                det[b] = c
                pooled_detector_vals.append(c)

        # Full-window corr (sensitivity proxy).
        win_corr = mean_pairwise_corr(rets, 1, n_bars)

        trades = []
        with open(trades_csv) as f:
            for row in csv.DictReader(f):
                cyc = int(row["cycle"])
                hold = int(float(row["hold_cycles"]))
                entry_bar = cyc - hold + ENTRY_OFFSET
                trades.append(
                    {
                        "pnl": float(row["pnl"]),
                        "entry_bar": entry_bar,
                        "det": det.get(entry_bar),
                        "symbol": row["symbol"],
                    }
                )
        windows.append(
            {
                "id": wid,
                "regime": regime,
                "trades": trades,
                "win_corr": win_corr,
                "det_series": det,
            }
        )

    pooled_detector_vals.sort()
    taus = {f"p{p}": percentile(pooled_detector_vals, p) for p in TAU_PCTS}
    win_corrs_sorted = sorted(w["win_corr"] for w in windows if w["win_corr"] is not None)
    taus_w = {f"p{p}": percentile(win_corrs_sorted, p) for p in TAU_PCTS}

    def regime_stats(window_pnls):
        by = {}
        for regime in ("crisis", "trend", "recent", "pooled"):
            vals = sorted(
                v for r, v in window_pnls if regime == "pooled" or r == regime
            )
            by[regime] = {
                "n": len(vals),
                "mean": math.fsum(vals) / len(vals) if vals else float("nan"),
                "p25": percentile(vals, 25),
                "p50": percentile(vals, 50),
                "p75": percentile(vals, 75),
            }
        return by

    base_pnls = [
        (w["regime"], math.fsum(t["pnl"] for t in w["trades"])) for w in windows
    ]
    base = regime_stats(base_pnls)

    def score(mode, tau_name, tau, s):
        capped_pnls = []
        n_trades = n_capped = 0
        fired_windows = 0
        bar_fire_fracs = []
        for w in windows:
            tot = 0.0
            any_capped = False
            for t in w["trades"]:
                n_trades += 1
                if mode == "entry_bar":
                    fire = t["det"] is not None and t["det"] > tau
                else:
                    fire = w["win_corr"] is not None and w["win_corr"] > tau
                if fire:
                    tot += t["pnl"] * s
                    n_capped += 1
                    any_capped = True
                else:
                    tot += t["pnl"]
            if any_capped:
                fired_windows += 1
            if mode == "entry_bar" and w["det_series"]:
                nfire = sum(1 for v in w["det_series"].values() if v > tau)
                bar_fire_fracs.append(nfire / len(w["det_series"]))
            capped_pnls.append((w["regime"], tot))
        st = regime_stats(capped_pnls)
        delta = {
            reg: {k: st[reg][k] - base[reg][k] for k in ("mean", "p25", "p50", "p75")}
            for reg in st
        }
        return {
            "mode": mode,
            "tau_name": tau_name,
            "tau": tau,
            "scale": s,
            "trades_capped": n_capped,
            "trades_total": n_trades,
            "trade_cap_frac": n_capped / n_trades if n_trades else 0.0,
            "windows_fired": fired_windows,
            "mean_bar_fire_frac": (
                math.fsum(bar_fire_fracs) / len(bar_fire_fracs) if bar_fire_fracs else None
            ),
            "stats": st,
            "delta": delta,
        }

    cells = []
    for tau_name, tau in taus.items():
        for s in SCALES:
            cells.append(score("entry_bar", tau_name, tau, s))
    sens = []
    for tau_name, tau in taus_w.items():
        for s in SCALES:
            sens.append(score("window", tau_name, tau, s))

    # Pre-registered sanity gate.
    def gate(c):
        return c["delta"]["pooled"]["p25"] > 100.0 and c["delta"]["recent"]["mean"] > 100.0

    survivors = [c for c in cells if gate(c)]

    out = {
        "version": "v244_offline_calibration",
        "lookback": LOOKBACK,
        "taus_pooled_bar": taus,
        "taus_window": taus_w,
        "n_detector_obs": len(pooled_detector_vals),
        "baseline": base,
        "cells": cells,
        "sensitivity_window_mode": sens,
        "sanity_gate": "pooled p25-D > +$100 AND recent mean-D > +$100",
        "survivors": [
            {"tau_name": c["tau_name"], "scale": c["scale"]} for c in survivors
        ],
        "verdict": "PASS" if survivors else "REFUTED_AT_SCORING",
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    json.dump(out, open(args.out_json, "w"), indent=1)

    hdr = f"{'cell':<14}{'s':>5}{'cap%':>7}{'poolΔp25':>10}{'poolΔmean':>10}{'recΔmean':>10}{'recΔp25':>10}{'trnΔmean':>10}{'crsΔmean':>10} gate"
    print("=== V244 offline calibration (entry-bar detector, L=7) ===")
    print(f"taus: {json.dumps({k: round(v,4) for k,v in taus.items()})}")
    print(hdr)
    for c in cells:
        d = c["delta"]
        print(
            f"{c['tau_name']:<14}{c['scale']:>5}{c['trade_cap_frac']*100:>6.1f}%"
            f"{d['pooled']['p25']:>10.0f}{d['pooled']['mean']:>10.0f}"
            f"{d['recent']['mean']:>10.0f}{d['recent']['p25']:>10.0f}"
            f"{d['trend']['mean']:>10.0f}{d['crisis']['mean']:>10.0f}"
            f"  {'PASS' if gate(c) else '-'}"
        )
    print("=== sensitivity: window-level corr proxy ===")
    for c in sens:
        d = c["delta"]
        print(
            f"{c['tau_name']:<14}{c['scale']:>5}{c['trade_cap_frac']*100:>6.1f}%"
            f"{d['pooled']['p25']:>10.0f}{d['pooled']['mean']:>10.0f}"
            f"{d['recent']['mean']:>10.0f}{d['recent']['p25']:>10.0f}"
            f"{d['trend']['mean']:>10.0f}{d['crisis']['mean']:>10.0f}"
        )
    print(f"VERDICT: {out['verdict']}  survivors={out['survivors']}")


if __name__ == "__main__":
    main()
