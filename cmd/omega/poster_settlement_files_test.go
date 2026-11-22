//go:build unix

package main

import (
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestSettlementEvidencePrivateImmutableFiles(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	require.NoError(t, err)
	directory := filepath.Join(root, "new", "statements")
	dir, err := openSettlementEvidenceDir(directory)
	require.NoError(t, err)
	defer func() { _ = dir.Close() }()
	st, err := dir.Stat()
	require.NoError(t, err)
	require.Equal(t, os.FileMode(0700), st.Mode().Perm())
	body := []byte("{\"testMode\": true}\n")
	digest := fmt.Sprintf("%x", sha256.Sum256(body))
	path := filepath.Join(directory, digest+".json")

	var results [8]error
	var workers sync.WaitGroup
	for i := range results {
		workers.Go(func() { results[i] = saveSettlementStatement(dir, digest, body) })
	}
	workers.Wait()
	for _, err := range results {
		require.NoError(t, err)
	}
	files, err := os.ReadDir(directory)
	require.NoError(t, err)
	require.Len(t, files, 1)
	st, err = os.Lstat(path)
	require.NoError(t, err)
	require.True(t, st.Mode().IsRegular())
	require.Equal(t, os.FileMode(0600), st.Mode().Perm())
	exact, err := os.ReadFile(path)
	require.NoError(t, err)
	require.Equal(t, body, exact)
	require.Error(t, saveSettlementStatement(dir, "../escape", body))

	require.NoError(t, os.Chmod(path, 0644))
	require.ErrorContains(t, saveSettlementStatement(dir, digest, body), "0600")
	require.NoError(t, os.Chmod(path, 0600))
	damaged := []byte("preserve this existing file")
	require.NoError(t, os.WriteFile(path, damaged, 0600))
	require.ErrorContains(t, saveSettlementStatement(dir, digest, body), "does not match")
	exact, err = os.ReadFile(path)
	require.NoError(t, err)
	require.Equal(t, damaged, exact)

	require.NoError(t, os.Remove(path))
	target := filepath.Join(root, "target")
	require.NoError(t, os.WriteFile(target, body, 0600))
	require.NoError(t, os.Symlink(target, path))
	require.Error(t, saveSettlementStatement(dir, digest, body))
	st, err = os.Lstat(path)
	require.NoError(t, err)
	require.NotZero(t, st.Mode()&os.ModeSymlink)
}

func TestSettlementEvidenceRejectsDirectorySymlinksAndExposedPermissions(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	require.NoError(t, err)
	target := filepath.Join(root, "private")
	require.NoError(t, os.Mkdir(target, 0700))
	link := filepath.Join(root, "linked")
	require.NoError(t, os.Symlink(target, link))
	for _, path := range []string{link, filepath.Join(link, "subdir")} {
		_, err := openSettlementEvidenceDir(path)
		require.Error(t, err)
	}
	_, err = os.Stat(filepath.Join(target, "subdir"))
	require.ErrorIs(t, err, os.ErrNotExist)
	require.NoError(t, os.Chmod(target, 0755))
	_, err = openSettlementEvidenceDir(target)
	require.ErrorContains(t, err, "0700")
}
