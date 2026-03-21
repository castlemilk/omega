package core

import (
	"context"
	"testing"
	"time"

	adversarialpkg "github.com/benebsworth/omega/internal/adversarial"
)

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

// newFullCycleOrch returns a basic Orchestrator wired for full-cycle tests.
func newFullCycleOrch(t *testing.T) *Orchestrator {
	t.Helper()
	orch, _ := newOrch(t)
	return orch
}

// newSafeEnvelope returns a lenient SafetyEnvelope that passes typical test inputs.
func newSafeEnvelope() *SafetyEnvelope {
	return NewSafetyEnvelope(0.9, 0.9, 0.99, 10.0)
}

// newAdversarialAll returns an AdversarialPressure with all three rings active.
func newAdversarialAll(threshold float64) *AdversarialPressure {
	return NewAdversarialPressure(threshold, 5, []int{1, 2, 3})
}

// newDebateGate returns a default DebateGate for testing.
func newDebateGate() *adversarialpkg.DebateGate {
	return adversarialpkg.NewDebateGate(
		&adversarialpkg.BullCaseBuilder{},
		&adversarialpkg.BearCaseBuilder{},
		&adversarialpkg.Judge{},
	)
}

// tripCircuit records enough failures on orch's circuit manager to open the
// breaker for nodeID.  Uses FailureThreshold=3 from newOrch defaults.
func tripCircuit(orch *Orchestrator, nodeID string) {
	for i := 0; i < 5; i++ {
		orch.circuit.RecordFailure(nodeID)
	}
}

// setNextCycleID sets the orchestrator's cycleCounter so that the next call
// to nextCycleID returns target.
func setNextCycleID(orch *Orchestrator, target int64) {
	orch.mu.Lock()
	orch.cycleCounter = target - 1
	orch.mu.Unlock()
}

// ---------------------------------------------------------------------------
// Test 1: Happy path — 3 nodes all pass
// ---------------------------------------------------------------------------

func TestRunFullCycle_HappyPath(t *testing.T) {
	orch := newFullCycleOrch(t)
	kern := mustKernel(t)
	autonomy := NewAutonomyManager()

	nodes := []*stubNode{
		{id: "node-a"},
		{id: "node-b"},
		{id: "node-c"},
	}
	for _, n := range nodes {
		orch.Register(n)
	}

	cfg := FullCycleConfig{
		Safety:      newSafeEnvelope(),
		Adversarial: newAdversarialAll(0.5),
		Memory:      kern,
		Autonomy:    autonomy,
		NodeContextProvider: func(nodeID string) NodeCycleContext {
			return NodeCycleContext{
				Portfolio: map[string]float64{"BTC": 0.3, "ETH": 0.3, "SOL": 0.4},
				Drawdown:  0.05,
				Signals:   map[string]float64{"signal": 0.6},
			}
		},
	}

	report, err := orch.RunFullCycle(context.Background(), cfg)
	if err != nil {
		t.Fatalf("RunFullCycle: %v", err)
	}

	// All 3 nodes should have executed.
	if report.Summary.TotalNodes != 3 {
		t.Errorf("TotalNodes = %d, want 3", report.Summary.TotalNodes)
	}
	if report.Summary.Passed != 3 {
		t.Errorf("Passed = %d, want 3", report.Summary.Passed)
	}
	if report.Summary.Failed != 0 {
		t.Errorf("Failed = %d, want 0", report.Summary.Failed)
	}
	if report.Summary.Skipped != 0 {
		t.Errorf("Skipped = %d, want 0", report.Summary.Skipped)
	}

	// No safety violations.
	if len(report.SafetyViolations) != 0 {
		t.Errorf("SafetyViolations = %v, want empty", report.SafetyViolations)
	}

	// Each node report exists and executed.
	for _, n := range nodes {
		nr, ok := report.PerNode[n.id]
		if !ok {
			t.Errorf("missing PerNodeReport for %s", n.id)
			continue
		}
		if !nr.Executed {
			t.Errorf("node %s: Executed = false, want true", n.id)
		}
		if nr.Skipped {
			t.Errorf("node %s: Skipped = true, want false", n.id)
		}
		if !nr.SafetyPassed {
			t.Errorf("node %s: SafetyPassed = false, want true", n.id)
		}
		if nr.ExecutionErr != "" {
			t.Errorf("node %s: unexpected ExecutionErr = %q", n.id, nr.ExecutionErr)
		}
	}

	// Each node executed exactly once.
	for _, n := range nodes {
		if got := n.calls.Load(); got != 1 {
			t.Errorf("node %s: calls = %d, want 1", n.id, got)
		}
	}
}

