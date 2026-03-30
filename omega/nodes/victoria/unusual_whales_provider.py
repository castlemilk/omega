"""
omega.nodes.victoria.unusual_whales_provider
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unusual Whales API client — options flow, dark pool, congressional trading,
insider transactions, and IV rank data.

Official API: https://api.unusualwhales.com/api
MCP server:   https://github.com/unusual-whales/unusual-whales-official-mcp

Endpoint categories implemented (skeleton — requires UW_API_KEY):
  - Flow      : options flow tape, net flow by expiry, sector flow
  - Dark Pool : transactions with NBBO context
  - Congress  : congressional trades, late filings
  - Insider   : insider transactions by ticker
  - Stock     : IV rank, options flow per ticker, max pain
  - Market    : market overview / sector tide

Data policy:
  - Zero external dependencies (urllib.request only)
  - 5-minute TTL cache (UW data updates ~every few minutes)
  - Circuit breaker on 3 consecutive failures
  - Never raises — returns None gracefully on any failure
  - API key read from UW_API_KEY environment variable

Authentication:
  Set UW_API_KEY in your environment or .env file.
  Keys are available at: https://unusualwhales.com/settings/api-dashboard
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

from omega.core.circuit_breaker import CircuitBreaker
from omega.core.degradation import get_registry as _get_registry

logger = logging.getLogger("omega.nodes.victoria.unusual_whales_provider")

_UW_API_KEY = os.environ.get("UW_API_KEY", "")
_UW_BASE_URL = "https://api.unusualwhales.com/api"

# Cache TTL: UW flow data updates every few minutes; 5 min is safe
_CACHE_TTL_SECONDS = 300

# Tickers that map to crypto/broad-market context (BTC-related equities + ETFs)
_CRYPTO_PROXY_TICKERS = ["MSTR", "COIN", "IBIT", "GBTC", "FBTC", "BITO"]


def _make_headers() -> dict[str, str]:
    """Build request headers, injecting API key if available."""
    headers = {
        "User-Agent": "OmegaVictoria/1.0 (quantitative research bot)",
        "Accept": "application/json",
    }
    if _UW_API_KEY:
        headers["Authorization"] = f"Bearer {_UW_API_KEY}"
    return headers


def _fetch_json(url: str, timeout: float = 10.0) -> Any | None:
    """
    HTTP GET + JSON parse. Returns parsed JSON or None on any error.
    Does not raise.
    """
    if not _UW_API_KEY:
        logger.debug("UW_API_KEY not set — skipping %s", url)
        return None
    try:
        req = urllib.request.Request(url, headers=_make_headers())
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        logger.warning("UW HTTP %s for %s", exc.code, url)
        return None
    except urllib.error.URLError as exc:
        logger.warning("UW URL error for %s: %s", url, exc.reason)
        return None
    except Exception as exc:
        logger.warning("UW fetch error for %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# FlowClient — options flow tape
# ---------------------------------------------------------------------------


class FlowClient:
    """
    Fetches live options flow data from Unusual Whales.

    Endpoints:
      GET /api/flow/alerts            — recent unusual options alerts
      GET /api/flow/full-tape         — complete options tape (paginated)
      GET /api/flow/net-flow          — net call vs put premium by expiry bucket
      GET /api/flow/sector-flow       — sector-level net flow
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cb = CircuitBreaker("unusual_whales_flow", failure_threshold=3, recovery_timeout=300)

    def _cached(self, key: str, fn, *args) -> Any | None:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data
        try:
            result = self._cb.call(fn, *args)
            if result is not None:
                _get_registry().mark_healthy("unusual_whales_flow")
                self._cache[key] = (time.time(), result)
            else:
                _get_registry().mark_degraded(
                    "unusual_whales_flow", reason="empty response", fallback="none"
                )
        except Exception as exc:
            _get_registry().mark_degraded(
                "unusual_whales_flow", reason=str(exc)[:80], fallback="none"
            )
            return None
        return result

    def get_alerts(self, limit: int = 100) -> list[dict[str, Any]] | None:
        """
        Recent unusual options alerts — large premium, high IV, unusual volume.

        Returns list of alert dicts with fields:
          ticker, expiry, strike, type (call/put), premium, iv, volume, open_interest,
          unusual_volume_ratio, timestamp
        """
        url = f"{_UW_BASE_URL}/flow/alerts?limit={limit}"
        return self._cached(f"alerts:{limit}", _fetch_json, url)

    def get_full_tape(self, limit: int = 200) -> list[dict[str, Any]] | None:
        """
        Full options tape — every options transaction above a size threshold.

        Returns list of trade dicts with fields:
          ticker, expiry, strike, type, premium, size, price, iv,
          side (bid/ask), timestamp
        """
        url = f"{_UW_BASE_URL}/flow/full-tape?limit={limit}"
        return self._cached(f"tape:{limit}", _fetch_json, url)

    def get_net_flow(self) -> dict[str, Any] | None:
        """
        Net call vs put premium aggregated by expiry bucket (0dte, 1w, 1m, 3m, 6m+).

        Returns dict with fields:
          buckets: [{expiry_bucket, net_call_premium, net_put_premium, ratio}]
          overall_ratio: float  (>1.0 = call-dominated, <1.0 = put-dominated)
          timestamp: str
        """
        url = f"{_UW_BASE_URL}/flow/net-flow"
        return self._cached("net_flow", _fetch_json, url)

    def get_sector_flow(self) -> list[dict[str, Any]] | None:
        """
        Net options premium flow by market sector.

        Returns list of sector dicts with fields:
          sector, net_call_premium, net_put_premium, ratio, ticker_count, timestamp
        """
        url = f"{_UW_BASE_URL}/flow/sector-flow"
        return self._cached("sector_flow", _fetch_json, url)


