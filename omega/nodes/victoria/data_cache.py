"""
omega/nodes/victoria/data_cache.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Local SQLite cache for slow-updating macro signals.

FRED data (Treasury yields, Dollar Index, VIX) updates at most once per day
(~3:30 PM ET). Fetching from the API every training cycle wastes rate-limit
budget and adds latency. This module caches observations locally and refreshes
only when stale.

Schema (macro_cache.db):
    series_id TEXT  — FRED series identifier (e.g. "DGS10")
    date TEXT       — observation date (YYYY-MM-DD)
    value REAL      — observation value
    fetched_at TEXT — ISO-8601 timestamp of when this row was written
    PRIMARY KEY (series_id, date)

Funding rates are stored in a separate table (same db) because they update
every 8 hours (perpetual settlement cycle) rather than daily:
    funding_rate_cache(symbol TEXT, rate REAL, fetched_at TEXT, PRIMARY KEY symbol)

Usage:
    from omega.nodes.victoria.data_cache import MacroDataCache
    cache = MacroDataCache()
    data = cache.get("DGS10", lookback_days=90)   # [{date, value}, ...]
    cache.warm_up()                                 # refresh all stale series at startup
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.data_cache")

# ── Constants ──────────────────────────────────────────────────────────────────

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
_FRED_TIMEOUT = 15.0
_MACRO_STALE_HOURS = 4  # FRED data: refresh if older than 4 hours
_FUNDING_STALE_HOURS = 8  # Funding rates: refresh every 8 hours (settlement cycle)

# Module-level set of FRED series that returned HTTP 4xx this session.
# Shared across ALL MacroDataCache instances in the same process to prevent
# repeated failed fetches after DEMO_KEY hits the 30 req/day limit.
_FRED_PERM_FAILED: set[str] = set()

# FRED series to warm up at training startup
MACRO_SERIES = ["DGS2", "DGS10", "DTWEXBGS", "VIXCLS"]

# OKX instrument map: our symbol → OKX instrument ID
_OKX_INST_MAP = {
    "BTCUSDT": "BTC-USDT-SWAP",
    "ETHUSDT": "ETH-USDT-SWAP",
    "SOLUSDT": "SOL-USDT-SWAP",
    "LINKUSDT": "LINK-USDT-SWAP",
    "AVAXUSDT": "AVAX-USDT-SWAP",
}
_OKX_FUNDING_URL = "https://www.okx.com/api/v5/public/funding-rate"

# Coinbase Advanced Trade API — public market data (no auth required)
_COINBASE_AT_API = "https://api.coinbase.com/api/v3/brokerage/market/products"
_COINBASE_INTX_MAP = {
    "BTCUSDT": "BTC-PERP-INTX",
    "ETHUSDT": "ETH-PERP-INTX",
    "SOLUSDT": "SOL-PERP-INTX",
    "LINKUSDT": "LINK-PERP-INTX",
    "AVAXUSDT": "AVAX-PERP-INTX",
}


# ── Database path ──────────────────────────────────────────────────────────────


def _default_db_path() -> Path:
    root = Path(__file__).resolve().parent.parent.parent.parent  # project root
    return root / "data" / "macro_cache.db"


# ── MacroDataCache ─────────────────────────────────────────────────────────────


class MacroDataCache:
    """
    SQLite-backed local cache for FRED macro series and funding rates.

    Thread-safe: uses a per-instance lock around all write operations.
    Multiple instances sharing the same db_path are safe because SQLite
    WAL mode serialises concurrent writes.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._api_key = os.environ.get("FRED_API_KEY", "DEMO_KEY")
        if self._api_key == "DEMO_KEY":
            logger.warning(
                "MacroDataCache: FRED_API_KEY not set — using DEMO_KEY (30 req/day limit). "
                "Set FRED_API_KEY env var for full access."
            )
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    # ── Public API ─────────────────────────────────────────────────────────────

    def get(self, series_id: str, lookback_days: int = 90) -> list[dict[str, Any]]:
        """
        Return cached observations for a FRED series.

        Triggers a refresh first if the cache is stale (> 4 hours old).
        Returns a list of dicts: [{"date": "YYYY-MM-DD", "value": float}, ...]
        sorted oldest-first. Empty list if no data available.
        """
        if self._is_macro_stale(series_id):
            self._refresh_macro(series_id)
        return self._read_macro(series_id, lookback_days)

    def get_values(self, series_id: str, lookback_days: int = 90) -> list[float]:
        """Convenience: return just the float values (oldest first)."""
        return [row["value"] for row in self.get(series_id, lookback_days)]

    def get_funding_rate(self, symbol: str) -> float | None:
        """
        Return the cached funding rate for a symbol.

        Refreshes from OKX (falling back to CoinGecko) if stale (> 8 hours).
        Returns None if unavailable.
        """
        if self._is_funding_stale(symbol):
            self._refresh_funding(symbol)
        return self._read_funding(symbol)

    def warm_up(self) -> None:
        """
        Refresh all stale series at training startup.

        Should be called once before the training loop begins. Logs which
        series were refreshed vs already fresh.
        """
        logger.info("MacroDataCache: warming up %d series …", len(MACRO_SERIES))
        for series_id in MACRO_SERIES:
            if self._is_macro_stale(series_id):
                logger.info("  [REFRESH] %s", series_id)
                self._refresh_macro(series_id)
            else:
                logger.info("  [FRESH]   %s", series_id)

    def refresh(self, series_id: str) -> None:
        """Force-refresh a FRED series regardless of staleness."""
        self._refresh_macro(series_id)

    # ── Schema ─────────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS macro_cache (
                    series_id  TEXT NOT NULL,
                    date       TEXT NOT NULL,
                    value      REAL NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY (series_id, date)
                );

                CREATE TABLE IF NOT EXISTS funding_rate_cache (
                    symbol     TEXT PRIMARY KEY NOT NULL,
                    rate       REAL NOT NULL,
                    fetched_at TEXT NOT NULL
                );
            """)
            self._conn.commit()

    # ── Staleness checks ───────────────────────────────────────────────────────

    def _is_macro_stale(self, series_id: str) -> bool:
        """True if no cache entry or newest fetched_at is older than _MACRO_STALE_HOURS."""
        row = self._conn.execute(
            "SELECT MAX(fetched_at) FROM macro_cache WHERE series_id = ?",
            (series_id,),
        ).fetchone()
        if not row or not row[0]:
            return True
        try:
            last = datetime.fromisoformat(row[0])
            # Make timezone-aware for comparison
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            age = datetime.now(UTC) - last
            return age > timedelta(hours=_MACRO_STALE_HOURS)
        except Exception:
            return True

    def _is_funding_stale(self, symbol: str) -> bool:
        """True if no cache entry or fetched_at is older than _FUNDING_STALE_HOURS."""
        row = self._conn.execute(
            "SELECT fetched_at FROM funding_rate_cache WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        if not row:
            return True
        try:
            last = datetime.fromisoformat(row[0])
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            age = datetime.now(UTC) - last
            return age > timedelta(hours=_FUNDING_STALE_HOURS)
        except Exception:
            return True

    # ── FRED fetch + upsert ────────────────────────────────────────────────────

    def _refresh_macro(self, series_id: str) -> None:
        """Fetch the last 120 observations from FRED and upsert into cache."""
        # Skip if FRED returned a 4xx for this series earlier in this session
        # (_FRED_PERM_FAILED is module-level so shared across all instances).
        if series_id in _FRED_PERM_FAILED:
            return
        observations = _fetch_fred_observations(series_id, self._api_key, n_obs=120)
        if not observations:
            logger.warning("MacroDataCache: no data returned for %s", series_id)
            # Write a sentinel so _is_macro_stale returns False for _MACRO_STALE_HOURS,
            # preventing repeated failed fetches every cycle.
            self._record_failed_fetch(series_id)
            return

        now_iso = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.executemany(
                """
                INSERT INTO macro_cache (series_id, date, value, fetched_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(series_id, date) DO UPDATE SET
                    value = excluded.value,
                    fetched_at = excluded.fetched_at
                """,
                [(series_id, obs["date"], obs["value"], now_iso) for obs in observations],
            )
            self._conn.commit()
        logger.info(
            "MacroDataCache: refreshed %s — %d observations (latest: %s=%.4f)",
            series_id,
            len(observations),
            observations[-1]["date"],
            observations[-1]["value"],
        )

    def _record_failed_fetch(self, series_id: str) -> None:
        """Insert a sentinel row so _is_macro_stale won't retry for _MACRO_STALE_HOURS."""
        now_iso = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO macro_cache (series_id, date, value, fetched_at)
                VALUES (?, '__failed__', 0.0, ?)
                ON CONFLICT(series_id, date) DO UPDATE SET fetched_at = excluded.fetched_at
                """,
                (series_id, now_iso),
            )
            self._conn.commit()

    # ── Read from cache ────────────────────────────────────────────────────────

    def _read_macro(self, series_id: str, lookback_days: int) -> list[dict[str, Any]]:
        cutoff = (datetime.now(UTC) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        rows = self._conn.execute(
            """
            SELECT date, value FROM macro_cache
            WHERE series_id = ? AND date >= ? AND date != '__failed__'
            ORDER BY date ASC
            """,
            (series_id, cutoff),
        ).fetchall()
        return [{"date": r[0], "value": r[1]} for r in rows]

    # ── Funding rate ───────────────────────────────────────────────────────────

    def _refresh_funding(self, symbol: str) -> None:
        """Fetch funding rate from OKX → Coinbase INTX → CoinGecko and upsert."""
        rate = _fetch_okx_funding(symbol)
        if rate is None:
            rate = _fetch_coinbase_intx_funding(symbol)
        if rate is None:
            rate = _fetch_coingecko_funding(symbol)
        if rate is None:
            logger.debug("MacroDataCache: could not fetch funding rate for %s", symbol)
            return

        now_iso = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO funding_rate_cache (symbol, rate, fetched_at)
                VALUES (?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    rate = excluded.rate,
                    fetched_at = excluded.fetched_at
                """,
                (symbol, rate, now_iso),
            )
            self._conn.commit()
        logger.debug("MacroDataCache: funding %s = %.6f", symbol, rate)

    def _read_funding(self, symbol: str) -> float | None:
        row = self._conn.execute(
            "SELECT rate FROM funding_rate_cache WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        return row[0] if row else None


# ── FRED fetch helper ──────────────────────────────────────────────────────────


def _fetch_fred_observations(
    series_id: str,
    api_key: str,
    n_obs: int = 120,
) -> list[dict[str, Any]]:
    """
    Fetch the most recent *n_obs* observations from FRED for *series_id*.

    Returns list of {"date": "YYYY-MM-DD", "value": float}, oldest first.
    Returns [] on any network or parse error.
    """
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": str(n_obs),
    }
    url = _FRED_BASE + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omega-victoria/1.0"})
        with urllib.request.urlopen(req, timeout=_FRED_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())

        result: list[dict[str, Any]] = []
        for obs in data.get("observations", []):
            raw = obs.get("value", ".")
            if raw == ".":
                continue
            try:
                result.append({"date": obs["date"], "value": float(raw)})
            except (ValueError, KeyError):
                continue

        result.reverse()  # oldest first
        return result

    except urllib.error.HTTPError as exc:
        if exc.code in (400, 401, 403):
            # Permanent client error — mark series as unavailable for this session
            # to avoid 30-req/day DEMO_KEY exhaustion and log-spam.
            _FRED_PERM_FAILED.add(series_id)
            logger.warning(
                "MacroDataCache: FRED %d for %s — marking unavailable for this session "
                "(set FRED_API_KEY for full access)",
                exc.code,
                series_id,
            )
        else:
            logger.warning("MacroDataCache: FRED fetch failed (series=%s): %s", series_id, exc)
        return []
    except Exception as exc:
        logger.warning("MacroDataCache: FRED fetch failed (series=%s): %s", series_id, exc)
        return []


