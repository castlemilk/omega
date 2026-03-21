// Package core implements the Three-Rings adversarial pressure architecture.
//
// Ring 1 — EnsembleDisagreementDetector (every cycle)
// Ring 2 — ScenarioGenerator (every N cycles)
// Ring 3 — EvolutionaryTournament (every N cycles)
//
// AdversarialPressure orchestrates all three rings and accumulates failure
// cases for consumption by the improvement loop.
package core

import (
	"context"
	"fmt"
	"log/slog"
	"math"
	"math/rand"
	"sort"
	"sync"

	"github.com/google/uuid"
)

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// DisagreementResult is the output of Ring 1 ensemble disagreement detection.
type DisagreementResult struct {
	Flagged              bool
	MaxDisagreement      float64
	DisagreeingVariants  []string
	Outputs              map[string]map[string]float64 // variant_id → signals
}

// Scenario is a single adversarial market stress scenario.
type Scenario struct {
	ScenarioID           string
	Name                 string
	Description          string
	MarketShocks         map[string]float64 // ticker → shock multiplier
	VolMultiplier        float64
	CorrelationBreakdown bool
	Severity             float64 // 0 → 1
}

// TournamentResult is the output of Ring 3 evolutionary tournament.
type TournamentResult struct {
	ChampionID     string
	ChampionParams map[string]any
	Eliminated     []string
	FitnessScores  map[string]float64
	Generation     int
}

// AdversarialReport is the consolidated output from one full adversarial pressure cycle.
type AdversarialReport struct {
	Cycle         int
	Ring1Result   *DisagreementResult
	Ring2Scenarios []Scenario
	Ring3Result   *TournamentResult
	FailureCases  []map[string]any // for feeding back into improvement loop
}

// FitnessFunc evaluates a set of strategy parameters and returns a fitness score.
type FitnessFunc func(params map[string]any) float64

// ---------------------------------------------------------------------------
// Ring 1: EnsembleDisagreementDetector
// ---------------------------------------------------------------------------

// EnsembleDisagreementDetector runs multiple strategy variants and detects
// when their outputs diverge beyond an acceptable threshold.
type EnsembleDisagreementDetector struct {
	DisagreementThreshold float64

	mu       sync.Mutex
	variants map[string]string            // variant_id → description
	outputs  map[string]map[string]float64 // variant_id → output
}

// NewEnsembleDisagreementDetector creates a new Ring 1 detector.
func NewEnsembleDisagreementDetector(threshold float64) *EnsembleDisagreementDetector {
	return &EnsembleDisagreementDetector{
		DisagreementThreshold: threshold,
		variants:              make(map[string]string),
		outputs:               make(map[string]map[string]float64),
	}
}

// RegisterVariant registers a variant slot; outputs are submitted later.
func (d *EnsembleDisagreementDetector) RegisterVariant(variantID, description string) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.variants[variantID] = description
	slog.Debug("Ring1: registered variant", "variant_id", variantID, "description", description)
}

// SubmitOutput submits a variant's output (numeric map of signal values).
func (d *EnsembleDisagreementDetector) SubmitOutput(variantID string, output map[string]float64) {
	d.mu.Lock()
	defer d.mu.Unlock()
	if _, ok := d.variants[variantID]; !ok {
		slog.Warn("Ring1: submit_output for unregistered variant; auto-registering", "variant_id", variantID)
		d.variants[variantID] = ""
	}
	d.outputs[variantID] = output
}

// normalisedDistance computes pairwise Euclidean distance between two signal
// dicts, normalised by the number of shared keys.
func normalisedDistance(a, b map[string]float64) float64 {
	var squaredSum float64
	var sharedCount int
	for k, av := range a {
		if bv, ok := b[k]; ok {
			diff := av - bv
			squaredSum += diff * diff
			sharedCount++
		}
	}
	if sharedCount == 0 {
		return 0.0
	}
	return math.Sqrt(squaredSum) / float64(max1(1, sharedCount))
}

func max1(a, b int) int {
	if a > b {
		return a
	}
	return b
}

