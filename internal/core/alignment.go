// alignment.go — 3-layer alignment system for the Omega autonomous AI framework.
//
// Layer 1 — SafetyEnvelope:
//   Hard constraints enforced unconditionally. Covers max per-asset position
//   concentration, portfolio drawdown, pairwise correlation, and improvement
//   magnitude. These constraints can never be "optimised away" by higher layers.
//
// Layer 2 — ParetoEvaluator (NSGA-II):
//   Non-dominated sorting with crowding-distance tiebreaking ranks nodes across
//   multiple conflicting objectives without collapsing to a scalar.
//
// Layer 3 — OutcomeBasedScorer:
//   Scores nodes by actual prediction accuracy and risk-adjusted returns,
//   tracking a rolling history of predicted vs actual outcomes per node.
//   score = clamp(0.6 * accuracy + 0.4 * sharpe_contribution, 0, 1)
package core

import (
	"fmt"
	"log/slog"
	"math"
	"sync"
)

// ---------------------------------------------------------------------------
// Layer 1: SafetyEnvelope
// ---------------------------------------------------------------------------

// SafetyEnvelope enforces hard portfolio constraints unconditionally.
type SafetyEnvelope struct {
	MaxPositionPct          float64
	MaxDrawdownPct          float64
	MaxCorrelation          float64
	MaxImprovementMagnitude float64
}

// NewSafetyEnvelope creates a SafetyEnvelope with sensible defaults.
func NewSafetyEnvelope(maxPositionPct, maxDrawdownPct, maxCorrelation, maxImprovementMagnitude float64) *SafetyEnvelope {
	return &SafetyEnvelope{
		MaxPositionPct:          maxPositionPct,
		MaxDrawdownPct:          maxDrawdownPct,
		MaxCorrelation:          maxCorrelation,
		MaxImprovementMagnitude: maxImprovementMagnitude,
	}
}

// Check validates a portfolio against all hard constraints.
//
// portfolio: asset → weight mapping. Weights need not sum to 1.
// drawdown: current portfolio drawdown as a fraction (0–1).
// correlationMatrix: asset_i → {asset_j → correlation}.
//
// Returns (ok, violations) where ok=true iff no constraints are breached.
func (se *SafetyEnvelope) Check(portfolio map[string]float64, drawdown float64, correlationMatrix map[string]map[string]float64) (bool, []string) {
	var violations []string

	totalWeight := 0.0
	for _, w := range portfolio {
		totalWeight += math.Abs(w)
	}
	if totalWeight == 0 {
		totalWeight = 1.0
	}

	// 1. Position concentration.
	for asset, weight := range portfolio {
		pct := math.Abs(weight) / totalWeight
		if pct > se.MaxPositionPct {
			violations = append(violations, fmt.Sprintf("position_concentration: %s = %.4f > %.4f", asset, pct, se.MaxPositionPct))
		}
	}

	// 2. Drawdown.
	if drawdown > se.MaxDrawdownPct {
		violations = append(violations, fmt.Sprintf("drawdown: %.4f > %.4f", drawdown, se.MaxDrawdownPct))
	}

	// 3. Correlation.
	if len(correlationMatrix) > 0 {
		assets := make([]string, 0, len(portfolio))
		for a := range portfolio {
			assets = append(assets, a)
		}
		seen := make(map[[2]string]bool)
		for _, assetI := range assets {
			row, ok := correlationMatrix[assetI]
			if !ok {
				continue
			}
			for assetJ, corr := range row {
				if assetJ == assetI {
					continue
				}
				pair := sortedPair(assetI, assetJ)
				if seen[pair] {
					continue
				}
				seen[pair] = true
				if math.Abs(corr) > se.MaxCorrelation {
					violations = append(violations, fmt.Sprintf("correlation: (%s, %s) = %.4f > %.4f", assetI, assetJ, corr, se.MaxCorrelation))
				}
			}
		}
	}

	if len(violations) > 0 {
		slog.Warn("SafetyEnvelope violations", "count", len(violations), "violations", violations)
	}
	return len(violations) == 0, violations
}

// CheckImprovementMagnitude gates an improvement step on absolute magnitude.
// Returns (ok, reason) where ok=false if |delta| > MaxImprovementMagnitude.
func (se *SafetyEnvelope) CheckImprovementMagnitude(improvementDelta float64) (bool, string) {
	if math.Abs(improvementDelta) > se.MaxImprovementMagnitude {
		reason := fmt.Sprintf("improvement_magnitude: |%.6f| > %.6f", improvementDelta, se.MaxImprovementMagnitude)
		slog.Warn("SafetyEnvelope magnitude gate triggered", "reason", reason)
		return false, reason
	}
	return true, ""
}

