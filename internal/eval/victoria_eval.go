package eval

import (
	"fmt"
	"math"
	"strings"
	"time"
)

// ── VictoriaEvalSuite ─────────────────────────────────────────────────────────

// VictoriaEvalSuite implements EvalHarness for the Victoria/Vectora market layer.
// It reads a VictoriaSnapshot and evaluates signal quality, portfolio metrics,
// backtest validity, and risk characteristics.
type VictoriaEvalSuite struct {
	provider VictoriaProvider
}

// NewVictoriaEvalSuite creates a VictoriaEvalSuite backed by the given provider.
// Use NewVectoraDBProvider() for live runs or &StubVictoriaProvider{} for tests.
func NewVictoriaEvalSuite(p VictoriaProvider) *VictoriaEvalSuite {
	return &VictoriaEvalSuite{provider: p}
}

// Name implements EvalHarness.
func (v *VictoriaEvalSuite) Name() string { return "victoria" }

// Run implements EvalHarness. It fetches a snapshot and runs all checks.
func (v *VictoriaEvalSuite) Run() EvalResult {
	snap, err := v.provider.Snapshot()
	if err != nil {
		return EvalResult{
			Failed:  1,
			Score:   0,
			Details: []string{fmt.Sprintf("FAIL snapshot fetch: %v", err)},
		}
	}
	if !snap.Available {
		return EvalResult{
			Failed:  1,
			Score:   0,
			Details: []string{"SKIP Victoria DB has no data yet — Python engine has not run or tables are empty"},
		}
	}

	var passed, failed int
	var details []string

	check := func(name string, ok bool, msg string) {
		if ok {
			passed++
			details = append(details, fmt.Sprintf("PASS %s", name))
		} else {
			failed++
			details = append(details, fmt.Sprintf("FAIL %s: %s", name, msg))
		}
	}

	// ── Portfolio metrics ──────────────────────────────────────────────────
	p := snap.Portfolio
	check("sharpe_positive",
		p.Sharpe > 0,
		fmt.Sprintf("Sharpe=%.3f must be > 0", p.Sharpe))
	check("sharpe_threshold",
		p.Sharpe >= 0.5,
		fmt.Sprintf("Sharpe=%.3f below minimum viable threshold 0.5", p.Sharpe))
	check("win_rate",
		p.WinRate >= 0.45,
		fmt.Sprintf("WinRate=%.2f%% below 45%%", p.WinRate*100))
	check("profit_factor",
		p.ProfitFactor >= 1.0,
		fmt.Sprintf("ProfitFactor=%.3f below 1.0 (losing money net)", p.ProfitFactor))
	check("ann_vol_sane",
		p.AnnVol > 0 && p.AnnVol < 1.5,
		fmt.Sprintf("AnnVol=%.2f%% outside sane range (0, 150%%)", p.AnnVol*100))

	// ── PnL / risk metrics ─────────────────────────────────────────────────
	if snap.PnL != nil {
		pnl := snap.PnL
		check("max_drawdown",
			pnl.MaxDD >= 0 && pnl.MaxDD < 0.25,
			fmt.Sprintf("MaxDD=%.1f%% exceeds 25%% limit", pnl.MaxDD*100))
		check("sortino_positive",
			pnl.Sortino > 0,
			fmt.Sprintf("Sortino=%.3f <= 0 (downside risk dominates)", pnl.Sortino))
		check("cvar_sane",
			pnl.CVaR95 >= 0 && pnl.CVaR95 < 0.15,
			fmt.Sprintf("CVaR95=%.1f%% exceeds 15%%", pnl.CVaR95*100))
	}

	// ── Signal quality ─────────────────────────────────────────────────────
	if len(snap.Signals) == 0 {
		failed++
		details = append(details, "FAIL no_signals: no signals registered in DB")
	} else {
		// At least one signal with meaningful IC.
		bestIC := 0.0
		totalWeight := 0.0
		totalBrier := 0.0
		sigCount := float64(len(snap.Signals))
		for _, sig := range snap.Signals {
			if sig.AvgIC > bestIC {
				bestIC = sig.AvgIC
			}
			totalWeight += sig.Weight
			totalBrier += sig.BrierScore
		}
		avgBrier := totalBrier / sigCount

		check("signal_ic",
			bestIC >= 0.05,
			fmt.Sprintf("best signal IC=%.4f below 0.05 — all signals near noise", bestIC))
		check("signal_weights_sum",
			math.Abs(totalWeight-1.0) < 0.05,
			fmt.Sprintf("signal weights sum=%.3f (expected ~1.0)", totalWeight))
		check("brier_score",
			avgBrier < 0.30,
			fmt.Sprintf("avg BrierScore=%.3f >= 0.30 — poor confidence calibration", avgBrier))

		// Signal-to-noise ratio: IC > 0.05 signals / total signals.
		stnSignals := 0
		for _, sig := range snap.Signals {
			if sig.AvgIC > 0.05 {
				stnSignals++
			}
		}
		stn := float64(stnSignals) / sigCount
		check("signal_to_noise",
			stn >= 0.5,
			fmt.Sprintf("only %.0f%% of signals above IC=0.05 threshold", stn*100))
	}

	// ── Backtest validity ──────────────────────────────────────────────────
	if bt := snap.BacktestStats; bt != nil && bt.SharpeAnn != 0 {
		check("backtest_sharpe_positive",
			bt.SharpeAnn > 0,
			fmt.Sprintf("backtest SharpeAnn=%.3f <= 0", bt.SharpeAnn))

		// IS/OOS overfitting check: OOS Sharpe should be >= 70% of IS Sharpe.
		if bt.SharpeIS > 0 && bt.SharpeOOS != 0 {
			ratio := bt.SharpeOOS / bt.SharpeIS
			check("is_oos_gap",
				ratio >= 0.70,
				fmt.Sprintf("OOS/IS Sharpe ratio=%.2f — possible overfitting (SharpeIS=%.2f, SharpeOOS=%.2f)",
					ratio, bt.SharpeIS, bt.SharpeOOS))
		}

		check("backtest_max_dd",
			bt.MaxDDPct < 0.30,
			fmt.Sprintf("backtest MaxDD=%.1f%% exceeds 30%%", bt.MaxDDPct*100))
	}

	// ── Regime analysis ────────────────────────────────────────────────────
	if rm := snap.RiskMetrics; rm != nil {
		if len(rm.Regimes) > 0 {
			// Must have at least one regime with positive Sharpe.
			positiveRegimes := 0
			for _, r := range rm.Regimes {
				if r.Sharpe > 0 {
					positiveRegimes++
				}
			}
			check("regime_positive",
				positiveRegimes > 0,
				"no regime shows positive Sharpe — strategy has no directional edge")
		}

		// Crash scenario pass rate.
		if len(rm.Crashes) > 0 {
			passed_crashes := 0
			for _, c := range rm.Crashes {
				if c.Pass {
					passed_crashes++
				}
			}
			passRate := float64(passed_crashes) / float64(len(rm.Crashes))
			check("crash_scenarios",
				passRate >= 0.5,
				fmt.Sprintf("only %.0f%% of crash scenarios passed (%d/%d)",
					passRate*100, passed_crashes, len(rm.Crashes)))
		}

		// Ablation: at least one signal should have significant Sharpe contribution.
		if len(rm.Ablation) > 0 {
			sigCount := 0
			for _, a := range rm.Ablation {
				if a.Sig {
					sigCount++
				}
			}
			check("ablation_significance",
				sigCount > 0,
				"no signal shows statistically significant Sharpe contribution")
		}
	}

	total := passed + failed
	score := 0.0
	if total > 0 {
		score = float64(passed) / float64(total)
	}

	return EvalResult{
		Passed:  passed,
		Failed:  failed,
		Score:   score,
		Details: details,
	}
}

