"""V232: unit tests for the additive RV-term-structure inversion brake.

Covers: determinism (byte-identical across calls + subprocess), sign convention
(one-sided [-1, 0], never bullish), firing on inversion / quiet below threshold,
graceful missing-data (always 0.0, never NaN), and the degenerate-variance fence.
"""

from __future__ import annotations

import math
import subprocess
import sys

import pytest

from omega.nodes.victoria.signals.rv_term_structure import RVTermStructureSignal


def _calm_window(n: int = 30, start: float = 100.0, step: float = 0.005) -> list[float]:
    """Steady, low, constant-magnitude oscillation → RV_short ≈ RV_long → R ≈ 1."""
    out = [start]
    for i in range(1, n):
        out.append(out[-1] * (1.0 + (step if i % 2 == 0 else -step)))
    return out


def _inverted_window(n: int = 30) -> list[float]:
    """Long calm history, then a sharp near-term vol burst in the last 3 bars.

    RV_3d (the burst) ≫ RV_14d (mostly calm) → ratio ≫ threshold → brake fires.
    """
    out = _calm_window(n - 3)
    burst = [0.08, -0.07, 0.09]  # explosive last 3 daily moves
    for g in burst:
        out.append(out[-1] * (1.0 + g))
    return out


def test_determinism_same_call() -> None:
    sig = RVTermStructureSignal()
    w = _inverted_window()
    a = sig.compute(w)
    b = sig.compute(list(w))  # fresh list, same values
    assert a == b  # bit-identical (fsum, fixed order, stateless)


def test_determinism_subprocess() -> None:
    """Same window in a fresh interpreter → identical bytes (no hidden global/order)."""
    w = _inverted_window()
    code = (
        "from omega.nodes.victoria.signals.rv_term_structure import RVTermStructureSignal as S;"
        f"print(repr(S().compute({w!r})))"
    )
    r1 = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    r2 = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert r1.stdout == r2.stdout
    assert r1.stdout.strip() == repr(RVTermStructureSignal().compute(w))


def test_brake_fires_on_inversion() -> None:
    """A near-term vol burst (R > threshold) must produce a negative brake."""
    out = RVTermStructureSignal().compute(_inverted_window())
    assert out < 0.0, f"an inverted RV term-structure should brake (negative), got {out}"
    assert -1.0 <= out <= 0.0


def test_brake_quiet_below_threshold() -> None:
    """Steady vol (R ≈ 1 < threshold) must produce exactly 0.0 (no brake)."""
    out = RVTermStructureSignal().compute(_calm_window())
    assert out == 0.0, f"steady vol (no inversion) must produce 0.0, got {out}"


def test_threshold_monotonicity() -> None:
    """Lowering X (more permissive) must never reduce the brake magnitude."""
    w = _inverted_window()
    lax = RVTermStructureSignal(inversion_threshold=1.2).compute(w)
    strict = RVTermStructureSignal(inversion_threshold=2.5).compute(w)
    assert lax <= strict <= 0.0  # more permissive ⇒ at least as negative


def test_one_sided_invariant_random() -> None:
    """For arbitrary windows the output is always within [-1, 0] (never positive)."""
    import random

    rng = random.Random(42)  # fixed seed — deterministic test
    sig = RVTermStructureSignal()
    for _ in range(200):
        n = rng.randint(2, 40)
        w = [100.0]
        for _ in range(1, n):
            w.append(max(0.01, w[-1] * (1.0 + rng.uniform(-0.12, 0.12))))
        out = sig.compute(w)
        assert -1.0 <= out <= 0.0
        assert math.isfinite(out)


def test_flat_window_is_zero() -> None:
    """Constant series (degenerate variance) → 0.0 (the V221 fence)."""
    assert RVTermStructureSignal().compute([100.0] * 30) == 0.0


def test_short_window_returns_zero() -> None:
    """Fewer than long_window + 1 closes → 0.0 (not NaN, not a partial estimate)."""
    sig = RVTermStructureSignal(short_window=3, long_window=14)
    assert sig.compute([100.0 + i for i in range(10)]) == 0.0  # only 10 closes < 15


@pytest.mark.parametrize(
    "bad",
    [None, [], [100.0], [float("nan")] + [100.0] * 20, [100.0] * 20 + [float("inf")], [0.0] * 20],
)
def test_missing_data_returns_zero_never_nan(bad: list[float] | None) -> None:
    out = RVTermStructureSignal().compute(bad)
    assert out == 0.0
    assert math.isfinite(out)


def test_value_in_range_for_inversion() -> None:
    out = RVTermStructureSignal().compute(_inverted_window())
    assert -1.0 <= out <= 0.0
    assert math.isfinite(out)
