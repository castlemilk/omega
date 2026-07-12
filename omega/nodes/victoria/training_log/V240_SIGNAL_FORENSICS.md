# V240 per-signal forensics results

**Verdict (2026-07-12, 160/160 cells, 0 determinism FAILs, 0 missing):
the V238 crisis/trend tradeoff lives almost entirely inside ONE signal.**
whale_flow alone accounts for ~90% of series-ON's trend floor breach
(**−$2,433** of −$2,693) AND ~65% of its crisis benefit (**+$2,063** of
+$3,148). fear_greed (+$836 crisis / −$637 trend) and vix (−$672 trend)
split the rest of the trend tax; dxy and yield_curve are benign SHIP-shape
but small (pooled p25 = $0 — inert in most windows).

Implications queued for V241+:
1. "Ship the helpful subset" = {dxy, yield_curve} clears every floor but is
   likely noise-level (combined pooled ≈ +$148, most windows $0).
2. The interesting bet is **regime-gating whale_flow** (± fear_greed): serve
   the series only in crisis/high-bear-prob state — keep the +$2,063 crisis
   edge without the −$2,433 trend tax. Strategy change ⇒ own pre-reg + grid.
3. Solo deltas do not sum to the joint series-ON delta (interactions are
   unattributed), and these reads are vs the V238 `main` (4-name legacy)
   baseline, PRE-V240.A adoption — any shipped subset needs its own confirm
   grid on the new selective-universe baseline.

--- (auto-generated detail below) ---

Each of the 5 V238-wired feeds run SOLO (frozen_series_enabled + frozen_series_signals=<name>) vs the V238 `main` baseline over the 32-window manifest. Question: which feed carries series-ON's trend −$2,693 / recent −$1,161 floor breach.

## Per-signal summary (mean-Δ vs main, $)

| signal | n | pooled | crisis | recent | trend | read |
|---|---:|---:|---:|---:|---:|---|
| fear_greed | 32 | 175 | 836 | 193 | -637 | DRAGGER (trend/recent) |
| vix | 32 | -210 | 111 | -131 | -672 | DRAGGER (trend/recent) |
| dxy | 32 | 14 | -84 | -49 | 193 | SHIP CANDIDATE |
| yield_curve | 32 | 135 | 266 | 49 | 63 | SHIP CANDIDATE |
| whale_flow | 32 | -123 | 2,063 | -435 | -2,433 | DRAGGER (trend/recent) |

## Per-signal distributions

### fear_greed

```json
{
  "pooled": {
    "n": 32,
    "mean": 174.92,
    "p25": -233.26,
    "median": 396.51,
    "min": -8490.14,
    "max": 2859.94,
    "spread": 11350.08
  },
  "regimes": {
    "crisis": {
      "n": 12,
      "mean": 836.34,
      "p25": 66.05,
      "median": 795.99,
      "min": -1656.54,
      "max": 2859.94,
      "spread": 4516.48
    },
    "trend": {
      "n": 10,
      "mean": -636.73,
      "p25": -417.39,
      "median": 112.98,
      "min": -8490.14,
      "max": 1656.78,
      "spread": 10146.92
    },
    "recent": {
      "n": 10,
      "mean": 192.85,
      "p25": -374.95,
      "median": 108.92,
      "min": -1258.95,
      "max": 1821.24,
      "spread": 3080.19
    }
  }
}
```

Per-window Δ: {"snap_wf_20200101": 428.3, "snap_wf_20200331": 446.02, "snap_wf_20200629": 1086.81, "snap_wf_20200813": -164.16, "snap_wf_20200927": 1656.78, "snap_wf_20201226": -8490.14, "snap_wf_20210326": 2859.94, "snap_wf_20210624": 1059.25, "snap_wf_20210922": -445.21, "snap_wf_20211221": 1801.33, "snap_wf_20220321": 88.31, "snap_wf_20220619": -1357.92, "snap_wf_20220917": 505.17, "snap_wf_20221216": -189.83, "snap_wf_20230130": 364.72, "snap_wf_20230316": 935.99, "snap_wf_20230430": 614.72, "snap_wf_20230614": 2109.4, "snap_wf_20230729": -146.89, "snap_wf_20230912": 139.39, "snap_wf_20231211": -493.25, "snap_wf_20240310": 1123.6, "snap_wf_20240608": -363.56, "snap_wf_20240723": -1122.12, "snap_wf_20240906": 775.81, "snap_wf_20241205": -1656.54, "snap_wf_20250305": 1821.24, "snap_wf_20250603": 86.58, "snap_wf_20250718": -1258.95, "snap_wf_20250901": -0.72, "snap_wf_20251130": 2054.04, "snap_wf_20260228": 1329.18}

