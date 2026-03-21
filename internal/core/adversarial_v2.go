package core

// adversarial_v2.go — Enhanced adversarial layer that builds on Ring 1
// (ensemble disagreement) and activates Ring 2 (scenario bank) via four
// new components:
//
// AdaptiveThresholdManager — auto-tunes Ring 1 threshold based on FP rate.
// DisagreementAttributor   — identifies which variant(s) are outliers.
// FalsePositiveTracker     — tracks flag accuracy over time.
// AdversarialPressureV2    — extends AdversarialPressure with all of the above.

import (
	"context"
	"log/slog"
	"math"
	"sort"
	"sync"

	adversarialpkg "github.com/benebsworth/omega/internal/adversarial"
)

// ---------------------------------------------------------------------------
// AdaptiveThresholdManager
// ---------------------------------------------------------------------------

// ThresholdAdjustment records a single threshold adjustment event.
type ThresholdAdjustment struct {
	Cycle             int
	OldThreshold      float64
	NewThreshold      float64
	Reason            string
	FalsePositiveRate float64
}

// AdaptiveThresholdManager auto-tunes the Ring 1 disagreement threshold based
// on observed false positive rate over a rolling window.
type AdaptiveThresholdManager struct {
	CurrentThreshold float64

	minThreshold        float64
	maxThreshold        float64
	stepSize            float64
	fpRateHighWatermark float64
	fpRateLowWatermark  float64
	minFlagRate         float64
	adjustmentInterval  int
	windowSize          int

	mu                    sync.Mutex
	lastAdjustmentCycle   int
	adjustmentHistory     []ThresholdAdjustment
	fpWindow              []float64 // rolling window of FP observations (1.0 = FP, 0.0 = TP)
	flagWindow            []bool    // rolling window of flag observations
}

// AdaptiveThresholdConfig holds configuration for the threshold manager.
type AdaptiveThresholdConfig struct {
	InitialThreshold    float64
	MinThreshold        float64
	MaxThreshold        float64
	StepSize            float64
	FPRateHighWatermark float64
	FPRateLowWatermark  float64
	MinFlagRate         float64
	AdjustmentInterval  int
	WindowSize          int
}

// DefaultAdaptiveThresholdConfig returns sensible defaults.
func DefaultAdaptiveThresholdConfig(initialThreshold float64) AdaptiveThresholdConfig {
	return AdaptiveThresholdConfig{
		InitialThreshold:    initialThreshold,
		MinThreshold:        0.05,
		MaxThreshold:        0.60,
		StepSize:            0.02,
		FPRateHighWatermark: 0.30,
		FPRateLowWatermark:  0.05,
		MinFlagRate:         0.05,
		AdjustmentInterval:  10,
		WindowSize:          50,
	}
}

// NewAdaptiveThresholdManager creates a new threshold manager.
func NewAdaptiveThresholdManager(cfg AdaptiveThresholdConfig) *AdaptiveThresholdManager {
	return &AdaptiveThresholdManager{
		CurrentThreshold:    cfg.InitialThreshold,
		minThreshold:        cfg.MinThreshold,
		maxThreshold:        cfg.MaxThreshold,
		stepSize:            cfg.StepSize,
		fpRateHighWatermark: cfg.FPRateHighWatermark,
		fpRateLowWatermark:  cfg.FPRateLowWatermark,
		minFlagRate:         cfg.MinFlagRate,
		adjustmentInterval:  cfg.AdjustmentInterval,
		windowSize:          cfg.WindowSize,
		lastAdjustmentCycle: -cfg.AdjustmentInterval,
	}
}

// RecordObservation records one cycle's flag observation.
func (m *AdaptiveThresholdManager) RecordObservation(flagged bool, wasFalsePositive *bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.flagWindow = appendRolling(m.flagWindowAsBool(), flagged, m.windowSize)
	if wasFalsePositive != nil {
		v := 0.0
		if *wasFalsePositive {
			v = 1.0
		}
		m.fpWindow = appendRollingF(m.fpWindow, v, m.windowSize)
	}
}

