<!-- NARRATIVE HEADER (git-maintained; re-apply if v239_wf_aggregate.py is re-run — it overwrites everything below the divider). -->

# V239 — universe/blacklist flip: verdict (MARGINAL miss, KEEP LEGACY)

**Grid:** 64/64 cells, **0 determinism FAILs**, all `$0.00` spread.
`universe_legacy` (4 names) **byte-identical to the V238 `main` grid**
(`nonzero_diffs: {}`, 32/32) — the new `universe_full_enabled` flag is a clean
no-op when OFF.

**Verdict — `adopt_universe_full`: NO, KEEP THE 4-NAME UNIVERSE (per-ticker
forensics next).** The bar was pooled mean-Δ(full−legacy) > −$300 AND every
regime mean-Δ > −$500. The flip **passes pooled** (+$210, n=32 — it is
net-positive) but **crisis regresses −$522, tripping the −$500 regime floor by
$22** → the pre-registered gate fails. Not moving the goalposts: KEEP LEGACY.

| Regime | legacy (4-name) | full (13-name) | mean-Δ | p25-Δ | median-Δ | note |
|---|---:|---:|---:|---:|---:|---|
| crisis | +$819 | +$298 | **−$522** | −$2,457 | −$500 | fails −$500 floor by $22 |
| trend  | +$1,941 | +$2,992 | **+$1,051** | −$3,191 | −$1,276 | mean up, median down (few big winners) |
| recent | −$516 | −$268 | **+$248** | −$1,587 | +$1,067 | improves |
| **pooled** | — | — | **+$210** | −$2,953 | +$305 | net-positive |

**Why this is a genuinely marginal result (the V240 hook), not a clean reject:**
- The flip is **net-positive pooled** (+$210) and **helps trend and recent**.
- Crisis's regression is a **loss of upside, not worse tails** — the full
  universe actually **tightens the crisis p25 to −$1,004 (vs legacy −$2,135)**
  and lifts min. Breadth reduces crisis tail risk but gives up crisis mean.
- So the −$522 crisis mean drop is the single gate-tripping number, and it's
  $22 past the floor. The right next move is **per-ticker forensics** (which of
  the 9 re-included names carries the crisis mean loss vs the tail-tightening
  benefit), not a blanket reject of breadth. Any per-regime *improvement* claim
  (trend +$1,051, recent +$248) is inside the recent 2·SE ≈ $2,400 noise band —
  directionally encouraging, not significant.

**Standing baseline UNCHANGED** (legacy = V238 = V235: crisis +$819 / trend
+$1,941 / recent −$516). `universe_full_enabled` stays default-OFF.

---

# V239 walk-forward universe-flip results (auto-generated)

blacklist ON (`universe_legacy`, 4 names) vs OFF (`universe_full`, 13 names) over the 32-window manifest.

## legacy-path identity vs V238 `main` grid

```json
{
  "checked": true,
  "v238_distribution": "/Volumes/gamma-systems-2/omega-victoria-data/v238_wf/distribution.json",
  "baseline_config": "universe_legacy",
  "windows_compared": 32,
  "nonzero_diffs": {},
  "verdict": "IDENTICAL"
}
```

## crisis

| config | n | mean | p25 | median | min | max |
|---|---:|---:|---:|---:|---:|---:|
| universe_legacy | 12 | 819.34 | -2,135.44 | 248.90 | -5,819.23 | 8,679.33 |
| universe_full | 12 | 297.66 | -1,003.76 | 1,176.58 | -5,215.31 | 5,141.95 |
| delta | 12 | -521.68 | -2,457.29 | -500.28 | -7,586.16 | 5,297.94 |

Per-window Δ (full − legacy): {"snap_wf_20200101": -7586.16, "snap_wf_20200629": -2097.26, "snap_wf_20210326": -3537.38, "snap_wf_20211221": 603.92, "snap_wf_20220321": -3571.23, "snap_wf_20220917": -1621.53, "snap_wf_20230614": 1552.09, "snap_wf_20240310": 2717.22, "snap_wf_20240608": -1604.47, "snap_wf_20241205": 2351.64, "snap_wf_20250901": 1235.1, "snap_wf_20251130": 5297.94}

## recent

| config | n | mean | p25 | median | min | max |
|---|---:|---:|---:|---:|---:|---:|
| universe_legacy | 10 | -516.27 | -2,551.49 | -1,571.14 | -5,355.69 | 6,551.05 |
| universe_full | 10 | -268.45 | -1,341.29 | -561.87 | -2,527.95 | 2,996.91 |
| delta | 10 | 247.82 | -1,586.87 | 1,066.96 | -7,982.87 | 8,352.60 |

