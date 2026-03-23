// weight_adapter.go — EMA online prior for routing weight adaptation.
//
// RoutingWeightAdapter provides lightweight online updates to per-node routing
// priors without requiring full attention model retraining. It operates as the
// "layer-level" improvement loop described in the spec (every 50 cycles).
//
// This creates a two-level routing system:
//   - Attention model: goal-conditioned routing weights (retrained weekly)
//   - RoutingWeightAdapter: experience-conditioned prior (updated per-outcome)
//
// The AttentionRouter multiplies the prior additively into pre-softmax scores
// as a centred bias: bias = prior − 0.5 ∈ [−0.5, +0.5].

package coordination

import (
	"sync"
)

// RoutingWeightAdapter provides per-node EMA routing priors.
// Safe for concurrent use.
type RoutingWeightAdapter struct {
	mu     sync.RWMutex
	priors map[string]float32 // node_id → prior ∈ [0.0, 1.0]
	decay  float32            // EMA decay α (higher = slower adaptation)
}

// NewRoutingWeightAdapter creates a RoutingWeightAdapter with the given EMA decay.
// decay=0.95 is the default from the spec (slow, stable adaptation).
func NewRoutingWeightAdapter(decay float32) *RoutingWeightAdapter {
	if decay <= 0 || decay >= 1 {
		decay = 0.95
	}
	return &RoutingWeightAdapter{
		priors: make(map[string]float32),
		decay:  decay,
	}
}

// UpdateFromOutcome applies a Bayesian-style EMA update:
//
//	new_prior = decay * current + (1 - decay) * outcomeScore
//
// outcomeScore ∈ [0, 1]; positive outcomes nudge the prior up, negative down.
// The result is clamped to [0.0, 1.0].
func (a *RoutingWeightAdapter) UpdateFromOutcome(nodeID string, outcomeScore float32) {
	a.mu.Lock()
	defer a.mu.Unlock()

	current, ok := a.priors[nodeID]
	if !ok {
		current = 0.5 // neutral prior for new nodes
	}
	updated := a.decay*current + (1-a.decay)*outcomeScore
	a.priors[nodeID] = clampF32(updated, 0.0, 1.0)
}

// PriorFor returns the current routing prior for a node.
// Returns 0.5 (neutral) for nodes with no recorded history.
func (a *RoutingWeightAdapter) PriorFor(nodeID string) float32 {
	a.mu.RLock()
	defer a.mu.RUnlock()

	if p, ok := a.priors[nodeID]; ok {
		return p
	}
	return 0.5
}

// Snapshot returns a copy of all current priors for diagnostics.
func (a *RoutingWeightAdapter) Snapshot() map[string]float32 {
	a.mu.RLock()
	defer a.mu.RUnlock()

	out := make(map[string]float32, len(a.priors))
	for k, v := range a.priors {
		out[k] = v
	}
	return out
}

// Reset clears the prior for a specific node (e.g. after node replacement).
func (a *RoutingWeightAdapter) Reset(nodeID string) {
	a.mu.Lock()
	delete(a.priors, nodeID)
	a.mu.Unlock()
}

// Decay returns the configured EMA decay factor.
func (a *RoutingWeightAdapter) Decay() float32 {
	return a.decay
}
