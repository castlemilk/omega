package core

import (
	"testing"
	"time"
)

func makeClock(t time.Time) func() time.Time {
	return func() time.Time { return t }
}

func TestScheduler_Register_DueImmediately(t *testing.T) {
	now := time.Now()
	s := NewImprovementScheduler(makeClock(now))
	s.Register("node-a", nil, true /* runImmediately */)

	due := s.DueNodes()
	if len(due) != 1 || due[0] != "node-a" {
		t.Fatalf("expected node-a to be due, got %v", due)
	}
}

func TestScheduler_Register_NotDueYet(t *testing.T) {
	now := time.Now()
	s := NewImprovementScheduler(makeClock(now))
	cfg := DefaultNodeScheduleConfig("node-b")
	cfg.Interval = time.Hour
	s.Register("node-b", &cfg, false)

	due := s.DueNodes()
	if len(due) != 0 {
		t.Fatalf("expected no due nodes, got %v", due)
	}
}

func TestScheduler_RecordOutcome_Success(t *testing.T) {
	now := time.Now()
	s := NewImprovementScheduler(makeClock(now))
	s.Register("node-a", nil, true)

	// Consume the due entry
	s.DueNodes()

	// Record success — should reschedule at now + Interval
	_ = s.RecordOutcome("node-a", true, nil)

	// Immediately after: not due
	due := s.DueNodes()
	if len(due) != 0 {
		t.Fatalf("expected no due nodes immediately after success, got %v", due)
	}

	// After interval: due
	cfg := s.configs["node-a"]
	futureS := NewImprovementScheduler(makeClock(now.Add(cfg.Interval + time.Second)))
	futureS.configs = s.configs
	futureS.entries = s.entries
	futureS.generations = s.generations
	for _, e := range s.entries {
		futureS.h = append(futureS.h, e)
	}

	due2 := futureS.DueNodes()
	if len(due2) != 1 {
		t.Fatalf("expected node-a due after interval, got %v", due2)
	}
}

func TestScheduler_RecordOutcome_Failure_Backoff(t *testing.T) {
	now := time.Now()
	s := NewImprovementScheduler(makeClock(now))
	cfg := DefaultNodeScheduleConfig("node-fail")
	cfg.Cooldown = time.Minute
	s.Register("node-fail", &cfg, true)
	s.DueNodes()

	_ = s.RecordOutcome("node-fail", false, nil)

	entry := s.entries["node-fail"]
	if entry.consecutiveFailures != 1 {
		t.Errorf("expected 1 failure, got %d", entry.consecutiveFailures)
	}
	// Next run should be now + cooldown (backoff factor = 2^0 = 1x)
	expectedDelay := cfg.Cooldown
	actualDelay := entry.nextRunAt.Sub(now)
	if actualDelay < expectedDelay-time.Second || actualDelay > expectedDelay+time.Second {
		t.Errorf("expected delay ~%s, got %s", expectedDelay, actualDelay)
	}
}

func TestScheduler_Suspension(t *testing.T) {
	now := time.Now()
	s := NewImprovementScheduler(makeClock(now))
	cfg := DefaultNodeScheduleConfig("flakey")
	cfg.MaxConsecutiveFailures = 3
	cfg.Cooldown = time.Millisecond
	s.Register("flakey", &cfg, true)

	for i := 0; i < 3; i++ {
		s.DueNodes()
		_ = s.RecordOutcome("flakey", false, nil)
		// advance clock so entry is due each time
		s = NewImprovementScheduler(makeClock(now.Add(time.Duration(i+1) * time.Second)))
		s.configs["flakey"] = cfg
		s.entries["flakey"] = &scheduleEntry{
			nodeID:              "flakey",
			consecutiveFailures: i + 1,
			nextRunAt:           now,
			priority:            1.0,
			generation:          1,
		}
		s.generations["flakey"] = 1
		s.h = append(s.h, s.entries["flakey"])
	}

	if !s.IsSuspended("flakey") {
		t.Fatal("expected node to be suspended after MaxConsecutiveFailures")
	}
}

func TestScheduler_ResetFailures(t *testing.T) {
	now := time.Now()
	s := NewImprovementScheduler(makeClock(now))
	s.Register("node-r", nil, true)
	s.DueNodes()
	_ = s.RecordOutcome("node-r", false, nil)
	_ = s.RecordOutcome("node-r", false, nil)

	s.ResetFailures("node-r")
	if s.entries["node-r"].consecutiveFailures != 0 {
		t.Fatal("expected failures reset to 0")
	}
}

func TestScheduler_Unregister(t *testing.T) {
	s := NewImprovementScheduler(nil)
	s.Register("node-x", nil, true)
	s.Unregister("node-x")

	nodes := s.RegisteredNodes()
	for _, n := range nodes {
		if n == "node-x" {
			t.Fatal("node-x should be unregistered")
		}
	}
}

func TestScheduler_PriorityOrder(t *testing.T) {
	now := time.Now()
	s := NewImprovementScheduler(makeClock(now))

	low := DefaultNodeScheduleConfig("low")
	low.Priority = 0.1
	high := DefaultNodeScheduleConfig("high")
	high.Priority = 10.0

	s.Register("low", &low, true)
	s.Register("high", &high, true)

	due := s.DueNodes()
	if len(due) < 2 {
		t.Fatalf("expected 2 due nodes, got %d", len(due))
	}
	if due[0] != "high" {
		t.Errorf("expected high-priority node first, got %s", due[0])
	}
}

func TestScheduler_ScheduleStatus(t *testing.T) {
	s := NewImprovementScheduler(nil)
	s.Register("node-a", nil, false)
	s.Register("node-b", nil, false)

	status := s.ScheduleStatus()
	if len(status) != 2 {
		t.Fatalf("expected 2 entries in schedule status, got %d", len(status))
	}
}

func TestScheduler_NextDue(t *testing.T) {
	now := time.Now()
	s := NewImprovementScheduler(makeClock(now))
	s.Register("only", nil, true)

	nodeID, in, ok := s.NextDue()
	if !ok {
		t.Fatal("expected a next due entry")
	}
	if nodeID != "only" {
		t.Errorf("expected nodeID=only, got %s", nodeID)
	}
	if in > time.Second {
		t.Errorf("expected due immediately, got %s", in)
	}
}
