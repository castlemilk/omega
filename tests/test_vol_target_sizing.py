"""V284 G1: per-ticker vol-target sizing is trim-only and correctly conditioned.

V283 Phase 0 found the strategy's only volatility-driven decision never executes. V284
is the mechanism that gives a volatility estimate somewhere to act. These tests pin the
two properties that make it safe: it never adds leverage, and it is inert when the flag
is off.
"""

from __future__ import annotations

import math

from omega.nodes.victoria.features import VictoriaFeatures
from omega.nodes.victoria.strategy import StrategyNode


def _node(**kw) -> StrategyNode:
    n = StrategyNode.__new__(StrategyNode)
    n.features = VictoriaFeatures(**kw)
    return n


def _series(vols: list[float], per_seg: int = 25, start: float = 100.0) -> list[float]:
    """Build a price path whose realized vol steps through `vols`."""
    p = [start]
    for v in vols:
        for i in range(per_seg):
            p.append(p[-1] * (1.0 + (v if i % 2 == 0 else -v)))
    return p


def test_multiplier_is_never_above_one() -> None:
    """Trim-only by construction — this must de-risk, never add leverage."""
    n = _node(vol_target_sizing_enabled=True)
    # calm now, wild before => ref/cur > 1 => must clamp to 1.0, not up-size
    md = {"ETHUSDT": {"close": _series([0.05] * 3 + [0.001])}}
    m = n._vol_target_multipliers(md, ["ETHUSDT"])
    assert m, "no multiplier produced"
    assert m["ETHUSDT"] <= 1.0, f"up-sized to {m['ETHUSDT']} — V284 is trim-only"


def test_high_current_vol_trims() -> None:
    """The direction that makes the mechanism do anything at all."""
    n = _node(vol_target_sizing_enabled=True, vol_target_floor=0.1)
    md = {"ETHUSDT": {"close": _series([0.002] * 3 + [0.05])}}   # calm history, wild now
    m = n._vol_target_multipliers(md, ["ETHUSDT"])
    assert m["ETHUSDT"] < 1.0, "elevated current vol did not trim"
    assert m["ETHUSDT"] >= 0.1, "trimmed below the configured floor"


def test_floor_is_respected() -> None:
    n = _node(vol_target_sizing_enabled=True, vol_target_floor=0.75)
    md = {"ETHUSDT": {"close": _series([0.001] * 3 + [0.20])}}
    m = n._vol_target_multipliers(md, ["ETHUSDT"])
    assert m["ETHUSDT"] >= 0.75


def test_floor_of_one_is_a_noop() -> None:
    """An operator can neutralise the mechanism without touching code."""
    n = _node(vol_target_sizing_enabled=True, vol_target_floor=1.0)
    md = {"ETHUSDT": {"close": _series([0.001] * 3 + [0.20])}}
    m = n._vol_target_multipliers(md, ["ETHUSDT"])
    assert m["ETHUSDT"] == 1.0


def test_degenerate_inputs_return_no_multiplier() -> None:
    """Return {} rather than sizing on a degenerate estimate.

    A silent 1.0 here would be indistinguishable from "measured, no trim" — the
    ambiguity that made V279/V283's inertness so expensive to diagnose.
    """
    n = _node(vol_target_sizing_enabled=True)
    assert n._vol_target_multipliers({"ETHUSDT": {"close": [1.0, 2.0]}}, ["ETHUSDT"]) == {}
    assert n._vol_target_multipliers({"ETHUSDT": None}, ["ETHUSDT"]) == {}
    assert n._vol_target_multipliers({}, ["ETHUSDT"]) == {}
    flat = [100.0] * 80          # zero variance => cur vol 0 => must not divide
    assert n._vol_target_multipliers({"ETHUSDT": {"close": flat}}, ["ETHUSDT"]) == {}


def test_flag_defaults_off() -> None:
    """V284 ships OFF; arm-OFF must be byte-identical to pre-V284."""
    assert VictoriaFeatures().vol_target_sizing_enabled is False


def test_multiplier_is_finite_and_positive() -> None:
    n = _node(vol_target_sizing_enabled=True)
    md = {"ETHUSDT": {"close": _series([0.01, 0.02, 0.03, 0.015])}}
    for v in n._vol_target_multipliers(md, ["ETHUSDT"]).values():
        assert math.isfinite(v) and v > 0.0
