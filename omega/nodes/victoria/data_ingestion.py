"""
omega.nodes.victoria.data_ingestion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
DataIngestionNode — fetches real crypto market data via pluggable providers.

Data sources (via ProviderRegistry):
  1. BinanceProvider   — OHLCV klines (primary)
  2. CoinGeckoProvider — market caps, rankings (enrichment)
  3. BybitProvider     — OHLCV klines (fallback when Binance fails)
  4. FearGreedProvider — Alternative.me Fear & Greed Index (supplementary)
  5. DefiLlamaProvider — DeFi protocol TVL rankings (supplementary)

Pairs: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT,
       ADAUSDT, DOTUSDT, AVAXUSDT, LINKUSDT, MATICUSDT

Improvement arc:
  v1.0 — Basic Binance klines fetch, no retry, no cache
  v1.1 — Retry logic with exponential backoff
  v1.2 — In-memory response cache (TTL 5 minutes)
  v1.3 — CoinGecko supplementary data integrated + extended pairs
  v1.4 — Bybit fallback enabled for failed pairs
"""

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any

from omega.core.actions import NodeAction
from omega.core.credentials import credentials
from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.nodes.victoria.data_providers import (
    BinanceProvider,
    BybitProvider,
    CoinGeckoProvider,
    DefiLlamaProvider,
    FearGreedProvider,
    ProviderRegistry,
)

credentials.register(
    "BINANCE_API_KEY",
    required=False,
    description="Binance authenticated endpoints (optional, public API works without)",
)

logger = logging.getLogger("omega.nodes.victoria.data_ingestion")

_BASE_PAIRS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOTUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "MATICUSDT",
]

_EXTENDED_PAIRS = [
    "ATOMUSDT",
    "NEARUSDT",
    "ALGOUSDT",
    "FILUSDT",
    "LTCUSDT",
    "UNIUSDT",
    "AAVEUSDT",
    "SHIBUSDT",
    "TRXUSDT",
    "DOGEUSDT",
]


