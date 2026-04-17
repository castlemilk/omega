// Package registry — static node catalog.
//
// catalog.go holds the compile-time metadata for every known node type in the
// Omega platform.  Unlike the dynamic NodeRegistry (which tracks live
// registrations and heartbeats), the Catalog is a read-only manifest that
// powers the `omega nodes catalog` CLI command, the generated markdown doc,
// and the machine-readable data/node_registry.json.
package registry

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
	"text/tabwriter"
)

// ── types ─────────────────────────────────────────────────────────────────────

// CatalogEntry is the full static descriptor for one node type.
type CatalogEntry struct {
	Name         string `json:"name"`
	ModulePath   string `json:"module_path"`
	NodeType     string `json:"node_type"`   // signal | strategy | risk | memory | reasoning | execution | platform
	Project      string `json:"project"`     // victoria | polymarket | shared | platform
	Description  string `json:"description"` // 1–2 sentence summary
	Purpose      string `json:"purpose"`     // one-line "why this exists"
	AutonomyLevel int   `json:"autonomy_level"` // 0–4

	// Intelligence flags
	HasMemory    bool `json:"has_memory"`
	HasReasoning bool `json:"has_reasoning"`
	HasReflection bool `json:"has_reflection"`
	UsesBrain    bool `json:"uses_brain"`

	// Data sourcing
	DataSources    []string `json:"data_sources"`
	APIEndpoints   []string `json:"api_endpoints"`
	RequiresAPIKey bool     `json:"requires_api_key"`
	APIKeyName     string   `json:"api_key_name,omitempty"`

	// Hyperparameters
	Parameters      map[string]any `json:"parameters"`
	TunableParams   []string       `json:"tunable_parameters"`

	// Performance (nil = not yet measured)
	CurrentIC      *float64 `json:"current_ic,omitempty"`
	CurrentWeight  *float64 `json:"current_weight,omitempty"`
	WinAttribution *float64 `json:"win_attribution,omitempty"`

	// Research provenance
	References   []CatalogReference `json:"references"`
	InspiredBy   string             `json:"inspired_by,omitempty"`
	ResearchDocs []string           `json:"research_docs"`

	// Version history
	AddedDate    string   `json:"added_date"`
	LastModified string   `json:"last_modified"`
	Version      string   `json:"version"`
	Changelog    []string `json:"changelog"`
}

// CatalogReference is a pointer to an external resource that informed a node's design.
type CatalogReference struct {
	Title     string `json:"title"`
	Authors   string `json:"authors,omitempty"`
	URL       string `json:"url,omitempty"`
	Relevance string `json:"relevance"`
}

// ── helpers ───────────────────────────────────────────────────────────────────

func f64(v float64) *float64 { return &v }

// ── catalog ───────────────────────────────────────────────────────────────────

