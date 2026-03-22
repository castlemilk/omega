package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// buildRegistry returns a registry with migrations v1→v2 and v2→v3 for testing.
func buildRegistry() *MigrationRegistry {
	r := NewMigrationRegistry()
	r.Register(1, 2, func(old []byte) ([]byte, error) {
		var m map[string]any
		if err := json.Unmarshal(old, &m); err != nil {
			return nil, err
		}
		m["v2_field"] = "added"
		return json.Marshal(m)
	})
	r.Register(2, 3, func(old []byte) ([]byte, error) {
		var m map[string]any
		if err := json.Unmarshal(old, &m); err != nil {
			return nil, err
		}
		m["v3_field"] = true
		return json.Marshal(m)
	})
	return r
}

func TestSingleMigrationStep(t *testing.T) {
	r := buildRegistry()
	input := mustMarshal(t, map[string]any{"original": 1})

	out, err := r.Migrate(input, 1, 2)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var m map[string]any
	if err := json.Unmarshal(out, &m); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if m["v2_field"] != "added" {
		t.Errorf("expected v2_field=added, got %v", m["v2_field"])
	}
}

func TestMultiStepMigrationChain(t *testing.T) {
	r := buildRegistry()
	input := mustMarshal(t, map[string]any{"original": 1})

	out, err := r.Migrate(input, 1, 3)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var m map[string]any
	if err := json.Unmarshal(out, &m); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if m["v2_field"] != "added" {
		t.Errorf("expected v2_field=added, got %v", m["v2_field"])
	}
	if m["v3_field"] != true {
		t.Errorf("expected v3_field=true, got %v", m["v3_field"])
	}
}

func TestMissingMigrationPath(t *testing.T) {
	r := NewMigrationRegistry() // no migrations registered
	_, err := r.Migrate([]byte(`{}`), 1, 2)
	if err == nil {
		t.Fatal("expected error for missing migration path, got nil")
	}
}

func TestIdempotentLoad(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")

	vc := VersionedConfig{
		ConfigVersion: ConfigVersion{
			Version:    1,
			Schema:     "omega/v1",
			MigratedAt: time.Now().UTC(),
		},
		Payload: json.RawMessage(`{"key":"value"}`),
	}
	writeConfig(t, path, vc)

	r := NewMigrationRegistry()
	upgrader := NewAutoUpgrader(r, 1) // target == current version

	loaded, err := upgrader.Load(path)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if loaded.Version != 1 {
		t.Errorf("expected version 1, got %d", loaded.Version)
	}
	// No backup should have been written since no migration occurred.
	entries, _ := os.ReadDir(dir)
	if len(entries) != 1 {
		t.Errorf("expected 1 file in dir (no backup), got %d", len(entries))
	}
}

func TestBackupCreationBeforeUpgrade(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")

	vc := VersionedConfig{
		ConfigVersion: ConfigVersion{Version: 1, Schema: "omega/v1"},
		Payload:       json.RawMessage(`{"original":true}`),
	}
	writeConfig(t, path, vc)

	r := buildRegistry()
	upgrader := NewAutoUpgrader(r, 2)

	_, err := upgrader.Load(path)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	entries, _ := os.ReadDir(dir)
	// Expect the original (now upgraded) file + at least one .bak.* file.
	if len(entries) < 2 {
		t.Errorf("expected backup file to be created, found %d files", len(entries))
	}
}

// helpers

func mustMarshal(t *testing.T, v any) []byte {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	return b
}

func writeConfig(t *testing.T, path string, vc VersionedConfig) {
	t.Helper()
	b, err := json.MarshalIndent(vc, "", "  ")
	if err != nil {
		t.Fatalf("marshal config: %v", err)
	}
	if err := os.WriteFile(path, b, 0o600); err != nil {
		t.Fatalf("write config: %v", err)
	}
}
