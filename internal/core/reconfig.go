// Package core — reconfig.go
//
// ReconfigEngine provides hot-reconfiguration of the running orchestrator:
// adding/removing nodes, live config patches, strategy hot-swaps, and
// autonomy threshold updates — all without stopping the cycle loop.
package core

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/benebsworth/omega/internal/framework"
)

// ---------------------------------------------------------------------------
// Event topics (published on the framework.EventBus)
// ---------------------------------------------------------------------------

const (
	TopicNodeAdded            = "reconfig.node.added"
	TopicNodeRemoved          = "reconfig.node.removed"
	TopicNodeConfigUpdated    = "reconfig.node.config_updated"
	TopicStrategySwapped      = "reconfig.strategy.swapped"
	TopicAutonomyReconfigured = "reconfig.autonomy.reconfigured"
)

// ---------------------------------------------------------------------------
// AutonomyThresholds — per-node promotion/demotion knobs
// ---------------------------------------------------------------------------

// AutonomyThresholds controls when a node is promoted or demoted autonomously.
type AutonomyThresholds struct {
	// MinCyclesForPromotion is the minimum number of successful cycles required
	// before a promotion to a higher autonomy level is considered.
	MinCyclesForPromotion int64

	// MinSharpeForPromotion is the Sharpe ratio floor required for promotion.
	MinSharpeForPromotion float64

	// MaxDrawdownForDemotion triggers an automatic demotion when breached.
	MaxDrawdownForDemotion float64

	// ConfidenceFloor is the minimum confidence score to remain at the current level.
	ConfidenceFloor float64
}

// DefaultAutonomyThresholds returns safe, conservative defaults.
func DefaultAutonomyThresholds() AutonomyThresholds {
	return AutonomyThresholds{
		MinCyclesForPromotion:  10,
		MinSharpeForPromotion:  0.5,
		MaxDrawdownForDemotion: 0.15,
		ConfidenceFloor:        0.6,
	}
}

// ---------------------------------------------------------------------------
// NodeConfig — description of a node to be hot-added
// ---------------------------------------------------------------------------

// NodeConfig describes the configuration of a single orchestration node.
// It is the runtime representation used by the ReconfigEngine; it is distinct
// from the protobuf NodeConfig in gen/ which is the wire format.
type NodeConfig struct {
	// NodeID is the stable unique identifier for the node.
	NodeID string

	// NodeType is a classifier used for resource estimation and plugin lookup.
	NodeType string

	// StrategyID names the active strategy the node should run.
	StrategyID string

	// Params holds arbitrary key/value configuration consumed by the node.
	Params map[string]interface{}

	// AutonomyThresholds governs autonomous promotion/demotion of this node.
	AutonomyThresholds AutonomyThresholds
}

// ---------------------------------------------------------------------------
// ReconfigEvent — payload published on every reconfig operation
// ---------------------------------------------------------------------------

// ReconfigEvent is the payload published to the framework.EventBus on every
// successful reconfig operation.
type ReconfigEvent struct {
	// Op is the topic / operation name (e.g. TopicNodeAdded).
	Op string

	// NodeID identifies the node affected by the operation.
	NodeID string

	// Timestamp is when the operation was applied.
	Timestamp time.Time

	// Details carries operation-specific metadata (may be nil).
	Details map[string]interface{}
}

// ---------------------------------------------------------------------------
// ReconfigEngine
// ---------------------------------------------------------------------------

// ReconfigEngine is the hot-reconfiguration controller for a running Orchestrator.
// All exported methods are safe for concurrent use.
type ReconfigEngine struct {
	mu       sync.Mutex
	orch     *Orchestrator
	registry *framework.PluginRegistry
	bus      *framework.EventBus

	// nodes tracks the NodeConfig for every hot-added node.
	nodes map[string]NodeConfig
}

// NewReconfigEngine creates a ReconfigEngine wired to the given Orchestrator.
// registry and bus may be nil (operations still succeed; events are suppressed).
func NewReconfigEngine(
	orch *Orchestrator,
	registry *framework.PluginRegistry,
	bus *framework.EventBus,
) *ReconfigEngine {
	return &ReconfigEngine{
		orch:     orch,
		registry: registry,
		bus:      bus,
		nodes:    make(map[string]NodeConfig),
	}
}

// AddNode hot-adds a new node to the running orchestrator.
// Returns an error if a node with the same ID is already tracked.
func (e *ReconfigEngine) AddNode(config NodeConfig) error {
	if config.NodeID == "" {
		return fmt.Errorf("reconfig: NodeID must not be empty")
	}

	e.mu.Lock()
	defer e.mu.Unlock()

	if _, exists := e.nodes[config.NodeID]; exists {
		return fmt.Errorf("reconfig: node %q already exists", config.NodeID)
	}

	exec := newConfiguredNode(config)
	e.orch.Register(exec)
	e.nodes[config.NodeID] = config

	e.emit(TopicNodeAdded, config.NodeID, map[string]interface{}{
		"node_type":   config.NodeType,
		"strategy_id": config.StrategyID,
	})
	return nil
}

