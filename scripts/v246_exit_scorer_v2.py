#!/usr/bin/env python3
"""V246 $0 exit scorer v2 — EXACT bar-mark replay (supersedes v246_exit_scorer.py).

v1 is VOID: it credited exits at threshold levels (the engine books exits at
the breaching bar MARK) and re-described incumbent rules (the baseline already
runs a -2% ROI stop, a 50%-giveback trail with 0.5%-of-size trigger, and 6/10
time exits — omega/core/paper_trading.py mark loop).

v2 replays each ledger trade's per-bar unrealized stream from the frozen
snapshot closes (mapping validated: entry_price == close[cycle-hold+28],
exit_price == close[cycle+28]) and applies exit rules exactly as the engine
does — exits booked at the breaching MARK. Validation gate: replaying the
INCUMBENT rules must reproduce (exit_cycle, pnl) for >=95% of trades; the
counterfactual baseline is the replayed incumbent (bias cancels).

Limitations (documented, unchanged from pre-reg): per-trade transform — no
re-entry/capital modeling; bar-close marks only (the engine's own granularity).

Usage: python3 scripts/v246_exit_scorer_v2.py \
          --audit-root /Volumes/gamma-systems-2/omega-victoria-data \
          --out-json <path>
"""

import argparse
import csv
import json
import math
import os
import sys

OFFSET = 28
INCUMBENT = {"theta": 0.02, "trail_k": 0.5, "trail_m": 0.005, "hold_lose": 6, "hold_win": 10}

# OFAT sweep around the incumbent (12 non-incumbent cells), pre-registered.
SWEEP = {
    "theta": [0.01, 0.015, 0.03, 0.05],
    "trail_k": [0.25, 0.75],
    "trail_m": [0.01, 0.02],
    "hold_lose": [3, 4],
    "hold_win": [8, 14],
}


