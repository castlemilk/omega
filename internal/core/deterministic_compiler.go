package core

// deterministic_compiler.go — DeterministicCompiler, DeterministicStrategy,
// Signal, StrategyRegistry.
//
// Compiles a node's current parameters into a versioned, LLM-free rule set
// (PICO-mode execution engine).  Pure deterministic logic — no network calls.

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
)

// ---------------------------------------------------------------------------
// SignalDirection
// ---------------------------------------------------------------------------

// SignalDirection represents the direction of a trading/action signal.
type SignalDirection string

const (
	DirectionLong  SignalDirection = "long"
	DirectionShort SignalDirection = "short"
	DirectionFlat  SignalDirection = "flat"
)

// ---------------------------------------------------------------------------
// Signal
// ---------------------------------------------------------------------------

// Signal is the output of a DeterministicStrategy.Execute() call.
type Signal struct {
	Direction   SignalDirection
	Confidence  float64
	Metadata    map[string]any
	GeneratedAt time.Time
}

// IsActionable returns true if the signal has a non-flat direction and meets
// the minimum confidence threshold.
func (s Signal) IsActionable(minConfidence float64) bool {
	return s.Direction != DirectionFlat && s.Confidence >= minConfidence
}

// ---------------------------------------------------------------------------
// Rule condition helpers
// ---------------------------------------------------------------------------

// RuleCondition is a single condition in a strategy rule.
type RuleCondition struct {
	Field string  // dot-notation field path in market data, e.g. "price.close"
	Op    string  // ">", "<", ">=", "<=", "==", "!="
	Value float64
}

// StrategyRule is a single rule in a DeterministicStrategy.
type StrategyRule struct {
	Name       string
	Direction  SignalDirection
	Conditions []RuleCondition
	Confidence float64
}

// evaluate returns true if all conditions pass against data.
func (r StrategyRule) evaluate(data map[string]any) bool {
	if len(r.Conditions) == 0 {
		return false
	}
	for _, c := range r.Conditions {
		v, ok := resolveField(c.Field, data)
		if !ok {
			return false
		}
		if !compareFloat(v, c.Op, c.Value) {
			return false
		}
	}
	return true
}

func resolveField(path string, data map[string]any) (float64, bool) {
	parts := strings.Split(path, ".")
	var cur any = data
	for _, p := range parts {
		m, ok := cur.(map[string]any)
		if !ok {
			return 0, false
		}
		cur = m[p]
		if cur == nil {
			return 0, false
		}
	}
	switch v := cur.(type) {
	case float64:
		return v, true
	case float32:
		return float64(v), true
	case int:
		return float64(v), true
	case int64:
		return float64(v), true
	default:
		return 0, false
	}
}

func compareFloat(v float64, op string, threshold float64) bool {
	switch op {
	case ">":
		return v > threshold
	case "<":
		return v < threshold
	case ">=":
		return v >= threshold
	case "<=":
		return v <= threshold
	case "==":
		return v == threshold
	case "!=":
		return v != threshold
	}
	return false
}

// ---------------------------------------------------------------------------
// DeterministicStrategy
// ---------------------------------------------------------------------------

// DeterministicStrategy is a frozen, versioned rule set compiled from a node's
// parameters at a specific point in time.
type DeterministicStrategy struct {
	StrategyID  string
	NodeID      string
	NodeVersion string
	Version     int
	Parameters  map[string]any
	Rules       []StrategyRule
	CompiledAt  time.Time
	Checksum    string // SHA-256 of serialised parameters
}

// Execute evaluates the frozen rules against marketData and returns a Signal.
// Rules are evaluated in order; the first matching rule wins.  If no rule
// fires, a flat Signal with zero confidence is returned.
func (s *DeterministicStrategy) Execute(marketData map[string]any) Signal {
	for _, rule := range s.Rules {
		if rule.evaluate(marketData) {
			return Signal{
				Direction:  rule.Direction,
				Confidence: rule.Confidence,
				Metadata: map[string]any{
					"rule_name":        rule.Name,
					"strategy_id":      s.StrategyID,
					"strategy_version": s.Version,
				},
				GeneratedAt: time.Now(),
			}
		}
	}
	return Signal{
		Direction:  DirectionFlat,
		Confidence: 0,
		Metadata:   map[string]any{"strategy_id": s.StrategyID, "reason": "no_rule_fired"},
		GeneratedAt: time.Now(),
	}
}

// VerifyChecksum returns true if the parameters have not been tampered with.
func (s *DeterministicStrategy) VerifyChecksum() bool {
	return computeChecksum(s.Parameters) == s.Checksum
}

