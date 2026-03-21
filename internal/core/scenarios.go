package core

// Ring 2 infrastructure: historical scenario storage, synthetic scenario
// generation, scenario-based resilience testing, and the SimulationGate
// go/no-go decision before a strategy goes live.

import (
	"context"
	"fmt"
	"log/slog"
	"math"
	"math/rand"
	"sort"
	"time"

	"github.com/google/uuid"
)

// ---------------------------------------------------------------------------
// Supplementary types
// ---------------------------------------------------------------------------

// ScenarioRecord is a scenario stored in the bank, with metadata.
type ScenarioRecord struct {
	Scenario  Scenario
	Tags      []string
	Source    string // "historical" | "synthetic" | "user"
	CreatedAt time.Time
	Notes     string
}

// RunResult is the result of running a single scenario through a strategy.
type RunResult struct {
	ScenarioID     string
	ScenarioName   string
	Severity       float64
	RawOutput      map[string]float64
	ResilienceScore float64 // 0 (catastrophic) → 1 (perfect)
	Passed         bool    // True if resilience_score >= gate threshold
	Details        map[string]any
}

// SimulationReport is the aggregated report from ScenarioRunner covering all scenarios.
type SimulationReport struct {
	StrategyID       string
	RunResults       []RunResult
	OverallResilience float64
	WorstScenario    string
	WorstResilience  float64
	GatePassed       bool
	GateReason       string
}

// StrategyCallable is a strategy under test. It receives stressed signals and
// the scenario, and returns an output signal dict.
type StrategyCallable func(signals map[string]float64, scenario Scenario) map[string]float64

// ResilienceScorer maps strategy output and scenario to a resilience score in [0,1].
type ResilienceScorer func(output map[string]float64, scenario Scenario) float64

// ---------------------------------------------------------------------------
// HistoricalScenarioBank
// ---------------------------------------------------------------------------

// HistoricalScenarioBank stores known market scenarios and retrieves them by
// tag or severity. Pre-loaded with canonical scenarios at construction.
type HistoricalScenarioBank struct {
	records map[string]ScenarioRecord
}

// NewHistoricalScenarioBank creates a bank pre-populated with canonical scenarios.
func NewHistoricalScenarioBank() *HistoricalScenarioBank {
	b := &HistoricalScenarioBank{records: make(map[string]ScenarioRecord)}
	b.loadCanonical()
	return b
}

// Add adds a scenario record, keyed by scenario_id.
func (b *HistoricalScenarioBank) Add(record ScenarioRecord) {
	sid := record.Scenario.ScenarioID
	b.records[sid] = record
	slog.Debug("ScenarioBank: added", "id", sid, "tags", record.Tags)
}

// Get retrieves a scenario record by ID.
func (b *HistoricalScenarioBank) Get(scenarioID string) (ScenarioRecord, bool) {
	r, ok := b.records[scenarioID]
	return r, ok
}

// GetByTag returns all records with the given tag.
func (b *HistoricalScenarioBank) GetByTag(tag string) []ScenarioRecord {
	var result []ScenarioRecord
	for _, r := range b.records {
		for _, t := range r.Tags {
			if t == tag {
				result = append(result, r)
				break
			}
		}
	}
	return result
}

// GetBySeverity returns records within the severity range [minSeverity, maxSeverity].
func (b *HistoricalScenarioBank) GetBySeverity(minSeverity, maxSeverity float64) []ScenarioRecord {
	var result []ScenarioRecord
	for _, r := range b.records {
		if r.Scenario.Severity >= minSeverity && r.Scenario.Severity <= maxSeverity {
			result = append(result, r)
		}
	}
	return result
}

// AllScenarios returns all scenarios from the bank.
func (b *HistoricalScenarioBank) AllScenarios() []Scenario {
	result := make([]Scenario, 0, len(b.records))
	for _, r := range b.records {
		result = append(result, r.Scenario)
	}
	return result
}

// AllRecords returns all scenario records.
func (b *HistoricalScenarioBank) AllRecords() []ScenarioRecord {
	result := make([]ScenarioRecord, 0, len(b.records))
	for _, r := range b.records {
		result = append(result, r)
	}
	return result
}

