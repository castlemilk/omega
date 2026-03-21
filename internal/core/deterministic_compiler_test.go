package core

import (
	"testing"
)

// ---------------------------------------------------------------------------
// Signal
// ---------------------------------------------------------------------------

func TestSignal_IsActionable(t *testing.T) {
	tests := []struct {
		name          string
		signal        Signal
		minConfidence float64
		want          bool
	}{
		{"flat is never actionable", Signal{Direction: DirectionFlat, Confidence: 0.9}, 0.5, false},
		{"long with high confidence", Signal{Direction: DirectionLong, Confidence: 0.8}, 0.5, true},
		{"long below threshold", Signal{Direction: DirectionLong, Confidence: 0.3}, 0.5, false},
		{"short exactly at threshold", Signal{Direction: DirectionShort, Confidence: 0.5}, 0.5, true},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := tc.signal.IsActionable(tc.minConfidence); got != tc.want {
				t.Errorf("IsActionable(%f) = %v, want %v", tc.minConfidence, got, tc.want)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// DeterministicStrategy.Execute
// ---------------------------------------------------------------------------

type testRule struct {
	name      string
	direction SignalDirection
	field     string
	op        string
	value     float64
	conf      float64
}

func buildStrategy(rules []testRule) *DeterministicStrategy {
	sr := make([]StrategyRule, len(rules))
	for i, r := range rules {
		sr[i] = StrategyRule{
			Name:       r.name,
			Direction:  r.direction,
			Conditions: []RuleCondition{{Field: r.field, Op: r.op, Value: r.value}},
			Confidence: r.conf,
		}
	}
	return &DeterministicStrategy{
		StrategyID: "test-strategy",
		NodeID:     "test-node",
		Version:    1,
		Rules:      sr,
	}
}

func TestStrategy_Execute_FiresFirstMatchingRule(t *testing.T) {
	s := buildStrategy([]testRule{
		{"rsi_long", DirectionLong, "rsi", "<=", 30, 0.8},
		{"rsi_short", DirectionShort, "rsi", ">=", 70, 0.8},
	})

	sig := s.Execute(map[string]any{"rsi": 25.0})
	if sig.Direction != DirectionLong {
		t.Errorf("expected LONG, got %s", sig.Direction)
	}
	if sig.Confidence != 0.8 {
		t.Errorf("expected confidence 0.8, got %f", sig.Confidence)
	}
}

func TestStrategy_Execute_NoRuleFired_ReturnsFlat(t *testing.T) {
	s := buildStrategy([]testRule{
		{"signal_long", DirectionLong, "signal", ">=", 0.9, 0.7},
	})

	sig := s.Execute(map[string]any{"signal": 0.3})
	if sig.Direction != DirectionFlat {
		t.Errorf("expected FLAT, got %s", sig.Direction)
	}
}

func TestStrategy_Execute_DotNotationField(t *testing.T) {
	s := buildStrategy([]testRule{
		{"price_close_long", DirectionLong, "price.close", ">", 100.0, 0.6},
	})

	sig := s.Execute(map[string]any{"price": map[string]any{"close": 150.0}})
	if sig.Direction != DirectionLong {
		t.Errorf("expected LONG with dot-notation field, got %s", sig.Direction)
	}
}

func TestStrategy_Execute_MissingField_SkipsRule(t *testing.T) {
	s := buildStrategy([]testRule{
		{"missing_field", DirectionLong, "nonexistent.field", ">", 0.0, 0.9},
		{"fallback_long", DirectionLong, "rsi", "<=", 30.0, 0.5},
	})

	sig := s.Execute(map[string]any{"rsi": 20.0})
	if sig.Direction != DirectionLong || sig.Confidence != 0.5 {
		t.Errorf("expected fallback rule to fire: dir=%s conf=%f", sig.Direction, sig.Confidence)
	}
}

func TestStrategy_Execute_AllOps(t *testing.T) {
	tests := []struct {
		op       string
		fieldVal float64
		ruleVal  float64
		wantFire bool
	}{
		{">", 5, 3, true},
		{">", 3, 5, false},
		{"<", 3, 5, true},
		{">=", 5, 5, true},
		{"<=", 5, 5, true},
		{"==", 5, 5, true},
		{"!=", 4, 5, true},
	}
	for _, tc := range tests {
		s := buildStrategy([]testRule{
			{"rule", DirectionLong, "v", tc.op, tc.ruleVal, 0.9},
		})
		sig := s.Execute(map[string]any{"v": tc.fieldVal})
		fired := sig.Direction == DirectionLong
		if fired != tc.wantFire {
			t.Errorf("op=%s fieldVal=%f ruleVal=%f: fired=%v want=%v", tc.op, tc.fieldVal, tc.ruleVal, fired, tc.wantFire)
		}
	}
}

// ---------------------------------------------------------------------------
// DeterministicStrategy checksum
// ---------------------------------------------------------------------------

func TestStrategy_Checksum(t *testing.T) {
	params := map[string]any{"rsi_oversold": 30.0, "rsi_overbought": 70.0}
	checksum := computeChecksum(params)
	if checksum == "" {
		t.Fatal("expected non-empty checksum")
	}

	s := &DeterministicStrategy{Parameters: params, Checksum: checksum}
	if !s.VerifyChecksum() {
		t.Fatal("expected checksum to verify")
	}

	s.Parameters["tampered"] = true
	if s.VerifyChecksum() {
		t.Fatal("expected checksum to fail after tampering")
	}
}

// ---------------------------------------------------------------------------
// StrategyRegistry
// ---------------------------------------------------------------------------

func TestStrategyRegistry_RegisterAndGet(t *testing.T) {
	r := NewStrategyRegistry()
	s := &DeterministicStrategy{StrategyID: "s1", NodeID: "node-a", Version: 1}
	r.Register(s)

	got := r.Get("node-a", 1)
	if got == nil || got.StrategyID != "s1" {
		t.Fatalf("expected to retrieve registered strategy, got %v", got)
	}
}

func TestStrategyRegistry_GetCurrent(t *testing.T) {
	r := NewStrategyRegistry()
	r.Register(&DeterministicStrategy{NodeID: "n", Version: 1})
	r.Register(&DeterministicStrategy{NodeID: "n", Version: 3})
	r.Register(&DeterministicStrategy{NodeID: "n", Version: 2})

	cur := r.GetCurrent("n")
	if cur == nil || cur.Version != 3 {
		t.Fatalf("expected version 3, got %v", cur)
	}
}

func TestStrategyRegistry_ListVersions(t *testing.T) {
	r := NewStrategyRegistry()
	r.Register(&DeterministicStrategy{NodeID: "n", Version: 2})
	r.Register(&DeterministicStrategy{NodeID: "n", Version: 1})
	r.Register(&DeterministicStrategy{NodeID: "n", Version: 3})

	versions := r.ListVersions("n")
	if len(versions) != 3 || versions[0] != 1 || versions[2] != 3 {
		t.Errorf("expected sorted [1,2,3], got %v", versions)
	}
}

func TestStrategyRegistry_NextVersion_Empty(t *testing.T) {
	r := NewStrategyRegistry()
	if r.NextVersion("unknown") != 1 {
		t.Error("expected first version to be 1")
	}
}

func TestStrategyRegistry_NextVersion_Increments(t *testing.T) {
	r := NewStrategyRegistry()
	r.Register(&DeterministicStrategy{NodeID: "n", Version: 5})
	if r.NextVersion("n") != 6 {
		t.Error("expected next version to be 6")
	}
}

// ---------------------------------------------------------------------------
// DeterministicCompiler
// ---------------------------------------------------------------------------

// testNode implements NodeSnapshot for use in tests.
type testNode struct {
	nodeID      string
	nodeVersion string
	params      map[string]any
	rules       []StrategyRule
}

func (n *testNode) NodeID() string             { return n.nodeID }
func (n *testNode) NodeVersion() string        { return n.nodeVersion }
func (n *testNode) Parameters() map[string]any { return n.params }
func (n *testNode) Rules() []StrategyRule      { return n.rules }

func TestCompiler_Compile_AssignsVersion(t *testing.T) {
	c := NewDeterministicCompiler()
	node := &testNode{nodeID: "my-node", nodeVersion: "v1.0", params: map[string]any{"rsi_oversold": 30.0}}
	s1 := c.Compile(node)
	s2 := c.Compile(node)

	if s1.Version != 1 {
		t.Errorf("expected version 1, got %d", s1.Version)
	}
	if s2.Version != 2 {
		t.Errorf("expected version 2, got %d", s2.Version)
	}
}

func TestCompiler_Compile_SetsChecksum(t *testing.T) {
	c := NewDeterministicCompiler()
	node := &testNode{nodeID: "n", nodeVersion: "v1", params: map[string]any{"threshold": 0.5}}
	s := c.Compile(node)
	if s.Checksum == "" {
		t.Fatal("expected non-empty checksum")
	}
	if !s.VerifyChecksum() {
		t.Fatal("checksum should verify immediately after compile")
	}
}

func TestCompiler_Compile_SynthesisesRulesFromParams(t *testing.T) {
	c := NewDeterministicCompiler()
	node := &testNode{
		nodeID:      "rsi-node",
		nodeVersion: "v1",
		params:      map[string]any{"rsi_oversold": 30.0, "rsi_overbought": 70.0},
		rules:       nil, // no explicit rules — should be synthesised
	}
	s := c.Compile(node)
	if len(s.Rules) == 0 {
		t.Fatal("expected synthesised rules from RSI params")
	}

	// Should fire a LONG signal when RSI is oversold
	sig := s.Execute(map[string]any{"rsi": 25.0})
	if sig.Direction != DirectionLong {
		t.Errorf("expected LONG signal for oversold RSI, got %s", sig.Direction)
	}
}

func TestCompiler_Compile_UsesExplicitRules(t *testing.T) {
	c := NewDeterministicCompiler()
	explicit := []StrategyRule{
		{Name: "custom_long", Direction: DirectionLong, Conditions: []RuleCondition{{Field: "x", Op: ">", Value: 5}}, Confidence: 0.99},
	}
	node := &testNode{nodeID: "n", nodeVersion: "v1", params: map[string]any{}, rules: explicit}
	s := c.Compile(node)
	if len(s.Rules) != 1 || s.Rules[0].Name != "custom_long" {
		t.Fatal("expected explicit rules to be used without modification")
	}
}

func TestCompiler_Rollback(t *testing.T) {
	c := NewDeterministicCompiler()
	node := &testNode{nodeID: "n", nodeVersion: "v1", params: map[string]any{"v": 1.0}}
	c.Compile(node)
	node.params = map[string]any{"v": 2.0}
	c.Compile(node)

	old := c.Rollback("n", 1)
	if old == nil || old.Version != 1 {
		t.Fatalf("expected version 1 on rollback, got %v", old)
	}
	if old.Parameters["v"].(float64) != 1.0 {
		t.Error("rolled-back strategy should have original parameters")
	}
}

func TestCompiler_GetCurrent(t *testing.T) {
	c := NewDeterministicCompiler()
	node := &testNode{nodeID: "n", nodeVersion: "v1", params: map[string]any{}}
	c.Compile(node)
	c.Compile(node)
	cur := c.GetCurrent("n")
	if cur == nil || cur.Version != 2 {
		t.Fatalf("expected version 2 as current, got %v", cur)
	}
}

// ---------------------------------------------------------------------------
// ValidationError
// ---------------------------------------------------------------------------

func TestValidationError_Error(t *testing.T) {
	err := &ValidationError{Field: "foo", Message: "bar"}
	if err.Error() == "" {
		t.Fatal("expected non-empty error message")
	}
}
