"""Tests for CCXTDataSource and CoinGeckoSource with mocked HTTP."""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from omega.data.base import OHLCV, MarketData, OrderBookSnapshot
from omega.data.ccxt_source import SUPPORTED_EXCHANGES, CCXTDataSource
from omega.data.coingecko_source import SYMBOL_TO_ID, CoinGeckoSource

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


def _fake_ticker(last: float = 50_000.0) -> dict[str, Any]:
    return {
        "symbol": "BTC/USDT",
        "timestamp": int(time.time() * 1000),
        "bid": last - 10,
        "ask": last + 10,
        "last": last,
        "baseVolume": 1234.5,
        "quoteVolume": last * 1234.5,
    }


def _fake_ohlcv_row(ts_offset: int = 0) -> list:
    base_ts = int(time.time() * 1000) - ts_offset
    return [base_ts, 49_000, 51_000, 48_500, 50_500, 500.0]


def _fake_orderbook() -> dict[str, Any]:
    return {
        "timestamp": int(time.time() * 1000),
        "bids": [[50_000, 3.0], [49_990, 2.5], [49_980, 0.5]],  # total: 6.0
        "asks": [[50_010, 1.5], [50_020, 1.0], [50_030, 0.5]],  # total: 3.0
    }


def _make_mock_exchange(**overrides) -> MagicMock:
    ex = MagicMock()
    ex.fetch_ticker.return_value = _fake_ticker()
    ex.fetch_ohlcv.return_value = [_fake_ohlcv_row(i * 60_000) for i in range(3)]
    ex.fetch_order_book.return_value = _fake_orderbook()
    ex.fetch_funding_rate.return_value = {"fundingRate": 0.0001}
    ex.fetch_open_interest.return_value = {"openInterestAmount": 10_000.0}
    for k, v in overrides.items():
        setattr(ex, k, v)
    return ex


# ---------------------------------------------------------------------------
# CCXTDataSource tests
# ---------------------------------------------------------------------------


class TestCCXTDataSource:
    def _source(self, exchange_id: str = "binance") -> CCXTDataSource:
        src = CCXTDataSource(exchange_id=exchange_id)
        # Skip the real connect; inject mock exchange directly
        src._exchange = _make_mock_exchange()
        src._connected = True
        return src

    def test_invalid_exchange_raises(self):
        with pytest.raises(ValueError, match="Unsupported exchange"):
            CCXTDataSource("not_a_real_exchange")

    def test_supported_exchanges(self):
        for ex in SUPPORTED_EXCHANGES:
            src = CCXTDataSource(ex)
            assert src.name == f"ccxt:{ex}"

    def test_get_ticker_returns_market_data(self):
        src = self._source()
        md = src.get_ticker("BTC/USDT")
        assert isinstance(md, MarketData)
        assert md.symbol == "BTC/USDT"
        assert md.last_price == pytest.approx(50_000.0)
        assert md.bid == pytest.approx(49_990.0)
        assert md.ask == pytest.approx(50_010.0)
        assert md.volume_24h == pytest.approx(1234.5)

    def test_get_snapshot_delegates_to_get_ticker(self):
        src = self._source()
        md = src.get_snapshot("BTC/USDT")
        assert isinstance(md, MarketData)
        src._exchange.fetch_ticker.assert_called_once_with("BTC/USDT")

    def test_get_ticker_returns_none_on_error(self):
        src = self._source()
        src._exchange.fetch_ticker.side_effect = RuntimeError("network error")
        result = src.get_ticker("BTC/USDT")
        assert result is None
        assert src._error_count == 1

    def test_get_ohlcv_returns_list_of_ohlcv(self):
        src = self._source()
        candles = src.get_ohlcv("BTC/USDT", timeframe="1h", limit=3)
        assert len(candles) == 3
        for c in candles:
            assert isinstance(c, OHLCV)
            assert c.symbol == "BTC/USDT"
            assert c.timeframe == "1h"
            assert c.open == pytest.approx(49_000)
            assert c.high == pytest.approx(51_000)
            assert c.low == pytest.approx(48_500)
            assert c.close == pytest.approx(50_500)
            assert c.volume == pytest.approx(500.0)

    def test_get_ohlcv_returns_empty_on_error(self):
        src = self._source()
        src._exchange.fetch_ohlcv.side_effect = Exception("timeout")
        result = src.get_ohlcv("BTC/USDT")
        assert result == []

    def test_get_orderbook_returns_snapshot(self):
        src = self._source()
        ob = src.get_orderbook("BTC/USDT", depth=20)
        assert isinstance(ob, OrderBookSnapshot)
        assert len(ob.bids) == 3
        assert len(ob.asks) == 3
        assert ob.bids[0].price == pytest.approx(50_000)
        assert ob.asks[0].price == pytest.approx(50_010)
        assert ob.mid_price == pytest.approx(50_005)
        assert ob.spread == pytest.approx(10)
        # More bids than asks → positive imbalance
        assert ob.imbalance > 0

    def test_get_orderbook_returns_none_on_error(self):
        src = self._source()
        src._exchange.fetch_order_book.side_effect = Exception("connection refused")
        result = src.get_orderbook("BTC/USDT")
        assert result is None

    def test_get_funding_rate(self):
        src = self._source()
        rate = src.get_funding_rate("BTC/USDT")
        assert rate == pytest.approx(0.0001)

    def test_get_funding_rate_zero_on_error(self):
        src = self._source()
        src._exchange.fetch_funding_rate.side_effect = Exception("not a perp")
        rate = src.get_funding_rate("BTC/USDT")
        assert rate == 0.0

    def test_get_open_interest(self):
        src = self._source()
        oi = src.get_open_interest("BTC/USDT")
        assert oi == pytest.approx(10_000.0)

    def test_get_full_snapshot_includes_funding_and_oi(self):
        src = self._source()
        md = src.get_full_snapshot("BTC/USDT")
        assert md is not None
        assert md.funding_rate == pytest.approx(0.0001)
        assert md.open_interest == pytest.approx(10_000.0)

    def test_mark_fetch_resets_error_count(self):
        src = self._source()
        src._error_count = 5
        src.get_ticker("BTC/USDT")
        assert src._error_count == 0


