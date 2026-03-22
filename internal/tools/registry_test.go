package tools_test

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/core"
	"github.com/benebsworth/omega/internal/framework"
	"github.com/benebsworth/omega/internal/tools"
)

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

// stubTool is a minimal Tool implementation for tests.
type stubTool struct {
	name        string
	description string
	minLevel    tools.AutonomyLevel
	execFn      func(ctx context.Context, args map[string]any) (tools.ToolResult, error)
}

func newStub(name, description string, minLevel tools.AutonomyLevel) *stubTool {
	return &stubTool{name: name, description: description, minLevel: minLevel}
}

func (s *stubTool) Name() string        { return s.name }
func (s *stubTool) Description() string { return s.description }
func (s *stubTool) Schema() tools.ToolSchema {
	return tools.ToolSchema{
		Name:                  s.name,
		Description:           s.description,
		Parameters:            map[string]any{"type": "object"},
		RequiredAutonomyLevel: s.minLevel,
	}
}
func (s *stubTool) Execute(ctx context.Context, args map[string]any) (tools.ToolResult, error) {
	if s.execFn != nil {
		return s.execFn(ctx, args)
	}
	return tools.ToolResult{Content: "ok"}, nil
}

// ---------------------------------------------------------------------------
// Register / deferred / activate / deactivate lifecycle
// ---------------------------------------------------------------------------

func TestRegisterAndActiveTools(t *testing.T) {
	reg := tools.NewRegistry(nil)
	tool := newStub("alpha", "alpha tool", 0)

	reg.Register(tool)

	active := reg.ActiveTools()
	if len(active) != 1 {
		t.Fatalf("expected 1 active tool, got %d", len(active))
	}
	if active[0].Name != "alpha" {
		t.Errorf("expected name alpha, got %s", active[0].Name)
	}
}

func TestRegisterDeferred_HiddenFromActiveTools(t *testing.T) {
	reg := tools.NewRegistry(nil)
	reg.RegisterDeferred(newStub("hidden", "hidden tool", 0))

	if len(reg.ActiveTools()) != 0 {
		t.Fatal("deferred tool should not appear in ActiveTools")
	}
}

func TestActivate_MovesToActivePool(t *testing.T) {
	reg := tools.NewRegistry(nil)
	reg.RegisterDeferred(newStub("beta", "beta description", 0))

	if err := reg.Activate("beta"); err != nil {
		t.Fatalf("Activate returned error: %v", err)
	}
	active := reg.ActiveTools()
	if len(active) != 1 || active[0].Name != "beta" {
		t.Errorf("expected beta in active pool after Activate")
	}
}

func TestActivate_AlreadyActive_Idempotent(t *testing.T) {
	reg := tools.NewRegistry(nil)
	reg.Register(newStub("gamma", "gamma tool", 0))

	// Activating an already-active tool should succeed silently.
	if err := reg.Activate("gamma"); err != nil {
		t.Errorf("unexpected error activating already-active tool: %v", err)
	}
}

func TestActivate_NotFound_Error(t *testing.T) {
	reg := tools.NewRegistry(nil)
	if err := reg.Activate("nonexistent"); err == nil {
		t.Error("expected error when activating unknown tool")
	}
}

func TestDeactivate_MovesToDeferredPool(t *testing.T) {
	reg := tools.NewRegistry(nil)
	reg.Register(newStub("delta", "delta description", 0))

	if err := reg.Deactivate("delta"); err != nil {
		t.Fatalf("Deactivate returned error: %v", err)
	}
	if len(reg.ActiveTools()) != 0 {
		t.Error("tool should no longer be active after Deactivate")
	}
	// Re-activation should succeed since it is now deferred.
	if err := reg.Activate("delta"); err != nil {
		t.Errorf("expected re-activation to succeed: %v", err)
	}
}

func TestDeactivate_NotFound_Error(t *testing.T) {
	reg := tools.NewRegistry(nil)
	if err := reg.Deactivate("ghost"); err == nil {
		t.Error("expected error when deactivating unknown tool")
	}
}

func TestRegister_OverridesDeferred(t *testing.T) {
	reg := tools.NewRegistry(nil)
	reg.RegisterDeferred(newStub("phi", "phi tool", 0))
	reg.Register(newStub("phi", "phi tool v2", 0))

	active := reg.ActiveTools()
	if len(active) != 1 || active[0].Name != "phi" {
		t.Fatal("expected phi in active pool")
	}
}

// ---------------------------------------------------------------------------
// Search — keyword scoring and auto-activation
// ---------------------------------------------------------------------------

func TestSearch_ReturnsRelevantTools(t *testing.T) {
	reg := tools.NewRegistry(nil)
	reg.RegisterDeferred(newStub("deploy_app", "deploy application to cloud environment", 0))
	reg.RegisterDeferred(newStub("memory_search", "search episodic and semantic memory", 0))
	reg.RegisterDeferred(newStub("metrics_dashboard", "show node performance metrics", 0))

	results := reg.Search("deploy cloud", 5)
	if len(results) == 0 {
		t.Fatal("expected at least one search result")
	}
	if results[0].Name != "deploy_app" {
		t.Errorf("expected deploy_app as top result, got %s", results[0].Name)
	}
}

