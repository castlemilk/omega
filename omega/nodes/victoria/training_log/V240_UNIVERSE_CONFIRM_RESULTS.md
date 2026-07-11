# V240 selective-universe confirm results (auto-generated)

`universe_selective` (V240 grid: blacklist {BTC, DOT, LINK}, 10-name universe) vs `universe_legacy` (reused V239 grid cells, 4 names) over the 32-window manifest.

## crisis

| config | n | mean | p25 | median | min | max |
|---|---:|---:|---:|---:|---:|---:|
| universe_legacy | 12 | 819.34 | -2,135.44 | 248.90 | -5,819.23 | 8,679.33 |
| universe_selective | 12 | 598.53 | -1,089.17 | 65.33 | -5,004.58 | 10,343.34 |
| delta | 12 | -220.80 | -1,455.25 | 350.52 | -7,285.39 | 5,200.30 |

Per-window Δ (selective − legacy): {"snap_wf_20200101": -7285.39, "snap_wf_20200629": -1399.82, "snap_wf_20210326": 1664.01, "snap_wf_20211221": 814.65, "snap_wf_20220321": -4934.08, "snap_wf_20220917": -1621.53, "snap_wf_20230614": 1941.75, "snap_wf_20240310": 2717.22, "snap_wf_20240608": -447.77, "snap_wf_20241205": 429.32, "snap_wf_20250901": 271.73, "snap_wf_20251130": 5200.3}

## recent

| config | n | mean | p25 | median | min | max |
|---|---:|---:|---:|---:|---:|---:|
| universe_legacy | 10 | -516.27 | -2,551.49 | -1,571.14 | -5,355.69 | 6,551.05 |
| universe_selective | 10 | 29.64 | -856.51 | -643.52 | -2,543.87 | 3,450.63 |
| delta | 10 | 545.92 | -1,315.53 | 567.36 | -7,599.01 | 8,806.32 |

Per-window Δ (selective − legacy): {"snap_wf_20200813": 3930.37, "snap_wf_20210922": -810.34, "snap_wf_20230130": 2505.19, "snap_wf_20230316": -781.05, "snap_wf_20230430": 2063.75, "snap_wf_20230729": -1483.92, "snap_wf_20240723": 8806.32, "snap_wf_20250305": -3087.92, "snap_wf_20250718": 1915.77, "snap_wf_20260228": -7599.01}

## trend

| config | n | mean | p25 | median | min | max |
|---|---:|---:|---:|---:|---:|---:|
| universe_legacy | 10 | 1,940.57 | -855.04 | 1,885.71 | -3,104.78 | 10,038.01 |
| universe_selective | 10 | 2,996.92 | -572.01 | 1,011.77 | -2,066.03 | 17,366.58 |
| delta | 10 | 1,056.35 | -2,945.45 | -1,604.88 | -4,990.67 | 9,053.80 |

Per-window Δ (selective − legacy): {"snap_wf_20200331": -3172.74, "snap_wf_20200927": -1971.2, "snap_wf_20201226": 7328.57, "snap_wf_20210624": -1238.57, "snap_wf_20220619": -2263.57, "snap_wf_20221216": -4276.32, "snap_wf_20230912": 6948.07, "snap_wf_20231211": 9053.8, "snap_wf_20240906": 5146.1, "snap_wf_20250603": -4990.67}

## Pooled Δ (selective − legacy, all windows)

```json
{
  "n": 32,
  "mean": 417.91,
  "p25": -2044.29,
  "median": -88.02,
  "min": -7599.01,
  "max": 9053.8,
  "spread": 16652.81
}
```

## Pre-registered verdicts (V240.md Track A acceptance bar)

