package brain

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"strings"
)

// GenericCLIProvider runs any binary with the prompt on stdin, reading stdout.
// Configured entirely via env vars:
//
//	OMEGA_BRAIN_CLI_COMMAND    — binary name/path (required)
//	OMEGA_BRAIN_CLI_QUICK_ARGS — extra args for QUICK tier (space-separated)
//	OMEGA_BRAIN_CLI_DEEP_ARGS  — extra args for DEEP tier (space-separated)
//
// Example (kimi-cli):
//
//	OMEGA_BRAIN_CLI_COMMAND=kimi-cli
//	OMEGA_BRAIN_CLI_QUICK_ARGS=--model moonshot-v1-8k
//	OMEGA_BRAIN_CLI_DEEP_ARGS=--model kimi-k2
type GenericCLIProvider struct {
	binary    string
	quickArgs []string
	deepArgs  []string
}

// NewGenericCLIProvider creates a GenericCLIProvider from env.
// Returns nil when OMEGA_BRAIN_CLI_COMMAND is not set.
func NewGenericCLIProvider() *GenericCLIProvider {
	command := strings.TrimSpace(os.Getenv("OMEGA_BRAIN_CLI_COMMAND"))
	if command == "" {
		return nil
	}
	binary, _ := exec.LookPath(command)
	if binary == "" {
		binary = command // allow absolute paths
	}
	return &GenericCLIProvider{
		binary:    binary,
		quickArgs: splitArgs(os.Getenv("OMEGA_BRAIN_CLI_QUICK_ARGS")),
		deepArgs:  splitArgs(os.Getenv("OMEGA_BRAIN_CLI_DEEP_ARGS")),
	}
}

func (p *GenericCLIProvider) Name() string { return "cli:" + p.binary }

func (p *GenericCLIProvider) IsAvailable() bool {
	return p.binary != "" && p.AuthStatus().Status == AuthAuthenticated
}

func (p *GenericCLIProvider) AuthStatus() AuthResult {
	if p.binary == "" {
		return AuthResult{AuthNeedsConfig, "OMEGA_BRAIN_CLI_COMMAND not set or binary not found"}
	}
	if _, err := exec.LookPath(p.binary); err != nil {
		return AuthResult{AuthNeedsConfig, fmt.Sprintf("%s not found in PATH", p.binary)}
	}
	return AuthResult{AuthAuthenticated, p.binary + " found in PATH"}
}

func (p *GenericCLIProvider) Authenticate() error {
	s := p.AuthStatus()
	if s.Status != AuthAuthenticated {
		return &AuthError{"cli", s.Message}
	}
	return nil
}

func (p *GenericCLIProvider) Models() map[ModelTier]string {
	return map[ModelTier]string{
		QUICK: strings.Join(p.quickArgs, " "),
		DEEP:  strings.Join(p.deepArgs, " "),
	}
}

func (p *GenericCLIProvider) Consult(ctx context.Context, prompt string, tier ModelTier) (string, error) {
	args := p.quickArgs
	if tier == DEEP {
		args = p.deepArgs
	}
	cmd := exec.CommandContext(ctx, p.binary, args...) //nolint:gosec
	cmd.Stdin = strings.NewReader(prompt)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("cli %s: %w; stderr: %s", p.binary, err, strings.TrimSpace(stderr.String()))
	}
	out := strings.TrimSpace(stdout.String())
	if out == "" {
		return "", fmt.Errorf("cli %s: empty response", p.binary)
	}
	return out, nil
}

// splitArgs splits a space-separated argument string into a slice.
// Returns nil for empty input.
func splitArgs(s string) []string {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil
	}
	return strings.Fields(s)
}