// Catalog is the compile-time manifest of every known node in the Omega platform.
// Entries are ordered: signals → strategy/execution → intelligence → polymarket → platform.
var Catalog = []CatalogEntry{

	// ── Victoria signal nodes (class-granular) ────────────────────────────────

	{
		Name: "OrderFlowSignal", ModulePath: "omega.nodes.victoria.signals_advanced",
		NodeType: "signal", Project: "victoria",
		Description:   "Computes order-book depth imbalance, cumulative-volume-delta (CVD), and bid-ask spread from Binance L2 order book snapshots.",
		Purpose:       "Detect real-time directional pressure from institutional order flow before price moves.",
		AutonomyLevel: 0, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Binance REST order book (depth 20)", "Binance trade stream"},
		APIEndpoints: []string{"https://api.binance.com/api/v3/depth", "https://api.binance.com/api/v3/trades"},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"depth_levels": 20, "cvd_window": 100, "imbalance_threshold": 0.6},
		TunableParams: []string{"depth_levels", "cvd_window", "imbalance_threshold"},
		CurrentIC: f64(0.146), CurrentWeight: f64(0.123),
		References: []CatalogReference{
			{Title: "Order imbalance based strategy in high frequency trading", Authors: "Cartea, Jaimungal & Penalva 2015", Relevance: "Theoretical basis for bid-ask imbalance as a short-term alpha signal"},
			{Title: "Informed Trading in Futures Markets", Authors: "Ederington & Lee 1993", Relevance: "Order flow imbalance predicts short-term price direction"},
		},
		ResearchDocs: []string{"docs/ideas/simons-alpha-sources.md"},
		AddedDate: "2026-01-15", LastModified: "2026-03-20", Version: "1.2",
		Changelog: []string{"V1.0: bid-ask imbalance only", "V1.1: added CVD", "V1.2: configurable depth levels"},
	},

	{
		Name: "CrossAssetSignal", ModulePath: "omega.nodes.victoria.signals_advanced",
		NodeType: "signal", Project: "victoria",
		Description:   "Measures rolling cross-correlations between BTC, ETH, SOL and SPY to detect regime shifts via co-movement changes.",
		Purpose:       "Identify when crypto decouples from equities or when ETH/SOL lead BTC — exploitable short-term divergences.",
		AutonomyLevel: 0, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Binance OHLCV (BTC/ETH/SOL)", "Yahoo Finance SPY daily"},
		APIEndpoints: []string{"https://api.binance.com/api/v3/klines"},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"window": 30, "symbols": []string{"BTCUSDT", "ETHUSDT", "SOLUSDT"}, "equity_symbol": "SPY"},
		TunableParams: []string{"window"},
		CurrentIC: f64(0.093), CurrentWeight: f64(0.081),
		References: []CatalogReference{
			{Title: "Cross-asset signals in quantitative trading", Authors: "Asness, Moskowitz & Pedersen 2013", Relevance: "Cross-asset momentum and correlation timing"},
			{Title: "Crypto–equity correlation dynamics", Authors: "Corbet et al. 2021", Relevance: "BTC-SPY correlation regime changes during market stress"},
		},
		ResearchDocs: []string{"docs/ideas/simons-alpha-sources.md"},
		AddedDate: "2026-01-15", LastModified: "2026-03-10", Version: "1.1",
		Changelog: []string{"V1.0: BTC/ETH only", "V1.1: added SOL + SPY"},
	},

	{
		Name: "MicrostructureSignal", ModulePath: "omega.nodes.victoria.signals_advanced",
		NodeType: "signal", Project: "victoria",
		Description:   "Estimates effective bid-ask spread, Kyle's lambda (price impact), and trade intensity from tick-level Binance data.",
		Purpose:       "Measure market liquidity and execution cost regime — widens before large moves, tightens in trending markets.",
		AutonomyLevel: 0, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Binance aggTrades stream", "Binance order book"},
		APIEndpoints: []string{"https://api.binance.com/api/v3/aggTrades"},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"trade_window": 500, "lambda_window": 100},
		TunableParams: []string{"trade_window", "lambda_window"},
		CurrentIC: f64(0.071),
		References: []CatalogReference{
			{Title: "Continuous Auctions and Insider Trading", Authors: "Kyle 1985", Relevance: "Lambda (price impact coefficient) from Kyle model"},
			{Title: "A New Approach to Measuring Financial Contagion", Authors: "Forbes & Rigobon 2002", Relevance: "Spread-based microstructure regime classification"},
		},
		ResearchDocs: []string{},
		AddedDate: "2026-02-01", LastModified: "2026-03-10", Version: "1.0",
		Changelog: []string{"V1.0: initial"},
	},

	{
		Name: "SentimentSignal", ModulePath: "omega.nodes.victoria.signals_advanced",
		NodeType: "signal", Project: "victoria",
		Description:   "Aggregates the Fear & Greed Index (alternative.me) and CryptoPanic bullish/bearish vote ratio into a composite sentiment score.",
		Purpose:       "Contrarian and trend-confirming signal — extreme fear predicts reversals, moderate fear trends with momentum.",
		AutonomyLevel: 0, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"alternative.me Fear & Greed API", "CryptoPanic API votes"},
		APIEndpoints: []string{"https://api.alternative.me/fng/", "https://cryptopanic.com/api/v1/posts/"},
		RequiresAPIKey: true, APIKeyName: "CRYPTOPANIC_API_KEY",
		Parameters:    map[string]any{"fear_extreme_threshold": 20, "greed_extreme_threshold": 80, "vote_window": 24},
		TunableParams: []string{"fear_extreme_threshold", "greed_extreme_threshold"},
		CurrentIC: f64(0.058),
		References: []CatalogReference{
			{Title: "Investor sentiment and the cross-section of stock returns", Authors: "Baker & Wurgler 2006", Relevance: "Sentiment as contrarian signal at extremes"},
			{Title: "Speculative Betas", Authors: "Hong & Sraer 2016", Relevance: "Sentiment-driven mispricing in high-beta assets"},
		},
		ResearchDocs: []string{"docs/ideas/simons-alpha-sources.md"},
		AddedDate: "2026-01-20", LastModified: "2026-03-15", Version: "1.1",
		Changelog: []string{"V1.0: F&G only", "V1.1: added CryptoPanic votes"},
	},

	{
		Name: "SignalGenerationNode", ModulePath: "omega.nodes.victoria.signal_generation",
		NodeType: "signal", Project: "victoria",
		Description:   "Computes classical technical indicators: SMA crossover, RSI, MACD, Bollinger Bands, and volume momentum from OHLCV data. Self-improving via improve() — currently stuck at v1.0 (improve() never called by orchestrator).",
		Purpose:       "Baseline technical signal suite that provides fundamental price-action context for the ensemble.",
		AutonomyLevel: 1, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Binance OHLCV REST"},
		APIEndpoints: []string{"https://api.binance.com/api/v3/klines"},
		RequiresAPIKey: false,
		Parameters: map[string]any{
			"sma_fast": 10, "sma_slow": 30,
			"rsi_window": 14, "rsi_overbought": 70, "rsi_oversold": 30,
			"macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
			"bb_window": 20, "bb_num_std": 2.0,
			"volume_window": 20,
		},
		TunableParams: []string{"sma_fast", "sma_slow", "rsi_window", "rsi_overbought", "rsi_oversold", "macd_fast", "macd_slow", "bb_window"},
		CurrentIC: f64(0.104), CurrentWeight: f64(0.092),
		References: []CatalogReference{
			{Title: "Technical Analysis of the Financial Markets", Authors: "Murphy 1999", Relevance: "SMA/RSI/MACD baseline indicator definitions"},
			{Title: "151 Formulas for Algorithmic Trading Strategies", Authors: "Kakushadze & Serur 2018", Relevance: "Formulas 1–15: momentum and trend indicators"},
		},
		ResearchDocs: []string{},
		AddedDate: "2026-01-10", LastModified: "2026-03-01", Version: "1.0",
		Changelog: []string{"V1.0: SMA + RSI + MACD + BB + volume (v1.1–v1.3 implemented but never unlocked)"},
	},

	{
		Name: "MarketDataSignal", ModulePath: "omega.nodes.victoria.market_data_signals",
		NodeType: "signal", Project: "victoria",
		Description:   "Computes price returns (1h, 4h, 24h), realized volatility, and momentum scores from raw OHLCV.",
		Purpose:       "Foundation signal layer: price-based features consumed by all higher-level nodes.",
		AutonomyLevel: 0, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Binance OHLCV REST"},
		APIEndpoints: []string{"https://api.binance.com/api/v3/klines"},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"return_windows": []int{1, 4, 24, 168}, "vol_window": 30},
		TunableParams: []string{"vol_window"},
		CurrentIC: f64(0.104),
		References: []CatalogReference{
			{Title: "Returns to Buying Winners and Selling Losers", Authors: "Jegadeesh & Titman 1993", Relevance: "Cross-sectional momentum from return windows"},
		},
		ResearchDocs: []string{},
		AddedDate: "2026-01-10", LastModified: "2026-02-15", Version: "1.0",
		Changelog: []string{"V1.0: initial"},
	},

	{
		Name: "VRPSignal", ModulePath: "omega.nodes.victoria.vrp_signal",
		NodeType: "signal", Project: "victoria",
		Description:   "Computes the Volatility Risk Premium as the spread between 30-day implied volatility (Deribit ATM options) and subsequent realized volatility. Generates a carry regime signal when VRP is positive.",
		Purpose:       "Exploit systematic overpricing of options — positive VRP regime favours vol-selling and mean-reversion strategies.",
		AutonomyLevel: 1, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Deribit options REST", "Binance OHLCV (realized vol)"},
		APIEndpoints: []string{"https://www.deribit.com/api/v2/public/get_ticker"},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"iv_window": 30, "rv_window": 30, "vrp_zscore_threshold": 1.0},
		TunableParams: []string{"iv_window", "rv_window", "vrp_zscore_threshold"},
		CurrentIC: f64(0.118), CurrentWeight: f64(0.089),
		References: []CatalogReference{
			{Title: "The Variance Risk Premium", Authors: "Bollerslev, Tauchen & Zhou 2009", Relevance: "VRP measurement and its predictive content for equity returns"},
			{Title: "Volatility Risk Premia and Future Stock Returns", Authors: "Carr & Wu 2009", Relevance: "Cross-sectional and time-series VRP as alpha signal"},
		},
		InspiredBy:   "Christensen & Prabhala 1998 — implied vol as biased forecast of realized vol",
		ResearchDocs: []string{"docs/ideas/geometric-mathematics-for-trading.md"},
		AddedDate: "2026-02-10", LastModified: "2026-03-20", Version: "1.1",
		Changelog: []string{"V1.0: raw VRP", "V1.1: z-score normalization + regime output"},
	},

	{
		Name: "FundingRateSignal", ModulePath: "omega.nodes.victoria.alt_data_signals",
		NodeType: "signal", Project: "victoria",
		Description:   "Reads Binance perpetual swap funding rates (8-hourly) and computes a rolling z-score to signal crowded long/short positioning.",
		Purpose:       "Funding extremes predict mean-reversion — highly positive funding means crowded longs about to unwind.",
		AutonomyLevel: 0, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Binance futures funding rate API"},
		APIEndpoints: []string{"https://fapi.binance.com/fapi/v1/fundingRate"},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"zscore_window": 90, "extreme_threshold": 2.0},
		TunableParams: []string{"zscore_window", "extreme_threshold"},
		CurrentIC: f64(0.082), CurrentWeight: f64(0.071),
		References: []CatalogReference{
			{Title: "The Cross-Section of Cryptocurrency Returns", Authors: "Liu, Tsyvinski & Wu 2022", Relevance: "Funding rate as carry signal in crypto perpetuals"},
		},
		ResearchDocs: []string{"docs/ideas/simons-alpha-sources.md"},
		AddedDate: "2026-01-20", LastModified: "2026-03-10", Version: "1.0",
		Changelog: []string{"V1.0: initial"},
	},

	{
		Name: "OpenInterestSignal", ModulePath: "omega.nodes.victoria.alt_data_signals",
		NodeType: "signal", Project: "victoria",
		Description:   "Tracks Binance perpetual open interest change (1h delta and 24h delta) as a proxy for new speculative capital entering or leaving the market.",
		Purpose:       "Rising OI with rising price = trend confirmation; rising OI with falling price = increasing shorts / bearish.",
		AutonomyLevel: 0, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Binance futures open interest API"},
		APIEndpoints: []string{"https://fapi.binance.com/fapi/v1/openInterest", "https://fapi.binance.com/futures/data/openInterestHist"},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"delta_window_hours": []int{1, 4, 24}},
		TunableParams: []string{},
		CurrentIC: f64(0.067),
		References: []CatalogReference{
			{Title: "Open Interest and Futures Price Volatility", Authors: "Bessembinder & Seguin 1992", Relevance: "OI as proxy for speculative participation and volatility regime"},
		},
		ResearchDocs: []string{},
		AddedDate: "2026-01-25", LastModified: "2026-02-20", Version: "1.0",
		Changelog: []string{"V1.0: initial"},
	},

	{
		Name: "MacroSignal", ModulePath: "omega.nodes.victoria.macro_signals",
		NodeType: "signal", Project: "victoria",
		Description:   "Ingests US macro data from FRED: M2 money supply growth, federal funds rate, real 10Y yield, 2s10s yield curve, DXY, and Fed net liquidity (assets minus RRP minus TGA).",
		Purpose:       "Regime signal — crypto bull markets historically correlate with monetary expansion and falling real yields.",
		AutonomyLevel: 0, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"FRED API (M2SL, FEDFUNDS, DFII10, T10Y2Y, DTWEXBGS)", "FRED balance sheet series"},
		APIEndpoints: []string{"https://api.stlouisfed.org/fred/series/observations"},
		RequiresAPIKey: true, APIKeyName: "FRED_API_KEY",
		Parameters: map[string]any{
			"series": []string{"M2SL", "FEDFUNDS", "DFII10", "T10Y2Y", "DTWEXBGS"},
			"smoothing_window": 4,
		},
		TunableParams: []string{"smoothing_window"},
		References: []CatalogReference{
			{Title: "The Fed Model: A Note", Authors: "Asness 2003", Relevance: "Fed liquidity and real yield impact on risk asset valuations"},
			{Title: "Global Liquidity and Bitcoin", Authors: "Cieslak & Schrimpf 2022", Relevance: "Net liquidity measure as crypto price predictor"},
		},
		ResearchDocs: []string{"docs/ideas/simons-alpha-sources.md"},
		AddedDate: "2026-02-05", LastModified: "2026-03-15", Version: "1.0",
		Changelog: []string{"V1.0: initial"},
	},

	{
		Name: "OptionsSignal", ModulePath: "omega.nodes.victoria.options_signals",
		NodeType: "signal", Project: "victoria",
		Description:   "Fetches Deribit BTC/ETH options data to compute gamma exposure (GEX), put/call ratio, IV skew (25-delta RR), max pain price, and term structure slope.",
		Purpose:       "Options market provides institutional positioning signals — GEX pinning, skew as tail-risk proxy, max pain as gravitational level.",
		AutonomyLevel: 0, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Deribit options REST API"},
		APIEndpoints: []string{"https://www.deribit.com/api/v2/public/get_book_summary_by_currency", "https://www.deribit.com/api/v2/public/get_instruments"},
		RequiresAPIKey: false,
		Parameters: map[string]any{
			"expiry_window_days": 30,
			"delta_threshold":    0.25,
			"gex_flip_threshold": 0.0,
		},
		TunableParams: []string{"expiry_window_days"},
		References: []CatalogReference{
			{Title: "Gamma Exposure and Market Maker Hedging", Authors: "Bouchaud & Potters 2003", Relevance: "GEX pinning effect near large gamma strikes"},
			{Title: "The Information Content of the Implied Volatility Term Structure", Authors: "Mixon 2007", Relevance: "IV term structure slope as forward-looking fear indicator"},
		},
		InspiredBy:   "SpotGamma GEX methodology",
		ResearchDocs: []string{"docs/ideas/geometric-mathematics-for-trading.md"},
		AddedDate: "2026-02-15", LastModified: "2026-03-20", Version: "1.1",
		Changelog: []string{"V1.0: put/call + skew", "V1.1: GEX + max pain + term structure"},
	},

	{
		Name: "DerivativesSignal", ModulePath: "omega.nodes.victoria.derivatives_signals",
		NodeType: "signal", Project: "victoria",
		Description:   "Computes futures basis (spot-perp spread), funding rate carry, and basis term structure from Binance quarterly and perpetual contracts.",
		Purpose:       "Basis and carry signals capture institutional term-structure expectations — contango/backwardation regime detection.",
		AutonomyLevel: 0, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Binance futures REST", "Binance perp funding rate"},
		APIEndpoints: []string{"https://fapi.binance.com/fapi/v1/ticker/price", "https://fapi.binance.com/fapi/v1/fundingRate"},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"basis_window": 24, "carry_annualize": true},
		TunableParams: []string{"basis_window"},
		CurrentIC: f64(0.076),
		References: []CatalogReference{
			{Title: "Carry Trades and Global FX Volatility", Authors: "Menkhoff et al. 2012", Relevance: "Carry strategy returns and crash risk in derivative markets"},
		},
		ResearchDocs: []string{},
		AddedDate: "2026-02-01", LastModified: "2026-03-10", Version: "1.0",
		Changelog: []string{"V1.0: initial"},
	},

	{
		Name: "LiquidationSignal", ModulePath: "omega.nodes.victoria.liquidation_signals",
		NodeType: "signal", Project: "victoria",
		Description:   "Fetches Coinglass and Bybit liquidation data to compute cascade risk scores — proximity to large liquidation clusters predicts volatility spikes.",
		Purpose:       "Liquidation clusters act as price magnets; signals proximity to cascades for risk management and momentum entries.",
		AutonomyLevel: 1, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Coinglass liquidation heatmap API", "Bybit risk limit tiers"},
		APIEndpoints: []string{"https://open-api.coinglass.com/public/v2/liquidation_chart"},
		RequiresAPIKey: true, APIKeyName: "COINGLASS_API_KEY",
		Parameters:    map[string]any{"cluster_radius_pct": 1.5, "history_days": 7},
		TunableParams: []string{"cluster_radius_pct"},
		CurrentIC: f64(0.089),
		References: []CatalogReference{
			{Title: "Fire Sales in a Model of Complexity", Authors: "Caballero & Simsek 2013", Relevance: "Liquidation cascade mechanics in leveraged markets"},
		},
		ResearchDocs: []string{"docs/ideas/simons-alpha-sources.md"},
		AddedDate: "2026-02-10", LastModified: "2026-03-15", Version: "1.1",
		Changelog: []string{"V1.0: Coinglass only", "V1.1: Bybit levels + historical window"},
	},

	{
		Name: "LiquidationCascadeSignal", ModulePath: "omega.nodes.victoria.liquidation_cascade",
		NodeType: "signal", Project: "victoria",
		Description:   "Models the amplification factor of liquidation cascades using historical price-liquidation co-movements. Outputs a cascade amplification score and estimated cascade radius.",
		Purpose:       "Predict second-order liquidation effects beyond the initial cluster — cascade risk > 1 means hedging required.",
		AutonomyLevel: 2, HasMemory: true, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Coinglass historical liquidations", "Binance OHLCV"},
		APIEndpoints: []string{"https://open-api.coinglass.com/public/v2/liquidation_chart"},
		RequiresAPIKey: true, APIKeyName: "COINGLASS_API_KEY",
		Parameters:    map[string]any{"history_days": 30, "min_cluster_size_usd": 1_000_000, "amplification_decay": 0.9},
		TunableParams: []string{"history_days", "amplification_decay"},
		CurrentIC: f64(0.096),
		References: []CatalogReference{
			{Title: "Systemic Risk and Liquidation Cascades", Authors: "Brunnermeier & Pedersen 2009", Relevance: "Liquidity spirals and cascade amplification in leveraged systems"},
		},
		ResearchDocs: []string{},
		AddedDate: "2026-02-20", LastModified: "2026-03-20", Version: "1.0",
		Changelog: []string{"V1.0: initial with historical learning"},
	},

	{
		Name: "StablecoinSignal", ModulePath: "omega.nodes.victoria.stablecoin_signals",
		NodeType: "signal", Project: "victoria",
		Description:   "Tracks USDT and USDC on-chain supply growth via DeFiLlama, plus Tether premium (USDT/USD on OTC markets) as a measure of crypto market demand.",
		Purpose:       "Stablecoin inflows signal fresh capital entering crypto; Tether premium above 1% historically precedes bull runs.",
		AutonomyLevel: 0, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"DeFiLlama stablecoin API", "CoinGecko USDT price"},
		APIEndpoints: []string{"https://stablecoins.llama.fi/stablecoins", "https://api.coingecko.com/api/v3/simple/price"},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"supply_window": 7, "premium_threshold": 0.002},
		TunableParams: []string{"supply_window"},
		CurrentIC: f64(0.054),
		References: []CatalogReference{
			{Title: "Is Bitcoin Really Untethered?", Authors: "Griffin & Shams 2020", Relevance: "USDT issuance as demand signal and price predictor"},
		},
		ResearchDocs: []string{},
		AddedDate: "2026-02-15", LastModified: "2026-03-10", Version: "1.0",
		Changelog: []string{"V1.0: initial"},
	},

	{
		Name: "NewsSignal", ModulePath: "omega.nodes.victoria.news_signals",
		NodeType: "signal", Project: "victoria",
		Description:   "Aggregates CryptoPanic API headlines and RSS feeds, applies VADER sentiment NLP, and learns per-source reliability weights from outcome feedback.",
		Purpose:       "News-driven price gaps are exploitable in the first 30 minutes — source reliability weighting filters noise.",
		AutonomyLevel: 1, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"CryptoPanic API", "CoinDesk RSS", "CoinTelegraph RSS"},
		APIEndpoints: []string{"https://cryptopanic.com/api/v1/posts/"},
		RequiresAPIKey: true, APIKeyName: "CRYPTOPANIC_API_KEY",
		Parameters: map[string]any{
			"lookback_hours": 2,
			"min_importance": "medium",
			"vader_compound_threshold": 0.05,
		},
		TunableParams: []string{"lookback_hours", "vader_compound_threshold"},
		CurrentIC: f64(0.045),
		References: []CatalogReference{
			{Title: "The Impact of News Sentiment on Cryptocurrency Markets", Authors: "Kraaijeveld & De Smedt 2020", Relevance: "News sentiment predictive content for BTC/ETH"},
		},
		ResearchDocs: []string{},
		AddedDate: "2026-02-01", LastModified: "2026-03-15", Version: "1.1",
		Changelog: []string{"V1.0: VADER on all sources equally", "V1.1: per-source reliability weights learned from feedback"},
	},

	{
		Name: "TwitterSignal", ModulePath: "omega.nodes.victoria.twitter_signals",
		NodeType: "signal", Project: "victoria",
		Description:   "Reads CryptoCompare social stats API for tweet volume, Reddit activity, and social dominance scores for BTC/ETH/SOL.",
		Purpose:       "Social volume spikes predict volatility; social dominance shifts predict capital rotation between tokens.",
		AutonomyLevel: 1, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"CryptoCompare Social Stats API"},
		APIEndpoints: []string{"https://min-api.cryptocompare.com/data/social/coin/histo/hour"},
		RequiresAPIKey: true, APIKeyName: "CC_API_KEY",
		Parameters:    map[string]any{"zscore_window": 48, "spike_threshold": 2.5},
		TunableParams: []string{"zscore_window", "spike_threshold"},
		CurrentIC: f64(0.038),
		References: []CatalogReference{
			{Title: "Twitter Sentiment and the Stock Market", Authors: "Bollen, Mao & Zeng 2011", Relevance: "Social sentiment as leading predictor of price moves"},
		},
		ResearchDocs: []string{},
		AddedDate: "2026-02-01", LastModified: "2026-03-10", Version: "1.0",
		Changelog: []string{"V1.0: initial"},
	},

	{
		Name: "OnChainSignal", ModulePath: "omega.nodes.victoria.onchain_data",
		NodeType: "signal", Project: "victoria",
		Description:   "Pulls on-chain metrics from ErcinDedeoglu's GitHub dataset and CryptoQuant: MVRV Z-score, Puell Multiple, exchange netflow, taker buy/sell ratio, and Coinbase premium index.",
		Purpose:       "On-chain signals reflect holder behaviour and miner economics — MVRV and Puell are primary cycle peak/trough indicators.",
		AutonomyLevel: 1, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"ErcinDedeoglu GitHub (bitcoin-on-chain-indicators)", "CryptoQuant exchange netflow", "Binance taker ratio API"},
		APIEndpoints: []string{
			"https://raw.githubusercontent.com/coinmetrics/data/master/csv/",
			"https://fapi.binance.com/futures/data/takerlongshortRatio",
		},
		RequiresAPIKey: false,
		Parameters: map[string]any{
			"mvrv_overvalued_threshold": 3.5,
			"mvrv_undervalued_threshold": 1.0,
			"puell_extreme_high": 4.0,
			"puell_extreme_low": 0.5,
			"netflow_window": 7,
		},
		TunableParams: []string{"mvrv_overvalued_threshold", "mvrv_undervalued_threshold"},
		CurrentIC: f64(0.096), CurrentWeight: f64(0.085),
		References: []CatalogReference{
			{Title: "The Bitcoin Network Momentum and Value Cycles", Authors: "Plan B 2019", Relevance: "MVRV as market cycle indicator for BTC"},
			{Title: "Puell Multiple as a Mining-Driven Cycle Indicator", Authors: "Dedeoglu 2019", URL: "https://github.com/ercindedeoglu/bitcoin-on-chain", Relevance: "Miner revenue relative to 365-day average as cycle signal"},
		},
		ResearchDocs: []string{"docs/ideas/simons-alpha-sources.md"},
		AddedDate: "2026-01-25", LastModified: "2026-03-20", Version: "1.2",
		Changelog: []string{"V1.0: MVRV + Puell", "V1.1: exchange netflow", "V1.2: Coinbase premium + taker ratio"},
	},

	{
		Name: "InformationFlowSignal", ModulePath: "omega.nodes.victoria.information_flow",
		NodeType: "signal", Project: "victoria",
		Description:   "Computes transfer entropy from BTC returns to ETH and SOL returns to detect which asset is the current information leader.",
		Purpose:       "BTC-dominance regime detection via information causality — when ETH leads, alt-season dynamics apply.",
		AutonomyLevel: 1, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Binance OHLCV (BTC/ETH/SOL)"},
		APIEndpoints: []string{"https://api.binance.com/api/v3/klines"},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"window": 120, "lag": 1, "bins": 10},
		TunableParams: []string{"window", "lag"},
		CurrentIC: f64(0.062),
		References: []CatalogReference{
			{Title: "Information Transfer Between Stock Market Sectors", Authors: "Kwon & Yang 2008", Relevance: "Transfer entropy methodology for financial time series"},
			{Title: "151 Formulas for Algorithmic Trading Strategies", Authors: "Kakushadze & Serur 2018", Relevance: "Formula 103: information ratio and cross-asset information flow"},
		},
		ResearchDocs: []string{"docs/ideas/geometric-mathematics-for-trading.md"},
		AddedDate: "2026-02-20", LastModified: "2026-03-15", Version: "1.0",
		Changelog: []string{"V1.0: initial"},
	},

	{
		Name: "DisagreementSignal", ModulePath: "omega.nodes.victoria.disagreement_signal",
		NodeType: "signal", Project: "victoria",
		Description:   "Measures the pairwise disagreement entropy across all signal outputs in the current cycle. High disagreement indicates regime uncertainty; low disagreement indicates consensus.",
		Purpose:       "Meta-signal: when all signals agree, conviction is high; when they disagree, reduce position size.",
		AutonomyLevel: 0, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Internal signal bus (no external API)"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"entropy_bins": 5, "disagreement_threshold": 0.7},
		TunableParams: []string{"disagreement_threshold"},
		References: []CatalogReference{
			{Title: "Analyst Disagreement and Return Predictability", Authors: "Diether, Malloy & Scherbina 2002", Relevance: "Disagreement among forecasters as uncertainty proxy"},
		},
		ResearchDocs: []string{},
		AddedDate: "2026-03-01", LastModified: "2026-03-15", Version: "1.0",
		Changelog: []string{"V1.0: initial"},
	},

	{
		Name: "WassersteinRegimeSignal", ModulePath: "omega.nodes.victoria.wasserstein_regime",
		NodeType: "signal", Project: "victoria",
		Description:   "Uses optimal transport (Wasserstein-2 distance) between rolling 30-day correlation matrices to detect regime transitions — large distance = regime change.",
		Purpose:       "Model-free regime detection that is sensitive to structural breaks in cross-asset correlations, not just return distributions.",
		AutonomyLevel: 1, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Binance OHLCV (BTC/ETH/SOL/BNB)"},
		APIEndpoints: []string{"https://api.binance.com/api/v3/klines"},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"window": 30, "overlap": 5, "distance_threshold": 0.15},
		TunableParams: []string{"window", "distance_threshold"},
		CurrentIC: f64(0.078),
		References: []CatalogReference{
			{Title: "Optimal Transport: Old and New", Authors: "Villani 2009", Relevance: "Wasserstein distance theory for probability distributions"},
			{Title: "Wasserstein Distance for Portfolio Regime Detection", Authors: "Marti et al. 2021", Relevance: "Financial correlation matrix comparison via optimal transport"},
		},
		InspiredBy:   "Marti et al. 2021 — applying Wasserstein distance to financial correlation matrices",
		ResearchDocs: []string{"docs/ideas/geometric-mathematics-for-trading.md"},
		AddedDate: "2026-03-05", LastModified: "2026-03-20", Version: "1.0",
		Changelog: []string{"V1.0: initial Wasserstein-2 on Pearson correlation matrices"},
	},

	{
		Name: "RMTDenoiserNode", ModulePath: "omega.nodes.victoria.rmt_denoiser",
		NodeType: "signal", Project: "victoria",
		Description:   "Applies Random Matrix Theory (Marchenko-Pastur law) to eigenvalue-clean the signal correlation matrix, separating true signal structure from noise.",
		Purpose:       "Noise in correlation matrices degrades portfolio construction — RMT cleaning extracts the true factor structure.",
		AutonomyLevel: 1, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Internal signal bus (correlation matrix of all signals)"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"q_ratio": 0.5, "eigenvalue_clip": "marchenko_pastur"},
		TunableParams: []string{"q_ratio"},
		References: []CatalogReference{
			{Title: "Distribution of eigenvalues for some sets of random matrices", Authors: "Marchenko & Pastur 1967", Relevance: "Foundational RMT result defining the noise eigenvalue bulk"},
			{Title: "Noise Dressing of Financial Correlation Matrices", Authors: "Laloux et al. 1999", Relevance: "Application of RMT to financial covariance matrix cleaning"},
		},
		InspiredBy:   "Laloux et al. 1999 — RMT correlation matrix cleaning for portfolio optimization",
		ResearchDocs: []string{"docs/ideas/geometric-mathematics-for-trading.md", "docs/ideas/quantscience-library-research.md"},
		AddedDate: "2026-03-10", LastModified: "2026-03-25", Version: "1.0",
		Changelog: []string{"V1.0: Marchenko-Pastur eigenvalue clipping on signal correlation matrix"},
	},

	{
		Name: "FactorModelNode", ModulePath: "omega.nodes.victoria.factor_model",
		NodeType: "signal", Project: "victoria",
		Description:   "Decomposes the signal matrix into orthogonal PCA factors and computes each signal's factor loadings for risk attribution.",
		Purpose:       "Identify correlated risk clusters in the signal ensemble — prevent doubling up on the same underlying risk factor.",
		AutonomyLevel: 0, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Internal signal bus"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"n_components": 5, "explained_variance_threshold": 0.85},
		TunableParams: []string{"n_components"},
		References: []CatalogReference{
			{Title: "Risk Models and Their Uses", Authors: "Ross 1976", Relevance: "APT factor model as basis for risk decomposition"},
			{Title: "151 Formulas for Algorithmic Trading Strategies", Authors: "Kakushadze & Serur 2018", Relevance: "Formula 78: PCA-based risk factor construction"},
		},
		ResearchDocs: []string{"docs/ideas/geometric-mathematics-for-trading.md"},
		AddedDate: "2026-03-10", LastModified: "2026-03-20", Version: "1.0",
		Changelog: []string{"V1.0: initial PCA factor decomposition"},
	},

	// ── Victoria strategy / execution nodes (file-granular) ──────────────────

	{
		Name: "VictoriaNode", ModulePath: "omega.nodes.victoria.victoria_node",
		NodeType: "strategy", Project: "victoria",
		Description:   "Top-level Victoria trading node. Composes all signal subsystems, applies IC-weighted ensemble scoring, routes through DebateGate adversarial filter, and constructs final portfolio. Supports pico/supervised/autonomous modes.",
		Purpose:       "The orchestrating node that turns a signal ensemble into a position. Brain optional.",
		AutonomyLevel: 3, HasMemory: true, HasReasoning: true, HasReflection: true, UsesBrain: true,
		DataSources: []string{"All signal subsystems", "SignalBus", "MemoryBus"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"mode": "pico", "conviction_threshold": 0.3, "max_position_pct": 0.1},
		TunableParams: []string{"conviction_threshold", "max_position_pct"},
		CurrentIC: f64(0.147),
		References: []CatalogReference{
			{Title: "The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market", Authors: "Thorp 1997", Relevance: "Kelly-based position sizing as core portfolio construction method"},
		},
		ResearchDocs: []string{"docs/architecture.md", "docs/v14_results.md"},
		AddedDate: "2026-01-10", LastModified: "2026-03-27", Version: "3.4",
		Changelog: []string{"V1: single-signal", "V2: ensemble + IC weights", "V3: DebateGate + MemoryBus", "V3.4: pico baseline + regime multipliers"},
	},

	{
		Name: "StrategyNode", ModulePath: "omega.nodes.victoria.strategy",
		NodeType: "strategy", Project: "victoria",
		Description:   "Reads peer signals from SignalBus and VictoriaNode output to construct Kelly-optimal portfolio with regime-aware position scaling.",
		Purpose:       "Translates conviction scores into executable position sizes respecting risk limits.",
		AutonomyLevel: 3, HasMemory: true, HasReasoning: false, HasReflection: false, UsesBrain: true,
		DataSources: []string{"SignalBus", "RegimeDetectorNode output"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"kelly_fraction": 0.25, "max_leverage": 3.0, "regime_scale_bull": 1.2, "regime_scale_bear": 0.6},
		TunableParams: []string{"kelly_fraction", "max_leverage", "regime_scale_bull", "regime_scale_bear"},
		ResearchDocs: []string{"docs/architecture.md"},
		AddedDate: "2026-01-15", LastModified: "2026-03-20", Version: "2.1",
		Changelog: []string{"V1: fixed Kelly", "V2: regime-aware scaling", "V2.1: SignalBus peer reads"},
	},

	{
		Name: "RegimeDetectorNode", ModulePath: "omega.nodes.victoria.regime_detector",
		NodeType: "strategy", Project: "victoria",
		Description:   "Classifies market into bullish/bearish/neutral/crisis regimes using HMM with Gaussian emissions on log-returns and realized volatility.",
		Purpose:       "All downstream signal multipliers and position sizes are conditioned on regime — getting this right is critical.",
		AutonomyLevel: 2, HasMemory: true, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Binance OHLCV", "WassersteinRegimeSignal output"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"n_regimes": 4, "hmm_n_iter": 100, "vol_lookback": 30},
		TunableParams: []string{"n_regimes", "vol_lookback"},
		References: []CatalogReference{
			{Title: "A New Approach to the Economic Analysis of Nonstationary Time Series", Authors: "Hamilton 1989", Relevance: "Hidden Markov Model for regime-switching in financial time series"},
		},
		InspiredBy:   "Hamilton 1989 HMM regime-switching model",
		ResearchDocs: []string{"docs/regime_aware_results.md"},
		AddedDate: "2026-01-20", LastModified: "2026-03-15", Version: "1.3",
		Changelog: []string{"V1.0: 2-state HMM", "V1.2: 4-state + vol features", "V1.3: WassersteinRegime input"},
	},

	{
		Name: "MetaModelNode", ModulePath: "omega.nodes.victoria.meta_model",
		NodeType: "strategy", Project: "victoria",
		Description:   "GradientBoosting ensemble meta-learner that takes all signal outputs as features and learns optimal weighting from realized PnL outcomes.",
		Purpose:       "Non-linear signal combination — captures interaction effects between signals that IC-weighted linear ensemble misses.",
		AutonomyLevel: 2, HasMemory: true, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"All signal node outputs", "PaperTradingEngine PnL"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"n_estimators": 100, "max_depth": 4, "learning_rate": 0.1, "min_samples_leaf": 20},
		TunableParams: []string{"n_estimators", "max_depth", "learning_rate"},
		References: []CatalogReference{
			{Title: "Greedy Function Approximation: A Gradient Boosting Machine", Authors: "Friedman 2001", Relevance: "GBM as meta-learner for signal stacking"},
		},
		ResearchDocs: []string{},
		AddedDate: "2026-02-15", LastModified: "2026-03-20", Version: "1.1",
		Changelog: []string{"V1.0: sklearn GBM", "V1.1: regime-conditional training"},
	},

	{
		Name: "PositionSizingNode", ModulePath: "omega.nodes.victoria.position_sizing",
		NodeType: "risk", Project: "victoria",
		Description:   "Computes dynamic position sizes using a fractional Kelly criterion adjusted for estimated IC and signal correlation, with risk parity overlay.",
		Purpose:       "Bet sizing is the primary driver of long-run returns — Kelly maximizes log-wealth growth rate.",
		AutonomyLevel: 2, HasMemory: true, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Signal IC history", "Portfolio correlation matrix"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters: map[string]any{
			"kelly_fraction": 0.25,
			"max_position_pct": 0.15,
			"vol_target": 0.15,
			"risk_parity_weight": 0.3,
		},
		TunableParams: []string{"kelly_fraction", "max_position_pct", "vol_target"},
		References: []CatalogReference{
			{Title: "A New Interpretation of Information Rate", Authors: "Kelly 1956", Relevance: "Original Kelly criterion for optimal bet sizing"},
			{Title: "Risk Parity Portfolios: Efficient Frontiers and Optimal", Authors: "Qian 2011", Relevance: "Risk parity as diversification constraint on Kelly positions"},
		},
		ResearchDocs: []string{},
		AddedDate: "2026-01-20", LastModified: "2026-03-15", Version: "1.2",
		Changelog: []string{"V1.0: fixed Kelly", "V1.1: fractional Kelly", "V1.2: risk parity overlay"},
	},

	{
		Name: "DynamicWeightAllocator", ModulePath: "omega.nodes.victoria.dynamic_weights",
		NodeType: "strategy", Project: "victoria",
		Description:   "Maintains rolling Bayesian IC estimates per signal using exponential decay. Updates weights after each cycle outcome. Powers IC-weighted ensemble in VictoriaNode.",
		Purpose:       "Adaptive signal weighting — signals with recent high IC get more weight; decaying signals get down-weighted.",
		AutonomyLevel: 2, HasMemory: true, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Per-cycle signal predictions vs outcomes (internal)"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"decay_rate": 0.95, "min_observations": 20, "ic_floor": 0.0},
		TunableParams: []string{"decay_rate", "min_observations"},
		References: []CatalogReference{
			{Title: "Bayesian Learning in Undirected Graphical Models", Authors: "Koller & Friedman 2009", Relevance: "Bayesian updating framework for IC estimation"},
		},
		ResearchDocs: []string{},
		AddedDate: "2026-01-15", LastModified: "2026-03-20", Version: "1.1",
		Changelog: []string{"V1.0: equal weights", "V1.1: Bayesian IC decay"},
	},

	{
		Name: "RiskManagementNode", ModulePath: "omega.nodes.victoria.risk_management",
		NodeType: "risk", Project: "victoria",
		Description:   "Enforces position limits, max drawdown stops, and portfolio-level concentration rules. Integrates DebateGate adversarial checks before any trade is approved.",
		Purpose:       "Last line of defence before execution — reject any position that violates structural risk rules.",
		AutonomyLevel: 2, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Portfolio state", "DebateGate adversarial output"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters: map[string]any{
			"max_drawdown_pct": 0.05,
			"max_single_position_pct": 0.15,
			"max_portfolio_leverage": 3.0,
			"debate_gate_threshold": 0.6,
		},
		TunableParams: []string{"max_drawdown_pct", "max_single_position_pct"},
		ResearchDocs: []string{},
		AddedDate: "2026-01-10", LastModified: "2026-03-10", Version: "1.1",
		Changelog: []string{"V1.0: basic limits", "V1.1: DebateGate integration"},
	},

	{
		Name: "DataIngestionNode", ModulePath: "omega.nodes.victoria.data_ingestion",
		NodeType: "execution", Project: "victoria",
		Description:   "Fetches OHLCV data from Binance REST with CoinGecko fallback. Caches results and tracks per-source health scores.",
		Purpose:       "Reliable data pipeline foundation — all signal nodes depend on this node's outputs.",
		AutonomyLevel: 1, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Binance REST klines", "CoinGecko OHLCV"},
		APIEndpoints: []string{
			"https://api.binance.com/api/v3/klines",
			"https://api.coingecko.com/api/v3/coins/{id}/ohlc",
		},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"cache_ttl_seconds": 60, "max_retries": 3, "timeout_seconds": 10},
		TunableParams: []string{"cache_ttl_seconds"},
		ResearchDocs: []string{},
		AddedDate: "2026-01-10", LastModified: "2026-03-01", Version: "1.2",
		Changelog: []string{"V1.0: Binance only", "V1.1: CoinGecko fallback", "V1.2: health tracking"},
	},

	{
		Name: "SignalResearchNode", ModulePath: "omega.nodes.victoria.signal_research",
		NodeType: "reasoning", Project: "victoria",
		Description:   "Uses QUICK-tier LLM to analyze MemoryKernel episodes and generate research hypotheses about new alpha signals. Currently generates hypotheses but does not auto-test them.",
		Purpose:       "AI-driven signal discovery — extract patterns from past cycle outcomes that aren't captured by current signal set.",
		AutonomyLevel: 3, HasMemory: true, HasReasoning: true, HasReflection: false, UsesBrain: true,
		DataSources: []string{"MemoryKernel episodes", "Cycle outcome history"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"episode_lookback": 20, "hypothesis_count": 3, "brain_tier": "QUICK"},
		TunableParams: []string{"episode_lookback", "hypothesis_count"},
		References: []CatalogReference{
			{Title: "Hypothesis Generation in Scientific Discovery", Authors: "Langley et al. 1987", Relevance: "Automated hypothesis generation as ML loop component"},
		},
		ResearchDocs: []string{"docs/node_intelligence_audit.md"},
		AddedDate: "2026-02-20", LastModified: "2026-03-20", Version: "1.0",
		Changelog: []string{"V1.0: LLM hypothesis generation from episodes"},
	},

	{
		Name: "VerificationNode", ModulePath: "omega.nodes.victoria.verification",
		NodeType: "execution", Project: "victoria",
		Description:   "Compares live trade outcomes to backtest expectations and flags systematic divergences (slippage, latency, fill rate).",
		Purpose:       "Detect execution drift — when live performance diverges from backtest, the strategy needs re-calibration.",
		AutonomyLevel: 2, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Live trade records", "Backtest reference database"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"divergence_threshold_pct": 20.0, "min_trades_for_test": 30},
		TunableParams: []string{"divergence_threshold_pct"},
		ResearchDocs: []string{"docs/BUG_BASH_AND_VALIDATION.md"},
		AddedDate: "2026-02-15", LastModified: "2026-03-15", Version: "1.0",
		Changelog: []string{"V1.0: initial divergence checks"},
	},

	{
		Name: "DataCleanersNode", ModulePath: "omega.nodes.victoria.cleaners",
		NodeType: "execution", Project: "victoria",
		Description:   "Multi-stage data validation pipeline: DataIntegrityNode (NaN/outlier detection), LintNode (schema validation), PropertyTestNode (statistical invariants), ConvergenceMonitorNode (IC trend monitoring).",
		Purpose:       "Garbage in, garbage out — catch data quality issues before they contaminate signal generation.",
		AutonomyLevel: 2, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"All upstream signal outputs (validation only)"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters: map[string]any{
			"zscore_outlier_threshold": 5.0,
			"nan_tolerance_pct": 5.0,
			"min_ic_trend_window": 10,
		},
		TunableParams: []string{"zscore_outlier_threshold"},
		ResearchDocs: []string{},
		AddedDate: "2026-02-10", LastModified: "2026-03-10", Version: "1.1",
		Changelog: []string{"V1.0: NaN + outlier detection", "V1.1: IC trend monitoring"},
	},

	// ── Intelligence / memory nodes (shared) ─────────────────────────────────

	{
		Name: "ReasoningNode", ModulePath: "omega.nodes.shared.reasoning_node",
		NodeType: "reasoning", Project: "shared",
		Description:   "LLM-powered structured reasoning with QUICK-tier brain and MemoryBus context injection. Produces structured decisions with confidence and evidence fields.",
		Purpose:       "Cross-project reasoning layer — any node that needs LLM decision-making delegates here.",
		AutonomyLevel: 3, HasMemory: true, HasReasoning: true, HasReflection: false, UsesBrain: true,
		DataSources: []string{"MemoryBus (regime insights, risk warnings)", "Caller-provided context"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"brain_tier": "QUICK", "max_context_memories": 5, "confidence_threshold": 0.7},
		TunableParams: []string{"max_context_memories", "confidence_threshold"},
		ResearchDocs: []string{"docs/architecture/distributed-intelligence.md"},
		AddedDate: "2026-02-01", LastModified: "2026-03-20", Version: "1.1",
		Changelog: []string{"V1.0: basic LLM calls", "V1.1: MemoryBus context injection"},
	},

	{
		Name: "ReflectionNode", ModulePath: "omega.nodes.shared.reflection_node",
		NodeType: "reasoning", Project: "shared",
		Description:   "Per-cycle LLM reflection that analyzes cycle outcomes and writes regime insights to both the episodic MemoryKernel and cross-project MemoryBus. Memory consolidation gap: written episodes never consolidated to semantic.",
		Purpose:       "Continuous learning via self-reflection — turn cycle outcomes into persistent strategic knowledge.",
		AutonomyLevel: 3, HasMemory: true, HasReasoning: true, HasReflection: true, UsesBrain: true,
		DataSources: []string{"Cycle outcome metrics", "MemoryKernel episodes"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"brain_tier": "QUICK", "reflection_prompt_version": "v2", "min_cycles_before_reflect": 1},
		TunableParams: []string{"min_cycles_before_reflect"},
		ResearchDocs: []string{"docs/architecture/distributed-intelligence.md", "docs/node_intelligence_audit.md"},
		AddedDate: "2026-02-01", LastModified: "2026-03-20", Version: "1.2",
		Changelog: []string{"V1.0: episodic writes only", "V1.1: MemoryBus writes", "V1.2: structured insight format"},
	},

	{
		Name: "SemanticMemoryNode", ModulePath: "omega.nodes.shared.semantic_memory",
		NodeType: "memory", Project: "shared",
		Description:   "Cross-project semantic memory index that enables Victoria and Polymarket to share distilled strategic insights. Wraps the MemoryBus with semantic retrieval (embedding-based similarity).",
		Purpose:       "Break project silos — Victoria's regime knowledge should inform Polymarket's event probability models.",
		AutonomyLevel: 2, HasMemory: true, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"MemoryBus", "MemoryKernel (both projects)"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"embedding_model": "text-embedding-3-small", "top_k": 5, "min_relevance": 0.4},
		TunableParams: []string{"top_k", "min_relevance"},
		ResearchDocs: []string{"docs/architecture/distributed-intelligence.md"},
		AddedDate: "2026-02-10", LastModified: "2026-03-20", Version: "1.0",
		Changelog: []string{"V1.0: initial cross-project semantic retrieval"},
	},

	// ── Polymarket nodes ──────────────────────────────────────────────────────

	{
		Name: "EdgeDetectionNode", ModulePath: "omega.nodes.polymarket.edge_detection",
		NodeType: "signal", Project: "polymarket",
		Description:   "Computes edge as the difference between Omega's model probability and Polymarket's market price for binary events. Calculates Kelly fraction when edge exceeds threshold.",
		Purpose:       "Only bet when expected value is positive and large enough to justify execution cost.",
		AutonomyLevel: 2, HasMemory: true, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Gamma API (Polymarket markets)", "Internal probability models"},
		APIEndpoints: []string{"https://gamma-api.polymarket.com/markets"},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"min_edge_pct": 3.0, "kelly_fraction": 0.1, "min_liquidity_usd": 1000},
		TunableParams: []string{"min_edge_pct", "kelly_fraction"},
		References: []CatalogReference{
			{Title: "A New Interpretation of Information Rate", Authors: "Kelly 1956", Relevance: "Kelly criterion applied to binary prediction market betting"},
		},
		ResearchDocs: []string{"docs/alpha-edge-research.md"},
		AddedDate: "2026-02-01", LastModified: "2026-03-20", Version: "1.1",
		Changelog: []string{"V1.0: fixed edge threshold", "V1.1: adaptive threshold from outcome history"},
	},

	{
		Name: "VolArbNode", ModulePath: "omega.nodes.polymarket.vol_arb",
		NodeType: "signal", Project: "polymarket",
		Description:   "Detects opportunities where Polymarket's implied volatility (from binary option pricing) diverges significantly from realized volatility on the underlying asset.",
		Purpose:       "Vol arb between prediction markets and options markets exploits model disagreement on event probability distributions.",
		AutonomyLevel: 2, HasMemory: true, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Gamma API", "Binance options (realized vol)", "Deribit (implied vol)"},
		APIEndpoints: []string{"https://gamma-api.polymarket.com/markets", "https://www.deribit.com/api/v2/public/get_ticker"},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"min_vol_spread_pct": 10.0, "lookback_days": 30},
		TunableParams: []string{"min_vol_spread_pct"},
		ResearchDocs: []string{"data/polymarket_vol_arb_opportunities.json"},
		AddedDate: "2026-02-15", LastModified: "2026-03-15", Version: "1.0",
		Changelog: []string{"V1.0: initial vol comparison"},
	},

	{
		Name: "WeatherEnsembleNode", ModulePath: "omega.nodes.polymarket.weather_ensemble",
		NodeType: "signal", Project: "polymarket",
		Description:   "Runs a 30-member NOAA GEFS weather ensemble for 57 cities and aggregates probabilistic temperature/precipitation forecasts to price Polymarket weather event markets.",
		Purpose:       "Weather prediction markets are dominated by retail bettors — ensemble meteorological models have systematic edge over simple forecasts.",
		AutonomyLevel: 2, HasMemory: true, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"NOAA GEFS ensemble API (open-meteo)", "Polymarket weather markets"},
		APIEndpoints: []string{
			"https://ensemble-api.open-meteo.com/v1/ensemble",
			"https://gamma-api.polymarket.com/markets?tag=weather",
		},
		RequiresAPIKey: false,
		Parameters: map[string]any{
			"ensemble_members": 30,
			"cities_count": 57,
			"forecast_horizon_days": 7,
			"confidence_threshold": 0.65,
		},
		TunableParams: []string{"confidence_threshold", "forecast_horizon_days"},
		References: []CatalogReference{
			{Title: "The ECMWF Ensemble Prediction System", Authors: "Buizza et al. 2008", Relevance: "Ensemble weather forecasting methodology and calibration"},
		},
		ResearchDocs: []string{"docs/ideas/simons-alpha-sources.md", "data/polymarket_weather_edges.json"},
		AddedDate: "2026-02-20", LastModified: "2026-03-20", Version: "1.2",
		Changelog: []string{"V1.0: 10-member ensemble, 20 cities", "V1.1: 30-member", "V1.2: 57 cities + adaptive confidence"},
	},

	{
		Name: "PolymarketPricingNode", ModulePath: "omega.nodes.polymarket.pricing",
		NodeType: "execution", Project: "polymarket",
		Description:   "Fetches active Polymarket event markets via Gamma API and computes fair value probabilities using calibrated Bayesian priors.",
		Purpose:       "Market data ingestion layer for Polymarket — all edge detection depends on accurate current prices.",
		AutonomyLevel: 1, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Gamma API (Polymarket)"},
		APIEndpoints: []string{"https://gamma-api.polymarket.com/markets", "https://gamma-api.polymarket.com/events"},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"min_volume_usd": 500, "min_liquidity_usd": 200, "active_only": true},
		TunableParams: []string{"min_volume_usd"},
		ResearchDocs: []string{},
		AddedDate: "2026-02-01", LastModified: "2026-03-10", Version: "1.1",
		Changelog: []string{"V1.0: basic fetch", "V1.1: Bayesian calibration"},
	},

	{
		Name: "LatencyArbNode", ModulePath: "omega.nodes.polymarket.strategies.latency_arb",
		NodeType: "strategy", Project: "polymarket",
		Description:   "Detects latency arbitrage opportunities when Binance crypto price moves before Polymarket crypto-related event markets update.",
		Purpose:       "Polymarket markets referencing crypto prices lag Binance by 30–120 seconds — first mover wins edge.",
		AutonomyLevel: 1, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"BinanceFeedNode (real-time prices)", "Gamma API (event markets)"},
		APIEndpoints: []string{"https://api.binance.com/api/v3/ticker/price", "https://gamma-api.polymarket.com/markets"},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"min_price_move_pct": 1.5, "max_latency_seconds": 120, "min_edge_pct": 5.0},
		TunableParams: []string{"min_price_move_pct", "max_latency_seconds"},
		ResearchDocs: []string{},
		AddedDate: "2026-03-01", LastModified: "2026-03-20", Version: "1.0",
		Changelog: []string{"V1.0: initial latency arb detection"},
	},

	{
		Name: "BinanceFeedNode", ModulePath: "omega.nodes.polymarket.strategies.binance_feed",
		NodeType: "execution", Project: "polymarket",
		Description:   "Stateless Binance spot price feed connector for Polymarket correlation detection. Fetches current prices and 24h stats.",
		Purpose:       "Provides the Binance price reference that LatencyArbNode uses to detect lagged Polymarket updates.",
		AutonomyLevel: 0, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Binance REST ticker API"},
		APIEndpoints: []string{"https://api.binance.com/api/v3/ticker/24hr", "https://api.binance.com/api/v3/ticker/price"},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"symbols": []string{"BTCUSDT", "ETHUSDT", "SOLUSDT"}, "cache_ttl_seconds": 5},
		TunableParams: []string{},
		ResearchDocs: []string{},
		AddedDate: "2026-03-01", LastModified: "2026-03-10", Version: "1.0",
		Changelog: []string{"V1.0: initial"},
	},

	// ── Platform nodes ────────────────────────────────────────────────────────

	{
		Name: "DevilsAdvocateNode", ModulePath: "omega.nodes.devils_advocate",
		NodeType: "reasoning", Project: "platform",
		Description:   "Adversarial challenger that generates counter-arguments to proposed trades via ChallengeRegistry and DebateGate. Currently rule-based; LLM challenge generation is not yet wired.",
		Purpose:       "Force explicit risk consideration before every trade — if the devil can't find a flaw, proceed with higher confidence.",
		AutonomyLevel: 3, HasMemory: true, HasReasoning: true, HasReflection: false, UsesBrain: false,
		DataSources: []string{"ChallengeRegistry (internal)", "Proposed trade parameters"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"challenge_threshold": 0.6, "max_challenges": 5, "required_rebuttal": true},
		TunableParams: []string{"challenge_threshold"},
		References: []CatalogReference{
			{Title: "Thinking, Fast and Slow", Authors: "Kahneman 2011", Relevance: "Adversarial pre-mortem as bias reduction technique"},
		},
		ResearchDocs: []string{"docs/superpowers/plans/2026-03-21-devils-advocate.md"},
		AddedDate: "2026-01-20", LastModified: "2026-03-15", Version: "1.1",
		Changelog: []string{"V1.0: ChallengeRegistry + DebateGate", "V1.1: structured rebuttal format"},
	},

	{
		Name: "DashboardNode", ModulePath: "omega.nodes.dashboard_node",
		NodeType: "platform", Project: "platform",
		Description:   "Monitoring and reporting node that self-evaluates system health, generates improvement reports, and exports metrics. Cannot take action — observes only.",
		Purpose:       "Single pane of glass for system health — tracks all node metrics and generates actionable improvement suggestions.",
		AutonomyLevel: 2, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"All node health metrics (internal)", "StateStore"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"report_interval_cycles": 10, "alert_health_threshold": 0.5},
		TunableParams: []string{"report_interval_cycles"},
		ResearchDocs: []string{},
		AddedDate: "2026-01-20", LastModified: "2026-03-10", Version: "1.1",
		Changelog: []string{"V1.0: health metrics", "V1.1: improvement report generation"},
	},

	{
		Name: "SkillCreatorNode", ModulePath: "omega.nodes.skill_creator",
		NodeType: "platform", Project: "platform",
		Description:   "Factory node that generates new SKILL.md capability definitions at runtime based on observed node behaviour patterns.",
		Purpose:       "Self-extending platform — new capabilities discovered during cycles are formalized as reusable skills.",
		AutonomyLevel: 1, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Node capability logs (internal)"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"min_usage_count": 3, "confidence_threshold": 0.8},
		TunableParams: []string{"min_usage_count"},
		ResearchDocs: []string{},
		AddedDate: "2026-02-01", LastModified: "2026-03-01", Version: "1.0",
		Changelog: []string{"V1.0: initial SKILL.md generation"},
	},

	{
		Name: "CalculatorNode", ModulePath: "omega.nodes.calculator",
		NodeType: "platform", Project: "platform",
		Description:   "Stateful arithmetic node with add/subtract/multiply/divide. Tracks operation counts and error rates as a reference implementation for the node framework.",
		Purpose:       "Reference node for testing the autonomy framework — also used in integration tests.",
		AutonomyLevel: 1, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"precision": 6},
		TunableParams: []string{},
		ResearchDocs: []string{},
		AddedDate: "2026-01-10", LastModified: "2026-02-01", Version: "1.0",
		Changelog: []string{"V1.0: initial reference implementation"},
	},

	{
		Name: "TextAnalyzerNode", ModulePath: "omega.nodes.text_analyzer",
		NodeType: "platform", Project: "platform",
		Description:   "Sequential text analysis with progressive feature unlock: v1.0 (word count), v1.1 (sentiment), v1.2 (entity extraction), v1.3 (topic modelling). Demonstrates the improve() progression pattern.",
		Purpose:       "Demonstration of self-improving node pattern — shows how improve() unlocks higher-capability versions.",
		AutonomyLevel: 1, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Text input (caller-provided)"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters:    map[string]any{"max_tokens": 512},
		TunableParams: []string{},
		ResearchDocs: []string{},
		AddedDate: "2026-01-15", LastModified: "2026-02-15", Version: "1.0",
		Changelog: []string{"V1.0: word count only (v1.1–v1.3 implemented but improve() never called)"},
	},

	{
		Name: "WebFetcherNode", ModulePath: "omega.nodes.web_fetcher",
		NodeType: "platform", Project: "platform",
		Description:   "HTTP fetch with exponential-backoff retry, response caching, and per-URL reliability score learning from historic success/failure rates.",
		Purpose:       "Resilient HTTP layer used by any node that needs to fetch external data without managing retry logic itself.",
		AutonomyLevel: 1, HasMemory: false, HasReasoning: false, HasReflection: false, UsesBrain: false,
		DataSources: []string{"Any HTTP endpoint (caller-provided)"},
		APIEndpoints: []string{},
		RequiresAPIKey: false,
		Parameters: map[string]any{
			"max_retries": 3,
			"backoff_base_seconds": 2,
			"cache_ttl_seconds": 300,
			"timeout_seconds": 15,
		},
		TunableParams: []string{"max_retries", "cache_ttl_seconds"},
		ResearchDocs: []string{},
		AddedDate: "2026-01-15", LastModified: "2026-03-01", Version: "1.1",
		Changelog: []string{"V1.0: basic retry", "V1.1: per-URL reliability scoring"},
	},
}

