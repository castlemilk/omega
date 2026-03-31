"""
omega.core.feedback_descent
~~~~~~~~~~~~~~~~~~~~~~~~~~~
FeedbackDescent — stores textual feedback alongside scalar metrics and derives
directional guidance ("do more of X", "stop doing Y") from historical feedback.

This is the Feedback Descent component from the Meta-Harness architecture,
inspired by Yoonho Lee's Stanford research on self-improvement loops.

The key insight: textual feedback is a richer gradient signal than scalar
metrics alone. By accumulating rationales for successes and failures, the
system can identify causal patterns that numeric scores cannot capture.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("omega.core.feedback_descent")

_BASE_DIR = Path("data/meta_harness")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class FeedbackRecord:
    """A single feedback observation tied to a strategy iteration."""

    iteration_id: int
    feedback_text: str  # qualitative rationale from the proposer/evaluator
    metrics_delta: dict[str, float]  # change in metrics vs parent (positive = improvement)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    tags: list[str] = field(default_factory=list)  # e.g. ["signal_weight", "regime"]

    def is_improvement(self) -> bool:
        """Overall improvement if composite score delta is positive."""
        return self.metrics_delta.get("score", 0.0) > 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FeedbackRecord":
        return cls(
            iteration_id=int(d["iteration_id"]),
            feedback_text=str(d["feedback_text"]),
            metrics_delta={k: float(v) for k, v in d.get("metrics_delta", {}).items()},
            timestamp=d.get("timestamp", datetime.now(UTC).isoformat()),
            tags=list(d.get("tags", [])),
        )


@dataclass
class DirectionalGuidance:
    """Derived guidance: what to do more of, what to stop doing."""

    do_more: list[str]   # patterns correlated with positive score deltas
    stop_doing: list[str]  # patterns correlated with negative score deltas
    neutral: list[str]   # patterns with mixed results
    confidence: float    # 0–1; higher when more data supports each direction
    based_on_n: int      # number of feedback records used

    def summary(self) -> str:
        lines = [f"Directional guidance (n={self.based_on_n}, conf={self.confidence:.2f}):"]
        for item in self.do_more:
            lines.append(f"  + {item}")
        for item in self.stop_doing:
            lines.append(f"  - {item}")
        for item in self.neutral:
            lines.append(f"  ~ {item}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# FeedbackDescent
# ---------------------------------------------------------------------------


class FeedbackDescent:
    """
    Accumulates textual feedback alongside scalar metrics and derives
    directional guidance for the next iteration.

    Storage layout::
        data/meta_harness/feedback/
            feedback_log.jsonl   ← append-only JSONL record
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = (base_dir or _BASE_DIR) / "feedback"
        self._base.mkdir(parents=True, exist_ok=True)
        self._log_path = self._base / "feedback_log.jsonl"
        self._records: list[FeedbackRecord] = []
        self._load()

    # ------------------------------------------------------------------ I/O

    def _load(self) -> None:
        if not self._log_path.exists():
            return
        with open(self._log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._records.append(FeedbackRecord.from_dict(json.loads(line)))
                except Exception as exc:
                    logger.warning("Failed to parse feedback record: %s", exc)

    def _append(self, record: FeedbackRecord) -> None:
        with open(self._log_path, "a") as f:
            f.write(json.dumps(record.to_dict()) + "\n")

    # ------------------------------------------------------------------ Public API

    def record_feedback(
        self,
        iteration_id: int,
        feedback_text: str,
        metrics_delta: dict[str, float],
        tags: list[str] | None = None,
    ) -> FeedbackRecord:
        """
        Store feedback for one iteration.

        Args:
            iteration_id: The iteration this feedback describes.
            feedback_text: Qualitative rationale (from LLM or heuristic).
            metrics_delta: Dict of metric_name → delta vs parent iteration.
                           Positive = improvement. Must include "score" key.
            tags: Optional category tags (e.g. ["signal_weight", "conviction"]).

        Returns:
            The stored FeedbackRecord.
        """
        record = FeedbackRecord(
            iteration_id=iteration_id,
            feedback_text=feedback_text,
            metrics_delta=metrics_delta,
            tags=tags or [],
        )
        self._records.append(record)
        self._append(record)
        logger.debug(
            "Recorded feedback for iter %d: delta_score=%.4f",
            iteration_id,
            metrics_delta.get("score", 0.0),
        )
        return record

    def get_directional_feedback(
        self,
        min_records: int = 3,
        recent_n: int | None = None,
    ) -> DirectionalGuidance:
        """
        Derive directional guidance from accumulated feedback.

        Analyzes which textual patterns co-occur with positive vs negative
        score deltas. Returns prioritized "do more / stop doing" lists.

        Args:
            min_records: Minimum records required to produce guidance.
            recent_n: Only consider the most recent N records (None = all).

        Returns:
            DirectionalGuidance with prioritized lists.
        """
        records = self._records
        if recent_n is not None:
            records = records[-recent_n:]

        if len(records) < min_records:
            return DirectionalGuidance(
                do_more=["Insufficient data — continue iterating"],
                stop_doing=[],
                neutral=[],
                confidence=0.0,
                based_on_n=len(records),
            )

        improvements = [r for r in records if r.is_improvement()]
        regressions = [r for r in records if not r.is_improvement()]

        do_more = self._extract_patterns(improvements, label="positive")
        stop_doing = self._extract_patterns(regressions, label="negative")
        neutral = self._find_neutral_patterns(improvements, regressions)

        # Confidence scales with n and balance of outcomes
        n = len(records)
        balance = abs(len(improvements) - len(regressions)) / max(n, 1)
        confidence = min(1.0, (n / 20.0) * (1.0 - balance * 0.5))

        return DirectionalGuidance(
            do_more=do_more[:5],
            stop_doing=stop_doing[:5],
            neutral=neutral[:3],
            confidence=round(confidence, 3),
            based_on_n=n,
        )

    def get_all_records(self) -> list[FeedbackRecord]:
        """Return all feedback records in chronological order."""
        return list(self._records)

    def get_records_for_iteration(self, iteration_id: int) -> list[FeedbackRecord]:
        """Return all feedback records for a specific iteration."""
        return [r for r in self._records if r.iteration_id == iteration_id]

    def summarize_for_llm(self, recent_n: int = 10) -> str:
        """
        Format recent feedback as a compact text block for LLM context injection.
        Used by MetaProposer to give the LLM a history digest.
        """
        records = self._records[-recent_n:] if recent_n else self._records
        if not records:
            return "No feedback history yet."

        lines = ["=== Recent Feedback History ==="]
        for r in records:
            delta = r.metrics_delta.get("score", 0.0)
            direction = "IMPROVED" if delta > 0 else "REGRESSED"
            lines.append(
                f"[Iter {r.iteration_id}] {direction} (Δscore={delta:+.4f}): {r.feedback_text}"
            )

        guidance = self.get_directional_feedback(recent_n=recent_n)
        lines.append("")
        lines.append(guidance.summary())
        return "\n".join(lines)

    # ------------------------------------------------------------------ Internal

    def _extract_patterns(
        self, records: list[FeedbackRecord], label: str
    ) -> list[str]:
        """
        Extract the most common themes from a set of feedback texts.
        Simple keyword/phrase frequency — no external NLP dependency.
        """
        if not records:
            return []

        # Extract key phrases by looking at noun-like tokens > 4 chars
        phrase_counts: dict[str, int] = {}
        for r in records:
            words = r.feedback_text.lower().split()
            # Slide a 2-gram window
            for i in range(len(words) - 1):
                bigram = f"{words[i]} {words[i+1]}"
                if all(len(w) > 3 for w in [words[i], words[i+1]]):
                    phrase_counts[bigram] = phrase_counts.get(bigram, 0) + 1
            # Also track single meaningful words
            for w in words:
                if len(w) > 5 and w.isalpha():
                    phrase_counts[w] = phrase_counts.get(w, 0) + 1

        if not phrase_counts:
            # Fallback: return the most recent rationale snippet
            return [records[-1].feedback_text[:120]]

        top = sorted(phrase_counts.items(), key=lambda x: -x[1])
        results = []
        seen_tokens: set[str] = set()
        for phrase, count in top:
            tokens = set(phrase.split())
            if tokens & seen_tokens:
                continue  # skip overlapping phrases
            seen_tokens |= tokens
            if count >= 2:
                results.append(f"{phrase} (seen {count}x in {label} iterations)")
            elif results:  # allow 1-count only if we have < 3 results
                break
            else:
                results.append(phrase)
            if len(results) >= 5:
                break

        return results if results else [records[-1].feedback_text[:120]]

    def _find_neutral_patterns(
        self,
        improvements: list[FeedbackRecord],
        regressions: list[FeedbackRecord],
    ) -> list[str]:
        """Find patterns that appear in both improved and regressed iterations."""
        if not improvements or not regressions:
            return []

        def word_set(records: list[FeedbackRecord]) -> set[str]:
            words: set[str] = set()
            for r in records:
                for w in r.feedback_text.lower().split():
                    if len(w) > 5 and w.isalpha():
                        words.add(w)
            return words

        imp_words = word_set(improvements)
        reg_words = word_set(regressions)
        shared = imp_words & reg_words
        return [f"'{w}' appears in both improved and regressed iterations" for w in list(shared)[:3]]