// Detect computes pairwise normalised Euclidean distance between all variant
// outputs and flags if any pairwise distance exceeds the threshold.
func (d *EnsembleDisagreementDetector) Detect(_ context.Context) DisagreementResult {
	d.mu.Lock()
	defer d.mu.Unlock()

	variantIDs := make([]string, 0, len(d.outputs))
	for id := range d.outputs {
		variantIDs = append(variantIDs, id)
	}
	sort.Strings(variantIDs) // deterministic iteration order

	var maxDisagreement float64
	var disagreeingVariants []string
	seen := make(map[string]bool)

	for i := 0; i < len(variantIDs); i++ {
		for j := i + 1; j < len(variantIDs); j++ {
			vidA, vidB := variantIDs[i], variantIDs[j]
			dist := normalisedDistance(d.outputs[vidA], d.outputs[vidB])
			if dist > maxDisagreement {
				maxDisagreement = dist
			}
			if dist > d.DisagreementThreshold {
				if !seen[vidA] {
					disagreeingVariants = append(disagreeingVariants, vidA)
					seen[vidA] = true
				}
				if !seen[vidB] {
					disagreeingVariants = append(disagreeingVariants, vidB)
					seen[vidB] = true
				}
			}
		}
	}

	flagged := maxDisagreement > d.DisagreementThreshold
	if flagged {
		slog.Warn("Ring1: disagreement flagged",
			"max_distance", maxDisagreement,
			"threshold", d.DisagreementThreshold,
			"variants", disagreeingVariants,
		)
	} else {
		slog.Debug("Ring1: no disagreement", "max_distance", maxDisagreement)
	}

	// Copy outputs for result
	outputsCopy := make(map[string]map[string]float64, len(d.outputs))
	for vid, out := range d.outputs {
		cp := make(map[string]float64, len(out))
		for k, v := range out {
			cp[k] = v
		}
		outputsCopy[vid] = cp
	}

	return DisagreementResult{
		Flagged:             flagged,
		MaxDisagreement:     maxDisagreement,
		DisagreeingVariants: disagreeingVariants,
		Outputs:             outputsCopy,
	}
}

// Clear clears submitted outputs for next cycle.
func (d *EnsembleDisagreementDetector) Clear() {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.outputs = make(map[string]map[string]float64)
}

// ---------------------------------------------------------------------------
// Ring 2: ScenarioGenerator
// ---------------------------------------------------------------------------

var defaultTickers = []string{"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT"}

// ScenarioGenerator generates adversarial market stress scenarios for Ring 2.
type ScenarioGenerator struct {
	rng *rand.Rand
}

// NewScenarioGenerator creates a new ScenarioGenerator with optional seed.
func NewScenarioGenerator(seed int64, useSeed bool) *ScenarioGenerator {
	var rng *rand.Rand
	if useSeed {
		rng = rand.New(rand.NewSource(seed)) //nolint:gosec
	} else {
		rng = rand.New(rand.NewSource(rand.Int63())) //nolint:gosec
	}
	return &ScenarioGenerator{rng: rng}
}