// Len returns the number of scenarios in the bank.
func (b *HistoricalScenarioBank) Len() int { return len(b.records) }

func (b *HistoricalScenarioBank) loadCanonical() {
	type entry struct {
		scenario Scenario
		tags     []string
		source   string
	}
	canonical := []entry{
		{
			Scenario{
				ScenarioID:           "hist_2010_flash_crash",
				Name:                 "2010 Flash Crash",
				Description:          "6 May 2010 — DJIA lost ~9% intraday then recovered most losses within minutes.",
				MarketShocks:         map[string]float64{"BTCUSDT": -0.09, "ETHUSDT": -0.12, "SOLUSDT": -0.15, "BNBUSDT": -0.11},
				VolMultiplier:        4.5,
				CorrelationBreakdown: false,
				Severity:             0.80,
			},
			[]string{"crash", "flash", "historical", "intraday"},
			"historical",
		},
		{
			Scenario{
				ScenarioID:           "hist_2020_covid_crash",
				Name:                 "COVID Crash 2020",
				Description:          "March 2020: global markets dropped 30-40% as pandemic declared.",
				MarketShocks:         map[string]float64{"BTCUSDT": -0.50, "ETHUSDT": -0.55, "SOLUSDT": -0.60, "BNBUSDT": -0.48},
				VolMultiplier:        6.0,
				CorrelationBreakdown: false,
				Severity:             0.95,
			},
			[]string{"crash", "pandemic", "historical", "2020", "high-severity"},
			"historical",
		},
		{
			Scenario{
				ScenarioID:           "hist_2022_luna_collapse",
				Name:                 "LUNA/UST Collapse 2022",
				Description:          "May 2022: LUNA lost >99% in 72 hours; UST de-pegged.",
				MarketShocks:         map[string]float64{"BTCUSDT": -0.30, "ETHUSDT": -0.35, "SOLUSDT": -0.40, "BNBUSDT": -0.28, "ADAUSDT": -0.38},
				VolMultiplier:        5.0,
				CorrelationBreakdown: false,
				Severity:             0.90,
			},
			[]string{"crash", "defi", "contagion", "historical", "2022"},
			"historical",
		},
		{
			Scenario{
				ScenarioID:           "hist_2021_may_squeeze",
				Name:                 "May 2021 Short Squeeze",
				Description:          "May 2021: BTC dropped 50% from ATH amid China mining ban fears.",
				MarketShocks:         map[string]float64{"BTCUSDT": -0.50, "ETHUSDT": -0.45, "SOLUSDT": -0.42, "BNBUSDT": -0.48},
				VolMultiplier:        4.0,
				CorrelationBreakdown: false,
				Severity:             0.88,
			},
			[]string{"squeeze", "liquidation", "historical", "2021"},
			"historical",
		},
		{
			Scenario{
				ScenarioID:           "hist_2018_crypto_winter",
				Name:                 "Crypto Winter 2018",
				Description:          "2018 bear market: BTC fell from ~20k to ~3k (-85%).",
				MarketShocks:         map[string]float64{"BTCUSDT": -0.85, "ETHUSDT": -0.94, "SOLUSDT": -0.90, "BNBUSDT": -0.88, "ADAUSDT": -0.95},
				VolMultiplier:        2.5,
				CorrelationBreakdown: false,
				Severity:             0.97,
			},
			[]string{"bear", "regime-shift", "prolonged", "historical", "2018"},
			"historical",
		},
		{
			Scenario{
				ScenarioID:           "hist_2021_nft_mania",
				Name:                 "NFT/Alt Mania 2021 Q1",
				Description:          "Early 2021: BTC dominance fell as capital rotated to alts; ETH +400%, SOL +3000%.",
				MarketShocks:         map[string]float64{"BTCUSDT": 0.80, "ETHUSDT": 4.00, "SOLUSDT": 30.00, "BNBUSDT": 10.00, "ADAUSDT": 5.00},
				VolMultiplier:        3.5,
				CorrelationBreakdown: true,
				Severity:             0.70,
			},
			[]string{"bull", "mania", "rotation", "historical", "2021"},
			"historical",
		},
		{
			Scenario{
				ScenarioID:           "hist_2022_ftx_collapse",
				Name:                 "FTX Collapse 2022",
				Description:          "November 2022: FTX declared bankruptcy; BTC -25% in 48 h.",
				MarketShocks:         map[string]float64{"BTCUSDT": -0.25, "ETHUSDT": -0.28, "SOLUSDT": -0.60, "BNBUSDT": -0.20},
				VolMultiplier:        4.5,
				CorrelationBreakdown: false,
				Severity:             0.87,
			},
			[]string{"crash", "exchange", "contagion", "historical", "2022"},
			"historical",
		},
	}

	for _, e := range canonical {
		b.records[e.scenario.ScenarioID] = ScenarioRecord{
			Scenario:  e.scenario,
			Tags:      e.tags,
			Source:    e.source,
			CreatedAt: time.Now().UTC(),
			Notes:     "Pre-loaded canonical historical scenario.",
		}
	}
	slog.Info("HistoricalScenarioBank: loaded canonical scenarios", "count", len(b.records))
}