// ---------------------------------------------------------------------------
// Test 2: Mixed — safety violation, pass, circuit open skip
// ---------------------------------------------------------------------------

func TestRunFullCycle_Mixed(t *testing.T) {
	orch := newFullCycleOrch(t)
	kern := mustKernel(t)
	autonomy := NewAutonomyManager()

	nodePass := &stubNode{id: "node-pass"}
	nodeFail := &stubNode{id: "node-safety-fail"}  // safety violated via NodeContextProvider
	nodeSkip := &stubNode{id: "node-circuit-open"} // circuit will be opened before cycle

	orch.Register(nodePass)
	orch.Register(nodeFail)
	orch.Register(nodeSkip)

	// Pre-open the circuit for nodeSkip.
	tripCircuit(orch, nodeSkip.id)

	// Tight safety envelope: max 25% per asset.
	tightSafety := NewSafetyEnvelope(0.25, 0.50, 0.99, 10.0)

	cfg := FullCycleConfig{
		Safety:      tightSafety,
		Adversarial: newAdversarialAll(0.5),
		Memory:      kern,
		Autonomy:    autonomy,
		NodeContextProvider: func(nodeID string) NodeCycleContext {
			if nodeID == nodeFail.id {
				// 80% BTC concentration violates max 25% — safety should flag.
				return NodeCycleContext{
					Portfolio: map[string]float64{"BTC": 0.80, "ETH": 0.20},
					Drawdown:  0.05,
				}
			}
			// Equal-weight 4-asset portfolio: each 25% — exactly at limit, not over.
			return NodeCycleContext{
				Portfolio: map[string]float64{"BTC": 0.25, "ETH": 0.25, "SOL": 0.25, "ADA": 0.25},
				Drawdown:  0.05,
			}
		},
	}

	report, err := orch.RunFullCycle(context.Background(), cfg)
	if err != nil {
		t.Fatalf("RunFullCycle: %v", err)
	}

	// Summary totals.
	if report.Summary.TotalNodes != 3 {
		t.Errorf("TotalNodes = %d, want 3", report.Summary.TotalNodes)
	}

	// node-pass: executed, safety ok.
	nrPass := report.PerNode[nodePass.id]
	if nrPass == nil {
		t.Fatal("missing PerNodeReport for node-pass")
	}
	if !nrPass.Executed {
		t.Errorf("node-pass: Executed = false")
	}
	if !nrPass.SafetyPassed {
		t.Errorf("node-pass: SafetyPassed = false")
	}

	// node-safety-fail: executed (safety violation doesn't block execution), safety not ok.
	nrFail := report.PerNode[nodeFail.id]
	if nrFail == nil {
		t.Fatal("missing PerNodeReport for node-safety-fail")
	}
	if nrFail.SafetyPassed {
		t.Errorf("node-safety-fail: SafetyPassed = true, want false (BTC 80%% exceeds 25%% limit)")
	}
	if len(nrFail.SafetyViolations) == 0 {
		t.Errorf("node-safety-fail: SafetyViolations empty, want ≥1")
	}

	// node-circuit-open: skipped.
	nrSkip := report.PerNode[nodeSkip.id]
	if nrSkip == nil {
		t.Fatal("missing PerNodeReport for node-circuit-open")
	}
	if !nrSkip.Skipped {
		t.Errorf("node-circuit-open: Skipped = false, want true")
	}
	if nodeSkip.calls.Load() != 0 {
		t.Errorf("node-circuit-open: Execute called %d time(s), want 0", nodeSkip.calls.Load())
	}

	// Safety violations aggregated.
	if len(report.SafetyViolations) == 0 {
		t.Errorf("SafetyViolations empty, want ≥1 from node-safety-fail")
	}

	// Skipped should be counted.
	if report.Summary.Skipped != 1 {
		t.Errorf("Skipped = %d, want 1", report.Summary.Skipped)
	}
}

// ---------------------------------------------------------------------------
// Test 3: Adversarial escalation — Ring 1 high disagreement → Ring 2+3 cascade
// ---------------------------------------------------------------------------