// ── ObservabilityAudit ────────────────────────────────────────────────────────

// ObsStatus classifies how observable a package is.
type ObsStatus string

const (
	ObsObservable ObsStatus = "Observable"
	ObsPartial    ObsStatus = "Partial"
	ObsBlackBox   ObsStatus = "BlackBox"
	ObsNA         ObsStatus = "N/A"
)

// PackageAudit describes the observability posture of one internal/ package.
type PackageAudit struct {
	Package    string
	Status     ObsStatus
	HasMetrics bool   // Prometheus instruments
	HasSlog    bool   // structured logging (log/slog)
	HasTraces  bool   // trace/span hooks
	Notes      string // what IS visible
	Recommend  string // what to add to improve
}

// SystemAudit is the result of ObservabilityAudit.Run().
type SystemAudit struct {
	Packages        []PackageAudit
	VisibilityScore float64 // fraction of non-N/A packages that are Observable or Partial
	ObservableCount int
	PartialCount    int
	BlackBoxCount   int
}

// ObservabilityAudit inspects each internal/ package and classifies its
// observability posture. It works statically from known package contents
// (no runtime reflection needed).
type ObservabilityAudit struct{}

// Name implements EvalHarness.
func (o *ObservabilityAudit) Name() string { return "observability-audit" }

