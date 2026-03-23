package core

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/db"
)

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

func newTestRegistry() *StrategyRegistry {
	return NewStrategyRegistry()
}

func mustKernel(t *testing.T) *MemoryKernel {
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
	k, err := NewMemoryKernel(database.StateDB())
	if err != nil {
		database.Close()
		t.Fatalf("NewMemoryKernel: %v", err)
	}
	t.Cleanup(func() { database.Close() })
	return k
}

// lowStrategy: fires long only when price > 200 (confidence 0.3) — rarely fires.
func lowStrategy(nodeID string, version int) *DeterministicStrategy {
	s := &DeterministicStrategy{
		StrategyID:  "low-strat",
		NodeID:      nodeID,
		NodeVersion: "v1",
		Version:     version,
		Parameters:  map[string]any{"threshold": 200.0},
		Rules: []StrategyRule{
			{
				Name:      "high_price_long",
				Direction: DirectionLong,
				Conditions: []RuleCondition{
					{Field: "price", Op: ">", Value: 200.0},
				},
				Confidence: 0.3,
			},
		},
		CompiledAt: time.Now(),
	}
	s.Checksum = computeChecksum(s.Parameters)
	return s
}

// highStrategy: fires long when price > 50 (confidence 0.9) — fires often.
func highStrategy(nodeID string, version int) *DeterministicStrategy {
	s := &DeterministicStrategy{
		StrategyID:  "high-strat",
		NodeID:      nodeID,
		NodeVersion: "v2",
		Version:     version,
		Parameters:  map[string]any{"threshold": 50.0},
		Rules: []StrategyRule{
			{
				Name:      "mid_price_long",
				Direction: DirectionLong,
				Conditions: []RuleCondition{
					{Field: "price", Op: ">", Value: 50.0},
				},
				Confidence: 0.9,
			},
		},
		CompiledAt: time.Now(),
	}
	s.Checksum = computeChecksum(s.Parameters)
	return s
}

// episodesWithPrice creates N episodes whose content contains the given price.
func episodesWithPrice(ctx context.Context, kernel *MemoryKernel, nodeID string, price float64, n int) {
	for i := 0; i < n; i++ {
		_, _ = kernel.StoreEpisode(ctx, Episode{
			EpisodeID: "",
			EventType: "market_tick",
			Content:   map[string]any{"price": price},
			Tags:      []string{"market"},
			Importance: 1.0,
			Cycle:     i,
			Namespace: nodeID,
		})
	}
}

// captureEmitter records emitted events for assertions.
type captureEmitter struct {
	triggered []string
	changed   []strategyChangeRecord
}

type strategyChangeRecord struct {
	nodeID      string
	fromVersion int
	toVersion   int
	improvement float64
}

func (e *captureEmitter) OnImprovementTriggered(nodeID string, version int) {
	e.triggered = append(e.triggered, nodeID)
}

func (e *captureEmitter) OnStrategyChanged(nodeID string, fromVersion, toVersion int, improvement float64) {
	e.changed = append(e.changed, strategyChangeRecord{nodeID, fromVersion, toVersion, improvement})
}

// ---------------------------------------------------------------------------
// BuildSnapshot tests
// ---------------------------------------------------------------------------

func TestBuildSnapshot_RegisteredNode_HasStrategy(t *testing.T) {
	ctx := context.Background()
	reg := newTestRegistry()
	kern := mustKernel(t)

	s := lowStrategy("node-A", 1)
	reg.Register(s)

	snap, err := BuildSnapshot(ctx, "node-A", kern, reg)
	if err != nil {
		t.Fatalf("BuildSnapshot: %v", err)
	}
	if snap.NodeID != "node-A" {
		t.Errorf("NodeID got %q, want %q", snap.NodeID, "node-A")
	}
	if snap.CurrentStrategy == nil {
		t.Fatal("expected CurrentStrategy to be populated")
	}
	if snap.CurrentStrategy.Version != 1 {
		t.Errorf("CurrentStrategy.Version got %d, want 1", snap.CurrentStrategy.Version)
	}
}

func TestBuildSnapshot_NoStrategy_ReturnsNilStrategy(t *testing.T) {
	ctx := context.Background()
	reg := newTestRegistry()
	kern := mustKernel(t)

	snap, err := BuildSnapshot(ctx, "unknown-node", kern, reg)
	if err != nil {
		t.Fatalf("BuildSnapshot: %v", err)
	}
	if snap.CurrentStrategy != nil {
		t.Errorf("expected nil CurrentStrategy for unregistered node")
	}
}

func TestBuildSnapshot_LoadsRecentEpisodes(t *testing.T) {
	ctx := context.Background()
	reg := newTestRegistry()
	kern := mustKernel(t)

	episodesWithPrice(ctx, kern, "node-B", 100.0, 5)

	snap, err := BuildSnapshot(ctx, "node-B", kern, reg)
	if err != nil {
		t.Fatalf("BuildSnapshot: %v", err)
	}
	if len(snap.RecentEpisodes) != 5 {
		t.Errorf("RecentEpisodes len got %d, want 5", len(snap.RecentEpisodes))
	}
}

