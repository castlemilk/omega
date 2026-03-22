// Package config provides versioned configuration management with automatic
// migration support for Omega configuration files.
package config

import (
	"encoding/json"
	"fmt"
	"time"
)

// currentVersion is the latest known config schema version.
const currentVersion = 1

// ConfigVersion records version metadata for a configuration payload.
type ConfigVersion struct {
	Version    int       `json:"version"`
	Schema     string    `json:"schema"`
	MigratedAt time.Time `json:"migrated_at"`
}

// VersionedConfig wraps any configuration payload with version metadata.
type VersionedConfig struct {
	ConfigVersion
	Payload json.RawMessage `json:"payload"`
}

// MigrationFunc transforms a config payload from one version to the next.
type MigrationFunc func(old []byte) ([]byte, error)

// versionPair is the key used to look up a migration function.
type versionPair struct {
	from, to int
}

// MigrationRegistry maps version pairs to their migration functions.
type MigrationRegistry struct {
	migrations map[versionPair]MigrationFunc
}

// NewMigrationRegistry creates an empty MigrationRegistry.
func NewMigrationRegistry() *MigrationRegistry {
	return &MigrationRegistry{
		migrations: make(map[versionPair]MigrationFunc),
	}
}

// Register adds a migration from fromVersion to toVersion.
func (r *MigrationRegistry) Register(fromVersion, toVersion int, fn MigrationFunc) {
	r.migrations[versionPair{fromVersion, toVersion}] = fn
}

// Migrate chains migrations from fromVersion to toVersion, applying each step
// in sequence. Returns an error if any step in the chain is missing.
func (r *MigrationRegistry) Migrate(data []byte, fromVersion, toVersion int) ([]byte, error) {
	if fromVersion == toVersion {
		return data, nil
	}
	if fromVersion > toVersion {
		return nil, fmt.Errorf("config: downgrade from v%d to v%d is not supported", fromVersion, toVersion)
	}

	current := data
	for v := fromVersion; v < toVersion; v++ {
		pair := versionPair{v, v + 1}
		fn, ok := r.migrations[pair]
		if !ok {
			return nil, fmt.Errorf("config: no migration registered from v%d to v%d", v, v+1)
		}
		next, err := fn(current)
		if err != nil {
			return nil, fmt.Errorf("config: migration v%d→v%d failed: %w", v, v+1, err)
		}
		current = next
	}
	return current, nil
}

// CurrentVersion returns the current (latest) config schema version.
func CurrentVersion() int {
	return currentVersion
}
