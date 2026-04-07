# Cross-Asset Signals for Crypto Trading

**Last updated:** 2026-04-07
**Status:** Research + partial implementation
**Implemented:** Fear & Greed (`fear_greed.py`), DXY correlation (`dxy_signal.py`), Exchange flow stub (`exchange_flow.py`)

---

## Overview

Crypto markets are increasingly correlated with macro risk assets. Cross-asset signals exploit these relationships by incorporating exogenous data (equity volatility, dollar strength, yield curve shape, safe-haven flows) that pure on-chain or price-momentum signals miss. They are most valuable during regime transitions — the points where crypto-native signals lag.

The key insight: **crypto leads on idiosyncratic events, macro leads on regime shifts**. Cross-asset signals improve timing on regime entries/exits rather than intra-regime alpha.

---

## 1. US Dollar Index (DXY)

**Status: Implemented** — `omega/nodes/victoria/signals/dxy_signal.py`

### Mechanism
DXY measures the dollar vs a basket of 6 currencies (EUR 57.6%, JPY 13.6%, GBP 11.9%, CAD 9.1%, SEK 4.2%, CHF 3.6%). A rising dollar tightens global liquidity — USD-denominated risk assets (crypto, EM equities) fall.

### Empirical relationship
| Period | DXY move | BTC move | 20d correlation |
|--------|----------|----------|-----------------|
| Mar–Oct 2022 | +16% | -68% | -0.81 |
| Nov 2022–Feb 2023 | -8% | +40% | -0.73 |
| Sep–Oct 2023 | +5% | -12% | -0.65 |
| Q4 2023 | -4% | +70% | -0.58 |

Correlation is **regime-dependent** — breaks down during idiosyncratic crypto events (Luna/FTX collapses drove BTC down regardless of DXY). Signal fires only when corr < -0.5.

### Implementation
- Fetch DXY via `yfinance` (`DX-Y.NYB`)
- Compute 20-day rolling Pearson correlation of daily returns (BTC vs DXY)
- When `corr < -0.5` and DXY has a positive 5-day return → bearish signal for BTC
- Signal magnitude = `-dxy_5d_ret × |corr - threshold| × 20`, clamped to [-1, 1]

### Data source
- **yfinance** (free, Yahoo Finance backend): `pip install yfinance`
- Alternative: Alpha Vantage `FX_DAILY` for EURUSD as DXY proxy (env: `ALPHAVANTAGE_API_KEY`)

### Improvement ideas
- Use 1h DXY bars (requires paid data) for intraday signal timing
- Detect regime where DXY/BTC correlation breaks down (post-correlation filter)
- Add EURUSD as a free substitute when yfinance is unavailable (CoinGecko-compatible)

---

## 2. VIX (CBOE Volatility Index)

**Status: Not implemented**

### Mechanism
VIX measures implied volatility of S&P 500 options (30-day forward). High VIX = market fear = risk-off = typically bearish for crypto. VIX spikes above 30 have correlated with crypto drawdowns.

### Empirical relationship
- VIX < 15: "complacent" regime — crypto tends to grind higher
- VIX 15–25: neutral
- VIX 25–35: risk-off; BTC typically -10% to -20% over next 30d
- VIX > 35: "crisis" — high variance, but also reversal opportunities

### Signal logic (proposed)
```
if VIX > 30: signal = -1.0 (bearish)
elif VIX > 25: signal = -0.5 (mildly bearish)
elif VIX < 15: signal = +0.3 (complacency = bullish)
else: signal = 0.0
```

Contrarian overlay: VIX spike > 40 (extreme fear) often marks capitulation → flip to +0.5 after 3 days.

### Data source
- **yfinance**: ticker `^VIX` (daily, free)
- **CBOE API**: `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv` (free)
- **Alpha Vantage**: `TIME_SERIES_DAILY` for `^VIX`

### Implementation sketch
```python
# omega/nodes/victoria/signals/vix_signal.py
class VIXSignal:
    def compute(self) -> float:
        vix = self._fetch_vix()  # yfinance "^VIX"
        if vix > 40: return 0.5   # contrarian: capitulation
        if vix > 30: return -1.0
        if vix > 25: return -0.5
        if vix < 15: return 0.3
        return 0.0
```

---

## 3. SPY / S&P 500 Correlation

**Status: Not implemented**

### Mechanism
BTC/SPY correlation has risen from ~0.1 (2019) to ~0.6 (2022–2023) as institutional ownership increased. During risk-off events, the correlation spikes toward 1.0 — crypto sells off with equities. During crypto-native events, correlation decouples.

### Signal logic (proposed)
Track rolling 20-day BTC/SPY correlation:
- When `corr > 0.6` and SPY is falling (5d return < -2%): bearish for BTC (follow the lead)
- When `corr < 0.2`: crypto-native regime — ignore SPY signal (decouple filter)
- SPY rising with high correlation → mild bullish bias

### Key difference from DXY
DXY is a leading indicator (dollar leads risk sentiment). SPY is coincident — both BTC and SPY are reacting to the same macro driver. SPY signal is most useful as a **regime filter** (am I in a correlated vs uncorrelated regime?) rather than alpha.

### Data source
- yfinance: `SPY` or `^GSPC`

---

## 4. Yield Curve (2s10s Spread)

**Status: Not implemented**

