// Package core implements the Omega safety and goals enforcement layer.
//
// goals.go — 3-layer goal architecture:
//   1. ConstitutionalConstraints — hard/soft safety rules (blocking gate)
//   2. BalancedScorecard        — multi-dimensional goal tracking
//   3. HTNDecomposer            — Hierarchical Task Network decomposition
//
// AdaptiveReferenceTracker replaces MPCReferenceTracker. It maintains a rolling
// EMA target that adapts each cycle, avoiding the tension between MPC's
// fixed-trajectory assumption and self-improving systems.
//
// NashWelfareAggregator and MPCReferenceTracker are retained for advanced/
// experimental use but are NOT wired into GoalArchitecture by default.
package core

import (
	"context"
	"fmt"
	"log/slog"
	"math"
	"sync"

	"github.com/google/uuid"
)

// ---------------------------------------------------------------------------
// Data contracts
// ---------------------------------------------------------------------------

// ConstraintViolation describes a single constitutional constraint violation.
type ConstraintViolation struct {
	ConstraintName string
	MetricName     string
	CurrentValue   float64
	Limit          float64
	Severity       string // "hard" | "soft"
}

// Task is a unit of work produced by HTN decomposition.
type Task struct {
	TaskID       string
	Name         string
	Parameters   map[string]any
	AssignedTo   string
	Priority     float64
	Preconditions map[string]any
}

// GoalDecision is the result of one GoalArchitecture cycle.
type GoalDecision struct {
	Approved             bool
	ConstraintViolations []ConstraintViolation
	Scorecard            map[string]float64
	CompositeScore       float64
	Subtasks             []Task
	TrackingError        float64
	ControlAction        map[string]float64
	Cycle                int
}

// ---------------------------------------------------------------------------
// Layer 1: ConstitutionalConstraints
// ---------------------------------------------------------------------------

type constraint struct {
	name      string
	metricKey string
	limit     float64
	direction string // "max" | "min"
	severity  string // "hard" | "soft"
}

// ConstitutionalConstraints enforces hard safety rules that override everything else.
type ConstitutionalConstraints struct {
	mu          sync.RWMutex
	constraints []constraint
}

// Register adds a constraint.
// direction "max" means metric must be <= limit; "min" means >= limit.
// severity "hard" blocks; "soft" warns only.
func (cc *ConstitutionalConstraints) Register(name, metricKey string, limit float64, direction, severity string) {
	cc.mu.Lock()
	defer cc.mu.Unlock()
	cc.constraints = append(cc.constraints, constraint{
		name:      name,
		metricKey: metricKey,
		limit:     limit,
		direction: direction,
		severity:  severity,
	})
	op := "<="
	if direction == "min" {
		op = ">="
	}
	slog.Debug("registered constraint", "name", name, "metric", metricKey, "op", op, "limit", limit, "severity", severity)
}

// Check evaluates all constraints against current metrics.
// Returns (passed, violations) where passed=false if any hard constraint is violated.
func (cc *ConstitutionalConstraints) Check(_ context.Context, metrics map[string]float64) (bool, []ConstraintViolation) {
	cc.mu.RLock()
	defer cc.mu.RUnlock()

	var violations []ConstraintViolation
	for _, c := range cc.constraints {
		value, ok := metrics[c.metricKey]
		if !ok {
			continue
		}
		violated := (c.direction == "max" && value > c.limit) ||
			(c.direction == "min" && value < c.limit)
		if !violated {
			continue
		}
		v := ConstraintViolation{
			ConstraintName: c.name,
			MetricName:     c.metricKey,
			CurrentValue:   value,
			Limit:          c.limit,
			Severity:       c.severity,
		}
		violations = append(violations, v)
		slog.Warn("constraint violated",
			"constraint", c.name,
			"metric", c.metricKey,
			"value", value,
			"limit", c.limit,
			"severity", c.severity,
		)
	}
	hardViolated := false
	for _, v := range violations {
		if v.Severity == "hard" {
			hardViolated = true
			break
		}
	}
	return !hardViolated, violations
}

// RegisterDefaults registers sensible defaults for the Victoria pipeline.
func (cc *ConstitutionalConstraints) RegisterDefaults() {
	cc.Register("max_drawdown_limit", "max_drawdown_pct", 15.0, "max", "hard")
	cc.Register("max_position_limit", "max_position_pct", 25.0, "max", "hard")
	cc.Register("min_sharpe_ratio", "sharpe_ratio", -2.0, "min", "soft")
	cc.Register("max_error_rate", "error_rate", 0.5, "max", "soft")
}

