#!/usr/bin/env python3
"""V263 Phase 1 — drift-robust roll-up of the Kronos smoke cells.

Raw directional accuracy is confounded by drift: an asset that rose in 56% of
sampled windows hands 56% "accuracy" to any model that is merely biased long.
This script recomputes each cell's edge with statistics that are immune to that:

  * ``spearman``     — rank correlation of forecast return vs realized return
                       (the pre-registered F4 statistic).
  * ``balanced_acc`` — mean of up-recall and down-recall.
  * ``mcc``          — Matthews correlation on the 2x2 sign confusion matrix.

It also reports the realized and forecast up-rates so drift bias is visible, and
applies a Bonferroni correction across all cells (this is a multi-cell sweep, so
an uncorrected p-value is not a result).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

AUDIT = Path("/Volumes/gamma-systems-2/omega-victoria-data")


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    def rank(x):
        order = np.argsort(x, kind="stable")
        r = np.empty(len(x), dtype=float)
        r[order] = np.arange(len(x), dtype=float)
        # average ties
        _, inv, counts = np.unique(x, return_inverse=True, return_counts=True)
        sums = np.zeros(len(counts))
        np.add.at(sums, inv, r)
        return (sums / counts)[inv]

    ra, rb = rank(a), rank(b)
    ra -= ra.mean()
    rb -= rb.mean()
    denom = math.sqrt(float((ra**2).sum()) * float((rb**2).sum()))
    return float((ra * rb).sum() / denom) if denom > 0 else 0.0


def two_sided_p_from_z(z: float) -> float:
    return float(math.erfc(abs(z) / math.sqrt(2.0)))


def analyze(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    rows = payload["windows"]
    if not rows:
        return None
    cfg = payload["config"]
    f = np.array([r["forecast_ret"] for r in rows], dtype=float)
    y = np.array([r["realized_ret"] for r in rows], dtype=float)
    n = len(rows)

    rho = spearman(f, y)
    # Fisher z for Spearman
    z = rho * math.sqrt(n - 1)
    p_rho = two_sided_p_from_z(z)

    fs, ys = np.sign(f), np.sign(y)
    tp = int(((fs > 0) & (ys > 0)).sum())
    tn = int(((fs < 0) & (ys < 0)).sum())
    fp = int(((fs > 0) & (ys < 0)).sum())
    fn = int(((fs < 0) & (ys > 0)).sum())
    up_recall = tp / max(tp + fn, 1)
    dn_recall = tn / max(tn + fp, 1)
    denom = math.sqrt(float((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)))
    mcc = ((tp * tn - fp * fn) / denom) if denom > 0 else 0.0

    return {
        "cell": f"{payload['corpus']['symbol']}_h{cfg['pred_len']}",
        "symbol": payload["corpus"]["symbol"],
        "horizon": cfg["pred_len"],
        "n": n,
        "raw_dir_acc": round(float((fs == ys).mean()), 4),
        "realized_up_rate": round(float((ys > 0).mean()), 4),
        "forecast_up_rate": round(float((fs > 0).mean()), 4),
        "balanced_acc": round((up_recall + dn_recall) / 2, 4),
        "mcc": round(mcc, 4),
        "spearman": round(rho, 4),
        "spearman_p": round(p_rho, 4),
        "median_rmse_ratio": payload["aggregate"].get("all_median_rmse_ratio"),
    }


def main() -> None:
    cells = [
        AUDIT / "v263_s8" / "v263_kronos_smoke" / "smoke_BTCUSDT.json",
        AUDIT / "v263_h1" / "v263_kronos_smoke" / "smoke_BTCUSDT.json",
        AUDIT / "v263_h4" / "v263_kronos_smoke" / "smoke_BTCUSDT.json",
        AUDIT / "v263_h12" / "v263_kronos_smoke" / "smoke_BTCUSDT.json",
        AUDIT / "v263_SOLUSDT_h1" / "v263_kronos_smoke" / "smoke_SOLUSDT.json",
        AUDIT / "v263_SOLUSDT_h24" / "v263_kronos_smoke" / "smoke_SOLUSDT.json",
        AUDIT / "v263_XRPUSDT_h1" / "v263_kronos_smoke" / "smoke_XRPUSDT.json",
        AUDIT / "v263_XRPUSDT_h24" / "v263_kronos_smoke" / "smoke_XRPUSDT.json",
    ]
    out = [r for r in (analyze(c) for c in cells) if r]
    k = len(out)

    hdr = (
        f"{'cell':<16}{'n':>5}{'rawAcc':>8}{'upRate':>8}{'fcUp':>7}"
        f"{'balAcc':>8}{'MCC':>8}{'rho':>8}{'p(rho)':>9}{'bonf':>7}{'rmseR':>8}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in out:
        sig = "PASS" if r["spearman_p"] < 0.05 / k else "-"
        print(
            f"{r['cell']:<16}{r['n']:>5}{r['raw_dir_acc']:>8.3f}{r['realized_up_rate']:>8.3f}"
            f"{r['forecast_up_rate']:>7.3f}{r['balanced_acc']:>8.3f}{r['mcc']:>8.3f}"
            f"{r['spearman']:>8.3f}{r['spearman_p']:>9.4f}{sig:>7}{r['median_rmse_ratio']:>8.3f}"
        )

    print(f"\ncells={k}  Bonferroni alpha = 0.05/{k} = {0.05 / k:.4f}")
    print("F4 pre-registered bar: pooled Spearman > 0.05")
    pooled = float(np.mean([r["spearman"] for r in out]))
    print(
        f"mean Spearman across cells = {pooled:.4f}  -> F4 {'PASS' if pooled > 0.05 else 'FAIL'}"
    )
    print(f"cells beating naive RMSE  = {sum(1 for r in out if r['median_rmse_ratio'] < 1.0)}/{k}")

    (AUDIT / "v263_rollup.json").write_text(
        json.dumps({"cells": out, "mean_spearman": pooled, "bonferroni_alpha": 0.05 / k}, indent=2)
    )


if __name__ == "__main__":
    main()
