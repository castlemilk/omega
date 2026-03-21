package core

import (
	"fmt"
	"sync"
	"testing"
)

// ---------------------------------------------------------------------------
// CanAddNode
// ---------------------------------------------------------------------------

func TestCapacityManager_CanAddNode(t *testing.T) {
	cm := NewCapacityManager(2)

	if !cm.CanAddNode() {
		t.Fatal("should be able to add node on empty manager")
	}

	cm.TrackNode("a", ResourceEstimation{64, 5})
	if !cm.CanAddNode() {
		t.Fatal("should be able to add node when 1 of 2 slots used")
	}

	cm.TrackNode("b", ResourceEstimation{64, 5})
	if cm.CanAddNode() {
		t.Fatal("should not be able to add node when at capacity")
	}
}

func TestCapacityManager_CanAddNode_AfterUntrack(t *testing.T) {
	cm := NewCapacityManager(1)
	cm.TrackNode("x", ResourceEstimation{64, 5})
	if cm.CanAddNode() {
		t.Fatal("should not be able to add node at capacity")
	}
	cm.UntrackNode("x")
	if !cm.CanAddNode() {
		t.Fatal("should be able to add node after untrack")
	}
}

// ---------------------------------------------------------------------------
// ResourceEstimate
// ---------------------------------------------------------------------------

func TestCapacityManager_ResourceEstimate_DefaultType(t *testing.T) {
	cm := NewCapacityManager(10)
	est := cm.ResourceEstimate(NodeConfig{NodeType: "unknown"})
	if est.EstimatedMemoryMB != 64.0 {
		t.Errorf("default memory: got %f want 64", est.EstimatedMemoryMB)
	}
	if est.EstimatedCPUPct != 5.0 {
		t.Errorf("default CPU: got %f want 5", est.EstimatedCPUPct)
	}
}

func TestCapacityManager_ResourceEstimate_QuantType(t *testing.T) {
	cm := NewCapacityManager(10)
	est := cm.ResourceEstimate(NodeConfig{NodeType: "quant"})
	if est.EstimatedMemoryMB != 128.0 {
		t.Errorf("quant memory: got %f want 128", est.EstimatedMemoryMB)
	}
}

func TestCapacityManager_ResourceEstimate_AdversarialType(t *testing.T) {
	cm := NewCapacityManager(10)
	est := cm.ResourceEstimate(NodeConfig{NodeType: "adversarial"})
	if est.EstimatedMemoryMB != 256.0 {
		t.Errorf("adversarial memory: got %f want 256", est.EstimatedMemoryMB)
	}
}

func TestCapacityManager_ResourceEstimate_MemoryType(t *testing.T) {
	cm := NewCapacityManager(10)
	est := cm.ResourceEstimate(NodeConfig{NodeType: "memory"})
	if est.EstimatedMemoryMB != 512.0 {
		t.Errorf("memory node memory: got %f want 512", est.EstimatedMemoryMB)
	}
}

// ---------------------------------------------------------------------------
// Totals
// ---------------------------------------------------------------------------

func TestCapacityManager_Totals(t *testing.T) {
	cm := NewCapacityManager(10)
	cm.TrackNode("a", ResourceEstimation{EstimatedMemoryMB: 100, EstimatedCPUPct: 10})
	cm.TrackNode("b", ResourceEstimation{EstimatedMemoryMB: 200, EstimatedCPUPct: 20})

	if got := cm.TotalMemoryMB(); got != 300.0 {
		t.Errorf("TotalMemoryMB: got %f want 300", got)
	}
	if got := cm.TotalCPUPct(); got != 30.0 {
		t.Errorf("TotalCPUPct: got %f want 30", got)
	}

	cm.UntrackNode("a")
	if got := cm.TotalMemoryMB(); got != 200.0 {
		t.Errorf("TotalMemoryMB after untrack: got %f want 200", got)
	}
}

// ---------------------------------------------------------------------------
// AutoScale
// ---------------------------------------------------------------------------

func TestCapacityManager_AutoScale_HighLoad_AddsNode(t *testing.T) {
	cm := NewCapacityManager(10)
	cm.TrackNode("a", ResourceEstimation{64, 5})

	rec := cm.AutoScale(map[string]float64{"load": 0.9})
	if rec.Action != ScaleActionAdd {
		t.Errorf("high load: got action %s want add", rec.Action)
	}
	if rec.Count != 1 {
		t.Errorf("count: got %d want 1", rec.Count)
	}
}

