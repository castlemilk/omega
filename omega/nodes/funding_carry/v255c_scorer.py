"""V255.C — $0 offline scorer + pre-registered verdict (hold/level-scaled carry).

Runs the full offline analysis for the V255.C re-parameterization:
  1. Load frozen funding + close; classify funding regimes (fixed a-priori).
  2. Run the empirical basis check (mechanism gate — carried from V255.B).
  3. Simulate the V255.C trades (7-day hold, level-scaled sizing, maker fee).
  4. Verify the hedge cancels price risk (spot+perp price PnL == 0).
  5. Pooled + per-regime distributional stats (NET PnL, after 2-leg fee):
     mean, median, p25, p75, WR, PF, N.
  6. Per-genuine-regime MWU: winners vs losers by |entry funding| (the level
     separator confirmed p ≈ 0 in V255.B).
  7. Annualized GROSS carry (pre-fee) AND annualized NET.
  8. Bootstrap CI on the pooled median net PnL (fixed-seed, deterministic).
  9. Verdict against the pre-registered falsifiers (V255_C.md).

Deterministic: pure-python stats, math.fsum, canonical sort. The bootstrap uses
a fixed-seed LOCAL ``random.Random`` (seed below) so re-runs are byte-identical
and independent of PYTHONHASHSEED. Reuses the audited MWU + stats helpers from
phase0_separator and the honest basis check from basis_hedge.
"""

from __future__ import annotations

import json
import math
import os
import random
from dataclasses import asdict

from .basis_data import BasisLoader
from .basis_hedge import empirical_basis_check
from .data import FundingDataLoader
from .hold_scaled import HoldScaledParams, HoldScaledTrade, simulate_universe_scaled
from .phase0_separator import _median, _stats, mann_whitney_u
from .regime import FundingRegime, FundingRegimeClassifier, build_market_index

# V255.D decision rule (pre-declared in V255_D_SCOPING.md §5.4): the measured
# basis residual is "small" (hedge clean) iff the median |residual| stays under
# 0.1% of one leg's notional over the 3–7d holds.
_BASIS_SMALL_FRAC = 0.001

GENUINE_REGIMES = (
    FundingRegime.NEGATIVE_CARRY.value,
    FundingRegime.POSITIVE_CARRY.value,
    FundingRegime.HIGH_VOL.value,
)

# Pre-declared in V255_C.md: fixed bootstrap seed → byte-identical re-runs.
_BOOTSTRAP_SEED = 20250714
_BOOTSTRAP_N = 10_000


def _annualized(rets_per_hold: list[float], hold_days: int) -> dict:
    """Mean per-trade return over ``hold_days`` annualized by 365/hold_days.

    Holds are non-overlapping per symbol, so 365/hold_days is the correct factor.
    """
    if not rets_per_hold:
        return {"n": 0, "annualized": 0.0, "annualized_pct": 0.0}
    mean_ret = math.fsum(rets_per_hold) / len(rets_per_hold)
    ann = mean_ret * (365.0 / hold_days)
    return {
        "n": len(rets_per_hold),
        "mean_ret_per_hold": round(mean_ret, 8),
        "hold_days": hold_days,
        "annualized": round(ann, 6),
        "annualized_pct": round(ann * 100.0, 3),
    }


def _bootstrap_median_ci(
    pnls: list[float], n_resamples: int = _BOOTSTRAP_N, seed: int = _BOOTSTRAP_SEED
) -> dict:
    """95% percentile bootstrap CI on the pooled median (fixed-seed, deterministic)."""
    n = len(pnls)
    if n == 0:
        return {"valid": False}
    rng = random.Random(seed)
    medians: list[float] = []
    for _ in range(n_resamples):
        sample = [pnls[rng.randrange(n)] for _ in range(n)]
        medians.append(_median(sample))
    medians.sort()

    def _q(q: float) -> float:
        idx = min(n_resamples - 1, max(0, round(q * (n_resamples - 1))))
        return medians[idx]

    lo = _q(0.025)
    hi = _q(0.975)
    return {
        "valid": True,
        "n_resamples": n_resamples,
        "seed": seed,
        "point_median": round(_median(pnls), 4),
        "ci95_lo": round(lo, 4),
        "ci95_hi": round(hi, 4),
        "ci95_excludes_zero": bool(lo > 0.0 or hi < 0.0),
        "ci95_lo_gt_zero": bool(lo > 0.0),
    }


