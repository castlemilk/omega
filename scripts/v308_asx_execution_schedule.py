#!/usr/bin/env python3
"""V308 — re-price V304's quarterly ASX book under explicit execution schedules.

Pre-registration: ``training_log/V308_ASX_EXECUTION.md``. Pure re-computation on
the frozen v3 substrate; writes ONE file (``data/asx_runs/v308_execution_schedule.json``).
Nothing here trades or sizes a live book.

The V299/V301/V304 capacity tables were produced in-session and never committed.
This script is the committed version, and F0 gates it on reproducing V304's row
before the new axis (``s``, the share of ADV a schedule can reach) is reported.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from omega.nodes.asx.engine import CostModel, run  # noqa: E402
from omega.nodes.asx.panel import ApiPriceSource, PanelSpec, load_short_series_csv  # noqa: E402
from omega.nodes.asx.portfolio import PortfolioSpec  # noqa: E402

V3 = ROOT / "data" / "frozen_series" / "asx" / "v3"
OUT = ROOT / "data" / "asx_runs" / "v308_execution_schedule.json"

# --- pre-registered (V308 §3–§4) -------------------------------------------------
HOLD_SESSIONS = 63
START = "2016-01-01"
CALENDAR_CODE = "BHP"  # a continuous large cap defines the session calendar
SIGMA_WINDOW = 60
SIGMA_MIN_OBS = 40
AUM_GRID_M = (1.0, 5.0, 20.0, 50.0)
K_GRID = (0.25, 0.5, 1.0)
# share of ADV reachable by the schedule (V307 5m volume profile)
SCHEDULES = {"full_day_vwap": 1.00, "last_hour_plus_auction": 0.47, "auction_only": 0.36}
V304_ROW = {"1": 4.87, "5": 4.00, "20": 2.52, "50": 1.39}  # % / yr, 63d, all eligible, k=0.5
F0_TOL_PP = 0.75
F2_TOL = 0.15
PERIODS_PER_YEAR = 252 / HOLD_SESSIONS

PORT = PortfolioSpec(top_quantile=0.20, max_names=10_000, max_weight=0.08, long_only=True)
PANEL = PanelSpec(
    label="v3-pit-quarterly",
    survivorship_safe=True,
    price_source="shorted-api-v3",
    notes="V308: V304 configuration, quarterly dates, weights recorded",
)


# ---------------------------------------------------------------------------
# substrate
# ---------------------------------------------------------------------------
def quarterly_dates(prices: ApiPriceSource) -> list[str]:
    cal = sorted(d for d in prices.closes(CALENDAR_CODE) if d >= START)
    return cal[::HOLD_SESSIONS]


def trailing_sigma(closes: dict[str, float]) -> dict[str, float]:
    """Trailing-60-session sd of daily simple returns, keyed by date, point-in-time."""
    days = sorted(closes)
    rets: list[float] = []
    out: dict[str, float] = {}
    prev: float | None = None
    for d in days:
        p = closes[d]
        if prev and prev > 0 and p > 0:
            rets.append(p / prev - 1.0)
            if len(rets) > SIGMA_WINDOW:
                rets.pop(0)
            if len(rets) >= SIGMA_MIN_OBS:
                out[d] = statistics.pstdev(rets)
        prev = p
    return out


def eligible(day: dict[str, dict[str, float]], spec: PortfolioSpec) -> dict[str, dict[str, float]]:
    """The same screens build_target applies, so the comparator is the drawn universe."""
    out = {}
    for c, v in day.items():
        if spec.min_price_aud is not None and v["price"] < spec.min_price_aud:
            continue
        adv = v.get("adv20_aud")
        if spec.min_adv_aud is not None and (adv is None or adv < spec.min_adv_aud):
            continue
        out[c] = v
    return out


# ---------------------------------------------------------------------------
# pricing
# ---------------------------------------------------------------------------
def impact_cost(
    prev_w: dict[str, float],
    new_w: dict[str, float],
    day: dict[str, dict[str, float]],
    sigma: dict[str, float],
    aum: float,
    k: float,
    s: float,
) -> tuple[float, int]:
    """Impact as a fraction of NAV for one rebalance. Returns (cost, n_defaulted)."""
    codes = set(prev_w) | set(new_w)
    advs = [day[c]["adv20_aud"] for c in codes if c in day and (day[c].get("adv20_aud") or 0) > 0]
    sigs = [sigma[c] for c in codes if c in sigma]
    med_adv = statistics.median(advs) if advs else None
    med_sig = statistics.median(sigs) if sigs else None
    cost = 0.0
    defaulted = 0
    for c in codes:
        dw = abs(new_w.get(c, 0.0) - prev_w.get(c, 0.0))
        if dw <= 0:
            continue
        adv = day.get(c, {}).get("adv20_aud")
        sg = sigma.get(c)
        # A zero ADV is a name that did not trade in its 20-session window — an
        # absent liquidity number, not evidence of infinite liquidity. Defaulted
        # to the period median like a missing one, and counted.
        if not adv or adv <= 0 or sg is None:
            defaulted += 1
            adv = adv if adv and adv > 0 else med_adv
            sg = sg if sg is not None else med_sig
            if not adv or adv <= 0 or sg is None:
                continue
        participation = (aum * dw) / (s * adv)
        cost += dw * k * sg * math.sqrt(participation)
    return cost, defaulted


def price_book(
    periods: list[dict[str, Any]],
    panel: dict[str, dict[str, dict[str, float]]],
    sigma_by_code: dict[str, dict[str, float]],
    aum: float,
    k: float,
    s: float,
) -> dict[str, Any]:
    """Annualised net excess over the eligible universe for one (AUM, k, s)."""
    dates = sorted(panel)
    idx = {d: i for i, d in enumerate(dates)}
    prev_w: dict[str, float] = {}
    excess: list[float] = []
    impacts: list[float] = []
    defaulted = 0
    for p in periods:
        d = p["date"]
        i = idx[d]
        if i + 1 >= len(dates):
            break
        day, nxt = panel[d], panel[dates[i + 1]]
        w = p.get("weights", {})
        if not w:
            prev_w = {}
            continue
        sig = {c: sigma_by_code.get(c, {}).get(d) for c in set(w) | set(prev_w)}
        sig = {c: v for c, v in sig.items() if v is not None}
        imp, nd = impact_cost(prev_w, w, day, sig, aum, k, s)
        defaulted += nd
        elig = eligible(day, PORT)
        univ = [
            nxt[c]["price"] / elig[c]["price"] - 1.0
            for c in elig
            if c in nxt and elig[c]["price"] > 0
        ]
        if not univ:
            prev_w = w
            continue
        excess.append(p["net_return"] - imp - statistics.fmean(univ))
        impacts.append(imp)
        prev_w = w
    n = len(excess)
    mean = statistics.fmean(excess) if excess else math.nan
    sd = statistics.stdev(excess) if n > 1 else math.nan
    return {
        "aum_m": aum / 1e6,
        "k": k,
        "s": s,
        "periods": n,
        "annualised_net_excess_pct": mean * PERIODS_PER_YEAR * 100 if n else None,
        "t": (mean / (sd / math.sqrt(n))) if n > 1 and sd > 0 else None,
        "mean_impact_per_period_bps": statistics.fmean(impacts) * 1e4 if impacts else None,
        "names_defaulted_sigma_or_adv": defaulted,
    }


def breakeven_aum(
    periods: list[dict[str, Any]],
    panel: dict[str, Any],
    sigma_by_code: dict[str, dict[str, float]],
    k: float,
    s: float,
) -> float | None:
    """Largest AUM with annualised net excess ≥ 0 (bisection; impact is monotone in AUM)."""

    def f(aum: float) -> float:
        r = price_book(periods, panel, sigma_by_code, aum, k, s)
        return r["annualised_net_excess_pct"] or 0.0

    lo, hi = 1e5, 1e10
    if f(lo) <= 0:
        return 0.0
    if f(hi) > 0:
        return hi
    for _ in range(40):
        mid = math.sqrt(lo * hi)
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    return lo


# ---------------------------------------------------------------------------
# decomposition — where the F0 discrepancy lives, if there is one
# ---------------------------------------------------------------------------
def decompose(
    periods: list[dict[str, Any]],
    panel: dict[str, Any],
    sigma_by_code: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Per-period means of every component at $1M / k=0.5 / s=1, plus the three
    comparator definitions V304 could have meant. Reported so a reader can see
    which definition reproduces the journal's row, rather than guessing."""
    dates = sorted(panel)
    idx = {d: i for i, d in enumerate(dates)}
    prev_w: dict[str, float] = {}
    gross: list[float] = []
    explicit: list[float] = []
    imp1m: list[float] = []
    ew_elig: list[float] = []
    ew_all: list[float] = []
    med_elig: list[float] = []
    n_elig: list[int] = []
    n_book: list[int] = []
    for p in periods:
        d = p["date"]
        i = idx[d]
        if i + 1 >= len(dates):
            break
        w = p.get("weights", {})
        if not w:
            prev_w = {}
            continue
        day, nxt = panel[d], panel[dates[i + 1]]
        sig = {
            c: v
            for c, v in ((c, sigma_by_code.get(c, {}).get(d)) for c in set(w) | set(prev_w))
            if v is not None
        }
        imp, _ = impact_cost(prev_w, w, day, sig, 1e6, 0.5, 1.0)
        elig = eligible(day, PORT)
        r_e = [
            nxt[c]["price"] / elig[c]["price"] - 1.0
            for c in elig
            if c in nxt and elig[c]["price"] > 0
        ]
        r_a = [
            nxt[c]["price"] / day[c]["price"] - 1.0
            for c in day
            if c in nxt and day[c]["price"] > 0
        ]
        if not r_e or not r_a:
            prev_w = w
            continue
        gross.append(p["gross_return"])
        explicit.append(p["cost"])
        imp1m.append(imp)
        ew_elig.append(statistics.fmean(r_e))
        ew_all.append(statistics.fmean(r_a))
        med_elig.append(statistics.median(r_e))
        n_elig.append(len(r_e))
        n_book.append(len(w))
        prev_w = w
    m = statistics.fmean
    ann = PERIODS_PER_YEAR * 100
    g, c, i_ = m(gross), m(explicit), m(imp1m)
    return {
        "periods": len(gross),
        "per_period_mean_pct": {
            "book_gross": g * 100,
            "explicit_cost": c * 100,
            "impact_1m_k05_s1": i_ * 100,
            "universe_ew_eligible": m(ew_elig) * 100,
            "universe_ew_all_panel": m(ew_all) * 100,
            "universe_median_eligible": m(med_elig) * 100,
        },
        "annualised_net_excess_pct_by_comparator_at_1m": {
            "vs_ew_eligible": (g - c - i_ - m(ew_elig)) * ann,
            "vs_ew_all_panel": (g - c - i_ - m(ew_all)) * ann,
            "vs_median_eligible": (g - c - i_ - m(med_elig)) * ann,
            "absolute_no_comparator": (g - c - i_) * ann,
        },
        "median_names": {"eligible": statistics.median(n_elig), "book": statistics.median(n_book)},
        "v304_row_at_1m": V304_ROW["1"],
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    prices = ApiPriceSource(root=V3 / "prices")
    shorts = load_short_series_csv(V3 / "shorts")
    dates = quarterly_dates(prices)
    print(
        f"[v308] {len(dates)} quarterly dates {dates[0]} → {dates[-1]}; {len(shorts)} short series"
    )

    # hold_periods=1 over a quarterly calendar == one 63-session hold per period.
    from omega.nodes.asx.panel import build_panel

    built = build_panel(dates, PANEL, price_source=prices, short_series=shorts)
    panel = built["panel"]
    print(
        f"[v308] panel: {built['n_dates']} dates, {built['n_codes']} codes, liquidity={built['has_liquidity']}"
    )

    res = run(
        dates,
        hold_periods=1,
        panel_spec=PANEL,
        port_spec=PORT,
        costs=CostModel(),
        price_source=prices,
        short_series=shorts,
    )
    traded = [p for p in res.periods if p.get("weights")]
    print(
        f"[v308] engine: {len(res.periods)} periods, {len(traded)} traded; summary {res.summary()}"
    )

    codes_needed = {c for p in traded for c in p["weights"]}
    sigma_by_code = {c: trailing_sigma(prices.closes(c)) for c in codes_needed}

    grid: list[dict[str, Any]] = []
    for name, s in SCHEDULES.items():
        for k in K_GRID:
            for aum_m in AUM_GRID_M:
                r = price_book(res.periods, panel, sigma_by_code, aum_m * 1e6, k, s)
                r["schedule"] = name
                grid.append(r)
    breakeven = {
        name: {str(k): breakeven_aum(res.periods, panel, sigma_by_code, k, s) for k in K_GRID}
        for name, s in SCHEDULES.items()
    }

    # F0 — reproduction of V304's row at s=1, k=0.5
    repro = {
        str(int(r["aum_m"])): r["annualised_net_excess_pct"]
        for r in grid
        if r["schedule"] == "full_day_vwap" and r["k"] == 0.5
    }
    f0 = {
        "v304": V304_ROW,
        "reconstruction": repro,
        "delta_pp": {
            a: (repro[a] - V304_ROW[a]) if repro.get(a) is not None else None for a in V304_ROW
        },
        "tolerance_pp": F0_TOL_PP,
    }
    f0["pass"] = all(d is not None and abs(d) <= F0_TOL_PP for d in f0["delta_pp"].values())

    # F1 — $5M, k=0.5, auction-only stays positive
    f1_val = next(
        r["annualised_net_excess_pct"]
        for r in grid
        if r["schedule"] == "auction_only" and r["k"] == 0.5 and r["aum_m"] == 5.0
    )
    f1 = {
        "aum_m": 5,
        "k": 0.5,
        "s": 0.36,
        "annualised_net_excess_pct": f1_val,
        "pass": (f1_val or 0) > 0,
    }

    # F2 — breakeven scales with s
    be1, be36 = breakeven["full_day_vwap"]["0.5"], breakeven["auction_only"]["0.5"]
    ratio = (be36 / be1) if be1 else None
    f2 = {
        "breakeven_full_day_m": be1 / 1e6 if be1 else None,
        "breakeven_auction_only_m": be36 / 1e6 if be36 else None,
        "ratio": ratio,
        "expected": 0.36,
        "tolerance": F2_TOL,
        "pass": ratio is not None and abs(ratio / 0.36 - 1.0) <= F2_TOL,
    }

    decomp = decompose(res.periods, panel, sigma_by_code)
    out = {
        "version": "V308",
        "decomposition": decomp,
        "config": {
            "hold_sessions": HOLD_SESSIONS,
            "start": START,
            "portfolio": PORT.__dict__,
            "cost_bps_per_side": CostModel().bps_per_side + CostModel().slippage_bps,
            "schedules": SCHEDULES,
            "k_grid": K_GRID,
            "aum_grid_m": AUM_GRID_M,
        },
        "engine_summary": res.summary(),
        "n_quarterly_dates": len(dates),
        "grid": grid,
        "breakeven_aum": breakeven,
        "F0_reproduction": f0,
        "F1_positive_at_5m_auction_only": f1,
        "F2_breakeven_scales_with_s": f2,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")

    print(
        "\ndecomposition, per-period means (%):",
        {k: round(v, 3) for k, v in decomp["per_period_mean_pct"].items()},
    )
    print(
        "annualised net excess at $1M by comparator (%):",
        {
            k: round(v, 2)
            for k, v in decomp["annualised_net_excess_pct_by_comparator_at_1m"].items()
        },
    )
    print("median names:", decomp["median_names"])
    print("\nF0 reproduction (s=1.00, k=0.5):", "PASS" if f0["pass"] else "FAIL")
    for a in V304_ROW:
        print(
            f"   ${a}M: V304 {V304_ROW[a]:+.2f}  recon {repro.get(a) or float('nan'):+.2f}  Δ {f0['delta_pp'][a] or float('nan'):+.2f} pp"
        )
    print("\n| schedule | s | k | $1M | $5M | $20M | $50M | breakeven |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    for name, s in SCHEDULES.items():
        for k in K_GRID:
            cells = [r for r in grid if r["schedule"] == name and r["k"] == k]
            vals = " | ".join(f"{c['annualised_net_excess_pct']:+.2f}%" for c in cells)
            be = breakeven[name][str(k)]
            print(f"| {name} | {s:.2f} | {k} | {vals} | ${be / 1e6:,.0f}M |")
    print(
        f"\nF1 ($5M, k=0.5, auction-only): {f1_val:+.2f}%/yr → {'PASS' if f1['pass'] else 'FAIL'}"
    )
    ratio_txt = f"{ratio:.3f}" if ratio is not None else "undefined (no positive breakeven)"
    print(
        f"F2 breakeven ratio auction/full-day at k=0.5: {ratio_txt} (expected 0.36) → "
        f"{'PASS' if f2['pass'] else 'FAIL'}"
    )
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
