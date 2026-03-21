package eval

import (
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/core"
)

// ---------------------------------------------------------------------------
// Registration and basic scheduling
// ---------------------------------------------------------------------------

func TestImprovement_RegisteredNodeAppearsInStatus(t *testing.T) {
	h := NewImprovementHarness(time.Minute)
	h.RegisterNode("node_a", false)
	h.RegisterNode("node_b", false)

	nodes := h.Scheduler.RegisteredNodes()
	if len(nodes) != 2 {
		t.Errorf("expected 2 registered nodes, got %d", len(nodes))
	}
}

func TestImprovement_ImmediateRunAppearsInDueNodes(t *testing.T) {
	h := NewImprovementHarness(time.Minute)
	h.RegisterNode("node_imm", true) // runImmediately=true

	due := h.Scheduler.DueNodes()
	if len(due) == 0 {
		t.Error("expected node_imm to be immediately due")
	}
	if due[0] != "node_imm" {
		t.Errorf("due[0]=%q want=node_imm", due[0])
	}
}

func TestImprovement_NonImmediateNotDueUntilInterval(t *testing.T) {
	h := NewImprovementHarness(time.Minute)

	cfg := core.DefaultNodeScheduleConfig("node_later")
	cfg.Interval = 10 * time.Minute
	h.RegisterNodeWithConfig(cfg)

	// No time has passed — node should not be due.
	due := h.Scheduler.DueNodes()
	for _, n := range due {
		if n == "node_later" {
			t.Error("node_later should not be due before interval elapses")
		}
	}
}

// ---------------------------------------------------------------------------
// Priority queue ordering
// ---------------------------------------------------------------------------

func TestImprovement_PriorityOrdering(t *testing.T) {
	h := NewImprovementHarness(time.Minute)

	// Register three nodes with different priorities, all due immediately.
	low := core.DefaultNodeScheduleConfig("low_priority")
	low.Priority = 0.1
	med := core.DefaultNodeScheduleConfig("med_priority")
	med.Priority = 0.5
	high := core.DefaultNodeScheduleConfig("high_priority")
	high.Priority = 1.0

	h.Scheduler.Register("low_priority", &low, true)
	h.Scheduler.Register("med_priority", &med, true)
	h.Scheduler.Register("high_priority", &high, true)

	due := h.Scheduler.DueNodes()
	if len(due) != 3 {
		t.Fatalf("expected 3 due nodes, got %d", len(due))
	}
	if due[0] != "high_priority" {
		t.Errorf("first due node should be high_priority, got %q", due[0])
	}
	if due[2] != "low_priority" {
		t.Errorf("last due node should be low_priority, got %q", due[2])
	}
}

// ---------------------------------------------------------------------------
// Success / failure handling
// ---------------------------------------------------------------------------

func TestImprovement_SuccessResetsFailureCount(t *testing.T) {
	h := NewImprovementHarness(time.Minute)
	h.RegisterNode("node_s", true)

	_ = h.Scheduler.RecordOutcome("node_s", false, nil)
	_ = h.Scheduler.RecordOutcome("node_s", false, nil)
	_ = h.Scheduler.RecordOutcome("node_s", true, ScorePtr(0.8))

	if h.Scheduler.IsSuspended("node_s") {
		t.Error("node should not be suspended after a success resets failures")
	}
}

func TestImprovement_ExponentialBackoffOnFailure(t *testing.T) {
	h := NewImprovementHarness(time.Minute)
	h.RegisterNode("node_backoff", true)

	statuses := make([]time.Duration, 3)
	for i := 0; i < 3; i++ {
		_ = h.Scheduler.RecordOutcome("node_backoff", false, nil)
		status := h.Scheduler.ScheduleStatus()
		for _, s := range status {
			if s.NodeID == "node_backoff" {
				statuses[i] = s.NextRunIn
			}
		}
	}

	// Each consecutive failure should increase the backoff.
	if statuses[1] <= statuses[0] {
		t.Errorf("backoff should increase: [0]=%v [1]=%v", statuses[0], statuses[1])
	}
	if statuses[2] <= statuses[1] {
		t.Errorf("backoff should increase: [1]=%v [2]=%v", statuses[1], statuses[2])
	}
}

func TestImprovement_SuspensionAfterMaxFailures(t *testing.T) {
	h := NewImprovementHarness(time.Minute)
	cfg := core.DefaultNodeScheduleConfig("node_suspend")
	cfg.MaxConsecutiveFailures = 3
	h.Scheduler.Register("node_suspend", &cfg, true)

	// Record 3 failures — should be suspended.
	_ = h.Scheduler.RecordOutcome("node_suspend", false, nil)
	_ = h.Scheduler.RecordOutcome("node_suspend", false, nil)
	_ = h.Scheduler.RecordOutcome("node_suspend", false, nil)

	if !h.Scheduler.IsSuspended("node_suspend") {
		t.Error("node_suspend should be suspended after 3 consecutive failures")
	}

	// Suspended node should not appear in due nodes even after time passes.
	h.Clock.Advance(24 * time.Hour)
	due := h.Scheduler.DueNodes()
	for _, n := range due {
		if n == "node_suspend" {
			t.Error("suspended node should not appear in due nodes")
		}
	}
}

func TestImprovement_NotSuspendedBeforeMaxFailures(t *testing.T) {
	h := NewImprovementHarness(time.Minute)
	cfg := core.DefaultNodeScheduleConfig("node_n")
	cfg.MaxConsecutiveFailures = 5
	h.Scheduler.Register("node_n", &cfg, true)

	suspended := h.SimulateFailures("node_n", 4)
	for i, s := range suspended {
		if s {
			t.Errorf("node should not be suspended after only %d failures (max=5)", i+1)
		}
	}
}

// ---------------------------------------------------------------------------
// Schedule status
// ---------------------------------------------------------------------------

func TestImprovement_ScheduleStatusPopulated(t *testing.T) {
	h := NewImprovementHarness(time.Minute)
	h.RegisterNode("status_node", false)

	statuses := h.Scheduler.ScheduleStatus()
	found := false
	for _, s := range statuses {
		if s.NodeID == "status_node" {
			found = true
			if !s.Enabled {
				t.Error("status_node should be enabled by default")
			}
		}
	}
	if !found {
		t.Error("status_node not found in ScheduleStatus")
	}
}

func TestImprovement_ScoreTracked(t *testing.T) {
	h := NewImprovementHarness(time.Minute)
	h.RegisterNode("score_node", true)

	score := 0.75
	_ = h.Scheduler.RecordOutcome("score_node", true, &score)

	statuses := h.Scheduler.ScheduleStatus()
	for _, s := range statuses {
		if s.NodeID == "score_node" {
			if s.LastScore == nil {
				t.Error("LastScore should be set after recording outcome")
			} else if *s.LastScore != 0.75 {
				t.Errorf("LastScore=%.4f want=0.75", *s.LastScore)
			}
		}
	}
}

// ---------------------------------------------------------------------------
// Unregistration
// ---------------------------------------------------------------------------

func TestImprovement_UnregisteredNodeNotDue(t *testing.T) {
	h := NewImprovementHarness(time.Minute)
	h.RegisterNode("removable", true)
	h.Scheduler.Unregister("removable")

	due := h.Scheduler.DueNodes()
	for _, n := range due {
		if n == "removable" {
			t.Error("unregistered node should not appear in due nodes")
		}
	}
}
