package auth

import (
	"crypto/subtle"
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"golang.org/x/time/rate"
)

// KeyStore holds registered API keys and their associated rate limiters.
type KeyStore struct {
	// keys maps keyID -> raw secret
	keys map[string]string

	// limiters holds per-key rate limiters
	mu       sync.Mutex
	limiters map[string]*rate.Limiter

	rateLimit int // req/s
	burst     int
}

// NewKeyStore reads OMEGA_API_KEYS env var.
// Format: comma-separated plain keys ("key1,key2") or "keyID:secret" pairs.
// Rate limit defaults to 100 req/s, burst 200. Configurable via OMEGA_API_RATE_LIMIT.
func NewKeyStore() *KeyStore {
	rl := 100
	if v := os.Getenv("OMEGA_API_RATE_LIMIT"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			rl = n
		}
	}
	burst := rl * 2

	ks := &KeyStore{
		keys:      make(map[string]string),
		limiters:  make(map[string]*rate.Limiter),
		rateLimit: rl,
		burst:     burst,
	}

	raw := os.Getenv("OMEGA_API_KEYS")
	if raw == "" {
		return ks
	}

	for _, entry := range strings.Split(raw, ",") {
		entry = strings.TrimSpace(entry)
		if entry == "" {
			continue
		}
		if idx := strings.Index(entry, ":"); idx > 0 {
			keyID := entry[:idx]
			secret := entry[idx+1:]
			ks.keys[keyID] = secret
		} else {
			// Plain key — use itself as both ID and secret.
			ks.keys[entry] = entry
		}
	}

	return ks
}

// Validate checks the provided key against the store using constant-time comparison.
// Returns the Identity for the key, or an error if not found or invalid.
func (ks *KeyStore) Validate(key string) (*Identity, error) {
	if key == "" {
		return nil, errors.New("auth: empty API key")
	}

	for keyID, secret := range ks.keys {
		if subtle.ConstantTimeCompare([]byte(key), []byte(secret)) == 1 {
			return &Identity{
				Subject: keyID,
				Roles:   []string{"api"},
				KeyID:   keyID,
			}, nil
		}
	}

	return nil, fmt.Errorf("auth: unknown API key")
}

// Allow checks the rate limiter for the given keyID.
// Returns true if the request is within rate limits, false if it should be throttled.
func (ks *KeyStore) Allow(keyID string) bool {
	ks.mu.Lock()
	lim, ok := ks.limiters[keyID]
	if !ok {
		lim = rate.NewLimiter(rate.Limit(ks.rateLimit), ks.burst)
		ks.limiters[keyID] = lim
	}
	ks.mu.Unlock()
	return lim.AllowN(time.Now(), 1)
}
