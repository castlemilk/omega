package core

// crash_scenarios.go — Real historical crash stress tests for the backtest engine.
//
// The problem with the existing adversarial system: all stress data is Gaussian
// synthetic noise. Real crypto markets have kurtosis 5–15. This module provides:
//
//   CrashScenarioProvider — four hardcoded historical crash profiles with full
//     OHLCV price series (hourly bars), realistic fat-tail volatility, volume
//     spikes, correlation matrix shifts, and liquidity degradation.
//
//   StressTestRunner — runs a strategy callable bar-by-bar through each crash
//     and reports regime-conditional metrics: Sharpe, max drawdown,
//     time-to-recovery, and tail loss (CVaR 99%).
//
//   BootstrapCrashScenarios — block-resamples historical crash bars with
//     replacement to generate novel but realistic stress scenarios.

import (
	"fmt"
	"math"
	"math/rand"
	"sort"
	"time"
)

// ---------------------------------------------------------------------------
// Core OHLCV types
// ---------------------------------------------------------------------------

// OHLCV is a single hourly candlestick bar.
// Volume is normalised (1.0 = one typical daily volume unit).
type OHLCV struct {
	Timestamp time.Time
	Open      float64
	High      float64
	Low       float64
	Close     float64
	Volume    float64
}

// CorrelationMatrix maps asset → asset → correlation coefficient.
// Access as CorrelationMatrix["BTCUSDT"]["ETHUSDT"].
type CorrelationMatrix map[string]map[string]float64

// LiquidityProfile describes market microstructure at normal and peak-crash conditions.
type LiquidityProfile struct {
	NormalSpreadBps  float64 // typical bid-ask spread in basis points
	PeakSpreadBps    float64 // spread at worst crash moment (basis points)
	SpreadMultiplier float64 // PeakSpreadBps / NormalSpreadBps (10–50x in real crashes)
	DepthRatio       float64 // order-book depth vs normal; < 1.0 during crashes
}

// CrashProfile is a complete historical crash scenario with full market data.
type CrashProfile struct {
	ID           string
	Name         string
	Description  string
	StartTime    time.Time
	DurationBars int                    // number of hourly bars
	Assets       []string               // ordered asset list
	PriceSeries  map[string][]OHLCV     // asset → hourly bars (len = DurationBars)
	NormalCorr   CorrelationMatrix      // typical pre-crash correlations
	CrashCorr    CorrelationMatrix      // peak-crash correlations (converge to 1.0)
	Liquidity    LiquidityProfile
	Severity     float64            // 0–1 severity score
	Tags         []string
	PeakDrawdown map[string]float64 // asset → peak drawdown fraction (negative)
}

// ---------------------------------------------------------------------------
// CrashScenarioProvider
// ---------------------------------------------------------------------------

// CrashScenarioProvider provides hardcoded historical crash profiles with
// realistic OHLCV series, volume spikes, correlation shifts, and liquidity
// degradation. Four scenarios are pre-loaded:
//
//   crash_2020_covid   — March 2020 COVID crash: BTC -45% in 24h, 30x spreads
//   crash_2022_luna    — May 2022 LUNA/UST collapse: -99.9% over 6 days
//   crash_2022_ftx     — Nov 2022 FTX collapse: BTC -25%, FTT -97%, SOL -60%
//   crash_2021_may     — May 2021 China mining ban: BTC -47% over 14 days
type CrashScenarioProvider struct {
	profiles map[string]CrashProfile
}

// NewCrashScenarioProvider creates a provider pre-loaded with the four canonical
// historical crash scenarios.
func NewCrashScenarioProvider() *CrashScenarioProvider {
	p := &CrashScenarioProvider{profiles: make(map[string]CrashProfile)}
	p.load()
	return p
}

// All returns all crash profiles sorted by severity descending.
func (p *CrashScenarioProvider) All() []CrashProfile {
	result := make([]CrashProfile, 0, len(p.profiles))
	for _, cp := range p.profiles {
		result = append(result, cp)
	}
	sort.Slice(result, func(i, j int) bool { return result[i].Severity > result[j].Severity })
	return result
}

// Get retrieves a crash profile by ID.
func (p *CrashScenarioProvider) Get(id string) (CrashProfile, bool) {
	cp, ok := p.profiles[id]
	return cp, ok
}

// GetByTag returns all crash profiles carrying the given tag.
func (p *CrashScenarioProvider) GetByTag(tag string) []CrashProfile {
	var result []CrashProfile
	for _, cp := range p.profiles {
		for _, t := range cp.Tags {
			if t == tag {
				result = append(result, cp)
				break
			}
		}
	}
	return result
}

