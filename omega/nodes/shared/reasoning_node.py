"""
omega.nodes.shared.reasoning_node
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
ReasoningNode — general-purpose LLM reasoning between raw signals and action.

The "thinking" layer between raw signals and decision.  Takes a question,
current context, and relevant past memories, then uses the brain (QUICK tier)
to produce a structured decision with rationale.

Wire into Victoria (pre-portfolio) and Polymarket (pre-edge) as an optional
reasoning step that improves decisions using cross-project memory.

Usage::
    node = ReasoningNode(brain_config=BrainConfig(provider="anthropic"))
    result = node.reason_with_memory(
        question="Should we increase position size given current regime?",
        context={"regime": "high_vol", "conviction": 0.72, "signals": {...}},
        domain="crypto",
        options=["increase", "hold", "reduce"],
    )
    # result = {"decision": "hold", "rationale": "...", "confidence": 0.65}
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, ClassVar

from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.shared.reasoning_node")


class ReasoningNode(Node):
    """
    General-purpose reasoning node.

    Capabilities: ``reason``, ``pre_decision``

    Input parameters (``reason`` action)
    ------------------------------------
    question  (str)  : The question to reason about
    context   (dict) : Current system state / signals
    memories  (list) : Relevant past insights (from MemoryBus / MemoryKernel)
    options   (list) : Possible actions/decisions (optional)
    domain    (str)  : Domain hint for LLM (e.g. "crypto", "polymarket")
    """

    skill_tags: ClassVar[list[str]] = ["reasoning", "decision", "quant"]

    def __init__(self, node_id: str | None = None, brain_config: Any = None) -> None:
        super().__init__(brain_config=brain_config)
        self._node_id = node_id or str(uuid.uuid4())
        self._version = "1.0"
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._reasoning_calls = 0
        self._mem_bus: Any = None

    # ------------------------------------------------------------------
    # Node interface
    # ------------------------------------------------------------------

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._node_id,
            name="ReasoningNode",
            version=self._version,
            health=max(0.0, 1.0 - self._error_count / max(1, self._execution_count)),
            capabilities=self.get_capabilities(),
            metrics=self.evaluate(),
            metadata={"reasoning_calls": self._reasoning_calls},
        )

    def get_capabilities(self) -> list[str]:
        return ["reason", "pre_decision"]

    def describe(self) -> str:
        return (
            "ReasoningNode: general-purpose reasoning layer between raw signals and action. "
            "Takes question + context + memories, uses brain (LLM, QUICK tier) to produce "
            "a structured decision with rationale and confidence."
        )

    def execute(self, inp: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1
        action = inp.action.lower()

        try:
            if action in ("reason", "pre_decision"):
                result = self._do_reason(inp)
            else:
                raise ValueError(f"ReasoningNode: unknown action '{action}'")
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._error_count += 1
            self._total_latency_ms += elapsed
            logger.warning("ReasoningNode error: %s", exc)
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
            metrics={"latency_ms": elapsed, "reasoning_calls": float(self._reasoning_calls)},
        )

    def evaluate(self) -> dict[str, float]:
        return {
            "error_rate": self._error_count / max(1, self._execution_count),
            "avg_latency_ms": self._total_latency_ms / max(1, self._execution_count),
            "reasoning_calls": float(self._reasoning_calls),
            "execution_count": float(self._execution_count),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        return False

    # ------------------------------------------------------------------
    # Convenience: reason with memory bus
    # ------------------------------------------------------------------

    def reason_with_memory(
        self,
        question: str,
        context: dict[str, Any],
        domain: str = "crypto",
        options: list[str] | None = None,
        min_bus_relevance: float = 0.3,
    ) -> dict[str, Any]:
        """
        Fetch relevant memories from the shared MemoryBus and reason.

        Returns dict with: decision, rationale, confidence, key_factor, memories_used.
        """
        memories: list[dict] = []
        bus = self._get_mem_bus()
        if bus is not None:
            try:
                from omega.core.memory_bus import MemoryType

                memories = bus.read(
                    memory_types=[
                        MemoryType.REGIME_INSIGHT,
                        MemoryType.SIGNAL_PATTERN,
                        MemoryType.RISK_WARNING,
                    ],
                    min_relevance=min_bus_relevance,
                    limit=5,
                )
            except Exception as exc:
                logger.debug("MemoryBus read failed: %s", exc)

        inp = NodeInput(
            action="reason",
            parameters={
                "question": question,
                "context": context,
                "memories": memories,
                "options": options or [],
                "domain": domain,
            },
        )
        out = self.execute(inp)
        return out.result or {
            "decision": "pass",
            "rationale": "reasoning unavailable",
            "confidence": 0.0,
        }

    # ------------------------------------------------------------------
    # Core reasoning logic
    # ------------------------------------------------------------------

    def _do_reason(self, inp: NodeInput) -> dict[str, Any]:
        from omega.core.brain import ModelTier

        question = str(inp.parameters.get("question", "What should we do?"))
        context = inp.parameters.get("context", {})
        memories: list[dict] = inp.parameters.get("memories", [])
        options: list[str] = inp.parameters.get("options", [])
        domain = str(inp.parameters.get("domain", "crypto"))

        self._reasoning_calls += 1

        brain = self.brain
        if brain is None or not brain.is_available():
            return self._rule_based_reason(question, context, options)

        # Format memory context
        mem_lines: list[str] = []
        for m in memories[:5]:
            mtype = m.get("memory_type", "")
            content = m.get("content", "")
            rel = m.get("relevance_score", 0.0)
            mem_lines.append(f"  [{mtype}](rel={rel:.2f}) {content}")

        memory_block = (
            "Relevant past memories:\n" + "\n".join(mem_lines)
            if mem_lines
            else "No relevant memories found."
        )
        options_str = f"Options to choose from: {', '.join(options)}" if options else ""
        ctx_str = json.dumps(context, default=str)[:500]

        prompt = (
            f"Domain: {domain}\n"
            f"Question: {question}\n\n"
            f"Current context:\n{ctx_str}\n\n"
            f"{memory_block}\n\n"
            f"{options_str}\n\n"
            f"Reason through this concisely using the memories as evidence. "
            f"Output JSON only:\n"
            f'{{"decision": "<answer>", "rationale": "<1-2 sentences>", '
            f'"confidence": <0.0-1.0>, "key_factor": "<most important factor>"}}'
        )

        try:
            raw = brain.consult(prompt, tier=ModelTier.QUICK)
        except Exception as exc:
            logger.debug("LLM reasoning call failed: %s", exc)
            return self._rule_based_reason(question, context, options)

        if not raw:
            return self._rule_based_reason(question, context, options)

        # Parse JSON response
        try:
            cleaned = raw.strip()
            if "```" in cleaned:
                for part in cleaned.split("```"):
                    part = part.strip().lstrip("json").strip()
                    if part.startswith("{"):
                        cleaned = part
                        break
            r = json.loads(cleaned)
            return {
                "decision": str(r.get("decision", "pass")),
                "rationale": str(r.get("rationale", "")),
                "confidence": float(r.get("confidence", 0.5)),
                "key_factor": str(r.get("key_factor", "")),
                "memories_used": len(memories),
            }
        except (json.JSONDecodeError, TypeError):
            return {
                "decision": raw[:100].strip(),
                "rationale": raw[:200].strip(),
                "confidence": 0.5,
                "key_factor": "",
                "memories_used": len(memories),
            }

    @staticmethod
    def _rule_based_reason(
        question: str, context: dict[str, Any], options: list[str]
    ) -> dict[str, Any]:
        return {
            "decision": options[0] if options else "pass",
            "rationale": "No brain configured — defaulting to first option or pass.",
            "confidence": 0.1,
            "key_factor": "no_brain",
            "memories_used": 0,
        }

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
