"""V229: unit tests for the drawdown-gate on the trend-IC overlay.

The gate lives inline in StrategyNode._compute_weighted_conviction. When
``ic_drawdown_gate_enabled`` is ON it must, independently of the V223 categorical
{crisis,high_vol} label, bypass IC to the equal-weight raw composite whenever the
per-ticker realized drawdown (``signals_dict["_skew_dd_mag"]``, produced upstream
by V227's ``_realized_drawdown_mag``) exceeds ``ic_drawdown_threshold`` — the same
per-ticker discriminator V227 validated for the crisis-skew.

Invariants under test:
  - flag ON + drawdown > threshold  ⇒ equal-weight composite (bit-identical
    return to the V223 bypass), _ic_skip_cycles increments;
  - flag ON + drawdown ≤ threshold  ⇒ the IC-weighted value, no skip;
  - flag OFF (default)              ⇒ byte-identical to the V228 stack (gate
    ignored even when drawdown is large) — the default-OFF non-regression;
  - strict ``>`` boundary (dd == threshold keeps IC, matching V227);
  - the V223 categorical bypass still takes precedence;
  - a missing ``_skew_dd_mag`` key is tolerated (degrades to IC, no crash).
"""

from __future__ import annotations

import math

from omega.nodes.victoria.features import VictoriaFeatures
from omega.nodes.victoria.strategy import StrategyNode


def _make_strategy(features: VictoriaFeatures, signal_ics: dict[str, float]) -> StrategyNode:
    """Build a StrategyNode without its heavy __init__, wiring only the
    attributes _compute_weighted_conviction reads/writes."""
    s = StrategyNode.__new__(StrategyNode)
    s.features = features
    s._signal_ics = dict(signal_ics)
    s._regime_ics = {}
    s._cycle_regime_label = "normal"
    s._last_ic_active = False
    s._ic_on_cycles = 0
    s._ic_off_cycles = 0
    s._ic_skip_cycles = 0
    s._logged_ic_regimes = set()
    s._ic_source = "seed"
    s._signal_value_history = {}
    return s


# Two signals with known ICs → an IC-weighted composite that is DISTINCT from the
# raw composite, so "equal-weight bypass" vs "IC value" is observably different.
_ICS = {"sma_crossover": 0.5, "ricci_curvature_signal": -0.3}


def _signals(dd_mag: float, regime: str = "normal") -> dict:
    return {
        "composite": 0.123,  # the equal-weight bypass value
        "ticker": "BTCUSDT",
        "_regime": regime,
        "_skew_dd_mag": dd_mag,
        "sma_crossover": 0.8,
        "ricci_curvature_signal": 0.4,
    }


def _expected_ic_value() -> float:
    # Mirror the method's fsum reduction for the fixture above (regime ICs empty,
    # so pooled ICs apply; normalization off).
    weighted = [0.8 * 0.5, 0.4 * -0.3]
    ic_terms = [abs(0.5), abs(-0.3)]
    return math.fsum(weighted) / math.fsum(ic_terms)


def test_drawdown_above_threshold_flag_on_returns_equal_weight() -> None:
    feats = VictoriaFeatures(ic_drawdown_gate_enabled=True, ic_drawdown_threshold=0.12)
    s = _make_strategy(feats, _ICS)
    out = s._compute_weighted_conviction(_signals(dd_mag=0.20))
    assert out == 0.123  # bit-identical equal-weight bypass
    assert s._last_ic_active is False
    assert s._ic_skip_cycles == 1


def test_drawdown_below_threshold_flag_on_returns_ic_value() -> None:
    feats = VictoriaFeatures(ic_drawdown_gate_enabled=True, ic_drawdown_threshold=0.12)
    s = _make_strategy(feats, _ICS)
    out = s._compute_weighted_conviction(_signals(dd_mag=0.05))
    assert out == _expected_ic_value()
    assert out != 0.123  # genuinely the IC value, not the equal-weight composite
    assert s._ic_skip_cycles == 0


def test_flag_off_ignores_drawdown_returns_ic_value() -> None:
    # Default-OFF non-regression: even with a large drawdown, the gate is inert
    # and the result is byte-identical to the V228 stack (the IC value).
    feats = VictoriaFeatures(ic_drawdown_gate_enabled=False, ic_drawdown_threshold=0.12)
    s = _make_strategy(feats, _ICS)
    out = s._compute_weighted_conviction(_signals(dd_mag=0.20))
    assert out == _expected_ic_value()
    assert s._ic_skip_cycles == 0


def test_boundary_drawdown_equals_threshold_keeps_ic() -> None:
    # Strict `>` (matches V227's skew convention): dd exactly at threshold keeps IC.
    feats = VictoriaFeatures(ic_drawdown_gate_enabled=True, ic_drawdown_threshold=0.12)
    s = _make_strategy(feats, _ICS)
    out = s._compute_weighted_conviction(_signals(dd_mag=0.12))
    assert out == _expected_ic_value()
    assert s._ic_skip_cycles == 0


def test_v223_categorical_bypass_takes_precedence() -> None:
    # Flag ON, low drawdown (IC-dd gate would NOT fire), but the V223 categorical
    # gate is ON and the label is crisis ⇒ still equal-weight via V223. Proves the
    # two bypasses compose and the new branch doesn't interfere with V223.
    feats = VictoriaFeatures(
        ic_drawdown_gate_enabled=True,
        ic_drawdown_threshold=0.12,
        regime_conditional_ic_weighting=True,
    )
    s = _make_strategy(feats, _ICS)
    out = s._compute_weighted_conviction(_signals(dd_mag=0.05, regime="crisis"))
    assert out == 0.123  # equal-weight via V223 (not the IC-dd branch)
    assert s._last_ic_active is False
    # V223 path does NOT touch the V229 counter (it short-circuits first).
    assert s._ic_skip_cycles == 0


def test_missing_skew_dd_mag_key_tolerated() -> None:
    # crisis_skew off / old snapshot: _skew_dd_mag absent ⇒ .get(...,0.0) ⇒ 0.0
    # ≤ threshold ⇒ IC value, no crash.
    feats = VictoriaFeatures(ic_drawdown_gate_enabled=True, ic_drawdown_threshold=0.12)
    s = _make_strategy(feats, _ICS)
    sig = _signals(dd_mag=0.20)
    del sig["_skew_dd_mag"]
    out = s._compute_weighted_conviction(sig)
    assert out == _expected_ic_value()
    assert s._ic_skip_cycles == 0