// ToScenarios converts all crash profiles to the existing Scenario type so they
// can be fed directly into the existing ScenarioRunner / SimulationGate pipeline.
func (p *CrashScenarioProvider) ToScenarios() []Scenario {
	all := p.All()
	scenarios := make([]Scenario, 0, len(all))
	for _, cp := range all {
		shocks := make(map[string]float64, len(cp.Assets))
		for _, asset := range cp.Assets {
			if dd, ok := cp.PeakDrawdown[asset]; ok {
				shocks[asset] = dd
			}
		}
		scenarios = append(scenarios, Scenario{
			ScenarioID:           cp.ID,
			Name:                 cp.Name,
			Description:          cp.Description,
			MarketShocks:         shocks,
			VolMultiplier:        cp.Liquidity.SpreadMultiplier / 10.0,
			CorrelationBreakdown: true,
			Severity:             cp.Severity,
		})
	}
	return scenarios
}

// Len returns the number of profiles loaded.
func (p *CrashScenarioProvider) Len() int { return len(p.profiles) }

func (p *CrashScenarioProvider) load() {
	p.profiles["crash_2020_covid"] = buildCOVIDCrash()
	p.profiles["crash_2022_luna"] = buildLUNACrash()
	p.profiles["crash_2022_ftx"] = buildFTXCrash()
	p.profiles["crash_2021_may"] = buildMay2021Crash()
}

// ---------------------------------------------------------------------------
// Crash profile builders
// ---------------------------------------------------------------------------

// buildCOVIDCrash constructs the March 12–13 2020 COVID crash profile.
// BTC fell ~45% in under 24 hours on 12 March 2020 as WHO declared a pandemic.
// This remains the sharpest single-day drop in BTC history by raw dollar amount.
// Spreads widened 30x, order books emptied, and all crypto assets crashed in lockstep.
func buildCOVIDCrash() CrashProfile {
	const seed = 2020031213
	const nBars = 48 // 2 days, hourly
	start := time.Date(2020, 3, 12, 0, 0, 0, 0, time.UTC)
	assets := []string{"BTCUSDT", "ETHUSDT", "BNBUSDT"}

	btc := buildPriceSeries(start, nBars, 8800, []priceWaypoint{
		{16, 4800}, {24, 5200}, {36, 5800}, {48, 6500},
	}, 2.5, seed)
	eth := buildPriceSeries(start, nBars, 200, []priceWaypoint{
		{18, 96}, {24, 115}, {36, 128}, {48, 142},
	}, 2.8, seed+1)
	bnb := buildPriceSeries(start, nBars, 14.5, []priceWaypoint{
		{18, 7.8}, {24, 8.5}, {48, 10.0},
	}, 2.6, seed+2)

	applyVolumeSpike(btc, 12, 24, 8.0, seed+10)
	applyVolumeSpike(eth, 12, 24, 7.5, seed+11)
	applyVolumeSpike(bnb, 14, 26, 6.0, seed+12)

	return CrashProfile{
		ID:           "crash_2020_covid",
		Name:         "COVID Crash (March 12–13 2020)",
		Description:  "BTC -45% in 24h as WHO declared a pandemic. Extreme volume spike, full correlation convergence, 30x spread widening. Highest single-day liquidity crisis in BTC history.",
		StartTime:    start,
		DurationBars: nBars,
		Assets:       assets,
		PriceSeries:  map[string][]OHLCV{"BTCUSDT": btc, "ETHUSDT": eth, "BNBUSDT": bnb},
		NormalCorr: CorrelationMatrix{
			"BTCUSDT": {"ETHUSDT": 0.72, "BNBUSDT": 0.68},
			"ETHUSDT": {"BTCUSDT": 0.72, "BNBUSDT": 0.70},
			"BNBUSDT": {"BTCUSDT": 0.68, "ETHUSDT": 0.70},
		},
		CrashCorr: CorrelationMatrix{
			"BTCUSDT": {"ETHUSDT": 0.97, "BNBUSDT": 0.95},
			"ETHUSDT": {"BTCUSDT": 0.97, "BNBUSDT": 0.96},
			"BNBUSDT": {"BTCUSDT": 0.95, "ETHUSDT": 0.96},
		},
		Liquidity: LiquidityProfile{
			NormalSpreadBps:  5,
			PeakSpreadBps:    150,
			SpreadMultiplier: 30,
			DepthRatio:       0.05,
		},
		Severity: 0.97,
		Tags:     []string{"covid", "2020", "crash", "liquidity", "corr-convergence"},
		PeakDrawdown: map[string]float64{
			"BTCUSDT": -0.455,
			"ETHUSDT": -0.520,
			"BNBUSDT": -0.462,
		},
	}
}