# ---------------------------------------------------------------------------
# DarkPoolClient — off-exchange transactions
# ---------------------------------------------------------------------------


class DarkPoolClient:
    """
    Fetches dark pool (off-exchange) transaction data.

    Endpoints:
      GET /api/darkpool/{ticker}   — dark pool trades for a specific ticker
      GET /api/darkpool/recent     — recent large dark pool prints across all tickers
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cb = CircuitBreaker(
            "unusual_whales_darkpool", failure_threshold=3, recovery_timeout=300
        )

    def _cached(self, key: str, fn, *args) -> Any | None:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data
        try:
            result = self._cb.call(fn, *args)
            if result is not None:
                _get_registry().mark_healthy("unusual_whales_darkpool")
                self._cache[key] = (time.time(), result)
            else:
                _get_registry().mark_degraded(
                    "unusual_whales_darkpool", reason="empty response", fallback="none"
                )
        except Exception as exc:
            _get_registry().mark_degraded(
                "unusual_whales_darkpool", reason=str(exc)[:80], fallback="none"
            )
            return None
        return result

    def get_ticker_prints(self, ticker: str, limit: int = 50) -> list[dict[str, Any]] | None:
        """
        Dark pool transactions for a specific ticker with NBBO context.

        Returns list of print dicts with fields:
          ticker, price, size, notional_value, nbbo_bid, nbbo_ask, premium_to_nbbo,
          exchange, timestamp
        """
        url = f"{_UW_BASE_URL}/darkpool/{ticker}?limit={limit}"
        return self._cached(f"dp:{ticker}:{limit}", _fetch_json, url)

    def get_recent_prints(self, min_notional: int = 1_000_000) -> list[dict[str, Any]] | None:
        """
        Recent dark pool prints across all tickers above a notional threshold.

        Args:
          min_notional: minimum trade size in USD (default $1M)

        Returns list of print dicts (same schema as get_ticker_prints).
        """
        url = f"{_UW_BASE_URL}/darkpool/recent?min_notional={min_notional}"
        return self._cached(f"dp_recent:{min_notional}", _fetch_json, url)


# ---------------------------------------------------------------------------
# CongressClient — congressional trading
# ---------------------------------------------------------------------------


class CongressClient:
    """
    Fetches congressional trading data.

    Congressional members are required to disclose trades within 45 days
    (STOCK Act). Late filings and clusters often precede market moves.

    Endpoints:
      GET /api/congress/trades          — recent disclosed trades
      GET /api/congress/late-filings    — members with overdue disclosures
      GET /api/congress/member/{member} — specific member's trade history
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        # Congress data updates slowly; longer circuit breaker recovery is fine
        self._cb = CircuitBreaker(
            "unusual_whales_congress", failure_threshold=3, recovery_timeout=600
        )

    def _cached(self, key: str, fn, *args) -> Any | None:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data
        try:
            result = self._cb.call(fn, *args)
            if result is not None:
                _get_registry().mark_healthy("unusual_whales_congress")
                self._cache[key] = (time.time(), result)
        except Exception as exc:
            _get_registry().mark_degraded(
                "unusual_whales_congress", reason=str(exc)[:80], fallback="none"
            )
            return None
        return result

    def get_recent_trades(self, limit: int = 100) -> list[dict[str, Any]] | None:
        """
        Recently disclosed congressional trades.

        Returns list of trade dicts with fields:
          member_name, chamber (house/senate), party, state, ticker,
          action (buy/sell), amount_range, filed_date, trade_date,
          days_to_disclosure, asset_description
        """
        url = f"{_UW_BASE_URL}/congress/trades?limit={limit}"
        return self._cached(f"congress_trades:{limit}", _fetch_json, url)

    def get_late_filings(self) -> list[dict[str, Any]] | None:
        """
        Members with overdue trade disclosures (>45 days past trade date).

        Returns list of member dicts with fields:
          member_name, chamber, party, overdue_count, oldest_pending_days
        """
        url = f"{_UW_BASE_URL}/congress/late-filings"
        return self._cached("congress_late", _fetch_json, url)

    def get_member_trades(self, member: str) -> list[dict[str, Any]] | None:
        """
        Full trade history for a specific congressional member.

        Args:
          member: URL-encoded member name (e.g. "nancy-pelosi")
        """
        url = f"{_UW_BASE_URL}/congress/member/{member}"
        return self._cached(f"congress_member:{member}", _fetch_json, url)