// ---------------------------------------------------------------------------
// SyntheticScenarioGenerator
// ---------------------------------------------------------------------------

// SyntheticMode represents a perturbation mode.
type SyntheticMode string

const (
	ModeAmplitudeScaling SyntheticMode = "amplitude_scaling"
	ModeTailShock        SyntheticMode = "tail_shock"
	ModeCorrelationNuke  SyntheticMode = "correlation_nuke"
	ModeRegimeFlip       SyntheticMode = "regime_flip"
	ModeVolExplosion     SyntheticMode = "vol_explosion"
)

var allModes = []SyntheticMode{
	ModeAmplitudeScaling,
	ModeTailShock,
	ModeCorrelationNuke,
	ModeRegimeFlip,
	ModeVolExplosion,
}

// SyntheticScenarioGenerator creates stress-test scenarios by perturbing market data.
type SyntheticScenarioGenerator struct {
	rng *rand.Rand
}

// NewSyntheticScenarioGenerator creates a new generator with optional seed.
func NewSyntheticScenarioGenerator(seed int64, useSeed bool) *SyntheticScenarioGenerator {
	var rng *rand.Rand
	if useSeed {
		rng = rand.New(rand.NewSource(seed)) //nolint:gosec
	} else {
		rng = rand.New(rand.NewSource(rand.Int63())) //nolint:gosec
	}
	return &SyntheticScenarioGenerator{rng: rng}
}

// Generate generates nScenarios synthetic scenarios from baseSignals.
func (g *SyntheticScenarioGenerator) Generate(baseSignals map[string]float64, nScenarios int, modes []SyntheticMode) []Scenario {
	if len(baseSignals) == 0 {
		slog.Warn("SyntheticScenarioGenerator: empty base_signals")
		return nil
	}
	if modes == nil {
		modes = allModes
	}
	scenarios := make([]Scenario, 0, nScenarios)
	for i := 0; i < nScenarios; i++ {
		mode := modes[g.rng.Intn(len(modes))]
		scenarios = append(scenarios, g.applyMode(mode, baseSignals, -1, false))
	}
	sort.Slice(scenarios, func(i, j int) bool { return scenarios[i].Severity > scenarios[j].Severity })
	slog.Debug("SyntheticScenarioGenerator: generated scenarios", "count", len(scenarios))
	return scenarios
}

// Perturb generates exactly one scenario with a specific mode and intensity.
func (g *SyntheticScenarioGenerator) Perturb(baseSignals map[string]float64, mode SyntheticMode, intensity float64) Scenario {
	return g.applyMode(mode, baseSignals, intensity, true)
}

