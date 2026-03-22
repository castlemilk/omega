// Package core — orchestrator.go
//
// Orchestrator is the Go-side cycle runner for the Omega framework.
// It manages a registry of NodeExecutors, runs timed cycles, and wires
// together the entire observability layer:
//
//   - observability.EventBus  → lifecycle events (started/completed/node state)
//   - observability.Metrics   → Prometheus counters & histograms
//   - NodeCircuitManager      → per-node circuit breakers
//   - observability.CompositeHealth → pre-cycle health gate
package core

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"time"

	omegaerrs "github.com/benebsworth/omega/internal/errors"
	"github.com/benebsworth/omega/internal/observability"
)

// ---------------------------------------------------------------------------
// NodeExecutor — interface implemented by each "node" in the system
// ---------------------------------------------------------------------------

// NodeExecutor is the interface every node must satisfy.
// The orchestrator calls Execute on healthy, circuit-allowed nodes each cycle.
type NodeExecutor interface {
	// NodeID returns a stable, unique identifier for this node.
	NodeID() string

	// Execute runs the node's logic for one cycle.
	// It must respect ctx cancellation and return an error on failure.
	Execute(ctx context.Context) error
}

// nodeEntry holds runtime metadata for a registered node.
type nodeEntry struct {
	executor NodeExecutor
	// registered at timestamp
	registeredAt time.Time
	// last known state ("active", "skipped", "demoted")
	state string
}

// ---------------------------------------------------------------------------
// OrchestratorConfig
// ---------------------------------------------------------------------------

// OrchestratorConfig holds tunable parameters for the Orchestrator.
type OrchestratorConfig struct {
	// CycleTimeout is the maximum time allotted to a single cycle.
	CycleTimeout time.Duration

	// NodeTimeout is the maximum time allotted to a single node execution within a cycle.
	NodeTimeout time.Duration

	// CircuitBreaker config applied uniformly to all nodes.
	CircuitBreaker observability.CircuitBreakerConfig

	// HealthCheckTimeout is the timeout for the pre-cycle health gate.
	HealthCheckTimeout time.Duration
}

// DefaultOrchestratorConfig returns sensible defaults.
func DefaultOrchestratorConfig() OrchestratorConfig {
	return OrchestratorConfig{
		CycleTimeout:       5 * time.Minute,
		NodeTimeout:        30 * time.Second,
		CircuitBreaker:     observability.DefaultCircuitBreakerConfig(),
		HealthCheckTimeout: 5 * time.Second,
	}
}

// ---------------------------------------------------------------------------
// Orchestrator
// ---------------------------------------------------------------------------

// Orchestrator runs timed orchestration cycles across all registered nodes.
// It is the central wiring point for the observability layer.
type Orchestrator struct {
	mu     sync.RWMutex
	cfg    OrchestratorConfig
	nodes  map[string]*nodeEntry
	logger *slog.Logger

	// Observability
	bus     *observability.EventBus
	metrics *observability.Metrics
	health  *observability.CompositeHealth
	circuit *NodeCircuitManager

	cycleCounter int64
}

// NewOrchestrator creates a fully wired Orchestrator.
// All observability components are required; pass nil metrics/health/bus to
// disable those subsystems (circuit breaker is always active).
func NewOrchestrator(
	cfg OrchestratorConfig,
	bus *observability.EventBus,
	metrics *observability.Metrics,
	health *observability.CompositeHealth,
	logger *slog.Logger,
) *Orchestrator {
	if logger == nil {
		logger = slog.Default()
	}
	return &Orchestrator{
		cfg:     cfg,
		nodes:   make(map[string]*nodeEntry),
		logger:  logger,
		bus:     bus,
		metrics: metrics,
		health:  health,
		circuit: NewNodeCircuitManager(cfg.CircuitBreaker, metrics, bus, logger),
	}
}

// ---------------------------------------------------------------------------
// Node registry
// ---------------------------------------------------------------------------

// Register adds a node to the orchestrator. Safe to call concurrently.
func (o *Orchestrator) Register(exec NodeExecutor) {
	o.mu.Lock()
	defer o.mu.Unlock()

	id := exec.NodeID()
	if _, exists := o.nodes[id]; exists {
		o.logger.Warn("orchestrator: node already registered, skipping", "node_id", id)
		return
	}
	o.nodes[id] = &nodeEntry{
		executor:     exec,
		registeredAt: time.Now(),
		state:        "active",
	}
	o.logger.Info("orchestrator: node registered", "node_id", id)

	if o.bus != nil {
		o.bus.PublishNodeRegistered(observability.NodeRegisteredPayload{NodeID: id})
	}
	o.emitNodeStateChanged(id, "", "active", "registered")
}

