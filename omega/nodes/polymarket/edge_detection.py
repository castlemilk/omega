"""
omega.nodes.polymarket.edge_detection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
EdgeDetectionNode — compares ensemble weather model probabilities with
Polymarket market prices to surface trading opportunities.

Edge formula
------------
    edge = model_probability - market_price

A positive edge means the model thinks the event is more likely than the
market is pricing. An opportunity is flagged when edge > edge_threshold
(default 0.08 = 8 percentage points).

Kelly position sizing
---------------------
    f* = edge / (1 - model_probability)

This is the fractional Kelly criterion for binary outcomes. The result is
capped at max_kelly_fraction (default 0.25) to prevent over-betting.

Usage::

    node = EdgeDetectionNode()
    out = node.execute(NodeInput(
        action="detect",
        parameters={
            "model_prob": 0.80,
            "market_price": 0.50,
            "city": "NYC",
            "market_id": "some-condition-id",
            "question": "Will NYC hit 95°F on July 4?",
        }
    ))
    # out.result = {"edge": 0.30, "kelly_fraction": 0.60, "opportunity": True, ...}
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.polymarket.edge_detection")

DEFAULT_EDGE_THRESHOLD = 0.08
DEFAULT_MAX_KELLY = 0.25


@dataclass
class EdgeOpportunity:
    city: str
    market_id: str
    question: str
    model_prob: float
    market_price: float
    edge: float
    kelly_fraction: float
    confidence: float
    direction: str  # "YES" or "NO"
    detected_at: str = field(default_factory=lambda: datetime.now().isoformat())


class EdgeDetectionNode(Node):
    """
    Detects trading opportunities by comparing model probabilities to market prices.

    Actions
    -------
    detect          — Evaluate a single (model_prob, market_price) pair
    batch_detect    — Evaluate a list of pairs
    """

    def __init__(
        self,
        edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
        max_kelly_fraction: float = DEFAULT_MAX_KELLY,
    ) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._opportunities_detected = 0
        self.edge_threshold = edge_threshold
        self.max_kelly_fraction = max_kelly_fraction

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._node_id,
            name="EdgeDetectionNode",
            version=self._version,
            health=max(0.0, 1.0 - self._error_count / max(1, self._execution_count)),
            capabilities=self.get_capabilities(),
            metrics=self.evaluate(),
            metadata={
                "edge_threshold": self.edge_threshold,
                "max_kelly_fraction": self.max_kelly_fraction,
                "opportunities_detected": self._opportunities_detected,
            },
        )

    def get_capabilities(self) -> list[str]:
        return ["detect", "batch_detect", "edge_detection"]

    def describe(self) -> str:
        return (
            "Compares weather ensemble model probabilities against Polymarket prices "
            "to detect edges. Flags opportunities when edge > threshold and computes "
            "Kelly-criterion position sizes."
        )

    def execute(self, inp: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1
        action = inp.action.lower()

        result: Any = None
        try:
            if action in ("detect", "edge_detection", "edgedetection"):
                result = self._detect_single(inp.parameters)
            elif action == "batch_detect":
                items = inp.parameters.get("items", [])
                result = self._batch_detect(items)
            else:
                raise ValueError(
                    f"Unknown action '{action}'. Supported: {self.get_capabilities()}"
                )
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._error_count += 1
            self._total_latency_ms += elapsed
            logger.warning("EdgeDetectionNode error: %s", exc)
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
            metrics={"latency_ms": elapsed},
        )

    def evaluate(self) -> dict[str, float]:
        return {
            "error_rate": self._error_count / max(1, self._execution_count),
            "avg_latency_ms": self._total_latency_ms / max(1, self._execution_count),
            "opportunities_detected": float(self._opportunities_detected),
            "execution_count": float(self._execution_count),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        changed = False
        if "edge_threshold" in feedback:
            new_thresh = float(feedback["edge_threshold"])
            if new_thresh != self.edge_threshold:
                self.edge_threshold = new_thresh
                self._version = "1.1"
                changed = True
        return changed

    # ------------------------------------------------------------------
    # Internal logic
    # ------------------------------------------------------------------

    @staticmethod
    def kelly_fraction(edge: float, model_prob: float, max_fraction: float) -> float:
        """
        Kelly criterion for binary outcome: f* = edge / (1 - model_prob)

        When model_prob is very high (close to 1), the denominator approaches 0.
        In that case we cap at max_fraction to avoid infinite sizing.
        """
        denom = 1.0 - model_prob
        if denom < 1e-9:
            return max_fraction
        raw_kelly = edge / denom
        return min(max(0.0, raw_kelly), max_fraction)

    @staticmethod
    def confidence_score(edge: float, member_count: int) -> float:
        """
        Simple confidence heuristic: larger edge and more ensemble members → higher confidence.
        Scaled to [0, 1].
        """
        edge_component = min(abs(edge) / 0.5, 1.0)  # saturates at 0.5 edge
        member_component = min(member_count / 50.0, 1.0)  # saturates at 50 members
        return round((edge_component + member_component) / 2.0, 4)

    def _detect_single(self, params: dict[str, Any]) -> dict[str, Any]:
        model_prob = float(params.get("model_prob", 0.5))
        market_price = float(params.get("market_price", 0.5))
        city = str(params.get("city", ""))
        market_id = str(params.get("market_id", ""))
        question = str(params.get("question", ""))
        member_count = int(params.get("member_count", 31))

        edge = model_prob - market_price
        opportunity = abs(edge) >= self.edge_threshold

        # Determine direction: buy YES if model > market, buy NO if model < market
        direction = "YES" if edge > 0 else "NO"

        kelly = self.kelly_fraction(abs(edge), model_prob, self.max_kelly_fraction)
        confidence = self.confidence_score(edge, member_count)

        if opportunity:
            self._opportunities_detected += 1

        return {
            "city": city,
            "market_id": market_id,
            "question": question,
            "model_prob": round(model_prob, 4),
            "market_price": round(market_price, 4),
            "edge": round(edge, 4),
            "kelly_fraction": round(kelly, 4),
            "confidence": confidence,
            "direction": direction,
            "opportunity": opportunity,
            "edge_threshold": self.edge_threshold,
            "detected_at": datetime.now().isoformat(),
        }

    def _batch_detect(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results = []
        for item in items:
            results.append(self._detect_single(item))
        return results