func (m *AdaptiveThresholdManager) flagWindowAsBool() []bool { return m.flagWindow }

// Update evaluates current performance and adjusts threshold if needed.
// Returns a ThresholdAdjustment if an adjustment was made, nil otherwise.
func (m *AdaptiveThresholdManager) Update(cycle int, falsePositiveRate, flagRate float64) *ThresholdAdjustment {
	m.mu.Lock()
	defer m.mu.Unlock()

	if cycle-m.lastAdjustmentCycle < m.adjustmentInterval {
		return nil
	}

	old := m.CurrentThreshold
	newThreshold := old
	reason := ""

	switch {
	case falsePositiveRate > m.fpRateHighWatermark:
		newThreshold = math.Min(m.maxThreshold, old+m.stepSize)
		reason = "FP rate too high — raising threshold"
	case falsePositiveRate < m.fpRateLowWatermark && flagRate < m.minFlagRate:
		newThreshold = math.Max(m.minThreshold, old-m.stepSize)
		reason = "FP rate low and flag_rate low — lowering threshold"
	}

	if newThreshold == old {
		return nil
	}

	m.CurrentThreshold = newThreshold
	m.lastAdjustmentCycle = cycle
	adj := ThresholdAdjustment{
		Cycle:             cycle,
		OldThreshold:      old,
		NewThreshold:      newThreshold,
		Reason:            reason,
		FalsePositiveRate: falsePositiveRate,
	}
	m.adjustmentHistory = append(m.adjustmentHistory, adj)
	slog.Info("AdaptiveThreshold adjusted",
		"cycle", cycle,
		"old", old,
		"new", newThreshold,
		"reason", reason,
	)
	return &adj
}

// AdjustmentHistory returns all recorded adjustments.
func (m *AdaptiveThresholdManager) AdjustmentHistory() []ThresholdAdjustment {
	m.mu.Lock()
	defer m.mu.Unlock()
	cp := make([]ThresholdAdjustment, len(m.adjustmentHistory))
	copy(cp, m.adjustmentHistory)
	return cp
}

// RollingFlagRate returns the fraction of flagged cycles in the rolling window.
func (m *AdaptiveThresholdManager) RollingFlagRate() float64 {
	m.mu.Lock()
	defer m.mu.Unlock()
	if len(m.flagWindow) == 0 {
		return 0.0
	}
	var count float64
	for _, f := range m.flagWindow {
		if f {
			count++
		}
	}
	return count / float64(len(m.flagWindow))
}

func appendRolling(window []bool, v bool, maxSize int) []bool {
	window = append(window, v)
	if len(window) > maxSize {
		window = window[len(window)-maxSize:]
	}
	return window
}

func appendRollingF(window []float64, v float64, maxSize int) []float64 {
	window = append(window, v)
	if len(window) > maxSize {
		window = window[len(window)-maxSize:]
	}
	return window
}

// ---------------------------------------------------------------------------
// DisagreementAttributor
// ---------------------------------------------------------------------------

// AttributionResult describes which variant(s) are outliers.
type AttributionResult struct {
	OutlierVariants []string
	OutlierScores   map[string]float64 // variant_id → outlier score (higher = more outlier)
	Method          string
	Confidence      float64 // 0 → 1
}

// DisagreementAttributor identifies which variant(s) are outliers using
// z-score on mean pairwise distance.
type DisagreementAttributor struct {
	ZScoreThreshold float64
}

// NewDisagreementAttributor creates a new attributor.
func NewDisagreementAttributor(zScoreThreshold float64) *DisagreementAttributor {
	return &DisagreementAttributor{ZScoreThreshold: zScoreThreshold}
}

func euclideanDist(a, b map[string]float64) float64 {
	var sq float64
	var count int
	for k, av := range a {
		if bv, ok := b[k]; ok {
			d := av - bv
			sq += d * d
			count++
		}
	}
	if count == 0 {
		return 0.0
	}
	return math.Sqrt(sq) / float64(max1(1, count))
}