// Deregister removes a node from the orchestrator and cleans up its circuit.
func (o *Orchestrator) Deregister(nodeID string) {
	o.mu.Lock()
	defer o.mu.Unlock()

	if _, exists := o.nodes[nodeID]; !exists {
		return
	}
	delete(o.nodes, nodeID)
	o.circuit.Remove(nodeID)
	o.logger.Info("orchestrator: node deregistered", "node_id", nodeID)
	o.emitNodeStateChanged(nodeID, "active", "deregistered", "explicitly deregistered")
}


// ---------------------------------------------------------------------------
// Cycle execution
// ---------------------------------------------------------------------------

// RunCycle executes one full orchestration cycle and returns a CycleResult.
// It is safe to call concurrently; each invocation gets its own cycle ID.
func (o *Orchestrator) RunCycle(ctx context.Context) (*CycleResult, error) {
	cycleID := o.nextCycleID()
	cycleCtx, cancel := context.WithTimeout(ctx, o.cfg.CycleTimeout)
	defer cancel()

	start := time.Now()

	// ── 1. Pre-cycle health gate ──────────────────────────────────────────
	activeNodes := o.snapshotActiveNodes()

	if o.health != nil {
		hCtx, hCancel := context.WithTimeout(cycleCtx, o.cfg.HealthCheckTimeout)
		report := o.health.Check(hCtx)
		hCancel()

		if report.State == observability.HealthStateUnhealthy {
			o.logger.Warn("orchestrator: system unhealthy, aborting cycle",
				"cycle_id", cycleID,
				"health_state", report.State.String(),
			)
			return nil, fmt.Errorf("cycle %d aborted: system health is %s", cycleID, report.State)
		}
	}

	// ── 2. Emit CycleStarted ─────────────────────────────────────────────
	ids := make([]string, 0, len(activeNodes))
	for _, e := range activeNodes {
		ids = append(ids, e.executor.NodeID())
	}
	if o.bus != nil {
		o.bus.PublishCycleStarted(observability.CycleStartedPayload{
			Cycle:       cycleID,
			ActiveNodes: ids,
		})
	}
	o.logger.Info("orchestrator: cycle started", "cycle_id", cycleID, "nodes", len(activeNodes))

	// ── 3. Execute nodes ──────────────────────────────────────────────────
	results := make(map[string]bool, len(activeNodes))
	errors := make(map[string]string)

	for _, entry := range activeNodes {
		nodeID := entry.executor.NodeID()

		// Circuit breaker gate
		if !o.circuit.AllowExecution(nodeID) {
			o.logger.Info("orchestrator: node skipped (circuit open)", "node_id", nodeID, "cycle_id", cycleID)
			results[nodeID] = false
			errors[nodeID] = observability.ErrCircuitOpen.Error()
			o.updateNodeState(nodeID, "active", "skipped", "circuit open")
			continue
		}

		// Per-node timeout
		nodeCtx, nodeCancel := context.WithTimeout(cycleCtx, o.cfg.NodeTimeout)
		nodeStart := time.Now()
		err := entry.executor.Execute(nodeCtx)
		nodeDur := time.Since(nodeStart)
		nodeCancel()

		if err != nil {
			o.circuit.RecordFailure(nodeID)
			results[nodeID] = false
			errors[nodeID] = err.Error()
			cls := omegaerrs.Classify(err)
			o.logger.Error("orchestrator: node execution failed",
				"node_id", nodeID, "cycle_id", cycleID, "error", err,
				"error_class", cls.Class, "error_code", cls.Code, "retryable", cls.Retryable)
			if o.metrics != nil {
				o.metrics.RecordNodeExecution(nodeID, nodeDur.Seconds(), false)
			}
		} else {
			o.circuit.RecordSuccess(nodeID)
			results[nodeID] = true
			if o.metrics != nil {
				o.metrics.RecordNodeExecution(nodeID, nodeDur.Seconds(), true)
			}
		}
	}

	duration := time.Since(start)

	// ── 4. Record cycle metrics ───────────────────────────────────────────
	if o.metrics != nil {
		status := "success"
		for _, ok := range results {
			if !ok {
				status = "error"
				break
			}
		}
		o.metrics.RecordCycle(duration.Seconds(), status)
	}

	// ── 5. Emit CycleCompleted ────────────────────────────────────────────
	if o.bus != nil {
		o.bus.PublishCycleCompleted(observability.CycleCompletedPayload{
			Cycle:        cycleID,
			DurationSecs: duration.Seconds(),
			NodeCount:    len(activeNodes),
			Success:      len(errors) == 0,
			ErrorText:    fmt.Sprintf("%d node(s) failed", len(errors)),
		})
	}
	o.logger.Info("orchestrator: cycle completed",
		"cycle_id", cycleID,
		"duration_ms", duration.Milliseconds(),
		"nodes_ok", len(results)-len(errors),
		"nodes_failed", len(errors),
	)

	return &CycleResult{
		CycleID:  cycleID,
		Duration: duration,
		Results:  results,
		Errors:   errors,
	}, nil
}

