#!/usr/bin/env python3
"""V247 Phase 0 — ruler diagnostic.

Quantifies the resolution of the walk-forward instrument (32-window
manifest) per regime, on the baseline (flag-OFF) arm, and calibrates
the paired-Delta noise floor from every completed ON-vs-OFF grid.

Inputs (read-only):
  $OMEGA_AUDIT_OUTPUT_DIR/{v241,v243a_wf,v245,v246}/distribution.json
    - each has per-window rows for config 'universe_selective' (OFF
      baseline) and one ON config.

Outputs:
  data/v247_ruler.json           (machine-readable)
  stdout                         (markdown tables for V247_RULER.md)

Deterministic: bootstrap seeded with 42. No wall-clock, no network.
"""

from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys

AUDIT = os.environ.get(
    "OMEGA_AUDIT_OUTPUT_DIR", "/Volumes/gamma-systems-2/omega-victoria-data"
)

GRIDS = {
    "v241_reasoning": ("v241", "reasoning_on"),
    "v243a_blacklist_ext": ("v243a_wf", "universe_selective_ext"),
    "v245_gdelt": ("v245", "gdelt_solo"),
    "v246_exit_adapt": ("v246", "exit_adapt"),
}
OFF = "universe_selective"
REGIMES = ("recent", "trend", "crisis", "pooled")

Z_ALPHA = 1.959964  # two-sided alpha=0.05
Z_POWER = 0.841621  # 80% power
BOOT_N = 20000


def load_rows(subdir: str) -> list[dict]:
    path = os.path.join(AUDIT, subdir, "distribution.json")
    with open(path) as f:
        return json.load(f)["rows"]


def pctl(sorted_xs: list[float], q: float) -> float:
    """Linear-interpolated percentile (matches numpy default)."""
    n = len(sorted_xs)
    if n == 1:
        return sorted_xs[0]
    pos = q / 100.0 * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


def dist_stats(xs: list[float]) -> dict:
    n = len(xs)
    s = sorted(xs)
    mean = math.fsum(xs) / n
    sd = statistics.stdev(xs) if n > 1 else 0.0
    se = sd / math.sqrt(n)
    return {
        "n": n,
        "mean": mean,
        "sd": sd,
        "se": se,
        "two_se": 2 * se,
        "p10": pctl(s, 10),
        "p25": pctl(s, 25),
        "p75": pctl(s, 75),
        "p90": pctl(s, 90),
        "min": s[0],
        "max": s[-1],
    }


def bootstrap_ci(xs: list[float], rng: random.Random) -> tuple[float, float]:
    n = len(xs)
    means = []
    for _ in range(BOOT_N):
        means.append(math.fsum(rng.choice(xs) for _ in range(n)) / n)
    means.sort()
    return pctl(means, 2.5), pctl(means, 97.5)


def mde(sd: float, n: int) -> float:
    """Minimum detectable mean effect, two-sided alpha=0.05, 80% power
    (normal approximation; slightly optimistic at n<15)."""
    return (Z_ALPHA + Z_POWER) * sd / math.sqrt(n)


def min_n(sd: float, effect: float) -> int:
    """Windows needed to detect `effect` at alpha=0.05 / 80% power.
    Normal approx + 2 (small-sample t correction, Snedecor-Cochran)."""
    return math.ceil(((Z_ALPHA + Z_POWER) * sd / effect) ** 2) + 2


def by_regime(rows: list[dict], config: str) -> dict[str, dict[str, float]]:
    """window_id -> pnl, keyed per regime (+ pooled)."""
    out: dict[str, dict[str, float]] = {r: {} for r in REGIMES}
    for r in rows:
        if r["config"] != config:
            continue
        out[r["regime"]][r["window"]] = r["pnl"]
        out["pooled"][r["window"]] = r["pnl"]
    return out


