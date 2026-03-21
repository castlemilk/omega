"""
omega.examples.vectora_main
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Vectora — Crypto Quantitative Research System
A real-world Omega heartbeat loop with self-evaluation, self-improvement,
memory consolidation, and human+self-supervised feedback.

Architecture:
  DataIngestionNode   → Binance/CoinGecko (free, no auth)
  SignalGenerationNode → SMA, RSI, MACD, BB, BTC-beta, vol-regime
  StrategyNode        → portfolio construction + backtest
  RiskManagementNode  → VaR, CVaR, correlation
  ReportingNode       → human-readable reports

Core infrastructure:
  MemoryKernel   → working + episodic + semantic memory (SQLite)
  FeedbackEngine → human CLI + self-supervised signal evaluation
  StateStore     → node registry, traces, cost events, issues, improvements
  Tracer         → distributed tracing (OpenTelemetry-inspired)
  MetricsCollector → rolling aggregates, dashboard
  SystemAnalyzer → recommendation engine for improvement loop

Heartbeat loop (every N seconds):
  1. begin_cycle (memory decay, consolidation)
  2. Ingest market data
  3. Evaluate last-cycle predictions (self-supervised feedback)
  4. Generate signals
  5. Construct portfolio
  6. Check risk
  7. Generate report (prints to stdout)
  8. Store cycle summary in episodic memory
  9. Evaluate all nodes → Improve() if below threshold
  10. Print status → sleep → repeat

Future SentimentNode (TODO):
  - Use `dv` CLI (Bittensor SN13 / Macrocosmos dataverse) for X/Reddit social data
  - dv search x -k bitcoin -o json → JSON social signal data
  - Pluggable via SentimentIngestionNode implementing the same Node interface

Run:
    python -m omega.examples.vectora_main
    python -m omega.examples.vectora_main --heartbeat 60 --iterations 5
    python -m omega.examples.vectora_main --once
"""

import argparse
import logging
import signal
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from omega.core.evaluator import GoalSpec
from omega.core.feedback import FeedbackEngine
from omega.core.memory import MemoryKernel
from omega.core.memory_v2 import MemoryKernelV2
from omega.core.node import NodeInput
from omega.core.orchestrator import Orchestrator
from omega.core.state_store import StateStore
from omega.core.tracing import Tracer, create_tracer
from omega.core.metrics import MetricsCollector
from omega.core.analyzer import SystemAnalyzer
from omega.core.alignment import AlignmentLayer
from omega.core.adversarial import AdversarialPressure
from omega.core.goals import GoalArchitecture
from omega.nodes.vectora import (
    DataIngestionNode,
    SignalGenerationNode,
    StrategyNode,
    RiskManagementNode,
    ReportingNode,
    LintNode,
    DataIntegrityNode,
    DashboardNode,
)
from omega.nodes.vectora.verification import (
    VerificationNode,
    PropertyTestNode,
    InvariantDiscoveryNode,
    ConvergenceMonitorNode,
)

# ─── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("omega.vectora")

# ─── Constants ─────────────────────────────────────────────────────────────────

GOAL = "vectora_crypto_research"
DB_PATH = "/tmp/omega_vectora.db"
MEMORY_DB_PATH = "/tmp/omega_vectora_memory.db"
STATE_DB_PATH = "/tmp/omega_vectora_state.db"
HEALTH_THRESHOLD = 0.6

# ─── Shutdown flag ─────────────────────────────────────────────────────────────

_shutdown = False


def _handle_sigint(sig, frame):
    global _shutdown
    print("\n\n[Vectora] Shutting down gracefully…")
    _shutdown = True


signal.signal(signal.SIGINT, _handle_sigint)


# ─── Vectora System ────────────────────────────────────────────────────────────

