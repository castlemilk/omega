# V245 gdelt-solo walk-forward results (auto-generated)

`gdelt_solo` (selective universe + frozen_series gdelt + geopolitical_signals) vs `universe_selective` (reused V240 confirm cells — the standing baseline) over the 32-window manifest.

## crisis

| config | n | mean | p25 | median | p75 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| universe_selective | 12 | 598.53 | -1,089.17 | 65.33 | 1,242.77 | -5,004.58 | 10,343.34 |
| gdelt_solo | 12 | 818.72 | -638.35 | 790.76 | 1,412.28 | -4,860.34 | 9,937.33 |
| delta | 12 | 220.19 | -187.29 | 30.70 | 620.58 | -2,167.02 | 3,518.85 |

Per-window Δ (gdelt_solo − selective): {"snap_wf_20200101": 3518.85, "snap_wf_20200629": 777.87, "snap_wf_20210326": -406.01, "snap_wf_20211221": 144.24, "snap_wf_20220321": -82.85, "snap_wf_20220917": 613.33, "snap_wf_20230614": -123.71, "snap_wf_20240310": -378.04, "snap_wf_20240608": 186.67, "snap_wf_20241205": -2167.02, "snap_wf_20250901": 642.34, "snap_wf_20251130": -83.44}

## recent

| config | n | mean | p25 | median | p75 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| universe_selective | 10 | 29.64 | -856.51 | -643.52 | 603.40 | -2,543.87 | 3,450.63 |
| gdelt_solo | 10 | -98.93 | -878.51 | -325.92 | 1,267.26 | -2,675.25 | 1,811.01 |
| delta | 10 | -128.57 | -641.29 | -297.36 | 32.28 | -1,903.12 | 2,810.61 |

Per-window Δ (gdelt_solo − selective): {"snap_wf_20200813": -739.9, "snap_wf_20210922": 381.12, "snap_wf_20230130": -329.14, "snap_wf_20230316": -131.38, "snap_wf_20230430": -265.58, "snap_wf_20230729": -849.68, "snap_wf_20240723": -1903.12, "snap_wf_20250305": -345.47, "snap_wf_20250718": 86.83, "snap_wf_20260228": 2810.61}

## trend

| config | n | mean | p25 | median | p75 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| universe_selective | 10 | 2,996.92 | -572.01 | 1,011.77 | 4,181.59 | -2,066.03 | 17,366.58 |
| gdelt_solo | 10 | 2,760.74 | -136.69 | 1,492.41 | 3,171.62 | -2,304.68 | 16,421.31 |
| delta | 10 | -236.18 | -1,290.95 | -473.44 | 65.83 | -1,640.70 | 2,883.80 |

Per-window Δ (gdelt_solo − selective): {"snap_wf_20200331": -708.24, "snap_wf_20200927": 2883.8, "snap_wf_20201226": -945.27, "snap_wf_20210624": 1285.3, "snap_wf_20220619": -1551.18, "snap_wf_20221216": 151.99, "snap_wf_20230912": -1406.18, "snap_wf_20231211": -1640.7, "snap_wf_20240906": -192.66, "snap_wf_20250603": -238.65}

## Pooled Δ (all windows)

```json
{
  "n": 32,
  "mean": -31.41,
  "p25": -716.15,
  "median": -162.02,
  "p75": 235.28,
  "min": -2167.02,
  "max": 3518.85,
  "spread": 5685.87
}
```

## Pre-registered verdict (V245.md falsifier)

