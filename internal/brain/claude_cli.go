package brain

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

const (
	claudeCLIQuickDefault = "claude-haiku-4-5"
	claudeCLIDeepDefault  = "claude-sonnet-4-6"
)

// ClaudeCLIProvider runs the `claude` CLI binary in non-interactive print mode.
//
// Auth detection: checks for ~/.claude directory (created by `claude auth login`).
// Quick: claude -p "<prompt>" --model claude-haiku-4-5
// Deep:  claude -p "<prompt>" --model claude-sonnet-4-6
type ClaudeCLIProvider struct {
	binary     string
	quickModel string
	deepModel  string
}

// NewClaudeCLIProvider creates a ClaudeCLIProvider.
func NewClaudeCLIProvider() *ClaudeCLIProvider {
	binary, _ := exec.LookPath("claude")
	return &ClaudeCLIProvider{
		binary:     binary,
		quickModel: orDefault(os.Getenv("OMEGA_BRAIN_QUICK_MODEL"), claudeCLIQuickDefault),
		deepModel:  orDefault(os.Getenv("OMEGA_BRAIN_DEEP_MODEL"), claudeCLIDeepDefault),
	}
}

func (p *ClaudeCLIProvider) Name() string { return "claude-cli" }

func (p *ClaudeCLIProvider) IsAvailable() bool {
	return p.binary != "" && p.AuthStatus().Status == AuthAuthenticated
}

func (p *ClaudeCLIProvider) AuthStatus() AuthResult {
	if p.binary == "" {
		return AuthResult{AuthNeedsConfig, "claude not found in PATH"}
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return AuthResult{AuthNeedsConfig, "cannot determine home dir"}
	}
	claudeDir := filepath.Join(home, ".claude")
	if _, err := os.Stat(claudeDir); os.IsNotExist(err) {
		return AuthResult{AuthNeedsConfig, "~/.claude not found; run 'claude auth login'"}
	}
	return AuthResult{AuthAuthenticated, "claude CLI ready"}
}

func (p *ClaudeCLIProvider) Authenticate() error {
	s := p.AuthStatus()
	if s.Status != AuthAuthenticated {
		return &AuthError{"claude-cli", s.Message}
	}
	return nil
}

func (p *ClaudeCLIProvider) Models() map[ModelTier]string {
	return map[ModelTier]string{
		QUICK: p.quickModel,
		DEEP:  p.deepModel,
	}
}

func (p *ClaudeCLIProvider) Consult(ctx context.Context, prompt string, tier ModelTier) (string, error) {
	if p.binary == "" {
		return "", &AuthError{"claude-cli", "binary not found"}
	}
	model := p.quickModel
	if tier == DEEP {
		model = p.deepModel
	}
	// claude -p "<prompt>" --model <model>
	cmd := exec.CommandContext(ctx, p.binary, "-p", prompt, "--model", model) //nolint:gosec // prompt is user-supplied brain input, binary is from PATH lookup
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("claude-cli: %w; stderr: %s", err, strings.TrimSpace(stderr.String()))
	}
	out := strings.TrimSpace(stdout.String())
	if out == "" {
		return "", fmt.Errorf("claude-cli: empty response (stderr: %s)", strings.TrimSpace(stderr.String()))
	}
	return out, nil
}