// buildLUNACrash constructs the May 7–13 2022 LUNA/UST collapse.
// UST stablecoin depegged, triggering LUNA hyperinflation: $87 → $0.0001 in 6 days.
// The death spiral (mint LUNA to defend UST peg → LUNA supply explosion → LUNA worthless)
// is the single largest wealth destruction event in crypto history.
func buildLUNACrash() CrashProfile {
	const seed = 2022050711
	const nBars = 144 // 6 days × 24h
	start := time.Date(2022, 5, 7, 0, 0, 0, 0, time.UTC)
	assets := []string{"LUNAUSDT", "BTCUSDT", "ETHUSDT", "USTUSDT"}

	luna := buildPriceSeries(start, nBars, 87.0, []priceWaypoint{
		{24, 60}, {48, 16}, {72, 0.80}, {96, 0.04}, {120, 0.001}, {144, 0.0001},
	}, 8.0, seed)
	ust := buildPriceSeries(start, nBars, 1.00, []priceWaypoint{
		{24, 0.92}, {48, 0.60}, {72, 0.20}, {96, 0.12}, {144, 0.08},
	}, 1.5, seed+1)
	btc := buildPriceSeries(start, nBars, 35000, []priceWaypoint{
		{48, 31000}, {96, 28500}, {144, 29000},
	}, 1.8, seed+2)
	eth := buildPriceSeries(start, nBars, 2700, []priceWaypoint{
		{48, 2300}, {96, 1900}, {144, 1980},
	}, 2.0, seed+3)

	applyVolumeSpike(luna, 24, 96, 35.0, seed+10)
	applyVolumeSpike(btc, 24, 72, 4.0, seed+11)
	applyVolumeSpike(eth, 24, 72, 3.5, seed+12)
	applyVolumeSpike(ust, 24, 96, 20.0, seed+13)

	return CrashProfile{
		ID:           "crash_2022_luna",
		Name:         "LUNA/UST Collapse (May 7–13 2022)",
		Description:  "UST stablecoin depeg triggered LUNA hyperinflation: $87 → $0.0001 over 6 days. Algorithmic death spiral, DeFi contagion, BTC -30%, exchange trading halts.",
		StartTime:    start,
		DurationBars: nBars,
		Assets:       assets,
		PriceSeries:  map[string][]OHLCV{"LUNAUSDT": luna, "BTCUSDT": btc, "ETHUSDT": eth, "USTUSDT": ust},
		NormalCorr: CorrelationMatrix{
			"LUNAUSDT": {"BTCUSDT": 0.60, "ETHUSDT": 0.58, "USTUSDT": -0.10},
			"BTCUSDT":  {"LUNAUSDT": 0.60, "ETHUSDT": 0.72, "USTUSDT": -0.05},
			"ETHUSDT":  {"LUNAUSDT": 0.58, "BTCUSDT": 0.72, "USTUSDT": -0.08},
			"USTUSDT":  {"LUNAUSDT": -0.10, "BTCUSDT": -0.05, "ETHUSDT": -0.08},
		},
		CrashCorr: CorrelationMatrix{
			"LUNAUSDT": {"BTCUSDT": 0.92, "ETHUSDT": 0.90, "USTUSDT": 0.85},
			"BTCUSDT":  {"LUNAUSDT": 0.92, "ETHUSDT": 0.97, "USTUSDT": 0.20},
			"ETHUSDT":  {"LUNAUSDT": 0.90, "BTCUSDT": 0.97, "USTUSDT": 0.18},
			"USTUSDT":  {"LUNAUSDT": 0.85, "BTCUSDT": 0.20, "ETHUSDT": 0.18},
		},
		Liquidity: LiquidityProfile{
			NormalSpreadBps:  12,
			PeakSpreadBps:    600,
			SpreadMultiplier: 50,
			DepthRatio:       0.02,
		},
		Severity: 0.99,
		Tags:     []string{"luna", "ust", "defi", "2022", "stablecoin", "hyperinflation", "contagion", "crash"},
		PeakDrawdown: map[string]float64{
			"LUNAUSDT": -0.9999,
			"USTUSDT":  -0.92,
			"BTCUSDT":  -0.30,
			"ETHUSDT":  -0.35,
		},
	}
}