```json
{
  "adopt_universe_selective": {
    "bar": "pooled mean-D > -300 AND every regime mean-D > -500",
    "measured": {
      "pooled_mean": 417.91,
      "pooled_n": 32,
      "regime_means": {
        "crisis": -220.8,
        "recent": 545.92,
        "trend": 1056.35
      },
      "worst_regime": [
        "crisis",
        -220.8
      ]
    },
    "reconstruction_prediction": {
      "pooled": 511.71,
      "crisis": -210.93,
      "trend": 1250.21,
      "recent": 642.57
    },
    "verdict": "ADOPT SELECTIVE UNIVERSE AS STANDING BASELINE"
  },
  "infra_ship": {
    "bar": "determinism PASS on all selective cells",
    "determinism_failures": 0,
    "verdict": "SHIP"
  },
  "noise_note": "any per-regime 'improvement' claim must clear the REFLECTION_V237 threshold (recent 2*SE ~= $2,400); the selective flip's null hypothesis is 'does not regress'"
}
```

## Per-window detail

| window | regime | config | pnl | trades | det | N |
|---|---|---|---:|---:|---|---:|
| snap_wf_20200101 | crisis | universe_legacy | 4,576.34 | 10 | PASS | 1 |
| snap_wf_20200101 | crisis | universe_selective | -2,709.05 | 13 | PASS | 1 |
| snap_wf_20200331 | trend | universe_legacy | 1,818.00 | 14 | PASS | 1 |
| snap_wf_20200331 | trend | universe_selective | -1,354.74 | 11 | PASS | 1 |
| snap_wf_20200629 | crisis | universe_legacy | 1,555.28 | 14 | PASS | 1 |
| snap_wf_20200629 | crisis | universe_selective | 155.46 | 14 | PASS | 1 |
| snap_wf_20200813 | recent | universe_legacy | -1,379.46 | 11 | PASS | 1 |
| snap_wf_20200813 | recent | universe_selective | 2,550.91 | 5 | PASS | 1 |
| snap_wf_20200927 | trend | universe_legacy | 1,953.42 | 13 | PASS | 1 |
| snap_wf_20200927 | trend | universe_selective | -17.78 | 14 | PASS | 1 |
| snap_wf_20201226 | trend | universe_legacy | 10,038.01 | 13 | PASS | 1 |
| snap_wf_20201226 | trend | universe_selective | 17,366.58 | 13 | PASS | 1 |
| snap_wf_20210326 | crisis | universe_legacy | 8,679.33 | 13 | PASS | 1 |
| snap_wf_20210326 | crisis | universe_selective | 10,343.34 | 14 | PASS | 1 |
| snap_wf_20210624 | trend | universe_legacy | 922.41 | 13 | PASS | 1 |
| snap_wf_20210624 | trend | universe_selective | -316.16 | 14 | PASS | 1 |
| snap_wf_20210922 | recent | universe_legacy | -54.72 | 11 | PASS | 1 |
| snap_wf_20210922 | recent | universe_selective | -865.06 | 11 | PASS | 1 |
| snap_wf_20211221 | crisis | universe_legacy | -5,819.23 | 14 | PASS | 1 |
| snap_wf_20211221 | crisis | universe_selective | -5,004.58 | 9 | PASS | 1 |
| snap_wf_20220321 | crisis | universe_legacy | 4,909.27 | 14 | PASS | 1 |
| snap_wf_20220321 | crisis | universe_selective | -24.81 | 12 | PASS | 1 |
| snap_wf_20220619 | trend | universe_legacy | 4,950.91 | 14 | PASS | 1 |
| snap_wf_20220619 | trend | universe_selective | 2,687.34 | 16 | PASS | 1 |
| snap_wf_20220917 | crisis | universe_legacy | 2,824.92 | 13 | PASS | 1 |
| snap_wf_20220917 | crisis | universe_selective | 1,203.39 | 8 | PASS | 1 |
| snap_wf_20221216 | trend | universe_legacy | 3,619.03 | 14 | PASS | 1 |
| snap_wf_20221216 | trend | universe_selective | -657.29 | 6 | PASS | 1 |
| snap_wf_20230130 | recent | universe_legacy | -3,099.39 | 13 | PASS | 1 |
| snap_wf_20230130 | recent | universe_selective | -594.20 | 8 | PASS | 1 |
| snap_wf_20230316 | recent | universe_legacy | -1,762.82 | 14 | PASS | 1 |
| snap_wf_20230316 | recent | universe_selective | -2,543.87 | 14 | PASS | 1 |
| snap_wf_20230430 | recent | universe_legacy | -1,966.07 | 15 | PASS | 1 |
| snap_wf_20230430 | recent | universe_selective | 97.68 | 8 | PASS | 1 |
| snap_wf_20230614 | crisis | universe_legacy | -3,941.20 | 10 | PASS | 1 |
| snap_wf_20230614 | crisis | universe_selective | -1,999.45 | 8 | PASS | 1 |
| snap_wf_20230729 | recent | universe_legacy | 791.08 | 15 | PASS | 1 |
| snap_wf_20230729 | recent | universe_selective | -692.84 | 12 | PASS | 1 |
| snap_wf_20230912 | trend | universe_legacy | -2,268.40 | 10 | PASS | 2 |
| snap_wf_20230912 | trend | universe_selective | 4,679.67 | 6 | PASS | 2 |
| snap_wf_20231211 | trend | universe_legacy | -1,447.53 | 16 | PASS | 1 |
| snap_wf_20231211 | trend | universe_selective | 7,606.27 | 12 | PASS | 1 |
| snap_wf_20240310 | crisis | universe_legacy | -1,567.46 | 16 | PASS | 2 |
| snap_wf_20240310 | crisis | universe_selective | 1,149.76 | 9 | PASS | 2 |
| snap_wf_20240608 | crisis | universe_legacy | 4,626.15 | 7 | PASS | 1 |
| snap_wf_20240608 | crisis | universe_selective | 4,178.38 | 7 | PASS | 1 |
| snap_wf_20240723 | recent | universe_legacy | -5,355.69 | 19 | PASS | 1 |
| snap_wf_20240723 | recent | universe_selective | 3,450.63 | 13 | PASS | 1 |
| snap_wf_20240906 | trend | universe_legacy | -3,104.78 | 10 | PASS | 1 |
| snap_wf_20240906 | trend | universe_selective | 2,041.32 | 5 | PASS | 1 |
| snap_wf_20241205 | crisis | universe_legacy | -1,114.51 | 15 | PASS | 1 |
| snap_wf_20241205 | crisis | universe_selective | -685.19 | 18 | PASS | 1 |
| snap_wf_20250305 | recent | universe_legacy | 3,859.90 | 10 | PASS | 2 |
| snap_wf_20250305 | recent | universe_selective | 771.98 | 13 | PASS | 2 |
| snap_wf_20250603 | trend | universe_legacy | 2,924.64 | 10 | PASS | 1 |
| snap_wf_20250603 | trend | universe_selective | -2,066.03 | 7 | PASS | 1 |
| snap_wf_20250718 | recent | universe_legacy | -2,746.63 | 20 | PASS | 1 |
| snap_wf_20250718 | recent | universe_selective | -830.86 | 12 | PASS | 1 |
| snap_wf_20250901 | crisis | universe_legacy | -1,057.48 | 15 | PASS | 1 |
| snap_wf_20250901 | crisis | universe_selective | -785.75 | 12 | PASS | 1 |
| snap_wf_20251130 | crisis | universe_legacy | -3,839.39 | 11 | PASS | 1 |
| snap_wf_20251130 | crisis | universe_selective | 1,360.91 | 6 | PASS | 1 |
| snap_wf_20260228 | recent | universe_legacy | 6,551.05 | 12 | PASS | 1 |
| snap_wf_20260228 | recent | universe_selective | -1,047.96 | 13 | PASS | 1 |
