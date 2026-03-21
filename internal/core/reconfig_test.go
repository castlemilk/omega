package core

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/framework"
	"github.com/benebsworth/omega/internal/observability"
)

// ---------------------------------------------------------------------------
// test helpers
// ---------------------------------------------------------------------------

func newReconfigFixture(t *testing.T) (*ReconfigEngine, *framework.EventBus, *Orchestrator) {
	t.Helper()
	logger := slog.Default()
	obs := observability.NewEventBus(logger)
	metrics := observability.NewMetrics()
	cfg := DefaultOrchestratorConfig()
	orch := NewOrchestrator(cfg, obs, metrics, nil, logger)

	fbus := framework.NewEventBus()
	registry := framework.NewPluginRegistry()
	engine := NewReconfigEngine(orch, registry, fbus)
	return engine, fbus, orch
}

func nodeConfigFor(id string) NodeConfig {
	return NodeConfig{
		NodeID:             id,
		NodeType:           "quant",
		StrategyID:         "momentum",
		Params:             map[string]interface{}{"window": "20"},
		AutonomyThresholds: DefaultAutonomyThresholds(),
	}
}

// ---------------------------------------------------------------------------
// AddNode
// ---------------------------------------------------------------------------

func TestReconfigEngine_AddNode_Success(t *testing.T) {
	engine, bus, _ := newReconfigFixture(t)

	// Subscribe before adding so we don't miss the event.
	evCh := make(chan framework.Event, 4)
	id := bus.Subscribe(TopicNodeAdded, func(e framework.Event) {
		evCh <- e
	})
	defer bus.Unsubscribe(TopicNodeAdded, id)

	if err := engine.AddNode(nodeConfigFor("alpha")); err != nil {
		t.Fatalf("AddNode: %v", err)
	}

	if _, ok := engine.Nodes()["alpha"]; !ok {
		t.Fatal("node 'alpha' should be tracked after AddNode")
	}
	if engine.NodeCount() != 1 {
		t.Errorf("NodeCount: got %d want 1", engine.NodeCount())
	}

	select {
	case ev := <-evCh:
		p := ev.Payload.(ReconfigEvent)
		if p.NodeID != "alpha" {
			t.Errorf("event NodeID: got %q want 'alpha'", p.NodeID)
		}
	case <-time.After(100 * time.Millisecond):
		t.Fatal("timeout waiting for NodeAdded event")
	}
}

func TestReconfigEngine_AddNode_Duplicate(t *testing.T) {
	engine, _, _ := newReconfigFixture(t)
	if err := engine.AddNode(nodeConfigFor("beta")); err != nil {
		t.Fatalf("first AddNode: %v", err)
	}
	if err := engine.AddNode(nodeConfigFor("beta")); err == nil {
		t.Fatal("expected error for duplicate AddNode")
	}
}

func TestReconfigEngine_AddNode_EmptyID(t *testing.T) {
	engine, _, _ := newReconfigFixture(t)
	if err := engine.AddNode(NodeConfig{}); err == nil {
		t.Fatal("expected error for empty NodeID")
	}
}

// ---------------------------------------------------------------------------
// RemoveNode
// ---------------------------------------------------------------------------

func TestReconfigEngine_RemoveNode_Success(t *testing.T) {
	engine, bus, _ := newReconfigFixture(t)

	evCh := make(chan framework.Event, 4)
	id := bus.Subscribe(TopicNodeRemoved, func(e framework.Event) { evCh <- e })
	defer bus.Unsubscribe(TopicNodeRemoved, id)

	if err := engine.AddNode(nodeConfigFor("gamma")); err != nil {
		t.Fatalf("AddNode: %v", err)
	}
	if err := engine.RemoveNode("gamma"); err != nil {
		t.Fatalf("RemoveNode: %v", err)
	}

	if _, ok := engine.Nodes()["gamma"]; ok {
		t.Fatal("node 'gamma' should have been removed")
	}
	if engine.NodeCount() != 0 {
		t.Errorf("NodeCount: got %d want 0", engine.NodeCount())
	}

	select {
	case ev := <-evCh:
		p := ev.Payload.(ReconfigEvent)
		if p.NodeID != "gamma" {
			t.Errorf("event NodeID: got %q want 'gamma'", p.NodeID)
		}
	case <-time.After(100 * time.Millisecond):
		t.Fatal("timeout waiting for NodeRemoved event")
	}
}