# ---------------------------------------------------------------------------
# InsiderClient — corporate insider transactions
# ---------------------------------------------------------------------------


class InsiderClient:
    """
    Fetches SEC Form 4 insider transaction data.

    Endpoints:
      GET /api/insider/{ticker}         — insider trades for a ticker
      GET /api/insider/sector-flow      — net insider buy/sell by sector
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cb = CircuitBreaker(
            "unusual_whales_insider", failure_threshold=3, recovery_timeout=300
        )

    def _cached(self, key: str, fn, *args) -> Any | None:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data
        try:
            result = self._cb.call(fn, *args)
            if result is not None:
                _get_registry().mark_healthy("unusual_whales_insider")
                self._cache[key] = (time.time(), result)
        except Exception as exc:
            _get_registry().mark_degraded(
                "unusual_whales_insider", reason=str(exc)[:80], fallback="none"
            )
            return None
        return result

    def get_ticker_flow(self, ticker: str, limit: int = 50) -> list[dict[str, Any]] | None:
        """
        Insider transactions for a specific ticker.

        Returns list of transaction dicts with fields:
          insider_name, title, transaction_type (buy/sell/award), shares,
          price, value, ownership_type (direct/indirect), filed_date, trade_date
        """
        url = f"{_UW_BASE_URL}/insider/{ticker}?limit={limit}"
        return self._cached(f"insider:{ticker}:{limit}", _fetch_json, url)

    def get_sector_flow(self) -> list[dict[str, Any]] | None:
        """
        Net insider buy vs sell aggregated by sector.

        Returns list of sector dicts with fields:
          sector, net_buy_count, net_sell_count, net_value, ratio
        """
        url = f"{_UW_BASE_URL}/insider/sector-flow"
        return self._cached("insider_sector", _fetch_json, url)


# ---------------------------------------------------------------------------
# StockOptionsClient — per-ticker options intelligence
# ---------------------------------------------------------------------------


class StockOptionsClient:
    """
    Per-ticker options data: IV rank, max pain, and options flow.

    Endpoints:
      GET /api/stock/{ticker}/iv-rank         — IV rank (0–100) + IV percentile
      GET /api/stock/{ticker}/options-flow    — options flow for a single ticker
      GET /api/stock/{ticker}/max-pain        — max pain price by expiry
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cb = CircuitBreaker(
            "unusual_whales_stock", failure_threshold=3, recovery_timeout=300
        )

    def _cached(self, key: str, fn, *args) -> Any | None:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data
        try:
            result = self._cb.call(fn, *args)
            if result is not None:
                _get_registry().mark_healthy("unusual_whales_stock")
                self._cache[key] = (time.time(), result)
        except Exception as exc:
            _get_registry().mark_degraded(
                "unusual_whales_stock", reason=str(exc)[:80], fallback="none"
            )
            return None
        return result

    def get_iv_rank(self, ticker: str) -> dict[str, Any] | None:
        """
        IV rank and IV percentile for a ticker.

        Returns dict with fields:
          ticker, iv_rank (0–100), iv_percentile (0–100),
          current_iv, iv_30d_high, iv_30d_low, iv_52w_high, iv_52w_low
        """
        url = f"{_UW_BASE_URL}/stock/{ticker}/iv-rank"
        return self._cached(f"iv_rank:{ticker}", _fetch_json, url)

    def get_ticker_flow(self, ticker: str, limit: int = 50) -> list[dict[str, Any]] | None:
        """
        Options flow for a specific ticker (calls + puts combined).

        Returns same schema as FlowClient.get_alerts() but filtered to one ticker.
        """
        url = f"{_UW_BASE_URL}/stock/{ticker}/options-flow?limit={limit}"
        return self._cached(f"stock_flow:{ticker}:{limit}", _fetch_json, url)

    def get_max_pain(self, ticker: str) -> list[dict[str, Any]] | None:
        """
        Max pain price per expiry date.

        Returns list of expiry dicts with fields:
          expiry, max_pain_price, open_interest_calls, open_interest_puts
        """
        url = f"{_UW_BASE_URL}/stock/{ticker}/max-pain"
        return self._cached(f"max_pain:{ticker}", _fetch_json, url)


