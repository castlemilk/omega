package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// AutoUpgrader reads a versioned config file, auto-migrates it to the target
// version if necessary, and writes the upgraded config back to disk.
type AutoUpgrader struct {
	mu        sync.Mutex
	registry  *MigrationRegistry
	targetVer int
}

// NewAutoUpgrader creates an AutoUpgrader targeting the given version.
func NewAutoUpgrader(registry *MigrationRegistry, targetVersion int) *AutoUpgrader {
	return &AutoUpgrader{
		registry:  registry,
		targetVer: targetVersion,
	}
}

// Load reads the config at path, detects its version, migrates to the target
// version if needed, writes the upgraded file back, and returns the result.
func (u *AutoUpgrader) Load(path string) (*VersionedConfig, error) {
	u.mu.Lock()
	defer u.mu.Unlock()

	raw, err := os.ReadFile(path) //nolint:gosec // path is supplied by trusted caller
	if err != nil {
		return nil, fmt.Errorf("config: read %q: %w", path, err)
	}

	var vc VersionedConfig
	if err := json.Unmarshal(raw, &vc); err != nil {
		return nil, fmt.Errorf("config: parse %q: %w", path, err)
	}

	if vc.Version == u.targetVer {
		return &vc, nil
	}

	if err := u.Backup(path); err != nil {
		return nil, fmt.Errorf("config: backup before migration: %w", err)
	}

	migratedPayload, err := u.registry.Migrate(vc.Payload, vc.Version, u.targetVer)
	if err != nil {
		return nil, err
	}

	vc.Version = u.targetVer
	vc.MigratedAt = time.Now().UTC()
	vc.Payload = migratedPayload

	updated, err := json.MarshalIndent(vc, "", "  ")
	if err != nil {
		return nil, fmt.Errorf("config: marshal upgraded config: %w", err)
	}
	if err := os.WriteFile(path, updated, 0o600); err != nil {
		return nil, fmt.Errorf("config: write upgraded config to %q: %w", path, err)
	}

	return &vc, nil
}

// Backup creates a timestamped copy of the config file before migration.
// The backup is placed in the same directory with a .bak.<timestamp> suffix.
func (u *AutoUpgrader) Backup(path string) error {
	raw, err := os.ReadFile(path) //nolint:gosec // path is supplied by trusted caller
	if err != nil {
		return fmt.Errorf("config: read for backup %q: %w", path, err)
	}

	ts := time.Now().UTC().Format("20060102T150405Z")
	backupPath := filepath.Join(
		filepath.Dir(path),
		filepath.Base(path)+".bak."+ts,
	)
	if err := os.WriteFile(backupPath, raw, 0o600); err != nil { //nolint:gosec // G304/G703: backupPath derived from operator-provided config path
		return fmt.Errorf("config: write backup %q: %w", backupPath, err)
	}
	return nil
}