func (g *SyntheticScenarioGenerator) applyMode(mode SyntheticMode, base map[string]float64, intensity float64, hasIntensity bool) Scenario {
	sid := fmt.Sprintf("synth_%s_%s", mode, uuid.New().String()[:6])

	switch mode {
	case ModeAmplitudeScaling:
		var factor float64
		if hasIntensity {
			factor = -intensity * 0.30
		} else {
			factor = -0.40 + g.rng.Float64()*0.30 // uniform [-0.40, -0.10]
		}
		shocks := make(map[string]float64, len(base))
		for t := range base {
			shocks[t] = factor
		}
		severity := math.Min(1.0, math.Abs(factor)+0.30)
		return Scenario{
			ScenarioID:           sid,
			Name:                 fmt.Sprintf("Amplitude Scaling (%+.0f%%)", factor*100),
			Description:          fmt.Sprintf("All signals scaled by %+.1f%%.", factor*100),
			MarketShocks:         shocks,
			VolMultiplier:        1.5 + g.rng.Float64()*1.0,
			CorrelationBreakdown: false,
			Severity:             severity,
		}

	case ModeTailShock:
		type kv struct {
			ticker string
			val    float64
		}
		sorted := make([]kv, 0, len(base))
		for t, v := range base {
			sorted = append(sorted, kv{t, v})
		}
		sort.Slice(sorted, func(i, j int) bool { return sorted[i].val > sorted[j].val })
		topTicker := sorted[0].ticker
		var shockMag float64
		if hasIntensity {
			shockMag = -intensity
		} else {
			shockMag = -(0.35 + g.rng.Float64()*0.30)
		}
		shocks := make(map[string]float64, len(base))
		for t := range base {
			if t == topTicker {
				shocks[t] = shockMag
			} else {
				shocks[t] = shockMag * 0.3
			}
		}
		severity := math.Min(1.0, math.Abs(shockMag)+0.25)
		return Scenario{
			ScenarioID:           sid,
			Name:                 fmt.Sprintf("Tail Shock on %s", topTicker),
			Description:          fmt.Sprintf("Fat-tail shock of %.0f%% on %s.", shockMag*100, topTicker),
			MarketShocks:         shocks,
			VolMultiplier:        3.0 + g.rng.Float64()*2.0,
			CorrelationBreakdown: false,
			Severity:             severity,
		}

	case ModeCorrelationNuke:
		shocks := make(map[string]float64, len(base))
		for t := range base {
			shocks[t] = g.rng.Float64()*0.20 - 0.10 // uniform [-0.10, 0.10]
		}
		return Scenario{
			ScenarioID:           sid,
			Name:                 "Correlation Nuke",
			Description:          "All inter-asset correlations collapse; independent random shocks.",
			MarketShocks:         shocks,
			VolMultiplier:        2.0 + g.rng.Float64()*1.0,
			CorrelationBreakdown: true,
			Severity:             0.65 + g.rng.Float64()*0.15,
		}

	case ModeRegimeFlip:
		shocks := make(map[string]float64, len(base))
		for t, sig := range base {
			shocks[t] = -sig * 0.5
		}
		return Scenario{
			ScenarioID:           sid,
			Name:                 "Regime Flip",
			Description:          "All signal directions invert — regime change stress test.",
			MarketShocks:         shocks,
			VolMultiplier:        2.5,
			CorrelationBreakdown: false,
			Severity:             0.75,
		}

	case ModeVolExplosion:
		var multiplier float64
		if hasIntensity {
			multiplier = intensity * 8.0
		} else {
			multiplier = 5.0 + g.rng.Float64()*5.0
		}
		shocks := make(map[string]float64, len(base))
		for t := range base {
			shocks[t] = 0.0
		}
		return Scenario{
			ScenarioID:           sid,
			Name:                 fmt.Sprintf("Vol Explosion (x%.1f)", multiplier),
			Description:          fmt.Sprintf("Volatility explodes %.1fx; no directional shock.", multiplier),
			MarketShocks:         shocks,
			VolMultiplier:        multiplier,
			CorrelationBreakdown: true,
			Severity:             math.Min(1.0, 0.50+multiplier*0.04),
		}

	default:
		slog.Warn("SyntheticScenarioGenerator: unknown mode, returning zero-shock", "mode", mode)
		shocks := make(map[string]float64, len(base))
		for t := range base {
			shocks[t] = 0.0
		}
		return Scenario{
			ScenarioID:           sid,
			Name:                 fmt.Sprintf("Unknown Mode: %s", mode),
			Description:          "No-op scenario due to unknown mode.",
			MarketShocks:         shocks,
			VolMultiplier:        1.0,
			CorrelationBreakdown: false,
			Severity:             0.0,
		}
	}
}

