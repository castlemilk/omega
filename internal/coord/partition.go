package coord

import (
	"crypto/sha256"
	"encoding/binary"
	"sort"
	"sync"
)

// PartitionManager assigns nodes to workers using rendezvous (highest random weight) hashing.
// This ensures minimal reassignment when workers join or leave.
type PartitionManager struct {
	mu      sync.RWMutex
	workers []string
	nodes   []string
}

// NewPartitionManager creates a PartitionManager with an initial set of workers and nodes.
func NewPartitionManager(workers, nodes []string) *PartitionManager {
	pm := &PartitionManager{}
	pm.workers = append(pm.workers, workers...)
	pm.nodes = append(pm.nodes, nodes...)
	sort.Strings(pm.workers)
	sort.Strings(pm.nodes)
	return pm
}

// AddWorker registers a new worker and triggers rebalancing.
func (pm *PartitionManager) AddWorker(workerID string) {
	pm.mu.Lock()
	defer pm.mu.Unlock()
	for _, w := range pm.workers {
		if w == workerID {
			return
		}
	}
	pm.workers = append(pm.workers, workerID)
	sort.Strings(pm.workers)
}

// RemoveWorker deregisters a worker and triggers rebalancing.
func (pm *PartitionManager) RemoveWorker(workerID string) {
	pm.mu.Lock()
	defer pm.mu.Unlock()
	for i, w := range pm.workers {
		if w == workerID {
			pm.workers = append(pm.workers[:i], pm.workers[i+1:]...)
			return
		}
	}
}

// AddNode registers a new node to be distributed across workers.
func (pm *PartitionManager) AddNode(nodeID string) {
	pm.mu.Lock()
	defer pm.mu.Unlock()
	for _, n := range pm.nodes {
		if n == nodeID {
			return
		}
	}
	pm.nodes = append(pm.nodes, nodeID)
	sort.Strings(pm.nodes)
}

// RemoveNode deregisters a node.
func (pm *PartitionManager) RemoveNode(nodeID string) {
	pm.mu.Lock()
	defer pm.mu.Unlock()
	for i, n := range pm.nodes {
		if n == nodeID {
			pm.nodes = append(pm.nodes[:i], pm.nodes[i+1:]...)
			return
		}
	}
}

// Rebalance recalculates assignments. Under rendezvous hashing the assignments
// update automatically — this method exists for explicit triggering.
func (pm *PartitionManager) Rebalance() {
	// Rendezvous hashing is stateless; assignments are computed on read.
	// Rebalance is a no-op here but is provided as an explicit hook for
	// callers that want to signal topology changes.
}

// GetAssignment returns the nodes assigned to workerID.
// Uses the rendezvous (highest random weight) algorithm: each node is assigned
// to the worker that produces the highest hash(worker, node).
func (pm *PartitionManager) GetAssignment(workerID string) []string {
	pm.mu.RLock()
	workers := append([]string(nil), pm.workers...)
	nodes := append([]string(nil), pm.nodes...)
	pm.mu.RUnlock()

	if len(workers) == 0 {
		return nil
	}

	var assigned []string
	for _, node := range nodes {
		owner := rendezVousOwner(workers, node)
		if owner == workerID {
			assigned = append(assigned, node)
		}
	}
	return assigned
}

// Workers returns a snapshot of the current worker list.
func (pm *PartitionManager) Workers() []string {
	pm.mu.RLock()
	defer pm.mu.RUnlock()
	out := make([]string, len(pm.workers))
	copy(out, pm.workers)
	return out
}

// rendezVousOwner returns the worker with the highest hash weight for node.
func rendezVousOwner(workers []string, node string) string {
	best := ""
	var bestScore uint64
	for _, w := range workers {
		score := rendezVousScore(w, node)
		if score > bestScore || best == "" {
			bestScore = score
			best = w
		}
	}
	return best
}

// rendezVousScore computes hash(worker + ":" + node) → uint64.
func rendezVousScore(worker, node string) uint64 {
	h := sha256.New()
	h.Write([]byte(worker))
	h.Write([]byte{':'})
	h.Write([]byte(node))
	sum := h.Sum(nil)
	return binary.BigEndian.Uint64(sum[:8])
}