def _apply_frozen_basis(
    trades: list[HoldScaledTrade], data_dir: str | None
) -> dict:
    """Re-price each trade's two legs on real perp-mark + spot-index (V255.D).

    Mutates ``trades`` in place: for every symbol that has a frozen mark+index
    pair, the previously-cancelling price legs are replaced with measured ones and
    ``pnl_usd`` is recomputed (funding + fee unchanged). Symbols with no frozen
    basis keep the zero-basis assumption (residual $0). Returns a report of what
    was re-priced + the measured basis-residual distribution — the §5.4 decision
    variable.
    """
    bl = BasisLoader(data_dir=data_dir)
    syms = sorted({t.symbol for t in trades})
    avail = bl.available(syms)

    residual_fracs: list[float] = []   # measured residual / notional, real-basis trades
    residual_pnls: list[float] = []
    n_real = 0
    n_fallback_symbol = 0   # symbol not in frozen set
    n_fallback_date = 0     # symbol frozen but a leg date missing

    for t in trades:
        if t.symbol not in avail:
            n_fallback_symbol += 1
            continue
        res = bl.residual_pnl(
            t.symbol, t.entry_date, t.exit_date, t.perp_side, t.notional_usd
        )
        if res is None:
            n_fallback_date += 1
            continue
        spot_leg_pnl, perp_leg_pnl, residual_frac = res
        t.spot_price_pnl = spot_leg_pnl
        t.perp_price_pnl = perp_leg_pnl
        t.spot_price_ret = spot_leg_pnl / t.notional_usd if t.notional_usd else 0.0
        t.perp_price_ret = perp_leg_pnl / t.notional_usd if t.notional_usd else 0.0
        t.pnl_usd = (
            t.spot_price_pnl + t.perp_price_pnl + t.funding_pnl + t.fee_pnl
        )
        n_real += 1
        residual_fracs.append(residual_frac)
        residual_pnls.append(spot_leg_pnl + perp_leg_pnl)

    abs_fracs = sorted(abs(x) for x in residual_fracs)

    def _q(v: list[float], q: float) -> float:
        if not v:
            return 0.0
        idx = min(len(v) - 1, max(0, round(q * (len(v) - 1))))
        return v[idx]

    median_abs_frac = _q(abs_fracs, 0.5)
    basis_small = median_abs_frac < _BASIS_SMALL_FRAC
    return {
        "frozen_symbols_available": sorted(avail),
        "n_trades_real_basis": n_real,
        "n_trades_fallback_symbol": n_fallback_symbol,
        "n_trades_fallback_date": n_fallback_date,
        "basis_residual_frac_of_notional": {
            "n": len(residual_fracs),
            "mean": round(math.fsum(residual_fracs) / len(residual_fracs), 8)
            if residual_fracs else 0.0,
            "median_signed": round(_median(residual_fracs), 8) if residual_fracs else 0.0,
            "median_abs": round(median_abs_frac, 8),
            "p75_abs": round(_q(abs_fracs, 0.75), 8),
            "p95_abs": round(_q(abs_fracs, 0.95), 8),
            "max_abs": round(abs_fracs[-1], 8) if abs_fracs else 0.0,
        },
        "basis_residual_pnl_usd": _stats(residual_pnls) if residual_pnls else {},
        "threshold_small_frac": _BASIS_SMALL_FRAC,
        "basis_residual_small": basis_small,
    }