// ---------------------------------------------------------------------------
// ScenarioRunner
// ---------------------------------------------------------------------------

// ScenarioRunner runs a strategy callable against a list of scenarios and
// scores resilience.
type ScenarioRunner struct {
	strategy         StrategyCallable
	resilienceScorer ResilienceScorer
	passThreshold    float64
	rng              *rand.Rand
}

// NewScenarioRunner creates a new ScenarioRunner.
func NewScenarioRunner(strategy StrategyCallable, scorer ResilienceScorer, passThreshold float64, seed int64, useSeed bool) *ScenarioRunner {
	if scorer == nil {
		scorer = defaultResilienceScorer
	}
	var rng *rand.Rand
	if useSeed {
		rng = rand.New(rand.NewSource(seed)) //nolint:gosec
	} else {
		rng = rand.New(rand.NewSource(rand.Int63())) //nolint:gosec
	}
	return &ScenarioRunner{
		strategy:         strategy,
		resilienceScorer: scorer,
		passThreshold:    passThreshold,
		rng:              rng,
	}
}

func defaultResilienceScorer(output map[string]float64, _ Scenario) float64 {
	if len(output) == 0 {
		return 0.0
	}
	var sumAbs float64
	for _, v := range output {
		sumAbs += math.Abs(v)
	}
	return math.Min(1.0, sumAbs/float64(len(output)))
}

func (r *ScenarioRunner) applyStress(baseSignals map[string]float64, scenario Scenario) map[string]float64 {
	stressed := make(map[string]float64, len(baseSignals))
	for ticker, sig := range baseSignals {
		shock := scenario.MarketShocks[ticker]
		val := sig * (1.0 + shock)
		if scenario.CorrelationBreakdown {
			val += r.rng.Float64()*0.20 - 0.10
		}
		val *= math.Min(1.0, 1.0/math.Max(1.0, scenario.VolMultiplier*0.2))
		stressed[ticker] = math.Max(-1.0, math.Min(1.0, val))
	}
	return stressed
}

// Run runs the strategy against each scenario and returns RunResult per scenario.
func (r *ScenarioRunner) Run(_ context.Context, scenarios []Scenario, baseSignals map[string]float64) []RunResult {
	results := make([]RunResult, 0, len(scenarios))
	for _, scenario := range scenarios {
		stressed := r.applyStress(baseSignals, scenario)
		var output map[string]float64
		func() {
			defer func() {
				if rec := recover(); rec != nil {
					slog.Warn("ScenarioRunner: strategy panicked", "scenario", scenario.ScenarioID, "error", rec)
					output = map[string]float64{}
				}
			}()
			output = r.strategy(stressed, scenario)
		}()

		resilience := r.resilienceScorer(output, scenario)
		passed := resilience >= r.passThreshold

		results = append(results, RunResult{
			ScenarioID:      scenario.ScenarioID,
			ScenarioName:    scenario.Name,
			Severity:        scenario.Severity,
			RawOutput:       output,
			ResilienceScore: resilience,
			Passed:          passed,
			Details: map[string]any{
				"stressed_signals": stressed,
				"base_signals":    baseSignals,
				"pass_threshold":  r.passThreshold,
			},
		})

		slog.Debug("ScenarioRunner",
			"scenario", scenario.Name,
			"severity", scenario.Severity,
			"resilience", resilience,
			"passed", passed,
		)
	}
	return results
}

// ---------------------------------------------------------------------------
// SimulationGate
// ---------------------------------------------------------------------------

// SimulationGateConfig holds configuration for SimulationGate.
type SimulationGateConfig struct {
	MinOverallResilience float64
	MinWorstCase         float64
	MinPassRate          float64
	MinSeverePassRate    float64
	SevereThreshold      float64
}

// DefaultSimulationGateConfig returns sensible defaults.
func DefaultSimulationGateConfig() SimulationGateConfig {
	return SimulationGateConfig{
		MinOverallResilience: 0.40,
		MinWorstCase:         0.15,
		MinPassRate:          0.70,
		MinSeverePassRate:    0.50,
		SevereThreshold:      0.80,
	}
}

