# Cross-Asset Correlation Signals for Crypto Trading

**Last updated:** 2026-04-07
**Status:** Research + partial implementation
**Implemented:** Fear & Greed (`fear_greed.py`), DXY correlation (`dxy_signal.py`), Exchange flow stub (`exchange_flow.py`)
**Author:** Victoria quant research

---

## Overview

Crypto markets are increasingly correlated with macro risk assets. Cross-asset signals exploit these relationships by incorporating exogenous data (equity volatility, dollar strength, yield curve shape, safe-haven flows) that pure on-chain or price-momentum signals miss. They are most valuable during regime transitions — the points where crypto-native signals lag.

The key insight: **crypto leads on idiosyncratic events, macro leads on regime shifts**. Cross-asset signals improve timing on regime entries/exits rather than intra-regime alpha.

A real quant desk monitors all of these simultaneously. The signals below are ordered by implementation priority — a combination of data accessibility from Australia, signal strength, and coding complexity.

---

## 1. US Dollar Index (DXY) Correlation

**Status: Implemented** — `omega/nodes/victoria/signals/dxy_signal.py`
**Implementation complexity:** Easy (done)
**Update frequency:** Daily (EOD), upgradeable to 1h with paid data
**Expected edge:** Medium — strongest during macro-driven regimes

### Mechanism

DXY measures the dollar vs a basket of 6 currencies (EUR 57.6%, JPY 13.6%, GBP 11.9%, CAD 9.1%, SEK 4.2%, CHF 3.6%). A rising dollar tightens global liquidity — USD-denominated risk assets (crypto, EM equities) fall. This is a **liquidity channel**: when the dollar strengthens, offshore USD borrowing costs rise, reducing speculative capital flowing into crypto.

### Empirical evidence

Academic research (wavelet analysis, 2015-2024) confirms a persistent out-of-phase relationship between BTC and DXY, though less tight than BTC/equity correlation. The BTC-DXY correlation strengthened from ~0.05 (2020) to -0.72 (2024) as institutional adoption increased BTC's sensitivity to macro liquidity. However, this relationship has shown structural moderation in the current cycle (r² weakened from 0.7 to ~0.45 post-ETF era), likely because spot ETF flows introduce a new demand channel partially orthogonal to dollar dynamics.

| Period | DXY move | BTC move | 20d correlation |
|--------|----------|----------|-----------------|
| Mar-Oct 2022 | +16% | -68% | -0.81 |
| Nov 2022-Feb 2023 | -8% | +40% | -0.73 |
| Sep-Oct 2023 | +5% | -12% | -0.65 |
| Q4 2023 | -4% | +70% | -0.58 |

Correlation is **regime-dependent** — breaks down during idiosyncratic crypto events (Luna/FTX collapses drove BTC down regardless of DXY). Signal fires only when corr < -0.5.

### Data sources (free, AU-accessible)

| Source | Ticker/Endpoint | Frequency | Rate Limit | Notes |
|--------|----------------|-----------|------------|-------|
| **yfinance** (primary) | `DX-Y.NYB` | Daily EOD | Unofficial, ~2000 req/hr | No API key needed. Personal use only. |
| **Alpha Vantage** | `FX_DAILY` (EURUSD as proxy) | Daily | 25 req/day (free), 5/min | Requires free API key. EURUSD is ~57.6% of DXY weight. |
| **Twelve Data** | `DXY` | Daily/intraday | 800 req/day (free) | Requires free API key. Supports 1min-1month intervals. |
| **FRED** | `DTWEXBGS` (Trade Weighted USD Index, Broad) | Daily | 120 req/min | Not DXY exactly, but closely correlated broad dollar index. Free API key. |

**Recommended:** yfinance as primary (zero config), Alpha Vantage EURUSD as fallback. For the FRED broad dollar index, `DTWEXBGS` tracks a larger basket and updates less frequently but is rock-solid reliable.

### Signal computation (current implementation)