def run_v255c(
    params: HoldScaledParams | None = None,
    data_dir: str | None = None,
    out_dir: str | None = None,
    basis_source: str = "zero",
) -> dict:
    p = params or HoldScaledParams()
    loader = FundingDataLoader(data_dir=data_dir)
    universe = loader.load_universe()

    # mechanism gate: can the hedge be validated empirically? (carried from V255.B)
    basis_check = empirical_basis_check(universe)

    # regimes (fixed a-priori boundaries)
    dates, market_index = build_market_index(universe)
    clf = FundingRegimeClassifier()
    date_regimes = clf.classify_span(dates, market_index)

    # trades (7-day hold, level-scaled sizing, near_zero excluded)
    trades = simulate_universe_scaled(universe, date_regimes, p)

    # V255.D: re-price legs on real perp-mark + spot-index where frozen data exists.
    # Default ("zero") leaves the single-close hedge intact → byte-identical to V255.C.
    basis_application: dict | None = None
    if basis_source == "frozen":
        basis_application = _apply_frozen_basis(trades, data_dir)

    # hedge-cancellation verification (spot + perp price PnL must be ~0)
    max_residual = 0.0
    for t in trades:
        max_residual = max(max_residual, abs(t.spot_price_pnl + t.perp_price_pnl))
    # In zero-basis mode the legs cancel to ~0 by construction; with real basis the
    # residual is a MEASURED number, so the "cancels" flag no longer applies there.
    hedge_cancels = max_residual < 1e-6

    pooled = [t.pnl_usd for t in trades]
    gross_pooled = [t.gross_carry_pnl for t in trades]

    # per-regime NET stats
    regime_trades: dict[str, list[HoldScaledTrade]] = {r: [] for r in GENUINE_REGIMES}
    for t in trades:
        if t.entry_regime in regime_trades:
            regime_trades[t.entry_regime].append(t)
    per_regime_stats = {
        r: _stats([t.pnl_usd for t in regime_trades[r]]) for r in GENUINE_REGIMES
    }

    # per-genuine-regime MWU: winners vs losers by |entry funding|
    per_regime_mwu: dict[str, dict] = {}
    any_regime_significant = False
    for r in GENUINE_REGIMES:
        ts = regime_trades[r]
        win = [abs(t.entry_funding) for t in ts if t.is_winner]
        lose = [abs(t.entry_funding) for t in ts if not t.is_winner]
        mwu = mann_whitney_u(win, lose)
        pval = mwu.get("p_two_sided") if mwu.get("valid") else None
        sig = bool(mwu.get("valid") and pval is not None and pval < 0.05)
        any_regime_significant = any_regime_significant or sig
        per_regime_mwu[r] = {
            "n_winners": len(win),
            "n_losers": len(lose),
            "winners_median_abs_funding": round(_median(win), 8),
            "losers_median_abs_funding": round(_median(lose), 8),
            "mann_whitney_u": {k: (round(v, 6) if isinstance(v, float) else v)
                               for k, v in mwu.items()},
            "p_lt_0_05": sig,
        }

    # annualized GROSS (funding_ret only) and NET (funding_ret + fee_ret) carry.
    # Both are per-unit-notional returns → notional-independent (size cannot game).
    gross_rets = [t.funding_ret for t in trades]
    net_rets = [t.funding_ret + t.cost_ret for t in trades]
    ann_gross = _annualized(gross_rets, p.hold_days)
    ann_net = _annualized(net_rets, p.hold_days)

    # bootstrap CI on pooled median net PnL (fixed-seed, deterministic)
    boot = _bootstrap_median_ci(pooled)

    # notional distribution (level-scaling diagnostic)
    notionals = sorted(t.notional_usd for t in trades)
    notional_stats = {
        "min": round(notionals[0], 2) if notionals else 0.0,
        "median": round(_median(notionals), 2),
        "max": round(notionals[-1], 2) if notionals else 0.0,
        "n_at_cap": sum(1 for x in notionals if abs(x - p.notional_cap_usd) < 1e-9),
    }

    # ---- verdict against pre-registered falsifiers (V255_C.md / V255_D §5.4) ----
    pooled_median = _median(pooled)
    f1_median_le_0 = pooled_median <= 0.0
    f2_no_regime_sig = not any_regime_significant
    f3_ann_below_15 = ann_gross["annualized"] < 0.15   # V255.C bar: 15% (was 5%)
    # f4 semantics depend on the basis source:
    #  * zero  → single-series hedge cancels by construction; f4 CANNOT fire.
    #  * frozen → measured basis residual must be SMALL (< 0.1% notional, §5.4);
    #             a large residual fires f4 but only caps to KEEP_FLAG_GATED (the
    #             carry alpha itself is judged by f1–f3), it does NOT close the lane.
    if basis_source == "frozen" and basis_application is not None:
        f4_basis_fail = not basis_application["basis_residual_small"]
    else:
        f4_basis_fail = (not hedge_cancels)

    falsifiers_fired = {
        "f1_pooled_median_net_le_0": f1_median_le_0,
        "f2_mwu_p_ge_0.05_every_genuine_regime": f2_no_regime_sig,
        "f3_annualized_gross_below_15pct": f3_ann_below_15,
        "f4_basis_hedge_fails_empirically": f4_basis_fail,
    }
    any_fired = any(falsifiers_fired.values())
    # ADOPT gate (only reachable with real basis): the carry alpha survives
    # (f1–f3 pass), the measured basis residual is small (f4 pass), AND the pooled
    # median-net bootstrap CI excludes zero on the positive side.
    ci_lo_gt_zero = bool(boot.get("ci95_lo_gt_zero"))
    core_alpha_broken = f1_median_le_0 or f2_no_regime_sig or f3_ann_below_15

    if core_alpha_broken:
        # the carry alpha itself failed under (real or clean) pricing → lane closes
        verdict = "REFUTED"
    elif basis_source == "frozen":
        if (not f4_basis_fail) and ci_lo_gt_zero:
            verdict = "ADOPT"          # cap lifted — real basis is clean & median>0
        else:
            verdict = "KEEP_FLAG_GATED"  # real basis too large / CI touches 0
    else:
        # zero-basis: all pass but basis-cleanliness untested → hard-capped
        verdict = "KEEP_FLAG_GATED"

    result = {
        "version": "V255_C",
        "basis_source": basis_source,
        "basis_application": basis_application,
        "params": asdict(p),
        "universe": sorted(universe),
        "span": {"first": dates[0], "last": dates[-1], "n_days": len(dates)},
        "n_trades": len(trades),
        "basis_check": basis_check,
        "hedge_cancellation": {
            "spot_perp_price_pnl_cancels": hedge_cancels,
            "max_residual_usd": round(max_residual, 10),
        },
        "notional_distribution": notional_stats,
        "pooled_net_stats": _stats(pooled),
        "pooled_gross_carry_stats": _stats(gross_pooled),
        "pooled_median_net_bootstrap_ci95": boot,
        "per_regime_net_stats": per_regime_stats,
        "per_regime_separator_mwu": per_regime_mwu,
        "annualized_gross_carry": ann_gross,
        "annualized_net_carry": ann_net,
        "falsifiers_fired": falsifiers_fired,
        "any_falsifier_fired": any_fired,
        "verdict": verdict,
        "verdict_reason": _verdict_reason(
            verdict, falsifiers_fired, pooled_median, ann_gross, any_regime_significant,
            basis_source, basis_application, boot,
        ),
    }

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "v255c_scorer.json"), "w") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
        with open(os.path.join(out_dir, "v255c_trades.csv"), "w") as fh:
            fh.write("entry_date,exit_date,symbol,perp_side,entry_regime,"
                     "entry_funding,notional_usd,entry_price,exit_price,spot_price_pnl,"
                     "perp_price_pnl,funding_pnl,fee_pnl,pnl_usd\n")
            for t in trades:
                fh.write(f"{t.entry_date},{t.exit_date},{t.symbol},{t.perp_side},"
                         f"{t.entry_regime},{t.entry_funding:.8f},{t.notional_usd:.2f},"
                         f"{t.entry_price:.6f},{t.exit_price:.6f},{t.spot_price_pnl:.4f},"
                         f"{t.perp_price_pnl:.4f},{t.funding_pnl:.4f},{t.fee_pnl:.4f},"
                         f"{t.pnl_usd:.4f}\n")
    return result


