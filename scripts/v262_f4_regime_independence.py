#!/usr/bin/env python3
"""
V262-2 falsifier F4 — intraday regime-independence gate.

PRE-REGISTERED in training_log/V262.md §6:

    F4 — regime independence (the gate on the thesis).
    Compute per-name hourly regime labels and correlate against the macro-day
    regime label. If correlation > 0.7, intraday regime is the daily regime
    with more sampling — no new information, effective N does not grow →
    REFUTED, stop before any grid.

Purely observational. Reads the V262 frozen 1h corpus + the committed
walk-forward manifest. Touches NO strategy code and mutates nothing.

Method (all components pre-declared, none tuned):

  macro-day regime   `data/walk_forward_manifest.json` — the committed 26
                     non-overlapping 90-day windows, each already carrying a
                     mechanical `regime` label from
                     scripts/walk_forward_freeze.py:regime_label. Each 1h bar
                     inherits the label of the window containing it.

  hourly regime      The SAME regime_label thresholds (crisis: max_dd >= 0.30
                     or ret <= -0.15; trend: ret >= +0.20; else recent),
                     applied to non-overlapping 90-BAR windows of the name's
                     own 1h close series. 90 bars at 1h = the 3.75-day window
                     named in V262.md §2a; STRIDE = WINDOW mirrors the daily
                     tiling (STRIDE_DAYS == WINDOW_DAYS). Single-name path, so
                     basket_metrics degenerates to that name's normalized path.

  correlation        Cramer's V over the (hourly label x macro label)
                     contingency table — the standard bounded-[0,1]
                     association measure for categorical x categorical, so the
                     pre-declared 0.7 cut applies directly. Agreement rate,
                     normalized mutual information and the full contingency
                     table are reported alongside as diagnostics.

  degeneracy guard   V260 was refuted for a degenerate classifier (94% one
                     class). A degenerate hourly labeller would drive Cramer's
                     V toward 0 and manufacture a SPURIOUS PASS, so the hourly
                     label distribution is reported and a diagnostic-only
                     secondary pass with sqrt-time-scaled thresholds is
                     computed. The VERDICT is taken from the primary
                     (unscaled, pre-declared) arm only.

MATIC/POL: per V262.md §3, MATIC and POL are treated as two separate
name-histories (the 80h migration hole is never spliced).

Usage:
    python3 scripts/v262_f4_regime_independence.py
    python3 scripts/v262_f4_regime_independence.py --out data/v262_f4.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTRADAY_DIR = ROOT / "data" / "frozen_series" / "binance_intraday"
MANIFEST = ROOT / "data" / "walk_forward_manifest.json"
DEFAULT_OUT = ROOT / "data" / "v262_f4_regime_independence.json"

# --- pre-declared, NOT tuned -------------------------------------------------
HOURLY_WINDOW_BARS = 90  # V262.md §2a: "a 3.75-day window (90 bars at 1h)"
HOURLY_STRIDE_BARS = 90  # mirrors STRIDE_DAYS == WINDOW_DAYS in the daily tiling
F4_CORRELATION_CUT = 0.7  # V262.md §6: > 0.7 => REFUTED

CRISIS_DD = 0.30
CRISIS_RET = -0.15
TREND_RET = 0.20

# V240-selective tradable set = frozen 13-name universe minus blacklist
# {BTC, DOT, LINK}, minus ETH (regime reference only). MATIC and POL are
# separate name-histories (V262.md §3).
PRIMARY_UNIVERSE = [
    "SOLUSDT", "BNBUSDT", "AVAXUSDT", "XRPUSDT", "SUIUSDT",
    "POLUSDT", "ADAUSDT", "NEARUSDT", "ARBUSDT", "MATICUSDT",
]
# Reported for completeness, EXCLUDED from the universe mean (§3: freezing
# data != admitting a name).
SECONDARY_NAMES = ["BTCUSDT", "ETHUSDT", "DOTUSDT", "LINKUSDT"]

LABELS = ("crisis", "trend", "recent")


def regime_label_from(ret: float, max_dd: float) -> str:
    """Identical thresholds to scripts/walk_forward_freeze.py:regime_label."""
    if max_dd >= CRISIS_DD or ret <= CRISIS_RET:
        return "crisis"
    if ret >= TREND_RET:
        return "trend"
    return "recent"


def path_metrics(closes: list[float]) -> tuple[float, float]:
    """(total return, max drawdown) of a single normalized price path."""
    base = closes[0]
    ret = closes[-1] / base - 1.0
    peak, max_dd = closes[0], 0.0
    for v in closes:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak)
    return ret, max_dd


def load_1h(symbol: str) -> list[tuple[int, float]]:
    """(open_ms, close) for every frozen 1h bar of `symbol`, time-ordered."""
    d = INTRADAY_DIR / symbol / "1h"
    bars: list[tuple[int, float]] = []
    for p in sorted(d.glob("*.json.gz")):
        with gzip.open(p, "rb") as fh:
            blob = json.loads(fh.read())
        # columns: open_ms, open, high, low, close, volume
        for row in blob["bars"]:
            bars.append((int(row[0]), float(row[4])))
    bars.sort(key=lambda r: r[0])
    return bars


def macro_intervals() -> list[tuple[int, int, str]]:
    """(start_ms, end_ms, label) for each committed 90-day walk-forward window."""
    man = json.loads(MANIFEST.read_text())
    out = []
    for w in man["windows"]:
        lo, hi = w["date_range"]
        s = int(datetime.fromisoformat(lo).replace(tzinfo=timezone.utc).timestamp() * 1000)
        e = int(datetime.fromisoformat(hi).replace(tzinfo=timezone.utc).timestamp() * 1000)
        out.append((s, e, w["regime"]))
    out.sort()
    return out


def macro_label_at(intervals: list[tuple[int, int, str]], ts_ms: int) -> str | None:
    for s, e, lab in intervals:
        if s <= ts_ms < e:
            return lab
    return None


def cramers_v(table: dict[str, dict[str, int]]) -> tuple[float, int]:
    """Cramer's V for a categorical x categorical contingency table."""
    rows = sorted(table)
    cols = sorted({c for r in table.values() for c in r})
    n = sum(sum(r.values()) for r in table.values())
    if n == 0 or len(rows) < 2 or len(cols) < 2:
        return 0.0, n
    row_tot = {r: sum(table[r].values()) for r in rows}
    col_tot = {c: sum(table[r].get(c, 0) for r in rows) for c in cols}
    chi2 = 0.0
    for r in rows:
        for c in cols:
            exp = row_tot[r] * col_tot[c] / n
            if exp <= 0:
                continue
            obs = table[r].get(c, 0)
            chi2 += (obs - exp) ** 2 / exp
    k = min(len(rows), len(cols)) - 1
    return math.sqrt(chi2 / (n * k)) if k > 0 else 0.0, n


