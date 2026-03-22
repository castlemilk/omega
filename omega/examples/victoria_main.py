"""
omega.examples.victoria_main
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Victoria — Crypto Quantitative Research System
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
    python -m omega.examples.victoria_main
    python -m omega.examples.victoria_main --heartbeat 60 --iterations 5
    python -m omega.examples.victoria_main --once
"""

import argparse
import signal
import time
from typing import Any

from omega.adversarial.debate_gate import DebateGate, SignalContext
from omega.bridge.adversarial_client import AdversarialServiceClient, AdversarialServiceError
from omega.bridge.improvement_client import ImprovementServiceClient, ImprovementServiceError
from omega.bridge.memory_client import MemoryServiceClient, MemoryServiceError
from omega.core.adversarial import AdversarialPressure
from omega.core.alignment import AlignmentLayer
from omega.core.analyzer import SystemAnalyzer
from omega.core.autonomy import AutonomyLevel
from omega.core.challenge_registry import ChallengeRegistry
from omega.core.config import OmegaConfig
from omega.core.evaluator import GoalSpec
from omega.core.feedback import FeedbackEngine
from omega.core.goals import GoalArchitecture
from omega.core.logging import configure_logging, get_logger
from omega.core.memory_v2 import MemoryKernelV2
from omega.core.metrics import MetricsCollector
from omega.core.metrics_exporter import MetricsExporter
from omega.core.node import NodeInput
from omega.core.orchestrator import Orchestrator
from omega.core.state_store import StateStore
from omega.core.tracing import create_tracer
from omega.core.verification_gates import (
    ConvergenceGate,
    InvariantGate,
    PropertyGate,
    RegressionGate,
    VerificationGateSystem,
)
from omega.eval.run_composite_backtest import walk_forward_backtest
from omega.nodes.devils_advocate import DevilsAdvocateNode
from omega.nodes.victoria import (
    DashboardNode,
    DataIngestionNode,
    DataIntegrityNode,
    LintNode,
    ReportingNode,
    RiskManagementNode,
    SignalGenerationNode,
    StrategyNode,
)
from omega.nodes.victoria.dynamic_weights import DynamicWeightAllocator
from omega.nodes.victoria.signal_research import SignalResearchNode
from omega.nodes.victoria.verification import (
    ConvergenceMonitorNode,
    InvariantDiscoveryNode,
    PropertyTestNode,
    VerificationNode,
)

# ─── Config + Logging ──────────────────────────────────────────────────────────

_cfg = OmegaConfig.load()
configure_logging(
    level=_cfg.monitoring.log_level,
    json_output=_cfg.monitoring.json_logs,
    log_file=_cfg.monitoring.log_file,
)
logger = get_logger("omega.victoria")

# ─── Signal key names (used for IC analysis and dynamic weighting) ─────────────
_SIGNAL_KEYS: list[str] = [
    "sma_crossover",
    "rsi_signal",
    "macd_crossover",
    "bb_signal",
    "zscore_signal",
    "volume_signal",
    "btc_beta_signal",
]
_MAX_SIGNAL_HISTORY = 50  # cycles of signal history to retain

# ─── Constants ─────────────────────────────────────────────────────────────────

GOAL = "victoria_crypto_research"
DB_PATH = _cfg.database.orchestrator_db_path
MEMORY_DB_PATH = _cfg.database.memory_db_path
STATE_DB_PATH = _cfg.database.state_db_path
HEALTH_THRESHOLD = _cfg.alignment.health_threshold

# ─── Shutdown flag ─────────────────────────────────────────────────────────────

_shutdown = False


def _handle_sigint(sig, frame):
    global _shutdown
    logger.info("Shutting down gracefully (SIGINT)")
    _shutdown = True


signal.signal(signal.SIGINT, _handle_sigint)


# ─── Victoria System ────────────────────────────────────────────────────────────


