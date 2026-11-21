package main

import (
	"os"
	"path/filepath"
	"testing"
)

// Containerized commands may start at the filesystem root without an .env.
func TestLoadDotEnvAtRoot(t *testing.T) {
	t.Chdir(filepath.VolumeName(t.TempDir()) + string(os.PathSeparator))
	loadDotEnv()
}
