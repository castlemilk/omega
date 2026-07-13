#!/usr/bin/env python3
"""V248 $0 scorer — regime-conditional exit params, exact bar-mark replay.

Extends the VALIDATED v246_exit_scorer_v2 replay (entry_price ==
close[cycle-hold+28], exits booked at the breaching MARK, engine rule order)
with regime-conditional rules: the rules applied at mark cycle t are those of
the runtime regime at cycle t-1 (matching the engine's 1-cycle-lag
set_current_regime push; cycle<=1 and missing cycles default to 'normal').
The per-cycle runtime regime series is read from each window's committed
v240wf_*_r1_signal_fingerprint.jsonl (the OFF baseline run's own trace, so
replay and engine see the identical series by construction).

Pre-registered sweep (V248.md): per-regime OFAT around the incumbent —
trail_k in {0.25, 0.75}, hold_win in {8, 14}, hold_lose in {4} — one regime
perturbed per cell (15 cells), plus a composition cell taking each regime's
best positive-pooled-mean single cell.

Pre-registered scorer gate (V248.md — no grid unless some cell passes):
  predicted pooled mean-D >= +$625
  AND predicted recent mean-D >= -$360
  AND predicted pooled level-p25 not worsened (d pooled p25 >= 0)

Validation gate unchanged: incumbent replay reproduces >=95% of
(exit_cycle, pnl). Limitations unchanged: per-trade transform, no
re-entry/capital modeling (the V247 re-entry counter reports that channel on
the grid, where it is measured for real).

Usage: python3 scripts/v248_exit_scorer.py \
          --audit-root /Volumes/gamma-systems-2/omega-victoria-data \
          --out-json <path>
"""

import argparse
import copy
import csv
import json
import math
import os
import sys

OFFSET = 28
REGIMES = ("normal", "high_vol", "crisis")
INCUMBENT_PARAMS = {"trail_k": 0.5, "hold_win": 10, "hold_lose": 6}
THETA = 0.02  # legacy stop, not swept in V248 (same posture as V246 winner)
TRAIL_M = 0.005

SWEEP = {"trail_k": [0.25, 0.75], "hold_win": [8, 14], "hold_lose": [4]}

# Pre-registered scorer gate (V248.md)
GATE_POOLED_MEAN = 625.0
GATE_RECENT_MEAN = -360.0


def incumbent_rules():
    return {r: dict(INCUMBENT_PARAMS) for r in REGIMES}


def percentile(vals, p):
    s = sorted(vals)
    if not s:
        return float("nan")
    k = (len(s) - 1) * p / 100.0
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def replay(trade, closes, max_cycle, rules_by_regime, regime_at):
    """Replay one trade under per-regime rules; return (exit_cycle, pnl)."""
    o = trade["open_cycle"]
    entry = trade["entry_price"]
    size = trade["size"]
    sgn = 1.0 if trade["side"] == "long" else -1.0
    mfe = 0.0
    t = o + 1
    while True:
        rules = rules_by_regime.get(regime_at(t), rules_by_regime["normal"])
        mark = closes[t + OFFSET]
        unreal = sgn * size * (mark / entry - 1.0)
        mfe = max(mfe, unreal)
        age = t - o
        roi = unreal / size
        # Engine order: time exit -> stop loss -> trailing (controller absent).
        max_hold = rules["hold_lose"] if unreal < 0 else rules["hold_win"]
        if age >= max_hold:
            return t, unreal
        if roi < -THETA:
            return t, unreal
        if mfe > TRAIL_M * size and unreal < rules["trail_k"] * mfe:
            return t, unreal
        if t >= max_cycle:  # end of run: force-mark at last cycle
            return t, unreal
        t += 1


