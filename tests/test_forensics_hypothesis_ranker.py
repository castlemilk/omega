"""Tests for hypothesis ranker."""
from pathlib import Path

from omega.tools.forensics.conviction_histogram import compute_histogram
from omega.tools.forensics.hypothesis_ranker import (
    Hypothesis,
    rank_hypotheses,
)
from omega.tools.forensics.loader import load_run
from omega.tools.forensics.signal_delta import compute_signal_delta_proxy
from omega.tools.forensics.skipped_trades import find_skipped_trades

FIXTURES = Path(__file__).parent / "fixtures" / "forensics"


def test_rank_hypotheses_returns_top3_with_descending_confidence():
    v35 = load_run(FIXTURES / "mini_v35_results.json", FIXTURES / "mini_v35_trades.csv")
    v48 = load_run(FIXTURES / "mini_v48_results.json", FIXTURES / "mini_v48_trades.csv")

    histogram_v35 = compute_histogram(v35, hold_threshold=0.20)
    histogram_v48 = compute_histogram(v48, hold_threshold=0.20)
    delta = compute_signal_delta_proxy(v35, v48)
    skipped = find_skipped_trades(v35, v48)

    hypotheses = rank_hypotheses(
        v35=v35,
        v48=v48,
        v35_histogram=histogram_v35,
        v48_histogram=histogram_v48,
        delta=delta,
        skipped=skipped,
    )
    assert len(hypotheses) == 3
    assert all(isinstance(h, Hypothesis) for h in hypotheses)
    # Ranks are 1, 2, 3
    assert [h.rank for h in hypotheses] == [1, 2, 3]
    # Confidence is monotonically non-increasing
    assert hypotheses[0].confidence >= hypotheses[1].confidence
    assert hypotheses[1].confidence >= hypotheses[2].confidence
    # Every hypothesis has non-empty claim and evidence refs
    for h in hypotheses:
        assert h.claim
        assert h.evidence_refs


def test_rank_hypotheses_identifies_conviction_widening_when_present():
    v35 = load_run(FIXTURES / "mini_v35_results.json", FIXTURES / "mini_v35_trades.csv")
    v48 = load_run(FIXTURES / "mini_v48_results.json", FIXTURES / "mini_v48_trades.csv")
    histogram_v35 = compute_histogram(v35, hold_threshold=0.20)
    histogram_v48 = compute_histogram(v48, hold_threshold=0.20)
    delta = compute_signal_delta_proxy(v35, v48)
    skipped = find_skipped_trades(v35, v48)

    hypotheses = rank_hypotheses(
        v35=v35, v48=v48,
        v35_histogram=histogram_v35, v48_histogram=histogram_v48,
        delta=delta, skipped=skipped,
    )
    # In fixtures: V48 mean conviction (0.065) is ~5x lower than V35 (0.255).
    # The top hypothesis should mention conviction/HOLD band.
    top_claim_lower = hypotheses[0].claim.lower()
    assert "conviction" in top_claim_lower or "hold" in top_claim_lower
