package connectors

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/benebsworth/omega/internal/integrations"
)

const newsAPIBaseURL = "https://newsapi.org/v2"

// NewsAPI connects to the NewsAPI.org service (requires an API key).
type NewsAPI struct {
	client *integrations.SharedHTTPClient
	apiKey string
}

// NewNewsAPI creates a NewsAPI connector with the given API key.
func NewNewsAPI(client *integrations.SharedHTTPClient, apiKey string) *NewsAPI {
	return &NewsAPI{client: client, apiKey: apiKey}
}

func (n *NewsAPI) Name() string                { return "newsapi" }
func (n *NewsAPI) Category() integrations.Category { return integrations.News }

func (n *NewsAPI) HealthCheck(ctx context.Context) error {
	// A sources call with apiKey is a lightweight probe.
	resp, err := n.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: newsAPIBaseURL + "/sources",
		Params:   map[string]string{"apiKey": n.apiKey},
	})
	if err != nil {
		return err
	}
	if resp.StatusCode != 200 {
		return fmt.Errorf("newsapi health check: HTTP %d", resp.StatusCode)
	}
	return nil
}

// Fetch implements DataConnector.
func (n *NewsAPI) Fetch(ctx context.Context, req *integrations.FetchRequest) (*integrations.FetchResponse, error) {
	if req.Params == nil {
		req.Params = map[string]string{}
	}
	req.Params["apiKey"] = n.apiKey
	return n.client.Do(ctx, req)
}

// NewsArticle represents a single article from the NewsAPI.
type NewsArticle struct {
	Source      map[string]string `json:"source"`
	Author      string            `json:"author"`
	Title       string            `json:"title"`
	Description string            `json:"description"`
	URL         string            `json:"url"`
	PublishedAt string            `json:"publishedAt"`
	Content     string            `json:"content"`
}

// NewsResponse wraps the top-level NewsAPI response envelope.
type NewsResponse struct {
	Status       string        `json:"status"`
	TotalResults int           `json:"totalResults"`
	Articles     []NewsArticle `json:"articles"`
}

// SearchNews queries the /everything endpoint for articles matching a query.
// from/to are ISO 8601 date strings (e.g. "2024-01-01"). sortBy: "relevancy", "popularity", "publishedAt".
func (n *NewsAPI) SearchNews(ctx context.Context, query, from, to, sortBy string) (*NewsResponse, error) {
	params := map[string]string{
		"q":      query,
		"sortBy": sortBy,
		"apiKey": n.apiKey,
	}
	if from != "" {
		params["from"] = from
	}
	if to != "" {
		params["to"] = to
	}
	resp, err := n.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: newsAPIBaseURL + "/everything",
		Params:   params,
	})
	if err != nil {
		return nil, fmt.Errorf("newsapi search: %w", err)
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("newsapi search: HTTP %d: %s", resp.StatusCode, resp.Body)
	}
	var result NewsResponse
	if err := json.Unmarshal(resp.Body, &result); err != nil {
		return nil, fmt.Errorf("newsapi search decode: %w", err)
	}
	return &result, nil
}

// GetTopHeadlines retrieves top headlines from the /top-headlines endpoint.
// country is an ISO 3166-1 alpha-2 code (e.g. "us"). category: "business", "technology", etc.
func (n *NewsAPI) GetTopHeadlines(ctx context.Context, country, category string) (*NewsResponse, error) {
	params := map[string]string{
		"apiKey": n.apiKey,
	}
	if country != "" {
		params["country"] = country
	}
	if category != "" {
		params["category"] = category
	}
	resp, err := n.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: newsAPIBaseURL + "/top-headlines",
		Params:   params,
	})
	if err != nil {
		return nil, fmt.Errorf("newsapi top_headlines: %w", err)
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("newsapi top_headlines: HTTP %d: %s", resp.StatusCode, resp.Body)
	}
	var result NewsResponse
	if err := json.Unmarshal(resp.Body, &result); err != nil {
		return nil, fmt.Errorf("newsapi top_headlines decode: %w", err)
	}
	return &result, nil
}