// ---------------------------------------------------------------------------
// Layer 2: BalancedScorecard
// ---------------------------------------------------------------------------

var scorecardDimensions = []string{"returns", "risk", "diversification", "information_ratio"}

func sigmoid(x float64) float64 {
	if x > 500 {
		return 1.0
	}
	if x < -500 {
		return 0.0
	}
	return 1.0 / (1.0 + math.Exp(-x))
}

// BalancedScorecard tracks multi-dimensional goals across four dimensions.
type BalancedScorecard struct {
	mu      sync.RWMutex
	weights map[string]float64
	scores  map[string]float64
	history []map[string]float64
}

// NewBalancedScorecard creates a scorecard with optional dimension weights.
// If dimensionWeights is nil, equal weights are used.
func NewBalancedScorecard(dimensionWeights map[string]float64) *BalancedScorecard {
	bs := &BalancedScorecard{
		weights: make(map[string]float64, len(scorecardDimensions)),
		scores:  make(map[string]float64, len(scorecardDimensions)),
	}
	if dimensionWeights == nil {
		equal := 1.0 / float64(len(scorecardDimensions))
		for _, d := range scorecardDimensions {
			bs.weights[d] = equal
		}
	} else {
		for _, d := range scorecardDimensions {
			bs.weights[d] = dimensionWeights[d]
		}
		bs.normaliseWeights()
	}
	for _, d := range scorecardDimensions {
		bs.scores[d] = 0.0
	}
	return bs
}

func (bs *BalancedScorecard) normaliseWeights() {
	total := 0.0
	for _, w := range bs.weights {
		total += w
	}
	if total > 0 {
		for k := range bs.weights {
			bs.weights[k] /= total
		}
	}
}

func (bs *BalancedScorecard) mapReturns(metrics map[string]float64) float64 {
	var parts []float64
	if v, ok := metrics["sharpe_ratio"]; ok {
		parts = append(parts, sigmoid(v))
	}
	if v, ok := metrics["pnl"]; ok {
		parts = append(parts, sigmoid(v))
	}
	if len(parts) == 0 {
		return 0.5
	}
	sum := 0.0
	for _, p := range parts {
		sum += p
	}
	return sum / float64(len(parts))
}

func (bs *BalancedScorecard) mapRisk(metrics map[string]float64) float64 {
	var parts []float64
	if v, ok := metrics["max_drawdown_pct"]; ok {
		parts = append(parts, math.Max(0.0, 1.0-v/100.0))
	}
	if v, ok := metrics["error_rate"]; ok {
		parts = append(parts, math.Max(0.0, 1.0-v))
	}
	if len(parts) == 0 {
		return 0.5
	}
	sum := 0.0
	for _, p := range parts {
		sum += p
	}
	return sum / float64(len(parts))
}

func (bs *BalancedScorecard) mapDiversification(metrics map[string]float64) float64 {
	if v, ok := metrics["max_correlation"]; ok {
		return math.Max(0.0, 1.0-math.Abs(v))
	}
	if v, ok := metrics["coverage_rate"]; ok {
		return math.Max(0.0, math.Min(1.0, v))
	}
	return 0.5
}

func (bs *BalancedScorecard) mapInformationRatio(metrics map[string]float64) float64 {
	if v, ok := metrics["information_ratio"]; ok {
		return sigmoid(v)
	}
	if v, ok := metrics["accuracy"]; ok {
		return math.Max(0.0, math.Min(1.0, v))
	}
	return 0.5
}

// Update maps incoming metrics to scorecard dimensions and records history.
func (bs *BalancedScorecard) Update(metrics map[string]float64) {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	bs.scores["returns"] = bs.mapReturns(metrics)
	bs.scores["risk"] = bs.mapRisk(metrics)
	bs.scores["diversification"] = bs.mapDiversification(metrics)
	bs.scores["information_ratio"] = bs.mapInformationRatio(metrics)
	snapshot := make(map[string]float64, len(bs.scores))
	for k, v := range bs.scores {
		snapshot[k] = v
	}
	bs.history = append(bs.history, snapshot)
	slog.Debug("scorecard updated", "scores", bs.scores)
}

// Score returns current dimension scores.
func (bs *BalancedScorecard) Score() map[string]float64 {
	bs.mu.RLock()
	defer bs.mu.RUnlock()
	out := make(map[string]float64, len(bs.scores))
	for k, v := range bs.scores {
		out[k] = v
	}
	return out
}

