package integrations

import (
	"context"
	"sync"
	"time"
)

// RateLimiter implements a per-domain token bucket rate limiter.
type RateLimiter struct {
	mu       sync.Mutex
	tokens   float64
	maxBurst float64
	ratePerS float64 // tokens added per second
	lastTick time.Time
}

// NewRateLimiter creates a token bucket limiter with the given rate and burst size.
// requestsPerSecond is the sustained rate; burst is the maximum token accumulation.
func NewRateLimiter(requestsPerSecond float64, burst int) *RateLimiter {
	return &RateLimiter{
		tokens:   float64(burst),
		maxBurst: float64(burst),
		ratePerS: requestsPerSecond,
		lastTick: time.Now(),
	}
}

// refill adds tokens based on elapsed time. Must be called with mu held.
func (r *RateLimiter) refill() {
	now := time.Now()
	elapsed := now.Sub(r.lastTick).Seconds()
	r.lastTick = now
	r.tokens += elapsed * r.ratePerS
	if r.tokens > r.maxBurst {
		r.tokens = r.maxBurst
	}
}

// TryAcquire attempts to consume one token without blocking.
// Returns true if a token was available, false otherwise.
func (r *RateLimiter) TryAcquire() bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.refill()
	if r.tokens >= 1 {
		r.tokens--
		return true
	}
	return false
}

// Wait blocks until a token is available or the context is cancelled.
func (r *RateLimiter) Wait(ctx context.Context) error {
	for {
		r.mu.Lock()
		r.refill()
		if r.tokens >= 1 {
			r.tokens--
			r.mu.Unlock()
			return nil
		}
		// Calculate how long until the next token arrives.
		waitSeconds := (1 - r.tokens) / r.ratePerS
		r.mu.Unlock()

		delay := time.Duration(waitSeconds * float64(time.Second))
		if delay < time.Millisecond {
			delay = time.Millisecond
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(delay):
		}
	}
}

// DomainRateLimiter manages per-domain RateLimiter instances.
type DomainRateLimiter struct {
	mu       sync.Mutex
	limiters map[string]*RateLimiter
	defaultR float64
	defaultB int
}

// NewDomainRateLimiter creates a manager with a default rate applied to unknown domains.
func NewDomainRateLimiter(defaultRPS float64, defaultBurst int) *DomainRateLimiter {
	return &DomainRateLimiter{
		limiters: make(map[string]*RateLimiter),
		defaultR: defaultRPS,
		defaultB: defaultBurst,
	}
}

// For returns the RateLimiter for the given domain, creating one with defaults if absent.
func (d *DomainRateLimiter) For(domain string) *RateLimiter {
	d.mu.Lock()
	defer d.mu.Unlock()
	if rl, ok := d.limiters[domain]; ok {
		return rl
	}
	rl := NewRateLimiter(d.defaultR, d.defaultB)
	d.limiters[domain] = rl
	return rl
}

// Set registers a custom rate limiter for a specific domain.
func (d *DomainRateLimiter) Set(domain string, rps float64, burst int) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.limiters[domain] = NewRateLimiter(rps, burst)
}
