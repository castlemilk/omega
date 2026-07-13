"""V255 Phase 0 — offline separator + verdict for the v2 directional strategy.

Runs the full $0 offline analysis:
  1. Load frozen funding + close for the universe.
  2. Classify every date into a funding regime (pre-registered boundaries).
  3. Simulate the v2 directional trades (no engine).
  4. Bucket trades by entry funding-regime; per-regime distributional stats.
  5. Separator: Mann-Whitney U of winners' vs losers' entry |z-score|.
  6. Independent-window count per funding regime vs spot-regime overlap.
  7. Verdict: ADVANCE (to V256 walk-forward grid) or REFUTED.

Pre-registered gate (V255.md §F):
  * PASS if MWU two-sided p <= 0.10 AND pooled median trade PnL > $0.
  * REFUTED otherwise.

Deterministic: pure-python stats (no RNG), canonical sorted, math.fsum.
Cross-checks MWU against scipy when available (diagnostic only; the pure
implementation is authoritative for the verdict).
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import os
from dataclasses import asdict

from .data import FundingDataLoader
from .regime import FundingRegime, FundingRegimeClassifier, build_market_index
from .strategy import StrategyParams, Trade, simulate_universe


# ---------------------------------------------------------------------------
# Statistics (pure python, deterministic)
# ---------------------------------------------------------------------------
def _phi(x: float) -> float:
    """Standard normal CDF via erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _rank_avg(values: list[float]) -> tuple[list[float], list[int]]:
    """Average ranks (1-based) for ``values``; also return tie-group sizes."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    tie_sizes: list[int] = []
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + 1 + j + 1) / 2.0  # average of 1-based positions
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        if j > i:
            tie_sizes.append(j - i + 1)
        i = j + 1
    return ranks, tie_sizes


def mann_whitney_u(a: list[float], b: list[float]) -> dict:
    """Tie-corrected MWU with normal approximation + continuity correction.

    Tests group ``a`` vs group ``b``. Returns U (for a), mean, std, z, and
    two-sided + one-sided (a>b) p-values. n1,n2 must be >= 1.
    """
    n1, n2 = len(a), len(b)
    if n1 == 0 or n2 == 0:
        return {"n1": n1, "n2": n2, "valid": False}
    combined = a + b
    ranks, tie_sizes = _rank_avg(combined)
    r1 = math.fsum(ranks[:n1])
    u1 = r1 - n1 * (n1 + 1) / 2.0
    mu = n1 * n2 / 2.0
    big_n = n1 + n2
    tie_term = math.fsum(t**3 - t for t in tie_sizes)
    var = (n1 * n2 / 12.0) * ((big_n + 1) - tie_term / (big_n * (big_n - 1)))
    if var <= 0.0:
        return {"n1": n1, "n2": n2, "valid": False, "u1": u1, "reason": "zero_variance"}
    sigma = math.sqrt(var)
    # continuity correction toward the mean
    cc = 0.5
    if u1 > mu:
        z = (u1 - mu - cc) / sigma
    elif u1 < mu:
        z = (u1 - mu + cc) / sigma
    else:
        z = 0.0
    p_two = 2.0 * (1.0 - _phi(abs(z)))
    p_one_a_gt_b = 1.0 - _phi(z)  # H1: a stochastically greater than b
    return {
        "n1": n1, "n2": n2, "valid": True,
        "u1": u1, "mu": mu, "sigma": sigma, "z": z,
        "p_two_sided": p_two, "p_one_sided_a_gt_b": p_one_a_gt_b,
    }


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    idx = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[idx]


def _stats(pnls: list[float]) -> dict:
    n = len(pnls)
    if n == 0:
        return {"n": 0}
    wins = [x for x in pnls if x > 0]
    total = math.fsum(pnls)
    gross_win = math.fsum(x for x in pnls if x > 0)
    gross_loss = -math.fsum(x for x in pnls if x < 0)
    return {
        "n": n,
        "total_pnl_usd": round(total, 2),
        "mean_pnl_usd": round(total / n, 2),
        "median_pnl_usd": round(_median(pnls), 2),
        "p25_pnl_usd": round(_pct(pnls, 0.25), 2),
        "p75_pnl_usd": round(_pct(pnls, 0.75), 2),
        "win_rate": round(len(wins) / n, 4),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
    }


# ---------------------------------------------------------------------------
# Independent-window counting (V249 preflight, applied to funding regimes)
# ---------------------------------------------------------------------------
def count_independent_windows(
    date_regimes: dict[str, FundingRegime], window_days: int = 90
) -> dict:
    """Tile the span with non-overlapping ``window_days`` slots, label each by
    the majority funding regime, and count per regime. This is the funding
    analogue of V249's spot-regime independent-N audit.
    """
    dates = sorted(date_regimes)
    if not dates:
        return {}
    d0 = _dt.date.fromisoformat(dates[0])
    d1 = _dt.date.fromisoformat(dates[-1])
    span_days = (d1 - d0).days + 1
    n_slots = span_days // window_days
    by_date = {d: date_regimes[d] for d in dates}
    counts: dict[str, int] = {r.value: 0 for r in FundingRegime}
    slot_labels = []
    for s in range(n_slots):
        start = d0 + _dt.timedelta(days=s * window_days)
        end = start + _dt.timedelta(days=window_days)
        votes: dict[str, int] = {}
        cur = start
        while cur < end:
            key = cur.isoformat()
            if key in by_date:
                r = by_date[key].value
                votes[r] = votes.get(r, 0) + 1
            cur += _dt.timedelta(days=1)
        if votes:
            # majority label, tie-broken by canonical regime order
            label = sorted(votes, key=lambda r: (-votes[r], r))[0]
            counts[label] += 1
            slot_labels.append({"start": start.isoformat(), "regime": label})
    return {
        "span_days": span_days,
        "window_days": window_days,
        "n_independent_slots": n_slots,
        "per_regime_independent_n": counts,
        "slot_labels": slot_labels,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def run_phase0(
    params: StrategyParams | None = None,
    data_dir: str | None = None,
    out_dir: str | None = None,
) -> dict:
    p = params or StrategyParams()
    loader = FundingDataLoader(data_dir=data_dir)
    universe = loader.load_universe()

    # regimes
    dates, market_index = build_market_index(universe)
    clf = FundingRegimeClassifier()
    date_regimes = clf.classify_span(dates, market_index)

    # trades
    trades = simulate_universe(universe, p)

    # bucket by entry funding-regime
    regime_pnls: dict[str, list[float]] = {r.value: [] for r in FundingRegime}
    for t in trades:
        r = date_regimes.get(t.entry_date, FundingRegime.NEAR_ZERO).value
        regime_pnls[r].append(t.pnl_usd)

    pooled_pnls = [t.pnl_usd for t in trades]

    # separator: winners vs losers by entry |z|
    win_z = [abs(t.entry_z) for t in trades if t.is_winner]
    lose_z = [abs(t.entry_z) for t in trades if not t.is_winner]
    mwu = mann_whitney_u(win_z, lose_z)

    # scipy cross-check (diagnostic only)
    scipy_check = None
    try:
        from scipy import stats as _sps  # type: ignore
        if win_z and lose_z:
            u, pv = _sps.mannwhitneyu(win_z, lose_z, alternative="two-sided")
            scipy_check = {"u": float(u), "p_two_sided": float(pv)}
    except Exception as exc:  # pragma: no cover - optional dep
        scipy_check = {"error": str(exc)}

    # verdict (pre-registered)
    pooled_median = _median(pooled_pnls)
    mwu_p = mwu.get("p_two_sided") if mwu.get("valid") else 1.0
    passes = bool(mwu.get("valid") and mwu_p <= 0.10 and pooled_median > 0.0)
    verdict = "ADVANCE" if passes else "REFUTED"

    # window independence
    windows = count_independent_windows(date_regimes)

    result = {
        "version": "V255_PHASE0",
        "params": asdict(p),
        "universe": sorted(universe),
        "span": {"first": dates[0], "last": dates[-1], "n_days": len(dates)},
        "n_trades": len(trades),
        "pooled_stats": _stats(pooled_pnls),
        "per_regime_stats": {r: _stats(regime_pnls[r]) for r in regime_pnls},
        "separator": {
            "winners_median_abs_z": round(_median(win_z), 4),
            "losers_median_abs_z": round(_median(lose_z), 4),
            "n_winners": len(win_z),
            "n_losers": len(lose_z),
            "mann_whitney_u": {k: (round(v, 6) if isinstance(v, float) else v)
                               for k, v in mwu.items()},
            "scipy_cross_check": scipy_check,
        },
        "funding_regime_windows": windows,
        "verdict": verdict,
        "verdict_reason": _verdict_reason(mwu, mwu_p, pooled_median, passes),
    }

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "v255_phase0_separator.json"), "w") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
        # per-trade ledger for auditability
        with open(os.path.join(out_dir, "v255_phase0_trades.csv"), "w") as fh:
            fh.write("entry_date,exit_date,symbol,side,entry_z,entry_funding,"
                     "entry_price,exit_price,price_ret,funding_ret,cost_ret,pnl_usd\n")
            for t in trades:
                fh.write(f"{t.entry_date},{t.exit_date},{t.symbol},{t.side},"
                         f"{t.entry_z:.6f},{t.entry_funding:.8f},{t.entry_price:.6f},"
                         f"{t.exit_price:.6f},{t.price_ret:.8f},{t.funding_ret:.8f},"
                         f"{t.cost_ret:.8f},{t.pnl_usd:.4f}\n")
    return result


def _verdict_reason(mwu: dict, mwu_p: float, pooled_median: float, passes: bool) -> str:
    if not mwu.get("valid"):
        return f"MWU invalid ({mwu.get('reason', 'degenerate groups')}) — REFUTED"
    if passes:
        return (f"MWU p={mwu_p:.4f} <= 0.10 AND pooled median trade "
                f"${pooled_median:.2f} > $0 — z-score discriminates, edge present")
    parts = []
    if mwu_p > 0.10:
        parts.append(f"MWU p={mwu_p:.4f} > 0.10 (z-score does NOT discriminate)")
    if pooled_median <= 0.0:
        parts.append(f"pooled median trade ${pooled_median:.2f} <= $0")
    return "REFUTED: " + "; ".join(parts)


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else None
    res = run_phase0(out_dir=out)
    print(json.dumps({k: res[k] for k in
                      ["version", "n_trades", "pooled_stats", "separator", "verdict",
                       "verdict_reason"]}, indent=2, default=str))
