"""
omega.nodes.text_analyzer
~~~~~~~~~~~~~~~~~~~~~~~~~~
Text analysis node that demonstrates capability-expansion improvement.

Improvement arc
---------------
v1.0 — word_count, char_count, sentence_count only.
v1.1 — Adds avg_word_length, lexical_diversity after feedback.
v1.2 — Adds basic sentiment scoring (positive/negative word lists).
"""

import logging
import re
import time
import uuid
from typing import Any

from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.text_analyzer")

# Minimal positive/negative word sets for v1.2 sentiment
_POSITIVE_WORDS = frozenset(
    [
        "good",
        "great",
        "excellent",
        "amazing",
        "wonderful",
        "fantastic",
        "happy",
        "positive",
        "love",
        "best",
        "beautiful",
        "perfect",
        "joy",
        "success",
        "awesome",
        "brilliant",
        "outstanding",
        "superb",
        "nice",
    ]
)
_NEGATIVE_WORDS = frozenset(
    [
        "bad",
        "terrible",
        "horrible",
        "awful",
        "poor",
        "negative",
        "hate",
        "worst",
        "ugly",
        "failure",
        "sad",
        "boring",
        "dull",
        "mediocre",
        "disappointing",
        "annoying",
        "frustrating",
        "useless",
        "broken",
    ]
)


class TextAnalyzerNode(Node):
    """
    Text analysis node.

    Capabilities : analyze, word_count, sentiment (added after improvement)
    Improves via : adding new analysis dimensions per feedback.
    """

    def __init__(self) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._has_extended_metrics = False  # unlocked in v1.1
        self._has_sentiment = False  # unlocked in v1.2

        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0

    # ------------------------------------------------------------------
    # Node interface
    # ------------------------------------------------------------------

    def get_state(self) -> NodeState:
        caps = ["analyze", "word_count"]
        if self._has_extended_metrics:
            caps += ["avg_word_length", "lexical_diversity"]
        if self._has_sentiment:
            caps += ["sentiment"]

        return NodeState(
            node_id=self._node_id,
            name="TextAnalyzerNode",
            version=self._version,
            health=1.0
            if self._error_count == 0
            else max(0.0, 1.0 - self._error_count / max(1, self._execution_count)),
            capabilities=caps,
            metrics={
                "avg_latency_ms": self._avg_latency_ms(),
                "error_rate": self._error_count / max(1, self._execution_count),
                "capability_count": float(len(caps)),
                "execution_count": float(self._execution_count),
            },
        )

    def get_capabilities(self) -> list[str]:
        return self.get_state().capabilities

    def describe(self) -> str:
        return (
            "Analyses text and returns metrics.  "
            "'analyze' returns all available metrics for the given text.  "
            "'word_count' returns just the word count.  "
            "After improvement: 'sentiment' returns a sentiment score in [-1, 1].  "
            "Accepts parameter 'text' (str).  "
            "Can self-improve by unlocking new analysis capabilities."
        )

    def execute(self, input: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        action = input.action.lower()
        text = input.parameters.get("text", "")

        if not isinstance(text, str):
            text = str(text)

        valid_caps = self.get_capabilities()
        if action not in valid_caps:
            elapsed = (time.perf_counter() - t0) * 1000
            self._error_count += 1
            self._execution_count += 1
            self._total_latency_ms += elapsed
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[f"Unknown action '{action}'. Available: {valid_caps}"],
                metrics={"latency_ms": elapsed},
            )

        try:
            result = self._analyse(action, text)
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._error_count += 1
            self._execution_count += 1
            self._total_latency_ms += elapsed
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": elapsed},
            )

        elapsed = (time.perf_counter() - t0) * 1000
        self._execution_count += 1
        self._total_latency_ms += elapsed

        return NodeOutput(
            request_id=input.request_id,
            success=True,
            result=result,
            metrics={"latency_ms": elapsed, "accuracy": 1.0},
        )

    def evaluate(self) -> dict[str, float]:
        return {
            "avg_latency_ms": self._avg_latency_ms(),
            "error_rate": self._error_count / max(1, self._execution_count),
            "capability_count": float(len(self.get_capabilities())),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        changed = False

        if not self._has_extended_metrics:
            self._has_extended_metrics = True
            self._version = "1.1"
            logger.info(
                "TextAnalyzerNode improved to v1.1: added avg_word_length, lexical_diversity"
            )
            changed = True
        elif not self._has_sentiment:
            self._has_sentiment = True
            self._version = "1.2"
            logger.info("TextAnalyzerNode improved to v1.2: added sentiment analysis")
            changed = True

        return changed

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def _analyse(self, action: str, text: str) -> Any:
        words = re.findall(r"\b\w+\b", text.lower())
        word_count = len(words)

        if action == "word_count":
            return word_count

        if action == "sentiment":
            return self._sentiment_score(words)

        # "analyze" (or any other registered capability) → full report
        result: dict[str, Any] = {
            "word_count": word_count,
            "char_count": len(text),
            "char_count_no_spaces": len(text.replace(" ", "")),
            "sentence_count": len(re.split(r"[.!?]+", text.strip())),
            "paragraph_count": len([p for p in text.split("\n\n") if p.strip()]),
        }

        if self._has_extended_metrics:
            result["avg_word_length"] = (
                sum(len(w) for w in words) / word_count if word_count else 0.0
            )
            result["lexical_diversity"] = len(set(words)) / word_count if word_count else 0.0
            result["unique_words"] = len(set(words))

        if self._has_sentiment:
            result["sentiment"] = self._sentiment_score(words)
            result["positive_word_count"] = sum(1 for w in words if w in _POSITIVE_WORDS)
            result["negative_word_count"] = sum(1 for w in words if w in _NEGATIVE_WORDS)

        return result

    def _sentiment_score(self, words: list[str]) -> float:
        """Returns a score in [-1.0, 1.0]; 0 = neutral."""
        if not words:
            return 0.0
        pos = sum(1 for w in words if w in _POSITIVE_WORDS)
        neg = sum(1 for w in words if w in _NEGATIVE_WORDS)
        total = pos + neg
        if total == 0:
            return 0.0
        return (pos - neg) / total

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _avg_latency_ms(self) -> float:
        return self._total_latency_ms / max(1, self._execution_count)
