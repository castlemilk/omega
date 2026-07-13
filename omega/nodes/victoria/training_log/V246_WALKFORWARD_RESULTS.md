# V246 exit-adapt walk-forward results (auto-generated)

`exit_adapt` (selective universe + exit_adaptivity: trail_keep_frac=0.25, max_hold_win=8) vs `universe_selective` (reused V240 confirm cells — the standing baseline) over the 32-window manifest.

## crisis

| config | n | mean | p25 | median | p75 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| universe_selective | 12 | 598.53 | -1,089.17 | 65.33 | 1,242.77 | -5,004.58 | 10,343.34 |
| exit_adapt | 12 | 1,121.74 | -878.59 | 1,268.75 | 1,990.28 | -5,004.58 | 12,143.74 |
| delta | 12 | 523.21 | 0.00 | 353.97 | 1,016.97 | -1,329.14 | 2,172.43 |

Per-window Δ (exit_adapt − selective): {"snap_wf_20200101": 70.45, "snap_wf_20200629": 142.07, "snap_wf_20210326": 1800.4, "snap_wf_20211221": 0.0, "snap_wf_20220321": -480.16, "snap_wf_20220917": 744.74, "snap_wf_20230614": 0.0, "snap_wf_20240310": 565.87, "snap_wf_20240608": -1329.14, "snap_wf_20241205": 2172.43, "snap_wf_20250901": 1836.01, "snap_wf_20251130": 755.82}

## recent

| config | n | mean | p25 | median | p75 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| universe_selective | 10 | 29.64 | -856.51 | -643.52 | 603.40 | -2,543.87 | 3,450.63 |
| exit_adapt | 10 | 101.17 | -759.31 | 326.25 | 1,339.79 | -2,907.83 | 2,110.98 |
| delta | 10 | 71.53 | -406.54 | -251.04 | 527.21 | -1,897.11 | 2,536.65 |

Per-window Δ (exit_adapt − selective): {"snap_wf_20200813": -439.93, "snap_wf_20210922": 2536.65, "snap_wf_20230130": 895.45, "snap_wf_20230316": -363.96, "snap_wf_20230430": 600.92, "snap_wf_20230729": -144.64, "snap_wf_20240723": -1897.11, "snap_wf_20250305": -420.73, "snap_wf_20250718": 306.07, "snap_wf_20260228": -357.45}

## trend

| config | n | mean | p25 | median | p75 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| universe_selective | 10 | 2,996.92 | -572.01 | 1,011.77 | 4,181.59 | -2,066.03 | 17,366.58 |
| exit_adapt | 10 | 4,303.77 | -383.99 | 1,926.01 | 8,486.22 | -1,660.74 | 16,314.61 |
| delta | 10 | 1,306.85 | -443.99 | 542.28 | 3,251.37 | -2,257.56 | 6,493.83 |

Per-window Δ (exit_adapt − selective): {"snap_wf_20200331": -306.0, "snap_wf_20200927": 2026.18, "snap_wf_20201226": -1051.97, "snap_wf_20210624": -489.98, "snap_wf_20220619": -2257.56, "snap_wf_20221216": 2.04, "snap_wf_20230912": 3659.76, "snap_wf_20231211": 1082.52, "snap_wf_20240906": 6493.83, "snap_wf_20250603": 3909.65}

## Pooled Δ (all windows)

```json
{
  "n": 32,
  "mean": 626.94,
  "p25": -378.15,
  "median": 106.26,
  "p75": 1261.99,
  "min": -2257.56,
  "max": 6493.83,
  "spread": 8751.39
}
```

## Pre-registered verdict (V246.md falsifier)