// CompositeScore returns the weighted average of dimension scores.
func (bs *BalancedScorecard) CompositeScore() float64 {
	bs.mu.RLock()
	defer bs.mu.RUnlock()
	total := 0.0
	for _, d := range scorecardDimensions {
		total += bs.scores[d] * bs.weights[d]
	}
	return total
}

// Trend returns {dimension: delta} over the last window updates.
func (bs *BalancedScorecard) Trend(window int) map[string]float64 {
	bs.mu.RLock()
	defer bs.mu.RUnlock()
	out := make(map[string]float64, len(scorecardDimensions))
	for _, d := range scorecardDimensions {
		out[d] = 0.0
	}
	if len(bs.history) < 2 {
		return out
	}
	recent := bs.history
	if len(recent) > window {
		recent = recent[len(recent)-window:]
	}
	if len(recent) < 2 {
		return out
	}
	first := recent[0]
	last := recent[len(recent)-1]
	for _, d := range scorecardDimensions {
		out[d] = last[d] - first[d]
	}
	return out
}

// ---------------------------------------------------------------------------
// AdaptiveReferenceTracker
// ---------------------------------------------------------------------------

// AdaptiveReferenceTracker is a rolling EMA reference tracker with
// uncertainty-aware horizon. Unlike MPC it does not assume fixed reference
// dynamics — the reference adapts each cycle via EMA.
type AdaptiveReferenceTracker struct {
	mu                sync.Mutex
	objectives        []string
	alpha             float64
	uncertaintyFactor float64

	ema             map[string]float64
	mean            map[string]float64
	m2              map[string]float64
	n               map[string]int
	last            map[string]float64
	manualReference map[string]float64
}

// NewAdaptiveReferenceTracker creates a tracker for the given objectives.
func NewAdaptiveReferenceTracker(objectives []string, emaAlpha, uncertaintyFactor float64) *AdaptiveReferenceTracker {
	return &AdaptiveReferenceTracker{
		objectives:        append([]string(nil), objectives...),
		alpha:             emaAlpha,
		uncertaintyFactor: uncertaintyFactor,
		ema:               make(map[string]float64),
		mean:              make(map[string]float64),
		m2:                make(map[string]float64),
		n:                 make(map[string]int),
		last:              make(map[string]float64),
		manualReference:   make(map[string]float64),
	}
}

// SetReference overrides the reference with the first value of each trajectory.
func (t *AdaptiveReferenceTracker) SetReference(trajectory map[string][]float64) {
	t.mu.Lock()
	defer t.mu.Unlock()
	for obj, vals := range trajectory {
		if len(vals) > 0 {
			t.manualReference[obj] = vals[0]
		}
	}
	slog.Debug("AdaptiveReferenceTracker: manual reference set", "reference", t.manualReference)
}

// Update updates EMA reference and running variance with new observations.
func (t *AdaptiveReferenceTracker) Update(current map[string]float64) {
	t.mu.Lock()
	defer t.mu.Unlock()
	for _, obj := range t.objectives {
		val, ok := current[obj]
		if !ok {
			continue
		}
		t.last[obj] = val

		// EMA update.
		if _, exists := t.ema[obj]; !exists {
			t.ema[obj] = val
		} else {
			t.ema[obj] = t.alpha*val + (1.0-t.alpha)*t.ema[obj]
		}

		// Welford online variance.
		n := t.n[obj] + 1
		t.n[obj] = n
		prevMean := t.mean[obj]
		if n == 1 {
			prevMean = val
		}
		delta := val - prevMean
		t.mean[obj] = prevMean + delta/float64(n)
		delta2 := val - t.mean[obj]
		t.m2[obj] += delta * delta2
	}
}

func (t *AdaptiveReferenceTracker) variance(obj string) float64 {
	n := t.n[obj]
	if n < 2 {
		return 0.0
	}
	return t.m2[obj] / float64(n)
}

// TrackingError returns MSE between current observations and adaptive reference,
// uncertainty-scaled.
func (t *AdaptiveReferenceTracker) TrackingError() float64 {
	t.mu.Lock()
	defer t.mu.Unlock()
	if len(t.last) == 0 {
		return 0.0
	}
	total := 0.0
	count := 0
	for _, obj := range t.objectives {
		lastVal, ok := t.last[obj]
		if !ok {
			continue
		}
		ref, hasManual := t.manualReference[obj]
		if !hasManual {
			emaVal, hasEMA := t.ema[obj]
			if !hasEMA {
				continue
			}
			ref = emaVal
		}
		uncertainty := t.uncertaintyFactor * math.Sqrt(t.variance(obj))
		diff := math.Abs(lastVal-ref) - uncertainty
		if diff < 0 {
			diff = 0
		}
		total += diff * diff
		count++
	}
	if count == 0 {
		return 0.0
	}
	return total / float64(count)
}

