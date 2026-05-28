# Victoria V94 Forensics Report

**Generated:** 2026-04-09  
**Config change:** `short_thresh` lowered from 0.07 (V93) to 0.05 (V94)  
**Regression:** V93 +$130.91 → V94 -$37.86 (delta: -$168.77)

---

## Executive Summary — Top 3 Root Causes

### 1. Crisis Regime Collapse (PRIMARY — accounts for ~$169 of the swing)

V94 executed **31 crisis-regime trades** vs V93's 16, and those trades produced **-$56.29** vs V93's **+$112.98** — a $169.27 swing in the same regime. V93's crisis regime was a genuine upside panic recovery (69% WR, 4 symbols all profiting); V94's "crisis" was a grinding bearish tape with 19% WR, 0% WR for ADAUSDT and NEARUSDT, and repeated 6-cycle stop-outs. The lower short_thresh did not cause this: the crisis regime labeler fired more frequently during V94's run window but conditions were opposed to the long-biased strategy.

### 2. Stop-Out Rate Spike: 21.7% → 36.2% (V94 was stopped out 12 more times)

V94 hit the 6-cycle hold cap (stop-out) on 25/69 trades (36.2%) vs V93's 13/60 (21.7%). Those stopped-out trades lost a cumulative **-$154.83** in V94 vs **-$76.68** in V93 — an additional -$78 loss from stop-outs alone. All trades that ran the full 10 cycles in V94 were profitable (+$162.16), confirming the strategy is directionally sound but V94's market was moving against positions before the 10-cycle window completed. This is a market-condition symptom, not a threshold issue.

### 3. ADAUSDT Complete Edge Reversal — +$17.39 → -$37.77 (-$55.16 swing)

ADAUSDT was V93's most consistent symbol (53% WR, +$17.39). In V94 it became the primary loss engine (19% WR, -$37.77). ADA's price declined continuously from ~0.2517 to ~0.2508 during V94's run, with the system issuing long signals throughout the decline. 12 of 16 V94 ADA longs lost money; 9 of those losses were 6-cycle stop-outs. V94 also had 3 fewer ADA short trades than V93 (3 vs 6), eliminating that hedging contribution. The short_thresh reduction is not responsible — V94's enabled short signals were profitable; V94 simply executed them less often.

---

## Per-Symbol PnL Comparison

| Symbol   | V93 Trades | V93 PnL  | V93 WR | V94 Trades | V94 PnL  | V94 WR |
|----------|-----------|----------|--------|-----------|----------|--------|
| ADAUSDT  | 15        | +$17.39  | 53%    | 16        | -$37.77  | 19%    |
| ARBUSDT  | 14        | +$73.58  | 50%    | 16        | +$12.64  | 25%    |
| ETHUSDT  | 16        | +$0.98   | 56%    | 20        | -$5.71   | 50%    |
| NEARUSDT | 15        | +$38.97  | 33%    | 17        | -$7.03   | 24%    |

**Key observations:**

- **ADAUSDT**: Complete collapse in V94. V93 ran on an ADA price around 0.2496–0.2505 with two big crisis winners (cycles 187 +$13.33, 106 +$3.33). V94 caught ADA in a continuous decline from 0.2517 to 0.2508, triggering 6-cycle stop-outs on 9 consecutive long trades. The system has no downtrend filter for long entries.
- **ARBUSDT**: V94 still profitable overall (+$12.64), but 25% WR is a sharp drop from 50%. ARBUSD suffered mechanical stop-outs: with ~$9,950 position and -$0.001 price move per cycle, each stop-out costs exactly ~$9.70-$9.96. 8 of the 10 worst V94 trades are ARBUSDT longs.
- **ETHUSDT**: Near-zero in both versions. V94 had 4 more ETH trades but the ~$6 aggregate loss is immaterial compared to ADA/ARB.
- **NEARUSDT**: V93 caught two large NEAR rallies (+$24.82 at cycle 187, +$13.02 at cycle 199) — windfall events that didn't occur during V94's window. V94 NEAR traded in a 1.328–1.333 range with no directional move.

