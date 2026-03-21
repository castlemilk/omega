// Package core — capacity.go
//
// CapacityManager tracks how many nodes the system can support and provides
// auto-scaling recommendations based on observed load metrics.
package core

import (
	"fmt"
	"sync"
)

// ---------------------------------------------------------------------------
// ResourceEstimation
// ---------------------------------------------------------------------------

// ResourceEstimation is a rough estimate of the resources a node will consume.
type ResourceEstimation struct {
	// EstimatedMemoryMB is the expected heap footprint in megabytes.
	EstimatedMemoryMB float64

	// EstimatedCPUPct is the expected CPU utilisation as a percentage (0–100).
	EstimatedCPUPct float64
}

// ---------------------------------------------------------------------------
// ScaleRecommendation
// ---------------------------------------------------------------------------

// ScaleAction is the direction of a scaling recommendation.
type ScaleAction string

const (
	ScaleActionAdd    ScaleAction = "add"
	ScaleActionRemove ScaleAction = "remove"
	ScaleActionNone   ScaleAction = "none"
)

// ScaleRecommendation is the result of an AutoScale evaluation.
type ScaleRecommendation struct {
	Action ScaleAction
	Count  int
	Reason string
}

// ---------------------------------------------------------------------------
// CapacityManager
// ---------------------------------------------------------------------------

// CapacityManager tracks the system's capacity limits and current resource
// usage. All methods are safe for concurrent use.
type CapacityManager struct {
	mu       sync.RWMutex
	maxNodes int

	// tracked holds the resource footprint of each currently registered node.
	tracked map[string]ResourceEstimation
}

// NewCapacityManager creates a CapacityManager with the given hard node limit.
func NewCapacityManager(maxNodes int) *CapacityManager {
	if maxNodes <= 0 {
		maxNodes = 32 // sensible default matching the config default
	}
	return &CapacityManager{
		maxNodes: maxNodes,
		tracked:  make(map[string]ResourceEstimation),
	}
}

// CanAddNode returns true if the system has capacity for at least one more node.
func (m *CapacityManager) CanAddNode() bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return len(m.tracked) < m.maxNodes
}

// ResourceEstimate returns a conservative estimate of the resources a node with
// the given config would consume. The heuristics are intentionally simple; they
// are meant to catch over-provisioning at config time, not to replace profiling.
func (m *CapacityManager) ResourceEstimate(config NodeConfig) ResourceEstimation {
	est := ResourceEstimation{
		EstimatedMemoryMB: 64.0,
		EstimatedCPUPct:   5.0,
	}

	switch config.NodeType {
	case "quant":
		est.EstimatedMemoryMB = 128.0
		est.EstimatedCPUPct = 10.0
	case "adversarial":
		est.EstimatedMemoryMB = 256.0
		est.EstimatedCPUPct = 20.0
	case "memory":
		est.EstimatedMemoryMB = 512.0
		est.EstimatedCPUPct = 8.0
	}

	return est
}

// TrackNode records a node's estimated resource footprint.
// If the node is already tracked its estimate is replaced.
func (m *CapacityManager) TrackNode(nodeID string, est ResourceEstimation) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.tracked[nodeID] = est
}

// UntrackNode removes a node's resource record.
func (m *CapacityManager) UntrackNode(nodeID string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.tracked, nodeID)
}

// NodeCount returns the number of currently tracked nodes.
func (m *CapacityManager) NodeCount() int {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return len(m.tracked)
}

// TotalMemoryMB returns the sum of estimated memory usage across all tracked nodes.
func (m *CapacityManager) TotalMemoryMB() float64 {
	m.mu.RLock()
	defer m.mu.RUnlock()
	var total float64
	for _, e := range m.tracked {
		total += e.EstimatedMemoryMB
	}
	return total
}

// TotalCPUPct returns the sum of estimated CPU usage across all tracked nodes.
func (m *CapacityManager) TotalCPUPct() float64 {
	m.mu.RLock()
	defer m.mu.RUnlock()
	var total float64
	for _, e := range m.tracked {
		total += e.EstimatedCPUPct
	}
	return total
}

// MaxNodes returns the configured hard limit on the number of nodes.
func (m *CapacityManager) MaxNodes() int {
	return m.maxNodes
}

// AutoScale evaluates the provided metrics and returns a scaling recommendation.
//
// Recognised metric keys:
//   - "load"       — normalised system load (0.0–1.0); add when > 0.8, remove when < 0.2
//   - "error_rate" — fraction of failing nodes (0.0–1.0); remove when > 0.5
//   - "memory_mb"  — actual measured memory usage; remove when > 90% of estimated capacity
func (m *CapacityManager) AutoScale(metrics map[string]float64) ScaleRecommendation {
	m.mu.RLock()
	current := len(m.tracked)
	totalMem := m.TotalMemoryMB() // reuses RLock internally — OK because we call after releasing below
	m.mu.RUnlock()

	load := metrics["load"]
	errorRate := metrics["error_rate"]
	actualMemMB := metrics["memory_mb"]

	// Error rate too high — shed a node.
	if errorRate > 0.5 && current > 1 {
		return ScaleRecommendation{
			Action: ScaleActionRemove,
			Count:  1,
			Reason: fmt.Sprintf("error_rate %.2f exceeds 0.50 threshold", errorRate),
		}
	}

	// Memory pressure — shed a node.
	if actualMemMB > 0 && totalMem > 0 && actualMemMB > totalMem*0.9 {
		return ScaleRecommendation{
			Action: ScaleActionRemove,
			Count:  1,
			Reason: fmt.Sprintf("memory %.0f MB exceeds 90%% of estimated %.0f MB", actualMemMB, totalMem),
		}
	}

	// High load — add a node if capacity allows.
	if load > 0.8 && current < m.maxNodes {
		return ScaleRecommendation{
			Action: ScaleActionAdd,
			Count:  1,
			Reason: fmt.Sprintf("load %.2f exceeds 0.80 threshold", load),
		}
	}

	// Low load — remove a node if more than one remains.
	if load > 0 && load < 0.2 && current > 1 {
		return ScaleRecommendation{
			Action: ScaleActionRemove,
			Count:  1,
			Reason: fmt.Sprintf("load %.2f below 0.20 threshold", load),
		}
	}

	return ScaleRecommendation{Action: ScaleActionNone}
}
