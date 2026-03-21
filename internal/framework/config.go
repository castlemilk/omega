package framework

import (
	"strings"
	"sync"
	"time"

	"github.com/fsnotify/fsnotify"
	"github.com/spf13/viper"
)

// ── ConfigOptions ─────────────────────────────────────────────────────────────

// ConfigOptions controls how a Config is initialised.
type ConfigOptions struct {
	// ConfigFile is an optional path to a YAML config file.
	ConfigFile string
	// EnvPrefix is the prefix for environment variable lookups (e.g. "OMEGA").
	EnvPrefix string
	// HotReload enables watching the config file for changes.
	HotReload bool
}

// ── Config ────────────────────────────────────────────────────────────────────

// Config is the hierarchical configuration store: defaults → file → env vars → CLI flags.
// It satisfies ConfigProvider so it can be passed directly to plugins.
type Config struct {
	v         *viper.Viper
	mu        sync.RWMutex
	onChange  []func()
	stopWatch chan struct{}
}

// NewConfig creates and initialises a Config according to opts.
func NewConfig(opts ConfigOptions) (*Config, error) {
	v := viper.NewWithOptions(viper.KeyDelimiter("."))

	// ── Defaults ──────────────────────────────────────────────────────────────
	setDefaults(v)

	// ── File ──────────────────────────────────────────────────────────────────
	if opts.ConfigFile != "" {
		v.SetConfigFile(opts.ConfigFile)
		if err := v.ReadInConfig(); err != nil {
			return nil, err
		}
	}

	// ── Environment ───────────────────────────────────────────────────────────
	if opts.EnvPrefix != "" {
		v.SetEnvPrefix(opts.EnvPrefix)
	}
	v.AutomaticEnv()
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))

	cfg := &Config{v: v, stopWatch: make(chan struct{})}

	// ── Hot-reload ────────────────────────────────────────────────────────────
	if opts.HotReload && opts.ConfigFile != "" {
		v.WatchConfig()
		v.OnConfigChange(func(e fsnotify.Event) {
			cfg.mu.RLock()
			handlers := append([]func(){}, cfg.onChange...)
			cfg.mu.RUnlock()
			for _, h := range handlers {
				h()
			}
		})
	}

	return cfg, nil
}

func setDefaults(v *viper.Viper) {
	v.SetDefault("orchestrator.heartbeat_interval", "120s")
	v.SetDefault("orchestrator.max_nodes", 32)
	v.SetDefault("orchestrator.cycle_timeout", "30s")

	v.SetDefault("adversarial.enabled", true)
	v.SetDefault("adversarial.debate_rounds", 2)

	v.SetDefault("memory.max_episodes", 10_000)
	v.SetDefault("memory.consolidation_interval", "1h")

	v.SetDefault("safety.enforcement_level", "strict")
}

// OnChange registers a callback invoked on every config-file change.
func (c *Config) OnChange(fn func()) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.onChange = append(c.onChange, fn)
}

// StopWatch stops the file watcher goroutine.
func (c *Config) StopWatch() {
	select {
	case <-c.stopWatch: // already closed
	default:
		close(c.stopWatch)
	}
}

// RegisterDomainDefaults registers per-domain config defaults keyed under domainKey.
// Plugins call this during Init so their config schema is self-documenting.
func (c *Config) RegisterDomainDefaults(domainKey string, schema map[string]any) {
	for k, v := range schema {
		c.v.SetDefault(domainKey+"."+k, v)
	}
}

// Set overrides a key at runtime (highest priority after flags).
func (c *Config) Set(key string, value any) { c.v.Set(key, value) }

// ── ConfigProvider implementation ─────────────────────────────────────────────

func (c *Config) GetString(key string) string { return c.v.GetString(key) }
func (c *Config) GetInt(key string) int        { return c.v.GetInt(key) }
func (c *Config) GetBool(key string) bool      { return c.v.GetBool(key) }
func (c *Config) GetDuration(key string) time.Duration { return c.v.GetDuration(key) }

// Sub returns a ConfigProvider scoped to the given key prefix.
// Returns nil if the key does not exist.
func (c *Config) Sub(key string) ConfigProvider {
	sub := c.v.Sub(key)
	if sub == nil {
		return nil
	}
	return &subConfig{v: sub}
}

// ── subConfig ─────────────────────────────────────────────────────────────────

// subConfig adapts a viper sub-tree to ConfigProvider.
type subConfig struct{ v *viper.Viper }

func (s *subConfig) GetString(key string) string { return s.v.GetString(key) }
func (s *subConfig) GetInt(key string) int        { return s.v.GetInt(key) }
func (s *subConfig) GetBool(key string) bool      { return s.v.GetBool(key) }
func (s *subConfig) Sub(key string) ConfigProvider {
	sub := s.v.Sub(key)
	if sub == nil {
		return nil
	}
	return &subConfig{v: sub}
}

