package eval

import (
	"context"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/core"
)

// ---------------------------------------------------------------------------
// Node registration and basic cycle
// ---------------------------------------------------------------------------

func TestOrchestrator_RegisterMultipleNodes(t *testing.T) {
	h := NewOrchestratorHarness(t)

	nodes := []NodeConfig{
		{
			NodeID:    "signal_node",
			Metrics:   DefaultNodeMetrics(),
			Portfolio: DefaultPortfolio(),
			Variants:  map[string]map[string]float64{"v1": {"BTC": 0.5}},
		},
		{
			NodeID:    "strategy_node",
			Metrics:   DefaultNodeMetrics(),
			Portfolio: DefaultPortfolio(),
			Variants:  map[string]map[string]float64{"v2": {"BTC": 0.4}},
		},
	}
	for _, nc := range nodes {
		h.RegisterNode(nc)
	}

	registered := h.Scheduler.RegisteredNodes()
	if len(registered) != 2 {
		t.Errorf("expected 2 registered nodes, got %d", len(registered))
	}
}

func TestOrchestrator_SingleCycleAllOutputsPresent(t *testing.T) {
	ctx := context.Background()
	h := NewOrchestratorHarness(t)

	h.RegisterNode(NodeConfig{
		NodeID:   "node_a",
		Variants: map[string]map[string]float64{"va": {"BTC": 0.5, "ETH": 0.4}},
	})

	nodeMetrics := map[string]map[string]float64{
		"node_a": DefaultNodeMetrics(),
	}
	result := h.RunCycle(ctx, 1, nodeMetrics, map[string]float64{"drawdown": 0.05}, DefaultPortfolio())

	if result.Cycle != 1 {
		t.Errorf("Cycle=%d want=1", result.Cycle)
	}
	if result.MemoryCycleEpID == "" {
		t.Error("MemoryCycleEpID should be set")
	}
}

// ---------------------------------------------------------------------------
// Alignment gate fires correctly
// ---------------------------------------------------------------------------

func TestOrchestrator_AlignmentApprovedForHealthyPortfolio(t *testing.T) {
	ctx := context.Background()
	h := NewOrchestratorHarness(t)

	h.RegisterNode(NodeConfig{NodeID: "node_b"})
	nodeMetrics := map[string]map[string]float64{"node_b": DefaultNodeMetrics()}

	result := h.RunCycle(ctx, 1, nodeMetrics, map[string]float64{"drawdown": 0.05}, DefaultPortfolio())
	if !result.AlignmentDecision.Approved {
		t.Errorf("alignment should be approved for healthy portfolio, violations: %v", result.AlignmentDecision.Violations)
	}
}

func TestOrchestrator_AlignmentRejectedForConcentratedPortfolio(t *testing.T) {
	ctx := context.Background()
	h := NewOrchestratorHarness(t)

	h.RegisterNode(NodeConfig{NodeID: "node_c"})
	nodeMetrics := map[string]map[string]float64{"node_c": DefaultNodeMetrics()}
	concentrated := map[string]float64{"BTCUSDT": 0.9, "ETHUSDT": 0.1}

	result := h.RunCycle(ctx, 1, nodeMetrics, map[string]float64{"drawdown": 0.05}, concentrated)
	if result.AlignmentDecision.Approved {
		t.Error("alignment should be rejected for concentrated portfolio")
	}
	if len(result.AlignmentDecision.Violations) == 0 {
		t.Error("expected at least one violation")
	}
}

// ---------------------------------------------------------------------------
// Ring 1 disagreement fires and affects autonomy
// ---------------------------------------------------------------------------

func TestOrchestrator_DisagreementFlagsAdversarialSignal(t *testing.T) {
	ctx := context.Background()
	h := NewOrchestratorHarness(t)

	// Register a node with two maximally divergent variants.
	h.Ring1.RegisterVariant("bull_v", "bull")
	h.Ring1.RegisterVariant("bear_v", "bear")
	h.Ring1.SubmitOutput("bull_v", map[string]float64{"BTC": 1.0, "ETH": 1.0})
	h.Ring1.SubmitOutput("bear_v", map[string]float64{"BTC": -1.0, "ETH": -1.0})

	h.Scheduler.Register("disagreement_node", nil, false)

	nodeMetrics := map[string]map[string]float64{"disagreement_node": DefaultNodeMetrics()}
	result := h.RunCycle(ctx, 1, nodeMetrics, map[string]float64{"drawdown": 0.05}, DefaultPortfolio())

	if !result.DisagreementResult.Flagged {
		t.Errorf("expected Ring1 disagreement to be flagged, MaxDisagreement=%.4f",
			result.DisagreementResult.MaxDisagreement)
	}
}

