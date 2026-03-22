// Package tools implements a deferred tool registry for Omega.
//
// Tools are divided into two pools:
//
//   - Active pool   — schemas returned by ActiveTools(); immediately callable.
//   - Deferred pool — hidden from the active context; discoverable via Search().
//
// The pattern mirrors DeerFlow's approach of hiding tool schemas until the LLM
// explicitly requests discovery, keeping the active context lean.
package tools

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/benebsworth/omega/internal/core"
	"github.com/benebsworth/omega/internal/framework"
)

// ---------------------------------------------------------------------------
// Event topics
// ---------------------------------------------------------------------------

const (
	// TopicToolActivated is published on the framework.EventBus when a tool
	// is moved from the deferred pool to the active pool.
	TopicToolActivated = "tools.activated"

	// TopicToolDeactivated is published when a tool is moved back to deferred.
	TopicToolDeactivated = "tools.deactivated"
)

// ---------------------------------------------------------------------------
// Core types
// ---------------------------------------------------------------------------

// AutonomyLevel aliases core.AutonomyLevel so callers don't need to import core.
type AutonomyLevel = core.AutonomyLevel

// ToolSchema describes a tool's interface contract for context injection.
type ToolSchema struct {
	// Name is the unique tool identifier.
	Name string

	// Description is a human- (and LLM-) readable summary of what the tool does.
	Description string

	// Parameters is a JSON Schema object describing the tool's input arguments.
	Parameters map[string]any

	// RequiredAutonomyLevel is the minimum AutonomyLevel required to execute
	// this tool. The zero value (Unspecified) means always available.
	RequiredAutonomyLevel AutonomyLevel
}

// ToolResult carries the output of a successful tool execution.
type ToolResult struct {
	// Content holds the tool's return value. Callers should type-assert as needed.
	Content any

	// IsError indicates the execution completed but returned an application-level error.
	IsError bool
}

// Tool is the interface all Omega tools must implement.
type Tool interface {
	// Name returns the unique tool identifier.
	Name() string

	// Description returns a human-readable summary used for search scoring.
	Description() string

	// Schema returns the full ToolSchema, including parameter definitions and
	// the minimum autonomy level required to run this tool.
	Schema() ToolSchema

	// Execute runs the tool with the provided arguments.
	Execute(ctx context.Context, args map[string]any) (ToolResult, error)
}

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

// Registry manages the active and deferred tool pools.
// All methods are safe for concurrent use.
type Registry struct {
	mu       sync.RWMutex
	active   map[string]Tool
	deferred map[string]Tool
	bus      *framework.EventBus
}

// NewRegistry returns a Registry. bus may be nil (events are suppressed).
func NewRegistry(bus *framework.EventBus) *Registry {
	return &Registry{
		active:   make(map[string]Tool),
		deferred: make(map[string]Tool),
		bus:      bus,
	}
}

// Register adds a tool to the active pool, removing it from deferred if present.
func (r *Registry) Register(t Tool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.active[t.Name()] = t
	delete(r.deferred, t.Name())
}

// RegisterDeferred adds a tool to the deferred pool (hidden from active context).
// If the tool was previously active it is moved back to deferred.
func (r *Registry) RegisterDeferred(t Tool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.deferred[t.Name()] = t
	delete(r.active, t.Name())
}

// ActiveTools returns schemas for all currently active tools.
// This is the lean context surface exposed to the LLM each turn.
func (r *Registry) ActiveTools() []ToolSchema {
	r.mu.RLock()
	defer r.mu.RUnlock()
	schemas := make([]ToolSchema, 0, len(r.active))
	for _, t := range r.active {
		schemas = append(schemas, t.Schema())
	}
	return schemas
}

// Search performs keyword matching across the deferred pool, activates the
// top matches, and returns their schemas. Up to maxResults tools are activated.
//
// If maxResults is ≤ 0 the default of 5 is used.
func (r *Registry) Search(query string, maxResults int) []ToolSchema {
	if maxResults <= 0 {
		maxResults = 5
	}

	r.mu.RLock()
	candidates := make([]Tool, 0, len(r.deferred))
	for _, t := range r.deferred {
		candidates = append(candidates, t)
	}
	r.mu.RUnlock()

	ranked := scoreQuery(query, candidates, maxResults)

	// Activate matched tools and collect their schemas.
	schemas := make([]ToolSchema, 0, len(ranked))
	for _, t := range ranked {
		// Activate under write lock; ignore "already active" condition.
		_ = r.Activate(t.Name())
		schemas = append(schemas, t.Schema())
	}
	return schemas
}

// Activate moves a tool from the deferred pool to the active pool.
// Returns nil if the tool is already active.
func (r *Registry) Activate(name string) error {
	r.mu.Lock()
	t, ok := r.deferred[name]
	if !ok {
		_, alreadyActive := r.active[name]
		r.mu.Unlock()
		if alreadyActive {
			return nil
		}
		return fmt.Errorf("tools: %q not found in deferred pool", name)
	}
	r.active[name] = t
	delete(r.deferred, name)
	r.mu.Unlock()

	r.emit(TopicToolActivated, name)
	return nil
}

// Deactivate moves a tool from the active pool back to the deferred pool.
func (r *Registry) Deactivate(name string) error {
	r.mu.Lock()
	t, ok := r.active[name]
	if !ok {
		r.mu.Unlock()
		return fmt.Errorf("tools: %q not found in active pool", name)
	}
	r.deferred[name] = t
	delete(r.active, name)
	r.mu.Unlock()

	r.emit(TopicToolDeactivated, name)
	return nil
}

// Execute runs the named tool (must be active) with the provided arguments.
func (r *Registry) Execute(name string, ctx context.Context, args map[string]any) (ToolResult, error) {
	r.mu.RLock()
	t, ok := r.active[name]
	r.mu.RUnlock()
	if !ok {
		return ToolResult{}, fmt.Errorf("tools: %q is not in the active pool", name)
	}
	return t.Execute(ctx, args)
}

// AuthorizedFor returns true if the given autonomy level satisfies the named
// tool's RequiredAutonomyLevel. Searches both pools; returns false if not found.
func (r *Registry) AuthorizedFor(name string, level AutonomyLevel) bool {
	r.mu.RLock()
	t, ok := r.active[name]
	if !ok {
		t, ok = r.deferred[name]
	}
	r.mu.RUnlock()
	if !ok {
		return false
	}
	return level >= t.Schema().RequiredAutonomyLevel
}

// emit publishes a tool lifecycle event on the framework bus.
// Called outside all locks to avoid deadlocks with synchronous bus handlers.
func (r *Registry) emit(topic, toolName string) {
	if r.bus == nil {
		return
	}
	r.bus.Publish(framework.Event{
		Topic: topic,
		Payload: map[string]any{
			"tool": toolName,
			"at":   time.Now(),
		},
	})
}
