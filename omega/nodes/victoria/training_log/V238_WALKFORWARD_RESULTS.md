<!-- NARRATIVE HEADER (git-maintained; re-apply if v238_wf_aggregate.py is re-run — it overwrites everything below the divider). -->

# V238 — frozen-series feed build: re-baseline verdict

**Grid:** 64/64 cells, **0 determinism FAILs**, all `$0.00` spread (sleep=0,
N=1 + 3 sentinel N=2). OFF-path (`main`) **byte-identical to the V235 grid**
(`nonzero_diffs: {}` across all 32 windows) — the `frozen_series_enabled=False`
default is a true no-op, so the standing 4-name baseline is unchanged.

**Verdict — two decisions, per `V238.md`:**

1. **Infra: SHIP.** Determinism PASS on every cell + OFF identity + freeze
   coverage clean. The `SeriesProvider` + freeze-gap validator + the six-signal
   wiring ship as platform. Five info feeds now serve **real frozen history**
   (banner-confirmed): `fear_greed` fng[2018-02→2026-07], `vix`
   fred_vixcls[1990→2026], `dxy` fred_dtwexbgs[2006→2026], `yield_curve`
   fred_dgs10+dgs2, `funding`/OI `frozen_funding_cache.json` (manifest hash
   OK). The sixth, **`gdelt`, is honestly `ABSENT`** (no frozen source built
   yet — serves neutral by the explicit no-silent-zeros contract, queued V240).
   Prior to V238 all six degraded to `0.0`/stale under the V215 hermetic guards.

2. **Adopt series-ON as standing baseline: NO — KEEP FLAG-GATED.** Bar was
   pooled mean-Δ(series−main) > −$300 AND every regime mean-Δ > −$500. Pooled
   mean-Δ = **−$23.79** (n=32) clears the −$300 clause, but **trend regresses
   −$2,693** and **recent −$1,161**, both past the −$500 regime floor →
   fail. The information set nets ≈flat pooled while re-shuffling regime
   exposure: **crisis +$3,148 mean-Δ** (p25 +$581 — 9/12 windows positive) but
   **trend −$2,693 / recent −$1,161**. Crisis's +$3,148 clears the recent
   2·SE ≈ $2,400 noise bar; trend/recent regressions are real, not noise. So
   `frozen_series_enabled` stays default-OFF; per-signal forensics (which of the
   five helps crisis without the trend/recent tax) is the V240 surface.

**V238-era vs V235-era (per-regime mean, series-ON minus the V235/OFF main):**

| Regime | V235/OFF main (standing) | V238 series-ON | mean-Δ | p25-Δ | verdict |
|---|---:|---:|---:|---:|---|
| crisis | +$819 (n=12) | +$3,968 | **+$3,148** | +$581 | improves, but flag-gated |
| trend  | +$1,941 (n=10) | −$753 | **−$2,693** | −$5,442 | regresses (fails −$500 bar) |
| recent | −$516 (n=10) | −$1,677 | **−$1,161** | −$3,165 | regresses (fails −$500 bar) |

The **standing baseline is unchanged** (crisis +$819 / trend +$1,941 / recent
−$516 — the OFF path). V238's contribution is infrastructure + a measured,
flag-gated information set, not a baseline move.

**Permanent lesson retained:** the replay wrap-seam (c244568) footnote still
governs — pre-V235 single-window numbers stay contaminated; only walk-forward
distributions are baselines.

---

# V238 walk-forward re-baseline results (auto-generated)

frozen-series OFF (`main`) vs ON (`series`) over the 32-window manifest.

## OFF-path identity vs V235 grid

```json
{
  "checked": true,
  "v235_distribution": "/Volumes/gamma-systems-2/omega-victoria-data/v235_wf/distribution.json",
  "windows_compared": 32,
  "nonzero_diffs": {},
  "verdict": "IDENTICAL"
}
```

## crisis

| config | n | mean | p25 | median | min | max |
|---|---:|---:|---:|---:|---:|---:|
| main | 12 | 819.34 | -2,135.44 | 248.90 | -5,819.23 | 8,679.33 |
| series | 12 | 3,967.78 | -647.03 | 2,497.28 | -9,423.31 | 18,437.90 |
| delta | 12 | 3,148.44 | 580.82 | 3,979.39 | -8,308.80 | 12,232.10 |

Per-window Δ (series − main): {"snap_wf_20200101": 7564.77, "snap_wf_20200629": 486.0, "snap_wf_20210326": 9758.57, "snap_wf_20211221": 3948.03, "snap_wf_20220321": -5148.24, "snap_wf_20220917": 612.43, "snap_wf_20230614": 727.57, "snap_wf_20240310": 12232.1, "snap_wf_20240608": 6699.2, "snap_wf_20241205": -8308.8, "snap_wf_20250901": 4010.75, "snap_wf_20251130": 5198.91}

