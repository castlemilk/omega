package framework

import (
	"sync"
)

// ── Capability ────────────────────────────────────────────────────────────────

// Capability is a named thing a node can do.
// New capabilities are added here; the orchestrator routes work based on them
// without knowing about the implementing domain at compile time.
type Capability string

const (
	CapabilitySignalGeneration     Capability = "signal_generation"
	CapabilityRiskAssessment       Capability = "risk_assessment"
	CapabilityBacktesting          Capability = "backtesting"
	CapabilityDataIngestion        Capability = "data_ingestion"
	CapabilityPortfolioOptimization Capability = "portfolio_optimization"
	CapabilityAnomalyDetection     Capability = "anomaly_detection"
	CapabilityForecasting          Capability = "forecasting"
	CapabilityExecution            Capability = "execution"
)

// CapabilityProvider is implemented by any node that exposes capabilities to the orchestrator.
type CapabilityProvider interface {
	// NodeID returns the unique identifier of the node.
	NodeID() string
	// Capabilities returns the capabilities this node provides.
	Capabilities() []Capability
}

// ── NegotiationResult ─────────────────────────────────────────────────────────

// NegotiationResult is returned by CapabilityRegistry.Negotiate.
type NegotiationResult struct {
	Satisfied bool
	Available []Capability
	Missing   []Capability
}

// ── CapabilityRegistry ────────────────────────────────────────────────────────

// CapabilityRegistry maps capabilities to the nodes that provide them.
// The orchestrator queries it before dispatching work, enabling fully dynamic
// composition: add a new capability, and the orchestrator uses it automatically.
type CapabilityRegistry struct {
	mu       sync.RWMutex
	// nodeID → provider
	nodes    map[string]CapabilityProvider
	// capability → set of nodeIDs
	capIndex map[Capability]map[string]struct{}
}

// NewCapabilityRegistry returns an empty CapabilityRegistry.
func NewCapabilityRegistry() *CapabilityRegistry {
	return &CapabilityRegistry{
		nodes:    make(map[string]CapabilityProvider),
		capIndex: make(map[Capability]map[string]struct{}),
	}
}

// Register adds a CapabilityProvider and indexes all its capabilities.
func (r *CapabilityRegistry) Register(p CapabilityProvider) {
	r.mu.Lock()
	defer r.mu.Unlock()

	id := p.NodeID()
	r.nodes[id] = p
	for _, cap := range p.Capabilities() {
		if r.capIndex[cap] == nil {
			r.capIndex[cap] = make(map[string]struct{})
		}
		r.capIndex[cap][id] = struct{}{}
	}
}

// Unregister removes a node and all its indexed capabilities.
func (r *CapabilityRegistry) Unregister(nodeID string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	p, ok := r.nodes[nodeID]
	if !ok {
		return
	}
	for _, cap := range p.Capabilities() {
		delete(r.capIndex[cap], nodeID)
		if len(r.capIndex[cap]) == 0 {
			delete(r.capIndex, cap)
		}
	}
	delete(r.nodes, nodeID)
}

// ProvidersFor returns all CapabilityProviders that offer the given capability.
func (r *CapabilityRegistry) ProvidersFor(cap Capability) []CapabilityProvider {
	r.mu.RLock()
	defer r.mu.RUnlock()

	ids := r.capIndex[cap]
	result := make([]CapabilityProvider, 0, len(ids))
	for id := range ids {
		result = append(result, r.nodes[id])
	}
	return result
}

// HasCapability reports whether at least one registered node provides cap.
func (r *CapabilityRegistry) HasCapability(cap Capability) bool {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return len(r.capIndex[cap]) > 0
}

// AllCapabilities returns the deduplicated set of capabilities currently available.
func (r *CapabilityRegistry) AllCapabilities() []Capability {
	r.mu.RLock()
	defer r.mu.RUnlock()
	caps := make([]Capability, 0, len(r.capIndex))
	for cap := range r.capIndex {
		caps = append(caps, cap)
	}
	return caps
}

// Negotiate checks whether all requested capabilities are available.
// Returns a NegotiationResult describing which (if any) are missing.
func (r *CapabilityRegistry) Negotiate(requested []Capability) NegotiationResult {
	r.mu.RLock()
	defer r.mu.RUnlock()

	var missing []Capability
	for _, cap := range requested {
		if len(r.capIndex[cap]) == 0 {
			missing = append(missing, cap)
		}
	}
	return NegotiationResult{
		Satisfied: len(missing) == 0,
		Available: r.allCapabilitiesLocked(),
		Missing:   missing,
	}
}

func (r *CapabilityRegistry) allCapabilitiesLocked() []Capability {
	caps := make([]Capability, 0, len(r.capIndex))
	for cap := range r.capIndex {
		caps = append(caps, cap)
	}
	return caps
}
