#!/usr/bin/env python3
"""V266 — portfolio-level composition analysis of the two validated alpha lanes.

Lane A: spot Victoria, V240 selective-universe confirm grid (26 independent
        primary walk-forward windows; supplements excluded because they overlap
        their primary neighbours by 45d and would double-count days).
Lane B: funding-carry V255.C priced on the V255.D-EXT *frozen* real-basis feed
        (1,225 trades, 13 names, 2020-02-07 -> 2026-05-14).

Pure ledger analysis. Reads committed/archived artifacts only. No backtests,
no strategy code, no network. Deterministic: the only randomness is the
bootstrap, pinned to seed 42.

Usage:  python3 scripts/v266_portfolio_composition.py [--out data/v266_portfolio.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
AUDIT = Path(os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", REPO / "data"))
MANIFEST = REPO / "data" / "walk_forward_manifest.json"

# Replay geometry (omega/nodes/victoria/providers/replay.py):
#   cursor starts at `window` (=28); cycle c returns bars [c-1 : 27+c],
#   so the decision/exit bar for cycle c is series index 26 + c.
WARMUP = 28
BAR_OFFSET = WARMUP - 2  # index = BAR_OFFSET + cycle

TRADING_DAYS_PER_YEAR = 365  # crypto trades every calendar day
BOOTSTRAP_N = 10_000
SEED = 42

# Pre-registered, LOCKED gates
G1_RHO_BAR = 0.5
G2_SHARPE_MULT = 1.05
G3_DD_MULT = 0.9


# ----------------------------------------------------------------- loading


def load_manifest() -> tuple[list[dict], set[str]]:
    m = json.loads(MANIFEST.read_text())
    supplements = set(m["_recent_supplements"]["windows"])
    primaries = [w for w in m["windows"] if w["id"] not in supplements]
    return primaries, supplements


def victoria_cell_dir(window_id: str, regime: str) -> Path:
    return AUDIT / f"v240wf_{window_id}_universe_selective_{regime}_determinism"


def load_victoria(primaries: list[dict]) -> tuple[dict[date, float], set[date], dict]:
    """Return (daily pnl by date, observed-day set, provenance)."""
    daily: dict[date, float] = defaultdict(float)
    observed: set[date] = set()
    prov: dict = {"windows": [], "missing": [], "n_trades": 0}

    for w in primaries:
        wid = w["id"]
        regime = w["regime"]
        start = date.fromisoformat(w["date_range"][0])
        nbars = int(w.get("min_bars", 91))
        n_cycles = nbars - WARMUP  # total_steps in the replay provider

        # Every day the strategy was live in this window is an OBSERVED day —
        # a no-trade day there is a genuine $0, not a gap.
        for c in range(1, n_cycles + 1):
            observed.add(start + timedelta(days=BAR_OFFSET + c))

        cell = victoria_cell_dir(wid, regime)
        matches = sorted(cell.glob("*_r1_trades.csv"))
        if not matches:
            prov["missing"].append(wid)
            continue

        n = 0
        pnl_sum = 0.0
        with matches[0].open() as fh:
            for row in csv.DictReader(fh):
                cycle = int(row["cycle"])
                if cycle > n_cycles:
                    # Beyond series end the replay provider WRAPS (V235 seam
                    # hazard). Confirm-grid cells are capped, so this should
                    # never fire; drop defensively rather than book fiction.
                    prov.setdefault("seam_dropped", []).append(f"{wid}:c{cycle}")
                    continue
                d = start + timedelta(days=BAR_OFFSET + cycle)
                pnl = float(row["pnl"])
                daily[d] += pnl
                pnl_sum += pnl
                n += 1
        prov["windows"].append(
            {
                "id": wid,
                "regime": regime,
                "n_trades": n,
                "pnl": round(pnl_sum, 2),
                "ledger": matches[0].name,
            }
        )
        prov["n_trades"] += n

    return dict(daily), observed, prov


def load_funding() -> tuple[dict[date, float], dict[date, int], dict]:
    path = AUDIT / "v255_D_ext" / "frozen" / "v255c_trades.csv"
    if not path.exists():  # fall back to the pre-extension V255.C ledger
        path = AUDIT / "v255_C" / "v255c_trades.csv"
    daily: dict[date, float] = defaultdict(float)
    counts: dict[date, int] = defaultdict(int)
    n = 0
    total = 0.0
    symbols: set[str] = set()
    with path.open() as fh:
        for row in csv.DictReader(fh):
            d = date.fromisoformat(row["exit_date"])
            pnl = float(row["pnl_usd"])
            daily[d] += pnl
            counts[d] += 1
            total += pnl
            symbols.add(row["symbol"])
            n += 1
    return (
        dict(daily),
        dict(counts),
        {
            "ledger": str(path),
            "n_trades": n,
            "total_pnl": round(total, 2),
            "symbols": sorted(symbols),
        },
    )


# ----------------------------------------------------------------- stats


def max_drawdown(pnl: np.ndarray) -> float:
    """Max peak-to-trough decline of the cumulative PnL curve, in dollars."""
    equity = np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[0.0], equity]))[1:]
    return float(np.max(peak - equity))


def sharpe(pnl: np.ndarray) -> float:
    sd = float(np.std(pnl, ddof=1))
    if sd == 0.0:
        return 0.0
    return float(np.mean(pnl)) / sd * math.sqrt(TRADING_DAYS_PER_YEAR)


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    if np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def rankdata(x: np.ndarray) -> np.ndarray:
    """Average-rank transform (ties averaged), no scipy dependency."""
    order = np.argsort(x, kind="stable")
    ranks = np.empty(len(x), dtype=float)
    sx = x[order]
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and sx[j + 1] == sx[i]:
            j += 1
        ranks[order[i : j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    return ranks


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    return pearson(rankdata(a), rankdata(b))


def bootstrap_ci(fn, *arrays, n: int = BOOTSTRAP_N, seed: int = SEED) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    m = len(arrays[0])
    vals = np.empty(n)
    for i in range(n):
        idx = rng.integers(0, m, m)
        vals[i] = fn(*(arr[idx] for arr in arrays))
    finite = vals[np.isfinite(vals)]
    return float(np.percentile(finite, 2.5)), float(np.percentile(finite, 97.5))


# ----------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "data" / "v266_portfolio.json"))
    args = ap.parse_args()

    primaries, supplements = load_manifest()
    vic_daily, observed, vic_prov = load_victoria(primaries)
    fun_daily, fun_counts, fun_prov = load_funding()

    if vic_prov["missing"]:
        print(f"FATAL: missing Victoria cells: {vic_prov['missing']}", file=sys.stderr)
        return 2

    # ---- Phase 1: common daily series -------------------------------------
    # Victoria's observed days are the ONLY days on which both lanes have a
    # defined value. Outside a walk-forward window Victoria is not flat, it is
    # unobserved -- treating those days as $0 would manufacture correlation.
    fun_days_all = set(fun_daily)
    days = sorted(d for d in observed if d >= min(fun_days_all) and d <= max(fun_days_all))

    v = np.array([vic_daily.get(d, 0.0) for d in days])
    f = np.array([fun_daily.get(d, 0.0) for d in days])

    # Reconciliation: the common range is bounded by the funding ledger, which
    # trims Victoria's leading days (snap_wf_20200101 starts 2020-01-28, before
    # the first funding exit) and trailing days (snap_wf_20260228 runs past the
    # last funding exit). Disclose the PnL that trimming removes so the overlap
    # numbers can be tied back to the published V240 confirm table.
    vic_full = sum(vic_daily.values())
    trimmed = round(vic_full - float(v.sum()), 2)
    by_regime_full: dict[str, list[float]] = defaultdict(list)
    for rec in vic_prov["windows"]:
        by_regime_full[rec["regime"]].append(rec["pnl"])
    reconciliation = {
        "victoria_pnl_all_observed_days": round(vic_full, 2),
        "victoria_pnl_in_common_range": round(float(v.sum()), 2),
        "victoria_pnl_trimmed_by_range_bound": trimmed,
        "victoria_window_means_full": {
            k: round(sum(x) / len(x), 2) for k, x in sorted(by_regime_full.items())
        },
        "victoria_window_counts_full": {k: len(x) for k, x in sorted(by_regime_full.items())},
        "note": (
            "crisis/trend window means reconcile EXACTLY with the published V240 "
            "confirm table (crisis +598.53 n=12, trend +2996.92 n=10). recent "
            "differs because V266 uses only the 4 INDEPENDENT primary recent "
            "windows; the published +29.64 is over 10 nominal windows including "
            "the 6 overlapping +/-45d supplements (V249 independent-N rule)."
        ),
    }

    phase1 = {
        "date_range": [days[0].isoformat(), days[-1].isoformat()],
        "reconciliation": reconciliation,
        "n_days": len(days),
        "n_windows_used": len(primaries),
        "n_windows_excluded_overlapping": len(supplements),
        "victoria": {
            "days_with_trade": int(np.sum(v != 0)),
            "n_trades": vic_prov["n_trades"],
            "total_pnl": round(float(v.sum()), 2),
            "mean_daily": round(float(v.mean()), 4),
            "std_daily": round(float(v.std(ddof=1)), 4),
        },
        "funding": {
            "days_with_trade": int(np.sum(f != 0)),
            "n_trades_in_window": int(
                sum(c for d, c in fun_counts.items() if days[0] <= d <= days[-1] and d in observed)
            ),
            "n_exit_dates_in_window": int(
                sum(1 for d in fun_daily if d in observed and days[0] <= d <= days[-1])
            ),
            "n_trades_total": fun_prov["n_trades"],
            "total_pnl_in_window": round(float(f.sum()), 2),
            "total_pnl_all": fun_prov["total_pnl"],
            "mean_daily": round(float(f.mean()), 4),
            "std_daily": round(float(f.std(ddof=1)), 4),
        },
    }

    # ---- Phase 2: G1 correlation ------------------------------------------
    rho = pearson(v, f)
    rho_lo, rho_hi = bootstrap_ci(pearson, v, f)
    rho_s = spearman(v, f)
    rho_s_lo, rho_s_hi = bootstrap_ci(spearman, v, f)
    g1_pass = bool(rho < G1_RHO_BAR)
    phase2 = {
        "pearson_rho": round(rho, 6),
        "pearson_ci95": [round(rho_lo, 6), round(rho_hi, 6)],
        "spearman_rho": round(rho_s, 6),
        "spearman_ci95": [round(rho_s_lo, 6), round(rho_s_hi, 6)],
        "bar": G1_RHO_BAR,
        "pass": g1_pass,
    }

    # ---- Phase 3: G2 Sharpe composition -----------------------------------
    sv, sf = sharpe(v), sharpe(f)
    best_single = max(sv, sf)

    w_eq = (0.5, 0.5)
    sd_v, sd_f = float(np.std(v, ddof=1)), float(np.std(f, ddof=1))
    inv = np.array([1.0 / sd_v, 1.0 / sd_f])
    w_rp = tuple(inv / inv.sum())

    mu = np.array([v.mean(), f.mean()])
    cov = np.cov(np.vstack([v, f]), ddof=1)
    w_raw = np.linalg.solve(cov, mu)
    w_mv = tuple(w_raw / w_raw.sum())

    def comb(w):
        return w[0] * v + w[1] * f

    s_eq, s_rp, s_mv = sharpe(comb(w_eq)), sharpe(comb(w_rp)), sharpe(comb(w_mv))
    eq_lo, eq_hi = bootstrap_ci(lambda a, b: sharpe(0.5 * a + 0.5 * b), v, f)
    g2_bar = best_single * G2_SHARPE_MULT
    g2_pass = bool(s_eq > g2_bar)

    phase3 = {
        "sharpe_victoria": round(sv, 4),
        "sharpe_funding": round(sf, 4),
        "best_single": round(best_single, 4),
        "bar_1.05x_best_single": round(g2_bar, 4),
        "sharpe_equal_weight_50_50": round(s_eq, 4),
        "sharpe_equal_weight_ci95": [round(eq_lo, 4), round(eq_hi, 4)],
        "sharpe_risk_parity": round(s_rp, 4),
        "weights_risk_parity": [round(w_rp[0], 6), round(w_rp[1], 6)],
        "sharpe_mean_variance_tangency": round(s_mv, 4),
        "weights_mean_variance": [round(w_mv[0], 6), round(w_mv[1], 6)],
        "pass": g2_pass,
    }

    # ---- Phase 4: G3 tail protection --------------------------------------
    dd_v, dd_f = max_drawdown(v), max_drawdown(f)
    dd_eq = max_drawdown(comb(w_eq))
    dd_rp = max_drawdown(comb(w_rp))
    g3_bar = G3_DD_MULT * min(dd_v, dd_f)
    g3_pass = bool(dd_eq < g3_bar)

    # Scale-normalised diagnostic: the two lanes run at wildly different
    # notional, so a raw-dollar drawdown comparison is dominated by the larger
    # book. Rescale each lane to unit daily sigma before combining.
    vz, fz = v / sd_v, f / sd_f
    dd_vz, dd_fz, dd_cz = max_drawdown(vz), max_drawdown(fz), max_drawdown(0.5 * (vz + fz))

    phase4 = {
        "max_dd_victoria": round(dd_v, 2),
        "max_dd_funding": round(dd_f, 2),
        "max_dd_equal_weight": round(dd_eq, 2),
        "max_dd_risk_parity": round(dd_rp, 2),
        "bar_0.9x_min_single": round(g3_bar, 2),
        "pass": g3_pass,
        "sigma_normalised_diagnostic": {
            "max_dd_victoria_sigma_units": round(dd_vz, 4),
            "max_dd_funding_sigma_units": round(dd_fz, 4),
            "max_dd_combined_sigma_units": round(dd_cz, 4),
            "combined_vs_min_single_ratio": round(dd_cz / min(dd_vz, dd_fz), 4),
        },
    }

    # ---- Supplementary diagnostics (NOT gates; gates stay locked) ---------
    # (a) Joint-trade-day subset. 1,375 of 1,590 days are joint zeros, which
    #     mechanically attenuates rho toward 0. Re-measure where both traded.
    both = (v != 0) & (f != 0)
    diag_both = None
    if int(both.sum()) >= 10:
        vb, fb = v[both], f[both]
        r_both = pearson(vb, fb)
        lo_b, hi_b = bootstrap_ci(pearson, vb, fb)
        diag_both = {
            "n_days": int(both.sum()),
            "pearson_rho": round(r_both, 6),
            "pearson_ci95": [round(lo_b, 6), round(hi_b, 6)],
        }

    # (b) Window-level PnL correlation across the 26 independent windows.
    wmap = {w["id"]: w for w in primaries}
    wv, wf, wreg = [], [], []
    for rec in vic_prov["windows"]:
        w = wmap[rec["id"]]
        start = date.fromisoformat(w["date_range"][0])
        n_cycles = int(w.get("min_bars", 91)) - WARMUP
        lo = start + timedelta(days=BAR_OFFSET + 1)
        hi = start + timedelta(days=BAR_OFFSET + n_cycles)
        wv.append(rec["pnl"])
        wf.append(sum(p for d, p in fun_daily.items() if lo <= d <= hi))
        wreg.append(rec["regime"])
    wv_a, wf_a = np.array(wv), np.array(wf)
    r_win = pearson(wv_a, wf_a)
    lo_w, hi_w = bootstrap_ci(pearson, wv_a, wf_a)

    # (c) Per-regime daily correlation — does the diversification survive
    #     exactly when it matters (crisis)?
    per_regime = {}
    for regime in ("crisis", "trend", "recent"):
        mask = np.zeros(len(days), dtype=bool)
        for rec in vic_prov["windows"]:
            if rec["regime"] != regime:
                continue
            w = wmap[rec["id"]]
            start = date.fromisoformat(w["date_range"][0])
            n_cycles = int(w.get("min_bars", 91)) - WARMUP
            lo = start + timedelta(days=BAR_OFFSET + 1)
            hi = start + timedelta(days=BAR_OFFSET + n_cycles)
            for i, d in enumerate(days):
                if lo <= d <= hi:
                    mask[i] = True
        if mask.sum() < 30:
            continue
        vr, fr = v[mask], f[mask]
        per_regime[regime] = {
            "n_days": int(mask.sum()),
            "pearson_rho": round(pearson(vr, fr), 6),
            "sharpe_victoria": round(sharpe(vr), 4),
            "sharpe_funding": round(sharpe(fr), 4),
            "pnl_victoria": round(float(vr.sum()), 2),
            "pnl_funding": round(float(fr.sum()), 2),
        }

    # (d) Is the tangency uplift over the best single lane real, or noise?
    #     Refit the weights inside each bootstrap resample (honest: no
    #     in-sample weight leakage across resamples).
    def tangency_ratio(a, b):
        m = np.array([a.mean(), b.mean()])
        c = np.cov(np.vstack([a, b]), ddof=1)
        try:
            wr = np.linalg.solve(c, m)
        except np.linalg.LinAlgError:
            return float("nan")
        if wr.sum() == 0:
            return float("nan")
        wn = wr / wr.sum()
        best = max(sharpe(a), sharpe(b))
        if best <= 0:
            return float("nan")
        return sharpe(wn[0] * a + wn[1] * b) / best

    t_lo, t_hi = bootstrap_ci(tangency_ratio, v, f)

    diagnostics = {
        "joint_trade_days": diag_both,
        "window_level": {
            "n_windows": len(wv),
            "pearson_rho": round(r_win, 6),
            "pearson_ci95": [round(lo_w, 6), round(hi_w, 6)],
        },
        "per_regime_daily": per_regime,
        "tangency_uplift_over_best_single": {
            "point": round(s_mv / best_single, 4),
            "ci95": [round(t_lo, 4), round(t_hi, 4)],
            "note": (
                "Weights refit inside each resample. Point estimate is still "
                "in-sample on the full period; G2 is pre-registered on the "
                "50/50 leg and is NOT re-scored against this."
            ),
        },
    }

    n_pass = sum([g1_pass, g2_pass, g3_pass])
    verdict = "ADOPT" if n_pass == 3 else ("STOP" if n_pass == 0 else "CAVEATED")

    out = {
        "version": "V266",
        "analysis": "portfolio composition — spot Victoria x funding-carry V255.C",
        "provenance": {
            "audit_dir": str(AUDIT),
            "victoria": vic_prov,
            "funding": fun_prov,
            "replay_geometry": {"warmup_bars": WARMUP, "exit_bar_index": "26 + cycle"},
            "bootstrap": {"n": BOOTSTRAP_N, "seed": SEED},
        },
        "phase1_alignment": phase1,
        "phase2_G1_correlation": phase2,
        "phase3_G2_sharpe": phase3,
        "phase4_G3_drawdown": phase4,
        "supplementary_diagnostics": diagnostics,
        "gates": {"G1": g1_pass, "G2": g2_pass, "G3": g3_pass, "n_pass": n_pass},
        "verdict": verdict,
    }

    Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