// Attribute attributes disagreement to specific variant(s) using z-scores on
// mean pairwise distance.
func (da *DisagreementAttributor) Attribute(result DisagreementResult) AttributionResult {
	outputs := result.Outputs
	variantIDs := make([]string, 0, len(outputs))
	for id := range outputs {
		variantIDs = append(variantIDs, id)
	}
	sort.Strings(variantIDs)

	if len(variantIDs) < 2 {
		return AttributionResult{
			Method:     "z_score_pairwise",
			Confidence: 0.0,
		}
	}

	meanDistances := make(map[string]float64, len(variantIDs))
	for _, vid := range variantIDs {
		var sumDist float64
		var count int
		for _, other := range variantIDs {
			if other != vid {
				sumDist += euclideanDist(outputs[vid], outputs[other])
				count++
			}
		}
		if count > 0 {
			meanDistances[vid] = sumDist / float64(count)
		}
	}

	if len(meanDistances) < 2 {
		// Fall back: return the highest distance variant
		var bestID string
		var bestDist float64
		for id, d := range meanDistances {
			if d > bestDist {
				bestDist = d
				bestID = id
			}
		}
		return AttributionResult{
			OutlierVariants: []string{bestID},
			OutlierScores:   meanDistances,
			Method:          "z_score_pairwise",
			Confidence:      0.5,
		}
	}

	// Compute mean and stdev of distances
	distValues := make([]float64, 0, len(meanDistances))
	for _, d := range meanDistances {
		distValues = append(distValues, d)
	}
	meanD := mean(distValues)
	stdevD := stdev(distValues)

	zScores := make(map[string]float64, len(meanDistances))
	for vid, d := range meanDistances {
		if stdevD > 0 {
			zScores[vid] = (d - meanD) / stdevD
		}
	}

	var outliers []string
	for vid, z := range zScores {
		if z > da.ZScoreThreshold {
			outliers = append(outliers, vid)
		}
	}

	maxZ := -math.MaxFloat64
	for _, z := range zScores {
		if z > maxZ {
			maxZ = z
		}
	}
	confidence := 0.0
	if maxZ > 0 {
		confidence = clamp01F(maxZ / (da.ZScoreThreshold * 2))
	}

	if len(outliers) == 0 && result.Flagged {
		// Fallback: return highest-z variant
		var bestID string
		bestZ := -math.MaxFloat64
		for vid, z := range zScores {
			if z > bestZ {
				bestZ = z
				bestID = vid
			}
		}
		outliers = []string{bestID}
	}

	slog.Debug("DisagreementAttributor",
		"outliers", outliers,
		"confidence", confidence,
	)

	return AttributionResult{
		OutlierVariants: outliers,
		OutlierScores:   meanDistances,
		Method:          "z_score_pairwise",
		Confidence:      confidence,
	}
}

func mean(vals []float64) float64 {
	if len(vals) == 0 {
		return 0.0
	}
	var sum float64
	for _, v := range vals {
		sum += v
	}
	return sum / float64(len(vals))
}

func stdev(vals []float64) float64 {
	if len(vals) < 2 {
		return 0.0
	}
	m := mean(vals)
	var sumSq float64
	for _, v := range vals {
		d := v - m
		sumSq += d * d
	}
	return math.Sqrt(sumSq / float64(len(vals)-1))
}

func clamp01F(v float64) float64 {
	return math.Max(0.0, math.Min(1.0, v))
}

// ---------------------------------------------------------------------------
// FalsePositiveTracker
// ---------------------------------------------------------------------------

// FPObservation is a single flag + outcome pair for FP tracking.
type FPObservation struct {
	Cycle           int
	Flagged         bool
	OutcomeKnown    bool
	WasFalsePositive *bool // set retrospectively
}