// ControlAction returns proportional correction: K_p*(reference-current)/uncertainty.
func (t *AdaptiveReferenceTracker) ControlAction() map[string]float64 {
	t.mu.Lock()
	defer t.mu.Unlock()
	const kP = 0.1
	actions := make(map[string]float64, len(t.objectives))
	for _, obj := range t.objectives {
		ref, hasManual := t.manualReference[obj]
		if !hasManual {
			emaVal, hasEMA := t.ema[obj]
			if !hasEMA {
				actions[obj] = 0.0
				continue
			}
			ref = emaVal
		}
		cur, hasCur := t.last[obj]
		if !hasCur {
			actions[obj] = 0.0
			continue
		}
		uncertainty := 1.0 + t.uncertaintyFactor*math.Sqrt(t.variance(obj))
		actions[obj] = kP * (ref - cur) / uncertainty
	}
	return actions
}

// ---------------------------------------------------------------------------
// Layer 3: HTNDecomposer
// ---------------------------------------------------------------------------

type htnMethod struct {
	name          string
	preconditions map[string]any
	subtasks      []htnSubtask
}

type htnSubtask struct {
	name       string
	parameters map[string]any
	assignedTo string
	priority   float64
}

// HTNDecomposer decomposes high-level goals into subtasks using a Hierarchical
// Task Network.
type HTNDecomposer struct {
	mu      sync.RWMutex
	methods map[string][]htnMethod // goal → methods
}

// NewHTNDecomposer creates an empty decomposer.
func NewHTNDecomposer() *HTNDecomposer {
	return &HTNDecomposer{methods: make(map[string][]htnMethod)}
}

// RegisterMethod registers a decomposition method for a goal.
func (h *HTNDecomposer) RegisterMethod(goal, methodName string, preconditions map[string]any, subtasks []htnSubtask) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.methods[goal] = append(h.methods[goal], htnMethod{
		name:          methodName,
		preconditions: preconditions,
		subtasks:      subtasks,
	})
	slog.Debug("registered HTN method", "method", methodName, "goal", goal)
}

// RegisterVictoriaMethods registers the default Victoria pipeline decompositions.
func (h *HTNDecomposer) RegisterVictoriaMethods() {
	h.RegisterMethod("research_cycle", "standard_pipeline", map[string]any{}, []htnSubtask{
		{name: "ingest_data", parameters: map[string]any{}, assignedTo: "data_ingestion_node", priority: 1.0},
		{name: "generate_signals", parameters: map[string]any{}, assignedTo: "signal_generation_node", priority: 0.9},
		{name: "run_strategy", parameters: map[string]any{}, assignedTo: "strategy_node", priority: 0.8},
		{name: "assess_risk", parameters: map[string]any{}, assignedTo: "risk_management_node", priority: 0.85},
		{name: "generate_report", parameters: map[string]any{}, assignedTo: "reporting_node", priority: 0.6},
	})
	h.RegisterMethod("risk_breach", "risk_response", map[string]any{"max_drawdown_pct": map[string]any{">": 10.0}}, []htnSubtask{
		{name: "run_risk_management", parameters: map[string]any{"mode": "emergency"}, assignedTo: "risk_management_node", priority: 1.0},
		{name: "rebalance_portfolio", parameters: map[string]any{}, assignedTo: "strategy_node", priority: 0.95},
		{name: "generate_report", parameters: map[string]any{"type": "risk_breach"}, assignedTo: "reporting_node", priority: 0.7},
	})
	h.RegisterMethod("data_stale", "data_refresh", map[string]any{}, []htnSubtask{
		{name: "ingest_data", parameters: map[string]any{"force_refresh": true}, assignedTo: "data_ingestion_node", priority: 1.0},
		{name: "generate_signals", parameters: map[string]any{}, assignedTo: "signal_generation_node", priority: 0.9},
	})
	h.RegisterMethod("system_improve", "self_improvement", map[string]any{}, []htnSubtask{
		{name: "evaluate_nodes", parameters: map[string]any{}, assignedTo: "orchestrator_node", priority: 0.9},
		{name: "improve_weakest_node", parameters: map[string]any{}, assignedTo: "orchestrator_node", priority: 0.85},
		{name: "generate_report", parameters: map[string]any{"type": "improvement"}, assignedTo: "reporting_node", priority: 0.6},
	})
}

