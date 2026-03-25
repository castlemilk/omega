// Package brain — see provider.go for package-level documentation.
package brain

import (
	"context"
	"fmt"
	"log"
	"os"
	"strings"
	"time"
)

const (
	maxTokens   = 512
	cliTimeout  = 30 * time.Second
)

// Client is the public entry point for the Go-side LLM brain.
// Create with New(); check IsAvailable() before calling Consult().
//
// Internally it holds a ProviderRegistry. The first available provider in
// the registry handles each call; on failure the next is tried automatically.
type Client struct {
	registry *ProviderRegistry
}

// New reads config from env and returns a ready Client.
//
// Provider selection via OMEGA_BRAIN_PROVIDER (comma-separated priority list):
//
//	"auto"        — anthropic → claude-cli → openrouter → ollama (default)
//	"anthropic"   — Anthropic API only
//	"claude-cli"  — claude CLI only
//	"openrouter"  — OpenRouter API only
//	"ollama"      — Ollama CLI only
//	"codex"       — Codex CLI only
//	"cli"         — GenericCLIProvider (needs OMEGA_BRAIN_CLI_COMMAND)
//	"a,b,c"       — custom ordered list
func New() *Client {
	registry := &ProviderRegistry{}
	providerEnv := strings.ToLower(strings.TrimSpace(os.Getenv("OMEGA_BRAIN_PROVIDER")))
	if providerEnv == "" {
		providerEnv = "auto"
	}

	if providerEnv == "auto" {
		// Auto: try all in sensible priority order
		registry.Register(NewAnthropicProvider())
		registry.Register(NewClaudeCLIProvider())
		registry.Register(NewOpenRouterProvider())
		registry.Register(NewOllamaCLIProvider())
		// GenericCLI only if explicitly configured
		if gp := NewGenericCLIProvider(); gp != nil {
			registry.Register(gp)
		}
	} else {
		for _, name := range strings.Split(providerEnv, ",") {
			name = strings.TrimSpace(name)
			if p := buildProvider(name); p != nil {
				registry.Register(p)
			} else {
				log.Printf("brain: unknown provider — skipping: %q", name) //nolint:gosec
			}
		}
	}

	c := &Client{registry: registry}
	primary := registry.Primary()
	if primary != nil {
		log.Printf("brain: ready — primary provider: %s", primary.Name())
	} else {
		logProviderStatus(registry)
	}
	return c
}

// IsAvailable reports whether at least one provider is ready.
func (c *Client) IsAvailable() bool {
	return c.registry.IsAvailable()
}

// ProviderName returns the name of the current primary provider, or "none".
func (c *Client) ProviderName() string {
	if p := c.registry.Primary(); p != nil {
		return p.Name()
	}
	return "none"
}

// Consult sends prompt to the primary (or fallback) provider at the given tier.
// Returns an error when all providers are unavailable or all fail.
func (c *Client) Consult(ctx context.Context, prompt string, tier ModelTier) (string, error) {
	if !c.registry.IsAvailable() {
		return "", fmt.Errorf("brain: no providers available — configure OMEGA_BRAIN_PROVIDER and credentials")
	}
	tctx, cancel := context.WithTimeout(ctx, cliTimeout)
	defer cancel()
	return c.registry.Consult(tctx, prompt, tier)
}

// Registry returns the underlying ProviderRegistry for status inspection.
func (c *Client) Registry() *ProviderRegistry {
	return c.registry
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func buildProvider(name string) BrainProvider {
	switch name {
	case "anthropic":
		return NewAnthropicProvider()
	case "openrouter":
		return NewOpenRouterProvider()
	case "claude-cli", "claude":
		return NewClaudeCLIProvider()
	case "codex":
		return NewCodexCLIProvider()
	case "ollama":
		return NewOllamaCLIProvider()
	case "cli":
		return NewGenericCLIProvider()
	default:
		return nil
	}
}

func logProviderStatus(r *ProviderRegistry) {
	log.Printf("brain: no providers available — status:")
	for _, p := range r.All() {
		s := p.AuthStatus()
		log.Printf("  %-14s %s", p.Name()+":", s.Message)
	}
}

// orDefault returns val if non-empty, otherwise def.
func orDefault(val, def string) string {
	if val != "" {
		return val
	}
	return def
}
