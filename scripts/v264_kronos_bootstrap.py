#!/usr/bin/env python3
"""V264 Phase 4b — bootstrap CIs on pooled Spearman and on the fine-tune delta.

This does NOT change the F4-ft gate (locked at +0.05, evaluated on the point
estimate). It answers a separate question the verdict has to answer honestly:
*is the result distinguishable from the bar, from zero, or from the zero-shot
arm at all?*

Both arms were scored on the IDENTICAL window set, so the delta is paired:
resampling window indices once and applying the same indices to both arms
preserves the pairing and removes shared window-draw variance.

Cells are NOT independent (BTC h1/h4/h12/h24 are nested horizons on overlapping
windows), so a naive across-cell SE would understate the interval. The bootstrap
resamples within each cell and averages, which propagates that structure.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

AUDIT = Path("/Volumes/gamma-systems-2/omega-victoria-data")
F4 = AUDIT / "v264" / "f4"
CELLS = [
    ("BTCUSDT", 1),
    ("BTCUSDT", 4),
    ("BTCUSDT", 12),
    ("BTCUSDT", 24),
    ("SOLUSDT", 1),
    ("SOLUSDT", 24),
    ("XRPUSDT", 1),
    ("XRPUSDT", 24),
]
N_BOOT = 10000
SEED = 20264


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    def rank(x):
        order = np.argsort(x, kind="stable")
        r = np.empty(len(x), dtype=float)
        r[order] = np.arange(len(x), dtype=float)
        _, inv, counts = np.unique(x, return_inverse=True, return_counts=True)
        sums = np.zeros(len(counts))
        np.add.at(sums, inv, r)
        return (sums / counts)[inv]

    ra, rb = rank(a), rank(b)
    ra -= ra.mean()
    rb -= rb.mean()
    den = math.sqrt(float((ra**2).sum()) * float((rb**2).sum()))
    return float((ra * rb).sum() / den) if den > 0 else 0.0


def load(tag: str) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    out = {}
    for sym, h in CELLS:
        rows = json.loads((F4 / tag / f"windows_{sym}_h{h}.json").read_text())
        out[f"{sym}_h{h}"] = (
            np.array([r["forecast_ret"] for r in rows], dtype=float),
            np.array([r["realized_ret"] for r in rows], dtype=float),
        )
    return out


def main() -> None:
    zs, ft = load("zeroshot_holdout"), load("finetuned")
    keys = [f"{s}_h{h}" for s, h in CELLS]

    for k in keys:
        if not np.allclose(zs[k][1], ft[k][1]):
            raise SystemExit(f"{k}: realized returns differ between arms — windows not identical")
    print("[check] both arms scored on identical windows (realized returns match) OK")

    rng = np.random.default_rng(SEED)
    pooled_zs, pooled_ft, pooled_d = [], [], []
    for _ in range(N_BOOT):
        rz, rf = [], []
        for k in keys:
            f_z, y = zs[k]
            f_f, _ = ft[k]
            idx = rng.integers(0, len(y), len(y))  # paired: same idx for both arms
            rz.append(spearman(f_z[idx], y[idx]))
            rf.append(spearman(f_f[idx], y[idx]))
        mz, mf = float(np.mean(rz)), float(np.mean(rf))
        pooled_zs.append(mz)
        pooled_ft.append(mf)
        pooled_d.append(mf - mz)

    def ci(a):
        a = np.array(a)
        return float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))

    obs_zs = float(np.mean([spearman(*zs[k]) for k in keys]))
    obs_ft = float(np.mean([spearman(*ft[k]) for k in keys]))
    lo_f, hi_f = ci(pooled_ft)
    lo_z, hi_z = ci(pooled_zs)
    lo_d, hi_d = ci(pooled_d)

    res = {
        "n_boot": N_BOOT,
        "seed": SEED,
        "zeroshot": {"pooled": round(obs_zs, 4), "ci95": [round(lo_z, 4), round(hi_z, 4)]},
        "finetuned": {"pooled": round(obs_ft, 4), "ci95": [round(lo_f, 4), round(hi_f, 4)]},
        "delta": {"pooled": round(obs_ft - obs_zs, 4), "ci95": [round(lo_d, 4), round(hi_d, 4)]},
        "p_ft_exceeds_bar": round(float(np.mean(np.array(pooled_ft) > 0.05)), 4),
        "p_ft_gt_zero": round(float(np.mean(np.array(pooled_ft) > 0.0)), 4),
        "p_delta_gt_zero": round(float(np.mean(np.array(pooled_d) > 0.0)), 4),
        "ft_ci_excludes_bar": bool(lo_f > 0.05 or hi_f < 0.05),
        "delta_ci_excludes_zero": bool(lo_d > 0 or hi_d < 0),
    }
    print(json.dumps(res, indent=2))
    (F4 / "bootstrap.json").write_text(json.dumps(res, indent=2))
    print(f"-> {F4 / 'bootstrap.json'}")


if __name__ == "__main__":
    main()
