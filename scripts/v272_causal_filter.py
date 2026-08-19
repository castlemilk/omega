#!/usr/bin/env python3
"""V272 — causal-labelling honesty test for the funding-carry regime filter.

Pre-registered in ``omega/nodes/victoria/training_log/V272.md`` (commit
``575990c``) BEFORE any scoring. Scores exactly three configurations of the
V255.C entry rule against the frozen V255.D real-basis book:

  * **FROZEN** — original full-span ``classify_span``, ``near_zero`` excluded.
    This is the G4 sanity re-score; it must reproduce n=1,225 / median $1.9539.
  * **A (causal)** — ``classify_span_causal`` (expanding-window standardizer),
    ``near_zero`` excluded. Everything else identical.
  * **B (no filter)** — original labels, ``excluded_regimes = ()``.

Deterministic: pure-python stats, ``math.fsum``, canonical sort, fixed local
``random.Random`` seeds, no wall-clock anywhere in the emitted JSON.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from omega.nodes.funding_carry.data import FundingDataLoader  # noqa: E402
from omega.nodes.funding_carry.hold_scaled import (  # noqa: E402
    HoldScaledParams,
    simulate_universe_scaled,
)
from omega.nodes.funding_carry.phase0_separator import _median, _stats  # noqa: E402
from omega.nodes.funding_carry.regime import (  # noqa: E402
    FundingRegimeClassifier,
    build_market_index,
)
from omega.nodes.funding_carry.v255c_scorer import (  # noqa: E402
    _apply_frozen_basis,
    _bootstrap_median_ci,
)

# Pre-registered constants (V272.md §3).
FROZEN_CI95 = (1.1347, 2.7957)
FROZEN_N = 1225
FROZEN_MEDIAN = 1.9539
PAIRED_WINDOW_DAYS = 90
PAIRED_BOOTSTRAP_N = 10_000
PAIRED_BOOTSTRAP_SEED = 20260819


def _d(s: str) -> _dt.date:
    return _dt.date.fromisoformat(s)


def _window_index(entry_date: str, span_first: str) -> int:
    return (_d(entry_date) - _d(span_first)).days // PAIRED_WINDOW_DAYS


def _score(trades, label: str) -> dict:
    pnls = [t.pnl_usd for t in trades]
    boot = _bootstrap_median_ci(pnls)
    regime_counts: dict[str, int] = {}
    for t in trades:
        regime_counts[t.entry_regime] = regime_counts.get(t.entry_regime, 0) + 1
    return {
        "label": label,
        "n_trades": len(trades),
        "stats": _stats(pnls),
        "median_bootstrap_ci95": boot,
        "entry_regime_counts": {k: regime_counts[k] for k in sorted(regime_counts)},
    }


def _fingerprint(trades) -> str:
    """Order-independent identity of a trade set (no PnL, so join-safe)."""
    keys = sorted(f"{t.entry_date}|{t.symbol}|{t.perp_side}" for t in trades)
    import hashlib

    return hashlib.sha256("\n".join(keys).encode()).hexdigest()[:16]


def _paired_window_delta(trades_a, trades_b, span_first: str) -> dict:
    """G3: paired 90d-calendar-window bootstrap on mean-per-trade Δ (A − B)."""
    by_a: dict[int, list[float]] = {}
    by_b: dict[int, list[float]] = {}
    for t in trades_a:
        by_a.setdefault(_window_index(t.entry_date, span_first), []).append(t.pnl_usd)
    for t in trades_b:
        by_b.setdefault(_window_index(t.entry_date, span_first), []).append(t.pnl_usd)

    all_w = sorted(set(by_a) | set(by_b))
    included = [w for w in all_w if by_a.get(w) and by_b.get(w)]
    dropped = [
        {
            "window": w,
            "n_a": len(by_a.get(w, [])),
            "n_b": len(by_b.get(w, [])),
        }
        for w in all_w
        if w not in included
    ]

    deltas = [
        (math.fsum(by_a[w]) / len(by_a[w])) - (math.fsum(by_b[w]) / len(by_b[w]))
        for w in included
    ]

    ci: dict = {"valid": False}
    if deltas:
        rng = random.Random(PAIRED_BOOTSTRAP_SEED)
        k = len(deltas)
        means: list[float] = []
        for _ in range(PAIRED_BOOTSTRAP_N):
            sample = [deltas[rng.randrange(k)] for _ in range(k)]
            means.append(math.fsum(sample) / k)
        means.sort()

        def _q(q: float) -> float:
            idx = min(
                PAIRED_BOOTSTRAP_N - 1, max(0, round(q * (PAIRED_BOOTSTRAP_N - 1)))
            )
            return means[idx]

        lo, hi = _q(0.025), _q(0.975)
        ci = {
            "valid": True,
            "n_windows": k,
            "n_resamples": PAIRED_BOOTSTRAP_N,
            "seed": PAIRED_BOOTSTRAP_SEED,
            "point_mean_delta": round(math.fsum(deltas) / k, 4),
            "ci95_lo": round(lo, 4),
            "ci95_hi": round(hi, 4),
            "ci95_excludes_zero": bool(lo > 0.0 or hi < 0.0),
        }

    return {
        "window_days": PAIRED_WINDOW_DAYS,
        "span_first": span_first,
        "n_windows_total": len(all_w),
        "n_windows_included": len(included),
        "windows_dropped": dropped,
        "per_window_delta_usd": [round(x, 4) for x in deltas],
        "bootstrap": ci,
    }


def run(data_dir: str | None, out_dir: str | None) -> dict:
    loader = FundingDataLoader(data_dir=data_dir)
    universe = loader.load_universe()
    dates, market_index = build_market_index(universe)
    clf = FundingRegimeClassifier()

    reg_full = clf.classify_span(dates, market_index)
    reg_causal = clf.classify_span_causal(dates, market_index)

    n_flip = sum(1 for d in dates if reg_full[d] != reg_causal[d])
    excluded = HoldScaledParams().excluded_regimes
    n_trade_flip = sum(
        1
        for d in dates
        if (reg_full[d].value in excluded) != (reg_causal[d].value in excluded)
    )

    p_filtered = HoldScaledParams()
    p_unfiltered = HoldScaledParams(excluded_regimes=())

    configs = {
        "frozen": (reg_full, p_filtered),
        "causal_A": (reg_causal, p_filtered),
        "nofilter_B": (reg_full, p_unfiltered),
    }

    variants: dict[str, dict] = {}
    trade_sets: dict[str, list] = {}
    for name, (regs, params) in configs.items():
        trades = simulate_universe_scaled(universe, regs, params)
        basis = _apply_frozen_basis(trades, data_dir)  # V255.D real basis
        scored = _score(trades, name)
        scored["basis_application"] = {
            k: basis[k]
            for k in (
                "n_trades_real_basis",
                "n_trades_fallback_symbol",
                "n_trades_fallback_date",
                "basis_residual_small",
            )
        }
        scored["trade_set_fingerprint"] = _fingerprint(trades)
        variants[name] = scored
        trade_sets[name] = trades

    span_first = dates[0]

    # ---- G4: sanity ------------------------------------------------------
    g4_n = variants["frozen"]["n_trades"] == FROZEN_N
    g4_med = (
        abs(variants["frozen"]["median_bootstrap_ci95"]["point_median"] - FROZEN_MEDIAN)
        < 5e-5
    )
    g4 = {
        "assertion": f"original classify_span reproduces n={FROZEN_N}, "
                     f"median=${FROZEN_MEDIAN}",
        "observed_n": variants["frozen"]["n_trades"],
        "observed_median": variants["frozen"]["median_bootstrap_ci95"]["point_median"],
        "status": "pass" if (g4_n and g4_med) else "fail",
    }

    # ---- G1: causal-A CI overlaps frozen CI ------------------------------
    a_ci = variants["causal_A"]["median_bootstrap_ci95"]
    a_lo, a_hi = a_ci["ci95_lo"], a_ci["ci95_hi"]
    overlaps = (a_lo <= FROZEN_CI95[1]) and (a_hi >= FROZEN_CI95[0])
    g1 = {
        "assertion": f"causal-A median CI95 overlaps frozen {list(FROZEN_CI95)}",
        "causal_a_ci95": [a_lo, a_hi],
        "frozen_ci95": list(FROZEN_CI95),
        "status": "pass" if overlaps else "fail",
    }

    # ---- G2: drop-B (report only) ----------------------------------------
    b_ci = variants["nofilter_B"]["median_bootstrap_ci95"]
    g2 = {
        "assertion": "drop-filter B median CI95 (numeric report, not a gate)",
        "nofilter_b_ci95": [b_ci["ci95_lo"], b_ci["ci95_hi"]],
        "point_median": b_ci["point_median"],
        "status": "report_only",
    }

    # ---- G3: A vs B paired-window bootstrap ------------------------------
    paired = _paired_window_delta(
        trade_sets["causal_A"], trade_sets["nofilter_B"], span_first
    )
    boot3 = paired["bootstrap"]
    g3 = {
        "assertion": "paired 90d-window bootstrap on mean-per-trade Δ (A − B)",
        "ci95": [boot3.get("ci95_lo"), boot3.get("ci95_hi")]
        if boot3.get("valid")
        else None,
        "point_mean_delta": boot3.get("point_mean_delta"),
        "excludes_zero": boot3.get("ci95_excludes_zero"),
        "interpretation": (
            "filter carries real signal"
            if boot3.get("ci95_excludes_zero")
            else "filter is noise (CI contains zero)"
        ),
        "status": "report_only",
    }

    secondary = {
        "pooled_mean_per_trade": {
            k: variants[k]["stats"]["mean_pnl_usd"] for k in variants
        },
        "total_pnl_usd": {k: variants[k]["stats"]["total_pnl_usd"] for k in variants},
        "n_trades": {k: variants[k]["n_trades"] for k in variants},
        "delta_A_minus_frozen": {
            "n": variants["causal_A"]["n_trades"] - variants["frozen"]["n_trades"],
            "median": round(
                variants["causal_A"]["median_bootstrap_ci95"]["point_median"]
                - variants["frozen"]["median_bootstrap_ci95"]["point_median"],
                4,
            ),
            "total_pnl_usd": round(
                variants["causal_A"]["stats"]["total_pnl_usd"]
                - variants["frozen"]["stats"]["total_pnl_usd"],
                2,
            ),
        },
        "delta_B_minus_frozen": {
            "n": variants["nofilter_B"]["n_trades"] - variants["frozen"]["n_trades"],
            "median": round(
                variants["nofilter_B"]["median_bootstrap_ci95"]["point_median"]
                - variants["frozen"]["median_bootstrap_ci95"]["point_median"],
                4,
            ),
            "total_pnl_usd": round(
                variants["nofilter_B"]["stats"]["total_pnl_usd"]
                - variants["frozen"]["stats"]["total_pnl_usd"],
                2,
            ),
        },
    }

    # Fraction of the frozen ledger that survives causal labelling.
    frozen_keys = {
        (t.entry_date, t.symbol, t.perp_side) for t in trade_sets["frozen"]
    }
    causal_keys = {
        (t.entry_date, t.symbol, t.perp_side) for t in trade_sets["causal_A"]
    }
    survival = {
        "n_frozen": len(frozen_keys),
        "n_causal": len(causal_keys),
        "n_common": len(frozen_keys & causal_keys),
        "frac_frozen_surviving_causal": round(
            len(frozen_keys & causal_keys) / len(frozen_keys), 6
        )
        if frozen_keys
        else 0.0,
        "n_causal_only": len(causal_keys - frozen_keys),
    }

    result = {
        "version": "V272",
        "prereg": "omega/nodes/victoria/training_log/V272.md",
        "params": {
            "filtered": {
                "level_thresh": p_filtered.level_thresh,
                "hold_days": p_filtered.hold_days,
                "excluded_regimes": list(p_filtered.excluded_regimes),
            },
            "unfiltered": {"excluded_regimes": list(p_unfiltered.excluded_regimes)},
            "basis_source": "frozen",
        },
        "span": {"first": dates[0], "last": dates[-1], "n_days": len(dates)},
        "universe": sorted(universe),
        "label_flips": {
            "n_dates": len(dates),
            "n_regime_label_flips": n_flip,
            "frac_regime_label_flips": round(n_flip / len(dates), 6),
            "n_trade_nontrade_flips": n_trade_flip,
            "frac_trade_nontrade_flips": round(n_trade_flip / len(dates), 6),
        },
        "variants": variants,
        "ledger_survival": survival,
        "paired_window_g3": paired,
        "gates": {"G4": g4, "G1": g1, "G2": g2, "G3": g3},
        "secondary": secondary,
    }

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "v272_causal_filter.json"), "w") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
        for name, trades in trade_sets.items():
            with open(os.path.join(out_dir, f"v272_{name}_trades.csv"), "w") as fh:
                fh.write("entry_date,exit_date,symbol,perp_side,entry_regime,"
                         "entry_funding,notional_usd,pnl_usd\n")
                for t in trades:
                    fh.write(f"{t.entry_date},{t.exit_date},{t.symbol},{t.perp_side},"
                             f"{t.entry_regime},{t.entry_funding:.8f},"
                             f"{t.notional_usd:.2f},{t.pnl_usd:.4f}\n")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="V272 causal-filter scorer")
    ap.add_argument("out_dir", nargs="?", default=None)
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()
    res = run(args.data_dir, args.out_dir)
    print(json.dumps(res, indent=2, sort_keys=True, default=str))
