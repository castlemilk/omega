package handler

import (
	"context"
	"strconv"
	"time"

	"connectrpc.com/connect"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"
	"google.golang.org/protobuf/types/known/timestamppb"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/integrations"
	"github.com/benebsworth/omega/internal/integrations/connectors"
	"github.com/benebsworth/omega/internal/telemetry"
)

// Ensure interface satisfaction at compile time.
var _ omegav1connect.DataServiceHandler = (*DataHandler)(nil)

// BinanceConnector is the subset of *connectors.Binance used by DataHandler.
// Exported so tests can inject mock implementations.
type BinanceConnector interface {
	GetPrice(ctx context.Context, symbol string) (*connectors.TickerPrice, error)
	GetKlines(ctx context.Context, symbol, interval string, limit int) ([]connectors.Kline, error)
	GetOrderBook(ctx context.Context, symbol string, limit int) (*connectors.OrderBook, error)
}

// CoinGeckoConnector is the subset of *connectors.CoinGecko used by DataHandler.
// Exported so tests can inject mock implementations.
type CoinGeckoConnector interface {
	GetPrice(ctx context.Context, ids []string, vsCurrencies []string) (map[string]map[string]float64, error)
	GetMarkets(ctx context.Context, vsCurrency string, perPage, page int) ([]connectors.CoinMarket, error)
}

// DataHandler implements DataService, routing requests to the appropriate
// connector from the registry fleet (Binance, CoinGecko, AlphaVantage, FRED).
type DataHandler struct {
	registry  *integrations.ConnectorRegistry
	binance   BinanceConnector
	coingecko CoinGeckoConnector
}

// NewData creates a DataHandler wired to the provided registry and typed connectors.
// binance and cg may be nil; affected RPCs will return CodeUnavailable.
func NewData(
	registry *integrations.ConnectorRegistry,
	binance *connectors.Binance,
	cg *connectors.CoinGecko,
) *DataHandler {
	h := &DataHandler{registry: registry}
	if binance != nil {
		h.binance = binance
	}
	if cg != nil {
		h.coingecko = cg
	}
	return h
}

// NewDataWithMocks creates a DataHandler with interface-typed connectors.
// Intended for use in tests; production code should use NewData.
func NewDataWithMocks(
	registry *integrations.ConnectorRegistry,
	binance BinanceConnector,
	cg CoinGeckoConnector,
) *DataHandler {
	return &DataHandler{
		registry:  registry,
		binance:   binance,
		coingecko: cg,
	}
}

// ── GetOHLCV ──────────────────────────────────────────────────────────────────

func (h *DataHandler) GetOHLCV(
	ctx context.Context,
	req *connect.Request[omegav1.GetOHLCVRequest],
) (*connect.Response[omegav1.GetOHLCVResponse], error) {
	ctx, span := telemetry.Tracer().Start(ctx, "DataService.GetOHLCV",
		trace.WithAttributes(
			attribute.String("symbol", req.Msg.Symbol),
			attribute.String("exchange", req.Msg.Exchange),
		),
	)
	defer span.End()

	if h.binance == nil {
		return nil, connect.NewError(connect.CodeUnavailable, nil)
	}

	interval := intervalString(req.Msg.Interval)
	limit := int(req.Msg.Limit)
	if limit <= 0 {
		limit = 100
	}

	klines, err := h.binance.GetKlines(ctx, req.Msg.Symbol, interval, limit)
	if err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	protoKlines := make([]*omegav1.Kline, 0, len(klines))
	for _, k := range klines {
		protoKlines = append(protoKlines, &omegav1.Kline{
			OpenTime:  k.OpenTime,
			Open:      parseFloatStr(k.Open),
			High:      parseFloatStr(k.High),
			Low:       parseFloatStr(k.Low),
			Close:     parseFloatStr(k.Close),
			Volume:    parseFloatStr(k.Volume),
			CloseTime: k.CloseTime,
		})
	}

	span.SetStatus(codes.Ok, "")
	return connect.NewResponse(&omegav1.GetOHLCVResponse{
		Symbol:   req.Msg.Symbol,
		Exchange: "binance",
		Interval: req.Msg.Interval,
		Klines:   protoKlines,
	}), nil
}

// ── GetTicker ─────────────────────────────────────────────────────────────────

