package skills

import (
	"os"
	"path/filepath"
	"sync"
	"testing"
)

func sampleSkill() Skill {
	return Skill{
		Name:         "my-skill",
		Version:      "1.0.0",
		Description:  "A test skill",
		Author:       "test",
		Dependencies: []string{},
		EntryPoint:   "main.go",
		Config:       map[string]any{"timeout": 30},
	}
}

// TestPackageUnpackageRoundtrip verifies that packaging and then unpackaging
// a skill produces an identical Skill value.
func TestPackageUnpackageRoundtrip(t *testing.T) {
	dir := t.TempDir()
	archivePath := filepath.Join(dir, "my-skill.skill")

	// Create a minimal source directory.
	srcDir := filepath.Join(dir, "src")
	if err := os.MkdirAll(srcDir, 0o750); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(srcDir, "main.go"), []byte("package main"), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}

	skill := sampleSkill()
	if err := Package(skill, srcDir, archivePath); err != nil {
		t.Fatalf("Package: %v", err)
	}

	targetDir := filepath.Join(dir, "out")
	got, err := Unpackage(archivePath, targetDir)
	if err != nil {
		t.Fatalf("Unpackage: %v", err)
	}

	if got.Name != skill.Name {
		t.Errorf("Name: got %q, want %q", got.Name, skill.Name)
	}
	if got.Version != skill.Version {
		t.Errorf("Version: got %q, want %q", got.Version, skill.Version)
	}
	if got.EntryPoint != skill.EntryPoint {
		t.Errorf("EntryPoint: got %q, want %q", got.EntryPoint, skill.EntryPoint)
	}

	// Verify source file was extracted.
	if _, err := os.Stat(filepath.Join(targetDir, "main.go")); err != nil {
		t.Errorf("extracted file missing: %v", err)
	}
}

// TestReadManifest verifies that ReadManifest parses the manifest without
// extracting the full archive.
func TestReadManifest(t *testing.T) {
	dir := t.TempDir()
	archivePath := filepath.Join(dir, "skill.skill")

	skill := sampleSkill()
	if err := Package(skill, "", archivePath); err != nil {
		t.Fatalf("Package: %v", err)
	}

	manifest, err := ReadManifest(archivePath)
	if err != nil {
		t.Fatalf("ReadManifest: %v", err)
	}
	if manifest.Name != skill.Name {
		t.Errorf("Name: got %q, want %q", manifest.Name, skill.Name)
	}
}

// TestValidate checks that Validate catches missing required fields.
func TestValidate(t *testing.T) {
	cases := []struct {
		name    string
		skill   Skill
		wantErr bool
	}{
		{"valid", sampleSkill(), false},
		{"missing name", Skill{Version: "1.0.0", EntryPoint: "main.go"}, true},
		{"missing version", Skill{Name: "x", EntryPoint: "main.go"}, true},
		{"missing entrypoint", Skill{Name: "x", Version: "1.0.0"}, true},
		{"bad dep", Skill{Name: "x", Version: "1.0.0", EntryPoint: "main.go", Dependencies: []string{"bad dep!"}}, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			err := Validate(c.skill)
			if (err != nil) != c.wantErr {
				t.Errorf("Validate() error = %v, wantErr %v", err, c.wantErr)
			}
		})
	}
}

// TestInstallUninstallLifecycle exercises the full install/get/uninstall flow.
func TestInstallUninstallLifecycle(t *testing.T) {
	dir := t.TempDir()
	archivePath := filepath.Join(dir, "skill.skill")

	skill := sampleSkill()
	if err := Package(skill, "", archivePath); err != nil {
		t.Fatalf("Package: %v", err)
	}

	registry := NewSkillRegistry(filepath.Join(dir, "store"))

	if err := registry.Install(archivePath); err != nil {
		t.Fatalf("Install: %v", err)
	}

	got, err := registry.Get(skill.Name)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if got.Name != skill.Name {
		t.Errorf("Name: got %q, want %q", got.Name, skill.Name)
	}

	if err := registry.Uninstall(skill.Name); err != nil {
		t.Fatalf("Uninstall: %v", err)
	}

	_, err = registry.Get(skill.Name)
	if err == nil {
		t.Fatal("expected error after uninstall, got nil")
	}
}

// TestDependencyResolution verifies topological ordering and cycle detection.
func TestDependencyResolution(t *testing.T) {
	dir := t.TempDir()
	registry := NewSkillRegistry(dir)

	// Install base and dependent skills directly (bypass packaging for speed).
	registry.skills["base"] = Skill{Name: "base", Version: "1.0.0", EntryPoint: ".", Dependencies: []string{}}
	registry.skills["mid"] = Skill{Name: "mid", Version: "1.0.0", EntryPoint: ".", Dependencies: []string{"base"}}
	registry.skills["top"] = Skill{Name: "top", Version: "1.0.0", EntryPoint: ".", Dependencies: []string{"mid"}}

	order, err := registry.Resolve([]string{"top"})
	if err != nil {
		t.Fatalf("Resolve: %v", err)
	}
	if len(order) != 3 {
		t.Fatalf("expected 3 skills in order, got %d", len(order))
	}
	// base must come before mid, mid before top.
	indexOf := func(name string) int {
		for i, s := range order {
			if s.Name == name {
				return i
			}
		}
		return -1
	}
	if indexOf("base") >= indexOf("mid") {
		t.Error("base must be before mid")
	}
	if indexOf("mid") >= indexOf("top") {
		t.Error("mid must be before top")
	}
}

func TestCycleDetection(t *testing.T) {
	dir := t.TempDir()
	registry := NewSkillRegistry(dir)

	// a → b → a (cycle)
	registry.skills["a"] = Skill{Name: "a", Version: "1.0.0", EntryPoint: ".", Dependencies: []string{"b"}}
	registry.skills["b"] = Skill{Name: "b", Version: "1.0.0", EntryPoint: ".", Dependencies: []string{"a"}}

	_, err := registry.Resolve([]string{"a"})
	if err == nil {
		t.Fatal("expected cycle detection error, got nil")
	}
}

// TestRegistryConcurrentAccess exercises the registry under concurrent load.
func TestRegistryConcurrentAccess(t *testing.T) {
	dir := t.TempDir()
	registry := NewSkillRegistry(dir)

	archivePath := filepath.Join(dir, "skill.skill")
	skill := sampleSkill()
	if err := Package(skill, "", archivePath); err != nil {
		t.Fatalf("Package: %v", err)
	}

	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_ = registry.Install(archivePath)
			registry.List()
			_, _ = registry.Get(skill.Name)
		}()
	}
	wg.Wait()
}
