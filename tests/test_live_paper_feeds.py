"""
V250 — network-free unit tests for omega.live_paper.feeds.

Covers the load-bearing, deterministic logic (no live fetch): the frozen-path
guard, as-of staleness semantics, atomic+checksummed cache, and the frozen-schema
mirror + reproducible content hash.
"""

from __future__ import annotations

from datetime import date

import pytest

from omega.live_paper import config, feeds


def test_assert_live_source_allows_http():
    assert feeds.assert_live_source("https://api.binance.com/x") == "https://api.binance.com/x"
    assert feeds.assert_live_source("http://example.com") == "http://example.com"


def test_assert_live_source_rejects_file_scheme():
    with pytest.raises(feeds.FrozenPathViolation):
        feeds.assert_live_source("file:///data/frozen_series/fng.json")


def test_assert_live_source_rejects_frozen_roots():
    frozen_file = str(config.FROZEN_ROOTS[0] / "fng.json")
    with pytest.raises(feeds.FrozenPathViolation):
        feeds.assert_live_source(frozen_file)
    with pytest.raises(feeds.FrozenPathViolation):
        feeds.assert_live_source(str(config.FROZEN_ROOTS[2]))  # macro_cache.db


def test_assert_live_source_rejects_arbitrary_local_path():
    with pytest.raises(feeds.FrozenPathViolation):
        feeds.assert_live_source("/etc/hosts")


def test_as_of_pick_fresh_stale_out_of_range():
    series = {"2026-07-08": 1.0, "2026-07-10": 2.0}  # Wed, Fri
    # Fri: exact obs -> fresh/0d
    r = feeds.as_of_pick(series, date(2026, 7, 10), max_stale_days=7)
    assert (r.status, r.staleness_days, r.value) == ("fresh", 0, 2.0)
    # Sun: latest obs is Fri -> stale/2d
    r = feeds.as_of_pick(series, date(2026, 7, 12), max_stale_days=7)
    assert (r.status, r.staleness_days, r.value) == ("stale", 2, 2.0)
    # Beyond staleness cap -> out_of_range
    r = feeds.as_of_pick(series, date(2026, 7, 20), max_stale_days=7)
    assert r.status == "out_of_range"
    # Before first obs -> out_of_range
    r = feeds.as_of_pick(series, date(2026, 7, 1), max_stale_days=7)
    assert r.status == "out_of_range"
    # Empty series
    assert feeds.as_of_pick({}, date(2026, 7, 10), 7).status == "empty"


def test_series_doc_schema_and_content_md5_stability():
    from scripts.live_paper_smoke import FROZEN_SCHEMA_KEYS

    s = {"2026-07-10": 1.5, "2026-07-11": 1.6}
    d1 = feeds.series_doc("t", "src", "u", s)
    # Superset of the frozen-manifest schema.
    assert FROZEN_SCHEMA_KEYS.issubset(d1.keys())
    assert d1["n_obs"] == 2 and d1["first_date"] == "2026-07-10" and d1["last_date"] == "2026-07-11"
    # content_md5 is stable across builds and independent of fetched_at_utc.
    d2 = feeds.series_doc("t", "src", "u", dict(reversed(list(s.items()))))
    assert d1["content_md5"] == d2["content_md5"]
    # Changing a value changes the hash.
    d3 = feeds.series_doc("t", "src", "u", {"2026-07-10": 9.9, "2026-07-11": 1.6})
    assert d3["content_md5"] != d1["content_md5"]


def test_write_and_verify_cache_atomic_checksum(tmp_path):
    doc = feeds.series_doc("t", "src", "u", {"2026-07-10": 1.0})
    target = tmp_path / "t.json"
    file_md5 = feeds.write_cache(target, doc)
    assert target.is_file()
    assert (tmp_path / "t.json.md5").read_text().strip() == file_md5
    assert feeds.verify_cache(target) is True
    # A stray truncated .tmp beside the committed file must not affect verification.
    (tmp_path / "t.json.tmp.999").write_bytes(b'{"partial": true')
    assert feeds.verify_cache(target) is True
    # Corrupting the committed file breaks the checksum.
    target.write_bytes(b'{"corrupted": true}')
    assert feeds.verify_cache(target) is False
