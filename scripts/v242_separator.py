#!/usr/bin/env python3
"""V242 separator analysis — does whale_flow's crisis lift separate by regime tag?

Pure analysis on committed V240 artifacts. NO grid runs, NO cache, NO network.

Inputs (both committed on main):
  - Per-window whale_flow solo-feed Δ (ON vs OFF) from
    omega/nodes/victoria/training_log/V240_SIGNAL_FORENSICS.md
    (Δ = whale_flow-ON minus OFF, vs the V238 legacy 4-name baseline,
     PRE-V240.A selective-universe adoption — see caveat in that doc).
  - Regime tags per window from data/walk_forward_manifest.json.

Outputs a JSON report to stdout answering:
  1. Distribution of whale_flow Δ within crisis vs trend vs recent
     (mean, p25, p50, p75, min, max) + per-window scatter.
  2. Does the crisis lift come from ALL 12 crisis windows or a subset?
  3. Mann-Whitney U: crisis-window Δ vs non-crisis (trend+recent) Δ —
     does the regime tag separate whale_flow's benefit?
  4. Sanity check on the crisis-only gate: crisis-only-lift and pooled Δ
     against the pre-registered bars (crisis-lift > +$1,500 AND pooled > +$800).
"""
import json
import statistics as st
from pathlib import Path

import numpy as np
from scipy.stats import mannwhitneyu

REPO = Path(__file__).resolve().parents[1]

# whale_flow per-window Δ (ON−OFF), verbatim from V240_SIGNAL_FORENSICS.md.
WHALE_FLOW_DELTA = {
    "snap_wf_20200101": 1535.5, "snap_wf_20200331": 213.8, "snap_wf_20200629": 350.59,
    "snap_wf_20200813": -184.73, "snap_wf_20200927": 164.18, "snap_wf_20201226": -22270.58,
    "snap_wf_20210326": 10750.21, "snap_wf_20210624": -119.42, "snap_wf_20210922": 135.58,
    "snap_wf_20211221": 5767.93, "snap_wf_20220321": -4005.44, "snap_wf_20220619": -1756.95,
    "snap_wf_20220917": 5024.73, "snap_wf_20221216": -6110.55, "snap_wf_20230130": 2185.38,
    "snap_wf_20230316": -2397.93, "snap_wf_20230430": -209.09, "snap_wf_20230614": 1239.14,
    "snap_wf_20230729": -3032.3, "snap_wf_20230912": 2014.35, "snap_wf_20231211": 4666.25,
    "snap_wf_20240310": 11546.8, "snap_wf_20240608": 4265.81, "snap_wf_20240723": 6929.66,
    "snap_wf_20240906": -1502.74, "snap_wf_20241205": -7346.36, "snap_wf_20250305": -2901.17,
    "snap_wf_20250603": 375.04, "snap_wf_20250718": -2076.41, "snap_wf_20250901": -3663.82,
    "snap_wf_20251130": -708.28, "snap_wf_20260228": -2801.5,
}

# Pre-registered sanity bars (from the V242 task brief).
CRISIS_LIFT_BAR = 1500.0
POOLED_BAR = 800.0


def pct(xs, q):
    return float(np.percentile(xs, q))


def summarize(xs):
    xs = list(xs)
    return {
        "n": len(xs),
        "sum": round(sum(xs), 2),
        "mean": round(st.mean(xs), 2),
        "p25": round(pct(xs, 25), 2),
        "p50": round(pct(xs, 50), 2),
        "p75": round(pct(xs, 75), 2),
        "min": round(min(xs), 2),
        "max": round(max(xs), 2),
        "n_positive": sum(1 for x in xs if x > 0),
        "n_negative": sum(1 for x in xs if x < 0),
    }