## recent

| config | n | mean | p25 | median | min | max |
|---|---:|---:|---:|---:|---:|---:|
| main | 10 | -516.27 | -2,551.49 | -1,571.14 | -5,355.69 | 6,551.05 |
| series | 10 | -1,677.21 | -2,782.59 | -1,759.83 | -5,182.93 | 3,030.31 |
| delta | 10 | -1,160.94 | -3,165.08 | -1,143.26 | -5,350.84 | 4,210.93 |

Per-window Δ (series − main): {"snap_wf_20200813": 265.62, "snap_wf_20210922": 654.92, "snap_wf_20230130": 261.58, "snap_wf_20230316": -2223.88, "snap_wf_20230430": -62.64, "snap_wf_20230729": -3408.01, "snap_wf_20240723": 4210.93, "snap_wf_20250305": -5350.84, "snap_wf_20250718": -2436.3, "snap_wf_20260228": -3520.74}

## trend

| config | n | mean | p25 | median | min | max |
|---|---:|---:|---:|---:|---:|---:|
| main | 10 | 1,940.57 | -855.04 | 1,885.71 | -3,104.78 | 10,038.01 |
| series | 10 | -752.75 | -3,976.22 | -256.51 | -7,412.36 | 4,627.85 |
| delta | 10 | -2,693.32 | -5,442.49 | -1,407.56 | -17,450.37 | 5,719.49 |

Per-window Δ (series − main): {"snap_wf_20200331": 2809.85, "snap_wf_20200927": -1547.37, "snap_wf_20201226": -17450.37, "snap_wf_20210624": -1841.49, "snap_wf_20220619": -9244.61, "snap_wf_20221216": -6642.83, "snap_wf_20230912": 2796.6, "snap_wf_20231211": 5719.49, "snap_wf_20240906": -1267.75, "snap_wf_20250603": -264.7}

## Pooled Δ (series − main, all windows)

```json
{
  "n": 32,
  "mean": -23.79,
  "p25": -2679.23,
  "median": 263.6,
  "min": -17450.37,
  "max": 12232.1,
  "spread": 29682.47
}
```

## Pre-registered verdicts (V238.md acceptance bar)

```json
{
  "adopt_series_on": {
    "bar": "pooled mean-D > -300 AND every regime mean-D > -500",
    "measured": {
      "pooled_mean": -23.79,
      "pooled_n": 32,
      "regime_means": {
        "crisis": 3148.44,
        "recent": -1160.94,
        "trend": -2693.32
      },
      "worst_regime": [
        "trend",
        -2693.32
      ]
    },
    "verdict": "KEEP FLAG-GATED \u2014 per-signal forensics next"
  },
  "infra_ship": {
    "bar": "determinism PASS all cells + OFF identity + coverage clean",
    "determinism_failures": 0,
    "off_identity": "IDENTICAL",
    "verdict": "SHIP"
  },
  "noise_note": "any per-regime 'improvement' claim must clear the REFLECTION_V237 threshold (recent 2*SE ~= $2,400); this re-baseline makes no improvement claim by itself"
}
```

## Per-window detail

