"""
omega.nodes.shared.semantic_memory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SemanticMemoryNode — distils episodic memories into long-term patterns.

Every ``review_interval`` cycles (default 50), reviews recent trading_reflection
episodes and uses the brain (QUICK tier) to extract recurring patterns that
become semantic memories (``semantic_memories`` table, namespace="victoria").

LLM output format (one JSON object per line)::
    {"concept": "high_vol_regime_low_ev", "content": "...", "confidence": 0.7, "tags": [...]}

Falls back to rule-based pattern extraction when no brain is configured.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, ClassVar

from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.shared.semantic_memory")

DEFAULT_REVIEW_INTERVAL = 50


class SemanticMemoryNode(Node):
    """
    Periodic semantic pattern extractor.

    Capabilities: ``build_semantic``, ``consolidate_memory``

    Input parameters (``build_semantic`` action)
    -------------------------------------------
    cycle   (int)  : current cycle number
    force   (bool) : skip review_interval check (default False)
    """

    skill_tags: ClassVar[list[str]] = ["memory", "semantic", "pattern"]

    def __init__(
        self,
        node_id: str | None = None,
        brain_config: Any = None,
        review_interval: int = DEFAULT_REVIEW_INTERVAL,
    ) -> None:
        super().__init__(brain_config=brain_config)
        self._node_id = node_id or str(uuid.uuid4())
        self._version = "1.0"
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._patterns_extracted = 0
        self._last_review_cycle = -1
        self.review_interval = review_interval
        self._mem_kernel: Any = None

    # ------------------------------------------------------------------
    # Node interface
    # ------------------------------------------------------------------

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._node_id,
            name="SemanticMemoryNode",
            version=self._version,
            health=max(0.0, 1.0 - self._error_count / max(1, self._execution_count)),
            capabilities=self.get_capabilities(),
            metrics=self.evaluate(),
            metadata={
                "patterns_extracted": self._patterns_extracted,
                "last_review_cycle": self._last_review_cycle,
                "review_interval": self.review_interval,
            },
        )

    def get_capabilities(self) -> list[str]:
        return ["build_semantic", "consolidate_memory"]

    def describe(self) -> str:
        return (
            f"SemanticMemoryNode: every {self.review_interval} cycles, reviews recent "
            "episodic memories and uses LLM (QUICK tier) to extract recurring patterns "
            "as semantic memories. Creates long-term knowledge the system references before decisions."
        )

    def execute(self, inp: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1
        action = inp.action.lower()

        try:
            if action in ("build_semantic", "consolidate_memory", "consolidate"):
                result = self._do_build_semantic(inp)
            else:
                raise ValueError(f"SemanticMemoryNode: unknown action '{action}'")
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._error_count += 1
            self._total_latency_ms += elapsed
            logger.warning("SemanticMemoryNode error: %s", exc)
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
            metrics={"latency_ms": elapsed, "patterns_extracted": float(self._patterns_extracted)},
        )

    def evaluate(self) -> dict[str, float]:
        return {
            "error_rate": self._error_count / max(1, self._execution_count),
            "avg_latency_ms": self._total_latency_ms / max(1, self._execution_count),
            "patterns_extracted": float(self._patterns_extracted),
            "execution_count": float(self._execution_count),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        return False

    def should_run(self, cycle: int) -> bool:
        """Return True if enough cycles have passed since the last review."""
        return cycle - self._last_review_cycle >= self.review_interval

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def _do_build_semantic(self, inp: NodeInput) -> dict[str, Any]:
        from omega.core.brain import ModelTier

        cycle = int(inp.context.get("cycle", inp.parameters.get("cycle", 0)))
        force = bool(inp.parameters.get("force", False))

        if not force and not self.should_run(cycle):
            return {
                "status": "skipped",
                "reason": f"review_interval not reached (last={self._last_review_cycle})",
                "patterns_extracted": self._patterns_extracted,
            }

        mem_kernel = self._get_mem_kernel()
        if mem_kernel is None:
            return {"status": "skipped", "reason": "no database connection"}

        since_cycle = max(0, cycle - self.review_interval)
        try:
            recent = mem_kernel.retrieve_episodes(
                event_type="trading_reflection",
                limit=self.review_interval,
                min_importance=0.05,
                since_cycle=since_cycle,
                namespace="victoria",
            )
        except Exception as exc:
            logger.debug("retrieve_episodes failed: %s", exc)
            return {"status": "error", "reason": str(exc)}

        if not recent:
            self._last_review_cycle = cycle
            return {"status": "ok", "patterns_extracted": 0, "reason": "no recent episodes"}

        episode_digest = self._build_digest(recent)
        patterns = self._extract_patterns(cycle, episode_digest, ModelTier.QUICK)

        stored_count = 0
        for p in patterns:
            concept = str(p.get("concept", "")).strip()
            content = str(p.get("content", "")).strip()
            confidence = float(p.get("confidence", 0.5))
            tags = p.get("tags", [])

            if not concept or not content:
                continue
            try:
                mem_kernel.store_semantic(
                    concept=concept,
                    content=content,
                    confidence=confidence,
                    tags=tags,
                    namespace="victoria",
                )
                stored_count += 1
            except Exception as exc:
                logger.debug("store_semantic failed for '%s': %s", concept, exc)

        self._patterns_extracted += stored_count
        self._last_review_cycle = cycle

        logger.info(
            "SemanticMemoryNode cycle=%d: %d episodes reviewed → %d patterns stored",
            cycle,
            len(recent),
            stored_count,
        )
        return {
            "status": "ok",
            "episodes_reviewed": len(recent),
            "patterns_extracted": stored_count,
            "total_patterns": self._patterns_extracted,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_digest(episodes: list) -> str:
        lines = []
        for ep in episodes[:30]:
            c = ep.content
            cycle_n = c.get("cycle", ep.cycle)
            regime = c.get("regime", "?")
            conviction = c.get("conviction", 0.0)
            result = c.get("trade_result", "?")
            lesson = c.get("lesson", "")
            lines.append(
                f"  Cycle {cycle_n}: regime={regime}, conviction={conviction:.2f}, "
                f"result={result}. {lesson}"
            )
        return "\n".join(lines)

    def _extract_patterns(self, cycle: int, digest: str, tier: Any) -> list[dict[str, Any]]:
        """Extract patterns via LLM or fall back to rule-based."""
        brain = self.brain
        if brain is None or not brain.is_available():
            return self._rule_based_patterns(digest)

        prompt = (
            f"You are reviewing {len(digest.splitlines())} cycles of crypto trading history.\n\n"
            f"Recent trading episodes:\n{digest}\n\n"
            f"Identify 2-4 recurring patterns. Output each as JSON on its own line:\n"
            f'  {{"concept": "short_snake_case_id", "content": "clear description ≤50 words", '
            f'"confidence": 0.0-1.0, "tags": ["tag1", "tag2"]}}\n\n'
            f"Focus on: regime-signal correlations, conviction thresholds, outcome predictors. "
            f"Be specific (name signals, regimes, thresholds). No generic statements."
        )

        try:
            raw = brain.consult(prompt, tier=tier)
        except Exception as exc:
            logger.debug("LLM pattern extraction failed: %s", exc)
            return self._rule_based_patterns(digest)

        if not raw:
            return self._rule_based_patterns(digest)

        patterns: list[dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    p = json.loads(line)
                    if "concept" in p and "content" in p:
                        patterns.append(p)
                except (json.JSONDecodeError, TypeError):
                    pass

        return patterns if patterns else self._rule_based_patterns(digest)

    @staticmethod
    def _rule_based_patterns(digest: str) -> list[dict[str, Any]]:
        """Minimal rule-based pattern extraction when LLM unavailable."""
        win_by_regime: dict[str, int] = {}
        loss_by_regime: dict[str, int] = {}
        regime_total: dict[str, int] = {}

        for line in digest.splitlines():
            regime = "unknown"
            for tok in line.split():
                if tok.startswith("regime="):
                    regime = tok.split("=", 1)[1].rstrip(",.")
                    break
            regime_total[regime] = regime_total.get(regime, 0) + 1
            ll = line.lower()
            if "result=win" in ll:
                win_by_regime[regime] = win_by_regime.get(regime, 0) + 1
            elif "result=loss" in ll:
                loss_by_regime[regime] = loss_by_regime.get(regime, 0) + 1

        patterns: list[dict[str, Any]] = []
        for regime, total in sorted(regime_total.items(), key=lambda x: -x[1])[:3]:
            wins = win_by_regime.get(regime, 0)
            losses = loss_by_regime.get(regime, 0)
            resolved = wins + losses
            if resolved < 3:
                continue
            win_rate = wins / resolved
            patterns.append(
                {
                    "concept": f"{regime}_win_rate",
                    "content": (
                        f"In '{regime}' regime over {total} cycles: "
                        f"{win_rate:.0%} win rate ({wins} wins / {resolved} resolved trades)."
                    ),
                    "confidence": min(0.8, 0.3 + win_rate * 0.5),
                    "tags": [regime, "outcome", "regime"],
                }
            )

        return patterns

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
