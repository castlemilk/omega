// Package registry implements the Go-side node registry — the source of truth
// for dynamic node registration, capability discovery, and health tracking.
//
// Python nodes register themselves by calling Register on this registry (or via
// the NodeService Connect-RPC endpoint which delegates here).  The registry
// drives periodic heartbeat checks and marks unresponsive nodes offline.
package registry

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"go.opentelemetry.io/otel/metric"

	"github.com/benebsworth/omega/internal/telemetry"
)

// NodeState represents the health state of a registered node.
type NodeState string

const (
	NodeStateHealthy  NodeState = "healthy"
	NodeStateDegraded NodeState = "degraded"
	NodeStateOffline  NodeState = "offline"
)

// defaultHeartbeatTimeout is how long a node may go without a heartbeat before
// it is marked offline by the health loop.
const defaultHeartbeatTimeout = 30 * time.Second

// NodeEntry holds all metadata for a registered node.
type NodeEntry struct {
	ID           string
	Name         string
	Version      string
	Address      string // base URL of the node's Connect-RPC server, e.g. "http://localhost:50051"
	Capabilities []string
	Language     string // e.g. "python", "go"
	Health       float64
	State        NodeState
	RegisteredAt time.Time
	LastHeartbeat time.Time
}

// NodeRegistry is a thread-safe, capability-indexed store of registered nodes.
// It also runs a background health loop that marks unresponsive nodes offline.
type NodeRegistry struct {
	mu       sync.RWMutex
	nodes    map[string]*NodeEntry
	capIndex map[string][]string // capability → []nodeID

	heartbeatTimeout time.Duration

	// OTel instruments
	nodesTotal   metric.Int64UpDownCounter
	healthChecks metric.Int64Counter
}

// NewNodeRegistry creates and initialises a NodeRegistry with OTel instruments.
func NewNodeRegistry() (*NodeRegistry, error) {
	m := telemetry.Meter()

	nodesTotal, err := m.Int64UpDownCounter(
		telemetry.MetricRegistryNodesTotal,
		metric.WithDescription("Number of registered nodes by state"),
	)
	if err != nil {
		return nil, fmt.Errorf("registry: create nodes gauge: %w", err)
	}

	healthChecks, err := m.Int64Counter(
		telemetry.MetricRegistryHealthChecks,
		metric.WithDescription("Total registry health-check ticks executed"),
	)
	if err != nil {
		return nil, fmt.Errorf("registry: create health_checks counter: %w", err)
	}

	return &NodeRegistry{
		nodes:            make(map[string]*NodeEntry),
		capIndex:         make(map[string][]string),
		heartbeatTimeout: defaultHeartbeatTimeout,
		nodesTotal:       nodesTotal,
		healthChecks:     healthChecks,
	}, nil
}

// Register adds a node to the registry. Returns an error if the ID is empty or
// the address is empty. Re-registering an existing node ID overwrites the entry.
func (r *NodeRegistry) Register(entry NodeEntry) error {
	if entry.ID == "" {
		return errors.New("registry: node ID must not be empty")
	}
	if entry.Address == "" {
		return errors.New("registry: node address must not be empty")
	}
	if entry.State == "" {
		entry.State = NodeStateHealthy
	}
	if entry.RegisteredAt.IsZero() {
		entry.RegisteredAt = time.Now()
	}
	if entry.LastHeartbeat.IsZero() {
		entry.LastHeartbeat = time.Now()
	}

	r.mu.Lock()
	defer r.mu.Unlock()

	// If re-registering, remove old capability index entries first.
	if old, exists := r.nodes[entry.ID]; exists {
		r.removeFromCapIndex(old)
		r.adjustNodesGauge(context.Background(), old.State, -1)
	}

	cp := entry // copy to avoid external mutation
	r.nodes[entry.ID] = &cp
	r.addToCapIndex(&cp)
	r.adjustNodesGauge(context.Background(), cp.State, 1)
	return nil
}

// Deregister removes a node from the registry and the capability index.
// Silently no-ops if the node is not found.
func (r *NodeRegistry) Deregister(nodeID string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	entry, exists := r.nodes[nodeID]
	if !exists {
		return
	}
	r.removeFromCapIndex(entry)
	r.adjustNodesGauge(context.Background(), entry.State, -1)
	delete(r.nodes, nodeID)
}

// Get returns a copy of the NodeEntry for the given ID.
// The second return value is false when the node is not registered.
func (r *NodeRegistry) Get(nodeID string) (NodeEntry, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	entry, exists := r.nodes[nodeID]
	if !exists {
		return NodeEntry{}, false
	}
	return *entry, true
}

