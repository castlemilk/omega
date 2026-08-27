"""V280 G1: the signal node runs at v1.0 unless something upgrades it.

SignalGenerationNode ships six technical signals default OFF, switched on only by
improve() at iteration>=1/>=2. Nothing in the training path calls improve(), so every
walk-forward cell in the campaign — the 32 behind the standing baseline included — ran
with RSI, MACD, Bollinger Bands, Z-score, BTC-beta and vol-regime disabled.

These tests pin the default (so the finding cannot silently stop being true) and pin the
arm (so the measurement means what V280 says it means).
"""

from __future__ import annotations

import os
from unittest import mock

from omega.nodes.victoria.signal_generation import SignalGenerationNode

_TOGGLES = ("_use_rsi", "_use_macd", "_use_bb", "_use_zscore",
            "_use_btc_beta", "_use_vol_regime")


def test_node_defaults_to_v1_0_with_technicals_off() -> None:
    """The finding itself, pinned. If this ever fails, V280's premise changed."""
    env = {k: v for k, v in os.environ.items() if k != "OMEGA_SIGNAL_NODE_V12"}
    with mock.patch.dict(os.environ, env, clear=True):
        node = SignalGenerationNode()
        off = [t for t in _TOGGLES if getattr(node, t) is False]
        assert len(off) == len(_TOGGLES), (
            f"a technical signal is now ON by default: "
            f"{[t for t in _TOGGLES if getattr(node, t)]}. V280's premise — that the "
            "campaign measured with these disabled — no longer holds; re-read V280.md."
        )


def test_arm_upgrades_to_v1_2_via_the_real_improve_path() -> None:
    """The arm must reach v1.2 through improve(), not by setting booleans behind its back."""
    with mock.patch.dict(os.environ, {"OMEGA_SIGNAL_NODE_V12": "1"}):
        node = SignalGenerationNode()
        assert node._version == "1.2", f"arm did not reach v1.2: {node._version!r}"
        still_off = [t for t in _TOGGLES if not getattr(node, t)]
        assert still_off == [], f"arm left technicals off: {still_off}"


def test_arm_is_inert_when_unset_or_not_one() -> None:
    """Arm-OFF must be byte-identical to pre-V280, or G3's comparison is invalid."""
    for val in ("0", "", "true", "yes"):
        with mock.patch.dict(os.environ, {"OMEGA_SIGNAL_NODE_V12": val}):
            node = SignalGenerationNode()
            assert node._version != "1.2", (
                f"OMEGA_SIGNAL_NODE_V12={val!r} upgraded the node; only '1' may."
            )