def percentile(vals, p):
    s = sorted(vals)
    if not s:
        return float("nan")
    k = (len(s) - 1) * p / 100.0
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def replay(trade, closes, max_cycle, rules):
    """Replay one trade under `rules`; return (exit_cycle, pnl)."""
    o = trade["open_cycle"]
    entry = trade["entry_price"]
    size = trade["size"]
    sgn = 1.0 if trade["side"] == "long" else -1.0
    mfe = 0.0
    t = o + 1
    while True:
        mark = closes[t + OFFSET]
        unreal = sgn * size * (mark / entry - 1.0)
        mfe = max(mfe, unreal)
        age = t - o
        roi = unreal / size
        # Engine order: time exit -> stop loss -> trailing (controller absent).
        max_hold = rules["hold_lose"] if unreal < 0 else rules["hold_win"]
        if age >= max_hold:
            return t, unreal
        if roi < -rules["theta"]:
            return t, unreal
        if mfe > rules["trail_m"] * size and unreal < rules["trail_k"] * mfe:
            return t, unreal
        if t >= max_cycle:  # end of run: force-mark at last cycle
            return t, unreal
        t += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit-root", default=os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", "data"))
    ap.add_argument("--manifest", default="data/walk_forward_manifest.json")
    ap.add_argument("--out-json", required=True)
    args = ap.parse_args()

    windows = []
    for w in json.load(open(args.manifest))["windows"]:
        wid, regime = w["id"], w["regime"]
        path = os.path.join(
            args.audit_root,
            f"v240wf_{wid}_universe_selective_{regime}_determinism",
            f"v240wf_{wid}_universe_selective_{regime}_r1_trades.csv",
        )
        if not os.path.exists(path):
            print(f"FATAL: missing {path}", file=sys.stderr)
            sys.exit(2)
        snap = json.load(open(w["path"]))
        max_cycle = max(1, min(200, w["min_bars"] - 31))
        trades = []
        with open(path) as f:
            for row in csv.DictReader(f):
                cyc = int(row["cycle"])
                hold = int(float(row["hold_cycles"]))
                trades.append(
                    {
                        "open_cycle": cyc - hold,
                        "exit_cycle": cyc,
                        "entry_price": float(row["entry_price"]),
                        "size": float(row["size"]),
                        "side": row["side"],
                        "pnl": float(row["pnl"]),
                        "symbol": row["symbol"],
                    }
                )
        windows.append(
            {
                "id": wid,
                "regime": regime,
                "trades": trades,
                "closes": {s: snap[s]["close"] for s in snap["_symbols"] if s in snap},
                "max_cycle": max_cycle,
            }
        )

    # ---- Validation: incumbent replay must reproduce the ledger ----
    n = ok_cycle = ok_pnl = 0
    mismatches = []
    for w in windows:
        for t in w["trades"]:
            n += 1
            xc, pnl = replay(t, w["closes"][t["symbol"]], w["max_cycle"], INCUMBENT)
            c_ok = xc == t["exit_cycle"]
            p_ok = abs(pnl - t["pnl"]) < 0.51
            ok_cycle += c_ok
            ok_pnl += p_ok
            if not (c_ok and p_ok) and len(mismatches) < 8:
                mismatches.append(
                    f"{w['id']}/{t['symbol']} open={t['open_cycle']} "
                    f"real=({t['exit_cycle']},{t['pnl']:.0f}) replay=({xc},{pnl:.0f})"
                )
    v_cycle, v_pnl = ok_cycle / n, ok_pnl / n
    print(f"VALIDATION: {n} trades, exit-cycle match {v_cycle:.1%}, pnl match {v_pnl:.1%}")
    for m in mismatches:
        print("  mismatch:", m)
    valid = v_cycle >= 0.95 and v_pnl >= 0.95

    def score(rules):
        window_pnls = []
        moved = 0
        total = 0
        for w in windows:
            tot = 0.0
            for t in w["trades"]:
                total += 1
                xc, pnl = replay(t, w["closes"][t["symbol"]], w["max_cycle"], rules)
                if xc != t["exit_cycle"]:
                    moved += 1
                tot += pnl
            window_pnls.append((w["regime"], tot))
        stats = {}
        for reg in ("crisis", "trend", "recent", "pooled"):
            vals = [v for r, v in window_pnls if reg == "pooled" or r == reg]
            stats[reg] = {
                "mean": math.fsum(vals) / len(vals),
                "p25": percentile(vals, 25),
                "p50": percentile(vals, 50),
                "p75": percentile(vals, 75),
            }
        return stats, moved / total

    base_stats, _ = score(INCUMBENT)

    def delta(st):
        return {
            reg: {k: st[reg][k] - base_stats[reg][k] for k in ("mean", "p25", "p50", "p75")}
            for reg in st
        }

    cells = []

    def add(label, rules):
        st, moved = score(rules)
        d = delta(st)
        cells.append(
            {
                "label": label,
                "rules": rules,
                "moved_frac": moved,
                "delta": d,
                "gate": d["pooled"]["p25"] > 100.0 and d["recent"]["mean"] > 100.0,
            }
        )

    for param, vals in SWEEP.items():
        for v in vals:
            add(f"{param}={v}", {**INCUMBENT, param: v})

    # Top-2 single-param winners combined (if any improve pooled p25).
    singles = sorted(cells, key=lambda c: -c["delta"]["pooled"]["p25"])
    tops = [c for c in singles[:2] if c["delta"]["pooled"]["p25"] > 0]
    if len(tops) == 2:
        combo = dict(INCUMBENT)
        for c in tops:
            k, v = c["label"].split("=")
            combo[k] = type(INCUMBENT[k])(float(v))
        add(f"combo:{tops[0]['label']}+{tops[1]['label']}", combo)

    survivors = [c for c in cells if c["gate"]]
    verdict = (
        "INVALID_REPLAY" if not valid else ("PASS" if survivors else "REFUTED_AT_SCORING")
    )

    out = {
        "version": "v246_exit_scorer_v2",
        "validation": {"n": n, "exit_cycle_match": v_cycle, "pnl_match": v_pnl},
        "incumbent": INCUMBENT,
        "baseline_replayed": base_stats,
        "cells": cells,
        "survivors": [c["label"] for c in survivors],
        "verdict": verdict,
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    json.dump(out, open(args.out_json, "w"), indent=1)

    print("=== V246 exit scorer v2 (exact bar-mark replay; Δ vs replayed incumbent) ===")
    print(
        f"{'cell':<28}{'moved%':>8}{'poolΔp25':>10}{'poolΔmean':>10}{'recΔmean':>10}"
        f"{'recΔp25':>10}{'trnΔmean':>10}{'crsΔmean':>10} gate"
    )
    for c in cells:
        d = c["delta"]
        print(
            f"{c['label']:<28}{c['moved_frac']*100:>7.1f}%"
            f"{d['pooled']['p25']:>10.0f}{d['pooled']['mean']:>10.0f}"
            f"{d['recent']['mean']:>10.0f}{d['recent']['p25']:>10.0f}"
            f"{d['trend']['mean']:>10.0f}{d['crisis']['mean']:>10.0f}"
            f"  {'PASS' if c['gate'] else '-'}"
        )
    print(f"VERDICT: {verdict}  survivors={out['survivors']}")


if __name__ == "__main__":
    main()
