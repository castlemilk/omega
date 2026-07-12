# V241 reasoning-layer walk-forward results (auto-generated)

`reasoning_on` (V241 grid: selective universe + reasoning_layer_enabled, served entirely from the frozen LLM cache) vs `universe_selective` (reused V240 confirm cells — the standing baseline) over the 32-window manifest.

## crisis

| config | n | mean | p25 | median | p75 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| universe_selective | 12 | 598.53 | -1,089.17 | 65.33 | 1,242.77 | -5,004.58 | 10,343.34 |
| reasoning_on | 12 | 550.51 | -881.09 | 1,538.61 | 2,067.09 | -4,152.12 | 3,269.13 |
| delta | 12 | -48.02 | -910.22 | 141.23 | 1,108.29 | -7,120.12 | 4,814.75 |

Per-window Δ (reasoning_on − selective): {"snap_wf_20200101": 4814.75, "snap_wf_20200629": 1898.76, "snap_wf_20210326": -7120.12, "snap_wf_20211221": 2111.6, "snap_wf_20220321": 205.76, "snap_wf_20220917": 844.8, "snap_wf_20230614": -2152.67, "snap_wf_20240310": 497.54, "snap_wf_20240608": -909.25, "snap_wf_20241205": 76.7, "snap_wf_20250901": -913.14, "snap_wf_20251130": 69.0}

## recent

| config | n | mean | p25 | median | p75 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| universe_selective | 10 | 29.64 | -856.51 | -643.52 | 603.40 | -2,543.87 | 3,450.63 |
| reasoning_on | 10 | 256.20 | -1,126.67 | -200.71 | 2,162.84 | -3,872.72 | 4,763.08 |
| delta | 10 | 226.56 | -705.44 | 64.61 | 875.61 | -1,823.29 | 3,991.10 |

Per-window Δ (reasoning_on − selective): {"snap_wf_20200813": 1019.92, "snap_wf_20210922": 912.28, "snap_wf_20230130": -710.69, "snap_wf_20230316": -1328.85, "snap_wf_20230430": -689.68, "snap_wf_20230729": -1823.29, "snap_wf_20240723": -582.58, "snap_wf_20250305": 3991.1, "snap_wf_20250718": 765.61, "snap_wf_20260228": 711.8}

## trend

| config | n | mean | p25 | median | p75 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| universe_selective | 10 | 2,996.92 | -572.01 | 1,011.77 | 4,181.59 | -2,066.03 | 17,366.58 |
| reasoning_on | 10 | 2,927.65 | -1,093.17 | 1,574.88 | 7,028.23 | -2,863.05 | 12,095.87 |
| delta | 10 | -69.26 | -938.04 | -99.05 | 4,178.21 | -18,733.44 | 8,611.71 |

Per-window Δ (reasoning_on − selective): {"snap_wf_20200331": -1508.31, "snap_wf_20200927": 3244.05, "snap_wf_20201226": -18733.44, "snap_wf_20210624": 8611.71, "snap_wf_20220619": -995.62, "snap_wf_20221216": 385.17, "snap_wf_20230912": 5162.77, "snap_wf_20231211": 4489.6, "snap_wf_20240906": -583.28, "snap_wf_20250603": -765.3}

## Pooled Δ (all windows)

```json
{
  "n": 32,
  "mean": 31.15,
  "p25": -910.22,
  "median": 141.23,
  "p75": 1239.63,
  "min": -18733.44,
  "max": 8611.71,
  "spread": 27345.15
}
```

## Pre-registered verdict (V241.md falsifier)

```json
{
  "adopt_reasoning_layer": {
    "bar": "recent mean-D > +$400 AND recent p25-D > +$500 AND trend mean-D > -$300 AND crisis mean-D > -$300 (conjunction)",
    "clauses": {
      "recent_mean_gt_400": {
        "measured": 226.56,
        "bar": 400.0,
        "pass": false
      },
      "recent_p25_gt_500": {
        "measured": -705.44,
        "bar": 500.0,
        "pass": false
      },
      "trend_mean_gt_-300": {
        "measured": -69.26,
        "bar": -300.0,
        "pass": true
      },
      "crisis_mean_gt_-300": {
        "measured": -48.02,
        "bar": -300.0,
        "pass": true
      }
    },
    "verdict": "KEEP FLAG-GATED OFF \u2014 falsifier clause(s) failed"
  },
  "determinism": {
    "failures": 0,
    "verdict": "PASS"
  },
  "noise_note": "recent 2*SE ~= $2,400 (REFLECTION_V237 \u00a72): a lone +$400 mean is in noise, which is why the falsifier conjoins p25 + no-regression bars"
}
```

## Per-window detail