// CycleResult is the outcome of a single RunCycle invocation.
type CycleResult struct {
	CycleID  int64
	Duration time.Duration
	Results  map[string]bool
	Errors   map[string]string
}

// ---------------------------------------------------------------------------
// Node promotion / demotion helpers (called externally by evaluation layers)
// ---------------------------------------------------------------------------

// PromoteNode records a node promotion event.
func (o *Orchestrator) PromoteNode(nodeID string, fromLevel, toLevel float64) {
	o.logger.Info("orchestrator: node promoted", "node_id", nodeID,
		"from", fromLevel, "to", toLevel)
	if o.bus != nil {
		o.bus.PublishNodePromoted(observability.NodePromotedPayload{
			NodeID:    nodeID,
			FromLevel: fromLevel,
			ToLevel:   toLevel,
		})
	}
	if o.metrics != nil {
		o.metrics.RecordAutonomyPromotion(nodeID)
		o.metrics.SetNodeAutonomyLevel(nodeID, toLevel)
	}
	o.updateNodeState(nodeID, "active", "active", fmt.Sprintf("promoted %.2f→%.2f", fromLevel, toLevel))
}

// DemoteNode records a node demotion event.
func (o *Orchestrator) DemoteNode(nodeID, reason string, fromLevel, toLevel float64) {
	o.logger.Warn("orchestrator: node demoted", "node_id", nodeID,
		"from", fromLevel, "to", toLevel, "reason", reason)
	if o.bus != nil {
		o.bus.PublishNodeDemoted(observability.NodeDemotedPayload{
			NodeID:    nodeID,
			FromLevel: fromLevel,
			ToLevel:   toLevel,
			Reason:    reason,
		})
	}
	if o.metrics != nil {
		o.metrics.SetNodeAutonomyLevel(nodeID, toLevel)
	}
	o.updateNodeState(nodeID, "active", "demoted", reason)
}

// EmitSafetyViolation records a safety gate firing for a node.
func (o *Orchestrator) EmitSafetyViolation(nodeID, gate, severity, details string) {
	o.logger.Warn("orchestrator: safety violation",
		"node_id", nodeID, "gate", gate, "severity", severity, "details", details)
	if o.bus != nil {
		o.bus.PublishSafetyViolation(observability.SafetyViolationPayload{
			NodeID:     nodeID,
			Layer:      0,
			Constraint: gate,
		})
	}
	if o.metrics != nil {
		o.metrics.RecordSafetyViolation("0")
	}
}

// EmitAdversarialAlert records an adversarial ring alert.
func (o *Orchestrator) EmitAdversarialAlert(ring int, nodeID string, score, threshold float64) {
	o.logger.Warn("orchestrator: adversarial alert",
		"ring", ring, "node_id", nodeID, "score", score, "threshold", threshold)
	if o.bus != nil {
		o.bus.PublishAdversarialVeto(observability.AdversarialVetoPayload{
			NodeID: nodeID,
			Ring:   ring,
			Reason: fmt.Sprintf("score %.4f exceeds threshold %.4f", score, threshold),
		})
	}
	if o.metrics != nil {
		o.metrics.RecordAdversarialVeto(nodeID, fmt.Sprintf("%d", ring))
	}
}

// ---------------------------------------------------------------------------
// internal helpers
// ---------------------------------------------------------------------------

func (o *Orchestrator) nextCycleID() int64 {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.cycleCounter++
	return o.cycleCounter
}

func (o *Orchestrator) snapshotActiveNodes() []*nodeEntry {
	o.mu.RLock()
	defer o.mu.RUnlock()
	entries := make([]*nodeEntry, 0, len(o.nodes))
	for _, e := range o.nodes {
		entries = append(entries, e)
	}
	return entries
}

func (o *Orchestrator) updateNodeState(nodeID, oldState, newState, reason string) {
	o.mu.Lock()
	if e, ok := o.nodes[nodeID]; ok {
		e.state = newState
	}
	o.mu.Unlock()
	o.emitNodeStateChanged(nodeID, oldState, newState, reason)
}

func (o *Orchestrator) emitNodeStateChanged(nodeID, oldState, newState, reason string) {
	// NodeStateChangedEvent is a domain struct; log it but do not publish it on
	// the bus directly (EventBus only carries observability.EventPayload).
	o.logger.Debug("node state changed",
		"node_id", nodeID,
		"old_state", oldState,
		"new_state", newState,
		"reason", reason,
	)
	// Store for potential diagnostics consumers.
	_ = NodeStateChangedEvent{
		NodeID:   nodeID,
		OldState: oldState,
		NewState: newState,
		Reason:   reason,
	}
}