| window | regime | config | pnl | trades | det | N |
|---|---|---|---:|---:|---|---:|
| snap_wf_20200101 | crisis | main | 4,576.34 | 10 | PASS | 1 |
| snap_wf_20200101 | crisis | series | 12,141.11 | 9 | PASS | 1 |
| snap_wf_20200331 | trend | main | 1,818.00 | 14 | PASS | 1 |
| snap_wf_20200331 | trend | series | 4,627.85 | 11 | PASS | 1 |
| snap_wf_20200629 | crisis | main | 1,555.28 | 14 | PASS | 1 |
| snap_wf_20200629 | crisis | series | 2,041.28 | 15 | PASS | 1 |
| snap_wf_20200813 | recent | main | -1,379.46 | 11 | PASS | 1 |
| snap_wf_20200813 | recent | series | -1,113.84 | 13 | PASS | 1 |
| snap_wf_20200927 | trend | main | 1,953.42 | 13 | PASS | 1 |
| snap_wf_20200927 | trend | series | 406.05 | 14 | PASS | 1 |
| snap_wf_20201226 | trend | main | 10,038.01 | 13 | PASS | 1 |
| snap_wf_20201226 | trend | series | -7,412.36 | 11 | PASS | 1 |
| snap_wf_20210326 | crisis | main | 8,679.33 | 13 | PASS | 1 |
| snap_wf_20210326 | crisis | series | 18,437.90 | 12 | PASS | 1 |
| snap_wf_20210624 | trend | main | 922.41 | 13 | PASS | 1 |
| snap_wf_20210624 | trend | series | -919.08 | 13 | PASS | 1 |
| snap_wf_20210922 | recent | main | -54.72 | 11 | PASS | 1 |
| snap_wf_20210922 | recent | series | 600.20 | 9 | PASS | 1 |
| snap_wf_20211221 | crisis | main | -5,819.23 | 14 | PASS | 1 |
| snap_wf_20211221 | crisis | series | -1,871.20 | 19 | PASS | 1 |
| snap_wf_20220321 | crisis | main | 4,909.27 | 14 | PASS | 1 |
| snap_wf_20220321 | crisis | series | -238.97 | 14 | PASS | 1 |
| snap_wf_20220619 | trend | main | 4,950.91 | 14 | PASS | 1 |
| snap_wf_20220619 | trend | series | -4,293.70 | 19 | PASS | 1 |
| snap_wf_20220917 | crisis | main | 2,824.92 | 13 | PASS | 1 |
| snap_wf_20220917 | crisis | series | 3,437.35 | 12 | PASS | 1 |
| snap_wf_20221216 | trend | main | 3,619.03 | 14 | PASS | 1 |
| snap_wf_20221216 | trend | series | -3,023.80 | 15 | PASS | 1 |
| snap_wf_20230130 | recent | main | -3,099.39 | 13 | PASS | 1 |
| snap_wf_20230130 | recent | series | -2,837.81 | 18 | PASS | 1 |
| snap_wf_20230316 | recent | main | -1,762.82 | 14 | PASS | 1 |
| snap_wf_20230316 | recent | series | -3,986.70 | 16 | PASS | 1 |
| snap_wf_20230430 | recent | main | -1,966.07 | 15 | PASS | 1 |
| snap_wf_20230430 | recent | series | -2,028.71 | 13 | PASS | 1 |
| snap_wf_20230614 | crisis | main | -3,941.20 | 10 | PASS | 1 |
| snap_wf_20230614 | crisis | series | -3,213.63 | 15 | PASS | 1 |
| snap_wf_20230729 | recent | main | 791.08 | 15 | PASS | 1 |
| snap_wf_20230729 | recent | series | -2,616.93 | 24 | PASS | 1 |
| snap_wf_20230912 | trend | main | -2,268.40 | 10 | PASS | 2 |
| snap_wf_20230912 | trend | series | 528.20 | 16 | PASS | 2 |
| snap_wf_20231211 | trend | main | -1,447.53 | 16 | PASS | 1 |
| snap_wf_20231211 | trend | series | 4,271.96 | 16 | PASS | 1 |
| snap_wf_20240310 | crisis | main | -1,567.46 | 16 | PASS | 2 |
| snap_wf_20240310 | crisis | series | 10,664.64 | 18 | PASS | 2 |
| snap_wf_20240608 | crisis | main | 4,626.15 | 7 | PASS | 1 |
| snap_wf_20240608 | crisis | series | 11,325.35 | 12 | PASS | 1 |
| snap_wf_20240723 | recent | main | -5,355.69 | 19 | PASS | 1 |
| snap_wf_20240723 | recent | series | -1,144.76 | 14 | PASS | 1 |
| snap_wf_20240906 | trend | main | -3,104.78 | 10 | PASS | 1 |
| snap_wf_20240906 | trend | series | -4,372.53 | 11 | PASS | 1 |
| snap_wf_20241205 | crisis | main | -1,114.51 | 15 | PASS | 1 |
| snap_wf_20241205 | crisis | series | -9,423.31 | 22 | PASS | 1 |
| snap_wf_20250305 | recent | main | 3,859.90 | 10 | PASS | 2 |
| snap_wf_20250305 | recent | series | -1,490.94 | 15 | PASS | 2 |
| snap_wf_20250603 | trend | main | 2,924.64 | 10 | PASS | 1 |
| snap_wf_20250603 | trend | series | 2,659.94 | 12 | PASS | 1 |
| snap_wf_20250718 | recent | main | -2,746.63 | 20 | PASS | 1 |
| snap_wf_20250718 | recent | series | -5,182.93 | 19 | PASS | 1 |
| snap_wf_20250901 | crisis | main | -1,057.48 | 15 | PASS | 1 |
| snap_wf_20250901 | crisis | series | 2,953.27 | 19 | PASS | 1 |
| snap_wf_20251130 | crisis | main | -3,839.39 | 11 | PASS | 1 |
| snap_wf_20251130 | crisis | series | 1,359.52 | 11 | PASS | 1 |
| snap_wf_20260228 | recent | main | 6,551.05 | 12 | PASS | 1 |
| snap_wf_20260228 | recent | series | 3,030.31 | 18 | PASS | 1 |