// FalsePositiveTracker tracks whether Ring 1 flags were genuine or false positives.
type FalsePositiveTracker struct {
	Window int

	mu           sync.Mutex
	observations map[int]*FPObservation
	resolved     []bool // rolling window: true = FP, false = TP
}

// NewFalsePositiveTracker creates a new tracker.
func NewFalsePositiveTracker(window int) *FalsePositiveTracker {
	return &FalsePositiveTracker{
		Window:       window,
		observations: make(map[int]*FPObservation),
	}
}

// RecordFlag records that a flag (or non-flag) occurred at this cycle.
func (t *FalsePositiveTracker) RecordFlag(cycle int, flagged bool) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.observations[cycle] = &FPObservation{
		Cycle:   cycle,
		Flagged: flagged,
	}
}

// RecordOutcome records the retrospective outcome for a previously flagged cycle.
func (t *FalsePositiveTracker) RecordOutcome(cycle int, wasFalsePositive bool) {
	t.mu.Lock()
	defer t.mu.Unlock()

	obs, ok := t.observations[cycle]
	if !ok {
		slog.Warn("FalsePositiveTracker: no observation for cycle", "cycle", cycle)
		return
	}
	if !obs.Flagged {
		slog.Debug("FalsePositiveTracker: cycle was not flagged; outcome irrelevant", "cycle", cycle)
		return
	}
	obs.OutcomeKnown = true
	obs.WasFalsePositive = &wasFalsePositive
	t.resolved = appendRolling(t.resolved, wasFalsePositive, t.Window)

	slog.Debug("FalsePositiveTracker",
		"cycle", cycle,
		"was_false_positive", wasFalsePositive,
		"fp_rate", t.falsePositiveRateLocked(),
	)
}

func (t *FalsePositiveTracker) falsePositiveRateLocked() float64 {
	if len(t.resolved) == 0 {
		return 0.0
	}
	var count float64
	for _, fp := range t.resolved {
		if fp {
			count++
		}
	}
	return count / float64(len(t.resolved))
}

// FalsePositiveRate returns the rolling FP rate over the last window resolved flags.
func (t *FalsePositiveTracker) FalsePositiveRate() float64 {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.falsePositiveRateLocked()
}

// FlagRate returns the fraction of cycles where flagged=True in the last recentN observations.
// Pass recentN=0 to use all observations.
func (t *FalsePositiveTracker) FlagRate(recentN int) float64 {
	t.mu.Lock()
	defer t.mu.Unlock()

	// Collect all observations as ordered slice
	obsList := make([]*FPObservation, 0, len(t.observations))
	for _, obs := range t.observations {
		obsList = append(obsList, obs)
	}
	sort.Slice(obsList, func(i, j int) bool { return obsList[i].Cycle < obsList[j].Cycle })

	if recentN > 0 && len(obsList) > recentN {
		obsList = obsList[len(obsList)-recentN:]
	}
	if len(obsList) == 0 {
		return 0.0
	}
	var flagged float64
	for _, obs := range obsList {
		if obs.Flagged {
			flagged++
		}
	}
	return flagged / float64(len(obsList))
}

// PendingOutcomes returns cycle IDs of flags without a recorded outcome.
func (t *FalsePositiveTracker) PendingOutcomes() []int {
	t.mu.Lock()
	defer t.mu.Unlock()
	var pending []int
	for cycle, obs := range t.observations {
		if obs.Flagged && !obs.OutcomeKnown {
			pending = append(pending, cycle)
		}
	}
	sort.Ints(pending)
	return pending
}

// Summary returns a summary map of tracker state.
func (t *FalsePositiveTracker) Summary() map[string]any {
	t.mu.Lock()
	defer t.mu.Unlock()

	total := len(t.observations)
	var flagged int
	for _, obs := range t.observations {
		if obs.Flagged {
			flagged++
		}
	}
	var pending int
	for _, obs := range t.observations {
		if obs.Flagged && !obs.OutcomeKnown {
			pending++
		}
	}
	return map[string]any{
		"total_cycles_observed": total,
		"total_flagged":         flagged,
		"resolved_flags":        len(t.resolved),
		"false_positive_rate":   t.falsePositiveRateLocked(),
		"pending_outcomes":      pending,
	}
}

