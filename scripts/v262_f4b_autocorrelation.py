#!/usr/bin/env python3
"""
V262-2 falsifier F4b — intraday regime AUTOCORRELATION gate.

PRE-REGISTERED (V262_F4_VERDICT.md §6 residual risk 1):

    Serial dependence. Low correlation with the *macro* label != mutual
    independence *between consecutive hourly windows*. If adjacent 90-bar
    windows are autocorrelated, effective N grows sub-linearly in bar count.
    V262-2 should measure the lag-1 label transition matrix before quoting
    any N.

Pre-registered thresholds (locked, no post-hoc tuning) — universe-mean lag-1
same-state probability on the PRIMARY arm:

    > 0.90          -> FAIL           (effective N is ~1x, not 24x)
    0.60 < p <= 0.90 -> CAVEATED PASS (effective N grows ~5-15x, not 24x)
    <= 0.60         -> CLEAN PASS     (effective N genuinely grows)

Purely observational. Reads the V262 frozen 1h corpus. Touches NO strategy
code and mutates nothing.

Method — every component reused verbatim from the F4 scorer, nothing tuned:

  windows        The SAME non-overlapping 90-bar tiling of each name's own 1h
                 close series used by scripts/v262_f4_regime_independence.py
                 (HOURLY_WINDOW_BARS == HOURLY_STRIDE_BARS == 90).
  labels         The SAME regime_label thresholds (crisis: max_dd >= 0.30 or
                 ret <= -0.15; trend: ret >= +0.20; else recent).
  arms           Primary (unscaled, pre-declared) is the VERDICT arm. The
                 diagnostic arm re-runs with the sqrt-time-scaled thresholds
                 (x0.2041) that F4 used to defeat the degeneracy objection.
                 Both reported, per F4's dual-track discipline.

  contiguity     A lag-1 transition is counted ONLY when window i+1 begins
                 exactly HOURLY_STRIDE_BARS hours after window i (timestamp
                 check, not index adjacency). This is load-bearing: the frozen
                 corpus has real holes (V262.md §3 — the MATIC/POL 80h
                 migration gap), and index-adjacency across a hole would
                 fabricate a transition between non-consecutive periods.

  N_eff          Two estimators off the lag-1 transition matrix P:
                   lambda2 = second-largest eigenvalue modulus (SLEM) of P,
                             the Markov-chain analogue of an AR(1) rho.
                   n_eff_ratio_simple = 1 - lambda2      (the form named in
                             the task's diagnostic clause)
                   n_eff_ratio_slem   = (1-lambda2)/(1+lambda2)  (the standard
                             serial-correlation ESS deflator; strictly more
                             conservative)

  chance guard   Same-state probability is inflated MECHANICALLY by a skewed
                 marginal: a labeller emitting 91% "recent" scores ~0.83
                 same-state with zero persistence. So the chance baseline
                 sum_i p_i^2 (marginals) and the excess over it are reported
                 for every name. The VERDICT still uses the raw pre-registered
                 quantity — the baseline is interpretation, not a moved goalpost.

Usage:
    python3 scripts/v262_f4b_autocorrelation.py
    python3 scripts/v262_f4b_autocorrelation.py --out data/v262_f4b.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTRADAY_DIR = ROOT / "data" / "frozen_series" / "binance_intraday"
DEFAULT_OUT = ROOT / "data" / "v262_f4b_autocorrelation.json"

# --- reused verbatim from v262_f4_regime_independence.py, NOT tuned ----------
HOURLY_WINDOW_BARS = 90
HOURLY_STRIDE_BARS = 90
HOUR_MS = 3_600_000

CRISIS_DD = 0.30
CRISIS_RET = -0.15
TREND_RET = 0.20

PRIMARY_UNIVERSE = [
    "SOLUSDT", "BNBUSDT", "AVAXUSDT", "XRPUSDT", "SUIUSDT",
    "POLUSDT", "ADAUSDT", "NEARUSDT", "ARBUSDT", "MATICUSDT",
]
SECONDARY_NAMES = ["BTCUSDT", "ETHUSDT", "DOTUSDT", "LINKUSDT"]

LABELS = ("crisis", "trend", "recent")

# --- pre-registered F4b cuts -------------------------------------------------
FAIL_CUT = 0.90
CAVEAT_CUT = 0.60


def path_metrics(closes: list[float]) -> tuple[float, float]:
    """(total return, max drawdown) of a single normalized price path."""
    base = closes[0]
    ret = closes[-1] / base - 1.0
    peak, max_dd = closes[0], 0.0
    for v in closes:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak)
    return ret, max_dd


def load_1h(symbol: str, normalize_units: bool = True) -> list[tuple[int, float]]:
    """(open_ms, close) for every frozen 1h bar of `symbol`, time-ordered.

    UNIT DEFECT (found by this scorer, 2026-07-28): every name's 2025-01 ..
    2026-07 monthly file stores column 0 in MICROSECONDS, not milliseconds --
    19 files / 13,680 bars per name, 177,840 of 665,824 bars = 26.7% of the
    frozen corpus, with a clean edge at 2025-01. Magnitude-detect and rescale
    so the series is genuinely contiguous. This is a data-READ correction, not
    a threshold or classifier change: no pre-declared quantity is touched.

    `normalize_units=False` reproduces the un-normalized reading, which is the
    ms-only era that scripts/v262_f4_regime_independence.py effectively scored
    (its macro_label_at() returned None for every out-of-range us timestamp and
    those windows were silently skipped).
    """
    d = INTRADAY_DIR / symbol / "1h"
    bars: list[tuple[int, float]] = []
    for p in sorted(d.glob("*.json.gz")):
        with gzip.open(p, "rb") as fh:
            blob = json.loads(fh.read())
        for row in blob["bars"]:
            ts = int(row[0])
            if normalize_units and ts >= 1_000_000_000_000_000:  # >= ~2001 in us
                ts //= 1000
            bars.append((ts, float(row[4])))
    bars.sort(key=lambda r: r[0])
    return bars


def label_windows(bars: list[tuple[int, float]], scale: float) -> list[tuple[int, str]]:
    """[(window_start_ms, label)] over the non-overlapping 90-bar tiling."""
    crisis_ret = CRISIS_RET * scale
    trend_ret = TREND_RET * scale
    crisis_dd = CRISIS_DD * scale
    out: list[tuple[int, str]] = []
    for i in range(0, len(bars) - HOURLY_WINDOW_BARS + 1, HOURLY_STRIDE_BARS):
        chunk = bars[i:i + HOURLY_WINDOW_BARS]
        ret, max_dd = path_metrics([c for _, c in chunk])
        if max_dd >= crisis_dd or ret <= crisis_ret:
            lab = "crisis"
        elif ret >= trend_ret:
            lab = "trend"
        else:
            lab = "recent"
        out.append((chunk[0][0], lab))
    return out


def slem(P: list[list[float]]) -> float:
    """Second-largest eigenvalue modulus of a row-stochastic 3x3 matrix.

    Closed-form via the characteristic cubic; a row-stochastic matrix always
    has eigenvalue 1, so the remaining two are the roots of the quadratic
    obtained by deflating the cubic by (lambda - 1). Real-symmetric is NOT
    assumed — complex conjugate pairs are handled by returning the modulus.
    """
    n = len(P)
    # coefficients of det(P - lambda I) for n == 3:
    #   -l^3 + t l^2 - m l + d      with t = trace, m = sum of principal
    #   2x2 minors, d = det
    if n != 3:
        raise ValueError("slem() expects a 3x3 transition matrix")
    a, b, c = P[0]
    d, e, f = P[1]
    g, h, i = P[2]
    t = a + e + i
    m = (a * e - b * d) + (a * i - c * g) + (e * i - f * h)
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    # cubic l^3 - t l^2 + m l - det = 0 has root l = 1 (row-stochastic).
    # Deflate: l^2 + (1 - t) l + det  (synthetic division by (l - 1)).
    p = 1.0 - t
    q = det
    disc = p * p - 4.0 * q
    if disc >= 0.0:
        r = math.sqrt(disc)
        return max(abs((-p + r) / 2.0), abs((-p - r) / 2.0))
    return math.sqrt(q) if q >= 0.0 else 0.0  # |complex pair| = sqrt(product)


def score_symbol(symbol: str, scale: float, normalize_units: bool = True) -> dict | None:
    bars = load_1h(symbol, normalize_units=normalize_units)
    if len(bars) < HOURLY_WINDOW_BARS * 2:
        return None
    windows = label_windows(bars, scale)

    counts = {r: {c: 0 for c in LABELS} for r in LABELS}
    marg = {k: 0 for k in LABELS}
    n_trans = 0
    dropped = 0
    for (t0, l0), (t1, l1) in zip(windows, windows[1:]):
        if t1 - t0 != HOURLY_STRIDE_BARS * HOUR_MS:
            dropped += 1  # a real hole in the frozen corpus — never bridge it
            continue
        counts[l0][l1] += 1
        marg[l0] += 1
        n_trans += 1
    if n_trans == 0:
        return None

    same = sum(counts[k][k] for k in LABELS)
    same_prob = same / n_trans

    # row-stochastic P; an unvisited state is made absorbing-neutral (identity
    # row) so it contributes no spurious mixing. Such rows have zero mass in
    # `marg`, so they cannot affect same_prob.
    P = [
        [counts[r][c] / marg[r] for c in LABELS] if marg[r] > 0
        else [1.0 if c == r else 0.0 for c in LABELS]
        for r in LABELS
    ]
    lam2 = min(1.0, max(0.0, slem(P)))

    # chance baseline: same-state rate a memoryless sampler with these
    # marginals would already produce.
    stat = {k: marg[k] / n_trans for k in LABELS}
    chance = math.fsum(v * v for v in stat.values())

    n_nominal = len(windows)
    return {
        "symbol": symbol,
        "n_windows_nominal": n_nominal,
        "n_transitions": n_trans,
        "dropped_noncontiguous": dropped,
        "lag1_same_state_prob": round(same_prob, 6),
        "chance_same_state_prob": round(chance, 6),
        "excess_over_chance": round(same_prob - chance, 6),
        "lambda2_slem": round(lam2, 6),
        "n_eff_ratio_simple": round(1.0 - lam2, 6),
        "n_eff_ratio_slem": round((1.0 - lam2) / (1.0 + lam2), 6),
        "n_eff_simple": round(n_nominal * (1.0 - lam2), 2),
        "n_eff_slem": round(n_nominal * (1.0 - lam2) / (1.0 + lam2), 2),
        "label_marginals": {k: marg[k] for k in LABELS},
        "transition_counts": {r: dict(counts[r]) for r in LABELS},
        "transition_matrix": {
            r: {c: round(P[ri][ci], 6) for ci, c in enumerate(LABELS)}
            for ri, r in enumerate(LABELS)
        },
    }


def run_arm(symbols: list[str], scale: float, norm: bool = True) -> list[dict]:
    return [r for s in symbols if (r := score_symbol(s, scale, norm)) is not None]


def mean(xs: list[float]) -> float | None:
    return math.fsum(xs) / len(xs) if xs else None


def stdev(xs: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    mu = math.fsum(xs) / len(xs)
    return math.sqrt(math.fsum((x - mu) ** 2 for x in xs) / (len(xs) - 1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    diag_scale = math.sqrt(HOURLY_WINDOW_BARS / 24.0 / 90.0)

    result: dict = {
        "_falsifier": "V262-2 F4b (regime autocorrelation / effective-N)",
        "_source": "data/frozen_series/binance_intraday/{symbol}/1h/*.json.gz",
        "_method": "lag-1 label transition matrix over the F4 90-bar non-overlapping tiling",
        "_thresholds": {
            "crisis_max_dd": CRISIS_DD,
            "crisis_ret": CRISIS_RET,
            "trend_ret": TREND_RET,
            "hourly_window_bars": HOURLY_WINDOW_BARS,
            "hourly_stride_bars": HOURLY_STRIDE_BARS,
            "fail_cut": FAIL_CUT,
            "caveat_cut": CAVEAT_CUT,
        },
        "_diagnostic_scale": round(diag_scale, 6),
    }

    arms = (
        # (name, threshold scale, normalize timestamp units)
        ("primary", 1.0, True),
        ("diagnostic_scaled", diag_scale, True),
        # coverage robustness: the ms-only era that F4 effectively scored
        ("primary_ms_era_only", 1.0, False),
        ("diagnostic_scaled_ms_era_only", diag_scale, False),
    )
    for arm, scale, norm in arms:
        primary = run_arm(PRIMARY_UNIVERSE, scale, norm)
        secondary = run_arm(SECONDARY_NAMES, scale, norm)
        ps = [r["lag1_same_state_prob"] for r in primary]
        result[arm] = {
            "per_name": primary,
            "secondary_per_name": secondary,
            "universe_mean_same_state": round(m, 6) if (m := mean(ps)) is not None else None,
            "universe_std_same_state": round(s, 6) if (s := stdev(ps)) is not None else None,
            "universe_min_same_state": round(min(ps), 6) if ps else None,
            "universe_max_same_state": round(max(ps), 6) if ps else None,
            "universe_mean_chance_same_state": round(
                mean([r["chance_same_state_prob"] for r in primary]), 6),
            "universe_mean_excess_over_chance": round(
                mean([r["excess_over_chance"] for r in primary]), 6),
            "universe_mean_n_eff_ratio_simple": round(
                mean([r["n_eff_ratio_simple"] for r in primary]), 6),
            "universe_mean_n_eff_ratio_slem": round(
                mean([r["n_eff_ratio_slem"] for r in primary]), 6),
            "n_names": len(primary),
        }

    mp = result["primary"]["universe_mean_same_state"]
    if mp is None:
        verdict = "ERROR (no names scored)"
    elif mp > FAIL_CUT:
        verdict = "FAIL (autocorrelation high; effective N ~1x, not 24x)"
    elif mp > CAVEAT_CUT:
        verdict = "CAVEATED PASS (effective N grows sub-linearly)"
    else:
        verdict = "CLEAN PASS (effective N genuinely grows)"
    result["verdict"] = {
        "arm": "primary (pre-declared thresholds, unscaled)",
        "universe_mean_lag1_same_state_prob": mp,
        "cuts": {"fail_above": FAIL_CUT, "caveat_above": CAVEAT_CUT},
        "f4b": verdict,
    }

    out = Path(args.out)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    for arm, _s, _n in arms:
        a = result[arm]
        print(f"\n--- arm: {arm} ---")
        print(f"{'symbol':<10} {'Nnom':>5} {'trans':>6} {'same':>7} {'chance':>7} "
              f"{'excess':>7} {'lam2':>7} {'Neff/N':>7} {'Neff':>8}  drop")
        for r in a["per_name"] + a["secondary_per_name"]:
            tag = "" if r in a["per_name"] else "  (excl)"
            print(f"{r['symbol']:<10} {r['n_windows_nominal']:>5} {r['n_transitions']:>6} "
                  f"{r['lag1_same_state_prob']:>7.3f} {r['chance_same_state_prob']:>7.3f} "
                  f"{r['excess_over_chance']:>7.3f} {r['lambda2_slem']:>7.3f} "
                  f"{r['n_eff_ratio_simple']:>7.3f} {r['n_eff_simple']:>8.1f} "
                  f"{r['dropped_noncontiguous']:>4}{tag}")
        print(f"universe-mean lag-1 same-state = {a['universe_mean_same_state']} "
              f"(sd {a['universe_std_same_state']}, "
              f"min {a['universe_min_same_state']}, max {a['universe_max_same_state']})")
        print(f"  chance baseline mean = {a['universe_mean_chance_same_state']}, "
              f"excess = {a['universe_mean_excess_over_chance']}")
        print(f"  mean N_eff/N: simple {a['universe_mean_n_eff_ratio_simple']}, "
              f"slem {a['universe_mean_n_eff_ratio_slem']}")

    print(f"\nF4b VERDICT: {verdict}")
    print(f"  universe-mean lag-1 same-state = {mp}  vs cuts "
          f"(FAIL >{FAIL_CUT}, CAVEAT >{CAVEAT_CUT})")
    print(f"  written: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
