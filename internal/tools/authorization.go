package tools

import (
	"fmt"
	"sync"

	"github.com/benebsworth/omega/internal/core"
)

// ---------------------------------------------------------------------------
// Default policy constants
// ---------------------------------------------------------------------------

// Minimum autonomy levels for well-known tool categories.
// Any tool not listed in a policy falls back to AutonomyLevelManual (always
// available to supervised operators).
const (
	// levelAlways — tools available at any autonomy level (read-only, safe ops).
	levelAlways = core.AutonomyLevelUnspecified

	// levelSupervised — tools that modify state and require at-least-supervised ops.
	levelSupervised = core.AutonomyLevelSupervised

	// levelAutonomous — tools that must only run when the agent is fully autonomous.
	levelAutonomous = core.AutonomyLevelFull
)

// defaultPolicyRules maps tool name patterns to their minimum autonomy level.
// Loaded once at startup; individual entries can be overridden via config.
var defaultPolicyRules = map[string]core.AutonomyLevel{
	// Destructive / side-effecting operations require SUPERVISED or higher.
	"bash":       levelSupervised,
	"write_file": levelSupervised,
	"deploy":     levelSupervised,

	// Read-only / query operations are always available.
	"read_file": levelAlways,
	"search":    levelAlways,
	"query":     levelAlways,

	// Self-modifying operations require full autonomy.
	"reconfigure":      levelAutonomous,
	"promote_autonomy": levelAutonomous,
}

// ---------------------------------------------------------------------------
// AuthorizationPolicy
// ---------------------------------------------------------------------------

// AuthorizationPolicy maps tool names to their minimum required AutonomyLevel.
// The zero value is ready to use with DefaultPolicies() applied.
// All methods are safe for concurrent use.
type AuthorizationPolicy struct {
	mu    sync.RWMutex
	rules map[string]core.AutonomyLevel
}

// NewAuthorizationPolicy returns a policy pre-loaded with the default rules.
func NewAuthorizationPolicy() *AuthorizationPolicy {
	p := &AuthorizationPolicy{
		rules: make(map[string]core.AutonomyLevel, len(defaultPolicyRules)),
	}
	for name, level := range defaultPolicyRules {
		p.rules[name] = level
	}
	return p
}

// Set adds or replaces the minimum autonomy level for a single tool.
func (p *AuthorizationPolicy) Set(toolName string, minLevel core.AutonomyLevel) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.rules[toolName] = minLevel
}

// Remove deletes the explicit rule for toolName; future checks will fall back
// to the levelAlways default.
func (p *AuthorizationPolicy) Remove(toolName string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	delete(p.rules, toolName)
}

// Load replaces all current rules with the provided map.
// Used for hot-reload from config; the map is copied so the caller may reuse it.
func (p *AuthorizationPolicy) Load(rules map[string]core.AutonomyLevel) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.rules = make(map[string]core.AutonomyLevel, len(rules))
	for k, v := range rules {
		p.rules[k] = v
	}
}

// Authorize returns (allowed bool, reason string).
//
// allowed is true when the given level satisfies the tool's minimum requirement.
// reason explains the decision for logging or user-facing messages.
func (p *AuthorizationPolicy) Authorize(toolName string, level core.AutonomyLevel) (bool, string) {
	p.mu.RLock()
	minLevel, ok := p.rules[toolName]
	p.mu.RUnlock()

	if !ok {
		// No explicit rule: always available.
		return true, fmt.Sprintf("tool %q has no explicit policy (default: always available)", toolName)
	}

	if level >= minLevel {
		return true, fmt.Sprintf("autonomy level %d satisfies minimum %d for tool %q",
			level, minLevel, toolName)
	}

	return false, fmt.Sprintf("autonomy level %d is below minimum %d required for tool %q",
		level, minLevel, toolName)
}

// MinLevel returns the minimum autonomy level recorded for toolName.
// If no rule exists, levelAlways (0) is returned.
func (p *AuthorizationPolicy) MinLevel(toolName string) core.AutonomyLevel {
	p.mu.RLock()
	defer p.mu.RUnlock()
	if lvl, ok := p.rules[toolName]; ok {
		return lvl
	}
	return levelAlways
}

// Snapshot returns a copy of all current rules. Safe to call concurrently.
func (p *AuthorizationPolicy) Snapshot() map[string]core.AutonomyLevel {
	p.mu.RLock()
	defer p.mu.RUnlock()
	out := make(map[string]core.AutonomyLevel, len(p.rules))
	for k, v := range p.rules {
		out[k] = v
	}
	return out
}