class VictoriaSystem:
    """
    Full Victoria pipeline with memory, feedback, and self-improvement.

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
        self.signals = SignalGenerationNode()
        self.strategy = StrategyNode()
        self.risk = RiskManagementNode()
        self.reporting = ReportingNode()
        self.lint = LintNode()
        self.integrity = DataIntegrityNode()
        self.verification = VerificationNode()
        self.property_tests = PropertyTestNode()
        self.invariants = InvariantDiscoveryNode()
        self.convergence = ConvergenceMonitorNode()
        # DashboardNode — passed the live StateStore so it can audit metric coverage
        self.dashboard = DashboardNode(
            state_store=self.state_store,
            api_base_url="http://localhost:8080",
        )

        # ── Orchestrator (health tracking, evaluation) ───────────────────────
        self.orchestrator = Orchestrator(name="victoria", db_path=DB_PATH)
        for node in [
            self.ingestion,
            self.signals,
            self.strategy,
            self.risk,
            self.reporting,
            self.lint,
            self.integrity,
        ]:
            self.orchestrator.register_node(node)
        for node in [self.verification, self.property_tests, self.invariants, self.convergence]:
            self.orchestrator.register_node(node)
        self.orchestrator.register_node(self.dashboard)

        # ── Register all nodes in StateStore ─────────────────────────────────
        for node in [
            self.ingestion,
            self.signals,
            self.strategy,
            self.risk,
            self.reporting,
            self.lint,
            self.integrity,
        ]:
            state = node.get_state()
            self.state_store.upsert_node(
                node_id=state.node_id,
                name=state.name,
                version=state.version,
                capabilities=state.capabilities,
                health=state.health,
            )
            self.state_store.log_activity(
                "node_registered",
                "node",
                state.node_id,
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
            "node_registered",
            "node",
            dash_state.node_id,
            {"name": dash_state.name, "version": dash_state.version},
        )

        # ── Devil's Advocate layer ────────────────────────────────────────────
        self.challenge_registry = ChallengeRegistry(db_path=STATE_DB_PATH)
        seeded = self.challenge_registry.seed_initial_challenges()
        if seeded:
            logger.info("[DA] Seeded %d initial challenges into registry", seeded)

        self._gate_system = VerificationGateSystem()
        self._gate_system.register(
            PropertyGate(
                "node_health_bounded",
                predicate=lambda ctx: all(0.0 <= v <= 1.0 for v in ctx.get("node_healths", [1.0])),
                description="All node health scores must be in [0, 1]",
            )
        )
        self._gate_system.register(
            InvariantGate(
                "sharpe_non_negative",
                invariant=lambda ctx: ctx.get("sharpe_ratio", 0.0) >= -10.0,
                description="Sharpe ratio must be above -10 (sanity bound)",
            )
        )
        self._gate_system.register(
            RegressionGate(
                "sharpe_regression",
                metric="sharpe_ratio",
                direction="maximize",
                threshold_pct=25.0,
            )
        )
        self._gate_system.register(
            ConvergenceGate(
                "system_convergence",
                metric="score",
                window=4,
            )
        )

        self.devils_advocate = DevilsAdvocateNode(
            registry=self.challenge_registry,
            gate_system=self._gate_system,
        )
        self._last_metrics: dict[str, float] = {}

        # ── Signal research + IC-weighted compositing ─────────────────────────
        self.signal_research = SignalResearchNode()
        self.dynamic_weights = DynamicWeightAllocator(signal_names=_SIGNAL_KEYS)
        self.debate_gate = DebateGate()
        # Rolling histories for IC computation (keyed by signal name / ticker)
        self._signal_history: dict[str, list[float]] = {}
        self._price_history: dict[str, list[float]] = {}
        self._ic_values: dict[str, float] = {}  # signal_name → ic at 1d horizon
        self._ic_long_values: dict[str, float] = {}  # signal_name → ic at 5d horizon
        self._last_sharpe: float = 0.0
        # Register signal_research in orchestrator + StateStore
        self.orchestrator.register_node(self.signal_research)
        _sr_state = self.signal_research.get_state()
        self.state_store.upsert_node(
            node_id=_sr_state.node_id,
            name=_sr_state.name,
            version=_sr_state.version,
            capabilities=_sr_state.capabilities,
            health=_sr_state.health,
        )

        # ── Protocol bridge clients — Go server REQUIRED at localhost:8080 ───
        # Fail loudly if server is not reachable; no graceful degradation.
        self.improvement_client = ImprovementServiceClient("http://localhost:8080")
        self.memory_client = MemoryServiceClient("http://localhost:8080")
        self.adversarial_client = AdversarialServiceClient("http://localhost:8080")

        # ── Autonomy level — gates Ring 3 activation ──────────────────────────
        # Starts at PICO; promoted to SUPERVISED after cycle 3 (enough history).
        self._autonomy_level: AutonomyLevel = AutonomyLevel.PICO

        # ── Goal spec ─────────────────────────────────────────────────────────
        spec = (
            GoalSpec(GOAL, description="Victoria crypto quantitative research pipeline")
            .add_metric("coverage_rate", direction="maximize", weight=2.0)
            .add_metric("signal_coverage", direction="maximize", weight=2.0)
            .add_metric("sharpe_ratio", direction="maximize", weight=3.0)
            .add_metric("completeness_score", direction="maximize", weight=1.5)
            .add_metric("error_rate", direction="minimize", weight=2.0)
            .add_metric("indicator_count", direction="maximize", weight=1.0)
        )
        self.orchestrator.register_goal(spec)

        self._iteration = 0
        self._last_market_data: dict[str, Any] = {}
        self._last_signals: dict[str, Any] = {}
        self._last_portfolio: dict[str, Any] = {}
        self._last_risk: dict[str, Any] = {}

        # Metrics exporter — attached via attach_metrics_exporter() when --metrics is used
        self._mex: MetricsExporter | None = None

    def attach_metrics_exporter(self, mex: MetricsExporter) -> None:
        """Attach a MetricsExporter; called from main() when --metrics flag is set."""
        self._mex = mex

    def run_heartbeat(self) -> dict[str, Any]:
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
            goal_decision.approved,
            goal_decision.composite_score,
            goal_decision.tracking_error,
            len(goal_decision.subtasks),
        )

        # ── Start distributed trace for this heartbeat ────────────────────────
        root_ctx = self.tracer.start_trace(operation="heartbeat", cycle=cycle)
        self.memory.set_working("trace_id", root_ctx.trace_id)

        # ── Step 1: Data Ingestion ─────────────────────────────────────────────
        logger.info("[1/5] Fetching crypto market data (Binance + CoinGecko)…")
        ingest_out, _ingest_ctx = self.tracer.execute_with_tracing(
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
                logger.info(
                    "    Fear/Greed: %d (%s)",
                    fg.get("current_value", 0),
                    fg.get("current_label", "?"),
                )
            defi = market_data.get("_defi_tvl", {})
            if defi:
                total_tvl = defi.get("total_tvl", 0)
                logger.info("    DeFi TVL: $%s (top 20 protocols)", f"{total_tvl:,.0f}")
        else:
            logger.warning("Data ingestion failed, using cached data: %s", ingest_out.errors)
            market_data = self._last_market_data

        valid_count = len([v for k, v in market_data.items() if not k.startswith("_") and v])
        logger.info(
            "    → %d/%d pairs fetched (%.1fms)",
            valid_count,
            len([k for k in market_data if not k.startswith("_")]),
            ingest_out.metrics.get("latency_ms", 0),
        )

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
                    len(outcomes),
                    hit_rate * 100,
                )

        # ── Step 1c: Cleaner nodes health check ──────────────────────────────
        logger.info("[1c] Running cleaner nodes…")
        lint_out, _ = self.tracer.execute_with_tracing(
            self.lint,
            NodeInput(
                action="lint_market_data",
                parameters={"market_data": market_data},
                context={"cycle": cycle},
            ),
            parent_ctx=root_ctx,
        )
        integrity_out, _ = self.tracer.execute_with_tracing(
            self.integrity,
            NodeInput(
                action="check_data_integrity",
                parameters={"market_data": market_data},
                context={"cycle": cycle},
            ),
            parent_ctx=root_ctx,
        )

        if lint_out.success and lint_out.result:
            lr = lint_out.result
            logger.info(
                "    Lint: %d pairs checked, %d issues, clean=%s",
                lr.get("pairs_checked", 0),
                lr.get("issues_found", 0),
                lr.get("clean", True),
            )
        if integrity_out.success and integrity_out.result:
            ir = integrity_out.result
            logger.info(
                "    Integrity: dq=%.2f, fresh=%d/%d, cov=%s",
                ir.get("data_quality_score", 1.0),
                ir.get("fresh_pairs", 0),
                ir.get("pairs_checked", 0),
                "OK" if ir.get("coverage_ok", True) else "WARN",
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

        logger.info(
            "    → %d signals | cov=%.0f%% | indicators=%d (%.1fms)",
            len(signals),
            sig_out.metrics.get("signal_coverage", 0) * 100,
            int(sig_out.metrics.get("indicator_count", 1)),
            sig_out.metrics.get("latency_ms", 0),
        )

        # Store top signals episode
        top_signals = sorted(
            [(t, s.get("composite", 0)) for t, s in signals.items()], key=lambda x: -abs(x[1])
        )[:5]
        self.memory.store_episode(
            event_type="top_signals",
            content={"cycle": cycle, "signals": top_signals},
            tags=["signals"] + [t.replace("USDT", "").lower() for t, _ in top_signals],
            importance=0.7,
            cycle=cycle,
        )

        # ── Step 2b: IC analysis — accumulate history, compute IC, update weights ─
        # Cross-ticker average signal value at this cycle
        for _sk in _SIGNAL_KEYS:
            _vals = [
                float(s[_sk])
                for s in signals.values()
                if _sk in s and isinstance(s.get(_sk), (int, float))
            ]
            if _vals:
                _avg = sum(_vals) / len(_vals)
                _hist = self._signal_history.setdefault(_sk, [])
                _hist.append(_avg)
                if len(_hist) > _MAX_SIGNAL_HISTORY:
                    self._signal_history[_sk] = _hist[-_MAX_SIGNAL_HISTORY:]

        # Per-ticker close price history for IC return computation
        for _ticker, _tdata in market_data.items():
            if _ticker.startswith("_") or not _tdata:
                continue
            _closes = _tdata.get("close") or _tdata.get("adjclose", [])
            if _closes and isinstance(_closes[-1], (int, float)):
                _ph = self._price_history.setdefault(_ticker, [])
                _ph.append(float(_closes[-1]))
                if len(_ph) > _MAX_SIGNAL_HISTORY:
                    self._price_history[_ticker] = _ph[-_MAX_SIGNAL_HISTORY:]

        _min_hist = min((len(v) for v in self._signal_history.values()), default=0)
        if _min_hist >= 15:
            ic_research_out, _ = self.tracer.execute_with_tracing(
                self.signal_research,
                NodeInput(
                    action="analyze_ic",
                    parameters={
                        "signal_history": self._signal_history,
                        "price_history": self._price_history,
                    },
                    context={"cycle": cycle},
                ),
                parent_ctx=root_ctx,
            )
            if ic_research_out.success and ic_research_out.result:
                _ic_result = ic_research_out.result
                _ic_by_signal = _ic_result.get("ic_by_signal", {})
                _current_regime = self.memory.get_working("regime", "default") or "default"
                for _sname, _hresults in _ic_by_signal.items():
                    _ic1 = next((r["ic"] for r in _hresults if r["horizon_days"] == 1), 0.0)
                    _ic5 = next((r["ic"] for r in _hresults if r["horizon_days"] == 5), 0.0)
                    self._ic_values[_sname] = _ic1
                    self._ic_long_values[_sname] = _ic5
                    self.dynamic_weights.update_ic(_sname, _ic1, _current_regime)

                # Recompute composite for every ticker using IC-weighted blend
                for _ticker, _sig in signals.items():
                    if _ticker.startswith("_"):
                        continue
                    _sv = {
                        k: float(_sig[k])
                        for k in _SIGNAL_KEYS
                        if k in _sig and isinstance(_sig.get(k), (int, float))
                    }
                    if _sv:
                        _sig["composite"] = self.dynamic_weights.blend_signals(
                            _sv, _current_regime
                        )
                logger.info(
                    "    IC(analyzed=%d, ic_weighted_composite=ON) regime=%s",
                    len(_ic_by_signal),
                    _current_regime,
                )
            else:
                logger.warning("    SignalResearchNode: %s", ic_research_out.errors)

        # ── Step 2c: DebateGate verdict — consumes IC values ─────────────────
        if self._ic_values:
            _avg_ic_short = sum(self._ic_values.values()) / len(self._ic_values)
            _avg_ic_long = (
                sum(self._ic_long_values.values()) / len(self._ic_long_values)
                if self._ic_long_values
                else _avg_ic_short
            )
            _regime_label = self.memory.get_working("regime", "default") or "default"
            _regime_ic_map: dict[str, float] = {_regime_label: _avg_ic_short}
            _composites = [
                float(s.get("composite", 0))
                for s in signals.values()
                if isinstance(s.get("composite"), (int, float))
            ]
            _avg_composite = sum(_composites) / len(_composites) if _composites else 0.0
            _rsis = [
                float(s.get("rsi", 50))
                for s in signals.values()
                if isinstance(s.get("rsi"), (int, float))
            ]
            _avg_rsi = sum(_rsis) / len(_rsis) if _rsis else 50.0
            _sig_ctx = SignalContext(
                composite_signal=_avg_composite,
                ic_short=_avg_ic_short,
                ic_long=_avg_ic_long,
                vol_regime=_regime_label,
                regime_ic=_regime_ic_map,
                recent_sharpe=self._last_sharpe,
                node_error_rate=self._pipeline_error_rate([ingest_out, sig_out]),
                rsi=_avg_rsi,
            )
            _debate_verdict = self.debate_gate.evaluate(_sig_ctx)
            logger.info(
                "    DebateGate: %s conf=%.3f pos_scale=%.3f (ic_short=%.4f ic_long=%.4f)",
                _debate_verdict.direction.value,
                _debate_verdict.confidence,
                _debate_verdict.position_scale,
                _avg_ic_short,
                _avg_ic_long,
            )
            self.memory.set_working(
                "debate_verdict",
                {
                    "direction": _debate_verdict.direction.value,
                    "confidence": float(_debate_verdict.confidence),
                    "position_scale": float(_debate_verdict.position_scale),
                },
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
        _prev_sharpe = self._last_sharpe
        self._last_sharpe = sharpe  # feed DebateGate in next cycle
        logger.info(
            "    → %d positions | method=%s | Sharpe=%.3f | MaxDD=%.2f%% (%.1fms)",
            portfolio.get("positions", 0),
            portfolio.get("method", "?"),
            sharpe,
            bt.get("max_drawdown", 0.0) * 100,
            strat_out.metrics.get("latency_ms", 0),
        )

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

        logger.info(
            "    → VaR(95)=%.2f%% | limits=%s | violations=%d (%.1fms)",
            risk_result.get("portfolio_var_95", 0.0) * 100,
            "PASSED" if risk_result.get("passed", True) else "VIOLATED",
            len(risk_result.get("violations", [])),
            risk_out.metrics.get("latency_ms", 0),
        )

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
        system_metrics: dict[str, float] = {
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

        # ── Walk-forward backtest with composite signals (every 3 cycles) ────────
        # Uses the OHLCV window already in market_data to evaluate multi-signal
        # composite strategy out-of-sample — replacing SMA-only in-sample eval.
        _btc_tdata = market_data.get("BTCUSDT", {})
        if _btc_tdata:
            _wf_closes = _btc_tdata.get("close") or _btc_tdata.get("adjclose", [])
            _wf_opens = _btc_tdata.get("open", _wf_closes)
            _wf_highs = _btc_tdata.get("high", _wf_closes)
            _wf_lows = _btc_tdata.get("low", _wf_closes)
            _wf_vols = _btc_tdata.get("volume", [1.0] * len(_wf_closes))
            _wf_ts = _btc_tdata.get("timestamps", list(range(len(_wf_closes))))
            _wf_len = min(
                len(_wf_closes),
                len(_wf_opens),
                len(_wf_highs),
                len(_wf_lows),
                len(_wf_vols),
            )
            if _wf_len >= 71:  # min_lookback(40) + min_train(30) + 1
                _wf_bars = [
                    {
                        "timestamp": _wf_ts[i],
                        "open": float(_wf_opens[i]),
                        "high": float(_wf_highs[i]),
                        "low": float(_wf_lows[i]),
                        "close": float(_wf_closes[i]),
                        "volume": float(_wf_vols[i]),
                    }
                    for i in range(_wf_len)
                ]
                try:
                    _wf_result = walk_forward_backtest("BTCUSDT", _wf_bars, min_train=30)
                    if "error" not in _wf_result:
                        _wf_sharpe = _wf_result.get("sharpe", 0.0)
                        _wf_dd = _wf_result.get("max_drawdown", 0.0)
                        _wf_sig = _wf_result.get("sharpe_significant", False)
                        logger.info(
                            "    WalkForward(OOS): Sharpe=%.3f MaxDD=%.1f%% "
                            "significant=%s active_days=%d/%d",
                            _wf_sharpe,
                            _wf_dd * 100,
                            _wf_sig,
                            _wf_result.get("n_active_days", 0),
                            _wf_result.get("n_oos_days", 0),
                        )
                        system_metrics["wf_oos_sharpe"] = _wf_sharpe
                        system_metrics["wf_max_drawdown"] = _wf_dd
                except Exception as _wfe:
                    logger.warning("Walk-forward backtest skipped: %s", _wfe)

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
        _, _ = self.tracer.execute_with_tracing(
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
            regime_state.label,
            regime_state.changepoint_prob,
            regime_state.mean_estimate,
        )

        # ── Adversarial pressure ──────────────────────────────────────────────
        # Ring 1 uses signals as variant outputs (single variant for now)
        variant_signals = {
            "primary": {t: float(s.get("composite", 0)) for t, s in signals.items()}
        }
        adv_report = self.adversarial.run(
            cycle=cycle,
            variant_outputs=variant_signals,
            current_signals={t: float(s.get("composite", 0)) for t, s in signals.items()},
            strategy_params={
                "method": portfolio.get("method", "equal"),
                "positions": portfolio.get("positions", 0),
            },
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
            max_disagreement=adv_report.ring1_result.max_disagreement
            if adv_report.ring1_result
            else 0.0,
            scenario_count=len(adv_report.ring2_scenarios),
            failure_cases=adv_report.failure_cases,
        )

        # ── Autonomy promotion check ──────────────────────────────────────────
        # Promote to SUPERVISED after cycle 3 so Ring 3 can activate.
        if self._autonomy_level == AutonomyLevel.PICO and cycle >= 3:
            self._autonomy_level = AutonomyLevel.SUPERVISED
            logger.info("[autonomy] Promoted to SUPERVISED at cycle %d — Ring 3 now active", cycle)

        # ── Ring 3: Evolutionary tournament via Go (autonomy >= SUPERVISED) ───
        if self._autonomy_level.value in ("supervised", "autonomous"):
            _ring3_strategy_params: dict[str, float] = {
                "composite_signal": float(system_metrics.get("sharpe_ratio", 0.0)),
                "sma_short": float(self.signals._sma_short),
                "sma_long": float(self.signals._sma_long),
                "rsi_period": float(self.signals._rsi_period),
                "error_rate": float(system_metrics.get("error_rate", 0.0)),
                "wf_oos_sharpe": float(system_metrics.get("wf_oos_sharpe", 0.0)),
            }
            try:
                _ring3_report = self.adversarial_client.run_pressure(
                    cycle=cycle,
                    variant_outputs=variant_signals,
                    current_signals={t: float(s.get("composite", 0)) for t, s in signals.items()},
                    strategy_params=_ring3_strategy_params,
                    run_ring2=False,
                    run_ring3=True,
                    run_debate=False,
                )
                _ring3 = _ring3_report.get("ring3") or {}
                if _ring3:
                    _champion = _ring3.get("champion") or {}
                    logger.info(
                        "[Ring3] Tournament: generation=%d champion_fitness=%.3f "
                        "population=%d flagged=%s",
                        _ring3.get("generation", 0),
                        _champion.get("fitness", 0.0),
                        _ring3.get("populationSize", 0),
                        _ring3.get("flagged", False),
                    )
                    if _ring3.get("flagged"):
                        self.state_store.record_adversarial_result(
                            cycle=cycle,
                            ring=3,
                            flagged=True,
                            max_disagreement=float(
                                _ring3.get("fitnessSpreead", 0.0)
                                or _ring3.get("fitness_spread", 0.0)
                            ),
                            scenario_count=0,
                            failure_cases=[],
                        )
            except AdversarialServiceError as _ae:
                raise RuntimeError(
                    f"Go AdversarialService Ring 3 failed at cycle {cycle}: {_ae}"
                ) from _ae

        # ── Alignment check before improvement ───────────────────────────────
        node_metrics_map = {
            node.get_state().name: node.evaluate()
            for node in [self.ingestion, self.signals, self.strategy, self.risk, self.reporting]
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
            adjustments=alignment_decision.outcome_scores,
            vcg_payments={},
            goodhart_warning=alignment_decision.magnitude_warning,
        )
        if not alignment_decision.approved:
            logger.warning(
                "[alignment] BLOCKED improvement: violations=%s",
                alignment_decision.violations,
            )
        elif alignment_decision.magnitude_warning:
            logger.warning("[alignment] Improvement magnitude exceeded — proceeding with caution")
        else:
            logger.info(
                "[alignment] Approved. Pareto ranks: %s",
                dict(list(alignment_decision.pareto_ranks.items())[:3]),
            )

        # ── Goal tracking: update with real system_metrics ───────────────────
        goal_decision_final = self.goals.step(
            metrics=system_metrics,
            system_state={
                "health": sum(
                    n.get_state().health for n in [self.ingestion, self.signals, self.strategy]
                )
                / 3,
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
            nash_weights={},
            tracking_error=goal_decision_final.tracking_error,
            control_action=goal_decision_final.control_action,
            subtasks=[
                {"name": t.name, "assigned_to": t.assigned_to}
                for t in goal_decision_final.subtasks
            ],
            violations=[v.constraint_name for v in goal_decision_final.constraint_violations],
        )

        # ── Self-improvement pass (only if alignment approves) ────────────────
        fb_summary = self.feedback.get_improvement_feedback()
        improved_nodes = (
            self._run_improvement_pass(system_metrics, fb_summary, cycle)
            if alignment_decision.approved
            else []
        )

        # ── Devil's Advocate review (after improvements, before committing) ───
        da_context = {
            "node_healths": [
                self.ingestion.get_state().health,
                self.signals.get_state().health,
                self.strategy.get_state().health,
                self.risk.get_state().health,
                self.reporting.get_state().health,
            ],
            "before": self._last_metrics,
            "after": system_metrics,
            "history": [s.score for s in self.orchestrator._iteration_history[-5:]],
            "sharpe_ratio": system_metrics.get("sharpe_ratio", 0.0),
            "subsystem": "victoria",
        }
        da_out = self.devils_advocate.execute(
            NodeInput(action="architectural_review", parameters=da_context)
        )
        if da_out.success and da_out.result:
            da_report = da_out.result
            veto = da_report.get("veto", False)
            open_count = da_report.get("open_count", 0)
            logger.info(
                "[DA] %s | open_challenges=%d | critical=%d | veto=%s",
                da_report.get("verdict", "?"),
                open_count,
                da_report.get("critical_count", 0),
                veto,
            )
            if veto:
                logger.warning(
                    "[DA] Improvement VETOED — unresolved CRITICAL challenges "
                    "or gate failures detected"
                )
        self._last_metrics = dict(system_metrics)

        # ── End root trace ────────────────────────────────────────────────────
        self.tracer.end_span(
            root_ctx.span_id,
            status="ok",
            metadata={
                "score": score,
                "pipeline_ms": pipeline_ms,
                "improved_nodes": len(improved_nodes),
            },
        )

        # ── Store cycle summary in episodic memory ────────────────────────────
        self.memory.end_cycle(
            cycle,
            {
                "score": score,
                "system_metrics": system_metrics,
                "improved_nodes": improved_nodes,
                "pipeline_ms": pipeline_ms,
            },
        )

        # ── Mirror cycle summary to Go MemoryService ──────────────────────────
        try:
            self.memory_client.store_episode(
                node_id="victoria_cycle",
                event_type="cycle_result",
                content={
                    "cycle": str(cycle),
                    "sharpe": str(round(sharpe, 4)),
                    "score": str(round(score, 4)),
                    "improved_nodes": str(len(improved_nodes)),
                    "error_rate": str(round(system_metrics.get("error_rate", 0.0), 4)),
                    "wf_oos_sharpe": str(round(system_metrics.get("wf_oos_sharpe", 0.0), 4)),
                },
                importance=0.7,
                cycle=cycle,
            )
            # Trigger Go ConsolidationPipeline every 5 cycles
            if cycle > 0 and cycle % 5 == 0:
                _consol = self.memory_client.trigger_consolidation("victoria_cycle")
                logger.info(
                    "[memory_go] Consolidation: examined=%d promoted=%d pruned=%d",
                    _consol.get("episodesExamined", 0),
                    _consol.get("promotedToSemantic", 0),
                    _consol.get("pruned", 0),
                )
        except MemoryServiceError as _me:
            raise RuntimeError(f"Go MemoryService failed at cycle {cycle}: {_me}") from _me

        # ── Submit cycle results to Go ImprovementEngine ──────────────────────
        # Ensure nodes are registered before recording outcomes.
        for _imp_node, _prio in [(self.signals, 1.0), (self.strategy, 0.8)]:
            try:
                self.improvement_client.schedule_improvement(
                    node_id=_imp_node.get_state().node_id,
                    priority=_prio,
                    interval_seconds=60,
                )
            except ImprovementServiceError as _se:
                logger.warning("ImprovementEngine registration skipped: %s", _se)

        _score_delta = sharpe - _prev_sharpe if cycle > 0 else 0.0
        try:
            for _imp_node in [self.signals, self.strategy]:
                _imp_state = _imp_node.get_state()
                self.improvement_client.record_outcome(
                    node_id=_imp_state.node_id,
                    success=system_metrics.get("error_rate", 0.0) < 0.3,
                    score=_score_delta,
                    cycle=cycle,
                    before_metrics={k: float(v) for k, v in self._last_metrics.items()},
                    after_metrics={k: float(v) for k, v in system_metrics.items()},
                )
        except ImprovementServiceError as _ie:
            raise RuntimeError(
                f"Go ImprovementService record_outcome failed at cycle {cycle}: {_ie}"
            ) from _ie

        # ── Print iteration summary ───────────────────────────────────────────
        mem_summary = self.memory.summary()
        mem_summary["regime"] = self.memory.get_working("regime", "unknown")
        self._print_iteration_summary(
            cycle, system_metrics, score, improved_nodes, pipeline_ms, mem_summary
        )

        # ── Flush metrics exporter ────────────────────────────────────────────
        self._flush_metrics(
            pipeline_ms=pipeline_ms,
            signals=signals,
            portfolio=portfolio,
            node_outputs=[
                (self.ingestion, ingest_out),
                (self.signals, sig_out),
                (self.strategy, strat_out),
                (self.risk, risk_out),
                (self.reporting, report_out),
                (self.lint, lint_out),
                (self.integrity, integrity_out),
            ],
            improved_count=len(improved_nodes),
        )

        self._iteration += 1
        return {
            "iteration": cycle,
            "score": score,
            "system_metrics": system_metrics,
            "improved_nodes": improved_nodes,
        }

    def _flush_metrics(
        self,
        pipeline_ms: float,
        signals: dict[str, Any],
        portfolio: dict[str, Any],
        node_outputs: list,
        improved_count: int,
    ) -> None:
        """Push heartbeat data into the MetricsExporter (no-op if not attached)."""
        if self._mex is None:
            return
        mex = self._mex

        # Heartbeat duration
        mex.record_heartbeat(pipeline_ms / 1000.0)

        # Per-node execution durations
        for node, output in node_outputs:
            state = node.get_state()
            mex.record_node_execution(
                node_id=state.node_id,
                node_type=state.name,
                duration_s=output.metrics.get("latency_ms", 0.0) / 1000.0,
                success=output.success,
            )

        # Improvement counter (per-cycle count, not cumulative — DB is cumulative)
        for _ in range(improved_count):
            mex.record_improvement(result="improved")

        # Signal values
        if signals:
            mex.update_signals(signals)

        # Portfolio gross exposure
        weights = portfolio.get("weights", {})
        gross_exposure = sum(abs(v) for v in weights.values()) if weights else 0.0
        mex.update_portfolio_exposure(gross_exposure)

    def _run_improvement_pass(
        self,
        system_metrics: dict[str, float],
        feedback_summary: dict[str, Any],
        iteration: int,
    ) -> list[str]:
        """Evaluate each node and trigger Improve() where needed."""
        improved: list[str] = []
        nodes_info = [
            (self.ingestion, "DataIngestionNode"),
            (self.signals, "SignalGenerationNode"),
            (self.strategy, "StrategyNode"),
            (self.risk, "RiskManagementNode"),
            (self.reporting, "ReportingNode"),
            (self.lint, "LintNode"),
            (self.integrity, "DataIntegrityNode"),
            (self.verification, "VerificationNode"),
            (self.property_tests, "PropertyTestNode"),
            (self.dashboard, "DashboardNode"),
            # Note: InvariantDiscoveryNode and ConvergenceMonitorNode don't self-improve
        ]

        # ── Query Go ImprovementEngine for due nodes and trial suggestions ───
        _go_trial_params: dict[str, dict[str, float]] = {}
        try:
            _due_nodes = self.improvement_client.due_nodes(cycle=iteration)
            for _nid in _due_nodes:
                try:
                    _proposal = self.improvement_client.propose_trial_params(
                        node_id=_nid,
                        param_space={
                            "sma_short": {"low": 3, "high": 20},
                            "sma_long": {"low": 10, "high": 60},
                            "rsi_period": {"low": 7, "high": 21},
                        },
                    )
                    _params = _proposal.get("params", {})
                    if _params:
                        _go_trial_params[_nid] = _params
                        logger.info(
                            "[improvement_go] Node %s trial params: %s (EI=%.3f)",
                            _nid,
                            {k: round(v, 3) for k, v in _params.items()},
                            _proposal.get("expectedImprovement", 0.0),
                        )
                except ImprovementServiceError:
                    pass  # individual node failure does not block the loop
        except ImprovementServiceError as _ie:
            raise RuntimeError(
                f"Go ImprovementService due_nodes failed at cycle {iteration}: {_ie}"
            ) from _ie

        # Run system analyzer to get recommendations
        analyzer_recs = self.analyzer.analyze(cycle=iteration)
        # Build per-node recommendation context
        rec_by_node: dict[str, dict] = {}
        for rec in analyzer_recs:
            if rec.target_node not in rec_by_node:
                rec_by_node[rec.target_node] = {}
            rec_by_node[rec.target_node].update(rec.as_feedback_dict())

        # Retrieve relevant semantic memories for context
        memory_context = self.memory.retrieve_semantic(limit=3)

        for node, name in nodes_info:
            node_metrics = node.evaluate()
            negative_feedback = name in feedback_summary.get("negative_feedback_nodes", [])

            _node_id = node.get_state().node_id
            feedback: dict[str, Any] = {
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
                    {"concept": m.concept, "content": m.content} for m in memory_context
                ],
                # Go ImprovementEngine TPE-proposed trial parameters (if any)
                "go_trial_params": _go_trial_params.get(_node_id, {}),
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
                            name,
                            verify_result.get("details", "regression detected"),
                        )
                        # Don't record this as an improvement since it was reverted
                    else:
                        improved.append(f"{name} → v{new_state.version}")
                        logger.info(
                            "✓ %s improved to v%s [verification: PASS]", name, new_state.version
                        )
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
        metrics: dict[str, float],
        score: float,
        improved: list[str],
        elapsed_ms: float,
        mem_summary: dict[str, Any],
    ) -> None:
        improved_str = ", ".join(improved) if improved else "—"
        logger.info(
            "Heartbeat #%d complete",
            iteration,
            extra={
                "cycle_id": iteration,
                "score": round(score, 4),
                "elapsed_s": round(elapsed_ms / 1000, 1),
                "coverage_rate": metrics.get("coverage_rate", 0),
                "signal_coverage": metrics.get("signal_coverage", 0),
                "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                "indicator_count": int(metrics.get("indicator_count", 1)),
                "error_rate": metrics.get("error_rate", 0),
                "episodic_memories": mem_summary.get("episodic_count", 0),
                "semantic_patterns": mem_summary.get("semantic_count", 0),
                "regime": mem_summary.get("regime", "unknown"),
                "improved_nodes": improved_str,
            },
        )

    def print_node_health(self) -> None:
        for node in [
            self.ingestion,
            self.signals,
            self.strategy,
            self.risk,
            self.reporting,
            self.lint,
            self.integrity,
            self.verification,
            self.property_tests,
            self.invariants,
            self.convergence,
        ]:
            state = node.get_state()
            logger.info(
                "Node health: %s v%s health=%.0f%%",
                state.name,
                state.version,
                state.health * 100,
                extra={
                    "node_id": state.node_id,
                    "health": state.health,
                    "version": state.version,
                    **state.metrics,
                },
            )

    def print_verification_summary(self) -> None:
        """Log verification + convergence + invariant summary."""
        v = self.verification
        total = v._pass_count + v._fail_count
        pass_rate = v._pass_count / max(1, total)
        logger.info(
            "VerificationNode: %d pass / %d fail / %d rollbacks (pass_rate=%.0f%%)",
            v._pass_count,
            v._fail_count,
            v._rollback_count,
            pass_rate * 100,
        )

        c = self.convergence
        if c._scores:
            logger.info(
                "ConvergenceMonitor: %d cycles | EMA=%.4f | oscillations=%d",
                len(c._scores),
                c._score_emas[-1],
                c._oscillation_count,
            )
            if c._oscillation_count > 0:
                logger.warning("Oscillations detected: %d", c._oscillation_count)

        inv = self.invariants
        logger.info(
            "InvariantDiscovery: %d confirmed | %d proposed | %d violations",
            len(inv._confirmed_invariants),
            len(inv._proposed_invariants),
            inv._violation_count,
        )

        p = self.property_tests
        active = p._active_issues()
        logger.info("PropertyTestNode: v%s | %d active violations", p._version, len(active))

    def print_memory_status(self) -> None:
        summary = self.memory.summary()
        logger.info(
            "Memory: cycle=%d episodic=%d semantic=%d working_keys=%s",
            summary["current_cycle"],
            summary["episodic_count"],
            summary["semantic_count"],
            ", ".join(summary["working_memory_keys"]) or "(empty)",
        )
        for concept in summary.get("top_semantic_concepts", []):
            logger.debug(
                "Learned pattern [%.2f]: %s",
                concept["confidence"],
                concept["concept"],
            )

    def print_observability_summary(self) -> None:
        """Log concise observability dashboard after each heartbeat."""
        logger.info("Metrics dashboard:\n%s", self.metrics.format_dashboard())

        recent = self.state_store.get_recent_traces(limit=1)
        if recent:
            last_trace_id = recent[0]["trace_id"]
            logger.info("Last heartbeat trace:\n%s", self.tracer.format_waterfall(last_trace_id))

    def accept_feedback(self, cycle: int) -> None:
        """Prompt the user for optional feedback (non-blocking, 3s window)."""
        logger.info(
            "Feedback window open — type and press Enter within 3s, or wait to continue",
            extra={"cycle_id": cycle},
        )
        fb = self.feedback.try_read_cli_feedback(timeout_sec=3.0, cycle=cycle)
        if fb:
            logger.info("Feedback recorded: %s", fb[:60], extra={"cycle_id": cycle})

    def print_evaluation_report(self) -> None:
        logger.info("Evaluation report:\n%s", self.orchestrator.evaluator.report(GOAL))


# ─── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Victoria — Omega crypto quantitative research heartbeat"
    )
    parser.add_argument(
        "--heartbeat", type=int, default=120, help="Seconds between heartbeats (default: 120)"
    )
    parser.add_argument(
        "--iterations", type=int, default=0, help="Max iterations (0 = run forever)"
    )
    parser.add_argument("--once", action="store_true", help="Run exactly one heartbeat then exit")
    parser.add_argument(
        "--feedback", action="store_true", help="Prompt for human feedback between heartbeats"
    )
    parser.add_argument(
        "--metrics",
        action="store_true",
        help="Start Prometheus metrics exporter on --metrics-port",
    )
    parser.add_argument(
        "--metrics-port",
        type=int,
        default=9090,
        help="Port for Prometheus /metrics endpoint (default: 9090)",
    )
    args = parser.parse_args()

    logger.info(
        "VICTORIA starting",
        extra={
            "system": "Victoria — Omega Crypto Quantitative Research System",
            "data_sources": "Binance (OHLCV) + CoinGecko (market caps)",
            "memory": "episodic + semantic + working (SQLite)",
            "feedback": "self-supervised + human CLI",
            "heartbeat_s": args.heartbeat,
            "pairs": "BTC,ETH,SOL,BNB,XRP,ADA,DOT,AVAX,LINK,MATIC",
            "future": "SentimentNode via Bittensor SN13 / Macrocosmos dv CLI",
        },
    )
    _cfg.dump_to_log()

    system = VictoriaSystem()

    if args.metrics:
        mex = MetricsExporter(
            state_store=system.state_store,
            memory_kernel=system.memory,
            port=args.metrics_port,
        )
        system.attach_metrics_exporter(mex)
        mex.start()
        logger.info("Metrics exporter started — http://localhost:%d/metrics", args.metrics_port)

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
    logger.info("=== FINAL EVALUATION REPORT ===")
    system.print_node_health()
    system.print_memory_status()
    system.print_evaluation_report()

    fb_summary = system.feedback.get_feedback_history_summary()
    logger.info("Feedback history:\n%s", fb_summary)
    logger.info("Completed %d heartbeat(s). Goodbye.", iteration_count)


if __name__ == "__main__":
    main()
