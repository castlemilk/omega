package integrations

import (
	"container/list"
	"sync"
	"time"
)

const defaultMaxEntries = 1000

// cacheEntry holds the value and expiration for a cached item.
type cacheEntry struct {
	key       string
	value     []byte
	expiresAt time.Time
	elem      *list.Element
}

// CacheStats holds operational statistics for the cache.
type CacheStats struct {
	Hits      int64
	Misses    int64
	Evictions int64
	Size      int
}

// LRUCache is a thread-safe LRU cache with TTL support.
type LRUCache struct {
	mu         sync.RWMutex
	maxEntries int
	items      map[string]*cacheEntry
	lru        *list.List // front = most recently used

	hits      int64
	misses    int64
	evictions int64
}

// NewLRUCache creates a new LRU cache with the given max entry count.
// If maxEntries <= 0, defaults to 1000.
func NewLRUCache(maxEntries int) *LRUCache {
	if maxEntries <= 0 {
		maxEntries = defaultMaxEntries
	}
	return &LRUCache{
		maxEntries: maxEntries,
		items:      make(map[string]*cacheEntry),
		lru:        list.New(),
	}
}

// Get retrieves a value by key. Returns (value, true) on hit, (nil, false) on miss or expiry.
func (c *LRUCache) Get(key string) ([]byte, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()

	entry, ok := c.items[key]
	if !ok {
		c.misses++
		return nil, false
	}
	if time.Now().After(entry.expiresAt) {
		c.removeEntry(entry)
		c.misses++
		return nil, false
	}
	c.lru.MoveToFront(entry.elem)
	c.hits++
	return entry.value, true
}

// Set stores a value with the given TTL. Overwrites existing entries.
func (c *LRUCache) Set(key string, value []byte, ttl time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()

	if entry, ok := c.items[key]; ok {
		c.lru.MoveToFront(entry.elem)
		entry.value = value
		entry.expiresAt = time.Now().Add(ttl)
		return
	}

	entry := &cacheEntry{
		key:       key,
		value:     value,
		expiresAt: time.Now().Add(ttl),
	}
	entry.elem = c.lru.PushFront(entry)
	c.items[key] = entry

	for len(c.items) > c.maxEntries {
		c.evictOldest()
	}
}

// Evict removes a specific key from the cache.
func (c *LRUCache) Evict(key string) {
	c.mu.Lock()
	defer c.mu.Unlock()

	if entry, ok := c.items[key]; ok {
		c.removeEntry(entry)
	}
}

// Stats returns a snapshot of cache statistics.
func (c *LRUCache) Stats() CacheStats {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return CacheStats{
		Hits:      c.hits,
		Misses:    c.misses,
		Evictions: c.evictions,
		Size:      len(c.items),
	}
}

// evictOldest removes the least recently used entry. Must be called with mu held.
func (c *LRUCache) evictOldest() {
	oldest := c.lru.Back()
	if oldest == nil {
		return
	}
	c.removeEntry(oldest.Value.(*cacheEntry))
	c.evictions++
}

// removeEntry removes the entry from both the map and the LRU list. Must be called with mu held.
func (c *LRUCache) removeEntry(entry *cacheEntry) {
	delete(c.items, entry.key)
	c.lru.Remove(entry.elem)
}
