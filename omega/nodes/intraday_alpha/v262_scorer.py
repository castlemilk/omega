"""V262-2 — offline F1/F2/F3 scorer for the intraday (1h) thesis.

LOCKED to ``victoria/training_log/V262-2.md``. Nothing here is tuned after a result:
the z-window, entry threshold, hold horizon, fee model, notional, member signs, the
two direction arms, the Bonferroni α, and the N_eff deflator are all pre-registered
in that document (committed before this file was written).

Pipeline, per V255.C / V261 pattern — read frozen series, compute statistics, no node
DAG, no cycle loop, no sleep:

  1. Load the corrected 1h corpus + the daily auxiliary feeds.
  2. Build per-bar composite z for both direction arms (M momentum / R reversion).
  3. Simulate non-overlapping $10k trades at the primary 5-bar hold.
  4. F1 — pooled median net > $0 with an N_eff-deflated bootstrap CI95 excluding 0.
  5. F2 — MWU on entry |z| (winners vs losers), N_eff-deflated, α = 0.025 (2 arms).
  6. F3 — annualized net >= 15% at 12 bps/side.
  7. Diagnostics (never verdict-bearing): the gross (0 bps) book, the hold ladder
     {5,24,72,168} with its break-even hold, per-name tables, and the
     intraday-native-only composite.
  8. Verdict per V262-2.md §5: ADOPT / FLAG-GATED / REFUTED.

Determinism: pure-python stats, ``math.fsum``, fixed-seed ``random.Random``, no
wall clock. Re-running produces a byte-identical result JSON.
"""

from __future__ import annotations

import json
import math
import os
import random
from dataclasses import asdict

from omega.nodes.funding_carry.phase0_separator import (
    _median,
    _stats,
    mann_whitney_u,
)

from .loader import IntradayLoader
from .signals import MEMBER_KEYS, NATIVE_MEMBER_KEYS, build_members, composite_z_series
from .sim import IntradayParams, IntradayTrade, simulate_symbol

# ---- pre-registered constants (V262-2.md) ----
VERDICT_UNIVERSE = (
    "SOLUSDT",
    "BNBUSDT",
    "AVAXUSDT",
    "XRPUSDT",
    "SUIUSDT",
    "POLUSDT",
    "ADAUSDT",
    "NEARUSDT",
    "ARBUSDT",
    "MATICUSDT",
)
REPORTED_ONLY = ("BTCUSDT", "ETHUSDT", "DOTUSDT", "LINKUSDT")

ARMS = {"M_momentum": +1.0, "R_reversion": -1.0}  # V262-2.md §3b
ALPHA = 0.025  # 0.05 / 2 arms, Bonferroni (V262-2.md §3b)
N_EFF_FACTOR = 0.778  # F4b SLEM (1-λ₂)/(1+λ₂) (V262-2.md §6)
N_EFF_ALT = 0.872  # F4b (1-λ₂), reported for comparison
ANN_FLOOR = 0.15  # F3: annualized net >= 15% (V262.md §6)
HOLD_LADDER = (5, 24, 72, 168)  # diagnostic only (V262-2.md §4)
BOOTSTRAP_N = 10_000
BOOTSTRAP_SEED = 20260730
_HOURS_PER_YEAR = 8760.0