func (g *ScenarioGenerator) baseStressScenarios() []Scenario {
	tickers := defaultTickers

	flashShocks := map[string]float64{"BTCUSDT": -0.30}
	for _, t := range tickers {
		if t != "BTCUSDT" {
			flashShocks[t] = -0.20
		}
	}

	bullShocks := map[string]float64{"BTCUSDT": 0.40}
	for _, t := range tickers {
		if t != "BTCUSDT" {
			bullShocks[t] = 0.60
		}
	}

	volShocks := make(map[string]float64)
	corrShocks := make(map[string]float64)
	liquidShocks := make(map[string]float64)
	bsShocks := make(map[string]float64)
	for _, t := range tickers {
		volShocks[t] = 0.0
		corrShocks[t] = 0.0
		liquidShocks[t] = -0.15
		bsShocks[t] = -0.50
	}

	return []Scenario{
		{
			ScenarioID:           "base_flash_crash",
			Name:                 "Flash Crash",
			Description:          "Rapid liquidity withdrawal: BTC drops 30%, alts drop 20%, volatility triples.",
			MarketShocks:         flashShocks,
			VolMultiplier:        3.0,
			CorrelationBreakdown: false,
			Severity:             0.85,
		},
		{
			ScenarioID:           "base_vol_spike",
			Name:                 "Volatility Spike",
			Description:          "Volatility explodes 5×; correlations break down across the board.",
			MarketShocks:         volShocks,
			VolMultiplier:        5.0,
			CorrelationBreakdown: true,
			Severity:             0.75,
		},
		{
			ScenarioID:           "base_corr_breakdown",
			Name:                 "Correlation Breakdown",
			Description:          "All pairwise correlations collapse toward zero; diversification assumptions fail.",
			MarketShocks:         corrShocks,
			VolMultiplier:        1.5,
			CorrelationBreakdown: true,
			Severity:             0.65,
		},
		{
			ScenarioID:           "base_liquidity_crisis",
			Name:                 "Liquidity Crisis",
			Description:          "Universal 15% price drop as market makers withdraw; spreads widen dramatically.",
			MarketShocks:         liquidShocks,
			VolMultiplier:        2.0,
			CorrelationBreakdown: false,
			Severity:             0.70,
		},
		{
			ScenarioID:           "base_bull_run",
			Name:                 "Bull Run",
			Description:          "BTC rallies 40%, alts rally 60% — tests whether strategy captures upside or lags.",
			MarketShocks:         bullShocks,
			VolMultiplier:        1.8,
			CorrelationBreakdown: false,
			Severity:             0.55,
		},
		{
			ScenarioID:           "base_black_swan",
			Name:                 "Black Swan",
			Description:          "Catastrophic 50% BTC drop with correlations jumping to 1.0; no refuge assets.",
			MarketShocks:         bsShocks,
			VolMultiplier:        8.0,
			CorrelationBreakdown: false,
			Severity:             0.99,
		},
	}
}

// GenerateAdversarial generates N adversarial scenarios calibrated to stress the current strategy.
func (g *ScenarioGenerator) GenerateAdversarial(_ context.Context, currentSignals map[string]float64, strategyParams map[string]any, nScenarios int) []Scenario {
	base := g.baseStressScenarios()
	var targeted []Scenario

	if len(currentSignals) > 0 {
		// Sort tickers by signal strength descending
		type tickerScore struct {
			ticker string
			score  float64
		}
		sorted := make([]tickerScore, 0, len(currentSignals))
		for t, s := range currentSignals {
			sorted = append(sorted, tickerScore{t, s})
		}
		sort.Slice(sorted, func(i, j int) bool { return sorted[i].score > sorted[j].score })

		// Target top-2 overweight assets
		nTop := 2
		if len(sorted) < nTop {
			nTop = len(sorted)
		}
		for i := 0; i < nTop; i++ {
			asset := sorted[i].ticker
			shockMag := -(0.25 + g.rng.Float64()*0.15 + 0.05)
			shocks := make(map[string]float64, len(currentSignals))
			for ticker := range currentSignals {
				if ticker == asset {
					shocks[ticker] = shockMag
				} else {
					shocks[ticker] = shockMag * 0.4
				}
			}
			targeted = append(targeted, Scenario{
				ScenarioID:           fmt.Sprintf("targeted_%s_%s", lowercaseReplace(asset), uuid.New().String()[:6]),
				Name:                 fmt.Sprintf("Targeted Crash: %s", asset),
				Description:          fmt.Sprintf("Adversarial scenario targeting current overweight position in %s with a %.0f%% shock.", asset, math.Abs(shockMag)*100),
				MarketShocks:         shocks,
				VolMultiplier:        2.5 + g.rng.Float64()*1.5,
				CorrelationBreakdown: g.rng.Float64() > 0.5,
				Severity:             math.Min(0.95, 0.60+math.Abs(shockMag)),
			})
		}

		// Signal inversion scenario
		invertedShocks := make(map[string]float64, len(currentSignals))
		for ticker, signal := range currentSignals {
			invertedShocks[ticker] = -signal * 0.3
		}
		targeted = append(targeted, Scenario{
			ScenarioID:           fmt.Sprintf("signal_inversion_%s", uuid.New().String()[:6]),
			Name:                 "Signal Inversion",
			Description:          "All current signals invert — tests robustness to regime change.",
			MarketShocks:         invertedShocks,
			VolMultiplier:        2.0,
			CorrelationBreakdown: false,
			Severity:             0.72,
		})
		_ = strategyParams // available for future calibration
	}

	all := make([]Scenario, len(base)+len(targeted))
	copy(all, base)
	copy(all[len(base):], targeted)
	sort.Slice(all, func(i, j int) bool { return all[i].Severity > all[j].Severity })
	if len(all) > nScenarios {
		all = all[:nScenarios]
	}
	return all
}

