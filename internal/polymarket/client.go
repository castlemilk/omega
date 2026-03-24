// Package polymarket provides a Go client for the Polymarket Data API.
//
// Base URLs:
//   - Gamma API (markets, events):  https://gamma-api.polymarket.com
//   - CLOB API  (orderbook, prices): https://clob.polymarket.com
//   - Data API  (trades):            https://data-api.polymarket.com
//
// All public endpoints require no authentication.
package polymarket

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	defaultGammaURL = "https://gamma-api.polymarket.com"
	defaultCLOBURL  = "https://clob.polymarket.com"
	defaultDataURL  = "https://data-api.polymarket.com"

	defaultTimeout = 15 * time.Second
)

// APIError represents a non-2xx HTTP response.
type APIError struct {
	StatusCode int
	Status     string
	Body       string
}

func (e *APIError) Error() string {
	if e.Body != "" {
		return fmt.Sprintf("polymarket: HTTP %d %s: %s", e.StatusCode, e.Status, e.Body)
	}
	return fmt.Sprintf("polymarket: HTTP %d %s", e.StatusCode, e.Status)
}

// -------------------------------------------------------------------------
// Types
// -------------------------------------------------------------------------

// Market represents a single prediction market.
type Market struct {
	ID                 string    `json:"id"`
	ConditionID        string    `json:"conditionId"`
	Question           string    `json:"question"`
	Slug               string    `json:"slug"`
	Description        string    `json:"description"`
	Category           string    `json:"category"`
	MarketType         string    `json:"marketType"`
	Outcomes           []string  `json:"outcomes"`
	OutcomePrices      []string  `json:"outcomePrices"`
	ClobTokenIDs       []string  `json:"clobTokenIds"`
	Active             bool      `json:"active"`
	Closed             bool      `json:"closed"`
	Archived           bool      `json:"archived"`
	Restricted         bool      `json:"restricted"`
	Approved           bool      `json:"approved"`
	Volume             string    `json:"volume"`
	VolumeNum          float64   `json:"volumeNum"`
	Volume24hr         float64   `json:"volume24hr"`
	Volume1wk          float64   `json:"volume1wk"`
	Volume1mo          float64   `json:"volume1mo"`
	Liquidity          string    `json:"liquidity"`
	LiquidityNum       float64   `json:"liquidityNum"`
	BestBid            float64   `json:"bestBid"`
	BestAsk            float64   `json:"bestAsk"`
	LastTradePrice     float64   `json:"lastTradePrice"`
	Spread             float64   `json:"spread"`
	EndDate            string    `json:"endDate"`
	ClosedTime         string    `json:"closedTime"`
	CreatedAt          time.Time `json:"createdAt"`
	UpdatedAt          time.Time `json:"updatedAt"`
	MarketMakerAddress string    `json:"marketMakerAddress"`
	Image              string    `json:"image"`
	Icon               string    `json:"icon"`
}

// Event groups multiple related markets.
type Event struct {
	ID             string    `json:"id"`
	Ticker         string    `json:"ticker"`
	Slug           string    `json:"slug"`
	Title          string    `json:"title"`
	Description    string    `json:"description"`
	ResolutionSource string  `json:"resolutionSource"`
	StartDate      string    `json:"startDate"`
	CreationDate   string    `json:"creationDate"`
	EndDate        string    `json:"endDate"`
	Active         bool      `json:"active"`
	Closed         bool      `json:"closed"`
	Archived       bool      `json:"archived"`
	Restricted     bool      `json:"restricted"`
	New            bool      `json:"new"`
	Featured       bool      `json:"featured"`
	Liquidity      float64   `json:"liquidity"`
	Volume         float64   `json:"volume"`
	Volume24hr     float64   `json:"volume24hr"`
	Volume1wk      float64   `json:"volume1wk"`
	Volume1mo      float64   `json:"volume1mo"`
	OpenInterest   float64   `json:"openInterest"`
	CommentCount   int       `json:"commentCount"`
	CreatedAt      time.Time `json:"createdAt"`
	UpdatedAt      time.Time `json:"updatedAt"`
	Markets        []Market  `json:"markets"`
	Tags           []Tag     `json:"tags"`
	Image          string    `json:"image"`
	Icon           string    `json:"icon"`
}

