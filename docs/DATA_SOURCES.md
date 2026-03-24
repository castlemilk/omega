# Omega Data Sources

Audited: 2026-03-24

## Status Summary

| Source | Status | Auth Required | Cost | Data Types | Used By |
|--------|--------|---------------|------|------------|---------|
| Binance | ✅ Working | No (public endpoints) | Free | OHLCV, order book, trades, funding rates | Victoria |
| CoinGecko | ✅ Working | No (rate-limited) | Free / Pro $129/mo | Spot prices, market cap, volume | Victoria |
| Polymarket Gamma API | ✅ Working* | No (User-Agent required) | Free | Active/closed markets, prices, volume | Polymarket project |
| Open-Meteo Ensemble | ✅ Working | No | Free | Weather forecasts, 30 ensemble members | Available |
| Deribit | ✅ Working | No (public endpoints) | Free | Options chain, IV, order books (910 BTC instruments) | VRP/IV strategies |
| DefiLlama | ✅ Working | No | Free | Protocol TVL, yields, DeFi metrics (7216 protocols) | Available |
| Coinglass | ❌ Not configured | API key required | $29/mo | OI, funding rates, liquidations, long/short ratio | Planned |
| SN13/Gravity | ❌ Not configured | Signup required | TBD | Social sentiment, on-chain signals | Planned |
| Polymarket Historical Resolutions | ⚠️ Partial | No | Free | Closed markets exist but outcome field unpopulated | Needs scraper |

*Polymarket Gamma API returns HTTP 403 without a User-Agent header — set `User-Agent: Mozilla/5.0 (compatible; omega-research/1.0)` on all requests.

---

## Working Sources — Details

### Binance
- **Base URL**: `https://api.binance.com/api/v3/`
- **Tested**: `GET /klines?symbol=BTCUSDT&interval=1h&limit=5` → 5 candles, latest close ~$70,462
- **Key endpoints**: `/klines`, `/ticker/24hr`, `/depth`, `/trades`, `/fundingRate`
- **Limits**: 1200 req/min unauthenticated, 6000/min with API key
- **Notes**: No key needed for market data. Key only needed for account/trading endpoints.

### CoinGecko
- **Base URL**: `https://api.coingecko.com/api/v3/`
- **Tested**: `GET /simple/price?ids=bitcoin,ethereum&vs_currencies=usd` → BTC $70,497, ETH $2,137
- **Key endpoints**: `/simple/price`, `/coins/markets`, `/coins/{id}/market_chart`
- **Limits**: ~30 req/min free tier (rate-limited, no hard block)
- **Notes**: Free tier adequate for price feeds. Pro needed for historical OHLCV at high frequency.

### Polymarket Gamma API
- **Base URL**: `https://gamma-api.polymarket.com/`
- **Tested**: `GET /markets?active=true&limit=3` → 3 active markets
- **Key endpoints**: `/markets`, `/markets?closed=true`, `/events`
- **Notes**:
  - Requires `User-Agent` header or returns 403
  - Closed markets are queryable but `outcome` field is not populated — `outcomePrices` shows final settlement prices (e.g. `["1","0"]` for Yes/No)
  - Historical resolution requires parsing `outcomePrices` on closed markets, not a dedicated `outcome` field
  - CLOB API (`https://clob.polymarket.com/`) available for order book data

### Open-Meteo Ensemble
- **Base URL**: `https://ensemble-api.open-meteo.com/v1/`
- **Tested**: `GET /ensemble?latitude=40.71&longitude=-74.01&models=gfs_seamless&hourly=temperature_2m&forecast_days=1` → 30 ensemble members
- **Key endpoints**: `/ensemble` (GFS, ECMWF, ICON models)
- **Notes**: Full probabilistic weather forecasts free. Useful for weather-contingent prediction markets.

### Deribit
- **Base URL**: `https://www.deribit.com/api/v2/public/`
- **Tested**: `GET /get_book_summary_by_currency?currency=BTC&kind=option` → 910 BTC option instruments
- **Key endpoints**: `/get_book_summary_by_currency`, `/get_index_price`, `/get_volatility_index_data`
- **Notes**: Full options chain with IV data. No auth needed for public market data. Key needed for trading.

### DefiLlama
- **Base URL**: `https://api.llama.fi/`
- **Tested**: `GET /protocols` → 7,216 protocols
- **Key endpoints**: `/protocols`, `/tvl/{protocol}`, `/yields/pools`, `/stablecoins`
- **Notes**: Comprehensive DeFi on-chain data, entirely free. No rate limit documented.

---

## Not Yet Available

### Coinglass
- **What it provides**: Open interest aggregated across exchanges, funding rates, liquidation heatmaps, long/short ratios, basis
- **Why needed**: Essential for VRP and basis trading strategies
- **Cost**: $29/mo Basic, $79/mo Pro
- **Action**: Sign up at coinglass.com, obtain API key, add to `COINGLASS_API_KEY` env var

### SN13 / Gravity (Bittensor subnet)
- **What it provides**: Social media sentiment, on-chain behavioral signals via Bittensor subnet 13
- **Why needed**: Sentiment overlay for prediction market strategies
- **Cost**: TBD (Bittensor miner fees)
- **Action**: Evaluate API access via Gravity platform or direct subnet query

### Polymarket Historical Resolutions (complete dataset)
- **Problem**: `gamma-api.polymarket.com/markets?closed=true` returns closed markets but `outcome` is null; settlement must be inferred from `outcomePrices`
- **Workaround**: Parse `outcomePrices` — on a binary Yes/No market, `["1","0"]` means Yes resolved, `["0","1"]` means No resolved
- **Better option**: Build a scraper against the Polymarket subgraph or use the CLOB API's settlement endpoint
- **Action**: Implement `outcomePrices` parser in the Polymarket client as short-term fix; evaluate subgraph for complete history

---

## Polymarket Resolution Parsing Note

For closed binary markets, use this logic to determine outcome:

```python
prices = market.get("outcomePrices", ["0", "0"])
outcomes = market.get("outcomes", ["Yes", "No"])
# Winner is the outcome with price == "1"
winner = next((o for o, p in zip(outcomes, prices) if p == "1"), None)
```

Markets where all prices are `"0"` are likely unresolved/voided — filter these out.
