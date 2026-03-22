package framework_test

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/framework"
)

func TestConfig_Defaults(t *testing.T) {
	cfg, err := framework.NewConfig(framework.ConfigOptions{})
	if err != nil {
		t.Fatalf("NewConfig: %v", err)
	}

	// Verify default values are present and typed correctly
	if cfg.GetDuration("orchestrator.heartbeat_interval") == 0 {
		t.Fatal("expected non-zero default for orchestrator.heartbeat_interval")
	}
}

func TestConfig_FileOverridesDefaults(t *testing.T) {
	dir := t.TempDir()
	cfgFile := filepath.Join(dir, "omega.yaml")

	content := `
orchestrator:
  heartbeat_interval: 30s
  max_nodes: 10
`
	if err := os.WriteFile(cfgFile, []byte(content), 0600); err != nil {
		t.Fatal(err)
	}

	cfg, err := framework.NewConfig(framework.ConfigOptions{ConfigFile: cfgFile})
	if err != nil {
		t.Fatalf("NewConfig with file: %v", err)
	}

	if cfg.GetDuration("orchestrator.heartbeat_interval") != 30*time.Second {
		t.Fatalf("expected 30s, got %v", cfg.GetDuration("orchestrator.heartbeat_interval"))
	}
	if cfg.GetInt("orchestrator.max_nodes") != 10 {
		t.Fatalf("expected 10, got %d", cfg.GetInt("orchestrator.max_nodes"))
	}
}

func TestConfig_EnvVarOverridesFile(t *testing.T) {
	dir := t.TempDir()
	cfgFile := filepath.Join(dir, "omega.yaml")
	content := `
orchestrator:
  max_nodes: 5
`
	_ = os.WriteFile(cfgFile, []byte(content), 0600)

	t.Setenv("OMEGA_ORCHESTRATOR_MAX_NODES", "99")

	cfg, err := framework.NewConfig(framework.ConfigOptions{
		ConfigFile: cfgFile,
		EnvPrefix:  "OMEGA",
	})
	if err != nil {
		t.Fatalf("NewConfig: %v", err)
	}

	if cfg.GetInt("orchestrator.max_nodes") != 99 {
		t.Fatalf("expected env override 99, got %d", cfg.GetInt("orchestrator.max_nodes"))
	}
}

func TestConfig_SetAndGet(t *testing.T) {
	cfg, err := framework.NewConfig(framework.ConfigOptions{})
	if err != nil {
		t.Fatal(err)
	}

	cfg.Set("mykey", "myval")
	if cfg.GetString("mykey") != "myval" {
		t.Fatalf("expected 'myval', got %q", cfg.GetString("mykey"))
	}
}

func TestConfig_Sub(t *testing.T) {
	dir := t.TempDir()
	cfgFile := filepath.Join(dir, "omega.yaml")
	content := `
adversarial:
  debate_rounds: 3
  enabled: true
`
	_ = os.WriteFile(cfgFile, []byte(content), 0600)

	cfg, err := framework.NewConfig(framework.ConfigOptions{ConfigFile: cfgFile})
	if err != nil {
		t.Fatal(err)
	}

	sub := cfg.Sub("adversarial")
	if sub == nil {
		t.Fatal("expected non-nil sub-config")
	}
	if sub.GetInt("debate_rounds") != 3 {
		t.Fatalf("expected 3, got %d", sub.GetInt("debate_rounds"))
	}
	if !sub.GetBool("enabled") {
		t.Fatal("expected enabled=true")
	}
}

func TestConfig_HotReload(t *testing.T) {
	dir := t.TempDir()
	cfgFile := filepath.Join(dir, "omega.yaml")

	initial := "orchestrator:\n  max_nodes: 1\n"
	if err := os.WriteFile(cfgFile, []byte(initial), 0600); err != nil {
		t.Fatal(err)
	}

	cfg, err := framework.NewConfig(framework.ConfigOptions{
		ConfigFile: cfgFile,
		HotReload:  true,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer cfg.StopWatch()

	changed := make(chan struct{}, 1)
	cfg.OnChange(func() {
		changed <- struct{}{}
	})

	// Write new value
	updated := "orchestrator:\n  max_nodes: 42\n"
	if err := os.WriteFile(cfgFile, []byte(updated), 0600); err != nil {
		t.Fatal(err)
	}

	select {
	case <-changed:
		// good
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for config hot-reload notification")
	}

	if cfg.GetInt("orchestrator.max_nodes") != 42 {
		t.Fatalf("expected hot-reloaded value 42, got %d", cfg.GetInt("orchestrator.max_nodes"))
	}
}

func TestConfig_DomainRegistration(t *testing.T) {
	cfg, err := framework.NewConfig(framework.ConfigOptions{})
	if err != nil {
		t.Fatal(err)
	}

	schema := map[string]any{
		"signal_ttl":  "5m",
		"max_signals": 100,
	}
	cfg.RegisterDomainDefaults("victoria", schema)

	if cfg.GetString("victoria.signal_ttl") != "5m" {
		t.Fatalf("expected domain default '5m', got %q", cfg.GetString("victoria.signal_ttl"))
	}
	if cfg.GetInt("victoria.max_signals") != 100 {
		t.Fatalf("expected domain default 100, got %d", cfg.GetInt("victoria.max_signals"))
	}
}