// ToMap serialises the strategy to a plain map for persistence.
func (s *DeterministicStrategy) ToMap() map[string]any {
	rules := make([]map[string]any, len(s.Rules))
	for i, r := range s.Rules {
		conds := make([]map[string]any, len(r.Conditions))
		for j, c := range r.Conditions {
			conds[j] = map[string]any{"field": c.Field, "op": c.Op, "value": c.Value}
		}
		rules[i] = map[string]any{
			"name":       r.Name,
			"direction":  string(r.Direction),
			"conditions": conds,
			"confidence": r.Confidence,
		}
	}
	return map[string]any{
		"strategy_id":  s.StrategyID,
		"node_id":      s.NodeID,
		"node_version": s.NodeVersion,
		"version":      s.Version,
		"parameters":   s.Parameters,
		"rules":        rules,
		"compiled_at":  s.CompiledAt.Unix(),
		"checksum":     s.Checksum,
	}
}

// ---------------------------------------------------------------------------
// StrategyRegistry
// ---------------------------------------------------------------------------

// StrategyRegistry stores all compiled strategies for each node, indexed by
// version number.
type StrategyRegistry struct {
	mu         sync.RWMutex
	strategies map[string]map[int]*DeterministicStrategy // nodeID → version → strategy
}

// NewStrategyRegistry creates an empty registry.
func NewStrategyRegistry() *StrategyRegistry {
	return &StrategyRegistry{
		strategies: make(map[string]map[int]*DeterministicStrategy),
	}
}

// Register adds a compiled strategy to the registry.
func (r *StrategyRegistry) Register(s *DeterministicStrategy) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.strategies[s.NodeID] == nil {
		r.strategies[s.NodeID] = make(map[int]*DeterministicStrategy)
	}
	r.strategies[s.NodeID][s.Version] = s
}

// Get retrieves a strategy by node ID and version; returns nil if not found.
func (r *StrategyRegistry) Get(nodeID string, version int) *DeterministicStrategy {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.strategies[nodeID][version]
}

// GetCurrent returns the highest-versioned strategy for a node.
func (r *StrategyRegistry) GetCurrent(nodeID string) *DeterministicStrategy {
	r.mu.RLock()
	defer r.mu.RUnlock()
	versions := r.strategies[nodeID]
	if len(versions) == 0 {
		return nil
	}
	latest := -1
	for v := range versions {
		if v > latest {
			latest = v
		}
	}
	return versions[latest]
}

// ListVersions returns sorted version numbers for a node.
func (r *StrategyRegistry) ListVersions(nodeID string) []int {
	r.mu.RLock()
	defer r.mu.RUnlock()
	versions := r.strategies[nodeID]
	out := make([]int, 0, len(versions))
	for v := range versions {
		out = append(out, v)
	}
	// insertion sort (version lists are short)
	for i := 1; i < len(out); i++ {
		for j := i; j > 0 && out[j] < out[j-1]; j-- {
			out[j], out[j-1] = out[j-1], out[j]
		}
	}
	return out
}

// NextVersion returns the next monotonically increasing version for a node.
func (r *StrategyRegistry) NextVersion(nodeID string) int {
	versions := r.ListVersions(nodeID)
	if len(versions) == 0 {
		return 1
	}
	return versions[len(versions)-1] + 1
}

// ---------------------------------------------------------------------------
// NodeSnapshot — what DeterministicCompiler reads from a node
// ---------------------------------------------------------------------------

// NodeSnapshot is the interface that nodes must implement so the compiler can
// extract parameters and rules without depending on any concrete node type.
type NodeSnapshot interface {
	// NodeID returns the node's unique identifier.
	NodeID() string
	// NodeVersion returns the node's current version string.
	NodeVersion() string
	// Parameters returns a deep copy of the node's current parameters.
	Parameters() map[string]any
	// Rules returns the node's explicit rules, or nil to trigger synthesis.
	Rules() []StrategyRule
}

// ---------------------------------------------------------------------------
// DeterministicCompiler
// ---------------------------------------------------------------------------

// DeterministicCompiler freezes a node's current parameters into a versioned
// DeterministicStrategy.  Each compilation is assigned a monotonically
// increasing version number.  Any previous version can be retrieved via
// Rollback().
type DeterministicCompiler struct {
	Registry *StrategyRegistry
}

// NewDeterministicCompiler creates a compiler with a fresh registry.
func NewDeterministicCompiler() *DeterministicCompiler {
	return &DeterministicCompiler{Registry: NewStrategyRegistry()}
}

// NewDeterministicCompilerWithRegistry creates a compiler using an existing registry.
func NewDeterministicCompilerWithRegistry(r *StrategyRegistry) *DeterministicCompiler {
	return &DeterministicCompiler{Registry: r}
}