// ── query helpers ─────────────────────────────────────────────────────────────

// ByName returns the CatalogEntry with the given name, or nil.
func ByName(name string) *CatalogEntry {
	for i := range Catalog {
		if Catalog[i].Name == name {
			return &Catalog[i]
		}
	}
	return nil
}

// ByType returns all entries matching the given node_type.
func ByType(nodeType string) []CatalogEntry {
	var out []CatalogEntry
	for _, e := range Catalog {
		if e.NodeType == nodeType {
			out = append(out, e)
		}
	}
	return out
}

// ByProject returns all entries matching the given project.
func ByProject(project string) []CatalogEntry {
	var out []CatalogEntry
	for _, e := range Catalog {
		if e.Project == project {
			out = append(out, e)
		}
	}
	return out
}

// ByAutonomyLevel returns all entries at or above the given autonomy level.
func ByAutonomyLevel(minLevel int) []CatalogEntry {
	var out []CatalogEntry
	for _, e := range Catalog {
		if e.AutonomyLevel >= minLevel {
			out = append(out, e)
		}
	}
	return out
}

// WithBrain returns all entries that use a brain (LLM).
func WithBrain() []CatalogEntry {
	var out []CatalogEntry
	for _, e := range Catalog {
		if e.UsesBrain {
			out = append(out, e)
		}
	}
	return out
}

