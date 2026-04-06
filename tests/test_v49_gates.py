"""Tests for V49 hard gate module."""
import json
from pathlib import Path

from omega.eval.v49_gates import GateResult, check_v49_gates


def _write_results(path: Path, *, pnl: float, trades: int, max_dd: float) -> None:
    """Write a minimal results JSON with the fields v49_gates reads."""
    payload = {
        "version": path.stem.replace("_results", ""),
        "trades": {
            "total_closed": trades,
            "total_pnl_usd": pnl,
            "win_rate": 0.3,
            "long_trades": trades // 2,
            "short_trades": trades - trades // 2,
            "profit_factor": 1.3,
        },
        "observability": {
            "max_drawdown_usd": max_dd,
            "total_zero_trade_cycles": 100,
            "conviction_filter_rate": 0.5,
        },
    }
    path.write_text(json.dumps(payload))


def _write_trades(path: Path, trades: list[tuple[str, str, float, str]]) -> None:
    """Write a minimal trades CSV with the columns v49_gates reads.

    trades is a list of (symbol, side, pnl, regime) tuples.
    """
    lines = [
        "cycle,timestamp,symbol,side,size,entry_price,exit_price,pnl,slippage,hold_cycles,conviction,regime,sit_out_reason"
    ]
    for i, (symbol, side, pnl, regime) in enumerate(trades):
        lines.append(
            f"{i},2026-04-06T00:00:00Z,{symbol},{side},100,100,101,{pnl},0,2,0.07,{regime},normal"
        )
    path.write_text("\n".join(lines) + "\n")


def test_gates_pass_when_v49_beats_v48_in_every_regime(tmp_path: Path):
    v48_results = tmp_path / "v48_results.json"
    v48_trades_p = tmp_path / "v48_trades.csv"
    v49_results = tmp_path / "v49_results.json"
    v49_trades_p = tmp_path / "v49_trades.csv"

    _write_results(v48_results, pnl=32.0, trades=103, max_dd=10.0)
    _write_trades(
        v48_trades_p,
        [
            ("BTCUSDT", "long", 10.0, "normal"),
            ("ADAUSDT", "short", 5.0, "normal"),
            ("ETHUSDT", "long", 15.0, "high_vol"),
            ("DOTUSDT", "short", 2.0, "crisis"),
        ],
    )
    _write_results(v49_results, pnl=90.0, trades=120, max_dd=8.0)
    _write_trades(
        v49_trades_p,
        [
            ("BTCUSDT", "long", 10.0, "normal"),
            ("ADAUSDT", "short", 50.0, "normal"),
            ("ETHUSDT", "long", 20.0, "high_vol"),
            ("DOTUSDT", "short", 10.0, "crisis"),
        ],
    )

    result = check_v49_gates(
        v49_results=v49_results,
        v49_trades=v49_trades_p,
        v48_results=v48_results,
        v48_trades=v48_trades_p,
    )
    assert isinstance(result, GateResult)
    assert result.passed is True, f"expected pass, got failures: {result.failures}"
    assert result.failures == []


def test_gate_fails_pnl_floor(tmp_path: Path):
    v48 = tmp_path / "v48_results.json"
    v49 = tmp_path / "v49_results.json"
    _write_results(v48, pnl=32.0, trades=103, max_dd=10.0)
    _write_results(v49, pnl=20.0, trades=120, max_dd=5.0)  # below v48 pnl floor
    v48t = tmp_path / "v48_trades.csv"
    v49t = tmp_path / "v49_trades.csv"
    _write_trades(v48t, [("BTCUSDT", "long", 32.0, "normal")])
    _write_trades(v49t, [("BTCUSDT", "long", 20.0, "normal")])

    result = check_v49_gates(v49, v49t, v48, v48t)
    assert result.passed is False
    assert any("pnl_floor" in f for f in result.failures)


def test_gate_fails_trade_count_floor(tmp_path: Path):
    v48 = tmp_path / "v48_results.json"
    v49 = tmp_path / "v49_results.json"
    _write_results(v48, pnl=32.0, trades=103, max_dd=10.0)
    _write_results(v49, pnl=100.0, trades=15, max_dd=5.0)  # beats pnl but only 15 trades (< 20 floor)
    v48t = tmp_path / "v48_trades.csv"
    v49t = tmp_path / "v49_trades.csv"
    _write_trades(v48t, [("BTCUSDT", "long", 32.0, "normal")])
    _write_trades(v49t, [("BTCUSDT", "long", 100.0, "normal")])

    result = check_v49_gates(v49, v49t, v48, v48t)
    assert result.passed is False
    assert any("trade_count_floor" in f for f in result.failures)


