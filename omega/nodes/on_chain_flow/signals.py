"""V261 — per-asset composite on-chain flow z-score (LOCKED per V261.md).

Four signed components, each z-scored over a trailing 30-obs window on the clean
gapless on-chain daily grid; the composite is the MEAN of the four signed z-scores
(kept on z-score scale). Degenerate windows (std==0 or <30 obs) contribute no signal
that day, and any missing component drops the composite for that day — a semantic
fence, never an epsilon (V221 lesson). Deterministic: ``math.fsum`` throughout.
"""

from __future__ import annotations

import math
from typing import cast

WINDOW = 30

# component key -> declared sign (V261.md param table)
COMPONENT_SIGNS = {
    "netflow": -1.0,          # FlowIn-FlowOut level; inflow = distribution = bearish
    "addr_velocity": +1.0,    # Δ active addresses; rising usage = bullish
    "whale_velocity": -1.0,   # Δ SplyExNtv (PROXY); rising exch supply = distribution
    "tx_velocity": +1.0,      # Δ transfers; rising throughput = bullish
}
COMPONENT_KEYS = ("netflow", "addr_velocity", "whale_velocity", "tx_velocity")


def _sample_std(window: list[float], mean: float) -> float:
    """Sample std (ddof=1) via fsum; window length assumed == WINDOW (>=2)."""
    ss = math.fsum((x - mean) ** 2 for x in window)
    return math.sqrt(ss / (len(window) - 1))


def _rolling_z(series: list[float | None], idx: int) -> float | None:
    """z of ``series[idx]`` vs its trailing WINDOW obs; None if degenerate/incomplete."""
    if idx < WINDOW:
        return None
    window = series[idx - WINDOW + 1 : idx + 1]  # inclusive of idx, WINDOW obs
    if any(v is None for v in window):
        return None
    w = [float(v) for v in cast("list[float]", window)]
    mean = math.fsum(w) / len(w)
    std = _sample_std(w, mean)
    if std == 0.0:
        return None
    return (w[-1] - mean) / std


def build_components(onchain: dict[str, dict[str, float]]) -> tuple[list[str], dict[str, list[float | None]]]:
    """Build the four raw component series aligned to the sorted on-chain date grid.

    ``netflow`` is a level (defined every day); the three velocities are first
    differences (index 0 is None). Returns (dates, {component_key -> [values]}).
    """
    dates = sorted(onchain["active_addresses"].keys())
    infl = onchain["exchange_inflow_native"]
    outfl = onchain["exchange_outflow_native"]
    addr = onchain["active_addresses"]
    whale = onchain["exchange_supply_native"]
    tx = onchain["transfer_count"]

    netflow: list[float | None] = [infl[d] - outfl[d] for d in dates]
    addr_v: list[float | None] = [None]
    whale_v: list[float | None] = [None]
    tx_v: list[float | None] = [None]
    for i in range(1, len(dates)):
        d, p = dates[i], dates[i - 1]
        addr_v.append(addr[d] - addr[p])
        whale_v.append(whale[d] - whale[p])
        tx_v.append(tx[d] - tx[p])
    return dates, {
        "netflow": netflow,
        "addr_velocity": addr_v,
        "whale_velocity": whale_v,
        "tx_velocity": tx_v,
    }


def composite_z_series(
    onchain: dict[str, dict[str, float]],
    include: tuple[str, ...] = COMPONENT_KEYS,
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Per-date composite z (mean of signed component z's) over ``include`` components.

    Returns (composite {date -> z}, per_component {component_key -> {date -> signed z}}).
    A date is only in ``composite`` when EVERY included component has a valid z that day.
    ``include`` lets the scorer run single-component and leave-one-out ablations
    against the identical windowing/fence (F4 proxy honesty check).
    """
    dates, comps = build_components(onchain)
    per_comp: dict[str, dict[str, float]] = {k: {} for k in include}
    composite: dict[str, float] = {}
    for i, date in enumerate(dates):
        signed: list[float] = []
        ok = True
        for k in include:
            z = _rolling_z(comps[k], i)
            if z is None:
                ok = False
                break
            sz = COMPONENT_SIGNS[k] * z
            per_comp[k][date] = sz
            signed.append(sz)
        if ok and signed:
            composite[date] = math.fsum(signed) / len(signed)
        else:
            # drop any partial per-component writes for this date (all-or-nothing)
            for k in include:
                per_comp[k].pop(date, None)
    return composite, per_comp