Per-window Δ (full − legacy): {"snap_wf_20200813": 1127.44, "snap_wf_20210922": 1390.56, "snap_wf_20230130": 2227.68, "snap_wf_20230316": -765.13, "snap_wf_20230430": 2185.66, "snap_wf_20230729": -1860.78, "snap_wf_20240723": 8352.6, "snap_wf_20250305": -3203.41, "snap_wf_20250718": 1006.48, "snap_wf_20260228": -7982.87}

## trend

| config | n | mean | p25 | median | min | max |
|---|---:|---:|---:|---:|---:|---:|
| universe_legacy | 10 | 1,940.57 | -855.04 | 1,885.71 | -3,104.78 | 10,038.01 |
| universe_full | 10 | 2,991.76 | -678.84 | 1,470.92 | -1,345.45 | 17,197.55 |
| delta | 10 | 1,051.19 | -3,191.39 | -1,275.89 | -3,901.95 | 7,285.49 |

Per-window Δ (full − legacy): {"snap_wf_20200331": -2868.97, "snap_wf_20200927": -3298.87, "snap_wf_20201226": 7159.54, "snap_wf_20210624": 6.05, "snap_wf_20220619": -2557.83, "snap_wf_20221216": -3402.46, "snap_wf_20230912": 6972.71, "snap_wf_20231211": 7285.49, "snap_wf_20240906": 5118.16, "snap_wf_20250603": -3901.95}

## Pooled Δ (full − legacy, all windows)

```json
{
  "n": 32,
  "mean": 210.31,
  "p25": -2952.58,
  "median": 304.99,
  "min": -7982.87,
  "max": 8352.6,
  "spread": 16335.47
}
```

## Pre-registered verdicts (V239.md acceptance bar)

```json
{
  "adopt_universe_full": {
    "bar": "pooled mean-D > -300 AND every regime mean-D > -500",
    "measured": {
      "pooled_mean": 210.31,
      "pooled_n": 32,
      "regime_means": {
        "crisis": -521.68,
        "recent": 247.82,
        "trend": 1051.19
      },
      "worst_regime": [
        "crisis",
        -521.68
      ]
    },
    "verdict": "KEEP LEGACY 4-NAME UNIVERSE \u2014 per-ticker forensics next"
  },
  "infra_ship": {
    "bar": "determinism PASS all cells + legacy identity vs V238 main + coverage clean",
    "determinism_failures": 0,
    "legacy_identity": "IDENTICAL",
    "verdict": "SHIP"
  },
  "noise_note": "any per-regime 'improvement' claim must clear the REFLECTION_V237 threshold (recent 2*SE ~= $2,400); the flip's null hypothesis is 'does not regress'"
}
```

## Per-window detail

