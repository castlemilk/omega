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

from .basis_hedge import empirical_basis_check
from .data import FundingDataLoader
from .hold_scaled import HoldScaledParams, HoldScaledTrade, simulate_universe_scaled
from .phase0_separator import _median, _stats, mann_whitney_u
from .regime import FundingRegime, FundingRegimeClassifier, build_market_index

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


def run_v255c(
    params: HoldScaledParams | None = None,
    data_dir: str | None = None,
    out_dir: str | None = None,
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

    # hedge-cancellation verification (spot + perp price PnL must be ~0)
    max_residual = 0.0
    for t in trades:
        max_residual = max(max_residual, abs(t.spot_price_pnl + t.perp_price_pnl))
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

    # ---- verdict against pre-registered falsifiers (V255_C.md) ----
    pooled_median = _median(pooled)
    f1_median_le_0 = pooled_median <= 0.0
    f2_no_regime_sig = not any_regime_significant
    f3_ann_below_15 = ann_gross["annualized"] < 0.15   # V255.C bar: 15% (was 5%)
    f4_basis_fail = (not hedge_cancels)  # cannot fire on single-series data

    falsifiers_fired = {
        "f1_pooled_median_net_le_0": f1_median_le_0,
        "f2_mwu_p_ge_0.05_every_genuine_regime": f2_no_regime_sig,
        "f3_annualized_gross_below_15pct": f3_ann_below_15,
        "f4_basis_hedge_fails_empirically": f4_basis_fail,
    }
    any_fired = any(falsifiers_fired.values())

    if any_fired:
        verdict = "REFUTED"
    else:
        # all pass, but basis-cleanliness untested → hard-capped (ADOPT excluded)
        verdict = "KEEP_FLAG_GATED"

    result = {
        "version": "V255_C",
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


def _verdict_reason(verdict, ff, pooled_median, ann_gross, any_sig) -> str:
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
        if ff["f4_basis_hedge_fails_empirically"]:
            parts.append("basis hedge did not cancel price risk on committed data")
        return "REFUTED: " + "; ".join(parts) + ". Funding-carry lane CLOSES."
    base = (f"all pass: median net ${pooled_median:.2f}>$0, "
            f"annualized gross {ann_gross['annualized_pct']:.2f}%>=15%, "
            f"MWU<0.05 in >=1 genuine regime={any_sig}")
    return (base + ". CAPPED at KEEP-FLAG-GATED: basis-cleanliness UNTESTED "
            "(single price series, no perp/spot split) — real basis execution is a "
            "mandatory gate before ADOPT. Next: basis-data acquisition + V255.D "
            "live re-verify.")


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else None
    res = run_v255c(out_dir=out)
    print(json.dumps({k: res[k] for k in
                      ["version", "n_trades", "hedge_cancellation",
                       "notional_distribution", "pooled_net_stats",
                       "pooled_gross_carry_stats", "pooled_median_net_bootstrap_ci95",
                       "per_regime_net_stats", "per_regime_separator_mwu",
                       "annualized_gross_carry", "annualized_net_carry",
                       "falsifiers_fired", "verdict", "verdict_reason"]},
                     indent=2, default=str))