# ---------------------------------------------------------------------------
# OrderBookSnapshot computed properties
# ---------------------------------------------------------------------------


class TestOrderBookSnapshot:
    def _make_ob(self) -> OrderBookSnapshot:
        from omega.data.base import OrderBookLevel

        return OrderBookSnapshot(
            symbol="BTC/USDT",
            timestamp=time.time(),
            bids=[OrderBookLevel(50_000, 2.0), OrderBookLevel(49_990, 1.0)],
            asks=[OrderBookLevel(50_010, 1.0), OrderBookLevel(50_020, 0.5)],
        )

    def test_mid_price(self):
        ob = self._make_ob()
        assert ob.mid_price == pytest.approx(50_005)

    def test_spread(self):
        ob = self._make_ob()
        assert ob.spread == pytest.approx(10)

    def test_imbalance_with_more_bids(self):
        ob = self._make_ob()
        # bid vol = 3.0, ask vol = 1.5 → imbalance = (3 - 1.5)/4.5 = 0.333
        assert ob.imbalance == pytest.approx((3.0 - 1.5) / 4.5)

    def test_empty_orderbook(self):
        from omega.data.base import OrderBookSnapshot

        ob = OrderBookSnapshot(symbol="X", timestamp=0, bids=[], asks=[])
        assert ob.mid_price == 0.0
        assert ob.spread == 0.0
        assert ob.imbalance == 0.0


# ---------------------------------------------------------------------------
# OHLCV computed properties
# ---------------------------------------------------------------------------


class TestOHLCV:
    def _candle(self, o=100, h=110, low=90, c=105) -> OHLCV:
        return OHLCV(
            timestamp=time.time(),
            symbol="BTC/USDT",
            timeframe="1h",
            open=o,
            high=h,
            low=low,
            close=c,
            volume=1000,
        )

    def test_bullish(self):
        assert self._candle(o=100, c=105).is_bullish is True

    def test_bearish(self):
        assert self._candle(o=105, c=100).is_bullish is False

    def test_body(self):
        assert self._candle(o=100, c=105).body == pytest.approx(5)

    def test_range(self):
        assert self._candle(h=110, low=90).range == pytest.approx(20)

    def test_upper_wick(self):
        # close=105 is max(open=100, close=105), high=110 → upper wick = 5
        c = self._candle(o=100, h=110, low=90, c=105)
        assert c.upper_wick == pytest.approx(5)

    def test_lower_wick(self):
        # min(open=100, close=105) = 100, low=90 → lower wick = 10
        c = self._candle(o=100, h=110, low=90, c=105)
        assert c.lower_wick == pytest.approx(10)


