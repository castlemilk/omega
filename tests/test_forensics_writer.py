"""Tests for forensics JSON + Markdown writer."""
import json
from pathlib import Path

from omega.tools.forensics.conviction_histogram import compute_histogram
from omega.tools.forensics.hypothesis_ranker import rank_hypotheses
from omega.tools.forensics.loader import load_run
from omega.tools.forensics.signal_delta import compute_signal_delta_proxy
from omega.tools.forensics.skipped_trades import find_skipped_trades
from omega.tools.forensics.writer import write_forensics_json, write_forensics_markdown

FIXTURES = Path(__file__).parent / "fixtures" / "forensics"


def _build_bundle():
    v35 = load_run(FIXTURES / "mini_v35_results.json", FIXTURES / "mini_v35_trades.csv")
    v48 = load_run(FIXTURES / "mini_v48_results.json", FIXTURES / "mini_v48_trades.csv")
    h35 = compute_histogram(v35, 0.20)
    h48 = compute_histogram(v48, 0.20)
    delta = compute_signal_delta_proxy(v35, v48)
    skipped = find_skipped_trades(v35, v48)
    hypotheses = rank_hypotheses(v35=v35, v48=v48, v35_histogram=h35, v48_histogram=h48, delta=delta, skipped=skipped)
    return v35, v48, h35, h48, delta, skipped, hypotheses


def test_write_forensics_json_produces_valid_schema(tmp_path: Path):
    v35, v48, h35, h48, delta, skipped, hypotheses = _build_bundle()
    out = tmp_path / "forensics.json"
    write_forensics_json(
        out,
        v35=v35, v48=v48,
        v35_histogram=h35, v48_histogram=h48,
        delta=delta, skipped=skipped, hypotheses=hypotheses,
    )
    data = json.loads(out.read_text())
    assert data["schema_version"] == "1.0"
    assert data["status"] == "ok"
    assert data["baselines"]["v35"]["pnl"] == 120.0
    assert data["baselines"]["v48"]["pnl"] == 15.0
    assert "conviction_histogram" in data
    assert "skipped_trades" in data
    assert len(data["hypotheses"]) == 3
    assert data["hypotheses"][0]["rank"] == 1
    assert "regime_breakdown" in data
    assert "signal_contribution_delta_proxy" in data


def test_write_forensics_markdown_contains_top_hypothesis(tmp_path: Path):
    v35, v48, h35, h48, delta, skipped, hypotheses = _build_bundle()
    out = tmp_path / "forensics.md"
    write_forensics_markdown(
        out,
        v35=v35, v48=v48,
        v35_histogram=h35, v48_histogram=h48,
        delta=delta, skipped=skipped, hypotheses=hypotheses,
    )
    text = out.read_text()
    assert "# V35 → V48 Forensics Report" in text
    assert hypotheses[0].claim in text
    assert "| Metric | V35 | V48 |" in text  # summary table
