"""V247 Phase 2 — tests for the walk-forward observability instruments."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from wf_obs import dual_tail, reentry_coupling_window


def _row(window, regime, config, pnl):
    return {"window": window, "regime": regime, "config": config, "pnl": pnl}


def test_dual_tail_divergence_detected():
    # OFF recent: [-1000, -100, 500]; ON recent: [-800, -400, 900]
    # deltas: [+200, -300, +400] -> delta p25 = -50 (negative)
    # level p25: OFF -550, ON -600 ... choose values so level tail TIGHTENS
    rows = []
    for w, off_pnl, on_pnl in (
        ("w1", -1000.0, -800.0),  # delta +200
        ("w2", -100.0, -400.0),  # delta -300
        ("w3", 500.0, 900.0),  # delta +400
    ):
        rows.append(_row(w, "recent", "off_cfg", off_pnl))
        rows.append(_row(w, "recent", "on_cfg", on_pnl))
    st = dual_tail(rows, "off_cfg", "on_cfg")
    rec = st["recent"]
    assert rec["n"] == 3
    # deltas sorted: [-300, +200, +400], p25 = -50
    assert abs(rec["delta_p25"] - (-50.0)) < 1e-9
    # levels sorted OFF: [-1000, -100, 500] p25 = -550; ON: [-800,-400,900] p25 = -600
    assert abs(rec["level_p25_off"] - (-550.0)) < 1e-9
    assert abs(rec["level_p25_on"] - (-600.0)) < 1e-9
    # delta-p25 negative AND level-p25 worsened -> tails agree, no divergence
    assert rec["diverges"] is False


def test_dual_tail_divergence_flag_fires():
    # Construct the V245/V246 shape: delta-p25 negative, level-p25 improves.
    rows = []
    for w, off_pnl, on_pnl in (
        ("w1", -2000.0, -1000.0),  # delta +1000, worst level improves
        ("w2", 0.0, -300.0),  # delta -300
        ("w3", 100.0, -100.0),  # delta -200
        ("w4", 500.0, 800.0),  # delta +300
    ):
        rows.append(_row(w, "recent", "off", off_pnl))
        rows.append(_row(w, "recent", "on", on_pnl))
    rec = dual_tail(rows, "off", "on")["recent"]
    assert rec["delta_p25"] < 0
    assert rec["level_p25_change"] > 0
    assert rec["diverges"] is True


def _trade(cycle, symbol, side, hold, pnl=0.0):
    return {
        "cycle": str(cycle),
        "symbol": symbol,
        "side": side,
        "hold_cycles": str(hold),
        "pnl": str(pnl),
        "_entry_cycle": cycle - hold,
        "_exit_cycle": cycle,
    }


def test_reentry_coupling_counts():
    # OFF: one BTC trade opened at 10 (exit 20, hold 10), one ETH opened 5.
    off = [_trade(20, "BTC", "long", 10), _trade(15, "ETH", "long", 10)]
    # ON: same BTC open but earlier exit (14, hold 4) -> matched on open key;
    # then a re-entry BTC opened at 16 (within 8 bars of ON exit 14, and OFF
    # has no exit at 14) -> ON-only + re-entry. ETH matched identically.
    on = [
        _trade(14, "BTC", "long", 4),
        _trade(28, "BTC", "long", 12),  # entry 16
        _trade(15, "ETH", "long", 10),
    ]
    s = reentry_coupling_window(on, off, window_bars=8)
    assert s["matched_open"] == 2  # BTC@10 and ETH@5
    assert s["on_only"] == 1  # BTC entry 16
    assert s["off_only"] == 0
    assert s["reentries_within_bars"] == 1  # freed by the ON-only exit at 14


def test_reentry_not_counted_when_off_had_same_exit():
    # If OFF also exited BTC at cycle 14, the ON re-entry is NOT attributed
    # to the mechanism (the exit would have fired on OFF too).
    off = [_trade(14, "BTC", "long", 4)]
    on = [_trade(14, "BTC", "long", 4), _trade(28, "BTC", "long", 12)]
    s = reentry_coupling_window(on, off, window_bars=8)
    assert s["on_only"] == 1
    assert s["reentries_within_bars"] == 0
