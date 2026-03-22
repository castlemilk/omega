package registry_test

import (
	"context"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/registry"
)

// newTestRegistry returns a registry with OTel wired to the no-op provider
// (telemetry.Init is not called, so all instruments are no-ops).
func newTestRegistry(t *testing.T) *registry.NodeRegistry {
	t.Helper()
	reg, err := registry.NewNodeRegistry()
	if err != nil {
		t.Fatalf("NewNodeRegistry: %v", err)
	}
	return reg
}

func entry(id string, caps ...string) registry.NodeEntry {
	return registry.NodeEntry{
		ID:           id,
		Name:         "node-" + id,
		Version:      "1.0.0",
		Address:      "http://localhost:0",
		Capabilities: caps,
		Language:     "python",
		Health:       1.0,
		State:        registry.NodeStateHealthy,
	}
}

// ── Registration ──────────────────────────────────────────────────────────────

func TestRegister_Get(t *testing.T) {
	reg := newTestRegistry(t)

	if err := reg.Register(entry("n1", "trade", "analyze")); err != nil {
		t.Fatal(err)
	}

	got, ok := reg.Get("n1")
	if !ok {
		t.Fatal("expected node n1 to exist")
	}
	if got.ID != "n1" {
		t.Errorf("id: got %q want %q", got.ID, "n1")
	}
	if len(got.Capabilities) != 2 {
		t.Errorf("capabilities: got %d want 2", len(got.Capabilities))
	}
}

func TestRegister_EmptyID_Error(t *testing.T) {
	reg := newTestRegistry(t)
	if err := reg.Register(registry.NodeEntry{Address: "http://x"}); err == nil {
		t.Fatal("expected error for empty ID")
	}
}

func TestRegister_EmptyAddress_Error(t *testing.T) {
	reg := newTestRegistry(t)
	if err := reg.Register(registry.NodeEntry{ID: "n1"}); err == nil {
		t.Fatal("expected error for empty address")
	}
}

func TestRegister_Overwrite(t *testing.T) {
	reg := newTestRegistry(t)
	_ = reg.Register(entry("n1", "trade"))
	_ = reg.Register(registry.NodeEntry{
		ID:           "n1",
		Address:      "http://updated",
		Capabilities: []string{"analyze"},
		State:        registry.NodeStateHealthy,
	})

	got, _ := reg.Get("n1")
	if got.Address != "http://updated" {
		t.Errorf("address not updated, got %q", got.Address)
	}
	// Old capability should be gone, new one present.
	nodes := reg.FindByCapability("trade", false)
	if len(nodes) != 0 {
		t.Errorf("old capability 'trade' should have been removed")
	}
	nodes = reg.FindByCapability("analyze", false)
	if len(nodes) != 1 {
		t.Errorf("new capability 'analyze' should have 1 node, got %d", len(nodes))
	}
}

// ── Deregistration ────────────────────────────────────────────────────────────

func TestDeregister(t *testing.T) {
	reg := newTestRegistry(t)
	_ = reg.Register(entry("n1", "trade"))

	reg.Deregister("n1")

	if _, ok := reg.Get("n1"); ok {
		t.Fatal("node should have been removed")
	}
	if nodes := reg.FindByCapability("trade", false); len(nodes) != 0 {
		t.Errorf("capability index should be empty after deregistration, got %d nodes", len(nodes))
	}
}

func TestDeregister_NoOp(t *testing.T) {
	reg := newTestRegistry(t)
	// Should not panic.
	reg.Deregister("nonexistent")
}

// ── Capability queries ────────────────────────────────────────────────────────

func TestFindByCapability_HealthyOnly(t *testing.T) {
	reg := newTestRegistry(t)
	_ = reg.Register(entry("h1", "trade"))
	_ = reg.Register(entry("h2", "trade"))

	// Mark h2 offline.
	reg.UpdateHealth("h2", 0, registry.NodeStateOffline)

	healthyNodes := reg.FindByCapability("trade", true)
	if len(healthyNodes) != 1 {
		t.Errorf("expected 1 healthy node, got %d", len(healthyNodes))
	}
	if healthyNodes[0].ID != "h1" {
		t.Errorf("expected h1, got %q", healthyNodes[0].ID)
	}

	allNodes := reg.FindByCapability("trade", false)
	if len(allNodes) != 2 {
		t.Errorf("expected 2 total nodes, got %d", len(allNodes))
	}
}