// buildFTXCrash constructs the November 6–11 2022 FTX collapse.
// CoinDesk published a Binance/FTX balance sheet story on Nov 6; CZ announced
// FTT selloff on Nov 7; FTX halted withdrawals Nov 8; filed Chapter 11 Nov 11.
func buildFTXCrash() CrashProfile {
	const seed = 2022110611
	const nBars = 120 // 5 days × 24h
	start := time.Date(2022, 11, 6, 0, 0, 0, 0, time.UTC)
	assets := []string{"BTCUSDT", "FTTUSDT", "SOLUSDT", "ETHUSDT"}

	btc := buildPriceSeries(start, nBars, 21000, []priceWaypoint{
		{24, 19500}, {48, 17200}, {72, 16100}, {96, 16500}, {120, 16800},
	}, 1.2, seed)
	ftt := buildPriceSeries(start, nBars, 25.0, []priceWaypoint{
		{12, 18.0}, {24, 8.0}, {48, 2.0}, {72, 0.50}, {120, 0.25},
	}, 6.0, seed+1)
	sol := buildPriceSeries(start, nBars, 35.0, []priceWaypoint{
		{24, 26.0}, {48, 16.0}, {72, 12.5}, {120, 13.5},
	}, 2.5, seed+2)
	eth := buildPriceSeries(start, nBars, 1580, []priceWaypoint{
		{24, 1440}, {48, 1220}, {72, 1170}, {120, 1220},
	}, 1.4, seed+3)

	applyVolumeSpike(btc, 8, 72, 4.5, seed+10)
	applyVolumeSpike(ftt, 8, 72, 15.0, seed+11)
	applyVolumeSpike(sol, 12, 72, 6.0, seed+12)
	applyVolumeSpike(eth, 12, 60, 3.5, seed+13)

	return CrashProfile{
		ID:           "crash_2022_ftx",
		Name:         "FTX Collapse (Nov 6–11 2022)",
		Description:  "FTX bankruptcy: BTC -25%, FTT -97%, SOL -60%. Exchange bank-run, withdrawal halts, systemic counter-party risk. Second-largest exchange failure in history.",
		StartTime:    start,
		DurationBars: nBars,
		Assets:       assets,
		PriceSeries:  map[string][]OHLCV{"BTCUSDT": btc, "FTTUSDT": ftt, "SOLUSDT": sol, "ETHUSDT": eth},
		NormalCorr: CorrelationMatrix{
			"BTCUSDT":  {"FTTUSDT": 0.45, "SOLUSDT": 0.62, "ETHUSDT": 0.72},
			"FTTUSDT":  {"BTCUSDT": 0.45, "SOLUSDT": 0.55, "ETHUSDT": 0.40},
			"SOLUSDT":  {"BTCUSDT": 0.62, "FTTUSDT": 0.55, "ETHUSDT": 0.68},
			"ETHUSDT":  {"BTCUSDT": 0.72, "FTTUSDT": 0.40, "SOLUSDT": 0.68},
		},
		CrashCorr: CorrelationMatrix{
			"BTCUSDT":  {"FTTUSDT": 0.90, "SOLUSDT": 0.95, "ETHUSDT": 0.96},
			"FTTUSDT":  {"BTCUSDT": 0.90, "SOLUSDT": 0.93, "ETHUSDT": 0.88},
			"SOLUSDT":  {"BTCUSDT": 0.95, "FTTUSDT": 0.93, "ETHUSDT": 0.94},
			"ETHUSDT":  {"BTCUSDT": 0.96, "FTTUSDT": 0.88, "SOLUSDT": 0.94},
		},
		Liquidity: LiquidityProfile{
			NormalSpreadBps:  5,
			PeakSpreadBps:    80,
			SpreadMultiplier: 16,
			DepthRatio:       0.15,
		},
		Severity: 0.90,
		Tags:     []string{"ftx", "exchange", "contagion", "2022", "counterparty", "crash"},
		PeakDrawdown: map[string]float64{
			"BTCUSDT":  -0.25,
			"FTTUSDT":  -0.97,
			"SOLUSDT":  -0.60,
			"ETHUSDT":  -0.26,
		},
	}
}

