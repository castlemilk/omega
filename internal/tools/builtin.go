package tools

import (
	"context"
	"fmt"
	"time"

	"github.com/benebsworth/omega/internal/core"
)

// ---------------------------------------------------------------------------
// Dependency interfaces
//
// Each builtin tool declares only the slice of behaviour it needs. This keeps
// coupling minimal and makes mocking trivial in tests.
// ---------------------------------------------------------------------------

// NodeStatusProvider is satisfied by any component that can report active node IDs.
type NodeStatusProvider interface {
	// ActiveNodeIDs returns the IDs of nodes currently registered with the orchestrator.
	ActiveNodeIDs() []string
}

// CycleHistoryProvider is satisfied by any component that can return recent cycle results.
type CycleHistoryProvider interface {
	// RecentCycles returns the N most recent cycle results, newest first.
	RecentCycles(n int) []core.CycleResult
}

// MemorySearcher is satisfied by core.NodeMemory (or any comparable adapter).
type MemorySearcher interface {
	// Search performs a cross-tier keyword search across episodic and semantic memory.
	Search(ctx context.Context, question string, limit int) (*core.MemoryQueryResult, error)
}

// MetricsProvider is satisfied by any component that can return named metric values.
type MetricsProvider interface {
	// CurrentMetrics returns a snapshot of named performance metrics.
	CurrentMetrics() map[string]float64
}

// ReconfigProvider is satisfied by core.ReconfigEngine.
type ReconfigProvider interface {
	// AddNode hot-adds a node to the running orchestrator.
	AddNode(config core.NodeConfig) error
	// RemoveNode hot-removes a node from the running orchestrator.
	RemoveNode(nodeID string) error
	// UpdateNodeConfig patches configuration for an existing node.
	UpdateNodeConfig(nodeID string, patch map[string]interface{}) error
}

// ---------------------------------------------------------------------------
// NodeStatusTool
// ---------------------------------------------------------------------------

// NodeStatusTool queries the current registered node list from the orchestrator.
type NodeStatusTool struct {
	provider NodeStatusProvider
}

// NewNodeStatusTool constructs a NodeStatusTool backed by the given provider.
func NewNodeStatusTool(provider NodeStatusProvider) *NodeStatusTool {
	return &NodeStatusTool{provider: provider}
}

func (t *NodeStatusTool) Name() string { return "node_status" }

func (t *NodeStatusTool) Description() string {
	return "List all nodes currently registered with the Omega orchestrator and their active state."
}

func (t *NodeStatusTool) Schema() ToolSchema {
	return ToolSchema{
		Name:        t.Name(),
		Description: t.Description(),
		Parameters: map[string]any{
			"type":       "object",
			"properties": map[string]any{},
		},
		RequiredAutonomyLevel: levelAlways,
	}
}

// Execute returns the list of active node IDs.
func (t *NodeStatusTool) Execute(_ context.Context, _ map[string]any) (ToolResult, error) {
	ids := t.provider.ActiveNodeIDs()
	return ToolResult{Content: map[string]any{
		"node_ids": ids,
		"count":    len(ids),
	}}, nil
}

// ---------------------------------------------------------------------------
// CycleHistoryTool
// ---------------------------------------------------------------------------

// CycleHistoryTool returns recent orchestration cycle results.
type CycleHistoryTool struct {
	provider CycleHistoryProvider
}

// NewCycleHistoryTool constructs a CycleHistoryTool backed by the given provider.
func NewCycleHistoryTool(provider CycleHistoryProvider) *CycleHistoryTool {
	return &CycleHistoryTool{provider: provider}
}

func (t *CycleHistoryTool) Name() string { return "cycle_history" }

func (t *CycleHistoryTool) Description() string {
	return "Retrieve recent orchestration cycle results including duration, node outcomes, and errors."
}

func (t *CycleHistoryTool) Schema() ToolSchema {
	return ToolSchema{
		Name:        t.Name(),
		Description: t.Description(),
		Parameters: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"limit": map[string]any{
					"type":        "integer",
					"description": "Maximum number of cycles to return (default 10)",
					"default":     10,
				},
			},
		},
		RequiredAutonomyLevel: levelAlways,
	}
}

// Execute returns up to limit recent cycle results.
//
// args:
//   - "limit" int (optional) — number of cycles, default 10
func (t *CycleHistoryTool) Execute(_ context.Context, args map[string]any) (ToolResult, error) {
	limit := 10
	if l, ok := args["limit"].(int); ok && l > 0 {
		limit = l
	}
	cycles := t.provider.RecentCycles(limit)
	return ToolResult{Content: cycles}, nil
}

// ---------------------------------------------------------------------------
// MemoryQueryTool
// ---------------------------------------------------------------------------