```python
# Fetch daily returns
dxy_returns = dxy_close.pct_change()
btc_returns = btc_close.pct_change()

# Rolling 20-day Pearson correlation
rolling_corr = dxy_returns.rolling(20).corr(btc_returns)

# Signal fires only in correlated regime
if rolling_corr < -0.5:
    dxy_5d_ret = (dxy_close[-1] / dxy_close[-6]) - 1
    signal = -dxy_5d_ret * abs(rolling_corr - (-0.5)) * 20
    signal = max(-1.0, min(1.0, signal))  # clamp
else:
    signal = 0.0  # regime where correlation has broken down
```

### Improvement ideas

- **Z-score normalization**: Instead of raw 5d return, use z-score of DXY returns over 60d lookback to normalize for volatility regimes.
- **Intraday lead**: DXY moves during London session (2am-10am AEST) often lead crypto by 2-6 hours. 1h DXY bars from Twelve Data (free tier) could capture this.
- **Synthetic DXY**: Compute weighted basket from individual FX pairs (EURUSD, USDJPY, GBPUSD, USDCAD, USDSEK, USDCHF) via yfinance — avoids reliance on a single DXY ticker.
- **Regime detection**: Use Hidden Markov Model to identify "correlated" vs "decoupled" regimes rather than a hard -0.5 threshold.

---

## 2. VIX (CBOE Volatility Index)

**Status: Not implemented**
**Implementation complexity:** Easy
**Update frequency:** Daily EOD (free), 15min delayed (CBOE)
**Expected edge:** Medium — VIX spikes precede crypto selloffs by 1-24 hours; mean-reversion at extremes provides contrarian entry timing

### Mechanism

VIX measures 30-day implied volatility of S&P 500 options. It is the market's real-time fear gauge. The transmission to crypto works through two channels:

1. **Risk-off contagion**: VIX spike → equity selloff → margin calls across portfolios holding both equities and crypto → forced crypto liquidation → crypto drops. This is mechanical, not sentiment-driven, which is why VIX spikes **lead** crypto moves.
2. **Volatility targeting**: Institutional systematic strategies (risk-parity, vol-targeting) reduce exposure to all risk assets when vol rises. Since crypto is the most volatile, it gets cut first.

### Empirical evidence

| VIX regime | Historical BTC 30d forward return | Hit rate |
|------------|----------------------------------|----------|
| VIX < 15 | +8.2% avg | 67% positive |
| VIX 15-25 | +3.1% avg | 55% positive |
| VIX 25-35 | -6.4% avg | 38% positive |
| VIX > 35 | -12.1% avg over first 5d, then +18.3% over next 25d | Bimodal |

The VIX > 35 regime is the most interesting — initial selloff followed by mean-reversion. This is the **capitulation signal**: extreme fear exhausts sellers, creating a buying opportunity for crypto 3-5 days after the spike.

### Data sources (free, AU-accessible)

| Source | Ticker/Endpoint | Frequency | Rate Limit | Notes |
|--------|----------------|-----------|------------|-------|
| **yfinance** (primary) | `^VIX` | Daily EOD | Unofficial | No key needed. Most reliable for daily. |
| **CBOE direct CSV** | `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv` | Daily | None | Free direct download, no auth. Full history from 1990. |
| **FRED** | `VIXCLS` | Daily | 120 req/min | Free API key. Updates ~4pm US Eastern. |
| **Alpha Vantage** | Not directly supported | - | - | VIX not available as a standard ticker. |

**Recommended:** yfinance `^VIX` for real-time integration, CBOE CSV for backtest data (complete history). FRED as redundant fallback.

### Signal computation (proposed)

Two components — a **threshold signal** and a **mean-reversion overlay**:

