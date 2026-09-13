"""V307 — the intraday bucket assembly, tested against the rules it claims to follow.

Offline: synthetic bars only. The claims under test are the ones the ASX line paid
for — a missing bar is excluded not defaulted (V303), an unexpected stamp is
reported (V302), and a filter with no input applies to nothing rather than to
everything (V293).
"""

from __future__ import annotations

import gzip
import json
import math

from omega.nodes.asx.intraday import (
    BUCKETS,
    COLUMNS,
    STAMPS_1H,
    bucket_returns,
    encode_frozen,
    ew_daily,
    ex_dividend_dates,
    sessions,
    split_halves,
    tstat,
    volume_profile,
)


def _bar(day: str, stamp: str, o: float, c: float, v: float = 100.0) -> list:
    return [f"{day}T{stamp}", 0, o, max(o, c), min(o, c), c, v]


def _doc(bars: list[list]) -> dict:
    return {"code": "X", "columns": list(COLUMNS), "bars": bars}


def _full_day(day: str, closes: list[float], open_: float | None = None) -> list[list]:
    """Seven bars; each bar's open is the previous close (first from ``open_``)."""
    assert len(closes) == 7
    out = []
    prev = open_ if open_ is not None else closes[0]
    for stamp, c in zip(STAMPS_1H, closes, strict=True):
        out.append(_bar(day, stamp, prev, c))
        prev = c
    return out


def test_sessions_group_by_day_and_report_off_stamps():
    bars = _full_day("2024-01-02", [10, 11, 12, 13, 14, 15, 16])
    bars.append(_bar("2024-01-02", "09:30", 9, 9))  # pre-open print: not a session bar
    bars.append(["2024-01-03T10:00", 0, 1.0, 1.0, 1.0, math.nan, 5.0])  # NaN close
    sess, defects = sessions(_doc(bars))
    assert set(sess) == {"2024-01-02"}
    assert set(sess["2024-01-02"]) == set(STAMPS_1H)
    assert defects.off_stamp_bars == 1
    assert defects.nan_close_bars == 1
    assert defects.incomplete_sessions == 0
    assert defects.sessions == 1


def test_missing_bar_is_excluded_not_defaulted():
    bars = _full_day("2024-01-02", [10, 11, 12, 13, 14, 15, 16], open_=9)
    bars = [b for b in bars if not b[0].endswith("12:00")]  # lunch bar gone
    sess, defects = sessions(_doc(bars))
    assert defects.incomplete_sessions == 1
    r = bucket_returns(sess, ex_div=set())
    day = r["2024-01-02"]
    # B12 needs close(12:00); B13 needs close(12:00) as its base. Both absent — not 0.0.
    assert "B12" not in day and "B13" not in day
    assert 0.0 not in day.values()
    assert math.isclose(day["B10"], 10 / 9 - 1)
    assert math.isclose(day["B11"], 11 / 10 - 1)
    assert math.isclose(day["B16"], 16 / 15 - 1)


def test_overnight_needs_previous_close_and_skips_ex_div():
    d1 = _full_day("2024-01-02", [10, 11, 12, 13, 14, 15, 16])
    d2 = _full_day("2024-01-03", [17, 17, 17, 17, 17, 17, 17], open_=17)
    d3 = _full_day("2024-01-04", [18, 18, 18, 18, 18, 18, 18], open_=18)
    sess, _ = sessions(_doc(d1 + d2 + d3))
    r = bucket_returns(sess, ex_div={"2024-01-04"})
    assert "ON" not in r["2024-01-02"]  # no previous session
    assert math.isclose(r["2024-01-03"]["ON"], 17 / 16 - 1)
    assert "ON" not in r["2024-01-04"]  # ex-dividend: a dividend is not a pattern
    assert math.isclose(r["2024-01-04"]["B10"], 0.0)  # flat first hour is a real 0


def test_no_daily_series_means_no_overnight_at_all():
    d1 = _full_day("2024-01-02", [10] * 7)
    d2 = _full_day("2024-01-03", [11] * 7, open_=11)
    sess, _ = sessions(_doc(d1 + d2))
    r = bucket_returns(sess, ex_div=None)
    assert all("ON" not in day for day in r.values())


def test_ex_dividend_dates_from_ratio_change():
    daily = [
        ("2024-01-02", 100.0, 90.0),
        ("2024-01-03", 100.0, 90.0),
        ("2024-01-04", 99.0, 90.0),  # adjusted/close moved: ex-div
        ("2024-01-05", 98.0, 89.0909),  # same ratio to 5e-6: not ex-div
        ("2024-01-08", 0.0, 0.0),  # gap in the daily series
        ("2024-01-09", 98.0, 89.0909),  # after a gap: no prior ratio, nothing asserted
    ]
    assert ex_dividend_dates(daily) == {"2024-01-04"}


def test_ew_daily_requires_a_cross_section():
    per = {f"C{i}": {"2024-01-02": {"B11": 0.01 * (i + 1)}} for i in range(5)}
    thin = ew_daily(per, min_names=20)
    assert thin["B11"] == []
    ok = ew_daily(per, min_names=5)
    day, mean, n = ok["B11"][0]
    assert (day, n) == ("2024-01-02", 5)
    assert math.isclose(mean, 0.03)
    assert set(ok) == set(BUCKETS)


def test_tstat_and_halves():
    s = tstat([1.0, 2.0, 3.0, 4.0])
    assert s.n == 4 and math.isclose(s.mean, 2.5)
    assert math.isclose(s.t, 2.5 / (s.sd / 2.0))
    assert math.isnan(tstat([1.0, 1.0, 1.0]).t)  # sd == 0 is undefined, not infinite
    assert math.isnan(tstat([]).t) and tstat([]).n == 0
    rows = [("2024-01-02", 1.0, 30), ("2024-12-31", 2.0, 30), ("2025-01-01", 3.0, 30)]
    h1, h2 = split_halves(rows, "2025-01-01")
    assert (h1, h2) == ([1.0, 2.0], [3.0])


def test_volume_profile_is_a_share_over_complete_sessions():
    d1 = _full_day("2024-01-02", [10] * 7)
    for b in d1:
        b[6] = 30.0 if b[0].endswith("16:00") else 10.0
    d2 = _full_day("2024-01-03", [10] * 7)[:6]  # incomplete: ignored
    sess, _ = sessions(_doc(d1 + d2))
    prof = volume_profile(sess)
    assert math.isclose(sum(prof.values()), 1.0)
    assert math.isclose(prof["16:00"], 30 / 90)


def test_encode_frozen_is_byte_deterministic():
    doc = {"b": [1.5, 2.25], "a": "x"}
    one, two = encode_frozen(doc), encode_frozen(doc)
    assert one == two
    assert json.loads(gzip.decompress(one)) == doc
    assert gzip.decompress(one).startswith(b'{"a":"x"')  # sorted, compact