func (h *DataHandler) GetTicker(
	ctx context.Context,
	req *connect.Request[omegav1.GetTickerRequest],
) (*connect.Response[omegav1.GetTickerResponse], error) {
	ctx, span := telemetry.Tracer().Start(ctx, "DataService.GetTicker",
		trace.WithAttributes(
			attribute.String("symbol", req.Msg.Symbol),
			attribute.String("exchange", req.Msg.Exchange),
		),
	)
	defer span.End()

	exchange := req.Msg.Exchange
	if exchange == "" {
		exchange = "binance"
	}

	switch exchange {
	case "coingecko":
		if h.coingecko == nil {
			return nil, connect.NewError(connect.CodeUnavailable, nil)
		}
		prices, err := h.coingecko.GetPrice(ctx, []string{req.Msg.Symbol}, []string{"usd"})
		if err != nil {
			span.RecordError(err)
			span.SetStatus(codes.Error, err.Error())
			return nil, connect.NewError(connect.CodeInternal, err)
		}
		coinPrices, ok := prices[req.Msg.Symbol]
		if !ok {
			return nil, connect.NewError(connect.CodeNotFound, nil)
		}
		span.SetStatus(codes.Ok, "")
		return connect.NewResponse(&omegav1.GetTickerResponse{
			Symbol:   req.Msg.Symbol,
			Price:    coinPrices["usd"],
			Exchange: "coingecko",
		}), nil

	default: // "binance" or any unrecognised exchange
		if h.binance == nil {
			return nil, connect.NewError(connect.CodeUnavailable, nil)
		}
		ticker, err := h.binance.GetPrice(ctx, req.Msg.Symbol)
		if err != nil {
			span.RecordError(err)
			span.SetStatus(codes.Error, err.Error())
			return nil, connect.NewError(connect.CodeInternal, err)
		}
		span.SetStatus(codes.Ok, "")
		return connect.NewResponse(&omegav1.GetTickerResponse{
			Symbol:   ticker.Symbol,
			Price:    parseFloatStr(ticker.Price),
			Exchange: "binance",
		}), nil
	}
}

// ── GetOrderBook ──────────────────────────────────────────────────────────────

func (h *DataHandler) GetOrderBook(
	ctx context.Context,
	req *connect.Request[omegav1.GetOrderBookRequest],
) (*connect.Response[omegav1.GetOrderBookResponse], error) {
	ctx, span := telemetry.Tracer().Start(ctx, "DataService.GetOrderBook",
		trace.WithAttributes(attribute.String("symbol", req.Msg.Symbol)),
	)
	defer span.End()

	if h.binance == nil {
		return nil, connect.NewError(connect.CodeUnavailable, nil)
	}

	depth := int(req.Msg.Depth)
	if depth <= 0 {
		depth = 20
	}

	ob, err := h.binance.GetOrderBook(ctx, req.Msg.Symbol, depth)
	if err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	bids := make([]*omegav1.OrderBookLevel, 0, len(ob.Bids))
	for _, b := range ob.Bids {
		if len(b) < 2 {
			continue
		}
		bids = append(bids, &omegav1.OrderBookLevel{
			Price:    parseFloatStr(b[0]),
			Quantity: parseFloatStr(b[1]),
		})
	}

	asks := make([]*omegav1.OrderBookLevel, 0, len(ob.Asks))
	for _, a := range ob.Asks {
		if len(a) < 2 {
			continue
		}
		asks = append(asks, &omegav1.OrderBookLevel{
			Price:    parseFloatStr(a[0]),
			Quantity: parseFloatStr(a[1]),
		})
	}

	span.SetStatus(codes.Ok, "")
	return connect.NewResponse(&omegav1.GetOrderBookResponse{
		Symbol:       req.Msg.Symbol,
		Exchange:     "binance",
		LastUpdateId: ob.LastUpdateID,
		Bids:         bids,
		Asks:         asks,
	}), nil
}

// ── ListDataSources ───────────────────────────────────────────────────────────

func (h *DataHandler) ListDataSources(
	ctx context.Context,
	req *connect.Request[omegav1.ListDataSourcesRequest],
) (*connect.Response[omegav1.ListDataSourcesResponse], error) {
	ctx, span := telemetry.Tracer().Start(ctx, "DataService.ListDataSources")
	defer span.End()

	results := h.registry.HealthCheckAll(ctx)

	sources := make([]*omegav1.DataSource, 0, len(results))
	for _, r := range results {
		c, ok := h.registry.Get(r.Name)
		if !ok {
			continue
		}
		src := &omegav1.DataSource{
			Name:     r.Name,
			Category: c.Category().String(),
			Status:   omegav1.DataSourceStatus_DATA_SOURCE_STATUS_HEALTHY,
		}
		if r.Error != nil {
			src.Status = omegav1.DataSourceStatus_DATA_SOURCE_STATUS_UNAVAILABLE
			src.Error = r.Error.Error()
		}
		sources = append(sources, src)
	}

	span.SetStatus(codes.Ok, "")
	return connect.NewResponse(&omegav1.ListDataSourcesResponse{Sources: sources}), nil
}