def main() -> None:
    rng = random.Random(42)

    # --- OFF-arm levels (identical across grids; take v246's, verify) ---
    v246_rows = load_rows("v246/")
    off = by_regime(v246_rows, OFF)
    for name, (sub, _on) in GRIDS.items():
        other = by_regime(load_rows(sub), OFF)
        for reg in REGIMES:
            common = set(off[reg]) & set(other[reg])
            mism = [w for w in common if abs(off[reg][w] - other[reg][w]) > 0.005]
            if mism:
                print(f"WARN: OFF-arm mismatch vs {name} in {reg}: {mism}", file=sys.stderr)

    result: dict = {"off_levels": {}, "deltas": {}, "mde_table": {}, "min_n_table": {}}

    print("## OFF-arm (baseline) level distribution — window PnL, USD\n")
    print("| regime | n | mean | sd | SE | 2·SE | p10 | p25 | p75 | p90 | boot 95% CI (mean) |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for reg in REGIMES:
        xs = list(off[reg].values())
        st = dist_stats(xs)
        lo, hi = bootstrap_ci(xs, rng)
        st["boot_ci_mean"] = [lo, hi]
        result["off_levels"][reg] = st
        print(
            f"| {reg} | {st['n']} | {st['mean']:+,.0f} | {st['sd']:,.0f} | {st['se']:,.0f} "
            f"| {st['two_se']:,.0f} | {st['p10']:+,.0f} | {st['p25']:+,.0f} | {st['p75']:+,.0f} "
            f"| {st['p90']:+,.0f} | [{lo:+,.0f}, {hi:+,.0f}] |"
        )

    # --- Paired Delta distributions per intervention ---
    print("\n## Paired Δ (ON − OFF per window) — the actual verdict instrument\n")
    print("| grid | regime | n | Δ mean | Δ sd | SE | 2·SE | Δ p25 | boot 95% CI (Δ mean) |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---|")
    delta_sds: dict[str, list[float]] = {r: [] for r in REGIMES}
    for name, (sub, on_cfg) in GRIDS.items():
        rows = load_rows(sub)
        offm = by_regime(rows, OFF)
        onm = by_regime(rows, on_cfg)
        result["deltas"][name] = {}
        for reg in REGIMES:
            common = sorted(set(offm[reg]) & set(onm[reg]))
            ds = [onm[reg][w] - offm[reg][w] for w in common]
            st = dist_stats(ds)
            lo, hi = bootstrap_ci(ds, rng)
            st["boot_ci_mean"] = [lo, hi]
            result["deltas"][name][reg] = st
            delta_sds[reg].append(st["sd"])
            print(
                f"| {name} | {reg} | {st['n']} | {st['mean']:+,.0f} | {st['sd']:,.0f} "
                f"| {st['se']:,.0f} | {st['two_se']:,.0f} | {st['p25']:+,.0f} "
                f"| [{lo:+,.0f}, {hi:+,.0f}] |"
            )

    # --- MDE + min-N using the median Δ sd across the 4 interventions ---
    print("\n## MDE at 80% power / α=0.05 (median Δ-sd across the 4 grids)\n")
    print("| regime | n now | median Δ sd | range Δ sd | MDE now | min-N for $100 | $250 | $500 | $1000 |")
    print("|---|---:|---:|---|---:|---:|---:|---:|---:|")
    n_now = {"recent": 10, "trend": 10, "crisis": 12, "pooled": 32}
    for reg in REGIMES:
        sds = delta_sds[reg]
        med = statistics.median(sds)
        result["mde_table"][reg] = {
            "n_now": n_now[reg],
            "median_delta_sd": med,
            "delta_sd_range": [min(sds), max(sds)],
            "mde_now": mde(med, n_now[reg]),
        }
        row = result["min_n_table"][reg] = {}
        for eff in (100, 250, 500, 1000):
            row[f"${eff}"] = min_n(med, eff)
        print(
            f"| {reg} | {n_now[reg]} | {med:,.0f} | [{min(sds):,.0f}, {max(sds):,.0f}] "
            f"| {mde(med, n_now[reg]):,.0f} | {row['$100']} | {row['$250']} | {row['$500']} "
            f"| {row['$1000']} |"
        )

    out_path = "data/v247_ruler.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