// ---------------------------------------------------------------------------
// Ring2ActivationController
// ---------------------------------------------------------------------------

// Ring2ActivationStatus tracks Ring 2 simulation gate results.
type Ring2ActivationStatus struct {
	Activated              bool
	LastGateCycle          int
	LastGatePassed         *bool
	ConsecutiveGatePasses  int
	ConsecutiveGateFails   int
	TotalEvaluations       int
}

// Ring2ActivationController decides whether Ring 2 simulation gate should gate
// further execution.
type Ring2ActivationController struct {
	MinRing1Cycles   int
	MinRing1FlagRate float64
	Gate             *SimulationGate

	mu     sync.Mutex
	status Ring2ActivationStatus
}

// NewRing2ActivationController creates a new controller.
func NewRing2ActivationController(minCycles int, minFlagRate float64, gate *SimulationGate) *Ring2ActivationController {
	if gate == nil {
		gate = NewSimulationGate(DefaultSimulationGateConfig())
	}
	return &Ring2ActivationController{
		MinRing1Cycles:   minCycles,
		MinRing1FlagRate: minFlagRate,
		Gate:             gate,
		status: Ring2ActivationStatus{
			LastGateCycle: -1,
		},
	}
}

// ShouldActivate returns true when Ring 2 activation criteria are met.
func (c *Ring2ActivationController) ShouldActivate(ring1CyclesRun int, ring1FlagRate float64) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	activated := ring1CyclesRun >= c.MinRing1Cycles && ring1FlagRate >= c.MinRing1FlagRate
	c.status.Activated = activated
	return activated
}

// RecordGateResult records the outcome of a gate evaluation.
func (c *Ring2ActivationController) RecordGateResult(cycle int, passed bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.status.LastGateCycle = cycle
	c.status.LastGatePassed = &passed
	c.status.TotalEvaluations++
	if passed {
		c.status.ConsecutiveGatePasses++
		c.status.ConsecutiveGateFails = 0
	} else {
		c.status.ConsecutiveGateFails++
		c.status.ConsecutiveGatePasses = 0
	}
}

// Status returns the current activation status.
func (c *Ring2ActivationController) Status() Ring2ActivationStatus {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.status
}

// ---------------------------------------------------------------------------
// AdversarialReportV2
// ---------------------------------------------------------------------------

// AdversarialReportV2 is the enhanced report including attribution, threshold
// adjustments, Ring 2 gate, and optional DebateGate outputs.
type AdversarialReportV2 struct {
	BaseReport          AdversarialReport
	Attribution         *AttributionResult
	ThresholdAdjustment *ThresholdAdjustment
	FPSummary           map[string]any
	Ring2SimReport      *SimulationReport
	Ring2Activated      bool
	CurrentThreshold    float64

	// DebateGate outputs (set when Ring 1 flags disagreement and DebateGate is configured)
	DebateVerdict       *adversarialpkg.DebateVerdict
	RiskDebateResult    *adversarialpkg.RiskDebateResult
	DebateAction        string  // "proceed" | "reduce" | "veto"
	DebatePositionScale float64
}

// ---------------------------------------------------------------------------
// AdversarialPressureV2
// ---------------------------------------------------------------------------

const ring2SimInterval = 20 // cycles between Ring 2 simulation gate runs

// AdversarialPressureV2Config holds all configuration for AdversarialPressureV2.
type AdversarialPressureV2Config struct {
	Ring1Threshold    float64
	PopulationSize    int
	ActiveRings       []int
	ThresholdCfg      AdaptiveThresholdConfig
	OutlierZThreshold float64
	// Ring 2 activation
	MinRing1CyclesForRing2   int
	MinRing1FlagRateForRing2 float64
	// DebateGate — nil means no debate (non-trading domains)
	DebateGate *adversarialpkg.DebateGate
}

