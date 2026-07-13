# V243.A universe-blacklist-extension confirm results (auto-generated)

`universe_selective_ext` (flag ON: blacklist {BTC,DOT,LINK,ADA,NEAR,ARB}, 7-name universe) vs `universe_selective` (flag OFF: {BTC,DOT,LINK}, 10-name universe) — BOTH arms run fresh on the V243.A branch, same code, flag-only A/B, over the 32-window manifest. Δ = ext − selective.

## crisis

| config | n | mean | p25 | median | min | max |
|---|---:|---:|---:|---:|---:|---:|
| universe_selective | 12 | 598.53 | -1,089.17 | 65.33 | -5,004.58 | 10,343.34 |
| universe_selective_ext | 12 | 1,924.78 | -416.84 | 1,338.04 | -3,140.04 | 9,609.47 |
| delta | 12 | 1,326.25 | -464.45 | 93.88 | -1,140.59 | 7,422.00 |

Per-window Δ (ext − selective): {"snap_wf_20200101": 16.75, "snap_wf_20200629": -374.65, "snap_wf_20210326": -733.87, "snap_wf_20211221": 7422.0, "snap_wf_20220321": -984.97, "snap_wf_20220917": -92.54, "snap_wf_20230614": -1140.59, "snap_wf_20240310": 3118.24, "snap_wf_20240608": 4006.46, "snap_wf_20241205": 1829.35, "snap_wf_20250901": 2677.79, "snap_wf_20251130": 171.01}

## recent

| config | n | mean | p25 | median | min | max |
|---|---:|---:|---:|---:|---:|---:|
| universe_selective | 10 | 29.64 | -856.51 | -643.52 | -2,543.87 | 3,450.63 |
| universe_selective_ext | 10 | 262.08 | -634.06 | -271.22 | -2,366.47 | 4,303.31 |
| delta | 10 | 232.44 | -235.79 | 87.53 | -1,673.63 | 1,895.31 |

Per-window Δ (ext − selective): {"snap_wf_20200813": 171.42, "snap_wf_20210922": 1812.55, "snap_wf_20230130": 3.64, "snap_wf_20230316": 1895.31, "snap_wf_20230430": -235.13, "snap_wf_20230729": -1673.63, "snap_wf_20240723": 852.68, "snap_wf_20250305": -968.48, "snap_wf_20250718": -236.01, "snap_wf_20260228": 702.02}

## trend

| config | n | mean | p25 | median | min | max |
|---|---:|---:|---:|---:|---:|---:|
| universe_selective | 10 | 2,996.92 | -572.01 | 1,011.77 | -2,066.03 | 17,366.58 |
| universe_selective_ext | 10 | 5,004.01 | -683.76 | 136.39 | -1,751.73 | 37,807.82 |
| delta | 10 | 2,007.10 | -631.99 | -39.38 | -2,150.23 | 20,441.24 |

Per-window Δ (ext − selective): {"snap_wf_20200331": 724.08, "snap_wf_20200927": -683.68, "snap_wf_20201226": 20441.24, "snap_wf_20210624": -393.06, "snap_wf_20220619": -2150.23, "snap_wf_20221216": 392.95, "snap_wf_20230912": -778.93, "snap_wf_20231211": 2681.21, "snap_wf_20240906": -476.93, "snap_wf_20250603": 314.3}

## Pooled Δ (ext − selective, all windows)

```json
{
  "n": 32,
  "mean": 1197.2,
  "p25": -528.62,
  "median": 93.88,
  "min": -2150.23,
  "max": 20441.24,
  "spread": 22591.47
}
```

## Pre-registered three-tier verdict (V243_A_VERDICT.md)

