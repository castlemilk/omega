# V231 snapshot sourcing manifest

Built 2026-06-22 via the V215 freeze recipe (`scripts/freeze_snapshot.py` historical
mode → Binance daily OHLCV via ccxt public API). 13-symbol universe = `ALL_SYMBOLS`
(`freeze_snapshot.py:54`). `_macro` block is **live scalars at build time** (FRED demo
key; fear/greed + btc_dominance unavailable) — NOT historically backfilled, consistent
with every prior snapshot.

| File | id | window | symbols | bars/sym | command |
|------|----|--------|---------|----------|---------|
| `snap_crisis_2024aug.json` | snap_crisis_2024aug | 2024-07-15 → 2024-09-15 (yen-carry unwind, Aug-5 risk-off) | **13/13** | 63 (MATIC 58) | `freeze_snapshot.py --start-date 2024-07-15 --end-date 2024-09-15 --id snap_crisis_2024aug` |
| `snap_trending_2024q1.json` | snap_trending_2024q1 | 2024-01-01 → 2024-03-31 (post-halving rally) | **13/13** | 91 | `freeze_snapshot.py --start-date 2024-01-01 --end-date 2024-03-31 --id snap_trending_2024q1` |

Purpose: V231 distributional eval. `snap_crisis_2024aug` is the binding 3rd crisis
window (13/13, avoids the V218.E universe-shrink); `snap_trending_2024q1` is the 2nd
trend window (bonus).

Notes:
- MATICUSDT has 58/63 bars in the 2024-Aug window (5 thin days on Binance) — symbol is
  present, minor within-symbol gap. All other symbols full.
- Crisis universe across the 3 windows is intrinsically non-uniform (2020-Q1 7/13,
  2022-H1 11/13, 2024-Aug 13/13) — pre-2020/pre-2023 tokens genuinely don't exist on
  Binance. Documented confound; 2024-Aug is the cleanest crisis window.
