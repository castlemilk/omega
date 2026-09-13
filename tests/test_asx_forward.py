"""V309 — the forward ASX lane's pure parts, offline.

What is asserted is what the pre-registration promises: a store that writes once
and never rewrites, a publication-lag rule identical to the panel's, quintiles
that are fifths of the eligible set, a realisation that excludes a name with a
missing price rather than charging it 0% (V303), and a week that is only "complete"
when the calendar says so.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from omega.nodes.asx.forward import (
    ForwardStore,
    complete_weeks,
    knowable_panel_date,
    quintile_books,
    realise,
    weekly_mark_from,
)


def test_store_writes_once_and_records_md5(tmp_path: Path) -> None:
    st = ForwardStore(tmp_path)
    md5 = st.write_once("short_panel", "2026-09-05", {"date": "2026-09-05", "stocks": {}})
    assert md5 and len(md5) == 32
    again = st.write_once("short_panel", "2026-09-05", {"date": "2026-09-05", "stocks": {"X": 1}})
    assert again is None  # freeze-once: a second write is refused, not merged
    assert st.read("short_panel", "2026-09-05") == {"date": "2026-09-05", "stocks": {}}
    assert st.keys("short_panel") == ["2026-09-05"]
    man = json.loads((tmp_path / "MANIFEST.json").read_text())
    assert man["files"]["short_panel/2026-09-05.json"] == md5


def test_knowable_panel_date_applies_publication_lag() -> None:
    dates = ["2026-08-28", "2026-09-01", "2026-09-04", "2026-09-07"]
    # formed 2026-09-11, lag 7 → cutoff 2026-09-04 → the 09-04 panel, not 09-07
    assert knowable_panel_date(dates, "2026-09-11", lag_days=7) == "2026-09-04"
    assert knowable_panel_date(dates, "2026-09-04", lag_days=7) == "2026-08-28"  # cutoff 08-28 inclusive
    assert knowable_panel_date(dates, "2026-09-03", lag_days=7) is None  # cutoff 08-27: nothing published
    assert knowable_panel_date(dates, "2026-08-20", lag_days=7) is None


def test_quintile_books_are_fifths_of_the_eligible_set() -> None:
    shorts = {c: float(i) for i, c in enumerate("ABCDEFGHIJ")}  # A least shorted
    books = quintile_books(shorts, eligible=set("ABCDEFGHIJ"), min_names=10)
    assert books["Q1"] == ["A", "B"]
    assert books["Q5"] == ["I", "J"]
    assert books["universe"] == sorted("ABCDEFGHIJ")
    # a name outside the eligible set never enters a book, however low its short
    books = quintile_books({**shorts, "Z": -1.0}, eligible=set("ABCDEFGHIJ"), min_names=10)
    assert "Z" not in books["Q1"] and "Z" not in books["universe"]


def test_quintile_books_refuse_a_thin_cross_section() -> None:
    assert quintile_books({"A": 1.0, "B": 2.0}, eligible={"A", "B"}, min_names=10) is None


def test_realise_excludes_a_missing_price_rather_than_charging_zero() -> None:
    r = realise(["A", "B", "C"], p0={"A": 10, "B": 10, "C": 10}, p1={"A": 11, "B": 9})
    assert math.isclose(r["ret"], 0.0, abs_tol=1e-12)
    assert r["n"] == 2 and r["n_gap"] == 1
    assert realise([], {}, {})["ret"] is None


def test_complete_weeks_need_a_friday_or_a_later_week() -> None:
    sessions = ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14"]
    # week 37 ends on Friday 09-11 → complete; week 38 has one session, no Friday, nothing later
    assert complete_weeks(sessions) == [
        ("2026-09-11", ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"])
    ]
    # a holiday Friday: the week is complete once a later week's session exists
    sessions2 = ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-14"]
    assert complete_weeks(sessions2)[0][0] == "2026-09-10"


def test_weekly_mark_from_synthetic_inputs() -> None:
    codes = list("ABCDEFGHIJ")
    shorts = {c: float(i) for i, c in enumerate(codes)}
    p0 = {c: 10.0 for c in codes}
    p1 = {c: 10.0 * (1 + 0.01 * i) for i, c in enumerate(codes)}  # most-shorted rose most
    rec = weekly_mark_from(
        formed_date="2026-09-04",
        mark_date="2026-09-11",
        panel_date="2026-08-28",
        shorts=shorts,
        eligible=set(codes),
        p0=p0,
        p1=p1,
        lag_days=7,
        min_names=10,
    )
    assert rec is not None
    assert math.isclose(rec["q1"]["ret"], 0.005)  # A,B: 0%, 1% → 0.5%
    assert math.isclose(rec["q5"]["ret"], 0.085)  # I,J: 8%, 9%
    assert math.isclose(rec["spread_q1_q5"], 0.005 - 0.085)
    assert math.isclose(rec["universe"]["ret"], 0.045)
    assert math.isclose(rec["excess_q1_vs_ew"], 0.005 - 0.045)
    assert "equal-weight" in rec["comparator"]
    assert rec["panel_date"] == "2026-08-28" and rec["lag_days"] == 7
    assert rec["forward"] is False  # no lane start given: a backfill, never a forward obs


def test_forward_flag_needs_a_book_formed_on_or_after_lane_start() -> None:
    codes = list("ABCDEFGHIJ")
    kw = dict(
        mark_date="2026-09-11",
        panel_date="2026-08-28",
        shorts={c: float(i) for i, c in enumerate(codes)},
        eligible=set(codes),
        p0={c: 10.0 for c in codes},
        p1={c: 11.0 for c in codes},
        min_names=10,
    )
    assert (
        weekly_mark_from(formed_date="2026-09-04", lane_start="2026-09-05", **kw)["forward"]
        is False
    )
    assert (
        weekly_mark_from(formed_date="2026-09-04", lane_start="2026-09-04", **kw)["forward"]
        is True
    )


def test_store_records_lane_start_once(tmp_path: Path) -> None:
    st = ForwardStore(tmp_path)
    assert st.lane_start() is None
    assert st.ensure_lane_start("2026-09-13") == "2026-09-13"
    assert st.ensure_lane_start("2026-09-14") == "2026-09-13"  # first cycle wins, forever
    assert st.lane_start() == "2026-09-13"