// ---------------------------------------------------------------------------
// StrategyEvaluator tests
// ---------------------------------------------------------------------------

func TestSimpleEvaluator_CandidateBetter(t *testing.T) {
	// Episodes all have price=100, so highStrategy fires (>50) but lowStrategy doesn't (>200).
	ctx := context.Background()
	kern := mustKernel(t)
	episodesWithPrice(ctx, kern, "node-C", 100.0, 10)

	snap, _ := BuildSnapshot(ctx, "node-C", kern, newTestRegistry())
	current := lowStrategy("node-C", 1)
	candidate := highStrategy("node-C", 2)

	ev := NewSimpleEvaluator()
	winner, improvement, err := ev.Evaluate(current, candidate, snap.RecentEpisodes)
	if err != nil {
		t.Fatalf("Evaluate: %v", err)
	}
	if winner.Version != candidate.Version {
		t.Errorf("expected candidate (v%d) to win, got v%d", candidate.Version, winner.Version)
	}
	if improvement <= 0 {
		t.Errorf("expected positive improvement, got %f", improvement)
	}
}

func TestSimpleEvaluator_CurrentBetter(t *testing.T) {
	// Episodes all have price=300, so lowStrategy fires (>200) with conf 0.3
	// and highStrategy also fires (>50) with conf 0.9.
	// But let's make current better: invert — current has high confidence, candidate has low.
	ctx := context.Background()
	kern := mustKernel(t)
	episodesWithPrice(ctx, kern, "node-D", 300.0, 10)

	snap, _ := BuildSnapshot(ctx, "node-D", kern, newTestRegistry())
	current := highStrategy("node-D", 1)  // fires with 0.9
	candidate := lowStrategy("node-D", 2) // also fires but with 0.3

	ev := NewSimpleEvaluator()
	winner, improvement, err := ev.Evaluate(current, candidate, snap.RecentEpisodes)
	if err != nil {
		t.Fatalf("Evaluate: %v", err)
	}
	if winner.Version != current.Version {
		t.Errorf("expected current (v%d) to win, got v%d", current.Version, winner.Version)
	}
	if improvement >= 0 {
		t.Errorf("expected negative improvement (candidate worse), got %f", improvement)
	}
}

func TestSimpleEvaluator_EmptyEpisodes_ReturnsCurrent(t *testing.T) {
	current := lowStrategy("node-E", 1)
	candidate := highStrategy("node-E", 2)

	ev := NewSimpleEvaluator()
	winner, improvement, err := ev.Evaluate(current, candidate, nil)
	if err != nil {
		t.Fatalf("Evaluate: %v", err)
	}
	if winner.Version != current.Version {
		t.Errorf("expected current to win on empty episodes, got v%d", winner.Version)
	}
	if improvement != 0 {
		t.Errorf("expected 0 improvement on empty episodes, got %f", improvement)
	}
}

// ---------------------------------------------------------------------------
// ImprovementEngine — full cycle tests
// ---------------------------------------------------------------------------

func newTestEngine(t *testing.T, nodeID string) (*ImprovementEngine, *StrategyRegistry, *MemoryKernel, *captureEmitter) {
	t.Helper()
	reg := newTestRegistry()
	kern := mustKernel(t)
	sched := NewImprovementScheduler(time.Now)
	emitter := &captureEmitter{}

	eng := NewImprovementEngine(sched, reg, NewDeterministicCompilerWithRegistry(reg), kern, emitter)
	eng.ImprovementThreshold = 0.01 // low threshold so tests can trigger promotion

	sched.Register(nodeID, &NodeScheduleConfig{
		NodeID:                nodeID,
		Interval:              0, // due immediately
		Cooldown:              0,
		MaxConsecutiveFailures: 3,
		Priority:              1.0,
		Enabled:               true,
	}, true)

	return eng, reg, kern, emitter
}

func TestImprovementCycle_PromotesWhenCandidateBetter(t *testing.T) {
	ctx := context.Background()
	nodeID := "node-promote"
	eng, reg, kern, emitter := newTestEngine(t, nodeID)

	// Register current (low) strategy
	current := lowStrategy(nodeID, 1)
	reg.Register(current)

	// Store episodes: price=100 → highStrategy fires, lowStrategy doesn't
	episodesWithPrice(ctx, kern, nodeID, 100.0, 10)

	// Override compiler to produce highStrategy as candidate
	eng.CandidateBuilder = func(snap *NodeSnapshotData) *DeterministicStrategy {
		return highStrategy(snap.NodeID, reg.NextVersion(snap.NodeID))
	}

	err := eng.RunImprovementCycle(ctx)
	if err != nil {
		t.Fatalf("RunImprovementCycle: %v", err)
	}

	// Should have promoted to a new version
	versions := reg.ListVersions(nodeID)
	if len(versions) < 2 {
		t.Fatalf("expected at least 2 strategy versions after promotion, got %d", len(versions))
	}
	if len(emitter.triggered) == 0 {
		t.Error("expected OnImprovementTriggered to be called")
	}
	if len(emitter.changed) == 0 {
		t.Error("expected OnStrategyChanged to be called")
	}
	if emitter.changed[0].improvement <= 0 {
		t.Errorf("expected positive improvement in event, got %f", emitter.changed[0].improvement)
	}
}

