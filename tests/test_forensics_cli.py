"""End-to-end test for the forensics CLI runner."""
import json
from pathlib import Path

from omega.tools.forensics.run_diff import run_diff

FIXTURES = Path(__file__).parent / "fixtures" / "forensics"


def test_run_diff_produces_json_and_markdown(tmp_path: Path):
    out_json = tmp_path / "v35-v48-forensics.json"
    out_md = tmp_path / "v35-v48-forensics.md"
    exit_code = run_diff(
        baseline_results=FIXTURES / "mini_v35_results.json",
        baseline_trades=FIXTURES / "mini_v35_trades.csv",
        target_results=FIXTURES / "mini_v48_results.json",
        target_trades=FIXTURES / "mini_v48_trades.csv",
        out_json=out_json,
        out_md=out_md,
        hold_threshold=0.20,
    )
    assert exit_code == 0
    assert out_json.exists()
    assert out_md.exists()
    data = json.loads(out_json.read_text())
    assert data["schema_version"] == "1.0"
    assert data["status"] == "ok"
    assert len(data["hypotheses"]) == 3
    assert data["baselines"]["v35"]["version"] == "mini_v35"
    assert data["baselines"]["v48"]["version"] == "mini_v48"


def test_run_diff_signal_delta_sums_to_pnl_gap(tmp_path: Path):
    """The sum of per-symbol deltas should equal the PnL gap (integrity invariant)."""
    out_json = tmp_path / "forensics.json"
    out_md = tmp_path / "forensics.md"
    run_diff(
        baseline_results=FIXTURES / "mini_v35_results.json",
        baseline_trades=FIXTURES / "mini_v35_trades.csv",
        target_results=FIXTURES / "mini_v48_results.json",
        target_trades=FIXTURES / "mini_v48_trades.csv",
        out_json=out_json,
        out_md=out_md,
        hold_threshold=0.20,
    )
    data = json.loads(out_json.read_text())
    per_symbol = data["signal_contribution_delta_proxy"]["per_symbol"]
    # Sum of all per-symbol PnL deltas == V48 trade sum - V35 trade sum
    # V35: 50+30+30+10-5+5 = 120; V48: 20-5 = 15; diff = -105
    assert sum(per_symbol.values()) == -105.0
