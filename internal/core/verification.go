// verification.go — Composable gate objects that verify system properties
// before committing improvements.
//
// Gate types:
//   PropertyGate    — arbitrary predicate on a context map
//   InvariantGate   — system invariant that must hold across all states
//   ConsistencyGate — cross-subsystem consistency check
//   RegressionGate  — before/after metric regression detection
//   ConvergenceGate — statistical test that a metric series is converging
//
// Composition:
//   AndGate — all children must pass
//   OrGate  — at least one child must pass
//
// Each gate has a Check(context) method returning GateResult(PASS/FAIL/WARNING).
// Gates can be registered with VerificationGateSystem and run collectively.
package core

import (
	"fmt"
	"math"
)

// ---------------------------------------------------------------------------
// GateStatus
// ---------------------------------------------------------------------------

// GateStatus is the outcome of a gate check.
type GateStatus string

const (
	GatePass    GateStatus = "pass"
	GateFail    GateStatus = "fail"
	GateWarning GateStatus = "warning"
)

// GateResult is the result of a single gate check.
type GateResult struct {
	Status   GateStatus
	GateName string
	Evidence string
	Details  map[string]any
}

// Passed returns true if the status is GatePass.
func (r GateResult) Passed() bool { return r.Status == GatePass }

// Failed returns true if the status is GateFail.
func (r GateResult) Failed() bool { return r.Status == GateFail }

// ---------------------------------------------------------------------------
// Gate interface
// ---------------------------------------------------------------------------

// Gate is the common interface for all verification gates.
type Gate interface {
	Name() string
	Check(context map[string]any) GateResult
}

// ---------------------------------------------------------------------------
// PropertyGate
// ---------------------------------------------------------------------------

// PropertyGate passes when predicate(context) is true.
type PropertyGate struct {
	name        string
	predicate   func(map[string]any) bool
	description string
}

// NewPropertyGate creates a PropertyGate.
func NewPropertyGate(name string, predicate func(map[string]any) bool, description string) *PropertyGate {
	return &PropertyGate{name: name, predicate: predicate, description: description}
}

func (g *PropertyGate) Name() string { return g.name }

func (g *PropertyGate) Check(context map[string]any) (result GateResult) {
	defer func() {
		if r := recover(); r != nil {
			result = GateResult{
				Status:   GateFail,
				GateName: g.name,
				Evidence: fmt.Sprintf("panic: %v", r),
			}
		}
	}()
	ok := g.predicate(context)
	evidence := g.description
	if !ok {
		evidence = "Property violated: " + g.description
	}
	status := GatePass
	if !ok {
		status = GateFail
	}
	return GateResult{Status: status, GateName: g.name, Evidence: evidence}
}

// ---------------------------------------------------------------------------
// InvariantGate
// ---------------------------------------------------------------------------

// InvariantGate checks a system invariant — must hold at all times.
type InvariantGate struct {
	name        string
	invariant   func(map[string]any) bool
	description string
}

// NewInvariantGate creates an InvariantGate.
func NewInvariantGate(name string, invariant func(map[string]any) bool, description string) *InvariantGate {
	return &InvariantGate{name: name, invariant: invariant, description: description}
}

func (g *InvariantGate) Name() string { return g.name }

func (g *InvariantGate) Check(context map[string]any) (result GateResult) {
	defer func() {
		if r := recover(); r != nil {
			result = GateResult{
				Status:   GateFail,
				GateName: g.name,
				Evidence: fmt.Sprintf("Invariant check raised: panic: %v", r),
			}
		}
	}()
	ok := g.invariant(context)
	evidence := g.description
	if !ok {
		evidence = "Invariant violated: " + g.description
	}
	status := GatePass
	if !ok {
		status = GateFail
	}
	return GateResult{Status: status, GateName: g.name, Evidence: evidence}
}

// ---------------------------------------------------------------------------
// ConsistencyGate
// ---------------------------------------------------------------------------

// ConsistencyGate performs a cross-subsystem consistency check.
type ConsistencyGate struct {
	name        string
	checkFn     func(map[string]any) bool
	description string
}

// NewConsistencyGate creates a ConsistencyGate.
func NewConsistencyGate(name string, checkFn func(map[string]any) bool, description string) *ConsistencyGate {
	return &ConsistencyGate{name: name, checkFn: checkFn, description: description}
}

func (g *ConsistencyGate) Name() string { return g.name }

func (g *ConsistencyGate) Check(context map[string]any) (result GateResult) {
	defer func() {
		if r := recover(); r != nil {
			result = GateResult{
				Status:   GateFail,
				GateName: g.name,
				Evidence: fmt.Sprintf("Consistency check raised: %v", r),
			}
		}
	}()
	ok := g.checkFn(context)
	evidence := g.description
	if !ok {
		evidence = "Consistency violated: " + g.description
	}
	status := GatePass
	if !ok {
		status = GateFail
	}
	return GateResult{Status: status, GateName: g.name, Evidence: evidence}
}

