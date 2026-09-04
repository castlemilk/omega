"""Normal-regime conviction thresholds are balanced, and both legs are equal.

History, because the numbers here have moved four times and the guard did not:

  V49  lowered the normal-regime short threshold to 0.05 to admit more shorts;
       forensics blamed it for a normal-regime collapse (-$10.98 vs V48 +$16.49).
  V50  reverted to 0.10/0.10 — which is what this file used to assert.
  V86  raised long 0.07 -> 0.10; caused max_zero_streak=150, 8 trades in 200 cycles.
  V87  reverted long to 0.07 for post-crash recovery conviction levels.
  V94  lowered short 0.07 -> 0.05; produced only 3 shorts in 200 cycles.
  V95  reverted short to 0.07, V88's calibration.

So the settled contract is 0.07/0.07, and 0.10 has now been tried and reverted
twice. This file asserted the V50 value and had been failing ever since V87 —
unnoticed, because it sat in a suite nobody could run (see tests/conftest.py and
the `slow` markers added alongside).

It also used to assert by REGEX OVER strategy.py's source, which is why its own
failure message said "strategy.py may have been refactored". A test that greps
source goes stale invisibly and cannot tell a refactor from a regression. These
call the method and assert what it sets, so a rename cannot silence them and a
behaviour change cannot hide from them.
"""

from __future__ import annotations

import pytest

from omega.nodes.victoria.strategy import StrategyNode

NORMAL_LONG = 0.07
NORMAL_SHORT = 0.07


def _normal_node() -> StrategyNode:
    node = StrategyNode()
    # Comfortably inside NORMAL: below V91's 0.65 bear trigger and the 0.55 bull one.
    node._apply_regime_adaptive_thresholds(
        {"_regime_w_bear_prob": 0.20, "_regime_w_bull_prob": 0.20}
    )
    return node


def test_normal_regime_short_threshold() -> None:
    node = _normal_node()
    assert node._short_conviction_threshold == NORMAL_SHORT, (
        f"Normal-regime short threshold is {node._short_conviction_threshold}, "
        f"expected {NORMAL_SHORT} (V95 restored V88's calibration; V94's 0.05 "
        "produced only 3 shorts in 200 cycles)."
    )


def test_normal_regime_long_threshold() -> None:
    node = _normal_node()
    assert node._long_conviction_threshold == NORMAL_LONG, (
        f"Normal-regime long threshold is {node._long_conviction_threshold}, "
        f"expected {NORMAL_LONG} (V87; V86's 0.10 caused max_zero_streak=150)."
    )


def test_normal_regime_legs_are_balanced() -> None:
    """The property V50 was actually defending, and the one that survived.

    Every specific value here has moved, but 'neither direction is favoured in a
    regime with no directional view' has held through all of it. Asserting the
    property as well as the numbers means a future retune breaks one test rather
    than silently satisfying none.
    """
    node = _normal_node()
    assert node._long_conviction_threshold == node._short_conviction_threshold, (
        "Normal-regime legs are asymmetric — a directional tilt in a regime that "
        "has no directional view. V49 did exactly this and cost -$10.98."
    )


@pytest.mark.parametrize(
    ("bear", "bull", "long_t", "short_t"),
    [
        (0.20, 0.20, 0.07, 0.07),  # NORMAL
        (0.65, 0.10, 0.50, 0.04),  # CRISIS/BEAR — V91 trigger, V84 levels
        (0.10, 0.60, 0.05, 0.20),  # BULL
    ],
)
def test_regime_threshold_contract(bear: float, bull: float, long_t: float, short_t: float) -> None:
    """The whole table in one place, so a retune has a single obvious thing to update.

    CLAUDE.md documented this table wrongly for ~90 versions because it was
    maintained by hand in four places at once.
    """
    node = StrategyNode()
    node._apply_regime_adaptive_thresholds(
        {"_regime_w_bear_prob": bear, "_regime_w_bull_prob": bull}
    )
    assert (node._long_conviction_threshold, node._short_conviction_threshold) == (long_t, short_t)
