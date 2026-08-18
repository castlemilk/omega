#!/usr/bin/env python3
"""V271 Phase 0 — funding-carry live-paper lane feasibility scorer.

Answers F0 from ``training_log/V271.md``: can the V253 harness host an additive
k=1 funding-carry lane WITHOUT modifying strategy code in ``omega/nodes/``?

Two sub-gates, both scored mechanically here:

* **F0a — online-computable entry rule.** The V255.B/C/D entry rule is
  ``|funding| >= level_thresh`` AND ``regime not in {near_zero}``. The regime
  label comes from ``FundingRegimeClassifier.classify_span``, which standardizes
  the market funding index over the **FULL SPAN** (``regime._standardize``).
  A live lane on date *t* has only data up to *t*. This gate recomputes each
  date's label causally (expanding window) and counts how often that flips the
  **trade / no-trade** decision. Bar: <= 5% of dates.

* **F0b — additive harness seam.** Structural inspection of
  ``omega.live_paper.runner``: does the harness expose a multi-lane seam, or a
  single ``cycle_fn``?

$0 offline scorer. Reads frozen data only. Places no order, touches no daemon,
writes one JSON artifact. Deterministic: re-running produces a byte-identical
artifact (no wall-clock, no RNG, no network).
"""

from __future__ import annotations

import inspect
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from omega.nodes.funding_carry.data import FundingDataLoader  # noqa: E402
from omega.nodes.funding_carry.hold_scaled import (  # noqa: E402
    HoldScaledParams,
    simulate_universe_scaled,
)
from omega.nodes.funding_carry.regime import (  # noqa: E402
    FundingRegime,
    FundingRegimeClassifier,
    build_market_index,
)

# Pre-registered bar: > 5% of dates flipping trade/no-trade under a causal
# recomputation ⇒ the entry rule is not online-computable ⇒ F0a FAIL.
F0A_FLIP_BAR = 0.05


def score_f0a() -> dict:
    """Causal (expanding-window) vs full-span regime label — decision flips."""
    loader = FundingDataLoader()
    universe = loader.load_universe()
    dates, index = build_market_index(universe)
    clf = FundingRegimeClassifier()
    full = clf.classify_span(dates, index)
    params = HoldScaledParams()
    excluded = set(params.excluded_regimes)

    # How load-bearing is the regime filter at all? Count level-passing
    # candidate symbol-days it gates out.
    candidates = 0
    gated = 0
    candidate_regimes: Counter[str] = Counter()
    for series in universe.values():
        for d, f in zip(series.dates, series.funding):
            if abs(f) < params.level_thresh:
                continue
            candidates += 1
            label = full.get(d, FundingRegime.NEAR_ZERO)
            candidate_regimes[label.value] += 1
            if label.value in excluded:
                gated += 1

    # Causal recomputation: label date i using only index[:i+1].
    compared = 0
    label_flips = 0
    decision_flips = 0
    transitions: Counter[str] = Counter()
    for i in range(clf.avg_lookback, len(dates)):
        d = dates[i]
        online = clf.classify_span(dates[: i + 1], index[: i + 1])[d]
        offline = full[d]
        compared += 1
        if online is offline:
            continue
        label_flips += 1
        transitions[f"{offline.value}->{online.value}"] += 1
        if (offline.value in excluded) != (online.value in excluded):
            decision_flips += 1

    flip_rate = decision_flips / compared if compared else 0.0
    return {
        "span": {"start": dates[0], "end": dates[-1], "n_days": len(dates)},
        "symbols": len(universe),
        "candidate_symbol_days": candidates,
        "gated_by_regime_filter": gated,
        "gated_fraction": gated / candidates if candidates else 0.0,
        "candidate_regime_mix": dict(sorted(candidate_regimes.items())),
        "dates_compared": compared,
        "label_flips": label_flips,
        "label_flip_rate": label_flips / compared if compared else 0.0,
        "decision_flips": decision_flips,
        "decision_flip_rate": flip_rate,
        "transitions": dict(sorted(transitions.items())),
        "bar": F0A_FLIP_BAR,
        "pass": flip_rate <= F0A_FLIP_BAR,
    }


def score_f0b() -> dict:
    """Structural: does the harness expose a multi-lane seam?"""
    from omega.live_paper import runner as rt

    sig = inspect.signature(rt.LivePaperRunner.__init__)
    params = [p for p in sig.parameters if p != "self"]
    source = inspect.getsource(rt)
    lane_tokens = sum(source.lower().count(tok) for tok in ("lane",))
    single_cycle_fn = "cycle_fn" in params and not any(
        p.endswith(("lanes", "cycle_fns")) for p in params
    )
    return {
        "runner_init_params": params,
        "lane_token_occurrences_in_runner": lane_tokens,
        "single_cycle_fn": single_cycle_fn,
        # PASS would require an existing additive seam (multi-lane or a
        # composition hook). A single cycle_fn + zero lane vocabulary means a
        # lane must be BUILT, not hot-added.
        "pass": not single_cycle_fn or lane_tokens > 0,
    }


def score_gmeas() -> dict:
    """Context for the precommitted N: frozen ledger CI + live arrival rate."""
    loader = FundingDataLoader()
    universe = loader.load_universe()
    dates, index = build_market_index(universe)
    regimes = FundingRegimeClassifier().classify_span(dates, index)
    trades = simulate_universe_scaled(universe, regimes, HoldScaledParams())
    pnl = sorted(t.pnl_usd for t in trades)
    n = len(pnl)
    k = int(math.floor(n / 2 - 1.96 * math.sqrt(n) / 2))
    lo, hi = pnl[k], pnl[n - 1 - k]
    last = max(t.entry_date for t in trades)
    y, m, d = (int(x) for x in last.split("-"))
    import datetime as _dt

    end = _dt.date(y, m, d)
    rates = {}
    for w in (365, 730, 1095):
        cut = (end - _dt.timedelta(days=w)).isoformat()
        c = sum(1 for t in trades if t.entry_date >= cut)
        rates[f"last_{w}d"] = {"trades": c, "per_year": round(c / (w / 365.25), 2)}
    r12 = rates["last_365d"]["per_year"]
    half_width = (hi - lo) / 2
    return {
        "frozen_trades": n,
        "frozen_median_pnl_usd": round(statistics.median(pnl), 4),
        "frozen_median_ci95": [round(lo, 4), round(hi, 4)],
        "frozen_ci_half_width_usd": round(half_width, 4),
        "arrival_rates": rates,
        "precommitted_N": 100,
        "years_to_precommitted_N": round(100 / r12, 3) if r12 else None,
        # CI half-width at the precommitted N (scales ~ 1/sqrt(n)).
        "ci_half_width_at_N100_usd": round(half_width * math.sqrt(n / 100), 4),
    }


def main() -> int:
    f0a = score_f0a()
    f0b = score_f0b()
    gmeas = score_gmeas()
    verdict = "PASS" if (f0a["pass"] and f0b["pass"]) else "FAIL_R5"
    doc = {
        "version": "V271",
        "phase": "0",
        "gates": {"F0a": f0a, "F0b": f0b},
        "g_meas_context": gmeas,
        "verdict": verdict,
        "lane_activated": False,
    }
    out = ROOT / "data" / "v271_lane_feasibility.json"
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    print(json.dumps(doc["gates"], indent=2, sort_keys=True))
    print(json.dumps(gmeas, indent=2, sort_keys=True))
    print(f"\nV271 Phase 0 verdict: {verdict}   artifact: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