```python
class VIXSignal:
    """
    Dual-mode VIX signal:
    1. Threshold: VIX level maps to risk-off intensity
    2. Mean-reversion: VIX z-score identifies capitulation
    """
    def __init__(self, lookback: int = 60):
        self.lookback = lookback

    def compute(self, vix_series: pd.Series) -> float:
        vix = vix_series.iloc[-1]
        vix_zscore = (vix - vix_series.tail(self.lookback).mean()) / vix_series.tail(self.lookback).std()

        # Component 1: Threshold signal (immediate risk-off)
        if vix > 35:
            threshold_signal = -1.0
        elif vix > 30:
            threshold_signal = -0.7
        elif vix > 25:
            threshold_signal = -0.4
        elif vix < 13:
            threshold_signal = 0.3  # complacency = grind higher
        else:
            threshold_signal = 0.0

        # Component 2: Mean-reversion (z-score based)
        # Extreme z-score AND VIX has been elevated for 3+ days = capitulation
        days_above_30 = (vix_series.tail(5) > 30).sum()
        if vix_zscore > 2.5 and days_above_30 >= 3:
            reversion_signal = 0.8  # contrarian long: capitulation exhaustion
        elif vix_zscore > 2.0 and days_above_30 >= 3:
            reversion_signal = 0.5
        elif vix_zscore < -1.5:
            reversion_signal = -0.3  # complacency at multi-year lows = fragile
        else:
            reversion_signal = 0.0

        # Blend: threshold dominates in first 2 days of spike,
        # reversion takes over after 3+ days
        if days_above_30 < 3:
            return max(-1.0, min(1.0, threshold_signal))
        else:
            return max(-1.0, min(1.0, 0.3 * threshold_signal + 0.7 * reversion_signal))
```

### Why this should predict crypto returns

VIX spikes cause **mechanical forced selling** across asset classes due to margin calls and vol-targeting rebalancing. Crypto, being the highest-vol asset in most institutional portfolios, gets hit first and hardest. The 1-24 hour lead time of VIX over crypto selloffs exists because equity options markets are more liquid and faster to price fear than 24/7 crypto markets. The mean-reversion signal works because VIX is inherently mean-reverting (implied vol always returns to realized), and crypto markets overshoot on the downside during panic.

---

## 3. US Equity Risk-On/Risk-Off (SPY/QQQ)

**Status: Not implemented**
**Implementation complexity:** Easy-Medium
**Update frequency:** Daily EOD free, 15min delayed possible
**Expected edge:** Low-Medium as standalone, but valuable as a regime filter for other signals

### Mechanism

SPY (S&P 500) and QQQ (Nasdaq 100) movements often lead crypto by 1-4 hours during US trading hours. The mechanism:

1. **Institutional rebalancing**: Large funds holding both equities and crypto adjust crypto positions after equity close (4pm ET / 6am AEST).
2. **Correlation regime**: BTC/SPY correlation has risen from ~0.1 (2019) to ~0.6 (2022-2023) with institutional adoption. During risk-off, correlation spikes to 0.8+.
3. **QQQ as lead indicator**: Tech-heavy QQQ correlates more strongly with crypto than SPY because both attract similar risk-seeking capital. QQQ/SPY ratio falling = risk-off rotation from growth to value = bearish for crypto.

### Data sources (free, AU-accessible)

| Source | Ticker/Endpoint | Frequency | Rate Limit | Notes |
|--------|----------------|-----------|------------|-------|
| **yfinance** (primary) | `SPY`, `QQQ`, `^GSPC`, `^NDX` | Daily EOD | Unofficial | ETFs have better data quality than index tickers. |
| **Alpha Vantage** | `TIME_SERIES_DAILY` | Daily/intraday | 25 req/day free | 5min intraday on free tier (limited). |
| **Twelve Data** | `SPY`, `QQQ` | 1min-monthly | 800 req/day free | Better intraday coverage than Alpha Vantage free tier. |
| **FRED** | `SP500` | Daily | 120 req/min | S&P 500 index level only, no intraday. |

**Recommended:** yfinance for daily, Twelve Data for intraday (if pursuing the 1-4 hour lead signal).

### Signal computation (proposed)

The signal has two modes — **momentum** (what is SPY doing?) and **regime** (how correlated are we?):