// StressTest applies scenario shocks to signals and returns stressed signals.
func (g *ScenarioGenerator) StressTest(signals map[string]float64, scenario Scenario) map[string]float64 {
	stressed := make(map[string]float64, len(signals))
	for ticker, signalVal := range signals {
		shock := scenario.MarketShocks[ticker] // zero if not present
		newVal := signalVal * (1.0 + shock)
		if scenario.CorrelationBreakdown {
			noise := g.rng.Float64()*0.30 - 0.15 // uniform [-0.15, 0.15]
			newVal += noise
		}
		newVal *= math.Min(1.0, 1.0/math.Max(1.0, scenario.VolMultiplier*0.2))
		stressed[ticker] = math.Max(-1.0, math.Min(1.0, newVal))
	}
	slog.Debug("Ring2: stress_test", "scenario", scenario.Name, "severity", scenario.Severity, "tickers", len(signals))
	return stressed
}

func lowercaseReplace(s string) string {
	result := make([]byte, len(s))
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c >= 'A' && c <= 'Z' {
			result[i] = c + 32
		} else {
			result[i] = c
		}
	}
	return string(result)
}

// ---------------------------------------------------------------------------
// Ring 3: EvolutionaryTournament
// ---------------------------------------------------------------------------

// EvolutionaryTournament maintains a population of strategy parameter variants
// and evolves them via tournament selection and mutation.
type EvolutionaryTournament struct {
	PopulationSize int
	MutationRate   float64

	mu             sync.Mutex
	population     map[string]map[string]any    // variant_id → params
	fitnessHistory map[string][]float64
	generation     int
	rng            *rand.Rand
}

// NewEvolutionaryTournament creates a new Ring 3 tournament.
func NewEvolutionaryTournament(populationSize int, mutationRate float64) *EvolutionaryTournament {
	return &EvolutionaryTournament{
		PopulationSize: populationSize,
		MutationRate:   mutationRate,
		population:     make(map[string]map[string]any),
		fitnessHistory: make(map[string][]float64),
		rng:            rand.New(rand.NewSource(rand.Int63())), //nolint:gosec
	}
}

func (t *EvolutionaryTournament) newVariantID() string {
	return fmt.Sprintf("v_%s", uuid.New().String()[:8])
}

func (t *EvolutionaryTournament) mutateParams(params map[string]any) map[string]any {
	mutated := make(map[string]any, len(params))
	for key, val := range params {
		switch v := val.(type) {
		case bool:
			if t.rng.Float64() < t.MutationRate*0.5 {
				mutated[key] = !v
			} else {
				mutated[key] = v
			}
		case int:
			factor := 1.0 - t.MutationRate + t.rng.Float64()*2*t.MutationRate
			rounded := int(math.Round(float64(v) * factor))
			if rounded < 1 {
				rounded = 1
			}
			mutated[key] = rounded
		case float64:
			factor := 1.0 - t.MutationRate + t.rng.Float64()*2*t.MutationRate
			mutated[key] = v * factor
		default:
			mutated[key] = val
		}
	}
	return mutated
}

// InitialisePopulation creates PopulationSize variants by randomly mutating base_params.
func (t *EvolutionaryTournament) InitialisePopulation(baseParams map[string]any) {
	t.mu.Lock()
	defer t.mu.Unlock()

	t.population = make(map[string]map[string]any)
	t.fitnessHistory = make(map[string][]float64)

	// First member is the base (un-mutated) variant
	baseID := t.newVariantID()
	cp := make(map[string]any, len(baseParams))
	for k, v := range baseParams {
		cp[k] = v
	}
	t.population[baseID] = cp

	for i := 1; i < t.PopulationSize; i++ {
		vid := t.newVariantID()
		t.population[vid] = t.mutateParams(baseParams)
	}

	slog.Info("Ring3: initialised population", "size", len(t.population))
}

