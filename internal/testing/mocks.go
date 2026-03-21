package omegatest

// mocks.go — mock implementations of key Omega interfaces.
//
// Each mock records method calls (name + args) and lets tests configure
// return values via With* setters. Mocks are not safe for concurrent use
// unless noted.

import (
	"fmt"
	"sync"

	"github.com/benebsworth/omega/internal/core"
)

// ---------------------------------------------------------------------------
// Call recording
// ---------------------------------------------------------------------------

// Call records one invocation of a mocked method.
type Call struct {
	Method string
	Args   []any
}

// callRecorder is embedded in mocks to provide call recording.
type callRecorder struct {
	mu    sync.Mutex
	calls []Call
}

func (r *callRecorder) record(method string, args ...any) {
	r.mu.Lock()
	r.calls = append(r.calls, Call{Method: method, Args: args})
	r.mu.Unlock()
}

// Calls returns a snapshot of all recorded calls.
func (r *callRecorder) Calls() []Call {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]Call, len(r.calls))
	copy(out, r.calls)
	return out
}

// CallCount returns the number of times method was called.
func (r *callRecorder) CallCount(method string) int {
	r.mu.Lock()
	defer r.mu.Unlock()
	n := 0
	for _, c := range r.calls {
		if c.Method == method {
			n++
		}
	}
	return n
}

// Reset clears all recorded calls.
func (r *callRecorder) Reset() {
	r.mu.Lock()
	r.calls = r.calls[:0]
	r.mu.Unlock()
}

// ---------------------------------------------------------------------------
// MockTPEOptimizer
// ---------------------------------------------------------------------------

// MockTPEOptimizer implements core.TPEOptimizer.
type MockTPEOptimizer struct {
	callRecorder

	// ProposeTrialParamsFunc overrides the default behaviour when set.
	ProposeTrialParamsFunc func(nodeID string, history []core.TrialHistory) (map[string]any, error)

	// DefaultParams is returned when ProposeTrialParamsFunc is nil.
	DefaultParams map[string]any
	// DefaultErr is the error returned when ProposeTrialParamsFunc is nil.
	DefaultErr error
}

// NewMockTPEOptimizer returns a MockTPEOptimizer that returns a deterministic
// parameter set by default.
func NewMockTPEOptimizer() *MockTPEOptimizer {
	return &MockTPEOptimizer{
		DefaultParams: map[string]any{
			"learning_rate": 0.001,
			"lookback":      20,
			"threshold":     0.5,
		},
	}
}

// ProposeTrialParams satisfies core.TPEOptimizer.
func (m *MockTPEOptimizer) ProposeTrialParams(nodeID string, history []core.TrialHistory) (map[string]any, error) {
	m.record("ProposeTrialParams", nodeID, history)
	if m.ProposeTrialParamsFunc != nil {
		return m.ProposeTrialParamsFunc(nodeID, history)
	}
	return m.DefaultParams, m.DefaultErr
}

// ---------------------------------------------------------------------------
// MockChangePointDetector
// ---------------------------------------------------------------------------

// MockChangePointDetector implements core.ChangePointDetector.
type MockChangePointDetector struct {
	callRecorder

	// DetectChangePointsFunc overrides the default behaviour when set.
	DetectChangePointsFunc func(values []float64) ([]int, error)

	// DefaultIndices is returned when DetectChangePointsFunc is nil.
	DefaultIndices []int
	// DefaultErr is the error returned when DetectChangePointsFunc is nil.
	DefaultErr error
}

// NewMockChangePointDetector returns a MockChangePointDetector that reports no
// changepoints by default.
func NewMockChangePointDetector() *MockChangePointDetector {
	return &MockChangePointDetector{}
}

// DetectChangePoints satisfies core.ChangePointDetector.
func (m *MockChangePointDetector) DetectChangePoints(values []float64) ([]int, error) {
	m.record("DetectChangePoints", values)
	if m.DetectChangePointsFunc != nil {
		return m.DetectChangePointsFunc(values)
	}
	return m.DefaultIndices, m.DefaultErr
}

// ---------------------------------------------------------------------------
// MockHealthChecker
// ---------------------------------------------------------------------------