// MemoryQueryTool searches episodic and semantic memory for relevant information.
type MemoryQueryTool struct {
	searcher MemorySearcher
}

// NewMemoryQueryTool constructs a MemoryQueryTool backed by the given searcher.
func NewMemoryQueryTool(searcher MemorySearcher) *MemoryQueryTool {
	return &MemoryQueryTool{searcher: searcher}
}

func (t *MemoryQueryTool) Name() string { return "memory_query" }

func (t *MemoryQueryTool) Description() string {
	return "Search Omega's episodic and semantic memory stores for information relevant to a natural-language question."
}

func (t *MemoryQueryTool) Schema() ToolSchema {
	return ToolSchema{
		Name:        t.Name(),
		Description: t.Description(),
		Parameters: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"question": map[string]any{
					"type":        "string",
					"description": "Natural-language question to search memory for",
				},
				"limit": map[string]any{
					"type":        "integer",
					"description": "Maximum results per memory tier (default 5)",
					"default":     5,
				},
			},
			"required": []string{"question"},
		},
		RequiredAutonomyLevel: levelAlways,
	}
}

// Execute searches memory and returns a MemoryQueryResult.
//
// args:
//   - "question" string (required) — the search query
//   - "limit"    int    (optional) — results per tier, default 5
func (t *MemoryQueryTool) Execute(ctx context.Context, args map[string]any) (ToolResult, error) {
	question, _ := args["question"].(string)
	if question == "" {
		return ToolResult{IsError: true, Content: "question argument is required"}, nil
	}
	limit := 5
	if l, ok := args["limit"].(int); ok && l > 0 {
		limit = l
	}
	result, err := t.searcher.Search(ctx, question, limit)
	if err != nil {
		return ToolResult{IsError: true, Content: err.Error()}, err
	}
	return ToolResult{Content: result}, nil
}

// ---------------------------------------------------------------------------
// MetricsQueryTool
// ---------------------------------------------------------------------------

// MetricsQueryTool returns a snapshot of current performance metrics.
type MetricsQueryTool struct {
	provider MetricsProvider
}

// NewMetricsQueryTool constructs a MetricsQueryTool backed by the given provider.
func NewMetricsQueryTool(provider MetricsProvider) *MetricsQueryTool {
	return &MetricsQueryTool{provider: provider}
}

func (t *MetricsQueryTool) Name() string { return "metrics_query" }

func (t *MetricsQueryTool) Description() string {
	return "Query current performance metrics including autonomy levels, cycle durations, and node error rates."
}

func (t *MetricsQueryTool) Schema() ToolSchema {
	return ToolSchema{
		Name:        t.Name(),
		Description: t.Description(),
		Parameters: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"filter": map[string]any{
					"type":        "string",
					"description": "Optional prefix filter on metric names",
				},
			},
		},
		RequiredAutonomyLevel: levelAlways,
	}
}

// Execute returns the current metrics snapshot, optionally filtered by prefix.
//
// args:
//   - "filter" string (optional) — metric name prefix filter
func (t *MetricsQueryTool) Execute(_ context.Context, args map[string]any) (ToolResult, error) {
	all := t.provider.CurrentMetrics()
	filter, _ := args["filter"].(string)
	if filter == "" {
		return ToolResult{Content: all}, nil
	}
	filtered := make(map[string]float64)
	for k, v := range all {
		if len(k) >= len(filter) && k[:len(filter)] == filter {
			filtered[k] = v
		}
	}
	return ToolResult{Content: filtered}, nil
}

// ---------------------------------------------------------------------------
// ReconfigTool
// ---------------------------------------------------------------------------

// ReconfigTool triggers dynamic reconfiguration of the running orchestrator.
// It requires AUTONOMOUS (Full) autonomy level because it modifies live state.
type ReconfigTool struct {
	engine ReconfigProvider
}

// NewReconfigTool constructs a ReconfigTool backed by the given engine.
func NewReconfigTool(engine ReconfigProvider) *ReconfigTool {
	return &ReconfigTool{engine: engine}
}

func (t *ReconfigTool) Name() string { return "reconfigure" }

func (t *ReconfigTool) Description() string {
	return "Trigger dynamic reconfiguration of the Omega orchestrator: add/remove nodes or patch node configuration at runtime."
}

