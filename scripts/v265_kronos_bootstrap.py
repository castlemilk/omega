#!/usr/bin/env python3
"""V265 — paired bootstrap CI95 for the three pre-registered F5 gates.

Resamples windows WITHIN cell with replacement (10k draws), using the same
resampled index set for the Kronos and naive arms so the arms stay paired, then
re-pools with V264's mean-across-cells convention. Reports CI95 for each gate
statistic plus P(gate passes) and the paired Kronos-minus-naive Spearman delta.

Usage::

    python3 scripts/v265_kronos_bootstrap.py --tag finetuned
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]

import importlib.util

_spec = importlib.util.spec_from_file_location("v265_scorer", REPO / "scripts" / "v265_kronos_vol_scorer.py")
_scorer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_scorer)

spearman = _scorer.spearman
rmse = _scorer.rmse
kruskal_wallis = _scorer.kruskal_wallis
quintile_groups = _scorer.quintile_groups
_rankdata = _scorer._rankdata
F5_VOL_BAR = _scorer.F5_VOL_BAR
F5_CORR_BAR = _scorer.F5_CORR_BAR
N_QUINTILES = _scorer.N_QUINTILES


def ci95(x: np.ndarray) -> list[float]:
    return [round(float(np.percentile(x, 2.5)), 4), round(float(np.percentile(x, 97.5)), 4)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="finetuned")
    ap.add_argument("--draws", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    root = Path(os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", str(REPO / "data"))) / "v265" / "vol" / args.tag
    summary = json.loads((root / "summary.json").read_text())
    cell_names = [c["cell"] for c in summary["cells"]]

    data = {}
    for name in cell_names:
        rows = json.loads((root / f"windows_{name}.json").read_text())
        data[name] = (
            np.array([r["kronos_vol"] for r in rows], dtype=float),
            np.array([r["naive_vol"] for r in rows], dtype=float),
            np.array([r["realized_vol"] for r in rows], dtype=float),
        )

    rng = np.random.default_rng(args.seed)
    ratios, rhos, rhos_naive, kw_Hs = [], [], [], []

    for _ in range(args.draws):
        cell_ratio, cell_rho, cell_rho_n = [], [], []
        grp: list[list[float]] = [[] for _ in range(N_QUINTILES)]
        for name in cell_names:
            fk, fn, y = data[name]
            idx = rng.integers(0, len(y), len(y))  # paired: one index set per cell
            fk_b, fn_b, y_b = fk[idx], fn[idx], y[idx]
            rn = rmse(fn_b, y_b)
            cell_ratio.append(rmse(fk_b, y_b) / rn if rn > 0 else np.nan)
            cell_rho.append(spearman(fk_b, y_b))
            cell_rho_n.append(spearman(fn_b, y_b))
            yn = _rankdata(y_b) / (len(y_b) + 1.0)
            for i, g in enumerate(quintile_groups(fk_b, yn)):
                grp[i].extend(g.tolist())
        ratios.append(np.mean(cell_ratio))
        rhos.append(np.mean(cell_rho))
        rhos_naive.append(np.mean(cell_rho_n))
        kw_Hs.append(kruskal_wallis([np.array(g) for g in grp])[0])

    ratios = np.array(ratios)
    rhos = np.array(rhos)
    rhos_naive = np.array(rhos_naive)
    kw_Hs = np.array(kw_Hs)
    delta = rhos - rhos_naive

    out = {
        "tag": args.tag,
        "draws": args.draws,
        "seed": args.seed,
        "point": {
            "pooled_rmse_ratio": summary["pooled_rmse_ratio"],
            "pooled_spearman": summary["pooled_spearman"],
            "pooled_spearman_naive": summary["pooled_spearman_naive"],
            "pooled_kw_H": summary["pooled_kw_H"],
            "pooled_kw_p": summary["pooled_kw_p"],
        },
        "ci95": {
            "pooled_rmse_ratio": ci95(ratios),
            "pooled_spearman": ci95(rhos),
            "pooled_spearman_naive": ci95(rhos_naive),
            "delta_spearman_kronos_minus_naive": ci95(delta),
            "pooled_kw_H": ci95(kw_Hs),
        },
        "p_gate_passes": {
            "f5_vol": round(float((ratios < F5_VOL_BAR).mean()), 4),
            "f5_corr": round(float((rhos > F5_CORR_BAR).mean()), 4),
        },
        "p_delta_rho_gt_0": round(float((delta > 0).mean()), 4),
    }
    (root / "bootstrap.json").write_text(json.dumps(out, indent=2))

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