// HealthChecker is the interface mocked here. It can be used wherever a
// component needs to query node health without a full DB round-trip.
type HealthChecker interface {
	NodeHealth(nodeID string) (float64, error)
	SystemCompositeScore() (float64, error)
}

// MockHealthChecker implements HealthChecker.
type MockHealthChecker struct {
	callRecorder

	// NodeHealthFunc overrides the default behaviour when set.
	NodeHealthFunc func(nodeID string) (float64, error)
	// SystemCompositeScoreFunc overrides the default behaviour when set.
	SystemCompositeScoreFunc func() (float64, error)

	// NodeHealthMap stores per-node health values for the default implementation.
	NodeHealthMap map[string]float64
	// DefaultSystemScore is returned by SystemCompositeScore when no func is set.
	DefaultSystemScore float64
}

// NewMockHealthChecker returns a MockHealthChecker where all nodes have health 1.0
// and system composite score is 1.0.
func NewMockHealthChecker() *MockHealthChecker {
	return &MockHealthChecker{
		NodeHealthMap:      make(map[string]float64),
		DefaultSystemScore: 1.0,
	}
}

// SetNodeHealth configures the health returned for nodeID.
func (m *MockHealthChecker) SetNodeHealth(nodeID string, health float64) {
	m.mu.Lock()
	m.NodeHealthMap[nodeID] = health
	m.mu.Unlock()
}

// NodeHealth satisfies HealthChecker.
func (m *MockHealthChecker) NodeHealth(nodeID string) (float64, error) {
	m.record("NodeHealth", nodeID)
	if m.NodeHealthFunc != nil {
		return m.NodeHealthFunc(nodeID)
	}
	m.mu.Lock()
	h, ok := m.NodeHealthMap[nodeID]
	m.mu.Unlock()
	if !ok {
		return 1.0, nil
	}
	return h, nil
}

// SystemCompositeScore satisfies HealthChecker.
func (m *MockHealthChecker) SystemCompositeScore() (float64, error) {
	m.record("SystemCompositeScore")
	if m.SystemCompositeScoreFunc != nil {
		return m.SystemCompositeScoreFunc()
	}
	return m.DefaultSystemScore, nil
}

// ---------------------------------------------------------------------------
// MockNode
// ---------------------------------------------------------------------------

// NodeRunner is the interface mocked here. It represents a node that can be
// asked to run a single cycle.
type NodeRunner interface {
	RunCycle(nodeID string, cycle int, params map[string]any) (map[string]float64, error)
	NodeID() string
}

// MockNode implements NodeRunner.
type MockNode struct {
	callRecorder

	id string

	// RunCycleFunc overrides the default behaviour when set.
	RunCycleFunc func(nodeID string, cycle int, params map[string]any) (map[string]float64, error)

	// DefaultMetrics is returned by RunCycle when RunCycleFunc is nil.
	DefaultMetrics map[string]float64
	// DefaultErr is the error returned by RunCycle when RunCycleFunc is nil.
	DefaultErr error
}

// NewMockNode returns a MockNode that succeeds with deterministic metrics.
func NewMockNode(nodeID string) *MockNode {
	return &MockNode{
		id: nodeID,
		DefaultMetrics: map[string]float64{
			"accuracy": 0.9,
			"latency":  120.0,
		},
	}
}

// NodeID satisfies NodeRunner.
func (m *MockNode) NodeID() string { return m.id }

// RunCycle satisfies NodeRunner.
func (m *MockNode) RunCycle(nodeID string, cycle int, params map[string]any) (map[string]float64, error) {
	m.record("RunCycle", nodeID, cycle, params)
	if m.RunCycleFunc != nil {
		return m.RunCycleFunc(nodeID, cycle, params)
	}
	return m.DefaultMetrics, m.DefaultErr
}

// ---------------------------------------------------------------------------
// MockDomainConfig
// ---------------------------------------------------------------------------

// DomainConfig is the interface mocked here. It provides node-level config
// values that vary per deployment.
type DomainConfig interface {
	MaxPositionPct(nodeID string) float64
	MaxDrawdownPct(nodeID string) float64
	ImprovementInterval(nodeID string) int // cycles
}