def norm_mutual_info(table: dict[str, dict[str, int]]) -> float:
    """Mutual information normalized by min(H(hourly), H(macro))."""
    rows = sorted(table)
    cols = sorted({c for r in table.values() for c in r})
    n = sum(sum(r.values()) for r in table.values())
    if n == 0:
        return 0.0
    px = {r: sum(table[r].values()) / n for r in rows}
    py = {c: sum(table[r].get(c, 0) for r in rows) / n for c in cols}
    mi = 0.0
    for r in rows:
        for c in cols:
            pxy = table[r].get(c, 0) / n
            if pxy > 0:
                mi += pxy * math.log2(pxy / (px[r] * py[c]))
    hx = -sum(p * math.log2(p) for p in px.values() if p > 0)
    hy = -sum(p * math.log2(p) for p in py.values() if p > 0)
    denom = min(hx, hy)
    return mi / denom if denom > 0 else 0.0


def score_symbol(
    symbol: str,
    intervals: list[tuple[int, int, str]],
    scale: float,
) -> dict | None:
    """Tile the name's 1h series into 90-bar windows and cross-tab vs macro.

    `scale` multiplies the return thresholds only (1.0 = pre-declared primary
    arm; the diagnostic arm uses sqrt(3.75/90) time-scaling).
    """
    bars = load_1h(symbol)
    if len(bars) < HOURLY_WINDOW_BARS:
        return None
    crisis_ret = CRISIS_RET * scale
    trend_ret = TREND_RET * scale
    crisis_dd = CRISIS_DD * scale

    table: dict[str, dict[str, int]] = {}
    hourly_counts: dict[str, int] = {}
    macro_counts: dict[str, int] = {}
    agree = 0
    skipped = 0

    for i in range(0, len(bars) - HOURLY_WINDOW_BARS + 1, HOURLY_STRIDE_BARS):
        chunk = bars[i:i + HOURLY_WINDOW_BARS]
        # window is labelled at its close; macro label taken at the same instant
        macro = macro_label_at(intervals, chunk[-1][0])
        if macro is None:
            skipped += 1
            continue
        ret, max_dd = path_metrics([c for _, c in chunk])
        if max_dd >= crisis_dd or ret <= crisis_ret:
            lab = "crisis"
        elif ret >= trend_ret:
            lab = "trend"
        else:
            lab = "recent"
        table.setdefault(lab, {})
        table[lab][macro] = table[lab].get(macro, 0) + 1
        hourly_counts[lab] = hourly_counts.get(lab, 0) + 1
        macro_counts[macro] = macro_counts.get(macro, 0) + 1
        agree += int(lab == macro)

    v, n = cramers_v(table)
    if n == 0:
        return None
    top = max(hourly_counts.values()) / n
    return {
        "symbol": symbol,
        "n_windows": n,
        "skipped_windows": skipped,
        "cramers_v": round(v, 6),
        "agreement_rate": round(agree / n, 6),
        "normalized_mi": round(norm_mutual_info(table), 6),
        "hourly_label_counts": {k: hourly_counts.get(k, 0) for k in LABELS},
        "macro_label_counts": {k: macro_counts.get(k, 0) for k in LABELS},
        "hourly_top_class_frac": round(top, 6),
        "degenerate": top >= 0.90,
        "contingency": {r: dict(sorted(table[r].items())) for r in sorted(table)},
    }