// DefaultAdversarialPressureV2Config returns sensible defaults.
func DefaultAdversarialPressureV2Config() AdversarialPressureV2Config {
	return AdversarialPressureV2Config{
		Ring1Threshold:          0.20,
		PopulationSize:          10,
		ActiveRings:             []int{1},
		ThresholdCfg:            DefaultAdaptiveThresholdConfig(0.20),
		OutlierZThreshold:       1.5,
		MinRing1CyclesForRing2:  20,
		MinRing1FlagRateForRing2: 0.05,
	}
}

// AdversarialPressureV2 is the enhanced adversarial pressure orchestrator.
type AdversarialPressureV2 struct {
	base          *AdversarialPressure
	thresholdMgr  *AdaptiveThresholdManager
	attributor    *DisagreementAttributor
	fpTracker     *FalsePositiveTracker
	scenarioBank  *HistoricalScenarioBank
	synthGen      *SyntheticScenarioGenerator
	ring2Ctrl     *Ring2ActivationController

	debateGate  *adversarialpkg.DebateGate
	riskDebate  *adversarialpkg.RiskDebate
}

// NewAdversarialPressureV2 creates a new enhanced adversarial pressure orchestrator.
func NewAdversarialPressureV2(cfg AdversarialPressureV2Config) *AdversarialPressureV2 {
	base := NewAdversarialPressure(cfg.Ring1Threshold, cfg.PopulationSize, cfg.ActiveRings)
	simGate := NewSimulationGate(DefaultSimulationGateConfig())

	var riskDebate *adversarialpkg.RiskDebate
	if cfg.DebateGate != nil {
		riskDebate = adversarialpkg.NewRiskDebate(nil, nil, nil)
	}

	return &AdversarialPressureV2{
		base:         base,
		thresholdMgr: NewAdaptiveThresholdManager(cfg.ThresholdCfg),
		attributor:   NewDisagreementAttributor(cfg.OutlierZThreshold),
		fpTracker:    NewFalsePositiveTracker(100),
		scenarioBank: NewHistoricalScenarioBank(),
		synthGen:     NewSyntheticScenarioGenerator(0, false),
		ring2Ctrl:    NewRing2ActivationController(cfg.MinRing1CyclesForRing2, cfg.MinRing1FlagRateForRing2, simGate),
		debateGate:   cfg.DebateGate,
		riskDebate:   riskDebate,
	}
}

// Ring1, Ring2, Ring3 expose inner ring objects for external access.
func (ap *AdversarialPressureV2) Ring1() *EnsembleDisagreementDetector { return ap.base.Ring1 }
func (ap *AdversarialPressureV2) Ring2() *ScenarioGenerator            { return ap.base.Ring2 }
func (ap *AdversarialPressureV2) Ring3() *EvolutionaryTournament       { return ap.base.Ring3 }
func (ap *AdversarialPressureV2) Ring2Status() Ring2ActivationStatus   { return ap.ring2Ctrl.Status() }