---

## Per-Regime PnL Comparison

| Regime   | V93 Trades | V93 %  | V93 PnL  | V93 WR | V94 Trades | V94 %  | V94 PnL  | V94 WR |
|----------|-----------|--------|----------|--------|-----------|--------|----------|--------|
| crisis   | 16        | 26.7%  | +$112.98 | 69%    | 31        | 44.9%  | -$56.29  | 19%    |
| high_vol | 17        | 28.3%  | +$40.72  | 47%    | 7         | 10.1%  | +$42.14  | 100%   |
| normal   | 27        | 45.0%  | -$22.79  | 37%    | 31        | 44.9%  | -$23.71  | 26%    |

**Key observations:**

- **Crisis is the entire story.** Crisis regime contributed the $169 swing between versions. V93's crisis = recovery bounce (69% WR). V94's crisis = prolonged drawdown (19% WR). Same label, opposite market conditions.
- **High-vol regime was perfect in V94 (100% WR, +$42.14)** but only 7 trades fired. When high_vol correctly identified momentum, every trade won.
- **Normal regime is consistently unprofitable** in both versions (-$22.79 vs -$23.71). This is a structural issue predating V94.
- Crisis regime went from 26.7% to 44.9% of trades — the regime classifier was firing "crisis" more aggressively in V94's window, but those crisis-labeled periods were adverse for longs.

---

## Trade Size Analysis

| Metric      | V93      | V94      |
|-------------|----------|----------|
| Avg size    | $8,361   | $8,551   |
| Median size | $8,333   | $8,333   |
| P25 size    | $7,832   | $8,333   |
| P75 size    | $8,747   | $8,534   |
| Min size    | $5,036   | $5,324   |
| Max size    | $25,000  | $25,000  |

Trade sizes are statistically identical. The conviction-proportional sizing system clusters at $8,333 (base conviction 0.0833). The $25,000 outlier is the forced high-conviction ADAUSDT short (conviction=0.25) present in both runs at cycle 33. No meaningful difference.

---

## Conviction Distribution Analysis

| Conviction Band | V93 Count | V93 %  | V94 Count | V94 %  |
|-----------------|-----------|--------|-----------|--------|
| < 0.06          | 10        | 16.7%  | 2         | 2.9%   |
| 0.06 – 0.07     | 4         | 6.7%   | 12        | 17.4%  |
| 0.07 – 0.08     | 3         | 5.0%   | 2         | 2.9%   |
| 0.08 – 0.09     | 31        | 51.7%  | 37        | 53.6%  |
| 0.09 – 0.10     | 9         | 15.0%  | 12        | 17.4%  |
| >= 0.10         | 3         | 5.0%   | 4         | 5.8%   |

**Average conviction:** V93 = 0.08361, V94 = 0.08551

**Counterintuitive finding:** V94's average conviction is *higher* than V93's despite the lower threshold. The lower short_thresh did not flood the system with low-conviction trades. The conviction distribution is structurally similar — both versions concentrate at the 0.08–0.09 band (~52%).

The main shift: `<0.06` collapsed from 16.7% → 2.9%. V93 had many very-low-conviction ETHUSDT longs (0.054–0.058 range) that were mostly losers (-$6.55 aggregate). V94 filtered these out, slightly improving quality. The 0.06–0.07 band grew (4 → 12), mostly ETHUSDT longs that collectively earned +$8.37.

---

## The "Extra 9 Trades" Analysis

V94 had 69 trades vs V93's 60 — net +9. By (symbol, side):

| Symbol / Side     | V93 | V94 | Delta |
|-------------------|-----|-----|-------|
| ADAUSDT long      | 9   | 13  | +4    |
| ADAUSDT short     | 6   | 3   | -3    |
| ARBUSDT long      | 14  | 16  | +2    |
| ETHUSDT long      | 16  | 20  | +4    |
| NEARUSDT long     | 15  | 17  | +2    |

