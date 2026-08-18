#!/usr/bin/env python3
"""V270 — spread-budget confirmation scorer.

Scores V269's retained per-minute bookTicker artefact against V267 G2's
`slippage_to_median_zero_bps = 1.6475`. Pre-registration:
omega/nodes/victoria/training_log/V270.md (committed BEFORE this file existed).

No strategy code. No flag. No grid. Reads only; writes one JSON artefact.

Usage: python3 scripts/v270_spread_budget.py [--out data/v270_spread_budget.json]
"""

from __future__ import annotations

import argparse
import csv
import glob
import gzip
import json
import math
import os
import random
import statistics
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(REPO, "data", "frozen_series", "binance_bookticker")
LEDGER = os.path.join(REPO, "data", "v269_ledger", "v255c_trades.csv")

SEED = 42
BOOTSTRAP_N = 10_000

# V267 G2, per-crossing (one leg, one side). scripts/v267_capacity.py:55,228.
V267_BUDGET_BPS = 1.6475
V267_MEDIAN_EDGE_BPS = 6.587
SLIPPAGE_LEG_MULT = 4.0


# ---------------------------------------------------------------- primitives
def median(xs: list[float]) -> float:
    """Deterministic median; sorted input, fsum for the even-length midpoint."""
    if not xs:
        return float("nan")
    s = sorted(xs)
    n = len(s)
    if n % 2:
        return s[n // 2]
    return math.fsum((s[n // 2 - 1], s[n // 2])) / 2.0


def quantile(xs: list[float], q: float) -> float:
    """Linear-interpolated quantile on sorted input (matches numpy default)."""
    if not xs:
        return float("nan")
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return math.fsum((s[lo] * (1.0 - frac), s[hi] * frac))


def cluster_boot_ci(clusters: list[list[float]], rng: random.Random) -> list[float]:
    """CI95 of the pooled median, resampling whole TRADES (entry+exit together).

    Entry and exit crossings of one trade are dependent; resampling them
    independently would understate the interval. V270.md §4.
    """
    if not clusters:
        return [float("nan"), float("nan")]
    n = len(clusters)
    stats = []
    for _ in range(BOOTSTRAP_N):
        pooled: list[float] = []
        for _ in range(n):
            pooled.extend(clusters[rng.randrange(n)])
        stats.append(median(pooled))
    return [round(quantile(stats, 0.025), 6), round(quantile(stats, 0.975), 6)]


# ------------------------------------------------------------------- loading
def load_artefact() -> dict[str, dict[str, dict[str, float]]]:
    """symbol -> day -> {median, p75, p90} of that day's per-minute sp_bps_p50."""
    by_day: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for path in sorted(glob.glob(os.path.join(ART, "*", "*.json.gz"))):
        with gzip.open(path, "rt") as fh:
            part = json.load(fh)
        sym = part["symbol"]
        for row in part["rows"]:
            # unix minute -> UTC date, no wall-clock, no tz database
            day = _utc_date(int(row["t"]))
            by_day[sym][day].append(float(row["sp_bps_p50"]))
    out: dict[str, dict[str, dict[str, float]]] = {}
    for sym in sorted(by_day):
        out[sym] = {}
        for day in sorted(by_day[sym]):
            vals = by_day[sym][day]
            out[sym][day] = {
                "median": median(vals),
                "p75": quantile(vals, 0.75),
                "p90": quantile(vals, 0.90),
                "minutes": len(vals),
            }
    return out


def _utc_date(epoch_s: int) -> str:
    """Civil UTC date from a unix second. Pure arithmetic (Howard Hinnant)."""
    z = epoch_s // 86400 + 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    y = y + 1 if m <= 2 else y
    return f"{y:04d}-{m:02d}-{d:02d}"


def load_ledger() -> list[dict]:
    with open(LEDGER, newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["notional"] = float(r["notional_usd"])
        r["pnl"] = float(r["pnl_usd"])
        r["edge_bps"] = 1e4 * r["pnl"] / r["notional"]  # v267_capacity.py:228
    return rows


# --------------------------------------------------------------------- gates
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "data", "v270_spread_budget.json"))
    args = ap.parse_args()

    rng = random.Random(SEED)
    art = load_artefact()
    ledger = load_ledger()

    # ---- G4a: rule fidelity against V267's published pooled numbers ---------
    all_edges = [t["edge_bps"] for t in ledger]
    med_edge_all = median(all_edges)
    s_median0 = med_edge_all / SLIPPAGE_LEG_MULT
    g4a_edge_err = abs(med_edge_all - V267_MEDIAN_EDGE_BPS) / V267_MEDIAN_EDGE_BPS
    g4a_budget_err = abs(s_median0 - V267_BUDGET_BPS) / V267_BUDGET_BPS
    g4a_pass = g4a_edge_err <= 0.01 and g4a_budget_err <= 0.01

    # ---- join --------------------------------------------------------------
    joinable, entry_only, unjoinable = [], 0, 0
    for t in ledger:
        days = art.get(t["symbol"], {})
        has_e, has_x = t["entry_date"] in days, t["exit_date"] in days
        if has_e and has_x:
            t["sp_entry"] = days[t["entry_date"]]
            t["sp_exit"] = days[t["exit_date"]]
            joinable.append(t)
        elif has_e or has_x:
            entry_only += 1
        else:
            unjoinable += 1

    # ---- G1: pooled median half-spread per crossing -------------------------
    def half(stat: str, t: dict) -> list[float]:
        return [t["sp_entry"][stat] / 2.0, t["sp_exit"][stat] / 2.0]

    clusters = [half("median", t) for t in joinable]
    crossings = [c for cl in clusters for c in cl]
    g1_median = median(crossings)
    g1_ci = cluster_boot_ci(clusters, rng)
    g1_pass = g1_median <= V267_BUDGET_BPS
    g1_ci_upper_clears = g1_ci[1] <= V267_BUDGET_BPS

    pess = {
        s: {
            "pooled_median_half_spread_bps": round(
                median([c for t in joinable for c in half(s, t)]), 6
            )
        }
        for s in ("p75", "p90")
    }

    # ---- G2: per-symbol distribution ---------------------------------------
    per_symbol: dict[str, dict] = {}
    by_sym: dict[str, list[float]] = defaultdict(list)
    trades_by_sym: dict[str, int] = defaultdict(int)
    for t in joinable:
        by_sym[t["symbol"]].extend(half("median", t))
        trades_by_sym[t["symbol"]] += 1
    for sym in sorted(by_sym):
        v = by_sym[sym]
        per_symbol[sym] = {
            "trades": trades_by_sym[sym],
            "crossings": len(v),
            "median_half_spread_bps": round(median(v), 6),
            "iqr_p25_bps": round(quantile(v, 0.25), 6),
            "iqr_p75_bps": round(quantile(v, 0.75), 6),
            "exceeds_budget": median(v) > V267_BUDGET_BPS,
        }
    g2_breaches = sorted(s for s, v in per_symbol.items() if v["exceeds_budget"])
    g2_pass = not g2_breaches

    # ---- G3: coverage honesty ----------------------------------------------
    hv_total = sum(1 for t in ledger if t["entry_regime"] == "high_vol")
    reg_join: dict[str, int] = defaultdict(int)
    reg_total: dict[str, int] = defaultdict(int)
    for t in ledger:
        reg_total[t["entry_regime"]] += 1
    for t in joinable:
        reg_join[t["entry_regime"]] += 1
    month_rule = sum(
        1 for t in ledger
        if "2023-05" <= t["entry_date"][:7] <= "2024-04"
        and "2023-05" <= t["exit_date"][:7] <= "2024-04"
    )

    # ---- G4b: representativeness (diagnostic, no bar) ----------------------
    sub_edges = [t["edge_bps"] for t in joinable]
    med_edge_sub = median(sub_edges)

    # ---- §7 derived colour (NOT gated) -------------------------------------
    def net_median(mult: float) -> float:
        return median([
            t["edge_bps"] - mult * median(half("median", t)) for t in joinable
        ])

    colour = {
        "gross_median_edge_bps_subset": round(med_edge_sub, 6),
        "C1_measured_perp_2_crossings_net_bps": round(net_median(2.0), 6),
        "C2_symmetric_spot_ASSUMPTION_4_crossings_net_bps": round(net_median(4.0), 6),
        "note": "C2 assumes spot half-spread == perp half-spread. That is an "
                "ASSUMPTION, not a measurement: the artefact covers the Binance "
                "USD-M perp leg only. Neither line is an impact model; depth-1 "
                "cannot produce one.",
    }

    if not g4a_pass:
        verdict = "R4_SCORER_INVALID"
    elif not g1_pass and g1_ci[0] > V267_BUDGET_BPS:
        verdict = "REFUTES_V267_G2"
    elif g1_ci[0] <= V267_BUDGET_BPS <= g1_ci[1]:
        verdict = "R2_BELOW_RESOLUTION"
    elif g1_ci[1] <= V267_BUDGET_BPS / 2.0:
        verdict = "CONFIRMS_AND_TIGHTENS_V267_G2"
    else:
        verdict = "CONFIRMS_V267_G2"

    out = {
        "colour_not_gated": colour,
        "determinism": {"seed": SEED, "bootstrap_n": BOOTSTRAP_N,
                        "reduction": "math.fsum", "iteration": "sorted"},
        "g1_pooled_spread": {
            "bar_bps": V267_BUDGET_BPS,
            "ci95": g1_ci,
            "ci95_upper_clears_bar": g1_ci_upper_clears,
            "crossings": len(crossings),
            "pass": g1_pass,
            "pooled_median_half_spread_bps": round(g1_median, 6),
            "pessimistic_intraday_variants": pess,
            "trades": len(joinable),
        },
        "g2_per_symbol": {"bar_bps": V267_BUDGET_BPS, "breaches": g2_breaches,
                          "pass": g2_pass, "per_symbol": per_symbol},
        "g3_coverage": {
            "high_vol_joined": reg_join.get("high_vol", 0),
            "high_vol_total": hv_total,
            "joinable_pct": round(100.0 * len(joinable) / len(ledger), 4),
            "joinable_trades": len(joinable),
            "ledger_trades": len(ledger),
            "partial_entry_or_exit_only_excluded": entry_only,
            "per_regime": {r: {"joined": reg_join.get(r, 0), "total": reg_total[r],
                               "pct": round(100.0 * reg_join.get(r, 0) / reg_total[r], 2)}
                           for r in sorted(reg_total)},
            "unjoinable_trades": unjoinable,
            "v269_month_rule_claim": month_rule,
            "v269_overstatement_pct": round(
                100.0 * (month_rule - len(joinable)) / len(joinable), 2),
        },
        "g4a_rule_fidelity": {
            "budget_rel_err": round(g4a_budget_err, 8),
            "median_edge_bps_recomputed": round(med_edge_all, 6),
            "median_edge_rel_err": round(g4a_edge_err, 8),
            "pass": g4a_pass,
            "slippage_to_median_zero_bps_recomputed": round(s_median0, 6),
            "v267_budget_bps": V267_BUDGET_BPS,
            "v267_median_edge_bps": V267_MEDIAN_EDGE_BPS,
        },
        "g4b_representativeness_diagnostic": {
            "note": "No bar. The joinable subset is a smaller, later-era draw; it "
                    "is not required to match the pooled 2020-2026 median.",
            "pooled_median_edge_bps": round(med_edge_all, 6),
            "subset_median_edge_bps": round(med_edge_sub, 6),
        },
        "verdict": verdict,
    }

    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)

    # ------------------------------------------------------------ human read
    print("=" * 74)
    print("V270 — SPREAD-BUDGET CONFIRMATION SCORING")
    print("=" * 74)
    print(f"\nG4a rule fidelity  : {'PASS' if g4a_pass else 'FAIL'}")
    print(f"  median edge      : {med_edge_all:.4f} bps  (V267 {V267_MEDIAN_EDGE_BPS})"
          f"  rel-err {g4a_edge_err*100:.4f}%")
    print(f"  s_median0        : {s_median0:.4f} bps  (V267 {V267_BUDGET_BPS})"
          f"  rel-err {g4a_budget_err*100:.4f}%")

    print(f"\nG1 pooled spread   : {'PASS' if g1_pass else 'FAIL'}")
    print(f"  median half-sp   : {g1_median:.4f} bps   bar {V267_BUDGET_BPS} bps")
    print(f"  cluster CI95     : [{g1_ci[0]:.4f}, {g1_ci[1]:.4f}]"
          f"   upper clears bar: {g1_ci_upper_clears}")
    print(f"  n                : {len(joinable)} trades / {len(crossings)} crossings")
    print(f"  intraday p75/p90 : {pess['p75']['pooled_median_half_spread_bps']:.4f}"
          f" / {pess['p90']['pooled_median_half_spread_bps']:.4f} bps")

    print(f"\nG2 per-symbol      : {'PASS' if g2_pass else 'FAIL'}"
          f"{'  breaches: ' + ', '.join(g2_breaches) if g2_breaches else ''}")
    print(f"\n  {'symbol':<10}{'trades':>7}{'median':>10}{'p25':>10}{'p75':>10}"
          f"{'x budget':>10}")
    for s, v in sorted(per_symbol.items()):
        print(f"  {s:<10}{v['trades']:>7}{v['median_half_spread_bps']:>10.4f}"
              f"{v['iqr_p25_bps']:>10.4f}{v['iqr_p75_bps']:>10.4f}"
              f"{v['median_half_spread_bps']/V267_BUDGET_BPS:>10.2f}")

    print("\nG3 COVERAGE (binding on every number above)")
    print(f"  joinable         : {len(joinable)}/{len(ledger)} = "
          f"{100*len(joinable)/len(ledger):.2f}%  (both entry-day AND exit-day)")
    print(f"  V269 month-rule  : {month_rule} -> overstates usable set by "
          f"{100*(month_rule-len(joinable))/len(joinable):.1f}%")
    print(f"  partial (1 day)  : {entry_only} excluded, never half-filled")
    print(f"  high_vol         : {reg_join.get('high_vol',0)}/{hv_total}"
          f"  <-- G1/G2 DO NOT SPEAK TO high_vol")
    for r in sorted(reg_total):
        print(f"    {r:<16}: {reg_join.get(r,0):>4}/{reg_total[r]:<5} "
              f"{100*reg_join.get(r,0)/reg_total[r]:>6.2f}%")
    print("  depth            : depth-1 top-of-book, PERP LEG ONLY. Spot leg "
          "unmeasured.\n                     No L2 ladder; no impact model derivable.")

    print(f"\nColour (NOT gated): gross {colour['gross_median_edge_bps_subset']:.4f} bps"
          f" -> C1 {colour['C1_measured_perp_2_crossings_net_bps']:.4f}"
          f" / C2(assumed) {colour['C2_symmetric_spot_ASSUMPTION_4_crossings_net_bps']:.4f}")
    print(f"\nVERDICT: {verdict}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