// RunV2 executes a full enhanced adversarial cycle.
//
//  1. Sync Ring 1 threshold from adaptive manager.
//  2. Run base AdversarialPressure cycle (all active rings).
//  3. If Ring 1 flagged: attribute outliers, update FP tracker.
//  4. Adjust threshold based on FP rate.
//  5. If Ring 2 activation criteria met and on interval: run simulation gate.
func (ap *AdversarialPressureV2) RunV2(
	ctx context.Context,
	cycle int,
	variantOutputs map[string]map[string]float64,
	currentSignals map[string]float64,
	strategyParams map[string]any,
	fitnessFn FitnessFunc,
	strategyCallable StrategyCallable,
) AdversarialReportV2 {
	// Sync Ring 1 threshold
	ap.base.Ring1.DisagreementThreshold = ap.thresholdMgr.CurrentThreshold

	// Base run
	baseReport := ap.base.Run(ctx, cycle, variantOutputs, currentSignals, strategyParams, fitnessFn)

	// Attribution on flag
	var attribution *AttributionResult
	if baseReport.Ring1Result != nil && baseReport.Ring1Result.Flagged {
		result := ap.attributor.Attribute(*baseReport.Ring1Result)
		attribution = &result
		slog.Info("AdversarialV2: Ring1 flagged",
			"cycle", cycle,
			"outliers", attribution.OutlierVariants,
			"confidence", attribution.Confidence,
		)
	}

	// Record flag in FP tracker
	flagged := baseReport.Ring1Result != nil && baseReport.Ring1Result.Flagged
	ap.fpTracker.RecordFlag(cycle, flagged)

	// Adaptive threshold update
	fpRate := ap.fpTracker.FalsePositiveRate()
	flagRate := ap.fpTracker.FlagRate(50)
	threshAdj := ap.thresholdMgr.Update(cycle, fpRate, flagRate)

	// DebateGate — called when Ring 1 flags and DebateGate is configured
	var debateVerdict *adversarialpkg.DebateVerdict
	var riskDebateResult *adversarialpkg.RiskDebateResult
	var debateAction string
	var debatePositionScale float64

	if flagged && ap.debateGate != nil {
		sigCtx := buildSignalContext(currentSignals, strategyParams)
		verdict := ap.debateGate.Evaluate(sigCtx)
		debateVerdict = &verdict
		action, scale := adversarialpkg.ActionFromVerdict(verdict)
		debateAction = string(action)
		debatePositionScale = scale

		if ap.riskDebate != nil {
			riskCtx := adversarialpkg.RiskContext{
				CompositeSignal:  sigCtx.CompositeSignal,
				ICShort:          sigCtx.ICShort,
				VolRegime:        sigCtx.VolRegime,
				RecentSharpe:     sigCtx.RecentSharpe,
				NodeErrorRate:    sigCtx.NodeErrorRate,
				ATLDistance:      sigCtx.ATLDistance,
				DebateConfidence: verdict.Confidence,
			}
			result := ap.riskDebate.Resolve(riskCtx)
			riskDebateResult = &result

			slog.Info("AdversarialV2 DebateGate",
				"cycle", cycle,
				"action", debateAction,
				"position_scale", debatePositionScale,
				"confidence", verdict.Confidence,
				"risk_scale", result.PositionScale,
			)
		}
	}

	// Ring 2 simulation gate
	var ring2SimReport *SimulationReport
	ring2Activated := ap.ring2Ctrl.ShouldActivate(ap.base.Ring1CyclesRun(), flagRate)

	if ring2Activated && strategyCallable != nil && cycle%ring2SimInterval == 0 {
		report := ap.runRing2Gate(ctx, cycle, strategyCallable, currentSignals)
		if report != nil {
			ring2SimReport = report
			ap.ring2Ctrl.RecordGateResult(cycle, report.GatePassed)
		}
	}

	return AdversarialReportV2{
		BaseReport:          baseReport,
		Attribution:         attribution,
		ThresholdAdjustment: threshAdj,
		FPSummary:           ap.fpTracker.Summary(),
		Ring2SimReport:      ring2SimReport,
		Ring2Activated:      ring2Activated,
		CurrentThreshold:    ap.thresholdMgr.CurrentThreshold,
		DebateVerdict:       debateVerdict,
		RiskDebateResult:    riskDebateResult,
		DebateAction:        debateAction,
		DebatePositionScale: debatePositionScale,
	}
}

// RegisterOutcome registers retrospective outcome for a previously flagged cycle.
func (ap *AdversarialPressureV2) RegisterOutcome(cycle int, wasFalsePositive bool) {
	ap.fpTracker.RecordOutcome(cycle, wasFalsePositive)
}

// CollectFailureCases delegates to the base failure case buffer.
func (ap *AdversarialPressureV2) CollectFailureCases() []map[string]any {
	return ap.base.CollectFailureCases()
}

