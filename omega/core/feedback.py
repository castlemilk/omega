"""
omega.core.feedback
~~~~~~~~~~~~~~~~~~~~
FeedbackEngine — collects human and self-supervised feedback to drive improvement.

Feedback types:
  - Human CLI feedback : typed by the operator during a heartbeat pause
  - Self-supervised    : system compares signal predictions to actual outcomes
  - Node-generated     : nodes suggest their own improvements via suggestions[]

All feedback is stored in the MemoryKernel as high-importance episodes and
influences the next improvement cycle.
"""

from __future__ import annotations

import logging
import select
import sys
import time
from typing import Any

from omega.core.memory import MemoryKernel

logger = logging.getLogger("omega.core.feedback")


class FeedbackEngine:
    """
    Collects, stores, and routes feedback to nodes and the memory kernel.

    Human feedback: operator types during the inter-heartbeat window.
    Self-supervised: compares last cycle's signals to observed price outcomes.
    """

    def __init__(self, memory: MemoryKernel) -> None:
        self.memory = memory
        self._pending_human: list[dict[str, Any]] = []
        self._pending_self: list[dict[str, Any]] = []
        self._cycle_predictions: dict[str, Any] = {}  # store signals for self-eval next cycle
        self._feedback_history: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ Human feedback

    def add_human_feedback(
        self,
        text: str,
        target_node: str | None = None,
        sentiment: float | None = None,
        cycle: int = 0,
    ) -> None:
        """
        Accept human feedback text. Sentiment: +1.0 (positive) to -1.0 (negative).
        Stored as a high-importance episodic memory.
        """
        # Infer sentiment from keywords if not provided
        if sentiment is None:
            text_lower = text.lower()
            positive_words = ["good", "great", "correct", "right", "yes", "perfect", "excellent"]
            negative_words = ["wrong", "bad", "incorrect", "no", "poor", "mistake", "too", "fix"]
            pos = sum(1 for w in positive_words if w in text_lower)
            neg = sum(1 for w in negative_words if w in text_lower)
            sentiment = (pos - neg) / max(1, pos + neg)

        entry = {
            "text": text,
            "target_node": target_node,
            "sentiment": sentiment,
            "cycle": cycle,
            "source": "human",
            "timestamp": time.time(),
        }
        self._pending_human.append(entry)
        self._feedback_history.append(entry)

        tags = ["human_feedback"]
        if target_node:
            tags.append(target_node.lower().replace(" ", "_"))
        if sentiment > 0.3:
            tags.append("positive_feedback")
        elif sentiment < -0.3:
            tags.append("negative_feedback")

        self.memory.store_episode(
            event_type="human_feedback",
            content=entry,
            tags=tags,
            importance=0.9,  # human feedback is high-importance
            cycle=cycle,
        )
        logger.info(
            "Human feedback received [sentiment=%.2f, target=%s]: %s",
            sentiment,
            target_node or "system",
            text[:80],
        )

    def try_read_cli_feedback(self, timeout_sec: float = 2.0, cycle: int = 0) -> str | None:
        """
        Non-blocking read from stdin. If user types within timeout_sec, process it.
        Returns the feedback text if provided, else None.
        """
        try:
            # Check if stdin has data available (non-blocking on Unix)
            if sys.stdin.isatty():
                ready, _, _ = select.select([sys.stdin], [], [], timeout_sec)
                if ready:
                    line = sys.stdin.readline().strip()
                    if line:
                        self.add_human_feedback(line, cycle=cycle)
                        return line
        except (OSError, ValueError):
            # stdin may not support select (e.g., piped input)
            pass
        return None

    # ------------------------------------------------------------------ Self-supervised feedback

    def record_cycle_signals(self, signals: dict[str, Any], cycle: int) -> None:
        """
        Store current cycle's signals for comparison in the next cycle.
        This enables self-supervised learning: compare prediction to outcome.
        """
        self._cycle_predictions = {
            "cycle": cycle,
            "signals": {
                ticker: {
                    "composite": sig.get("composite"),
                    "price": sig.get("price"),
                    "predicted_direction": 1 if sig.get("composite", 0) > 0 else -1,
                }
                for ticker, sig in signals.items()
                if sig.get("composite") is not None
            },
            "timestamp": time.time(),
        }
        self.memory.set_working("last_predictions", self._cycle_predictions)

    def evaluate_predictions(self, current_signals: dict[str, Any], cycle: int) -> list[dict]:
        """
        Compare last cycle's predictions against current prices.
        Store outcomes as episodic memories and generate self-feedback.
        """
        outcomes: list[dict[str, Any]] = []
        last = self.memory.get_working("last_predictions") or self._cycle_predictions

        if not last or "signals" not in last:
            return outcomes

        for ticker, pred in last["signals"].items():
            if ticker not in current_signals:
                continue
            curr = current_signals[ticker]
            if pred.get("price") is None or curr.get("price") is None:
                continue

            old_price = pred["price"]
            new_price = curr["price"]
            if old_price == 0:
                continue

            actual_return = (new_price - old_price) / old_price
            predicted_direction = pred.get("predicted_direction", 0)
            actual_direction = 1 if actual_return > 0 else -1
            was_correct = predicted_direction == actual_direction

            outcome = {
                "ticker": ticker,
                "predicted_direction": predicted_direction,
                "actual_return": actual_return,
                "was_correct": was_correct,
                "signal_type": "composite",
                "outcome": actual_return * predicted_direction,  # positive if correct
                "old_price": old_price,
                "new_price": new_price,
            }
            outcomes.append(outcome)

            # Store as episodic memory for consolidation
            self.memory.store_episode(
                event_type="signal_outcome",
                content=outcome,
                tags=[
                    ticker.replace("USDT", "").lower(),
                    "signal_outcome",
                    "correct" if was_correct else "incorrect",
                ],
                importance=0.7,
                cycle=cycle,
            )

            # Reinforce or weaken semantic patterns
            concept = f"{ticker.lower()}_composite_pattern"
            if was_correct:
                self.memory.reinforce_semantic(concept, delta=0.05)
            else:
                self.memory.reinforce_semantic(concept, delta=-0.03)

        if outcomes:
            hit_rate = sum(1 for o in outcomes if o["was_correct"]) / len(outcomes)
            self._pending_self.append(
                {
                    "cycle": cycle,
                    "hit_rate": hit_rate,
                    "n_predictions": len(outcomes),
                    "outcomes": outcomes,
                }
            )
            logger.info(
                "Self-supervised eval: %d predictions, hit_rate=%.0f%%",
                len(outcomes),
                hit_rate * 100,
            )

        return outcomes

    # ------------------------------------------------------------------ Node improvement feedback

    def get_improvement_feedback(self) -> dict[str, Any]:
        """
        Aggregate pending feedback into a dict that the improvement pass can use.
        Clears pending queues after returning.
        """
        # Summarize human feedback
        human_sentiments = [f["sentiment"] for f in self._pending_human]
        avg_human_sentiment = (
            sum(human_sentiments) / len(human_sentiments) if human_sentiments else 0.0
        )
        negative_nodes = [
            f["target_node"]
            for f in self._pending_human
            if f["sentiment"] < -0.3 and f["target_node"]
        ]

        # Summarize self-supervised feedback
        self_hit_rates = [f["hit_rate"] for f in self._pending_self]
        avg_hit_rate = sum(self_hit_rates) / len(self_hit_rates) if self_hit_rates else None

        feedback = {
            "human_feedback_count": len(self._pending_human),
            "avg_human_sentiment": avg_human_sentiment,
            "negative_feedback_nodes": list(set(negative_nodes)),
            "self_supervised_hit_rate": avg_hit_rate,
            "has_negative_feedback": avg_human_sentiment < -0.2 or bool(negative_nodes),
            "human_feedback_texts": [f["text"] for f in self._pending_human[-3:]],
        }

        # Clear processed feedback
        self._pending_human.clear()
        self._pending_self.clear()

        return feedback

    def get_feedback_history_summary(self) -> str:
        """Return a human-readable summary of all feedback received."""
        if not self._feedback_history:
            return "  No feedback recorded yet."
        lines = [f"  Total feedback entries: {len(self._feedback_history)}"]
        for fb in self._feedback_history[-5:]:
            sentiment_str = f"{fb['sentiment']:+.2f}" if fb.get("sentiment") is not None else "N/A"
            lines.append(
                f"  [cycle {fb.get('cycle', '?')}] [{sentiment_str}] {fb.get('text', '')[:60]}"
            )
        return "\n".join(lines)
