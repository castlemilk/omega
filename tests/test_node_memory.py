"""
tests/test_node_memory.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for V-TR1: per-node cycle reflection memory.

Covers:
- NodeReflectionStore.store_reflection / get_recent_reflections (in-memory mock)
- NodeReflectionStore.get_context_prompt formatting
- VictoriaNode.reflect_on_cycle — NoBrain fallback path
- VictoriaNode.reflect_on_cycle — mock brain path
- VictoriaNode.get_reflection_context — propagates context when store available
"""

from __future__ import annotations

import time
import uuid
from typing import Any
from unittest.mock import patch

from omega.core.brain import BrainAdapter, BrainResponse, ModelTier
from omega.core.memory import NodeReflection
from omega.nodes.victoria.victoria_node import VictoriaNode

# ---------------------------------------------------------------------------
# In-memory NodeReflectionStore for unit tests (no real DB required)
# ---------------------------------------------------------------------------


class InMemoryReflectionStore:
    """Drop-in replacement for NodeReflectionStore that stores in a list."""

    def __init__(self) -> None:
        self._rows: list[NodeReflection] = []

    def store_reflection(
        self,
        node_id: str,
        cycle: int,
        reflection_text: str,
        lesson_extracted: str,
    ) -> str:
        memory_id = str(uuid.uuid4())
        self._rows.append(
            NodeReflection(
                memory_id=memory_id,
                node_id=node_id,
                cycle=cycle,
                reflection_text=reflection_text,
                lesson_extracted=lesson_extracted,
                created_at=time.time(),
            )
        )
        return memory_id

    def get_recent_reflections(
        self,
        node_id: str,
        limit: int = 5,
    ) -> list[NodeReflection]:
        node_rows = [r for r in self._rows if r.node_id == node_id]
        node_rows.sort(key=lambda r: (r.cycle, r.created_at), reverse=True)
        return node_rows[:limit]

    def get_context_prompt(self, node_id: str, limit: int = 5) -> str:
        reflections = self.get_recent_reflections(node_id, limit=limit)
        if not reflections:
            return ""
        lines = ["Recent cycle lessons (most recent first):"]
        for r in reflections:
            lines.append(f"  Cycle {r.cycle}: {r.lesson_extracted}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# NodeReflectionStore unit tests (in-memory)
# ---------------------------------------------------------------------------


class TestInMemoryReflectionStore:
    def setup_method(self) -> None:
        self.store = InMemoryReflectionStore()
        self.node_id = "TestNode-abc"

    def test_store_and_retrieve(self) -> None:
        mid = self.store.store_reflection(
            node_id=self.node_id,
            cycle=1,
            reflection_text="Cycle 1 was fine.",
            lesson_extracted="All good.",
        )
        assert isinstance(mid, str) and len(mid) == 36  # UUID

        results = self.store.get_recent_reflections(self.node_id, limit=5)
        assert len(results) == 1
        assert results[0].cycle == 1
        assert results[0].lesson_extracted == "All good."
        assert results[0].node_id == self.node_id

    def test_returns_most_recent_first(self) -> None:
        for cycle in range(1, 8):
            self.store.store_reflection(
                node_id=self.node_id,
                cycle=cycle,
                reflection_text=f"Reflection for cycle {cycle}",
                lesson_extracted=f"Lesson {cycle}",
            )
        results = self.store.get_recent_reflections(self.node_id, limit=5)
        assert len(results) == 5
        cycles = [r.cycle for r in results]
        assert cycles == sorted(cycles, reverse=True)

    def test_namespace_isolation(self) -> None:
        self.store.store_reflection("NodeA", 1, "A reflection", "A lesson")
        self.store.store_reflection("NodeB", 1, "B reflection", "B lesson")

        a_results = self.store.get_recent_reflections("NodeA")
        b_results = self.store.get_recent_reflections("NodeB")
        assert len(a_results) == 1
        assert len(b_results) == 1
        assert a_results[0].lesson_extracted == "A lesson"
        assert b_results[0].lesson_extracted == "B lesson"

    def test_empty_returns_empty_string(self) -> None:
        ctx = self.store.get_context_prompt("NonExistentNode")
        assert ctx == ""

    def test_context_prompt_format(self) -> None:
        for cycle in (3, 5):
            self.store.store_reflection(
                node_id=self.node_id,
                cycle=cycle,
                reflection_text=f"Reflection {cycle}",
                lesson_extracted=f"Lesson {cycle}",
            )
        ctx = self.store.get_context_prompt(self.node_id)
        assert "Recent cycle lessons" in ctx
        assert "Lesson 5" in ctx
        assert "Lesson 3" in ctx
        # Most recent should appear first
        assert ctx.index("Lesson 5") < ctx.index("Lesson 3")

    def test_limit_respected(self) -> None:
        for i in range(10):
            self.store.store_reflection(self.node_id, i, f"r{i}", f"l{i}")
        results = self.store.get_recent_reflections(self.node_id, limit=3)
        assert len(results) == 3


# ---------------------------------------------------------------------------
# VictoriaNode.reflect_on_cycle — NoBrain (fallback)
# ---------------------------------------------------------------------------


class TestVictoriaNodeReflectNoBrain:
    def setup_method(self) -> None:
        self.node = VictoriaNode(node_id="test-victoria")
        self.store = InMemoryReflectionStore()
        self.node._reflection_store = self.store  # inject in-memory store

    def _make_signals(
        self,
        quality: float = 0.5,
        avg_conf: float = 0.5,
        coverage: float = 1.0,
        regime: str = "default",
    ) -> dict[str, Any]:
        return {
            "_quality_score": quality,
            "_avg_confidence": avg_conf,
            "_signal_coverage": coverage,
            "_regime": regime,
            "_signal_count": 6.0,
        }

    def test_reflect_stores_reflection(self) -> None:
        signals = self._make_signals(quality=0.6)
        lesson = self.node.reflect_on_cycle(1, signals)
        assert isinstance(lesson, str)
        assert len(lesson) > 0
        stored = self.store.get_recent_reflections(self.node._node_id)
        assert len(stored) == 1
        assert stored[0].cycle == 1

    def test_high_quality_lesson(self) -> None:
        lesson = self.node.reflect_on_cycle(2, self._make_signals(quality=0.8))
        assert "high quality" in lesson.lower() or "maintain" in lesson.lower()

    def test_low_quality_lesson(self) -> None:
        lesson = self.node.reflect_on_cycle(3, self._make_signals(quality=0.2, coverage=0.3))
        assert "weak" in lesson.lower() or "risk" in lesson.lower() or "skip" in lesson.lower()

    def test_multiple_cycles_stored(self) -> None:
        for cycle in range(1, 6):
            self.node.reflect_on_cycle(cycle, self._make_signals(quality=0.5 + cycle * 0.05))
        stored = self.store.get_recent_reflections(self.node._node_id, limit=10)
        assert len(stored) == 5

    def test_get_reflection_context_with_store(self) -> None:
        self.store.store_reflection(self.node._node_id, 1, "Some reflection", "Watch the regime.")
        ctx = self.node.get_reflection_context()
        assert "Watch the regime" in ctx

    def test_get_reflection_context_no_store(self) -> None:
        # Without a DB URL and no injected store, should return empty string gracefully
        node = VictoriaNode(node_id="isolated-node")
        node._reflection_store = None
        with patch.dict("os.environ", {}, clear=False):
            # Remove DATABASE_URL temporarily
            import os

            old = os.environ.pop("DATABASE_URL", None)
            try:
                ctx = node.get_reflection_context()
                assert ctx == ""
            finally:
                if old is not None:
                    os.environ["DATABASE_URL"] = old


# ---------------------------------------------------------------------------
# VictoriaNode.reflect_on_cycle — mock brain path
# ---------------------------------------------------------------------------


class MockBrain(BrainAdapter):
    """Brain that returns a scripted consult() response."""

    def __init__(self, response: str) -> None:
        self._response = response
        self._calls: list[str] = []

    def think(self, request: Any) -> BrainResponse:
        return BrainResponse(action="pass", reasoning="mock", confidence=0.0)

    def consult(self, prompt: str, tier: ModelTier = ModelTier.QUICK) -> str:
        self._calls.append(prompt)
        return self._response

    def is_available(self) -> bool:
        return True

    def provider_name(self) -> str:
        return "mock"


class TestVictoriaNodeReflectWithBrain:
    def setup_method(self) -> None:
        self.node = VictoriaNode(node_id="brain-victoria")
        self.store = InMemoryReflectionStore()
        self.node._reflection_store = self.store

    def test_llm_reflection_stored_when_brain_available(self) -> None:
        mock_response = (
            "Signals were strong in this trending regime, confidence is high.\n"
            "LESSON: Increase position sizing in trending regime."
        )
        self.node.brain = MockBrain(mock_response)

        signals = {
            "_quality_score": 0.75,
            "_avg_confidence": 0.7,
            "_signal_coverage": 1.0,
            "_regime": "trending",
            "_signal_count": 6.0,
        }
        lesson = self.node.reflect_on_cycle(5, signals)
        assert lesson == "Increase position sizing in trending regime."

        stored = self.store.get_recent_reflections(self.node._node_id)
        assert len(stored) == 1
        assert "strong" in stored[0].reflection_text.lower()

    def test_fallback_when_brain_returns_empty(self) -> None:
        self.node.brain = MockBrain("")
        signals = {
            "_quality_score": 0.3,
            "_avg_confidence": 0.3,
            "_signal_coverage": 0.5,
            "_regime": "high_vol",
            "_signal_count": 3.0,
        }
        lesson = self.node.reflect_on_cycle(6, signals)
        # Should fall back to rule-based lesson
        assert isinstance(lesson, str) and len(lesson) > 0

    def test_brain_called_with_quick_tier(self) -> None:
        mock_brain = MockBrain("Some reflection.\nLESSON: Test lesson.")
        self.node.brain = mock_brain
        signals = {
            "_quality_score": 0.6,
            "_avg_confidence": 0.6,
            "_signal_coverage": 1.0,
            "_regime": "default",
            "_signal_count": 6.0,
        }
        self.node.reflect_on_cycle(10, signals)
        assert len(mock_brain._calls) == 1
        assert "cycle" in mock_brain._calls[0].lower()


# ---------------------------------------------------------------------------
# NodeReflection dataclass
# ---------------------------------------------------------------------------


class TestNodeReflectionDataclass:
    def test_fields(self) -> None:
        r = NodeReflection(
            memory_id="abc",
            node_id="n1",
            cycle=3,
            reflection_text="text",
            lesson_extracted="lesson",
            created_at=1234567890.0,
        )
        assert r.memory_id == "abc"
        assert r.node_id == "n1"
        assert r.cycle == 3
        assert r.reflection_text == "text"
        assert r.lesson_extracted == "lesson"
        assert r.created_at == 1234567890.0