def _verdict_reason(verdict, ff, pooled_median, ann_gross, any_sig,
                    basis_source="zero", basis_app=None, boot=None) -> str:
    if verdict == "REFUTED":
        parts = []
        if ff["f1_pooled_median_net_le_0"]:
            parts.append(f"pooled median net PnL ${pooled_median:.2f} <= $0")
        if ff["f2_mwu_p_ge_0.05_every_genuine_regime"]:
            parts.append("MWU p>=0.05 in EVERY genuine regime (level separator "
                         "does not hold on any subset)")
        if ff["f3_annualized_gross_below_15pct"]:
            parts.append(f"annualized gross carry {ann_gross['annualized_pct']:.2f}% "
                         f"< 15% (7d hold destroyed the alpha)")
        return "REFUTED: " + "; ".join(parts) + ". Funding-carry lane CLOSES."

    # ---- frozen (real-basis) verdicts -------------------------------------
    if basis_source == "frozen":
        ci = boot or {}
        med_abs = (basis_app or {}).get(
            "basis_residual_frac_of_notional", {}).get("median_abs", 0.0)
        n_real = (basis_app or {}).get("n_trades_real_basis", 0)
        base = (f"real-basis re-verify: median net ${pooled_median:.2f}, "
                f"CI95 [${ci.get('ci95_lo', 0):.2f}, ${ci.get('ci95_hi', 0):.2f}], "
                f"measured median |basis residual| {med_abs*1e4:.2f}bps of notional "
                f"over {n_real} real-basis trades")
        if verdict == "ADOPT":
            return (base + f" (< {_BASIS_SMALL_FRAC*1e4:.0f}bps §5.4 bar) → basis "
                    "hedge is CLEAN and median net-positive with CI excluding zero. "
                    "V255.C ADOPT UNLOCKED: remove the KEEP-FLAG-GATED cap.")
        # frozen but not adopted
        if pooled_median <= 0.0:
            why = "real basis flipped the pooled median to <= $0"
        elif not ff["f4_basis_hedge_fails_empirically"] and not ci.get("ci95_lo_gt_zero"):
            why = "median stays >0 but the bootstrap CI now touches zero"
        else:
            why = (f"measured median |basis residual| {med_abs*1e4:.2f}bps "
                   f">= {_BASIS_SMALL_FRAC*1e4:.0f}bps (§5.4 'large')")
        return (base + f". REVERT/HOLD at KEEP-FLAG-GATED: {why}. The zero-basis "
                "assumption was optimistic; median must be re-earned under real "
                "basis (longer hold / higher |funding| entry bar).")

    # ---- zero-basis (unchanged V255.C cap) --------------------------------
    base = (f"all pass: median net ${pooled_median:.2f}>$0, "
            f"annualized gross {ann_gross['annualized_pct']:.2f}%>=15%, "
            f"MWU<0.05 in >=1 genuine regime={any_sig}")
    return (base + ". CAPPED at KEEP-FLAG-GATED: basis-cleanliness UNTESTED "
            "(single price series, no perp/spot split) — real basis execution is a "
            "mandatory gate before ADOPT. Next: basis-data acquisition + V255.D "
            "live re-verify.")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="V255.C scorer (+ V255.D real basis)")
    ap.add_argument("out_dir", nargs="?", default=None,
                    help="optional dir for v255c_scorer.json + v255c_trades.csv")
    ap.add_argument("--basis-source", choices=["zero", "frozen"], default="zero",
                    help="zero = single-close hedge (default, byte-identical to V255.C); "
                         "frozen = real perp-mark + spot-index basis (V255.D)")
    ap.add_argument("--data-dir", default=None, help="override the data/ root")
    args = ap.parse_args()

    res = run_v255c(out_dir=args.out_dir, data_dir=args.data_dir,
                    basis_source=args.basis_source)
    keys = ["version", "basis_source", "basis_application", "n_trades",
            "hedge_cancellation", "notional_distribution", "pooled_net_stats",
            "pooled_gross_carry_stats", "pooled_median_net_bootstrap_ci95",
            "per_regime_net_stats", "per_regime_separator_mwu",
            "annualized_gross_carry", "annualized_net_carry",
            "falsifiers_fired", "verdict", "verdict_reason"]
    print(json.dumps({k: res[k] for k in keys}, indent=2, default=str))
