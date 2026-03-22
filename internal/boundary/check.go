// Package boundary enforces import-graph rules across the Omega codebase.
// It is designed to be run in CI to catch architecture violations early.
package boundary

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
)

// ---------------------------------------------------------------------------
// Rules
// ---------------------------------------------------------------------------

// rule describes a forbidden import from one internal package to another.
type rule struct {
	// fromPkg is the last segment of the importing package path (e.g. "core").
	fromPkg string
	// bannedImport is a substring that must NOT appear in any import path.
	bannedImport string
	description  string
}

var defaultRules = []rule{
	{
		fromPkg:      "core",
		bannedImport: "internal/api",
		description:  "internal/core must not import internal/api",
	},
	{
		fromPkg:      "memory",
		bannedImport: "internal/handler",
		description:  "internal/memory must not import internal/handler",
	},
	{
		fromPkg:      "core",
		bannedImport: "internal/handler",
		description:  "internal/core must not import internal/handler",
	},
	{
		fromPkg:      "coord",
		bannedImport: "internal/api",
		description:  "internal/coord must not import internal/api",
	},
	{
		fromPkg:      "boundary",
		bannedImport: "internal/handler",
		description:  "internal/boundary must not import internal/handler",
	},
}

// ---------------------------------------------------------------------------
// Violation
// ---------------------------------------------------------------------------

// Violation records a single import-rule breach.
type Violation struct {
	File       string
	ImportPath string
	Rule       string
}

// ---------------------------------------------------------------------------
// CheckBoundaries
// ---------------------------------------------------------------------------

// CheckBoundaries walks rootDir, parses every .go file, and returns all
// import violations found according to the built-in rule set.
func CheckBoundaries(rootDir string) []Violation {
	var violations []Violation

	_ = filepath.WalkDir(rootDir, func(path string, d os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return nil //nolint:nilerr
		}
		if d.IsDir() {
			return nil
		}
		if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}

		imports, parseErr := parseImports(path)
		if parseErr != nil {
			return nil //nolint:nilerr // skip unparseable files
		}

		// Determine which package segment this file belongs to.
		pkg := packageSegment(path)

		for _, imp := range imports {
			for _, r := range defaultRules {
				if r.fromPkg == pkg && strings.Contains(imp, r.bannedImport) {
					violations = append(violations, Violation{
						File:       path,
						ImportPath: imp,
						Rule:       r.description,
					})
				}
			}
		}
		return nil
	})

	return violations
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

// parseImports returns all import paths declared in the given Go source file.
func parseImports(path string) ([]string, error) {
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, path, nil, parser.ImportsOnly)
	if err != nil {
		return nil, err
	}

	var imports []string
	for _, imp := range f.Imports {
		if imp.Path != nil {
			// Strip surrounding quotes.
			p := ast.BasicLit(*imp.Path)
			val := p.Value
			val = strings.Trim(val, `"`)
			imports = append(imports, val)
		}
	}
	return imports, nil
}

// packageSegment returns the last path segment of the internal package that
// contains path (e.g. ".../internal/core/foo.go" → "core").
func packageSegment(path string) string {
	parts := strings.Split(filepath.ToSlash(path), "/")
	for i, p := range parts {
		if p == "internal" && i+1 < len(parts) {
			return parts[i+1]
		}
	}
	return ""
}
