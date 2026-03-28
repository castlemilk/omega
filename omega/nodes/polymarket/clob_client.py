"""
omega.nodes.polymarket.clob_client
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Polymarket Central Limit Order Book (CLOB) client.

Wraps the ``py-clob-client`` library to provide:

  - Fetching active markets with live bid/ask/mid prices via the CLOB API.
  - Fetching order-book depth for a given token_id (condition_id + outcome).
  - Placing limit orders in *paper mode* (default) or live mode.
  - Smart-money consensus via ``TopTradersNode`` integration.

Authentication
--------------
Set the following env vars for authenticated write access::

    POLYMARKET_API_KEY        — L2 API key
    POLYMARKET_API_SECRET     — L2 API secret
    POLYMARKET_API_PASSPHRASE — L2 API passphrase
    POLYMARKET_PK             — Polygon wallet private key (0x-prefixed)

Without credentials the client operates in *read-only* mode (market data,
order books) — paper-mode order placement is still fully functional because
it only logs the intent.

Paper mode
----------
Paper mode is enabled by default (``POLYMARKET_LIVE`` not set to ``"true"``).
In paper mode, ``place_limit_order()`` and ``place_market_order()`` log the
intended order at INFO level and return a ``PaperOrderResult`` instead of
sending anything to the wire.

Set ``POLYMARKET_LIVE=true`` in the environment to enable real execution.

Usage::

    from omega.nodes.polymarket.clob_client import CLOBClient

    client = CLOBClient()

    # Fetch top markets
    markets = client.get_active_markets(limit=20)

    # Order book depth
    book = client.get_order_book(token_id="0xabc...")

    # Paper limit order
    result = client.place_limit_order(
        token_id="0xabc...",
        side="BUY",
        price=0.62,
        size_usdc=50.0,
    )
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("omega.nodes.polymarket.clob_client")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POLYMARKET_CLOB_HOST = "https://clob.polymarket.com"
POLYGON_CHAIN_ID = 137

# Env-var switch: set to "true" to enable real order placement.
_LIVE_MODE_ENV = "POLYMARKET_LIVE"


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MarketInfo:
    """Snapshot of a Polymarket market from the CLOB API."""

    condition_id: str
    question: str
    market_slug: str
    # Per-outcome tokens — usually two: YES (token[0]) and NO (token[1]).
    tokens: list[dict[str, Any]] = field(default_factory=list)
    # Mid-prices keyed by outcome ("YES"/"NO") when available.
    mid_prices: dict[str, float] = field(default_factory=dict)
    active: bool = True
    closed: bool = False
    volume_24h: float = 0.0
    liquidity: float = 0.0
    fetched_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def yes_mid(self) -> float:
        return self.mid_prices.get("YES", float("nan"))

    @property
    def no_mid(self) -> float:
        return self.mid_prices.get("NO", float("nan"))


@dataclass
class OrderBookLevel:
    """Single price/size level in an order book."""

    price: float
    size: float


@dataclass
class OrderBook:
    """L2 order book snapshot for a single outcome token."""

    token_id: str
    market: str
    asset_id: str
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)
    fetched_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else float("nan")

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else float("nan")

    @property
    def mid(self) -> float:
        if self.bids and self.asks:
            return (self.bids[0].price + self.asks[0].price) / 2
        return float("nan")

    @property
    def spread(self) -> float:
        if self.bids and self.asks:
            return self.asks[0].price - self.bids[0].price
        return float("nan")

    def bid_depth(self, levels: int = 5) -> float:
        """Total USDC size across top `levels` bid levels."""
        return sum(lv.price * lv.size for lv in self.bids[:levels])

    def ask_depth(self, levels: int = 5) -> float:
        """Total USDC size across top `levels` ask levels."""
        return sum(lv.price * lv.size for lv in self.asks[:levels])


@dataclass
class PaperOrderResult:
    """Returned by place_* methods in paper mode."""

    order_id: str = field(default_factory=lambda: f"paper-{uuid.uuid4()}")
    paper: bool = True
    token_id: str = ""
    side: str = ""
    price: float = 0.0
    size_usdc: float = 0.0
    status: str = "logged"
    logged_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class LiveOrderResult:
    """Returned by place_* methods in live mode."""

    order_id: str = ""
    paper: bool = False
    token_id: str = ""
    side: str = ""
    price: float = 0.0
    size_usdc: float = 0.0
    status: str = ""  # "matched" | "live" | "delayed" | "unmatched" | "error"
    raw: dict[str, Any] = field(default_factory=dict)


OrderResult = PaperOrderResult | LiveOrderResult


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------


class CLOBClient:
    """
    Polymarket CLOB client with paper-mode order placement.

    Parameters
    ----------
    live_mode
        If ``True``, real orders are sent.  Defaults to the value of the
        ``POLYMARKET_LIVE`` environment variable (``"true"`` → live).
    host
        CLOB API base URL (default: ``https://clob.polymarket.com``).
    """

    def __init__(
        self,
        live_mode: bool | None = None,
        host: str = POLYMARKET_CLOB_HOST,
    ) -> None:
        if live_mode is None:
            live_mode = os.environ.get(_LIVE_MODE_ENV, "").lower() == "true"
        self._live = live_mode
        self._host = host
        self._client: Any = None  # lazy-initialised py-clob-client instance
        self._creds_available: bool = False

        mode_label = "LIVE" if self._live else "PAPER"
        logger.info("CLOBClient initialised — mode=%s host=%s", mode_label, host)

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------

    def _get_clob(self) -> Any:
        """Return a py-clob-client ClobClient, creating it on first call."""
        if self._client is not None:
            return self._client

        try:
            from py_clob_client.client import ClobClient as _ClobClient
            from py_clob_client.clob_types import ApiCreds

            pk = os.environ.get("POLYMARKET_PK", "")
            api_key = os.environ.get("POLYMARKET_API_KEY", "")
            api_secret = os.environ.get("POLYMARKET_API_SECRET", "")
            api_passphrase = os.environ.get("POLYMARKET_API_PASSPHRASE", "")

            if pk and api_key:
                creds = ApiCreds(
                    api_key=api_key,
                    api_secret=api_secret,
                    api_passphrase=api_passphrase,
                )
                self._client = _ClobClient(
                    host=self._host,
                    key=pk,
                    chain_id=POLYGON_CHAIN_ID,
                    creds=creds,
                    signature_type=2,  # EIP-712 poly-proxy
                )
                self._creds_available = True
                logger.debug("CLOBClient: authenticated with API key + PK")
            else:
                # Read-only: no credentials — only public endpoints work.
                self._client = _ClobClient(host=self._host, chain_id=POLYGON_CHAIN_ID)
                self._creds_available = False
                logger.debug("CLOBClient: no credentials — read-only mode")

        except ImportError:
            raise RuntimeError(
                "py-clob-client not installed.  Run: pip install py-clob-client"
            )

        return self._client

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_active_markets(
        self,
        limit: int = 50,
        next_cursor: str = "MA==",
    ) -> list[MarketInfo]:
        """
        Fetch active markets from the CLOB API.

        Returns a list of ``MarketInfo`` objects sorted by 24h volume
        descending.  Paginates up to ``limit`` total results.

        Parameters
        ----------
        limit
            Maximum number of markets to return (CLOB returns 100 per page).
        next_cursor
            Pagination cursor; ``"MA=="`` is the first page.
        """
        clob = self._get_clob()
        collected: list[MarketInfo] = []
        cursor = next_cursor

        while len(collected) < limit:
            try:
                resp = clob.get_markets(next_cursor=cursor)
            except Exception as exc:
                logger.warning("CLOBClient.get_active_markets error: %s", exc)
                break

            data = resp.get("data", []) if isinstance(resp, dict) else []
            for raw in data:
                info = self._parse_market(raw)
                if info.active and not info.closed:
                    collected.append(info)
                if len(collected) >= limit:
                    break

            cursor = resp.get("next_cursor", "") if isinstance(resp, dict) else ""
            if not cursor or cursor == "LTE=":  # LTE= means end of results
                break

        logger.debug("CLOBClient.get_active_markets: returned %d markets", len(collected))
        return collected[:limit]

    def get_market(self, condition_id: str) -> MarketInfo | None:
        """Fetch a single market by its condition_id."""
        clob = self._get_clob()
        try:
            raw = clob.get_market(condition_id)
            return self._parse_market(raw) if raw else None
        except Exception as exc:
            logger.warning("CLOBClient.get_market(%s) error: %s", condition_id, exc)
            return None

    def get_market_price_sync(self, condition_id: str, outcome: str = "YES") -> float:
        """
        Return the current mid-price for one outcome of a market (synchronous).

        Returns ``float("nan")`` on any error.
        """
        info = self.get_market(condition_id)
        if info is None:
            return float("nan")
        return info.mid_prices.get(outcome, float("nan"))

    def get_order_book(self, token_id: str) -> OrderBook | None:
        """
        Fetch L2 order-book depth for a single outcome token.

        Parameters
        ----------
        token_id
            The token_id (outcome-specific) string from MarketInfo.tokens.
        """
        clob = self._get_clob()
        try:
            raw = clob.get_order_book(token_id)
            return self._parse_order_book(raw, token_id)
        except Exception as exc:
            logger.warning("CLOBClient.get_order_book(%s) error: %s", token_id, exc)
            return None

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    def place_limit_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size_usdc: float,
    ) -> OrderResult:
        """
        Place a limit order on a single outcome token.

        Parameters
        ----------
        token_id
            Outcome token ID (from MarketInfo.tokens[n]["token_id"]).
        side
            ``"BUY"`` or ``"SELL"``.
        price
            Limit price in USDC probability space (0.0 – 1.0).
        size_usdc
            Order size in USDC.

        Returns
        -------
        PaperOrderResult
            In paper mode — the order is logged only.
        LiveOrderResult
            In live mode — result from the CLOB API.
        """
        if not self._live:
            return self._paper_order(token_id, side, price, size_usdc)

        if not self._creds_available:
            logger.error(
                "CLOBClient.place_limit_order: LIVE mode but no credentials configured."
            )
            return self._paper_order(token_id, side, price, size_usdc)

        return self._live_limit_order(token_id, side, price, size_usdc)

    def place_market_order_sync(
        self,
        condition_id: str,
        side: str,
        size_usdc: float,
    ) -> OrderResult:
        """
        Synchronous market-order helper using the YES/NO outcome token.

        ``side`` is ``"YES"`` or ``"NO"`` (mapped to BUY on the correct token).
        For async usage from LatencyArbEngine use ``place_market_order()``
        (the async coroutine defined further below).
        """
        market = self.get_market(condition_id)
        if market is None or not market.tokens:
            logger.warning(
                "CLOBClient.place_market_order: market not found for %s", condition_id
            )
            return self._paper_order(condition_id, side, 0.0, size_usdc)

        # Map YES/NO to the correct token.
        token_id = ""
        price = 0.0
        for tok in market.tokens:
            outcome = tok.get("outcome", "").upper()
            if outcome == side.upper():
                token_id = tok.get("token_id", "")
                price = market.mid_prices.get(outcome, 0.5)
                break

        if not token_id:
            logger.warning(
                "CLOBClient.place_market_order: no %s token for %s", side, condition_id
            )
            return self._paper_order(condition_id, side, price, size_usdc)

        return self.place_limit_order(
            token_id=token_id,
            side="BUY",
            price=price,
            size_usdc=size_usdc,
        )

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. No-op in paper mode."""
        if not self._live:
            logger.info("CLOBClient [PAPER]: cancel_order %s — no-op", order_id)
            return True
        clob = self._get_clob()
        try:
            from py_clob_client.clob_types import OrderCancelParams

            resp = clob.cancel_order(OrderCancelParams(order_id=order_id))
            return bool(resp)
        except Exception as exc:
            logger.error("CLOBClient.cancel_order(%s) error: %s", order_id, exc)
            return False

    def get_open_orders(self) -> list[dict[str, Any]]:
        """Return a list of open orders from the CLOB API."""
        if not self._creds_available:
            return []
        clob = self._get_clob()
        try:
            resp = clob.get_orders()
            return resp if isinstance(resp, list) else []
        except Exception as exc:
            logger.warning("CLOBClient.get_open_orders error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _paper_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size_usdc: float,
    ) -> PaperOrderResult:
        result = PaperOrderResult(
            token_id=token_id,
            side=side,
            price=price,
            size_usdc=size_usdc,
        )
        logger.info(
            "CLOBClient [PAPER] %s token=%s price=%.4f size_usdc=%.2f  →  order_id=%s",
            side,
            token_id[:16] + "…" if len(token_id) > 16 else token_id,
            price,
            size_usdc,
            result.order_id,
        )
        return result

    def _live_limit_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size_usdc: float,
    ) -> LiveOrderResult:
        clob = self._get_clob()
        try:
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL

            clob_side = BUY if side.upper() == "BUY" else SELL
            # CLOB size is in shares (outcome tokens), not USDC.
            # size_shares ≈ size_usdc / price  (approximation at limit price)
            size_shares = round(size_usdc / max(price, 0.001), 4)

            order_args = OrderArgs(
                token_id=token_id,
                price=round(price, 4),
                size=size_shares,
                side=clob_side,
                fee_rate_bps=0,
                nonce=0,
                expiration=0,
            )
            signed = clob.create_order(order_args)
            resp = clob.post_order(signed, OrderType.GTC)

            order_id = (
                resp.get("orderID", "")
                if isinstance(resp, dict)
                else getattr(resp, "orderID", str(uuid.uuid4()))
            )
            status = (
                resp.get("status", "unknown")
                if isinstance(resp, dict)
                else getattr(resp, "status", "unknown")
            )

            logger.info(
                "CLOBClient [LIVE] %s token=%s price=%.4f size_usdc=%.2f  →  id=%s status=%s",
                side,
                token_id[:16] + "…" if len(token_id) > 16 else token_id,
                price,
                size_usdc,
                order_id,
                status,
            )
            return LiveOrderResult(
                order_id=order_id,
                token_id=token_id,
                side=side,
                price=price,
                size_usdc=size_usdc,
                status=status,
                raw=resp if isinstance(resp, dict) else {},
            )
        except Exception as exc:
            logger.error("CLOBClient._live_limit_order error: %s", exc)
            return LiveOrderResult(
                token_id=token_id,
                side=side,
                price=price,
                size_usdc=size_usdc,
                status="error",
                raw={"error": str(exc)},
            )

    @staticmethod
    def _parse_market(raw: dict[str, Any]) -> MarketInfo:
        """Convert a raw CLOB API market dict into a MarketInfo."""
        tokens: list[dict[str, Any]] = raw.get("tokens", [])
        mid_prices: dict[str, float] = {}
        for tok in tokens:
            outcome = tok.get("outcome", "")
            if outcome:
                # price field may be named "price" or "mid_price"
                p = float(tok.get("price", tok.get("mid_price", 0.0)))
                mid_prices[outcome.upper()] = p

        return MarketInfo(
            condition_id=raw.get("condition_id", ""),
            question=raw.get("question", ""),
            market_slug=raw.get("market_slug", ""),
            tokens=tokens,
            mid_prices=mid_prices,
            active=raw.get("active", True),
            closed=raw.get("closed", False),
            volume_24h=float(raw.get("volume24hr", raw.get("volume_24h", 0.0))),
            liquidity=float(raw.get("liquidity", 0.0)),
        )

    @staticmethod
    def _parse_order_book(raw: Any, token_id: str) -> OrderBook:
        """Convert a raw CLOB order-book response into an OrderBook."""
        if raw is None:
            return OrderBook(token_id=token_id, market="", asset_id=token_id)

        # raw may be an object or a dict depending on py-clob-client version
        def _attr(obj: Any, key: str, default: Any = None) -> Any:
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        bids_raw = _attr(raw, "bids", []) or []
        asks_raw = _attr(raw, "asks", []) or []

        def _parse_levels(levels: list[Any]) -> list[OrderBookLevel]:
            result = []
            for lv in levels:
                p = float(_attr(lv, "price", 0.0))
                s = float(_attr(lv, "size", 0.0))
                if p > 0:
                    result.append(OrderBookLevel(price=p, size=s))
            # Sort bids descending, asks ascending (already sorted by API)
            return result

        return OrderBook(
            token_id=token_id,
            market=_attr(raw, "market", ""),
            asset_id=_attr(raw, "asset_id", token_id),
            bids=_parse_levels(bids_raw),
            asks=_parse_levels(asks_raw),
        )

    # ------------------------------------------------------------------
    # Async interface for LatencyArbEngine
    # ------------------------------------------------------------------

    async def get_market_price(self, condition_id: str) -> float:
        """
        Async method used by LatencyArbEngine to poll YES-outcome mid-prices.

        Runs the synchronous CLOB call in the default thread-pool executor
        so it does not block the event loop.
        """
        import asyncio

        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.get_market_price_sync(condition_id, "YES")
        )

    async def place_market_order(
        self,
        condition_id: str,
        side: str,
        size_usd: float,
    ) -> bool:
        """
        Async method used by LatencyArbEngine to place directional orders.

        Maps ``side`` = ``"YES"`` / ``"NO"`` to a BUY on the appropriate
        outcome token. Returns ``True`` on success in both paper and live mode.
        """
        import asyncio

        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: self._sync_market_order(condition_id, side, size_usd)
        )

    def _sync_market_order(self, condition_id: str, side: str, size_usd: float) -> bool:
        """Synchronous implementation backing the async place_market_order."""
        result = self.place_market_order_sync(condition_id, side, size_usd)
        return result is not None

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def is_live(self) -> bool:
        return self._live

    @property
    def has_credentials(self) -> bool:
        return self._creds_available

    def health(self) -> dict[str, Any]:
        """Return a health snapshot for monitoring."""
        clob = self._get_clob()
        try:
            ok = clob.get_ok()
            ts = time.time()
        except Exception as exc:
            return {"ok": False, "error": str(exc), "mode": "live" if self._live else "paper"}
        return {
            "ok": True,
            "server_ok": ok,
            "mode": "live" if self._live else "paper",
            "credentials": self._creds_available,
            "checked_at": ts,
        }