# ── OKX funding fetch helper ───────────────────────────────────────────────────


def _fetch_okx_funding(symbol: str) -> float | None:
    """
    Fetch current funding rate from OKX public API.

    OKX endpoint: GET /api/v5/public/funding-rate?instId={instId}
    Returns the fundingRate as a float, or None on failure.
    """
    inst_id = _OKX_INST_MAP.get(symbol)
    if not inst_id:
        logger.debug("_fetch_okx_funding: no OKX mapping for %s", symbol)
        return None

    url = _OKX_FUNDING_URL + "?" + urllib.parse.urlencode({"instId": inst_id})
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "omega-victoria/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            data = json.loads(resp.read().decode())

        # Response: {"code": "0", "data": [{"fundingRate": "0.0001", ...}]}
        if data.get("code") != "0":
            logger.debug("_fetch_okx_funding: OKX error code %s for %s", data.get("code"), symbol)
            return None

        items = data.get("data", [])
        if not items:
            return None

        return float(items[0]["fundingRate"])

    except Exception as exc:
        logger.debug("_fetch_okx_funding: failed for %s: %s", symbol, exc)
        return None


# ── Coinbase INTX funding fallback ────────────────────────────────────────────


def _fetch_coinbase_intx_funding(symbol: str) -> float | None:
    """
    Fetch perpetual funding rate from Coinbase INTX via Advanced Trade public API.

    Endpoint: GET /api/v3/brokerage/market/products/{product_id}
    The funding rate lives at future_product_details.perpetual_details.funding_rate.
    Public endpoint — no auth required.
    """
    product_id = _COINBASE_INTX_MAP.get(symbol)
    if not product_id:
        logger.debug("_fetch_coinbase_intx_funding: no INTX mapping for %s", symbol)
        return None

    url = f"{_COINBASE_AT_API}/{product_id}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "omega-victoria/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            data = json.loads(resp.read().decode())

        future_details = data.get("future_product_details", {})
        perp_details = future_details.get("perpetual_details", {})
        rate_str = perp_details.get("funding_rate")
        if rate_str is not None:
            rate = float(rate_str)
            logger.debug("_fetch_coinbase_intx_funding: %s = %.6f", symbol, rate)
            return rate
        return None

    except Exception as exc:
        logger.debug("_fetch_coinbase_intx_funding: failed for %s: %s", symbol, exc)
        return None