func TestRunFullCycle_AdversarialEscalation(t *testing.T) {
	orch := newFullCycleOrch(t)
	kern := mustKernel(t)

	node := &stubNode{id: "node-adversarial"}
	orch.Register(node)

	// Set cycleID to 49 so that next cycle is 50 (divisible by Ring2Interval=10
	// and Ring3Interval=50) to trigger both Ring 2 and Ring 3.
	setNextCycleID(orch, 50)

	// Low threshold so Ring 1 fires easily.
	adversarial := newAdversarialAll(0.1)

	// Provide a fitness function so Ring 3 has something to evaluate.
	fitnessFn := func(params map[string]any) float64 {
		return 0.7
	}

	// Seed Ring 3 population so it doesn't skip.
	adversarial.Ring3.InitialisePopulation(map[string]any{
		"signal_threshold_long": 0.5,
		"rsi_threshold":         30.0,
	})

	// VariantOutputs with high disagreement: variant A is all +1, variant B is all -1.
	highDisagreementOutputs := map[string]map[string]float64{
		"variant-bull": {"signal": 1.0, "momentum": 0.9},
		"variant-bear": {"signal": -1.0, "momentum": -0.9},
	}

	cfg := FullCycleConfig{
		Safety:      newSafeEnvelope(),
		Adversarial: adversarial,
		Memory:      kern,
		NodeContextProvider: func(nodeID string) NodeCycleContext {
			return NodeCycleContext{
				Signals:        map[string]float64{"signal": 0.5},
				StrategyParams: map[string]any{"rsi_threshold": 30.0},
				VariantOutputs: highDisagreementOutputs,
				FitnessFunc:    fitnessFn,
			}
		},
	}

	report, err := orch.RunFullCycle(context.Background(), cfg)
	if err != nil {
		t.Fatalf("RunFullCycle: %v", err)
	}

	nr := report.PerNode[node.id]
	if nr == nil {
		t.Fatal("missing PerNodeReport for node-adversarial")
	}

	// Ring 1 should have flagged due to high disagreement.
	if !nr.AdversarialFlagged {
		t.Errorf("AdversarialFlagged = false, want true (max_disagreement = %.3f)", nr.AdversarialScore)
	}
	if nr.AdversarialScore <= 0.1 {
		t.Errorf("AdversarialScore = %.3f, want > 0.1", nr.AdversarialScore)
	}

	// Ring 2 should have fired (cycle 50 % 10 == 0).
	if !nr.Ring2Triggered {
		t.Errorf("Ring2Triggered = false at cycle 50, want true")
	}

	// Ring 3 should have fired (cycle 50 % 50 == 0).
	if !nr.Ring3Triggered {
		t.Errorf("Ring3Triggered = false at cycle 50, want true")
	}

	// AdversarialAlerts should contain an entry for this node.
	if len(report.AdversarialAlerts) == 0 {
		t.Errorf("AdversarialAlerts empty, want ≥1")
	}
	found := false
	for _, alert := range report.AdversarialAlerts {
		if alert.NodeID == node.id {
			found = true
			if !alert.Ring2Triggered {
				t.Errorf("alert.Ring2Triggered = false")
			}
			if !alert.Ring3Triggered {
				t.Errorf("alert.Ring3Triggered = false")
			}
		}
	}
	if !found {
		t.Errorf("no AdversarialAlert found for node %s", node.id)
	}
}

// ---------------------------------------------------------------------------
// Test 4: Improvement triggers during cycle
// ---------------------------------------------------------------------------

