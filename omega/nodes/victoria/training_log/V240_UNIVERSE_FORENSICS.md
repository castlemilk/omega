# V240 Track A — per-ticker forensics on the V239 universe flip

**Date:** 2026-07-11 · **Author:** claude (Fable 5)
**Inputs:** V239 grid per-cell `trades.csv` (gamma, 32 windows × universe_full
arm) + `v239_wf/distribution.json`. Tool: `scripts/v240_universe_forensics.py`
(trade-log reconstruction; per-window sum-check vs recorded cell PnL exact to
$0.00).

## Question

V239's full universe flip missed the crisis floor by $22 (crisis mean-Δ −$522
vs the −$500 bar) while passing pooled/trend/recent. Which of the 9
re-included names carries the crisis loss, and is there a selective re-include
subset that clears all four bars?

## Per-ticker PnL in the universe_full arm (32 windows, $)

| ticker | trades | crisis | recent | trend | total |
|---|---:|---:|---:|---:|---:|
| DOT | 14 | **−1,686** | −1,600 | −945 | **−4,231** |
| LINK | 32 | **−1,340** | −2,349 | −895 | **−4,584** |
| BTC | 4 | **−703** | +2 | −151 | −852 |
| MATIC | 34 | −180 | −560 | +10,242 | +9,502 |
| SUI | 26 | −27 | +1,775 | +9,505 | +11,252 |
| XRP | 27 | +1,563 | +1,025 | +3,626 | +6,214 |
| AVAX | 21 | +2,151 | −349 | −1,528 | +274 |
| SOL | 28 | +2,916 | +2,884 | +6,435 | +12,235 |
| BNB | 36 | +3,667 | +77 | −231 | +3,512 |

**The crisis regression is carried by exactly three names: DOT, LINK, BTC.**
DOT and LINK are negative in *every* regime (no offsetting benefit anywhere);
BTC is short-only under the flip (`_LONG_BLACKLIST` kept) with only 4 trades.
The other six names are the source of both the trend/recent lift and the
crisis tail-tightening that made V239 a "lost upside" miss.

## Subset search (exhaustive, 2^9 keep-subsets, trade-log reconstruction)

Bar: pooled mean-Δ > −$300 AND every regime mean-Δ > −$500, plus pooled > 0.
**32/512 subsets pass.** Selected subset (best pooled among the
top-headroom family, and the clean drop-the-three-crisis-draggers shape):

**keep {SOL, BNB, AVAX, XRP, SUI, MATIC} = drop {BTC, DOT, LINK}:**

| | pooled | crisis | trend | recent |
|---|---:|---:|---:|---:|
| full flip (V239 measured) | +210 | −522 | +1,051 | +248 |
| selective (reconstructed) | **+512** | **−211** | **+1,250** | **+643** |

## Caveat (pre-registered)

Reconstruction = full-arm PnL minus dropped tickers' trade PnL. It ignores
budget/N reallocation and cross-sectional demean interactions — removing three
names changes basket composition for the remaining ten. Early confirm-grid
color already shows real interaction (window snap_wf_20200101: selective
−$2,709 vs reconstruction-implied ≈ full −$3,010 + BTC/DOT/LINK adjustments,
vs legacy +$4,576). **The verdict is the confirm grid, not this table.**

## Action

- Shipped `universe_selective_enabled` (effective blacklist {BTC, DOT, LINK};
  `_universe_blocked` precedence full > selective > legacy; commit `35f99be`).
- Confirm grid running: `scripts/v240_wf_grid.sh` (32 selective cells; legacy
  arm reused from the V239 grid), aggregated by `scripts/v240_wf_aggregate.py`
  → `V240_UNIVERSE_CONFIRM_RESULTS.md`.
- Adopt-or-close decision comes from the confirm grid against the same bar.