def main():
    manifest = json.loads((REPO / "data/walk_forward_manifest.json").read_text())
    tags = {w["id"]: w["regime"] for w in manifest["windows"]}

    # Sanity: every forensics window must have a regime tag.
    missing = [w for w in WHALE_FLOW_DELTA if w not in tags]
    assert not missing, f"windows missing regime tag: {missing}"
    assert len(WHALE_FLOW_DELTA) == 32, f"expected 32 windows, got {len(WHALE_FLOW_DELTA)}"

    buckets = {"crisis": [], "trend": [], "recent": []}
    scatter = {"crisis": {}, "trend": {}, "recent": {}}
    for wid, d in WHALE_FLOW_DELTA.items():
        r = tags[wid]
        buckets[r].append(d)
        scatter[r][wid] = d

    report = {
        "_source": "V240_SIGNAL_FORENSICS.md whale_flow solo-feed Δ (ON−OFF)",
        "_baseline_caveat": (
            "Δ measured vs V238 legacy 4-name 'main' baseline, PRE-V240.A "
            "selective-universe adoption. The V240 standing baseline is a "
            "DIFFERENT universe (blacklist BTC/DOT/LINK); these Δ are an "
            "ESTIMATE of the crisis-gate lift, not a confirm-grid measurement."
        ),
        "distributions": {r: summarize(v) for r, v in buckets.items()},
        "scatter": scatter,
    }

    # --- Q2: all crisis windows or a subset? ---
    crisis = buckets["crisis"]
    crisis_sorted = sorted(scatter["crisis"].items(), key=lambda kv: kv[1])
    # Top contributor share of the positive mass.
    pos = [x for x in crisis if x > 0]
    top1 = max(crisis)
    top2 = sum(sorted(crisis, reverse=True)[:2])
    report["crisis_subset_analysis"] = {
        "n_windows": len(crisis),
        "n_positive": len(pos),
        "n_negative": sum(1 for x in crisis if x < 0),
        "sum_all": round(sum(crisis), 2),
        "sum_positive_only": round(sum(pos), 2),
        "largest_single_window": {"id": crisis_sorted[-1][0], "delta": crisis_sorted[-1][1]},
        "top1_share_of_positive_mass": round(top1 / sum(pos), 3) if pos else None,
        "top2_share_of_positive_mass": round(top2 / sum(pos), 3) if pos else None,
        "windows_sorted_ascending": crisis_sorted,
        "read": (
            "If top1/top2 share of positive mass is near 1.0, the crisis lift "
            "is carried by 1-2 windows (fragile); if spread across many, it is robust."
        ),
    }

    # --- Q3: Mann-Whitney U — crisis vs non-crisis Δ ---
    noncrisis = buckets["trend"] + buckets["recent"]
    u_stat, p_two = mannwhitneyu(crisis, noncrisis, alternative="two-sided")
    _, p_greater = mannwhitneyu(crisis, noncrisis, alternative="greater")
    report["mann_whitney"] = {
        "group_a": "crisis (n=%d)" % len(crisis),
        "group_b": "non-crisis trend+recent (n=%d)" % len(noncrisis),
        "crisis_median": round(st.median(crisis), 2),
        "noncrisis_median": round(st.median(noncrisis), 2),
        "U": float(u_stat),
        "p_two_sided": round(float(p_two), 4),
        "p_greater_crisis_gt_noncrisis": round(float(p_greater), 4),
        "separates_at_0.05": bool(p_greater < 0.05),
        "read": (
            "H1: crisis-window whale_flow Δ stochastically exceeds non-crisis. "
            "p_greater < 0.05 ⇒ the regime tag meaningfully separates the benefit."
        ),
    }

    # --- Q4: crisis-only gate sanity check ---
    # Gate ON in crisis only ⇒ only crisis windows change by their whale_flow Δ;
    # trend/recent unchanged (whale_flow OFF = baseline). So:
    #   crisis-only lift  = sum/mean of crisis Δ
    #   pooled-gate Δ     = same crisis Δ mass spread over all 32 windows
    crisis_lift_sum = sum(crisis)
    crisis_lift_mean = st.mean(crisis)
    pooled_gate_sum = crisis_lift_sum  # trend+recent contribute 0 Δ
    pooled_gate_mean_32 = pooled_gate_sum / 32.0

    report["gate_sanity_check"] = {
        "interpretation": (
            "Crisis-gated whale_flow: ON in the 12 crisis windows, OFF (=baseline) "
            "in trend+recent. Only crisis windows move; trend/recent Δ = 0 by construction."
        ),
        "crisis_only_lift_sum": round(crisis_lift_sum, 2),
        "crisis_only_lift_mean_per_window": round(crisis_lift_mean, 2),
        "pooled_gate_delta_sum": round(pooled_gate_sum, 2),
        "pooled_gate_delta_mean_over_32": round(pooled_gate_mean_32, 2),
        "bars": {
            "crisis_lift_bar": CRISIS_LIFT_BAR,
            "pooled_bar": POOLED_BAR,
        },
        "verdict_per_window_mean": {
            "crisis_lift_clears": bool(crisis_lift_mean > CRISIS_LIFT_BAR),
            "pooled_clears": bool(pooled_gate_mean_32 > POOLED_BAR),
            "both_clear": bool(
                crisis_lift_mean > CRISIS_LIFT_BAR and pooled_gate_mean_32 > POOLED_BAR
            ),
        },
        "note": (
            "Bars read as per-window mean-$. crisis_only_lift_mean_per_window vs "
            "$1,500 bar; pooled_gate_delta_mean_over_32 vs $800 bar. Sum figures "
            "reported for reference."
        ),
    }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
