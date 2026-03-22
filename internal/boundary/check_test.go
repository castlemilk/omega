package boundary

import (
	"os"
	"path/filepath"
	"testing"
)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// writeGoFile creates a minimal .go file with the given imports in dir/pkg/name.go.
func writeGoFile(t *testing.T, root, pkg, filename, content string) {
	t.Helper()
	dir := filepath.Join(root, "internal", pkg)
	if err := os.MkdirAll(dir, 0o750); err != nil { //nolint:gosec
		t.Fatalf("mkdir %q: %v", dir, err)
	}
	path := filepath.Join(dir, filename)
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil { //nolint:gosec
		t.Fatalf("write %q: %v", path, err)
	}
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

func TestNoBoundaryViolations(t *testing.T) {
	root := t.TempDir()
	writeGoFile(t, root, "core", "ok.go", `package core

import (
	"fmt"
	"github.com/benebsworth/omega/internal/coord"
)

var _ = fmt.Sprintf
var _ = coord.Fake
`)
	violations := CheckBoundaries(root)
	if len(violations) != 0 {
		t.Fatalf("expected no violations, got: %+v", violations)
	}
}

func TestCoreMustNotImportAPI(t *testing.T) {
	root := t.TempDir()
	writeGoFile(t, root, "core", "bad.go", `package core

import (
	"github.com/benebsworth/omega/internal/api"
)

var _ = api.Fake
`)
	violations := CheckBoundaries(root)
	if len(violations) == 0 {
		t.Fatal("expected violation: core importing api")
	}
	found := false
	for _, v := range violations {
		if v.ImportPath == "github.com/benebsworth/omega/internal/api" {
			found = true
		}
	}
	if !found {
		t.Fatalf("violation not reported for api import: %+v", violations)
	}
}

func TestMemoryMustNotImportHandler(t *testing.T) {
	root := t.TempDir()
	writeGoFile(t, root, "memory", "bad.go", `package memory

import (
	"github.com/benebsworth/omega/internal/handler"
)

var _ = handler.Fake
`)
	violations := CheckBoundaries(root)
	if len(violations) == 0 {
		t.Fatal("expected violation: memory importing handler")
	}
}

func TestCoreMustNotImportHandler(t *testing.T) {
	root := t.TempDir()
	writeGoFile(t, root, "core", "bad.go", `package core

import (
	"github.com/benebsworth/omega/internal/handler"
)

var _ = handler.Fake
`)
	violations := CheckBoundaries(root)
	if len(violations) == 0 {
		t.Fatal("expected violation: core importing handler")
	}
}

func TestMultipleViolationsDetected(t *testing.T) {
	root := t.TempDir()
	writeGoFile(t, root, "core", "bad1.go", `package core

import "github.com/benebsworth/omega/internal/api"

var _ = api.X
`)
	writeGoFile(t, root, "memory", "bad2.go", `package memory

import "github.com/benebsworth/omega/internal/handler"

var _ = handler.X
`)
	violations := CheckBoundaries(root)
	if len(violations) < 2 {
		t.Fatalf("expected at least 2 violations, got %d: %+v", len(violations), violations)
	}
}

func TestTestFilesSkipped(t *testing.T) {
	root := t.TempDir()
	// Test files are allowed to import anything — they should not be checked.
	writeGoFile(t, root, "core", "ok_test.go", `package core

import "github.com/benebsworth/omega/internal/api"

var _ = api.X
`)
	violations := CheckBoundaries(root)
	if len(violations) != 0 {
		t.Fatalf("test files should be skipped; got violations: %+v", violations)
	}
}

func TestEmptyDir(t *testing.T) {
	root := t.TempDir()
	violations := CheckBoundaries(root)
	if len(violations) != 0 {
		t.Fatalf("empty dir should yield no violations, got: %+v", violations)
	}
}
