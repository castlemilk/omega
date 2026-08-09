#!/usr/bin/env python3
"""V267 — funding-carry capacity study.

Pure offline analysis over committed/archived artifacts:
  * ledger : $AUDIT/v255_D_ext/frozen/v255c_trades.csv  (V255.D-EXT frozen basis)
  * ADV    : frozen_series/binance_intraday_raw/{SYM}/1h/{monthly,daily}
  * OI     : frozen_series/binance_futures/{SYM}/daily/metrics/{SYM}/

No network, no strategy code, no backtest. Deterministic: the only randomness is
the bootstrap, pinned to seed 42. All float reductions use math.fsum.

Gates are LOCKED in training_log/V267.md and hard-coded below.

Usage: python3 scripts/v267_capacity.py [--out data/v267_capacity.json]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
AUDIT = Path(os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", REPO / "data"))
LEDGER = AUDIT / "v255_D_ext" / "frozen" / "v255c_trades.csv"
FROZEN = AUDIT / "frozen_series"
MANIFEST = REPO / "data" / "walk_forward_manifest.json"

SEED = 42
BOOTSTRAP_N = 10_000
TRADING_DAYS_PER_YEAR = 365

# ---- LOCKED gates (V267.md §4) -------------------------------------------
G0_ADV_COVERAGE_BAR = 0.80
G0_OI_COVERAGE_BAR = 0.60
G1_SCALE_K = 100
G1_ADV_PARTICIPATION_BAR = 0.0100   # 1.00% of daily quote volume
G1_OI_PARTICIPATION_BAR = 0.0050    # 0.50% of open interest
G2_SLIPPAGE_BAR_BPS = 5.0
G2_SHARPE_TARGET = 1.0
G3_MEDIAN_FRAC_BAR = 0.50
G3_RECENT_SHARPE_BAR = 1.0

K_GRID = (1, 10, 100, 1000)
# cost multiplier for `s` bps of slippage: 2 legs x (entry + exit)
SLIPPAGE_LEG_MULT = 4.0


# ----------------------------------------------------------------- helpers


def _ts_to_dt(raw: str) -> datetime:
    """Binance archive timestamps are ms (13 digit) in older eras and us (16
    digit) in newer ones. Detect per row by magnitude — V262 P0 lesson."""
    v = int(raw)
    if v >= 10**15:
        v //= 1000
    return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc)


def _zip_rows(path: Path):
    with zipfile.ZipFile(path) as zf:
        for name in sorted(zf.namelist()):
            with zf.open(name) as fh:
                yield from csv.reader(io.TextIOWrapper(fh, encoding="utf-8"))


def load_adv(symbol: str) -> dict[date, float]:
    """Daily quote volume (USD) per UTC date, from 1h klines."""
    out: dict[date, list[float]] = defaultdict(list)
    base = FROZEN / "binance_intraday_raw" / symbol / "1h"
    files = sorted(base.glob("monthly/*.zip")) + sorted(base.glob("daily/*.zip"))
    for f in files:
        for row in _zip_rows(f):
            if not row or not row[0].lstrip("-").isdigit():
                continue  # header row in some archive eras
            d = _ts_to_dt(row[0]).date()
            out[d].append(float(row[7]))  # quote_asset_volume
    return {d: math.fsum(v) for d, v in out.items()}


def load_oi(symbol: str) -> dict[date, float]:
    """Mean open interest value (USD) per UTC date, from the metrics archive."""
    out: dict[date, list[float]] = defaultdict(list)
    base = FROZEN / "binance_futures" / symbol / "daily" / "metrics" / symbol
    if not base.exists():
        return {}
    for f in sorted(base.glob("*.zip")):
        for row in _zip_rows(f):
            if not row or row[0] == "create_time":
                continue
            try:
                d = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").date()
                val = float(row[3])  # sum_open_interest_value
            except (ValueError, IndexError):
                continue
            if val > 0:
                out[d].append(val)
    return {d: math.fsum(v) / len(v) for d, v in out.items() if v}


def pct(xs: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(xs, dtype=float), q)) if xs else float("nan")


def sharpe(daily: list[float]) -> float:
    if len(daily) < 2:
        return float("nan")
    a = np.asarray(daily, dtype=float)
    sd = float(a.std(ddof=1))
    if sd == 0.0:
        return float("nan")
    return float(a.mean() / sd * math.sqrt(TRADING_DAYS_PER_YEAR))


def boot_ci(xs: list[float], stat, n: int = BOOTSTRAP_N) -> list[float]:
    if len(xs) < 2:
        return [float("nan"), float("nan")]
    rng = np.random.default_rng(SEED)
    a = np.asarray(xs, dtype=float)
    idx = rng.integers(0, len(a), size=(n, len(a)))
    vals = np.sort(np.asarray([stat(a[i]) for i in idx], dtype=float))
    return [float(vals[int(0.025 * n)]), float(vals[int(0.975 * n)])]


def daily_book(trades: list[dict], slippage_bps: float = 0.0) -> list[float]:
    """Aggregate net PnL by exit_date, charging `slippage_bps` per leg-side."""
    by_day: dict[date, list[float]] = defaultdict(list)
    for t in trades:
        cost = t["notional"] * (slippage_bps / 1e4) * SLIPPAGE_LEG_MULT
        by_day[t["exit_date"]].append(t["pnl"] - cost)
    return [math.fsum(v) for _, v in sorted(by_day.items())]


# ----------------------------------------------------------------- loading


def load_trades() -> list[dict]:
    rows = list(csv.DictReader(LEDGER.open()))
    out = []
    for r in rows:
        out.append(
            {
                "symbol": r["symbol"],
                "entry_date": date.fromisoformat(r["entry_date"]),
                "exit_date": date.fromisoformat(r["exit_date"]),
                "regime_carry": r["entry_regime"],
                "notional": float(r["notional_usd"]),
                "pnl": float(r["pnl_usd"]),
            }
        )
    return out


def load_regime_map() -> list[tuple[date, date, str]]:
    """Independent primary walk-forward windows only (V249 rule)."""
    m = json.loads(MANIFEST.read_text())
    supp = set(m.get("_recent_supplements", {}).get("windows", []))
    out = []
    for w in m["windows"]:
        if w["id"] in supp:
            continue
        s, e = w["date_range"]
        out.append((date.fromisoformat(s), date.fromisoformat(e), w["regime"]))
    return out


def regime_of(d: date, windows) -> str | None:
    for s, e, lab in windows:
        if s <= d <= e:
            return lab
    return None


# ----------------------------------------------------------------- gates


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "data" / "v267_capacity.json"))
    args = ap.parse_args()

    trades = load_trades()
    symbols = sorted({t["symbol"] for t in trades})

    adv: dict[str, dict[date, float]] = {}
    oi: dict[str, dict[date, float]] = {}
    for s in symbols:
        adv[s] = load_adv(s)
        oi[s] = load_oi(s)

    for t in trades:
        t["adv"] = adv[t["symbol"]].get(t["entry_date"])
        t["oi"] = oi[t["symbol"]].get(t["entry_date"])
        t["edge_bps"] = 1e4 * t["pnl"] / t["notional"]

    n = len(trades)
    with_adv = [t for t in trades if t["adv"]]
    with_oi = [t for t in trades if t["oi"]]
    cov_adv = len(with_adv) / n
    cov_oi = len(with_oi) / n

    res: dict = {
        "n_trades": n,
        "symbols": symbols,
        "ledger": str(LEDGER),
        "gates_locked": {
            "G0_adv_coverage_bar": G0_ADV_COVERAGE_BAR,
            "G0_oi_coverage_bar": G0_OI_COVERAGE_BAR,
            "G1_scale_k": G1_SCALE_K,
            "G1_adv_participation_bar": G1_ADV_PARTICIPATION_BAR,
            "G1_oi_participation_bar": G1_OI_PARTICIPATION_BAR,
            "G2_slippage_bar_bps": G2_SLIPPAGE_BAR_BPS,
            "G2_sharpe_target": G2_SHARPE_TARGET,
            "G3_median_frac_bar": G3_MEDIAN_FRAC_BAR,
            "G3_recent_sharpe_bar": G3_RECENT_SHARPE_BAR,
        },
        "seed": SEED,
    }

    # ---- G0 ---------------------------------------------------------------
    res["G0"] = {
        "adv_coverage": round(cov_adv, 4),
        "oi_coverage": round(cov_oi, 4),
        "n_with_adv": len(with_adv),
        "n_with_oi": len(with_oi),
        "adv_pass": cov_adv >= G0_ADV_COVERAGE_BAR,
        "oi_pass": cov_oi >= G0_OI_COVERAGE_BAR,
        "per_symbol_adv_missing": {
            s: sum(1 for t in trades if t["symbol"] == s and not t["adv"])
            for s in symbols
        },
        "per_symbol_oi_missing": {
            s: sum(1 for t in trades if t["symbol"] == s and not t["oi"])
            for s in symbols
        },
    }

    # ---- G1: capacity envelope -------------------------------------------
    def participation(ts, field, k):
        return [k * t["notional"] / t[field] for t in ts]

    env = {}
    for k in K_GRID:
        pa = participation(with_adv, "adv", k)
        po = participation(with_oi, "oi", k)
        env[str(k)] = {
            "adv": {"median": pct(pa, 50), "p75": pct(pa, 75), "p95": pct(pa, 95)},
            "oi": {"median": pct(po, 50), "p75": pct(po, 75), "p95": pct(po, 95)},
            "median_notional_usd": pct([k * t["notional"] for t in trades], 50),
        }

    # peak concurrent gross book notional at k=1 (both legs => x2)
    day_book: dict[date, float] = defaultdict(float)
    for t in trades:
        d = t["entry_date"]
        while d <= t["exit_date"]:
            day_book[d] += t["notional"] * 2.0
            d += timedelta(days=1)
    peak_book_k1 = max(day_book.values()) if day_book else 0.0

    # max feasible k under BOTH thresholds (median participation)
    med_adv_k1 = pct(participation(with_adv, "adv", 1), 50)
    med_oi_k1 = pct(participation(with_oi, "oi", 1), 50)
    k_max_adv = G1_ADV_PARTICIPATION_BAR / med_adv_k1 if med_adv_k1 else float("inf")
    k_max_oi = G1_OI_PARTICIPATION_BAR / med_oi_k1 if med_oi_k1 else float("inf")
    k_max = min(k_max_adv, k_max_oi)

    g1_adv_ok = env[str(G1_SCALE_K)]["adv"]["median"] <= G1_ADV_PARTICIPATION_BAR
    g1_oi_ok = env[str(G1_SCALE_K)]["oi"]["median"] <= G1_OI_PARTICIPATION_BAR
    res["G1"] = {
        "envelope": env,
        "peak_concurrent_gross_book_usd_k1": peak_book_k1,
        "peak_concurrent_gross_book_usd_at_kmax": peak_book_k1 * k_max,
        "k_max_adv": k_max_adv,
        "k_max_oi": k_max_oi,
        "k_max_both": k_max,
        "adv_pass": bool(g1_adv_ok),
        "oi_pass": bool(g1_oi_ok),
        "pass": bool(g1_adv_ok and g1_oi_ok),
    }

    # ---- G2: slippage budget ---------------------------------------------
    base_daily = daily_book(trades, 0.0)
    base_sharpe = sharpe(base_daily)
    edges = [t["edge_bps"] for t in trades]
    med_edge_bps = pct(edges, 50)

    def sharpe_at(s: float) -> float:
        return sharpe(daily_book(trades, s))

    def median_net_at(s: float) -> float:
        return pct([t["pnl"] - t["notional"] * (s / 1e4) * SLIPPAGE_LEG_MULT
                    for t in trades], 50)

    # bisect on a monotone-decreasing objective, 0..200 bps, 60 iters (exact
    # to ~1e-16 bps; deterministic, no tolerance-dependent early exit)
    def bisect(fn, target: float, lo: float = 0.0, hi: float = 200.0) -> float:
        if fn(lo) < target:
            return 0.0
        if fn(hi) > target:
            return float("inf")
        for _ in range(60):
            mid = (lo + hi) / 2.0
            if fn(mid) > target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0

    s_sharpe1 = bisect(sharpe_at, G2_SHARPE_TARGET)
    s_median0 = bisect(median_net_at, 0.0)
    res["G2"] = {
        "base_sharpe_annualised": base_sharpe,
        "base_sharpe_ci95": boot_ci(base_daily, lambda a: float(
            a.mean() / a.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))
            if a.std(ddof=1) > 0 else float("nan")),
        "n_book_days": len(base_daily),
        "median_edge_bps": med_edge_bps,
        "median_edge_bps_ci95": boot_ci(edges, lambda a: float(np.median(a))),
        "slippage_to_sharpe_1_bps": s_sharpe1,
        "slippage_to_median_zero_bps": s_median0,
        "sharpe_curve": {f"{s:g}": sharpe_at(s) for s in (0, 1, 2, 3, 5, 10, 20)},
        "pass": bool(s_sharpe1 >= G2_SLIPPAGE_BAR_BPS),
    }

    # ---- G3: liquidity-conditioned edge ----------------------------------
    windows = load_regime_map()
    for t in trades:
        t["regime_wf"] = regime_of(t["exit_date"], windows)

    def tercile_report(ts: list[dict], field: str) -> dict:
        ranked = sorted(ts, key=lambda t: t[field])
        third = len(ranked) // 3
        cells = {
            "low": ranked[:third],
            "mid": ranked[third: 2 * third],
            "high": ranked[2 * third:],
        }
        out = {}
        for name, cell in cells.items():
            e = [t["edge_bps"] for t in cell]
            out[name] = {
                "n": len(cell),
                "median_edge_bps": pct(e, 50),
                "median_edge_bps_ci95": boot_ci(e, lambda a: float(np.median(a))),
                "mean_pnl_usd": math.fsum(t["pnl"] for t in cell) / len(cell),
                "total_pnl_usd": math.fsum(t["pnl"] for t in cell),
                "sharpe": sharpe(daily_book(cell, 0.0)),
                f"median_{field}_usd": pct([t[field] for t in cell], 50),
                "by_regime": {
                    reg: {
                        "n": len(sub),
                        "median_edge_bps": pct([t["edge_bps"] for t in sub], 50),
                        "total_pnl_usd": math.fsum(t["pnl"] for t in sub),
                        "sharpe": sharpe(daily_book(sub, 0.0)),
                    }
                    for reg in ("crisis", "trend", "recent")
                    if (sub := [t for t in cell if t["regime_wf"] == reg])
                },
            }
        return out

    adv_terciles = tercile_report(with_adv, "adv")
    oi_terciles = tercile_report(with_oi, "oi")

    pooled_med = pct([t["edge_bps"] for t in with_adv], 50)
    high = adv_terciles["high"]
    frac = high["median_edge_bps"] / pooled_med if pooled_med else float("nan")
    ci = high["median_edge_bps_ci95"]
    ci_excl_zero = bool((ci[0] > 0) or (ci[1] < 0))
    recent_sharpe = high["by_regime"].get("recent", {}).get("sharpe", float("nan"))
    g3_pass = bool(
        frac >= G3_MEDIAN_FRAC_BAR
        and ci_excl_zero
        and (recent_sharpe == recent_sharpe and recent_sharpe > G3_RECENT_SHARPE_BAR)
    )
    res["G3"] = {
        "pooled_median_edge_bps": pooled_med,
        "adv_terciles": adv_terciles,
        "oi_terciles": oi_terciles,
        "high_tercile_frac_of_pooled": frac,
        "high_tercile_ci_excludes_zero": ci_excl_zero,
        "high_tercile_recent_sharpe": recent_sharpe,
        "regime_coverage": {
            reg: sum(1 for t in trades if t["regime_wf"] == reg)
            for reg in ("crisis", "trend", "recent")
        },
        "n_unmapped_to_window": sum(1 for t in trades if t["regime_wf"] is None),
        "pass": g3_pass,
    }

    # ---- verdict ----------------------------------------------------------
    g0_ok = res["G0"]["adv_pass"] and res["G0"]["oi_pass"]
    passes = [res["G1"]["pass"], res["G2"]["pass"], res["G3"]["pass"]]
    if not g0_ok:
        verdict = "R4_DATA_BLOCKED"
    elif all(passes):
        verdict = "ADOPT"
    elif any(passes):
        verdict = "CAVEATED"
    else:
        verdict = "STOP"
    res["verdict"] = verdict
    res["n_gates_passed"] = sum(passes)
    res["excluded_lane_R4"] = (
        "Fitted market-impact curve Sharpe(2k/20k/200k/2M): NOT COMPUTABLE. No "
        "orderbook depth, no observed slippage, zero size variation above the "
        "$10k notional cap. Declared in V267.md section 2 before running."
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, sort_keys=True, default=str) + "\n")
    print(f"verdict={verdict} gates_passed={sum(passes)}/3 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
