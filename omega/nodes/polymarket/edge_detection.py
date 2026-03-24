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
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from omega.core.actions import NodeAction
from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.polymarket.edge_detection")

DEFAULT_EDGE_THRESHOLD = 0.08
DEFAULT_MAX_KELLY = 0.25


def _persist_edge(
    cycle: int,
    city: str,
    market_slug: str,
    model_prob: float,
    market_price: float,
    edge: float,
    kelly_fraction: float,
) -> None:
    """Upsert a detected edge into the polymarket_edges table."""
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return
    try:
        import psycopg2

        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO polymarket_edges
                        (cycle, city, market_slug, model_prob, market_price, edge, kelly_fraction)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (cycle, city, market_slug, model_prob, market_price, edge, kelly_fraction),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("polymarket_edges persist skipped: %s", exc)


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
        return [NodeAction.DETECT.value, "batch_detect", NodeAction.EDGE_DETECTION.value]

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
        cycle = int(inp.context.get("cycle", 0))

        result: Any = None
        try:
            if action in (
                NodeAction.DETECT.value,
                NodeAction.EDGE_DETECTION.value,
                "edgedetection",
            ):
                # If no explicit model_prob/market_price params, auto-fetch from
                # PolymarketPricingNode and WeatherEnsembleNode.
                if not inp.parameters or "model_prob" not in inp.parameters:
                    result = self._auto_detect(cycle)
                else:
                    params = dict(inp.parameters)
                    params.setdefault("cycle", cycle)
                    result = self._detect_single(params)
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

    def _auto_detect(self, cycle: int) -> dict[str, Any]:
        """Auto-fetch markets and weather probs, then detect best edge.

        Instantiates PolymarketPricingNode and WeatherEnsembleNode internally,
        fetches live data, runs batch detection across all pairs, persists every
        edge to polymarket_edges, and returns the highest-|edge| result.
        """
        from omega.core.node import NodeInput as NodeInputLocal
        from omega.nodes.polymarket.pricing import PolymarketPricingNode
        from omega.nodes.polymarket.weather_ensemble import WeatherEnsembleNode

        # Fetch active markets from Polymarket.
        try:
            pricing_out = PolymarketPricingNode().execute(
                NodeInputLocal(action="fetch_weather_markets")
            )
            markets: list[dict[str, Any]] = (
                pricing_out.result if isinstance(pricing_out.result, list) else []
            )
        except Exception as exc:
            logger.warning("auto_detect: pricing fetch failed: %s", exc)
            markets = []

        # Fetch weather ensemble probabilities per city.
        try:
            weather_out = WeatherEnsembleNode().execute(
                NodeInputLocal(action=NodeAction.PROBABILITY.value)
            )
            weather_result = weather_out.result or {}
        except Exception as exc:
            logger.warning("auto_detect: weather fetch failed: %s", exc)
            weather_result = {}

        # Build city→prob lookup from WeatherEnsembleNode result.
        # The node returns either a per-city dict {city: {probability: float, ...}}
        # or a single-city dict {city: str, probability: float, ...}.
        city_probs: dict[str, float] = {}
        if isinstance(weather_result, dict):
            if "city" in weather_result and "probability" in weather_result:
                # Single-city result
                city_probs[str(weather_result["city"]).upper()] = float(
                    weather_result["probability"]
                )
            else:
                for city, data in weather_result.items():
                    if isinstance(data, dict) and "probability" in data:
                        city_probs[city.upper()] = float(data["probability"])
                    elif isinstance(data, (int, float)):
                        city_probs[city.upper()] = float(data)

        best: dict[str, Any] | None = None
        for mkt in markets:
            # Match market to a city: check city field first, then scan question text.
            mkt_city = str(mkt.get("city", "")).upper()
            question = str(mkt.get("question", ""))
            if not mkt_city and question:
                # Try to find a known city name in the question text.
                for known_city in city_probs:
                    if known_city.title() in question or known_city.lower() in question.lower():
                        mkt_city = known_city
                        break
            model_prob = city_probs.get(mkt_city, 0.5) if mkt_city else 0.5
            market_price = float(mkt.get("yes_price", 0.5))
            params = {
                "model_prob": model_prob,
                "market_price": market_price,
                "city": mkt_city or mkt.get("city", ""),
                "market_id": mkt.get("market_id", ""),
                "market_slug": mkt.get("market_slug", mkt.get("market_id", "")),
                "question": question,
                "member_count": 31,
                "cycle": cycle,
            }
            r = self._detect_single(params)
            if best is None or abs(r["edge"]) > abs(best["edge"]):
                best = r

        if best is None:
            # Fallback: no markets found, return a zero-edge placeholder.
            best = self._detect_single({"model_prob": 0.5, "market_price": 0.5, "cycle": cycle})

        logger.info(
            "auto_detect: cycle=%d markets=%d best_edge=%.4f opportunity=%s",
            cycle,
            len(markets),
            best["edge"],
            best["opportunity"],
        )
        return best

    def _detect_single(self, params: dict[str, Any]) -> dict[str, Any]:
        model_prob = float(params.get("model_prob", 0.5))
        market_price = float(params.get("market_price", 0.5))
        city = str(params.get("city", ""))
        market_id = str(params.get("market_id", ""))
        market_slug = str(params.get("market_slug", market_id))
        question = str(params.get("question", ""))
        member_count = int(params.get("member_count", 31))
        cycle = int(params.get("cycle", 0))

        edge = model_prob - market_price
        opportunity = abs(edge) >= self.edge_threshold

        # Determine direction: buy YES if model > market, buy NO if model < market
        direction = "YES" if edge > 0 else "NO"

        kelly = self.kelly_fraction(abs(edge), model_prob, self.max_kelly_fraction)
        confidence = self.confidence_score(edge, member_count)

        if opportunity:
            self._opportunities_detected += 1

        # Persist every detected edge (opportunity or not) for analysis.
        _persist_edge(
            cycle, city, market_slug, model_prob, market_price, round(edge, 4), round(kelly, 4)
        )

        return {
            "city": city,
            "market_id": market_id,
            "market_slug": market_slug,
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