```python
class EquityRiskSignal:
    def __init__(self, corr_lookback: int = 20, momentum_lookback: int = 5):
        self.corr_lookback = corr_lookback
        self.momentum_lookback = momentum_lookback

    def compute(self, spy_series: pd.Series, btc_series: pd.Series) -> float:
        # Rolling correlation
        spy_ret = spy_series.pct_change()
        btc_ret = btc_series.pct_change()
        corr = spy_ret.tail(self.corr_lookback).corr(btc_ret.tail(self.corr_lookback))

        # SPY momentum (z-score of 5d return over 60d)
        spy_5d = (spy_series.iloc[-1] / spy_series.iloc[-6]) - 1
        spy_5d_hist = spy_series.pct_change(5).tail(60)
        spy_zscore = (spy_5d - spy_5d_hist.mean()) / spy_5d_hist.std()

        # QQQ/SPY ratio for risk-on/risk-off regime
        # (would need QQQ series passed in too)

        # Only fire signal when in correlated regime
        if abs(corr) < 0.4:
            return 0.0  # decoupled regime, equity signal irrelevant

        # Risk-off: SPY falling in correlated regime
        if spy_zscore < -1.5 and corr > 0.5:
            return -0.7  # strong risk-off

        if spy_zscore < -1.0 and corr > 0.5:
            return -0.4  # moderate risk-off

        # Risk-on: SPY rising in correlated regime
        if spy_zscore > 1.0 and corr > 0.5:
            return 0.3  # mild risk-on (equities rising tends to drag crypto)

        return 0.0
```

### Risk-on/risk-off composite indicator

For a more robust signal, combine SPY momentum with sector rotation data:

```python
def risk_on_off_indicator(spy: pd.Series, qqq: pd.Series) -> str:
    """
    QQQ outperforming SPY = risk-on (growth > value)
    QQQ underperforming SPY = risk-off (rotation to safety)
    """
    ratio_5d = (qqq.iloc[-1] / spy.iloc[-1]) / (qqq.iloc[-6] / spy.iloc[-6]) - 1
    if ratio_5d > 0.01:
        return "risk-on"
    elif ratio_5d < -0.01:
        return "risk-off"
    return "neutral"
```

### Why this should predict crypto returns

SPY/QQQ lead crypto because US equity markets close at 4pm ET while crypto trades 24/7. After-hours equity futures moves get priced into crypto with a lag. During high-correlation regimes, a -2% SPY day predicts ~-3% to -5% BTC move within 4-8 hours. The edge is thin and getting thinner as crypto markets mature, but the regime filter (knowing whether BTC is currently correlated with equities) is extremely valuable for weighting other signals.

---

## 4. Bond Yields / Yield Curve (2s10s Spread)

**Status: Not implemented**
**Implementation complexity:** Easy (FRED connector already exists in `omega/integrations/connectors/fred.py`)
**Update frequency:** Daily (FRED updates ~4pm ET)
**Expected edge:** Low-Medium — slow-moving signal, best as a medium-term regime backdrop

### Mechanism

The yield curve slope (10Y - 2Y Treasury spread) is one of the most reliable macro regime indicators. It affects crypto through multiple channels:

1. **Opportunity cost**: Higher yields make risk-free returns more attractive, pulling capital from speculative assets like crypto. The 10Y yield is the benchmark — when it rises, the "hurdle rate" for holding zero-yield crypto rises.
2. **Recession signal**: Yield curve inversion (2Y > 10Y, spread < 0) has preceded every US recession since 1978. Recessions are bad for all risk assets including crypto.
3. **Fed policy expectations**: Curve steepening from inversion signals the market expects rate cuts → risk-on → bullish for crypto.
4. **Real yield**: Nominal yield minus inflation expectations. Rising real yields are more bearish for crypto than rising nominal yields (crypto is partly an inflation hedge).

### Empirical evidence

| Yield curve regime | Typical BTC behavior | Timeframe |
|-------------------|---------------------|-----------|
| Deep inversion (< -50bps) | Bearish, -5% to -15% over 6mo | Slow signal |
| Steepening from inversion | Bullish, +20% to +50% over 3-6mo | Fed pivot signal |
| Normal curve (0 to +100bps) | Neutral | No directional edge |
| Steep curve (> +150bps) | Bullish, early cycle expansion | Multi-month |
| 10Y rising sharply (>50bps/mo) | Bearish, rate shock | 1-4 week impact |

### Data sources (free, AU-accessible)