// Run implements EvalHarness. Returns a score equal to the visibility fraction.
func (o *ObservabilityAudit) Run() EvalResult {
	audit := o.RunAudit()

	total := audit.ObservableCount + audit.PartialCount + audit.BlackBoxCount
	var details []string
	for _, p := range audit.Packages {
		marker := "✓"
		if p.Status == ObsBlackBox {
			marker = "✗"
		} else if p.Status == ObsPartial {
			marker = "~"
		} else if p.Status == ObsNA {
			marker = "-"
		}
		details = append(details, fmt.Sprintf("%s [%s] %s — %s", marker, p.Status, p.Package, p.Notes))
	}
	details = append(details, fmt.Sprintf(
		"Visibility: %.0f%% (%d observable, %d partial, %d black-box of %d audited)",
		audit.VisibilityScore*100,
		audit.ObservableCount, audit.PartialCount, audit.BlackBoxCount, total))

	return EvalResult{
		Passed:  audit.ObservableCount + audit.PartialCount,
		Failed:  audit.BlackBoxCount,
		Score:   audit.VisibilityScore,
		Details: details,
	}
}

// RunAudit returns the full SystemAudit with per-package detail.
func (o *ObservabilityAudit) RunAudit() SystemAudit {
	packages := []PackageAudit{
		// ── Fully observable ────────────────────────────────────────────────
		{
			Package:    "internal/observability",
			Status:     ObsObservable,
			HasMetrics: true,
			HasSlog:    true,
			HasTraces:  false,
			Notes:      "Prometheus registry with cycle duration, node execution, autonomy promotions, adversarial vetoes, memory consolidations, improvement proposals, safety violations, circuit breaker state, error rates",
			Recommend:  "Add OpenTelemetry trace export; add histogram for DB query latency",
		},
		// ── Partial ─────────────────────────────────────────────────────────
		{
			Package:    "internal/core",
			Status:     ObsPartial,
			HasMetrics: false,
			HasSlog:    true,
			HasTraces:  false,
			Notes:      "orchestrator_events.go emits structured events; metrics_aggregator.go feeds SSE dashboard; improvement_engine uses slog; no Prometheus instruments directly in package",
			Recommend:  "Wire core events into observability.Metrics (CycleDuration, ImprovementProposals); add per-subsystem error counters",
		},
		{
			Package:    "internal/middleware",
			Status:     ObsPartial,
			HasMetrics: false,
			HasSlog:    false,
			HasTraces:  false,
			Notes:      "MetricsCollectorMiddleware tracks atomic counters (Total, Success, Errors) and wall-clock duration per chain execution; not exported to Prometheus",
			Recommend:  "Expose Counters as Prometheus gauges/counters; add per-chain histogram for execution duration",
		},
		{
			Package:    "internal/framework",
			Status:     ObsPartial,
			HasMetrics: false,
			HasSlog:    true,
			HasTraces:  false,
			Notes:      "service_registry.go tracks registered services; plugin.go manages lifecycle; slog used in config hot-reload; no metrics",
			Recommend:  "Add plugin registration/deregistration counter; add service health gauge",
		},
		{
			Package:    "internal/db",
			Status:     ObsPartial,
			HasMetrics: false,
			HasSlog:    false,
			HasTraces:  false,
			Notes:      "Victoria state readable via VectoraDB (portfolio, PnL, signals, backtest, equity curve, risk metrics); no query latency metrics, no error rate, no DB size metric",
			Recommend:  "Add Prometheus histogram for SQL query duration per table; add counter for query errors; add gauge for last_updated_at staleness",
		},
		// ── Black boxes ─────────────────────────────────────────────────────
		{
			Package:    "internal/handler",
			Status:     ObsBlackBox,
			HasMetrics: false,
			HasSlog:    false,
			HasTraces:  false,
			Notes:      "VectoraHandler, OrchestratorHandler etc. handle HTTP/Connect-RPC; no per-request latency, no error rate, no request count",
			Recommend:  "Add Connect-RPC interceptor that records request duration, status code, and error rate per method into observability.Metrics.SubsystemErrorsTotal",
		},
		{
			Package:    "internal/memory",
			Status:     ObsBlackBox,
			HasMetrics: false,
			HasSlog:    false,
			HasTraces:  false,
			Notes:      "episodic.go, semantic.go, persistence.go implement memory store; write_queue.go queues writes; no metrics on write throughput, queue depth, or consolidation latency",
			Recommend:  "Add gauge for write queue depth; add counter for episodic/semantic store operations; add histogram for consolidation duration",
		},
		{
			Package:    "internal/tools",
			Status:     ObsBlackBox,
			HasMetrics: false,
			HasSlog:    false,
			HasTraces:  false,
			Notes:      "registry.go, search.go, builtin.go, authorization.go implement tool dispatch; no metrics on tool invocation count, latency, or authorization failures",
			Recommend:  "Add counter for tool invocations per tool name; add counter for authorization failures; add histogram for tool execution duration",
		},
		{
			Package:    "internal/coord",
			Status:     ObsBlackBox,
			HasMetrics: false,
			HasSlog:    false,
			HasTraces:  false,
			Notes:      "Distributed coordination layer; no metrics on coordination events, leader election, or inter-process message latency",
			Recommend:  "Add gauge for active coordinators; add counter for coordination messages; add histogram for consensus latency",
		},
		{
			Package:    "internal/adversarial",
			Status:     ObsBlackBox,
			HasMetrics: false,
			HasSlog:    false,
			HasTraces:  false,
			Notes:      "Adversarial pressure module; flag rate and veto decisions not instrumented outside of core.AdversarialPressure",
			Recommend:  "Expose flag rate as Prometheus gauge; add counter for flagged vs passed proposals; add histogram for adversarial check duration",
		},
		{
			Package:    "internal/boundary",
			Status:     ObsBlackBox,
			HasMetrics: false,
			HasSlog:    false,
			HasTraces:  false,
			Notes:      "Boundary enforcement; violations not instrumented",
			Recommend:  "Add counter for boundary violations per boundary type",
		},
		{
			Package:    "internal/errors",
			Status:     ObsBlackBox,
			HasMetrics: false,
			HasSlog:    false,
			HasTraces:  false,
			Notes:      "Error types and wrapping; no error frequency metrics",
			Recommend:  "Add counter for error occurrences per error category",
		},
		{
			Package:    "internal/config",
			Status:     ObsBlackBox,
			HasMetrics: false,
			HasSlog:    false,
			HasTraces:  false,
			Notes:      "Version tracking and auto-upgrade; no metrics on config reload frequency or version transitions",
			Recommend:  "Add counter for config reloads; add gauge for current config version",
		},
		{
			Package:    "internal/skills",
			Status:     ObsBlackBox,
			HasMetrics: false,
			HasSlog:    false,
			HasTraces:  false,
			Notes:      "Skills packaging; no metrics on skill invocations or failures",
			Recommend:  "Add counter for skill invocations per skill name; add counter for skill failures",
		},
		{
			Package:    "internal/conformance",
			Status:     ObsBlackBox,
			HasMetrics: false,
			HasSlog:    false,
			HasTraces:  false,
			Notes:      "Conformance tests; outputs only in test context",
			Recommend:  "Emit conformance check results to observability layer for continuous validation",
		},
		// ── Python layer (cross-boundary) ────────────────────────────────────
		{
			Package:    "python/VectoraNode+signals",
			Status:     ObsBlackBox,
			HasMetrics: false,
			HasSlog:    false,
			HasTraces:  false,
			Notes:      "VectoraNode, signals_advanced.py, dynamic_weights.py, backtest.py, TPE optimizer — completely opaque from Go; state only visible when Python writes to SQLite",
			Recommend:  "Add Python prometheus_client metrics for: signal IC per bar, signal generation latency, TPE trial scores, data ingestion success/failure; expose /metrics from Python process",
		},
		// ── Test utilities ───────────────────────────────────────────────────
		{
			Package:   "internal/testing",
			Status:    ObsNA,
			Notes:     "Test utilities only; not part of production observability surface",
			Recommend: "",
		},
	}

	var obsCount, partialCount, blackCount int
	for _, p := range packages {
		switch p.Status {
		case ObsObservable:
			obsCount++
		case ObsPartial:
			partialCount++
		case ObsBlackBox:
			blackCount++
		}
	}

	audited := obsCount + partialCount + blackCount
	visScore := 0.0
	if audited > 0 {
		visScore = float64(obsCount+partialCount) / float64(audited)
	}

	return SystemAudit{
		Packages:        packages,
		VisibilityScore: visScore,
		ObservableCount: obsCount,
		PartialCount:    partialCount,
		BlackBoxCount:   blackCount,
	}
}