func (h *HTNDecomposer) checkPreconditions(preconditions map[string]any, state map[string]any) bool {
	for key, condition := range preconditions {
		stateVal, ok := state[key]
		if !ok {
			return false
		}
		switch cond := condition.(type) {
		case map[string]any:
			stateFloat, ok := toFloat64(stateVal)
			if !ok {
				return false
			}
			for op, limitVal := range cond {
				limit, ok := toFloat64(limitVal)
				if !ok {
					return false
				}
				switch op {
				case ">":
					if !(stateFloat > limit) {
						return false
					}
				case "<":
					if !(stateFloat < limit) {
						return false
					}
				case ">=":
					if !(stateFloat >= limit) {
						return false
					}
				case "<=":
					if !(stateFloat <= limit) {
						return false
					}
				case "==":
					if !(stateFloat == limit) {
						return false
					}
				default:
					slog.Warn("unknown precondition operator", "op", op)
					return false
				}
			}
		default:
			if stateVal != condition {
				return false
			}
		}
	}
	return true
}

func toFloat64(v any) (float64, bool) {
	switch n := v.(type) {
	case float64:
		return n, true
	case float32:
		return float64(n), true
	case int:
		return float64(n), true
	case int64:
		return float64(n), true
	case int32:
		return float64(n), true
	}
	return 0, false
}

// ApplicableMethods returns method names where all preconditions are satisfied.
func (h *HTNDecomposer) ApplicableMethods(goal string, state map[string]any) []string {
	h.mu.RLock()
	defer h.mu.RUnlock()
	var names []string
	for _, m := range h.methods[goal] {
		if h.checkPreconditions(m.preconditions, state) {
			names = append(names, m.name)
		}
	}
	return names
}

func (h *HTNDecomposer) buildTasks(subtasks []htnSubtask) []Task {
	tasks := make([]Task, 0, len(subtasks))
	for _, st := range subtasks {
		params := make(map[string]any, len(st.parameters))
		for k, v := range st.parameters {
			params[k] = v
		}
		tasks = append(tasks, Task{
			TaskID:        uuid.New().String(),
			Name:          st.name,
			Parameters:    params,
			AssignedTo:    st.assignedTo,
			Priority:      st.priority,
			Preconditions: map[string]any{},
		})
	}
	return tasks
}

// Decompose finds applicable methods for goal and returns Tasks from the first match.
func (h *HTNDecomposer) Decompose(goal string, state map[string]any) []Task {
	h.mu.RLock()
	defer h.mu.RUnlock()
	for _, method := range h.methods[goal] {
		if h.checkPreconditions(method.preconditions, state) {
			slog.Debug("HTN decomposing goal", "goal", goal, "method", method.name)
			return h.buildTasks(method.subtasks)
		}
	}
	slog.Warn("HTN: no applicable method for goal; returning default task", "goal", goal)
	return []Task{{
		TaskID:        uuid.New().String(),
		Name:          goal,
		Parameters:    map[string]any{},
		AssignedTo:    "orchestrator_node",
		Priority:      0.5,
		Preconditions: map[string]any{},
	}}
}

// ---------------------------------------------------------------------------
// Advanced / experimental
// ---------------------------------------------------------------------------

// NashWelfareAggregator computes the Nash bargaining solution for balancing
// competing objectives. Advanced component — not activated in GoalArchitecture
// by default.
type NashWelfareAggregator struct {
	mu              sync.Mutex
	objectives      []string
	disagreement    map[string]float64
	weights         map[string]float64
	outcomesHistory []map[string]float64
}

// NewNashWelfareAggregator creates an aggregator for the given objectives.
func NewNashWelfareAggregator(objectives []string, disagreementPoints map[string]float64) *NashWelfareAggregator {
	n := &NashWelfareAggregator{
		objectives:   append([]string(nil), objectives...),
		disagreement: make(map[string]float64, len(objectives)),
		weights:      make(map[string]float64, len(objectives)),
	}
	for _, o := range objectives {
		n.disagreement[o] = 0.0
		n.weights[o] = 1.0 / float64(len(objectives))
	}
	for o, d := range disagreementPoints {
		n.disagreement[o] = d
	}
	return n
}

