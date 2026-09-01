"""Tests for the ASX benchmark source.

The property under test is narrow and load-bearing: a period the index does not
cover must return ``None``, never ``0.0``. A silent zero reads downstream as "the
market was flat that week", which converts an ABSENT benchmark into a FABRICATED
one and hands the strategy the market's entire return as excess.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from omega.nodes.asx.benchmark import PRICE_ONLY, IndexBenchmark


@pytest.fixture
def idx(tmp_path: Path) -> IndexBenchmark:
    (tmp_path / "XJT.csv").write_text(
        "date,close\n2024-09-02,100.0\n2024-09-03,110.0\n2024-09-06,121.0\n"
    )
    return IndexBenchmark(code="XJT", root=tmp_path)


def test_coverage_reported(idx: IndexBenchmark) -> None:
    assert idx.covered == ("2024-09-02", "2024-09-06")


def test_return_within_coverage(idx: IndexBenchmark) -> None:
    assert idx.total_return("2024-09-02", "2024-09-03") == pytest.approx(0.10)
    assert idx.total_return("2024-09-02", "2024-09-06") == pytest.approx(0.21)


def test_before_coverage_is_none_not_zero(idx: IndexBenchmark) -> None:
    """The whole point. A missing benchmark must not read as a flat market."""
    assert idx.total_return("2016-01-01", "2016-06-01") is None
    assert idx.total_return("2016-01-01", "2024-09-03") is None


def test_asof_uses_last_session_on_or_before(idx: IndexBenchmark) -> None:
    """2024-09-07 is a Saturday: resolves back to Friday's close, not forward."""
    assert idx.total_return("2024-09-02", "2024-09-07") == pytest.approx(0.21)


def test_missing_file_is_inert_not_crash(tmp_path: Path) -> None:
    b = IndexBenchmark(code="NOPE", root=tmp_path)
    assert b.covered is None
    assert b.total_return("2024-09-02", "2024-09-03") is None
    assert b.provenance()["sessions"] == 0


def test_price_only_indices_flagged(tmp_path: Path) -> None:
    """XJO must not silently pass as a total-return comparator."""
    (tmp_path / "XJO.csv").write_text("date,close\n2024-09-02,100.0\n2024-09-03,110.0\n")
    assert "XJO" in PRICE_ONLY
    assert IndexBenchmark(code="XJO", root=tmp_path).provenance()["total_return_index"] is False
    assert IndexBenchmark(code="XJT", root=tmp_path).provenance()["total_return_index"] is True


def test_frozen_series_matches_documented_limitation() -> None:
    """Guards the real frozen data: if a backfill (#572) lands, this test should fail
    and the 2-year limitation in the docstrings must be revisited rather than left stale."""
    b = IndexBenchmark()
    if b.covered is None:
        pytest.skip("frozen benchmark not present")
    assert b.covered[0] == "2024-09-02", (
        "index coverage changed — #572 may have landed; update benchmark.py and panel docs"
    )