| window | regime | config | pnl | trades | det | N |
|---|---|---|---:|---:|---|---:|
| snap_wf_20200101 | crisis | universe_full | -3,009.82 | 9 | PASS | 1 |
| snap_wf_20200101 | crisis | universe_legacy | 4,576.34 | 10 | PASS | 1 |
| snap_wf_20200331 | trend | universe_full | -1,050.97 | 10 | PASS | 1 |
| snap_wf_20200331 | trend | universe_legacy | 1,818.00 | 14 | PASS | 1 |
| snap_wf_20200629 | crisis | universe_full | -541.98 | 15 | PASS | 1 |
| snap_wf_20200629 | crisis | universe_legacy | 1,555.28 | 14 | PASS | 1 |
| snap_wf_20200813 | recent | universe_full | -252.02 | 7 | PASS | 1 |
| snap_wf_20200813 | recent | universe_legacy | -1,379.46 | 11 | PASS | 1 |
| snap_wf_20200927 | trend | universe_full | -1,345.45 | 17 | PASS | 1 |
| snap_wf_20200927 | trend | universe_legacy | 1,953.42 | 13 | PASS | 1 |
| snap_wf_20201226 | trend | universe_full | 17,197.55 | 15 | PASS | 1 |
| snap_wf_20201226 | trend | universe_legacy | 10,038.01 | 13 | PASS | 1 |
| snap_wf_20210326 | crisis | universe_full | 5,141.95 | 10 | PASS | 1 |
| snap_wf_20210326 | crisis | universe_legacy | 8,679.33 | 13 | PASS | 1 |
| snap_wf_20210624 | trend | universe_full | 928.46 | 13 | PASS | 1 |
| snap_wf_20210624 | trend | universe_legacy | 922.41 | 13 | PASS | 1 |
| snap_wf_20210922 | recent | universe_full | 1,335.84 | 11 | PASS | 1 |
| snap_wf_20210922 | recent | universe_legacy | -54.72 | 11 | PASS | 1 |
| snap_wf_20211221 | crisis | universe_full | -5,215.31 | 9 | PASS | 1 |
| snap_wf_20211221 | crisis | universe_legacy | -5,819.23 | 14 | PASS | 1 |
| snap_wf_20220321 | crisis | universe_full | 1,338.04 | 11 | PASS | 1 |
| snap_wf_20220321 | crisis | universe_legacy | 4,909.27 | 14 | PASS | 1 |
| snap_wf_20220619 | trend | universe_full | 2,393.08 | 15 | PASS | 1 |
| snap_wf_20220619 | trend | universe_legacy | 4,950.91 | 14 | PASS | 1 |
| snap_wf_20220917 | crisis | universe_full | 1,203.39 | 8 | PASS | 1 |
| snap_wf_20220917 | crisis | universe_legacy | 2,824.92 | 13 | PASS | 1 |
| snap_wf_20221216 | trend | universe_full | 216.57 | 2 | PASS | 1 |
| snap_wf_20221216 | trend | universe_legacy | 3,619.03 | 14 | PASS | 1 |
| snap_wf_20230130 | recent | universe_full | -871.71 | 8 | PASS | 1 |
| snap_wf_20230130 | recent | universe_legacy | -3,099.39 | 13 | PASS | 1 |
| snap_wf_20230316 | recent | universe_full | -2,527.95 | 14 | PASS | 1 |
| snap_wf_20230316 | recent | universe_legacy | -1,762.82 | 14 | PASS | 1 |
| snap_wf_20230430 | recent | universe_full | 219.59 | 7 | PASS | 1 |
| snap_wf_20230430 | recent | universe_legacy | -1,966.07 | 15 | PASS | 1 |
| snap_wf_20230614 | crisis | universe_full | -2,389.11 | 11 | PASS | 1 |
| snap_wf_20230614 | crisis | universe_legacy | -3,941.20 | 10 | PASS | 1 |
| snap_wf_20230729 | recent | universe_full | -1,069.70 | 15 | PASS | 1 |
| snap_wf_20230729 | recent | universe_legacy | 791.08 | 15 | PASS | 1 |
| snap_wf_20230912 | trend | universe_full | 4,704.31 | 6 | PASS | 2 |
| snap_wf_20230912 | trend | universe_legacy | -2,268.40 | 10 | PASS | 2 |
| snap_wf_20231211 | trend | universe_full | 5,837.96 | 13 | PASS | 1 |
| snap_wf_20231211 | trend | universe_legacy | -1,447.53 | 16 | PASS | 1 |
| snap_wf_20240310 | crisis | universe_full | 1,149.76 | 9 | PASS | 2 |
| snap_wf_20240310 | crisis | universe_legacy | -1,567.46 | 16 | PASS | 2 |
| snap_wf_20240608 | crisis | universe_full | 3,021.68 | 7 | PASS | 1 |
| snap_wf_20240608 | crisis | universe_legacy | 4,626.15 | 7 | PASS | 1 |
| snap_wf_20240723 | recent | universe_full | 2,996.91 | 14 | PASS | 1 |
| snap_wf_20240723 | recent | universe_legacy | -5,355.69 | 19 | PASS | 1 |
| snap_wf_20240906 | trend | universe_full | 2,013.38 | 5 | PASS | 1 |
| snap_wf_20240906 | trend | universe_legacy | -3,104.78 | 10 | PASS | 1 |
| snap_wf_20241205 | crisis | universe_full | 1,237.13 | 17 | PASS | 1 |
| snap_wf_20241205 | crisis | universe_legacy | -1,114.51 | 15 | PASS | 1 |
| snap_wf_20250305 | recent | universe_full | 656.49 | 11 | PASS | 2 |
| snap_wf_20250305 | recent | universe_legacy | 3,859.90 | 10 | PASS | 2 |
| snap_wf_20250603 | trend | universe_full | -977.31 | 5 | PASS | 1 |
| snap_wf_20250603 | trend | universe_legacy | 2,924.64 | 10 | PASS | 1 |
| snap_wf_20250718 | recent | universe_full | -1,740.15 | 12 | PASS | 1 |
| snap_wf_20250718 | recent | universe_legacy | -2,746.63 | 20 | PASS | 1 |
| snap_wf_20250901 | crisis | universe_full | 177.62 | 10 | PASS | 1 |
| snap_wf_20250901 | crisis | universe_legacy | -1,057.48 | 15 | PASS | 1 |
| snap_wf_20251130 | crisis | universe_full | 1,458.55 | 6 | PASS | 1 |
| snap_wf_20251130 | crisis | universe_legacy | -3,839.39 | 11 | PASS | 1 |
| snap_wf_20260228 | recent | universe_full | -1,431.82 | 15 | PASS | 1 |
| snap_wf_20260228 | recent | universe_legacy | 6,551.05 | 12 | PASS | 1 |