// Tag categorises events.
type Tag struct {
	ID        string `json:"id"`
	Label     string `json:"label"`
	Slug      string `json:"slug"`
	ForceShow bool   `json:"forceShow"`
}

// OrderBookLevel is a single price level in an order book.
type OrderBookLevel struct {
	Price string `json:"price"`
	Size  string `json:"size"`
}

// OrderBook is the order book for a token.
type OrderBook struct {
	Market    string           `json:"market"`
	AssetID   string           `json:"asset_id"`
	Bids      []OrderBookLevel `json:"bids"`
	Asks      []OrderBookLevel `json:"asks"`
	Hash      string           `json:"hash"`
	Timestamp string           `json:"timestamp"`
}

// Trade is a single executed trade.
type Trade struct {
	ProxyWallet      string  `json:"proxyWallet"`
	Side             string  `json:"side"`
	Asset            string  `json:"asset"`
	ConditionID      string  `json:"conditionId"`
	Size             string  `json:"size"`
	Price            string  `json:"price"`
	Timestamp        int64   `json:"timestamp"`
	Title            string  `json:"title"`
	Slug             string  `json:"slug"`
	Outcome          string  `json:"outcome"`
	OutcomeIndex     int     `json:"outcomeIndex"`
	Name             string  `json:"name"`
	Pseudonym        string  `json:"pseudonym"`
	TransactionHash  string  `json:"transactionHash"`
}

// -------------------------------------------------------------------------
// Query option structs
// -------------------------------------------------------------------------

// MarketQuery parameters for listing markets.
type MarketQuery struct {
	Active   *bool
	Closed   *bool
	Category string
	Limit    int
	Offset   int
}

// EventQuery parameters for listing events.
type EventQuery struct {
	Active   *bool
	Closed   *bool
	Tag      string
	Limit    int
	Offset   int
}

// TradeQuery parameters for listing trades.
type TradeQuery struct {
	Market string
	Limit  int
	Offset int
}

// -------------------------------------------------------------------------
// Cache
// -------------------------------------------------------------------------

type cacheEntry struct {
	data    []byte
	expires time.Time
}

type responseCache struct {
	mu      sync.Mutex
	entries map[string]cacheEntry
	ttl     time.Duration
}

func newResponseCache(ttl time.Duration) *responseCache {
	return &responseCache{
		entries: make(map[string]cacheEntry),
		ttl:     ttl,
	}
}