// Evaluate calls fitnessFn for each variant and returns {variant_id: fitness_score}.
func (t *EvolutionaryTournament) Evaluate(fitnessFn FitnessFunc) map[string]float64 {
	t.mu.Lock()
	defer t.mu.Unlock()

	scores := make(map[string]float64, len(t.population))
	for vid, params := range t.population {
		score := func() (s float64) {
			defer func() {
				if r := recover(); r != nil {
					slog.Warn("Ring3: fitness_fn panicked", "variant", vid, "error", r)
					s = 0.0
				}
			}()
			return fitnessFn(params)
		}()
		scores[vid] = score
		t.fitnessHistory[vid] = append(t.fitnessHistory[vid], score)
	}

	best, worst := -math.MaxFloat64, math.MaxFloat64
	for _, s := range scores {
		if s > best {
			best = s
		}
		if s < worst {
			worst = s
		}
	}
	slog.Debug("Ring3: evaluated variants", "count", len(scores), "best", best, "worst", worst)
	return scores
}

// TournamentSelect performs k-tournament selection and returns the best variant ID.
func (t *EvolutionaryTournament) TournamentSelect(fitnessScores map[string]float64, k int) string {
	candidates := make([]string, 0, len(fitnessScores))
	for id := range fitnessScores {
		candidates = append(candidates, id)
	}
	if k > len(candidates) {
		k = len(candidates)
	}
	// Fisher-Yates shuffle for k samples
	t.rng.Shuffle(len(candidates), func(i, j int) { candidates[i], candidates[j] = candidates[j], candidates[i] })
	selected := candidates[:k]

	best := selected[0]
	for _, c := range selected[1:] {
		if fitnessScores[c] > fitnessScores[best] {
			best = c
		}
	}
	return best
}

// EliminateLosers keeps the top survivalRate fraction; eliminates the rest.
func (t *EvolutionaryTournament) EliminateLosers(fitnessScores map[string]float64, survivalRate float64) {
	if len(fitnessScores) == 0 {
		return
	}

	type kv struct {
		id    string
		score float64
	}
	sorted := make([]kv, 0, len(fitnessScores))
	for id, score := range fitnessScores {
		sorted = append(sorted, kv{id, score})
	}
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].score > sorted[j].score })

	nKeep := int(math.Round(float64(len(fitnessScores)) * survivalRate))
	if nKeep < 1 {
		nKeep = 1
	}

	survivors := make(map[string]bool, nKeep)
	for _, kv := range sorted[:nKeep] {
		survivors[kv.id] = true
	}

	var eliminated []string
	for id := range t.population {
		if !survivors[id] {
			eliminated = append(eliminated, id)
		}
	}
	for _, id := range eliminated {
		delete(t.population, id)
		delete(t.fitnessHistory, id)
	}
	slog.Debug("Ring3: eliminated variants", "count", len(eliminated), "survivors", len(t.population))
}

// SpawnVariants mutates the winner to create 2 new child variants.
func (t *EvolutionaryTournament) SpawnVariants(parentID string) []string {
	parent, ok := t.population[parentID]
	if !ok {
		slog.Warn("Ring3: spawn_variants parent not in population", "parent", parentID)
		return nil
	}

	var newIDs []string
	for i := 0; i < 2; i++ {
		childID := t.newVariantID()
		t.population[childID] = t.mutateParams(parent)
		newIDs = append(newIDs, childID)
	}
	slog.Debug("Ring3: spawned children", "count", len(newIDs), "parent", parentID)
	return newIDs
}