```json
{
  "v246_falsifier": {
    "bar": "FAIL if ANY: (recent mean-D<+$100 AND recent p25-D<+$400); pooled p25-D<$0; trend mean-D<-$300; crisis mean-D<-$300. ADOPT only if none fire AND pooled mean-D>$0.",
    "measured": {
      "recent_mean": 71.53,
      "recent_p25": -406.54,
      "pooled_p25": -378.15,
      "pooled_mean": 626.94,
      "trend_mean": 1306.85,
      "crisis_mean": 523.21
    },
    "fail_clauses": {
      "recent_conjunction (mean<+100 AND p25<+400)": true,
      "pooled_p25_lt_0": true,
      "trend_mean_lt_-300": false,
      "crisis_mean_lt_-300": false
    },
    "verdict": "REFUTED \u2014 falsifier clause(s) fired; flag stays OFF"
  },
  "determinism": {
    "failures": 0,
    "verdict": "PASS"
  },
  "noise_note": "recent 2*SE ~= $2,400; the falsifier's conjunction structure is the standing REFLECTION_V241 threshold (mean + p25 + no-regression)"
}
```

## Per-window detail

| window | regime | config | pnl | trades | det | N |
|---|---|---|---:|---:|---|---:|
| snap_wf_20200101 | crisis | exit_adapt | -2,638.60 | 12 | PASS | 1 |
| snap_wf_20200101 | crisis | universe_selective | -2,709.05 | 13 | PASS | 1 |
| snap_wf_20200331 | trend | exit_adapt | -1,660.74 | 11 | PASS | 1 |
| snap_wf_20200331 | trend | universe_selective | -1,354.74 | 11 | PASS | 1 |
| snap_wf_20200629 | crisis | exit_adapt | 297.53 | 13 | PASS | 1 |
| snap_wf_20200629 | crisis | universe_selective | 155.46 | 14 | PASS | 1 |
| snap_wf_20200813 | recent | exit_adapt | 2,110.98 | 4 | PASS | 1 |
| snap_wf_20200813 | recent | universe_selective | 2,550.91 | 5 | PASS | 1 |
| snap_wf_20200927 | trend | exit_adapt | 2,008.40 | 12 | PASS | 1 |
| snap_wf_20200927 | trend | universe_selective | -17.78 | 14 | PASS | 1 |
| snap_wf_20201226 | trend | exit_adapt | 16,314.61 | 13 | PASS | 1 |
| snap_wf_20201226 | trend | universe_selective | 17,366.58 | 13 | PASS | 1 |
| snap_wf_20210326 | crisis | exit_adapt | 12,143.74 | 12 | PASS | 1 |
| snap_wf_20210326 | crisis | universe_selective | 10,343.34 | 14 | PASS | 1 |
| snap_wf_20210624 | trend | exit_adapt | -806.14 | 14 | PASS | 1 |
| snap_wf_20210624 | trend | universe_selective | -316.16 | 14 | PASS | 1 |
| snap_wf_20210922 | recent | exit_adapt | 1,671.59 | 11 | PASS | 1 |
| snap_wf_20210922 | recent | universe_selective | -865.06 | 11 | PASS | 1 |
| snap_wf_20211221 | crisis | exit_adapt | -5,004.58 | 9 | PASS | 1 |
| snap_wf_20211221 | crisis | universe_selective | -5,004.58 | 9 | PASS | 1 |
| snap_wf_20220321 | crisis | exit_adapt | -504.97 | 12 | PASS | 1 |
| snap_wf_20220321 | crisis | universe_selective | -24.81 | 12 | PASS | 1 |
| snap_wf_20220619 | trend | exit_adapt | 429.78 | 14 | PASS | 1 |
| snap_wf_20220619 | trend | universe_selective | 2,687.34 | 16 | PASS | 1 |
| snap_wf_20220917 | crisis | exit_adapt | 1,948.13 | 7 | PASS | 1 |
| snap_wf_20220917 | crisis | universe_selective | 1,203.39 | 8 | PASS | 1 |
| snap_wf_20221216 | trend | exit_adapt | -655.25 | 5 | PASS | 1 |
| snap_wf_20221216 | trend | universe_selective | -657.29 | 6 | PASS | 1 |
| snap_wf_20230130 | recent | exit_adapt | 301.25 | 8 | PASS | 1 |
| snap_wf_20230130 | recent | universe_selective | -594.20 | 8 | PASS | 1 |
| snap_wf_20230316 | recent | exit_adapt | -2,907.83 | 14 | PASS | 1 |
| snap_wf_20230316 | recent | universe_selective | -2,543.87 | 14 | PASS | 1 |
| snap_wf_20230430 | recent | exit_adapt | 698.60 | 8 | PASS | 1 |
| snap_wf_20230430 | recent | universe_selective | 97.68 | 8 | PASS | 1 |
| snap_wf_20230614 | crisis | exit_adapt | -1,999.45 | 8 | PASS | 1 |
| snap_wf_20230614 | crisis | universe_selective | -1,999.45 | 8 | PASS | 1 |
| snap_wf_20230729 | recent | exit_adapt | -837.48 | 11 | PASS | 1 |
| snap_wf_20230729 | recent | universe_selective | -692.84 | 12 | PASS | 1 |
| snap_wf_20230912 | trend | exit_adapt | 8,339.43 | 7 | PASS | 2 |
| snap_wf_20230912 | trend | universe_selective | 4,679.67 | 6 | PASS | 2 |
| snap_wf_20231211 | trend | exit_adapt | 8,688.79 | 13 | PASS | 1 |
| snap_wf_20231211 | trend | universe_selective | 7,606.27 | 12 | PASS | 1 |
| snap_wf_20240310 | crisis | exit_adapt | 1,715.63 | 8 | PASS | 2 |
| snap_wf_20240310 | crisis | universe_selective | 1,149.76 | 9 | PASS | 2 |
| snap_wf_20240608 | crisis | exit_adapt | 2,849.24 | 6 | PASS | 1 |
| snap_wf_20240608 | crisis | universe_selective | 4,178.38 | 7 | PASS | 1 |
| snap_wf_20240723 | recent | exit_adapt | 1,553.52 | 12 | PASS | 1 |
| snap_wf_20240723 | recent | universe_selective | 3,450.63 | 13 | PASS | 1 |
| snap_wf_20240906 | trend | exit_adapt | 8,535.15 | 6 | PASS | 1 |
| snap_wf_20240906 | trend | universe_selective | 2,041.32 | 5 | PASS | 1 |
| snap_wf_20241205 | crisis | exit_adapt | 1,487.24 | 16 | PASS | 1 |
| snap_wf_20241205 | crisis | universe_selective | -685.19 | 18 | PASS | 1 |
| snap_wf_20250305 | recent | exit_adapt | 351.25 | 13 | PASS | 2 |
| snap_wf_20250305 | recent | universe_selective | 771.98 | 13 | PASS | 2 |
| snap_wf_20250603 | trend | exit_adapt | 1,843.62 | 7 | PASS | 1 |
| snap_wf_20250603 | trend | universe_selective | -2,066.03 | 7 | PASS | 1 |
| snap_wf_20250718 | recent | exit_adapt | -524.79 | 11 | PASS | 1 |
| snap_wf_20250718 | recent | universe_selective | -830.86 | 12 | PASS | 1 |
| snap_wf_20250901 | crisis | exit_adapt | 1,050.26 | 12 | PASS | 1 |
| snap_wf_20250901 | crisis | universe_selective | -785.75 | 12 | PASS | 1 |
| snap_wf_20251130 | crisis | exit_adapt | 2,116.73 | 6 | PASS | 1 |
| snap_wf_20251130 | crisis | universe_selective | 1,360.91 | 6 | PASS | 1 |
| snap_wf_20260228 | recent | exit_adapt | -1,405.41 | 12 | PASS | 1 |
| snap_wf_20260228 | recent | universe_selective | -1,047.96 | 13 | PASS | 1 |
