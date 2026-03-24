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

	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/auth"
	"github.com/benebsworth/omega/internal/bridge"
	"github.com/benebsworth/omega/internal/coordination"
	"github.com/benebsworth/omega/internal/db"
	"github.com/benebsworth/omega/internal/handler"
	"github.com/benebsworth/omega/internal/integrations"
	"github.com/benebsworth/omega/internal/integrations/connectors"
	mw "github.com/benebsworth/omega/internal/middleware"
	"github.com/benebsworth/omega/internal/observability"
	"github.com/benebsworth/omega/internal/projectseed"
	"github.com/benebsworth/omega/internal/registry"
	"github.com/benebsworth/omega/internal/telemetry"
	"github.com/benebsworth/omega/internal/terminal"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	// ---------------------------------------------------------------------------
	// OpenTelemetry — initialise before anything else so all downstream code
	// gets instrumented automatically.
	// ---------------------------------------------------------------------------
	otlpEndpoint := os.Getenv("OTLP_ENDPOINT")
	if otlpEndpoint == "" {
		// Auto-detect: if the OTel collector is reachable at localhost:4318, use it.
		// This covers `make dev` runs where OTLP_ENDPOINT may not be explicitly set.
		if otelCollectorReachable("http://localhost:4318") {
			otlpEndpoint = "http://localhost:4318"
			log.Printf("OTLP: auto-configured to %s (collector reachable)", otlpEndpoint) //nolint:gosec
		} else {
			log.Printf("warn: OTLP_ENDPOINT not set and collector not reachable at localhost:4318 — traces will not be exported")
		}
	}
	telCfg := telemetry.Config{
		OtlpEndpoint:         otlpEndpoint,
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
	database, err := db.New(ctx)
	if err != nil {
		log.Fatalf("open DB: %v", err) //nolint:gocritic
	}
	defer database.Close()

	vdb := db.NewVictoria(database.StateDB())

	// ---------------------------------------------------------------------------
	// Prometheus observability layer (existing, coexists with OTel)
	// ---------------------------------------------------------------------------
	logger := slog.Default()
	database.StartPoolStatsLogger(ctx, 60*time.Second, logger)

	metrics := observability.NewMetrics()

	composite := observability.NewCompositeHealth(logger)
	composite.Register(observability.NewDBHealthChecker("postgres", func(ctx context.Context) error {
		return database.StateDB().PingContext(ctx)
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

	// ── Project handler — created first so the orchestrator can read pipeline configs ──
	// Projects are loaded from YAML files in OMEGA_PROJECTS_DIR (default: ./projects/).
	projectH := handler.NewProject()
	if err := projectseed.LoadAndSeed(projectH, ""); err != nil {
		log.Printf("warn: project loader: %v — no projects registered from YAML", err)
	}
	// Ensure each project has its own Postgres schema namespace.
	for _, p := range projectH.AllProjects() {
		if err := database.EnsureProjectSchema(ctx, p.ProjectId); err != nil {
			log.Printf("warn: ensure schema for project %q: %v", p.ProjectId, err)
		} else {
			log.Printf("Project schema ready: %s", db.ProjectSchemaName(p.ProjectId))
		}
	}

	// ── Service handlers ──────────────────────────────────────────────────────
	h := handler.New(database).WithCircuitBreakerRegistry(cbRegistry).WithProjectHandler(projectH).WithMetrics(metrics)

	// Pipeline bridge — connects Go orchestrator to Python pipeline server.
	// Set OMEGA_PYTHON_PIPELINE_ADDR (e.g. "http://localhost:9090") to enable.
	// When unset, runCycle() skips Python step dispatch and runs observation-only.
	if addr := os.Getenv("OMEGA_PYTHON_PIPELINE_ADDR"); addr != "" {
		pipelineClient := bridge.NewPipelineClient(addr)
		h = h.WithPipelineClient(pipelineClient)
		log.Printf("Pipeline bridge: Go→Python connected at %s", addr) //nolint:gosec
		// Register bridge as a platform health checker (DEGRADED, not UNHEALTHY, when unreachable).
		bridgeAddr := addr
		composite.Register(observability.NewHealthCheckerFunc("bridge", func(hctx context.Context) observability.HealthStatus {
			req, err := http.NewRequestWithContext(hctx, http.MethodGet, bridgeAddr+"/health", nil)
			if err != nil {
				return observability.HealthStatus{State: observability.HealthStateDegraded, Details: map[string]any{"error": err.Error()}}
			}
			bridgeClient := &http.Client{Timeout: 2 * time.Second}
			resp, err := bridgeClient.Do(req) //nolint:gosec // bridgeAddr is the operator-configured OMEGA_PYTHON_PIPELINE_ADDR
			if err != nil {
				return observability.HealthStatus{State: observability.HealthStateDegraded, Details: map[string]any{"error": err.Error()}}
			}
			if err := resp.Body.Close(); err != nil {
				_ = err // non-fatal; body already read
			}
			return observability.HealthStatus{State: observability.HealthStateHealthy, Details: map[string]any{"addr": bridgeAddr}}
		}))
	} else {
		log.Printf("Pipeline bridge: disabled (set OMEGA_PYTHON_PIPELINE_ADDR to enable)")
	}
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

	// ── Coordination handler ───────────────────────────────────────────────────
	var coordH *coordination.Handler
	if outcomeStore, outcomeErr := coordination.NewOutcomeStore(database.StateDB()); outcomeErr != nil {
		log.Printf("warn: coordination outcome store init failed (%v), using no-persistence mode", outcomeErr)
		coordH = coordination.NewDefaultHandler(nil, logger)
	} else {
		coordH = coordination.NewDefaultHandler(outcomeStore, logger)
	}

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

	coordPath, coordSvcHandler := omegav1connect.NewCoordinationServiceHandler(coordH, withHandlerOpts()...)
	mux.Handle(coordPath, coordSvcHandler)

	// PipelineService — Python is the authoritative server; Go mounts an
	// unimplemented stub so the service path is registered for discovery.
	pipePath, pipeSvcHandler := omegav1connect.NewPipelineServiceHandler(
		omegav1connect.UnimplementedPipelineServiceHandler{}, withHandlerOpts()...,
	)
	mux.Handle(pipePath, pipeSvcHandler)

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

	srv := &http.Server{ //nolint:gosec
		Addr:              addr,
		Handler:           h2c.NewHandler(withCORS(withPanicRecovery(withExecChain(execChain, mux))), &http2.Server{}),
		ReadHeaderTimeout: 10 * time.Second,
	}

	// Start serving in a goroutine so we can listen for shutdown signals.
	serverErr := make(chan error, 1)
	go func() {
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			serverErr <- err
		}
	}()

	// Block until SIGINT/SIGTERM or a fatal server error.
	select {
	case <-ctx.Done():
		log.Printf("Shutdown signal received — draining in-flight requests (5s grace)…")
	case err := <-serverErr:
		log.Printf("Server error: %v", err)
	}

	// Give in-flight requests 5 seconds to complete.
	shutCtx, shutCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer shutCancel()
	if err := srv.Shutdown(shutCtx); err != nil {
		log.Printf("HTTP server forced shutdown: %v", err)
	}

	// Close Python pipeline client if configured.
	if os.Getenv("OMEGA_PYTHON_PIPELINE_ADDR") != "" {
		log.Printf("Pipeline bridge: closed") //nolint:gosec
	}

	log.Printf("Omega API shutdown complete.")
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
// otelCollectorReachable returns true if an HTTP GET to addr+"/health"
// succeeds within 500ms. Used to auto-configure OTLP_ENDPOINT at startup.
func otelCollectorReachable(addr string) bool {
	client := &http.Client{Timeout: 500 * time.Millisecond}
	resp, err := client.Get(addr + "/health") //nolint:gosec,noctx
	if err != nil {
		return false
	}
	_ = resp.Body.Close()
	return resp.StatusCode < 500
}

func withExecChain(chain *mw.Chain, h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		p := r.URL.Path
		// REST API paths and observability endpoints bypass the execution chain.
		// The autonomy gate operates on semantic action names (e.g. "run_cycle"),
		// not on HTTP verbs — passing r.Method ("GET") would incorrectly block
		// read-only REST consumers such as the dashboard (BUG-005).
		if p == "/healthz" || p == "/readyz" || p == "/metrics" ||
			strings.HasPrefix(p, "/debug/") ||
			strings.HasPrefix(p, "/omega.v1.") ||
			strings.HasPrefix(p, "/api/v1/") {
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


