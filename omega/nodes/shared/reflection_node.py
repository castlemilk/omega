"""
omega.nodes.shared.reflection_node
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
ReflectionNode — per-cycle LLM reflection on trading outcomes.

After each Victoria trading cycle, uses the brain (QUICK tier) to reflect on:
  - Signal values and conviction
  - Trade result (win / loss / hold)
  - Market context (regime, VRP)

Stores the reflection as:
  1. An episodic memory in ``episodes`` (MemoryKernel, namespace="victoria")
  2. A regime/signal insight in ``shared_memory`` (MemoryBus, for cross-project use)

The importance of each episode is scaled by conviction x rating so
high-surprise, high-conviction reflections stay alive longer before decay.

Usage (standalone)::
    node = ReflectionNode(brain_config=BrainConfig(provider="anthropic"))
    out = node.execute(NodeInput(
        action="reflect",
        parameters={
            "cycle": 7,
            "signals": {...},   # from _do_compute_signals
            "trade_result": "win",
            "regime": "high_vol",
            "conviction": 0.72,
        },
        context={"cycle": 7},
    ))
    # out.result = {"episode_id": "...", "lesson": "...", "rating": 4}
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, ClassVar

from omega.core.actions import NodeAction
from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.shared.reflection_node")


class ReflectionNode(Node):
    """
    Per-cycle reflection node.

    Capabilities: ``reflect``, ``memory_reflect``, ``memory``

    Input parameters (``reflect`` / ``memory_reflect`` action)
    -----------------------------------------------------------
    cycle         (int)   : heartbeat cycle number
    signals       (dict)  : signal dict from _do_compute_signals
    trade_result  (str)   : "win" | "loss" | "hold"  (default "hold")
    regime        (str)   : current market regime label
    conviction    (float) : composite conviction / quality score (0-1)
    market_context (dict) : extra market data (optional)
    """

    skill_tags: ClassVar[list[str]] = ["memory", "reflection", "quant"]

    def __init__(self, node_id: str | None = None, brain_config: Any = None) -> None:
        super().__init__(brain_config=brain_config)
        self._node_id = node_id or str(uuid.uuid4())
        self._version = "1.0"
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._reflections_stored = 0
        self._mem_kernel: Any = None
        self._mem_bus: Any = None

    # ------------------------------------------------------------------
    # Node interface
    # ------------------------------------------------------------------

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._node_id,
            name="ReflectionNode",
            version=self._version,
            health=max(0.0, 1.0 - self._error_count / max(1, self._execution_count)),
            capabilities=self.get_capabilities(),
            metrics=self.evaluate(),
            metadata={"reflections_stored": self._reflections_stored},
        )

    def get_capabilities(self) -> list[str]:
        return ["reflect", "memory_reflect", NodeAction.MEMORY.value]

    def describe(self) -> str:
        return (
            "ReflectionNode: after each trading cycle uses LLM (QUICK tier) to reflect on "
            "signal values, conviction, and trade outcomes. Stores episodic memories with "
            "importance ratings and writes regime insights to the cross-project memory bus."
        )

    def execute(self, inp: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1
        action = inp.action.lower().replace("-", "_")

        try:
            if action in ("reflect", "memory_reflect", NodeAction.MEMORY.value, "memory"):
                result = self._do_reflect(inp)
            else:
                raise ValueError(f"ReflectionNode: unknown action '{action}'")
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._error_count += 1
            self._total_latency_ms += elapsed
            logger.warning("ReflectionNode.execute error: %s", exc)
            return NodeOutput(
                request_id=inp.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": elapsed},
            )

        elapsed = (time.perf_counter() - t0) * 1000
        self._total_latency_ms += elapsed
        return NodeOutput(
            request_id=inp.request_id,
            success=True,
            result=result,
            metrics={
                "latency_ms": elapsed,
                "reflections_stored": float(self._reflections_stored),
            },
        )

    def evaluate(self) -> dict[str, float]:
        return {
            "error_rate": self._error_count / max(1, self._execution_count),
            "avg_latency_ms": self._total_latency_ms / max(1, self._execution_count),
            "reflections_stored": float(self._reflections_stored),
            "execution_count": float(self._execution_count),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        return False

    # ------------------------------------------------------------------
    # Core reflection logic
    # ------------------------------------------------------------------

    def _do_reflect(self, inp: NodeInput) -> dict[str, Any]:
        from omega.core.brain import ModelTier

        cycle = int(inp.context.get("cycle", inp.parameters.get("cycle", 0)))
        signals: dict[str, Any] = inp.parameters.get("signals", {})
        trade_result = str(inp.parameters.get("trade_result", "hold"))
        regime = str(inp.parameters.get("regime", signals.get("_regime", "default")))
        conviction = float(inp.parameters.get("conviction", signals.get("_quality_score", 0.0)))
        market_context: dict[str, Any] = inp.parameters.get("market_context", {})

        signal_summary = self._summarise_signals(signals)

        reflection_text, lesson, rating = self._llm_reflect(
            cycle=cycle,
            signal_summary=signal_summary,
            trade_result=trade_result,
            regime=regime,
            conviction=conviction,
            market_context=market_context,
            tier=ModelTier.QUICK,
        )

        episode_id = self._store_episode(
            cycle=cycle,
            signal_summary=signal_summary,
            trade_result=trade_result,
            regime=regime,
            conviction=conviction,
            reflection_text=reflection_text,
            lesson=lesson,
            rating=rating,
        )

        # Write cross-project insight to the memory bus for Polymarket
        self._write_to_bus(
            cycle=cycle,
            regime=regime,
            signal_summary=signal_summary,
            trade_result=trade_result,
            conviction=conviction,
            lesson=lesson,
        )

        self._reflections_stored += 1
        logger.info(
            "cycle=%d reflect: result=%s regime=%s conviction=%.2f rating=%d | %s",
            cycle,
            trade_result,
            regime,
            conviction,
            rating,
            lesson[:80] if lesson else "(no lesson)",
        )

        return {
            "episode_id": episode_id,
            "reflection_text": reflection_text,
            "lesson": lesson,
            "rating": rating,
            "cycle": cycle,
        }

    # ------------------------------------------------------------------
    # Signal summary
    # ------------------------------------------------------------------

    @staticmethod
    def _summarise_signals(signals: dict[str, Any]) -> str:
        parts = []
        for name, val in signals.items():
            if name.startswith("_") or not isinstance(val, dict):
                continue
            value = val.get("value", 0.0)
            conf = val.get("confidence", 0.0)
            rtag = val.get("regime_tag", "")
            suffix = f",{rtag}" if rtag else ""
            parts.append(f"{name}={value:+.3f}(c={conf:.2f}{suffix})")
        return "; ".join(parts[:8]) if parts else "no signals"

    # ------------------------------------------------------------------
    # LLM reflection
    # ------------------------------------------------------------------

    def _llm_reflect(
        self,
        cycle: int,
        signal_summary: str,
        trade_result: str,
        regime: str,
        conviction: float,
        market_context: dict[str, Any],
        tier: Any,
    ) -> tuple[str, str, int]:
        """Call the brain for LLM reflection. Returns (reflection_text, lesson, rating 1-5)."""
        brain = self.brain
        if brain is None or not brain.is_available():
            return self._rule_based_reflect(
                cycle, signal_summary, trade_result, regime, conviction
            )

        ctx_str = json.dumps(market_context, default=str)[:300]
        prompt = (
            f"You are reviewing a completed crypto trading cycle.\n\n"
            f"Cycle: {cycle}  |  Regime: {regime}  |  Conviction: {conviction:.3f}  "
            f"|  Result: {trade_result}\n"
            f"Signals: {signal_summary}\n"
            f"Market context: {ctx_str}\n\n"
            f"Given these signals produced conviction={conviction:.3f} which led to a "
            f"'{trade_result}' outcome, answer:\n"
            f"1. In 1-2 sentences, what pattern does this suggest about the {regime} regime?\n"
            f"2. LESSON: one actionable lesson ≤15 words.\n"
            f"3. RATING: 1-5 (5=very surprising/useful, 1=obvious/useless).\n"
            f"Be specific about signal names and magnitudes."
        )

        try:
            raw = brain.consult(prompt, tier=tier)
        except Exception as exc:
            logger.debug("LLM reflection call failed: %s", exc)
            return self._rule_based_reflect(
                cycle, signal_summary, trade_result, regime, conviction
            )

        if not raw:
            return self._rule_based_reflect(
                cycle, signal_summary, trade_result, regime, conviction
            )

        reflection_text = raw.strip()
        lesson = ""
        rating = 3

        for line in raw.splitlines():
            s = line.strip()
            if s.upper().startswith("LESSON:"):
                lesson = s.split(":", 1)[-1].strip()
            elif s.upper().startswith("RATING:"):
                try:
                    rating = max(1, min(5, int(s.split(":", 1)[-1].strip()[0])))
                except (ValueError, IndexError):
                    rating = 3

        if not lesson:
            lesson = reflection_text[:80]

        return reflection_text, lesson, rating

    @staticmethod
    def _rule_based_reflect(
        cycle: int,
        signal_summary: str,
        trade_result: str,
        regime: str,
        conviction: float,
    ) -> tuple[str, str, int]:
        """Rule-based fallback when brain is unavailable or returns nothing."""
        quality = (
            "high conviction"
            if conviction >= 0.7
            else "moderate conviction"
            if conviction >= 0.4
            else "low conviction"
        )
        rating = 3 if conviction >= 0.7 else 2

        outcome_note = {
            "win": "successful outcome",
            "loss": "loss — review signal alignment",
            "hold": "held position (no trade)",
        }.get(trade_result, trade_result)

        reflection_text = (
            f"Cycle {cycle}: {quality} ({conviction:.2f}) in {regime} regime. "
            f"Signals: {signal_summary[:120]}. Outcome: {outcome_note}."
        )
        lesson = f"{quality} {regime} → {outcome_note}"
        return reflection_text, lesson, rating

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _store_episode(
        self,
        cycle: int,
        signal_summary: str,
        trade_result: str,
        regime: str,
        conviction: float,
        reflection_text: str,
        lesson: str,
        rating: int,
    ) -> str:
        mem_kernel = self._get_mem_kernel()
        if mem_kernel is None:
            return ""

        # Scale importance: high conviction + high rating → persists longer
        importance = min(1.0, 0.3 + conviction * 0.45 + (rating - 1) * 0.05)
        tags = ["reflection", f"cycle_{cycle}", regime, trade_result]

        try:
            episode_id = mem_kernel.store_episode(
                event_type="trading_reflection",
                content={
                    "cycle": cycle,
                    "signal_summary": signal_summary,
                    "trade_result": trade_result,
                    "regime": regime,
                    "conviction": conviction,
                    "reflection_text": reflection_text,
                    "lesson": lesson,
                    "rating": rating,
                },
                tags=tags,
                importance=importance,
                cycle=cycle,
                namespace="victoria",
            )
            mem_kernel.rate_memory(episode_id, rating / 5.0, namespace="victoria")
            return str(episode_id)
        except Exception as exc:
            logger.debug("store_episode failed: %s", exc)
            return ""

    def _write_to_bus(
        self,
        cycle: int,
        regime: str,
        signal_summary: str,
        trade_result: str,
        conviction: float,
        lesson: str,
    ) -> None:
        """Write cross-project insight to MemoryBus for Polymarket to read."""
        bus = self._get_mem_bus()
        if bus is None:
            return
        from omega.core.memory_bus import MemoryType

        # Only write sufficiently informative memories
        if conviction < 0.2 and trade_result == "hold":
            return

        mtype = MemoryType.REGIME_INSIGHT if conviction > 0.5 else MemoryType.SIGNAL_PATTERN
        content = (
            f"Cycle {cycle}: {regime} regime, conviction={conviction:.2f}, "
            f"result={trade_result}. {lesson}"
        )
        try:
            bus.write(
                project_source="victoria",
                memory_type=mtype,
                content=content,
                relevance_score=min(1.0, max(0.1, conviction)),
                cycle=cycle,
                ttl_seconds=86400 * 7,  # 7-day TTL
            )
        except Exception as exc:
            logger.debug("MemoryBus write failed: %s", exc)

    # ------------------------------------------------------------------
    # Lazy inits
    # ------------------------------------------------------------------

    def _get_mem_kernel(self) -> Any:
        if self._mem_kernel is not None:
            return self._mem_kernel
        import os

        if not os.environ.get("DATABASE_URL"):
            return None
        try:
            from omega.core.memory import MemoryKernel

            self._mem_kernel = MemoryKernel()
        except Exception as exc:
            logger.debug("MemoryKernel init failed: %s", exc)
        return self._mem_kernel

    def _get_mem_bus(self) -> Any:
        if self._mem_bus is not None:
            return self._mem_bus
        import os

        if not os.environ.get("DATABASE_URL"):
            return None
        try:
            from omega.core.memory_bus import MemoryBus

            self._mem_bus = MemoryBus()
        except Exception as exc:
            logger.debug("MemoryBus init failed: %s", exc)
        return self._mem_bus