func (c *responseCache) get(key string) ([]byte, bool) {
	if c.ttl == 0 {
		return nil, false
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.entries[key]
	if !ok || time.Now().After(e.expires) {
		return nil, false
	}
	return e.data, true
}

func (c *responseCache) set(key string, data []byte) {
	if c.ttl == 0 {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	c.entries[key] = cacheEntry{data: data, expires: time.Now().Add(c.ttl)}
}

// -------------------------------------------------------------------------
// Rate limiter (token bucket)
// -------------------------------------------------------------------------

type rateLimiter struct {
	tokens   float64
	maxTokens float64
	refillRate float64 // tokens per second
	lastRefill time.Time
	mu         sync.Mutex
}

func newRateLimiter(requestsPerSecond float64) *rateLimiter {
	return &rateLimiter{
		tokens:     requestsPerSecond,
		maxTokens:  requestsPerSecond,
		refillRate: requestsPerSecond,
		lastRefill: time.Now(),
	}
}

func (r *rateLimiter) Wait(ctx context.Context) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	now := time.Now()
	elapsed := now.Sub(r.lastRefill).Seconds()
	r.tokens = min(r.maxTokens, r.tokens+elapsed*r.refillRate)
	r.lastRefill = now

	if r.tokens >= 1 {
		r.tokens--
		return nil
	}

	// Calculate wait time until next token
	wait := time.Duration((1-r.tokens)/r.refillRate*1000) * time.Millisecond
	r.mu.Unlock()

	select {
	case <-ctx.Done():
		r.mu.Lock()
		return ctx.Err()
	case <-time.After(wait):
		r.mu.Lock()
		r.tokens--
		return nil
	}
}

func min(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}

// -------------------------------------------------------------------------
// Client
// -------------------------------------------------------------------------

// Client is the Polymarket API client.
type Client struct {
	gammaURL   string
	clobURL    string
	dataURL    string
	httpClient *http.Client
	cache      *responseCache
	limiter    *rateLimiter
}

// Option configures a Client.
type Option func(*Client)

// WithHTTPClient sets a custom HTTP client.
func WithHTTPClient(hc *http.Client) Option {
	return func(c *Client) { c.httpClient = hc }
}

// WithCacheTTL enables response caching with the given TTL (0 = disabled).
func WithCacheTTL(ttl time.Duration) Option {
	return func(c *Client) { c.cache = newResponseCache(ttl) }
}

// WithRateLimit sets requests-per-second limit (0 = disabled).
func WithRateLimit(rps float64) Option {
	return func(c *Client) {
		if rps > 0 {
			c.limiter = newRateLimiter(rps)
		}
	}
}

// WithGammaURL overrides the Gamma API base URL.
func WithGammaURL(u string) Option {
	return func(c *Client) { c.gammaURL = strings.TrimRight(u, "/") }
}

// WithCLOBURL overrides the CLOB API base URL.
func WithCLOBURL(u string) Option {
	return func(c *Client) { c.clobURL = strings.TrimRight(u, "/") }
}

// WithDataURL overrides the Data API base URL.
func WithDataURL(u string) Option {
	return func(c *Client) { c.dataURL = strings.TrimRight(u, "/") }
}

// NewClient creates a new Polymarket API client.
func NewClient(opts ...Option) *Client {
	c := &Client{
		gammaURL: defaultGammaURL,
		clobURL:  defaultCLOBURL,
		dataURL:  defaultDataURL,
		httpClient: &http.Client{
			Timeout: defaultTimeout,
		},
		cache: newResponseCache(0), // caching off by default
	}
	for _, o := range opts {
		o(c)
	}
	return c
}

// -------------------------------------------------------------------------
// Core HTTP helpers
// -------------------------------------------------------------------------

func (c *Client) get(ctx context.Context, rawURL string, out interface{}) error {
	if c.limiter != nil {
		if err := c.limiter.Wait(ctx); err != nil {
			return err
		}
	}

	if data, ok := c.cache.get(rawURL); ok {
		return json.Unmarshal(data, out)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return fmt.Errorf("polymarket: build request: %w", err)
	}
	req.Header.Set("Accept", "application/json")

	resp, err := c.httpClient.Do(req) //nolint:gosec // URL is caller-supplied; SSRF is caller's responsibility
	if err != nil {
		return fmt.Errorf("polymarket: request: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("polymarket: read body: %w", err)
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return &APIError{
			StatusCode: resp.StatusCode,
			Status:     resp.Status,
			Body:       strings.TrimSpace(string(body)),
		}
	}

	if err := json.Unmarshal(body, out); err != nil {
		return fmt.Errorf("polymarket: decode response: %w", err)
	}

	c.cache.set(rawURL, body)
	return nil
}

func buildURL(base string, params url.Values) string {
	if len(params) == 0 {
		return base
	}
	return base + "?" + params.Encode()
}

// -------------------------------------------------------------------------
// Markets
// -------------------------------------------------------------------------

// GetMarkets returns a paginated list of markets.
func (c *Client) GetMarkets(ctx context.Context, opts *MarketQuery) ([]Market, error) {
	params := url.Values{}
	if opts != nil {
		if opts.Active != nil {
			params.Set("active", strconv.FormatBool(*opts.Active))
		}
		if opts.Closed != nil {
			params.Set("closed", strconv.FormatBool(*opts.Closed))
		}
		if opts.Category != "" {
			params.Set("category", opts.Category)
		}
		if opts.Limit > 0 {
			params.Set("limit", strconv.Itoa(opts.Limit))
		}
		if opts.Offset > 0 {
			params.Set("offset", strconv.Itoa(opts.Offset))
		}
	}

	u := buildURL(c.gammaURL+"/markets", params)
	var markets []Market
	if err := c.get(ctx, u, &markets); err != nil {
		return nil, err
	}
	return markets, nil
}

// GetMarket returns a single market by condition ID.
func (c *Client) GetMarket(ctx context.Context, conditionID string) (*Market, error) {
	params := url.Values{"condition_ids": []string{conditionID}}
	u := buildURL(c.gammaURL+"/markets", params)

	var markets []Market
	if err := c.get(ctx, u, &markets); err != nil {
		return nil, err
	}
	if len(markets) == 0 {
		return nil, &APIError{StatusCode: 404, Status: "404 Not Found", Body: "market not found: " + conditionID}
	}
	return &markets[0], nil
}

// -------------------------------------------------------------------------
// Events
// -------------------------------------------------------------------------

// GetEvents returns a paginated list of events.
func (c *Client) GetEvents(ctx context.Context, opts *EventQuery) ([]Event, error) {
	params := url.Values{}
	if opts != nil {
		if opts.Active != nil {
			params.Set("active", strconv.FormatBool(*opts.Active))
		}
		if opts.Closed != nil {
			params.Set("closed", strconv.FormatBool(*opts.Closed))
		}
		if opts.Tag != "" {
			params.Set("tag", opts.Tag)
		}
		if opts.Limit > 0 {
			params.Set("limit", strconv.Itoa(opts.Limit))
		}
		if opts.Offset > 0 {
			params.Set("offset", strconv.Itoa(opts.Offset))
		}
	}

	u := buildURL(c.gammaURL+"/events", params)
	var events []Event
	if err := c.get(ctx, u, &events); err != nil {
		return nil, err
	}
	return events, nil
}

// GetEvent returns a single event by ID or slug.
func (c *Client) GetEvent(ctx context.Context, id string) (*Event, error) {
	u := c.gammaURL + "/events/" + url.PathEscape(id)
	var event Event
	if err := c.get(ctx, u, &event); err != nil {
		return nil, err
	}
	return &event, nil
}

// -------------------------------------------------------------------------
// Prices (CLOB)
// -------------------------------------------------------------------------

// GetPrices returns the midpoint price for each token ID.
// tokenIDs are the clobTokenIds from a market's token list.
func (c *Client) GetPrices(ctx context.Context, tokenIDs []string) (map[string]float64, error) {
	result := make(map[string]float64, len(tokenIDs))
	// Fetch midpoint for each token (CLOB doesn't have a batch midpoint endpoint)
	for _, id := range tokenIDs {
		params := url.Values{"token_id": []string{id}}
		u := buildURL(c.clobURL+"/midpoint", params)
		var resp struct {
			Mid string `json:"mid"`
		}
		if err := c.get(ctx, u, &resp); err != nil {
			return nil, fmt.Errorf("GetPrices token %s: %w", id, err)
		}
		price, err := strconv.ParseFloat(resp.Mid, 64)
		if err != nil {
			return nil, fmt.Errorf("GetPrices parse price %q: %w", resp.Mid, err)
		}
		result[id] = price
	}
	return result, nil
}

// -------------------------------------------------------------------------
// Order Book (CLOB)
// -------------------------------------------------------------------------

// GetOrderBook returns the order book for a token.
func (c *Client) GetOrderBook(ctx context.Context, tokenID string) (*OrderBook, error) {
	params := url.Values{"token_id": []string{tokenID}}
	u := buildURL(c.clobURL+"/book", params)
	var ob OrderBook
	if err := c.get(ctx, u, &ob); err != nil {
		return nil, err
	}
	return &ob, nil
}

// -------------------------------------------------------------------------
// Trades (Data API)
// -------------------------------------------------------------------------

// GetTrades returns a paginated list of trades.
func (c *Client) GetTrades(ctx context.Context, opts *TradeQuery) ([]Trade, error) {
	params := url.Values{}
	if opts != nil {
		if opts.Market != "" {
			params.Set("market", opts.Market)
		}
		if opts.Limit > 0 {
			params.Set("limit", strconv.Itoa(opts.Limit))
		}
		if opts.Offset > 0 {
			params.Set("offset", strconv.Itoa(opts.Offset))
		}
	}

	u := buildURL(c.dataURL+"/trades", params)
	var trades []Trade
	if err := c.get(ctx, u, &trades); err != nil {
		return nil, err
	}
	return trades, nil
}