// buildMay2021Crash constructs the May 12–26 2021 China mining ban crash.
// BTC fell ~47% over 14 days driven by China mining/transaction ban announcements
// and cascading liquidations. Unlike the COVID crash, this was a sustained grind
// down rather than a single-session collapse.
func buildMay2021Crash() CrashProfile {
	const seed = 2021051900
	const nBars = 336 // 14 days × 24h
	start := time.Date(2021, 5, 12, 0, 0, 0, 0, time.UTC)
	assets := []string{"BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT"}

	btc := buildPriceSeries(start, nBars, 57000, []priceWaypoint{
		{24, 52000}, {72, 43000}, {120, 38000}, {168, 33000}, {240, 30500}, {336, 35000},
	}, 1.6, seed)
	eth := buildPriceSeries(start, nBars, 3900, []priceWaypoint{
		{24, 3500}, {72, 2800}, {120, 2300}, {168, 2000}, {240, 1730}, {336, 2200},
	}, 1.8, seed+1)
	sol := buildPriceSeries(start, nBars, 52.0, []priceWaypoint{
		{24, 46.0}, {72, 35.0}, {168, 25.0}, {240, 22.0}, {336, 28.0},
	}, 2.2, seed+2)
	ada := buildPriceSeries(start, nBars, 1.80, []priceWaypoint{
		{72, 1.50}, {168, 1.20}, {240, 0.95}, {336, 1.10},
	}, 2.0, seed+3)

	applyVolumeSpike(btc, 60, 180, 3.5, seed+10)
	applyVolumeSpike(eth, 60, 180, 3.0, seed+11)
	applyVolumeSpike(sol, 60, 200, 3.8, seed+12)
	applyVolumeSpike(ada, 60, 200, 2.5, seed+13)

	return CrashProfile{
		ID:           "crash_2021_may",
		Name:         "May 2021 Crash (China Mining Ban)",
		Description:  "BTC -47% over 14 days driven by China mining/transaction ban and liquidation cascade. Sustained drawdown with multiple false recoveries, not a single-session shock.",
		StartTime:    start,
		DurationBars: nBars,
		Assets:       assets,
		PriceSeries:  map[string][]OHLCV{"BTCUSDT": btc, "ETHUSDT": eth, "SOLUSDT": sol, "ADAUSDT": ada},
		NormalCorr: CorrelationMatrix{
			"BTCUSDT": {"ETHUSDT": 0.70, "SOLUSDT": 0.65, "ADAUSDT": 0.62},
			"ETHUSDT": {"BTCUSDT": 0.70, "SOLUSDT": 0.72, "ADAUSDT": 0.68},
			"SOLUSDT": {"BTCUSDT": 0.65, "ETHUSDT": 0.72, "ADAUSDT": 0.75},
			"ADAUSDT": {"BTCUSDT": 0.62, "ETHUSDT": 0.68, "SOLUSDT": 0.75},
		},
		CrashCorr: CorrelationMatrix{
			"BTCUSDT": {"ETHUSDT": 0.94, "SOLUSDT": 0.92, "ADAUSDT": 0.91},
			"ETHUSDT": {"BTCUSDT": 0.94, "SOLUSDT": 0.93, "ADAUSDT": 0.92},
			"SOLUSDT": {"BTCUSDT": 0.92, "ETHUSDT": 0.93, "ADAUSDT": 0.94},
			"ADAUSDT": {"BTCUSDT": 0.91, "ETHUSDT": 0.92, "SOLUSDT": 0.94},
		},
		Liquidity: LiquidityProfile{
			NormalSpreadBps:  5,
			PeakSpreadBps:    50,
			SpreadMultiplier: 10,
			DepthRatio:       0.25,
		},
		Severity: 0.88,
		Tags:     []string{"china", "mining-ban", "2021", "crash", "liquidation"},
		PeakDrawdown: map[string]float64{
			"BTCUSDT": -0.47,
			"ETHUSDT": -0.56,
			"SOLUSDT": -0.58,
			"ADAUSDT": -0.47,
		},
	}
}

// ---------------------------------------------------------------------------
// Price series generation
// ---------------------------------------------------------------------------

// priceWaypoint specifies a target price at a given bar index.
type priceWaypoint struct {
	barIdx int
	price  float64
}

