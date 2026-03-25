package brain

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
	"strings"
)

const (
	ollamaQuickDefault = "llama3"
	ollamaDeepDefault  = "mixtral"
)

// OllamaCLIProvider runs `ollama run <model>` with the prompt on stdin.
// No auth required — Ollama runs locally.
//
// Quick: echo "<prompt>" | ollama run llama3
// Deep:  echo "<prompt>" | ollama run mixtral
type OllamaCLIProvider struct {
	binary     string
	quickModel string
	deepModel  string
}

// NewOllamaCLIProvider creates an OllamaCLIProvider.
func NewOllamaCLIProvider() *OllamaCLIProvider {
	binary, _ := exec.LookPath("ollama")
	return &OllamaCLIProvider{
		binary:     binary,
		quickModel: orDefault("", ollamaQuickDefault),
		deepModel:  orDefault("", ollamaDeepDefault),
	}
}

func (p *OllamaCLIProvider) Name() string { return "ollama" }

func (p *OllamaCLIProvider) IsAvailable() bool {
	return p.binary != "" && p.AuthStatus().Status == AuthAuthenticated
}

func (p *OllamaCLIProvider) AuthStatus() AuthResult {
	if p.binary == "" {
		return AuthResult{AuthNeedsConfig, "ollama not found in PATH"}
	}
	// Verify ollama daemon is running by checking if list works
	cmd := exec.Command(p.binary, "list") //nolint:gosec // binary resolved from PATH lookup
	if err := cmd.Run(); err != nil {
		return AuthResult{AuthNeedsConfig, "ollama daemon not running; run 'ollama serve'"}
	}
	return AuthResult{AuthAuthenticated, "ollama CLI ready"}
}

func (p *OllamaCLIProvider) Authenticate() error {
	s := p.AuthStatus()
	if s.Status != AuthAuthenticated {
		return &AuthError{"ollama", s.Message}
	}
	return nil
}

func (p *OllamaCLIProvider) Models() map[ModelTier]string {
	return map[ModelTier]string{
		QUICK: p.quickModel,
		DEEP:  p.deepModel,
	}
}

func (p *OllamaCLIProvider) Consult(ctx context.Context, prompt string, tier ModelTier) (string, error) {
	if p.binary == "" {
		return "", &AuthError{"ollama", "binary not found"}
	}
	model := p.quickModel
	if tier == DEEP {
		model = p.deepModel
	}
	// echo prompt | ollama run <model>
	cmd := exec.CommandContext(ctx, p.binary, "run", model) //nolint:gosec // binary from PATH; model is constant string
	cmd.Stdin = strings.NewReader(prompt)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("ollama: %w; stderr: %s", err, strings.TrimSpace(stderr.String()))
	}
	out := strings.TrimSpace(stdout.String())
	if out == "" {
		return "", fmt.Errorf("ollama: empty response")
	}
	return out, nil
}