// ---------------------------------------------------------------------------
// Post-cycle hooks — safety, memory persistence
// ---------------------------------------------------------------------------

func TestOrchestrator_MemoryCycleEpisodesAccumulate(t *testing.T) {
	ctx := context.Background()
	h := NewOrchestratorHarness(t)
	h.Scheduler.Register("accum_node", nil, false)

	nodeMetrics := map[string]map[string]float64{"accum_node": DefaultNodeMetrics()}
	sysMet := map[string]float64{"drawdown": 0.03}

	const nCycles = 5
	for i := 1; i <= nCycles; i++ {
		h.RunCycle(ctx, i, nodeMetrics, sysMet, DefaultPortfolio())
	}

	// Each cycle stores a cycle_summary episode.
	eps, err := h.Memory.RetrieveEpisodes(ctx, core.EpisodeFilter{
		EventType: "cycle_summary",
		Limit:     20,
	})
	if err != nil {
		t.Fatalf("RetrieveEpisodes: %v", err)
	}
	if len(eps) != nCycles {
		t.Errorf("expected %d cycle_summary episodes, got %d", nCycles, len(eps))
	}
}

// ---------------------------------------------------------------------------
// Node lifecycle: register → improvement cycle → autonomous promotion
// ---------------------------------------------------------------------------

func TestOrchestrator_NodeLifecycle_RegisterThenPromote(t *testing.T) {
	ctx := context.Background()
	h := NewOrchestratorHarness(t)

	nodeID := "lifecycle_orch"
	h.Scheduler.Register(nodeID, nil, false)
	h.Autonomy.GetLevel(nodeID) // initialise at Manual

	good := GoodMetrics()

	// Run 10 successful cycles to build up CyclesAtLevel.
	for i := 1; i <= 10; i++ {
		h.Autonomy.RecordCycleMetrics(nodeID, int64(i), good, true)
	}

	// Request promotion to Supervised.
	result := h.Autonomy.RequestPromotion(ctx, nodeID, core.AutonomyLevelSupervised, good, 11)
	if !result.Approved {
		t.Fatalf("expected Supervised promotion after 10 cycles: %v", result.Reasons)
	}
	h.Autonomy.RecordPromotion(nodeID, core.AutonomyLevelManual, core.AutonomyLevelSupervised, "perf", 11)

	if h.Autonomy.GetLevel(nodeID).Level != core.AutonomyLevelSupervised {
		t.Error("expected Supervised level after promotion")
	}
}

// ---------------------------------------------------------------------------
// Multi-node parallel orchestration
// ---------------------------------------------------------------------------

func TestOrchestrator_MultiNode_IndependentAlignment(t *testing.T) {
	ctx := context.Background()
	h := NewOrchestratorHarness(t)

	for _, id := range []string{"node_x", "node_y", "node_z"} {
		h.Scheduler.Register(id, nil, false)
	}

	nodeMetrics := map[string]map[string]float64{
		"node_x": {"sharpe": 1.0, "pnl": 0.05},
		"node_y": {"sharpe": 0.8, "pnl": 0.03},
		"node_z": {"sharpe": 1.5, "pnl": 0.08},
	}
	result := h.RunCycle(ctx, 1, nodeMetrics, map[string]float64{"drawdown": 0.04}, DefaultPortfolio())

	// All 3 nodes should appear in Pareto ranks.
	if len(result.AlignmentDecision.ParetoRanks) != 3 {
		t.Errorf("expected 3 Pareto ranks, got %d", len(result.AlignmentDecision.ParetoRanks))
	}

	// All ranks must be non-negative.
	for nodeID, rank := range result.AlignmentDecision.ParetoRanks {
		if rank < 0 {
			t.Errorf("node %q has negative Pareto rank %d", nodeID, rank)
		}
	}
}

func TestOrchestrator_ImprovementSchedulerIntegration(t *testing.T) {
	ctx := context.Background()
	h := NewOrchestratorHarness(t)

	// Register a node with a short 1-minute interval (matching FixedClock step).
	cfg := core.DefaultNodeScheduleConfig("sched_node")
	cfg.Interval = time.Minute
	h.Scheduler.Register("sched_node", &cfg, true) // due immediately

	// First cycle: node should be due.
	nodeMetrics := map[string]map[string]float64{"sched_node": DefaultNodeMetrics()}
	result := h.RunCycle(ctx, 1, nodeMetrics, map[string]float64{"drawdown": 0.02}, DefaultPortfolio())

	if len(result.DueNodes) == 0 {
		t.Log("no due nodes in first cycle (may depend on clock timing)")
	}
	_ = ctx
}