```json
{
  "v245_falsifier": {
    "bar": "FAIL if ANY: (recent mean-D<+$100 AND recent p25-D<+$400); pooled p25-D<$0; trend mean-D<-$300; crisis mean-D<-$300. ADOPT only if none fire AND pooled mean-D>$0.",
    "measured": {
      "recent_mean": -128.57,
      "recent_p25": -641.29,
      "pooled_p25": -716.15,
      "pooled_mean": -31.41,
      "trend_mean": -236.18,
      "crisis_mean": 220.19
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
| snap_wf_20200101 | crisis | gdelt_solo | 809.80 | 9 | PASS | 1 |
| snap_wf_20200101 | crisis | universe_selective | -2,709.05 | 13 | PASS | 1 |
| snap_wf_20200331 | trend | gdelt_solo | -2,062.98 | 11 | PASS | 1 |
| snap_wf_20200331 | trend | universe_selective | -1,354.74 | 11 | PASS | 1 |
| snap_wf_20200629 | crisis | gdelt_solo | 933.33 | 13 | PASS | 1 |
| snap_wf_20200629 | crisis | universe_selective | 155.46 | 14 | PASS | 1 |
| snap_wf_20200813 | recent | gdelt_solo | 1,811.01 | 4 | PASS | 1 |
| snap_wf_20200813 | recent | universe_selective | 2,550.91 | 5 | PASS | 1 |
| snap_wf_20200927 | trend | gdelt_solo | 2,866.02 | 10 | PASS | 1 |
| snap_wf_20200927 | trend | universe_selective | -17.78 | 14 | PASS | 1 |
| snap_wf_20201226 | trend | gdelt_solo | 16,421.31 | 12 | PASS | 1 |
| snap_wf_20201226 | trend | universe_selective | 17,366.58 | 13 | PASS | 1 |
| snap_wf_20210326 | crisis | gdelt_solo | 9,937.33 | 13 | PASS | 1 |
| snap_wf_20210326 | crisis | universe_selective | 10,343.34 | 14 | PASS | 1 |
| snap_wf_20210624 | trend | gdelt_solo | 969.14 | 13 | PASS | 1 |
| snap_wf_20210624 | trend | universe_selective | -316.16 | 14 | PASS | 1 |
| snap_wf_20210922 | recent | gdelt_solo | -483.94 | 12 | PASS | 1 |
| snap_wf_20210922 | recent | universe_selective | -865.06 | 11 | PASS | 1 |
| snap_wf_20211221 | crisis | gdelt_solo | -4,860.34 | 6 | PASS | 1 |
| snap_wf_20211221 | crisis | universe_selective | -5,004.58 | 9 | PASS | 1 |
| snap_wf_20220321 | crisis | gdelt_solo | -107.66 | 13 | PASS | 1 |
| snap_wf_20220321 | crisis | universe_selective | -24.81 | 12 | PASS | 1 |
| snap_wf_20220619 | trend | gdelt_solo | 1,136.16 | 18 | PASS | 1 |
| snap_wf_20220619 | trend | universe_selective | 2,687.34 | 16 | PASS | 1 |
| snap_wf_20220917 | crisis | gdelt_solo | 1,816.72 | 7 | PASS | 1 |
| snap_wf_20220917 | crisis | universe_selective | 1,203.39 | 8 | PASS | 1 |
| snap_wf_20221216 | trend | gdelt_solo | -505.30 | 4 | PASS | 1 |
| snap_wf_20221216 | trend | universe_selective | -657.29 | 6 | PASS | 1 |
| snap_wf_20230130 | recent | gdelt_solo | -923.34 | 9 | PASS | 1 |
| snap_wf_20230130 | recent | universe_selective | -594.20 | 8 | PASS | 1 |
| snap_wf_20230316 | recent | gdelt_solo | -2,675.25 | 13 | PASS | 1 |
| snap_wf_20230316 | recent | universe_selective | -2,543.87 | 14 | PASS | 1 |
| snap_wf_20230430 | recent | gdelt_solo | -167.90 | 8 | PASS | 1 |
| snap_wf_20230430 | recent | universe_selective | 97.68 | 8 | PASS | 1 |
| snap_wf_20230614 | crisis | gdelt_solo | -2,123.16 | 13 | PASS | 1 |
| snap_wf_20230614 | crisis | universe_selective | -1,999.45 | 8 | PASS | 1 |
| snap_wf_20230729 | recent | gdelt_solo | -1,542.52 | 14 | PASS | 1 |
| snap_wf_20230729 | recent | universe_selective | -692.84 | 12 | PASS | 1 |
| snap_wf_20230912 | trend | gdelt_solo | 3,273.49 | 8 | PASS | 2 |
| snap_wf_20230912 | trend | universe_selective | 4,679.67 | 6 | PASS | 2 |
| snap_wf_20231211 | trend | gdelt_solo | 5,965.57 | 13 | PASS | 1 |
| snap_wf_20231211 | trend | universe_selective | 7,606.27 | 12 | PASS | 1 |
| snap_wf_20240310 | crisis | gdelt_solo | 771.72 | 10 | PASS | 2 |
| snap_wf_20240310 | crisis | universe_selective | 1,149.76 | 9 | PASS | 2 |
| snap_wf_20240608 | crisis | gdelt_solo | 4,365.05 | 6 | PASS | 1 |
| snap_wf_20240608 | crisis | universe_selective | 4,178.38 | 7 | PASS | 1 |
| snap_wf_20240723 | recent | gdelt_solo | 1,547.51 | 19 | PASS | 1 |
| snap_wf_20240723 | recent | universe_selective | 3,450.63 | 13 | PASS | 1 |
| snap_wf_20240906 | trend | gdelt_solo | 1,848.66 | 5 | PASS | 1 |
| snap_wf_20240906 | trend | universe_selective | 2,041.32 | 5 | PASS | 1 |
| snap_wf_20241205 | crisis | gdelt_solo | -2,852.21 | 20 | PASS | 1 |
| snap_wf_20241205 | crisis | universe_selective | -685.19 | 18 | PASS | 1 |
| snap_wf_20250305 | recent | gdelt_solo | 426.51 | 13 | PASS | 2 |
| snap_wf_20250305 | recent | universe_selective | 771.98 | 13 | PASS | 2 |
| snap_wf_20250603 | trend | gdelt_solo | -2,304.68 | 10 | PASS | 1 |
| snap_wf_20250603 | trend | universe_selective | -2,066.03 | 7 | PASS | 1 |
| snap_wf_20250718 | recent | gdelt_solo | -744.03 | 13 | PASS | 1 |
| snap_wf_20250718 | recent | universe_selective | -830.86 | 12 | PASS | 1 |
| snap_wf_20250901 | crisis | gdelt_solo | -143.41 | 14 | PASS | 1 |
| snap_wf_20250901 | crisis | universe_selective | -785.75 | 12 | PASS | 1 |
| snap_wf_20251130 | crisis | gdelt_solo | 1,277.47 | 10 | PASS | 1 |
| snap_wf_20251130 | crisis | universe_selective | 1,360.91 | 6 | PASS | 1 |
| snap_wf_20260228 | recent | gdelt_solo | 1,762.65 | 10 | PASS | 1 |
| snap_wf_20260228 | recent | universe_selective | -1,047.96 | 13 | PASS | 1 |