// buildPriceSeries generates a realistic OHLCV hourly bar series.
//
// Construction:
//  1. Log-linearly interpolate between waypoints (piecewise drift).
//  2. Each bar adds fat-tail noise: Box-Muller normal + 5% chance of a 2–5σ jump
//     biased downward (80% negative), replicating crash kurtosis of 5–15.
//  3. A 30%-per-bar mean-reversion pull toward the target prevents path runaway.
//  4. High/Low are constructed from intrabar volatility around Open/Close.
//  5. Volume is proportional to |return| with a quadratic kurtotic term.
//
// The seed is fixed so the series is deterministic and reproducible across runs.
func buildPriceSeries(
	startTime time.Time,
	nBars int,
	startPrice float64,
	waypoints []priceWaypoint,
	annualVol float64,
	seed int64,
) []OHLCV {
	rng := rand.New(rand.NewSource(seed)) //nolint:gosec
	hourlyVol := annualVol / math.Sqrt(8760.0)

	// Build piecewise log-linear target path including the implicit bar-0 waypoint.
	wps := append([]priceWaypoint{{0, startPrice}}, waypoints...)
	sort.Slice(wps, func(i, j int) bool { return wps[i].barIdx < wps[j].barIdx })

	logTargets := make([]float64, nBars+1)
	logTargets[0] = math.Log(math.Max(startPrice, 1e-10))
	for seg := 0; seg+1 < len(wps); seg++ {
		from, to := wps[seg], wps[seg+1]
		fromLog := math.Log(math.Max(from.price, 1e-10))
		toLog := math.Log(math.Max(to.price, 1e-10))
		n := to.barIdx - from.barIdx
		if n <= 0 {
			continue
		}
		for b := from.barIdx + 1; b <= to.barIdx && b <= nBars; b++ {
			frac := float64(b-from.barIdx) / float64(n)
			logTargets[b] = fromLog + frac*(toLog-fromLog)
		}
	}
	// Pad any bars beyond the last waypoint.
	last := wps[len(wps)-1]
	lastLog := math.Log(math.Max(last.price, 1e-10))
	for b := last.barIdx + 1; b <= nBars; b++ {
		logTargets[b] = lastLog
	}

	// Generate close prices with fat-tail noise.
	closes := make([]float64, nBars+1)
	closes[0] = startPrice
	logPrice := math.Log(math.Max(startPrice, 1e-10))

	for i := 1; i <= nBars; i++ {
		// Mean-reversion pull toward target (30% per bar prevents runaway).
		drift := (logTargets[i] - logPrice) * 0.30

		// Box-Muller normal variate.
		u1 := math.Max(1e-10, rng.Float64())
		u2 := rng.Float64()
		z := math.Sqrt(-2*math.Log(u1)) * math.Cos(2*math.Pi*u2)

		// Fat-tail jump: 5% probability, magnitude 2–5σ, 80% downward.
		jump := 0.0
		if rng.Float64() < 0.05 {
			mag := (2.0 + rng.Float64()*3.0) * hourlyVol
			if rng.Float64() < 0.80 {
				jump = -mag
			} else {
				jump = mag
			}
		}

		logPrice += drift + hourlyVol*z + jump
		closes[i] = math.Max(math.Exp(logPrice), 1e-10)
	}

	bars := make([]OHLCV, nBars)
	for i := 0; i < nBars; i++ {
		open := closes[i]
		close := closes[i+1]
		ret := math.Abs(close/math.Max(open, 1e-10) - 1)

		// Intrabar high/low: expand around open/close by intrabar vol.
		intraRange := math.Min(hourlyVol*(1.0+rng.Float64()*2.0)*0.5, 0.99)
		high := math.Max(open, close) * (1 + intraRange)
		low := math.Max(math.Min(open, close)*(1-intraRange), 1e-10)

		// Volume spikes with large returns (kurtotic relationship).
		volFactor := 1.0 + ret*20.0 + math.Pow(ret*10, 2)*5.0
		volume := math.Max(volFactor*(0.8+rng.Float64()*0.4), 0.01)

		bars[i] = OHLCV{
			Timestamp: startTime.Add(time.Duration(i) * time.Hour),
			Open:      open,
			High:      high,
			Low:       low,
			Close:     close,
			Volume:    volume,
		}
	}
	return bars
}

// applyVolumeSpike multiplies volume in bars [fromBar, toBar) by a tapered spike.
// The spike is bell-shaped (peak in the middle) and jittered with a seeded RNG.
func applyVolumeSpike(bars []OHLCV, fromBar, toBar int, factor float64, seed int64) {
	rng := rand.New(rand.NewSource(seed)) //nolint:gosec
	if toBar > len(bars) {
		toBar = len(bars)
	}
	if fromBar >= toBar {
		return
	}
	mid := float64(fromBar+toBar) / 2.0
	halfWidth := float64(toBar-fromBar) / 2.0
	for i := fromBar; i < toBar; i++ {
		dist := math.Abs(float64(i) - mid)
		taper := 1.0 - 0.5*(dist/halfWidth)
		spike := factor * taper * (0.7 + rng.Float64()*0.6)
		bars[i].Volume *= spike
	}
}

// ---------------------------------------------------------------------------
// StressTestRunner
// ---------------------------------------------------------------------------

// CrashStrategyFn receives per-bar close prices and returns position weights.
// weights[asset] ∈ [-1.0, 1.0]: positive = long, negative = short, 0 = flat.
// barIdx is the current bar (0 = pre-crash open bar, before any price moves).
type CrashStrategyFn func(barIdx int, closes map[string]float64) map[string]float64

// StressMetrics captures strategy performance during a single crash scenario.
type StressMetrics struct {
	ScenarioID     string
	ScenarioName   string
	Sharpe         float64 // annualised Sharpe (hourly basis, √8760 scaling)
	MaxDrawdown    float64 // most negative peak-to-trough fraction (e.g. -0.35)
	TimeToRecovery int     // bars for equity to recover to 1.0; -1 if never
	CVaR99         float64 // conditional VaR at 99% (average of worst 1% of bar returns)
	Tags           []string
	BarReturns     []float64 // bar-by-bar portfolio returns (for custom analysis)
}

// StressTestReport aggregates stress metrics across all crash scenarios.
type StressTestReport struct {
	Metrics       []StressMetrics
	ByScenario    map[string]*StressMetrics
	ByTag         map[string][]*StressMetrics
	WorstSharpe   *StressMetrics // scenario with lowest Sharpe
	WorstDrawdown *StressMetrics // scenario with most negative MaxDrawdown
	WorstCVaR     *StressMetrics // scenario with most negative CVaR99
}

// StressTestRunner runs a strategy bar-by-bar through each crash profile and
// computes regime-conditional metrics: Sharpe, max drawdown, time-to-recovery,
// and CVaR 99%.
type StressTestRunner struct {
	provider *CrashScenarioProvider
}

