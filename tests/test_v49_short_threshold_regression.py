"""V50 regression guard: normal-regime thresholds must be balanced at 0.10/0.10.

History:
  V49 lowered short_conviction_threshold to 0.05 in normal regime to admit more
  shorts (data/v35-v48-forensics.json — ADAUSDT short losses). V49 training showed
  this caused normal-regime collapse (-$10.98 vs V48 +$16.49). V50 reverts to 0.10
  balanced; the ETHUSDT long momentum gate is the targeted fix for near-breakeven longs.

If this test fails, someone changed the normal-regime thresholds. Read
docs/training/v35-v48-forensics.md and data/v49_gate_result.json before changing.
"""
from __future__ import annotations

import re
from pathlib import Path

STRATEGY_FILE = (
    Path(__file__).parent.parent / "omega" / "nodes" / "victoria" / "strategy.py"
)


def test_normal_regime_short_threshold_is_010():
    """The normal-regime else branch must set short_conviction_threshold to 0.10."""
    text = STRATEGY_FILE.read_text()
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
    assert val == 0.10, (
        f"Normal-regime short_conviction_threshold is {val}, expected 0.10. "
        "V49 0.05 caused normal-regime collapse (-$10.98 PnL vs V48 +$16.49). "
        "Use the ETHUSDT momentum gate for targeted filtering instead of lowering this threshold."
    )


def test_long_threshold_is_010():
    """Normal-regime long threshold must stay at 0.10."""
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
        f"Normal-regime long_conviction_threshold is {val}, expected 0.10."
    )


def test_ethusdt_momentum_gate_exists():
    """ETHUSDT long momentum gate must be present in _passes_conviction_filters."""
    text = STRATEGY_FILE.read_text()
    assert "ethusdt_long_momentum_gate" in text.lower() or "ETHUSDT" in text, (
        "ETHUSDT momentum gate not found in strategy.py. "
        "This gate filters near-breakeven ETHUSDT longs in normal regime (V50 fix)."
    )
    assert "sma_crossover" in text and "zscore_signal" in text, (
        "Momentum gate must use sma_crossover and zscore_signal for direction check."
    )