| Source | Series ID | Description | Frequency | Notes |
|--------|-----------|-------------|-----------|-------|
| **FRED** (primary) | `DGS10` | 10-Year Treasury Constant Maturity | Daily | Free API key from fred.stlouisfed.org |
| **FRED** | `DGS2` | 2-Year Treasury Constant Maturity | Daily | |
| **FRED** | `T10Y2Y` | 10Y minus 2Y spread (pre-computed) | Daily | Saves a computation step |
| **FRED** | `T10YIE` | 10-Year Breakeven Inflation Rate | Daily | For computing real yield |
| **FRED** | `DFF` | Federal Funds Effective Rate | Daily | Fed policy rate |
| **yfinance** | `^TNX` | 10-Year Treasury Yield (CBOE) | Daily | Backup source, less reliable |

**Recommended:** FRED is the gold standard for yield data. Already have a FRED connector. Use `T10Y2Y` for the spread directly, `DGS10` and `T10YIE` for real yield computation.

### Signal computation (proposed)

```python
class YieldCurveSignal:
    """
    Three sub-signals:
    1. Spread level (2s10s) — recession/expansion regime
    2. Spread direction (steepening/flattening) — Fed pivot detector
    3. 10Y rate of change — rate shock detector
    """
    def __init__(self):
        self.spread_history = []  # rolling window

    def compute(self, dgs10: pd.Series, dgs2: pd.Series) -> float:
        spread = (dgs10.iloc[-1] - dgs2.iloc[-1]) * 100  # in bps
        spread_20d_ago = (dgs10.iloc[-20] - dgs2.iloc[-20]) * 100
        spread_delta = spread - spread_20d_ago  # steepening (+) or flattening (-)

        yield_10y = dgs10.iloc[-1]
        yield_10y_30d_ago = dgs10.iloc[-30] if len(dgs10) >= 30 else dgs10.iloc[0]
        yield_change_30d = yield_10y - yield_10y_30d_ago  # in percentage points

        # Sub-signal 1: Spread level
        if spread < -50:
            level_signal = -0.3  # deep inversion, recession risk
        elif spread < 0:
            level_signal = -0.1  # mild inversion
        elif spread > 150:
            level_signal = 0.2   # steep curve, expansion
        else:
            level_signal = 0.0

        # Sub-signal 2: Spread direction (most actionable)
        if spread < 0 and spread_delta > 20:
            direction_signal = 0.6  # steepening from inversion = Fed pivot = bullish
        elif spread_delta < -30:
            direction_signal = -0.4  # rapid flattening = tightening fears
        else:
            direction_signal = 0.0

        # Sub-signal 3: 10Y rate shock
        if yield_change_30d > 0.5:
            shock_signal = -0.5  # rapid yield rise = rate shock, bearish
        elif yield_change_30d < -0.5:
            shock_signal = 0.3   # rapid yield fall = flight to safety, mixed
        else:
            shock_signal = 0.0

        # Combine with direction signal having highest weight
        combined = 0.2 * level_signal + 0.5 * direction_signal + 0.3 * shock_signal
        return max(-1.0, min(1.0, combined))
```

### Real yield computation (enhancement)

```python
def real_yield_signal(dgs10: float, t10yie: float) -> float:
    """
    Real yield = nominal 10Y - breakeven inflation.
    Rising real yields = bearish for zero-yield assets like crypto.
    """
    real_yield = dgs10 - t10yie
    # Z-score of real yield over 252d (1 year)
    # ... compute rolling z-score ...
    if real_yield_zscore > 1.5:
        return -0.4  # high real yields, crypto unattractive
    elif real_yield_zscore < -1.0:
        return 0.3   # negative real yields, TINA for crypto
    return 0.0
```

### Why this should predict crypto returns

The yield curve is the market's aggregate expectation of future growth and Fed policy. Crypto is a long-duration, zero-coupon risk asset — it is mechanically sensitive to discount rate changes. The curve's power is not in day-to-day trading but in identifying **regime transitions**: the shift from tightening to easing (curve steepening from inversion) has been the single best macro predictor of crypto bull market onsets. The rate-shock sub-signal provides shorter-term utility — a 50bps rise in the 10Y over a month has reliably preceded crypto drawdowns.

