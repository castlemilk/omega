package main

import (
	"context"
	"log"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"connectrpc.com/connect"
	"golang.org/x/net/http2"
	"golang.org/x/net/http2/h2c"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/auth"
	"github.com/benebsworth/omega/internal/db"
	"github.com/benebsworth/omega/internal/handler"
	"github.com/benebsworth/omega/internal/integrations"
	"github.com/benebsworth/omega/internal/integrations/connectors"
	mw "github.com/benebsworth/omega/internal/middleware"
	"github.com/benebsworth/omega/internal/observability"
	"github.com/benebsworth/omega/internal/registry"
	"github.com/benebsworth/omega/internal/telemetry"
	"github.com/benebsworth/omega/internal/terminal"

	"google.golang.org/protobuf/types/known/timestamppb"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	// ---------------------------------------------------------------------------
	// OpenTelemetry — initialise before anything else so all downstream code
	// gets instrumented automatically.
	// ---------------------------------------------------------------------------
	telCfg := telemetry.Config{
		OtlpEndpoint:         os.Getenv("OTLP_ENDPOINT"), // e.g. "http://otel-collector:4318"
		ServiceName:          "omega-api",
		ServiceVersion:       "0.1.0",
		SampleRate:           1.0,
		MetricExportInterval: 15 * time.Second,
	}
	if _, err := telemetry.Init(ctx, telCfg); err != nil {
		log.Printf("warn: telemetry init failed (%v) — continuing without OTel", err)
	}
	defer func() {
		shutCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := telemetry.Shutdown(shutCtx); err != nil {
			log.Printf("warn: telemetry shutdown error: %v", err)
		}
	}()

	// ---------------------------------------------------------------------------
	// Handler metrics (OTel interceptor shared across all Connect-RPC services)
	// ---------------------------------------------------------------------------
	hMetrics, err := handler.NewHandlerMetrics()
	if err != nil {
		log.Printf("warn: handler metrics init failed (%v) — continuing without RPC metrics", err)
	}

	// ---------------------------------------------------------------------------
	// Auth — JWT + API key interceptor (optional, controlled by OMEGA_AUTH_ENABLED)
	// ---------------------------------------------------------------------------
	jwtValidator, jwtErr := auth.NewValidator()
	if jwtErr != nil {
		log.Printf("warn: JWT validator init: %v — JWT auth will be unavailable", jwtErr)
	}
	keyStore := auth.NewKeyStore()
	authCfg := auth.DefaultConfig()
	authInterceptor := auth.NewInterceptor(authCfg, jwtValidator, keyStore)

	// Convenience helper: returns the interceptor options, or a no-op if hMetrics is nil.
	withHandlerOpts := func(opts ...connect.HandlerOption) []connect.HandlerOption {
		if hMetrics != nil {
			opts = append(opts, connect.WithInterceptors(hMetrics.MetricsInterceptor()))
		}
		opts = append(opts, connect.WithInterceptors(authInterceptor))
		opts = append(opts, connect.WithCompressMinBytes(1024))
		return opts
	}

	// ---------------------------------------------------------------------------
	// Database
	// ---------------------------------------------------------------------------
	stateDBPath := db.StateDBPath()
	memoryDBPath := db.MemoryDBPath()
	for _, p := range []string{stateDBPath, memoryDBPath} {
		if _, err := os.Stat(p); os.IsNotExist(err) {
			f, _ := os.Create(p) //nolint:gosec
			if f != nil {
				f.Close() //nolint:errcheck,gosec
			}
		}
	}

	database, err := db.New(stateDBPath, memoryDBPath)
	if err != nil {
		log.Fatalf("open DB: %v", err) //nolint:gocritic
	}

	victoriaDBPath := db.VictoriaDBPath()
	if _, err := os.Stat(victoriaDBPath); os.IsNotExist(err) {
		f, _ := os.Create(victoriaDBPath) //nolint:gosec
		if f != nil {
			f.Close() //nolint:errcheck,gosec
		}
	}
	vdb, err := db.NewVictoria(victoriaDBPath)
	if err != nil {
		database.Close() //nolint:errcheck,gosec
		log.Fatalf("open Victoria DB: %v", err)
	}
	defer database.Close()
	defer vdb.Close()

	// ---------------------------------------------------------------------------
	// Prometheus observability layer (existing, coexists with OTel)
	// ---------------------------------------------------------------------------
	logger := slog.Default()

	metrics := observability.NewMetrics()

	composite := observability.NewCompositeHealth(logger)
	composite.Register(observability.NewDBHealthChecker("state-db", func(ctx context.Context) error {
		return database.StateDB().PingContext(ctx)
	}, 2*time.Second))
	composite.Register(observability.NewDBHealthChecker("memory-db", func(ctx context.Context) error {
		return database.MemoryDB().PingContext(ctx)
	}, 2*time.Second))

	cbRegistry := observability.NewCircuitBreakerRegistry(
		observability.DefaultCircuitBreakerConfig(), logger, metrics,
	)

	bus := observability.NewEventBus(logger)

	degradationMonitor := observability.NewDegradationMonitor(
		observability.DefaultDegradationConfig(), bus, metrics, logger,
	)
	_ = degradationMonitor // available for orchestrator integration

	diagCollector := observability.NewDiagnosticsCollector(nil, nil, cbRegistry, logger)

	// ── Service handlers ──────────────────────────────────────────────────────
	h := handler.New(database)
	vh := handler.NewVictoria(vdb)
	sh := handler.NewState(database)

	// ── New proto-service handlers ────────────────────────────────────────────
	autonomyH := handler.NewAutonomy()
	adversarialH := handler.NewAdversarial(database)

	safetyH, err := handler.NewSafety(database)
	if err != nil {
		log.Printf("warn: safety handler init failed (%v), using unimplemented stub", err)
	}

	memoryH, err := handler.NewMemory(database)
	if err != nil {
		log.Printf("warn: memory handler init failed (%v), using unimplemented stub", err)
	}

	improvementH := handler.NewImprovement()

	// ── Terminal manager + handler ────────────────────────────────────────────
	terminalMgr := terminal.NewManager(terminal.WithDB(database))
	terminalH := handler.NewTerminal(terminalMgr, database)

	// ── Data service: connector registry + DataHandler ────────────────────────
	httpClient := integrations.NewSharedHTTPClient(integrations.DefaultHTTPClientConfig())
	connectorRegistry := integrations.NewConnectorRegistry()

	binanceConnector := connectors.NewBinance(httpClient)
	cgConnector := connectors.NewCoinGecko(httpClient)

	for _, c := range []integrations.Connector{binanceConnector, cgConnector} {
		if err := connectorRegistry.Register(c); err != nil {
			log.Printf("warn: connector register %q: %v", c.Name(), err)
		}
	}

	// AlphaVantage and FRED require API keys; register only when configured.
	if avKey := os.Getenv("ALPHAVANTAGE_API_KEY"); avKey != "" {
		av := connectors.NewAlphaVantage(httpClient, avKey)
		if err := connectorRegistry.Register(av); err != nil {
			log.Printf("warn: connector register %q: %v", av.Name(), err) //nolint:gosec
		}
	}
	if fredKey := os.Getenv("FRED_API_KEY"); fredKey != "" {
		fred := connectors.NewFRED(httpClient, fredKey)
		if err := connectorRegistry.Register(fred); err != nil {
			log.Printf("warn: connector register %q: %v", fred.Name(), err) //nolint:gosec
		}
	}

	dataH := handler.NewData(connectorRegistry, binanceConnector, cgConnector)

	// ── Node registry + handler ───────────────────────────────────────────────
	nodeReg, err := registry.NewNodeRegistry()
	if err != nil {
		log.Printf("warn: node registry init failed (%v), using unimplemented stub", err)
	}
	if nodeReg != nil {
		nodeReg.StartHealthLoop(ctx, 15*time.Second)
	}
	var nodeH *handler.NodeHandler
	if nodeReg != nil {
		nodeH = handler.NewNodeHandler(nodeReg)
	}

	// ── Project handler ───────────────────────────────────────────────────────
	projectH := handler.NewProject()
	projectH.SeedProject(victoriaProject())

	// ── Mux registration ──────────────────────────────────────────────────────
	mux := http.NewServeMux()

	// Connect-RPC service handlers — all wrapped with OTel interceptor.
	path, svcHandler := omegav1connect.NewOrchestratorServiceHandler(h, withHandlerOpts()...)
	mux.Handle(path, svcHandler)

	vPath, vSvcHandler := omegav1connect.NewVictoriaServiceHandler(vh, withHandlerOpts()...)
	mux.Handle(vPath, vSvcHandler)

	sPath, sSvcHandler := omegav1connect.NewStateServiceHandler(sh, withHandlerOpts()...)
	mux.Handle(sPath, sSvcHandler)

	aPath, aSvcHandler := omegav1connect.NewAutonomyServiceHandler(autonomyH, withHandlerOpts()...)
	mux.Handle(aPath, aSvcHandler)

	advPath, advSvcHandler := omegav1connect.NewAdversarialServiceHandler(adversarialH, withHandlerOpts()...)
	mux.Handle(advPath, advSvcHandler)

	if safetyH != nil {
		sfPath, sfSvcHandler := omegav1connect.NewSafetyServiceHandler(safetyH, withHandlerOpts()...)
		mux.Handle(sfPath, sfSvcHandler)
	} else {
		sfPath, sfSvcHandler := omegav1connect.NewSafetyServiceHandler(
			omegav1connect.UnimplementedSafetyServiceHandler{}, withHandlerOpts()...,
		)
		mux.Handle(sfPath, sfSvcHandler)
	}

	if memoryH != nil {
		mPath, mSvcHandler := omegav1connect.NewMemoryServiceHandler(memoryH, withHandlerOpts()...)
		mux.Handle(mPath, mSvcHandler)
	} else {
		mPath, mSvcHandler := omegav1connect.NewMemoryServiceHandler(
			omegav1connect.UnimplementedMemoryServiceHandler{}, withHandlerOpts()...,
		)
		mux.Handle(mPath, mSvcHandler)
	}

	impPath, impSvcHandler := omegav1connect.NewImprovementServiceHandler(improvementH, withHandlerOpts()...)
	mux.Handle(impPath, impSvcHandler)

	termPath, termSvcHandler := omegav1connect.NewTerminalServiceHandler(terminalH, withHandlerOpts()...)
	mux.Handle(termPath, termSvcHandler)

	if nodeH != nil {
		nodePath, nodeSvcHandler := omegav1connect.NewNodeServiceHandler(nodeH, withHandlerOpts()...)
		mux.Handle(nodePath, nodeSvcHandler)
	} else {
		nodePath, nodeSvcHandler := omegav1connect.NewNodeServiceHandler(
			omegav1connect.UnimplementedNodeServiceHandler{}, withHandlerOpts()...,
		)
		mux.Handle(nodePath, nodeSvcHandler)
	}

	dataPath, dataSvcHandler := omegav1connect.NewDataServiceHandler(dataH, withHandlerOpts()...)
	mux.Handle(dataPath, dataSvcHandler)

	projPath, projSvcHandler := omegav1connect.NewProjectServiceHandler(projectH, withHandlerOpts()...)
	mux.Handle(projPath, projSvcHandler)

	// Observability endpoints.
	observability.NewHealthHandler(composite).RegisterRoutes(mux)
	observability.NewDiagnosticsHandler(diagCollector).RegisterRoutes(mux)
	mux.Handle("/metrics", metrics.Handler())

	_ = bus // available for event streaming integration

	// ── Execution middleware chain (wired into HTTP handler) ──────────────────
	// context_recovery: injects recovery signal when execution depth exceeds threshold.
	// metrics_collector: counts total/success/error executions.
	// loop_detection: warns/aborts on repeated identical (node, action, path) calls.
	// autonomy_gate: enforces autonomy level constraints on execution requests.
	mwCounters := new(mw.Counters)
	execChain := mw.NewChain(
		func(_ context.Context, _ *mw.ExecutionRequest) (*mw.ExecutionResponse, error) {
			return &mw.ExecutionResponse{}, nil
		},
		mw.NewContextRecoveryMiddleware(0),
		mw.NewMetricsCollectorMiddleware(mwCounters),
		mw.NewLoopDetectionMiddleware(),
		mw.NewAutonomyGateMiddleware(),
	)

	addr := ":8080"
	if p := os.Getenv("OMEGA_API_PORT"); p != "" {
		addr = ":" + p
	}
	log.Printf("Omega API listening on %s", addr) //nolint:gosec
	log.Printf("Observability: /healthz /readyz /metrics /debug/diagnostics (OTel endpoint=%q)", telCfg.OtlpEndpoint)
	log.Fatal(http.ListenAndServe(addr, h2c.NewHandler( //nolint:gosec,gocritic
		withCORS(withPanicRecovery(withExecChain(execChain, mux))),
		&http2.Server{},
	)))
}