// NewStressTestRunner creates a new runner backed by the given crash provider.
func NewStressTestRunner(provider *CrashScenarioProvider) *StressTestRunner {
	return &StressTestRunner{provider: provider}
}

// Run executes the strategy against each crash scenario and returns a StressTestReport.
// Pass nil for strategy to use equal-weight buy-and-hold (the worst-case baseline).
func (r *StressTestRunner) Run(strategy CrashStrategyFn) StressTestReport {
	if strategy == nil {
		strategy = equalWeightLong
	}
	report := StressTestReport{
		ByScenario: make(map[string]*StressMetrics),
		ByTag:      make(map[string][]*StressMetrics),
	}
	for _, profile := range r.provider.All() {
		m := runOneProfile(strategy, profile)
		report.Metrics = append(report.Metrics, m)
		ptr := &report.Metrics[len(report.Metrics)-1]
		report.ByScenario[profile.ID] = ptr
		for _, tag := range profile.Tags {
			report.ByTag[tag] = append(report.ByTag[tag], ptr)
		}
	}
	for i := range report.Metrics {
		m := &report.Metrics[i]
		if report.WorstSharpe == nil || m.Sharpe < report.WorstSharpe.Sharpe {
			report.WorstSharpe = m
		}
		if report.WorstDrawdown == nil || m.MaxDrawdown < report.WorstDrawdown.MaxDrawdown {
			report.WorstDrawdown = m
		}
		if report.WorstCVaR == nil || m.CVaR99 < report.WorstCVaR.CVaR99 {
			report.WorstCVaR = m
		}
	}
	return report
}

// runOneProfile simulates the strategy bar-by-bar through a crash profile.
func runOneProfile(strategy CrashStrategyFn, profile CrashProfile) StressMetrics {
	nBars := profile.DurationBars

	// Build per-bar close price maps: index 0 = bar[0].Open (pre-crash level).
	closePrices := make([]map[string]float64, nBars+1)
	for i := range closePrices {
		closePrices[i] = make(map[string]float64, len(profile.Assets))
	}
	for _, asset := range profile.Assets {
		series, ok := profile.PriceSeries[asset]
		if !ok || len(series) == 0 {
			continue
		}
		closePrices[0][asset] = series[0].Open
		for i, bar := range series {
			if i+1 <= nBars {
				closePrices[i+1][asset] = bar.Close
			}
		}
	}

	barReturns := make([]float64, 0, nBars)
	for bar := 0; bar < nBars; bar++ {
		weights := strategy(bar, closePrices[bar])
		portRet := 0.0
		for asset, w := range weights {
			prev := closePrices[bar][asset]
			next := closePrices[bar+1][asset]
			if prev > 0 && next > 0 {
				portRet += w * (next/prev - 1.0)
			}
		}
		barReturns = append(barReturns, portRet)
	}

	return StressMetrics{
		ScenarioID:     profile.ID,
		ScenarioName:   profile.Name,
		Sharpe:         crashSharpe(barReturns),
		MaxDrawdown:    crashMaxDrawdown(barReturns),
		TimeToRecovery: crashTimeToRecovery(barReturns),
		CVaR99:         crashCVaR(barReturns, 0.99),
		Tags:           profile.Tags,
		BarReturns:     barReturns,
	}
}

// equalWeightLong is the default strategy: equal weight long all available assets.
func equalWeightLong(_ int, closes map[string]float64) map[string]float64 {
	if len(closes) == 0 {
		return nil
	}
	w := 1.0 / float64(len(closes))
	weights := make(map[string]float64, len(closes))
	for asset := range closes {
		weights[asset] = w
	}
	return weights
}

// ---------------------------------------------------------------------------
// Metric helpers
// ---------------------------------------------------------------------------

// crashSharpe computes the annualised Sharpe ratio from hourly bar returns.
// Uses √8760 to annualise (8760 trading hours per year for 24/7 crypto markets).
func crashSharpe(returns []float64) float64 {
	if len(returns) < 2 {
		return 0.0
	}
	m := mean(returns)
	s := stdev(returns)
	if s == 0 {
		return 0.0
	}
	return m / s * math.Sqrt(8760.0)
}

// crashMaxDrawdown computes the peak-to-trough max drawdown from a return series.
// Returns a negative fraction, e.g. -0.35 means the equity fell 35% from its peak.
func crashMaxDrawdown(returns []float64) float64 {
	equity := 1.0
	peak := 1.0
	maxDD := 0.0
	for _, r := range returns {
		equity *= (1 + r)
		if equity > peak {
			peak = equity
		}
		if dd := (equity - peak) / peak; dd < maxDD {
			maxDD = dd
		}
	}
	return maxDD
}