// MockDomainConfig implements DomainConfig with configurable per-node overrides.
type MockDomainConfig struct {
	callRecorder

	// Per-node overrides. Falls back to defaults when not set.
	MaxPositionPctOverrides    map[string]float64
	MaxDrawdownPctOverrides    map[string]float64
	ImprovementIntervalOverrides map[string]int

	// Defaults applied when no override is present.
	DefaultMaxPositionPct   float64
	DefaultMaxDrawdownPct   float64
	DefaultImprovementInterval int
}

// NewMockDomainConfig returns a MockDomainConfig with conservative defaults.
func NewMockDomainConfig() *MockDomainConfig {
	return &MockDomainConfig{
		MaxPositionPctOverrides:      make(map[string]float64),
		MaxDrawdownPctOverrides:      make(map[string]float64),
		ImprovementIntervalOverrides: make(map[string]int),
		DefaultMaxPositionPct:        0.3,
		DefaultMaxDrawdownPct:        0.15,
		DefaultImprovementInterval:   10,
	}
}

// SetMaxPosition configures per-node MaxPositionPct.
func (m *MockDomainConfig) SetMaxPosition(nodeID string, v float64) {
	m.mu.Lock()
	m.MaxPositionPctOverrides[nodeID] = v
	m.mu.Unlock()
}

// MaxPositionPct satisfies DomainConfig.
func (m *MockDomainConfig) MaxPositionPct(nodeID string) float64 {
	m.record("MaxPositionPct", nodeID)
	m.mu.Lock()
	defer m.mu.Unlock()
	if v, ok := m.MaxPositionPctOverrides[nodeID]; ok {
		return v
	}
	return m.DefaultMaxPositionPct
}

// MaxDrawdownPct satisfies DomainConfig.
func (m *MockDomainConfig) MaxDrawdownPct(nodeID string) float64 {
	m.record("MaxDrawdownPct", nodeID)
	m.mu.Lock()
	defer m.mu.Unlock()
	if v, ok := m.MaxDrawdownPctOverrides[nodeID]; ok {
		return v
	}
	return m.DefaultMaxDrawdownPct
}

// ImprovementInterval satisfies DomainConfig.
func (m *MockDomainConfig) ImprovementInterval(nodeID string) int {
	m.record("ImprovementInterval", nodeID)
	m.mu.Lock()
	defer m.mu.Unlock()
	if v, ok := m.ImprovementIntervalOverrides[nodeID]; ok {
		return v
	}
	return m.DefaultImprovementInterval
}

// ---------------------------------------------------------------------------
// AssertCalled / AssertNotCalled helpers for test assertions
// ---------------------------------------------------------------------------

// AssertCalled fails tb if method was never called on the mock.
func AssertCalled(tb interface{ Helper(); Errorf(string, ...any) }, r interface{ CallCount(string) int }, method string) {
	tb.Helper()
	if r.CallCount(method) == 0 {
		tb.Errorf("expected %q to have been called at least once, but it was not", method)
	}
}

// AssertNotCalled fails tb if method was called on the mock.
func AssertNotCalled(tb interface{ Helper(); Errorf(string, ...any) }, r interface{ CallCount(string) int }, method string) {
	tb.Helper()
	if n := r.CallCount(method); n > 0 {
		tb.Errorf("expected %q not to have been called, but it was called %d time(s)", method, n)
	}
}

// AssertCalledN fails tb if method was not called exactly n times.
func AssertCalledN(tb interface{ Helper(); Errorf(string, ...any) }, r interface{ CallCount(string) int }, method string, n int) {
	tb.Helper()
	if got := r.CallCount(method); got != n {
		tb.Errorf("expected %q to have been called %d time(s), got %d", method, n, got)
	}
}

// FormatCalls returns a human-readable summary of all recorded calls for
// use in failure messages.
func FormatCalls(r interface{ Calls() []Call }) string {
	calls := r.Calls()
	if len(calls) == 0 {
		return "(no calls recorded)"
	}
	out := ""
	for i, c := range calls {
		out += fmt.Sprintf("  [%d] %s(%v)\n", i, c.Method, c.Args)
	}
	return out
}
