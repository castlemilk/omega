package core

import (
	"testing"
)

// newInMemoryRegistry creates an in-memory registry for testing.
func newInMemoryRegistry(t *testing.T) *ChallengeRegistry {
	t.Helper()
	reg, err := NewChallengeRegistry(":memory:")
	if err != nil {
		t.Fatalf("NewChallengeRegistry: %v", err)
	}
	t.Cleanup(func() { _ = reg.Close() })
	return reg
}

// ---------------------------------------------------------------------------
// CRUD
// ---------------------------------------------------------------------------

func TestChallengeRegistry_AddAndGet(t *testing.T) {
	reg := newInMemoryRegistry(t)
	id, err := reg.Add("subsystem.test", SeverityHigh, "test description", "test evidence", "")
	if err != nil {
		t.Fatalf("Add: %v", err)
	}
	if id == "" {
		t.Fatal("expected non-empty challenge ID")
	}

	ch, err := reg.Get(id)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if ch == nil {
		t.Fatal("expected challenge, got nil")
	}
	if ch.ChallengeID != id {
		t.Errorf("expected ID=%s, got %s", id, ch.ChallengeID)
	}
	if ch.TargetSubsystem != "subsystem.test" {
		t.Errorf("expected subsystem=subsystem.test, got %s", ch.TargetSubsystem)
	}
	if ch.Severity != SeverityHigh {
		t.Errorf("expected severity=high, got %s", ch.Severity)
	}
	if ch.Status != StatusOpen {
		t.Errorf("expected status=open, got %s", ch.Status)
	}
}

func TestChallengeRegistry_Get_NotFound(t *testing.T) {
	reg := newInMemoryRegistry(t)
	ch, err := reg.Get("nonexistent-id")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if ch != nil {
		t.Error("expected nil for nonexistent challenge")
	}
}

func TestChallengeRegistry_AddWithExplicitID(t *testing.T) {
	reg := newInMemoryRegistry(t)
	id, err := reg.Add("sys", SeverityLow, "desc", "evidence", "explicit-id-123")
	if err != nil {
		t.Fatalf("Add: %v", err)
	}
	if id != "explicit-id-123" {
		t.Errorf("expected explicit ID, got %s", id)
	}
}

func TestChallengeRegistry_UpdateStatus(t *testing.T) {
	reg := newInMemoryRegistry(t)
	id, _ := reg.Add("sys", SeverityMedium, "desc", "", "")

	updated, err := reg.UpdateStatus(id, StatusResolved, "fixed in v2")
	if err != nil {
		t.Fatalf("UpdateStatus: %v", err)
	}
	if !updated {
		t.Error("expected updated=true")
	}

	ch, _ := reg.Get(id)
	if ch.Status != StatusResolved {
		t.Errorf("expected status=resolved, got %s", ch.Status)
	}
	if ch.ResolutionNotes != "fixed in v2" {
		t.Errorf("expected notes='fixed in v2', got %s", ch.ResolutionNotes)
	}
}

func TestChallengeRegistry_UpdateStatus_NotFound(t *testing.T) {
	reg := newInMemoryRegistry(t)
	updated, err := reg.UpdateStatus("nonexistent", StatusResolved, "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if updated {
		t.Error("expected updated=false for nonexistent ID")
	}
}

// ---------------------------------------------------------------------------
// AllChallenges / OpenChallenges
// ---------------------------------------------------------------------------

func TestChallengeRegistry_AllChallenges(t *testing.T) {
	reg := newInMemoryRegistry(t)
	_, _ = reg.Add("sys.a", SeverityHigh, "d1", "", "")
	_, _ = reg.Add("sys.b", SeverityLow, "d2", "", "")

	all, err := reg.AllChallenges("")
	if err != nil {
		t.Fatalf("AllChallenges: %v", err)
	}
	if len(all) != 2 {
		t.Errorf("expected 2 challenges, got %d", len(all))
	}
}

func TestChallengeRegistry_AllChallenges_SubsystemFilter(t *testing.T) {
	reg := newInMemoryRegistry(t)
	_, _ = reg.Add("orchestrator.loop", SeverityHigh, "d1", "", "")
	_, _ = reg.Add("memory.decay", SeverityLow, "d2", "", "")

	filtered, err := reg.AllChallenges("orchestrator")
	if err != nil {
		t.Fatalf("AllChallenges filtered: %v", err)
	}
	if len(filtered) != 1 {
		t.Errorf("expected 1 filtered challenge, got %d", len(filtered))
	}
	if filtered[0].TargetSubsystem != "orchestrator.loop" {
		t.Errorf("wrong subsystem filtered: %s", filtered[0].TargetSubsystem)
	}
}

func TestChallengeRegistry_OpenChallenges(t *testing.T) {
	reg := newInMemoryRegistry(t)
	id1, _ := reg.Add("sys", SeverityCritical, "critical", "", "")
	id2, _ := reg.Add("sys", SeverityHigh, "high", "", "")
	_, _ = reg.UpdateStatus(id2, StatusResolved, "")

	open, err := reg.OpenChallenges("")
	if err != nil {
		t.Fatalf("OpenChallenges: %v", err)
	}
	if len(open) != 1 {
		t.Errorf("expected 1 open challenge, got %d", len(open))
	}
	if open[0].ChallengeID != id1 {
		t.Errorf("expected open challenge to be id1")
	}
}

