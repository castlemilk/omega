package brain

import (
	"context"
	"fmt"
	"log"
)

// ProviderRegistry holds an ordered list of BrainProviders.
// The first available provider is used; on failure the next is tried.
type ProviderRegistry struct {
	providers []BrainProvider
}

// Register appends a provider to the end of the fallback chain.
func (r *ProviderRegistry) Register(p BrainProvider) {
	r.providers = append(r.providers, p)
}

// All returns all registered providers (for status inspection).
func (r *ProviderRegistry) All() []BrainProvider {
	return r.providers
}

// Primary returns the first available provider, or nil when none are ready.
func (r *ProviderRegistry) Primary() BrainProvider {
	for _, p := range r.providers {
		if p.IsAvailable() {
			return p
		}
	}
	return nil
}

// IsAvailable reports whether at least one provider is ready.
func (r *ProviderRegistry) IsAvailable() bool {
	return r.Primary() != nil
}

// Consult tries each available provider in priority order.
// Returns the first successful response.
// Returns an error only when every available provider fails.
func (r *ProviderRegistry) Consult(ctx context.Context, prompt string, tier ModelTier) (string, error) {
	var lastErr error
	for _, p := range r.providers {
		if !p.IsAvailable() {
			continue
		}
		result, err := p.Consult(ctx, prompt, tier)
		if err == nil {
			return result, nil
		}
		log.Printf("brain: provider %q failed (%v); trying next", p.Name(), err)
		lastErr = err
	}
	if lastErr != nil {
		return "", fmt.Errorf("brain: all providers failed; last: %w", lastErr)
	}
	return "", fmt.Errorf("brain: no providers available")
}