// RequiringAPIKey returns all entries that require an API key.
func RequiringAPIKey() []CatalogEntry {
	var out []CatalogEntry
	for _, e := range Catalog {
		if e.RequiresAPIKey {
			out = append(out, e)
		}
	}
	return out
}

// Summary returns a one-line summary string for the catalog.
func Summary() string {
	typeCount := map[string]int{}
	projectCount := map[string]int{}
	levelCount := map[int]int{}
	for _, e := range Catalog {
		typeCount[e.NodeType]++
		projectCount[e.Project]++
		levelCount[e.AutonomyLevel]++
	}
	return fmt.Sprintf("%d nodes | victoria=%d polymarket=%d shared=%d platform=%d | L0=%d L1=%d L2=%d L3=%d L4=%d",
		len(Catalog),
		projectCount["victoria"], projectCount["polymarket"], projectCount["shared"], projectCount["platform"],
		levelCount[0], levelCount[1], levelCount[2], levelCount[3], levelCount[4],
	)
}

// FormatTable returns a formatted ASCII table for the CLI.
func FormatTable(filter string) string {
	entries := Catalog
	if filter != "" {
		entries = nil
		for _, e := range Catalog {
			if e.Project == filter || e.NodeType == filter {
				entries = append(entries, e)
			}
		}
	}
	sort.Slice(entries, func(i, j int) bool {
		if entries[i].Project != entries[j].Project {
			return entries[i].Project < entries[j].Project
		}
		return entries[i].Name < entries[j].Name
	})

	var sb strings.Builder
	w := tabwriter.NewWriter(&sb, 0, 0, 2, ' ', 0)
	_, _ = fmt.Fprintln(w, "NAME\tTYPE\tPROJECT\tL\tIC\tWEIGHT\tMEMORY\tBRAIN")
	_, _ = fmt.Fprintln(w, strings.Repeat("─", 90))
	for _, e := range entries {
		ic := "—"
		if e.CurrentIC != nil {
			ic = fmt.Sprintf("%.3f", *e.CurrentIC)
		}
		wt := "—"
		if e.CurrentWeight != nil {
			wt = fmt.Sprintf("%.1f%%", *e.CurrentWeight*100)
		}
		mem := " "
		if e.HasMemory {
			mem = "✓"
		}
		brain := " "
		if e.UsesBrain {
			brain = "✓"
		}
		_, _ = fmt.Fprintf(w, "%s\t%s\t%s\tL%d\t%s\t%s\t%s\t%s\n",
			e.Name, e.NodeType, e.Project, e.AutonomyLevel, ic, wt, mem, brain)
	}
	_ = w.Flush()
	return sb.String()
}

