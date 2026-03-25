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
)

const (
	openRouterBase      = "https://openrouter.ai/api/v1/chat/completions"
	openRouterQuickDef  = "openai/gpt-4o-mini"
	openRouterDeepDef   = "openai/gpt-4o"
	openRouterMaxTokens = 512
	openRouterTimeout   = 30 * time.Second
)

// OpenRouterProvider calls OpenRouter.ai using the OpenAI chat-completions format.
// Requires OPENROUTER_API_KEY.
type OpenRouterProvider struct {
	apiKey     string
	quickModel string
	deepModel  string
	http       *http.Client
}

// NewOpenRouterProvider creates an OpenRouterProvider reading config from env.
func NewOpenRouterProvider() *OpenRouterProvider {
	return &OpenRouterProvider{
		apiKey:     os.Getenv("OPENROUTER_API_KEY"),
		quickModel: orDefault(os.Getenv("OMEGA_BRAIN_QUICK_MODEL"), openRouterQuickDef),
		deepModel:  orDefault(os.Getenv("OMEGA_BRAIN_DEEP_MODEL"), openRouterDeepDef),
		http:       &http.Client{Timeout: openRouterTimeout},
	}
}

func (p *OpenRouterProvider) Name() string { return "openrouter" }

func (p *OpenRouterProvider) IsAvailable() bool { return p.apiKey != "" }

func (p *OpenRouterProvider) AuthStatus() AuthResult {
	if p.apiKey == "" {
		return AuthResult{AuthNeedsConfig, "set OPENROUTER_API_KEY"}
	}
	return AuthResult{AuthAuthenticated, "OPENROUTER_API_KEY present"}
}

func (p *OpenRouterProvider) Authenticate() error {
	if p.apiKey == "" {
		return &AuthError{"openrouter", "OPENROUTER_API_KEY not set"}
	}
	return nil
}

func (p *OpenRouterProvider) Models() map[ModelTier]string {
	return map[ModelTier]string{
		QUICK: p.quickModel,
		DEEP:  p.deepModel,
	}
}

func (p *OpenRouterProvider) Consult(ctx context.Context, prompt string, tier ModelTier) (string, error) {
	if p.apiKey == "" {
		return "", &AuthError{"openrouter", "OPENROUTER_API_KEY not set"}
	}
	model := p.quickModel
	if tier == DEEP {
		model = p.deepModel
	}

	body, err := json.Marshal(map[string]any{
		"model":      model,
		"max_tokens": openRouterMaxTokens,
		"messages":   []map[string]any{{"role": "user", "content": prompt}},
	})
	if err != nil {
		return "", fmt.Errorf("openrouter: marshal request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, openRouterBase, bytes.NewReader(body))
	if err != nil {
		return "", fmt.Errorf("openrouter: build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+p.apiKey)
	req.Header.Set("HTTP-Referer", "https://github.com/benebsworth/omega")
	req.Header.Set("X-Title", "omega")

	resp, err := p.http.Do(req) //nolint:gosec
	if err != nil {
		return "", fmt.Errorf("openrouter: HTTP: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("openrouter: read body: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("openrouter: API error %d: %s", resp.StatusCode, strings.TrimSpace(string(raw)))
	}

	var result struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.Unmarshal(raw, &result); err != nil {
		return "", fmt.Errorf("openrouter: unmarshal response: %w", err)
	}
	if len(result.Choices) == 0 {
		return "", fmt.Errorf("openrouter: no choices in response")
	}
	return strings.TrimSpace(result.Choices[0].Message.Content), nil
}
