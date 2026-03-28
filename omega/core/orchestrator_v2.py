"""
omega.core.orchestrator_v2
~~~~~~~~~~~~~~~~~~~~~~~~~~
OmegaOrchestrator — pluggable, goal-driven orchestrator that composes all
subsystems without hardcoding any domain-specific node logic.

Architecture
------------
Nodes are registered via register_node() and stored in a NodeRegistry.
Which nodes are *active* during a given cycle is determined by the goal system
and node health — not hardcoded per domain.

Main loop (one iteration):
  1. Reconcile active_nodes: health-check, goal-activation
  2. data_poll()  — call poll() on all active nodes that support it
  3. signals()    — nodes compute signals from polled data
  4. strategy()   — strategy-capable nodes propose trades
  5. adversarial() — adversarial layer validates proposals
  6. execute_or_block() — execute clean proposals; block flagged ones
  7. post_cycle()  — improvement scheduling, memory consolidation, metrics

The orchestrator is deliberately generic — domain logic lives in nodes.
VictoriaNode is one node among many; the system works with zero nodes.

Prometheus metrics (via MetricsExporter)
-----------------------------------------
  omega_cycle_duration_seconds histogram
  omega_signals_per_cycle gauge
  omega_trades_per_cycle gauge
  omega_adversarial_flags_total counter
  omega_active_nodes gauge
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from omega.core.actions import (
    POLL_CAPABILITIES,
    SIGNAL_CAPABILITIES,
    STRATEGY_CAPABILITIES,
    NodeAction,
)
from omega.core.adversarial_v2 import AdversarialPressureV2
from omega.core.autonomy import AutonomyLevel, GraduatedAutonomyController
from omega.core.cycle import CycleContext, CycleHistory, CycleResult
from omega.core.improvement_engine import ImprovementEngine
from omega.core.improvement_scheduler import ImprovementScheduler
from omega.core.memory_consolidation import ConsolidationPipeline
from omega.core.metrics_exporter import MetricsExporter
from omega.core.node import Node, NodeInput, NodeOutput
from omega.core.regime_handler import RegimeTransitionHandler
from omega.core.registry import NodeRegistry
from omega.nodes.shared.semantic_memory import SemanticMemoryNode

logger = logging.getLogger("omega.orchestrator_v2")

# Proposals with adversarial disagreement score above this threshold are blocked even in PICO mode.
# Prevents rubber-stamping all proposals regardless of signal quality.
# Calibrated for 11 signals: structural max_disagreement with a diverse signal suite (news, derivatives,
# order flow, microstructure, etc.) is empirically 0.51-0.63 at typical market conditions.
# Threshold set to 0.70 (sufficient headroom above structural ceiling) - still blocks genuine
# outliers > 0.70 while allowing normal 11-signal diversity through.
_ADVERSARIAL_SCORE_THRESHOLD = 0.70

# ---------------------------------------------------------------------------
# DebateGateLearner — learns the optimal block threshold from outcomes
# ---------------------------------------------------------------------------


class DebateGateLearner:
    """
    Learns the optimal adversarial block threshold from trade outcomes.

    When the gate blocks a proposal, we record what would have happened
    (via paper-trade simulation or next-cycle price check).
    If blocked proposals would have been profitable, lower the threshold.
    If blocked proposals would have been losses, raise it.

    Update rule (EMA):
      threshold += alpha * (target_block_rate - actual_block_rate)

    Target: block proposals that would lose, pass the ones that would win.
    """

    def __init__(
        self,
        initial_threshold: float = _ADVERSARIAL_SCORE_THRESHOLD,
        alpha: float = 0.05,  # EMA step size
        target_block_rate: float = 0.30,  # aim to block ~30% of proposals
        window: int = 50,  # rolling window for rate computation
        min_threshold: float = 0.10,
        max_threshold: float = 0.70,
    ) -> None:
        self.threshold = initial_threshold
        self._alpha = alpha
        self._target_block_rate = target_block_rate
        self._window = window
        self._min_threshold = min_threshold
        self._max_threshold = max_threshold

        # Rolling history: each entry = {"blocked": bool, "would_have_won": bool | None}
        self._history: list[dict] = []

    def record_proposal(self, blocked: bool, cycle_id: str, proposal: dict) -> None:
        """Record a proposal decision (blocked or passed)."""
        self._history = self._history[-self._window + 1 :]
        self._history.append(
            {
                "blocked": blocked,
                "cycle_id": cycle_id,
                "proposal": proposal,
                "would_have_won": None,  # resolved later via record_outcome
            }
        )

    def record_outcome(self, cycle_id: str, pnl: float) -> None:
        """
        Resolve the outcome of a proposal that was passed (not blocked).

        Marks the matching history entry so the threshold learner can
        estimate what the block rate should converge to.
        """
        for entry in reversed(self._history):
            if entry.get("cycle_id") == cycle_id and entry.get("would_have_won") is None:
                entry["would_have_won"] = pnl > 0
                break

    def update_threshold(self) -> float:
        """
        Run one EMA update step on the block threshold.

        Returns the updated threshold value.
        """
        if not self._history:
            return self.threshold

        total = len(self._history)
        blocked_count = sum(1 for e in self._history if e["blocked"])
        actual_block_rate = blocked_count / total if total > 0 else 0.0

        # EMA update: push threshold toward the rate that achieves target_block_rate
        delta = self._alpha * (self._target_block_rate - actual_block_rate)
        new_threshold = self.threshold + delta
        self.threshold = max(self._min_threshold, min(self._max_threshold, new_threshold))

        logger.debug(
            "DebateGateLearner: actual_block_rate=%.2f target=%.2f threshold %.3f→%.3f",
            actual_block_rate,
            self._target_block_rate,
            self.threshold - delta,
            self.threshold,
        )
        return self.threshold


# ---------------------------------------------------------------------------
# NodeHealth — lightweight health record per node
# ---------------------------------------------------------------------------


class NodeHealth:
    """Rolling health tracker for a single node."""

    def __init__(self, node_id: str, window: int = 20) -> None:
        self.node_id = node_id
        self._scores: list[float] = []
        self._window = window
        self._consecutive_errors = 0

    def record(self, health: float, success: bool) -> None:
        self._scores = [*self._scores[-self._window + 1 :], health]
        if success:
            self._consecutive_errors = 0
        else:
            self._consecutive_errors += 1

    @property
    def avg_health(self) -> float:
        return sum(self._scores) / len(self._scores) if self._scores else 1.0

    @property
    def is_degraded(self) -> bool:
        return self.avg_health < 0.4 or self._consecutive_errors >= 5


# ---------------------------------------------------------------------------
# OmegaOrchestrator
# ---------------------------------------------------------------------------


class OmegaOrchestrator:
    """
    The Omega system main orchestrator.

    Pluggable and goal-driven — does not hardcode any domain node logic.

    Quick-start::

        orch = OmegaOrchestrator()
        orch.register_node(my_node)
        orch.run(max_cycles=100)
    """

    # After N cycles, run TPE improvement if eligible
    IMPROVEMENT_INTERVAL = 10
    # After N cycles, run memory consolidation
    CONSOLIDATION_INTERVAL = 100

    def __init__(
        self,
        name: str = "omega",
        autonomy_controller: GraduatedAutonomyController | None = None,
        improvement_engine: ImprovementEngine | None = None,
        improvement_scheduler: ImprovementScheduler | None = None,
        regime_handler: RegimeTransitionHandler | None = None,
        adversarial: AdversarialPressureV2 | None = None,
        memory_consolidation: ConsolidationPipeline | None = None,
        metrics_exporter: MetricsExporter | None = None,
        history_size: int = 500,
        paper_trading: Any | None = None,
        metrics_collector: Any | None = None,  # IntelligenceMetricsCollector
    ) -> None:
        self.name = name
        self._registry = NodeRegistry()
        self._active_node_ids: set[str] = set()
        self._node_health: dict[str, NodeHealth] = {}

        # Subsystems — all optional for testability
        self._autonomy = autonomy_controller or GraduatedAutonomyController()
        self._improvement_engine = improvement_engine or ImprovementEngine()
        self._improvement_scheduler = improvement_scheduler or ImprovementScheduler()
        self._regime_handler = regime_handler or RegimeTransitionHandler()
        # Always wire an adversarial instance — never leave the gate as None in production.
        # Callers may inject a custom instance (e.g., with DebateGate) for domain-specific behaviour.
        # ring1_threshold=1.0: after switching to cosine distance (0-2 scale), threshold must
        # be recalibrated.  Cosine distance = 1 - cos(angle).  1.0 means signals are orthogonal
        # (90°); >1.0 means opposing directions.  Threshold=1.0 fires only when two signal vectors
        # are more than 90° apart — genuine directional disagreement, not scale artefacts.
        # Previously 0.40 Euclidean, but basic_signals' raw price sub-keys (BB levels, SMA prices)
        # were inflating Euclidean distance regardless of signal direction.
        self._adversarial = adversarial if adversarial is not None else AdversarialPressureV2(ring1_threshold=1.0)
        self._consolidation = memory_consolidation
        self._metrics = metrics_exporter
        self._paper_trading = paper_trading
        self._intel_collector = metrics_collector

        self._history = CycleHistory(max_size=history_size)
        self._cycle_number: int = 0
        self._running: bool = False
        self._tracer: Any = None
        self._store: Any = None
        self._semantic_memory = SemanticMemoryNode(review_interval=50)

        # Debate gate learner — learns optimal block threshold from outcomes
        self._gate_learner = DebateGateLearner(
            initial_threshold=_ADVERSARIAL_SCORE_THRESHOLD,
        )

        logger.info("OmegaOrchestrator '%s' initialised", name)

    # ------------------------------------------------------------------
    # Pipeline server integration (Go→Python bridge)
    # ------------------------------------------------------------------

    def start_pipeline_server(
        self,
        port: int = 9090,
    ) -> tuple:
        """Start the Connect-RPC pipeline server in a daemon background thread.

        The server handles ``ExecuteStep`` calls from Go, routing each request
        to the matching registered node via its capabilities.

        Can be called before or after :meth:`run`. The server runs until the
        Python process exits (daemon thread) or until the returned
        ``server.shutdown()`` is called.

        Returns:
            ``(server, thread)`` — ``ThreadingHTTPServer`` and its daemon
            thread.  Call ``server.shutdown()`` for a clean stop.
        """
        from omega.bridge.pipeline_server import StepHandlerRegistry
        from omega.bridge.pipeline_server import start_pipeline_server as _start
        from omega.bridge.pipeline_types import ExecuteStepRequest, ExecuteStepResponse
        from omega.core.actions import resolve_action
        from omega.core.node import NodeInput

        registry = StepHandlerRegistry()

        # Register a handler for each active node keyed by its capabilities.
        # Each capability string is normalised to UPPER_SNAKE_CASE to match
        # the nodeType field in ExecuteStepRequest (e.g. "DATA_INGESTION").
        for node in self._registry.all_nodes():
            caps = [
                c.upper().replace(" ", "_").replace("-", "_")
                for c in (node.get_capabilities() or [])
            ]
            for cap in caps:
                # Capture `node` and `cap` via default-argument binding.
                def _make_handler(n: Any = node, capability: str = cap, orch: Any = self) -> Any:
                    def _handler(req: ExecuteStepRequest) -> ExecuteStepResponse:
                        import json as _json

                        # ── Distributed trace propagation (Go→Python) ──────────
                        # When Go sends a traceparent header, continue the trace
                        # so Python spans appear in the same tree in the viewer.
                        child_ctx = None
                        if orch._tracer is not None and req.trace_id and req.parent_span_id:
                            traceparent = f"00-{req.trace_id}-{req.parent_span_id}-01"
                            try:
                                child_ctx = orch._tracer.continue_trace(
                                    traceparent,
                                    operation=f"{capability}.{req.step_name}",
                                    cycle=req.cycle,
                                )
                            except Exception:
                                child_ctx = None

                        # Resolve typed action: prefer STEP_TO_ACTION mapping from
                        # node_type (e.g. "DATA_INGESTION" → "fetch_market_data"),
                        # then fall back to step_name, then raw capability string.
                        _resolved = resolve_action(req.node_type)
                        _action = (
                            _resolved.value
                            if _resolved is not None
                            else (req.step_name.lower() or capability.lower())
                        )
                        inp = NodeInput(
                            action=_action,
                            parameters=dict(req.parameters),
                            context={
                                "cycle": req.cycle,
                                "trace_id": req.trace_id,
                                "parent_span_id": req.parent_span_id,
                                "input": _json.loads(req.input_payload)
                                if req.input_payload
                                else {},
                            },
                        )
                        out = n.execute(inp)
                        state = n.get_state()

                        # End the distributed trace span.
                        if child_ctx is not None and orch._tracer is not None:
                            import contextlib

                            with contextlib.suppress(Exception):
                                orch._tracer.end_span(
                                    child_ctx.span_id,
                                    status="ok" if out.success else "error",
                                )

                        # Persist signal IC history when a signal-research step completes.
                        if (
                            out.success
                            and out.result
                            and orch._paper_trading is not None
                            and capability
                            in (
                                NodeAction.SIGNAL_RESEARCH.value.upper(),
                                NodeAction.COMPUTE_SIGNALS.value.upper(),
                                "SIGNAL_RESEARCH",
                                "COMPUTE_SIGNALS",
                            )
                        ):
                            try:
                                # Transform {signal_name: {value, confidence, ...}} →
                                # [{symbol: name, composite_score: value}] for the DB writer.
                                signals_list = [
                                    {
                                        "symbol": sig_name,
                                        "composite_score": float(sig_val.get("value", 0.0)),
                                        "ic": float(sig_val.get("ic", 0.0)),
                                    }
                                    for sig_name, sig_val in out.result.items()
                                    if isinstance(sig_val, dict) and "value" in sig_val
                                ]
                                if signals_list:
                                    orch._paper_trading.persist_signal_history_to_db(
                                        {state.node_id: signals_list}, req.cycle
                                    )
                            except Exception as _exc:
                                logger.debug("signal history persistence failed: %s", _exc)

                        # After a portfolio-construction step, execute paper trades so that
                        # signal → paper trade pathway is live, not just persisted as signals.
                        if (
                            out.success
                            and orch._paper_trading is not None
                            and capability
                            in (
                                "STRATEGY",
                                "INTELLIGENCECOORDINATION",
                                "CONSTRUCT_PORTFOLIO",
                                NodeAction.STRATEGY.value.upper(),
                                NodeAction.CONSTRUCT_PORTFOLIO.value.upper(),
                            )
                            and out.result
                        ):
                            try:
                                # Expand {weights: {sym: w}} portfolio dicts into
                                # per-symbol proposal dicts that execute_proposals expects.
                                raw_result = out.result
                                proposals: list[dict] = []
                                if isinstance(raw_result, list):
                                    for item in raw_result:
                                        if isinstance(item, dict) and "weights" in item:
                                            for sym, w in item["weights"].items():
                                                proposals.append(
                                                    {"symbol": sym, "weight": float(w)}
                                                )
                                        elif isinstance(item, dict):
                                            proposals.append(item)
                                elif isinstance(raw_result, dict) and "weights" in raw_result:
                                    for sym, w in raw_result["weights"].items():
                                        proposals.append({"symbol": sym, "weight": float(w)})
                                elif isinstance(raw_result, dict):
                                    proposals = [raw_result]
                                if proposals:
                                    market_data = getattr(n, "_last_market_data", {})
                                    executed = orch._paper_trading.execute_proposals(
                                        proposals,
                                        market_data=market_data,
                                        cycle_id=str(req.cycle),
                                    )
                                    logger.info(
                                        "Paper trades executed: %d (cycle=%d)",
                                        len(executed),
                                        req.cycle,
                                    )
                                    # Surface trade counts and PnL into metrics for Go.
                                    if executed:
                                        out.metrics["paper_trades_executed"] = float(len(executed))
                                        out.metrics["paper_trade_total_size"] = sum(
                                            float(t.get("size", 0.0)) for t in executed
                                        )
                                        out.metrics["paper_realised_pnl"] = float(
                                            orch._paper_trading.realised_pnl
                                        )
                            except Exception as _exc:
                                logger.debug("paper trading execution failed: %s", _exc)

                        # Base metrics from node execution (latency_ms etc.)
                        resp_metrics: dict[str, float] = {
                            k: float(v)
                            for k, v in out.metrics.items()
                            if isinstance(v, (int, float))
                        }

                        # Surface financial quality metrics from result dict.
                        # VictoriaNode embeds these as _quality_score, _signal_count etc.
                        # in the result for signal-research and improvement steps.
                        _quality_keys = (
                            "_quality_score",
                            "_signal_count",
                            "_avg_confidence",
                            "_signal_coverage",
                            "_best_score",
                            "_improvement_applied",
                        )
                        if out.success and isinstance(out.result, dict):
                            for _k in _quality_keys:
                                if _k in out.result and isinstance(out.result[_k], (int, float)):
                                    # Strip leading underscore for the Go metric key
                                    resp_metrics[_k.lstrip("_")] = float(out.result[_k])

                        # Surface Polymarket edge metrics so Go can see edge quality.
                        if (
                            out.success
                            and isinstance(out.result, dict)
                            and capability in ("EDGE_DETECTION", "EDGEDETECTION")
                        ):
                            for _ek in ("edge", "kelly_fraction", "model_prob", "market_price"):
                                if _ek in out.result and isinstance(out.result[_ek], (int, float)):
                                    resp_metrics[_ek] = float(out.result[_ek])
                            resp_metrics["opportunity"] = (
                                1.0 if out.result.get("opportunity") else 0.0
                            )

                        return ExecuteStepResponse(
                            success=out.success,
                            error_text="; ".join(out.errors) if out.errors else "",
                            metrics=resp_metrics,
                            node_id=state.node_id,
                            node_name=state.name,
                        )

                    return _handler

                registry.register(cap, _make_handler())

        server, thread = _start(port=port, registry=registry)
        logger.info("OmegaOrchestrator pipeline server started on port %d", port)
        return server, thread

    # ------------------------------------------------------------------
    # Node registry (pluggable — no domain knowledge here)
    # ------------------------------------------------------------------

    def register_node(self, node: Node, *, activate: bool = True) -> str:
        """
        Add a node to the registry.

        Parameters
        ----------
        node     : Any Node subclass — the orchestrator needs no domain knowledge.
        activate : If True (default), add the node to the active set immediately.

        Returns the node_id.
        """
        self._registry.register(node)
        state = node.get_state()
        node_id = state.node_id
        self._autonomy.register_node(node_id)
        self._node_health[node_id] = NodeHealth(node_id)
        if activate:
            self._active_node_ids.add(node_id)

        # Auto-register with improvement engine if the node declares a param space.
        param_space = node.get_param_space()
        if param_space and not self._improvement_engine.is_registered(node_id):
            self._improvement_engine.register_node(node_id, param_space)
            logger.info(
                "Registered node '%s' with ImprovementEngine (%d params)",
                state.name,
                len(param_space),
            )

        logger.info("Registered node '%s' (id=%s, activate=%s)", state.name, node_id, activate)
        return node_id

    def set_paper_trading(self, engine: Any) -> None:
        """Wire in a PaperTradingEngine after construction.

        Called by project-specific setup code (e.g. the Victoria runner).
        Not part of the platform's core — only projects that need paper trading
        should call this.
        """
        self._paper_trading = engine
        logger.debug("PaperTradingEngine wired into orchestrator.")

    def set_tracer(self, tracer: Any) -> None:
        """Wire a Tracer for distributed trace propagation (Go→Python bridge).

        When set, the pipeline server handler creates a child span under the
        incoming W3C traceparent header so Go and Python spans appear in the
        same trace tree.
        """
        self._tracer = tracer
        logger.debug("Tracer wired into orchestrator.")

    def set_state_store(self, store: Any) -> None:
        """Wire a StateBackend for cycle-result persistence.

        Persists CycleResult to the ``cycle_results`` table after each cycle
        and seeds CycleHistory from the DB on startup.
        """
        self._store = store
        self._seed_history_from_store()
        logger.debug("StateStore wired into orchestrator; history seeded from DB.")

    def _seed_history_from_store(self) -> None:
        """Load recent cycle results from the state store into CycleHistory."""
        if self._store is None:
            return
        try:
            rows = self._store.get_recent_cycle_results(limit=self._history._window.maxlen or 200)
            for row in reversed(rows):  # oldest first
                ctx = CycleContext(
                    cycle_id=row["cycle_id"],
                    cycle_number=row["cycle_number"],
                    timestamp=row["started_at"],
                    regime=row.get("regime", "normal"),
                    active_node_ids=(),
                    autonomy_levels={},
                    metadata={},
                )
                result = CycleResult(
                    context=ctx,
                    duration_seconds=row.get("duration_seconds", 0.0),
                    signals_generated=row.get("signals_generated", 0),
                    actions_proposed=row.get("actions_proposed", 0),
                    actions_executed=row.get("actions_executed", 0),
                    error_count=row.get("error_count", 0),
                    improvement_proposed=bool(row.get("improvement_proposed", 0)),
                    regime_transition=bool(row.get("regime_transition", 0)),
                    metrics=row.get("metrics", {}),
                )
                self._history.append(result)
            if rows:
                self._cycle_number = max(r["cycle_number"] for r in rows) + 1
            logger.info(
                "Seeded CycleHistory with %d results from DB (next cycle=%d)",
                len(rows),
                self._cycle_number,
            )
        except Exception as exc:
            logger.warning("Could not seed CycleHistory from DB: %s", exc)

    def deregister_node(self, node_id: str) -> None:
        """Remove a node from the registry and active set."""
        self._active_node_ids.discard(node_id)
        self._node_health.pop(node_id, None)
        self._registry.deregister(node_id)
        logger.info("Deregistered node %s", node_id)

    def activate_node(self, node_id: str) -> None:
        """Mark a registered node as active."""
        if not self._registry.get_node(node_id):
            raise KeyError(f"Node {node_id!r} not registered")
        self._active_node_ids.add(node_id)

    def deactivate_node(self, node_id: str) -> None:
        """Remove a node from the active set without unregistering it."""
        self._active_node_ids.discard(node_id)

    @property
    def active_nodes(self) -> list[Node]:
        """Return all currently active nodes in registration order."""
        nodes = []
        for nid in list(self._active_node_ids):
            node = self._registry.get_node(nid)
            if node is not None:
                nodes.append(node)
        return nodes

    # ------------------------------------------------------------------
    # Goal-driven node activation (hook for goal system)
    # ------------------------------------------------------------------

    def reconcile_active_nodes(
        self,
        goal_node_ids: set[str] | None = None,
        health_threshold: float = 0.3,
    ) -> None:
        """
        Reconcile which nodes should be active.

        1. If goal_node_ids is provided, activate exactly those nodes
           (plus any already active that are not in the goal set remain
           active — callers can explicitly deactivate if needed).
        2. Deactivate nodes whose health has degraded below threshold.
        3. Register autonomy-appropriate brain on each active node.

        This is the hook through which the goal system drives activation.
        """
        if goal_node_ids is not None:
            for nid in goal_node_ids:
                if self._registry.get_node(nid):
                    self._active_node_ids.add(nid)

        for node in list(self.active_nodes):
            state = node.get_state()
            health_rec = self._node_health.get(state.node_id)
            if (
                health_rec
                and health_rec.is_degraded
                and health_threshold > 0
                and health_rec.avg_health < health_threshold
            ):
                logger.warning(
                    "Deactivating degraded node '%s' (avg_health=%.2f)",
                    state.name,
                    health_rec.avg_health,
                )
                self.deactivate_node(state.node_id)
                continue
            # Apply brain appropriate for autonomy level
            try:
                self._autonomy.apply_brain_for_level(node, state.node_id)
            except Exception as exc:
                logger.debug("apply_brain_for_level failed for %s: %s", state.node_id, exc)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(
        self,
        max_cycles: int | None = None,
        sleep_seconds: float = 0.0,
        sleep_until: str = "fixed",
        goal_node_ids: set[str] | None = None,
    ) -> CycleHistory:
        """
        Run the main orchestration loop.

        Parameters
        ----------
        max_cycles    : Stop after this many cycles (None = run forever).
        sleep_seconds : For ``sleep_until="fixed"``, seconds to sleep between cycles.
                        Ignored when ``sleep_until="next_candle"``.
        sleep_until   : Sleep strategy between cycles.

                        ``"fixed"`` (default) — sleep for ``sleep_seconds`` seconds.
                        ``"next_candle"``      — sleep until the next UTC hourly
                        boundary (aligns with 1-hour candle close times).  If the
                        computed wait is < 1 s (i.e. we are already at/past the
                        boundary), wait 1 s to avoid a tight spin.

        goal_node_ids : If provided, reconcile active nodes to this set each cycle.

        Returns the full CycleHistory.

        Adaptive sleep guard
        --------------------
        For ``"fixed"`` mode: if ``sleep_seconds < 1.0`` AND the last cycle
        completed in under 0.05 s (indicating no real I/O occurred), the loop
        backs off to 1 s to prevent hammering external APIs.
        """
        self._running = True
        logger.info("Starting OmegaOrchestrator '%s' (max_cycles=%s)", self.name, max_cycles)
        try:
            while self._running:
                if max_cycles is not None and self._cycle_number >= max_cycles:
                    break
                cycle_result = self.run_one_cycle(goal_node_ids=goal_node_ids)
                wait = self._compute_sleep(sleep_until, sleep_seconds, cycle_result)
                if wait > 0:
                    time.sleep(wait)
        except KeyboardInterrupt:
            logger.info("OmegaOrchestrator '%s' interrupted", self.name)
        finally:
            self._running = False

        logger.info(
            "OmegaOrchestrator '%s' stopped after %d cycles",
            self.name,
            self._cycle_number,
        )
        return self._history

    @staticmethod
    def _compute_sleep(
        sleep_until: str,
        sleep_seconds: float,
        cycle_result: CycleResult | None,
    ) -> float:
        """Return the number of seconds to sleep before the next cycle.

        ``"fixed"``       — return ``sleep_seconds``, with an adaptive floor of
                            1 s when the cycle was too fast (< 0.05 s) and
                            ``sleep_seconds < 1.0``, preventing API hammering.
        ``"next_candle"`` — compute seconds until the next UTC hour boundary.
                            Minimum 1 s so we never spin.
        """
        if sleep_until == "next_candle":
            now = datetime.now(UTC)
            # Next full UTC hour
            seconds_into_hour = now.minute * 60 + now.second + now.microsecond / 1e6
            seconds_until_next_hour = 3600.0 - seconds_into_hour
            return max(1.0, seconds_until_next_hour)

        # "fixed" mode
        cycle_duration = getattr(cycle_result, "duration_seconds", None)
        if sleep_seconds < 1.0 and cycle_duration is not None and cycle_duration < 0.05:
            logger.debug(
                "Adaptive sleep: cycle too fast (%.3fs), backing off to 1s to avoid API hammering",
                cycle_duration,
            )
            return 1.0
        return sleep_seconds

    def stop(self) -> None:
        """Signal the run loop to stop after the current cycle completes."""
        self._running = False

    def run_one_cycle(
        self,
        goal_node_ids: set[str] | None = None,
    ) -> CycleResult:
        """
        Execute one full orchestration cycle and return the CycleResult.

        Steps
        -----
        1. reconcile_active_nodes
        2. Build CycleContext
        3. data_poll  — poll active nodes that support data fetching
        4. signals    — compute signals from polled data
        5. strategy   — nodes propose trades
        6. adversarial — validate proposals
        7. execute_or_block
        8. post_cycle  — improvement, consolidation, metrics
        """
        t_start = time.perf_counter()
        cycle_num = self._cycle_number
        self._cycle_number += 1

        # 1. Reconcile active nodes
        self.reconcile_active_nodes(goal_node_ids=goal_node_ids)

        # 2. Build CycleContext
        regime = self._regime_handler.current_regime
        active_ids = tuple(n.get_state().node_id for n in self.active_nodes)
        autonomy_levels = {nid: self._autonomy.get_level(nid).value for nid in active_ids}
        ctx = CycleContext.new(
            cycle_number=cycle_num,
            regime=regime,
            active_node_ids=active_ids,
            autonomy_levels=autonomy_levels,
        )
        result = CycleResult(context=ctx)

        log = logging.LoggerAdapter(logger, {"cycle_id": ctx.cycle_id, "cycle": cycle_num})
        log.debug("Cycle %d start (regime=%s, nodes=%d)", cycle_num, regime, len(active_ids))

        # 3-7. Execute pipeline — each step is guarded so a crash skips forward
        # instead of aborting the whole cycle.
        poll_outputs: dict[str, Any] = {}
        signal_data: dict[str, Any] = {}
        proposals: list[dict[str, Any]] = []
        clean_proposals: list[dict[str, Any]] = []
        cycle_market_data: dict[str, Any] = {}

        try:
            poll_outputs = self._step_data_poll(ctx, result, log)
        except Exception as _exc:
            result.error_count += 1
            log.error("CYCLE STEP CRASH — data_poll: %s", _exc)

        try:
            signal_data = self._step_signals(ctx, result, poll_outputs, log)
        except Exception as _exc:
            result.error_count += 1
            log.error("CYCLE STEP CRASH — signals: %s", _exc)

        try:
            proposals = self._step_strategy(ctx, result, signal_data, log)
        except Exception as _exc:
            result.error_count += 1
            log.error("CYCLE STEP CRASH — strategy: %s", _exc)

        try:
            clean_proposals = self._step_adversarial(ctx, result, proposals, signal_data, log)
        except Exception as _exc:
            result.error_count += 1
            log.error("CYCLE STEP CRASH — adversarial: %s", _exc)
            clean_proposals = proposals  # fail-open: pass unvalidated proposals

        try:
            for _po in poll_outputs.values():
                if _po and _po.success and isinstance(_po.result, dict):
                    cycle_market_data.update(_po.result)
            self._step_execute(ctx, result, clean_proposals, log, cycle_market_data)
        except Exception as _exc:
            result.error_count += 1
            log.error("CYCLE STEP CRASH — execute: %s", _exc)

        # 8. Post-cycle
        result.duration_seconds = time.perf_counter() - t_start
        self._post_cycle(ctx, result, log)

        self._history.append(result)

        # Persist cycle result to the state store for crash-safe history.
        if self._store is not None:
            try:
                self._store.record_cycle_result(
                    cycle_id=result.cycle_id,
                    cycle_number=result.cycle_number,
                    started_at=ctx.timestamp,
                    duration_seconds=result.duration_seconds,
                    signals_generated=result.signals_generated,
                    actions_proposed=result.actions_proposed,
                    actions_executed=result.actions_executed,
                    error_count=result.error_count,
                    regime=ctx.regime,
                    improvement_proposed=result.improvement_proposed,
                    regime_transition=result.regime_transition,
                    adversarial_flags=result.adversarial_flags,
                    metrics=result.metrics,
                )
            except Exception as exc:
                logger.warning("cycle_result persistence failed: %s", exc)

        log.info(
            "Cycle %d done: signals=%d actions_exec=%d flags=%d dur=%.3fs",
            cycle_num,
            result.signals_generated,
            result.actions_executed,
            len(result.adversarial_flags),
            result.duration_seconds,
        )
        return result

    # ------------------------------------------------------------------
    # Pipeline steps (generic — no domain assumptions)
    # ------------------------------------------------------------------

    def _step_data_poll(
        self,
        ctx: CycleContext,
        result: CycleResult,
        log: Any,
    ) -> dict[str, NodeOutput]:
        """Ask each active node to poll for new data (if it supports it)."""
        outputs: dict[str, NodeOutput] = {}
        for node in self.active_nodes:
            state = node.get_state()
            caps = node.get_capabilities()
            if not POLL_CAPABILITIES.intersection(caps):
                continue
            action = (
                NodeAction.POLL.value
                if NodeAction.POLL.value in caps
                else NodeAction.FETCH_MARKET_DATA.value
            )
            inp = NodeInput(
                action=action,
                parameters={},
                context={"cycle_id": ctx.cycle_id, "cycle": ctx.cycle_number},
            )
            try:
                t0 = time.perf_counter()
                out = node.execute(inp)
                latency = (time.perf_counter() - t0) * 1000
                self._node_health[state.node_id].record(state.health, out.success)
                out.metrics.setdefault("latency_ms", latency)
                outputs[state.node_id] = out
                result.node_results[state.node_id] = {
                    "health": state.health,
                    "success": out.success,
                }
                if self._metrics:
                    self._metrics.record_node_execution(
                        state.node_id, state.name, latency / 1000, success=out.success
                    )
            except Exception as exc:
                result.error_count += 1
                log.error("data_poll failed for node '%s': %s", state.name, exc)
        return outputs

    def _step_signals(
        self,
        ctx: CycleContext,
        result: CycleResult,
        poll_outputs: dict[str, NodeOutput],
        log: Any,
    ) -> dict[str, Any]:
        """Ask signal-capable nodes to compute signals from polled data."""
        signal_data: dict[str, Any] = {}
        for node in self.active_nodes:
            state = node.get_state()
            if not SIGNAL_CAPABILITIES.intersection(node.get_capabilities()):
                continue
            poll_out = poll_outputs.get(state.node_id)
            market_data = poll_out.result if poll_out and poll_out.success else {}
            inp = NodeInput(
                action=NodeAction.COMPUTE_SIGNALS.value,
                parameters={"market_data": market_data or {}},
                context={"cycle_id": ctx.cycle_id, "regime": ctx.regime},
            )
            try:
                out = node.execute(inp)
                self._node_health[state.node_id].record(state.health, out.success)
                if out.success and out.result:
                    signal_data[state.node_id] = out.result
                    n_signals = len(out.result) if isinstance(out.result, dict) else 1
                    result.signals_generated += n_signals
                if not out.success:
                    result.error_count += 1
            except Exception as exc:
                result.error_count += 1
                log.error("signals failed for node '%s': %s", state.name, exc)

        # Update regime handler if any node produced regime data
        for node_signals in signal_data.values():
            if isinstance(node_signals, dict) and "regime_label" in node_signals:
                self._regime_handler.update(
                    regime_label=node_signals["regime_label"],
                    changepoint_prob=float(node_signals.get("changepoint_prob", 0.0)),
                )

        # Persist signal IC history — Victoria-specific, only runs if paper trading is wired.
        if self._paper_trading is not None and signal_data:
            self._paper_trading.persist_signal_history_to_db(signal_data, ctx.cycle_number)

        # Intelligence metrics: signal coverage
        if self._intel_collector is not None:
            all_signals: dict[str, Any] = {}
            for sigs in signal_data.values():
                if isinstance(sigs, dict):
                    all_signals.update(sigs)
            signals_nonzero = sum(
                1 for v in all_signals.values() if isinstance(v, (int, float)) and v != 0
            )
            self._intel_collector.record("signals_active", len(all_signals))
            self._intel_collector.record("signals_nonzero", signals_nonzero)
            rmt = all_signals.get("rmt_info_ratio") or all_signals.get("_rmt_info_ratio")
            if rmt is None:
                # RMT signal stores info_ratio in rmt_signal.raw.info_ratio
                rmt_sig = all_signals.get("rmt_signal")
                if isinstance(rmt_sig, dict):
                    raw = rmt_sig.get("raw", {})
                    rmt = raw.get("info_ratio") if isinstance(raw, dict) else None
            if rmt is not None:
                self._intel_collector.record("rmt_info_ratio", float(rmt))
            w_conf = all_signals.get("_regime_w_confidence")
            if w_conf is not None:
                self._intel_collector.record("wasserstein_confidence", float(w_conf))

        return signal_data

    def _step_strategy(
        self,
        ctx: CycleContext,
        result: CycleResult,
        signal_data: dict[str, Any],
        log: Any,
    ) -> list[dict[str, Any]]:
        """Ask strategy-capable nodes to propose trades."""
        proposals: list[dict[str, Any]] = []
        for node in self.active_nodes:
            state = node.get_state()
            if not STRATEGY_CAPABILITIES.intersection(node.get_capabilities()):
                continue

            # Check autonomy: PICO mode = deterministic strategy only
            autonomy_level = self._autonomy.get_level(state.node_id)
            inp = NodeInput(
                action=NodeAction.CONSTRUCT_PORTFOLIO.value,
                parameters={
                    "signals": signal_data,
                    "regime": ctx.regime,
                    "pico_mode": autonomy_level == AutonomyLevel.PICO,
                },
                context={"cycle_id": ctx.cycle_id},
            )
            try:
                out = node.execute(inp)
                self._node_health[state.node_id].record(state.health, out.success)
                if out.success and out.result:
                    raw_list = out.result if isinstance(out.result, list) else [out.result]
                    # Expand portfolio-dict proposals: {weights: {sym: w}} → per-symbol dicts
                    node_proposals: list[dict] = []
                    for item in raw_list:
                        if isinstance(item, dict) and "weights" in item and item["weights"]:
                            for sym, w in item["weights"].items():
                                node_proposals.append(
                                    {
                                        "symbol": sym,
                                        "weight": float(w),
                                        "node_id": state.node_id,
                                        "autonomy_level": autonomy_level.value,
                                    }
                                )
                        elif isinstance(item, dict):
                            item.setdefault("node_id", state.node_id)
                            item.setdefault("autonomy_level", autonomy_level.value)
                            node_proposals.append(item)
                    proposals.extend(node_proposals)
                    result.actions_proposed += len(node_proposals)
                if not out.success:
                    result.error_count += 1
            except Exception as exc:
                result.error_count += 1
                log.error("strategy failed for node '%s': %s", state.name, exc)
        result.proposals = proposals
        return proposals

    def _step_adversarial(
        self,
        ctx: CycleContext,
        result: CycleResult,
        proposals: list[dict[str, Any]],
        signal_data: dict[str, Any],
        log: Any,
    ) -> list[dict[str, Any]]:
        """Run adversarial checks via AdversarialPressureV2; return clean proposals."""
        if not proposals:
            return []

        # Intelligence metrics: count proposals evaluated by debate gate
        if self._intel_collector is not None:
            self._intel_collector.increment("debate_gate_invocations", len(proposals))

        # Drop malformed proposals before any further processing
        clean: list[dict[str, Any]] = []
        for proposal in proposals:
            if not isinstance(proposal, dict):
                result.add_adversarial_flag(
                    ring="ring0",
                    severity="warning",
                    reason="malformed_proposal",
                    details={"proposal": str(proposal)[:200]},
                )
                if self._metrics:
                    self._metrics.record_adversarial_flag("ring0", "warning")
            else:
                clean.append(proposal)

        if self._adversarial is None:
            if result.had_critical_flag:
                for node_id in ctx.active_node_ids:
                    self._autonomy.check_and_demote(node_id, da_critical=True)
                    log.warning(
                        "Critical adversarial flag → autonomy demotion for node %s", node_id
                    )
            return clean

        # --- Build variant_outputs for Ring 1 ---
        # Each signal TYPE from each node is its own variant so that Ring 1 can
        # detect disagreement between (e.g.) the VRP signal vs basic_signals.
        # This ensures meaningful pairwise comparison even with a single node.
        #
        # Signals with confidence=0.0 or stale=True are excluded from Ring 1
        # to avoid spurious disagreement from uninformative / expired data.
        variant_outputs: dict[str, dict[str, float]] = {}
        confident_signal_count = 0
        for node_id, signals in signal_data.items():
            if not isinstance(signals, dict):
                continue
            for sig_name, sig_val in signals.items():
                if sig_name.startswith("_"):
                    continue
                if isinstance(sig_val, dict):
                    # Skip stale signals
                    if sig_val.get("stale") is True:
                        log.debug("Ring1 filter: skipping stale signal '%s'", sig_name)
                        continue
                    # Skip signals in warmup period (new signals, first 20 cycles)
                    if sig_val.get("warmup") is True:
                        log.debug(
                            "Ring1 filter: skipping warmup signal '%s' (calibrating)", sig_name
                        )
                        continue
                    # Skip zero-confidence signals
                    confidence = sig_val.get("confidence")
                    if confidence is not None and float(confidence) == 0.0:
                        log.debug(
                            "Ring1 filter: skipping zero-confidence signal '%s'", sig_name
                        )
                        continue
                    # Per-signal-type variant: flatten its numeric sub-fields
                    flat: dict[str, float] = {}
                    for sub_k, sub_v in sig_val.items():
                        if isinstance(sub_v, (int, float)):
                            flat[sub_k] = float(sub_v)
                        elif isinstance(sub_v, dict):
                            for sk2, sv2 in sub_v.items():
                                if isinstance(sv2, (int, float)):
                                    flat[f"{sub_k}_{sk2}"] = float(sv2)
                    if flat:
                        variant_outputs[f"{node_id}:{sig_name}"] = flat
                        confident_signal_count += 1
                elif isinstance(sig_val, (int, float)):
                    variant_outputs[f"{node_id}:{sig_name}"] = {sig_name: float(sig_val)}
                    confident_signal_count += 1

        # Skip Ring 1 if fewer than 3 confident signals — not enough diversity for
        # meaningful pairwise disagreement detection; avoids false positives on
        # sparse signal cycles.
        _skip_ring1 = confident_signal_count < 3
        if _skip_ring1:
            log.debug(
                "Ring1 skipped: only %d confident signals (need ≥3)", confident_signal_count
            )

        # Fallback: synthesise variant_outputs from proposal weights if no signal data
        if not variant_outputs:
            for i, prop in enumerate(clean):
                nid = prop.get("node_id", f"proposal_{i}")
                variant_outputs[nid] = {"weight": float(prop.get("weight", 0.0))}

        # --- Build current_signals (flat ticker → value) ---
        current_signals: dict[str, float] = {}
        for signals in signal_data.values():
            if not isinstance(signals, dict):
                continue
            for k, v in signals.items():
                if isinstance(v, (int, float)):
                    current_signals[k] = float(v)
                elif isinstance(v, dict) and "composite_signal" in v:
                    current_signals[k] = float(v["composite_signal"])

        # Build actual position weights from proposals so AdversarialPressureV2
        # has real portfolio data for structural challenge evaluation.
        positions: dict[str, float] = {}
        for prop in clean:
            sym = prop.get("symbol") or prop.get("node_id", "unknown")
            positions[sym] = float(prop.get("weight", 0.0))

        strategy_params: dict[str, Any] = {
            "proposal_count": len(clean),
            "regime": ctx.regime,
            # Real proposal data for structural checks
            "positions": positions,
            "total_weight": sum(abs(w) for w in positions.values()),
        }

        # --- Call AdversarialPressureV2 ---
        # When Ring 1 is skipped (< 3 confident signals), pass empty variant_outputs
        # so Ring 1 has nothing to compare and will not fire spuriously.
        try:
            adv_report = self._adversarial.run_v2(
                cycle=ctx.cycle_number,
                variant_outputs={} if _skip_ring1 else variant_outputs,
                current_signals=current_signals,
                strategy_params=strategy_params,
            )
        except Exception as exc:
            result.error_count += 1
            log.error("AdversarialPressureV2.run_v2 failed: %s", exc)
            return clean  # fail-open

        # Intelligence metrics: count ring1 fires
        if self._intel_collector is not None:
            base = adv_report.base_report
            if base.ring1_result and base.ring1_result.flagged:
                self._intel_collector.increment("adversarial_ring1")

        # --- DevilsAdvocateNode structural checks ---
        # Run against real cycle data: proposals, signals, data freshness.
        self._run_da_structural_checks(
            ctx=ctx,
            result=result,
            proposals=clean,
            current_signals=current_signals,
            log=log,
        )

        ring1_result = adv_report.base_report.ring1_result
        ring1_flagged = ring1_result is not None and ring1_result.flagged
        attribution = adv_report.attribution

        # Update the learned block threshold from gate learner (EMA)
        if ctx.cycle_number > 0 and ctx.cycle_number % 10 == 0:
            learned_threshold = self._gate_learner.update_threshold()
            logger.debug(
                "DebateGateLearner updated threshold=%.3f (cycle=%d)",
                learned_threshold,
                ctx.cycle_number,
            )

        if ring1_flagged:
            assert ring1_result is not None  # narrowing for type checker
            outlier_nodes: set[str] = set(attribution.outlier_variants) if attribution else set()
            log.warning(
                "Ring 1 fired [cycle=%d]: max_disagreement=%.3f outliers=%s threshold=%.3f learned=%.3f",
                ctx.cycle_number,
                ring1_result.max_disagreement,
                list(outlier_nodes),
                adv_report.current_threshold,
                self._gate_learner.threshold,
            )
            result.add_adversarial_flag(
                ring="ring1",
                severity="warning",
                reason="ensemble_disagreement",
                details={
                    "max_disagreement": ring1_result.max_disagreement,
                    "disagreeing_variants": ring1_result.disagreeing_variants,
                    "outlier_nodes": list(outlier_nodes),
                    "attribution_confidence": attribution.confidence if attribution else 0.0,
                    "threshold": adv_report.current_threshold,
                },
            )
            if self._metrics:
                self._metrics.record_adversarial_flag("ring1", "warning")

        # --- Apply adversarial decisions to each proposal ---
        approved: list[dict[str, Any]] = []
        for proposal in clean:
            if not ring1_flagged:
                # Proposal passes — record as not blocked for gate learner
                self._gate_learner.record_proposal(
                    blocked=False,
                    cycle_id=ctx.cycle_id,
                    proposal=proposal,
                )
                approved.append(proposal)
                continue

            node_id = proposal.get("node_id", "")
            autonomy_level = proposal.get("autonomy_level", AutonomyLevel.PICO.value)

            if autonomy_level == AutonomyLevel.SUPERVISED.value:
                # SUPERVISED: block the trade — Ring 1 flag requires human review
                log.warning(
                    "SUPERVISED mode: blocking proposal from node %s (Ring 1 fired)", node_id
                )
                result.add_adversarial_flag(
                    ring="ring1",
                    severity="critical",
                    reason="supervised_block",
                    details={"node_id": node_id, "symbol": proposal.get("symbol", "unknown")},
                )
                if self._metrics:
                    self._metrics.record_adversarial_flag("ring1", "critical")
                # Record as blocked for gate learner
                self._gate_learner.record_proposal(
                    blocked=True, cycle_id=ctx.cycle_id, proposal=proposal
                )
                if self._intel_collector is not None:
                    self._intel_collector.increment("debate_gate_blocks")
                # do NOT append — proposal is blocked
            elif autonomy_level == AutonomyLevel.AUTONOMOUS.value:
                # AUTONOMOUS: reduce position size by 50%
                modified = dict(proposal)
                original_weight = float(modified.get("weight", 1.0))
                modified["weight"] = original_weight * 0.5
                modified["adversarial_reduced"] = True
                log.info(
                    "AUTONOMOUS mode: 50%% position reduction for node %s (Ring 1 fired)",
                    node_id,
                )
                self._gate_learner.record_proposal(
                    blocked=False, cycle_id=ctx.cycle_id, proposal=modified
                )
                approved.append(modified)
            else:
                # PICO or unknown: use learned threshold instead of fixed constant
                # This is the key debate gate learning: the threshold shifts based on outcomes
                effective_threshold = max(
                    _ADVERSARIAL_SCORE_THRESHOLD,
                    self._gate_learner.threshold,
                )
                assert ring1_result is not None  # narrowing: ring1_flagged is True
                if ring1_result.max_disagreement > effective_threshold:
                    result.add_adversarial_flag(
                        ring="ring1",
                        severity="critical",
                        reason="high_disagreement_block",
                        details={
                            "node_id": node_id,
                            "symbol": proposal.get("symbol", "unknown"),
                            "max_disagreement": ring1_result.max_disagreement,
                            "score": 1.0 - ring1_result.max_disagreement,
                            "learned_threshold": self._gate_learner.threshold,
                        },
                    )
                    if self._metrics:
                        self._metrics.record_adversarial_flag("ring1", "critical")
                    # Record as blocked for gate learner
                    self._gate_learner.record_proposal(
                        blocked=True, cycle_id=ctx.cycle_id, proposal=proposal
                    )
                    if self._intel_collector is not None:
                        self._intel_collector.increment("debate_gate_blocks")
                    # do NOT append — blocked by adversarial gate
                else:
                    self._gate_learner.record_proposal(
                        blocked=False, cycle_id=ctx.cycle_id, proposal=proposal
                    )
                    approved.append(proposal)

        # Critical flag → demote autonomy for all active nodes
        if result.had_critical_flag:
            for node_id in ctx.active_node_ids:
                self._autonomy.check_and_demote(node_id, da_critical=True)
                log.warning("Critical adversarial flag → autonomy demotion for node %s", node_id)

        return approved

    def _run_da_structural_checks(
        self,
        ctx: CycleContext,
        result: CycleResult,
        proposals: list[dict[str, Any]],
        current_signals: dict[str, float],
        log: Any,
    ) -> None:
        """
        Invoke DevilsAdvocateNode structural checks if one is registered.

        Finds the first active DevilsAdvocateNode and runs its 3 structural
        checks (concentration risk, data staleness, signal correlation) against
        the current cycle's proposals and signals.  Fires adversarial flags for
        any checks that trigger.
        """
        from omega.nodes.devils_advocate import DevilsAdvocateNode

        da_node: DevilsAdvocateNode | None = None
        for node in self.active_nodes:
            if isinstance(node, DevilsAdvocateNode):
                da_node = node
                break

        if da_node is None:
            return

        # Extract data freshness from node state metrics (if available)
        data_freshness_minutes = 0.0
        for node in self.active_nodes:
            state = node.get_state()
            freshness = state.metrics.get("data_freshness_minutes")
            if freshness is not None:
                data_freshness_minutes = max(data_freshness_minutes, float(freshness))

        try:
            structural_results = da_node.run_structural_checks(
                proposals=proposals,
                signals=current_signals,
                data_freshness_minutes=data_freshness_minutes,
            )
        except Exception as exc:
            log.warning("DevilsAdvocateNode structural checks failed: %s", exc)
            return

        for check in structural_results:
            if check.fired:
                severity = "critical" if check.severity == "critical" else "warning"
                log.warning(
                    "DA structural check fired [cycle=%d]: %s — %s",
                    ctx.cycle_number,
                    check.check_name,
                    check.description,
                )
                result.add_adversarial_flag(
                    ring="da_structural",
                    severity=severity,
                    reason=check.check_name,
                    details={
                        "description": check.description,
                        "value": check.value,
                        "threshold": check.threshold,
                    },
                )
                if self._metrics:
                    self._metrics.record_adversarial_flag("da_structural", severity)

    def _step_execute(
        self,
        ctx: CycleContext,
        result: CycleResult,
        proposals: list[dict[str, Any]],
        log: Any,
        market_data: dict[str, Any] | None = None,
    ) -> None:
        """Execute approved trade proposals via PaperTradingEngine (if wired in)."""
        if not proposals:
            return
        result.actions_executed = len(proposals)
        log.debug("Executing %d proposals (cycle %d)", len(proposals), ctx.cycle_number)

        if self._paper_trading is not None:
            try:
                # Also check node._last_market_data as a fallback for real prices
                node_market_data: dict[str, Any] = {}
                for node in self.active_nodes:
                    node_market_data.update(getattr(node, "_last_market_data", {}))
                combined_market_data = {**(market_data or {}), **node_market_data}

                if not proposals:
                    # No new proposals — still run mark_to_market so stale positions close
                    self._paper_trading.mark_to_market(
                        combined_market_data,
                        ctx.cycle_number,
                        cycle_id=ctx.cycle_id,
                    )
                    return

                # Track closed trades before execution so we can diff after
                closed_before = len(self._paper_trading.closed_trades)

                executed = self._paper_trading.execute_proposals(
                    proposals,
                    market_data=combined_market_data,
                    cycle_id=ctx.cycle_id,
                    current_cycle=ctx.cycle_number,
                )
                log.info(
                    "PaperTrading: executed %d trades (cycle %d)",
                    len(executed),
                    ctx.cycle_number,
                )
                # ── Feedback loop: record closed trade outcomes ───────────
                # Feed PnL back into:
                #   1. DebateGateLearner — so it can adjust the block threshold
                #   2. VictoriaNode.record_trade_outcome — updates CrossNodeMemory
                import contextlib

                newly_closed = self._paper_trading.closed_trades[closed_before:]
                if newly_closed:
                    for trade in newly_closed:
                        pnl = float(trade.get("pnl", 0.0))
                        trade_cycle_id = trade.get("cycle_id", "")
                        sym = str(trade.get("sym") or trade.get("symbol", ""))
                        size = float(trade.get("size", 1.0))
                        if trade_cycle_id:
                            with contextlib.suppress(Exception):
                                self._gate_learner.record_outcome(trade_cycle_id, pnl)
                        for node in self.active_nodes:
                            if hasattr(node, "record_trade_outcome") and sym:
                                with contextlib.suppress(Exception):
                                    node.record_trade_outcome(sym, pnl, size)
            except Exception as exc:
                log.warning("PaperTrading execution failed: %s", exc)

    # ------------------------------------------------------------------
    # Post-cycle: improvement, consolidation, metrics, regime
    # ------------------------------------------------------------------

    def _post_cycle(
        self,
        ctx: CycleContext,
        result: CycleResult,
        log: Any,
    ) -> None:
        cycle_num = ctx.cycle_number

        # Regime transition check
        regime_now = self._regime_handler.current_regime
        if regime_now != ctx.regime:
            result.regime_transition = True
            log.info("Regime transition detected: %s → %s", ctx.regime, regime_now)
            # Apply regime-modified signal weights via regime_handler

        # TPE improvement scheduling
        if cycle_num > 0 and cycle_num % self.IMPROVEMENT_INTERVAL == 0:
            self._try_improvement(ctx, result, log)

        # Memory consolidation
        if (
            self._consolidation is not None
            and cycle_num > 0
            and cycle_num % self.CONSOLIDATION_INTERVAL == 0
        ):
            try:
                self._consolidation.consolidate()
                log.info("Memory consolidation triggered at cycle %d", cycle_num)
            except Exception as exc:
                log.warning("Memory consolidation failed: %s", exc)

        # Autonomy cycle recording
        for node in self.active_nodes:
            state = node.get_state()
            nid = state.node_id
            health_rec = self._node_health.get(nid)
            if health_rec:
                # Pass full metrics dict — autonomy controller maps to its
                # configured PerformanceMetric list generically.
                cycle_metrics = dict(result.metrics)
                if "sharpe" not in cycle_metrics:
                    cycle_metrics["sharpe"] = health_rec.avg_health
                self._autonomy.record_cycle(nid, metrics=cycle_metrics)
                # Attempt promotion every 10 cycles
                if cycle_num % 10 == 0:
                    transition = self._autonomy.promote_node(nid)
                    if transition.changed:
                        log.info(
                            "Autonomy promotion: node %s → %s",
                            nid,
                            transition.new_level.value,
                        )

        # Direct improve() trigger every 10 cycles — fires for all active nodes,
        # bypassing TPE gating so nodes can self-upgrade internal heuristics
        # (e.g. SignalGenerationNode unlocks RSI/MACD/Bollinger when called here).
        if cycle_num > 0 and cycle_num % 10 == 0:
            cycle_metrics = dict(result.metrics)
            for node in self.active_nodes:
                if hasattr(node, "improve"):
                    try:
                        node.improve(cycle_metrics)
                    except Exception as exc:
                        log.warning("Direct improve() failed for %s: %s", node, exc)

        # Semantic memory consolidation every 50 cycles — distils episodic
        # memories into long-term patterns (LLM-assisted or rule-based fallback).
        if cycle_num > 0 and cycle_num % 50 == 0:
            try:
                out = self._semantic_memory.execute(
                    NodeInput(
                        action="build_semantic",
                        parameters={},
                        context={"cycle": cycle_num},
                    )
                )
                if out.success and isinstance(out.result, dict):
                    log.info(
                        "Semantic memory consolidation cycle=%d: %s",
                        cycle_num,
                        out.result,
                    )
            except Exception as exc:
                log.warning("Semantic memory consolidation failed: %s", exc)

        # Emit Prometheus metrics
        if self._metrics:
            self._metrics.record_heartbeat(result.duration_seconds)
            self._metrics.update_signals({f"cycle_{cycle_num}": float(result.signals_generated)})

        # Intelligence metrics: aggregate brain calls from node results, flush
        if self._intel_collector is not None:
            for _node_data in result.node_results.values():
                if isinstance(_node_data, dict):
                    bc = _node_data.get("brain_calls", 0)
                    if bc:
                        self._intel_collector.increment("brain_calls", int(bc))
                    bl = _node_data.get("brain_latency_ms")
                    if bl is not None:
                        self._intel_collector.record("brain_latency_ms", int(bl))
                    bt = _node_data.get("brain_tokens_used")
                    if bt is not None:
                        self._intel_collector.record("brain_tokens_used", int(bt))
                    bp = _node_data.get("brain_provider")
                    if bp:
                        self._intel_collector.record("brain_provider", str(bp))
            # Top-level result metrics (paper trading pathway)
            if result.metrics.get("brain_calls"):
                self._intel_collector.record("brain_calls", int(result.metrics["brain_calls"]))
            self._intel_collector.flush(cycle=ctx.cycle_number)

    def _try_improvement(
        self,
        ctx: CycleContext,
        result: CycleResult,
        log: Any,
    ) -> None:
        """Trigger TPE improvement for eligible nodes."""
        for node in self.active_nodes:
            state = node.get_state()
            nid = state.node_id
            if not self._improvement_engine.is_registered(nid):
                continue
            # Check scheduler — auto-register with a short interval if not yet tracked
            try:
                if nid not in self._improvement_scheduler.registered_nodes():
                    from omega.core.improvement_scheduler import NodeScheduleConfig

                    self._improvement_scheduler.register(
                        nid,
                        NodeScheduleConfig(node_id=nid, interval_seconds=30.0),
                        run_immediately=True,
                    )
                due = self._improvement_scheduler.due_nodes()
                if nid not in due:
                    continue
            except Exception:
                pass  # scheduler optional
            try:
                # Build context with real cycle metrics so TPE can use actual
                # Sharpe ratio and error rate rather than synthetic scores.
                health_rec = self._node_health.get(nid)
                real_metrics = dict(result.metrics)
                if health_rec:
                    real_metrics.setdefault("error_rate", 1.0 - health_rec.avg_health)
                # Sharpe from recent history
                recent = self._history.recent(30)
                if len(recent) >= 5:
                    cycle_sharpes = [
                        float(c.metrics.get("sharpe", 0.0))
                        for c in recent
                        if hasattr(c, "metrics")
                    ]
                    if cycle_sharpes:
                        mean_s = sum(cycle_sharpes) / len(cycle_sharpes)
                        real_metrics.setdefault("sharpe", mean_s)

                if self._intel_collector is not None:
                    self._intel_collector.increment("improve_calls")

                params = self._improvement_engine.propose(nid)
                trial = self._improvement_engine.evaluate_and_record(
                    nid,
                    params,
                    context={
                        "regime": ctx.regime,
                        "cycle": ctx.cycle_number,
                        **real_metrics,
                    },
                    cycle=ctx.cycle_number,
                )
                result.improvement_proposed = True
                log.info(
                    "TPE improvement for node %s: score=%.4f accepted=%s params=%s",
                    nid,
                    trial.score,
                    trial.accepted,
                    params,
                )
                # Intelligence metrics: track accept/reject
                if self._intel_collector is not None:
                    if trial.accepted:
                        self._intel_collector.increment("improve_accepted")
                    else:
                        self._intel_collector.increment("improve_rejected")

                # Apply accepted params to the live node so improvements take effect.
                if trial.accepted:
                    try:
                        node.improve(params)
                        log.info("Applied improved params to node %s: %s", nid, params)
                        # Persist improvement_applied=1 so it's queryable
                        if self._store is not None and hasattr(self._store, "record_improvement"):
                            self._store.record_improvement(
                                node_id=nid,
                                node_name=state.name,
                                from_version="pre-tpe",
                                to_version=f"tpe-{trial.trial_id[:8]}",
                                before_metrics={},
                                after_metrics={
                                    "params": str(params),
                                    "score": round(trial.score or 0.0, 6),
                                    "improvement_applied": 1,
                                },
                                triggered_by="tpe",
                                cycle=ctx.cycle_number,
                            )
                    except Exception as apply_exc:
                        log.warning("apply_params via improve() failed for %s: %s", nid, apply_exc)
                if self._metrics:
                    self._metrics.record_improvement(
                        result="improved" if trial.accepted else "unchanged"
                    )
            except Exception as exc:
                log.warning("TPE improvement failed for node %s: %s", nid, exc)

    # ------------------------------------------------------------------
    # Introspection / reporting
    # ------------------------------------------------------------------

    @property
    def history(self) -> CycleHistory:
        return self._history

    @property
    def cycle_number(self) -> int:
        return self._cycle_number

    def node_summary(self) -> list[dict[str, Any]]:
        """Return health/autonomy summary for all registered nodes."""
        rows = []
        for node in self._registry.all_nodes():
            state = node.get_state()
            nid = state.node_id
            health_rec = self._node_health.get(nid)
            rows.append(
                {
                    "node_id": nid,
                    "name": state.name,
                    "active": nid in self._active_node_ids,
                    "health": state.health,
                    "avg_health": health_rec.avg_health if health_rec else state.health,
                    "autonomy": self._autonomy.get_level(nid).value,
                    "capabilities": state.capabilities,
                }
            )
        return rows