```json
{
  "adopt_bar": "recent mean-\u0394 >= +$300 AND pooled mean-\u0394 >= +$400 AND every regime mean-\u0394 >= \u2212$100",
  "keep_bar": "recent mean-\u0394 in [+$100,+$300) AND positive in every regime",
  "revert_bar": "any regime mean-\u0394 < \u2212$300",
  "measured": {
    "recent_mean": 232.44,
    "pooled_mean": 1197.2,
    "pooled_n": 32,
    "regime_means": {
      "crisis": 1326.25,
      "recent": 232.44,
      "trend": 2007.1
    },
    "worst_regime": [
      "recent",
      232.44
    ]
  },
  "paper_prediction": {
    "crisis": 837.6,
    "trend": 163.4,
    "recent": 373.8,
    "pooled": 482.0
  },
  "verdict": "KEEP FLAG-GATED",
  "determinism": {
    "failures": 0,
    "status": "SHIP"
  },
  "noise_note": "recent 2*SE ~= $2,400 (REFLECTION_V237); a mean-\u0394 inside that band is directional, not significant \u2014 the acceptance unit is the distribution, not a single window."
}
```

## Per-window detail

| window | regime | config | pnl | trades | det | N |
|---|---|---|---:|---:|---|---:|
| snap_wf_20200101 | crisis | universe_selective | -2,709.05 | 13 | PASS | 1 |
| snap_wf_20200101 | crisis | universe_selective_ext | -2,692.30 | 11 | PASS | 1 |
| snap_wf_20200331 | trend | universe_selective | -1,354.74 | 11 | PASS | 1 |
| snap_wf_20200331 | trend | universe_selective_ext | -630.66 | 14 | PASS | 1 |
| snap_wf_20200629 | crisis | universe_selective | 155.46 | 14 | PASS | 1 |
| snap_wf_20200629 | crisis | universe_selective_ext | -219.19 | 19 | PASS | 1 |
| snap_wf_20200813 | recent | universe_selective | 2,550.91 | 5 | PASS | 1 |
| snap_wf_20200813 | recent | universe_selective_ext | 2,722.33 | 6 | PASS | 1 |
| snap_wf_20200927 | trend | universe_selective | -17.78 | 14 | PASS | 1 |
| snap_wf_20200927 | trend | universe_selective_ext | -701.46 | 15 | PASS | 1 |
| snap_wf_20201226 | trend | universe_selective | 17,366.58 | 13 | PASS | 1 |
| snap_wf_20201226 | trend | universe_selective_ext | 37,807.82 | 13 | PASS | 1 |
| snap_wf_20210326 | crisis | universe_selective | 10,343.34 | 14 | PASS | 1 |
| snap_wf_20210326 | crisis | universe_selective_ext | 9,609.47 | 16 | PASS | 1 |
| snap_wf_20210624 | trend | universe_selective | -316.16 | 14 | PASS | 1 |
| snap_wf_20210624 | trend | universe_selective_ext | -709.22 | 14 | PASS | 1 |
| snap_wf_20210922 | recent | universe_selective | -865.06 | 11 | PASS | 1 |
| snap_wf_20210922 | recent | universe_selective_ext | 947.49 | 15 | PASS | 1 |
| snap_wf_20211221 | crisis | universe_selective | -5,004.58 | 9 | PASS | 1 |
| snap_wf_20211221 | crisis | universe_selective_ext | 2,417.42 | 10 | PASS | 1 |
| snap_wf_20220321 | crisis | universe_selective | -24.81 | 12 | PASS | 1 |
| snap_wf_20220321 | crisis | universe_selective_ext | -1,009.78 | 12 | PASS | 1 |
| snap_wf_20220619 | trend | universe_selective | 2,687.34 | 16 | PASS | 1 |
| snap_wf_20220619 | trend | universe_selective_ext | 537.11 | 19 | PASS | 1 |
| snap_wf_20220917 | crisis | universe_selective | 1,203.39 | 8 | PASS | 1 |
| snap_wf_20220917 | crisis | universe_selective_ext | 1,110.85 | 10 | PASS | 1 |
| snap_wf_20221216 | trend | universe_selective | -657.29 | 6 | PASS | 1 |
| snap_wf_20221216 | trend | universe_selective_ext | -264.34 | 6 | PASS | 1 |
| snap_wf_20230130 | recent | universe_selective | -594.20 | 8 | PASS | 1 |
| snap_wf_20230130 | recent | universe_selective_ext | -590.56 | 14 | PASS | 1 |
| snap_wf_20230316 | recent | universe_selective | -2,543.87 | 14 | PASS | 1 |
| snap_wf_20230316 | recent | universe_selective_ext | -648.56 | 12 | PASS | 1 |
| snap_wf_20230430 | recent | universe_selective | 97.68 | 8 | PASS | 1 |
| snap_wf_20230430 | recent | universe_selective_ext | -137.45 | 10 | PASS | 1 |
| snap_wf_20230614 | crisis | universe_selective | -1,999.45 | 8 | PASS | 1 |
| snap_wf_20230614 | crisis | universe_selective_ext | -3,140.04 | 11 | PASS | 1 |
| snap_wf_20230729 | recent | universe_selective | -692.84 | 12 | PASS | 1 |
| snap_wf_20230729 | recent | universe_selective_ext | -2,366.47 | 14 | PASS | 1 |
| snap_wf_20230912 | trend | universe_selective | 4,679.67 | 6 | PASS | 2 |
| snap_wf_20230912 | trend | universe_selective_ext | 3,900.74 | 7 | PASS | 2 |
| snap_wf_20231211 | trend | universe_selective | 7,606.27 | 12 | PASS | 1 |
| snap_wf_20231211 | trend | universe_selective_ext | 10,287.48 | 13 | PASS | 1 |
| snap_wf_20240310 | crisis | universe_selective | 1,149.76 | 9 | PASS | 2 |
| snap_wf_20240310 | crisis | universe_selective_ext | 4,268.00 | 15 | PASS | 2 |
| snap_wf_20240608 | crisis | universe_selective | 4,178.38 | 7 | PASS | 1 |
| snap_wf_20240608 | crisis | universe_selective_ext | 8,184.84 | 8 | PASS | 1 |
| snap_wf_20240723 | recent | universe_selective | 3,450.63 | 13 | PASS | 1 |
| snap_wf_20240723 | recent | universe_selective_ext | 4,303.31 | 16 | PASS | 1 |
| snap_wf_20240906 | trend | universe_selective | 2,041.32 | 5 | PASS | 1 |
| snap_wf_20240906 | trend | universe_selective_ext | 1,564.39 | 9 | PASS | 1 |
| snap_wf_20241205 | crisis | universe_selective | -685.19 | 18 | PASS | 1 |
| snap_wf_20241205 | crisis | universe_selective_ext | 1,144.16 | 13 | PASS | 1 |
| snap_wf_20250305 | recent | universe_selective | 771.98 | 13 | PASS | 2 |
| snap_wf_20250305 | recent | universe_selective_ext | -196.50 | 13 | PASS | 2 |
| snap_wf_20250603 | trend | universe_selective | -2,066.03 | 7 | PASS | 1 |
| snap_wf_20250603 | trend | universe_selective_ext | -1,751.73 | 6 | PASS | 1 |
| snap_wf_20250718 | recent | universe_selective | -830.86 | 12 | PASS | 1 |
| snap_wf_20250718 | recent | universe_selective_ext | -1,066.87 | 7 | PASS | 1 |
| snap_wf_20250901 | crisis | universe_selective | -785.75 | 12 | PASS | 1 |
| snap_wf_20250901 | crisis | universe_selective_ext | 1,892.04 | 8 | PASS | 1 |
| snap_wf_20251130 | crisis | universe_selective | 1,360.91 | 6 | PASS | 1 |
| snap_wf_20251130 | crisis | universe_selective_ext | 1,531.92 | 7 | PASS | 1 |
| snap_wf_20260228 | recent | universe_selective | -1,047.96 | 13 | PASS | 1 |
| snap_wf_20260228 | recent | universe_selective_ext | -345.94 | 15 | PASS | 1 |