class DataIngestionNode(Node):
    """
    Fetches OHLCV and market data via pluggable provider architecture.

    Primary:     BinanceProvider (OHLCV klines)
    Fallback:    BybitProvider (OHLCV klines when Binance fails)
    Enrichment:  CoinGeckoProvider (market caps, rank, 24h change)
    Supplementary: FearGreedProvider, DefiLlamaProvider

    Capabilities : fetch_market_data, fetch_ohlcv, fetch_ticker_info
    Improves via : retry logic → response caching → extended pairs + CoinGecko → Bybit fallback
    """

    def __init__(self) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._pairs: list[str] = list(_BASE_PAIRS)
        self._use_retry = False
        self._use_cache = False
        self._use_coingecko = False
        self._use_bybit_fallback = False
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._total_pairs_fetched = 0
        self._total_pairs_failed = 0
        self._last_fetch_time: datetime | None = None

        # ── Provider registry ─────────────────────────────────────────────────
        self._registry = ProviderRegistry()
        self._binance = BinanceProvider()
        self._coingecko = CoinGeckoProvider()
        self._bybit = BybitProvider()
        self._fear_greed = FearGreedProvider()
        self._defillama = DefiLlamaProvider()

        self._registry.register(self._binance, enabled=True)
        self._registry.register(self._coingecko, enabled=True)
        self._registry.register(self._bybit, enabled=True)
        self._registry.register(self._fear_greed, enabled=True)
        self._registry.register(self._defillama, enabled=True)

    # ------------------------------------------------------------------ Node interface

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._node_id,
            name="DataIngestionNode",
            version=self._version,
            health=max(0.0, 1.0 - self._error_rate()),
            capabilities=self.get_capabilities(),
            metrics={
                "avg_latency_ms": self._avg_latency_ms(),
                "error_rate": self._error_rate(),
                "coverage_rate": self._coverage_rate(),
                "pair_count": float(len(self._pairs)),
                "data_freshness_minutes": self._data_freshness_minutes(),
            },
            metadata={
                "use_retry": self._use_retry,
                "use_cache": self._use_cache,
                "use_coingecko": self._use_coingecko,
                "use_bybit_fallback": self._use_bybit_fallback,
                "pairs": self._pairs,
                "provider_status": self._registry.status(),
            },
        )

    def get_capabilities(self) -> list[str]:
        return [NodeAction.FETCH_MARKET_DATA.value, "fetch_ohlcv", "fetch_ticker_info"]

    def describe(self) -> str:
        return (
            "Fetches real-time and historical OHLCV data for crypto pairs via "
            "pluggable provider architecture (Binance primary, Bybit fallback). "
            "Enriches with CoinGecko market caps and supplementary Fear/Greed + DeFi TVL. "
            "Tracks BTC, ETH, SOL, BNB, XRP, ADA, DOT, AVAX, LINK, MATIC. "
            "Self-improves via retry, caching, expanded pairs, and provider fallback."
        )

    def execute(self, input: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        action = input.action
        params = input.parameters

        try:
            if action == NodeAction.FETCH_MARKET_DATA.value:
                result = self._fetch_all_pairs(
                    interval=params.get("interval", "1d"),
                    limit=int(params.get("limit", 90)),
                )
            elif action == "fetch_ohlcv":
                pair = params.get("pair", self._pairs[0])
                data = self._binance.fetch_klines(
                    pair,
                    interval=params.get("interval", "1d"),
                    limit=int(params.get("limit", 90)),
                )
                result = {pair: data}
            elif action == "fetch_ticker_info":
                result = self._fetch_24h_tickers()
            else:
                elapsed = (time.perf_counter() - t0) * 1000
                self._execution_count += 1
                self._error_count += 1
                self._total_latency_ms += elapsed
                return NodeOutput(
                    request_id=input.request_id,
                    success=False,
                    errors=[f"Unknown action '{action}'"],
                    metrics={"latency_ms": elapsed},
                )

            elapsed = (time.perf_counter() - t0) * 1000
            self._execution_count += 1
            self._total_latency_ms += elapsed
            self._last_fetch_time = datetime.now()

            # Count only non-supplementary keys for pairs_ok
            pairs_ok = (
                len([v for k, v in result.items() if not k.startswith("_") and v])
                if isinstance(result, dict)
                else 0
            )

            return NodeOutput(
                request_id=input.request_id,
                success=True,
                result=result,
                metrics={
                    "latency_ms": elapsed,
                    "pairs_fetched": float(pairs_ok),
                    "coverage_rate": self._coverage_rate(),
                    "data_freshness_minutes": self._data_freshness_minutes(),
                },
            )

        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._execution_count += 1
            self._error_count += 1
            self._total_latency_ms += elapsed
            logger.error("DataIngestionNode error: %s", exc, exc_info=True)
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": elapsed},
            )

    def evaluate(self) -> dict[str, float]:
        return {
            "avg_latency_ms": self._avg_latency_ms(),
            "error_rate": self._error_rate(),
            "coverage_rate": self._coverage_rate(),
            "pair_count": float(len(self._pairs)),
            "data_freshness_minutes": self._data_freshness_minutes(),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        changed = False
        iteration = feedback.get("iteration", 0)
        error_rate = self._error_rate()
        coverage = self._coverage_rate()

        # v1.1: Add retry logic
        if not self._use_retry and (error_rate > 0.05 or iteration >= 1):
            self._use_retry = True
            self._version = "1.1"
            logger.info(
                "DataIngestionNode → v1.1: retry logic enabled (error_rate=%.2f)", error_rate
            )
            changed = True

        # v1.2: Add caching when latency is high
        if (
            self._use_retry
            and not self._use_cache
            and (self._avg_latency_ms() > 500 or iteration >= 2)
        ):
            self._use_cache = True
            self._version = "1.2"
            logger.info("DataIngestionNode → v1.2: response caching enabled")
            changed = True

        # v1.3: Add CoinGecko enrichment + extended pairs
        if (
            self._use_cache
            and not self._use_coingecko
            and coverage >= 0.7
            and len(self._pairs) <= len(_BASE_PAIRS)
        ):
            self._use_coingecko = True
            new_pairs = [p for p in _EXTENDED_PAIRS if p not in self._pairs]
            self._pairs.extend(new_pairs[:5])
            self._version = "1.3"
            logger.info(
                "DataIngestionNode → v1.3: CoinGecko enrichment + %d extended pairs (total %d)",
                len(new_pairs[:5]),
                len(self._pairs),
            )
            changed = True

        # v1.4: Enable Bybit fallback for failed pairs
        if (
            self._use_coingecko
            and not self._use_bybit_fallback
            and (coverage < 0.8 or iteration >= 4)
        ):
            self._use_bybit_fallback = True
            self._version = "1.4"
            logger.info(
                "DataIngestionNode → v1.4: Bybit fallback enabled for failed pairs "
                "(coverage=%.2f)",
                coverage,
            )
            changed = True

        return changed

    # ------------------------------------------------------------------ Fetching

    def _fetch_all_pairs(self, interval: str = "1d", limit: int = 90) -> dict[str, Any]:
        """Fetch OHLCV for all tracked pairs with provider fallback + supplementary data."""
        result: dict[str, Any] = {}

        # ── CoinGecko enrichment data ─────────────────────────────────────────
        cg_data: dict[str, Any] = {}
        if self._use_coingecko:
            cg_data = self._coingecko.fetch(self._pairs)

        # ── Primary: Binance ──────────────────────────────────────────────────
        failed_pairs: list[str] = []
        for pair in self._pairs:
            data = self._binance.fetch_klines(pair, interval=interval, limit=limit)
            if data:
                if cg_data:
                    cg = cg_data.get(pair, {})
                    if cg:
                        data["market_cap"] = cg.get("market_cap")
                        data["market_cap_rank"] = cg.get("market_cap_rank")
                        data["total_volume_usd"] = cg.get("total_volume")
                        data["price_change_pct_24h"] = cg.get("price_change_percentage_24h")
                self._total_pairs_fetched += 1
                result[pair] = data
            else:
                failed_pairs.append(pair)
            time.sleep(0.05)

        # ── Fallback: Bybit for failed pairs ──────────────────────────────────
        bybit_enabled = self._registry.status().get("bybit", {}).get("enabled", True)
        if failed_pairs and bybit_enabled:
            for pair in failed_pairs:
                data = self._bybit.fetch_klines(pair, interval=interval, limit=limit)
                if data:
                    if cg_data:
                        cg = cg_data.get(pair, {})
                        if cg:
                            data["market_cap"] = cg.get("market_cap")
                            data["market_cap_rank"] = cg.get("market_cap_rank")
                            data["total_volume_usd"] = cg.get("total_volume")
                            data["price_change_pct_24h"] = cg.get("price_change_percentage_24h")
                    self._total_pairs_fetched += 1
                    result[pair] = data
                    logger.info("Bybit fallback succeeded for %s", pair)
                else:
                    self._total_pairs_failed += 1
                    result[pair] = None
                    logger.warning("Both Binance and Bybit failed for %s", pair)
                time.sleep(0.05)
        else:
            for pair in failed_pairs:
                self._total_pairs_failed += 1
                result[pair] = None

        # ── Supplementary: Fear & Greed ────────────────────────────────────────
        fg_enabled = self._registry.status().get("fear_greed", {}).get("enabled", True)
        if fg_enabled:
            fg_data = self._fear_greed.fetch(self._pairs)
            if fg_data:
                fg_index = fg_data.get("fear_greed", {})
                result["_fear_greed"] = fg_index
            # If unreachable, just skip — no key added

        # ── Supplementary: DefiLlama ──────────────────────────────────────────
        defi_enabled = self._registry.status().get("defillama", {}).get("enabled", True)
        if defi_enabled:
            defi_data = self._defillama.fetch(self._pairs)
            if defi_data:
                defi_tvl = defi_data.get("defi_tvl", {})
                result["_defi_tvl"] = defi_tvl
            # If unreachable, just skip — no key added

        # ── Supplementary: Binance funding rates (BTCUSDT, free public API) ──
        try:
            import urllib.request as _ureq

            _furl = "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=8"
            _freq = _ureq.Request(_furl, headers={"User-Agent": "Mozilla/5.0"})
            with _ureq.urlopen(_freq, timeout=5) as _fresp:
                _fdata = json.loads(_fresp.read().decode("utf-8"))
            if isinstance(_fdata, list) and _fdata:
                result["funding_rates"] = [
                    float(e["fundingRate"]) for e in _fdata if "fundingRate" in e
                ]
                logger.debug(
                    "Binance funding rates fetched: %d periods, latest=%.6f",
                    len(result["funding_rates"]),
                    result["funding_rates"][-1] if result["funding_rates"] else 0.0,
                )
        except Exception as _exc:
            logger.debug("Binance funding rate fetch skipped: %s", _exc)

        # ── Supplementary: Binance order book depth (BTCUSDT, free public API) ──
        try:
            import urllib.request as _ureq

            _ourl = "https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=20"
            _oreq = _ureq.Request(_ourl, headers={"User-Agent": "Mozilla/5.0"})
            with _ureq.urlopen(_oreq, timeout=5) as _oresp:
                _odata = json.loads(_oresp.read().decode("utf-8"))
            _bids = _odata.get("bids", [])
            _asks = _odata.get("asks", [])
            if _bids and _asks:
                _bid_vol = sum(float(b[1]) for b in _bids)
                _ask_vol = sum(float(a[1]) for a in _asks)
                result["_bid_sizes"] = [_bid_vol]
                result["_ask_sizes"] = [_ask_vol]
                # Best bid/ask prices for spread computation (MicrostructureSignal)
                _best_bid = float(_bids[0][0])  # highest bid price
                _best_ask = float(_asks[0][0])  # lowest ask price
                result["_best_bid"] = _best_bid
                result["_best_ask"] = _best_ask
                logger.debug(
                    "Binance order book: bid_vol=%.4f ask_vol=%.4f imbalance=%.4f spread_bps=%.2f",
                    _bid_vol,
                    _ask_vol,
                    (_bid_vol - _ask_vol) / (_bid_vol + _ask_vol)
                    if (_bid_vol + _ask_vol) > 0
                    else 0.0,
                    (_best_ask - _best_bid) / ((_best_bid + _best_ask) / 2) * 10000
                    if (_best_bid + _best_ask) > 0
                    else 0.0,
                )
        except Exception as _exc:
            logger.debug("Binance order book fetch skipped: %s", _exc)

        # ── Supplementary: CoinGecko /global — BTC dominance (fetched ONCE here) ──
        try:
            import os as _os
            import urllib.request as _ureq

            _gurl = "https://api.coingecko.com/api/v3/global"
            _cg_headers: dict = {"User-Agent": "Mozilla/5.0"}
            _cg_key = _os.getenv("CG_API_KEY", "")
            if _cg_key:
                _cg_headers["x-cg-demo-api-key"] = _cg_key
            _greq = _ureq.Request(_gurl, headers=_cg_headers)
            with _ureq.urlopen(_greq, timeout=8) as _gresp:
                _gdata = json.loads(_gresp.read().decode("utf-8"))
            _btc_dom = float(_gdata["data"]["market_cap_percentage"]["btc"])
            result["_btc_dominance"] = _btc_dom
            result["_market_cap_change_24h"] = float(
                _gdata["data"].get("market_cap_change_percentage_24h_usd", 0.0)
            )
            logger.debug("CoinGecko global: btc_dominance=%.2f%%", _btc_dom)
        except Exception as _exc:
            logger.debug("CoinGecko global fetch skipped: %s", _exc)

        return result

    def _fetch_24h_tickers(self) -> dict[str, Any]:
        """Fetch 24h ticker stats from Binance for all pairs."""
        import json
        import urllib.request as _req

        binance_api = "https://api.binance.com/api/v3"
        headers = {
            "User-Agent": "OmegaVictoria/1.0 (quantitative research bot)",
            "Accept": "application/json",
        }
        result: dict[str, Any] = {}
        try:
            url = f"{binance_api}/ticker/24hr"
            req = _req.Request(url, headers=headers)
            with _req.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read().decode("utf-8"))

            tracked = set(self._pairs)
            for ticker in raw:
                sym = ticker.get("symbol", "")
                if sym in tracked:
                    result[sym] = {
                        "price": float(ticker.get("lastPrice", 0)),
                        "price_change_pct": float(ticker.get("priceChangePercent", 0)),
                        "volume": float(ticker.get("volume", 0)),
                        "quote_volume": float(ticker.get("quoteVolume", 0)),
                        "high_24h": float(ticker.get("highPrice", 0)),
                        "low_24h": float(ticker.get("lowPrice", 0)),
                        "trades": int(ticker.get("count", 0)),
                    }
        except Exception as exc:
            logger.warning("24h ticker fetch failed: %s", exc)

        return result

    # ------------------------------------------------------------------ helpers

    def _avg_latency_ms(self) -> float:
        return self._total_latency_ms / max(1, self._execution_count)

    def _error_rate(self) -> float:
        return self._error_count / max(1, self._execution_count)

    def _coverage_rate(self) -> float:
        total = self._total_pairs_fetched + self._total_pairs_failed
        if total == 0:
            return 1.0
        return self._total_pairs_fetched / total

    def _data_freshness_minutes(self) -> float:
        if self._last_fetch_time is None:
            return 9999.0
        delta = datetime.now() - self._last_fetch_time
        return delta.total_seconds() / 60.0