// RunTournament runs a full tournament cycle and returns a TournamentResult.
func (t *EvolutionaryTournament) RunTournament(_ context.Context, fitnessFn FitnessFunc) (TournamentResult, error) {
	t.mu.Lock()
	if len(t.population) == 0 {
		t.mu.Unlock()
		return TournamentResult{}, fmt.Errorf("population is empty — call InitialisePopulation() first")
	}
	t.generation++
	t.mu.Unlock()

	fitnessScores := t.Evaluate(fitnessFn)

	t.mu.Lock()
	defer t.mu.Unlock()

	k := 3
	if len(fitnessScores) < k {
		k = len(fitnessScores)
	}
	championID := t.TournamentSelect(fitnessScores, k)
	championParams := make(map[string]any, len(t.population[championID]))
	for k, v := range t.population[championID] {
		championParams[k] = v
	}

	// Record eliminated before removing them
	type kv struct {
		id    string
		score float64
	}
	sorted := make([]kv, 0, len(fitnessScores))
	for id, score := range fitnessScores {
		sorted = append(sorted, kv{id, score})
	}
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].score > sorted[j].score })
	nKeep := int(math.Round(float64(len(fitnessScores)) * 0.5))
	if nKeep < 1 {
		nKeep = 1
	}
	eliminatedIDs := make([]string, 0)
	for _, kv := range sorted[nKeep:] {
		eliminatedIDs = append(eliminatedIDs, kv.id)
	}

	t.EliminateLosers(fitnessScores, 0.5)
	t.SpawnVariants(championID)

	slog.Info("Ring3: tournament complete",
		"generation", t.generation,
		"champion", championID,
		"fitness", fitnessScores[championID],
		"eliminated", len(eliminatedIDs),
	)

	return TournamentResult{
		ChampionID:     championID,
		ChampionParams: championParams,
		Eliminated:     eliminatedIDs,
		FitnessScores:  fitnessScores,
		Generation:     t.generation,
	}, nil
}

// GetChampionParams returns the params of the highest-fitness variant based on
// cumulative fitness history. Returns nil if no variants are registered.
func (t *EvolutionaryTournament) GetChampionParams() map[string]any {
	t.mu.Lock()
	defer t.mu.Unlock()

	if len(t.population) == 0 {
		return nil
	}

	var bestID string
	bestScore := -math.MaxFloat64
	for vid := range t.population {
		history := t.fitnessHistory[vid]
		var avg float64
		if len(history) > 0 {
			var sum float64
			for _, s := range history {
				sum += s
			}
			avg = sum / float64(len(history))
		}
		if avg > bestScore {
			bestScore = avg
			bestID = vid
		}
	}
	if bestID == "" {
		for id := range t.population {
			bestID = id
			break
		}
	}
	cp := make(map[string]any, len(t.population[bestID]))
	for k, v := range t.population[bestID] {
		cp[k] = v
	}
	return cp
}

// PopulationSize returns the current population count (for external inspection).
func (t *EvolutionaryTournament) CurrentPopulationSize() int {
	t.mu.Lock()
	defer t.mu.Unlock()
	return len(t.population)
}

// ---------------------------------------------------------------------------
// AdversarialPressure — orchestrator
// ---------------------------------------------------------------------------

const (
	Ring2Interval = 10 // cycles between scenario generation runs
	Ring3Interval = 50 // cycles between evolutionary tournament runs
)

// AdversarialPressure orchestrates the Three-Rings adversarial pressure architecture.
type AdversarialPressure struct {
	Ring1 *EnsembleDisagreementDetector
	Ring2 *ScenarioGenerator
	Ring3 *EvolutionaryTournament

	ActiveRings []int

	mu                sync.Mutex
	failureCases      []map[string]any
	ring1CyclesRun    int
	ring1FlaggedCount int
}

// NewAdversarialPressure creates a new AdversarialPressure orchestrator.
func NewAdversarialPressure(ring1Threshold float64, populationSize int, activeRings []int) *AdversarialPressure {
	if activeRings == nil {
		activeRings = []int{1}
	}
	rings := make([]int, len(activeRings))
	copy(rings, activeRings)

	return &AdversarialPressure{
		Ring1:       NewEnsembleDisagreementDetector(ring1Threshold),
		Ring2:       NewScenarioGenerator(0, false),
		Ring3:       NewEvolutionaryTournament(populationSize, 0.1),
		ActiveRings: rings,
	}
}

