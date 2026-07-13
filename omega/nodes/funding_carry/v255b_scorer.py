"""V255.B — $0 offline scorer + pre-registered verdict (basis-hedged carry).

Runs the full offline analysis for the v1 basis-hedged strategy:
  1. Load frozen funding + close; classify funding regimes (fixed a-priori).
  2. Run the empirical basis check (mechanism gate — surfaced before scoring).
  3. Simulate the V255.B basis-hedged trades (level entry, near_zero excluded).
  4. Verify the hedge cancels price risk (spot+perp price PnL == 0).
  5. Pooled + per-regime distributional stats (NET PnL, after 2-leg fee).
  6. Per-genuine-regime MWU: winners vs losers by |entry funding| (the level
     separator Phase 0 found at p<0.0001).
  7. Annualized GROSS carry (pre-fee).
  8. Verdict against the pre-registered falsifiers (V255_B.md).

Deterministic: pure-python stats (no RNG), math.fsum, canonical sort. Reuses the
audited MWU + stats helpers from phase0_separator.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict

from .basis_hedge import (
    BasisHedgeParams,
    HedgedTrade,
    empirical_basis_check,
    simulate_universe_hedged,
)
from .data import FundingDataLoader
from .phase0_separator import _median, _stats, mann_whitney_u
from .regime import FundingRegime, FundingRegimeClassifier, build_market_index

GENUINE_REGIMES = (
    FundingRegime.NEGATIVE_CARRY.value,
    FundingRegime.POSITIVE_CARRY.value,
    FundingRegime.HIGH_VOL.value,
)


def _annualized_gross_carry(trades: list[HedgedTrade], hold_days: int) -> dict:
    """Mean per-trade GROSS carry return (funding_ret, price-neutral) annualized.

    Each trade's funding_ret is the fractional carry over ``hold_days``. The
    annualization factor is 365/hold_days (holds are non-overlapping per symbol).
    """
    if not trades:
        return {"n": 0, "annualized_gross": 0.0}
    carry_rets = [t.funding_ret for t in trades]  # per-unit-notional over hold
    mean_ret = math.fsum(carry_rets) / len(carry_rets)
    ann = mean_ret * (365.0 / hold_days)
    return {
        "n": len(trades),
        "mean_carry_ret_per_hold": round(mean_ret, 8),
        "hold_days": hold_days,
        "annualized_gross": round(ann, 6),
        "annualized_gross_pct": round(ann * 100.0, 3),
    }


def run_v255b(
    params: BasisHedgeParams | None = None,
    data_dir: str | None = None,
    out_dir: str | None = None,
) -> dict:
    p = params or BasisHedgeParams()
    loader = FundingDataLoader(data_dir=data_dir)
    universe = loader.load_universe()

    # mechanism gate: can the hedge be validated empirically?
    basis_check = empirical_basis_check(universe)

    # regimes (fixed a-priori boundaries)
    dates, market_index = build_market_index(universe)
    clf = FundingRegimeClassifier()
    date_regimes = clf.classify_span(dates, market_index)

    # trades (level entry, near_zero excluded, sign(funding) carry receiver)
    trades = simulate_universe_hedged(universe, date_regimes, p)

    # hedge-cancellation verification (spot + perp price PnL must be ~0)
    max_residual = 0.0
    for t in trades:
        max_residual = max(max_residual, abs(t.spot_price_pnl + t.perp_price_pnl))
    hedge_cancels = max_residual < 1e-6

    pooled = [t.pnl_usd for t in trades]
    gross_pooled = [t.gross_carry_pnl for t in trades]

    # per-regime NET stats
    regime_trades: dict[str, list[HedgedTrade]] = {r: [] for r in GENUINE_REGIMES}
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

    # annualized gross carry (pre-fee)
    ann = _annualized_gross_carry(trades, p.hold_days)

    # ---- verdict against pre-registered falsifiers (V255_B.md) ----
    pooled_median = _median(pooled)
    f1_median_le_0 = pooled_median <= 0.0
    f2_no_regime_sig = not any_regime_significant
    f3_ann_below_5 = ann["annualized_gross"] < 0.05
    # f4: basis falsifier cannot fire on single-series data (documented)
    f4_basis_fail = (not hedge_cancels)  # would only trip if cancellation broke

    falsifiers_fired = {
        "f1_pooled_median_net_le_0": f1_median_le_0,
        "f2_mwu_p_ge_0.05_every_genuine_regime": f2_no_regime_sig,
        "f3_annualized_gross_below_5pct": f3_ann_below_5,
        "f4_basis_hedge_fails_empirically": f4_basis_fail,
    }
    any_fired = any(falsifiers_fired.values())

    if any_fired:
        verdict = "REFUTED"
    elif not basis_check["realized_basis_measurable"]:
        # all pass, but basis-cleanliness untested → capped
        verdict = "KEEP_FLAG_GATED"
    else:
        verdict = "ADOPT"

    result = {
        "version": "V255_B",
        "params": asdict(p),
        "universe": sorted(universe),
        "span": {"first": dates[0], "last": dates[-1], "n_days": len(dates)},
        "n_trades": len(trades),
        "basis_check": basis_check,
        "hedge_cancellation": {
            "spot_perp_price_pnl_cancels": hedge_cancels,
            "max_residual_usd": round(max_residual, 10),
        },
        "pooled_net_stats": _stats(pooled),
        "pooled_gross_carry_stats": _stats(gross_pooled),
        "per_regime_net_stats": per_regime_stats,
        "per_regime_separator_mwu": per_regime_mwu,
        "annualized_gross_carry": ann,
        "falsifiers_fired": falsifiers_fired,
        "any_falsifier_fired": any_fired,
        "verdict": verdict,
        "verdict_reason": _verdict_reason(
            verdict, falsifiers_fired, pooled_median, ann, any_regime_significant,
            basis_check,
        ),
    }

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "v255b_scorer.json"), "w") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
        with open(os.path.join(out_dir, "v255b_trades.csv"), "w") as fh:
            fh.write("entry_date,exit_date,symbol,perp_side,entry_regime,"
                     "entry_funding,entry_price,exit_price,spot_price_pnl,"
                     "perp_price_pnl,funding_pnl,fee_pnl,pnl_usd\n")
            for t in trades:
                fh.write(f"{t.entry_date},{t.exit_date},{t.symbol},{t.perp_side},"
                         f"{t.entry_regime},{t.entry_funding:.8f},{t.entry_price:.6f},"
                         f"{t.exit_price:.6f},{t.spot_price_pnl:.4f},{t.perp_price_pnl:.4f},"
                         f"{t.funding_pnl:.4f},{t.fee_pnl:.4f},{t.pnl_usd:.4f}\n")
    return result


def _verdict_reason(verdict, ff, pooled_median, ann, any_sig, basis_check) -> str:
    if verdict == "REFUTED":
        parts = []
        if ff["f1_pooled_median_net_le_0"]:
            parts.append(f"pooled median net PnL ${pooled_median:.2f} <= $0")
        if ff["f2_mwu_p_ge_0.05_every_genuine_regime"]:
            parts.append("MWU p>=0.05 in EVERY genuine regime (level separator "
                         "does not hold on any subset)")
        if ff["f3_annualized_gross_below_5pct"]:
            parts.append(f"annualized gross carry {ann['annualized_gross_pct']:.2f}% "
                         f"< 5%")
        if ff["f4_basis_hedge_fails_empirically"]:
            parts.append("basis hedge did not cancel price risk on committed data")
        return "REFUTED: " + "; ".join(parts)
    base = (f"all pass: median net ${pooled_median:.2f}>$0, "
            f"annualized gross {ann['annualized_gross_pct']:.2f}%>=5%, "
            f"MWU<0.05 in >=1 genuine regime={any_sig}")
    if verdict == "KEEP_FLAG_GATED":
        return (base + ". CAPPED at KEEP-FLAG-GATED: basis-cleanliness UNTESTED "
                "(single price series, no perp/spot split) — real basis execution "
                "is a mandatory gate for V255.C.")
    return base + ". ADOPT."


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else None
    res = run_v255b(out_dir=out)
    print(json.dumps({k: res[k] for k in
                      ["version", "n_trades", "hedge_cancellation", "pooled_net_stats",
                       "pooled_gross_carry_stats", "per_regime_net_stats",
                       "per_regime_separator_mwu", "annualized_gross_carry",
                       "falsifiers_fired", "verdict", "verdict_reason"]},
                     indent=2, default=str))
