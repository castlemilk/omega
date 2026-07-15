"""V261 — $0 offline scorer + pre-registered verdict (on-chain flow primary).

Runs the full offline analysis for the V256/V261 flow-primary book, LOCKED to the
V261.md param table:
  1. Load frozen on-chain series + spot-index price (BTC, ETH).
  2. Build per-asset composite z (mean of 4 signed component z's, 30d window).
  3. Simulate non-overlapping directional trades ($10k, 5d hold, 5bps/side).
  4. Pooled + per-asset distributional stats (mean/median/p25/p75/WR/PF/N).
  5. MWU: winners vs losers by entry composite |z| (F2 mechanism gate).
  6. Bootstrap CI95 on pooled median (fixed-seed, deterministic).
  7. Annualized GROSS return (F3 noise-floor gate).
  8. Ablation: single-component + leave-one-out-whale (F4 SplyExNtv proxy honesty).
  9. Verdict against the pre-registered falsifiers (V261.md).

Deterministic: pure-python stats, ``math.fsum``, canonical sort, fixed-seed local
``random.Random``. Reuses the audited MWU + stats helpers from funding_carry's
phase0_separator (no strategy coupling — pure statistics).
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

from .loader import OnChainLoader
from .signals import COMPONENT_KEYS, composite_z_series
from .sim import FlowParams, FlowTrade, simulate_asset

# hold length in DAYS for annualization (5 positions on the daily grid = 5 days)
_HOLD_DAYS = 5
_BOOTSTRAP_SEED = 20250715
_BOOTSTRAP_N = 10_000
_ANN_FLOOR = 0.05          # F3: annualized gross >= 5%
_F4_FLIP_LABEL = "whale_velocity"  # the SplyExNtv proxy component


def _annualized_gross(gross_rets: list[float], hold_days: int) -> dict:
    if not gross_rets:
        return {"n": 0, "annualized": 0.0, "annualized_pct": 0.0}
    mean_ret = math.fsum(gross_rets) / len(gross_rets)
    ann = mean_ret * (365.0 / hold_days)
    return {
        "n": len(gross_rets),
        "mean_gross_ret_per_hold": round(mean_ret, 8),
        "hold_days": hold_days,
        "annualized": round(ann, 6),
        "annualized_pct": round(ann * 100.0, 3),
    }


def _bootstrap_median_ci(
    pnls: list[float], n_resamples: int = _BOOTSTRAP_N, seed: int = _BOOTSTRAP_SEED
) -> dict:
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

    lo, hi = _q(0.025), _q(0.975)
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


def _mwu_winners_losers(trades: list[FlowTrade]) -> dict:
    """MWU on entry |z|: winners vs losers. H1 (one-sided): winners have higher |z|."""
    win = [t.entry_abs_z for t in trades if t.is_winner]
    lose = [t.entry_abs_z for t in trades if not t.is_winner]
    mwu = mann_whitney_u(win, lose)
    pval = mwu.get("p_two_sided") if mwu.get("valid") else None
    return {
        "n_winners": len(win),
        "n_losers": len(lose),
        "winners_median_abs_z": round(_median(win), 6),
        "losers_median_abs_z": round(_median(lose), 6),
        "mann_whitney_u": {
            k: (round(v, 6) if isinstance(v, float) else v) for k, v in mwu.items()
        },
        "p_two_sided": round(pval, 6) if pval is not None else None,
        "p_lt_0_05": bool(pval is not None and pval < 0.05),
    }


def _run_book(
    loader: OnChainLoader, include: tuple[str, ...], p: FlowParams
) -> dict:
    """Simulate the flow book over ``include`` components; return trades + core stats."""
    all_trades: list[FlowTrade] = []
    per_asset: dict[str, dict] = {}
    for asset in loader.assets():
        onchain = loader.load_onchain(asset)
        price = loader.load_price(asset)
        composite, _ = composite_z_series(onchain, include=include)
        trades = simulate_asset(asset, composite, price, p)
        all_trades.extend(trades)
        per_asset[asset] = {
            "n_composite_days": len(composite),
            "stats": _stats([t.pnl_usd for t in trades]),
            "trades": trades,
        }
    pooled = [t.pnl_usd for t in all_trades]
    gross_rets = [t.gross_ret for t in all_trades]
    pooled_median = _median(pooled)
    ann = _annualized_gross(gross_rets, _HOLD_DAYS)
    mwu = _mwu_winners_losers(all_trades)
    f1 = pooled_median <= 0.0          # F1 REFUTE
    f2 = not mwu["p_lt_0_05"]          # F2 REFUTE (mechanism)
    f3 = ann["annualized"] < _ANN_FLOOR  # F3 REFUTE
    return {
        "include": list(include),
        "n_trades": len(all_trades),
        "pooled_stats": _stats(pooled),
        "pooled_median": round(pooled_median, 4),
        "annualized_gross": ann,
        "mwu_winners_losers": mwu,
        "f1_median_le_0": f1,
        "f2_mwu_not_sig": f2,
        "f3_ann_below_floor": f3,
        "core_pass": bool((not f1) and (not f2) and (not f3)),
        "_trades": all_trades,
        "_per_asset": per_asset,
    }


def run_v261(
    params: FlowParams | None = None,
    data_dir: str | None = None,
    out_dir: str | None = None,
) -> dict:
    p = params or FlowParams()
    loader = OnChainLoader(data_dir=data_dir)

    # ---- primary: full 4-component composite ----
    full = _run_book(loader, COMPONENT_KEYS, p)
    all_trades: list[FlowTrade] = full["_trades"]
    per_asset = full["_per_asset"]
    pooled = [t.pnl_usd for t in all_trades]
    boot = _bootstrap_median_ci(pooled)

    # ---- ablations (F4 SplyExNtv proxy honesty) ----
    # single-component books (diagnostic contribution color)
    singles = {
        k: {
            kk: vv for kk, vv in _run_book(loader, (k,), p).items()
            if not kk.startswith("_")
        }
        for k in COMPONENT_KEYS
    }
    # leave-one-out whale — does removing the proxy flip the verdict?
    loo_whale_keys = tuple(k for k in COMPONENT_KEYS if k != _F4_FLIP_LABEL)
    loo_whale = _run_book(loader, loo_whale_keys, p)
    loo_whale_pub = {k: v for k, v in loo_whale.items() if not k.startswith("_")}

    # ---- verdict against pre-registered falsifiers ----
    f1 = full["f1_median_le_0"]
    f2 = full["f2_mwu_not_sig"]
    f3 = full["f3_ann_below_floor"]
    core_pass = full["core_pass"]
    ci_excl_zero = bool(boot.get("ci95_excludes_zero"))
    # F4: whale proxy dominance — full passes core, but LOO-whale FAILS core.
    f4_proxy_dominant = bool(core_pass and not loo_whale["core_pass"])

    if not core_pass:
        verdict = "REFUTED"
    elif f4_proxy_dominant or (not ci_excl_zero):
        verdict = "KEEP_FLAG_GATED"
    else:
        verdict = "ADOPT"  # real alpha, flag-gated pending live on-chain feed wiring

    result = {
        "version": "V261",
        "params": asdict(p),
        "universe": [f"{a}USDT" for a in loader.assets()],
        "hold_days": _HOLD_DAYS,
        "n_trades": full["n_trades"],
        "per_asset_stats": {a: per_asset[a]["stats"] for a in per_asset},
        "per_asset_composite_days": {
            a: per_asset[a]["n_composite_days"] for a in per_asset
        },
        "pooled_net_stats": full["pooled_stats"],
        "pooled_median_bootstrap_ci95": boot,
        "annualized_gross": full["annualized_gross"],
        "mwu_winners_losers": full["mwu_winners_losers"],
        "ablation_single_component": singles,
        "ablation_leave_one_out_whale": loo_whale_pub,
        "falsifiers_fired": {
            "f1_pooled_median_le_0": f1,
            "f2_mwu_p_ge_0.05": f2,
            "f3_annualized_gross_below_5pct": f3,
            "f4_whale_proxy_dominance": f4_proxy_dominant,
        },
        "ci95_excludes_zero": ci_excl_zero,
        "verdict": verdict,
        "verdict_reason": _verdict_reason(
            verdict, f1, f2, f3, f4_proxy_dominant, ci_excl_zero,
            full, loo_whale_pub, boot,
        ),
    }

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "v261_scorer.json"), "w") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
        with open(os.path.join(out_dir, "v261_trades.csv"), "w") as fh:
            fh.write("asset,entry_date,exit_date,direction,entry_z,entry_price,"
                     "exit_price,gross_ret,gross_pnl_usd,fee_usd,pnl_usd\n")
            for t in all_trades:
                fh.write(f"{t.asset},{t.entry_date},{t.exit_date},{t.direction},"
                         f"{t.entry_z:.6f},{t.entry_price:.6f},{t.exit_price:.6f},"
                         f"{t.gross_ret:.8f},{t.gross_pnl_usd:.4f},{t.fee_usd:.4f},"
                         f"{t.pnl_usd:.4f}\n")
    # strip private keys before returning
    return result


def _verdict_reason(verdict, f1, f2, f3, f4, ci_excl, full, loo, boot) -> str:
    med = full["pooled_median"]
    ann = full["annualized_gross"]["annualized_pct"]
    p2 = full["mwu_winners_losers"]["p_two_sided"]
    if verdict == "REFUTED":
        parts = []
        if f1:
            parts.append(f"pooled median PnL ${med:.2f} <= $0")
        if f2:
            parts.append(f"MWU p={p2} >= 0.05 (winners' |z| not separable from losers')")
        if f3:
            parts.append(f"annualized gross {ann:.2f}% < 5% (below noise floor)")
        return ("REFUTED: " + "; ".join(parts)
                + ". On-chain flow-primary lane CLOSES (specific evidence, not data absence).")
    ci = boot or {}
    base = (f"median ${med:.2f}, CI95 [${ci.get('ci95_lo', 0):.2f}, "
            f"${ci.get('ci95_hi', 0):.2f}], MWU p={p2}, annualized gross {ann:.2f}%")
    if verdict == "ADOPT":
        return (base + ". F1-F3 pass, CI excludes zero, whale-proxy NOT dominant "
                "(LOO-whale still passes core). ADOPT — real alpha, default OFF flag, "
                "FLAG-GATED pending live on-chain feed wiring (no live CM feed yet).")
    # KEEP_FLAG_GATED
    why = []
    if f4:
        loo_med = loo["pooled_median"]
        loo_ann = loo["annualized_gross"]["annualized_pct"]
        why.append(f"SplyExNtv whale PROXY dominates: removing it flips the verdict "
                    f"(LOO-whale median ${loo_med:.2f}, ann {loo_ann:.2f}%, core_pass="
                    f"{loo['core_pass']})")
    if not ci_excl:
        why.append("bootstrap CI95 touches zero (marginal)")
    return (base + ". KEEP FLAG-GATED: " + "; ".join(why)
            + ". Alpha may be real but is not clean enough to lift the cap.")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="V261 on-chain flow-primary offline scorer")
    ap.add_argument("out_dir", nargs="?", default=None,
                    help="optional dir for v261_scorer.json + v261_trades.csv")
    ap.add_argument("--data-dir", default=None, help="override the data/ root")
    args = ap.parse_args()

    res = run_v261(out_dir=args.out_dir, data_dir=args.data_dir)
    print(json.dumps(res, indent=2, default=str))