// withCORS enforces a configurable CORS origin allowlist.
// Origins are read from OMEGA_CORS_ORIGINS (comma-separated).
// Defaults to localhost dev origins when the env var is unset.
func withCORS(h http.Handler) http.Handler {
	rawOrigins := os.Getenv("OMEGA_CORS_ORIGINS")
	if rawOrigins == "" {
		rawOrigins = "http://localhost:5173,http://localhost:3000,http://localhost:3001"
	}
	allowed := make(map[string]bool)
	for _, o := range strings.Split(rawOrigins, ",") {
		if o = strings.TrimSpace(o); o != "" {
			allowed[o] = true
		}
	}

	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if origin := r.Header.Get("Origin"); allowed[origin] {
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Vary", "Origin")
		}
		w.Header().Set("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers",
			"Content-Type, Connect-Protocol-Version, Connect-Timeout-Ms, "+
				"Grpc-Timeout, X-Grpc-Web, X-User-Agent, "+
				"connect-accept-encoding, connect-content-encoding, "+
				"Authorization, X-Api-Key")
		w.Header().Set("Access-Control-Expose-Headers",
			"Grpc-Status, Grpc-Message, Grpc-Status-Details-Bin, "+
				"connect-accept-encoding, connect-content-encoding")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		h.ServeHTTP(w, r)
	})
}