func TestCapacityManager_AutoScale_HighLoad_AtCapacity_NoAdd(t *testing.T) {
	cm := NewCapacityManager(1)
	cm.TrackNode("a", ResourceEstimation{64, 5})

	rec := cm.AutoScale(map[string]float64{"load": 0.9})
	if rec.Action != ScaleActionNone {
		t.Errorf("at capacity: expected none, got %s", rec.Action)
	}
}

func TestCapacityManager_AutoScale_LowLoad_RemovesNode(t *testing.T) {
	cm := NewCapacityManager(10)
	cm.TrackNode("a", ResourceEstimation{64, 5})
	cm.TrackNode("b", ResourceEstimation{64, 5})

	rec := cm.AutoScale(map[string]float64{"load": 0.1})
	if rec.Action != ScaleActionRemove {
		t.Errorf("low load: got action %s want remove", rec.Action)
	}
}

func TestCapacityManager_AutoScale_LowLoad_SingleNode_NoRemove(t *testing.T) {
	cm := NewCapacityManager(10)
	cm.TrackNode("a", ResourceEstimation{64, 5})

	rec := cm.AutoScale(map[string]float64{"load": 0.1})
	if rec.Action != ScaleActionNone {
		t.Errorf("single node: expected none, got %s", rec.Action)
	}
}

func TestCapacityManager_AutoScale_HighErrorRate_RemovesNode(t *testing.T) {
	cm := NewCapacityManager(10)
	cm.TrackNode("a", ResourceEstimation{64, 5})
	cm.TrackNode("b", ResourceEstimation{64, 5})

	rec := cm.AutoScale(map[string]float64{"error_rate": 0.6})
	if rec.Action != ScaleActionRemove {
		t.Errorf("high error rate: got %s want remove", rec.Action)
	}
}

func TestCapacityManager_AutoScale_NormalLoad_NoAction(t *testing.T) {
	cm := NewCapacityManager(10)
	cm.TrackNode("a", ResourceEstimation{64, 5})

	rec := cm.AutoScale(map[string]float64{"load": 0.5})
	if rec.Action != ScaleActionNone {
		t.Errorf("normal load: got %s want none", rec.Action)
	}
}

func TestCapacityManager_AutoScale_MemoryPressure_RemovesNode(t *testing.T) {
	cm := NewCapacityManager(10)
	cm.TrackNode("a", ResourceEstimation{EstimatedMemoryMB: 100, EstimatedCPUPct: 5})
	cm.TrackNode("b", ResourceEstimation{EstimatedMemoryMB: 100, EstimatedCPUPct: 5})

	// actual_memory > 90% of estimated 200MB = 180MB
	rec := cm.AutoScale(map[string]float64{"memory_mb": 190})
	if rec.Action != ScaleActionRemove {
		t.Errorf("memory pressure: got %s want remove", rec.Action)
	}
}

// ---------------------------------------------------------------------------
// Capacity limits prevent over-provisioning
// ---------------------------------------------------------------------------

func TestCapacityManager_OverProvisioningPrevented(t *testing.T) {
	const maxNodes = 5
	cm := NewCapacityManager(maxNodes)

	for i := 0; i < maxNodes; i++ {
		cm.TrackNode(fmt.Sprintf("node-%d", i), ResourceEstimation{64, 5})
	}

	if cm.CanAddNode() {
		t.Errorf("should not be able to add beyond max=%d", maxNodes)
	}
	if cm.NodeCount() != maxNodes {
		t.Errorf("NodeCount: got %d want %d", cm.NodeCount(), maxNodes)
	}
}

// ---------------------------------------------------------------------------
// Concurrent safety
// ---------------------------------------------------------------------------

func TestCapacityManager_ConcurrentAccess(t *testing.T) {
	cm := NewCapacityManager(100)
	var wg sync.WaitGroup

	// Concurrent TrackNode.
	for i := 0; i < 50; i++ {
		wg.Add(1)
		id := fmt.Sprintf("node-%d", i)
		go func() {
			defer wg.Done()
			cm.TrackNode(id, ResourceEstimation{64, 5})
		}()
	}
	wg.Wait()

	if cm.NodeCount() != 50 {
		t.Errorf("NodeCount after concurrent track: got %d want 50", cm.NodeCount())
	}

	// Concurrent CanAddNode / TotalMemoryMB while untracking.
	for i := 0; i < 50; i++ {
		wg.Add(3)
		id := fmt.Sprintf("node-%d", i)
		go func() {
			defer wg.Done()
			cm.UntrackNode(id)
		}()
		go func() {
			defer wg.Done()
			_ = cm.CanAddNode()
		}()
		go func() {
			defer wg.Done()
			_ = cm.TotalMemoryMB()
		}()
	}
	wg.Wait()
}