// Compile freezes node's current state into a DeterministicStrategy, registers
// it, and returns the result.
func (c *DeterministicCompiler) Compile(node NodeSnapshot) *DeterministicStrategy {
	params := node.Parameters()
	rules := node.Rules()
	if len(rules) == 0 {
		rules = synthesiseRules(params)
	}

	version := c.Registry.NextVersion(node.NodeID())
	checksum := computeChecksum(params)

	s := &DeterministicStrategy{
		StrategyID:  uuid.New().String(),
		NodeID:      node.NodeID(),
		NodeVersion: node.NodeVersion(),
		Version:     version,
		Parameters:  params,
		Rules:       rules,
		CompiledAt:  time.Now(),
		Checksum:    checksum,
	}
	c.Registry.Register(s)
	slog.Info("compiled strategy",
		"node_id", s.NodeID,
		"version", s.Version,
		"rules", len(s.Rules),
		"checksum", s.Checksum[:8],
	)
	return s
}

// Rollback retrieves a previously compiled strategy by version.
// Returns nil if the version does not exist.  Does NOT apply the strategy to
// the node; callers must do that explicitly.
func (c *DeterministicCompiler) Rollback(nodeID string, version int) *DeterministicStrategy {
	return c.Registry.Get(nodeID, version)
}

// GetCurrent returns the most recently compiled strategy for a node.
func (c *DeterministicCompiler) GetCurrent(nodeID string) *DeterministicStrategy {
	return c.Registry.GetCurrent(nodeID)
}

// ---------------------------------------------------------------------------
// Rule synthesis
// ---------------------------------------------------------------------------

// synthesiseRules builds a rule set from well-known parameter keys when the
// node does not provide explicit rules.
func synthesiseRules(params map[string]any) []StrategyRule {
	var rules []StrategyRule

	// RSI-style rules
	if v, ok := floatParam(params, "rsi_oversold"); ok {
		rules = append(rules, StrategyRule{
			Name:       "rsi_oversold_long",
			Direction:  DirectionLong,
			Conditions: []RuleCondition{{Field: "rsi", Op: "<=", Value: v}},
			Confidence: 0.7,
		})
	}
	if v, ok := floatParam(params, "rsi_overbought"); ok {
		rules = append(rules, StrategyRule{
			Name:       "rsi_overbought_short",
			Direction:  DirectionShort,
			Conditions: []RuleCondition{{Field: "rsi", Op: ">=", Value: v}},
			Confidence: 0.7,
		})
	}

	// Generic threshold rules
	sigConf, _ := floatParamDefault(params, "signal_confidence", 0.6)
	if v, ok := floatParam(params, "signal_threshold_long"); ok {
		rules = append(rules, StrategyRule{
			Name:       "signal_long",
			Direction:  DirectionLong,
			Conditions: []RuleCondition{{Field: "signal", Op: ">=", Value: v}},
			Confidence: sigConf,
		})
	}
	if v, ok := floatParam(params, "signal_threshold_short"); ok {
		rules = append(rules, StrategyRule{
			Name:       "signal_short",
			Direction:  DirectionShort,
			Conditions: []RuleCondition{{Field: "signal", Op: "<=", Value: v}},
			Confidence: sigConf,
		})
	}

	return rules
}

func floatParam(params map[string]any, key string) (float64, bool) {
	v, ok := params[key]
	if !ok {
		return 0, false
	}
	switch f := v.(type) {
	case float64:
		return f, true
	case float32:
		return float64(f), true
	case int:
		return float64(f), true
	}
	return 0, false
}

func floatParamDefault(params map[string]any, key string, def float64) (float64, bool) {
	if v, ok := floatParam(params, key); ok {
		return v, true
	}
	return def, false
}

// ---------------------------------------------------------------------------
// Checksum
// ---------------------------------------------------------------------------

func computeChecksum(params map[string]any) string {
	b, err := json.Marshal(sortedMap(params))
	if err != nil {
		return ""
	}
	sum := sha256.Sum256(b)
	return fmt.Sprintf("%x", sum)
}

// sortedMap produces a deterministic JSON representation of an arbitrary map.
func sortedMap(m map[string]any) map[string]any {
	// json.Marshal already sorts map keys, so just return m.
	// Nested maps are handled by encoding/json's natural key sorting.
	return m
}

// ---------------------------------------------------------------------------
// ValidationError (shared with memory_consolidation.go)
// ---------------------------------------------------------------------------

// ValidationError is returned when configuration parameters fail validation.
type ValidationError struct {
	Field   string
	Message string
}

func (e *ValidationError) Error() string {
	return fmt.Sprintf("validation error: field %q — %s", e.Field, e.Message)
}
