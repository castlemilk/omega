package integrations

import (
	"context"
	"time"
)

// Category represents the type of data a connector provides.
type Category int

const (
	MarketData  Category = iota // Price, volume, OHLCV data from exchanges
	News                        // News articles and headlines
	OnChain                     // Blockchain/on-chain metrics
	Macro                       // Macroeconomic indicators
	Alternative                 // Alternative data (sentiment, social, etc.)
	AIML                        // AI/ML model outputs and signals
	Reference                   // Reference/static data (symbols, metadata)
)

func (c Category) String() string {
	switch c {
	case MarketData:
		return "market_data"
	case News:
		return "news"
	case OnChain:
		return "on_chain"
	case Macro:
		return "macro"
	case Alternative:
		return "alternative"
	case AIML:
		return "ai_ml"
	case Reference:
		return "reference"
	default:
		return "unknown"
	}
}

// Connector is the base interface all connectors must implement.
type Connector interface {
	Name() string
	Category() Category
	HealthCheck(ctx context.Context) error
}

// DataConnector supports request/response style data fetching.
type DataConnector interface {
	Connector
	Fetch(ctx context.Context, req *FetchRequest) (*FetchResponse, error)
}

// StreamConnector supports streaming/subscription-based data delivery.
type StreamConnector interface {
	Connector
	Subscribe(ctx context.Context, params map[string]string) (<-chan []byte, error)
	Unsubscribe() error
}

// FetchRequest encapsulates parameters for a data fetch operation.
type FetchRequest struct {
	Endpoint string
	Params   map[string]string
	Headers  map[string]string
}

// FetchResponse encapsulates the result of a data fetch operation.
type FetchResponse struct {
	StatusCode int
	Body       []byte
	Headers    map[string]string
	CachedAt   time.Time
	FromCache  bool
}