**The extra 9 trades are: +4 ADA longs, -3 ADA shorts, +2 ARB longs, +4 ETH longs, +2 NEAR longs.**

The reduction in ADA shorts (-3) is the most consequential swap. V93's 6 ADA shorts contributed a cumulative +$4.06. V94's 3 ADA shorts still contributed +$5.34 (higher per-trade). The issue is not fewer shorts but the 4 additional ADA longs, which collectively lost ~-$22.94 during ADA's declining price phase.

The 4 extra ETHUSDT longs and 2 extra NEARUSDT longs earned a small positive net (+$3.72 for ETH, approximately flat for NEAR).

**The extra 9 trades are not a threshold artifact.** They represent more signal firing frequency in V94's adverse tape, not lower-quality signals. The marginal longs entered during declining price action and lost.

---

## Short Threshold Impact Analysis

Trades passing 0.05 threshold that would have been filtered at 0.07:

### Short-side trades (directly affected by short_thresh change):

| Cycle | Symbol  | Conviction | Regime   | PnL      |
|-------|---------|-----------|----------|----------|
| 23    | ADAUSDT | 0.06726   | high_vol | +$5.34   |
| 171   | ADAUSDT | 0.05324   | crisis   | $0.00    |

**Net PnL from threshold relaxation: +$5.34 (positive)**

The lower short_thresh **helped, did not hurt.** If V93's 0.07 threshold had been retained in V94, the regression would be $5.34 worse.

### Long-side trades in 0.05–0.07 conviction range (NOT affected by short_thresh):

| Cycle | Symbol  | Conviction | Regime   | PnL      |
|-------|---------|-----------|----------|----------|
| 23    | ETHUSDT | 0.06726   | high_vol | +$3.32   |
| 42    | ETHUSDT | 0.05538   | high_vol | +$1.77   |
| 42    | NEARUSDT| 0.06604   | high_vol | +$4.95   |
| 60    | ETHUSDT | 0.06532   | normal   | -$0.66   |
| 72    | ETHUSDT | 0.06642   | crisis   | -$4.48   |
| 84    | ETHUSDT | 0.06595   | normal   | +$4.49   |
| 91    | ETHUSDT | 0.06574   | crisis   | -$4.17   |
| 112   | ETHUSDT | 0.06713   | crisis   | -$0.70   |
| 128   | ETHUSDT | 0.06572   | crisis   | +$7.64   |
| 173   | NEARUSDT| 0.06436   | crisis   | $0.00    |
| 189   | ETHUSDT | 0.06639   | normal   | -$7.27   |
| 199   | ETHUSDT | 0.06738   | crisis   | +$3.48   |

**Total: +$8.37 — also net positive, also NOT caused by short_thresh change.**

These long trades appear because the long_thresh (unchanged) was already permitting them. They exist at similar rates in V93 (14 sub-0.07 trades in both versions).

**Verdict on threshold change: Not guilty. The short_thresh reduction contributed +$5.34.**

---

## Worst Trades Deep-Dive

Top 10 worst trades in V94 by PnL:

| Rank | Cycle | Symbol  | Side | Conviction | Regime  | PnL      | Size     | Hold |
|------|-------|---------|------|-----------|---------|----------|----------|------|
| 1    | 171   | ARBUSDT | long | 0.08333   | crisis  | -$16.36  | $8,333   | 6    |
| 2    | 154   | ETHUSDT | long | 0.08333   | crisis  | -$12.58  | $8,333   | 6    |
| 3    | 154   | ADAUSDT | long | 0.08333   | crisis  | -$9.96   | $8,333   | 6    |
| 4    | 148   | ARBUSDT | long | 0.10185   | crisis  | -$9.96   | $10,185  | 6    |
| 5    | 62    | ARBUSDT | long | 0.09950   | normal  | -$9.75   | $9,950   | 8    |
| 6    | 158   | ARBUSDT | long | 0.09950   | crisis  | -$9.75   | $9,950   | 6    |
| 7    | 140   | ARBUSDT | long | 0.09972   | normal  | -$9.74   | $9,972   | 7    |
| 8    | 188   | ARBUSDT | long | 0.09919   | normal  | -$9.73   | $9,919   | 9    |
| 9    | 164   | ARBUSDT | long | 0.09850   | normal  | -$9.66   | $9,850   | 6    |
| 10   | 38    | ARBUSDT | long | 0.07957   | normal  | -$7.80   | $7,957   | 6    |