// Run executes all three rings as appropriate for the given cycle.
func (ap *AdversarialPressure) Run(
	ctx context.Context,
	cycle int,
	variantOutputs map[string]map[string]float64,
	currentSignals map[string]float64,
	strategyParams map[string]any,
	fitnessFn FitnessFunc,
) AdversarialReport {
	ring1Result := ap.runRing1(ctx, cycle, variantOutputs)

	var ring2Scenarios []Scenario
	if ap.containsRing(2) && cycle%Ring2Interval == 0 {
		ring2Scenarios = ap.runRing2(ctx, cycle, currentSignals, strategyParams)
	}

	var ring3Result *TournamentResult
	if ap.containsRing(3) && cycle%Ring3Interval == 0 && fitnessFn != nil {
		r3, err := ap.runRing3(ctx, cycle, fitnessFn)
		if err != nil {
			slog.Warn("Ring3: skipped", "cycle", cycle, "error", err)
		} else {
			ring3Result = r3
		}
	}

	cycleFailures := ap.collectCycleFailures(cycle, ring1Result, ring2Scenarios, currentSignals, ring3Result)
	ap.mu.Lock()
	ap.failureCases = append(ap.failureCases, cycleFailures...)
	ap.mu.Unlock()

	return AdversarialReport{
		Cycle:          cycle,
		Ring1Result:    ring1Result,
		Ring2Scenarios: ring2Scenarios,
		Ring3Result:    ring3Result,
		FailureCases:   cycleFailures,
	}
}

func (ap *AdversarialPressure) containsRing(n int) bool {
	for _, r := range ap.ActiveRings {
		if r == n {
			return true
		}
	}
	return false
}

func (ap *AdversarialPressure) runRing1(ctx context.Context, cycle int, variantOutputs map[string]map[string]float64) *DisagreementResult {
	ap.Ring1.Clear()
	for variantID, output := range variantOutputs {
		ap.Ring1.SubmitOutput(variantID, output)
	}
	result := ap.Ring1.Detect(ctx)

	ap.mu.Lock()
	ap.ring1CyclesRun++
	if result.Flagged {
		ap.ring1FlaggedCount++
	}
	ap.mu.Unlock()

	slog.Debug("Ring1", "cycle", cycle, "flagged", result.Flagged, "max_disagreement", result.MaxDisagreement)
	return &result
}

func (ap *AdversarialPressure) runRing2(ctx context.Context, cycle int, currentSignals map[string]float64, strategyParams map[string]any) []Scenario {
	slog.Info("Ring2: generating adversarial scenarios", "cycle", cycle)
	scenarios := ap.Ring2.GenerateAdversarial(ctx, currentSignals, strategyParams, 5)
	topSeverity := 0.0
	if len(scenarios) > 0 {
		topSeverity = scenarios[0].Severity
	}
	slog.Info("Ring2: generated scenarios", "cycle", cycle, "count", len(scenarios), "top_severity", topSeverity)
	return scenarios
}

func (ap *AdversarialPressure) runRing3(ctx context.Context, cycle int, fitnessFn FitnessFunc) (*TournamentResult, error) {
	if ap.Ring3.CurrentPopulationSize() == 0 {
		slog.Warn("Ring3: population not initialised, skipping", "cycle", cycle)
		return nil, fmt.Errorf("population not initialised")
	}
	slog.Info("Ring3: running tournament", "cycle", cycle, "population", ap.Ring3.CurrentPopulationSize())
	result, err := ap.Ring3.RunTournament(ctx, fitnessFn)
	if err != nil {
		return nil, err
	}
	slog.Info("Ring3: tournament complete", "cycle", cycle, "champion", result.ChampionID, "generation", result.Generation)
	return &result, nil
}

