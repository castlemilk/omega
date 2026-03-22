package integrations

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"time"
)

const (
	defaultCacheTTL    = 30 * time.Second
	maxRetries         = 3
	retryBaseDelay     = 200 * time.Millisecond
	defaultHTTPTimeout = 15 * time.Second
)

// HTTPClientConfig controls SharedHTTPClient behaviour.
type HTTPClientConfig struct {
	// CacheTTL is how long responses are cached. Zero disables caching.
	CacheTTL time.Duration
	// RatePerSecond is the default per-domain sustained request rate.
	RatePerSecond float64
	// Burst is the default per-domain burst size.
	Burst int
	// Timeout for individual HTTP requests.
	Timeout time.Duration
	// Logger for request/response logging. Nil disables logging.
	Logger *slog.Logger
}

// DefaultHTTPClientConfig returns sensible defaults.
func DefaultHTTPClientConfig() HTTPClientConfig {
	return HTTPClientConfig{
		CacheTTL:      defaultCacheTTL,
		RatePerSecond: 10,
		Burst:         20,
		Timeout:       defaultHTTPTimeout,
		Logger:        slog.Default(),
	}
}

// SharedHTTPClient is a reusable HTTP client with rate limiting, caching, and retry.
type SharedHTTPClient struct {
	client      *http.Client
	cache       *LRUCache
	domainRL    *DomainRateLimiter
	config      HTTPClientConfig
}

// NewSharedHTTPClient creates a SharedHTTPClient with the given configuration.
func NewSharedHTTPClient(cfg HTTPClientConfig) *SharedHTTPClient {
	if cfg.Timeout == 0 {
		cfg.Timeout = defaultHTTPTimeout
	}
	if cfg.RatePerSecond == 0 {
		cfg.RatePerSecond = 10
	}
	if cfg.Burst == 0 {
		cfg.Burst = 20
	}
	return &SharedHTTPClient{
		client:   &http.Client{Timeout: cfg.Timeout},
		cache:    NewLRUCache(defaultMaxEntries),
		domainRL: NewDomainRateLimiter(cfg.RatePerSecond, cfg.Burst),
		config:   cfg,
	}
}

// Do executes an HTTP GET request with rate limiting, caching, and retry.
func (c *SharedHTTPClient) Do(ctx context.Context, req *FetchRequest) (*FetchResponse, error) {
	// Build canonical cache key from endpoint + sorted params.
	cacheKey := buildCacheKey(req)

	if c.config.CacheTTL > 0 {
		if data, hit := c.cache.Get(cacheKey); hit {
			if c.config.Logger != nil {
				c.config.Logger.DebugContext(ctx, "cache hit", "endpoint", req.Endpoint)
			}
			return &FetchResponse{
				StatusCode: http.StatusOK,
				Body:       data,
				Headers:    map[string]string{},
				FromCache:  true,
				CachedAt:   time.Now(),
			}, nil
		}
	}

	domain := extractDomain(req.Endpoint)
	rl := c.domainRL.For(domain)

	var resp *FetchResponse
	var lastErr error

	for attempt := 0; attempt <= maxRetries; attempt++ {
		if attempt > 0 {
			delay := retryBaseDelay * (1 << (attempt - 1)) // exponential: 200ms, 400ms, 800ms
			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-time.After(delay):
			}
		}

		if err := rl.Wait(ctx); err != nil {
			return nil, fmt.Errorf("rate limiter: %w", err)
		}

		r, err := c.execute(ctx, req)
		if err != nil {
			lastErr = err
			if c.config.Logger != nil {
				c.config.Logger.WarnContext(ctx, "request failed, retrying",
					"attempt", attempt+1, "endpoint", req.Endpoint, "error", err)
			}
			continue
		}

		// Don't retry 4xx client errors (except 429).
		if r.StatusCode >= 400 && r.StatusCode < 500 && r.StatusCode != http.StatusTooManyRequests {
			return r, nil
		}
		if r.StatusCode >= 500 || r.StatusCode == http.StatusTooManyRequests {
			lastErr = fmt.Errorf("server error: HTTP %d", r.StatusCode)
			if c.config.Logger != nil {
				c.config.Logger.WarnContext(ctx, "server error, retrying",
					"attempt", attempt+1, "status", r.StatusCode, "endpoint", req.Endpoint)
			}
			continue
		}

		resp = r
		break
	}

	if resp == nil {
		return nil, fmt.Errorf("all %d attempts failed for %s: %w", maxRetries+1, req.Endpoint, lastErr)
	}

	if c.config.CacheTTL > 0 && resp.StatusCode == http.StatusOK {
		c.cache.Set(cacheKey, resp.Body, c.config.CacheTTL)
	}

	return resp, nil
}

// execute performs a single HTTP GET without retry logic.
func (c *SharedHTTPClient) execute(ctx context.Context, req *FetchRequest) (*FetchResponse, error) {
	rawURL := req.Endpoint
	if len(req.Params) > 0 {
		params := url.Values{}
		for k, v := range req.Params {
			params.Set(k, v)
		}
		rawURL = req.Endpoint + "?" + params.Encode()
	}

	httpReq, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}
	for k, v := range req.Headers {
		httpReq.Header.Set(k, v)
	}

	start := time.Now()
	httpResp, err := c.client.Do(httpReq) //nolint:gosec
	elapsed := time.Since(start)
	if err != nil {
		return nil, fmt.Errorf("http do: %w", err)
	}
	defer httpResp.Body.Close() //nolint:errcheck

	body, err := io.ReadAll(httpResp.Body)
	if err != nil {
		return nil, fmt.Errorf("read body: %w", err)
	}

	headers := make(map[string]string, len(httpResp.Header))
	for k := range httpResp.Header {
		headers[k] = httpResp.Header.Get(k)
	}

	if c.config.Logger != nil {
		c.config.Logger.DebugContext(ctx, "http request",
			"endpoint", req.Endpoint,
			"status", httpResp.StatusCode,
			"elapsed_ms", elapsed.Milliseconds(),
			"body_bytes", len(body),
		)
	}

	return &FetchResponse{
		StatusCode: httpResp.StatusCode,
		Body:       body,
		Headers:    headers,
	}, nil
}

// buildCacheKey constructs a stable string key for a FetchRequest.
func buildCacheKey(req *FetchRequest) string {
	var buf bytes.Buffer
	buf.WriteString(req.Endpoint)
	if len(req.Params) > 0 {
		buf.WriteByte('?')
		params := url.Values{}
		for k, v := range req.Params {
			params.Set(k, v)
		}
		buf.WriteString(params.Encode())
	}
	return buf.String()
}

// extractDomain returns the host portion of a URL for per-domain rate limiting.
func extractDomain(rawURL string) string {
	u, err := url.Parse(rawURL)
	if err != nil {
		return rawURL
	}
	return u.Host
}