func (t *ReconfigTool) Schema() ToolSchema {
	return ToolSchema{
		Name:        t.Name(),
		Description: t.Description(),
		Parameters: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"op": map[string]any{
					"type":        "string",
					"enum":        []string{"add_node", "remove_node", "update_config"},
					"description": "Reconfiguration operation to perform",
				},
				"node_id": map[string]any{
					"type":        "string",
					"description": "Target node ID",
				},
				"node_type": map[string]any{
					"type":        "string",
					"description": "Node type (required for add_node)",
				},
				"strategy_id": map[string]any{
					"type":        "string",
					"description": "Strategy ID (required for add_node)",
				},
				"params": map[string]any{
					"type":        "object",
					"description": "Arbitrary key/value configuration (add_node or update_config)",
				},
			},
			"required": []string{"op", "node_id"},
		},
		RequiredAutonomyLevel: levelAutonomous,
	}
}

// Execute dispatches the requested reconfiguration operation.
//
// args:
//   - "op"          string         (required) — "add_node" | "remove_node" | "update_config"
//   - "node_id"     string         (required) — target node
//   - "node_type"   string         (add_node) — node classifier
//   - "strategy_id" string         (add_node) — active strategy
//   - "params"      map[string]any (optional) — config key/values
func (t *ReconfigTool) Execute(_ context.Context, args map[string]any) (ToolResult, error) {
	op, _ := args["op"].(string)
	nodeID, _ := args["node_id"].(string)

	if op == "" || nodeID == "" {
		return ToolResult{IsError: true, Content: "op and node_id are required"}, nil
	}

	switch op {
	case "add_node":
		nodeType, _ := args["node_type"].(string)
		strategyID, _ := args["strategy_id"].(string)
		params, _ := args["params"].(map[string]any)
		cfg := core.NodeConfig{
			NodeID:             nodeID,
			NodeType:           nodeType,
			StrategyID:         strategyID,
			Params:             params,
			AutonomyThresholds: core.DefaultAutonomyThresholds(),
		}
		if err := t.engine.AddNode(cfg); err != nil {
			return ToolResult{IsError: true, Content: err.Error()}, err
		}
		return ToolResult{Content: map[string]any{
			"op":      op,
			"node_id": nodeID,
			"status":  "added",
			"at":      time.Now(),
		}}, nil

	case "remove_node":
		if err := t.engine.RemoveNode(nodeID); err != nil {
			return ToolResult{IsError: true, Content: err.Error()}, err
		}
		return ToolResult{Content: map[string]any{
			"op":      op,
			"node_id": nodeID,
			"status":  "removed",
			"at":      time.Now(),
		}}, nil

	case "update_config":
		params, _ := args["params"].(map[string]any)
		if len(params) == 0 {
			return ToolResult{IsError: true, Content: "params must be non-empty for update_config"}, nil
		}
		// Convert map[string]any → map[string]interface{} (same underlying type).
		patch := make(map[string]interface{}, len(params))
		for k, v := range params {
			patch[k] = v
		}
		if err := t.engine.UpdateNodeConfig(nodeID, patch); err != nil {
			return ToolResult{IsError: true, Content: err.Error()}, err
		}
		return ToolResult{Content: map[string]any{
			"op":      op,
			"node_id": nodeID,
			"status":  "updated",
			"at":      time.Now(),
		}}, nil

	default:
		return ToolResult{IsError: true, Content: fmt.Sprintf("unknown op %q", op)}, nil
	}
}

// ---------------------------------------------------------------------------
// RegisterBuiltins is a convenience function that registers all built-in tools
// with the provided registry.
//
// toolSearch is always added to the active pool; the remaining five tools are
// added to the deferred pool so the active context stays lean.
// ---------------------------------------------------------------------------

// BuiltinDeps bundles the runtime dependencies required by the builtin tools.
// Fields may be nil; the corresponding tool is omitted from registration.
type BuiltinDeps struct {
	NodeStatus   NodeStatusProvider
	CycleHistory CycleHistoryProvider
	Memory       MemorySearcher
	Metrics      MetricsProvider
	Reconfig     ReconfigProvider
}

// RegisterBuiltins registers the full set of builtin tools into reg.
// toolSearch is always active; the rest are deferred pending discovery.
func RegisterBuiltins(reg *Registry, deps BuiltinDeps) {
	// The search tool is always active — it IS the discovery mechanism.
	reg.Register(NewToolSearchTool(reg))

	if deps.NodeStatus != nil {
		reg.RegisterDeferred(NewNodeStatusTool(deps.NodeStatus))
	}
	if deps.CycleHistory != nil {
		reg.RegisterDeferred(NewCycleHistoryTool(deps.CycleHistory))
	}
	if deps.Memory != nil {
		reg.RegisterDeferred(NewMemoryQueryTool(deps.Memory))
	}
	if deps.Metrics != nil {
		reg.RegisterDeferred(NewMetricsQueryTool(deps.Metrics))
	}
	if deps.Reconfig != nil {
		reg.RegisterDeferred(NewReconfigTool(deps.Reconfig))
	}
}