func TestFindByCapability_Unknown(t *testing.T) {
	reg := newTestRegistry(t)
	nodes := reg.FindByCapability("unknown", true)
	if nodes == nil {
		t.Fatal("expected non-nil slice")
	}
	if len(nodes) != 0 {
		t.Errorf("expected 0 nodes, got %d", len(nodes))
	}
}

func TestFindByCapability_MultipleCapabilities(t *testing.T) {
	reg := newTestRegistry(t)
	_ = reg.Register(entry("n1", "trade", "analyze"))
	_ = reg.Register(entry("n2", "analyze"))

	tradeNodes := reg.FindByCapability("trade", false)
	if len(tradeNodes) != 1 {
		t.Errorf("trade: expected 1 node, got %d", len(tradeNodes))
	}
	analyzeNodes := reg.FindByCapability("analyze", false)
	if len(analyzeNodes) != 2 {
		t.Errorf("analyze: expected 2 nodes, got %d", len(analyzeNodes))
	}
}

// ── Health state transitions ──────────────────────────────────────────────────

func TestUpdateHealth_StateTransition(t *testing.T) {
	reg := newTestRegistry(t)
	_ = reg.Register(entry("n1"))

	reg.UpdateHealth("n1", 0.3, registry.NodeStateDegraded)
	got, _ := reg.Get("n1")
	if got.State != registry.NodeStateDegraded {
		t.Errorf("expected degraded, got %q", got.State)
	}
	if got.Health != 0.3 {
		t.Errorf("health: got %v want 0.3", got.Health)
	}
}

func TestUpdateHealth_NoOp_Unknown(t *testing.T) {
	reg := newTestRegistry(t)
	// Should not panic.
	reg.UpdateHealth("nonexistent", 1.0, registry.NodeStateHealthy)
}

func TestHeartbeat_ResurrectOffline(t *testing.T) {
	reg := newTestRegistry(t)
	_ = reg.Register(entry("n1"))
	reg.UpdateHealth("n1", 0, registry.NodeStateOffline)

	reg.Heartbeat("n1")

	got, _ := reg.Get("n1")
	if got.State != registry.NodeStateHealthy {
		t.Errorf("heartbeat should revive node, got state %q", got.State)
	}
}

func TestHeartbeat_NoOp_Unknown(t *testing.T) {
	reg := newTestRegistry(t)
	// Should not panic.
	reg.Heartbeat("nonexistent")
}

func TestHealthLoop_MarksOffline(t *testing.T) {
	reg := newTestRegistry(t)

	// Register a node with a very old heartbeat by overwriting via Register.
	e := entry("n1")
	e.LastHeartbeat = time.Now().Add(-60 * time.Second) // older than 30s timeout
	_ = reg.Register(e)

	// Run one health check cycle immediately.
	ctx := context.Background()
	reg.StartHealthLoop(ctx, 10*time.Millisecond)

	// Wait for at least one tick.
	time.Sleep(50 * time.Millisecond)

	got, ok := reg.Get("n1")
	if !ok {
		t.Fatal("node should still be registered")
	}
	if got.State != registry.NodeStateOffline {
		t.Errorf("expected offline after heartbeat expiry, got %q", got.State)
	}
}

// ── Thread safety ─────────────────────────────────────────────────────────────

func TestConcurrentRegisterDeregister(t *testing.T) {
	reg := newTestRegistry(t)

	const n = 50
	var wg sync.WaitGroup
	wg.Add(n * 2)

	for i := range n {
		id := fmt.Sprintf("node-%d", i)
		go func() {
			defer wg.Done()
			_ = reg.Register(entry(id, "cap"))
		}()
		go func() {
			defer wg.Done()
			reg.Deregister(id)
		}()
	}
	wg.Wait()
	// No race detector errors = pass.
}

func TestConcurrentHeartbeat(t *testing.T) {
	reg := newTestRegistry(t)
	_ = reg.Register(entry("n1"))

	var wg sync.WaitGroup
	for range 100 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			reg.Heartbeat("n1")
		}()
	}
	wg.Wait()
}

func TestAll(t *testing.T) {
	reg := newTestRegistry(t)
	_ = reg.Register(entry("a"))
	_ = reg.Register(entry("b"))
	_ = reg.Register(entry("c"))

	all := reg.All()
	if len(all) != 3 {
		t.Errorf("expected 3 nodes, got %d", len(all))
	}
}