// FormatDetail returns a multi-line detail block for a single entry.
func FormatDetail(e CatalogEntry) string {
	var sb strings.Builder
	line := func(k, v string) { fmt.Fprintf(&sb, "  %-20s %s\n", k+":", v) }
	boolStr := func(b bool) string {
		if b {
			return "yes"
		}
		return "no"
	}
	fmt.Fprintf(&sb, "=== %s ===\n", e.Name)
	line("Module", e.ModulePath)
	line("Type", e.NodeType+" | Project: "+e.Project)
	line("Autonomy", fmt.Sprintf("L%d", e.AutonomyLevel))
	line("Memory", boolStr(e.HasMemory))
	line("Reasoning", boolStr(e.HasReasoning)+" | Reflection: "+boolStr(e.HasReflection)+" | Brain: "+boolStr(e.UsesBrain))
	line("Version", e.Version+" (added "+e.AddedDate+", modified "+e.LastModified+")")
	fmt.Fprintf(&sb, "\n  Description:\n    %s\n\n", e.Description)
	fmt.Fprintf(&sb, "  Purpose: %s\n\n", e.Purpose)
	if len(e.DataSources) > 0 {
		fmt.Fprintf(&sb, "  Data Sources:\n")
		for _, ds := range e.DataSources {
			fmt.Fprintf(&sb, "    • %s\n", ds)
		}
		fmt.Fprintln(&sb)
	}
	if e.RequiresAPIKey {
		line("API Key", e.APIKeyName)
	}
	if len(e.Parameters) > 0 {
		fmt.Fprintf(&sb, "  Parameters:\n")
		keys := make([]string, 0, len(e.Parameters))
		for k := range e.Parameters {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			tunable := ""
			for _, tp := range e.TunableParams {
				if tp == k {
					tunable = " (tunable)"
					break
				}
			}
			fmt.Fprintf(&sb, "    %-30s = %v%s\n", k, e.Parameters[k], tunable)
		}
		fmt.Fprintln(&sb)
	}
	if e.CurrentIC != nil || e.CurrentWeight != nil {
		fmt.Fprintf(&sb, "  Performance:\n")
		if e.CurrentIC != nil {
			fmt.Fprintf(&sb, "    IC = %.4f\n", *e.CurrentIC)
		}
		if e.CurrentWeight != nil {
			fmt.Fprintf(&sb, "    Weight = %.1f%%\n", *e.CurrentWeight*100)
		}
		fmt.Fprintln(&sb)
	}
	if e.InspiredBy != "" {
		line("Inspired by", e.InspiredBy)
	}
	if len(e.References) > 0 {
		fmt.Fprintf(&sb, "  Research References:\n")
		for _, r := range e.References {
			fmt.Fprintf(&sb, "    • %s", r.Title)
			if r.Authors != "" {
				fmt.Fprintf(&sb, " (%s)", r.Authors)
			}
			fmt.Fprintln(&sb)
			if r.Relevance != "" {
				fmt.Fprintf(&sb, "      → %s\n", r.Relevance)
			}
		}
		fmt.Fprintln(&sb)
	}
	if len(e.ResearchDocs) > 0 {
		fmt.Fprintf(&sb, "  Research Docs:\n")
		for _, d := range e.ResearchDocs {
			fmt.Fprintf(&sb, "    %s\n", d)
		}
		fmt.Fprintln(&sb)
	}
	if len(e.Changelog) > 0 {
		fmt.Fprintf(&sb, "  Changelog:\n")
		for _, c := range e.Changelog {
			fmt.Fprintf(&sb, "    • %s\n", c)
		}
	}
	return sb.String()
}

