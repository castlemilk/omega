// Package brain provides a pluggable LLM provider layer for the Go side of Omega.
//
// Architecture:
//
//	BrainProvider  — interface every backend must satisfy
//	ProviderRegistry — ordered fallback chain; first available provider wins
//	Client          — public entry point; wraps a ProviderRegistry
//
// Providers:
//
//	AnthropicProvider   — Anthropic Messages API (official SDK)
//	OpenRouterProvider  — OpenRouter.ai OpenAI-compatible HTTP endpoint
//	ClaudeCLIProvider   — `claude` CLI binary (stdin/arg)
//	CodexCLIProvider    — `codex` CLI binary (stdin)
//	OllamaCLIProvider   — `ollama run` (stdin)
//	GenericCLIProvider  — any command with stdin→stdout contract
//
// Env config:
//
//	OMEGA_BRAIN_PROVIDER       comma-separated priority list, e.g. "anthropic,claude-cli"
//	                           or single value. Default: auto (anthropic → claude-cli → openrouter → ollama)
//	OMEGA_BRAIN_QUICK_MODEL    override quick-tier model name
//	OMEGA_BRAIN_DEEP_MODEL     override deep-tier model name
//	ANTHROPIC_API_KEY          required for AnthropicProvider
//	OPENROUTER_API_KEY         required for OpenRouterProvider
//	OMEGA_BRAIN_CLI_COMMAND    binary for GenericCLIProvider
//	OMEGA_BRAIN_CLI_QUICK_ARGS args for generic CLI quick tier
//	OMEGA_BRAIN_CLI_DEEP_ARGS  args for generic CLI deep tier
package brain

import "context"

// ---------------------------------------------------------------------------
// ModelTier
// ---------------------------------------------------------------------------

// ModelTier selects between the fast/cheap model and the slow/smart model.
type ModelTier int

const (
	QUICK ModelTier = iota // fast, cheap — high-frequency signal calls
	DEEP                   // slow, smart — adversarial debate / planning
)

// ---------------------------------------------------------------------------
// Auth types
// ---------------------------------------------------------------------------

// AuthStatus describes the authentication state of a provider.
type AuthStatus int

const (
	AuthAuthenticated AuthStatus = iota // credentials present and usable
	AuthNeedsConfig                     // credentials missing; user must configure
	AuthFailed                          // credentials present but rejected
)

// AuthResult is returned by BrainProvider.AuthStatus().
type AuthResult struct {
	Status  AuthStatus
	Message string // human-readable explanation
}

// AuthError is returned by Authenticate() when credentials cannot be obtained.
type AuthError struct {
	Provider string
	Message  string
}

func (e *AuthError) Error() string {
	return "brain: " + e.Provider + ": " + e.Message
}

// ---------------------------------------------------------------------------
// BrainProvider interface
// ---------------------------------------------------------------------------

// BrainProvider is the contract every LLM backend must satisfy.
type BrainProvider interface {
	// Name returns a stable lowercase identifier, e.g. "anthropic", "claude-cli".
	Name() string

	// IsAvailable returns true when this provider can accept requests right now.
	// Implementations should be cheap (no network calls).
	IsAvailable() bool

	// Consult sends prompt at the given tier and returns the text response.
	Consult(ctx context.Context, prompt string, tier ModelTier) (string, error)

	// Models returns the model identifier used for each tier.
	Models() map[ModelTier]string

	// AuthStatus reports the current authentication state without side-effects.
	AuthStatus() AuthResult

	// Authenticate attempts to obtain or validate credentials.
	// Returns *AuthError if they cannot be obtained.
	Authenticate() error
}
