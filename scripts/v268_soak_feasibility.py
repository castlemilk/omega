#!/usr/bin/env python3
"""V268 Phase-0 — feasibility audit for a SCALED funding-carry live-paper soak.

$0 analysis. Reads only committed/frozen artifacts:
  - the V255.D-EXT funding-carry ledger (1,225 trades),
  - the frozen Binance 1h intraday archives (for ADV / the tercile cut),
reusing ``scripts/v267_capacity.py``'s own loaders so the ADV tercile boundary
is *identical* to the one V267's G3 was scored against.

Two pre-registered feasibility gates (see ``training_log/V268.md`` §3):

  F1  ACCRUAL   Can a forward live-paper soak supply the blocking quantity
                (high-ADV-tercile trades in the `recent` regime) fast enough to
                narrow V267's G3 CI below the operator-specified width bar of
                1.0 within a decision-relevant horizon (<= 3 years)?

  F2  PAYLOAD   Does running the paper lane at a *scaled* notional (the V267
                capacity-relevant k) produce any measurement that the unit-size
                lane does not? i.e. is annualised Sharpe a function of k at all
                under the harness's linear cost model?

No strategy code. No flag. No network. No trade. Deterministic: pure-python
stats, ``math.fsum``, canonical sort, no RNG.

Usage:  python3 scripts/v268_soak_feasibility.py
Writes: data/v268_soak_feasibility.json
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v267_capacity as V  # noqa: E402  — reuse the audited ADV loader + percentile

LEDGER = Path(
    "/Volumes/gamma-systems-2/omega-victoria-data/v255_D_ext/frozen/v255c_trades.csv"
)
OUT = ROOT / "data" / "v268_soak_feasibility.json"

# ── Pre-registered bars (V268.md §3). Fixed before any measurement; the CI-width
# bar of 1.0 is quoted verbatim from the operator brief.
F1_CI_WIDTH_BAR = 1.0
F1_HORIZON_YEARS_BAR = 3.0
F2_SHARPE_DELTA_BAR = 0.01  # |Sharpe(k) - Sharpe(1)| must exceed this to be informative

# V267 G3, the failing leg this soak exists to adjudicate.
G3_RECENT_N = 62
G3_RECENT_CI = (-0.601, 1.193)

# The paper book's capital, from LivePaperConfig.initial_capital.
PAPER_EQUITY_USD = 100_000.0
# V267 G1: max scale under the 1%-of-ADV participation threshold.
V267_K_MAX = 315.89098865090006


def _load_trades() -> list[dict]:
    rows = list(csv.DictReader(open(LEDGER)))
    for r in rows:
        r["entry_d"] = dt.date.fromisoformat(r["entry_date"])
        r["exit_d"] = dt.date.fromisoformat(r["exit_date"])
        r["pnl"] = float(r["pnl_usd"])
        r["notional"] = float(r["notional_usd"])
    return rows


def _daily_book_pnl(rows: list[dict], k: float) -> list[float]:
    """Book PnL over EVERY calendar day the book is live, zero-filled.

    Same convention as V267 G2 (``V267_CAPACITY_VERDICT.md`` §6.1) — the
    exit-days-only variant is a known-wrong diagnostic and is not used here.
    """
    lo = min(r["entry_d"] for r in rows)
    hi = max(r["exit_d"] for r in rows)
    by_day: dict[dt.date, float] = {}
    d = lo
    while d <= hi:
        by_day[d] = 0.0
        d += dt.timedelta(days=1)
    for r in rows:
        by_day[r["exit_d"]] += r["pnl"] * k
    return [by_day[d] for d in sorted(by_day)]


def _sharpe(v: list[float]) -> float:
    m = math.fsum(v) / len(v)
    sd = math.sqrt(math.fsum((x - m) ** 2 for x in v) / (len(v) - 1))
    return m / sd * math.sqrt(365.0) if sd else 0.0


def _peak_gross_book(rows: list[dict], k: float) -> float:
    """Peak concurrent GROSS book (both hedge legs counted), same as V267 G1."""
    ev: dict[dt.date, float] = defaultdict(float)
    for r in rows:
        ev[r["entry_d"]] += 2.0 * r["notional"] * k
        ev[r["exit_d"]] -= 2.0 * r["notional"] * k
    cur = peak = 0.0
    for d in sorted(ev):
        cur += ev[d]
        peak = max(peak, cur)
    return peak


def main() -> int:
    rows = _load_trades()
    out: dict = {
        "n_trades": len(rows),
        "ledger": str(LEDGER),
        "bars_locked": {
            "F1_ci_width_bar": F1_CI_WIDTH_BAR,
            "F1_horizon_years_bar": F1_HORIZON_YEARS_BAR,
            "F2_sharpe_delta_bar": F2_SHARPE_DELTA_BAR,
        },
    }

    # ── F1: accrual rate of the blocking quantity ──────────────────────────────
    symbols = sorted({r["symbol"] for r in rows})
    adv: dict[str, dict[dt.date, float]] = {}
    for s in symbols:
        try:
            adv[s] = V.load_adv(s)
        except Exception as exc:  # pragma: no cover — archive gap is reported, never filled
            adv[s] = {}
            print(f"ADV LOAD FAIL {s}: {exc}", file=sys.stderr)
    for r in rows:
        r["adv"] = adv.get(r["symbol"], {}).get(r["entry_d"])

    with_adv = [r for r in rows if r["adv"]]
    vals = sorted(r["adv"] for r in with_adv)
    cut_high = V.pct(vals, 200.0 / 3.0)
    high = [r for r in with_adv if r["adv"] > cut_high]

    end = max(r["entry_d"] for r in rows)
    accrual: dict[str, dict] = {}
    for months in (12, 24, 36):
        since = end - dt.timedelta(days=30 * months)
        n_high = sum(1 for r in high if r["entry_d"] >= since)
        n_all = sum(1 for r in rows if r["entry_d"] >= since)
        rate = n_high / (30.0 * months)
        accrual[f"last_{months}m"] = {
            "n_high_tercile": n_high,
            "n_all": n_all,
            "high_per_day": round(rate, 6),
            "high_per_year": round(rate * 365.0, 3),
        }

    ci_w0 = G3_RECENT_CI[1] - G3_RECENT_CI[0]
    # Sharpe CI width scales ~ 1/sqrt(n): n_req = n0 * (w0 / w_target)^2.
    n_req = G3_RECENT_N * (ci_w0 / F1_CI_WIDTH_BAR) ** 2
    need = n_req - G3_RECENT_N
    horizons = {
        key: (round((need / a["high_per_day"]) / 365.0, 2) if a["high_per_day"] else None)
        for key, a in accrual.items()
    }
    best_horizon = min(h for h in horizons.values() if h is not None)
    f1_pass = best_horizon <= F1_HORIZON_YEARS_BAR

    out["F1"] = {
        "adv_coverage": round(len(with_adv) / len(rows), 4),
        "tercile_cut_high_usd": cut_high,
        "n_high_tercile_total": len(high),
        "g3_recent_n": G3_RECENT_N,
        "g3_recent_ci95": list(G3_RECENT_CI),
        "g3_recent_ci_width": round(ci_w0, 4),
        "n_required_for_ci_bar": round(n_req),
        "n_additional_required": round(need),
        "accrual": accrual,
        "years_to_bar": horizons,
        "best_case_years": best_horizon,
        "pass": bool(f1_pass),
    }

    # ── F2: does scaling notional carry any payload? ───────────────────────────
    base = _sharpe(_daily_book_pnl(rows, 1.0))
    med_notional = sorted(r["notional"] for r in rows)[len(rows) // 2]
    curve = []
    for k in (1.0, 10.0, 100.0, V267_K_MAX, 1000.0):
        s = _sharpe(_daily_book_pnl(rows, k))
        curve.append(
            {
                "k": round(k, 6),
                "median_notional_usd": round(med_notional * k, 2),
                "annualised_sharpe": s,
                "delta_vs_k1": s - base,
            }
        )
    max_delta = max(abs(c["delta_vs_k1"]) for c in curve)
    f2_pass = max_delta > F2_SHARPE_DELTA_BAR

    peak_k1 = _peak_gross_book(rows, 1.0)
    out["F2"] = {
        "base_sharpe_annualised": base,
        "sharpe_curve": curve,
        "max_abs_sharpe_delta": max_delta,
        "peak_concurrent_gross_book_usd_k1": round(peak_k1, 2),
        "peak_concurrent_gross_book_usd_at_v267_kmax": round(peak_k1 * V267_K_MAX, 2),
        "paper_equity_usd": PAPER_EQUITY_USD,
        "implied_leverage_k1": round(peak_k1 / PAPER_EQUITY_USD, 2),
        "implied_leverage_at_v267_kmax": round(peak_k1 * V267_K_MAX / PAPER_EQUITY_USD, 1),
        "pass": bool(f2_pass),
    }

    n_pass = int(f1_pass) + int(f2_pass)
    out["n_gates_passed"] = n_pass
    out["verdict"] = "PROCEED" if n_pass == 2 else "STOP"
    out["refutation_codes"] = [c for c, ok in (("R3", f1_pass), ("R5", f2_pass)) if not ok]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")

    print(f"F1 ACCRUAL : {'PASS' if f1_pass else 'FAIL'} — need {need:.0f} more "
          f"high-tercile recent trades; best-case {best_horizon} yr (bar <= {F1_HORIZON_YEARS_BAR})")
    print(f"F2 PAYLOAD : {'PASS' if f2_pass else 'FAIL'} — max |dSharpe| across k=1..1000 "
          f"= {max_delta:.3e} (bar > {F2_SHARPE_DELTA_BAR})")
    print(f"VERDICT    : {out['verdict']} ({n_pass}/2)  codes={out['refutation_codes'] or 'none'}")
    print(f"artifact   : {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