class VectoraSystem:
    """
    Full Vectora pipeline with memory, feedback, and self-improvement.

    Node pipeline: Ingest → Signals → Strategy → Risk → Report
    Infrastructure: MemoryKernel + FeedbackEngine + StateStore + Tracer + MetricsCollector + SystemAnalyzer
    """

    def __init__(self) -> None:
        # ── Core infrastructure ──────────────────────────────────────────────
        self.memory = MemoryKernelV2(db_path=MEMORY_DB_PATH)
        self.feedback = FeedbackEngine(memory=self.memory)

        # ── Research subsystems (alignment, adversarial pressure, goals) ─────
        self.alignment = AlignmentLayer()
        self.adversarial = AdversarialPressure()
        self.goals = GoalArchitecture()

        # ── Observability infrastructure ─────────────────────────────────────
        self.state_store = StateStore(db_path=STATE_DB_PATH)
        self.tracer = create_tracer(self.state_store)
        self.metrics = MetricsCollector(self.state_store)
        self.analyzer = SystemAnalyzer(self.state_store, self.metrics)

        # ── Domain nodes ─────────────────────────────────────────────────────
        self.ingestion = DataIngestionNode()
        self.signals   = SignalGenerationNode()
        self.strategy  = StrategyNode()
        self.risk      = RiskManagementNode()
        self.reporting = ReportingNode()
        self.lint      = LintNode()
        self.integrity = DataIntegrityNode()
        self.verification   = VerificationNode()
        self.property_tests = PropertyTestNode()
        self.invariants     = InvariantDiscoveryNode()
        self.convergence    = ConvergenceMonitorNode()
        # DashboardNode — passed the live StateStore so it can audit metric coverage
        self.dashboard = DashboardNode(
            state_store=self.state_store,
            api_base_url="http://localhost:8080",
        )

        # ── Orchestrator (health tracking, evaluation) ───────────────────────
        self.orchestrator = Orchestrator(name="vectora", db_path=DB_PATH)
        for node in [self.ingestion, self.signals, self.strategy,
                     self.risk, self.reporting, self.lint, self.integrity]:
            self.orchestrator.register_node(node)
        for node in [self.verification, self.property_tests, self.invariants, self.convergence]:
            self.orchestrator.register_node(node)
        self.orchestrator.register_node(self.dashboard)

        # ── Register all nodes in StateStore ─────────────────────────────────
        for node in [self.ingestion, self.signals, self.strategy,
                     self.risk, self.reporting, self.lint, self.integrity]:
            state = node.get_state()
            self.state_store.upsert_node(
                node_id=state.node_id,
                name=state.name,
                version=state.version,
                capabilities=state.capabilities,
                health=state.health,
            )
            self.state_store.log_activity(
                "node_registered", "node", state.node_id,
                {"name": state.name, "version": state.version},
            )
        for node in [self.verification, self.property_tests, self.invariants, self.convergence]:
            state = node.get_state()
            self.state_store.upsert_node(
                node_id=state.node_id,
                name=state.name,
                version=state.version,
                capabilities=state.capabilities,
                health=state.health,
            )
        # Register DashboardNode
        dash_state = self.dashboard.get_state()
        self.state_store.upsert_node(
            node_id=dash_state.node_id,
            name=dash_state.name,
            version=dash_state.version,
            capabilities=dash_state.capabilities,
            health=dash_state.health,
        )
        self.state_store.log_activity(
            "node_registered", "node", dash_state.node_id,
            {"name": dash_state.name, "version": dash_state.version},
        )

        # ── Goal spec ─────────────────────────────────────────────────────────
        spec = (
            GoalSpec(GOAL, description="Vectora crypto quantitative research pipeline")
            .add_metric("coverage_rate",     direction="maximize", weight=2.0)
            .add_metric("signal_coverage",   direction="maximize", weight=2.0)
            .add_metric("sharpe_ratio",      direction="maximize", weight=3.0)
            .add_metric("completeness_score",direction="maximize", weight=1.5)
            .add_metric("error_rate",        direction="minimize", weight=2.0)
            .add_metric("indicator_count",   direction="maximize", weight=1.0)
        )
        self.orchestrator.register_goal(spec)

        self._iteration = 0
        self._last_market_data: Dict[str, Any] = {}
        self._last_signals: Dict[str, Any] = {}
        self._last_portfolio: Dict[str, Any] = {}
        self._last_risk: Dict[str, Any] = {}

    def run_heartbeat(self) -> Dict[str, Any]:
        """Execute one full heartbeat cycle."""
        cycle = self._iteration
        logger.info("━━━ Heartbeat #%d ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", cycle)

        pipeline_start = time.perf_counter()

        # ── Memory: begin cycle ───────────────────────────────────────────────
        self.memory.begin_cycle(cycle)
        self.memory.set_working("cycle", cycle)

        # ── Goal Architecture: evaluate current goal state ───────────────────
        goal_decision = self.goals.step(
            metrics={},  # populated later with system_metrics; initial step uses defaults
            system_state={"health": 1.0},
            cycle=cycle,
        )
        logger.info(
            "[goals] approved=%s score=%.3f tracking_err=%.3f subtasks=%d",
            goal_decision.approved, goal_decision.composite_score,
            goal_decision.tracking_error, len(goal_decision.subtasks),
        )

        # ── Start distributed trace for this heartbeat ────────────────────────
        root_ctx = self.tracer.start_trace(operation="heartbeat", cycle=cycle)
        self.memory.set_working("trace_id", root_ctx.trace_id)

        # ── Step 1: Data Ingestion ─────────────────────────────────────────────
        logger.info("[1/5] Fetching crypto market data (Binance + CoinGecko)…")
        ingest_out, ingest_ctx = self.tracer.execute_with_tracing(
            self.ingestion,
            NodeInput(
                action="fetch_market_data",
                parameters={"interval": "1d", "limit": 90},
                context={"goal": GOAL, "iteration": cycle},
            ),
            parent_ctx=root_ctx,
        )

        if ingest_out.success and ingest_out.result:
            market_data = ingest_out.result
            self._last_market_data = market_data
            fg = market_data.get("_fear_greed", {})
            if fg:
                logger.info("    Fear/Greed: %d (%s)", fg.get("current_value", 0), fg.get("current_label", "?"))
            defi = market_data.get("_defi_tvl", {})
            if defi:
                total_tvl = defi.get("total_tvl", 0)
                logger.info("    DeFi TVL: $%s (top 20 protocols)", f"{total_tvl:,.0f}")
        else:
            logger.warning("Data ingestion failed, using cached data: %s", ingest_out.errors)
            market_data = self._last_market_data

        valid_count = len([v for k, v in market_data.items() if not k.startswith("_") and v])
        logger.info("    → %d/%d pairs fetched (%.1fms)",
                    valid_count, len([k for k in market_data if not k.startswith("_")]),
                    ingest_out.metrics.get("latency_ms", 0))

        # Record cost events for API providers
        if ingest_out.success:
            self.state_store.record_cost(
                node_id=self.ingestion.get_state().node_id,
                provider="binance",
                call_type="klines",
                duration_ms=ingest_out.metrics.get("latency_ms", 0),
                cycle=cycle,
            )
            if market_data.get("_fear_greed"):
                self.state_store.record_cost(
                    node_id=self.ingestion.get_state().node_id,
                    provider="alternative.me",
                    call_type="fng",
                    duration_ms=10.0,
                    cycle=cycle,
                )
            if market_data.get("_defi_tvl"):
                self.state_store.record_cost(
                    node_id=self.ingestion.get_state().node_id,
                    provider="llama.fi",
                    call_type="protocols",
                    duration_ms=20.0,
                    cycle=cycle,
                )

        # Store market snapshot in working memory
        self.memory.set_working("market_data_keys", list(market_data.keys()))
        self.memory.set_working("valid_pairs", valid_count)

        # ── Step 1b: Self-supervised evaluation of last cycle's predictions ───
        if cycle > 0 and self._last_signals:
            outcomes = self.feedback.evaluate_predictions(
                # Build a simplified signals dict with just price
                {
                    ticker: {"price": data["close"][-1] if data and data.get("close") else None}
                    for ticker, data in market_data.items()
                    if data
                },
                cycle=cycle,
            )
            if outcomes:
                hit_rate = sum(1 for o in outcomes if o["was_correct"]) / len(outcomes)
                logger.info(
                    "    → Self-eval: %d predictions, hit_rate=%.0f%%",
                    len(outcomes), hit_rate * 100,
                )

        # ── Step 1c: Cleaner nodes health check ──────────────────────────────
        logger.info("[1c] Running cleaner nodes…")
        lint_out, _ = self.tracer.execute_with_tracing(
            self.lint,
            NodeInput(action="lint_market_data", parameters={"market_data": market_data}, context={"cycle": cycle}),
            parent_ctx=root_ctx,
        )
        integrity_out, _ = self.tracer.execute_with_tracing(
            self.integrity,
            NodeInput(action="check_data_integrity", parameters={"market_data": market_data}, context={"cycle": cycle}),
            parent_ctx=root_ctx,
        )

        if lint_out.success and lint_out.result:
            lr = lint_out.result
            logger.info(
                "    Lint: %d pairs checked, %d issues, clean=%s",
                lr.get("pairs_checked", 0), lr.get("issues_found", 0), lr.get("clean", True)
            )
        if integrity_out.success and integrity_out.result:
            ir = integrity_out.result
            logger.info(
                "    Integrity: dq=%.2f, fresh=%d/%d, cov=%s",
                ir.get("data_quality_score", 1.0),
                ir.get("fresh_pairs", 0), ir.get("pairs_checked", 0),
                "OK" if ir.get("coverage_ok", True) else "WARN"
            )

        # Sync cleaner issues to StateStore
        if lint_out.success and lint_out.result:
            for issue in lint_out.result.get("active_issues", []):
                self.state_store.open_issue(
                    issue_id=issue.get("issue_id", f"lint_{cycle}"),
                    detector="LintNode",
                    severity=issue.get("severity", "warning"),
                    description=issue.get("description", "Lint issue"),
                    context=issue.get("context", {}),
                    cycle=cycle,
                )

        if integrity_out.success and integrity_out.result:
            for issue in integrity_out.result.get("active_issues", []):
                self.state_store.open_issue(
                    issue_id=issue.get("issue_id", f"integrity_{cycle}"),
                    detector="DataIntegrityNode",
                    severity=issue.get("severity", "warning"),
                    description=issue.get("description", "Integrity issue"),
                    context=issue.get("context", {}),
                    cycle=cycle,
                )

        # ── Step 1d: Property tests on previous cycle's outputs (if available) ────
        if cycle > 0 and self._last_signals and self._last_portfolio and self._last_risk:
            prop_out, _ = self.tracer.execute_with_tracing(
                self.property_tests,
                NodeInput(
                    action="run_property_tests",
                    parameters={
                        "signals": self._last_signals,
                        "portfolio": self._last_portfolio,
                        "risk": self._last_risk,
                    },
                    context={"cycle": cycle},
                ),
                parent_ctx=root_ctx,
            )
            if prop_out.success and prop_out.result:
                pr = prop_out.result
                violations = pr.get("violations", 0)
                logger.info(
                    "    Props: %d tested, %d violations%s",
                    pr.get("properties_tested", 0),
                    violations,
                    " ✓" if violations == 0 else " ✗",
                )

        # ── Step 2: Signal Generation ─────────────────────────────────────────
        logger.info("[2/5] Computing trading signals…")
        sig_out, _ = self.tracer.execute_with_tracing(
            self.signals,
            NodeInput(
                action="compute_signals",
                parameters={"market_data": market_data},
                context={"goal": GOAL, "iteration": cycle},
            ),
            parent_ctx=root_ctx,
        )

        if sig_out.success and sig_out.result:
            signals = sig_out.result
            self._last_signals = signals
        else:
            logger.warning("Signal generation failed: %s", sig_out.errors)
            signals = self._last_signals

        # Store predictions for next cycle's self-evaluation
        self.feedback.record_cycle_signals(signals, cycle)
        self.memory.set_working("signals", {t: s.get("composite") for t, s in signals.items()})

        logger.info("    → %d signals | cov=%.0f%% | indicators=%d (%.1fms)",
                    len(signals),
                    sig_out.metrics.get("signal_coverage", 0) * 100,
                    int(sig_out.metrics.get("indicator_count", 1)),
                    sig_out.metrics.get("latency_ms", 0))

        # Store top signals episode
        top_signals = sorted(
            [(t, s.get("composite", 0)) for t, s in signals.items()],
            key=lambda x: -abs(x[1])
        )[:5]
        self.memory.store_episode(
            event_type="top_signals",
            content={"cycle": cycle, "signals": top_signals},
            tags=["signals"] + [t.replace("USDT", "").lower() for t, _ in top_signals],
            importance=0.7,
            cycle=cycle,
        )

        # ── Step 3: Portfolio Construction ─────────────────────────────────────
        logger.info("[3/5] Constructing portfolio…")
        strat_out, _ = self.tracer.execute_with_tracing(
            self.strategy,
            NodeInput(
                action="construct_portfolio",
                parameters={"signals": signals, "market_data": market_data},
                context={"goal": GOAL, "iteration": cycle},
            ),
            parent_ctx=root_ctx,
        )

        if strat_out.success and strat_out.result:
            portfolio = strat_out.result
            self._last_portfolio = portfolio
        else:
            logger.warning("Strategy failed: %s", strat_out.errors)
            portfolio = self._last_portfolio

        bt = portfolio.get("backtest", {})
        sharpe = bt.get("sharpe", 0.0)
        logger.info("    → %d positions | method=%s | Sharpe=%.3f | MaxDD=%.2f%% (%.1fms)",
                    portfolio.get("positions", 0),
                    portfolio.get("method", "?"),
                    sharpe,
                    bt.get("max_drawdown", 0.0) * 100,
                    strat_out.metrics.get("latency_ms", 0))

        # Store portfolio episode
        self.memory.store_episode(
            event_type="portfolio_decision",
            content={
                "cycle": cycle,
                "method": portfolio.get("method"),
                "positions": portfolio.get("positions", 0),
                "sharpe": sharpe,
                "weights": portfolio.get("weights", {}),
            },
            tags=["portfolio", portfolio.get("method", "equal")],
            importance=0.75,
            cycle=cycle,
        )

        # ── Step 4: Risk Management ───────────────────────────────────────────
        logger.info("[4/5] Checking risk limits…")
        risk_out, _ = self.tracer.execute_with_tracing(
            self.risk,
            NodeInput(
                action="check_risk_limits",
                parameters={"portfolio": portfolio, "market_data": market_data},
                context={"goal": GOAL, "iteration": cycle},
            ),
            parent_ctx=root_ctx,
        )

        if risk_out.success and risk_out.result:
            risk_result = risk_out.result
            self._last_risk = risk_result
        else:
            logger.warning("Risk check failed: %s", risk_out.errors)
            risk_result = self._last_risk

        logger.info("    → VaR(95)=%.2f%% | limits=%s | violations=%d (%.1fms)",
                    risk_result.get("portfolio_var_95", 0.0) * 100,
                    "PASSED" if risk_result.get("passed", True) else "VIOLATED",
                    len(risk_result.get("violations", [])),
                    risk_out.metrics.get("latency_ms", 0))

        # ── Step 5: Reporting ─────────────────────────────────────────────────
        logger.info("[5/5] Generating report…")
        combined_risk = {
            **risk_result,
            **risk_out.metrics,
            "portfolio_var_95": risk_result.get("portfolio_var_95", 0.0),
            "portfolio_cvar_95": risk_result.get("portfolio_cvar_95", 0.0),
        }
        report_out, _ = self.tracer.execute_with_tracing(
            self.reporting,
            NodeInput(
                action="generate_report",
                parameters={
                    "market_data": market_data,
                    "signals": signals,
                    "portfolio": portfolio,
                    "risk": combined_risk,
                },
                context={"goal": GOAL, "iteration": cycle},
            ),
            parent_ctx=root_ctx,
        )

        if report_out.success and report_out.result:
            report_text = report_out.result.get("report", "")
            print("\n" + report_text)

        pipeline_ms = (time.perf_counter() - pipeline_start) * 1000

        # ── Collect system metrics ─────────────────────────────────────────────
        system_metrics: Dict[str, float] = {
            "coverage_rate": ingest_out.metrics.get("coverage_rate", 0.0),
            "signal_coverage": sig_out.metrics.get("signal_coverage", 0.0),
            "sharpe_ratio": max(0.0, sharpe),
            "completeness_score": report_out.metrics.get("completeness_score", 0.0),
            "error_rate": self._pipeline_error_rate(
                [ingest_out, sig_out, strat_out, risk_out, report_out]
            ),
            "indicator_count": sig_out.metrics.get("indicator_count", 1.0),
            "pipeline_latency_ms": pipeline_ms,
            "positions": float(portfolio.get("positions", 0)),
            "portfolio_var_95": risk_result.get("portfolio_var_95", 0.0),
        }

        # ── Evaluate + record ─────────────────────────────────────────────────
        node_states = self.orchestrator.registry.all_states()
        self.orchestrator.evaluator.record(GOAL, cycle, node_states, system_metrics)
        score = self.orchestrator.evaluator.score(GOAL, system_metrics)

        # Record cycle score for MetricsCollector convergence tracking
        self.metrics.record_cycle_score(score)

        # ── Convergence monitoring ─────────────────────────────────────────────
        conv_out, _ = self.tracer.execute_with_tracing(
            self.convergence,
            NodeInput(
                action="monitor_convergence",
                parameters={"score": score, "system_metrics": system_metrics},
                context={"cycle": cycle},
            ),
            parent_ctx=root_ctx,
        )
        if conv_out.success and conv_out.result:
            cr = conv_out.result
            logger.info(
                "    Convergence: %s | EMA=%.4f | slope=%.5f | sparkline: %s",
                cr.get("trend", "?"),
                cr.get("ema_score", 0),
                cr.get("slope", 0),
                cr.get("sparkline", "")[:20],
            )

        # ── Invariant observation ──────────────────────────────────────────────
        inv_obs_out, _ = self.tracer.execute_with_tracing(
            self.invariants,
            NodeInput(
                action="observe",
                parameters={"metrics": system_metrics},
                context={"cycle": cycle},
            ),
            parent_ctx=root_ctx,
        )
        # Periodically discover invariants (every 3 cycles after observation window)
        if cycle >= 3 and cycle % 3 == 0:
            inv_disc_out, _ = self.tracer.execute_with_tracing(
                self.invariants,
                NodeInput(action="discover_invariants", parameters={}, context={"cycle": cycle}),
                parent_ctx=root_ctx,
            )
            if inv_disc_out.success and inv_disc_out.result:
                confirmed = inv_disc_out.result.get("confirmed_invariants", [])
                if confirmed:
                    logger.info("    Invariants: %d confirmed", len(confirmed))

        # ── Dashboard health check ─────────────────────────────────────────────
        dash_out, _ = self.tracer.execute_with_tracing(
            self.dashboard,
            NodeInput(
                action="api_health_check",
                parameters={},
                context={"cycle": cycle},
            ),
            parent_ctx=root_ctx,
        )
        if dash_out.success and dash_out.result:
            dr = dash_out.result
            checks_ok = len(dr.get("checks", []))
            api_issues = len([i for i in dr.get("issues", []) if "endpoint" in i])
            cov = dr.get("coverage", {})
            logger.info(
                "    Dashboard: %d endpoints OK, %d unreachable | "
                "coverage=%.0f%% | freshness=%.2f",
                checks_ok,
                api_issues,
                dash_out.metrics.get("coverage_score", 0) * 100,
                dash_out.metrics.get("freshness_score", 0),
            )
            # Sync API issues to StateStore
            for iss in dr.get("issues", []):
                if "endpoint" in iss:
                    self.state_store.open_issue(
                        issue_id=f"dashboard_api_{iss['endpoint'].replace('/', '_')}_{cycle}",
                        detector="DashboardNode",
                        severity=iss.get("severity", "medium"),
                        description=f"API endpoint unreachable: {iss['endpoint']}",
                        context={"endpoint": iss["endpoint"], "error": iss.get("error", "")},
                        cycle=cycle,
                    )

        # ── Memory v2: regime update from Sharpe as market indicator ─────────
        regime_obs = system_metrics.get("sharpe_ratio", 0.0)
        regime_state = self.memory.update_regime(regime_obs)
        self.memory.set_working("regime", regime_state.label)
        logger.info(
            "[memory_v2] regime=%s cp_prob=%.2f mean=%.3f",
            regime_state.label, regime_state.changepoint_prob, regime_state.mean_estimate,
        )

        # ── Adversarial pressure ──────────────────────────────────────────────
        # Ring 1 uses signals as variant outputs (single variant for now)
        variant_signals = {"primary": {t: float(s.get("composite", 0)) for t, s in signals.items()}}
        adv_report = self.adversarial.run(
            cycle=cycle,
            variant_outputs=variant_signals,
            current_signals={t: float(s.get("composite", 0)) for t, s in signals.items()},
            strategy_params={"method": portfolio.get("method", "equal"), "positions": portfolio.get("positions", 0)},
        )
        if adv_report.ring1_result and adv_report.ring1_result.flagged:
            logger.warning(
                "[adversarial] Ring 1 disagreement flagged — max_dist=%.3f",
                adv_report.ring1_result.max_disagreement,
            )
        if adv_report.ring2_scenarios:
            logger.info(
                "[adversarial] Ring 2 generated %d adversarial scenarios (top severity=%.2f)",
                len(adv_report.ring2_scenarios),
                max(s.severity for s in adv_report.ring2_scenarios),
            )
        # Persist adversarial result
        self.state_store.record_adversarial_result(
            cycle=cycle,
            ring=1,
            flagged=adv_report.ring1_result.flagged if adv_report.ring1_result else False,
            max_disagreement=adv_report.ring1_result.max_disagreement if adv_report.ring1_result else 0.0,
            scenario_count=len(adv_report.ring2_scenarios),
            failure_cases=adv_report.failure_cases,
        )

        # ── Alignment check before improvement ───────────────────────────────
        node_metrics_map = {
            node.get_state().name: node.evaluate()
            for node in [self.ingestion, self.signals, self.strategy,
                         self.risk, self.reporting]
        }
        portfolio_weights = portfolio.get("weights", {})
        alignment_decision = self.alignment.check_improvement_cycle(
            node_metrics_map=node_metrics_map,
            system_metrics=system_metrics,
            portfolio=portfolio_weights,
            cycle=cycle,
        )
        # Persist alignment decision
        self.state_store.record_alignment_decision(
            cycle=cycle,
            approved=alignment_decision.approved,
            violations=alignment_decision.violations,
            pareto_ranks={k: int(v) for k, v in alignment_decision.pareto_ranks.items()},
            adjustments=alignment_decision.adjustments,
            vcg_payments=alignment_decision.vcg_payments,
            goodhart_warning=alignment_decision.goodhart_warning,
        )
        if not alignment_decision.approved:
            logger.warning(
                "[alignment] BLOCKED improvement: violations=%s",
                alignment_decision.violations,
            )
        elif alignment_decision.goodhart_warning:
            logger.warning("[alignment] Goodhart divergence detected — improvement proceeding with caution")
        else:
            logger.info("[alignment] Approved. Pareto ranks: %s", dict(list(alignment_decision.pareto_ranks.items())[:3]))

        # ── Goal tracking: update with real system_metrics ───────────────────
        goal_decision_final = self.goals.step(
            metrics=system_metrics,
            system_state={
                "health": sum(n.get_state().health for n in [self.ingestion, self.signals, self.strategy]) / 3,
                "error_rate": system_metrics.get("error_rate", 0.0),
                "sharpe_ratio": system_metrics.get("sharpe_ratio", 0.0),
            },
            cycle=cycle,
        )
        self.state_store.record_goal_tracking(
            cycle=cycle,
            approved=goal_decision_final.approved,
            composite_score=goal_decision_final.composite_score,
            scorecard=goal_decision_final.scorecard,
            nash_weights=goal_decision_final.nash_weights,
            tracking_error=goal_decision_final.tracking_error,
            control_action=goal_decision_final.control_action,
            subtasks=[{"name": t.name, "assigned_to": t.assigned_to} for t in goal_decision_final.subtasks],
            violations=[v.constraint_name for v in goal_decision_final.constraint_violations],
        )

        # ── Self-improvement pass (only if alignment approves) ────────────────
        fb_summary = self.feedback.get_improvement_feedback()
        improved_nodes = (
            self._run_improvement_pass(system_metrics, fb_summary, cycle)
            if alignment_decision.approved
            else []
        )

        # ── End root trace ────────────────────────────────────────────────────
        self.tracer.end_span(root_ctx.span_id, status="ok", metadata={
            "score": score,
            "pipeline_ms": pipeline_ms,
            "improved_nodes": len(improved_nodes),
        })

        # ── Store cycle summary in episodic memory ────────────────────────────
        self.memory.end_cycle(cycle, {
            "score": score,
            "system_metrics": system_metrics,
            "improved_nodes": improved_nodes,
            "pipeline_ms": pipeline_ms,
        })

        # ── Print iteration summary ───────────────────────────────────────────
        mem_summary = self.memory.summary()
        mem_summary["regime"] = self.memory.get_working("regime", "unknown")
        self._print_iteration_summary(cycle, system_metrics, score, improved_nodes,
                                      pipeline_ms, mem_summary)

        self._iteration += 1
        return {
            "iteration": cycle,
            "score": score,
            "system_metrics": system_metrics,
            "improved_nodes": improved_nodes,
        }

    def _run_improvement_pass(
        self,
        system_metrics: Dict[str, float],
        feedback_summary: Dict[str, Any],
        iteration: int,
    ) -> List[str]:
        """Evaluate each node and trigger Improve() where needed."""
        improved: List[str] = []
        nodes_info = [
            (self.ingestion,      "DataIngestionNode"),
            (self.signals,        "SignalGenerationNode"),
            (self.strategy,       "StrategyNode"),
            (self.risk,           "RiskManagementNode"),
            (self.reporting,      "ReportingNode"),
            (self.lint,           "LintNode"),
            (self.integrity,      "DataIntegrityNode"),
            (self.verification,   "VerificationNode"),
            (self.property_tests, "PropertyTestNode"),
            (self.dashboard,      "DashboardNode"),
            # Note: InvariantDiscoveryNode and ConvergenceMonitorNode don't self-improve
        ]

        # Run system analyzer to get recommendations
        analyzer_recs = self.analyzer.analyze(cycle=iteration)
        # Build per-node recommendation context
        rec_by_node: Dict[str, Dict] = {}
        for rec in analyzer_recs:
            if rec.target_node not in rec_by_node:
                rec_by_node[rec.target_node] = {}
            rec_by_node[rec.target_node].update(rec.as_feedback_dict())

        # Retrieve relevant semantic memories for context
        memory_context = self.memory.retrieve_semantic(limit=3)

        for node, name in nodes_info:
            node_metrics = node.evaluate()
            negative_feedback = name in feedback_summary.get("negative_feedback_nodes", [])

            feedback: Dict[str, Any] = {
                "iteration": iteration,
                "goal": GOAL,
                "system_metrics": system_metrics,
                "node_metrics": node_metrics,
                "improve_latency": system_metrics.get("pipeline_latency_ms", 0) > 15000,
                "improve_accuracy": system_metrics.get("error_rate", 0) > 0.1,
                "has_negative_feedback": negative_feedback,
                "human_feedback_texts": feedback_summary.get("human_feedback_texts", []),
                "self_supervised_hit_rate": feedback_summary.get("self_supervised_hit_rate"),
                "memory_context": [
                    {"concept": m.concept, "content": m.content}
                    for m in memory_context
                ],
                # Merge analyzer recommendations
                **rec_by_node.get(name, {}),
            }

            try:
                state_before = node.get_state()
                state_before_version = state_before.version

                # Pre-improvement snapshot for verification
                snapshot = self.verification.snapshot_node(node)

                changed = node.improve(feedback)
                if changed:
                    new_state = node.get_state()

                    # Post-improvement verification
                    verify_result = self.verification.verify_improvement(
                        node=node,
                        node_name=name,
                        before_metrics=node_metrics,
                        after_metrics=new_state.metrics,
                        snapshot=snapshot,
                        cycle=iteration,
                    )

                    if verify_result.get("rolled_back"):
                        logger.warning(
                            "⚠ %s improvement rolled back: %s",
                            name, verify_result.get("details", "regression detected"),
                        )
                        # Don't record this as an improvement since it was reverted
                    else:
                        improved.append(f"{name} → v{new_state.version}")
                        logger.info("✓ %s improved to v%s [verification: PASS]", name, new_state.version)
                        # Store improvement episode
                        self.memory.store_episode(
                            event_type="node_improved",
                            content={
                                "node": name,
                                "new_version": new_state.version,
                                "iteration": iteration,
                                "triggered_by": "feedback" if negative_feedback else "metrics",
                                "verification": "pass",
                            },
                            tags=["improvement", name.lower()],
                            importance=0.9,
                            cycle=iteration,
                        )
                        # Record improvement in StateStore
                        self.state_store.record_improvement(
                            node_id=new_state.node_id,
                            node_name=name,
                            from_version=state_before_version,
                            to_version=new_state.version,
                            before_metrics=node_metrics,
                            after_metrics=new_state.metrics,
                            triggered_by="feedback" if negative_feedback else "metrics",
                            cycle=iteration,
                        )
                        # Update StateStore registry with new version
                        self.state_store.upsert_node(
                            node_id=new_state.node_id,
                            name=name,
                            version=new_state.version,
                            capabilities=new_state.capabilities,
                            health=new_state.health,
                        )
            except Exception as exc:
                logger.error("improve() error for %s: %s", name, exc)

        return improved

    def _pipeline_error_rate(self, outputs) -> float:
        failures = sum(1 for o in outputs if not o.success)
        return failures / len(outputs) if outputs else 0.0

    def _print_iteration_summary(
        self,
        iteration: int,
        metrics: Dict[str, float],
        score: float,
        improved: List[str],
        elapsed_ms: float,
        mem_summary: Dict[str, Any],
    ) -> None:
        improved_str = ", ".join(improved) if improved else "—"
        regime = mem_summary.get("regime", "unknown")
        print(
            f"\n{'─'*68}\n"
            f"  Heartbeat #{iteration:>3} │ Score: {score:.4f} │ {elapsed_ms/1000:.1f}s\n"
            f"  Coverage: {metrics.get('coverage_rate',0):.0%}"
            f"  Signals: {metrics.get('signal_coverage',0):.0%}"
            f"  Sharpe: {metrics.get('sharpe_ratio',0):+.3f}"
            f"  Indicators: {int(metrics.get('indicator_count',1))}"
            f"  Errors: {metrics.get('error_rate',0):.0%}\n"
            f"  Memory: {mem_summary.get('episodic_count',0)} episodes │ "
            f"{mem_summary.get('semantic_count',0)} patterns learned │ Regime: {regime}\n"
            f"  Improved: {improved_str}\n"
            f"{'─'*68}\n"
        )

    def print_node_health(self) -> None:
        print("\nNode Health Status:")
        print(f"  {'Node':<28} {'Ver':>5}  {'Health':>7}  Key Metrics")
        print("  " + "─" * 70)
        for node in [self.ingestion, self.signals, self.strategy,
                     self.risk, self.reporting, self.lint, self.integrity,
                     self.verification, self.property_tests, self.invariants, self.convergence]:
            state = node.get_state()
            m = state.metrics
            parts = []
            for k, label in [
                ("coverage_rate", "cov"),
                ("signal_coverage", "sig"),
                ("sharpe_ratio", "sharpe"),
                ("completeness_score", "complete"),
                ("error_rate", "err"),
                ("indicator_count", "indicators"),
            ]:
                if k in m:
                    v = m[k]
                    if k in ("coverage_rate", "signal_coverage",
                             "completeness_score", "error_rate"):
                        parts.append(f"{label}={v:.0%}")
                    elif k == "indicator_count":
                        parts.append(f"{label}={int(v)}")
                    else:
                        parts.append(f"{label}={v:+.2f}")
            metrics_str = "  ".join(parts) if parts else "(no metrics)"
            print(
                f"  {state.name:<28} {state.version:>5}  {state.health:>5.0%}  {metrics_str}"
            )
        print()

    def print_verification_summary(self) -> None:
        """Print verification + convergence + invariant summary."""
        print("\nVerification & Convergence Summary:")

        # Verification stats
        v = self.verification
        total = v._pass_count + v._fail_count
        pass_rate = v._pass_count / max(1, total)
        print(f"  VerificationNode: {v._pass_count} pass / {v._fail_count} fail / {v._rollback_count} rollbacks (pass_rate={pass_rate:.0%})")

        # Convergence stats
        c = self.convergence
        if c._scores:
            print(f"  ConvergenceMonitor: {len(c._scores)} cycles | EMA={c._score_emas[-1]:.4f} | trend={c._ascii_sparkline(c._scores)[:20]}")
            if c._oscillation_count > 0:
                print(f"    ⚠ Oscillations detected: {c._oscillation_count}")

        # Invariants
        inv = self.invariants
        print(f"  InvariantDiscovery: {len(inv._confirmed_invariants)} confirmed | {len(inv._proposed_invariants)} proposed | {inv._violation_count} violations")
        if inv._confirmed_invariants:
            for inv_item in inv._confirmed_invariants[:3]:
                print(f"    ✓ {inv_item.get('description', '?')[:70]}")

        # Property tests
        p = self.property_tests
        active = p._active_issues()
        print(f"  PropertyTestNode: v{p._version} | {len(active)} active violations")
        print()

    def print_memory_status(self) -> None:
        summary = self.memory.summary()
        print("\nMemory Kernel Status:")
        print(f"  Cycle           : {summary['current_cycle']}")
        print(f"  Episodic memories: {summary['episodic_count']}")
        print(f"  Semantic patterns: {summary['semantic_count']}")
        print(f"  Working memory   : {', '.join(summary['working_memory_keys']) or '(empty)'}")
        if summary.get("top_semantic_concepts"):
            print("  Top learned patterns:")
            for c in summary["top_semantic_concepts"]:
                print(f"    [{c['confidence']:.2f}] {c['concept']}")
        print()

    def print_observability_summary(self) -> None:
        """Print concise observability dashboard after each heartbeat."""
        print(self.metrics.format_dashboard())

        # Show recent trace waterfall for last heartbeat
        recent = self.state_store.get_recent_traces(limit=1)
        if recent:
            last_trace_id = recent[0]["trace_id"]
            print("\n  Last heartbeat trace:")
            print(self.tracer.format_waterfall(last_trace_id))
        print()

    def accept_feedback(self, cycle: int) -> None:
        """Prompt the user for optional feedback (non-blocking, 3s window)."""
        print(
            "\n  Feedback (optional — type and press Enter within 3s, "
            "or wait to continue):"
        )
        fb = self.feedback.try_read_cli_feedback(timeout_sec=3.0, cycle=cycle)
        if fb:
            print(f"  Feedback recorded: {fb[:60]}")

    def print_evaluation_report(self) -> None:
        print(self.orchestrator.evaluator.report(GOAL))


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Vectora — Omega crypto quantitative research heartbeat"
    )
    parser.add_argument(
        "--heartbeat", type=int, default=120,
        help="Seconds between heartbeats (default: 120)"
    )
    parser.add_argument(
        "--iterations", type=int, default=0,
        help="Max iterations (0 = run forever)"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run exactly one heartbeat then exit"
    )
    parser.add_argument(
        "--feedback", action="store_true",
        help="Prompt for human feedback between heartbeats"
    )
    args = parser.parse_args()

    print("\n" + "═" * 68)
    print("  VECTORA — Omega Crypto Quantitative Research System")
    print("  Data: Binance (OHLCV) + CoinGecko (market caps) — no API key")
    print("  Memory: episodic + semantic + working (SQLite)")
    print("  Feedback: self-supervised + human CLI")
    print("  Observability: StateStore + Tracer + MetricsCollector + SystemAnalyzer")
    print(f"  Heartbeat: {args.heartbeat}s | Pairs: BTC,ETH,SOL,BNB,XRP,ADA,DOT,AVAX,LINK,MATIC")
    print("  Ctrl+C to stop")
    print("═" * 68 + "\n")
    print("  [Future: SentimentNode via Bittensor SN13 / Macrocosmos `dv` CLI]")
    print("  [Architecture is pluggable — add SentimentIngestionNode for social signals]\n")

    system = VectoraSystem()
    iteration_count = 0

    try:
        while not _shutdown:
            result = system.run_heartbeat()
            iteration_count += 1

            system.print_node_health()
            system.print_memory_status()
            system.print_observability_summary()
            system.print_verification_summary()

            if args.once or (args.iterations > 0 and iteration_count >= args.iterations):
                break

            if _shutdown:
                break

            if args.feedback:
                system.accept_feedback(cycle=result["iteration"])

            logger.info("Next heartbeat in %ds… (Ctrl+C to stop)", args.heartbeat)
            for _ in range(args.heartbeat):
                if _shutdown:
                    break
                time.sleep(1)

    except KeyboardInterrupt:
        pass

    # Final report
    print("\n" + "═" * 68)
    print("  FINAL EVALUATION REPORT")
    print("═" * 68)
    system.print_node_health()
    system.print_memory_status()
    system.print_evaluation_report()

    # Feedback summary
    fb_summary = system.feedback.get_feedback_history_summary()
    print("\nFeedback History:\n" + fb_summary)
    print(f"\nCompleted {iteration_count} heartbeat(s). Goodbye.\n")


if __name__ == "__main__":
    main()
