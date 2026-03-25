package brain

import (
	"context"
	"fmt"
	"os"
	"strings"

	anthropic "github.com/anthropics/anthropic-sdk-go"
	"github.com/anthropics/anthropic-sdk-go/option"
)

const (
	anthropicQuickDefault = "claude-haiku-4-5-20251001"
	anthropicDeepDefault  = "claude-sonnet-4-6"
)

// AnthropicProvider uses the official anthropic-sdk-go to call the Anthropic Messages API.
// Requires ANTHROPIC_API_KEY.
type AnthropicProvider struct {
	apiKey     string
	quickModel string
	deepModel  string
	sdkClient  anthropic.Client
	ready      bool
}

// NewAnthropicProvider creates an AnthropicProvider reading config from env.
func NewAnthropicProvider() *AnthropicProvider {
	p := &AnthropicProvider{
		apiKey:     os.Getenv("ANTHROPIC_API_KEY"),
		quickModel: orDefault(os.Getenv("OMEGA_BRAIN_QUICK_MODEL"), anthropicQuickDefault),
		deepModel:  orDefault(os.Getenv("OMEGA_BRAIN_DEEP_MODEL"), anthropicDeepDefault),
	}
	if p.apiKey != "" {
		p.sdkClient = anthropic.NewClient(option.WithAPIKey(p.apiKey))
		p.ready = true
	}
	return p
}

func (p *AnthropicProvider) Name() string { return "anthropic" }

func (p *AnthropicProvider) IsAvailable() bool { return p.ready }

func (p *AnthropicProvider) AuthStatus() AuthResult {
	if p.apiKey == "" {
		return AuthResult{AuthNeedsConfig, "set ANTHROPIC_API_KEY"}
	}
	return AuthResult{AuthAuthenticated, "ANTHROPIC_API_KEY present"}
}

func (p *AnthropicProvider) Authenticate() error {
	if p.apiKey == "" {
		return &AuthError{"anthropic", "ANTHROPIC_API_KEY not set"}
	}
	return nil
}

func (p *AnthropicProvider) Models() map[ModelTier]string {
	return map[ModelTier]string{
		QUICK: p.quickModel,
		DEEP:  p.deepModel,
	}
}

func (p *AnthropicProvider) Consult(ctx context.Context, prompt string, tier ModelTier) (string, error) {
	if !p.ready {
		return "", &AuthError{"anthropic", "client not initialised — set ANTHROPIC_API_KEY"}
	}
	model := p.quickModel
	if tier == DEEP {
		model = p.deepModel
	}
	msg, err := p.sdkClient.Messages.New(ctx, anthropic.MessageNewParams{
		Model:     model,
		MaxTokens: maxTokens,
		Messages: []anthropic.MessageParam{
			anthropic.NewUserMessage(anthropic.NewTextBlock(prompt)),
		},
	})
	if err != nil {
		return "", fmt.Errorf("anthropic API: %w", err)
	}
	for _, block := range msg.Content {
		if block.Type == "text" {
			return strings.TrimSpace(block.Text), nil
		}
	}
	return "", fmt.Errorf("anthropic: no text block in response")
}
