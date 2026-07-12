#!/usr/bin/env python3
"""V241 phase-0 — reasoning-layer intervention report.

Reads one or more OMEGA_REASONING_TRACE JSONL files (one line per
review_basket call) and reports, per window and pooled:

  calls, candidates in/out, drop count, scale-down count,
  intervention_rate (fraction of calls with >=1 drop or scale-down),
  cache hit rate, latency p50/p95.

The pre-registered phase-0 falsifier: intervention_rate < 5% pooled AND in
every window => the layer is inert (or a scaffolding/prompt bug) — V241 dies
before the cache-fill. The complement (>95% of candidates dropped) is flagged
as a veto-everything scaffolding bug, per V241.md.

Usage:
    python3 scripts/v241_intervention_report.py trace1.jsonl [trace2.jsonl ...]
    python3 scripts/v241_intervention_report.py --glob "$AUDIT/v241_cache_fill/*_reasoning_trace.jsonl"
"""

from __future__ import annotations

import argparse
import glob as globmod
import json
import statistics
import sys
from collections import defaultdict


def pctl(vals: list[float], q: float) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    i = min(len(s) - 1, max(0, round(q * (len(s) - 1))))
    return s[i]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("traces", nargs="*")
    ap.add_argument("--glob", default="")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    paths = list(args.traces) + (sorted(globmod.glob(args.glob)) if args.glob else [])
    if not paths:
        print("no trace files given", file=sys.stderr)
        return 2

    rows: list[dict] = []
    for p in paths:
        with open(p) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    if not rows:
        print("trace files empty — the layer was never called (INERT/not wired)")
        return 1

    by_window: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_window[r.get("window") or "?"].append(r)

    def summarize(rs: list[dict]) -> dict:
        n = len(rs)
        cand_in = sum(r["candidates_in"] for r in rs)
        cand_out = sum(r["candidates_out"] for r in rs)
        drops = sum(len(r["drops"]) for r in rs)
        scales = sum(len(r["scaled_down"]) for r in rs)
        interv = sum(1 for r in rs if r["intervened"])
        lat = [r["latency_ms"] for r in rs]
        return {
            "calls": n,
            "candidates_in": cand_in,
            "candidates_out": cand_out,
            "drops": drops,
            "scale_downs": scales,
            "intervention_rate": interv / n if n else 0.0,
            "drop_fraction": drops / cand_in if cand_in else 0.0,
            "cache_hit_rate": sum(1 for r in rs if r["cache_hit"]) / n if n else 0.0,
            "latency_p50_ms": pctl(lat, 0.50),
            "latency_p95_ms": pctl(lat, 0.95),
            "mean_confidence": statistics.mean(r["confidence"] for r in rs) if rs else 0.0,
        }

    report = {
        "windows": {w: summarize(rs) for w, rs in sorted(by_window.items())},
        "pooled": summarize(rows),
    }

    pooled = report["pooled"]
    hdr = f"{'window':<22} {'calls':>5} {'in':>4} {'out':>4} {'drop':>4} {'scl':>4} {'int%':>6} {'hit%':>6} {'p50ms':>8}"
    print(hdr)
    print("-" * len(hdr))
    for w, s in report["windows"].items():
        print(
            f"{w:<22} {s['calls']:>5} {s['candidates_in']:>4} {s['candidates_out']:>4} "
            f"{s['drops']:>4} {s['scale_downs']:>4} {s['intervention_rate'] * 100:>5.1f}% "
            f"{s['cache_hit_rate'] * 100:>5.1f}% {s['latency_p50_ms']:>8.1f}"
        )
    print("-" * len(hdr))
    s = pooled
    print(
        f"{'POOLED':<22} {s['calls']:>5} {s['candidates_in']:>4} {s['candidates_out']:>4} "
        f"{s['drops']:>4} {s['scale_downs']:>4} {s['intervention_rate'] * 100:>5.1f}% "
        f"{s['cache_hit_rate'] * 100:>5.1f}% {s['latency_p50_ms']:>8.1f}"
    )

    verdict = "ACTIVE"
    if pooled["intervention_rate"] < 0.05:
        verdict = "INERT (phase-0 falsifier fires: intervention_rate < 5%)"
    elif pooled["drop_fraction"] > 0.95:
        verdict = "VETO-EVERYTHING (scaffolding/prompt bug per V241.md phase-0)"
    print(f"PHASE0 VERDICT: {verdict}")
    report["phase0_verdict"] = verdict

    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump(report, fh, indent=1, sort_keys=True)
    return 0 if verdict == "ACTIVE" else 1


if __name__ == "__main__":
    sys.exit(main())