### vix

```json
{
  "pooled": {
    "n": 32,
    "mean": -209.56,
    "p25": -163.53,
    "median": 54.47,
    "min": -11891.18,
    "max": 1843.31,
    "spread": 13734.49
  },
  "regimes": {
    "crisis": {
      "n": 12,
      "mean": 110.7,
      "p25": -41.24,
      "median": 137.0,
      "min": -864.93,
      "max": 1267.61,
      "spread": 2132.54
    },
    "trend": {
      "n": 10,
      "mean": -672.13,
      "p25": -132.94,
      "median": 287.82,
      "min": -11891.18,
      "max": 1843.31,
      "spread": 13734.49
    },
    "recent": {
      "n": 10,
      "mean": -131.3,
      "p25": -223.39,
      "median": -73.47,
      "min": -2210.26,
      "max": 969.45,
      "spread": 3179.71
    }
  }
}
```

Per-window Δ: {"snap_wf_20200101": 259.86, "snap_wf_20200331": 1009.2, "snap_wf_20200629": 71.15, "snap_wf_20200813": -235.48, "snap_wf_20200927": 927.5, "snap_wf_20201226": -11891.18, "snap_wf_20210326": -97.65, "snap_wf_20210624": 537.86, "snap_wf_20210922": -2210.26, "snap_wf_20211221": 202.86, "snap_wf_20220321": 301.99, "snap_wf_20220619": -155.67, "snap_wf_20220917": 505.17, "snap_wf_20221216": 1269.68, "snap_wf_20230130": 138.35, "snap_wf_20230316": 783.97, "snap_wf_20230430": -592.35, "snap_wf_20230614": 347.22, "snap_wf_20230729": 167.39, "snap_wf_20230912": 1843.31, "snap_wf_20231211": -235.07, "snap_wf_20240310": 1267.61, "snap_wf_20240608": 0.0, "snap_wf_20240723": -187.13, "snap_wf_20240906": 37.78, "snap_wf_20241205": -864.93, "snap_wf_20250305": 969.45, "snap_wf_20250603": -64.76, "snap_wf_20250718": -0.1, "snap_wf_20250901": -642.39, "snap_wf_20251130": -22.44, "snap_wf_20260228": -146.83}

### dxy

```json
{
  "pooled": {
    "n": 32,
    "mean": 13.5,
    "p25": 0.0,
    "median": 0.0,
    "min": -1106.79,
    "max": 2143.12,
    "spread": 3249.91
  },
  "regimes": {
    "crisis": {
      "n": 12,
      "mean": -83.83,
      "p25": 0.0,
      "median": 0.0,
      "min": -1106.79,
      "max": 302.11,
      "spread": 1408.9
    },
    "trend": {
      "n": 10,
      "mean": 192.81,
      "p25": 0.0,
      "median": 0.0,
      "min": -731.4,
      "max": 2143.12,
      "spread": 2874.52
    },
    "recent": {
      "n": 10,
      "mean": -49.01,
      "p25": 0.0,
      "median": 0.0,
      "min": -853.43,
      "max": 381.24,
      "spread": 1234.67
    }
  }
}
```

Per-window Δ: {"snap_wf_20200101": 0.0, "snap_wf_20200331": -265.32, "snap_wf_20200629": 0.0, "snap_wf_20200813": 381.24, "snap_wf_20200927": 0.0, "snap_wf_20201226": 0.0, "snap_wf_20210326": 0.0, "snap_wf_20210624": 781.69, "snap_wf_20210922": 0.0, "snap_wf_20211221": 58.81, "snap_wf_20220321": -345.98, "snap_wf_20220619": 2143.12, "snap_wf_20220917": 85.84, "snap_wf_20221216": 0.0, "snap_wf_20230130": 0.0, "snap_wf_20230316": -17.89, "snap_wf_20230430": 0.0, "snap_wf_20230614": 0.0, "snap_wf_20230729": 0.0, "snap_wf_20230912": -731.4, "snap_wf_20231211": 0.0, "snap_wf_20240310": 0.0, "snap_wf_20240608": -1106.79, "snap_wf_20240723": -853.43, "snap_wf_20240906": 0.0, "snap_wf_20241205": 0.0, "snap_wf_20250305": 0.0, "snap_wf_20250603": 0.0, "snap_wf_20250718": 0.0, "snap_wf_20250901": 0.0, "snap_wf_20251130": 302.11, "snap_wf_20260228": 0.0}

### yield_curve