def _phi(x: float) -> float:
    """Standard normal CDF (same erf-based form as phase0_separator)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _deflated_mwu(a: list[float], b: list[float]) -> dict:
    """MWU with the F4b N_eff deflation applied to the normal approximation.

    For fixed effect size, the MWU z statistic scales as sqrt(n): with both group
    sizes multiplied by f, ``u1 - mu`` scales as f² and ``sigma`` as f^1.5, so
    ``z`` scales as sqrt(f). Deflating the effective sample size by ``N_EFF_FACTOR``
    therefore multiplies z by sqrt(0.778) = 0.8820, which WIDENS the p-value — the
    conservative direction F4b §7 requires.
    """
    raw = mann_whitney_u(a, b)
    if not raw.get("valid"):
        return {"valid": False, "raw": raw}
    z = float(raw["z"])
    z_def = z * math.sqrt(N_EFF_FACTOR)
    p_two_def = 2.0 * (1.0 - _phi(abs(z_def)))
    return {
        "valid": True,
        "n1": raw["n1"],
        "n2": raw["n2"],
        "n1_eff": round(N_EFF_FACTOR * raw["n1"], 1),
        "n2_eff": round(N_EFF_FACTOR * raw["n2"], 1),
        "z_raw": round(z, 6),
        "z_deflated": round(z_def, 6),
        "p_two_sided_raw": round(float(raw["p_two_sided"]), 8),
        "p_two_sided_deflated": round(p_two_def, 8),
        "n_eff_factor": N_EFF_FACTOR,
    }


def _bootstrap_median_ci(pnls: list[float], deflate: bool) -> dict:
    """Bootstrap CI95 on the median.

    ``deflate=True`` draws ``round(N_EFF_FACTOR * n)`` observations per replicate
    instead of ``n``, which widens the interval — the F4b-mandated conservative form
    used for F1's verdict.
    """
    n = len(pnls)
    if n < 2:
        return {"valid": False, "n": n}
    draw = max(2, round(N_EFF_FACTOR * n)) if deflate else n
    rng = random.Random(BOOTSTRAP_SEED)
    meds: list[float] = []
    for _ in range(BOOTSTRAP_N):
        meds.append(_median([pnls[rng.randrange(n)] for _ in range(draw)]))
    meds.sort()

    def _q(q: float) -> float:
        return meds[min(BOOTSTRAP_N - 1, max(0, round(q * (BOOTSTRAP_N - 1))))]

    lo, hi = _q(0.025), _q(0.975)
    return {
        "valid": True,
        "n_obs": n,
        "resample_size": draw,
        "deflated": deflate,
        "n_resamples": BOOTSTRAP_N,
        "seed": BOOTSTRAP_SEED,
        "point_median": round(_median(pnls), 4),
        "ci95_lo": round(lo, 4),
        "ci95_hi": round(hi, 4),
        "ci95_excludes_zero": bool(lo > 0.0 or hi < 0.0),
        "ci95_lo_gt_zero": bool(lo > 0.0),
    }


def _annualized(rets: list[float], hold_bars: int, notional: float) -> dict:
    """Annualized return, two conventions — both reported, the first is F3's.

    ``fully_deployed`` inherits V261's convention verbatim (mean return per hold ×
    holds per year), i.e. capital continuously recycled into back-to-back holds.
    ``duty_cycled`` scales that by the fraction of available bars actually spent in
    a position, which is the honest realized figure when the entry filter is
    selective. F3's pre-registered gate reads ``fully_deployed``.
    """
    if not rets:
        return {"n": 0, "fully_deployed": 0.0, "fully_deployed_pct": 0.0}
    mean_ret = math.fsum(rets) / len(rets)
    holds_per_year = _HOURS_PER_YEAR / hold_bars
    ann = mean_ret * holds_per_year
    return {
        "n": len(rets),
        "hold_bars": hold_bars,
        "mean_ret_per_hold": round(mean_ret, 10),
        "holds_per_year_if_continuous": round(holds_per_year, 2),
        "fully_deployed": round(ann, 6),
        "fully_deployed_pct": round(ann * 100.0, 3),
        "notional_usd": notional,
    }


def _duty_cycle_ann(trades: list[IntradayTrade], hold_bars: int, span_bars: int) -> dict:
    """Annualized net on the realized duty cycle (diagnostic)."""
    if not trades or span_bars <= 0:
        return {"valid": False}
    bars_in_market = len(trades) * hold_bars
    duty = bars_in_market / span_bars
    total_ret = math.fsum(t.pnl_usd for t in trades) / 10_000.0
    # span_bars is summed ACROSS symbols, so this denominator is symbol-years
    # (portfolio-years), not calendar years — named accordingly so the figure is not
    # misread as a calendar return.
    symbol_years = span_bars / _HOURS_PER_YEAR
    return {
        "valid": True,
        "duty_cycle": round(duty, 6),
        "symbol_years": round(symbol_years, 3),
        "net_return_per_unit_notional_per_symbol_year": round(total_ret / symbol_years, 6),
        "pct_per_symbol_year": round(100.0 * total_ret / symbol_years, 3),
    }


def _fee_bps_breakeven(trades: list[IntradayTrade]) -> float | None:
    """Round-trip bps at which the pooled MEDIAN gross PnL is exactly consumed."""
    if not trades:
        return None
    med_gross = _median([t.gross_pnl_usd for t in trades])
    if med_gross <= 0.0:
        return None
    return round(1e4 * med_gross / 10_000.0, 4)


def _run_arm(
    per_symbol: dict[str, dict],
    include: tuple[str, ...],
    return_sign: float,
    p: IntradayParams,
) -> dict:
    """Simulate one (arm, member-set, params) cell across the verdict universe."""
    trades: list[IntradayTrade] = []
    per_name: dict[str, dict] = {}
    reported: dict[str, dict] = {}
    span_bars_total = 0
    for sym, d in per_symbol.items():
        comp = composite_z_series(d["members"], include, return_sign)
        t = simulate_symbol(
            sym, d["bar_times"], d["close"], comp, d["members"]["hourly_volume_z"], p
        )
        row = {
            "n_bars": len(d["bar_times"]),
            "n_composite_bars": sum(1 for z in comp if z is not None),
            "n_trades": len(t),
            "net": _stats([x.pnl_usd for x in t]),
            "gross": _stats([x.gross_pnl_usd for x in t]),
        }
        if sym in VERDICT_UNIVERSE:
            trades.extend(t)
            per_name[sym] = row
            span_bars_total += len(d["bar_times"])
        else:
            reported[sym] = row

    net = [t.pnl_usd for t in trades]
    gross = [t.gross_pnl_usd for t in trades]
    ann_net = _annualized(
        [t.gross_ret - 2 * p.fee_bps_per_side / 1e4 for t in trades], p.hold_bars, p.notional_usd
    )
    ann_gross = _annualized([t.gross_ret for t in trades], p.hold_bars, p.notional_usd)
    mwu = _deflated_mwu(
        [t.entry_abs_z for t in trades if t.is_winner],
        [t.entry_abs_z for t in trades if not t.is_winner],
    )
    return {
        "return_sign": return_sign,
        "include": list(include),
        "params": asdict(p),
        "n_trades": len(trades),
        "per_name": per_name,
        "reported_only_names": reported,
        "pooled_net_stats": _stats(net),
        "pooled_gross_stats": _stats(gross),
        "annualized_net": ann_net,
        "annualized_gross": ann_gross,
        "duty_cycle_net": _duty_cycle_ann(trades, p.hold_bars, span_bars_total),
        "mwu_winners_losers_entry_abs_z": mwu,
        "fee_bps_roundtrip_breakeven_on_median_gross": _fee_bps_breakeven(trades),
        "_trades": trades,
    }


def _falsifiers(arm: dict, boot_def: dict, boot_raw: dict) -> dict:
    med = arm["pooled_net_stats"].get("median_pnl_usd", 0.0) or 0.0
    mwu = arm["mwu_winners_losers_entry_abs_z"]
    p_def = mwu.get("p_two_sided_deflated") if mwu.get("valid") else None
    ann = arm["annualized_net"]["fully_deployed"]
    f1 = (med <= 0.0) or (not boot_def.get("ci95_excludes_zero", False))
    f2 = (p_def is None) or (p_def >= ALPHA)
    f3 = ann < ANN_FLOOR
    return {
        "f1_refuted": bool(f1),
        "f1_detail": {
            "pooled_median_net_usd": med,
            "median_gt_zero": bool(med > 0.0),
            "ci95_deflated": boot_def,
            "ci95_undeflated_reported": boot_raw,
        },
        "f2_refuted": bool(f2),
        "f2_detail": {"alpha_bonferroni": ALPHA, "p_deflated": p_def, "mwu": mwu},
        "f3_refuted": bool(f3),
        "f3_detail": {
            "annualized_net": ann,
            "annualized_net_pct": arm["annualized_net"]["fully_deployed_pct"],
            "floor": ANN_FLOOR,
            "annualized_gross_pct": arm["annualized_gross"]["fully_deployed_pct"],
        },
        "all_pass": bool(not f1 and not f2 and not f3),
    }


def run_v262_2(data_dir: str | None = None, out_dir: str | None = None) -> dict:
    loader = IntradayLoader(data_dir=data_dir)
    symbols = list(VERDICT_UNIVERSE) + list(REPORTED_ONLY)

    # ---- load once; member z's are arm-independent (only the SIGN differs) ----
    per_symbol: dict[str, dict] = {}
    coverage: dict[str, dict] = {}
    for sym in symbols:
        bar_times, cols = loader.load_ohlcv(sym, "1h")
        members = build_members(loader, sym, bar_times, cols["close"], cols["volume"])
        per_symbol[sym] = {
            "bar_times": bar_times,
            "close": cols["close"],
            "members": members,
        }
        coverage[sym] = {
            "n_bars": len(bar_times),
            "member_valid_bars": {
                k: sum(1 for x in v if x is not None) for k, v in sorted(members.items())
            },
        }
    # Feed-blocked symbols: a member with no frozen file at all zeroes the symbol via
    # the all-or-nothing fence. Surfaced, never silent (POLUSDT has no frozen
    # funding/open-interest series — the same POL data-era gap V255.D-EXT hit).
    feed_blocked = sorted(
        s for s in VERDICT_UNIVERSE if min(coverage[s]["member_valid_bars"].values()) == 0
    )

    primary = IntradayParams()
    arms: dict[str, dict] = {}
    for arm_name, sign in ARMS.items():
        cell = _run_arm(per_symbol, MEMBER_KEYS, sign, primary)
        net = [t.pnl_usd for t in cell["_trades"]]
        boot_def = _bootstrap_median_ci(net, deflate=True)
        boot_raw = _bootstrap_median_ci(net, deflate=False)
        cell["falsifiers"] = _falsifiers(cell, boot_def, boot_raw)
        arms[arm_name] = cell

    # ---- diagnostics (never verdict-bearing, V262-2.md §4) ----
    ladder: dict[str, dict] = {}
    for arm_name, sign in ARMS.items():
        for hold in HOLD_LADDER:
            cell = _run_arm(per_symbol, MEMBER_KEYS, sign, IntradayParams(hold_bars=hold))
            ladder[f"{arm_name}/hold_{hold}"] = {
                "n_trades": cell["n_trades"],
                "median_net_usd": cell["pooled_net_stats"].get("median_pnl_usd"),
                "median_gross_usd": cell["pooled_gross_stats"].get("median_pnl_usd"),
                "annualized_net_pct": cell["annualized_net"]["fully_deployed_pct"],
                "annualized_gross_pct": cell["annualized_gross"]["fully_deployed_pct"],
                "breakeven_roundtrip_bps": cell["fee_bps_roundtrip_breakeven_on_median_gross"],
            }

    native: dict[str, dict] = {}
    for arm_name, sign in ARMS.items():
        cell = _run_arm(per_symbol, NATIVE_MEMBER_KEYS, sign, primary)
        native[arm_name] = {
            "n_trades": cell["n_trades"],
            "pooled_net_stats": cell["pooled_net_stats"],
            "pooled_gross_stats": cell["pooled_gross_stats"],
            "annualized_net_pct": cell["annualized_net"]["fully_deployed_pct"],
            "annualized_gross_pct": cell["annualized_gross"]["fully_deployed_pct"],
            "mwu": cell["mwu_winners_losers_entry_abs_z"],
        }

    # ---- verdict (V262-2.md §5) ----
    verdict, reason, winning = _verdict(arms)

    result = {
        "version": "V262-2",
        "falsifier_set": "F1 (pooled median), F2 (MWU mechanism), F3 (annualized net)",
        "pre_registration": "omega/nodes/victoria/training_log/V262-2.md",
        "verdict_universe": list(VERDICT_UNIVERSE),
        "reported_only": list(REPORTED_ONLY),
        "feed_blocked_symbols": feed_blocked,
        "missing_frozen_feeds": sorted(loader.missing_feeds),
        "effective_verdict_universe": [s for s in VERDICT_UNIVERSE if s not in feed_blocked],
        "per_symbol_coverage": coverage,
        "n_eff": {
            "slem_factor_used": N_EFF_FACTOR,
            "one_minus_lambda2_reported": N_EFF_ALT,
            "effective_multiplier_vs_daily": "~19-21x (F4b), never 24x",
        },
        "alpha_bonferroni_2_arms": ALPHA,
        "annualized_net_floor": ANN_FLOOR,
        "arms": {
            k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in arms.items()
        },
        "diagnostic_hold_ladder": ladder,
        "diagnostic_intraday_native_only": native,
        "verdict": verdict,
        "winning_arm": winning,
        "verdict_reason": reason,
    }

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "v262_2_scorer.json"), "w") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
        for arm_name, cell in arms.items():
            fn = f"v262_2_trades_{arm_name}.csv"
            with open(os.path.join(out_dir, fn), "w") as fh:
                fh.write(
                    "symbol,entry_ms,exit_ms,direction,entry_z,entry_price,"
                    "exit_price,gross_ret,gross_pnl_usd,fee_usd,pnl_usd\n"
                )
                for t in cell["_trades"]:
                    fh.write(
                        f"{t.symbol},{t.entry_ms},{t.exit_ms},{t.direction},"
                        f"{t.entry_z:.8f},{t.entry_price:.8f},{t.exit_price:.8f},"
                        f"{t.gross_ret:.10f},{t.gross_pnl_usd:.4f},"
                        f"{t.fee_usd:.4f},{t.pnl_usd:.4f}\n"
                    )
    return result


def _verdict(arms: dict) -> tuple[str, str, str | None]:
    """V262-2.md §5 verdict rule. Evaluated per-arm; passes never combine across arms."""
    for arm_name, cell in sorted(arms.items()):
        if cell["falsifiers"]["all_pass"]:
            f = cell["falsifiers"]
            return (
                "ADOPT",
                f"{arm_name}: F1+F2+F3 all pass in the same arm — pooled median net "
                f"${f['f1_detail']['pooled_median_net_usd']:.2f} with a deflated CI95 "
                f"excluding zero, MWU p_deflated={f['f2_detail']['p_deflated']} < "
                f"{ALPHA}, annualized net "
                f"{f['f3_detail']['annualized_net_pct']:.2f}% >= 15%.",
                arm_name,
            )

    # FLAG-GATED: mechanism real (F2 passes) and the GROSS book clears F1+F3,
    # but the NET book fails — i.e. real signal, eaten by friction.
    for arm_name, cell in sorted(arms.items()):
        f = cell["falsifiers"]
        gross_med = cell["pooled_gross_stats"].get("median_pnl_usd", 0.0) or 0.0
        gross_ann = cell["annualized_gross"]["fully_deployed"]
        if (not f["f2_refuted"]) and gross_med > 0.0 and gross_ann >= ANN_FLOOR:
            return (
                "FLAG-GATED",
                f"{arm_name}: mechanism holds (MWU p_deflated="
                f"{f['f2_detail']['p_deflated']} < {ALPHA}) and the GROSS book clears "
                f"F1/F3 (median ${gross_med:.2f}, annualized gross "
                f"{cell['annualized_gross']['fully_deployed_pct']:.2f}%), but the NET "
                f"book fails (median ${f['f1_detail']['pooled_median_net_usd']:.2f}, "
                f"annualized net {f['f3_detail']['annualized_net_pct']:.2f}%). Signal "
                f"real, fee-eroded at intraday frequency — flag stays OFF.",
                arm_name,
            )

    bits = []
    for arm_name, cell in sorted(arms.items()):
        f = cell["falsifiers"]
        fired = [k[:2].upper() for k in ("f1_refuted", "f2_refuted", "f3_refuted") if f[k]]
        bits.append(
            f"{arm_name}: fired {'+'.join(fired)} "
            f"(median net ${f['f1_detail']['pooled_median_net_usd']:.2f}, "
            f"MWU p_def={f['f2_detail']['p_deflated']}, "
            f"ann net {f['f3_detail']['annualized_net_pct']:.2f}%, "
            f"ann gross {f['f3_detail']['annualized_gross_pct']:.2f}%)"
        )
    return (
        "REFUTED",
        "REFUTED: no arm passes all three falsifiers, and no arm's GROSS book clears "
        "F1/F3 with a surviving mechanism. "
        + "; ".join(bits)
        + ". Intraday resolution does not reopen the entry-side composite.",
        None,
    )


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="V262-2 intraday 1h offline scorer")
    ap.add_argument("out_dir", nargs="?", default=None)
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()
    res = run_v262_2(data_dir=args.data_dir, out_dir=args.out_dir)
    print(json.dumps(res, indent=2, sort_keys=True, default=str))