func TestReconfigEngine_RemoveNode_NotFound(t *testing.T) {
	engine, _, _ := newReconfigFixture(t)
	if err := engine.RemoveNode("nonexistent"); err == nil {
		t.Fatal("expected error removing nonexistent node")
	}
}

// ---------------------------------------------------------------------------
// UpdateNodeConfig
// ---------------------------------------------------------------------------

func TestReconfigEngine_UpdateNodeConfig_MergesPatch(t *testing.T) {
	engine, _, _ := newReconfigFixture(t)

	if err := engine.AddNode(nodeConfigFor("delta")); err != nil {
		t.Fatalf("AddNode: %v", err)
	}

	patch := map[string]interface{}{"window": "40", "lookback": "5"}
	if err := engine.UpdateNodeConfig("delta", patch); err != nil {
		t.Fatalf("UpdateNodeConfig: %v", err)
	}

	updated := engine.Nodes()["delta"]
	if updated.Params["window"] != "40" {
		t.Errorf("window: got %v want 40", updated.Params["window"])
	}
	if updated.Params["lookback"] != "5" {
		t.Errorf("lookback: got %v want 5", updated.Params["lookback"])
	}
}

func TestReconfigEngine_UpdateNodeConfig_NilValueRemovesKey(t *testing.T) {
	engine, _, _ := newReconfigFixture(t)

	if err := engine.AddNode(nodeConfigFor("epsilon")); err != nil {
		t.Fatalf("AddNode: %v", err)
	}

	if err := engine.UpdateNodeConfig("epsilon", map[string]interface{}{"window": nil}); err != nil {
		t.Fatalf("UpdateNodeConfig: %v", err)
	}

	if _, ok := engine.Nodes()["epsilon"].Params["window"]; ok {
		t.Error("'window' key should have been removed")
	}
}

func TestReconfigEngine_UpdateNodeConfig_NotFound(t *testing.T) {
	engine, _, _ := newReconfigFixture(t)
	if err := engine.UpdateNodeConfig("ghost", map[string]interface{}{"x": "1"}); err == nil {
		t.Fatal("expected error for unknown node")
	}
}

// ---------------------------------------------------------------------------
// SwapStrategy
// ---------------------------------------------------------------------------

func TestReconfigEngine_SwapStrategy_Success(t *testing.T) {
	engine, bus, _ := newReconfigFixture(t)

	evCh := make(chan framework.Event, 4)
	id := bus.Subscribe(TopicStrategySwapped, func(e framework.Event) { evCh <- e })
	defer bus.Unsubscribe(TopicStrategySwapped, id)

	if err := engine.AddNode(nodeConfigFor("zeta")); err != nil {
		t.Fatalf("AddNode: %v", err)
	}
	if err := engine.SwapStrategy("zeta", "mean_reversion"); err != nil {
		t.Fatalf("SwapStrategy: %v", err)
	}

	if engine.Nodes()["zeta"].StrategyID != "mean_reversion" {
		t.Errorf("strategy: got %q want mean_reversion", engine.Nodes()["zeta"].StrategyID)
	}

	select {
	case ev := <-evCh:
		p := ev.Payload.(ReconfigEvent)
		if p.Details["old_strategy"] != "momentum" {
			t.Errorf("old_strategy: got %v want momentum", p.Details["old_strategy"])
		}
		if p.Details["new_strategy"] != "mean_reversion" {
			t.Errorf("new_strategy: got %v want mean_reversion", p.Details["new_strategy"])
		}
	case <-time.After(100 * time.Millisecond):
		t.Fatal("timeout waiting for StrategySwapped event")
	}
}

func TestReconfigEngine_SwapStrategy_EmptyID(t *testing.T) {
	engine, _, _ := newReconfigFixture(t)
	_ = engine.AddNode(nodeConfigFor("eta"))
	if err := engine.SwapStrategy("eta", ""); err == nil {
		t.Fatal("expected error for empty strategy ID")
	}
}

func TestReconfigEngine_SwapStrategy_NotFound(t *testing.T) {
	engine, _, _ := newReconfigFixture(t)
	if err := engine.SwapStrategy("unknown", "momentum"); err == nil {
		t.Fatal("expected error for unknown node")
	}
}

// ---------------------------------------------------------------------------
// ReconfigureAutonomy
// ---------------------------------------------------------------------------