// ── GetMarketOverview ─────────────────────────────────────────────────────────

func (h *DataHandler) GetMarketOverview(
	ctx context.Context,
	req *connect.Request[omegav1.GetMarketOverviewRequest],
) (*connect.Response[omegav1.GetMarketOverviewResponse], error) {
	ctx, span := telemetry.Tracer().Start(ctx, "DataService.GetMarketOverview")
	defer span.End()

	if h.coingecko == nil {
		return nil, connect.NewError(connect.CodeUnavailable, nil)
	}

	vsCurrency := req.Msg.VsCurrency
	if vsCurrency == "" {
		vsCurrency = "usd"
	}
	limit := int(req.Msg.Limit)
	if limit <= 0 {
		limit = 20
	}

	markets, err := h.coingecko.GetMarkets(ctx, vsCurrency, limit, 1)
	if err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	coins := make([]*omegav1.CoinOverview, 0, len(markets))
	for _, m := range markets {
		coins = append(coins, &omegav1.CoinOverview{
			Id:                        m.ID,
			Symbol:                    m.Symbol,
			Name:                      m.Name,
			CurrentPrice:              m.CurrentPrice,
			MarketCap:                 m.MarketCap,
			MarketCapRank:             int32(m.MarketCapRank), //nolint:gosec
			TotalVolume:               m.TotalVolume,
			PriceChangePercentage_24H: m.PriceChangePercentage24h,
		})
	}

	span.SetStatus(codes.Ok, "")
	return connect.NewResponse(&omegav1.GetMarketOverviewResponse{
		Coins:      coins,
		VsCurrency: vsCurrency,
	}), nil
}

// ── StreamPrices ──────────────────────────────────────────────────────────────

func (h *DataHandler) StreamPrices(
	ctx context.Context,
	req *connect.Request[omegav1.StreamPricesRequest],
	stream *connect.ServerStream[omegav1.PriceUpdate],
) error {
	_, span := telemetry.Tracer().Start(ctx, "DataService.StreamPrices",
		trace.WithAttributes(attribute.Int("symbol_count", len(req.Msg.Symbols))),
	)
	defer span.End()

	if h.binance == nil {
		return connect.NewError(connect.CodeUnavailable, nil)
	}
	if len(req.Msg.Symbols) == 0 {
		return connect.NewError(connect.CodeInvalidArgument, nil)
	}

	intervalMs := int(req.Msg.IntervalMs)
	if intervalMs <= 0 {
		intervalMs = 1000
	}

	ticker := time.NewTicker(time.Duration(intervalMs) * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			span.SetStatus(codes.Ok, "")
			return nil
		case <-ticker.C:
			for _, sym := range req.Msg.Symbols {
				price, err := h.binance.GetPrice(ctx, sym)
				if err != nil {
					// Transient error: skip this tick for this symbol.
					continue
				}
				if err := stream.Send(&omegav1.PriceUpdate{
					Symbol:    price.Symbol,
					Price:     parseFloatStr(price.Price),
					Timestamp: timestamppb.Now(),
					Exchange:  "binance",
				}); err != nil {
					return err
				}
			}
		}
	}
}

// ── helpers ───────────────────────────────────────────────────────────────────

// intervalString converts the proto OHLCVInterval enum to the Binance interval string.
func intervalString(iv omegav1.OHLCVInterval) string {
	switch iv {
	case omegav1.OHLCVInterval_OHLCV_INTERVAL_1M:
		return "1m"
	case omegav1.OHLCVInterval_OHLCV_INTERVAL_5M:
		return "5m"
	case omegav1.OHLCVInterval_OHLCV_INTERVAL_15M:
		return "15m"
	case omegav1.OHLCVInterval_OHLCV_INTERVAL_30M:
		return "30m"
	case omegav1.OHLCVInterval_OHLCV_INTERVAL_1H:
		return "1h"
	case omegav1.OHLCVInterval_OHLCV_INTERVAL_4H:
		return "4h"
	case omegav1.OHLCVInterval_OHLCV_INTERVAL_1D:
		return "1d"
	case omegav1.OHLCVInterval_OHLCV_INTERVAL_1W:
		return "1w"
	default:
		return "1h"
	}
}

// parseFloatStr converts a numeric string (as returned by Binance) to float64.
// Returns 0 on parse failure.
func parseFloatStr(s string) float64 {
	v, _ := strconv.ParseFloat(s, 64)
	return v
}