// ── VictoriaReport ────────────────────────────────────────────────────────────

// VictoriaReport is the top-level result combining the eval suite and
// observability audit into an actionable markdown document.
type VictoriaReport struct {
	GeneratedAt   time.Time
	EvalResult    EvalResult
	AuditResult   SystemAudit
	ProviderSource string
	ProviderLive  bool
}

// RunVictoriaEval executes both the VictoriaEvalSuite and ObservabilityAudit
// and returns a VictoriaReport ready for rendering.
func RunVictoriaEval(provider VictoriaProvider) VictoriaReport {
	suite := NewVictoriaEvalSuite(provider)
	audit := &ObservabilityAudit{}

	return VictoriaReport{
		GeneratedAt:   time.Now().UTC(),
		EvalResult:    suite.Run(),
		AuditResult:   audit.RunAudit(),
		ProviderSource: provider.Source(),
		ProviderLive:  provider.IsLive(),
	}
}

// Markdown renders the VictoriaReport as a GitHub-flavoured markdown document.
func (r *VictoriaReport) Markdown() string {
	var b strings.Builder

	mode := "stub (offline)"
	if r.ProviderLive {
		mode = fmt.Sprintf("live (%s)", r.ProviderSource)
	}

	fmt.Fprintf(&b, "# Victoria Eval Report\n\n")
	fmt.Fprintf(&b, "_Generated: %s — data source: %s_\n\n", r.GeneratedAt.Format(time.RFC3339), mode)

	// ── Signal & Portfolio Quality ─────────────────────────────────────────
	fmt.Fprintf(&b, "## Signal & Portfolio Quality\n\n")
	evalScore := r.EvalResult.Score * 100
	totalChecks := r.EvalResult.Passed + r.EvalResult.Failed
	fmt.Fprintf(&b, "**Score: %.0f%% (%d/%d checks passed)**\n\n", evalScore, r.EvalResult.Passed, totalChecks)

	fmt.Fprintf(&b, "| Result | Check |\n|--------|-------|\n")
	for _, d := range r.EvalResult.Details {
		icon := "✅"
		if strings.HasPrefix(d, "FAIL") {
			icon = "❌"
		} else if strings.HasPrefix(d, "SKIP") {
			icon = "⏭️"
		}
		fmt.Fprintf(&b, "| %s | %s |\n", icon, strings.TrimPrefix(strings.TrimPrefix(strings.TrimPrefix(d, "PASS "), "FAIL "), "SKIP "))
	}
	fmt.Fprintf(&b, "\n")

	// ── Observability / Visibility Score ──────────────────────────────────
	a := r.AuditResult
	fmt.Fprintf(&b, "## Observability Audit\n\n")
	fmt.Fprintf(&b, "**Visibility Score: %.0f%%** — %d observable, %d partial, %d black-box\n\n",
		a.VisibilityScore*100, a.ObservableCount, a.PartialCount, a.BlackBoxCount)

	fmt.Fprintf(&b, "| Status | Package | What We See | Recommended Addition |\n")
	fmt.Fprintf(&b, "|--------|---------|-------------|----------------------|\n")
	for _, p := range a.Packages {
		icon := map[ObsStatus]string{
			ObsObservable: "🟢",
			ObsPartial:    "🟡",
			ObsBlackBox:   "🔴",
			ObsNA:         "⚪",
		}[p.Status]
		rec := p.Recommend
		if rec == "" {
			rec = "—"
		}
		fmt.Fprintf(&b, "| %s %s | `%s` | %s | %s |\n",
			icon, p.Status, p.Package, p.Notes, rec)
	}
	fmt.Fprintf(&b, "\n")

	// ── Improvement Candidates (ranked) ───────────────────────────────────
	fmt.Fprintf(&b, "## Improvement Candidates (Priority Order)\n\n")
	candidates := improvementCandidates(r)
	for i, c := range candidates {
		fmt.Fprintf(&b, "%d. **%s** — %s\n", i+1, c.title, c.reason)
	}
	fmt.Fprintf(&b, "\n")

	// ── Missing Instrumentation ────────────────────────────────────────────
	fmt.Fprintf(&b, "## Missing Instrumentation\n\n")
	fmt.Fprintf(&b, "The following would immediately increase visibility:\n\n")
	for _, p := range a.Packages {
		if p.Status == ObsBlackBox && p.Recommend != "" {
			fmt.Fprintf(&b, "- **`%s`**: %s\n", p.Package, p.Recommend)
		}
	}
	fmt.Fprintf(&b, "\n")
	fmt.Fprintf(&b, "### Partial packages that need promotion\n\n")
	for _, p := range a.Packages {
		if p.Status == ObsPartial && p.Recommend != "" {
			fmt.Fprintf(&b, "- **`%s`**: %s\n", p.Package, p.Recommend)
		}
	}

	return b.String()
}