def run_arm(symbols: list[str], intervals, scale: float) -> list[dict]:
    return [r for s in symbols if (r := score_symbol(s, intervals, scale)) is not None]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    intervals = macro_intervals()
    # diagnostic arm only: sqrt-time scaling of a 90-day threshold onto 3.75 days
    diag_scale = math.sqrt(HOURLY_WINDOW_BARS / 24.0 / 90.0)

    result: dict = {
        "_falsifier": "V262-2 F4 (regime independence)",
        "_source": "data/frozen_series/binance_intraday/{symbol}/1h/*.json.gz",
        "_macro_source": "data/walk_forward_manifest.json",
        "_method": "Cramer's V over (hourly 90-bar regime label x macro-day 90-day regime label)",
        "_thresholds": {
            "crisis_max_dd": CRISIS_DD,
            "crisis_ret": CRISIS_RET,
            "trend_ret": TREND_RET,
            "hourly_window_bars": HOURLY_WINDOW_BARS,
            "hourly_stride_bars": HOURLY_STRIDE_BARS,
            "f4_cut": F4_CORRELATION_CUT,
        },
        "_macro_windows": len(intervals),
        "_diagnostic_scale": round(diag_scale, 6),
    }

    for arm, scale in (("primary", 1.0), ("diagnostic_scaled", diag_scale)):
        primary = run_arm(PRIMARY_UNIVERSE, intervals, scale)
        secondary = run_arm(SECONDARY_NAMES, intervals, scale)
        vs = [r["cramers_v"] for r in primary]
        result[arm] = {
            "per_name": primary,
            "secondary_per_name": secondary,
            "universe_mean_cramers_v": round(math.fsum(vs) / len(vs), 6) if vs else None,
            "universe_max_cramers_v": round(max(vs), 6) if vs else None,
            "n_names": len(primary),
            "n_degenerate": sum(1 for r in primary if r["degenerate"]),
        }

    mean_v = result["primary"]["universe_mean_cramers_v"]
    result["verdict"] = {
        "arm": "primary (pre-declared thresholds, unscaled)",
        "universe_mean_cramers_v": mean_v,
        "cut": F4_CORRELATION_CUT,
        "f4": "FAIL (REFUTED: intraday regime is daily regime resampled)"
        if mean_v is not None and mean_v > F4_CORRELATION_CUT
        else "PASS (intraday regime is orthogonal to macro-day regime)",
    }

    out = Path(args.out)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    print(f"macro windows: {len(intervals)}")
    for arm in ("primary", "diagnostic_scaled"):
        a = result[arm]
        print(f"\n--- arm: {arm} ---")
        print(f"{'symbol':<10} {'n':>5} {'CramersV':>9} {'agree':>7} {'nMI':>7}  hourly dist")
        for r in a["per_name"] + a["secondary_per_name"]:
            tag = "" if r in a["per_name"] else "  (excl)"
            dist = "/".join(f"{r['hourly_label_counts'][k]}" for k in LABELS)
            print(f"{r['symbol']:<10} {r['n_windows']:>5} {r['cramers_v']:>9.4f} "
                  f"{r['agreement_rate']:>7.3f} {r['normalized_mi']:>7.4f}  {dist}{tag}")
        print(f"universe-mean Cramer's V = {a['universe_mean_cramers_v']}  "
              f"(max {a['universe_max_cramers_v']}, degenerate {a['n_degenerate']}/{a['n_names']})")

    print(f"\nF4 VERDICT: {result['verdict']['f4']}")
    print(f"  universe-mean Cramer's V = {mean_v}  vs cut {F4_CORRELATION_CUT}")
    # relative_to raises for any --out outside the repo (and for a relative --out,
    # whose absolute form is cwd-based); the display path must never fail the run
    # after the artifact has already been written.
    try:
        shown: Path | str = out.resolve().relative_to(ROOT)
    except ValueError:
        shown = out
    print(f"  written: {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