// Clamp returns a copy of the portfolio with position concentrations clamped.
// Iteratively clips violators and redistributes surplus among free positions.
func (se *SafetyEnvelope) Clamp(portfolio map[string]float64) map[string]float64 {
	if len(portfolio) == 0 {
		return map[string]float64{}
	}
	totalWeight := 0.0
	for _, w := range portfolio {
		totalWeight += math.Abs(w)
	}
	if totalWeight == 0 {
		totalWeight = 1.0
	}

	// Normalise to fraction space.
	fractions := make(map[string]float64, len(portfolio))
	for a, w := range portfolio {
		fractions[a] = w / totalWeight
	}

	maxIter := len(fractions) + 1
	for iter := 0; iter < maxIter; iter++ {
		clipped := make(map[string]float64)
		free := make(map[string]float64)
		surplus := 0.0
		for asset, frac := range fractions {
			sign := 1.0
			if frac < 0 {
				sign = -1.0
			}
			if math.Abs(frac) > se.MaxPositionPct {
				clipped[asset] = sign * se.MaxPositionPct
				surplus += math.Abs(frac) - se.MaxPositionPct
			} else {
				free[asset] = frac
			}
		}
		if surplus < 1e-10 {
			for a, v := range free {
				clipped[a] = v
			}
			fractions = clipped
			break
		}
		if len(free) == 0 {
			fractions = clipped
			break
		}
		freeTotal := 0.0
		for _, v := range free {
			freeTotal += math.Abs(v)
		}
		if freeTotal == 0 {
			freeTotal = 1.0
		}
		redistributed := make(map[string]float64, len(free))
		for a, v := range free {
			redistributed[a] = v + (v/freeTotal)*surplus
		}
		fractions = make(map[string]float64, len(clipped)+len(redistributed))
		for a, v := range clipped {
			fractions[a] = v
		}
		for a, v := range redistributed {
			fractions[a] = v
		}
	}

	result := make(map[string]float64, len(fractions))
	for a, f := range fractions {
		result[a] = f * totalWeight
	}
	return result
}

func sortedPair(a, b string) [2]string {
	if a <= b {
		return [2]string{a, b}
	}
	return [2]string{b, a}
}

// ---------------------------------------------------------------------------
// Layer 2: ParetoEvaluator (NSGA-II)
// ---------------------------------------------------------------------------

// ParetoEvaluator implements NSGA-II multi-objective ranking.
type ParetoEvaluator struct{}

const defaultDirection = "maximize"

func (pe *ParetoEvaluator) compare(a, b float64, direction string) int {
	if direction == "minimize" {
		a, b = -a, -b
	}
	if a > b {
		return 1
	}
	if a < b {
		return -1
	}
	return 0
}

// Dominates returns true if solution a Pareto-dominates solution b.
// a dominates b iff a is no worse in ALL objectives and strictly better in at least one.
func (pe *ParetoEvaluator) Dominates(a, b map[string]float64, objectives []string, directions map[string]string) bool {
	atLeastOneBetter := false
	for _, obj := range objectives {
		dir := directions[obj]
		if dir == "" {
			dir = defaultDirection
		}
		cmp := pe.compare(a[obj], b[obj], dir)
		if cmp < 0 {
			return false
		}
		if cmp > 0 {
			atLeastOneBetter = true
		}
	}
	return atLeastOneBetter
}

// AssignRanks performs non-dominated sorting and returns Pareto front rank per individual.
// Rank 0 = Pareto-optimal. Rank 1 = optimal after removing front 0, etc.
func (pe *ParetoEvaluator) AssignRanks(population []map[string]float64, objectives []string, directions map[string]string) []int {
	n := len(population)
	if n == 0 {
		return nil
	}

	dominationCount := make([]int, n)
	dominatedBy := make([][]int, n)
	for i := range dominatedBy {
		dominatedBy[i] = make([]int, 0)
	}

	for i := 0; i < n; i++ {
		for j := 0; j < n; j++ {
			if i == j {
				continue
			}
			if pe.Dominates(population[i], population[j], objectives, directions) {
				dominatedBy[i] = append(dominatedBy[i], j)
			} else if pe.Dominates(population[j], population[i], objectives, directions) {
				dominationCount[i]++
			}
		}
	}

	ranks := make([]int, n)
	for i := range ranks {
		ranks[i] = -1
	}
	var currentFront []int
	for i := 0; i < n; i++ {
		if dominationCount[i] == 0 {
			currentFront = append(currentFront, i)
		}
	}
	rank := 0
	for len(currentFront) > 0 {
		for _, i := range currentFront {
			ranks[i] = rank
		}
		var nextFront []int
		for _, i := range currentFront {
			for _, j := range dominatedBy[i] {
				dominationCount[j]--
				if dominationCount[j] == 0 {
					nextFront = append(nextFront, j)
				}
			}
		}
		currentFront = nextFront
		rank++
	}
	return ranks
}