### Mechanism
The 2y–10y Treasury yield spread is a leading recession indicator. Inversion (2y > 10y) has preceded every US recession since 1978 with 6–18 month lag. Crypto behavior around inversions:
- **Deep inversion (spread < -50bps)**: typically bearish over 12-month horizon (recession risk)
- **Steepening from inversion** (spread rising after inversion): historically bullish — Fed beginning to cut → risk-on
- **Normal curve (spread > 0)**: neutral to bullish

### Data source
- **FRED API** (free):
  - 2Y: `DGS2` — `https://api.stlouisfed.org/fred/series/observations?series_id=DGS2&api_key=...`
  - 10Y: `DGS10`
  - Env var: `FRED_API_KEY`
- Already integrated in `omega/integrations/connectors/fred.py`

### Implementation sketch
```python
# omega/nodes/victoria/signals/yield_curve.py
class YieldCurveSignal:
    def compute(self) -> float:
        spread = self._fetch_2s10s()  # 10Y - 2Y in bps
        # Steepening regime after inversion = bullish
        if spread < -50 and self._prev_spread < spread:
            return 0.5   # steepening from deep inversion → risk-on incoming
        if spread < -50:
            return -0.3  # inverted, holding — mild bearish
        if spread > 100:
            return 0.2   # steep curve — growth expectations, mild bullish
        return 0.0
```

---

## 5. Gold (XAU/USD)

**Status: Not implemented**

### Mechanism
Gold is the traditional safe-haven. BTC was positioned as "digital gold" but the correlation is inconsistent:
- In genuine flight-to-safety (COVID crash, 2022 rate shock): gold held, BTC fell → **negative correlation**
- In inflation hedging narratives (2020 QE bull run): both rose → **positive correlation**
- In idiosyncratic crypto regimes: decorrelated

Net: gold is useful as a **regime identifier** more than alpha signal.
- Gold rising + BTC falling = flight to traditional safe haven = bearish for crypto
- Gold rising + BTC rising = inflation hedge narrative = neutral/bullish continuation

### Data source
- yfinance: `GC=F` (gold futures) or `GLD` (ETF)
- CoinGecko: `/api/v3/simple/price?ids=gold&vs_currencies=usd` (limited precision)

---

## 6. Fear & Greed Index

**Status: Implemented** — `omega/nodes/victoria/signals/fear_greed.py`

### Mechanism
The Alternative.me Crypto Fear & Greed Index aggregates:
- Price volatility (25%)
- Market momentum/volume (25%)
- Social media sentiment (15%)
- Bitcoin dominance (10%)
- Google Trends (10%)
- Surveys (15%, currently paused)

Range: 0 (Extreme Fear) → 100 (Extreme Greed)

### Signal logic (contrarian)
The index is a mean-reversion indicator, not a momentum indicator:
| FGI reading | Signal | Rationale |
|-------------|--------|-----------|
| < 15 (Extreme Fear) | Strong long | Capitulation, max pessimism |
| 15–25 (Fear) | Moderate long | Oversold relative to history |
| 25–45 (Neutral–Fear) | Mild long | Below-average sentiment |
| 45–55 (Neutral) | None | No edge |
| 55–75 (Greed) | Mild short | Above-average complacency |
| 75–85 (Greed) | Moderate short | Overbought relative to history |
| > 85 (Extreme Greed) | Strong short | Euphoria, unsustainable |

### Victoria implementation
Uses 30-day z-score (not raw value) to normalize for regime drift:
- z < -1.5: contrarian long +1.0
- z > +1.5: contrarian short -1.0
- Linear ramp within ±1.5

### Historical back-of-envelope results
| Date | FGI | 30d forward BTC return |
|------|-----|----------------------|
| Mar 2020 (crash) | 8 | +78% |
| Jul 2021 (crash) | 10 | +59% |
| Jun 2022 (Luna) | 6 | +26% |
| Nov 2022 (FTX) | 20 | +28% |
| Nov 2021 (top) | 84 | -37% |
| Apr 2021 (top) | 78 | -52% |

Contrarian signal at extremes has strong historical support; middle range is noisy.

---

## Implementation Priority

| Signal | Data availability | Implementation complexity | Expected alpha |
|--------|-------------------|--------------------------|----------------|
| Fear & Greed | Free, no auth | Low (done) | Medium-high (extremes) |
| DXY | Free (yfinance) | Low (done) | Medium (corr-regime) |
| VIX | Free (yfinance) | Low | Medium |
| Yield curve | Free (FRED) | Low (FRED connector exists) | Low-medium (slow signal) |
| SPY correlation | Free (yfinance) | Low | Low (coincident) |
| Gold | Free (yfinance) | Medium (regime ID needed) | Low-medium |

**Next implementation:** VIX signal (high bang/buck, free data, clear threshold logic).

---

## Wiring notes

Both implemented signals are **market-level** (not per-ticker). In `signal_generation.py`:
1. Computed once per cycle before the ticker loop
2. Applied to every ticker's `ts` dict via `fear_greed_signal` / `dxy_signal` keys
3. The `_signal` suffix auto-includes them in the directional list for composite calculation
4. Both are guarded by `_HAS_*` import flags — zero impact when unavailable

Cross-asset signals should carry lower weight than per-ticker signals since they apply uniformly across all assets. The ML combiner (`SignalCombiner`) will learn appropriate weights automatically once sufficient trade history accumulates.