// All returns a snapshot of every registered node.
func (r *NodeRegistry) All() []NodeEntry {
	r.mu.RLock()
	defer r.mu.RUnlock()

	out := make([]NodeEntry, 0, len(r.nodes))
	for _, e := range r.nodes {
		out = append(out, *e)
	}
	return out
}

// FindByCapability returns all registered nodes that advertise the given
// capability.  If healthyOnly is true only healthy and degraded nodes are
// returned (offline nodes are excluded).
func (r *NodeRegistry) FindByCapability(capability string, healthyOnly bool) []NodeEntry {
	r.mu.RLock()
	defer r.mu.RUnlock()

	ids := r.capIndex[capability]
	out := make([]NodeEntry, 0, len(ids))
	for _, id := range ids {
		entry, exists := r.nodes[id]
		if !exists {
			continue
		}
		if healthyOnly && entry.State == NodeStateOffline {
			continue
		}
		out = append(out, *entry)
	}
	return out
}

// UpdateHealth updates the health score and state for an existing node.
// No-ops if the node is not registered.
func (r *NodeRegistry) UpdateHealth(nodeID string, health float64, state NodeState) {
	r.mu.Lock()
	defer r.mu.Unlock()

	entry, exists := r.nodes[nodeID]
	if !exists {
		return
	}

	if entry.State != state {
		r.adjustNodesGauge(context.Background(), entry.State, -1)
		r.adjustNodesGauge(context.Background(), state, 1)
		entry.State = state
	}
	entry.Health = health
}

// Heartbeat records a keepalive for the given node, resetting its last-seen
// timestamp and transitioning it back to healthy if it was offline.
func (r *NodeRegistry) Heartbeat(nodeID string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	entry, exists := r.nodes[nodeID]
	if !exists {
		return
	}
	entry.LastHeartbeat = time.Now()
	if entry.State == NodeStateOffline {
		r.adjustNodesGauge(context.Background(), NodeStateOffline, -1)
		entry.State = NodeStateHealthy
		r.adjustNodesGauge(context.Background(), NodeStateHealthy, 1)
	}
}

// StartHealthLoop launches a background goroutine that periodically checks
// every node's last heartbeat.  Nodes that have not sent a heartbeat within
// heartbeatTimeout are marked offline.  The loop runs until ctx is cancelled.
func (r *NodeRegistry) StartHealthLoop(ctx context.Context, interval time.Duration) {
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				r.runHealthCheck(ctx)
			}
		}
	}()
}

// runHealthCheck sweeps all registered nodes and marks those whose heartbeat
// has expired as offline.
func (r *NodeRegistry) runHealthCheck(ctx context.Context) {
	r.healthChecks.Add(ctx, 1)

	_, span := telemetry.Tracer().Start(ctx, telemetry.SpanRegistryHealthCheck)
	defer span.End()

	now := time.Now()
	r.mu.Lock()
	defer r.mu.Unlock()

	for _, entry := range r.nodes {
		if entry.State == NodeStateOffline {
			continue
		}
		if now.Sub(entry.LastHeartbeat) > r.heartbeatTimeout {
			r.adjustNodesGauge(ctx, entry.State, -1)
			entry.State = NodeStateOffline
			r.adjustNodesGauge(ctx, NodeStateOffline, 1)
		}
	}
}

// ── internal helpers ──────────────────────────────────────────────────────────

func (r *NodeRegistry) addToCapIndex(entry *NodeEntry) {
	for _, cap := range entry.Capabilities {
		r.capIndex[cap] = appendUnique(r.capIndex[cap], entry.ID)
	}
}

func (r *NodeRegistry) removeFromCapIndex(entry *NodeEntry) {
	for _, cap := range entry.Capabilities {
		r.capIndex[cap] = removeString(r.capIndex[cap], entry.ID)
		if len(r.capIndex[cap]) == 0 {
			delete(r.capIndex, cap)
		}
	}
}

func (r *NodeRegistry) adjustNodesGauge(ctx context.Context, state NodeState, delta int64) {
	r.nodesTotal.Add(ctx, delta,
		metric.WithAttributes(
			telemetry.AttrRegistryNodeState.String(string(state)),
		),
	)
}

func appendUnique(slice []string, s string) []string {
	for _, v := range slice {
		if v == s {
			return slice
		}
	}
	return append(slice, s)
}

func removeString(slice []string, s string) []string {
	out := slice[:0]
	for _, v := range slice {
		if v != s {
			out = append(out, v)
		}
	}
	return out
}