func TestChallengeRegistry_OpenChallenges_SeverityFilter(t *testing.T) {
	reg := newInMemoryRegistry(t)
	_, _ = reg.Add("sys", SeverityCritical, "c1", "", "")
	_, _ = reg.Add("sys", SeverityHigh, "h1", "", "")

	criticals, err := reg.OpenChallenges(SeverityCritical)
	if err != nil {
		t.Fatalf("OpenChallenges severity filter: %v", err)
	}
	if len(criticals) != 1 {
		t.Errorf("expected 1 critical, got %d", len(criticals))
	}
	if criticals[0].Severity != SeverityCritical {
		t.Errorf("wrong severity: %s", criticals[0].Severity)
	}
}

// ---------------------------------------------------------------------------
// Health metrics
// ---------------------------------------------------------------------------

func TestChallengeRegistry_ResolutionRate_Empty(t *testing.T) {
	reg := newInMemoryRegistry(t)
	rate, err := reg.ResolutionRate()
	if err != nil {
		t.Fatalf("ResolutionRate: %v", err)
	}
	if rate != 1.0 {
		t.Errorf("expected rate=1.0 for empty registry, got %f", rate)
	}
}

func TestChallengeRegistry_ResolutionRate_Mixed(t *testing.T) {
	reg := newInMemoryRegistry(t)
	id1, _ := reg.Add("sys", SeverityHigh, "d1", "", "")
	id2, _ := reg.Add("sys", SeverityHigh, "d2", "", "")
	_, _ = reg.Add("sys", SeverityHigh, "d3", "", "")
	_, _ = reg.UpdateStatus(id1, StatusResolved, "")
	_, _ = reg.UpdateStatus(id2, StatusWontfix, "")

	rate, err := reg.ResolutionRate()
	if err != nil {
		t.Fatalf("ResolutionRate: %v", err)
	}
	// 2 of 3 resolved → rate = 2/3 ≈ 0.667.
	if rate < 0.66 || rate > 0.68 {
		t.Errorf("expected rate≈0.667, got %f", rate)
	}
}

func TestChallengeRegistry_HasBlockingChallenges_True(t *testing.T) {
	reg := newInMemoryRegistry(t)
	_, _ = reg.Add("sys", SeverityCritical, "critical open", "", "")

	blocking, err := reg.HasBlockingChallenges()
	if err != nil {
		t.Fatalf("HasBlockingChallenges: %v", err)
	}
	if !blocking {
		t.Error("expected true when critical challenge is open")
	}
}

func TestChallengeRegistry_HasBlockingChallenges_False_WhenResolved(t *testing.T) {
	reg := newInMemoryRegistry(t)
	id, _ := reg.Add("sys", SeverityCritical, "critical resolved", "", "")
	_, _ = reg.UpdateStatus(id, StatusResolved, "fixed")

	blocking, err := reg.HasBlockingChallenges()
	if err != nil {
		t.Fatalf("HasBlockingChallenges: %v", err)
	}
	if blocking {
		t.Error("expected false when critical challenge is resolved")
	}
}

func TestChallengeRegistry_HasBlockingChallenges_HighNotBlocking(t *testing.T) {
	reg := newInMemoryRegistry(t)
	_, _ = reg.Add("sys", SeverityHigh, "high open", "", "")

	blocking, err := reg.HasBlockingChallenges()
	if err != nil {
		t.Fatalf("HasBlockingChallenges: %v", err)
	}
	if blocking {
		t.Error("expected false — only CRITICAL challenges block")
	}
}

// ---------------------------------------------------------------------------
// Seeding
// ---------------------------------------------------------------------------

func TestChallengeRegistry_SeedInitialChallenges_Idempotent(t *testing.T) {
	reg := newInMemoryRegistry(t)

	n1, err := reg.SeedInitialChallenges()
	if err != nil {
		t.Fatalf("SeedInitialChallenges (first): %v", err)
	}
	if n1 == 0 {
		t.Fatal("expected at least 1 challenge seeded")
	}

	n2, err := reg.SeedInitialChallenges()
	if err != nil {
		t.Fatalf("SeedInitialChallenges (second): %v", err)
	}
	if n2 != 0 {
		t.Errorf("expected 0 new on re-seed (idempotent), got %d", n2)
	}
}

func TestChallengeRegistry_SeedInitialChallenges_ContainsCritical(t *testing.T) {
	reg := newInMemoryRegistry(t)
	_, _ = reg.SeedInitialChallenges()

	criticals, err := reg.OpenChallenges(SeverityCritical)
	if err != nil {
		t.Fatalf("OpenChallenges: %v", err)
	}
	if len(criticals) == 0 {
		t.Error("expected at least one critical challenge in seed data")
	}
}
