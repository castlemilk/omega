package core

// improvement_engine.go — ImprovementEngine wires ImprovementScheduler,
// DeterministicCompiler, StrategyRegistry, and MemoryKernel into a
// self-improvement loop.
//
// Each call to RunImprovementCycle:
//   1. Queries the scheduler for nodes that are due for improvement.
//   2. Builds a NodeSnapshotData for each due node.
//   3. Produces a candidate strategy (via CandidateBuilder or the default
//      DeterministicCompiler).
//   4. Evaluates the candidate against the current strategy using
//      StrategyEvaluator and recent episodes.
//   5. Promotes the candidate if improvement > ImprovementThreshold; otherwise
//      records a failure so the scheduler can apply exponential back-off.
//   6. Emits events via the optional ImprovementEventEmitter.

import (
	"context"
	"fmt"
	"log/slog"
)

// ---------------------------------------------------------------------------
// Event interface
// ---------------------------------------------------------------------------

// ImprovementEventEmitter receives notifications from ImprovementEngine.
// Set the field to nil to silence all events.
type ImprovementEventEmitter interface {
	// OnImprovementTriggered is called when a node's improvement cycle starts.
	OnImprovementTriggered(nodeID string, currentVersion int)
	// OnStrategyChanged is called when a candidate is promoted.
	OnStrategyChanged(nodeID string, fromVersion, toVersion int, improvement float64)
}

// ---------------------------------------------------------------------------
// ImprovementEngine
// ---------------------------------------------------------------------------

// ImprovementEngine orchestrates the self-improvement loop.
type ImprovementEngine struct {
	scheduler  *ImprovementScheduler
	registry   *StrategyRegistry
	compiler   *DeterministicCompiler
	memory     *MemoryKernel
	evaluator  StrategyEvaluator
	emitter    ImprovementEventEmitter
	logger     *slog.Logger

	// ImprovementThreshold is the minimum relative improvement required before
	// a candidate strategy is promoted (default 0.05 = 5 %).
	ImprovementThreshold float64

	// CandidateBuilder, when set, overrides the default DeterministicCompiler
	// for producing candidate strategies.  Useful in tests.
	CandidateBuilder func(snap *NodeSnapshotData) *DeterministicStrategy

	// SnapshotDecorator, when set, is called after BuildSnapshot so callers
	// can enrich the snapshot with autonomy level or active challenges.
	SnapshotDecorator func(snap *NodeSnapshotData)
}

// NewImprovementEngine constructs an ImprovementEngine.  Pass nil for emitter
// to discard events.
func NewImprovementEngine(
	scheduler *ImprovementScheduler,
	registry *StrategyRegistry,
	compiler *DeterministicCompiler,
	memory *MemoryKernel,
	emitter ImprovementEventEmitter,
) *ImprovementEngine {
	return &ImprovementEngine{
		scheduler:            scheduler,
		registry:             registry,
		compiler:             compiler,
		memory:               memory,
		evaluator:            NewSimpleEvaluator(),
		emitter:              emitter,
		logger:               slog.Default(),
		ImprovementThreshold: 0.05,
	}
}

// ---------------------------------------------------------------------------
// RunImprovementCycle
// ---------------------------------------------------------------------------

// RunImprovementCycle executes one pass of the self-improvement loop for all
// nodes that are currently due.  It returns the first fatal error encountered;
// per-node failures are recorded in the scheduler and do not abort other nodes.
func (e *ImprovementEngine) RunImprovementCycle(ctx context.Context) error {
	due := e.scheduler.DueNodes()
	for _, nodeID := range due {
		if err := e.processNode(ctx, nodeID); err != nil {
			// Non-fatal: log and continue to other nodes.
			e.logger.Warn("improvement cycle error", "node", nodeID, "err", err)
		}
	}
	return nil
}

// processNode runs a full improvement cycle for a single node.
func (e *ImprovementEngine) processNode(ctx context.Context, nodeID string) error {
	// 1. Build snapshot.
	snap, err := BuildSnapshot(ctx, nodeID, e.memory, e.registry)
	if err != nil {
		return fmt.Errorf("BuildSnapshot(%s): %w", nodeID, err)
	}

	// 2. Optionally enrich snapshot (autonomy level, challenges, etc.).
	if e.SnapshotDecorator != nil {
		e.SnapshotDecorator(snap)
	}

	// Determine current version before any changes.
	currentVersion := 0
	if snap.CurrentStrategy != nil {
		currentVersion = snap.CurrentStrategy.Version
	}

	// 3. Emit triggered event.
	if e.emitter != nil {
		e.emitter.OnImprovementTriggered(nodeID, currentVersion)
	}

	// 4. Produce candidate strategy.
	var candidate *DeterministicStrategy
	if e.CandidateBuilder != nil {
		candidate = e.CandidateBuilder(snap)
	} else {
		candidate = e.compiler.Compile(snap.AsCompilerSnapshot())
	}
	if candidate == nil {
		_ = e.scheduler.RecordOutcome(nodeID, false, nil)
		return fmt.Errorf("candidate compilation returned nil for node %s", nodeID)
	}

	// 5. Evaluate candidate vs current.
	winner, improvement, err := e.evaluator.Evaluate(snap.CurrentStrategy, candidate, snap.RecentEpisodes)
	if err != nil {
		_ = e.scheduler.RecordOutcome(nodeID, false, nil)
		return fmt.Errorf("Evaluate(%s): %w", nodeID, err)
	}

	// 6. Promote or roll back.
	if winner == candidate && improvement > e.ImprovementThreshold {
		// Promote: register the candidate in the registry.
		e.registry.Register(candidate)
		score := improvement
		_ = e.scheduler.RecordOutcome(nodeID, true, &score)

		if e.emitter != nil {
			e.emitter.OnStrategyChanged(nodeID, currentVersion, candidate.Version, improvement)
		}
		e.logger.Info("strategy promoted",
			"node", nodeID,
			"from_version", currentVersion,
			"to_version", candidate.Version,
			"improvement", improvement,
		)
	} else {
		// Candidate did not improve; record failure so back-off is applied.
		_ = e.scheduler.RecordOutcome(nodeID, false, nil)
		e.logger.Debug("strategy not promoted",
			"node", nodeID,
			"improvement", improvement,
			"threshold", e.ImprovementThreshold,
		)
	}

	return nil
}