// CrowdingDistance computes NSGA-II crowding distance for a single Pareto front.
// Higher distance = more isolated = preferred for diversity.
func (pe *ParetoEvaluator) CrowdingDistance(front []map[string]float64, objectives []string) []float64 {
	n := len(front)
	if n == 0 {
		return nil
	}
	if n == 1 {
		return []float64{math.Inf(1)}
	}
	distances := make([]float64, n)
	for _, obj := range objectives {
		sortedIdx := make([]int, n)
		for i := range sortedIdx {
			sortedIdx[i] = i
		}
		// sort by objective value
		for i := 0; i < n-1; i++ {
			for j := i + 1; j < n; j++ {
				if front[sortedIdx[i]][obj] > front[sortedIdx[j]][obj] {
					sortedIdx[i], sortedIdx[j] = sortedIdx[j], sortedIdx[i]
				}
			}
		}
		objValues := make([]float64, n)
		for k, idx := range sortedIdx {
			objValues[k] = front[idx][obj]
		}
		objRange := objValues[n-1] - objValues[0]
		distances[sortedIdx[0]] = math.Inf(1)
		distances[sortedIdx[n-1]] = math.Inf(1)
		if objRange == 0 {
			continue
		}
		for k := 1; k < n-1; k++ {
			distances[sortedIdx[k]] += (objValues[k+1] - objValues[k-1]) / objRange
		}
	}
	return distances
}

// NSGA2Sort sorts population indices by NSGA-II rank then crowding distance.
// Returns indices sorted best→worst.
func (pe *ParetoEvaluator) NSGA2Sort(population []map[string]float64, objectives []string, directions map[string]string) []int {
	if len(population) == 0 {
		return nil
	}
	if directions == nil {
		directions = make(map[string]string, len(objectives))
		for _, obj := range objectives {
			directions[obj] = "maximize"
		}
	}
	ranks := pe.AssignRanks(population, objectives, directions)

	// Group indices by rank.
	rankGroups := make(map[int][]int)
	for idx, r := range ranks {
		rankGroups[r] = append(rankGroups[r], idx)
	}

	// Collect sorted rank keys.
	var rankKeys []int
	for r := range rankGroups {
		rankKeys = append(rankKeys, r)
	}
	for i := 0; i < len(rankKeys)-1; i++ {
		for j := i + 1; j < len(rankKeys); j++ {
			if rankKeys[i] > rankKeys[j] {
				rankKeys[i], rankKeys[j] = rankKeys[j], rankKeys[i]
			}
		}
	}

	var sortedIndices []int
	for _, r := range rankKeys {
		group := rankGroups[r]
		frontItems := make([]map[string]float64, len(group))
		for i, idx := range group {
			frontItems[i] = population[idx]
		}
		cd := pe.CrowdingDistance(frontItems, objectives)
		// Sort by crowding distance descending.
		groupSorted := make([]int, len(group))
		for i := range groupSorted {
			groupSorted[i] = i
		}
		for i := 0; i < len(groupSorted)-1; i++ {
			for j := i + 1; j < len(groupSorted); j++ {
				if cd[groupSorted[i]] < cd[groupSorted[j]] {
					groupSorted[i], groupSorted[j] = groupSorted[j], groupSorted[i]
				}
			}
		}
		for _, k := range groupSorted {
			sortedIndices = append(sortedIndices, group[k])
		}
	}
	return sortedIndices
}

// ---------------------------------------------------------------------------
// Layer 3: OutcomeBasedScorer
// ---------------------------------------------------------------------------

const maxOutcomeHistory = 50

type outcomeRecord struct {
	predicted          float64
	actual             float64
	returnContribution float64
}

// OutcomeBasedScorer scores nodes by prediction accuracy and risk-adjusted returns.
type OutcomeBasedScorer struct {
	mu      sync.RWMutex
	history map[string][]outcomeRecord // node_id → records
}

// NewOutcomeBasedScorer creates an empty scorer.
func NewOutcomeBasedScorer() *OutcomeBasedScorer {
	return &OutcomeBasedScorer{history: make(map[string][]outcomeRecord)}
}