func TestRunFullCycle_ImprovementTriggers(t *testing.T) {
	orch := newFullCycleOrch(t)
	kern := mustKernel(t)
	autonomy := NewAutonomyManager()

	nodeID := "node-improve"
	node := &stubNode{id: nodeID}
	orch.Register(node)

	// Set up ImprovementEngine with scheduler that immediately marks node as due.
	sched := NewImprovementScheduler(nil)
	reg := NewStrategyRegistry()
	compiler := NewDeterministicCompiler()

	// Register an initial strategy so BuildSnapshot finds it.
	initialStrategy := &DeterministicStrategy{
		StrategyID:  "initial",
		NodeID:      nodeID,
		NodeVersion: "v1",
		Version:     1,
		Parameters:  map[string]any{"rsi_threshold": 30.0, "signal_threshold_long": 0.5},
		Rules:       []StrategyRule{},
	}
	reg.Register(initialStrategy)

	// Register in scheduler and mark immediately due.
	sched.Register(nodeID, nil, true)

	var triggered bool
	emitter := &testEmitter{onTriggered: func(id string, _ int) {
		if id == nodeID {
			triggered = true
		}
	}}

	engine := NewImprovementEngine(sched, reg, compiler, kern, emitter)

	cfg := FullCycleConfig{
		Safety:      newSafeEnvelope(),
		Adversarial: newAdversarialAll(0.5),
		Memory:      kern,
		Autonomy:    autonomy,
		Improvement: engine,
		NodeContextProvider: func(string) NodeCycleContext {
			return NodeCycleContext{
				Portfolio: map[string]float64{"BTC": 0.5, "ETH": 0.5},
				Drawdown:  0.02,
			}
		},
	}

	report, err := orch.RunFullCycle(context.Background(), cfg)
	if err != nil {
		t.Fatalf("RunFullCycle: %v", err)
	}

	// Node should have executed.
	nr := report.PerNode[nodeID]
	if nr == nil {
		t.Fatal("missing PerNodeReport")
	}
	if !nr.Executed {
		t.Errorf("node: Executed = false")
	}

	// Improvement engine should have been triggered for the due node.
	if !triggered {
		t.Errorf("improvement engine was not triggered for %s", nodeID)
	}
}

// ---------------------------------------------------------------------------
// Test 5: DebateGate invoked when domain supports it
// ---------------------------------------------------------------------------

func TestRunFullCycle_DebateGate(t *testing.T) {
	orch := newFullCycleOrch(t)
	kern := mustKernel(t)

	node := &stubNode{id: "node-debate"}
	orch.Register(node)

	debateGate := newDebateGate()

	cfg := FullCycleConfig{
		Safety:      newSafeEnvelope(),
		Adversarial: newAdversarialAll(0.5),
		Memory:      kern,
		DebateGate:  debateGate,
		NodeContextProvider: func(string) NodeCycleContext {
			return NodeCycleContext{
				DomainSupportsDebate: true,
				SignalCtx: adversarialpkg.SignalContext{
					CompositeSignal: 0.7,
					ICShort:         0.15,
					ICLong:          0.10,
					VolRegime:       "normal_vol",
					RecentSharpe:    1.2,
					RSI:             45,
				},
			}
		},
	}

	report, err := orch.RunFullCycle(context.Background(), cfg)
	if err != nil {
		t.Fatalf("RunFullCycle: %v", err)
	}

	nr := report.PerNode[node.id]
	if nr == nil {
		t.Fatal("missing PerNodeReport")
	}
	// DebateVerdict should be one of BUY / SELL / HOLD.
	if nr.DebateVerdict == "" {
		t.Errorf("DebateVerdict empty — debate gate was not invoked")
	}
	valid := nr.DebateVerdict == "BUY" || nr.DebateVerdict == "SELL" || nr.DebateVerdict == "HOLD"
	if !valid {
		t.Errorf("unexpected DebateVerdict = %q", nr.DebateVerdict)
	}
}

// ---------------------------------------------------------------------------
// Test 6: No subsystems set — bare orchestrator still runs
// ---------------------------------------------------------------------------

func TestRunFullCycle_NilSubsystems(t *testing.T) {
	orch := newFullCycleOrch(t)
	node := &stubNode{id: "node-bare"}
	orch.Register(node)

	report, err := orch.RunFullCycle(context.Background(), FullCycleConfig{})
	if err != nil {
		t.Fatalf("RunFullCycle with nil subsystems: %v", err)
	}
	if report.Summary.Passed != 1 {
		t.Errorf("Passed = %d, want 1", report.Summary.Passed)
	}
}

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

// testEmitter is a trivial ImprovementEventEmitter for tests.
type testEmitter struct {
	onTriggered func(nodeID string, version int)
	onChanged   func(nodeID string, from, to int, improvement float64)
}

func (e *testEmitter) OnImprovementTriggered(nodeID string, version int) {
	if e.onTriggered != nil {
		e.onTriggered(nodeID, version)
	}
}

func (e *testEmitter) OnStrategyChanged(nodeID string, from, to int, improvement float64) {
	if e.onChanged != nil {
		e.onChanged(nodeID, from, to, improvement)
	}
}

// Ensure testEmitter satisfies ImprovementEventEmitter at compile time.
var _ ImprovementEventEmitter = (*testEmitter)(nil)

// Ensure full_cycle types are accessible from tests.
var _ time.Duration = 0 // keep time import used