// NashWelfare computes Nash welfare = Π(u_i - d_i) using log-sum for stability.
func (n *NashWelfareAggregator) NashWelfare(outcomes map[string]float64) float64 {
	logSum := 0.0
	for _, obj := range n.objectives {
		u := outcomes[obj]
		d := n.disagreement[obj]
		surplus := u - d
		if surplus <= 0 {
			return 0.0
		}
		logSum += math.Log(surplus)
	}
	return math.Exp(logSum)
}

func randomSimplexPoint(seed uint64, n int) []float64 {
	result := make([]float64, n)
	for i := range result {
		seed = seed*6364136223846793005 + 1442695040888963407
		result[i] = float64(seed>>11) / float64(1<<53)
	}
	exps := make([]float64, n)
	total := 0.0
	for i, v := range result {
		e := -math.Log(math.Max(1e-15, v))
		exps[i] = e
		total += e
	}
	for i := range exps {
		exps[i] /= total
	}
	return exps
}

// OptimalWeights finds objective weights maximising Nash welfare over outcomes history.
func (n *NashWelfareAggregator) OptimalWeights(outcomesHistory []map[string]float64, nTrials int) map[string]float64 {
	n.mu.Lock()
	defer n.mu.Unlock()
	if len(outcomesHistory) == 0 || len(n.objectives) == 0 {
		out := make(map[string]float64, len(n.weights))
		for k, v := range n.weights {
			out[k] = v
		}
		return out
	}
	k := len(n.objectives)
	bestWelfare := -1.0
	var bestWeights []float64
	for trial := 0; trial < nTrials; trial++ {
		candidate := randomSimplexPoint(uint64(trial*2654435761+1013904223), k)
		w := make(map[string]float64, k)
		for i, obj := range n.objectives {
			w[obj] = candidate[i]
		}
		totalWelfare := 0.0
		for _, outcomes := range outcomesHistory {
			weighted := make(map[string]float64, k)
			for _, obj := range n.objectives {
				weighted[obj] = outcomes[obj] * w[obj]
			}
			totalWelfare += n.nashWelfareInternal(weighted)
		}
		avg := totalWelfare / float64(len(outcomesHistory))
		if avg > bestWelfare {
			bestWelfare = avg
			bestWeights = candidate
		}
	}
	for i, obj := range n.objectives {
		n.weights[obj] = bestWeights[i]
	}
	out := make(map[string]float64, len(n.weights))
	for k, v := range n.weights {
		out[k] = v
	}
	return out
}

func (n *NashWelfareAggregator) nashWelfareInternal(outcomes map[string]float64) float64 {
	logSum := 0.0
	for _, obj := range n.objectives {
		u := outcomes[obj]
		d := n.disagreement[obj]
		surplus := u - d
		if surplus <= 0 {
			return 0.0
		}
		logSum += math.Log(surplus)
	}
	return math.Exp(logSum)
}

// Aggregate records metrics and returns Nash welfare using current weights.
func (n *NashWelfareAggregator) Aggregate(metrics map[string]float64) float64 {
	n.mu.Lock()
	defer n.mu.Unlock()
	snapshot := make(map[string]float64, len(metrics))
	for k, v := range metrics {
		snapshot[k] = v
	}
	n.outcomesHistory = append(n.outcomesHistory, snapshot)
	if len(n.outcomesHistory) > 200 {
		n.outcomesHistory = n.outcomesHistory[len(n.outcomesHistory)-200:]
	}
	weighted := make(map[string]float64, len(n.objectives))
	for _, obj := range n.objectives {
		weighted[obj] = metrics[obj] * n.weights[obj]
	}
	return n.nashWelfareInternal(weighted)
}

// MPCReferenceTracker is retained for experimental use. For production, prefer
// AdaptiveReferenceTracker which handles dynamic systems correctly.
type MPCReferenceTracker struct {
	mu         sync.Mutex
	objectives []string
	horizon    int
	reference  map[string][]float64
	history    []map[string]float64
}

// NewMPCReferenceTracker creates a tracker with the given objectives and horizon.
func NewMPCReferenceTracker(objectives []string, horizon int) *MPCReferenceTracker {
	return &MPCReferenceTracker{
		objectives: append([]string(nil), objectives...),
		horizon:    horizon,
		reference:  make(map[string][]float64),
	}
}

// SetReference sets the reference trajectory.
func (m *MPCReferenceTracker) SetReference(trajectory map[string][]float64) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.reference = make(map[string][]float64, len(trajectory))
	for obj, vals := range trajectory {
		m.reference[obj] = append([]float64(nil), vals...)
	}
}