# ---------------------------------------------------------------------------
# UnusualWhalesProvider — high-level facade used by signal generators
# ---------------------------------------------------------------------------


class UnusualWhalesProvider:
    """
    Facade over all Unusual Whales API clients.

    Usage::

        provider = UnusualWhalesProvider()

        # Options flow signal inputs
        flow_data = provider.get_flow_summary()

        # Dark pool accumulation check
        dp_data = provider.get_dark_pool_summary(tickers=["MSTR", "COIN"])

        # Congressional alpha
        congress_data = provider.get_congress_summary()

    All methods return None if the API key is not set or the API is unavailable.
    """

    def __init__(self) -> None:
        self.flow = FlowClient()
        self.dark_pool = DarkPoolClient()
        self.congress = CongressClient()
        self.insider = InsiderClient()
        self.stock_options = StockOptionsClient()
        self._api_key_present = bool(_UW_API_KEY)

    @property
    def is_configured(self) -> bool:
        """True if UW_API_KEY is present in the environment."""
        return self._api_key_present

    def get_flow_summary(self) -> dict[str, Any] | None:
        """
        Aggregate options flow signal inputs.

        Returns dict with:
          net_flow: net call/put ratio (from FlowClient.get_net_flow)
          alerts: recent unusual alerts (from FlowClient.get_alerts)
          sector_flow: sector-level flow (from FlowClient.get_sector_flow)
          signal_available: bool — False if any component is unavailable
        """
        if not self._api_key_present:
            return {"signal_available": False, "reason": "UW_API_KEY not configured"}

        net_flow = self.flow.get_net_flow()
        alerts = self.flow.get_alerts(limit=50)
        sector_flow = self.flow.get_sector_flow()

        return {
            "net_flow": net_flow,
            "alerts": alerts,
            "sector_flow": sector_flow,
            "signal_available": net_flow is not None,
        }

    def get_dark_pool_summary(self, tickers: list[str] | None = None) -> dict[str, Any] | None:
        """
        Aggregate dark pool signal inputs for a list of tickers.

        If tickers is None, uses _CRYPTO_PROXY_TICKERS (MSTR, COIN, IBIT, etc.).

        Returns dict with:
          ticker_prints: {ticker: [prints]} for each requested ticker
          recent_large: large prints across all tickers (≥$1M)
          signal_available: bool
        """
        if not self._api_key_present:
            return {"signal_available": False, "reason": "UW_API_KEY not configured"}

        tickers = tickers or _CRYPTO_PROXY_TICKERS
        ticker_prints: dict[str, Any] = {}
        for t in tickers:
            prints = self.dark_pool.get_ticker_prints(t, limit=20)
            if prints is not None:
                ticker_prints[t] = prints

        recent_large = self.dark_pool.get_recent_prints(min_notional=1_000_000)

        return {
            "ticker_prints": ticker_prints,
            "recent_large": recent_large,
            "signal_available": bool(ticker_prints) or recent_large is not None,
        }

    def get_congress_summary(self) -> dict[str, Any] | None:
        """
        Congressional trading signal inputs.

        Returns dict with:
          recent_trades: list of recent congressional trades
          late_filings: members with overdue disclosures
          signal_available: bool
        """
        if not self._api_key_present:
            return {"signal_available": False, "reason": "UW_API_KEY not configured"}

        trades = self.congress.get_recent_trades(limit=50)
        late = self.congress.get_late_filings()

        return {
            "recent_trades": trades,
            "late_filings": late,
            "signal_available": trades is not None,
        }

    def get_iv_rank_summary(self, tickers: list[str] | None = None) -> dict[str, Any] | None:
        """
        IV rank data for a list of tickers (for VRP signal enhancement).

        Returns dict with:
          iv_ranks: {ticker: iv_rank_data}
          signal_available: bool
        """
        if not self._api_key_present:
            return {"signal_available": False, "reason": "UW_API_KEY not configured"}

        tickers = tickers or _CRYPTO_PROXY_TICKERS
        iv_ranks: dict[str, Any] = {}
        for t in tickers:
            rank = self.stock_options.get_iv_rank(t)
            if rank is not None:
                iv_ranks[t] = rank

        return {
            "iv_ranks": iv_ranks,
            "signal_available": bool(iv_ranks),
        }

    def health_check(self) -> dict[str, Any]:
        """Return provider health status for the monitoring dashboard."""
        return {
            "provider": "unusual_whales",
            "api_key_configured": self._api_key_present,
            "clients": {
                "flow": "circuit_breaker_check_not_implemented",
                "dark_pool": "circuit_breaker_check_not_implemented",
                "congress": "circuit_breaker_check_not_implemented",
                "insider": "circuit_breaker_check_not_implemented",
                "stock_options": "circuit_breaker_check_not_implemented",
            },
        }


# Module-level singleton — imported by signal generators and node adapters
_provider: UnusualWhalesProvider | None = None


def get_provider() -> UnusualWhalesProvider:
    """Return the module-level UnusualWhalesProvider singleton."""
    global _provider
    if _provider is None:
        _provider = UnusualWhalesProvider()
    return _provider
