#!/usr/bin/env python3
"""V307 — the ASX time-of-day map, evaluated against its pre-registered falsifiers.

Reads ONLY the frozen corpus (`data/frozen_series/asx/intraday/`) and the frozen v3
short series. Writes ONE file, `data/asx_runs/v307_tod.json`, and prints the tables
that go into `training_log/V307_ASX_INTRADAY.md`. Nothing here trades or sizes.

Order of evaluation is the pre-registered one: F1 first, and if it fails nothing
below it is computed.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from omega.nodes.asx.intraday import (  # noqa: E402
    BUCKETS,
    FROZEN_INTRADAY,
    STAMPS_1H,
    Stat,
    bucket_returns,
    ew_daily,
    ex_dividend_dates,
    load_frozen,
    load_manifest,
    sessions,
    split_halves,
    tstat,
    volume_profile,
)
from omega.nodes.asx.panel import PUBLICATION_LAG_DAYS, load_short_series_csv  # noqa: E402

V3_SHORTS = ROOT / "data" / "frozen_series" / "asx" / "v3" / "shorts"
OUT = ROOT / "data" / "asx_runs" / "v307_tod.json"

# Pre-registered bars (V307 §5).
F1_COMPLETE_SHARE = 0.97
F1_AUCTION_SHARE = 0.15
F2_T_FULL = 3.0
F2_T_HALF = 1.5
F3_BPS = 20.0
F3_BPS_SENSITIVITY = 5.0
S_T = 2.4
HALF_CUT = "2025-01-01"
MIN_NAMES = 20


def _stat_dict(s: Stat) -> dict[str, Any]:
    return s.as_dict()


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------
def load_corpus(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    man = load_manifest(root)
    per: dict[str, Any] = {}
    for rel in sorted(man["files"]):
        if not rel.startswith("1h/"):
            continue
        code = rel.split("/")[1][:-8]
        doc = load_frozen(code, "1h", root)
        sess, defects = sessions(doc)
        ex_div: set[str] | None = None
        if f"daily/{code}.json.gz" in man["files"]:
            ddoc = load_frozen(code, "daily", root)
            ex_div = ex_dividend_dates([(r[0], r[1], r[2]) for r in ddoc["rows"]])
        per[code] = {
            "sessions": sess,
            "defects": defects,
            "ex_div": ex_div,
            "returns": bucket_returns(sess, ex_div),
            "vol_profile": volume_profile(sess),
        }
    return man, per


# ---------------------------------------------------------------------------
# F1
# ---------------------------------------------------------------------------
def f1_integrity(per: dict[str, Any]) -> dict[str, Any]:
    sess_total = sum(p["defects"].sessions for p in per.values())
    incomplete = sum(p["defects"].incomplete_sessions for p in per.values())
    off = sum(p["defects"].off_stamp_bars for p in per.values())
    nan = sum(p["defects"].nan_close_bars for p in per.values())
    no_daily = sorted(c for c, p in per.items() if p["ex_div"] is None)
    auction = statistics.median(
        p["vol_profile"]["16:00"]
        for p in per.values()
        if not math.isnan(p["vol_profile"]["16:00"])
    )
    complete_share = 1.0 - incomplete / sess_total if sess_total else 0.0
    checks = {
        "complete_session_share": {
            "value": complete_share,
            "bar": F1_COMPLETE_SHARE,
            "pass": complete_share >= F1_COMPLETE_SHARE,
        },
        "off_stamp_bars": {"value": off, "bar": 0, "pass": off == 0},
        "nan_close_bars": {"value": nan, "bar": 0, "pass": nan == 0},
        "auction_volume_share_median": {
            "value": auction,
            "bar": F1_AUCTION_SHARE,
            "pass": auction >= F1_AUCTION_SHARE,
        },
        "names_without_daily_series": {
            "value": no_daily,
            "pass": True,
            "note": "ON not computed for these",
        },
    }
    return {
        "names": len(per),
        "name_sessions": sess_total,
        "incomplete_sessions": incomplete,
        "checks": checks,
        "pass": all(c["pass"] for c in checks.values()),
    }


# ---------------------------------------------------------------------------
# F2 / F3
# ---------------------------------------------------------------------------
def f2_f3_buckets(ew: dict[str, list[tuple[str, float, int]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for b in BUCKETS:
        rows = ew[b]
        full = tstat([m for _, m, _ in rows])
        h1v, h2v = split_halves(rows, HALF_CUT)
        h1, h2 = tstat(h1v), tstat(h2v)
        same_sign = (
            not math.isnan(h1.t)
            and not math.isnan(h2.t)
            and math.copysign(1, h1.mean)
            == math.copysign(1, h2.mean)
            == math.copysign(1, full.mean)
        )
        f2 = (
            not math.isnan(full.t)
            and abs(full.t) >= F2_T_FULL
            and same_sign
            and abs(h1.t) >= F2_T_HALF
            and abs(h2.t) >= F2_T_HALF
        )
        out[b] = {
            "full": _stat_dict(full),
            "h1": _stat_dict(h1),
            "h2": _stat_dict(h2),
            "median_names_per_day": statistics.median(n for _, _, n in rows) if rows else 0,
            "first_date": rows[0][0] if rows else None,
            "last_date": rows[-1][0] if rows else None,
            "F2_recurring": f2,
            "F3_tradeable_20bps": f2 and abs(full.mean) * 1e4 >= F3_BPS,
            "F3_sensitivity_5bps": f2 and abs(full.mean) * 1e4 >= F3_BPS_SENSITIVITY,
        }
    # Best same-sign run of ADJACENT intraday buckets (B10..B16), cumulative mean.
    intr = [b for b in BUCKETS if b != "ON"]
    best: dict[str, Any] | None = None
    for i in range(len(intr)):
        for j in range(i, len(intr)):
            run = intr[i : j + 1]
            means = [out[b]["full"]["mean"] for b in run]
            if any(math.isnan(m) for m in means):
                continue
            signs = {math.copysign(1, m) for m in means}
            if len(signs) != 1:
                continue
            cum = sum(means) * 1e4
            if best is None or abs(cum) > abs(best["cum_bps"]):
                best = {"buckets": run, "cum_bps": cum}
    out["_best_adjacent_run"] = best
    out["_F3_any_run_clears_20bps"] = bool(best and abs(best["cum_bps"]) >= F3_BPS)
    return out


# ---------------------------------------------------------------------------
# secondaries
# ---------------------------------------------------------------------------
def _daily_conditional_diff(
    per: dict[str, Any],
    cond_bucket_fn,
    target_fn,
) -> list[float]:
    """Per date: EW mean of target among names with cond>0 minus among cond<0."""
    by_day: dict[str, tuple[list[float], list[float]]] = {}
    for p in per.values():
        for day, r in p["returns"].items():
            c = cond_bucket_fn(r)
            t = target_fn(r)
            if c is None or t is None or c == 0:
                continue
            up, dn = by_day.setdefault(day, ([], []))
            (up if c > 0 else dn).append(t)
    out = []
    for _day, (up, dn) in sorted(by_day.items()):
        if len(up) >= 10 and len(dn) >= 10:
            out.append(statistics.fmean(up) - statistics.fmean(dn))
    return out


def s1_gap_reversal(per: dict[str, Any]) -> dict[str, Any]:
    diffs = _daily_conditional_diff(per, lambda r: r.get("ON"), lambda r: r.get("B10"))
    s = tstat(diffs)
    return {
        "definition": "EW daily mean of B10 | ON>0  minus  EW daily mean of B10 | ON<0",
        "stat": _stat_dict(s),
        "reading": "negative = first hour fades the gap; positive = continues it",
        "significant": not math.isnan(s.t) and abs(s.t) >= S_T,
    }


def _morning(r: dict[str, float]) -> float | None:
    ks = ("B10", "B11", "B12", "B13", "B14")
    if not all(k in r for k in ks):
        return None
    x = 1.0
    for k in ks:
        x *= 1.0 + r[k]
    return x - 1.0


def _late(r: dict[str, float]) -> float | None:
    if "B15" not in r or "B16" not in r:
        return None
    return (1.0 + r["B15"]) * (1.0 + r["B16"]) - 1.0


def s2_momentum_into_close(per: dict[str, Any]) -> dict[str, Any]:
    diffs = _daily_conditional_diff(per, _morning, _late)
    s = tstat(diffs)
    return {
        "definition": "EW daily mean of (B15∘B16) | morning>0  minus  | morning<0, morning = B10∘…∘B14",
        "stat": _stat_dict(s),
        "reading": "positive = morning direction carries into the auction; negative = reverses",
        "significant": not math.isnan(s.t) and abs(s.t) >= S_T,
    }


def _lagged_step(series: list[tuple[str, float]], days: list[str], lag: int) -> dict[str, float]:
    """Knowable short reading per session date, two-pointer (series ascending)."""
    out: dict[str, float] = {}
    i = 0
    best: float | None = None
    for day in days:
        cutoff = (date.fromisoformat(day) - timedelta(days=lag)).isoformat()
        while i < len(series) and series[i][0] <= cutoff:
            best = series[i][1]
            i += 1
        if best is not None:
            out[day] = best
    return out


def s3_short_quintile_auction(per: dict[str, Any]) -> dict[str, Any]:
    shorts = load_short_series_csv(V3_SHORTS)
    days = sorted({d for p in per.values() for d in p["returns"]})
    lagged = {c: _lagged_step(shorts[c], days, PUBLICATION_LAG_DAYS) for c in per if c in shorts}
    diffs: list[float] = []
    q_means: dict[int, list[float]] = {q: [] for q in range(5)}
    n_days = 0
    for day in days:
        rows = [
            (lagged[c][day], per[c]["returns"][day]["B16"])
            for c in lagged
            if day in lagged[c] and "B16" in per[c]["returns"].get(day, {})
        ]
        if len(rows) < 50:
            continue
        rows.sort(key=lambda x: x[0])
        k = len(rows) // 5
        qs = [rows[i * k : (i + 1) * k] if i < 4 else rows[4 * k :] for i in range(5)]
        ms = [statistics.fmean(v for _, v in q) for q in qs]
        for i, m in enumerate(ms):
            q_means[i].append(m)
        diffs.append(ms[4] - ms[0])
        n_days += 1
    s = tstat(diffs)
    return {
        "definition": f"EW daily B16 of most-shorted quintile (Q5) minus least-shorted (Q1); short pct lagged {PUBLICATION_LAG_DAYS}d",
        "names_with_short_series": len(lagged),
        "days": n_days,
        "quintile_mean_bps": {
            f"Q{q + 1}": statistics.fmean(v) * 1e4 if v else None for q, v in q_means.items()
        },
        "stat": _stat_dict(s),
        "reading": "positive = most-shorted names rise more into the close (covering pressure); negative = they are sold into it",
        "significant": not math.isnan(s.t) and abs(s.t) >= S_T,
    }


# ---------------------------------------------------------------------------
# volume profiles (map colour, not a gate)
# ---------------------------------------------------------------------------
# A stamp whose volume reads 0 on more than half of all (name, session) bars is not
# measured by this source — reported as such, never averaged into a profile.
UNMEASURABLE_ZERO_RATE = 0.5


def _zero_rate_1h(per: dict[str, Any]) -> dict[str, float]:
    z: dict[str, int] = {s: 0 for s in STAMPS_1H}
    n: dict[str, int] = {s: 0 for s in STAMPS_1H}
    for p in per.values():
        for s in p["sessions"].values():
            for st, bar in s.items():
                n[st] += 1
                z[st] += bar[4] == 0
    return {st: (z[st] / n[st] if n[st] else math.nan) for st in STAMPS_1H}


def profile_1h(per: dict[str, Any]) -> dict[str, Any]:
    zero = _zero_rate_1h(per)
    unmeasurable = [st for st, r in zero.items() if r > UNMEASURABLE_ZERO_RATE]
    prof = {
        s: statistics.median(
            p["vol_profile"][s] for p in per.values() if not math.isnan(p["vol_profile"][s])
        )
        for s in STAMPS_1H
    }
    return {
        "median_share": prof,
        "zero_volume_rate": zero,
        "unmeasurable_stamps": unmeasurable,
        "note": "yfinance leaves the opening bar's volume at 0 on most sessions (V302: read the "
        "metadata); the 10:00 share is not a measurement of the opening auction.",
    }


def profile_5m(root: Path, man: dict[str, Any]) -> dict[str, Any]:
    """Median share of session volume per 5m stamp, across names. Audit only."""
    shares: dict[str, list[float]] = {}
    zero: dict[str, int] = {}
    cnt: dict[str, int] = {}
    n = 0
    for rel in sorted(man["files"]):
        if not rel.startswith("5m/"):
            continue
        code = rel.split("/")[1][:-8]
        try:
            doc = load_frozen(code, "5m", root)
        except FileNotFoundError:
            continue  # gitignored corpus absent on this checkout
        by_day: dict[str, dict[str, float]] = {}
        for row in doc["bars"]:
            st = row[0][11:16]
            by_day.setdefault(row[0][:10], {})[st] = row[6]
            cnt[st] = cnt.get(st, 0) + 1
            zero[st] = zero.get(st, 0) + (row[6] == 0)
        per_stamp: dict[str, list[float]] = {}
        for _day, d in by_day.items():
            tot = sum(d.values())
            if tot <= 0 or len(d) < 60:
                continue
            for st, v in d.items():
                per_stamp.setdefault(st, []).append(v / tot)
        for st, v in per_stamp.items():
            shares.setdefault(st, []).append(statistics.median(v))
        n += 1
    prof = {st: statistics.median(v) for st, v in sorted(shares.items())}
    zero_rate = {st: zero[st] / cnt[st] for st in sorted(cnt)}
    unmeasurable = [st for st, r in zero_rate.items() if r > UNMEASURABLE_ZERO_RATE]
    cont = {st: v for st, v in prof.items() if st < "16:00" and st not in unmeasurable}
    trough = min(cont, key=cont.get) if cont else None
    # Hour-of-day shares from the 5m bars, for the map (the 1h source cannot give
    # the opening hour; this one cannot give the opening 5 minutes).
    hour: dict[str, float] = {}
    for st, v in prof.items():
        if st in unmeasurable:
            continue
        h = "16:00" if st >= "16:00" else st[:2] + ":00"
        hour[h] = hour.get(h, 0.0) + v
    return {
        "names": n,
        "stamps": len(prof),
        "profile": prof,
        "zero_volume_rate_first_and_last": {
            st: r for st, r in zero_rate.items() if st <= "10:15" or st >= "15:55"
        },
        "unmeasurable_stamps": unmeasurable,
        "hourly_share_from_5m": hour,
        "continuous_trough_stamp": trough,
    }


# ---------------------------------------------------------------------------
# audits — NOT pre-registered. Added after the first run to test whether S1 is an
# artifact of the source, and where inside the first hour it lives. Labelled as
# such in the artifact; they change no verdict above.
# ---------------------------------------------------------------------------
# ASX staggered open (Sydney): group 1 (0-9, A-B) 10:00:00, group 2 (C-F) 10:02:15,
# group 3 (G-M) 10:04:30, group 4 (N-R) 10:06:45, group 5 (S-Z) 10:09:00. Only group
# 1 opens inside the 10:00 5m bar, so if the reversal were a stale pre-open price
# artifact it would be weakest there.
_GROUPS = (("A-B", "B"), ("C-F", "F"), ("G-M", "M"), ("N-R", "R"), ("S-Z", "Z"))


def opening_group(code: str) -> str:
    ch = code[0]
    if ch.isdigit():
        return "A-B"
    for name, last in _GROUPS:
        if ch <= last:
            return name
    return "S-Z"


def audit_s1_by_opening_group(per: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for g, _ in _GROUPS:
        sub = {c: p for c, p in per.items() if opening_group(c) == g}
        # S1's 10-per-side floor is too high for a 20-name group; use 5 here, always.
        diffs: list[float] = []
        # 20-34 names per group: relax the per-side floor to 5 for this audit only.
        if not diffs:
            by_day: dict[str, tuple[list[float], list[float]]] = {}
            for p in sub.values():
                for day, r in p["returns"].items():
                    if "ON" in r and "B10" in r and r["ON"] != 0:
                        up, dn = by_day.setdefault(day, ([], []))
                        (up if r["ON"] > 0 else dn).append(r["B10"])
            diffs = [
                statistics.fmean(u) - statistics.fmean(d)
                for _, (u, d) in sorted(by_day.items())
                if len(u) >= 5 and len(d) >= 5
            ]
        out[g] = {"names": len(sub), **_stat_dict(tstat(diffs))}
    return out


def audit_s1_5m(root: Path, man: dict[str, Any]) -> dict[str, Any]:
    """Where in the first hour does the reversal happen, and does it survive an
    entry at 10:10 — after every opening group has opened and traded?"""
    checkpoints = ("10:00", "10:05", "10:10", "10:15", "10:30", "10:45", "11:00", "12:00", "16:10")
    from_open: dict[str, dict[str, tuple[list[float], list[float]]]] = {c: {} for c in checkpoints}
    from_1010: dict[str, dict[str, tuple[list[float], list[float]]]] = {
        c: {} for c in ("10:55", "12:00", "16:10")
    }
    names = 0
    for rel in sorted(man["files"]):
        if not rel.startswith("5m/"):
            continue
        code = rel.split("/")[1][:-8]
        try:
            doc = load_frozen(code, "5m", root)
        except FileNotFoundError:
            continue
        names += 1
        days: dict[str, dict[str, list[Any]]] = {}
        for row in doc["bars"]:
            days.setdefault(row[0][:10], {})[row[0][11:16]] = row
        prev: float | None = None
        for day in sorted(days):
            s = days[day]
            b0, b10 = s.get("10:00"), s.get("10:10")
            last = s.get("16:10") or s.get("16:00")
            if prev:
                if b0 is not None and b0[2] > 0:
                    gap = b0[2] / prev - 1.0
                    if gap != 0:
                        for cp in checkpoints:
                            b = s.get(cp)
                            if b is not None:
                                up, dn = from_open[cp].setdefault(day, ([], []))
                                (up if gap > 0 else dn).append(b[5] / b0[2] - 1.0)
                if b10 is not None and b10[2] > 0:
                    gap = b10[2] / prev - 1.0
                    if gap != 0:
                        for cp in from_1010:
                            b = s.get(cp)
                            if b is not None:
                                up, dn = from_1010[cp].setdefault(day, ([], []))
                                (up if gap > 0 else dn).append(b[5] / b10[2] - 1.0)
            prev = last[5] if last and last[5] > 0 else None

    def _collapse(table: dict[str, dict[str, tuple[list[float], list[float]]]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for cp, by_day in table.items():
            diffs = [
                statistics.fmean(u) - statistics.fmean(d)
                for _, (u, d) in sorted(by_day.items())
                if len(u) >= 10 and len(d) >= 10
            ]
            out[cp] = _stat_dict(tstat(diffs))
        return out

    return {
        "names": names,
        "definition": "gap-up minus gap-down EW daily mean of the cumulative return from the entry price to each checkpoint close",
        "from_10:00_open": _collapse(from_open),
        "from_10:10_open (every group has opened; the tradeable entry)": _collapse(from_1010),
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=FROZEN_INTRADAY)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    man, per = load_corpus(args.root)
    res: dict[str, Any] = {
        "version": "V307",
        "corpus": {
            "downloaded_on": man["downloaded_on"],
            "names_1h": len(per),
            "holes": man["holes"],
            "universe_as_of": "2023-10-26",
        },
        "bars": {
            "F1_complete_share": F1_COMPLETE_SHARE,
            "F1_auction_share": F1_AUCTION_SHARE,
            "F2_t_full": F2_T_FULL,
            "F2_t_half": F2_T_HALF,
            "F3_bps": F3_BPS,
            "secondary_t": S_T,
            "half_cut": HALF_CUT,
            "min_names_per_day": MIN_NAMES,
        },
    }
    res["F1"] = f1_integrity(per)
    print(f"F1 integrity: {'PASS' if res['F1']['pass'] else 'FAIL'}")
    for k, c in res["F1"]["checks"].items():
        print(f"  {k:32s} {c['value']!s:>40s}  {'ok' if c['pass'] else 'FAIL'}")
    if not res["F1"]["pass"]:
        res["verdict"] = "F1 FAIL — corpus is not a corpus; nothing else measured"
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
        return 1

    ew = ew_daily({c: p["returns"] for c, p in per.items()}, MIN_NAMES)
    res["buckets"] = f2_f3_buckets(ew)
    print("\n| bucket | n days | mean bps | t | H1 bps (t) | H2 bps (t) | F2 | F3 |")
    print("|---|---:|---:|---:|---:|---:|---|---|")
    for b in BUCKETS:
        r = res["buckets"][b]
        f, h1, h2 = r["full"], r["h1"], r["h2"]
        fmt = lambda s: f"{s['mean_bps']:+.2f} ({s['t']:+.2f})" if s["t"] is not None else "n/a"  # noqa: E731
        print(
            f"| {b} | {f['n']} | {f['mean_bps']:+.2f} | {f['t']:+.2f} | {fmt(h1)} | {fmt(h2)} | "
            f"{'**yes**' if r['F2_recurring'] else 'no'} | {'**yes**' if r['F3_tradeable_20bps'] else 'no'} |"
        )
    print(f"\nbest adjacent same-sign run: {res['buckets']['_best_adjacent_run']}")

    res["S1"] = s1_gap_reversal(per)
    res["S2"] = s2_momentum_into_close(per)
    res["S3"] = s3_short_quintile_auction(per)
    for k in ("S1", "S2", "S3"):
        s = res[k]["stat"]
        print(
            f"{k}: mean {s['mean_bps']:+.2f} bps, t {s['t']:+.2f}, n {s['n']}  "
            f"{'SIGNIFICANT' if res[k]['significant'] else 'not significant'}"
        )
    print(f"S3 quintile means (bps): {res['S3']['quintile_mean_bps']}")

    res["volume_profile_1h"] = profile_1h(per)
    res["volume_profile_5m"] = profile_5m(args.root, man)
    v1 = res["volume_profile_1h"]
    print(
        f"\n1h volume profile (median share): "
        f"{ {k: round(v, 3) for k, v in v1['median_share'].items()} }  "
        f"unmeasurable: {v1['unmeasurable_stamps']}"
    )
    v5 = res["volume_profile_5m"]
    print(
        f"5m: hourly share { ({k: round(v, 3) for k, v in v5['hourly_share_from_5m'].items()}) }  "
        f"unmeasurable: {v5['unmeasurable_stamps']}  "
        f"continuous trough: {v5['continuous_trough_stamp']} ({v5['names']} names)"
    )

    res["audits_post_hoc"] = {
        "S1_by_opening_group_1h": audit_s1_by_opening_group(per),
        "S1_5m_decomposition": audit_s1_5m(args.root, man),
    }
    print("\naudit — S1 by opening group (1h):")
    for g, r in res["audits_post_hoc"]["S1_by_opening_group_1h"].items():
        print(
            f"   {g}: {r['mean_bps']:+7.2f} bps  t={r['t']:+6.2f}  n={r['n']}  names={r['names']}"
        )
    print("audit — S1 on 5m, from the 10:00 open:")
    a5 = res["audits_post_hoc"]["S1_5m_decomposition"]
    for cp, r in a5["from_10:00_open"].items():
        print(f"   →{cp}: {r['mean_bps']:+7.2f} bps  t={r['t']:+6.2f}  n={r['n']}")
    print("audit — S1 on 5m, entered at the 10:10 open:")
    for cp, r in a5["from_10:10_open (every group has opened; the tradeable entry)"].items():
        print(f"   →{cp}: {r['mean_bps']:+7.2f} bps  t={r['t']:+6.2f}  n={r['n']}")

    f2_hits = [b for b in BUCKETS if res["buckets"][b]["F2_recurring"]]
    f3_hits = [b for b in BUCKETS if res["buckets"][b]["F3_tradeable_20bps"]]
    res["verdict"] = {
        "F2_recurring_buckets": f2_hits,
        "F3_tradeable_buckets": f3_hits,
        "F3_any_adjacent_run": res["buckets"]["_F3_any_run_clears_20bps"],
        "secondaries_significant": [k for k in ("S1", "S2", "S3") if res[k]["significant"]],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