// ---------------------------------------------------------------------------
// RegressionGate
// ---------------------------------------------------------------------------

// RegressionGate detects metric regressions between before/after snapshots.
// Context keys: "before" and "after" — both map[string]float64.
// Direction "maximize": regression = drop. "minimize": regression = rise.
// ThresholdPct is the percentage change that constitutes a regression.
type RegressionGate struct {
	name         string
	metric       string
	direction    string
	thresholdPct float64
}

// NewRegressionGate creates a RegressionGate.
func NewRegressionGate(name, metric, direction string, thresholdPct float64) *RegressionGate {
	return &RegressionGate{
		name:         name,
		metric:       metric,
		direction:    direction,
		thresholdPct: thresholdPct,
	}
}

func (g *RegressionGate) Name() string { return g.name }

func (g *RegressionGate) Check(context map[string]any) GateResult {
	before, _ := context["before"].(map[string]float64)
	after, _ := context["after"].(map[string]float64)

	bval, bOK := before[g.metric]
	aval, aOK := after[g.metric]

	if !bOK || !aOK {
		return GateResult{
			Status:   GateWarning,
			GateName: g.name,
			Evidence: fmt.Sprintf("Metric '%s' missing from before/after context", g.metric),
		}
	}

	pctChange := 0.0
	if bval != 0 {
		pctChange = (aval - bval) / math.Abs(bval) * 100.0
	}

	regressed := false
	if g.direction == "maximize" {
		regressed = pctChange < -g.thresholdPct
	} else {
		regressed = pctChange > g.thresholdPct
	}

	details := map[string]any{
		"metric":     g.metric,
		"before":     bval,
		"after":      aval,
		"pct_change": pctChange,
	}

	if regressed {
		return GateResult{
			Status:   GateFail,
			GateName: g.name,
			Evidence: fmt.Sprintf("Regression: %s changed %.1f%% (before=%.4f, after=%.4f, threshold=%.1f%%)",
				g.metric, pctChange, bval, aval, g.thresholdPct),
			Details: details,
		}
	}
	return GateResult{
		Status:   GatePass,
		GateName: g.name,
		Evidence: fmt.Sprintf("%s change=%+.1f%% within threshold", g.metric, pctChange),
		Details:  details,
	}
}

// ---------------------------------------------------------------------------
// ConvergenceGate
// ---------------------------------------------------------------------------

// ConvergenceGate tests that a metric history is converging.
// Context key: "history" — []float64 in iteration order.
// Requires at least Window data points; returns WARNING if insufficient.
// FAIL if the series is oscillating (high mean abs diff relative to range).
type ConvergenceGate struct {
	name      string
	metric    string
	window    int
	direction string
}

// NewConvergenceGate creates a ConvergenceGate.
func NewConvergenceGate(name, metric string, window int, direction string) *ConvergenceGate {
	return &ConvergenceGate{name: name, metric: metric, window: window, direction: direction}
}

func (g *ConvergenceGate) Name() string { return g.name }

func (g *ConvergenceGate) Check(context map[string]any) GateResult {
	rawHistory := context["history"]
	var history []float64
	switch h := rawHistory.(type) {
	case []float64:
		history = h
	case []any:
		for _, v := range h {
			if f, ok := v.(float64); ok {
				history = append(history, f)
			}
		}
	}

	if len(history) < g.window {
		return GateResult{
			Status:   GateWarning,
			GateName: g.name,
			Evidence: fmt.Sprintf("Insufficient history: %d < %d required", len(history), g.window),
		}
	}

	recent := history[len(history)-g.window:]
	n := len(recent)
	meanX := float64(n-1) / 2.0
	meanY := 0.0
	for _, y := range recent {
		meanY += y
	}
	meanY /= float64(n)

	slopeNum, slopeDen := 0.0, 0.0
	for i, y := range recent {
		xi := float64(i) - meanX
		slopeNum += xi * (y - meanY)
		slopeDen += xi * xi
	}
	slope := 0.0
	if slopeDen != 0 {
		slope = slopeNum / slopeDen
	}

	converging := (g.direction == "maximize" && slope > 0) || (g.direction != "maximize" && slope < 0)

	minVal, maxVal := recent[0], recent[0]
	for _, v := range recent {
		if v < minVal {
			minVal = v
		}
		if v > maxVal {
			maxVal = v
		}
	}
	rng := maxVal - minVal

	sumAbsDiff := 0.0
	for i := 1; i < n; i++ {
		sumAbsDiff += math.Abs(recent[i] - recent[i-1])
	}
	meanAbsDiff := sumAbsDiff / float64(n-1)
	oscillating := rng > 0 && meanAbsDiff > rng*0.5

	details := map[string]any{
		"slope":        slope,
		"oscillating":  oscillating,
		"history_tail": recent,
	}

	if oscillating {
		return GateResult{
			Status:   GateFail,
			GateName: g.name,
			Evidence: fmt.Sprintf("%s oscillating (slope=%.4f, mean_abs_diff=%.4f)", g.metric, slope, meanAbsDiff),
			Details:  details,
		}
	}
	if !converging {
		return GateResult{
			Status:   GateWarning,
			GateName: g.name,
			Evidence: fmt.Sprintf("%s trend flat or diverging (slope=%.4f)", g.metric, slope),
			Details:  details,
		}
	}
	return GateResult{
		Status:   GatePass,
		GateName: g.name,
		Evidence: fmt.Sprintf("%s converging (slope=%+.4f)", g.metric, slope),
		Details:  details,
	}
}

