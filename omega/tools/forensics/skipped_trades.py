"""Find trades present in the baseline run but missing in the target run.

Matching key: (cycle, symbol, side). This is a necessary compromise: V35 and V48
will not have byte-identical cycle sequences, but using cycle+symbol+side captures
the intent ("same decision, same instrument, same direction") well enough for a
forensics diff. Rank mismatches will show as both a skipped-baseline and an
introduced-target trade, which is acceptable signal for hypothesis ranking.
"""

from __future__ import annotations

from dataclasses import dataclass

from omega.tools.forensics.loader import RunArtifacts


@dataclass
class SkippedTrade:
    cycle: int
    symbol: str
    side: str
    baseline_pnl: float
    baseline_conviction: float
    baseline_regime: str


def find_skipped_trades(baseline: RunArtifacts, target: RunArtifacts) -> list[SkippedTrade]:
    """Return baseline trades with no matching (cycle, symbol, side) in target."""
    target_keys = {(t["cycle"], t["symbol"], t["side"]) for t in target.trades}
    skipped: list[SkippedTrade] = []
    for t in baseline.trades:
        key = (t["cycle"], t["symbol"], t["side"])
        if key not in target_keys:
            skipped.append(
                SkippedTrade(
                    cycle=t["cycle"],
                    symbol=t["symbol"],
                    side=t["side"],
                    baseline_pnl=float(t["pnl"]),
                    baseline_conviction=float(t["conviction"]),
                    baseline_regime=t.get("regime", "unknown"),
                )
            )
    return skipped