def load_regime_series(path):
    """cycle -> runtime regime, from the OFF run's signal_fingerprint.jsonl."""
    series = {}
    with open(path) as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            reg = row.get("regime")
            if reg:
                series[int(row["cycle"])] = str(reg)
    return series


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit-root", default=os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", "data"))
    ap.add_argument("--manifest", default="data/walk_forward_manifest.json")
    ap.add_argument("--out-json", required=True)
    args = ap.parse_args()

    windows = []
    for w in json.load(open(args.manifest))["windows"]:
        wid, wregime = w["id"], w["regime"]
        base = os.path.join(args.audit_root, f"v240wf_{wid}_universe_selective_{wregime}")
        trades_path = os.path.join(
            args.audit_root,
            f"v240wf_{wid}_universe_selective_{wregime}_determinism",
            f"v240wf_{wid}_universe_selective_{wregime}_r1_trades.csv",
        )
        fp_path = base + "_r1_signal_fingerprint.jsonl"
        for p in (trades_path, fp_path):
            if not os.path.exists(p):
                print(f"FATAL: missing {p}", file=sys.stderr)
                sys.exit(2)
        snap = json.load(open(w["path"]))
        max_cycle = max(1, min(200, w["min_bars"] - 31))
        trades = []
        with open(trades_path) as f:
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
        regime_series = load_regime_series(fp_path)
        windows.append(
            {
                "id": wid,
                "regime": wregime,
                "trades": trades,
                "closes": {s: snap[s]["close"] for s in snap["_symbols"] if s in snap},
                "max_cycle": max_cycle,
                "regime_series": regime_series,
            }
        )

    def regime_at_factory(series):
        # marks at cycle t are governed by the regime computed at t-1
        # (engine 1-cycle lag); missing/first cycles default to normal.
        def regime_at(t):
            return series.get(t - 1, "normal")

        return regime_at

    # ---- Validation: incumbent replay must reproduce the ledger ----
    inc = incumbent_rules()
    n = ok_cycle = ok_pnl = 0
    mismatches = []
    for w in windows:
        ra = regime_at_factory(w["regime_series"])
        for t in w["trades"]:
            n += 1
            xc, pnl = replay(t, w["closes"][t["symbol"]], w["max_cycle"], inc, ra)
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

    def score(rules_by_regime):
        window_pnls = []
        moved = 0
        total = 0
        for w in windows:
            ra = regime_at_factory(w["regime_series"])
            tot = 0.0
            for t in w["trades"]:
                total += 1
                xc, pnl = replay(
                    t, w["closes"][t["symbol"]], w["max_cycle"], rules_by_regime, ra
                )
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

    base_stats, _ = score(inc)

    def delta(st):
        return {
            reg: {k: st[reg][k] - base_stats[reg][k] for k in ("mean", "p25", "p50", "p75")}
            for reg in st
        }

    cells = []

    def add(label, rules_by_regime):
        st, moved = score(rules_by_regime)
        d = delta(st)
        cells.append(
            {
                "label": label,
                "rules": rules_by_regime,
                "moved_frac": moved,
                "delta": d,
                # Pre-registered scorer gate (V248.md): pooled mean, recent
                # mean floor, pooled LEVEL-p25 not worsened.
                "gate": (
                    d["pooled"]["mean"] >= GATE_POOLED_MEAN
                    and d["recent"]["mean"] >= GATE_RECENT_MEAN
                    and d["pooled"]["p25"] >= 0.0
                ),
            }
        )

    for reg in REGIMES:
        for param, vals in SWEEP.items():
            for v in vals:
                rules = incumbent_rules()
                rules[reg][param] = v
                add(f"{reg}:{param}={v}", rules)

    # Composition: each regime's best positive-pooled-mean single cell.
    combo = incumbent_rules()
    picked = []
    for reg in REGIMES:
        reg_cells = [c for c in cells if c["label"].startswith(f"{reg}:")]
        best = max(reg_cells, key=lambda c: c["delta"]["pooled"]["mean"])
        if best["delta"]["pooled"]["mean"] > 0:
            param, v = best["label"].split(":")[1].split("=")
            combo[reg][param] = type(INCUMBENT_PARAMS[param])(float(v))
            picked.append(best["label"])
    if picked:
        add("combo:" + "+".join(picked), copy.deepcopy(combo))

    survivors = [c for c in cells if c["gate"]]
    verdict = (
        "INVALID_REPLAY" if not valid else ("PASS" if survivors else "REFUTED_AT_SCORING")
    )

    out = {
        "version": "v248_exit_scorer",
        "validation": {"n": n, "exit_cycle_match": v_cycle, "pnl_match": v_pnl},
        "incumbent": inc,
        "gate": {
            "pooled_mean": GATE_POOLED_MEAN,
            "recent_mean": GATE_RECENT_MEAN,
            "pooled_level_p25": 0.0,
        },
        "baseline_replayed": base_stats,
        "cells": cells,
        "survivors": [c["label"] for c in survivors],
        "verdict": verdict,
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    json.dump(out, open(args.out_json, "w"), indent=1)

    print("=== V248 exit scorer (regime-conditional; Δ vs replayed incumbent) ===")
    print(
        f"{'cell':<38}{'moved%':>8}{'poolΔmean':>10}{'poolΔp25':>10}{'recΔmean':>10}"
        f"{'trnΔmean':>10}{'crsΔmean':>10} gate"
    )
    for c in cells:
        d = c["delta"]
        print(
            f"{c['label']:<38}{c['moved_frac']*100:>7.1f}%"
            f"{d['pooled']['mean']:>10.0f}{d['pooled']['p25']:>10.0f}"
            f"{d['recent']['mean']:>10.0f}"
            f"{d['trend']['mean']:>10.0f}{d['crisis']['mean']:>10.0f}"
            f"  {'PASS' if c['gate'] else '-'}"
        )
    print(f"VERDICT: {verdict}  survivors={out['survivors']}")


if __name__ == "__main__":
    main()