func TestReconfigEngine_ReconfigureAutonomy_Success(t *testing.T) {
	engine, bus, _ := newReconfigFixture(t)

	evCh := make(chan framework.Event, 4)
	id := bus.Subscribe(TopicAutonomyReconfigured, func(e framework.Event) { evCh <- e })
	defer bus.Unsubscribe(TopicAutonomyReconfigured, id)

	if err := engine.AddNode(nodeConfigFor("theta")); err != nil {
		t.Fatalf("AddNode: %v", err)
	}

	newT := AutonomyThresholds{
		MinCyclesForPromotion:  20,
		MinSharpeForPromotion:  1.0,
		MaxDrawdownForDemotion: 0.05,
		ConfidenceFloor:        0.8,
	}
	if err := engine.ReconfigureAutonomy("theta", newT); err != nil {
		t.Fatalf("ReconfigureAutonomy: %v", err)
	}

	got := engine.Nodes()["theta"].AutonomyThresholds
	if got.MinCyclesForPromotion != 20 {
		t.Errorf("MinCycles: got %d want 20", got.MinCyclesForPromotion)
	}
	if got.ConfidenceFloor != 0.8 {
		t.Errorf("ConfidenceFloor: got %f want 0.8", got.ConfidenceFloor)
	}

	select {
	case <-evCh:
	case <-time.After(100 * time.Millisecond):
		t.Fatal("timeout waiting for AutonomyReconfigured event")
	}
}

// ---------------------------------------------------------------------------
// Concurrent safety
// ---------------------------------------------------------------------------

func TestReconfigEngine_ConcurrentOperations(t *testing.T) {
	engine, _, _ := newReconfigFixture(t)

	const n = 20
	var wg sync.WaitGroup

	for i := 0; i < n; i++ {
		wg.Add(1)
		id := fmt.Sprintf("node-%d", i)
		go func() {
			defer wg.Done()
			_ = engine.AddNode(NodeConfig{
				NodeID:     id,
				NodeType:   "quant",
				StrategyID: "momentum",
			})
		}()
	}
	wg.Wait()

	if engine.NodeCount() != n {
		t.Errorf("expected %d nodes, got %d", n, engine.NodeCount())
	}

	for i := 0; i < n; i++ {
		wg.Add(3)
		id := fmt.Sprintf("node-%d", i)
		go func() {
			defer wg.Done()
			_ = engine.UpdateNodeConfig(id, map[string]interface{}{"x": "1"})
		}()
		go func() {
			defer wg.Done()
			_ = engine.SwapStrategy(id, "mean_reversion")
		}()
		go func() {
			defer wg.Done()
			_ = engine.ReconfigureAutonomy(id, DefaultAutonomyThresholds())
		}()
	}
	wg.Wait()
}

// ---------------------------------------------------------------------------
// Hot-add/remove while orchestrator is running cycles
// ---------------------------------------------------------------------------

func TestReconfigEngine_HotAddRemoveDuringCycles(t *testing.T) {
	engine, _, orch := newReconfigFixture(t)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := engine.AddNode(nodeConfigFor("anchor")); err != nil {
		t.Fatalf("AddNode anchor: %v", err)
	}

	// First cycle with anchor.
	result1, err := orch.RunCycle(ctx)
	if err != nil {
		t.Fatalf("cycle 1: %v", err)
	}
	if _, ok := result1.Results["anchor"]; !ok {
		t.Fatal("anchor not in cycle 1 results")
	}

	// Hot-add a second node between cycles.
	if err := engine.AddNode(nodeConfigFor("hot-add")); err != nil {
		t.Fatalf("AddNode hot-add: %v", err)
	}

	result2, err := orch.RunCycle(ctx)
	if err != nil {
		t.Fatalf("cycle 2: %v", err)
	}
	if _, ok := result2.Results["hot-add"]; !ok {
		t.Fatal("hot-add not in cycle 2 results")
	}

	// Hot-remove anchor between cycles.
	if err := engine.RemoveNode("anchor"); err != nil {
		t.Fatalf("RemoveNode anchor: %v", err)
	}

	result3, err := orch.RunCycle(ctx)
	if err != nil {
		t.Fatalf("cycle 3: %v", err)
	}
	if _, ok := result3.Results["anchor"]; ok {
		t.Error("anchor should not appear in cycle 3 after removal")
	}
	if _, ok := result3.Results["hot-add"]; !ok {
		t.Fatal("hot-add should still be in cycle 3")
	}
}