// ClearFailureCases delegates to the base.
func (ap *AdversarialPressureV2) ClearFailureCases() {
	ap.base.ClearFailureCases()
}

// ValidateRing1 delegates to the base.
func (ap *AdversarialPressureV2) ValidateRing1(minCycles int, minFlagRate float64) bool {
	return ap.base.ValidateRing1(minCycles, minFlagRate)
}

func (ap *AdversarialPressureV2) runRing2Gate(ctx context.Context, cycle int, strategyCallable StrategyCallable, currentSignals map[string]float64) *SimulationReport {
	defer func() {
		if r := recover(); r != nil {
			slog.Warn("AdversarialV2 Ring2Gate: panic", "cycle", cycle, "error", r)
		}
	}()

	// Top 5 historical scenarios by severity + 5 synthetic
	allHistorical := ap.scenarioBank.AllScenarios()
	sort.Slice(allHistorical, func(i, j int) bool { return allHistorical[i].Severity > allHistorical[j].Severity })
	if len(allHistorical) > 5 {
		allHistorical = allHistorical[:5]
	}

	synthetic := ap.synthGen.Generate(currentSignals, 5, nil)
	all := make([]Scenario, len(allHistorical)+len(synthetic))
	copy(all, allHistorical)
	copy(all[len(allHistorical):], synthetic)

	report := ap.ring2Ctrl.Gate.RunAndEvaluate(
		ctx,
		"ring2_gate_cycle_"+itoa(cycle),
		strategyCallable,
		all,
		currentSignals,
		0.30,
		nil,
	)

	slog.Info("AdversarialV2 Ring2Gate",
		"cycle", cycle,
		"passed", report.GatePassed,
		"overall_resilience", report.OverallResilience,
	)
	return &report
}

// buildSignalContext constructs a SignalContext from current signals and strategy params.
func buildSignalContext(currentSignals map[string]float64, strategyParams map[string]any) adversarialpkg.SignalContext {
	ctx := adversarialpkg.DefaultSignalContext()

	if composite, ok := strategyParams["composite_signal"]; ok {
		if f, ok := composite.(float64); ok {
			ctx.CompositeSignal = f
		}
	} else if len(currentSignals) > 0 {
		var sum float64
		for _, v := range currentSignals {
			sum += v
		}
		ctx.CompositeSignal = sum / float64(len(currentSignals))
	}

	if v, ok := strategyParams["ic_short"]; ok {
		if f, ok := v.(float64); ok {
			ctx.ICShort = f
		}
	}
	if v, ok := strategyParams["ic_long"]; ok {
		if f, ok := v.(float64); ok {
			ctx.ICLong = f
		}
	}
	if v, ok := strategyParams["vol_regime"]; ok {
		if s, ok := v.(string); ok {
			ctx.VolRegime = s
		}
	}
	if v, ok := strategyParams["regime_ic"]; ok {
		if m, ok := v.(map[string]float64); ok {
			ctx.RegimeIC = m
		}
	}
	if v, ok := strategyParams["recent_sharpe"]; ok {
		if f, ok := v.(float64); ok {
			ctx.RecentSharpe = f
		}
	}
	if v, ok := strategyParams["node_error_rate"]; ok {
		if f, ok := v.(float64); ok {
			ctx.NodeErrorRate = f
		}
	}
	if v, ok := strategyParams["atl_distance"]; ok {
		if f, ok := v.(float64); ok {
			ctx.ATLDistance = f
		}
	}
	if v, ok := strategyParams["rsi"]; ok {
		if f, ok := v.(float64); ok {
			ctx.RSI = f
		}
	}
	return ctx
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := false
	if n < 0 {
		neg = true
		n = -n
	}
	var buf [20]byte
	pos := len(buf)
	for n > 0 {
		pos--
		buf[pos] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		pos--
		buf[pos] = '-'
	}
	return string(buf[pos:])
}