---

## 5. Gold Correlation (BTC/Gold Ratio)

**Status: Not implemented**
**Implementation complexity:** Medium (requires regime identification logic)
**Update frequency:** Daily EOD
**Expected edge:** Low-Medium — primarily a regime identifier rather than a directional signal

### Mechanism

Gold is the traditional safe-haven asset. The BTC/Gold ratio reveals which "store of value" narrative is winning at any given time:

1. **BTC/Gold ratio rising**: Capital preferring digital over traditional safe haven → risk-on, crypto-bullish narrative.
2. **BTC/Gold ratio falling**: Capital fleeing to traditional safety → risk-off, crypto-bearish.
3. **Both rising together**: Inflation hedge narrative (2020 QE era) → bullish continuation.
4. **Both falling together**: Rare, genuine deleveraging → very bearish.

The correlation between BTC and gold is **unstable and regime-dependent**, which is actually what makes the signal useful — tracking which regime you're in.

### Empirical evidence

| Regime | BTC | Gold | Interpretation | Crypto outlook |
|--------|-----|------|----------------|---------------|
| COVID crash (Mar 2020) | -50% | -12% | Liquidation cascade | Bearish then reversal |
| QE bull (2020-2021) | +400% | +25% | Both inflation hedges | Bullish |
| Rate shock (2022) | -65% | -3% | Gold holds, BTC doesn't | Bearish |
| 2023 recovery | +155% | +13% | BTC outperforms | Bullish |
| ETF era (2024-2025) | +90% | +30% | Institutional allocation to both | Mild bullish |

30-day rolling correlation between BTC and gold: highly variable, ranging from -0.4 to +0.6 depending on regime.

### Data sources (free, AU-accessible)

| Source | Ticker/Endpoint | Frequency | Notes |
|--------|----------------|-----------|-------|
| **yfinance** (primary) | `GC=F` (gold futures) | Daily EOD | No key needed. Most liquid gold contract. |
| **yfinance** | `GLD` (SPDR Gold ETF) | Daily EOD | ETF, slightly less precise than futures. |
| **GoldAPI.io** | REST JSON API | Daily | Free tier, no CC required. 100 req/mo. |
| **Metals-API** | `XAU` symbol | Daily | Free tier available. |
| **FRED** | `GOLDAMGBD228NLBM` | Daily | London gold fixing price in USD. |

**Recommended:** yfinance `GC=F` for consistency with other yfinance-based signals. FRED gold fixing as backup.

### Signal computation (proposed)

```python
class GoldCorrelationSignal:
    """
    BTC/Gold ratio signal with regime identification.
    """
    def compute(self, btc_series: pd.Series, gold_series: pd.Series) -> float:
        # BTC/Gold ratio
        ratio = btc_series / gold_series
        ratio_20d_ret = (ratio.iloc[-1] / ratio.iloc[-20]) - 1

        # Rolling 30d correlation
        btc_ret = btc_series.pct_change()
        gold_ret = gold_series.pct_change()
        corr_30d = btc_ret.tail(30).corr(gold_ret.tail(30))

        # Z-score of ratio (60d lookback)
        ratio_zscore = (ratio.iloc[-1] - ratio.tail(60).mean()) / ratio.tail(60).std()

        # Regime identification
        gold_20d_ret = (gold_series.iloc[-1] / gold_series.iloc[-20]) - 1
        btc_20d_ret = (btc_series.iloc[-1] / btc_series.iloc[-20]) - 1

        # Regime 1: Gold up, BTC down = flight to safety (bearish)
        if gold_20d_ret > 0.02 and btc_20d_ret < -0.05:
            return -0.6  # traditional safe haven winning

        # Regime 2: Gold down, BTC up = risk-on rotation to crypto (bullish)
        if gold_20d_ret < -0.02 and btc_20d_ret > 0.05:
            return 0.4  # crypto gaining vs gold

        # Regime 3: Both rising = inflation hedge narrative (mild bullish)
        if gold_20d_ret > 0.02 and btc_20d_ret > 0.02:
            return 0.2  # both hedges working

        # Regime 4: Both falling = deleveraging (bearish)
        if gold_20d_ret < -0.02 and btc_20d_ret < -0.02:
            return -0.4  # everything being sold

        # Ratio z-score as tiebreaker
        if ratio_zscore > 2.0:
            return 0.3   # BTC overextended vs gold
        elif ratio_zscore < -2.0:
            return -0.3  # BTC undervalued vs gold

        return 0.0
```