```json
{
  "pooled": {
    "n": 32,
    "mean": 134.98,
    "p25": 0.0,
    "median": 0.0,
    "min": -939.4,
    "max": 2467.7,
    "spread": 3407.1
  },
  "regimes": {
    "crisis": {
      "n": 12,
      "mean": 266.11,
      "p25": 0.0,
      "median": 0.0,
      "min": -358.34,
      "max": 1912.79,
      "spread": 2271.13
    },
    "trend": {
      "n": 10,
      "mean": 63.12,
      "p25": -305.9,
      "median": 0.0,
      "min": -939.4,
      "max": 2467.7,
      "spread": 3407.1
    },
    "recent": {
      "n": 10,
      "mean": 49.47,
      "p25": 0.0,
      "median": 0.0,
      "min": -821.74,
      "max": 997.81,
      "spread": 1819.55
    }
  }
}
```

Per-window Δ: {"snap_wf_20200101": 142.27, "snap_wf_20200331": 0.0, "snap_wf_20200629": 0.0, "snap_wf_20200813": 0.0, "snap_wf_20200927": 0.0, "snap_wf_20201226": 0.0, "snap_wf_20210326": 0.0, "snap_wf_20210624": 0.0, "snap_wf_20210922": 0.0, "snap_wf_20211221": 0.0, "snap_wf_20220321": 0.0, "snap_wf_20220619": -489.2, "snap_wf_20220917": 14.25, "snap_wf_20221216": -939.4, "snap_wf_20230130": 319.93, "snap_wf_20230316": 997.81, "snap_wf_20230430": 145.6, "snap_wf_20230614": 1482.4, "snap_wf_20230729": -146.89, "snap_wf_20230912": 2467.7, "snap_wf_20231211": -407.87, "snap_wf_20240310": 1912.79, "snap_wf_20240608": -358.34, "snap_wf_20240723": -821.74, "snap_wf_20240906": 0.0, "snap_wf_20241205": 0.0, "snap_wf_20250305": 0.0, "snap_wf_20250603": 0.0, "snap_wf_20250718": 0.0, "snap_wf_20250901": 0.0, "snap_wf_20251130": 0.0, "snap_wf_20260228": 0.0}

### whale_flow

```json
{
  "pooled": {
    "n": 32,
    "mean": -122.57,
    "p25": -2498.82,
    "median": 8.08,
    "min": -22270.58,
    "max": 11546.8,
    "spread": 33817.38
  },
  "regimes": {
    "crisis": {
      "n": 12,
      "mean": 2063.07,
      "p25": -1447.17,
      "median": 1387.32,
      "min": -7346.36,
      "max": 11546.8,
      "spread": 18893.16
    },
    "trend": {
      "n": 10,
      "mean": -2432.66,
      "p25": -1693.4,
      "median": 22.38,
      "min": -22270.58,
      "max": 4666.25,
      "spread": 26936.83
    },
    "recent": {
      "n": 10,
      "mean": -435.25,
      "p25": -2700.61,
      "median": -1142.75,
      "min": -3032.3,
      "max": 6929.66,
      "spread": 9961.96
    }
  }
}
```

Per-window Δ: {"snap_wf_20200101": 1535.5, "snap_wf_20200331": 213.8, "snap_wf_20200629": 350.59, "snap_wf_20200813": -184.73, "snap_wf_20200927": 164.18, "snap_wf_20201226": -22270.58, "snap_wf_20210326": 10750.21, "snap_wf_20210624": -119.42, "snap_wf_20210922": 135.58, "snap_wf_20211221": 5767.93, "snap_wf_20220321": -4005.44, "snap_wf_20220619": -1756.95, "snap_wf_20220917": 5024.73, "snap_wf_20221216": -6110.55, "snap_wf_20230130": 2185.38, "snap_wf_20230316": -2397.93, "snap_wf_20230430": -209.09, "snap_wf_20230614": 1239.14, "snap_wf_20230729": -3032.3, "snap_wf_20230912": 2014.35, "snap_wf_20231211": 4666.25, "snap_wf_20240310": 11546.8, "snap_wf_20240608": 4265.81, "snap_wf_20240723": 6929.66, "snap_wf_20240906": -1502.74, "snap_wf_20241205": -7346.36, "snap_wf_20250305": -2901.17, "snap_wf_20250603": 375.04, "snap_wf_20250718": -2076.41, "snap_wf_20250901": -3663.82, "snap_wf_20251130": -708.28, "snap_wf_20260228": -2801.5}

## Interaction caveat

solo-signal deltas do not sum to the V238 series-ON delta — interactions between feeds are not attributed by this design

