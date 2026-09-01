"""The ASX engine: rebalance loop, costs, and an honest evaluation.

Paper only. Nothing here places an order, and nothing here should — the Victoria
campaign's own phase transition (V249 → V253) put live-paper before capital for the
same reason: forward, out-of-sample observations are the only ones that cannot be
Goodharted, and they accrue whether or not you are risking money.

Two properties are load-bearing:

1. **Costs are charged on turnover, every rebalance.** ASX retail friction (~20bp round
   trip) is roughly ten times the crypto friction that already killed a lane in this
   campaign (V272: a 1.3–1.5bp edge sitting under 1.86bp of cost). A backtest that does
   not charge turnover is not measuring a strategy, it is measuring a ranking.

2. **The evaluation reports the MEDIAN and the hit rate, not just the mean.** V289 §7
   found a +8.28% mean period return whose median was −0.28% and whose top three periods
   carried 61% of the total. A mean alone would have called that a strategy.
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from omega.nodes.asx.panel import PanelSpec, build_panel
from omega.nodes.asx.portfolio import PortfolioSpec, build_target, turnover

if TYPE_CHECKING:
    from omega.nodes.asx.benchmark import IndexBenchmark

logger = logging.getLogger("omega.nodes.asx.engine")


@dataclass(frozen=True)
class CostModel:
    """ASX retail friction. Defaults are deliberately pessimistic."""

    bps_per_side: float = 10.0  # ~0.1%/side brokerage
    slippage_bps: float = 5.0  # spread/impact on a mid/small-cap book

    def charge(self, one_way_turnover: float) -> float:
        """Cost as a fraction of NAV for a rebalance of the given turnover."""
        return one_way_turnover * 2.0 * (self.bps_per_side + self.slippage_bps) / 10_000.0


@dataclass
class RunResult:
    provenance: dict[str, Any]
    periods: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        rets = [p["net_return"] for p in self.periods]
        if not rets:
            return {"periods": 0, "verdict": "no periods — nothing to report"}
        mean = statistics.fmean(rets)
        med = statistics.median(rets)
        hit = sum(1 for r in rets if r > 0) / len(rets)
        srt = sorted(rets, reverse=True)
        top3 = sum(srt[:3]) / sum(rets) if sum(rets) else float("nan")
        return {
            "periods": len(rets),
            "mean_return": mean,
            "median_return": med,
            "hit_rate": hit,
            "top3_share_of_total": top3,
            "total_cost": sum(p["cost"] for p in self.periods),
            # The judgement V289 §7 had to make by hand, made automatically here.
            "outlier_driven": bool(sum(rets) and top3 > 0.5),
            "median_negative": med < 0,
        }


def run(
    dates: list[str],
    hold_periods: int = 1,
    panel_spec: PanelSpec | None = None,
    port_spec: PortfolioSpec | None = None,
    costs: CostModel | None = None,
    scale_fn: Any = None,
) -> RunResult:
    """Walk the dates, rebalance, and charge costs.

    `scale_fn(date, day) -> {code: multiplier}` is the overlay seam. It can only trim
    (see portfolio.build_target), so a future news veto (#548) or liquidity haircut
    (#551) attaches without any risk of diluting the entry signal.
    """
    pspec = panel_spec or PanelSpec(label="asx-default")
    ospec = port_spec or PortfolioSpec()
    cm = costs or CostModel()

    built = build_panel(dates, pspec)
    panel = built["panel"]
    ordered = sorted(panel)
    res = RunResult(
        provenance={
            **built["provenance"],
            "n_dates": built["n_dates"],
            "n_codes": built["n_codes"],
            "hold_periods": hold_periods,
            "cost_bps_round_trip": (cm.bps_per_side + cm.slippage_bps) * 2,
        }
    )

    prev: dict[str, float] = {}
    for i in range(0, len(ordered) - hold_periods, hold_periods):
        d, d_next = ordered[i], ordered[i + hold_periods]
        day, nxt = panel[d], panel[d_next]

        scale = scale_fn(d, day) if scale_fn else None
        tgt = build_target(d, day, ospec, scale)
        if not tgt.weights:
            prev = {}
            res.periods.append(
                {
                    "date": d,
                    "gross_return": 0.0,
                    "cost": 0.0,
                    "net_return": 0.0,
                    "n": 0,
                    "skipped": tgt.diagnostics.get("reason"),
                }
            )
            continue

        gross = 0.0
        priced = 0
        for c, w in tgt.weights.items():
            p0, p1 = day[c]["price"], nxt.get(c, {}).get("price")
            if p1 is None or p0 <= 0:
                continue  # delisted or unpriced: contributes nothing, counted below
            gross += w * (p1 / p0 - 1.0)
            priced += 1

        cost = cm.charge(turnover(prev, tgt.weights))
        res.periods.append(
            {
                "date": d,
                "gross_return": gross,
                "cost": cost,
                "net_return": gross - cost,
                "n": len(tgt.weights),
                "priced": priced,
                # A name that vanishes between rebalances is exactly the survivorship
                # hole (#541). Counted rather than silently dropped.
                "unpriced_at_exit": len(tgt.weights) - priced,
            }
        )
        prev = tgt.weights

    return res


def write_run(res: RunResult, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"provenance": res.provenance, "summary": res.summary(), "periods": res.periods},
            indent=1,
            sort_keys=True,
        )
        + "\n"
    )
    return out


def benchmark_relative(
    res: RunResult,
    panel: dict[str, Any],
    benchmark: IndexBenchmark | None = None,
) -> dict[str, Any]:
    """Excess over a real index, with the periods it cannot cover reported, not hidden.

    NOT optional, and separated only so the omission is visible: the raw numbers `run()`
    reports are ABSOLUTE, and 2011-2026 on the ASX was a bull market. A +38% 12-month
    absolute return is mostly beta. The signal's claim is that the least-shorted quintile
    beats the market, and only this function tests that claim.

    Two comparators are reported and never blended:

    - ``excess_vs_index`` — against XJT (total return), the honest number. Computed only
      for periods the index covers; `covered_periods` says how many that was.
    - ``excess_vs_universe`` — against the equal-weight surviving universe. This is the
      old proxy, kept because it is the ONLY comparator available before 2024-09-02, and
      labelled ``biased: True`` because it is survivor-only and drawn from the same names
      the signal ranks. It flatters the strategy; it is a fallback, not a result.

    A period outside index coverage contributes to the universe number and is counted in
    ``uncovered_periods`` — it never silently borrows a zero benchmark.
    """
    from omega.nodes.asx.benchmark import IndexBenchmark

    bm = benchmark if benchmark is not None else IndexBenchmark()
    vs_index: list[float] = []
    vs_univ: list[float] = []
    uncovered = 0

    ordered = sorted(panel)
    idx = {d: i for i, d in enumerate(ordered)}
    h = res.provenance.get("hold_periods", 1)

    for p in res.periods:
        d = p["date"]
        i = idx.get(d)
        if i is None or p.get("n", 0) == 0 or i + h >= len(ordered):
            continue
        d_next = ordered[i + h]
        day, nxt = panel[d], panel[d_next]

        rs = [
            nxt[c]["price"] / day[c]["price"] - 1.0
            for c in day
            if c in nxt and day[c]["price"] > 0
        ]
        if rs:
            vs_univ.append(p["net_return"] - statistics.fmean(rs))

        mkt = bm.total_return(d, d_next)
        if mkt is None:
            uncovered += 1
        else:
            vs_index.append(p["net_return"] - mkt)

    def stats(xs: list[float]) -> dict[str, Any]:
        if not xs:
            return {"periods": 0}
        srt = sorted(xs, reverse=True)
        return {
            "periods": len(xs),
            "mean_excess": statistics.fmean(xs),
            "median_excess": statistics.median(xs),
            "hit_rate": sum(1 for x in xs if x > 0) / len(xs),
            "top3_share": sum(srt[:3]) / sum(xs) if sum(xs) else float("nan"),
        }

    return {
        "benchmark": bm.provenance(),
        "covered_periods": len(vs_index),
        "uncovered_periods": uncovered,
        "excess_vs_index": stats(vs_index),
        "excess_vs_universe": {
            **stats(vs_univ),
            "biased": True,
            "why": "survivor-only, drawn from the ranked universe",
        },
    }
