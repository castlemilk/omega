#!/usr/bin/env python3
"""V258 Phase-0 divergence probe (Track E specialist ensemble).

Replays a stratified sample of V241's frozen whole-basket-review decisions
through the V258 ``SpecialistEnsemble`` and measures how much the ensemble's
per-name keep/drop decision diverges from V241's. Pre-registered falsifier
(see ``training_log/V258.md``): if divergence < 5% OR ensemble intervention
rate < 20%, Track E is REFUTED at Phase 0 (no grid).

The specialist/meta prompts are NEW (different hashes than V241's whole-basket
prompts), so this run fills a SEPARATE V258 cache namespace on gamma — V241's
committed ``data/frozen_llm_cache/`` is never touched.

Usage (live agy calls, subscription-side $0, ~15s/call):
    python3 scripts/v258_phase0_divergence.py --sample 24 --out <dir>/v258
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from omega.nodes.victoria.reasoning_layer import (  # noqa: E402
    ReasoningLayer,
    SpecialistEnsemble,
)

V241_CACHE = REPO / "data" / "frozen_llm_cache" / "gemini-3.1-pro-low"


def load_v241_decisions() -> list[dict]:
    """Return [{phash, cycle_ctx, candidates, v241_keep, v241_drop, v241_scale}]."""
    out = []
    for f in sorted(glob.glob(str(V241_CACHE / "*.json"))):
        if f.endswith("MANIFEST.json"):
            continue
        e = json.loads(Path(f).read_text())
        prompt = json.loads(e["prompt"])
        cands = prompt.get("candidates", [])
        if not cands:
            continue
        resp = e["response"]
        out.append(
            {
                "phash": Path(f).stem,
                "cycle_ctx": prompt["cycle_ctx"],
                "candidates": cands,
                "symbols": [str(c.get("symbol")) for c in cands],
                "v241_drop": set(resp.get("drop", [])),
                "v241_scale": {k: float(v) for k, v in (resp.get("size_scale") or {}).items()},
            }
        )
    return out


def stratified_sample(decisions: list[dict], total: int) -> list[dict]:
    """Deterministic stratified pick by regime (sorted by phash, evenly spaced)."""
    by_regime: dict[str, list[dict]] = defaultdict(list)
    for d in decisions:
        by_regime[str(d["cycle_ctx"].get("regime"))].append(d)
    # Allocate proportionally to regime population, min 4 each where available.
    n_all = sum(len(v) for v in by_regime.values())
    picks: list[dict] = []
    for regime, items in sorted(by_regime.items()):
        items.sort(key=lambda d: d["phash"])
        want = max(4, round(total * len(items) / n_all)) if items else 0
        want = min(want, len(items))
        if want <= 0:
            continue
        step = max(1, len(items) // want)
        picks.extend(items[:: step][:want])
    return picks


def effective_weight(symbol: str, dropped: set[str], scale: dict[str, float]) -> float:
    """0 if dropped, else size_scale (default 1.0) — the position's effective weight."""
    if symbol in dropped:
        return 0.0
    return float(scale.get(symbol, 1.0))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=24, help="approx cycles to probe")
    ap.add_argument("--out", default=os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", "data") + "/v258")
    ap.add_argument("--cache-root", default=None, help="V258 specialist cache root (default <out>/frozen_llm_cache)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_root = Path(args.cache_root) if args.cache_root else (out_dir / "frozen_llm_cache")

    decisions = load_v241_decisions()
    sample = stratified_sample(decisions, args.sample)
    print(f"[v258-phase0] {len(decisions)} V241 decisions; probing {len(sample)} cycles", flush=True)

    ensemble = SpecialistEnsemble(cache_root=cache_root)

    slot_total = 0
    slot_decision_divergent = 0  # keep/drop differs
    weight_abs_diff_sum = 0.0
    ens_intervened_slots = 0  # ensemble dropped or scaled<1
    v241_intervened_slots = 0
    per_regime = defaultdict(lambda: {"slots": 0, "divergent": 0, "ens_interv": 0})
    per_cycle_log = []
    t0 = time.perf_counter()

    for i, d in enumerate(sample):
        ctx, cands, syms = d["cycle_ctx"], d["candidates"], d["symbols"]
        regime = str(ctx.get("regime"))
        try:
            _, review, _ = ensemble.review_basket(ctx, cands)
        except Exception as exc:  # noqa: BLE001
            print(f"[v258-phase0] cycle {ctx.get('cycle')} FAILED: {exc}", flush=True)
            continue
        ens_drop = set(review.drop)
        ens_scale = review.size_scale
        cyc_div = 0
        for s in syms:
            slot_total += 1
            per_regime[regime]["slots"] += 1
            v241_dropped = s in d["v241_drop"]
            ens_dropped = s in ens_drop
            if v241_dropped != ens_dropped:
                slot_decision_divergent += 1
                per_regime[regime]["divergent"] += 1
                cyc_div += 1
            w241 = effective_weight(s, d["v241_drop"], d["v241_scale"])
            wens = effective_weight(s, ens_drop, ens_scale)
            weight_abs_diff_sum += abs(w241 - wens)
            if wens < 1.0:
                ens_intervened_slots += 1
                per_regime[regime]["ens_interv"] += 1
            if w241 < 1.0:
                v241_intervened_slots += 1
        per_cycle_log.append(
            {
                "cycle": ctx.get("cycle"),
                "regime": regime,
                "n": len(syms),
                "v241_drop": sorted(d["v241_drop"]),
                "ens_drop": sorted(ens_drop),
                "decision_divergent_slots": cyc_div,
            }
        )
        if (i + 1) % 5 == 0:
            print(f"[v258-phase0] {i + 1}/{len(sample)} cycles, "
                  f"{slot_decision_divergent}/{slot_total} divergent slots", flush=True)

    div_frac = slot_decision_divergent / slot_total if slot_total else 0.0
    ens_interv = ens_intervened_slots / slot_total if slot_total else 0.0
    v241_interv = v241_intervened_slots / slot_total if slot_total else 0.0
    weight_div = weight_abs_diff_sum / slot_total if slot_total else 0.0

    result = {
        "n_cycles_probed": len(per_cycle_log),
        "n_slots": slot_total,
        "per_name_decision_divergence": round(div_frac, 4),
        "effective_weight_mean_abs_diff": round(weight_div, 4),
        "ensemble_intervention_rate": round(ens_interv, 4),
        "v241_intervention_rate": round(v241_interv, 4),
        "per_regime": {
            r: {
                "slots": v["slots"],
                "decision_divergence": round(v["divergent"] / v["slots"], 4) if v["slots"] else None,
                "ens_intervention": round(v["ens_interv"] / v["slots"], 4) if v["slots"] else None,
            }
            for r, v in sorted(per_regime.items())
        },
        "falsifier": {
            "divergence_lt_5pct": div_frac < 0.05,
            "intervention_lt_20pct": ens_interv < 0.20,
            "REFUTED_at_phase0": (div_frac < 0.05) or (ens_interv < 0.20),
        },
        "wall_clock_s": round(time.perf_counter() - t0, 1),
        "cache_root": str(cache_root),
    }
    (out_dir / "phase0_divergence.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (out_dir / "phase0_per_cycle.json").write_text(json.dumps(per_cycle_log, indent=1, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
