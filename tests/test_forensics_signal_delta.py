"""Tests for signal (trade-level proxy) delta."""
from pathlib import Path

import pytest

from omega.tools.forensics.loader import load_run
from omega.tools.forensics.signal_delta import (
    SignalDeltaProxy,
    compute_signal_delta_proxy,
)

FIXTURES = Path(__file__).parent / "fixtures" / "forensics"


def test_signal_delta_proxy_computes_per_symbol_pnl_delta():
    v35 = load_run(FIXTURES / "mini_v35_results.json", FIXTURES / "mini_v35_trades.csv")
    v48 = load_run(FIXTURES / "mini_v48_results.json", FIXTURES / "mini_v48_trades.csv")

    delta = compute_signal_delta_proxy(v35, v48)
    assert isinstance(delta, SignalDeltaProxy)
    # V35 BTC PnL: 50 + 30 + 5 = 85; V48 BTC PnL: 20. Delta = 20 - 85 = -65
    assert delta.per_symbol_delta["BTCUSDT"] == pytest.approx(-65.0)
    # V35 ETH PnL: 30 + -5 = 25; V48 ETH PnL: -5. Delta = -5 - 25 = -30
    assert delta.per_symbol_delta["ETHUSDT"] == pytest.approx(-30.0)


def test_signal_delta_proxy_totals_match_run_totals():
    v35 = load_run(FIXTURES / "mini_v35_results.json", FIXTURES / "mini_v35_trades.csv")
    v48 = load_run(FIXTURES / "mini_v48_results.json", FIXTURES / "mini_v48_trades.csv")
    delta = compute_signal_delta_proxy(v35, v48)
    # Sum of per-symbol deltas should equal (V48 total PnL - V35 total PnL) from trades
    # V35 trades sum: 50+30+30+10-5+5 = 120; V48 trades sum: 20-5 = 15
    assert sum(delta.per_symbol_delta.values()) == pytest.approx(15.0 - 120.0)
