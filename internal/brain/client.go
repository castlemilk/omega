// Package brain provides a multi-provider LLM client for the Go side of Omega.
//
// Supported providers (OMEGA_BRAIN_PROVIDER):
//
//	anthropic   — Anthropic Messages API via official SDK (default)
//	openrouter  — OpenRouter.ai OpenAI-compatible endpoint (net/http, no extra SDK)
//
// Model tiers:
//
//	QUICK — fast/cheap model (default: claude-haiku-4-5-20251001 / openai/gpt-4o-mini)
//	DEEP  — powerful model   (default: claude-sonnet-4-6      / openai/gpt-4o)
//
// Env overrides:
//
//	OMEGA_BRAIN_PROVIDER        anthropic | openrouter
//	OMEGA_BRAIN_QUICK_MODEL     override QUICK model name
//	OMEGA_BRAIN_DEEP_MODEL      override DEEP  model name
//	ANTHROPIC_API_KEY           required for provider=anthropic
//	OPENROUTER_API_KEY          required for provider=openrouter
package brain

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	anthropic "github.com/anthropics/anthropic-sdk-go"
	"github.com/anthropics/anthropic-sdk-go/option"
)

// Provider selects the LLM backend.
type Provider int

const (
	ProviderAnthropic  Provider = iota // uses Anthropic SDK
	ProviderOpenRouter                 // uses OpenRouter (OpenAI-compat HTTP)
)

// ModelTier selects between cheap/fast and expensive/smart models.
type ModelTier int

const (
	QUICK ModelTier = iota
	DEEP
)

// defaults per provider
var defaults = map[Provider][2]string{
	ProviderAnthropic:  {"claude-haiku-4-5-20251001", "claude-sonnet-4-6"},
	ProviderOpenRouter: {"openai/gpt-4o-mini", "openai/gpt-4o"},
}

const (
	openRouterBase = "https://openrouter.ai/api/v1/chat/completions"
	maxTokens      = 512
	httpTimeout    = 30 * time.Second
)

// Client is the Go-side LLM client. Create with New(); check IsAvailable() before Consult().
type Client struct {
	provider   Provider
	quickModel string
	deepModel  string
	apiKey     string // Anthropic or OpenRouter key

	// Anthropic SDK client (zero value when provider != anthropic or key missing)
	antClient anthropic.Client
	antReady  bool
	// Shared HTTP client for OpenRouter calls
	httpClient *http.Client
}

// New reads config from env and returns a ready Client.
// IsAvailable() returns false when the required API key is absent.
func New() *Client {
	provider := resolveProvider()
	defs := defaults[provider]

	quick := os.Getenv("OMEGA_BRAIN_QUICK_MODEL")
	if quick == "" {
		quick = defs[0]
	}
	deep := os.Getenv("OMEGA_BRAIN_DEEP_MODEL")
	if deep == "" {
		deep = defs[1]
	}

	c := &Client{
		provider:   provider,
		quickModel: quick,
		deepModel:  deep,
		httpClient: &http.Client{Timeout: httpTimeout},
	}

	switch provider {
	case ProviderAnthropic:
		c.apiKey = os.Getenv("ANTHROPIC_API_KEY")
		if c.apiKey != "" {
			c.antClient = anthropic.NewClient(option.WithAPIKey(c.apiKey))
			c.antReady = true
		}
	case ProviderOpenRouter:
		c.apiKey = os.Getenv("OPENROUTER_API_KEY")
	}

	return c
}

// IsAvailable reports whether the required API key is configured.
func (c *Client) IsAvailable() bool {
	return c.apiKey != ""
}

// ProviderName returns a human-readable provider label.
func (c *Client) ProviderName() string {
	switch c.provider {
	case ProviderOpenRouter:
		return "openrouter"
	default:
		return "anthropic"
	}
}

// Consult sends prompt to the selected tier and returns the text response.
func (c *Client) Consult(ctx context.Context, prompt string, tier ModelTier) (string, error) {
	if !c.IsAvailable() {
		return "", fmt.Errorf("brain: API key not set for provider %s", c.ProviderName())
	}
	model := c.quickModel
	if tier == DEEP {
		model = c.deepModel
	}

	switch c.provider {
	case ProviderAnthropic:
		return c.consultAnthropic(ctx, prompt, model)
	case ProviderOpenRouter:
		return c.consultOpenRouter(ctx, prompt, model)
	default:
		return "", fmt.Errorf("brain: unknown provider %d", c.provider)
	}
}

// consultAnthropic calls the Anthropic Messages API via the official SDK.
func (c *Client) consultAnthropic(ctx context.Context, prompt, model string) (string, error) {
	if !c.antReady {
		return "", fmt.Errorf("brain: anthropic client not initialised")
	}
	msg, err := c.antClient.Messages.New(ctx, anthropic.MessageNewParams{
		Model:     model,
		MaxTokens: maxTokens,
		Messages: []anthropic.MessageParam{
			anthropic.NewUserMessage(anthropic.NewTextBlock(prompt)),
		},
	})
	if err != nil {
		return "", fmt.Errorf("brain: anthropic API: %w", err)
	}
	for _, block := range msg.Content {
		if block.Type == "text" {
			return strings.TrimSpace(block.Text), nil
		}
	}
	return "", fmt.Errorf("brain: no text content in anthropic response")
}

// consultOpenRouter calls OpenRouter using the OpenAI chat completions format.
func (c *Client) consultOpenRouter(ctx context.Context, prompt, model string) (string, error) {
	body, err := json.Marshal(map[string]any{
		"model":      model,
		"max_tokens": maxTokens,
		"messages":   []map[string]any{{"role": "user", "content": prompt}},
	})
	if err != nil {
		return "", fmt.Errorf("brain: marshal openrouter request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, openRouterBase, bytes.NewReader(body))
	if err != nil {
		return "", fmt.Errorf("brain: build openrouter request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	req.Header.Set("HTTP-Referer", "https://github.com/benebsworth/omega")
	req.Header.Set("X-Title", "omega")

	resp, err := c.httpClient.Do(req) //nolint:gosec // URL is a fixed constant
	if err != nil {
		return "", fmt.Errorf("brain: openrouter http: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("brain: read openrouter body: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("brain: openrouter API error %d: %s", resp.StatusCode, strings.TrimSpace(string(raw)))
	}

	var result struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.Unmarshal(raw, &result); err != nil {
		return "", fmt.Errorf("brain: unmarshal openrouter response: %w", err)
	}
	if len(result.Choices) == 0 {
		return "", fmt.Errorf("brain: no choices in openrouter response")
	}
	return strings.TrimSpace(result.Choices[0].Message.Content), nil
}

// resolveProvider reads OMEGA_BRAIN_PROVIDER and returns the corresponding Provider.
func resolveProvider() Provider {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("OMEGA_BRAIN_PROVIDER"))) {
	case "openrouter":
		return ProviderOpenRouter
	default:
		return ProviderAnthropic
	}
}