// ToJSON serialises the full catalog to pretty-printed JSON.
func ToJSON() ([]byte, error) {
	return json.MarshalIndent(Catalog, "", "  ")
}

// WriteFiles writes docs/node_registry.md and data/node_registry.json
// relative to the given root directory.
func WriteFiles(root string) error {
	// JSON
	jsonData, err := ToJSON()
	if err != nil {
		return fmt.Errorf("catalog: marshal json: %w", err)
	}
	jsonPath := root + "/data/node_registry.json"
	if err := os.WriteFile(jsonPath, jsonData, 0o600); err != nil {
		return fmt.Errorf("catalog: write json: %w", err)
	}

	// Markdown
	mdPath := root + "/docs/node_registry.md"
	md := buildMarkdown()
	if err := os.WriteFile(mdPath, []byte(md), 0o600); err != nil {
		return fmt.Errorf("catalog: write markdown: %w", err)
	}

	return nil
}

func buildMarkdown() string {
	var sb strings.Builder
	sb.WriteString("# Omega Node Registry\n\n")
	sb.WriteString("> Auto-generated from `internal/registry/catalog.go`. Do not edit manually — run `omega nodes export` to regenerate.\n\n")
	sb.WriteString("## Summary\n\n")
	sb.WriteString(Summary() + "\n\n")

	projects := []string{"victoria", "polymarket", "shared", "platform"}
	projectHeadings := map[string]string{
		"victoria":   "Victoria (Crypto Quant)",
		"polymarket": "Polymarket",
		"shared":     "Shared Intelligence",
		"platform":   "Platform",
	}

	for _, proj := range projects {
		entries := ByProject(proj)
		if len(entries) == 0 {
			continue
		}
		fmt.Fprintf(&sb, "## %s\n\n", projectHeadings[proj])
		sb.WriteString("| Name | Type | L | IC | Memory | Brain | Purpose |\n")
		sb.WriteString("|------|------|---|----|----|---|---|\n")
		for _, e := range entries {
			ic := "—"
			if e.CurrentIC != nil {
				ic = fmt.Sprintf("%.3f", *e.CurrentIC)
			}
			mem := "✗"
			if e.HasMemory {
				mem = "✓"
			}
			brain := "✗"
			if e.UsesBrain {
				brain = "✓"
			}
			fmt.Fprintf(&sb, "| **%s** | %s | L%d | %s | %s | %s | %s |\n",
				e.Name, e.NodeType, e.AutonomyLevel, ic, mem, brain, e.Purpose)
		}
		sb.WriteString("\n")

		// Detail sections
		for _, e := range entries {
			fmt.Fprintf(&sb, "### %s\n\n", e.Name)
			fmt.Fprintf(&sb, "**Module:** `%s`  \n", e.ModulePath)
			fmt.Fprintf(&sb, "**Type:** %s | **Project:** %s | **Autonomy:** L%d  \n", e.NodeType, e.Project, e.AutonomyLevel)
			fmt.Fprintf(&sb, "**Version:** %s (added %s)\n\n", e.Version, e.AddedDate)
			fmt.Fprintf(&sb, "%s\n\n", e.Description)
			if len(e.DataSources) > 0 {
				sb.WriteString("**Data Sources:**\n")
				for _, ds := range e.DataSources {
					fmt.Fprintf(&sb, "- %s\n", ds)
				}
				sb.WriteString("\n")
			}
			if len(e.References) > 0 {
				sb.WriteString("**References:**\n")
				for _, r := range e.References {
					if r.Authors != "" {
						fmt.Fprintf(&sb, "- *%s* — %s\n", r.Title, r.Authors)
					} else {
						fmt.Fprintf(&sb, "- *%s*\n", r.Title)
					}
					if r.Relevance != "" {
						fmt.Fprintf(&sb, "  > %s\n", r.Relevance)
					}
				}
				sb.WriteString("\n")
			}
			if len(e.Changelog) > 0 {
				sb.WriteString("**Changelog:** " + strings.Join(e.Changelog, " → ") + "\n\n")
			}
			sb.WriteString("---\n\n")
		}
	}
	return sb.String()
}
