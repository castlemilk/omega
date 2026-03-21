package core

// node_snapshot.go — NodeSnapshotData and BuildSnapshot.
//
// NodeSnapshotData is the full picture of a node at improvement-cycle time:
// its current compiled strategy, recent episodic memory, historical performance
// metrics, autonomy level, and any active challenges.  It also implements the
// NodeSnapshot interface so it can be passed directly to DeterministicCompiler.

import (
	"context"
)

// ---------------------------------------------------------------------------
// NodeSnapshotData
// ---------------------------------------------------------------------------

// NodeSnapshotData captures the full state of a node for one improvement cycle.
type NodeSnapshotData struct {
	// NodeID identifies the node.
	NodeID string

	// CurrentStrategy is the node's active compiled strategy (may be nil if
	// the node has never been compiled).
	CurrentStrategy *DeterministicStrategy

	// RecentEpisodes holds the latest episodic memory entries for this node.
	RecentEpisodes []Episode

	// PerformanceHistory holds scalar metric snapshots from past cycles,
	// extracted from episodes whose EventType is "performance".
	PerformanceHistory []map[string]float64

	// Autonomy is the node's current autonomy level.
	Autonomy AutonomyLevel

	// ActiveChallenges lists open challenges raised against this node.
	ActiveChallenges []Challenge
}

// ---------------------------------------------------------------------------
// NodeSnapshot interface implementation (satisfies deterministic_compiler.go)
// ---------------------------------------------------------------------------

// compilerSnapshotAdapter adapts NodeSnapshotData to the NodeSnapshot interface
// expected by DeterministicCompiler without polluting NodeSnapshotData's field
// namespace.
type compilerSnapshotAdapter struct {
	data *NodeSnapshotData
}

func (a *compilerSnapshotAdapter) NodeID() string { return a.data.NodeID }

func (a *compilerSnapshotAdapter) NodeVersion() string {
	if a.data.CurrentStrategy != nil {
		return a.data.CurrentStrategy.NodeVersion
	}
	return "v0"
}

func (a *compilerSnapshotAdapter) Parameters() map[string]any {
	if a.data.CurrentStrategy != nil && a.data.CurrentStrategy.Parameters != nil {
		// Return a shallow copy so the compiler cannot mutate the snapshot.
		out := make(map[string]any, len(a.data.CurrentStrategy.Parameters))
		for k, v := range a.data.CurrentStrategy.Parameters {
			out[k] = v
		}
		return out
	}
	return map[string]any{}
}

func (a *compilerSnapshotAdapter) Rules() []StrategyRule {
	if a.data.CurrentStrategy != nil {
		return a.data.CurrentStrategy.Rules
	}
	return nil
}

// AsCompilerSnapshot returns a NodeSnapshot that DeterministicCompiler can use.
func (s *NodeSnapshotData) AsCompilerSnapshot() NodeSnapshot {
	return &compilerSnapshotAdapter{data: s}
}

// ---------------------------------------------------------------------------
// BuildSnapshot
// ---------------------------------------------------------------------------

// maxSnapshotEpisodes is the maximum number of recent episodes loaded per node.
const maxSnapshotEpisodes = 50

// BuildSnapshot assembles a NodeSnapshotData from the StrategyRegistry and
// MemoryKernel for the given nodeID.  It does not block on I/O beyond the
// SQLite queries already used by MemoryKernel.
//
// Callers can enrich the snapshot afterwards (e.g. set Autonomy, ActiveChallenges)
// before passing it to ImprovementEngine.
func BuildSnapshot(ctx context.Context, nodeID string, mem *MemoryKernel, registry *StrategyRegistry) (*NodeSnapshotData, error) {
	snap := &NodeSnapshotData{NodeID: nodeID}

	// Current strategy — may be nil for nodes that have never been compiled.
	snap.CurrentStrategy = registry.GetCurrent(nodeID)

	// Recent episodes for this node's namespace.
	episodes, err := mem.RetrieveEpisodes(ctx, EpisodeFilter{
		Namespace: nodeID,
		Limit:     maxSnapshotEpisodes,
	})
	if err != nil {
		return nil, err
	}
	snap.RecentEpisodes = episodes

	// Extract PerformanceHistory from episodes tagged as performance snapshots.
	for _, ep := range episodes {
		if ep.EventType != "performance" {
			continue
		}
		metrics := make(map[string]float64)
		for k, v := range ep.Content {
			switch n := v.(type) {
			case float64:
				metrics[k] = n
			case int:
				metrics[k] = float64(n)
			case int64:
				metrics[k] = float64(n)
			}
		}
		if len(metrics) > 0 {
			snap.PerformanceHistory = append(snap.PerformanceHistory, metrics)
		}
	}

	return snap, nil
}