# ── CoinGecko funding fallback ─────────────────────────────────────────────────

_CG_BASE_MAP = {
    "BTCUSDT": "BTC",
    "ETHUSDT": "ETH",
    "SOLUSDT": "SOL",
    "LINKUSDT": "LINK",
    "AVAXUSDT": "AVAX",
}


def _fetch_coingecko_funding(symbol: str) -> float | None:
    """
    Fetch funding rate from CoinGecko derivatives endpoint (fallback).

    Returns the median funding rate across matching entries, or None.
    """
    base = _CG_BASE_MAP.get(symbol)
    if not base:
        return None

    url = "https://api.coingecko.com/api/v3/derivatives"
    try:
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "omega-victoria/1.0"},
        )
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            data: list[dict] = json.loads(resp.read().decode())

        candidates: list[float] = []
        for entry in data:
            entry_sym: str = str(entry.get("symbol", "")).upper()
            fr = entry.get("funding_rate")
            if fr is None:
                continue
            try:
                fr_f = float(fr)
            except (TypeError, ValueError):
                continue
            if entry_sym.startswith(base) or f"/{base}" in entry_sym:
                candidates.append(fr_f)

        if not candidates:
            return None
        candidates.sort()
        return candidates[len(candidates) // 2]

    except Exception as exc:
        logger.debug("_fetch_coingecko_funding: failed for %s: %s", symbol, exc)
        return None


# ── Module-level singleton ─────────────────────────────────────────────────────

_default_cache: MacroDataCache | None = None
_singleton_lock = threading.Lock()


def get_cache() -> MacroDataCache:
    """Return the module-level singleton cache (created on first call)."""
    global _default_cache
    if _default_cache is None:
        with _singleton_lock:
            if _default_cache is None:
                _default_cache = MacroDataCache()
    return _default_cache