type candidate struct {
	title  string
	reason string
}

// improvementCandidates returns a ranked list of what to fix first based on
// the eval results and audit findings.
func improvementCandidates(r *VictoriaReport) []candidate {
	var cs []candidate

	// Failed eval checks → immediate improvements.
	for _, d := range r.EvalResult.Details {
		if strings.HasPrefix(d, "FAIL") {
			msg := strings.TrimPrefix(d, "FAIL ")
			cs = append(cs, candidate{
				title:  "Fix eval failure",
				reason: msg,
			})
		}
	}

	// Black-box packages with handler/critical path impact go first.
	priority := []string{"internal/handler", "python/VectoraNode+signals", "internal/memory", "internal/tools"}
	a := r.AuditResult
	for _, name := range priority {
		for _, p := range a.Packages {
			if p.Package == name && p.Status == ObsBlackBox {
				cs = append(cs, candidate{
					title:  fmt.Sprintf("Instrument %s", p.Package),
					reason: p.Recommend,
				})
			}
		}
	}

	// Partial packages that are close to observable.
	for _, p := range a.Packages {
		if p.Status == ObsPartial {
			cs = append(cs, candidate{
				title:  fmt.Sprintf("Promote %s to Observable", p.Package),
				reason: p.Recommend,
			})
		}
	}

	return cs
}