// Update records current state in history.
func (m *MPCReferenceTracker) Update(current map[string]float64) {
	m.mu.Lock()
	defer m.mu.Unlock()
	snapshot := make(map[string]float64, len(current))
	for k, v := range current {
		snapshot[k] = v
	}
	m.history = append(m.history, snapshot)
	if len(m.history) > 200 {
		m.history = m.history[len(m.history)-200:]
	}
}

// PredictHorizon returns linear trend predictions over the horizon.
func (m *MPCReferenceTracker) PredictHorizon() map[string][]float64 {
	m.mu.Lock()
	defer m.mu.Unlock()
	predictions := make(map[string][]float64, len(m.objectives))
	for _, obj := range m.objectives {
		var values []float64
		for _, h := range m.history {
			if v, ok := h[obj]; ok {
				values = append(values, v)
			}
		}
		if len(values) == 0 {
			preds := make([]float64, m.horizon)
			predictions[obj] = preds
			continue
		}
		if len(values) == 1 {
			preds := make([]float64, m.horizon)
			for i := range preds {
				preds[i] = values[0]
			}
			predictions[obj] = preds
			continue
		}
		window := 10
		if len(values) < window {
			window = len(values)
		}
		recent := values[len(values)-window:]
		n := len(recent)
		xMean := float64(n-1) / 2.0
		yMean := 0.0
		for _, y := range recent {
			yMean += y
		}
		yMean /= float64(n)
		num, den := 0.0, 0.0
		for i, y := range recent {
			xi := float64(i) - xMean
			num += xi * (y - yMean)
			den += xi * xi
		}
		slope := 0.0
		if den != 0 {
			slope = num / den
		}
		last := recent[len(recent)-1]
		preds := make([]float64, m.horizon)
		for t := range preds {
			preds[t] = last + slope*float64(t+1)
		}
		predictions[obj] = preds
	}
	return predictions
}

// TrackingError returns MSE between predicted horizon and reference trajectory.
func (m *MPCReferenceTracker) TrackingError() float64 {
	m.mu.Lock()
	defer m.mu.Unlock()
	if len(m.reference) == 0 {
		return 0.0
	}
	predicted := m.predictHorizonUnlocked()
	totalMSE, count := 0.0, 0
	for _, obj := range m.objectives {
		ref := m.reference[obj]
		pred := predicted[obj]
		if ref == nil || pred == nil {
			continue
		}
		steps := m.horizon
		if len(ref) < steps {
			steps = len(ref)
		}
		if len(pred) < steps {
			steps = len(pred)
		}
		for t := 0; t < steps; t++ {
			diff := pred[t] - ref[t]
			totalMSE += diff * diff
			count++
		}
	}
	if count == 0 {
		return 0.0
	}
	return totalMSE / float64(count)
}

func (m *MPCReferenceTracker) predictHorizonUnlocked() map[string][]float64 {
	// same logic as PredictHorizon but without locking (caller holds lock)
	predictions := make(map[string][]float64, len(m.objectives))
	for _, obj := range m.objectives {
		var values []float64
		for _, h := range m.history {
			if v, ok := h[obj]; ok {
				values = append(values, v)
			}
		}
		if len(values) == 0 {
			predictions[obj] = make([]float64, m.horizon)
			continue
		}
		if len(values) == 1 {
			preds := make([]float64, m.horizon)
			for i := range preds {
				preds[i] = values[0]
			}
			predictions[obj] = preds
			continue
		}
		window := 10
		if len(values) < window {
			window = len(values)
		}
		recent := values[len(values)-window:]
		n := len(recent)
		xMean := float64(n-1) / 2.0
		yMean := 0.0
		for _, y := range recent {
			yMean += y
		}
		yMean /= float64(n)
		num, den := 0.0, 0.0
		for i, y := range recent {
			xi := float64(i) - xMean
			num += xi * (y - yMean)
			den += xi * xi
		}
		slope := 0.0
		if den != 0 {
			slope = num / den
		}
		last := recent[len(recent)-1]
		preds := make([]float64, m.horizon)
		for t := range preds {
			preds[t] = last + slope*float64(t+1)
		}
		predictions[obj] = preds
	}
	return predictions
}

// ControlAction returns proportional corrections toward the reference.
func (m *MPCReferenceTracker) ControlAction() map[string]float64 {
	m.mu.Lock()
	defer m.mu.Unlock()
	const kP = 0.1
	actions := make(map[string]float64, len(m.objectives))
	if len(m.history) == 0 {
		for _, obj := range m.objectives {
			actions[obj] = 0.0
		}
		return actions
	}
	current := m.history[len(m.history)-1]
	for _, obj := range m.objectives {
		refTraj := m.reference[obj]
		refVal := 0.0
		if len(refTraj) > 0 {
			refVal = refTraj[0]
		}
		curVal := current[obj]
		actions[obj] = kP * (refVal - curVal)
	}
	return actions
}