func TestSearch_ActivatesMatches(t *testing.T) {
	reg := tools.NewRegistry(nil)
	reg.RegisterDeferred(newStub("memory_recall", "search episodic memory for past events", 0))

	_ = reg.Search("memory episodic", 5)

	// memory_recall should now be in the active pool.
	active := reg.ActiveTools()
	found := false
	for _, s := range active {
		if s.Name == "memory_recall" {
			found = true
			break
		}
	}
	if !found {
		t.Error("search result was not activated into the active pool")
	}
}

func TestSearch_EmptyQueryReturnsNil(t *testing.T) {
	reg := tools.NewRegistry(nil)
	reg.RegisterDeferred(newStub("tool_a", "some tool", 0))
	results := reg.Search("", 5)
	if len(results) != 0 {
		t.Errorf("expected empty results for empty query, got %d", len(results))
	}
}

func TestSearch_TopN_Respected(t *testing.T) {
	reg := tools.NewRegistry(nil)
	for i := 0; i < 10; i++ {
		reg.RegisterDeferred(newStub(
			"tool_"+string(rune('a'+i)),
			"search query performance metrics node",
			0,
		))
	}
	results := reg.Search("search metrics", 3)
	if len(results) > 3 {
		t.Errorf("expected at most 3 results, got %d", len(results))
	}
}

// ---------------------------------------------------------------------------
// Execute
// ---------------------------------------------------------------------------

func TestExecute_ActiveTool_Succeeds(t *testing.T) {
	reg := tools.NewRegistry(nil)
	tool := newStub("exec_tool", "execute me", 0)
	tool.execFn = func(_ context.Context, _ map[string]any) (tools.ToolResult, error) {
		return tools.ToolResult{Content: "executed"}, nil
	}
	reg.Register(tool)

	result, err := reg.Execute("exec_tool", context.Background(), nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Content != "executed" {
		t.Errorf("unexpected content: %v", result.Content)
	}
}

func TestExecute_InactiveTool_Error(t *testing.T) {
	reg := tools.NewRegistry(nil)
	reg.RegisterDeferred(newStub("sleeping", "deferred tool", 0))

	_, err := reg.Execute("sleeping", context.Background(), nil)
	if err == nil {
		t.Error("expected error executing deferred tool")
	}
}

// ---------------------------------------------------------------------------
// Authorization
// ---------------------------------------------------------------------------

func TestAuthorizedFor_SufficientLevel(t *testing.T) {
	reg := tools.NewRegistry(nil)
	reg.Register(newStub("bash", "run shell command", core.AutonomyLevelSupervised))

	if !reg.AuthorizedFor("bash", core.AutonomyLevelSupervised) {
		t.Error("supervised level should satisfy supervised requirement")
	}
	if !reg.AuthorizedFor("bash", core.AutonomyLevelFull) {
		t.Error("full autonomy should satisfy supervised requirement")
	}
}

func TestAuthorizedFor_InsufficientLevel(t *testing.T) {
	reg := tools.NewRegistry(nil)
	reg.Register(newStub("reconfigure", "reconfig engine", core.AutonomyLevelFull))

	if reg.AuthorizedFor("reconfigure", core.AutonomyLevelManual) {
		t.Error("manual level should NOT satisfy full autonomy requirement")
	}
	if reg.AuthorizedFor("reconfigure", core.AutonomyLevelSupervised) {
		t.Error("supervised level should NOT satisfy full autonomy requirement")
	}
}

func TestAuthorizedFor_UnknownTool_ReturnsFalse(t *testing.T) {
	reg := tools.NewRegistry(nil)
	if reg.AuthorizedFor("phantasm", core.AutonomyLevelFull) {
		t.Error("unknown tool should return false")
	}
}

func TestAuthorizedFor_DeferredTool_Checked(t *testing.T) {
	reg := tools.NewRegistry(nil)
	reg.RegisterDeferred(newStub("write_file", "write to filesystem", core.AutonomyLevelSupervised))

	if reg.AuthorizedFor("write_file", core.AutonomyLevelManual) {
		t.Error("manual level should not satisfy supervised requirement on deferred tool")
	}
	if !reg.AuthorizedFor("write_file", core.AutonomyLevelSupervised) {
		t.Error("supervised level should satisfy supervised requirement on deferred tool")
	}
}

// ---------------------------------------------------------------------------
// Thread safety
// ---------------------------------------------------------------------------

func TestRegistry_ConcurrentAccess(t *testing.T) {
	reg := tools.NewRegistry(nil)

	// Pre-populate.
	for i := 0; i < 20; i++ {
		reg.RegisterDeferred(newStub(
			"tool_"+string(rune('a'+i%26)),
			"concurrent test tool",
			0,
		))
	}

	var wg sync.WaitGroup
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			name := "tool_" + string(rune('a'+i%26))
			_ = reg.Activate(name)
			_ = reg.ActiveTools()
			_, _ = reg.Execute(name, context.Background(), nil)
			_ = reg.AuthorizedFor(name, core.AutonomyLevelManual)
			_ = reg.Deactivate(name)
			_ = reg.Search("concurrent test", 3)
		}(i)
	}
	// Give goroutines a deadline.
	done := make(chan struct{})
	go func() { wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("concurrent test timed out — possible deadlock")
	}
}

