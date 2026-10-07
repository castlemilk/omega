package framework_test

import (
	"os"
	"path/filepath"
	"sync/atomic"
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
	for _, mode := range []string{"in_place", "empty_then_complete"} {
		t.Run(mode, func(t *testing.T) {
			cfgFile := filepath.Join(t.TempDir(), "omega.yaml")
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
			if got := cfg.GetInt("orchestrator.max_nodes"); got != 1 {
				t.Fatalf("expected initial value 1, got %d", got)
			}

			// Read on Viper's watcher goroutine, after it reloads the file. Reading
			// from the test goroutine can race with another filesystem event.
			var observed atomic.Int64
			changed := make(chan struct{}, 1)
			cfg.OnChange(func() {
				observed.Store(int64(cfg.GetInt("orchestrator.max_nodes")))
				select {
				case changed <- struct{}{}:
				default: // duplicate events must never block the watcher
				}
			})
			waitForValue := func(want int64) {
				t.Helper()
				timer := time.NewTimer(2 * time.Second)
				defer timer.Stop()
				for {
					select {
					case <-changed:
						if observed.Load() == want {
							return
						}
					case <-timer.C:
						t.Fatalf("expected hot-reloaded value %d, last observed %d", want, observed.Load())
					}
				}
			}

			if mode == "empty_then_complete" {
				// Force the truncate/write interleaving seen in CI: an empty YAML
				// file loads defaults (32), before the completed write loads 42.
				if err := os.WriteFile(cfgFile, nil, 0600); err != nil {
					t.Fatal(err)
				}
				waitForValue(32)
			}

			updated := "orchestrator:\n  max_nodes: 42\n"
			if err := os.WriteFile(cfgFile, []byte(updated), 0600); err != nil {
				t.Fatal(err)
			}
			// A file write may emit several events, including one while the file
			// is truncated. Assert the completed value, not the first notification.
			waitForValue(42)
		})
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