// ---------------------------------------------------------------------------
// GoalArchitecture
// ---------------------------------------------------------------------------

var defaultObjectives = []string{"sharpe_ratio", "coverage_rate", "error_rate"}

// GoalArchitecture orchestrates 3 goal layers and produces a GoalDecision each cycle.
// Pipeline: ConstitutionalConstraints → BalancedScorecard → HTNDecomposer
// Tracking: AdaptiveReferenceTracker (rolling EMA, uncertainty-aware)
type GoalArchitecture struct {
	mu          sync.Mutex
	objectives  []string
	constraints *ConstitutionalConstraints
	scorecard   *BalancedScorecard
	htn         *HTNDecomposer
	tracker     *AdaptiveReferenceTracker
	currentGoal string
}

// NewGoalArchitecture creates a GoalArchitecture with optional objectives override.
func NewGoalArchitecture(objectives []string) *GoalArchitecture {
	if len(objectives) == 0 {
		objectives = append([]string(nil), defaultObjectives...)
	}
	cc := &ConstitutionalConstraints{}
	cc.RegisterDefaults()

	htn := NewHTNDecomposer()
	htn.RegisterVictoriaMethods()

	ga := &GoalArchitecture{
		objectives:  objectives,
		constraints: cc,
		scorecard:   NewBalancedScorecard(nil),
		htn:         htn,
		tracker:     NewAdaptiveReferenceTracker(objectives, 0.2, 1.5),
		currentGoal: "research_cycle",
	}
	slog.Info("GoalArchitecture initialised", "objectives", objectives)
	return ga
}

func (ga *GoalArchitecture) inferGoal(metrics map[string]float64, systemState map[string]any) string {
	if drawdown, ok := metrics["max_drawdown_pct"]; ok && drawdown > 10.0 {
		return "risk_breach"
	}
	if stale, ok := systemState["data_stale"]; ok {
		if b, ok := stale.(bool); ok && b {
			return "data_stale"
		}
	}
	if improve, ok := systemState["trigger_improvement"]; ok {
		if b, ok := improve.(bool); ok && b {
			return "system_improve"
		}
	}
	return "research_cycle"
}

// Step executes one goal-architecture cycle and returns a GoalDecision.
func (ga *GoalArchitecture) Step(ctx context.Context, metrics map[string]float64, systemState map[string]any, cycle int) GoalDecision {
	if systemState == nil {
		systemState = make(map[string]any)
	}
	slog.Debug("GoalArchitecture.Step", "cycle", cycle, "metrics", fmt.Sprintf("%v", metrics))

	// Layer 1: Constitutional constraints.
	passed, violations := ga.constraints.Check(ctx, metrics)

	// Layer 2: Balanced scorecard.
	ga.scorecard.Update(metrics)
	scorecard := ga.scorecard.Score()
	composite := ga.scorecard.CompositeScore()

	// Adaptive reference tracker.
	ga.tracker.Update(metrics)
	trackingErr := ga.tracker.TrackingError()
	ctrl := ga.tracker.ControlAction()

	// Layer 3: HTN decomposition.
	goal := ga.inferGoal(metrics, systemState)
	ga.mu.Lock()
	ga.currentGoal = goal
	ga.mu.Unlock()

	mergedState := make(map[string]any, len(systemState)+len(metrics))
	for k, v := range systemState {
		mergedState[k] = v
	}
	for k, v := range metrics {
		mergedState[k] = v
	}
	subtasks := ga.htn.Decompose(goal, mergedState)

	decision := GoalDecision{
		Approved:             passed,
		ConstraintViolations: violations,
		Scorecard:            scorecard,
		CompositeScore:       composite,
		Subtasks:             subtasks,
		TrackingError:        trackingErr,
		ControlAction:        ctrl,
		Cycle:                cycle,
	}
	slog.Info("GoalDecision",
		"cycle", cycle,
		"approved", decision.Approved,
		"goal", goal,
		"composite", composite,
		"tracking_error", trackingErr,
		"violations", len(violations),
	)
	return decision
}

// SetReferenceTrajectory sets a manual reference trajectory on the adaptive tracker.
func (ga *GoalArchitecture) SetReferenceTrajectory(trajectory map[string][]float64) {
	ga.tracker.SetReference(trajectory)
}