// RemoveNode gracefully drains and removes a node from the orchestrator.
// The LifecycleManager (lifecycle.go) handles the drain state machine; here we
// perform the final deregistration.
func (e *ReconfigEngine) RemoveNode(nodeID string) error {
	e.mu.Lock()
	defer e.mu.Unlock()

	if _, exists := e.nodes[nodeID]; !exists {
		return fmt.Errorf("reconfig: node %q not found", nodeID)
	}

	e.orch.Deregister(nodeID)
	delete(e.nodes, nodeID)

	e.emit(TopicNodeRemoved, nodeID, nil)
	return nil
}

// UpdateNodeConfig applies a key/value patch to a node's Params map.
// The patch is merged (not replaced); use a nil value to remove a key.
func (e *ReconfigEngine) UpdateNodeConfig(nodeID string, patch map[string]interface{}) error {
	e.mu.Lock()
	defer e.mu.Unlock()

	cfg, exists := e.nodes[nodeID]
	if !exists {
		return fmt.Errorf("reconfig: node %q not found", nodeID)
	}

	if cfg.Params == nil {
		cfg.Params = make(map[string]interface{}, len(patch))
	}
	for k, v := range patch {
		if v == nil {
			delete(cfg.Params, k)
		} else {
			cfg.Params[k] = v
		}
	}
	e.nodes[nodeID] = cfg

	e.emit(TopicNodeConfigUpdated, nodeID, map[string]interface{}{"patch": patch})
	return nil
}

// SwapStrategy hot-swaps the strategy ID for a running node.
// The calling layer is responsible for re-initialising any strategy-specific
// state on the node executor.
func (e *ReconfigEngine) SwapStrategy(nodeID string, strategyID string) error {
	if strategyID == "" {
		return fmt.Errorf("reconfig: strategyID must not be empty")
	}

	e.mu.Lock()
	defer e.mu.Unlock()

	cfg, exists := e.nodes[nodeID]
	if !exists {
		return fmt.Errorf("reconfig: node %q not found", nodeID)
	}

	old := cfg.StrategyID
	cfg.StrategyID = strategyID
	e.nodes[nodeID] = cfg

	e.emit(TopicStrategySwapped, nodeID, map[string]interface{}{
		"old_strategy": old,
		"new_strategy": strategyID,
	})
	return nil
}

// ReconfigureAutonomy replaces the autonomy thresholds for a node.
func (e *ReconfigEngine) ReconfigureAutonomy(nodeID string, newThresholds AutonomyThresholds) error {
	e.mu.Lock()
	defer e.mu.Unlock()

	cfg, exists := e.nodes[nodeID]
	if !exists {
		return fmt.Errorf("reconfig: node %q not found", nodeID)
	}

	cfg.AutonomyThresholds = newThresholds
	e.nodes[nodeID] = cfg

	e.emit(TopicAutonomyReconfigured, nodeID, map[string]interface{}{
		"min_cycles":    newThresholds.MinCyclesForPromotion,
		"min_sharpe":    newThresholds.MinSharpeForPromotion,
		"max_drawdown":  newThresholds.MaxDrawdownForDemotion,
		"conf_floor":    newThresholds.ConfidenceFloor,
	})
	return nil
}

// Nodes returns a snapshot of all currently tracked NodeConfigs.
func (e *ReconfigEngine) Nodes() map[string]NodeConfig {
	e.mu.Lock()
	defer e.mu.Unlock()

	out := make(map[string]NodeConfig, len(e.nodes))
	for k, v := range e.nodes {
		out[k] = v
	}
	return out
}

// NodeCount returns the number of nodes currently tracked by this engine.
func (e *ReconfigEngine) NodeCount() int {
	e.mu.Lock()
	defer e.mu.Unlock()
	return len(e.nodes)
}

// ---------------------------------------------------------------------------
// internal helpers
// ---------------------------------------------------------------------------

func (e *ReconfigEngine) emit(topic, nodeID string, details map[string]interface{}) {
	if e.bus == nil {
		return
	}
	e.bus.Publish(framework.Event{
		Topic: topic,
		Payload: ReconfigEvent{
			Op:        topic,
			NodeID:    nodeID,
			Timestamp: time.Now(),
			Details:   details,
		},
	})
}

// ---------------------------------------------------------------------------
// configuredNode — minimal NodeExecutor created from a NodeConfig
// ---------------------------------------------------------------------------

// configuredNode is a stub NodeExecutor constructed from a NodeConfig.
// It satisfies the NodeExecutor contract so the node can be registered
// immediately; real execution logic is wired in via the plugin registry.
type configuredNode struct {
	cfg NodeConfig
}

func newConfiguredNode(cfg NodeConfig) NodeExecutor {
	return &configuredNode{cfg: cfg}
}

func (n *configuredNode) NodeID() string { return n.cfg.NodeID }

func (n *configuredNode) Execute(_ context.Context) error {
	// Stub: real execution logic is injected by the plugin registry.
	// A configuredNode that has not been replaced by a real executor is
	// effectively a no-op node, which is safe by design.
	return nil
}