// RecordOutcome records one prediction outcome for a node.
func (s *OutcomeBasedScorer) RecordOutcome(nodeID string, predicted, actual, returnContribution float64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	h := s.history[nodeID]
	h = append(h, outcomeRecord{predicted: predicted, actual: actual, returnContribution: returnContribution})
	if len(h) > maxOutcomeHistory {
		h = h[len(h)-maxOutcomeHistory:]
	}
	s.history[nodeID] = h
}

func (s *OutcomeBasedScorer) accuracy(nodeID string) float64 {
	h := s.history[nodeID]
	if len(h) == 0 {
		return 0.0
	}
	sum := 0.0
	for _, rec := range h {
		sum += math.Abs(rec.predicted-rec.actual) / math.Max(math.Abs(rec.actual), 1e-6)
	}
	return 1.0 - sum/float64(len(h))
}

func (s *OutcomeBasedScorer) sharpeContribution(nodeID string) float64 {
	h := s.history[nodeID]
	if len(h) == 0 {
		return 0.0
	}
	returns := make([]float64, len(h))
	meanR := 0.0
	for i, rec := range h {
		returns[i] = rec.returnContribution
		meanR += rec.returnContribution
	}
	meanR /= float64(len(returns))
	stdR := 0.0
	if len(returns) >= 2 {
		variance := 0.0
		for _, r := range returns {
			diff := r - meanR
			variance += diff * diff
		}
		variance /= float64(len(returns))
		stdR = math.Sqrt(variance)
	}
	return meanR / (stdR + 1e-8)
}

// Score returns the composite score for a node, clamped to [0, 1].
// score = 0.6 * accuracy + 0.4 * sharpe_contribution
func (s *OutcomeBasedScorer) Score(nodeID string) float64 {
	s.mu.RLock()
	defer s.mu.RUnlock()
	acc := s.accuracy(nodeID)
	sharpe := s.sharpeContribution(nodeID)
	raw := 0.6*acc + 0.4*sharpe
	return math.Max(0.0, math.Min(1.0, raw))
}

// GetScores returns scores for all tracked nodes.
func (s *OutcomeBasedScorer) GetScores() map[string]float64 {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make(map[string]float64, len(s.history))
	for nodeID := range s.history {
		out[nodeID] = s.accuracy(nodeID)*0.6 + s.sharpeContribution(nodeID)*0.4
		if out[nodeID] < 0 {
			out[nodeID] = 0
		}
		if out[nodeID] > 1 {
			out[nodeID] = 1
		}
	}
	return out
}

// ---------------------------------------------------------------------------
// AlignmentDecision
// ---------------------------------------------------------------------------

// AlignmentDecision is the result of one alignment evaluation cycle.
type AlignmentDecision struct {
	Approved                bool
	Violations              []string
	ParetoRanks             map[string]int
	OutcomeScores           map[string]float64
	ImprovementMagnitudeOK  bool
	MagnitudeWarning        bool
	Cycle                   int
}

// ---------------------------------------------------------------------------
// AlignmentLayer
// ---------------------------------------------------------------------------

// AlignmentLayer orchestrates all 3 alignment layers for the Omega improvement loop.
type AlignmentLayer struct {
	mu                sync.Mutex
	safetyEnvelope    *SafetyEnvelope
	paretoEvaluator   *ParetoEvaluator
	scorer            *OutcomeBasedScorer
	magnitudeWarnings map[string]bool
}

// NewAlignmentLayer creates an AlignmentLayer with optional safety config.
// safetyConfig keys: max_position_pct, max_drawdown_pct, max_correlation,
// max_improvement_magnitude.
func NewAlignmentLayer(safetyConfig map[string]float64) *AlignmentLayer {
	cfg := safetyConfig
	if cfg == nil {
		cfg = map[string]float64{}
	}
	getOr := func(key string, def float64) float64 {
		if v, ok := cfg[key]; ok {
			return v
		}
		return def
	}
	se := NewSafetyEnvelope(
		getOr("max_position_pct", 0.25),
		getOr("max_drawdown_pct", 0.15),
		getOr("max_correlation", 0.85),
		getOr("max_improvement_magnitude", 0.5),
	)
	slog.Info("AlignmentLayer initialised", "safety_config", cfg)
	return &AlignmentLayer{
		safetyEnvelope:    se,
		paretoEvaluator:   &ParetoEvaluator{},
		scorer:            NewOutcomeBasedScorer(),
		magnitudeWarnings: make(map[string]bool),
	}
}

