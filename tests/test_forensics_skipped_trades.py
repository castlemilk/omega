"""Tests for skipped-trades detection (V35 trades V48 missed)."""
from pathlib import Path

from omega.tools.forensics.loader import load_run
from omega.tools.forensics.skipped_trades import SkippedTrade, find_skipped_trades

FIXTURES = Path(__file__).parent / "fixtures" / "forensics"


def test_find_skipped_trades_returns_v35_trades_with_no_v48_match():
    v35 = load_run(FIXTURES / "mini_v35_results.json", FIXTURES / "mini_v35_trades.csv")
    v48 = load_run(FIXTURES / "mini_v48_results.json", FIXTURES / "mini_v48_trades.csv")

    skipped = find_skipped_trades(v35, v48)
    # V35 has 6 trades, V48 has 2 (BTC short cycle 3, ETH short cycle 5).
    # V35 matches on (cycle, symbol, side): cycle 3 BTC short, cycle 5 ETH short.
    # So 6 - 2 = 4 skipped.
    assert len(skipped) == 4
    assert all(isinstance(s, SkippedTrade) for s in skipped)

    # Cycle 1 BTC long in V35 was not in V48
    symbols = {(s.cycle, s.symbol, s.side) for s in skipped}
    assert (1, "BTCUSDT", "long") in symbols
    assert (2, "ETHUSDT", "long") in symbols
    assert (4, "SOLUSDT", "long") in symbols
    assert (6, "BTCUSDT", "long") in symbols


def test_skipped_trade_attaches_baseline_conviction():
    v35 = load_run(FIXTURES / "mini_v35_results.json", FIXTURES / "mini_v35_trades.csv")
    v48 = load_run(FIXTURES / "mini_v48_results.json", FIXTURES / "mini_v48_trades.csv")
    skipped = find_skipped_trades(v35, v48)
    cycle_1 = next(s for s in skipped if s.cycle == 1)
    assert cycle_1.baseline_conviction == 0.35
    assert cycle_1.baseline_pnl == 50.0