// SimulationGate is the go/no-go gate before a strategy is promoted.
type SimulationGate struct {
	cfg SimulationGateConfig
}

// NewSimulationGate creates a SimulationGate with the given configuration.
func NewSimulationGate(cfg SimulationGateConfig) *SimulationGate {
	return &SimulationGate{cfg: cfg}
}

// Evaluate evaluates strategy resilience across all run results.
func (g *SimulationGate) Evaluate(strategyID string, runResults []RunResult) SimulationReport {
	if len(runResults) == 0 {
		return SimulationReport{
			StrategyID:       strategyID,
			OverallResilience: 0.0,
			WorstScenario:    "none",
			WorstResilience:  0.0,
			GatePassed:       false,
			GateReason:       "No scenario results to evaluate.",
		}
	}

	var sumResilience float64
	worst := runResults[0]
	for _, r := range runResults {
		sumResilience += r.ResilienceScore
		if r.ResilienceScore < worst.ResilienceScore {
			worst = r
		}
	}
	overall := sumResilience / float64(len(runResults))
	worstResilience := worst.ResilienceScore

	passedCount := 0
	for _, r := range runResults {
		if r.Passed {
			passedCount++
		}
	}
	passRate := float64(passedCount) / float64(len(runResults))

	var severeResults []RunResult
	for _, r := range runResults {
		if r.Severity >= g.cfg.SevereThreshold {
			severeResults = append(severeResults, r)
		}
	}
	severePassRate := 1.0
	if len(severeResults) > 0 {
		severePassCount := 0
		for _, r := range severeResults {
			if r.Passed {
				severePassCount++
			}
		}
		severePassRate = float64(severePassCount) / float64(len(severeResults))
	}

	var failureReasons []string
	if overall < g.cfg.MinOverallResilience {
		failureReasons = append(failureReasons, fmt.Sprintf("overall_resilience=%.3f < %.3f", overall, g.cfg.MinOverallResilience))
	}
	if worstResilience < g.cfg.MinWorstCase {
		failureReasons = append(failureReasons, fmt.Sprintf("worst_case=%.3f < %.3f (scenario='%s')", worstResilience, g.cfg.MinWorstCase, worst.ScenarioName))
	}
	if passRate < g.cfg.MinPassRate {
		failureReasons = append(failureReasons, fmt.Sprintf("pass_rate=%.2f%% < %.2f%%", passRate*100, g.cfg.MinPassRate*100))
	}
	if len(severeResults) > 0 && severePassRate < g.cfg.MinSeverePassRate {
		failureReasons = append(failureReasons, fmt.Sprintf("severe_pass_rate=%.2f%% < %.2f%%", severePassRate*100, g.cfg.MinSeverePassRate*100))
	}

	gatePassed := len(failureReasons) == 0
	gateReason := "All gate criteria passed."
	if !gatePassed {
		gateReason = "Gate failed: "
		for i, r := range failureReasons {
			if i > 0 {
				gateReason += "; "
			}
			gateReason += r
		}
	}

	if gatePassed {
		slog.Info("SimulationGate: passed",
			"strategy", strategyID,
			"overall", overall,
			"worst", worstResilience,
			"pass_rate", passRate,
			"severe_pass_rate", severePassRate,
		)
	} else {
		slog.Warn("SimulationGate: failed",
			"strategy", strategyID,
			"reason", gateReason,
		)
	}

	return SimulationReport{
		StrategyID:        strategyID,
		RunResults:        runResults,
		OverallResilience: overall,
		WorstScenario:     worst.ScenarioID,
		WorstResilience:   worstResilience,
		GatePassed:        gatePassed,
		GateReason:        gateReason,
	}
}

// RunAndEvaluate is a convenience method: create a runner, run it, then evaluate.
func (g *SimulationGate) RunAndEvaluate(
	ctx context.Context,
	strategyID string,
	strategy StrategyCallable,
	scenarios []Scenario,
	baseSignals map[string]float64,
	passThreshold float64,
	scorer ResilienceScorer,
) SimulationReport {
	runner := NewScenarioRunner(strategy, scorer, passThreshold, 0, false)
	results := runner.Run(ctx, scenarios, baseSignals)
	return g.Evaluate(strategyID, results)
}