// CheckImprovementCycle runs all 3 alignment layers for one improvement cycle.
//
// Execution order:
//  1. SafetyEnvelope — hard gate; approved=false if violated.
//  2. ParetoEvaluator — rank nodes across nodeMetricsMap objectives.
//  3. OutcomeBasedScorer — return current node performance scores.
func (al *AlignmentLayer) CheckImprovementCycle(
	nodeMetricsMap map[string]map[string]float64,
	systemMetrics map[string]float64,
	portfolio map[string]float64,
	cycle int,
) AlignmentDecision {
	// Layer 1: SafetyEnvelope.
	drawdown := systemMetrics["drawdown"]
	safeOK, violations := al.safetyEnvelope.Check(portfolio, drawdown, nil)
	slog.Info("cycle SafetyEnvelope", "cycle", cycle, "ok", safeOK, "violations", len(violations))

	// Layer 2: ParetoEvaluator.
	nodeIDs := make([]string, 0, len(nodeMetricsMap))
	for id := range nodeMetricsMap {
		nodeIDs = append(nodeIDs, id)
	}
	population := make([]map[string]float64, len(nodeIDs))
	for i, nid := range nodeIDs {
		population[i] = nodeMetricsMap[nid]
	}

	var objectives []string
	if len(population) > 0 {
		for k := range population[0] {
			if k != "node_id" {
				objectives = append(objectives, k)
			}
		}
	}
	directions := make(map[string]string, len(objectives))
	for _, obj := range objectives {
		if endsWithAny(obj, "_latency", "_error") || obj == "drawdown" {
			directions[obj] = "minimize"
		} else {
			directions[obj] = "maximize"
		}
	}

	paretoRanks := make(map[string]int, len(nodeIDs))
	if len(population) > 0 && len(objectives) > 0 {
		ranksList := al.paretoEvaluator.AssignRanks(population, objectives, directions)
		for i, nid := range nodeIDs {
			paretoRanks[nid] = ranksList[i]
		}
	} else {
		for _, nid := range nodeIDs {
			paretoRanks[nid] = 0
		}
	}
	slog.Debug("cycle pareto_ranks", "cycle", cycle, "ranks", paretoRanks)

	// Layer 3: OutcomeBasedScorer.
	outcomeScores := al.scorer.GetScores()
	slog.Debug("cycle outcome_scores", "cycle", cycle, "scores", outcomeScores)

	al.mu.Lock()
	magnitudeWarning := false
	for _, warned := range al.magnitudeWarnings {
		if warned {
			magnitudeWarning = true
			break
		}
	}
	al.mu.Unlock()

	return AlignmentDecision{
		Approved:               safeOK,
		Violations:             violations,
		ParetoRanks:            paretoRanks,
		OutcomeScores:          outcomeScores,
		ImprovementMagnitudeOK: !magnitudeWarning,
		MagnitudeWarning:       magnitudeWarning,
		Cycle:                  cycle,
	}
}

// RecordImprovementAttempt gates a node parameter update via improvement magnitude check.
// Computes delta as the change in mean absolute parameter value.
func (al *AlignmentLayer) RecordImprovementAttempt(nodeID string, oldParams, newParams map[string]float64) (bool, string) {
	oldMean := 0.0
	for _, v := range oldParams {
		oldMean += math.Abs(v)
	}
	if len(oldParams) > 0 {
		oldMean /= float64(len(oldParams))
	}
	newMean := 0.0
	for _, v := range newParams {
		newMean += math.Abs(v)
	}
	if len(newParams) > 0 {
		newMean /= float64(len(newParams))
	}
	delta := newMean - oldMean

	ok, reason := al.safetyEnvelope.CheckImprovementMagnitude(delta)
	al.mu.Lock()
	al.magnitudeWarnings[nodeID] = !ok
	al.mu.Unlock()

	slog.Debug("RecordImprovementAttempt", "node", nodeID, "ok", ok, "delta", delta, "reason", reason)
	return ok, reason
}

// RecordOutcome records a prediction outcome for a node.
func (al *AlignmentLayer) RecordOutcome(nodeID string, predicted, actual, returnContribution float64) {
	al.scorer.RecordOutcome(nodeID, predicted, actual, returnContribution)
	slog.Debug("RecordOutcome", "node", nodeID, "predicted", predicted, "actual", actual, "return_contribution", returnContribution)
}

func endsWithAny(s string, suffixes ...string) bool {
	for _, suffix := range suffixes {
		if len(s) >= len(suffix) && s[len(s)-len(suffix):] == suffix {
			return true
		}
	}
	return false
}
