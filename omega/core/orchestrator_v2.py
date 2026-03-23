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
from typing import Any

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

logger = logging.getLogger("omega.orchestrator_v2")

# Proposals with adversarial disagreement score above this threshold (score = 1 - max_disagreement < 0.6)
# are blocked even in PICO mode.  Prevents rubber-stamping all proposals regardless of signal quality.
_ADVERSARIAL_SCORE_THRESHOLD = 0.4


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
    IMPROVEMENT_INTERVAL = 50
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
        self._adversarial = adversarial if adversarial is not None else AdversarialPressureV2()
        self._consolidation = memory_consolidation
        self._metrics = metrics_exporter

        self._history = CycleHistory(max_size=history_size)
        self._cycle_number: int = 0
        self._running: bool = False

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
                def _make_handler(n: Any = node, capability: str = cap) -> Any:
                    def _handler(req: ExecuteStepRequest) -> ExecuteStepResponse:
                        import json as _json

                        inp = NodeInput(
                            action=req.step_name.lower() or capability.lower(),
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
                        return ExecuteStepResponse(
                            success=out.success,
                            error_text="; ".join(out.errors) if out.errors else "",
                            metrics={
                                k: float(v)
                                for k, v in out.metrics.items()
                                if isinstance(v, (int, float))
                            },
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
        logger.info("Registered node '%s' (id=%s, activate=%s)", state.name, node_id, activate)
        return node_id

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
        goal_node_ids: set[str] | None = None,
    ) -> CycleHistory:
        """
        Run the main orchestration loop.

        Parameters
        ----------
        max_cycles    : Stop after this many cycles (None = run forever).
        sleep_seconds : Time to sleep between cycles (0 = tight loop).
        goal_node_ids : If provided, reconcile active nodes to this set each cycle.

        Returns the full CycleHistory.
        """
        self._running = True
        logger.info("Starting OmegaOrchestrator '%s' (max_cycles=%s)", self.name, max_cycles)
        try:
            while self._running:
                if max_cycles is not None and self._cycle_number >= max_cycles:
                    break
                self.run_one_cycle(goal_node_ids=goal_node_ids)
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
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

        # 3-7. Execute pipeline
        poll_outputs = self._step_data_poll(ctx, result, log)
        signal_data = self._step_signals(ctx, result, poll_outputs, log)
        proposals = self._step_strategy(ctx, result, signal_data, log)
        clean_proposals = self._step_adversarial(ctx, result, proposals, signal_data, log)
        self._step_execute(ctx, result, clean_proposals, log)

        # 8. Post-cycle
        result.duration_seconds = time.perf_counter() - t_start
        self._post_cycle(ctx, result, log)

        self._history.append(result)
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
            if (
                "poll" not in node.get_capabilities()
                and "fetch_data" not in node.get_capabilities()
            ):
                continue
            action = "poll" if "poll" in node.get_capabilities() else "fetch_data"
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
            if "compute_signals" not in node.get_capabilities():
                continue
            poll_out = poll_outputs.get(state.node_id)
            market_data = poll_out.result if poll_out and poll_out.success else {}
            inp = NodeInput(
                action="compute_signals",
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
            if "construct_portfolio" not in node.get_capabilities():
                continue

            # Check autonomy: PICO mode = deterministic strategy only
            autonomy_level = self._autonomy.get_level(state.node_id)
            inp = NodeInput(
                action="construct_portfolio",
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
                    node_proposals = out.result if isinstance(out.result, list) else [out.result]
                    for prop in node_proposals:
                        if isinstance(prop, dict):
                            prop.setdefault("node_id", state.node_id)
                            prop.setdefault("autonomy_level", autonomy_level.value)
                    proposals.extend(p for p in node_proposals if isinstance(p, dict))
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
        # Each signal-producing node is a "variant"; outputs are its numeric signals.
        variant_outputs: dict[str, dict[str, float]] = {}
        for node_id, signals in signal_data.items():
            if not isinstance(signals, dict):
                continue
            flat: dict[str, float] = {}
            for k, v in signals.items():
                if isinstance(v, (int, float)):
                    flat[k] = float(v)
                elif isinstance(v, dict):
                    for sub_k, sub_v in v.items():
                        if isinstance(sub_v, (int, float)):
                            flat[f"{k}_{sub_k}"] = float(sub_v)
            if flat:
                variant_outputs[node_id] = flat

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

        strategy_params: dict[str, Any] = {
            "proposal_count": len(clean),
            "regime": ctx.regime,
        }

        # --- Call AdversarialPressureV2 ---
        try:
            adv_report = self._adversarial.run_v2(
                cycle=ctx.cycle_number,
                variant_outputs=variant_outputs,
                current_signals=current_signals,
                strategy_params=strategy_params,
            )
        except Exception as exc:
            result.error_count += 1
            log.error("AdversarialPressureV2.run_v2 failed: %s", exc)
            return clean  # fail-open

        ring1_result = adv_report.base_report.ring1_result
        ring1_flagged = ring1_result is not None and ring1_result.flagged
        attribution = adv_report.attribution

        if ring1_flagged:
            assert ring1_result is not None  # narrowing for type checker
            outlier_nodes: set[str] = set(attribution.outlier_variants) if attribution else set()
            log.warning(
                "Ring 1 fired [cycle=%d]: max_disagreement=%.3f outliers=%s threshold=%.3f",
                ctx.cycle_number,
                ring1_result.max_disagreement,
                list(outlier_nodes),
                adv_report.current_threshold,
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
                approved.append(modified)
            else:
                # PICO or unknown: block only when disagreement is extreme (score < 0.6).
                # Moderate disagreement (score >= 0.6) is acceptable for deterministic strategies.
                assert ring1_result is not None  # narrowing: ring1_flagged is True
                if ring1_result.max_disagreement > _ADVERSARIAL_SCORE_THRESHOLD:
                    result.add_adversarial_flag(
                        ring="ring1",
                        severity="critical",
                        reason="high_disagreement_block",
                        details={
                            "node_id": node_id,
                            "symbol": proposal.get("symbol", "unknown"),
                            "max_disagreement": ring1_result.max_disagreement,
                            "score": 1.0 - ring1_result.max_disagreement,
                        },
                    )
                    if self._metrics:
                        self._metrics.record_adversarial_flag("ring1", "critical")
                    # do NOT append — blocked by adversarial gate
                else:
                    approved.append(proposal)

        # Critical flag → demote autonomy for all active nodes
        if result.had_critical_flag:
            for node_id in ctx.active_node_ids:
                self._autonomy.check_and_demote(node_id, da_critical=True)
                log.warning("Critical adversarial flag → autonomy demotion for node %s", node_id)

        return approved

    def _step_execute(
        self,
        ctx: CycleContext,
        result: CycleResult,
        proposals: list[dict[str, Any]],
        log: Any,
    ) -> None:
        """Execute approved trade proposals (pluggable execution hook)."""
        if not proposals:
            return
        # Default: log and count; real execution implemented by subclass or injected hook
        result.actions_executed = len(proposals)
        log.debug("Executing %d proposals (cycle %d)", len(proposals), ctx.cycle_number)

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

        # Emit Prometheus metrics
        if self._metrics:
            self._metrics.record_heartbeat(result.duration_seconds)
            self._metrics.update_signals({f"cycle_{cycle_num}": float(result.signals_generated)})

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
            # Check scheduler
            try:
                due = self._improvement_scheduler.due_nodes()
                if nid not in due:
                    continue
            except Exception:
                pass  # scheduler optional
            try:
                params = self._improvement_engine.propose(nid)
                trial = self._improvement_engine.evaluate_and_record(
                    nid,
                    params,
                    context={"regime": ctx.regime, "cycle": ctx.cycle_number},
                    cycle=ctx.cycle_number,
                )
                result.improvement_proposed = True
                log.info(
                    "TPE improvement for node %s: score=%.4f accepted=%s",
                    nid,
                    trial.score,
                    trial.accepted,
                )
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
