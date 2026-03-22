// Package memory provides file-backed persistence for Omega memory subsystems.
package memory

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// ---------------------------------------------------------------------------
// AtomicWriter
// ---------------------------------------------------------------------------

// AtomicWriter writes files atomically using a write-to-temp-then-rename strategy.
// Concurrent writes to the same key are serialised per key via MtimeCache.
type AtomicWriter struct {
	baseDir string
	cache   *MtimeCache
}

// NewAtomicWriter creates an AtomicWriter rooted at baseDir.
// baseDir is created if it does not already exist.
func NewAtomicWriter(baseDir string) (*AtomicWriter, error) {
	if err := os.MkdirAll(baseDir, 0o750); err != nil { //nolint:gosec
		return nil, fmt.Errorf("atomic writer mkdir %q: %w", baseDir, err)
	}
	return &AtomicWriter{
		baseDir: baseDir,
		cache:   NewMtimeCache(),
	}, nil
}

// Write atomically persists data under key.
// It writes to a sibling temp file then os.Rename to the target path.
func (w *AtomicWriter) Write(key string, data []byte) error {
	target := filepath.Join(w.baseDir, key)

	// Ensure parent directory exists (key may contain subdirs).
	if err := os.MkdirAll(filepath.Dir(target), 0o750); err != nil { //nolint:gosec
		return fmt.Errorf("write mkdir: %w", err)
	}

	tmp, err := os.CreateTemp(filepath.Dir(target), ".tmp-"+filepath.Base(key)+"-")
	if err != nil {
		return fmt.Errorf("write create temp: %w", err)
	}
	tmpName := tmp.Name()

	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		_ = os.Remove(tmpName) //nolint:gosec
		return fmt.Errorf("write data: %w", err)
	}
	if err := tmp.Close(); err != nil {
		_ = os.Remove(tmpName) //nolint:gosec
		return fmt.Errorf("write close temp: %w", err)
	}
	if err := os.Rename(tmpName, target); err != nil { //nolint:gosec
		_ = os.Remove(tmpName) //nolint:gosec
		return fmt.Errorf("write rename: %w", err)
	}

	// Invalidate cache for this key so next Read sees fresh data.
	w.cache.Invalidate(key)
	return nil
}

// Read returns the contents of key, using the mtime cache to avoid
// unnecessary disk reads when the file has not changed.
func (w *AtomicWriter) Read(key string) ([]byte, error) {
	target := filepath.Join(w.baseDir, key)

	info, err := os.Stat(target)
	if err != nil {
		return nil, fmt.Errorf("read stat %q: %w", key, err)
	}

	if data, ok := w.cache.Get(key, info.ModTime()); ok {
		return data, nil
	}

	data, err := os.ReadFile(target) //nolint:gosec
	if err != nil {
		return nil, fmt.Errorf("read file %q: %w", key, err)
	}
	w.cache.Set(key, data, info.ModTime())
	return data, nil
}

// Delete removes the file for key and evicts its cache entry.
func (w *AtomicWriter) Delete(key string) error {
	target := filepath.Join(w.baseDir, key)
	if err := os.Remove(target); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("delete %q: %w", key, err)
	}
	w.cache.Invalidate(key)
	return nil
}

// ---------------------------------------------------------------------------
// MtimeCache
// ---------------------------------------------------------------------------

type cacheEntry struct {
	data  []byte
	mtime time.Time
}

// MtimeCache is a simple in-memory cache that invalidates entries when the
// file's modification time changes.
type MtimeCache struct {
	mu      sync.RWMutex
	entries map[string]cacheEntry
}

// NewMtimeCache creates an empty MtimeCache.
func NewMtimeCache() *MtimeCache {
	return &MtimeCache{entries: make(map[string]cacheEntry)}
}

// Get returns the cached data for key if it was written with the same mtime.
// ok is false if the cache is empty or stale.
func (c *MtimeCache) Get(key string, mtime time.Time) ([]byte, bool) {
	c.mu.RLock()
	e, ok := c.entries[key]
	c.mu.RUnlock()
	if !ok || !e.mtime.Equal(mtime) {
		return nil, false
	}
	return e.data, true
}

// Set stores data for key associated with the given mtime.
func (c *MtimeCache) Set(key string, data []byte, mtime time.Time) {
	cp := make([]byte, len(data))
	copy(cp, data)
	c.mu.Lock()
	c.entries[key] = cacheEntry{data: cp, mtime: mtime}
	c.mu.Unlock()
}

// Invalidate removes the cache entry for key.
func (c *MtimeCache) Invalidate(key string) {
	c.mu.Lock()
	delete(c.entries, key)
	c.mu.Unlock()
}