// withPanicRecovery wraps h with an HTTP-level panic recovery handler.
// Any panics are logged and converted to 500 responses.
func withPanicRecovery(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rv := recover(); rv != nil {
				slog.ErrorContext(r.Context(), "panic recovered in HTTP handler", "panic", rv)
				http.Error(w, "internal server error", http.StatusInternalServerError)
			}
		}()
		h.ServeHTTP(w, r)
	})
}

// withExecChain adapts the internal execution middleware chain to the HTTP handler.
// Observability endpoints (/healthz, /readyz, /metrics, /debug/) bypass the chain
// to avoid loop-detection false positives from polling.
func withExecChain(chain *mw.Chain, h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		p := r.URL.Path
		if p == "/healthz" || p == "/readyz" || p == "/metrics" || strings.HasPrefix(p, "/debug/") || strings.HasPrefix(p, "/omega.") {
			h.ServeHTTP(w, r)
			return
		}
		execReq := &mw.ExecutionRequest{
			NodeID: "http",
			Action: r.Method,
			Payload: []byte(p),
		}
		if _, err := chain.Execute(r.Context(), execReq); err != nil {
			http.Error(w, err.Error(), http.StatusTooManyRequests)
			return
		}
		h.ServeHTTP(w, r)
	})
}

// victoriaProject returns the default "Victoria" crypto-quant project seed.
// Victoria is the first configured instance running on the Omega platform.
func victoriaProject() *omegav1.Project {
	now := timestamppb.Now()
	steps := []*omegav1.PipelineStep{
		{StepId: "step_1", Name: "DataIngestion", NodeType: "DATA_INGESTION", Description: "Fetch and normalize market data from Binance/CoinGecko", Order: 1},
		{StepId: "step_2", Name: "SignalResearch", NodeType: "SIGNAL_RESEARCH", Description: "Generate alpha signals from price, volume, and on-chain data", Order: 2},
		{StepId: "step_3", Name: "IntelligenceCoordination", NodeType: "STRATEGY", Description: "Coordinate signals across timeframes into a coherent view", Order: 3},
		{StepId: "step_4", Name: "DynamicWeights", NodeType: "RISK_MANAGEMENT", Description: "Compute dynamic portfolio weights based on conviction and risk", Order: 4},
		{StepId: "step_5", Name: "DebateGate", NodeType: "VERIFICATION", Description: "Adversarial debate gate — bull/bear case adjudication", Order: 5},
		{StepId: "step_6", Name: "WalkForward", NodeType: "VERIFICATION", Description: "Walk-forward backtest validation of proposed weights", Order: 6},
		{StepId: "step_7", Name: "Memory", NodeType: "MEMORY", Description: "Store episode context, update semantic memory", Order: 7},
		{StepId: "step_8", Name: "ImprovementEngine", NodeType: "IMPROVEMENT", Description: "TPE-driven hyperparameter optimisation across the pipeline", Order: 8},
		{StepId: "step_9", Name: "Ring3Adversarial", NodeType: "ADVERSARIAL", Description: "Final adversarial red-team before execution", Order: 9},
	}
	return &omegav1.Project{
		ProjectId:     "proj_victoria",
		Name:          "Victoria",
		Description:   "Autonomous crypto quantitative research and trading system",
		Status:        "active",
		Domain:        "crypto_quant",
		AutonomyLevel: "supervised",
		NodeIds:       []string{},
		PipelineConfig: steps,
		EvalConfig: &omegav1.EvalConfig{
			PrimaryMetrics: []string{"sharpe_ratio", "ic", "max_drawdown", "win_rate"},
			MetricTargets:  map[string]float64{"sharpe_ratio": 1.5, "ic": 0.05, "max_drawdown": -0.15},
			EvalFrequency:  "per_cycle",
		},
		ImprovementConfig: &omegav1.ImprovementConfig{
			TpeEnabled:         true,
			TpeTrials:          50,
			AdversarialEnabled: true,
			AdversarialRounds:  3,
			WalkForwardEnabled: true,
		},
		Metadata:  map[string]string{"color": "#00ff00"},
		CreatedAt: now,
		UpdatedAt: now,
	}
}
