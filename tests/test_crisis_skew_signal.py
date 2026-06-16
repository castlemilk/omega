"""V225: unit tests for the additive crisis-skew signal.

Covers: determinism (byte-identical across calls + subprocess), sign convention
(one-sided [-1, 0], never bullish), sane values across regimes, and graceful
missing-data (always 0.0, never NaN).
"""

from __future__ import annotations

import math
import subprocess
import sys

import pytest

from omega.nodes.victoria.signals.crisis_skew import CrisisSkewSignal


def _crash_window(n: int = 30, start: float = 100.0, drop: float = 0.03) -> list[float]:
    """Monotone decline with accelerating losses (a crash)."""
    out = [start]
    for i in range(1, n):
        out.append(out[-1] * (1.0 - drop * (1.0 + i / n)))
    return out


def _rally_window(n: int = 30, start: float = 100.0, gain: float = 0.02) -> list[float]:
    out = [start]
    for _ in range(1, n):
        out.append(out[-1] * (1.0 + gain))
    return out


def test_determinism_same_call() -> None:
    sig = CrisisSkewSignal()
    w = _crash_window()
    a = sig.compute(w)
    b = sig.compute(list(w))  # fresh list, same values
    assert a == b  # bit-identical (fsum, fixed order, stateless)


def test_determinism_subprocess() -> None:
    """Same window in a fresh interpreter → identical bytes (no hidden global/order)."""
    w = _crash_window()
    code = (
        "from omega.nodes.victoria.signals.crisis_skew import CrisisSkewSignal as S;"
        f"print(repr(S().compute({w!r})))"
    )
    r1 = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    r2 = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert r1.stdout == r2.stdout
    assert r1.stdout.strip() == repr(CrisisSkewSignal().compute(w))


def test_sign_crash_is_negative() -> None:
    out = CrisisSkewSignal().compute(_crash_window())
    assert out <= -0.5, f"a crash window should be strongly risk-off, got {out}"


def test_sign_rally_is_zero_not_positive() -> None:
    out = CrisisSkewSignal().compute(_rally_window())
    # One-sided: a pure rally must never produce a bullish (positive) value.
    assert out == 0.0, f"a rally must produce 0.0 (one-sided), got {out}"


def test_one_sided_invariant_random() -> None:
    """For arbitrary windows the output is always within [-1, 0] (never positive)."""
    import random

    rng = random.Random(42)  # fixed seed — deterministic test
    sig = CrisisSkewSignal()
    for _ in range(200):
        n = rng.randint(2, 40)
        w = [100.0]
        for _ in range(1, n):
            w.append(max(0.01, w[-1] * (1.0 + rng.uniform(-0.1, 0.1))))
        out = sig.compute(w)
        assert -1.0 <= out <= 0.0
        assert math.isfinite(out)


def test_flat_window_is_zero() -> None:
    assert CrisisSkewSignal().compute([100.0] * 30) == 0.0


@pytest.mark.parametrize(
    "bad",
    [None, [], [100.0], [float("nan"), 100.0], [100.0, float("inf")], [0.0, 0.0]],
)
def test_missing_data_returns_zero_never_nan(bad: list[float] | None) -> None:
    out = CrisisSkewSignal().compute(bad)
    assert out == 0.0
    assert math.isfinite(out)


def test_value_in_range_for_crash() -> None:
    out = CrisisSkewSignal().compute(_crash_window())
    assert -1.0 <= out <= 0.0
    assert math.isfinite(out)