**Findings:**

1. **8 of 10 worst trades are ARBUSDT longs.** ARB moved down ~$0.001 per cycle persistently during V94's run. With $9,950 size, each 1-pip adverse move = $9.95. ARBUSD is a high-noise ticker that penalizes the strategy when it trends against it.

2. **None of the 10 worst trades have low conviction.** All have conviction ≥ 0.079. The worst trades are core-signal trades at the standard position size, not marginal-threshold entries. The threshold change is exonerated.

3. **Cycle 154 is the worst single cycle:** -$12.58 (ETH) and -$9.96 (ADA) simultaneously in crisis regime = -$22.53 in one cycle. This is a correlated multi-symbol drawdown.

4. **Hold=6 dominates.** 7 of 10 worst trades hit the 6-cycle stop-out. The strategy would benefit from a tighter intra-cycle stop-loss rather than waiting the full 6 cycles.

---

## Conclusion & Recommendations

### Root Cause Scorecard

| Factor | PnL Impact | Verdict |
|--------|-----------|---------|
| Crisis regime adverse tape (market timing) | ~-$169 swing | Primary cause — market, not config |
| ADAUSDT persistent decline (no downtrend filter) | ~-$55 | Market + missing feature |
| ARBUSDT normal-regime stop-outs | ~-$50 in worst-10 | Market + position sizing |
| Short threshold change 0.07→0.05 | +$5.34 | Beneficial, not harmful |

**The short_thresh change is NOT the cause of the regression.** V94 ran during an adverse 47-minute window where ADA declined ~40 basis points, ARB oscillated with downside bias, and NEAR had no significant rallies. V93 ran earlier in the session and caught an upside crisis-recovery move. The $168.77 regression is entirely explained by run-window market conditions.

### Recommendations

1. **Do NOT revert short_thresh to 0.07.** The change helped by +$5.34. Reverting it would make V94 marginally worse. The original hypothesis that lower short_thresh caused regression is incorrect.

2. **Add a downtrend suppression filter for long entries.** ADAUSDT's repeated long entries into a declining tape is the clearest actionable bug. Gate long entries when the ticker's last N (e.g., 3) realized prices are monotonically declining. Specifically for crisis regime, add a "price is below 5-cycle mean" long suppression.

3. **Investigate ARBUSDT positioning for normal regime.** 8 of the 10 worst V94 trades are ARBUSDT longs in normal/crisis. Consider raising the conviction requirement for ARBUSD longs to ≥0.10, or reducing position size by 30% on ARB to limit per-trade loss exposure.

4. **Re-examine the crisis regime classifier.** V93's crisis was a genuine upside recovery (longs outperformed at 69% WR). V94's crisis was a grinding decline (19% WR). The regime label does not distinguish between "crisis bounce" and "crisis bleed." Consider splitting crisis into `crisis_recovery` (price momentum positive) and `crisis_drawdown` (price momentum negative) with different long/short biases.

5. **Use the backtest harness for threshold A/B testing.** Forward paper trading results are dominated by run-window conditions. The backtest harness at `omega/nodes/victoria/backtest.py` (introduced in V94) is the correct tool for evaluating single-parameter changes like short_thresh. Comparing live paper runs in different time windows is not a valid evaluation methodology.

6. **Tighten the crisis regime stop-out.** The 6-cycle hold cap results in -$9.96 per stop-out on a $9,950 ARB position. A tighter stop (e.g., stop at 3 cycles or -$5 per position) would halve the loss on each adverse trade while preserving upside on the full-hold winners.
