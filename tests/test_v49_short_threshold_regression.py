"""V49 regression guard: the normal-regime short conviction threshold must be 0.05.

Motivation: data/v35-v48-forensics.json shows V48's short trades lost $137.55
relative to V35 extended, concentrated 144% in normal regime and 73% in ADAUSDT.
The surgical V49 fix lowers short_conviction_threshold from 0.10 to 0.05 in the
normal-regime branch of StrategyNode._apply_regime_adaptive_thresholds().

If this test fails, someone reverted the V49 fix. Read
docs/training/v35-v48-forensics.md before changing it back.
"""
from __future__ import annotations

import re
from pathlib import Path

STRATEGY_FILE = (
    Path(__file__).parent.parent / "omega" / "nodes" / "victoria" / "strategy.py"
)


def test_normal_regime_short_threshold_is_005():
    """The normal-regime else branch must set short_conviction_threshold to 0.05."""
    text = STRATEGY_FILE.read_text()
    # Find the normal-regime else branch (follows the bull-regime elif)
    # and assert the short_conviction_threshold assignment is 0.05.
    # This is a structural check, not a string search, so it survives reformatting.
    match = re.search(
        r"else:\s*\n"
        r"(?:.*\n){0,20}?"
        r"\s*self\._long_conviction_threshold\s*=\s*0\.10\s*\n"
        r"\s*self\._short_conviction_threshold\s*=\s*(?P<val>[0-9.]+)",
        text,
    )
    assert match is not None, (
        "Could not find normal-regime else branch setting long and short thresholds. "
        "strategy.py may have been refactored; update this regression test to match."
    )
    val = float(match.group("val"))
    assert val == 0.05, (
        f"Normal-regime short_conviction_threshold is {val}, expected 0.05. "
        "This reverts the V49 fix. Read docs/training/v35-v48-forensics.md — "
        "ADAUSDT alone accounts for 73% of the V35-V48 PnL gap, and the normal-regime "
        "0.10 threshold was the proximate cause."
    )


def test_long_regime_threshold_preserved_at_010():
    """The V49 fix must NOT touch the normal-regime long threshold."""
    text = STRATEGY_FILE.read_text()
    match = re.search(
        r"else:\s*\n"
        r"(?:.*\n){0,20}?"
        r"\s*self\._long_conviction_threshold\s*=\s*(?P<val>[0-9.]+)",
        text,
    )
    assert match is not None, "Could not find normal-regime long threshold."
    val = float(match.group("val"))
    assert val == 0.10, (
        f"Normal-regime long_conviction_threshold is {val}, expected 0.10. "
        "The V49 fix only lowers the short threshold; longs must remain untouched."
    )