// ---------------------------------------------------------------------------
// EventBus integration
// ---------------------------------------------------------------------------

func TestRegistry_EmitsActivateDeactivateEvents(t *testing.T) {
	bus := framework.NewEventBus()
	reg := tools.NewRegistry(bus)

	var activatedTools []string
	var deactivatedTools []string
	var mu sync.Mutex

	bus.Subscribe(tools.TopicToolActivated, func(e framework.Event) {
		payload := e.Payload.(map[string]any)
		mu.Lock()
		activatedTools = append(activatedTools, payload["tool"].(string))
		mu.Unlock()
	})
	bus.Subscribe(tools.TopicToolDeactivated, func(e framework.Event) {
		payload := e.Payload.(map[string]any)
		mu.Lock()
		deactivatedTools = append(deactivatedTools, payload["tool"].(string))
		mu.Unlock()
	})

	reg.RegisterDeferred(newStub("event_tool", "event test tool", 0))
	_ = reg.Activate("event_tool")
	_ = reg.Deactivate("event_tool")

	mu.Lock()
	defer mu.Unlock()
	if len(activatedTools) != 1 || activatedTools[0] != "event_tool" {
		t.Errorf("expected activation event for event_tool, got %v", activatedTools)
	}
	if len(deactivatedTools) != 1 || deactivatedTools[0] != "event_tool" {
		t.Errorf("expected deactivation event for event_tool, got %v", deactivatedTools)
	}
}

// ---------------------------------------------------------------------------
// AuthorizationPolicy
// ---------------------------------------------------------------------------

func TestAuthorizationPolicy_DefaultRules(t *testing.T) {
	policy := tools.NewAuthorizationPolicy()

	tests := []struct {
		tool    string
		level   core.AutonomyLevel
		allowed bool
	}{
		{"bash", core.AutonomyLevelManual, false},
		{"bash", core.AutonomyLevelSupervised, true},
		{"read_file", core.AutonomyLevelManual, true},
		{"reconfigure", core.AutonomyLevelSupervised, false},
		{"reconfigure", core.AutonomyLevelFull, true},
	}

	for _, tc := range tests {
		allowed, reason := policy.Authorize(tc.tool, tc.level)
		if allowed != tc.allowed {
			t.Errorf("Authorize(%q, %d): got %v, want %v — reason: %s",
				tc.tool, tc.level, allowed, tc.allowed, reason)
		}
	}
}

func TestAuthorizationPolicy_HotReload(t *testing.T) {
	policy := tools.NewAuthorizationPolicy()

	// Initially bash requires supervised.
	if ok, _ := policy.Authorize("bash", core.AutonomyLevelManual); ok {
		t.Fatal("bash should require supervised by default")
	}

	// Hot-reload with bash demoted to always available.
	newRules := map[string]core.AutonomyLevel{
		"bash": core.AutonomyLevelUnspecified,
	}
	policy.Load(newRules)

	if ok, _ := policy.Authorize("bash", core.AutonomyLevelManual); !ok {
		t.Error("after reload bash should be available at manual level")
	}
}

func TestAuthorizationPolicy_UnknownToolAllowed(t *testing.T) {
	policy := tools.NewAuthorizationPolicy()
	allowed, _ := policy.Authorize("unknown_widget", core.AutonomyLevelManual)
	if !allowed {
		t.Error("unknown tools should be allowed by default (no restriction)")
	}
}

// ---------------------------------------------------------------------------
// ToolSearchTool (builtin)
// ---------------------------------------------------------------------------

func TestToolSearchTool_Execute(t *testing.T) {
	reg := tools.NewRegistry(nil)
	reg.RegisterDeferred(newStub("deploy_service", "deploy a service to production", 0))
	reg.RegisterDeferred(newStub("query_logs", "query application logs", 0))

	searchTool := tools.NewToolSearchTool(reg)

	result, err := searchTool.Execute(context.Background(), map[string]any{"query": "deploy production"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.IsError {
		t.Fatalf("tool reported error: %v", result.Content)
	}
	schemas, ok := result.Content.([]tools.ToolSchema)
	if !ok {
		t.Fatalf("expected []ToolSchema, got %T", result.Content)
	}
	if len(schemas) == 0 {
		t.Error("expected at least one schema returned by search tool")
	}
	if schemas[0].Name != "deploy_service" {
		t.Errorf("expected deploy_service as top result, got %s", schemas[0].Name)
	}
}

func TestToolSearchTool_MissingQuery(t *testing.T) {
	reg := tools.NewRegistry(nil)
	searchTool := tools.NewToolSearchTool(reg)

	result, err := searchTool.Execute(context.Background(), map[string]any{})
	if err != nil {
		t.Fatalf("unexpected hard error: %v", err)
	}
	if !result.IsError {
		t.Error("expected IsError=true for missing query argument")
	}
}
