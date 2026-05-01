#!/usr/bin/env python3
"""V172: Ridge-regression weights on joint signal matrix, v161-era only.

Problem with V169-V171: independent per-signal Spearman IC ignores correlation
between signals. Composite is a SUM of weighted signal values; if two signals
are correlated, equal-weighting them double-counts. Ridge regression on the
joint signal matrix solves this: w = (X'X + λI)⁻¹X'y handles collinearity and
naturally dampens redundant signals.

Filtering: only v161 / v161_live / v167*_15min / v168* signal_contribs files
— anything earlier reflects different strategy logic and pollutes the IC.

Output: data/signal_ic_history.json with the Ridge weights stored under each
signal's `ic` field (so the strategy's existing IC-lookup code uses them).
Per-regime weights stored in `regime_ic` for per_regime_ic_weighting.

Usage: python3 scripts/calibrate_signal_ridge_v3.py [--lambda 1.0] [--out PATH]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEFAULT_OUT = DATA / "signal_ic_history.json"

# Eligible version prefixes (v161 era and forward — strategy logic is stable)
ELIGIBLE_PREFIXES = (
    "v161", "v167", "v168", "v167b", "v167c", "v166_live",
)


def _ridge_weights(X, y, lam: float):
    """Solve (X'X + λI)⁻¹ X'y. Returns weight vector aligned with X columns."""
    import numpy as np
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n, k = X.shape
    A = X.T @ X + lam * np.eye(k)
    b = X.T @ y
    try:
        w = np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        w = np.linalg.pinv(A) @ b
    return w


def _is_eligible(version: str) -> bool:
    return any(version.startswith(p) for p in ELIGIBLE_PREFIXES)


def _load_trade_regimes(version: str) -> dict[tuple, str]:
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
    ap.add_argument("--lam", type=float, default=1.0, help="Ridge regularization λ")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    files = []
    for p in sorted(DATA.glob("*_signal_contribs.jsonl")):
        if p.stat().st_size == 0:
            continue
        version = p.name.replace("_signal_contribs.jsonl", "")
        if _is_eligible(version):
            files.append(p)
    print(f"Filtered to {len(files)} v161-era files (eligible prefixes: {ELIGIBLE_PREFIXES})")

    # Collect per-trade rows: (signal_dict, pnl, regime)
    rows_all = []
    rows_by_regime: dict[str, list] = defaultdict(list)
    sig_seen: set[str] = set()
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
                dir_sign = 1.0 if side == "long" else -1.0
                row_signals: dict[str, float] = {}
                for t in d.get("signal_traces") or []:
                    name = t.get("name")
                    raw = t.get("value")
                    if not name or raw is None:
                        continue
                    try:
                        row_signals[name] = float(raw) * dir_sign
                    except (TypeError, ValueError):
                        continue
                    sig_seen.add(name)
                if not row_signals:
                    continue
                entry = (row_signals, pnl)
                rows_all.append(entry)
                if regime != "unknown":
                    rows_by_regime[regime].append(entry)
    print(f"Eligible trades: {len(rows_all)} pooled, "
          f"{ {r: len(v) for r, v in rows_by_regime.items()} }, "
          f"{len(sig_seen)} signals: {sorted(sig_seen)}")

    if not rows_all:
        print("No eligible data — aborting.")
        return 1

    sig_names = sorted(sig_seen)

    def _matrix(rows):
        X = [[row_signals.get(n, 0.0) for n in sig_names] for row_signals, _ in rows]
        y = [pnl for _, pnl in rows]
        return X, y

    print(f"\nRidge regression (λ={args.lam}):")
    Xall, yall = _matrix(rows_all)
    w_pooled = _ridge_weights(Xall, yall, args.lam)
    print(f"\n{'signal':<28} {'pooled w':>10}", end="")
    regime_weights: dict[str, list] = {}
    for r in sorted(rows_by_regime.keys()):
        print(f"  {r+' w':>11} {'(n)':>8}", end="")
        Xr, yr = _matrix(rows_by_regime[r])
        if len(Xr) >= max(10, len(sig_names) + 2):
            regime_weights[r] = _ridge_weights(Xr, yr, args.lam)
        else:
            regime_weights[r] = None  # too few rows
    print()
    for i, name in enumerate(sig_names):
        line = f"{name:<28} {w_pooled[i]:>+10.4f}"
        for r in sorted(rows_by_regime.keys()):
            wr = regime_weights[r]
            n = len(rows_by_regime[r])
            line += f"  {wr[i] if wr is not None else 0:>+11.4f} {n:>8}"
        print(line)

    # Normalise to [-1, +1] range so they're comparable to IC magnitudes.
    # Use the max abs of pooled weights as the scale; same scale for regime.
    import numpy as np
    scale = max(1e-6, float(np.max(np.abs(w_pooled))))
    w_norm = w_pooled / scale
    regime_norm = {
        r: (wr / scale if wr is not None else None) for r, wr in regime_weights.items()
    }

    out: dict = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "n_files_processed": len(files),
        "n_pairs": len(rows_all),
        "calibrator_version": "v3_ridge",
        "lambda": args.lam,
        "scale_factor": float(scale),
        "signals": {},
    }
    for i, name in enumerate(sig_names):
        ic = float(w_norm[i])
        regime_ic: dict[str, dict] = {}
        for r, wr in regime_norm.items():
            if wr is None:
                continue
            regime_ic[r] = {
                "ic": round(float(wr[i]), 4),
                "n": len(rows_by_regime[r]),
            }
        status = (
            "anti-predictive" if ic < -0.05 else
            "decaying" if ic < 0.0 else
            "weak" if ic < 0.05 else
            "active"
        )
        out["signals"][name] = {
            "ic": round(ic, 4),
            "n_obs": min(20, len(rows_all)),
            "n_total_pairs": len(rows_all),
            "status": status,
            "regime_ic": regime_ic,
            "obs": [],  # Ridge doesn't need raw obs (no Pearson recompute)
        }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {args.out} (calibrator=v3_ridge, λ={args.lam})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
