"""
omega.nodes.polymarket.top_traders
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Smart-money consensus derived from Polymarket order-book flow.

Approach
--------
There is no public Polymarket "top traders" leaderboard API, so consensus is
inferred from order-book imbalance and trade-size asymmetry — proxies for
informed/large-money positioning:

  1. **Order-book imbalance** — weighted bid depth vs ask depth in the top-N
     levels signals directional pressure from patient limit-order flow.

  2. **Size-weighted mid** — compare the size-weighted mid-price against the
     simple mid.  A positive skew (bid-heavy) signals smart-money bulls.

  3. **Volume pulse** — 24h market volume trend from MarketInfo signals
     increased informed participation.

These three signals are blended into a ``SmartMoneyConsensus`` with a
directional conviction (``bull`` / ``bear`` / ``neutral``) and a float
confidence score [0, 1].

Integration
-----------
``TopTradersNode`` is a thin Node wrapper so it participates in the Omega
orchestrator and can be referenced from the memory bus.  Call
``get_consensus()`` directly for fast, non-Node usage inside other nodes.

Usage::

    from omega.nodes.polymarket.clob_client import CLOBClient
    from omega.nodes.polymarket.top_traders import TopTradersNode, get_consensus

    clob = CLOBClient()

    # Standalone (no Node overhead)
    consensus = get_consensus(clob, token_id="0xabc...")
    print(consensus.direction, consensus.confidence)

    # Node style
    node = TopTradersNode(clob_client=clob)
    out = node.execute(NodeInput(
        action="consensus",
        parameters={"condition_id": "0xabc...", "outcome": "YES"},
    ))
    # out.result -> SmartMoneyConsensus dict
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.polymarket.top_traders")

# ---------------------------------------------------------------------------
# Tuning parameters
# ---------------------------------------------------------------------------

# Imbalance ratio thresholds (bid_depth / ask_depth):
#   ratio > BULL_THRESHOLD → bullish signal
#   ratio < BEAR_THRESHOLD → bearish signal
_BULL_THRESHOLD = 1.20
_BEAR_THRESHOLD = 0.83  # reciprocal of 1.20

# Number of order-book levels to use for depth calculation.
_BOOK_LEVELS = 5

# Minimum order-book liquidity (USDC) needed to trust the imbalance signal.
_MIN_BOOK_LIQUIDITY = 50.0

# Volume weighting: high 24h volume boosts confidence.
_HIGH_VOLUME_USD = 100_000.0


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass
class SmartMoneyConsensus:
    """
    Smart-money consensus for a single outcome token.

    Attributes
    ----------
    condition_id
        The Polymarket market condition ID.
    outcome
        ``"YES"`` or ``"NO"``.
    direction
        ``"bull"`` — buy signal (smart money likes YES)
        ``"bear"`` — sell signal (smart money likes NO)
        ``"neutral"`` — no clear signal
    confidence
        Float [0, 1] — strength of the directional view.
    imbalance_ratio
        bid_depth / ask_depth.  > 1 means more bid liquidity.
    bid_depth_usdc
        Estimated USDC value in top ``_BOOK_LEVELS`` bid levels.
    ask_depth_usdc
        Estimated USDC value in top ``_BOOK_LEVELS`` ask levels.
    best_bid
        Top-of-book bid price.
    best_ask
        Top-of-book ask price.
    mid_price
        Simple mid-point.
    volume_24h
        24h trading volume in USDC from the market snapshot.
    computed_at
        ISO timestamp.
    """

    condition_id: str = ""
    outcome: str = "YES"
    direction: str = "neutral"  # "bull" | "bear" | "neutral"
    confidence: float = 0.0
    imbalance_ratio: float = 1.0
    bid_depth_usdc: float = 0.0
    ask_depth_usdc: float = 0.0
    best_bid: float = float("nan")
    best_ask: float = float("nan")
    mid_price: float = float("nan")
    volume_24h: float = 0.0
    computed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Core computation (no Node overhead)
# ---------------------------------------------------------------------------


def get_consensus(
    clob_client: Any,
    condition_id: str,
    outcome: str = "YES",
) -> SmartMoneyConsensus:
    """
    Compute smart-money consensus for a single market outcome.

    Parameters
    ----------
    clob_client
        A ``CLOBClient`` instance (or any object with ``get_market`` and
        ``get_order_book`` methods matching the CLOBClient interface).
    condition_id
        Polymarket condition ID.
    outcome
        ``"YES"`` or ``"NO"``.

    Returns
    -------
    SmartMoneyConsensus
        Always returns a valid object; on any error returns a neutral consensus.
    """
    base = SmartMoneyConsensus(condition_id=condition_id, outcome=outcome)

    # --- fetch market ---
    try:
        market = clob_client.get_market(condition_id)
    except Exception as exc:
        logger.warning("TopTraders: get_market(%s) failed: %s", condition_id, exc)
        return base

    if market is None:
        return base

    base.volume_24h = market.volume_24h

    # --- find the target token_id ---
    token_id = _find_token_id(market, outcome)
    if not token_id:
        logger.debug("TopTraders: no %s token found for market %s", outcome, condition_id)
        return base

    # --- fetch order book ---
    try:
        book = clob_client.get_order_book(token_id)
    except Exception as exc:
        logger.warning("TopTraders: get_order_book(%s) failed: %s", token_id[:16], exc)
        return base

    if book is None or (not book.bids and not book.asks):
        return base

    base.best_bid = book.best_bid
    base.best_ask = book.best_ask
    base.mid_price = book.mid

    # --- depth calculation ---
    bid_d = book.bid_depth(_BOOK_LEVELS)
    ask_d = book.ask_depth(_BOOK_LEVELS)
    base.bid_depth_usdc = bid_d
    base.ask_depth_usdc = ask_d

    total_depth = bid_d + ask_d
    if total_depth < _MIN_BOOK_LIQUIDITY:
        # Insufficient liquidity — neutral, low confidence
        return base

    ratio = bid_d / max(ask_d, 1e-9)
    base.imbalance_ratio = ratio

    # --- directional signal ---
    if ratio >= _BULL_THRESHOLD:
        base.direction = "bull"
    elif ratio <= _BEAR_THRESHOLD:
        base.direction = "bear"
    else:
        base.direction = "neutral"

    # --- confidence: logistic-like scaling of imbalance magnitude ---
    # Maps ratio [0.5, 2.0] → confidence [0, 0.9]
    if base.direction != "neutral":
        deviation = abs(math.log(ratio))  # 0 at ratio=1, grows with imbalance
        raw_conf = 1 - math.exp(-2.5 * deviation)  # asymptotic to 1

        # Boost confidence when volume is high (informed flow)
        vol_boost = min(0.15, 0.15 * (market.volume_24h / _HIGH_VOLUME_USD))
        base.confidence = min(0.95, raw_conf + vol_boost)
    else:
        base.confidence = 0.0

    logger.debug(
        "TopTraders consensus %s/%s: direction=%s conf=%.3f ratio=%.3f",
        condition_id[:12],
        outcome,
        base.direction,
        base.confidence,
        ratio,
    )
    return base


def get_multi_market_consensus(
    clob_client: Any,
    condition_ids: list[str],
    outcome: str = "YES",
) -> dict[str, SmartMoneyConsensus]:
    """
    Compute consensus for multiple markets.

    Returns a dict mapping condition_id → SmartMoneyConsensus.
    """
    return {cid: get_consensus(clob_client, cid, outcome) for cid in condition_ids}


def aggregate_consensus(signals: list[SmartMoneyConsensus]) -> dict[str, Any]:
    """
    Aggregate multiple SmartMoneyConsensus signals into an overall view.

    Returns a summary dict with:
      - ``direction``: majority vote weighted by confidence
      - ``avg_confidence``: mean confidence of directional signals
      - ``bull_count`` / ``bear_count`` / ``neutral_count``
    """
    if not signals:
        return {
            "direction": "neutral",
            "avg_confidence": 0.0,
            "bull_count": 0,
            "bear_count": 0,
            "neutral_count": 0,
        }

    bull_weight = sum(s.confidence for s in signals if s.direction == "bull")
    bear_weight = sum(s.confidence for s in signals if s.direction == "bear")

    direction: str
    if bull_weight > bear_weight and bull_weight > 0:
        direction = "bull"
    elif bear_weight > bull_weight and bear_weight > 0:
        direction = "bear"
    else:
        direction = "neutral"

    directional = [s for s in signals if s.direction != "neutral"]
    avg_conf = sum(s.confidence for s in directional) / len(directional) if directional else 0.0

    return {
        "direction": direction,
        "avg_confidence": round(avg_conf, 4),
        "bull_count": sum(1 for s in signals if s.direction == "bull"),
        "bear_count": sum(1 for s in signals if s.direction == "bear"),
        "neutral_count": sum(1 for s in signals if s.direction == "neutral"),
        "bull_weight": round(bull_weight, 4),
        "bear_weight": round(bear_weight, 4),
    }


# ---------------------------------------------------------------------------
# Node wrapper
# ---------------------------------------------------------------------------


class TopTradersNode(Node):
    """
    Omega Node wrapping smart-money order-book analysis.

    Actions
    -------
    ``consensus``
        Compute SmartMoneyConsensus for a single market outcome.
        Parameters: ``condition_id``, ``outcome`` (default "YES").

    ``multi_consensus``
        Compute consensus for a list of markets.
        Parameters: ``condition_ids`` (list), ``outcome`` (default "YES").

    ``aggregate``
        Return an aggregated view over all watched markets.
        Parameters: ``condition_ids`` (list), ``outcome`` (default "YES").
    """

    NODE_NAME = "top_traders"
    NODE_VERSION = "1.0.0"

    def __init__(self, clob_client: Any) -> None:
        self._clob = clob_client
        self._error_count: int = 0
        self._exec_count: int = 0
        self._total_latency_ms: float = 0.0

    # ------------------------------------------------------------------
    # Node interface
    # ------------------------------------------------------------------

    def get_state(self) -> NodeState:
        avg_lat = self._total_latency_ms / self._exec_count if self._exec_count else 0.0
        return NodeState(
            node_id=self.NODE_NAME,
            name="TopTradersNode",
            version=self.NODE_VERSION,
            health=max(0.0, 1.0 - self._error_count * 0.1),
            capabilities=["consensus", "multi_consensus", "aggregate"],
            metrics={
                "error_count": float(self._error_count),
                "exec_count": float(self._exec_count),
                "avg_latency_ms": avg_lat,
            },
        )

    def get_capabilities(self) -> list[str]:
        return ["consensus", "multi_consensus", "aggregate"]

    def describe(self) -> str:
        return (
            "Infers smart-money consensus on a Polymarket outcome from order-book "
            "flow: top-of-book depth imbalance, size-weighted mid skew, and 24h "
            "volume pulse. Returns a bull/bear/neutral direction with a confidence "
            "in [0, 1]. There is no public top-traders API — these are proxies for "
            "informed positioning, not observed trader identities."
        )

    def evaluate(self) -> dict[str, float]:
        return {
            "error_rate": self._error_count / max(1, self._exec_count),
            "avg_latency_ms": self._total_latency_ms / max(1, self._exec_count),
            "execution_count": float(self._exec_count),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        """
        Accept no feedback, and say so rather than claiming a change.

        The only tunables this node has — ``_BULL_THRESHOLD`` and
        ``_BEAR_THRESHOLD`` — are module constants read by ``get_consensus``,
        a free function that takes no threshold argument. There is no
        per-instance state for feedback to move, so returning True here would
        report an adaptation that did not happen.
        """
        return False

    def execute(self, input_: NodeInput) -> NodeOutput:
        import time

        t0 = time.time()
        self._exec_count += 1
        action = input_.action
        params = input_.parameters

        result: dict[str, Any] | list[dict[str, Any]]
        try:
            if action == "consensus":
                result = self._action_consensus(params)
            elif action == "multi_consensus":
                result = self._action_multi(params)
            elif action == "aggregate":
                result = self._action_aggregate(params)
            else:
                return NodeOutput(
                    request_id=input_.request_id,
                    success=False,
                    errors=[f"Unknown action: {action!r}"],
                )
        except Exception as exc:
            self._error_count += 1
            logger.exception("TopTradersNode.execute error (action=%s)", action)
            return NodeOutput(
                request_id=input_.request_id,
                success=False,
                errors=[str(exc)],
            )

        latency_ms = (time.time() - t0) * 1000
        self._total_latency_ms += latency_ms
        return NodeOutput(
            request_id=input_.request_id,
            success=True,
            result=result,
            metrics={"latency_ms": latency_ms},
        )

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _action_consensus(self, params: dict[str, Any]) -> dict[str, Any]:
        condition_id = params.get("condition_id", "")
        outcome = params.get("outcome", "YES")
        consensus = get_consensus(self._clob, condition_id, outcome)
        return consensus.to_dict()

    def _action_multi(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        condition_ids = params.get("condition_ids", [])
        outcome = params.get("outcome", "YES")
        multi = get_multi_market_consensus(self._clob, condition_ids, outcome)
        return [c.to_dict() for c in multi.values()]

    def _action_aggregate(self, params: dict[str, Any]) -> dict[str, Any]:
        condition_ids = params.get("condition_ids", [])
        outcome = params.get("outcome", "YES")
        multi = get_multi_market_consensus(self._clob, condition_ids, outcome)
        summary = aggregate_consensus(list(multi.values()))
        summary["signals"] = [c.to_dict() for c in multi.values()]
        return summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_token_id(market: Any, outcome: str) -> str:
    """Return the token_id for the given outcome from a MarketInfo object."""
    for tok in market.tokens:
        if isinstance(tok, dict):
            if tok.get("outcome", "").upper() == outcome.upper():
                token_id: str = tok.get("token_id", "")
                return token_id
        else:
            if getattr(tok, "outcome", "").upper() == outcome.upper():
                attr_token_id: str = getattr(tok, "token_id", "")
                return attr_token_id
    return ""
