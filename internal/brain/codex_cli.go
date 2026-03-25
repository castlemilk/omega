package brain

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"strings"
)

const (
	codexQuickDefault = "o4-mini"
	codexDeepDefault  = "o3"
)

// CodexCLIProvider runs the `codex` CLI binary (OpenAI Codex CLI).
// Prompt is passed via stdin; response is read from stdout.
//
// Auth detection: checks for OPENAI_API_KEY env var or ~/.codex/config.json.
// Quick: echo "<prompt>" | codex --model o4-mini --quiet
// Deep:  echo "<prompt>" | codex --model o3 --quiet
type CodexCLIProvider struct {
	binary     string
	quickModel string
	deepModel  string
}

// NewCodexCLIProvider creates a CodexCLIProvider.
func NewCodexCLIProvider() *CodexCLIProvider {
	binary, _ := exec.LookPath("codex")
	return &CodexCLIProvider{
		binary:     binary,
		quickModel: orDefault(os.Getenv("OMEGA_BRAIN_QUICK_MODEL"), codexQuickDefault),
		deepModel:  orDefault(os.Getenv("OMEGA_BRAIN_DEEP_MODEL"), codexDeepDefault),
	}
}

func (p *CodexCLIProvider) Name() string { return "codex" }

func (p *CodexCLIProvider) IsAvailable() bool {
	return p.binary != "" && p.AuthStatus().Status == AuthAuthenticated
}

func (p *CodexCLIProvider) AuthStatus() AuthResult {
	if p.binary == "" {
		return AuthResult{AuthNeedsConfig, "codex not found in PATH"}
	}
	// Codex CLI uses OPENAI_API_KEY or ~/.codex config
	if os.Getenv("OPENAI_API_KEY") != "" {
		return AuthResult{AuthAuthenticated, "OPENAI_API_KEY present"}
	}
	home, _ := os.UserHomeDir()
	codexConfig := strings.Join([]string{home, ".codex", "config.json"}, string(os.PathSeparator))
	if _, err := os.Stat(codexConfig); err == nil {
		return AuthResult{AuthAuthenticated, "~/.codex/config.json found"}
	}
	return AuthResult{AuthNeedsConfig, "set OPENAI_API_KEY or run 'codex auth'"}
}

func (p *CodexCLIProvider) Authenticate() error {
	s := p.AuthStatus()
	if s.Status != AuthAuthenticated {
		return &AuthError{"codex", s.Message}
	}
	return nil
}

func (p *CodexCLIProvider) Models() map[ModelTier]string {
	return map[ModelTier]string{
		QUICK: p.quickModel,
		DEEP:  p.deepModel,
	}
}

func (p *CodexCLIProvider) Consult(ctx context.Context, prompt string, tier ModelTier) (string, error) {
	if p.binary == "" {
		return "", &AuthError{"codex", "binary not found"}
	}
	model := p.quickModel
	if tier == DEEP {
		model = p.deepModel
	}
	// echo prompt | codex --model <model> --quiet
	cmd := exec.CommandContext(ctx, p.binary, "--model", model, "--quiet") //nolint:gosec // binary resolved from PATH; prompt passed via stdin
	cmd.Stdin = strings.NewReader(prompt)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("codex: %w; stderr: %s", err, strings.TrimSpace(stderr.String()))
	}
	out := strings.TrimSpace(stdout.String())
	if out == "" {
		return "", fmt.Errorf("codex: empty response")
	}
	return out, nil
}
