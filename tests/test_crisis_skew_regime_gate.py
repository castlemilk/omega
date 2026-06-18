"""V226: unit tests for the regime gate on the additive crisis-skew term.

The gate lives in signal_generation._regime_gated_skew (a pure branch over the
V225 value). It must:
  - return 0.0 outside {crisis, high_vol} when the gate flag is ON,
  - pass the full V225 value through in {crisis, high_vol} when the gate is ON,
  - pass the full V225 value through in EVERY regime when the gate is OFF
    (V225's always-on path stays reachable for reproducibility),
  - introduce no new float-accumulation (the returned value is bit-identical to
    the input it lets through — no arithmetic).
"""

from __future__ import annotations

import math

import pytest

from omega.nodes.victoria.signal_generation import (
    _SKEW_W,
    _SKEW_W_GATED,
    _regime_gated_skew,
)
from omega.nodes.victoria.signals.crisis_skew import CrisisSkewSignal

# A representative non-zero V225 value (a crash window → strongly risk-off).
_CRASH = [100.0]
for _i in range(1, 30):
    _CRASH.append(_CRASH[-1] * (1.0 - 0.03 * (1.0 + _i / 30)))
_RAW = CrisisSkewSignal().compute(_CRASH)


def test_raw_value_is_nonzero_negative() -> None:
    # Guard the fixture: a crash must produce a real risk-off term so the
    # pass-through assertions below are meaningful (not 0==0).
    assert _RAW < 0.0


@pytest.mark.parametrize("regime", ["normal", "bull", "bear", "sideways", "default", "", "unknown"])
def test_gate_on_outside_crisis_returns_zero(regime: str) -> None:
    assert _regime_gated_skew(_RAW, regime, gate_enabled=True) == 0.0


@pytest.mark.parametrize("regime", ["crisis", "high_vol", "CRISIS", "High_Vol"])
def test_gate_on_inside_crisis_passes_full_value(regime: str) -> None:
    out = _regime_gated_skew(_RAW, regime, gate_enabled=True)
    assert out == _RAW  # bit-identical pass-through (no arithmetic)


@pytest.mark.parametrize("regime", ["normal", "crisis", "high_vol", "bull", "", "unknown"])
def test_gate_off_passes_full_value_every_regime(regime: str) -> None:
    # Gate OFF == V225 always-on behaviour, regardless of regime.
    assert _regime_gated_skew(_RAW, regime, gate_enabled=False) == _RAW


def test_gate_on_zero_value_stays_zero() -> None:
    # A benign-tape 0.0 value is unaffected (both branches return 0.0).
    assert _regime_gated_skew(0.0, "crisis", gate_enabled=True) == 0.0
    assert _regime_gated_skew(0.0, "normal", gate_enabled=True) == 0.0


def test_none_regime_label_is_safe() -> None:
    # victoria_node always passes a str, but the helper must tolerate None/empty.
    assert _regime_gated_skew(_RAW, None, gate_enabled=True) == 0.0  # type: ignore[arg-type]
    assert _regime_gated_skew(_RAW, None, gate_enabled=False) == _RAW  # type: ignore[arg-type]


def test_gated_weight_is_lower_than_v225() -> None:
    # V226 lowers the applied weight; the V225 constant is retained for the
    # gate-OFF reproducibility path.
    assert _SKEW_W_GATED == 0.2
    assert _SKEW_W == 0.5
    assert _SKEW_W_GATED < _SKEW_W


def test_passthrough_introduces_no_arithmetic() -> None:
    # The let-through value must be the SAME object-value (no fsum/multiply in the
    # gate), so the gate cannot open a summation-order channel.
    for v in (_RAW, -0.123456789, -1.0, 0.0):
        assert _regime_gated_skew(v, "crisis", gate_enabled=True) == v
        assert math.isfinite(_regime_gated_skew(v, "crisis", gate_enabled=True))