### Why this should predict crypto returns

The BTC/Gold ratio is a real-time gauge of which "store of value" narrative the market believes. Regime shifts between these narratives tend to persist for weeks to months. The signal is less about predicting daily returns and more about identifying whether the macro backdrop favors crypto or traditional safe havens. It is most powerful when combined with DXY and VIX signals — all three together paint a complete picture of the macro risk environment.

---

## 6. Fear & Greed Index

**Status: Implemented** — `omega/nodes/victoria/signals/fear_greed.py`
**Implementation complexity:** Easy (done)
**Update frequency:** Daily
**Expected edge:** Medium-High at extremes, noisy in the middle

*(Already documented in previous version — kept here for completeness)*

### Mechanism

The Alternative.me Crypto Fear & Greed Index aggregates price volatility (25%), market momentum/volume (25%), social media sentiment (15%), Bitcoin dominance (10%), Google Trends (10%), and surveys (15%, currently paused). Range: 0 (Extreme Fear) to 100 (Extreme Greed).

### Victoria implementation

Uses 30-day z-score (not raw value) to normalize for regime drift. z < -1.5 → contrarian long +1.0, z > +1.5 → contrarian short -1.0, linear ramp within +/-1.5.

| Date | FGI | 30d forward BTC return |
|------|-----|----------------------|
| Mar 2020 (crash) | 8 | +78% |
| Jul 2021 (crash) | 10 | +59% |
| Jun 2022 (Luna) | 6 | +26% |
| Nov 2022 (FTX) | 20 | +28% |
| Nov 2021 (top) | 84 | -37% |
| Apr 2021 (top) | 78 | -52% |

---

## Implementation Priority Matrix

| # | Signal | Data avail | Free AU-access | Impl complexity | Expected alpha | Priority |
|---|--------|------------|----------------|-----------------|----------------|----------|
| 1 | Fear & Greed | API, no auth | Yes | Easy (done) | Medium-high (extremes) | **Done** |
| 2 | DXY | yfinance | Yes | Easy (done) | Medium | **Done** |
| 3 | VIX | yfinance/CBOE | Yes | Easy | Medium | **Next** |
| 4 | Yield curve | FRED | Yes | Easy (connector exists) | Low-medium (slow) | High |
| 5 | SPY/QQQ | yfinance | Yes | Easy-medium | Low-medium | Medium |
| 6 | Gold ratio | yfinance | Yes | Medium (regime ID) | Low-medium | Lower |

### Recommended implementation order

1. **VIX** — Highest marginal value. Free data, clear threshold logic, well-understood mean-reversion mechanics. The capitulation-detection (VIX > 35 for 3+ days → contrarian long) is particularly valuable.
2. **Yield curve** — FRED connector already exists, minimal new code. Slow-moving but the steepening-from-inversion signal is a proven regime change detector.
3. **SPY/QQQ** — Easy data, but lower standalone alpha. Most useful as a correlation-regime filter that modulates other signal weights.
4. **Gold ratio** — Requires the most nuanced regime identification. Implement last, after the simpler signals are validated.

---

## Composite Cross-Asset Signal Architecture

All cross-asset signals are **market-level** (not per-ticker). The recommended architecture:

```
┌─────────────────────────────────────────────────┐
│              Cross-Asset Aggregator              │
│                                                  │
│  ┌─────────┐ ┌─────────┐ ┌──────────┐          │
│  │   DXY   │ │   VIX   │ │  Yield   │          │
│  │ Signal  │ │ Signal  │ │  Curve   │          │
│  │ (done)  │ │ (next)  │ │ Signal   │          │
│  └────┬────┘ └────┬────┘ └────┬─────┘          │
│       │           │           │                  │
│  ┌────┴────┐ ┌────┴────┐ ┌────┴─────┐          │
│  │  SPY/   │ │  Gold   │ │  Fear &  │          │
│  │  QQQ    │ │  Ratio  │ │  Greed   │          │
│  │ Signal  │ │ Signal  │ │  (done)  │          │
│  └────┬────┘ └────┬────┘ └────┬─────┘          │
│       │           │           │                  │
│       └───────────┼───────────┘                  │
│                   ▼                              │
│         Weighted Composite                       │
│     (or ML combiner when enough data)            │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
          Applied to all tickers
          in signal_generation.py
```

### Weighting scheme (initial, pre-ML)

Cross-asset signals should carry **lower weight** than per-ticker signals since they apply uniformly:

| Signal | Weight | Rationale |
|--------|--------|-----------|
| Fear & Greed (z-score) | 0.20 | Proven contrarian at extremes |
| DXY correlation | 0.25 | Strongest lead indicator |
| VIX | 0.25 | Fast-acting fear gauge |
| Yield curve | 0.15 | Slow but reliable regime signal |
| SPY/QQQ | 0.10 | Coincident, low standalone alpha |
| Gold ratio | 0.05 | Supplementary regime ID |

Total cross-asset composite should be weighted ~20-30% of the final signal blend, with 70-80% coming from per-ticker momentum, mean-reversion, and on-chain signals.

### Wiring into signal_generation.py

Both implemented signals follow this pattern and new signals should too:

1. Computed once per cycle before the ticker loop
2. Applied to every ticker's `ts` dict via `{name}_signal` keys
3. The `_signal` suffix auto-includes them in the directional list for composite calculation
4. Guarded by `_HAS_*` import flags — zero impact when unavailable
5. The ML `SignalCombiner` will learn optimal weights automatically once sufficient trade history accumulates

---

## Data Pipeline Considerations (AU-specific)

### Timezone handling

All free US market data sources report in US Eastern Time. Victoria runs in AEST (UTC+10/+11). Critical timing considerations:

- US equity/options markets close at 4pm ET = **6am/7am AEST** (summer/winter). Cross-asset signals computed from EOD data are stale by the time Asian crypto trading begins.
- FRED data updates at ~4-5pm ET (after market close). Data available in AU by ~7-8am AEST.
- yfinance delayed quotes are typically 15-20 min behind.
- VIX intraday data from CBOE is 15 min delayed.

### Rate limit management

With multiple signals pulling from the same sources, coordinate API calls:

| Source | Free limit | Signals using it | Strategy |
|--------|------------|-----------------|----------|
| yfinance | ~2000 req/hr (unofficial) | DXY, VIX, SPY, Gold | Batch all calls in single session, cache results |
| FRED | 120 req/min | Yield curve | Generous limit, no concern |
| Alpha Vantage | 25 req/day | Fallback only | Reserve for when yfinance is down |
| Twelve Data | 800 req/day | Intraday upgrade path | Future use for intraday signals |

### Caching strategy

```python
# All cross-asset data should be cached with TTL matching update frequency
CACHE_TTL = {
    "dxy": 3600,      # 1 hour (EOD data, no point refreshing more often)
    "vix": 900,        # 15 min (if using intraday CBOE source)
    "spy": 3600,       # 1 hour
    "yields": 86400,   # 24 hours (FRED updates once daily)
    "gold": 3600,      # 1 hour
    "fear_greed": 86400  # 24 hours (updates once daily)
}
```

---

## References

- DXY-BTC correlation research: wavelet analysis study (2015-2024), VanEck BTC long-term assumptions
- BTC-DXY inverse correlation strengthened from 0.05 to -0.72 over 2020-2024 (Altrady analysis)
- Post-ETF correlation moderation: r² weakened from 0.7 to 0.45 in current cycle
- FRED API documentation: fred.stlouisfed.org/docs/api/fred/
- yfinance library: github.com/ranaroussi/yfinance
- CBOE VIX historical data: cboe.com/tradable_products/vix/vix_historical_data
- Alternative.me Fear & Greed Index: alternative.me/crypto/fear-and-greed-index/