func TestImprovementCycle_RollbackWhenCandidateWorse(t *testing.T) {
	ctx := context.Background()
	nodeID := "node-rollback"
	eng, reg, kern, _ := newTestEngine(t, nodeID)

	// Register current (high) strategy — already good
	current := highStrategy(nodeID, 1)
	reg.Register(current)

	// Episodes: price=300 → high fires with 0.9, low fires with 0.3
	episodesWithPrice(ctx, kern, nodeID, 300.0, 10)

	// Candidate is worse (low strategy)
	eng.CandidateBuilder = func(snap *NodeSnapshotData) *DeterministicStrategy {
		return lowStrategy(snap.NodeID, reg.NextVersion(snap.NodeID))
	}

	err := eng.RunImprovementCycle(ctx)
	if err != nil {
		t.Fatalf("RunImprovementCycle: %v", err)
	}

	// Registry should still have only the original version (no promotion)
	versions := reg.ListVersions(nodeID)
	if len(versions) != 1 {
		t.Errorf("expected 1 version (no promotion), got %d", len(versions))
	}
}

func TestImprovementCycle_BackoffAfterRepeatedFailures(t *testing.T) {
	ctx := context.Background()
	nodeID := "node-backoff"
	reg := newTestRegistry()
	kern := mustKernel(t)
	sched := NewImprovementScheduler(time.Now)

	sched.Register(nodeID, &NodeScheduleConfig{
		NodeID:                nodeID,
		Interval:              0,
		Cooldown:              0,
		MaxConsecutiveFailures: 2, // suspend after 2 failures
		Priority:              1.0,
		Enabled:               true,
	}, true)

	eng := NewImprovementEngine(sched, reg, NewDeterministicCompilerWithRegistry(reg), kern, nil)
	eng.ImprovementThreshold = 0.01

	// Register current high strategy
	reg.Register(highStrategy(nodeID, 1))

	// Episodes where high fires well
	episodesWithPrice(ctx, kern, nodeID, 300.0, 10)

	// Candidate is always worse
	eng.CandidateBuilder = func(snap *NodeSnapshotData) *DeterministicStrategy {
		return lowStrategy(snap.NodeID, reg.NextVersion(snap.NodeID))
	}

	// Run cycles until suspended — each failure re-queues the node immediately
	// (cooldown=0) so DueNodes() keeps returning it until MaxConsecutiveFailures.
	for i := 0; i < 10 && !sched.IsSuspended(nodeID); i++ {
		_ = eng.RunImprovementCycle(ctx)
	}

	if !sched.IsSuspended(nodeID) {
		t.Error("expected node to be suspended after repeated failures")
	}
}

func TestImprovementCycle_NoDueNodes_IsNoop(t *testing.T) {
	ctx := context.Background()
	reg := newTestRegistry()
	kern := mustKernel(t)
	sched := NewImprovementScheduler(time.Now)

	// Register node with far-future interval (not due)
	sched.Register("node-future", &NodeScheduleConfig{
		NodeID:   "node-future",
		Interval: 24 * time.Hour,
		Enabled:  true,
	}, false)

	emitter := &captureEmitter{}
	eng := NewImprovementEngine(sched, reg, NewDeterministicCompilerWithRegistry(reg), kern, emitter)

	err := eng.RunImprovementCycle(ctx)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(emitter.triggered) != 0 {
		t.Errorf("expected no events, got %d triggered", len(emitter.triggered))
	}
}

func TestImprovementCycle_SnapshotAutonomyPreserved(t *testing.T) {
	ctx := context.Background()
	nodeID := "node-autonomy"
	eng, reg, _, _ := newTestEngine(t, nodeID)

	s := lowStrategy(nodeID, 1)
	reg.Register(s)

	var capturedSnap *NodeSnapshotData
	eng.CandidateBuilder = func(snap *NodeSnapshotData) *DeterministicStrategy {
		capturedSnap = snap
		return highStrategy(snap.NodeID, reg.NextVersion(snap.NodeID))
	}

	eng.SnapshotDecorator = func(snap *NodeSnapshotData) {
		snap.Autonomy = AutonomyLevelSupervised
	}

	_ = eng.RunImprovementCycle(ctx)

	if capturedSnap == nil {
		t.Fatal("expected CandidateBuilder to be called")
	}
	if capturedSnap.Autonomy != AutonomyLevelSupervised {
		t.Errorf("expected Autonomy=%d, got %d", AutonomyLevelSupervised, capturedSnap.Autonomy)
	}
}