| window | regime | config | pnl | trades | det | N |
|---|---|---|---:|---:|---|---:|
| snap_wf_20200101 | crisis | reasoning_on | 2,105.70 | 11 | PASS | 1 |
| snap_wf_20200101 | crisis | universe_selective | -2,709.05 | 13 | PASS | 1 |
| snap_wf_20200331 | trend | reasoning_on | -2,863.05 | 17 | PASS | 1 |
| snap_wf_20200331 | trend | universe_selective | -1,354.74 | 11 | PASS | 1 |
| snap_wf_20200629 | crisis | reasoning_on | 2,054.22 | 19 | PASS | 1 |
| snap_wf_20200629 | crisis | universe_selective | 155.46 | 14 | PASS | 1 |
| snap_wf_20200813 | recent | reasoning_on | 3,570.83 | 11 | PASS | 1 |
| snap_wf_20200813 | recent | universe_selective | 2,550.91 | 5 | PASS | 1 |
| snap_wf_20200927 | trend | reasoning_on | 3,226.27 | 11 | PASS | 1 |
| snap_wf_20200927 | trend | universe_selective | -17.78 | 14 | PASS | 1 |
| snap_wf_20201226 | trend | reasoning_on | -1,366.86 | 13 | PASS | 1 |
| snap_wf_20201226 | trend | universe_selective | 17,366.58 | 13 | PASS | 1 |
| snap_wf_20210326 | crisis | reasoning_on | 3,223.22 | 20 | PASS | 1 |
| snap_wf_20210326 | crisis | universe_selective | 10,343.34 | 14 | PASS | 1 |
| snap_wf_20210624 | trend | reasoning_on | 8,295.55 | 16 | PASS | 1 |
| snap_wf_20210624 | trend | universe_selective | -316.16 | 14 | PASS | 1 |
| snap_wf_20210922 | recent | reasoning_on | 47.22 | 14 | PASS | 1 |
| snap_wf_20210922 | recent | universe_selective | -865.06 | 11 | PASS | 1 |
| snap_wf_20211221 | crisis | reasoning_on | -2,892.98 | 14 | PASS | 1 |
| snap_wf_20211221 | crisis | universe_selective | -5,004.58 | 9 | PASS | 1 |
| snap_wf_20220321 | crisis | reasoning_on | 180.95 | 11 | PASS | 1 |
| snap_wf_20220321 | crisis | universe_selective | -24.81 | 12 | PASS | 1 |
| snap_wf_20220619 | trend | reasoning_on | 1,691.72 | 22 | PASS | 1 |
| snap_wf_20220619 | trend | universe_selective | 2,687.34 | 16 | PASS | 1 |
| snap_wf_20220917 | crisis | reasoning_on | 2,048.19 | 13 | PASS | 1 |
| snap_wf_20220917 | crisis | universe_selective | 1,203.39 | 8 | PASS | 1 |
| snap_wf_20221216 | trend | reasoning_on | -272.12 | 9 | PASS | 1 |
| snap_wf_20221216 | trend | universe_selective | -657.29 | 6 | PASS | 1 |
| snap_wf_20230130 | recent | reasoning_on | -1,304.89 | 14 | PASS | 1 |
| snap_wf_20230130 | recent | universe_selective | -594.20 | 8 | PASS | 1 |
| snap_wf_20230316 | recent | reasoning_on | -3,872.72 | 17 | PASS | 1 |
| snap_wf_20230316 | recent | universe_selective | -2,543.87 | 14 | PASS | 1 |
| snap_wf_20230430 | recent | reasoning_on | -592.00 | 12 | PASS | 1 |
| snap_wf_20230430 | recent | universe_selective | 97.68 | 8 | PASS | 1 |
| snap_wf_20230614 | crisis | reasoning_on | -4,152.12 | 13 | PASS | 1 |
| snap_wf_20230614 | crisis | universe_selective | -1,999.45 | 8 | PASS | 1 |
| snap_wf_20230729 | recent | reasoning_on | -2,516.13 | 15 | PASS | 1 |
| snap_wf_20230729 | recent | universe_selective | -692.84 | 12 | PASS | 1 |
| snap_wf_20230912 | trend | reasoning_on | 9,842.44 | 10 | PASS | 2 |
| snap_wf_20230912 | trend | universe_selective | 4,679.67 | 6 | PASS | 2 |
| snap_wf_20231211 | trend | reasoning_on | 12,095.87 | 19 | PASS | 1 |
| snap_wf_20231211 | trend | universe_selective | 7,606.27 | 12 | PASS | 1 |
| snap_wf_20240310 | crisis | reasoning_on | 1,647.30 | 15 | PASS | 2 |
| snap_wf_20240310 | crisis | universe_selective | 1,149.76 | 9 | PASS | 2 |
| snap_wf_20240608 | crisis | reasoning_on | 3,269.13 | 13 | PASS | 1 |
| snap_wf_20240608 | crisis | universe_selective | 4,178.38 | 7 | PASS | 1 |
| snap_wf_20240723 | recent | reasoning_on | 2,868.05 | 19 | PASS | 1 |
| snap_wf_20240723 | recent | universe_selective | 3,450.63 | 13 | PASS | 1 |
| snap_wf_20240906 | trend | reasoning_on | 1,458.04 | 9 | PASS | 1 |
| snap_wf_20240906 | trend | universe_selective | 2,041.32 | 5 | PASS | 1 |
| snap_wf_20241205 | crisis | reasoning_on | -608.49 | 18 | PASS | 1 |
| snap_wf_20241205 | crisis | universe_selective | -685.19 | 18 | PASS | 1 |
| snap_wf_20250305 | recent | reasoning_on | 4,763.08 | 14 | PASS | 2 |
| snap_wf_20250305 | recent | universe_selective | 771.98 | 13 | PASS | 2 |
| snap_wf_20250603 | trend | reasoning_on | -2,831.33 | 13 | PASS | 1 |
| snap_wf_20250603 | trend | universe_selective | -2,066.03 | 7 | PASS | 1 |
| snap_wf_20250718 | recent | reasoning_on | -65.25 | 14 | PASS | 1 |
| snap_wf_20250718 | recent | universe_selective | -830.86 | 12 | PASS | 1 |
| snap_wf_20250901 | crisis | reasoning_on | -1,698.89 | 18 | PASS | 1 |
| snap_wf_20250901 | crisis | universe_selective | -785.75 | 12 | PASS | 1 |
| snap_wf_20251130 | crisis | reasoning_on | 1,429.91 | 13 | PASS | 1 |
| snap_wf_20251130 | crisis | universe_selective | 1,360.91 | 6 | PASS | 1 |
| snap_wf_20260228 | recent | reasoning_on | -336.16 | 13 | PASS | 1 |
| snap_wf_20260228 | recent | universe_selective | -1,047.96 | 13 | PASS | 1 |
