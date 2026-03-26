# Paper Trading — Honest Backtest Results

Generated: 2026-03-26 04:02 UTC

```

========================================================================
  OMEGA HONEST BACKTEST — Multi-Period, Multi-Asset
  Strategy: SMA(10/30) + RSI<70 gate, long-only, 0.2% round-trip cost
========================================================================
  Periods: bull (Oct 2023–Mar 2024) | bear (May–Nov 2022) | sideways (Jul–Oct 2024)
  Assets:  BTC/USDT | ETH/USDT | SOL/USDT
========================================================================

  ── BULL PERIOD ──
  Expected to see positive returns — bulls should be kind to trend-followers.

  Symbol       Trades  WinRate      PF   Expect%   TotRet%   Sharpe   MaxDD%   Calmar   AvgMAE%   AvgMFE%      BnH%
  ------------------------------------------------------------------------------------------------------------
  BTC/USDT          0     0.0%   0.000    +0.000     +0.00   +0.000     0.00   +0.000     +0.00     +0.00   +154.64
  ETH/USDT          1   100.0%  ∞ (no losses)   +32.598    +33.07   +1.829    22.29   +3.445     -1.40    +63.29   +110.25
  SOL/USDT          0     0.0%   0.000    +0.000     +0.00   +0.000     0.00   +0.000     +0.00     +0.00   +748.14

  Average across 1 assets: win_rate=100.0%  profit_factor=999.000  expectancy=+32.598%  sharpe=+1.829

  ── BEAR PERIOD ──
  Expected losses if long-only — tells us if strategy knows when to stay flat.

  Symbol       Trades  WinRate      PF   Expect%   TotRet%   Sharpe   MaxDD%   Calmar   AvgMAE%   AvgMFE%      BnH%
  ------------------------------------------------------------------------------------------------------------
  BTC/USDT          5    20.0%   0.154    -6.088    -26.70   -1.292    33.02   -1.245    -11.17     +7.06    -55.38
  ETH/USDT          3    33.3%   1.392    +4.781     +1.72   +0.379    50.68   +0.058    -20.03    +34.27    -54.18
  SOL/USDT          6    16.7%   0.018   -11.155    -31.06   -0.752    45.71   -1.028    -17.41     +9.79    -84.21

  Average across 3 assets: win_rate=23.3%  profit_factor=0.522  expectancy=-4.154%  sharpe=-0.555

  ── SIDEWAYS PERIOD ──
  Chop eats trend strategies — expected low win rate and negative expectancy.

  Symbol       Trades  WinRate      PF   Expect%   TotRet%   Sharpe   MaxDD%   Calmar   AvgMAE%   AvgMFE%      BnH%
  ------------------------------------------------------------------------------------------------------------
  BTC/USDT          2     0.0%   0.000    -5.906     -5.32   -0.624    11.85   -1.264     -8.23     +3.12    +11.75
  ETH/USDT          1     0.0%   0.000    -7.986    -12.95   -1.678    17.13   -1.969    -12.73     +3.08    -26.83
  SOL/USDT          2     0.0%   0.000    -3.943     -5.34   -0.335    16.02   -0.937     -8.70     +6.32    +15.01

  Average across 3 assets: win_rate=0.0%  profit_factor=0.000  expectancy=-5.945%  sharpe=-0.879

========================================================================

  VERDICT
  -------
  Bull  win rate: 100.0%  profit_factor: 999.000  expectancy: +32.598%
  Bear  win rate: 23.3%  profit_factor: 0.522  expectancy: -4.154%
  Side  win rate: 0.0%  profit_factor: 0.000  expectancy: -5.945%

  OVERALL: Edge is regime-dependent. Works in bull, loses in bear.
           Add regime detection or short-side filter before live trading.

  NOTE: Results use production SMA(10/30)+RSI strategy with real Binance
        historical data. 0.2% round-trip commission applied. Long-only.
========================================================================
```
