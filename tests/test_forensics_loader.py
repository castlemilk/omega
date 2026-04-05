"""Tests for forensics data loader."""
from pathlib import Path

import pytest

from omega.tools.forensics.loader import RunArtifacts, load_run

FIXTURES = Path(__file__).parent / "fixtures" / "forensics"


def test_load_run_reads_results_json_and_trades_csv():
    run = load_run(
        results_path=FIXTURES / "mini_v35_results.json",
        trades_path=FIXTURES / "mini_v35_trades.csv",
    )
    assert isinstance(run, RunArtifacts)
    assert run.version == "mini_v35"
    assert run.total_pnl == 120.0
    assert run.win_rate == 0.5
    assert run.conviction_filter_rate == 0.2
    assert len(run.trades) == 6
    assert run.trades[0]["symbol"] == "BTCUSDT"
    assert run.trades[0]["pnl"] == 50.0


def test_load_run_computes_per_regime_pnl():
    run = load_run(
        results_path=FIXTURES / "mini_v35_results.json",
        trades_path=FIXTURES / "mini_v35_trades.csv",
    )
    # bull: 50 + 30 + 10 = 90; chop: 30 + 5 = 35; bear: -5
    assert run.regime_pnl["bull"] == pytest.approx(90.0)
    assert run.regime_pnl["chop"] == pytest.approx(35.0)
    assert run.regime_pnl["bear"] == pytest.approx(-5.0)


def test_load_run_handles_v48_shape():
    run = load_run(
        results_path=FIXTURES / "mini_v48_results.json",
        trades_path=FIXTURES / "mini_v48_trades.csv",
    )
    assert run.version == "mini_v48"
    assert run.total_pnl == 15.0
    assert len(run.trades) == 2
    assert run.zero_trade_cycles == 7