# ---------------------------------------------------------------------------
# CoinGeckoSource tests (mocked HTTP)
# ---------------------------------------------------------------------------

_FAKE_MARKETS_RESPONSE = [
    {
        "id": "bitcoin",
        "symbol": "btc",
        "current_price": 50000,
        "total_volume": 30_000_000_000,
        "market_cap": 950_000_000_000,
    },
    {
        "id": "ethereum",
        "symbol": "eth",
        "current_price": 3000,
        "total_volume": 15_000_000_000,
        "market_cap": 360_000_000_000,
    },
]

_FAKE_FEAR_GREED_RESPONSE = {"data": [{"value": "72", "value_classification": "Greed"}]}


class _FakeHTTPResponse:
    def __init__(self, data: Any) -> None:
        self._data = json.dumps(data).encode()

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class TestCoinGeckoSource:
    def _source(self) -> CoinGeckoSource:
        src = CoinGeckoSource()
        src._connected = True
        src._last_request = 0.0  # skip rate limit waits
        return src

    @patch("omega.data.coingecko_source.urlopen")
    def test_get_market_data_returns_list(self, mock_urlopen):
        mock_urlopen.return_value = _FakeHTTPResponse(_FAKE_MARKETS_RESPONSE)
        src = self._source()
        results = src.get_market_data(["bitcoin", "ethereum"])
        assert len(results) == 2
        btc = next(r for r in results if r.symbol == "BTC")
        assert btc.last_price == pytest.approx(50_000)
        assert btc.volume_24h == pytest.approx(30_000_000_000)
        assert btc.market_cap == pytest.approx(950_000_000_000)

    @patch("omega.data.coingecko_source.urlopen")
    def test_get_market_data_empty_ids(self, mock_urlopen):
        src = self._source()
        result = src.get_market_data([])
        assert result == []
        mock_urlopen.assert_not_called()

    @patch("omega.data.coingecko_source.urlopen")
    def test_get_market_data_returns_empty_on_error(self, mock_urlopen):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("timeout")
        src = self._source()
        result = src.get_market_data(["bitcoin"])
        assert result == []

    @patch("omega.data.coingecko_source.urlopen")
    def test_get_fear_greed_index(self, mock_urlopen):
        mock_urlopen.return_value = _FakeHTTPResponse(_FAKE_FEAR_GREED_RESPONSE)
        src = self._source()
        val = src.get_fear_greed_index()
        assert val == pytest.approx(72.0)

    @patch("omega.data.coingecko_source.urlopen")
    def test_get_fear_greed_index_defaults_to_neutral_on_error(self, mock_urlopen):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("connection refused")
        src = self._source()
        val = src.get_fear_greed_index()
        assert val == pytest.approx(50.0)

    @patch("omega.data.coingecko_source.urlopen")
    def test_get_snapshot_resolves_symbol(self, mock_urlopen):
        mock_urlopen.return_value = _FakeHTTPResponse([_FAKE_MARKETS_RESPONSE[0]])
        src = self._source()
        result = src.get_snapshot("BTC")
        assert result is not None
        assert result.last_price == pytest.approx(50_000)

    def test_symbol_to_id_map_coverage(self):
        common_symbols = ["BTC", "ETH", "SOL", "BNB", "XRP"]
        for sym in common_symbols:
            assert sym in SYMBOL_TO_ID, f"{sym} missing from SYMBOL_TO_ID"

    @patch("omega.data.coingecko_source.urlopen")
    def test_bid_ask_approximated_from_last(self, mock_urlopen):
        mock_urlopen.return_value = _FakeHTTPResponse([_FAKE_MARKETS_RESPONSE[0]])
        src = self._source()
        results = src.get_market_data(["bitcoin"])
        assert len(results) == 1
        md = results[0]
        # bid < last < ask
        assert md.bid < md.last_price
        assert md.ask > md.last_price
