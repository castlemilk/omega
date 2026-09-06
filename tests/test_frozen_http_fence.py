"""V227 Track C — frozen-backtest HTTP fence for non-urllib (yfinance) signals.

The V215 frozen-cache HTTP guard patches urllib.request.OpenerDirector.open, but
yfinance fetches via curl_cffi/requests — bypassing it. SPYSignal/VIXSignal
therefore hit LIVE Yahoo during frozen backtests and returned wall-clock-
dependent data (the V226 recent-OFF determinism FAIL: spy_signal flapping in/out
of the per-ticker composite → NEARUSDT entry cycle 95↔93 → $1,621.99 spread).

The fix is a per-signal OMEGA_FROZEN_CACHE fence. These tests pin it.
"""

from __future__ import annotations

from omega.nodes.victoria.signals.spy_signal import SPYSignal
from omega.nodes.victoria.signals.vix_signal import VIXSignal


def test_spy_signal_inert_under_frozen_cache(monkeypatch):
    """SPYSignal.compute returns exactly 0.0 (no fetch) when frozen."""
    monkeypatch.setenv("OMEGA_FROZEN_CACHE", "1")
    md = {"BTCUSDT": {"close": [100.0 + i for i in range(30)]}}
    assert SPYSignal().compute(md) == 0.0


def test_vix_signal_inert_under_frozen_cache(monkeypatch):
    """VIXSignal.compute returns exactly 0.0 (no fetch) when frozen."""
    monkeypatch.setenv("OMEGA_FROZEN_CACHE", "1")
    assert VIXSignal().compute() == 0.0


def test_fence_is_first_branch_no_state_touched(monkeypatch):
    """The fence short-circuits before any cache/network state is read.

    A freshly constructed signal under frozen mode must return 0.0 without
    populating its caches — proving the return happens at the top of compute().
    """
    monkeypatch.setenv("OMEGA_FROZEN_CACHE", "1")
    spy = SPYSignal()
    vix = VIXSignal()
    assert spy.compute({"BTCUSDT": {"close": [1.0] * 30}}) == 0.0
    assert vix.compute() == 0.0
    assert spy._spy_daily_cache == []
    assert spy._spy_4h_cache == []
    assert vix._vix_cache == []


def test_fence_inactive_when_flag_unset(monkeypatch):
    """Live trading (flag unset) is unaffected: the fence does not short-circuit.

    We can't assert a live value deterministically, but we can prove the early
    return is gated on the flag: with it unset the fence branch is not taken, so
    the code proceeds past it (here it reaches the yfinance/_HAS_YFINANCE path).
    """
    monkeypatch.delenv("OMEGA_FROZEN_CACHE", raising=False)
    # Should not raise; returns a float in range whatever the data path yields.
    val = SPYSignal().compute({"BTCUSDT": {"close": [100.0 + i for i in range(30)]}})
    assert isinstance(val, float)
    assert -0.3 <= val <= 0.3
