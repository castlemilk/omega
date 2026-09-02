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


def test_return_type_comes_from_manifest_not_a_code_list(tmp_path: Path) -> None:
    """The manifest is authoritative. The first version of benchmark.py guessed the
    price/total classification from a hardcoded code list; a guess about which
    benchmark is honest is exactly what should be read from the data."""
    (tmp_path / "MANIFEST.json").write_text(
        '{"series": {"XJO": {"return_type": "total"}}}'
    )
    (tmp_path / "XJO.csv").write_text("date,close\n2024-09-02,100.0\n")
    # XJO is in the hardcoded PRICE_ONLY set, but the manifest says total: manifest wins.
    assert "XJO" in PRICE_ONLY
    assert IndexBenchmark(code="XJO", root=tmp_path).is_total_return is True


def test_price_only_fallback_without_manifest(tmp_path: Path) -> None:
    (tmp_path / "XJO.csv").write_text("date,close\n2024-09-02,100.0\n")
    (tmp_path / "XJT.csv").write_text("date,close\n2024-09-02,100.0\n")
    assert IndexBenchmark(code="XJO", root=tmp_path).is_total_return is False
    assert IndexBenchmark(code="XJT", root=tmp_path).is_total_return is True


def test_frozen_xjt_is_total_return_and_starts_2019() -> None:
    """Guards the real frozen data. 2019-04-29 is an UPSTREAM limit that #573 states
    cannot be backfilled, so unlike the previous 2024-09-02 floor this is not expected
    to move. If it does, the tension this module documents has changed and the
    docstrings must be revisited."""
    b = IndexBenchmark()
    if b.covered is None:
        pytest.skip("frozen benchmark not present")
    assert b.code == "XJT"
    assert b.is_total_return is True
    assert b.covered[0] == "2019-04-29"


def test_deeper_indices_are_all_price_only() -> None:
    """The tension worth pinning: every series that reaches further back than XJT is
    price-only, so a longer study can only be bought by giving up dividends."""
    b = IndexBenchmark()
    if b.covered is None:
        pytest.skip("frozen benchmark not present")
    for code in ("XJO", "XAO", "XKO"):
        other = IndexBenchmark(code=code)
        if other.covered is None:
            continue
        assert other.covered[0] < b.covered[0], f"{code} should predate XJT"
        assert other.is_total_return is False, f"{code} unexpectedly total-return"