func (ap *AdversarialPressure) collectCycleFailures(
	cycle int,
	ring1Result *DisagreementResult,
	ring2Scenarios []Scenario,
	currentSignals map[string]float64,
	ring3Result *TournamentResult,
) []map[string]any {
	var failures []map[string]any

	// Ring 1 failure
	if ring1Result != nil && ring1Result.Flagged {
		failures = append(failures, map[string]any{
			"source": "ring1",
			"description": fmt.Sprintf(
				"Ensemble disagreement detected: max_distance=%.4f, disagreeing_variants=%v",
				ring1Result.MaxDisagreement, ring1Result.DisagreeingVariants,
			),
			"context": map[string]any{
				"max_disagreement":    ring1Result.MaxDisagreement,
				"disagreeing_variants": ring1Result.DisagreeingVariants,
			},
			"cycle": cycle,
		})
	}

	// Ring 2 failure cases — high severity scenarios that devastate signals
	for _, scenario := range ring2Scenarios {
		if scenario.Severity < 0.8 || len(currentSignals) == 0 {
			continue
		}
		stressed := ap.Ring2.StressTest(currentSignals, scenario)
		var sum float64
		for _, v := range stressed {
			sum += v
		}
		stressedMean := 0.0
		if len(stressed) > 0 {
			stressedMean = sum / float64(len(stressed))
		}
		if stressedMean < -0.3 {
			failures = append(failures, map[string]any{
				"source": "ring2",
				"description": fmt.Sprintf(
					"Scenario '%s' (severity=%.2f) devastates strategy signals (stressed_mean=%.4f)",
					scenario.Name, scenario.Severity, stressedMean,
				),
				"context": map[string]any{
					"scenario_id":      scenario.ScenarioID,
					"scenario_name":    scenario.Name,
					"severity":         scenario.Severity,
					"stressed_signals": stressed,
				},
				"cycle": cycle,
			})
		}
	}

	// Ring 3 failure cases — poor champion fitness
	if ring3Result != nil {
		bestFitness := ring3Result.FitnessScores[ring3Result.ChampionID]
		if bestFitness < 0.1 {
			failures = append(failures, map[string]any{
				"source": "ring3",
				"description": fmt.Sprintf(
					"Evolutionary tournament champion fitness too low: %.4f (generation=%d)",
					bestFitness, ring3Result.Generation,
				),
				"context": map[string]any{
					"champion_id":      ring3Result.ChampionID,
					"champion_fitness": bestFitness,
					"generation":       ring3Result.Generation,
				},
				"cycle": cycle,
			})
		}
	}

	if len(failures) > 0 {
		slog.Info("AdversarialPressure: collected failure cases", "cycle", cycle, "count", len(failures))
	}
	return failures
}

// ValidateRing1 checks whether Ring 1 has produced useful signals for at least minCycles.
func (ap *AdversarialPressure) ValidateRing1(minCycles int, minFlagRate float64) bool {
	ap.mu.Lock()
	cyclesRun := ap.ring1CyclesRun
	flaggedCount := ap.ring1FlaggedCount
	ap.mu.Unlock()

	if cyclesRun < minCycles {
		slog.Info("Ring1 validation: not enough cycles", "cycles_run", cyclesRun, "required", minCycles)
		return false
	}
	flagRate := float64(flaggedCount) / float64(cyclesRun)
	validated := flagRate >= minFlagRate
	slog.Info("Ring1 validation",
		"cycles", cyclesRun,
		"flagged", flaggedCount,
		"rate", flagRate,
		"min", minFlagRate,
		"validated", validated,
	)
	return validated
}

// CollectFailureCases returns all accumulated failure cases.
func (ap *AdversarialPressure) CollectFailureCases() []map[string]any {
	ap.mu.Lock()
	defer ap.mu.Unlock()
	result := make([]map[string]any, len(ap.failureCases))
	copy(result, ap.failureCases)
	return result
}

// ClearFailureCases clears the accumulated failure cases buffer.
func (ap *AdversarialPressure) ClearFailureCases() {
	ap.mu.Lock()
	defer ap.mu.Unlock()
	ap.failureCases = nil
	slog.Debug("AdversarialPressure: failure cases buffer cleared")
}

// Ring1CyclesRun returns the number of Ring 1 cycles run so far.
func (ap *AdversarialPressure) Ring1CyclesRun() int {
	ap.mu.Lock()
	defer ap.mu.Unlock()
	return ap.ring1CyclesRun
}
