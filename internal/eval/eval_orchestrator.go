package eval

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/core"
	"github.com/benebsworth/omega/internal/db"
)

// ---------------------------------------------------------------------------
// OrchestratorHarness
// ---------------------------------------------------------------------------

// OrchestratorHarness wires AlignmentLayer, AutonomyManager,
// EnsembleDisagreementDetector, and ImprovementScheduler together to simulate
// a full orchestration cycle.
type OrchestratorHarness struct {
	Alignment  *core.AlignmentLayer
	Autonomy   *core.AutonomyManager
	Ring1      *core.EnsembleDisagreementDetector
	Scheduler  *core.ImprovementScheduler
	Memory     *core.MemoryKernel
	Clock      *FixedClock

	database *db.DB
}

// NewOrchestratorHarness creates a fully wired orchestrator harness backed by Postgres.
// Test is skipped if TEST_DATABASE_URL is not set.
func NewOrchestratorHarness(t *testing.T) *OrchestratorHarness {
	t.Helper()
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL not set — skipping Postgres integration tests")
	}
	t.Setenv("DATABASE_URL", dsn)

	database, err := db.New(context.Background())
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	t.Cleanup(func() { database.Close() })

	kernel, err := core.NewMemoryKernel(database.StateDB())
	if err != nil {
		t.Fatalf("NewMemoryKernel: %v", err)
	}

	fc := NewFixedClock(time.Minute)

	alignment := core.NewAlignmentLayer(map[string]float64{
		"max_position_pct":          0.25,
		"max_drawdown_pct":          0.15,
		"max_correlation":           0.85,
		"max_improvement_magnitude": 0.5,
	})

	return &OrchestratorHarness{
		Alignment: alignment,
		Autonomy:  core.NewAutonomyManager(),
		Ring1:     core.NewEnsembleDisagreementDetector(0.4),
		Scheduler: core.NewImprovementScheduler(fc.Now),
		Memory:    kernel,
		Clock:     fc,
		database:  database,
	}
}

// NodeConfig describes a node registered with the orchestrator.
type NodeConfig struct {
	NodeID    string
	Metrics   map[string]float64
	Portfolio map[string]float64
	Variants  map[string]map[string]float64 // variantID → signals
}

// RegisterNode registers a node with the scheduler, autonomy manager, and Ring 1.
func (h *OrchestratorHarness) RegisterNode(cfg NodeConfig) {
	schedCfg := core.DefaultNodeScheduleConfig(cfg.NodeID)
	h.Scheduler.Register(cfg.NodeID, &schedCfg, false)
	h.Autonomy.GetLevel(cfg.NodeID) // initialise state

	for variantID, signals := range cfg.Variants {
		h.Ring1.RegisterVariant(variantID, cfg.NodeID+"_"+variantID)
		h.Ring1.SubmitOutput(variantID, signals)
	}
}

// OrchestratorCycleResult captures the outputs of one orchestration cycle.
type OrchestratorCycleResult struct {
	Cycle             int
	AlignmentDecision core.AlignmentDecision
	DisagreementResult core.DisagreementResult
	DueNodes          []string
	MemoryCycleEpID   string
}

// RunCycle executes one orchestration cycle for all registered nodes.
// cycleNodeMetrics: nodeID → {metric: value}
// systemMetrics: global system metrics (e.g., drawdown)
// portfolio: current portfolio positions
func (h *OrchestratorHarness) RunCycle(
	ctx context.Context,
	cycle int,
	cycleNodeMetrics map[string]map[string]float64,
	systemMetrics map[string]float64,
	portfolio map[string]float64,
) OrchestratorCycleResult {
	// Memory: begin cycle.
	_ = h.Memory.BeginCycle(ctx, cycle)

	// Ring 1: detect disagreement.
	disagreement := h.Ring1.Detect(ctx)
	h.Ring1.Clear()

	// Alignment: check improvement cycle.
	decision := h.Alignment.CheckImprovementCycle(cycleNodeMetrics, systemMetrics, portfolio, cycle)

	// Autonomy: record metrics for each node.
	for nodeID, metrics := range cycleNodeMetrics {
		h.Autonomy.RecordCycleMetrics(nodeID, int64(cycle), metrics, !disagreement.Flagged)
	}

	// Improvement scheduler: collect due nodes.
	h.Clock.Advance(time.Minute)
	due := h.Scheduler.DueNodes()

	// Memory: end cycle.
	epID, _ := h.Memory.EndCycle(ctx, cycle, map[string]any{
		"cycle":      cycle,
		"alignment":  decision.Approved,
		"disagreement": disagreement.Flagged,
	})

	return OrchestratorCycleResult{
		Cycle:              cycle,
		AlignmentDecision:  decision,
		DisagreementResult: disagreement,
		DueNodes:           due,
		MemoryCycleEpID:    epID,
	}
}

// DefaultNodeMetrics returns standard healthy metrics for a node.
func DefaultNodeMetrics() map[string]float64 {
	return map[string]float64{
		"sharpe":     1.0,
		"pnl":        0.05,
		"error_rate": 0.02,
	}
}

// DefaultPortfolio returns a diversified portfolio within safety limits.
func DefaultPortfolio() map[string]float64 {
	return map[string]float64{
		"BTCUSDT": 0.20,
		"ETHUSDT": 0.20,
		"SOLUSDT": 0.20,
		"BNBUSDT": 0.20,
		"ADAUSDT": 0.20,
	}
}