// crashTimeToRecovery returns how many bars it takes for the equity curve to
// recover to its starting level (≥ 1.0). Returns -1 if it never recovers.
func crashTimeToRecovery(returns []float64) int {
	equity := 1.0
	fallen := false
	for i, r := range returns {
		equity *= (1 + r)
		if equity < 1.0 {
			fallen = true
		}
		if fallen && equity >= 1.0 {
			return i + 1
		}
	}
	return -1
}

// crashCVaR computes Conditional Value at Risk (CVaR / Expected Shortfall) at
// the given confidence level. Returns the mean of the worst (1-confidence)
// fraction of bar returns. E.g. confidence=0.99 → average of worst 1%.
func crashCVaR(returns []float64, confidence float64) float64 {
	if len(returns) == 0 {
		return 0.0
	}
	sorted := make([]float64, len(returns))
	copy(sorted, returns)
	sort.Float64s(sorted)
	cutoff := int(math.Ceil(float64(len(sorted)) * (1 - confidence)))
	if cutoff < 1 {
		cutoff = 1
	}
	if cutoff > len(sorted) {
		cutoff = len(sorted)
	}
	var sum float64
	for i := 0; i < cutoff; i++ {
		sum += sorted[i]
	}
	return sum / float64(cutoff)
}

// ---------------------------------------------------------------------------
// Bootstrap resampling
// ---------------------------------------------------------------------------

// BootstrapCrashScenarios generates nScenarios novel crash profiles by
// block-resampling the given profile's price series with replacement.
//
// Block resampling divides the original series into consecutive blocks of
// blockSize bars. Blocks are sampled with replacement and concatenated to
// form new series of the same total length. This preserves intra-block serial
// dependence and volatility clustering while allowing novel combinations that
// the original history never saw.
//
// Pass blockSize=0 to use the default of 24 bars (one trading day).
// Returned profiles have IDs of the form "<original_id>_boot_<n>".
func BootstrapCrashScenarios(profile CrashProfile, nScenarios, blockSize int, seed int64) []CrashProfile {
	if blockSize <= 0 {
		blockSize = 24
	}
	rng := rand.New(rand.NewSource(seed)) //nolint:gosec
	results := make([]CrashProfile, 0, nScenarios)
	for s := 0; s < nScenarios; s++ {
		bp := bootstrapOne(profile, blockSize, rng)
		bp.ID = fmt.Sprintf("%s_boot_%d", profile.ID, s)
		bp.Name = fmt.Sprintf("%s [Bootstrap %d]", profile.Name, s)
		bp.Tags = append(append([]string{}, profile.Tags...), "bootstrap")
		results = append(results, bp)
	}
	return results
}

func bootstrapOne(profile CrashProfile, blockSize int, rng *rand.Rand) CrashProfile {
	nBars := profile.DurationBars
	nBlocks := int(math.Ceil(float64(nBars) / float64(blockSize)))

	newSeries := make(map[string][]OHLCV, len(profile.Assets))
	for _, asset := range profile.Assets {
		original, ok := profile.PriceSeries[asset]
		if !ok || len(original) == 0 {
			continue
		}
		resampled := resampleBlocks(original, blockSize, nBlocks, rng)
		if len(resampled) > nBars {
			resampled = resampled[:nBars]
		}
		// Re-anchor to original start price so return profiles are comparable.
		if len(resampled) > 0 && resampled[0].Open > 0 {
			scale := original[0].Open / resampled[0].Open
			if scale > 0 && !math.IsInf(scale, 0) && !math.IsNaN(scale) {
				for i := range resampled {
					resampled[i].Open *= scale
					resampled[i].High *= scale
					resampled[i].Low *= scale
					resampled[i].Close *= scale
				}
			}
		}
		newSeries[asset] = resampled
	}

	return CrashProfile{
		ID:           profile.ID,
		Name:         profile.Name,
		Description:  profile.Description + " (bootstrapped)",
		StartTime:    profile.StartTime,
		DurationBars: nBars,
		Assets:       profile.Assets,
		PriceSeries:  newSeries,
		NormalCorr:   profile.NormalCorr,
		CrashCorr:    profile.CrashCorr,
		Liquidity:    profile.Liquidity,
		Severity:     profile.Severity,
		PeakDrawdown: profile.PeakDrawdown,
	}
}

// resampleBlocks samples nBlocks blocks of blockSize bars from original with replacement.
func resampleBlocks(original []OHLCV, blockSize, nBlocks int, rng *rand.Rand) []OHLCV {
	if len(original) == 0 {
		return nil
	}
	if blockSize > len(original) {
		blockSize = len(original)
	}
	maxStart := len(original) - blockSize
	result := make([]OHLCV, 0, nBlocks*blockSize)
	for b := 0; b < nBlocks; b++ {
		start := 0
		if maxStart > 0 {
			start = rng.Intn(maxStart + 1) //nolint:gosec
		}
		result = append(result, original[start:start+blockSize]...)
	}
	return result
}