// ---------------------------------------------------------------------------
// Composite gates
// ---------------------------------------------------------------------------

// AndGate passes only when all children pass. Warnings propagate if no failures.
type AndGate struct {
	name     string
	children []Gate
}

// NewAndGate creates a composite AND gate.
func NewAndGate(name string, children []Gate) *AndGate {
	return &AndGate{name: name, children: children}
}

func (g *AndGate) Name() string { return g.name }

func (g *AndGate) Check(context map[string]any) GateResult {
	results := make([]GateResult, 0, len(g.children))
	for _, child := range g.children {
		results = append(results, child.Check(context))
	}
	var failures, warnings []GateResult
	for _, r := range results {
		if r.Failed() {
			failures = append(failures, r)
		} else if r.Status == GateWarning {
			warnings = append(warnings, r)
		}
	}
	if len(failures) > 0 {
		evidence := joinEvidence(failures)
		return GateResult{Status: GateFail, GateName: g.name, Evidence: evidence}
	}
	if len(warnings) > 0 {
		evidence := joinEvidence(warnings)
		return GateResult{Status: GateWarning, GateName: g.name, Evidence: evidence}
	}
	return GateResult{Status: GatePass, GateName: g.name, Evidence: "All children passed"}
}

// OrGate passes when at least one child passes.
type OrGate struct {
	name     string
	children []Gate
}

// NewOrGate creates a composite OR gate.
func NewOrGate(name string, children []Gate) *OrGate {
	return &OrGate{name: name, children: children}
}

func (g *OrGate) Name() string { return g.name }

func (g *OrGate) Check(context map[string]any) GateResult {
	results := make([]GateResult, 0, len(g.children))
	for _, child := range g.children {
		results = append(results, child.Check(context))
	}
	for _, r := range results {
		if r.Passed() {
			return GateResult{Status: GatePass, GateName: g.name, Evidence: "At least one child passed"}
		}
	}
	for _, r := range results {
		if r.Status == GateWarning {
			return GateResult{Status: GateWarning, GateName: g.name, Evidence: "No child passed; some warnings"}
		}
	}
	return GateResult{
		Status:   GateFail,
		GateName: g.name,
		Evidence: joinEvidence(results),
	}
}

// ---------------------------------------------------------------------------
// VerificationGateSystem
// ---------------------------------------------------------------------------

// VerificationGateSystem is a registry of gates run collectively.
type VerificationGateSystem struct {
	gates []Gate
}

// NewVerificationGateSystem creates an empty gate system.
func NewVerificationGateSystem() *VerificationGateSystem {
	return &VerificationGateSystem{}
}

// Register adds a gate to the system.
func (vgs *VerificationGateSystem) Register(gate Gate) {
	vgs.gates = append(vgs.gates, gate)
}

// RunAll executes all registered gates and returns results.
func (vgs *VerificationGateSystem) RunAll(context map[string]any) []GateResult {
	results := make([]GateResult, len(vgs.gates))
	for i, g := range vgs.gates {
		results[i] = g.Check(context)
	}
	return results
}

// AllPassed returns true if no gate failed (warnings are acceptable).
func (vgs *VerificationGateSystem) AllPassed(results []GateResult) bool {
	for _, r := range results {
		if r.Failed() {
			return false
		}
	}
	return true
}

// GateSummary contains aggregate statistics over a set of gate results.
type GateSummary struct {
	Total    int
	Passed   int
	Failed   int
	Warnings int
	Failures []struct {
		Gate     string
		Evidence string
	}
}

// Summary returns aggregate statistics over a set of gate results.
func (vgs *VerificationGateSystem) Summary(results []GateResult) GateSummary {
	s := GateSummary{Total: len(results)}
	for _, r := range results {
		switch r.Status {
		case GatePass:
			s.Passed++
		case GateFail:
			s.Failed++
			s.Failures = append(s.Failures, struct {
				Gate     string
				Evidence string
			}{Gate: r.GateName, Evidence: r.Evidence})
		case GateWarning:
			s.Warnings++
		}
	}
	return s
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

func joinEvidence(results []GateResult) string {
	out := ""
	for i, r := range results {
		if i > 0 {
			out += "; "
		}
		out += r.Evidence
	}
	return out
}