def test_gate_fails_drawdown_ceiling(tmp_path: Path):
    v48 = tmp_path / "v48_results.json"
    v49 = tmp_path / "v49_results.json"
    _write_results(v48, pnl=32.0, trades=103, max_dd=10.0)
    _write_results(v49, pnl=50.0, trades=120, max_dd=50.0)  # 5x drawdown
    v48t = tmp_path / "v48_trades.csv"
    v49t = tmp_path / "v49_trades.csv"
    _write_trades(v48t, [("BTCUSDT", "long", 32.0, "normal")])
    _write_trades(v49t, [("BTCUSDT", "long", 50.0, "normal")])

    result = check_v49_gates(v49, v49t, v48, v48t)
    assert result.passed is False
    assert any("drawdown_ceiling" in f for f in result.failures)


def test_gate_fails_regime_parity_high_vol_regression(tmp_path: Path):
    """V48 is BETTER than V35 in high_vol regime — V49 must preserve that gain."""
    v48 = tmp_path / "v48_results.json"
    v49 = tmp_path / "v49_results.json"
    _write_results(v48, pnl=32.0, trades=103, max_dd=10.0)
    _write_results(v49, pnl=100.0, trades=120, max_dd=8.0)
    v48t = tmp_path / "v48_trades.csv"
    v49t = tmp_path / "v49_trades.csv"
    _write_trades(
        v48t,
        [
            ("BTCUSDT", "long", 15.0, "normal"),
            ("ETHUSDT", "long", 17.0, "high_vol"),
        ],
    )
    _write_trades(
        v49t,
        [
            ("BTCUSDT", "long", 100.0, "normal"),
            ("ETHUSDT", "long", -5.0, "high_vol"),
        ],
    )

    result = check_v49_gates(v49, v49t, v48, v48t)
    assert result.passed is False
    assert any("regime_parity" in f and "high_vol" in f for f in result.failures)


def test_gate_fails_auto_apply_audit_missing_before(tmp_path: Path):
    """If the results JSON carries auto_applied diffs without before snapshots, fail."""
    v48 = tmp_path / "v48_results.json"
    v49 = tmp_path / "v49_results.json"
    _write_results(v48, pnl=32.0, trades=103, max_dd=10.0)
    v49_payload = {
        "version": "v49",
        "trades": {
            "total_closed": 120,
            "total_pnl_usd": 100.0,
            "win_rate": 0.3,
            "long_trades": 60,
            "short_trades": 60,
            "profit_factor": 1.3,
        },
        "observability": {
            "max_drawdown_usd": 5.0,
            "total_zero_trade_cycles": 80,
            "conviction_filter_rate": 0.5,
        },
        "meta_analyst": {
            "auto_applied": [
                {"proposal_id": "abc", "change_kind": "threshold", "before": None, "after": 0.05}
            ]
        },
    }
    v49.write_text(json.dumps(v49_payload))
    v48t = tmp_path / "v48_trades.csv"
    v49t = tmp_path / "v49_trades.csv"
    _write_trades(v48t, [("BTCUSDT", "long", 32.0, "normal")])
    _write_trades(v49t, [("BTCUSDT", "long", 100.0, "normal")])

    result = check_v49_gates(v49, v49t, v48, v48t)
    assert result.passed is False
    assert any("auto_apply_audit" in f for f in result.failures)


def test_gate_writes_report_json(tmp_path: Path):
    v48 = tmp_path / "v48_results.json"
    v49 = tmp_path / "v49_results.json"
    _write_results(v48, pnl=32.0, trades=103, max_dd=10.0)
    _write_results(v49, pnl=90.0, trades=120, max_dd=8.0)
    v48t = tmp_path / "v48_trades.csv"
    v49t = tmp_path / "v49_trades.csv"
    _write_trades(v48t, [("BTCUSDT", "long", 32.0, "normal")])
    _write_trades(v49t, [("BTCUSDT", "long", 90.0, "normal")])

    out = tmp_path / "v49_gate_result.json"
    result = check_v49_gates(v49, v49t, v48, v48t, out_path=out)
    assert result.passed is True
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["passed"] is True
    assert "gates" in data and len(data["gates"]) == 6
